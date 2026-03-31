"""
dev_pipeline_tasks.py — Multi-agent dev project pipeline orchestrator.

Provides `dev_pipeline_agent(state)` which orchestrates the complete
end-to-end project generation flow in a single agent call:

  blueprint → [y/n approval] → scaffold → db → auth → backend →
  frontend → deps → tests → security_scan → devops → verify →
  [auto-fix + retest loop ×N] → post_setup → zip export

Activated when state["dev_pipeline_mode"] is True.
Intended for `kendr run --dev "…"` or `kendr generate "…"`.
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
            "Orchestrates blueprint → [y/n approval] → scaffold → build → "
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


def _ask_yn(prompt: str) -> bool:
    """Block for an interactive y/n answer. Returns True on yes."""
    sys.stdout.write(f"\n{prompt}\n\nApprove? [y/N]: ")
    sys.stdout.flush()
    try:
        answer = sys.stdin.readline().strip().lower()
    except (EOFError, OSError):
        answer = ""
    return answer in ("y", "yes", "approve", "ok")


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
    Create a zip archive of the generated project in output_dir.
    Returns the zip file path string.
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
    Return True if verifier_status indicates success.
    project_verifier_agent writes state["verifier_status"] = "pass" or "fail".
    An absent/empty status is treated as pass (no checks run = nothing failed).
    """
    status = str(state.get("verifier_status", "")).strip().lower()
    return not status or status in ("pass", "passed", "ok", "success")


def _build_fix_context(state: dict, fix_round: int) -> str:
    """
    Build a rich fix context string for coding_agent.
    Combines verifier failures AND test_agent failures with concrete file paths.
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
        if not r.get("success", True)
    ]
    if failed_checks:
        lines.append("Failed verification checks:")
        for check in failed_checks[:15]:
            lines.append(f"  [{check.get('label', '?')}]")
            if check.get("stderr"):
                for err_line in str(check["stderr"]).splitlines()[:5]:
                    lines.append(f"    {err_line}")
        lines.append("")

    issues = state.get("verifier_issues") or []
    if issues:
        lines.append("Specific issues to resolve:")
        for issue in issues[:15]:
            lines.append(
                f"  [{issue.get('severity', '?')}] {issue.get('check', '?')}: "
                f"{str(issue.get('message', ''))[:200]}"
            )
        lines.append("")

    # ── Test agent failures ───────────────────────────────────────────────────
    test_status = str(state.get("test_agent_status", "") or "").strip().lower()
    if test_status and test_status not in ("pass", "passed", "ok", "success", ""):
        lines.append("=== Test Failures ===")
        test_summary = str(state.get("test_agent_summary", "") or "").strip()
        if test_summary:
            lines.append(test_summary[:2000])
            lines.append("")

        test_results = state.get("test_agent_results") or []
        failed_tests = [r for r in test_results if not r.get("success", True)]
        if failed_tests:
            lines.append("Failed test files/suites:")
            for result in failed_tests[:10]:
                file_path = str(result.get("file") or result.get("path") or result.get("test_file", "")).strip()
                if file_path:
                    lines.append(f"  File: {file_path}")
                error_msg = str(result.get("stderr") or result.get("error") or result.get("message", "")).strip()
                if error_msg:
                    for err_line in error_msg.splitlines()[:5]:
                        lines.append(f"    {err_line}")
            lines.append("")

    lines.append("Fix all issues listed above and ensure all checks pass.")
    return "\n".join(lines)


def dev_pipeline_agent(state: dict) -> dict:
    """
    End-to-end project generation pipeline agent.

    Runs synchronously through all build stages in sequence. Activates when
    state["dev_pipeline_mode"] is True.

    Blueprint approval gate (interactive y/n):
    - Renders the blueprint summary and prompts the user to approve or abort.
    - Skipped (auto-approved) when auto_approve=True in state.

    Auto-fix retry loop:
    - Triggers when verifier OR tests fail.
    - Passes failing verifier details AND failing test results (including file
      paths) to coding_agent.
    - Re-runs test_agent and project_verifier_agent after each fix.
    - Repeats up to dev_pipeline_max_fix_rounds times (default 3).
    - On persistent failure: dev_pipeline_status="partial" with diagnostics.

    Zip export:
    - Archives project into run_output_dir (state["run_output_dir"]).
    - Falls back to the active output dir, then project parent dir.
    - Persists dev_pipeline_zip_path in state and writes dev_pipeline_zip_path.txt.
    """
    active_task, task_content, _ = begin_agent_session(state, _AGENT_NAME)
    state["dev_pipeline_agent_calls"] = state.get("dev_pipeline_agent_calls", 0) + 1

    auto_approve: bool = bool(state.get("auto_approve") or state.get("auto_approve_blueprint"))
    skip_tests: bool = bool(state.get("skip_test_agent", False))
    skip_devops: bool = bool(state.get("skip_devops_agent", False))
    max_fix_rounds: int = max(0, int(state.get("dev_pipeline_max_fix_rounds", 3) or 3))

    stages_completed: list[str] = list(state.get("dev_pipeline_stages_completed") or [])
    state["dev_pipeline_stages_completed"] = stages_completed
    state["dev_pipeline_status"] = "running"
    state["dev_pipeline_error"] = ""

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

    # ── Stage 1: Blueprint ─────────────────────────────────────────────────────
    try:
        state = _run_stage("blueprint", project_blueprint_agent, state, stages_completed, fatal=True)
    except Exception as exc:
        state["dev_pipeline_status"] = "error"
        state["dev_pipeline_error"] = f"Blueprint stage failed: {exc}"
        return state

    # ── Blueprint approval gate: interactive y/n prompt ────────────────────────
    if auto_approve:
        state["blueprint_status"] = "approved"
        state["blueprint_waiting_for_approval"] = False
        log_task_update("DevPipeline", "Blueprint auto-approved.")
    else:
        blueprint_md = str(state.get("draft_response", "")).strip()
        project_root_display = str(state.get("project_root", "(working directory)"))
        approval_prompt = (
            f"Blueprint generated.\n\n"
            f"{blueprint_md[:3000]}\n\n"
            f"Project will be generated at: {project_root_display}"
        )
        _print_banner("Blueprint ready — review and approve")
        approved = _ask_yn(approval_prompt)
        if not approved:
            state["dev_pipeline_status"] = "cancelled"
            state["dev_pipeline_error"] = "Blueprint rejected by user at approval gate."
            log_task_update("DevPipeline", "User rejected blueprint. Pipeline cancelled.")
            _print_banner("Pipeline cancelled — blueprint not approved.")
            return state
        state["blueprint_status"] = "approved"
        state["blueprint_waiting_for_approval"] = False
        log_task_update("DevPipeline", "Blueprint approved — continuing to build.")

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
    verifier_passed = _verifier_passed(state)

    # ── Auto-fix + retest loop ────────────────────────────────────────────────
    # Triggers on verifier failure OR test failure.
    test_status = str(state.get("test_agent_status", "") or "").strip().lower()
    tests_failed = bool(test_status) and test_status not in ("pass", "passed", "ok", "success")

    if not verifier_passed or tests_failed:
        for fix_round in range(1, max_fix_rounds + 1):
            fix_context = _build_fix_context(state, fix_round)
            log_task_update(
                "DevPipeline",
                f"Auto-fix round {fix_round}/{max_fix_rounds} — "
                f"verifier={'fail' if not verifier_passed else 'pass'}, "
                f"tests={'fail' if tests_failed else 'pass'}.",
            )
            state["current_objective"] = fix_context
            state["task"] = fix_context

            state = _run_stage(f"auto_fix_{fix_round}", coding_agent, state, stages_completed)

            if not skip_tests:
                state = _run_stage(f"retest_{fix_round}", test_agent, state, stages_completed)
                test_status = str(state.get("test_agent_status", "") or "").strip().lower()
                tests_failed = bool(test_status) and test_status not in ("pass", "passed", "ok", "success")

            state = _run_stage(f"verify_{fix_round}", project_verifier_agent, state, stages_completed)
            verifier_passed = _verifier_passed(state)

            if verifier_passed and not tests_failed:
                log_task_update("DevPipeline", f"All checks passed after fix round {fix_round}.")
                break

        if not verifier_passed or tests_failed:
            log_task_update("DevPipeline", "Max auto-fix rounds exhausted; proceeding to post-setup.")

    # ── Stage 12: Post-setup ──────────────────────────────────────────────────
    state = _run_stage("post_setup", post_setup_agent, state, stages_completed)

    # ── Zip export (into run_output_dir) ──────────────────────────────────────
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
    pipeline_success = verifier_passed and not tests_failed
    if pipeline_success:
        state["dev_pipeline_status"] = "complete"
        final_label = "COMPLETE"
    else:
        state["dev_pipeline_status"] = "partial"
        final_label = "PARTIAL (some checks still failing)"
        failure_detail_lines = []
        if not verifier_passed:
            failure_detail_lines.append(
                f"Verifier: {state.get('verifier_status', 'fail')}\n"
                f"{str(state.get('verifier_summary', ''))[:500]}"
            )
        if tests_failed:
            failure_detail_lines.append(
                f"Tests: {state.get('test_agent_status', 'fail')}\n"
                f"{str(state.get('test_agent_summary', ''))[:500]}"
            )
        state["dev_pipeline_error"] = "\n\n".join(failure_detail_lines)

    state["dev_pipeline_stages_completed"] = stages_completed

    summary_lines = [
        f"Dev Pipeline {final_label}.",
        f"Stages completed: {', '.join(stages_completed)}.",
    ]
    if zip_path_result:
        summary_lines.append(f"Project archive: {zip_path_result}")
    if not pipeline_success:
        summary_lines.append(
            "Remaining failures:\n" + str(state.get("dev_pipeline_error", ""))[:600]
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
