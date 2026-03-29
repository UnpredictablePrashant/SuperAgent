from __future__ import annotations

import time
from typing import Any, Mapping


def normalize_channel(value: str) -> str:
    channel = (value or "webchat").strip().lower()
    aliases = {
        "ms_teams": "teams",
        "microsoft_teams": "teams",
        "web": "webchat",
    }
    return aliases.get(channel, channel)


def session_id_for_payload(payload: Mapping[str, Any], *, force_new: bool = False) -> str:
    channel = normalize_channel(str(payload.get("channel", "webchat")))
    workspace_id = str(payload.get("workspace_id", "") or "default")
    sender_id = str(payload.get("sender_id", "") or "")
    chat_id = str(payload.get("chat_id", "") or sender_id or "unknown")
    scope = "group" if bool(payload.get("is_group", False)) else "main"
    base = ":".join([channel, workspace_id, chat_id, scope])
    if force_new:
        return f"{base}:{int(time.time())}"
    return base
