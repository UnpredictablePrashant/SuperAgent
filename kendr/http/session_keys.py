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


def normalize_incoming_message(
    payload: Mapping[str, Any] | None = None,
    *,
    channel: str = "",
    sender_id: str = "",
    chat_id: str = "",
    workspace_id: str = "",
    text: str = "",
    is_group: bool | None = None,
    mentions_assistant: bool | None = None,
    gateway_trigger_tag: str = "@assistant",
    force_activate: bool = False,
) -> dict[str, Any]:
    raw = payload if isinstance(payload, Mapping) else {}
    resolved_channel = normalize_channel(str(channel or raw.get("channel") or "webchat"))
    resolved_sender = str(sender_id or raw.get("sender_id") or raw.get("from") or "")
    resolved_chat = str(chat_id or raw.get("chat_id") or raw.get("thread_id") or resolved_sender)
    resolved_workspace = str(workspace_id or raw.get("workspace_id") or "")
    resolved_text = str(text or raw.get("text") or raw.get("message") or "")
    resolved_group = bool(raw.get("is_group", False)) if is_group is None else bool(is_group)
    mention_token = str(gateway_trigger_tag or "@assistant").strip().lower()
    resolved_mentions = (
        bool(mentions_assistant)
        if mentions_assistant is not None
        else bool(mention_token and mention_token in resolved_text.lower())
    )
    should_activate = (not resolved_group) or resolved_mentions or bool(force_activate)
    if not resolved_group:
        activation_reason = "direct message"
    elif resolved_mentions:
        activation_reason = "assistant mentioned in group chat"
    elif force_activate:
        activation_reason = "forced activation override"
    else:
        activation_reason = "group message without assistant mention"
    return {
        "channel": resolved_channel,
        "sender_id": resolved_sender,
        "chat_id": resolved_chat,
        "workspace_id": resolved_workspace,
        "text": resolved_text,
        "is_group": resolved_group,
        "mentioned": resolved_mentions,
        "should_activate": should_activate,
        "activation_reason": activation_reason,
    }


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
