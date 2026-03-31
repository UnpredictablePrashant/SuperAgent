"""
dev_pipeline_tasks.py — Multi-agent dev project pipeline orchestrator.

Provides `dev_pipeline_agent(state)` which orchestrates the complete
end-to-end project generation flow in a single agent call:

  blueprint → [approval gate] → scaffold → db → auth → backend →
  frontend → deps → tests → security_scan → devops → verify →
  [auto-fix + retest loop ×N] → post_setup → zip export

Activated when state["dev_pipeline_mode"] is True.
Intended for `kendr run --dev "…"` or `kendr generate "…"`.

Blueprint approval:
- auto_approve=True → skip gate, continue immediately.
- auto_approve=False → set pending_user_input_kind="blueprint_approval",
  set dev_pipeline_status="waiting_for_approval", and return.
  The next orchestrator turn (after user replies) should set
  blueprint_status="approved" and re-dispatch dev_pipeline_agent.

Auto-fix retry loop:
- Triggers when verifier_status != "pass" OR test_agent_status indicates failure.
- Builds rich context (verifier report + failed checks + test output) for coding_agent.
- Re-runs test_agent and project_verifier_agent after each fix attempt.
- On persistent failure: dev_pipeline_status="partial" with diagnostic summary.

Zip export:
- Written to state["run_output_dir"] (falls back to get_output_dir()).
- dev_pipeline_zip_path persisted in state and written to dev_pipeline_zip_path.txt.
"""

from __future__ import annotations

import sys
import time
import zipfile
from pathlib import Path
from typing import Callable

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
    stages_completed: list[str],
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
    skip_dirs = {".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache", "dist", "build"}
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
    """
    Return True when verifier_status indicates success.
    project_verifier_agent writes state["verifier_status"] = "pass" or "fail".
    Empty/absent status = no checks ran = treated as pass.
    """
    status = str(state.get("verifier_status", "")).strip().lower()
    return not status or status in ("pass", "passed", "ok", "success")


def _tests_passed(state: dict) -> bool:
    """Return True when test_agent_status indicates success or tests were skipped."""
    status = str(state.get("test_agent_status", "") or "").strip().lower()
    return not status or status in ("pass", "passed", "ok", "success")


def _build_fix_context(state: dict, fix_round: int) -> str:
    """
    Build a rich fix-context string for coding_agent.
    Combines verifier failures AND test_agent failures.
    Handles test_agent_results as list[str] (as written by test_tasks.py).
    """
    lines = [
        f"Auto-fix round {fix_round}: Fix failures in the generated project.",
        "",
        f"Project root: {state.get('project_root', '(unknown)')}",
        "",
    ]

    # ── Verifier failures ─────────────────────────────────────────────────────
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
            stderr = str(check.get("stderr", "")).strip()
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

    # ── Test agent failures ───────────────────────────────────────────────────
    # test_agent_results is a list[str] (each entry is a result line/message)
    if not _tests_passed(state):
        lines.append("=== Test Failures ===")
        test_summary = str(state.get("test_agent_summary", "") or "").strip()
        if test_summary:
            lines.append(test_summary[:1000])
            lines.append("")

        test_results = state.get("test_agent_results") or []
        if test_results:
            lines.append("Test output:")
            for line in test_results[:30]:
                lines.append(f"  {str(line)[:300]}")
            lines.append("")

    lines.append("Fix all failures listed above and ensure all checks pass.")
    return "\n".join(lines)


def dev_pipeline_agent(state: dict) -> dict:
    """
    End-to-end project generation pipeline agent.

    Blueprint approval gate:
    - If auto_approve=True: blueprint auto-approved, pipeline continues immediately.
    - If auto_approve=False: sets pending_user_input_kind="blueprint_approval",
      pending_user_question=(blueprint summary + approval prompt),
      dev_pipeline_status="waiting_for_approval", and returns. The orchestrator
      exposes this to the user; the next run should have blueprint_status="approved".

    Auto-fix retry loop (max_fix_rounds, default 3):
    - Triggers when verifier_status != pass OR test failures detected.
    - coding_agent receives full failure context (verifier + test output).
    - test_agent and project_verifier_agent are re-run after each fix.
    - test_agent_results handled as list[str] (test_tasks.py format).
    - On persistent failure: dev_pipeline_status="partial" with diagnostics.

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

    auto_approve: bool = bool(state.get("auto_approve") or state.get("auto_approve_blueprint"))
    skip_tests: bool = bool(state.get("skip_test_agent", False))
    skip_devops: bool = bool(state.get("skip_devops_agent", False))
    max_fix_rounds: int = max(0, int(state.get("dev_pipeline_max_fix_rounds", 3) or 3))

    stages_completed: list[str] = list(state.get("dev_pipeline_stages_completed") or [])
    state["dev_pipeline_stages_completed"] = stages_completed
    state["dev_pipeline_error"] = ""

    # ── Handle resume after blueprint approval ─────────────────────────────────
    # If we're re-entering after the user approved the blueprint interactively,
    # blueprint_status should already be "approved" so we skip the gate below.
    already_approved = str(state.get("blueprint_status", "")).strip() == "approved"

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

    # ── Stage 1: Blueprint (only if not already done) ─────────────────────────
    if not already_approved:
        try:
            state = _run_stage("blueprint", project_blueprint_agent, state, stages_completed, fatal=True)
        except Exception as exc:
            state["dev_pipeline_status"] = "error"
            state["dev_pipeline_error"] = f"Blueprint stage failed: {exc}"
            return state

        # ── Blueprint approval gate ────────────────────────────────────────────
        blueprint_md = str(state.get("draft_response", "")).strip()
        project_root_display = str(state.get("project_root", "(working directory)"))

        if auto_approve:
            state["blueprint_status"] = "approved"
            state["blueprint_waiting_for_approval"] = False
            log_task_update("DevPipeline", "Blueprint auto-approved.")
        else:
            approval_prompt = (
                f"Blueprint ready for review:\n\n"
                f"{blueprint_md[:4000]}\n\n"
                f"Project will be generated at: {project_root_display}\n\n"
                "Reply **approve** (or yes/y) to proceed, or describe changes to regenerate."
            )
            state["pending_user_question"] = approval_prompt
            state["pending_user_input_kind"] = "blueprint_approval"
            state["approval_pending_scope"] = "dev_pipeline_blueprint"
            state["blueprint_waiting_for_approval"] = True
            state["dev_pipeline_status"] = "waiting_for_approval"
            state["draft_response"] = approval_prompt
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
    auth_type = str(((blueprint.get("tech_stack") or {}).get("auth", "")) or "").lower()
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
    # Triggers on verifier_status=fail OR test_agent_status indicating failure.
    all_passing = _verifier_passed(state) and (skip_tests or _tests_passed(state))

    if not all_passing:
        for fix_round in range(1, max_fix_rounds + 1):
            fix_context = _build_fix_context(state, fix_round)
            log_task_update(
                "DevPipeline",
                f"Auto-fix round {fix_round}/{max_fix_rounds} — "
                f"verifier={'pass' if _verifier_passed(state) else 'fail'}, "
                f"tests={'pass' if _tests_passed(state) else 'fail'}.",
            )
            state["current_objective"] = fix_context
            state["task"] = fix_context

            state = _run_stage(f"auto_fix_{fix_round}", coding_agent, state, stages_completed)

            if not skip_tests:
                state = _run_stage(f"retest_{fix_round}", test_agent, state, stages_completed)

            state = _run_stage(f"verify_{fix_round}", project_verifier_agent, state, stages_completed)

            all_passing = _verifier_passed(state) and (skip_tests or _tests_passed(state))
            if all_passing:
                log_task_update("DevPipeline", f"All checks passed after fix round {fix_round}.")
                break

        if not all_passing:
            log_task_update("DevPipeline", "Max auto-fix rounds exhausted; proceeding to post-setup.")

    # ── Stage 12: Post-setup ──────────────────────────────────────────────────
    state = _run_stage("post_setup", post_setup_agent, state, stages_completed)

    # ── Zip export (into run output directory) ────────────────────────────────
    project_root_str = str(state.get("project_root", "")).strip()
    project_name = str(state.get("project_name", "")).strip()
    zip_path_result = ""
    if project_root_str:
        project_root_path = Path(project_root_str).resolve()
        if not project_name:
            project_name = project_root_path.name or "project"
        if project_root_path.exists():
            run_output_dir_str = str(state.get("run_output_dir", "")).strip()
            if run_output_dir_str:
                zip_output_dir = Path(run_output_dir_str).resolve()
            else:
                zip_output_dir = Path(get_output_dir()).resolve()
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
