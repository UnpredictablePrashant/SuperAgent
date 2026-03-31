from __future__ import annotations

import concurrent.futures
import datetime as dt
import json
import os
import threading
from pathlib import Path
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from kendr.providers import get_google_access_token, get_microsoft_graph_access_token, get_slack_bot_token

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.research_infra import html_to_text, llm_text
from tasks.utils import OUTPUT_DIR, log_task_update, write_text_file


AGENT_METADATA = {
    "whatsapp_send_message_agent": {
        "description": (
            "Sends a WhatsApp message (plain text or template) via the Meta Graph API v18+. "
            "Requires WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID."
        ),
        "skills": ["whatsapp", "messaging", "meta-graph-api"],
        "input_keys": [
            "whatsapp_to",
            "whatsapp_message",
            "whatsapp_template_name",
            "whatsapp_template_language",
            "communication_authorized",
        ],
        "output_keys": ["whatsapp_send_result", "draft_response"],
        "requirements": ["openai", "whatsapp"],
    },
    "whatsapp_list_messages_agent": {
        "description": (
            "Lists recent WhatsApp Business inbox messages via the Meta Graph API v18+. "
            "Requires WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID."
        ),
        "skills": ["whatsapp", "messaging", "meta-graph-api"],
        "input_keys": [
            "whatsapp_max_messages",
            "communication_authorized",
        ],
        "output_keys": ["whatsapp_results", "draft_response"],
        "requirements": ["openai", "whatsapp"],
    },
    "communication_summary_agent": {
        "description": (
            "Queries all configured and authorized communication providers concurrently "
            "(Gmail, Slack, Microsoft Graph, Telegram, WhatsApp) and produces a unified "
            "digest sorted by timestamp. Useful as a morning briefing or status check."
        ),
        "skills": ["communication", "gmail", "slack", "telegram", "whatsapp", "microsoft-graph", "digest"],
        "input_keys": [
            "communication_lookback_hours",
            "communication_authorized",
            "communication_suites",
        ],
        "output_keys": ["communication_summary_report", "draft_response"],
        "requirements": ["openai"],
    },
}


def _write_outputs(agent_name: str, call_number: int, summary: str, payload: dict):
    write_text_file(f"{agent_name}_{call_number}.txt", summary)
    write_text_file(f"{agent_name}_{call_number}.json", json.dumps(payload, indent=2, ensure_ascii=False))


def _require_comm_authorization(state: dict):
    if not state.get("communication_authorized", False):
        raise PermissionError(
            "Communication agents require explicit authorization. Set state['communication_authorized']=True only for accounts and workspaces you are permitted to access."
        )


def _http_json(url: str, *, headers: dict | None = None, method: str = "GET", data: bytes | None = None, timeout: int = 30) -> dict:
    request = Request(url, headers=headers or {}, method=method, data=data)
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _run_telethon_sync(coro_factory, *args, **kwargs):
    """Run an async telethon coroutine in a dedicated thread with its own event loop.

    This avoids conflicts with any event loop that may already be running in the
    LangGraph sync executor thread.  The factory callable receives *args/**kwargs
    and must return an awaitable.
    """
    result_holder: list = []
    exc_holder: list = []

    def _thread_target():
        import asyncio
        loop = asyncio.new_event_loop()
        try:
            coro = coro_factory(*args, **kwargs)
            result_holder.append(loop.run_until_complete(coro))
        except Exception as exc:
            exc_holder.append(exc)
        finally:
            loop.close()

    thread = threading.Thread(target=_thread_target, daemon=True)
    thread.start()
    thread.join()
    if exc_holder:
        raise exc_holder[0]
    return result_holder[0] if result_holder else None


def communication_scope_guard_agent(state):
    _, task_content, _ = begin_agent_session(state, "communication_scope_guard_agent")
    state["communication_scope_guard_calls"] = state.get("communication_scope_guard_calls", 0) + 1
    call_number = state["communication_scope_guard_calls"]
    authorized = bool(state.get("communication_authorized", False))
    suites = state.get("communication_suites") or [
        name
        for name, configured in {
            "gmail": bool(get_google_access_token()),
            "drive": bool(get_google_access_token()),
            "telegram": bool(
                os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
                or (
                    os.getenv("TELEGRAM_SESSION_STRING", "").strip()
                    and os.getenv("TELEGRAM_API_ID", "").strip()
                    and os.getenv("TELEGRAM_API_HASH", "").strip()
                )
            ),
            "slack": bool(get_slack_bot_token()),
            "microsoft_graph": bool(get_microsoft_graph_access_token()),
            "whatsapp": bool(
                os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
                and os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
            ),
        }.items()
        if configured
    ]
    request_text = task_content or state.get("current_objective") or state.get("user_query", "")

    summary = (
        f"Authorized: {authorized}\n"
        f"Suites: {', '.join(suites)}\n"
        f"Policy: {'Access allowed for explicitly authorized suites.' if authorized else 'Access denied until authorization flag is provided.'}\n"
        f"Request: {request_text}"
    )
    payload = {
        "authorized": authorized,
        "suites": suites,
        "request": request_text,
        "decision": "allow" if authorized else "deny",
        "disallowed_actions": ["unauthorized account access", "credential misuse", "message sending without explicit instruction"],
    }
    _write_outputs("communication_scope_guard_agent", call_number, summary, payload)
    state["communication_scope_report"] = payload
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "communication_scope_guard_agent",
        summary,
        f"communication_scope_guard_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent"],
    )


def gmail_agent(state):
    _, task_content, _ = begin_agent_session(state, "gmail_agent")
    _require_comm_authorization(state)
    state["gmail_calls"] = state.get("gmail_calls", 0) + 1
    call_number = state["gmail_calls"]

    access_token = get_google_access_token()
    if not access_token:
        raise ValueError("GOOGLE_ACCESS_TOKEN is required for gmail_agent.")

    query = state.get("gmail_query") or task_content or "in:inbox"
    max_results = int(state.get("gmail_max_results", 10))
    headers = {"Authorization": f"Bearer {access_token}"}
    list_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages?" + urlencode({"q": query, "maxResults": max_results})
    listing = _http_json(list_url, headers=headers)

    messages = []
    for item in listing.get("messages", [])[:max_results]:
        msg = _http_json(
            f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{item['id']}?format=metadata&metadataHeaders=Subject&metadataHeaders=From&metadataHeaders=Date",
            headers=headers,
        )
        headers_map = {header["name"].lower(): header["value"] for header in msg.get("payload", {}).get("headers", [])}
        messages.append(
            {
                "id": msg.get("id"),
                "threadId": msg.get("threadId"),
                "snippet": msg.get("snippet", ""),
                "subject": headers_map.get("subject", ""),
                "from": headers_map.get("from", ""),
                "date": headers_map.get("date", ""),
                "labelIds": msg.get("labelIds", []),
            }
        )

    summary = llm_text(
        f"Summarize these Gmail messages and identify important threads, action items, and priorities:\n\n{json.dumps(messages, indent=2, ensure_ascii=False)}"
    )
    payload = {"query": query, "messages": messages}
    _write_outputs("gmail_agent", call_number, summary, payload)
    state["gmail_results"] = payload
    state["draft_response"] = summary
    log_task_update("Gmail", f"Gmail pass #{call_number} saved to {OUTPUT_DIR}/gmail_agent_{call_number}.txt")
    return publish_agent_output(
        state,
        "gmail_agent",
        summary,
        f"gmail_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def drive_agent(state):
    _, task_content, _ = begin_agent_session(state, "drive_agent")
    _require_comm_authorization(state)
    state["drive_calls"] = state.get("drive_calls", 0) + 1
    call_number = state["drive_calls"]

    access_token = get_google_access_token()
    if not access_token:
        raise ValueError("GOOGLE_ACCESS_TOKEN is required for drive_agent.")

    query = state.get("drive_query") or task_content or "starred = true"
    page_size = int(state.get("drive_page_size", 10))
    headers = {"Authorization": f"Bearer {access_token}"}
    url = "https://www.googleapis.com/drive/v3/files?" + urlencode(
        {
            "q": query,
            "pageSize": page_size,
            "fields": "files(id,name,mimeType,modifiedTime,owners(displayName),webViewLink)",
        }
    )
    listing = _http_json(url, headers=headers)
    files = listing.get("files", [])

    extracted = []
    for item in files[:page_size]:
        content_excerpt = ""
        if item.get("mimeType") == "application/vnd.google-apps.document":
            export_url = f"https://www.googleapis.com/drive/v3/files/{item['id']}/export?mimeType=text/plain"
            req = Request(export_url, headers=headers)
            with urlopen(req, timeout=30) as response:
                content_excerpt = response.read().decode("utf-8", errors="ignore")[:4000]
        extracted.append({**item, "content_excerpt": html_to_text(content_excerpt)[:4000] if content_excerpt else ""})

    summary = llm_text(
        f"Summarize these Drive files, important documents, and likely action-relevant materials:\n\n{json.dumps(extracted, indent=2, ensure_ascii=False)}"
    )
    payload = {"query": query, "files": extracted}
    _write_outputs("drive_agent", call_number, summary, payload)
    state["drive_results"] = payload
    state["draft_response"] = summary
    log_task_update("Drive", f"Drive pass #{call_number} saved to {OUTPUT_DIR}/drive_agent_{call_number}.txt")
    return publish_agent_output(
        state,
        "drive_agent",
        summary,
        f"drive_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def telegram_agent(state):
    _, task_content, _ = begin_agent_session(state, "telegram_agent")
    _require_comm_authorization(state)
    state["telegram_calls"] = state.get("telegram_calls", 0) + 1
    call_number = state["telegram_calls"]

    payload = {"mode": "", "messages": []}
    max_messages = int(state.get("telegram_max_messages", 20))

    session_string = os.getenv("TELEGRAM_SESSION_STRING")
    api_id = os.getenv("TELEGRAM_API_ID")
    api_hash = os.getenv("TELEGRAM_API_HASH")
    if session_string and api_id and api_hash:
        try:
            from telethon import TelegramClient
            from telethon.sessions import StringSession

            target = state.get("telegram_target") or task_content or "me"

            async def _collect():
                async with TelegramClient(StringSession(session_string), int(api_id), api_hash) as client:
                    messages = []
                    async for message in client.iter_messages(target, limit=max_messages):
                        messages.append(
                            {
                                "id": message.id,
                                "date": message.date.isoformat() if message.date else "",
                                "sender_id": getattr(message, "sender_id", None),
                                "text": (message.message or "")[:4000],
                            }
                        )
                    return messages

            payload["mode"] = "telethon_session"
            payload["messages"] = _run_telethon_sync(_collect)
        except Exception as exc:
            payload["telethon_error"] = str(exc)

    if not payload["messages"]:
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            raise ValueError(
                "telegram_agent requires either TELEGRAM_SESSION_STRING with TELEGRAM_API_ID/TELEGRAM_API_HASH, or TELEGRAM_BOT_TOKEN."
            )
        payload["mode"] = "bot_updates"
        updates = _http_json(f"https://api.telegram.org/bot{bot_token}/getUpdates")
        for item in updates.get("result", [])[-max_messages:]:
            message = item.get("message") or item.get("edited_message") or {}
            payload["messages"].append(
                {
                    "update_id": item.get("update_id"),
                    "chat_id": message.get("chat", {}).get("id"),
                    "date": message.get("date"),
                    "from": message.get("from", {}).get("username") or message.get("from", {}).get("id"),
                    "text": (message.get("text") or "")[:4000],
                }
            )

    summary = llm_text(
        f"Summarize these Telegram messages or updates and identify important threads, action items, and follow-ups:\n\n{json.dumps(payload, indent=2, ensure_ascii=False)}"
    )
    _write_outputs("telegram_agent", call_number, summary, payload)
    state["telegram_results"] = payload
    state["draft_response"] = summary
    log_task_update("Telegram", f"Telegram pass #{call_number} saved to {OUTPUT_DIR}/telegram_agent_{call_number}.txt")
    return publish_agent_output(
        state,
        "telegram_agent",
        summary,
        f"telegram_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def slack_agent(state):
    _, task_content, _ = begin_agent_session(state, "slack_agent")
    _require_comm_authorization(state)
    state["slack_calls"] = state.get("slack_calls", 0) + 1
    call_number = state["slack_calls"]

    token = get_slack_bot_token()
    if not token:
        raise ValueError("SLACK_BOT_TOKEN is required for slack_agent.")

    headers = {"Authorization": f"Bearer {token}"}
    channel = state.get("slack_channel") or task_content or ""
    if not channel:
        channels_payload = _http_json("https://slack.com/api/conversations.list?limit=20", headers=headers)
        payload = {"channels": channels_payload.get("channels", [])[:20]}
        summary = llm_text(f"Summarize these Slack channels and suggest which are likely most relevant:\n\n{json.dumps(payload, indent=2, ensure_ascii=False)}")
    else:
        history_payload = _http_json(
            "https://slack.com/api/conversations.history?" + urlencode({"channel": channel, "limit": int(state.get("slack_max_messages", 20))}),
            headers=headers,
        )
        payload = {"channel": channel, "messages": history_payload.get("messages", [])}
        summary = llm_text(f"Summarize these Slack messages and identify important decisions, blockers, and action items:\n\n{json.dumps(payload, indent=2, ensure_ascii=False)}")

    _write_outputs("slack_agent", call_number, summary, payload)
    state["slack_results"] = payload
    state["draft_response"] = summary
    log_task_update("Slack", f"Slack pass #{call_number} saved to {OUTPUT_DIR}/slack_agent_{call_number}.txt")
    return publish_agent_output(
        state,
        "slack_agent",
        summary,
        f"slack_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def microsoft_graph_agent(state):
    _, task_content, _ = begin_agent_session(state, "microsoft_graph_agent")
    _require_comm_authorization(state)
    state["microsoft_graph_calls"] = state.get("microsoft_graph_calls", 0) + 1
    call_number = state["microsoft_graph_calls"]

    access_token = get_microsoft_graph_access_token()
    if not access_token:
        raise ValueError("MICROSOFT_GRAPH_ACCESS_TOKEN is required for microsoft_graph_agent.")

    headers = {"Authorization": f"Bearer {access_token}"}
    mode = state.get("microsoft_graph_mode") or task_content or "mail"
    if mode == "drive":
        payload = _http_json("https://graph.microsoft.com/v1.0/me/drive/root/children?$top=10", headers=headers)
        summary = llm_text(f"Summarize these Microsoft Drive items and highlight important documents:\n\n{json.dumps(payload, indent=2, ensure_ascii=False)}")
    elif mode == "teams":
        payload = _http_json("https://graph.microsoft.com/v1.0/me/joinedTeams", headers=headers)
        summary = llm_text(f"Summarize these Microsoft Teams memberships and likely relevant collaboration spaces:\n\n{json.dumps(payload, indent=2, ensure_ascii=False)}")
    else:
        payload = _http_json("https://graph.microsoft.com/v1.0/me/messages?$top=10&$select=subject,from,receivedDateTime,bodyPreview", headers=headers)
        summary = llm_text(f"Summarize these Outlook messages and identify important priorities and action items:\n\n{json.dumps(payload, indent=2, ensure_ascii=False)}")

    _write_outputs("microsoft_graph_agent", call_number, summary, payload)
    state["microsoft_graph_results"] = payload
    state["draft_response"] = summary
    log_task_update("Microsoft Graph", f"Graph pass #{call_number} saved to {OUTPUT_DIR}/microsoft_graph_agent_{call_number}.txt")
    return publish_agent_output(
        state,
        "microsoft_graph_agent",
        summary,
        f"microsoft_graph_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def whatsapp_list_messages_agent(state):
    _, task_content, _ = begin_agent_session(state, "whatsapp_list_messages_agent")
    _require_comm_authorization(state)
    state["whatsapp_list_calls"] = state.get("whatsapp_list_calls", 0) + 1
    call_number = state["whatsapp_list_calls"]

    access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    if not access_token or not phone_number_id:
        raise ValueError("whatsapp_list_messages_agent requires WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID.")

    max_messages = int(state.get("whatsapp_max_messages", 20))
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages?" + urlencode({"limit": max_messages})
    response_data = _http_json(url, headers=headers)

    api_error = response_data.get("error")
    if api_error:
        error_msg = f"WhatsApp API error: {api_error}"
        payload = {
            "phone_number_id": phone_number_id,
            "status": "error",
            "error": api_error,
            "messages": [],
        }
        _write_outputs("whatsapp_list_messages_agent", call_number, error_msg, payload)
        state["whatsapp_results"] = payload
        state["draft_response"] = error_msg
        raise RuntimeError(error_msg)

    messages = response_data.get("data", response_data.get("messages", []))
    payload = {
        "phone_number_id": phone_number_id,
        "status": "ok",
        "messages": messages,
        "count": len(messages),
    }

    summary = llm_text(
        f"Summarize these WhatsApp Business messages and identify important conversations, action items, and follow-ups:\n\n{json.dumps(payload, indent=2, ensure_ascii=False)[:20000]}"
    )
    _write_outputs("whatsapp_list_messages_agent", call_number, summary, payload)
    state["whatsapp_results"] = payload
    state["draft_response"] = summary
    log_task_update("WhatsApp", f"WhatsApp list pass #{call_number} saved to {OUTPUT_DIR}/whatsapp_list_messages_agent_{call_number}.txt")
    return publish_agent_output(
        state,
        "whatsapp_list_messages_agent",
        summary,
        f"whatsapp_list_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent"],
    )


def whatsapp_send_message_agent(state):
    _, task_content, _ = begin_agent_session(state, "whatsapp_send_message_agent")
    _require_comm_authorization(state)
    state["whatsapp_send_calls"] = state.get("whatsapp_send_calls", 0) + 1
    call_number = state["whatsapp_send_calls"]

    access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    if not access_token or not phone_number_id:
        raise ValueError("whatsapp_send_message_agent requires WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID.")

    to = str(state.get("whatsapp_to") or "").strip()
    if not to:
        raise ValueError("whatsapp_send_message_agent requires state['whatsapp_to'] — the recipient phone number in E.164 format.")

    message_text = str(state.get("whatsapp_message") or task_content or "").strip()
    template_name = str(state.get("whatsapp_template_name") or "").strip()
    template_language = str(state.get("whatsapp_template_language") or "en_US").strip()

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"

    if template_name:
        body = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": template_language},
            },
        }
    elif message_text:
        body = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "text",
            "text": {"body": message_text},
        }
    else:
        raise ValueError("whatsapp_send_message_agent requires either state['whatsapp_message'] or state['whatsapp_template_name'].")

    data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    try:
        result = _http_json(url, headers=headers, method="POST", data=data)
    except Exception as exc:
        result = {"error": str(exc)}

    payload = {"to": to, "body": body, "result": result}
    success = "error" not in result
    summary = (
        f"WhatsApp message {'sent' if success else 'failed'} to {to}.\n"
        f"Type: {'template' if template_name else 'text'}\n"
        f"Result: {json.dumps(result, ensure_ascii=False)}"
    )
    _write_outputs("whatsapp_send_message_agent", call_number, summary, payload)
    state["whatsapp_send_result"] = payload
    state["draft_response"] = summary
    log_task_update("WhatsApp", f"WhatsApp send pass #{call_number} saved to {OUTPUT_DIR}/whatsapp_send_message_agent_{call_number}.txt")
    return publish_agent_output(
        state,
        "whatsapp_send_message_agent",
        summary,
        f"whatsapp_send_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent"],
    )


def _parse_timestamp(value) -> float:
    """Normalize a message timestamp to a UTC float (epoch seconds). Returns 0.0 on failure."""
    if not value:
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    s = str(value).strip()
    if not s:
        return 0.0
    try:
        return float(s)
    except ValueError:
        pass
    for fmt in ("%a, %d %b %Y %H:%M:%S %z", "%a, %d %b %Y %H:%M:%S %Z", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            parsed = dt.datetime.strptime(s[:31], fmt)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=dt.timezone.utc)
            return parsed.timestamp()
        except ValueError:
            continue
    try:
        import email.utils
        tup = email.utils.parsedate_to_datetime(s)
        return tup.timestamp()
    except Exception:
        pass
    return 0.0


def _normalize_message(channel: str, raw: dict) -> dict:
    """Convert a channel-specific message dict into a common envelope for cross-channel sorting."""
    subject = raw.get("subject", "")
    sender = raw.get("from", "") or raw.get("user", "") or str(raw.get("sender_id", ""))
    text = raw.get("snippet") or raw.get("preview") or raw.get("text") or raw.get("bodyPreview") or ""
    ts_raw = (
        raw.get("ts")
        or raw.get("date")
        or raw.get("receivedDateTime")
        or raw.get("timestamp")
        or 0
    )
    ts = _parse_timestamp(ts_raw)
    return {
        "channel": channel,
        "subject": subject,
        "sender": sender,
        "preview": (text or "")[:300],
        "timestamp": ts,
        "timestamp_iso": dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc).isoformat() if ts else "",
        "_raw": raw,
    }


def communication_summary_agent(state):
    _, task_content, _ = begin_agent_session(state, "communication_summary_agent")
    _require_comm_authorization(state)
    state["communication_summary_calls"] = state.get("communication_summary_calls", 0) + 1
    call_number = state["communication_summary_calls"]

    lookback_hours = int(state.get("communication_lookback_hours", 24))
    cutoff_ts = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=lookback_hours)
    cutoff_epoch = cutoff_ts.timestamp()

    configured_suites = list(state.get("communication_suites") or [])
    if not configured_suites:
        if get_google_access_token():
            configured_suites.append("gmail")
        if get_slack_bot_token():
            configured_suites.append("slack")
        if get_microsoft_graph_access_token():
            configured_suites.append("microsoft_graph")
        if os.getenv("TELEGRAM_BOT_TOKEN", "").strip() or (
            os.getenv("TELEGRAM_SESSION_STRING", "").strip()
            and os.getenv("TELEGRAM_API_ID", "").strip()
            and os.getenv("TELEGRAM_API_HASH", "").strip()
        ):
            configured_suites.append("telegram")
        if os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip() and os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip():
            configured_suites.append("whatsapp")

    provider_status: dict[str, str] = {}
    channel_results: dict[str, list[dict]] = {}
    errors: dict[str, str] = {}

    def _fetch_gmail():
        access_token = get_google_access_token()
        if not access_token:
            return []
        headers = {"Authorization": f"Bearer {access_token}"}
        list_url = "https://gmail.googleapis.com/gmail/v1/users/me/messages?" + urlencode({
            "q": f"in:inbox after:{int(cutoff_epoch)}",
            "maxResults": 20,
        })
        listing = _http_json(list_url, headers=headers)
        messages = []
        for item in listing.get("messages", [])[:20]:
            try:
                msg = _http_json(
                    f"https://gmail.googleapis.com/gmail/v1/users/me/messages/{item['id']}?format=metadata"
                    "&metadataHeaders=Subject&metadataHeaders=From&metadataHeaders=Date",
                    headers=headers,
                )
                hdrs = {h["name"].lower(): h["value"] for h in msg.get("payload", {}).get("headers", [])}
                messages.append({
                    "subject": hdrs.get("subject", ""),
                    "from": hdrs.get("from", ""),
                    "date": hdrs.get("date", ""),
                    "snippet": msg.get("snippet", ""),
                })
            except Exception:
                pass
        return messages

    def _fetch_slack():
        token = get_slack_bot_token()
        if not token:
            return []
        headers = {"Authorization": f"Bearer {token}"}
        channels_payload = _http_json("https://slack.com/api/conversations.list?limit=10", headers=headers)
        messages = []
        oldest = str(cutoff_epoch)
        for ch in channels_payload.get("channels", [])[:5]:
            try:
                hist = _http_json(
                    "https://slack.com/api/conversations.history?" + urlencode({"channel": ch["id"], "limit": 10, "oldest": oldest}),
                    headers=headers,
                )
                for msg in hist.get("messages", []):
                    messages.append({
                        "from": msg.get("user", ""),
                        "text": (msg.get("text") or "")[:500],
                        "ts": msg.get("ts", ""),
                        "channel_name": ch.get("name", ""),
                    })
            except Exception:
                pass
        return messages

    def _fetch_microsoft_graph():
        access_token = get_microsoft_graph_access_token()
        if not access_token:
            return []
        headers = {"Authorization": f"Bearer {access_token}"}
        filter_str = f"receivedDateTime ge {cutoff_ts.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        url = (
            f"https://graph.microsoft.com/v1.0/me/messages"
            f"?$top=20&$select=subject,from,receivedDateTime,bodyPreview&$filter={quote(filter_str)}"
        )
        payload = _http_json(url, headers=headers)
        messages = []
        for item in payload.get("value", []):
            messages.append({
                "subject": item.get("subject", ""),
                "from": (item.get("from") or {}).get("emailAddress", {}).get("address", ""),
                "date": item.get("receivedDateTime", ""),
                "preview": (item.get("bodyPreview") or "")[:300],
            })
        return messages

    def _fetch_telegram():
        session_string = os.getenv("TELEGRAM_SESSION_STRING", "").strip()
        api_id = os.getenv("TELEGRAM_API_ID", "").strip()
        api_hash = os.getenv("TELEGRAM_API_HASH", "").strip()
        bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()

        if session_string and api_id and api_hash:
            try:
                from telethon import TelegramClient
                from telethon.sessions import StringSession

                async def _collect_telethon():
                    messages = []
                    async with TelegramClient(StringSession(session_string), int(api_id), api_hash) as client:
                        async for dialog in client.iter_dialogs():
                            async for message in client.iter_messages(dialog, limit=10):
                                if not message.date:
                                    continue
                                msg_ts = message.date.timestamp()
                                if msg_ts < cutoff_epoch:
                                    break
                                messages.append({
                                    "from": str(getattr(message, "sender_id", "")),
                                    "text": (message.message or "")[:500],
                                    "date": msg_ts,
                                    "dialog": dialog.name or "",
                                })
                            if len(messages) >= 40:
                                break
                    return messages

                return _run_telethon_sync(_collect_telethon)
            except Exception as exc:
                if not bot_token:
                    raise RuntimeError(f"telegram session: {exc}") from exc

        if bot_token:
            updates = _http_json(f"https://api.telegram.org/bot{bot_token}/getUpdates")
            messages = []
            for item in updates.get("result", []):
                message = item.get("message") or item.get("edited_message") or {}
                ts = float(message.get("date", 0) or 0)
                if ts and ts < cutoff_epoch:
                    continue
                messages.append({
                    "from": message.get("from", {}).get("username") or str(message.get("from", {}).get("id", "")),
                    "text": (message.get("text") or "")[:500],
                    "date": ts,
                    "chat_id": message.get("chat", {}).get("id"),
                })
            return messages

        return []

    def _fetch_whatsapp():
        access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
        phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
        if not access_token or not phone_number_id:
            return []
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }
        url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages?" + urlencode({"limit": 20})
        response_data = _http_json(url, headers=headers)
        api_error = response_data.get("error")
        if api_error:
            raise RuntimeError(f"WhatsApp API error: {api_error}")
        return list(response_data.get("data", response_data.get("messages", [])))[:20]

    fetcher_map = {
        "gmail": _fetch_gmail,
        "slack": _fetch_slack,
        "microsoft_graph": _fetch_microsoft_graph,
        "telegram": _fetch_telegram,
        "whatsapp": _fetch_whatsapp,
    }

    active_fetchers = {suite: fetcher_map[suite] for suite in configured_suites if suite in fetcher_map}

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(active_fetchers))) as executor:
        future_map = {executor.submit(fn): suite for suite, fn in active_fetchers.items()}
        for future in concurrent.futures.as_completed(future_map):
            suite = future_map[future]
            try:
                raw_list = future.result()
                if raw_list is not None:
                    channel_results[suite] = [_normalize_message(suite, m) for m in raw_list]
                    provider_status[suite] = "ok"
            except Exception as exc:
                errors[suite] = str(exc)
                provider_status[suite] = f"error: {exc}"

    all_messages: list[dict] = []
    for suite, msgs in channel_results.items():
        for m in msgs:
            ts = m.get("timestamp", 0)
            if ts == 0 or ts >= cutoff_epoch:
                all_messages.append(m)

    all_messages.sort(key=lambda m: m.get("timestamp", 0), reverse=True)

    per_channel_section: dict[str, list[dict]] = {}
    for msg in all_messages:
        per_channel_section.setdefault(msg["channel"], []).append(msg)

    sections = []
    for suite in ["gmail", "slack", "microsoft_graph", "telegram", "whatsapp"]:
        if suite not in per_channel_section:
            continue
        msgs = per_channel_section[suite]
        section_lines = [f"\n### {suite.replace('_', ' ').title()} ({len(msgs)} messages)"]
        for m in msgs[:10]:
            parts = []
            if m.get("subject"):
                parts.append(f"Subject: {m['subject']}")
            if m.get("sender"):
                parts.append(f"From: {m['sender']}")
            if m.get("timestamp_iso"):
                parts.append(f"At: {m['timestamp_iso']}")
            if m.get("preview"):
                parts.append(f"Preview: {m['preview'][:200]}")
            section_lines.append("- " + " | ".join(parts))
        sections.append("\n".join(section_lines))

    global_timeline_preview = "\n\n### Unified Timeline (most recent first)\n"
    for m in all_messages[:20]:
        global_timeline_preview += (
            f"- [{m['channel']}] {m.get('timestamp_iso', '')} | "
            f"{m.get('sender', '')} | {m.get('preview', '')[:120]}\n"
        )

    digest_input = (
        f"Communication digest for the last {lookback_hours} hours across: "
        f"{', '.join(configured_suites) or 'none configured'}.\n"
        f"Provider status: {json.dumps(provider_status, ensure_ascii=False)}\n"
    )
    if sections:
        digest_input += "\n" + "\n".join(sections)
    digest_input += global_timeline_preview
    if errors:
        digest_input += f"\n\nProvider errors: {json.dumps(errors, ensure_ascii=False)}"

    summary = llm_text(
        "You are a personal communications assistant. Produce a concise morning briefing digest "
        "from the following multi-channel data. Show a unified timeline of the most recent messages "
        "first, then per-channel highlights, action items, and urgent topics. Be clear and scannable.\n\n"
        + digest_input
    )

    payload = {
        "lookback_hours": lookback_hours,
        "configured_suites": configured_suites,
        "provider_status": provider_status,
        "total_messages": len(all_messages),
        "per_channel_counts": {ch: len(msgs) for ch, msgs in per_channel_section.items()},
        "errors": errors,
        "unified_timeline": [
            {k: v for k, v in m.items() if k != "_raw"}
            for m in all_messages[:50]
        ],
    }
    _write_outputs("communication_summary_agent", call_number, summary, payload)
    state["communication_summary_report"] = payload
    state["draft_response"] = summary
    log_task_update("Communication Summary", f"Summary pass #{call_number} saved to {OUTPUT_DIR}/communication_summary_agent_{call_number}.txt")
    return publish_agent_output(
        state,
        "communication_summary_agent",
        summary,
        f"communication_summary_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "report_agent"],
    )


def communication_hub_agent(state):
    _, task_content, _ = begin_agent_session(state, "communication_hub_agent")
    _require_comm_authorization(state)
    state["communication_hub_calls"] = state.get("communication_hub_calls", 0) + 1
    call_number = state["communication_hub_calls"]

    evidence = {
        "scope": state.get("communication_scope_report", {}),
        "gmail": state.get("gmail_results", {}),
        "drive": state.get("drive_results", {}),
        "telegram": state.get("telegram_results", {}),
        "slack": state.get("slack_results", {}),
        "microsoft_graph": state.get("microsoft_graph_results", {}),
        "whatsapp": state.get("whatsapp_results", {}),
        "task": task_content or state.get("current_objective") or state.get("user_query", ""),
    }
    summary = llm_text(
        f"Synthesize these communication sources into one concise work summary with priorities, action items, and follow-up recommendations:\n\n{json.dumps(evidence, indent=2, ensure_ascii=False)}"
    )
    _write_outputs("communication_hub_agent", call_number, summary, evidence)
    state["communication_hub_report"] = evidence
    state["draft_response"] = summary
    log_task_update("Communication Hub", f"Communication hub pass #{call_number} saved to {OUTPUT_DIR}/communication_hub_agent_{call_number}.txt")
    return publish_agent_output(
        state,
        "communication_hub_agent",
        summary,
        f"communication_hub_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "report_agent"],
    )
