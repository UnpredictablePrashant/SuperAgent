"""
dev_pipeline_tasks.py — Multi-agent dev project pipeline orchestrator.

Provides `dev_pipeline_agent(state)` which orchestrates the complete
end-to-end project generation flow in a single agent call:

  blueprint → [approval gate] → scaffold → db → auth → backend →
  frontend → deps → tests → security_scan → devops → verify →
  [auto-fix + retest loop ×N] → post_setup → zip export

Activated when state["dev_pipeline_mode"] is True.
Intended for `kendr run --dev "…"` or `kendr generate "…"`.

Blueprint approval gate:
- Calls project_blueprint_agent which sets the "project_blueprint" approval scope
  (using the same state pattern recognized by the runtime's _apply_pending_user_response).
- auto_approve=True → project_blueprint_agent auto-approves and continues.
- auto_approve=False → project_blueprint_agent sets blueprint_waiting_for_approval=True,
  approval_pending_scope="project_blueprint", dev_pipeline_status="waiting_for_approval",
  and dev_pipeline_agent returns. The orchestrator sees blueprint_waiting_for_approval and
  routes to __finish__ to surface the approval prompt to the user. On the next run, the
  runtime sets blueprint_status="approved" via _apply_pending_user_response and
  re-dispatches dev_pipeline_agent which resumes past the blueprint stage.

Auto-fix retry loop:
- Triggers when verifier_status != "pass" OR test_agent_status indicates failure.
- Extracts failing file paths from verifier_issues and verifier_check_results.
- Calls coding_agent for each file with coding_write_path + coding_context_files set
  so actual file content is patched (not just text output).
- Re-runs test_agent and project_verifier_agent after each fix round.
- On persistent failure: dev_pipeline_status="partial" with diagnostic summary.

Zip export:
- Written to state["run_output_dir"] (falls back to get_output_dir()).
- dev_pipeline_zip_path persisted in state and written to dev_pipeline_zip_path.txt.
"""

from __future__ import annotations

import re
import sys
import time
import zipfile
from pathlib import Path
from typing import Callable, List

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.utils import get_output_dir, log_task_update, write_text_file

_AGENT_NAME = "dev_pipeline_agent"

AGENT_METADATA = {
    "dev_pipeline_agent": {
        "name": _AGENT_NAME,
        "display_name": "Dev Pipeline Agent",
        "description": (
            "End-to-end multi-agent software project generation pipeline. "
            "Orchestrates blueprint → approval → scaffold → build → "
            "test → verify (with auto-fix retry) → zip export."
        ),
        "skills": [
            "project generation",
            "full-stack development",
            "pipeline orchestration",
            "blueprint design",
            "scaffolding",
            "testing",
            "devops",
            "zip export",
        ],
        "input_keys": [
            "user_query",
            "project_build_mode",
            "dev_pipeline_mode",
            "project_name",
            "project_root",
            "project_stack",
            "auto_approve",
            "skip_test_agent",
            "skip_devops_agent",
            "skip_reviews",
            "dev_pipeline_max_fix_rounds",
        ],
        "output_keys": [
            "blueprint_json",
            "blueprint_status",
            "dev_pipeline_zip_path",
            "dev_pipeline_status",
            "dev_pipeline_stages_completed",
            "dev_pipeline_error",
            "verifier_status",
            "verifier_summary",
        ],
    }
}


def _print_banner(message: str, width: int = 72) -> None:
    bar = "─" * width
    sys.stdout.write(f"\n{bar}\n  {message}\n{bar}\n")
    sys.stdout.flush()


def _run_stage(
    name: str,
    agent_fn: Callable[[dict], dict],
    state: dict,
    stages_completed: list,
    *,
    fatal: bool = False,
) -> dict:
    """Run a single pipeline stage, optionally re-raising on error."""
    _print_banner(f"[{name}] starting…")
    t0 = time.monotonic()
    try:
        state = agent_fn(state)
        elapsed = time.monotonic() - t0
        stages_completed.append(name)
        log_task_update("DevPipeline", f"Stage '{name}' completed in {elapsed:.1f}s.")
        _print_banner(f"[{name}] done ({elapsed:.1f}s)")
    except Exception as exc:
        elapsed = time.monotonic() - t0
        log_task_update("DevPipeline", f"Stage '{name}' failed after {elapsed:.1f}s: {exc}")
        _print_banner(f"[{name}] FAILED — {exc}")
        if fatal:
            raise
    return state


def _zip_project(project_root: Path, output_dir: Path) -> str:
    """
    Create a zip archive of the project in output_dir (the run output directory).
    Returns the zip file path as a string.
    """
    project_name = project_root.name or "project"
    zip_path = output_dir / f"{project_name}.zip"
    output_dir.mkdir(parents=True, exist_ok=True)
    skip_dirs = {
        ".git", "node_modules", "__pycache__", ".venv", "venv",
        ".mypy_cache", "dist", "build",
    }
    with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED, allowZip64=True) as zf:
        for item in sorted(project_root.rglob("*")):
            if item.is_file():
                arcname = item.relative_to(project_root.parent)
                if any(part in skip_dirs for part in arcname.parts):
                    continue
                try:
                    zf.write(str(item), str(arcname))
                except Exception:
                    pass
    return str(zip_path)


def _verifier_passed(state: dict) -> bool:
    """Return True when verifier_status indicates success or no checks ran."""
    status = str(state.get("verifier_status", "") or "").strip().lower()
    return not status or status in ("pass", "passed", "ok", "success")


def _tests_passed(state: dict) -> bool:
    """Return True when test_agent_status indicates success or tests were skipped."""
    status = str(state.get("test_agent_status", "") or "").strip().lower()
    return not status or status in ("pass", "passed", "ok", "success")


def _extract_failing_files(state: dict, project_root: str) -> List[str]:
    """
    Extract absolute file paths that need fixing from verifier_issues,
    verifier_check_results, and test_agent_results (list[str]).
    Returns a deduplicated list of absolute paths that exist on disk.
    """
    paths = []
    root = Path(project_root).resolve() if project_root else None

    def _resolve(p: str) -> str | None:
        if not p:
            return None
        candidate = Path(p)
        if candidate.is_absolute() and candidate.is_file():
            return str(candidate)
        if root:
            full = root / p
            if full.is_file():
                return str(full)
        return None

    # From structured verifier issues: each issue dict may have "file" key
    for issue in (state.get("verifier_issues") or []):
        if isinstance(issue, dict):
            resolved = _resolve(str(issue.get("file", "") or ""))
            if resolved:
                paths.append(resolved)

    # From verifier_check_results: each failed check dict may have "file" key
    for check in (state.get("verifier_check_results") or []):
        if isinstance(check, dict) and not check.get("success", True):
            resolved = _resolve(str(check.get("file", "") or ""))
            if resolved:
                paths.append(resolved)
            stderr = str(check.get("stderr", "") or "")
            for m in re.finditer(r'(?:^|\s)([\w./\\-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|rb|cs))\b', stderr):
                resolved = _resolve(m.group(1).strip())
                if resolved:
                    paths.append(resolved)

    # From test_agent_results (list[str]): parse file paths from output lines
    for line in (state.get("test_agent_results") or []):
        for m in re.finditer(r'(?:^|\s)([\w./\\-]+\.(?:py|ts|tsx|js|jsx|go|rs|java|rb|cs))\b', str(line)):
            resolved = _resolve(m.group(1).strip())
            if resolved:
                paths.append(resolved)

    seen = set()
    result = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def _build_fix_context(state: dict, fix_round: int, target_file: str = "") -> str:
    """
    Build a rich fix-context string for coding_agent.
    Combines verifier failures AND test_agent failures (list[str]).
    """
    lines = [
        f"Auto-fix round {fix_round}: Fix failures in the generated project.",
        "",
        f"Project root: {state.get('project_root', '(unknown)')}",
    ]
    if target_file:
        lines.append(f"Target file to fix: {target_file}")
    lines.append("")

    # Verifier report
    verifier_summary = str(state.get("verifier_summary", "") or "").strip()
    if verifier_summary:
        lines.append("=== Verifier Report ===")
        lines.append(verifier_summary[:2000])
        lines.append("")

    failed_checks = [
        r for r in (state.get("verifier_check_results") or [])
        if isinstance(r, dict) and not r.get("success", True)
    ]
    if failed_checks:
        lines.append("Failed verification checks:")
        for check in failed_checks[:15]:
            lines.append(f"  [{check.get('label', '?')}]")
            stderr = str(check.get("stderr", "") or "").strip()
            if stderr:
                for err_line in stderr.splitlines()[:5]:
                    lines.append(f"    {err_line}")
        lines.append("")

    issues = [i for i in (state.get("verifier_issues") or []) if isinstance(i, dict)]
    if issues:
        lines.append("Specific issues to resolve:")
        for issue in issues[:15]:
            lines.append(
                f"  [{issue.get('severity', '?')}] {issue.get('check', '?')}: "
                f"{str(issue.get('message', ''))[:200]}"
            )
        lines.append("")

    # Test failures — test_agent_results is list[str]
    if not _tests_passed(state):
        lines.append("=== Test Failures ===")
        test_summary = str(state.get("test_agent_summary", "") or "").strip()
        if test_summary:
            lines.append(test_summary[:1000])
            lines.append("")
        test_results = state.get("test_agent_results") or []
        if test_results:
            lines.append("Test output:")
            for result_line in test_results[:30]:
                lines.append(f"  {str(result_line)[:300]}")
            lines.append("")

    lines.append("Fix all failures listed above and ensure all checks pass.")
    return "\n".join(lines)


def _run_fix_round(
    state: dict,
    fix_round: int,
    max_fix_rounds: int,
    skip_tests: bool,
    stages_completed: list,
    coding_agent: Callable[[dict], dict],
    test_agent: Callable[[dict], dict],
    project_verifier_agent: Callable[[dict], dict],
) -> dict:
    """
    Perform one auto-fix round: fix each failing file, then retest + re-verify.
    coding_agent is called per target file with coding_write_path set.
    Falls back to a single context-only fix call when no file paths can be extracted.
    """
    project_root = str(state.get("project_root", "") or "").strip()
    failing_files = _extract_failing_files(state, project_root)

    log_task_update(
        "DevPipeline",
        f"Auto-fix round {fix_round}/{max_fix_rounds} — "
        f"verifier={'pass' if _verifier_passed(state) else 'fail'}, "
        f"tests={'pass' if _tests_passed(state) else 'fail'}, "
        f"failing files: {len(failing_files)}.",
    )

    if failing_files:
        for file_path in failing_files:
            fix_task = _build_fix_context(state, fix_round, target_file=file_path)
            # Read current file content as context
            context_files = [file_path]
            # Add related files from the same directory if small enough
            try:
                parent = Path(file_path).parent
                for sibling in sorted(parent.iterdir()):
                    if (
                        sibling.is_file()
                        and sibling.suffix in {".py", ".ts", ".tsx", ".js", ".jsx", ".go", ".java"}
                        and str(sibling) != file_path
                        and len(context_files) < 5
                    ):
                        context_files.append(str(sibling))
            except Exception:
                pass

            state["coding_task"] = fix_task
            state["current_objective"] = fix_task
            state["coding_write_path"] = file_path
            state["coding_context_files"] = context_files
            state["coding_working_directory"] = project_root or "."
            stage_name = f"auto_fix_{fix_round}_{Path(file_path).name}"
            state = _run_stage(stage_name, coding_agent, state, stages_completed)
    else:
        # No specific file paths found — send a broad fix call without write path
        fix_task = _build_fix_context(state, fix_round)
        state["coding_task"] = fix_task
        state["current_objective"] = fix_task
        state["coding_write_path"] = ""
        state["coding_context_files"] = []
        state["coding_working_directory"] = project_root or "."
        state = _run_stage(f"auto_fix_{fix_round}", coding_agent, state, stages_completed)

    # Re-run tests then re-verify after this round's fixes
    if not skip_tests:
        state = _run_stage(f"retest_{fix_round}", test_agent, state, stages_completed)
    state = _run_stage(f"verify_{fix_round}", project_verifier_agent, state, stages_completed)
    return state


def dev_pipeline_agent(state: dict) -> dict:
    """
    End-to-end project generation pipeline agent.

    Blueprint approval gate:
    - Delegates to project_blueprint_agent which uses the "project_blueprint" scope
      (recognized by runtime._apply_pending_user_response).
    - auto_approve=True → blueprint auto-approved, pipeline continues.
    - auto_approve=False → blueprint_waiting_for_approval=True is set;
      dev_pipeline_status="waiting_for_approval" and returns; the orchestrator
      routes to __finish__ to surface the prompt. On the next run with
      blueprint_status="approved", the pipeline resumes past the blueprint stage.

    Auto-fix retry loop (max_fix_rounds, default 3):
    - Triggers when verifier_status != pass OR test failures detected.
    - Extracts failing file paths from verifier/test output.
    - coding_agent called per failing file with coding_write_path set (real patch).
    - Falls back to context-only call when no file paths found.
    - Re-runs test_agent and project_verifier_agent after each round.
    - dev_pipeline_status="partial" with diagnostics on persistent failure.

    Zip export (run output directory):
    - Archive written to state["run_output_dir"] (falls back to get_output_dir()).
    - dev_pipeline_zip_path stored in state and written to dev_pipeline_zip_path.txt.

    Orchestrator finalization:
    - On return, dev_pipeline_status is set to a terminal value (complete/partial/
      error/cancelled/waiting_for_approval). The orchestrator routing block checks
      this and routes to __finish__ accordingly.
    """
    active_task, task_content, _ = begin_agent_session(state, _AGENT_NAME)
    state["dev_pipeline_agent_calls"] = state.get("dev_pipeline_agent_calls", 0) + 1

    skip_tests: bool = bool(state.get("skip_test_agent", False))
    skip_devops: bool = bool(state.get("skip_devops_agent", False))
    max_fix_rounds: int = max(0, int(state.get("dev_pipeline_max_fix_rounds", 3) or 3))

    stages_completed = list(state.get("dev_pipeline_stages_completed") or [])
    state["dev_pipeline_stages_completed"] = stages_completed
    state["dev_pipeline_error"] = ""

    # ── Determine if we are resuming after blueprint approval ──────────────────
    already_approved = str(state.get("blueprint_status", "") or "").strip() == "approved"

    _print_banner("Kendr Dev Pipeline — starting full project generation")

    # ── Lazy imports ───────────────────────────────────────────────────────────
    try:
        from tasks.project_blueprint_tasks import project_blueprint_agent
        from tasks.project_scaffold_tasks import project_scaffold_agent
        from tasks.database_architect_tasks import database_architect_agent
        from tasks.auth_security_tasks import auth_security_agent
        from tasks.backend_builder_tasks import backend_builder_agent
        from tasks.frontend_builder_tasks import frontend_builder_agent
        from tasks.dependency_manager_tasks import dependency_manager_agent
        from tasks.test_tasks import test_agent
        from tasks.security_scanner_tasks import security_scanner_agent
        from tasks.devops_tasks import devops_agent
        from tasks.project_verifier_tasks import project_verifier_agent
        from tasks.coding_tasks import coding_agent
        from tasks.post_setup_tasks import post_setup_agent
    except ImportError as exc:
        state["dev_pipeline_status"] = "error"
        state["dev_pipeline_error"] = f"Import error: {exc}"
        log_task_update("DevPipeline", f"Import failure: {exc}")
        return state

    state["dev_pipeline_status"] = "running"

    # ── Stage 1: Blueprint ─────────────────────────────────────────────────────
    # project_blueprint_agent handles both auto-approve and the approval gate
    # using the "project_blueprint" scope (recognized by runtime handling).
    if not already_approved:
        try:
            state = _run_stage("blueprint", project_blueprint_agent, state, stages_completed, fatal=True)
        except Exception as exc:
            state["dev_pipeline_status"] = "error"
            state["dev_pipeline_error"] = f"Blueprint stage failed: {exc}"
            return state

        # If blueprint agent set the approval gate, surface it and stop
        if bool(state.get("blueprint_waiting_for_approval", False)):
            state["dev_pipeline_status"] = "waiting_for_approval"
            log_task_update("DevPipeline", "Blueprint awaiting user approval.")
            _print_banner("Blueprint generated — awaiting approval.")
            return state

    # ── Stage 2: Scaffold (fatal — no scaffold means no project) ───────────────
    try:
        state = _run_stage("scaffold", project_scaffold_agent, state, stages_completed, fatal=True)
    except Exception as exc:
        state["dev_pipeline_status"] = "error"
        state["dev_pipeline_error"] = f"Scaffold stage failed: {exc}"
        return state

    # ── Stage 3: Database architect ────────────────────────────────────────────
    state = _run_stage("database", database_architect_agent, state, stages_completed)

    # ── Stage 4: Auth & security helpers ──────────────────────────────────────
    blueprint = state.get("blueprint_json") or {}
    auth_type = str(((blueprint.get("tech_stack") or {}).get("auth", "") or "")).lower()
    if auth_type and auth_type not in ("none", "no"):
        state = _run_stage("auth", auth_security_agent, state, stages_completed)

    # ── Stage 5: Backend ───────────────────────────────────────────────────────
    state = _run_stage("backend", backend_builder_agent, state, stages_completed)

    # ── Stage 6: Frontend ──────────────────────────────────────────────────────
    has_frontend = bool(blueprint.get("frontend_components") or blueprint.get("frontend"))
    if has_frontend:
        state = _run_stage("frontend", frontend_builder_agent, state, stages_completed)

    # ── Stage 7: Dependency manager ────────────────────────────────────────────
    state = _run_stage("deps", dependency_manager_agent, state, stages_completed)

    # ── Stage 8: Tests (first run) ────────────────────────────────────────────
    if not skip_tests:
        state = _run_stage("tests", test_agent, state, stages_completed)

    # ── Stage 9: Security scanner ─────────────────────────────────────────────
    state = _run_stage("security_scan", security_scanner_agent, state, stages_completed)

    # ── Stage 10: DevOps ──────────────────────────────────────────────────────
    if not skip_devops:
        state = _run_stage("devops", devops_agent, state, stages_completed)

    # ── Stage 11: Initial verify ──────────────────────────────────────────────
    state = _run_stage("verify_0", project_verifier_agent, state, stages_completed)

    # ── Auto-fix + retest loop ────────────────────────────────────────────────
    all_passing = _verifier_passed(state) and (skip_tests or _tests_passed(state))

    if not all_passing:
        for fix_round in range(1, max_fix_rounds + 1):
            state = _run_fix_round(
                state,
                fix_round=fix_round,
                max_fix_rounds=max_fix_rounds,
                skip_tests=skip_tests,
                stages_completed=stages_completed,
                coding_agent=coding_agent,
                test_agent=test_agent,
                project_verifier_agent=project_verifier_agent,
            )
            all_passing = _verifier_passed(state) and (skip_tests or _tests_passed(state))
            if all_passing:
                log_task_update("DevPipeline", f"All checks passed after fix round {fix_round}.")
                break

        if not all_passing:
            log_task_update("DevPipeline", "Max auto-fix rounds exhausted; proceeding to post-setup.")

    # ── Stage 12: Post-setup ──────────────────────────────────────────────────
    state = _run_stage("post_setup", post_setup_agent, state, stages_completed)

    # ── Zip export (into run output directory) ────────────────────────────────
    project_root_str = str(state.get("project_root", "") or "").strip()
    project_name = str(state.get("project_name", "") or "").strip()
    zip_path_result = ""
    if project_root_str:
        project_root_path = Path(project_root_str).resolve()
        if not project_name:
            project_name = project_root_path.name or "project"
        if project_root_path.exists():
            run_output_dir_str = str(state.get("run_output_dir", "") or "").strip()
            zip_output_dir = (
                Path(run_output_dir_str).resolve()
                if run_output_dir_str
                else Path(get_output_dir()).resolve()
            )
            try:
                zip_path_result = _zip_project(project_root_path, zip_output_dir)
                state["dev_pipeline_zip_path"] = zip_path_result
                write_text_file("dev_pipeline_zip_path.txt", zip_path_result)
                log_task_update("DevPipeline", f"Project zipped to: {zip_path_result}")
                _print_banner(f"Project export: {zip_path_result}")
            except Exception as exc:
                log_task_update("DevPipeline", f"Zip export failed (non-fatal): {exc}")
                state["dev_pipeline_zip_path"] = ""
        else:
            log_task_update("DevPipeline", f"project_root not found for zip: {project_root_path}")
            state["dev_pipeline_zip_path"] = ""
    else:
        state["dev_pipeline_zip_path"] = ""

    # ── Final status ──────────────────────────────────────────────────────────
    if all_passing:
        state["dev_pipeline_status"] = "complete"
        final_label = "COMPLETE"
    else:
        state["dev_pipeline_status"] = "partial"
        final_label = "PARTIAL (some checks still failing)"
        failure_parts = []
        if not _verifier_passed(state):
            failure_parts.append(
                f"Verifier: {state.get('verifier_status', 'fail')}\n"
                f"{str(state.get('verifier_summary', ''))[:400]}"
            )
        if not skip_tests and not _tests_passed(state):
            failure_parts.append(
                f"Tests: {state.get('test_agent_status', 'fail')}\n"
                f"{str(state.get('test_agent_summary', ''))[:400]}"
            )
        state["dev_pipeline_error"] = "\n\n".join(failure_parts)

    state["dev_pipeline_stages_completed"] = stages_completed

    summary_lines = [
        f"Dev Pipeline {final_label}.",
        f"Stages completed: {', '.join(stages_completed)}.",
    ]
    if zip_path_result:
        summary_lines.append(f"Project archive: {zip_path_result}")
    if not all_passing:
        summary_lines.append(
            "Remaining failures:\n" + str(state.get("dev_pipeline_error", ""))[:500]
        )

    summary = "\n".join(summary_lines)
    state["draft_response"] = summary
    log_task_update("DevPipeline", summary)
    _print_banner(f"Kendr Dev Pipeline — {final_label}")

    state = publish_agent_output(
        state,
        _AGENT_NAME,
        summary,
        f"dev_pipeline_{state['dev_pipeline_status']}",
        recipients=["orchestrator_agent"],
    )
    return state
