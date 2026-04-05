from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from kendr.orchestration import state_awaiting_user_input


RUN_MANIFEST_FILE = "run_manifest.json"
RUN_CHECKPOINT_FILE = "checkpoint.json"
RUN_HEARTBEAT_FILE = "heartbeat.json"
RUN_RESUME_SUMMARY_FILE = "resume_summary.json"
RECOVERY_SCHEMA_VERSION = 1
DEFAULT_STALE_SECONDS = int(os.getenv("KENDR_STALE_HEARTBEAT_SECONDS", "900") or 900)

_STATE_BLACKLIST = {
    "a2a",
    "active_task",
    "available_agent_cards",
    "setup_status",
    "channel_session",
    "incoming_payload",
    "privileged_policy",
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_json(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _safe_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_safe_json(item) for item in value]
    return str(value)


def recovery_file_paths(run_output_dir: str) -> dict[str, str]:
    base = Path(run_output_dir).expanduser().resolve()
    return {
        "run_output_dir": str(base),
        "manifest": str(base / RUN_MANIFEST_FILE),
        "checkpoint": str(base / RUN_CHECKPOINT_FILE),
        "heartbeat": str(base / RUN_HEARTBEAT_FILE),
        "summary": str(base / RUN_RESUME_SUMMARY_FILE),
    }


def _state_snapshot(state: dict) -> dict[str, Any]:
    snapshot: dict[str, Any] = {}
    for key, value in state.items():
        if key in _STATE_BLACKLIST or str(key).startswith("_"):
            continue
        snapshot[str(key)] = _safe_json(value)
    return snapshot


def _parse_iso(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        if raw.endswith("Z"):
            raw = raw[:-1] + "+00:00"
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _classify_status(summary: dict[str, Any], *, stale_after_seconds: int = DEFAULT_STALE_SECONDS) -> tuple[str, bool, bool, str]:
    raw_status = str(summary.get("status", "") or "").strip().lower() or "unknown"
    awaiting = bool(summary.get("awaiting_user_input", False))
    if raw_status == "completed":
        return "completed", False, True, "branch_only"
    if awaiting or raw_status == "awaiting_user_input":
        return "awaiting_user_input", True, True, "user_input"

    failure_checkpoint = summary.get("failure_checkpoint", {})
    if raw_status == "failed":
        can_resume = bool(isinstance(failure_checkpoint, dict) and failure_checkpoint.get("can_resume", False))
        return "failed", can_resume, True, "step_resume" if can_resume else "blocked"

    updated_at = _parse_iso(str(summary.get("updated_at", "") or ""))
    if raw_status == "running":
        if updated_at:
            age = (datetime.now(timezone.utc) - updated_at).total_seconds()
            if age >= max(60, stale_after_seconds):
                return "running_stale", True, True, "takeover_resume"
        return "running", False, True, "takeover_required"

    return raw_status or "unknown", False, True, "unknown"


def build_recovery_payloads(
    state: dict,
    *,
    status: str,
    active_agent: str = "",
    completed_at: str = "",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    updated_at = _now_iso()
    snapshot = _state_snapshot(state)
    summary = {
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "run_id": state.get("run_id", ""),
        "workflow_id": state.get("workflow_id", state.get("run_id", "")),
        "attempt_id": state.get("attempt_id", state.get("run_id", "")),
        "workflow_type": state.get("workflow_type", ""),
        "session_id": state.get("session_id", ""),
        "session_started_at": state.get("session_started_at", ""),
        "status": status,
        "updated_at": updated_at,
        "completed_at": completed_at,
        "working_directory": state.get("working_directory", ""),
        "run_output_dir": state.get("run_output_dir", ""),
        "channel_session_key": state.get("channel_session_key", ""),
        "parent_run_id": state.get("parent_run_id", ""),
        "objective": state.get("current_objective", state.get("user_query", "")),
        "user_query": state.get("user_query", ""),
        "active_agent": active_agent or state.get("last_agent", ""),
        "last_agent": state.get("last_agent", ""),
        "last_error": state.get("last_error", ""),
        "awaiting_user_input": state_awaiting_user_input(state),
        "pending_user_input_kind": state.get("pending_user_input_kind", ""),
        "pending_user_question": state.get("pending_user_question", ""),
        "approval_pending_scope": state.get("approval_pending_scope", ""),
        "approval_request": _safe_json(state.get("approval_request", {})),
        "plan_step_index": int(state.get("plan_step_index", 0) or 0),
        "plan_step_count": len(state.get("plan_steps", []) or []),
        "current_plan_step_id": state.get("current_plan_step_id", ""),
        "current_plan_step_title": state.get("current_plan_step_title", ""),
        "last_completed_plan_step_id": state.get("last_completed_plan_step_id", ""),
        "last_completed_plan_step_title": state.get("last_completed_plan_step_title", ""),
        "failure_checkpoint": _safe_json(state.get("failure_checkpoint", {})),
    }
    resume_status, resumable, branchable, resume_strategy = _classify_status(summary)
    summary["resume_status"] = resume_status
    summary["resumable"] = resumable
    summary["branchable"] = branchable
    summary["resume_strategy"] = resume_strategy

    manifest = {
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "summary": summary,
        "files": recovery_file_paths(str(state.get("run_output_dir") or "")),
    }
    checkpoint = {
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "summary": summary,
        "state_snapshot": snapshot,
    }
    heartbeat = {
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "run_id": summary["run_id"],
        "workflow_id": summary["workflow_id"],
        "attempt_id": summary["attempt_id"],
        "workflow_type": summary["workflow_type"],
        "session_id": summary["session_id"],
        "status": status,
        "active_agent": summary["active_agent"],
        "updated_at": updated_at,
        "pid": os.getpid(),
    }
    resume_summary = {
        "schema_version": RECOVERY_SCHEMA_VERSION,
        "run_id": summary["run_id"],
        "workflow_id": summary["workflow_id"],
        "attempt_id": summary["attempt_id"],
        "status": summary["resume_status"],
        "resumable": summary["resumable"],
        "branchable": summary["branchable"],
        "resume_strategy": summary["resume_strategy"],
        "objective": summary["objective"],
        "active_agent": summary["active_agent"],
        "last_agent": summary["last_agent"],
        "last_error": summary["last_error"],
        "pending_user_input_kind": summary["pending_user_input_kind"],
        "pending_user_question": summary["pending_user_question"],
        "approval_request": summary["approval_request"],
        "plan_step_index": summary["plan_step_index"],
        "plan_step_count": summary["plan_step_count"],
        "current_plan_step_title": summary["current_plan_step_title"],
        "last_completed_plan_step_title": summary["last_completed_plan_step_title"],
        "updated_at": summary["updated_at"],
        "working_directory": summary["working_directory"],
        "run_output_dir": summary["run_output_dir"],
    }
    return manifest, checkpoint, heartbeat, resume_summary


def write_recovery_files(
    state: dict,
    *,
    status: str,
    active_agent: str = "",
    completed_at: str = "",
) -> dict[str, Any]:
    run_output_dir = str(state.get("run_output_dir") or "").strip()
    if not run_output_dir:
        return {}
    paths = recovery_file_paths(run_output_dir)
    base = Path(paths["run_output_dir"])
    base.mkdir(parents=True, exist_ok=True)

    manifest, checkpoint, heartbeat, resume_summary = build_recovery_payloads(
        state,
        status=status,
        active_agent=active_agent,
        completed_at=completed_at,
    )
    Path(paths["manifest"]).write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    Path(paths["checkpoint"]).write_text(json.dumps(checkpoint, indent=2, ensure_ascii=False), encoding="utf-8")
    Path(paths["heartbeat"]).write_text(json.dumps(heartbeat, indent=2, ensure_ascii=False), encoding="utf-8")
    Path(paths["summary"]).write_text(json.dumps(resume_summary, indent=2, ensure_ascii=False), encoding="utf-8")
    return {
        "manifest": manifest,
        "checkpoint": checkpoint,
        "heartbeat": heartbeat,
        "resume_summary": resume_summary,
        "paths": paths,
    }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return payload if isinstance(payload, dict) else {}


def _candidate_from_run_dir(run_dir: Path, *, stale_after_seconds: int = DEFAULT_STALE_SECONDS) -> dict[str, Any]:
    manifest = _load_json(run_dir / RUN_MANIFEST_FILE)
    checkpoint = _load_json(run_dir / RUN_CHECKPOINT_FILE)
    summary = manifest.get("summary", {}) if isinstance(manifest.get("summary"), dict) else {}
    if not summary and isinstance(checkpoint.get("summary"), dict):
        summary = checkpoint.get("summary", {})
    if not summary:
        return {}

    resume_status, resumable, branchable, resume_strategy = _classify_status(summary, stale_after_seconds=stale_after_seconds)
    candidate = {
        "run_id": str(summary.get("run_id", "")).strip(),
        "workflow_id": str(summary.get("workflow_id", "")).strip() or str(summary.get("run_id", "")).strip(),
        "attempt_id": str(summary.get("attempt_id", "")).strip() or str(summary.get("run_id", "")).strip(),
        "workflow_type": str(summary.get("workflow_type", "")).strip(),
        "session_id": str(summary.get("session_id", "")).strip(),
        "status": str(summary.get("status", "")).strip(),
        "resume_status": resume_status,
        "resumable": resumable,
        "branchable": branchable,
        "resume_strategy": resume_strategy,
        "working_directory": str(summary.get("working_directory", "")).strip(),
        "run_output_dir": str(run_dir.resolve()),
        "updated_at": str(summary.get("updated_at", "")).strip(),
        "completed_at": str(summary.get("completed_at", "")).strip(),
        "objective": str(summary.get("objective", "")).strip(),
        "user_query": str(summary.get("user_query", "")).strip(),
        "active_agent": str(summary.get("active_agent", "")).strip(),
        "last_agent": str(summary.get("last_agent", "")).strip(),
        "last_error": str(summary.get("last_error", "")).strip(),
        "pending_user_input_kind": str(summary.get("pending_user_input_kind", "")).strip(),
        "pending_user_question": str(summary.get("pending_user_question", "")).strip(),
        "approval_pending_scope": str(summary.get("approval_pending_scope", "")).strip(),
        "approval_request": _safe_json(summary.get("approval_request", {})),
        "plan_step_index": int(summary.get("plan_step_index", 0) or 0),
        "plan_step_count": int(summary.get("plan_step_count", 0) or 0),
        "current_plan_step_id": str(summary.get("current_plan_step_id", "")).strip(),
        "current_plan_step_title": str(summary.get("current_plan_step_title", "")).strip(),
        "last_completed_plan_step_id": str(summary.get("last_completed_plan_step_id", "")).strip(),
        "last_completed_plan_step_title": str(summary.get("last_completed_plan_step_title", "")).strip(),
        "failure_checkpoint": summary.get("failure_checkpoint", {}),
        "channel_session_key": str(summary.get("channel_session_key", "")).strip(),
        "parent_run_id": str(summary.get("parent_run_id", "")).strip(),
        "manifest": manifest,
        "checkpoint": checkpoint,
    }
    candidate["requires_takeover"] = resume_status in {"running", "running_stale"}
    return candidate


def _candidate_dirs(path_value: str) -> list[Path]:
    target = Path(path_value).expanduser().resolve()
    if target.is_file():
        if target.name in {RUN_MANIFEST_FILE, RUN_CHECKPOINT_FILE, RUN_HEARTBEAT_FILE, RUN_RESUME_SUMMARY_FILE}:
            target = target.parent
        else:
            target = target.parent

    dirs: list[Path] = []
    if (target / RUN_MANIFEST_FILE).exists() or (target / RUN_CHECKPOINT_FILE).exists():
        return [target]

    search_roots = [target]
    runs_child = target / "runs"
    if runs_child.exists():
        search_roots.insert(0, runs_child)

    seen: set[str] = set()
    for root in search_roots:
        if not root.exists() or not root.is_dir():
            continue
        for child in root.iterdir():
            if not child.is_dir():
                continue
            key = str(child.resolve())
            if key in seen:
                continue
            if (child / RUN_MANIFEST_FILE).exists() or (child / RUN_CHECKPOINT_FILE).exists():
                seen.add(key)
                dirs.append(child)
    return dirs


def discover_resume_candidates(path_value: str, *, stale_after_seconds: int = DEFAULT_STALE_SECONDS, limit: int = 20) -> list[dict[str, Any]]:
    candidates = [
        _candidate_from_run_dir(candidate_dir, stale_after_seconds=stale_after_seconds)
        for candidate_dir in _candidate_dirs(path_value)
    ]
    filtered = [item for item in candidates if item]
    filtered.sort(key=lambda item: str(item.get("updated_at", "")).strip(), reverse=True)
    return filtered[: max(1, int(limit or 20))]


def load_resume_candidate(path_value: str, *, stale_after_seconds: int = DEFAULT_STALE_SECONDS) -> dict[str, Any]:
    candidates = discover_resume_candidates(path_value, stale_after_seconds=stale_after_seconds, limit=1)
    return candidates[0] if candidates else {}


def render_resume_candidate(candidate: dict[str, Any]) -> str:
    if not candidate:
        return "No resumable session was found."
    lines = [
        f"Run ID: {candidate.get('run_id', '') or 'unknown'}",
        f"Run Folder: {candidate.get('run_output_dir', '') or 'unknown'}",
        f"Status: {candidate.get('resume_status', candidate.get('status', 'unknown'))}",
        f"Resumable: {bool(candidate.get('resumable', False))}",
        f"Branchable: {bool(candidate.get('branchable', False))}",
        f"Resume Strategy: {candidate.get('resume_strategy', 'unknown')}",
        f"Objective: {candidate.get('objective', '') or candidate.get('user_query', '') or 'n/a'}",
        f"Active Agent: {candidate.get('active_agent', '') or '-'}",
        f"Last Agent: {candidate.get('last_agent', '') or '-'}",
        f"Current Step: {candidate.get('current_plan_step_title', '') or '-'}",
        f"Last Completed Step: {candidate.get('last_completed_plan_step_title', '') or '-'}",
        f"Updated At: {candidate.get('updated_at', '') or '-'}",
    ]
    pending_kind = str(candidate.get("pending_user_input_kind", "") or "").strip()
    if pending_kind:
        lines.append(f"Awaiting Input: {pending_kind}")
    pending_question = str(candidate.get("pending_user_question", "") or "").strip()
    if pending_question:
        lines.extend(["", pending_question])
    last_error = str(candidate.get("last_error", "") or "").strip()
    if last_error:
        lines.extend(["", f"Last Error: {last_error}"])
    return "\n".join(lines)
