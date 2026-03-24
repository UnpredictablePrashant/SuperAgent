from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path


DEFAULT_WORKSPACE_DIR = os.getenv("SUPERAGENT_MEMORY_WORKSPACE", os.path.join("output", "workspace_memory"))


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _today_utc() -> str:
    return datetime.now(UTC).date().isoformat()


def _yesterday_utc() -> str:
    return (datetime.now(UTC).date() - timedelta(days=1)).isoformat()


def _safe_slug(value: str, default: str = "unknown") -> str:
    slug = re.sub(r"[^a-zA-Z0-9._-]+", "_", (value or "").strip())
    return slug[:96] if slug else default


def _read_text(path: Path, fallback: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return fallback


def _write_if_missing(path: Path, content: str) -> None:
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _append(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(content)


def _session_scope(state: dict) -> str:
    if state.get("incoming_is_group"):
        return "group"
    return "main"


def _derive_agent_identity(state: dict) -> str:
    channel = _safe_slug(str(state.get("incoming_channel") or "local"), "local")
    workspace_id = _safe_slug(str(state.get("incoming_workspace_id") or "default"), "default")
    sender_id = _safe_slug(str(state.get("incoming_sender_id") or "unknown"), "unknown")
    scope = _session_scope(state)
    return f"{channel}__{workspace_id}__{sender_id}__{scope}"


def _template_agent_md() -> str:
    return """# Agent.md

## Purpose
Operational policy for this agent workspace.

## Session Start Checklist
1. Read `soul.md`.
2. Read `IDENTITY.md` and `TOOLS.md`.
3. Read `memory/YYYY-MM-DD.md` for today and yesterday.
4. Read `memory.md` and `USER.md` only in direct/main sessions.
5. Read session snapshot in `sessions/<session_id>/session.md`.

## Memory Rules
- Write durable decisions to `memory.md`.
- Write execution notes to `memory/YYYY-MM-DD.md`.
- Keep secrets out of memory files unless explicitly requested.
"""


def _template_soul_md() -> str:
    return """# soul.md

## Identity
Pragmatic multi-agent operator focused on correctness, traceability, and safe execution.

## Behavior
- Make decisions explicit.
- Preserve context in files, not transient state only.
- Prefer small, verifiable updates.
"""


def _template_user_md() -> str:
    return """# USER.md

## User Profile
- Preferred response style:
- Constraints:
- Repeated priorities:

## Important Preferences
- 
"""


def _template_identity_md() -> str:
    return """# IDENTITY.md

## Agent Identity
- role: multi-agent runtime worker
- responsibility: orchestrate and execute delegated tasks safely
- security posture: least privilege
"""


def _template_tools_md() -> str:
    return """# TOOLS.md

## Tooling Conventions
- Use deterministic tools first.
- Persist significant actions in memory files.
- Prefer auditable outputs and summaries.
"""


def _template_heartbeat_md() -> str:
    return """# HEARTBEAT.md

## Maintenance Tasks
- Check session status and stale sessions.
- Compact recent daily notes into long-term memory.
- Record maintenance outcomes in memory files.
"""


def _template_memory_md() -> str:
    return """# memory.md

## Long-term Memory
Durable preferences, stable constraints, and recurring decisions belong here.

"""


def _template_session_md() -> str:
    return """# session.md

## Current Session
- status: initialized
- run_id:
- session_id:
- started_at:
- last_update_at:
- active_agent:
- objective:

## Last Event
- 
"""


def _template_planning_md() -> str:
    return """# planning.md

## Planning Status
- status: not_started
- updated_at:
- objective:

## Clarifications Needed
- none

## Step Plan
- none

## Execution Log
- none
"""


def _context_block(title: str, content: str, limit: int = 1800) -> str:
    cleaned = (content or "").strip()
    if len(cleaned) > limit:
        cleaned = cleaned[: limit - 3] + "..."
    return f"[{title}]\n{cleaned}" if cleaned else f"[{title}]"


def bootstrap_file_memory(state: dict) -> dict:
    workspace = Path(state.get("memory_workspace_dir") or DEFAULT_WORKSPACE_DIR).resolve()
    scope = _session_scope(state)
    agent_identity = _safe_slug(state.get("memory_agent_id") or _derive_agent_identity(state), "agent")
    session_identity = _safe_slug(state.get("session_id") or state.get("run_id") or f"session_{_today_utc()}", "session")

    agent_dir = workspace / "agents" / agent_identity
    memory_dir = agent_dir / "memory"
    session_dir = agent_dir / "sessions" / session_identity

    today_file = memory_dir / f"{_today_utc()}.md"
    yesterday_file = memory_dir / f"{_yesterday_utc()}.md"

    agent_md = agent_dir / "Agent.md"
    soul_md = agent_dir / "soul.md"
    user_md = agent_dir / "USER.md"
    identity_md = agent_dir / "IDENTITY.md"
    tools_md = agent_dir / "TOOLS.md"
    heartbeat_md = agent_dir / "HEARTBEAT.md"
    memory_md = agent_dir / "memory.md"
    session_md = session_dir / "session.md"
    session_events_md = session_dir / "events.md"
    session_summary_md = session_dir / "summary.md"
    planning_md = session_dir / "planning.md"

    _write_if_missing(agent_md, _template_agent_md())
    _write_if_missing(soul_md, _template_soul_md())
    _write_if_missing(user_md, _template_user_md())
    _write_if_missing(identity_md, _template_identity_md())
    _write_if_missing(tools_md, _template_tools_md())
    _write_if_missing(heartbeat_md, _template_heartbeat_md())
    _write_if_missing(memory_md, _template_memory_md())
    _write_if_missing(session_md, _template_session_md())
    _write_if_missing(session_events_md, f"# events.md\n\n")
    _write_if_missing(session_summary_md, "# summary.md\n\n")
    _write_if_missing(planning_md, _template_planning_md())
    _write_if_missing(today_file, f"# {_today_utc()}\n\n")

    context_parts = [
        _context_block("soul", _read_text(soul_md), 1200),
        _context_block("agent", _read_text(agent_md), 1200),
        _context_block("identity", _read_text(identity_md), 900),
        _context_block("tools", _read_text(tools_md), 900),
        _context_block("heartbeat", _read_text(heartbeat_md), 900),
        _context_block("yesterday", _read_text(yesterday_file) if yesterday_file.exists() else "", 1200),
        _context_block("today", _read_text(today_file), 1200),
    ]

    if scope == "main":
        context_parts.append(_context_block("user", _read_text(user_md), 1400))
        context_parts.append(_context_block("memory", _read_text(memory_md), 2200))
    else:
        context_parts.append("[user]\n(skipped in group session)")
        context_parts.append("[memory]\n(skipped in group session)")

    state["memory_workspace_dir"] = str(workspace)
    state["memory_agent_id"] = agent_identity
    state["memory_agent_dir"] = str(agent_dir)
    state["memory_session_dir"] = str(session_dir)
    state["memory_agent_file"] = str(agent_md)
    state["memory_soul_file"] = str(soul_md)
    state["memory_user_file"] = str(user_md)
    state["memory_identity_file"] = str(identity_md)
    state["memory_tools_file"] = str(tools_md)
    state["memory_heartbeat_file"] = str(heartbeat_md)
    state["memory_long_term_file"] = str(memory_md)
    state["memory_daily_file"] = str(today_file)
    state["memory_session_file"] = str(session_md)
    state["memory_session_events_file"] = str(session_events_md)
    state["memory_session_summary_file"] = str(session_summary_md)
    state["memory_planning_file"] = str(planning_md)
    state["memory_session_scope"] = scope
    state["file_memory_context"] = "\n\n".join(part for part in context_parts if part)

    return state


def append_daily_memory_note(state: dict, actor: str, title: str, detail: str) -> None:
    daily_path = Path(state.get("memory_daily_file") or "")
    if not str(daily_path):
        return
    timestamp = _now_iso()
    entry = (
        f"\n## {timestamp} | {actor} | {title}\n"
        f"run_id: {state.get('run_id', '')}\n"
        f"session_id: {state.get('session_id', '')}\n\n"
        f"{(detail or '').strip()}\n"
    )
    _append(daily_path, entry)


def append_session_event(state: dict, actor: str, event: str, detail: str = "") -> None:
    events_path = Path(state.get("memory_session_events_file") or "")
    if not str(events_path):
        return
    ts = _now_iso()
    payload = f"\n## {ts} | {actor} | {event}\n{(detail or '').strip()}\n"
    _append(events_path, payload)


def update_session_file(
    state: dict,
    *,
    status: str,
    active_agent: str = "",
    note: str = "",
) -> None:
    session_path = Path(state.get("memory_session_file") or "")
    if not str(session_path):
        return

    lines = [
        "# session.md",
        "",
        "## Current Session",
        f"- status: {status}",
        f"- run_id: {state.get('run_id', '')}",
        f"- session_id: {state.get('session_id', '')}",
        f"- started_at: {state.get('session_started_at', state.get('started_at', ''))}",
        f"- last_update_at: {_now_iso()}",
        f"- active_agent: {active_agent or state.get('last_agent', '')}",
        f"- objective: {state.get('current_objective', state.get('user_query', ''))}",
        "",
        "## Last Event",
        f"- {(note or 'none').strip()}",
    ]
    session_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def append_long_term_memory(state: dict, title: str, detail: str) -> None:
    if state.get("memory_session_scope") != "main":
        return
    memory_path = Path(state.get("memory_long_term_file") or "")
    if not str(memory_path):
        return
    timestamp = _now_iso()
    entry = f"\n## {timestamp} | {title}\n{(detail or '').strip()}\n"
    _append(memory_path, entry)


def close_session_memory(state: dict, *, status: str, final_output: str = "") -> None:
    summary_path = Path(state.get("memory_session_summary_file") or "")
    if not str(summary_path):
        return
    summary = (
        f"# summary.md\n\n"
        f"- status: {status}\n"
        f"- run_id: {state.get('run_id', '')}\n"
        f"- session_id: {state.get('session_id', '')}\n"
        f"- completed_at: {_now_iso()}\n"
        f"- last_agent: {state.get('last_agent', '')}\n"
        f"- objective: {state.get('current_objective', state.get('user_query', ''))}\n\n"
        f"## Final Output\n\n{(final_output or state.get('final_output', '') or state.get('draft_response', '')).strip()}\n"
    )
    summary_path.write_text(summary, encoding="utf-8")
    append_session_event(state, "system", "session_closed", f"status={status}")


def update_planning_file(
    state: dict,
    *,
    status: str,
    objective: str,
    plan_text: str,
    clarifications: list[str] | None = None,
    execution_note: str = "",
) -> None:
    planning_path = Path(state.get("memory_planning_file") or "")
    if not str(planning_path):
        return

    questions = [item.strip() for item in (clarifications or []) if str(item or "").strip()]
    clarification_block = "\n".join(f"- {item}" for item in questions) if questions else "- none"
    execution_block = f"- {execution_note.strip()}" if execution_note.strip() else "- none"
    payload = (
        "# planning.md\n\n"
        "## Planning Status\n"
        f"- status: {status}\n"
        f"- updated_at: {_now_iso()}\n"
        f"- objective: {objective}\n\n"
        "## Clarifications Needed\n"
        f"{clarification_block}\n\n"
        "## Step Plan\n"
        f"{(plan_text or '').strip() or '- none'}\n\n"
        "## Execution Log\n"
        f"{execution_block}\n"
    )
    planning_path.write_text(payload, encoding="utf-8")


def _collect_recent_daily_entries(memory_dir: Path, max_files: int = 5) -> list[str]:
    files = sorted(memory_dir.glob("*.md"), reverse=True)[:max_files]
    entries: list[str] = []
    for path in files:
        text = _read_text(path)
        for line in text.splitlines():
            if line.startswith("## "):
                entries.append(f"{path.name}: {line[3:].strip()}")
            if len(entries) >= 40:
                return entries
    return entries


def run_memory_maintenance(state: dict, *, force: bool = False) -> dict:
    if not state.get("memory_agent_dir"):
        state = bootstrap_file_memory(state)

    memory_dir = Path(state.get("memory_agent_dir", "")) / "memory"
    entries = _collect_recent_daily_entries(memory_dir)
    if not entries:
        return {"compacted": False, "reason": "no_daily_entries"}

    if not force and len(entries) < int(state.get("memory_compaction_min_entries", 10)):
        return {"compacted": False, "reason": "below_threshold", "entries": len(entries)}

    summary_lines = "\n".join(f"- {item}" for item in entries[:20])
    summary = (
        "Compacted recent daily memory events.\n"
        f"Session scope: {state.get('memory_session_scope', '')}\n"
        "Recent notable events:\n"
        f"{summary_lines}"
    )

    append_long_term_memory(state, "Memory Compaction", summary)
    append_session_event(state, "heartbeat_agent", "memory_compaction", summary)
    append_daily_memory_note(state, "heartbeat_agent", "memory_compaction", summary)

    return {"compacted": True, "entries": len(entries), "summary": summary}
