from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from kendr.orchestration.state import ResumeCandidate, ResumeStateOverrides


def infer_resume_working_directory(candidate: Mapping[str, Any], *, fallback: str = "") -> str:
    working_dir = str(candidate.get("working_directory", "") or "").strip()
    if working_dir:
        return str(Path(working_dir).expanduser().resolve())

    run_dir = Path(str(candidate.get("run_output_dir", "") or "")).expanduser().resolve()
    if run_dir.parent.name == "runs" and run_dir.parent.parent.exists():
        return str(run_dir.parent.parent.resolve())
    if run_dir.parent.exists():
        return str(run_dir.parent.resolve())
    if fallback:
        return str(Path(fallback).expanduser().resolve())
    return str(Path.cwd())


def resume_candidate_requires_branch(candidate: Mapping[str, Any], *, branch: bool) -> bool:
    return str(candidate.get("resume_status", "")).strip() == "completed" and not branch


def resume_candidate_requires_force(candidate: Mapping[str, Any], *, force: bool) -> bool:
    return str(candidate.get("resume_status", "")).strip() in {"running", "running_stale"} and not force


def resume_candidate_requires_reply(candidate: Mapping[str, Any]) -> bool:
    return str(candidate.get("resume_status", "")).strip() == "awaiting_user_input"


def build_resume_state_overrides(
    candidate: Mapping[str, Any],
    *,
    branch: bool,
    working_directory: str,
    incoming_channel: str,
    incoming_workspace_id: str,
    incoming_sender_id: str,
    incoming_chat_id: str,
    incoming_is_group: bool,
) -> ResumeStateOverrides:
    overrides: ResumeStateOverrides = {
        "working_directory": working_directory,
        "resume_checkpoint_payload": dict(candidate.get("checkpoint", {}) or {}),
        "resume_mode": "branch" if branch else "resume",
        "parent_run_id": str(candidate.get("run_id", "") or ""),
        "incoming_channel": incoming_channel,
        "incoming_workspace_id": incoming_workspace_id,
        "incoming_sender_id": incoming_sender_id,
        "incoming_chat_id": incoming_chat_id,
        "incoming_is_group": incoming_is_group,
    }
    if branch:
        overrides["memory_force_new_session"] = True
    else:
        overrides["run_id"] = str(candidate.get("run_id", "") or "")
        overrides["session_id"] = str(candidate.get("session_id", "") or "")
        overrides["resume_output_dir"] = str(candidate.get("run_output_dir", "") or "")
        channel_session_key = str(candidate.get("channel_session_key", "") or "").strip()
        if channel_session_key:
            overrides["channel_session_key"] = channel_session_key
    return overrides
