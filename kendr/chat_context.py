from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path


def estimate_token_count(text: str) -> int:
    raw = str(text or "")
    if not raw:
        return 0
    return max(1, (len(raw) + 3) // 4)


def summary_storage_root() -> Path:
    raw = str(os.getenv("KENDR_HOME", "")).strip()
    root = Path(raw).expanduser() if raw else (Path.home() / ".kendr")
    path = root / "chat_context"
    path.mkdir(parents=True, exist_ok=True)
    return path


def summary_file_path(session_key: str) -> Path:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", str(session_key or "").strip()).strip("._-") or "default"
    return summary_storage_root() / safe / "summary.md"


def normalize_chat_messages(messages: list[dict] | None, *, limit: int = 200) -> list[dict]:
    normalized: list[dict] = []
    for raw in messages or []:
        if not isinstance(raw, dict):
            continue
        role = str(raw.get("role") or "").strip().lower()
        if role == "agent":
            role = "assistant"
        if role not in {"user", "assistant"}:
            continue
        content = str(raw.get("content") or raw.get("text") or "").strip()
        if not content:
            continue
        normalized.append({
            "role": role,
            "content": content,
            "created_at": str(raw.get("created_at") or raw.get("timestamp") or "").strip(),
        })
    return normalized[-max(1, int(limit or 200)):]


def build_chat_summary_markdown(
    messages: list[dict] | None,
    *,
    requested_level: int = 0,
    max_tokens: int = 2048,
    recent_keep: int = 8,
) -> tuple[str, int]:
    normalized = normalize_chat_messages(messages)
    if not normalized:
        summary = "# summary.md\n\n- No prior conversation summarized yet.\n"
        return summary, 0

    older = normalized[:-max(1, int(recent_keep or 8))]
    last_user = next((m["content"] for m in reversed(normalized) if m["role"] == "user"), "")
    last_assistant = next((m["content"] for m in reversed(normalized) if m["role"] == "assistant"), "")
    level = max(0, int(requested_level or 0))

    while True:
        summary = _render_summary(older, last_user, last_assistant, level)
        if estimate_token_count(summary) <= max(256, int(max_tokens or 2048)) or level >= 4:
            return summary, level
        level += 1


def build_chat_context_block(summary_text: str, messages: list[dict] | None, *, recent_limit: int = 8) -> str:
    parts: list[str] = []
    text = str(summary_text or "").strip()
    if text:
        parts.append("Summary file context:\n" + text)
    recent = normalize_chat_messages(messages)[-max(1, int(recent_limit or 8)):]
    if recent:
        lines = [f"- {item['role']}: {_truncate(item['content'], 240)}" for item in recent]
        parts.append("Recent raw turns:\n" + "\n".join(lines))
    return "\n\n".join(parts).strip()


def _render_summary(older: list[dict], last_user: str, last_assistant: str, level: int) -> str:
    config = {
        0: {"items": 24, "chars": 220},
        1: {"items": 16, "chars": 160},
        2: {"items": 10, "chars": 110},
        3: {"items": 6, "chars": 80},
        4: {"items": 4, "chars": 60},
    }.get(level, {"items": 4, "chars": 60})
    lines = [
        "# summary.md",
        "",
        f"- Updated: {datetime.now(timezone.utc).isoformat()}",
        f"- Compaction level: {level}",
        f"- Older summarized turns: {len(older)}",
    ]
    if last_user:
        lines.append(f"- Latest user intent: {_truncate(last_user, 240)}")
    if last_assistant:
        lines.append(f"- Latest assistant state: {_truncate(last_assistant, 240)}")
    lines.extend(["", "## Earlier discussion", ""])
    if not older:
        lines.append("- No earlier discussion to summarize.")
    else:
        start = max(0, len(older) - config["items"])
        for item in older[start:]:
            lines.append(f"- {item['role']}: {_truncate(item['content'], config['chars'])}")
    lines.append("")
    return "\n".join(lines)


def _truncate(text: str, limit: int) -> str:
    raw = " ".join(str(text or "").split())
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 1)].rstrip() + "…"
