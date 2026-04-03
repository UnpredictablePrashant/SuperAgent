from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def duration_label(duration_ms: int | None) -> str:
    if duration_ms is None or duration_ms < 0:
        return ""
    if duration_ms < 1000:
        return f"{duration_ms} ms"
    seconds = duration_ms / 1000.0
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{round(seconds)}s"
    minutes, remainder = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes}m {remainder}s"
    hours, minute_remainder = divmod(minutes, 60)
    return f"{hours}h {minute_remainder}m"


def _truncate(value: Any, limit: int = 240) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 3)].rstrip() + "..."


def _coerce_duration_ms(
    *,
    duration_ms: int | None = None,
    started_at: str = "",
    completed_at: str = "",
) -> int | None:
    if duration_ms is not None:
        try:
            return max(0, int(duration_ms))
        except Exception:
            return None
    if not started_at or not completed_at:
        return None
    try:
        started = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
        completed = datetime.fromisoformat(completed_at.replace("Z", "+00:00"))
    except Exception:
        return None
    return max(0, int((completed - started).total_seconds() * 1000))


def _task_session_summary(session: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(session, dict):
        return {}
    summary = session.get("summary")
    if isinstance(summary, dict):
        return dict(summary)
    raw_summary = session.get("summary_json")
    if isinstance(raw_summary, str) and raw_summary.strip():
        try:
            decoded = json.loads(raw_summary)
        except Exception:
            return {}
        if isinstance(decoded, dict):
            return decoded
    return {}


def _persist_trace_snapshot(state: dict[str, Any], *, active_agent: str = "") -> None:
    session_id = str(state.get("session_id", "")).strip()
    run_id = str(state.get("run_id", "")).strip()
    if not session_id or not run_id:
        return
    try:
        from kendr.persistence import get_task_session_by_run, upsert_task_session
    except Exception:
        return

    existing = get_task_session_by_run(run_id) or {}
    summary = _task_session_summary(existing)
    plan_steps = state.get("plan_steps")
    if isinstance(plan_steps, list):
        summary["plan_steps"] = plan_steps
    summary.update(
        {
            "objective": state.get("current_objective", state.get("user_query", "")),
            "active_task": state.get("active_agent_task", state.get("active_task_summary", "")),
            "last_agent": state.get("last_agent", ""),
            "last_status": state.get("last_agent_status", ""),
            "last_error": state.get("last_error", ""),
            "pending_user_input_kind": state.get("pending_user_input_kind", ""),
            "approval_pending_scope": state.get("approval_pending_scope", ""),
            "pending_user_question": state.get("pending_user_question", ""),
            "plan_step_index": int(state.get("plan_step_index", 0) or 0),
            "plan_step_total": len(plan_steps) if isinstance(plan_steps, list) else int(summary.get("plan_step_total", 0) or 0),
            "execution_trace": state.get("execution_trace", []),
        }
    )
    payload = {
        "session_id": session_id,
        "run_id": run_id,
        "channel": state.get("incoming_channel", ""),
        "session_key": state.get("channel_session_key", ""),
        "started_at": state.get("session_started_at", state.get("started_at", "")),
        "updated_at": now_iso(),
        "completed_at": "",
        "status": str(existing.get("status", "") or "running"),
        "active_agent": active_agent or state.get("last_agent", ""),
        "step_count": max(
            int(existing.get("step_count", 0) or 0),
            len(state.get("agent_history", []) or []),
            int(state.get("effective_steps", 0) or 0),
        ),
        "summary": summary,
    }
    upsert_task_session(payload)


def append_execution_event(
    state: dict[str, Any],
    *,
    kind: str,
    actor: str,
    status: str,
    title: str,
    detail: str = "",
    command: str = "",
    cwd: str = "",
    started_at: str = "",
    completed_at: str = "",
    duration_ms: int | None = None,
    exit_code: int | None = None,
    metadata: dict[str, Any] | None = None,
    persist: bool = False,
    active_agent: str = "",
    task: str = "",
    subtask: str = "",
) -> dict[str, Any]:
    timestamp = completed_at or started_at or now_iso()
    resolved_duration = _coerce_duration_ms(
        duration_ms=duration_ms,
        started_at=started_at,
        completed_at=completed_at,
    )
    resolved_task = " ".join(
        str(task or state.get("current_objective") or state.get("user_query") or "").split()
    )
    resolved_subtask = " ".join(
        str(subtask or state.get("active_agent_task") or state.get("active_task_summary") or "").split()
    )
    event = {
        "id": f"trace-{uuid.uuid4().hex[:10]}",
        "timestamp": timestamp,
        "kind": str(kind or "activity"),
        "actor": str(actor or "system"),
        "status": str(status or "info"),
        "title": str(title or "Activity"),
        "detail": str(detail or "").strip(),
        "command": str(command or "").strip(),
        "cwd": str(cwd or "").strip(),
        "started_at": str(started_at or "").strip(),
        "completed_at": str(completed_at or "").strip(),
        "duration_ms": resolved_duration,
        "duration_label": duration_label(resolved_duration),
        "exit_code": exit_code,
        "task": resolved_task,
        "subtask": resolved_subtask,
        "metadata": metadata or {},
    }
    recent = state.get("execution_trace", [])
    if not isinstance(recent, list):
        recent = []
    recent.append(event)
    state["execution_trace"] = recent[-40:]
    state["last_execution_event"] = event
    if persist:
        try:
            _persist_trace_snapshot(state, active_agent=active_agent or actor)
        except Exception:
            pass
    return event


def render_execution_event_line(event: dict[str, Any]) -> str:
    if not isinstance(event, dict):
        return ""
    timestamp = str(event.get("timestamp", "")).strip()
    clock = ""
    if timestamp:
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
            clock = dt.astimezone().strftime("%H:%M:%S")
        except Exception:
            clock = timestamp
    head_parts = [part for part in [clock, str(event.get("actor", "")).strip(), str(event.get("title", "")).strip()] if part]
    tail_parts: list[str] = []
    command = _truncate(event.get("command", ""), limit=90)
    if command:
        tail_parts.append(command)
    detail = _truncate(event.get("detail", ""), limit=120)
    if detail and detail != command:
        tail_parts.append(detail)
    duration = str(event.get("duration_label", "")).strip()
    if duration:
        tail_parts.append(duration)
    exit_code = event.get("exit_code")
    if exit_code not in ("", None):
        tail_parts.append(f"exit {exit_code}")
    head = " · ".join(head_parts)
    tail = " · ".join(part for part in tail_parts if part)
    return " | ".join(part for part in [head, tail] if part)
