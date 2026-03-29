import json
import os
from pathlib import Path
from urllib.parse import urlencode, quote
from urllib.request import Request, urlopen

from kendr.providers import get_google_access_token, get_microsoft_graph_access_token, get_slack_bot_token

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.research_infra import html_to_text, llm_text
from tasks.utils import OUTPUT_DIR, log_task_update, write_text_file


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

            async def _collect():
                async with TelegramClient(StringSession(session_string), int(api_id), api_hash) as client:
                    target = state.get("telegram_target") or task_content or "me"
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

            import asyncio

            payload["mode"] = "telethon_session"
            payload["messages"] = asyncio.run(_collect())
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
