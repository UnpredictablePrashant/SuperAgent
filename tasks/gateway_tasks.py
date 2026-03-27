import importlib.util
import json
import os
import re
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin
from urllib.request import Request, urlopen

from superagent.http import normalize_channel, session_id_for_payload
from superagent.orchestration import state_awaiting_user_input
from superagent.persistence import (
    get_channel_session,
    initialize_db,
    insert_notification,
    insert_scheduled_job,
    upsert_channel_session,
)
from superagent.providers import get_slack_bot_token

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.research_infra import html_to_text, llm_text
from tasks.utils import log_task_update, resolve_output_path, write_text_file


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _write_outputs(agent_name: str, call_number: int, summary: str, payload: dict):
    write_text_file(f"{agent_name}_{call_number}.txt", summary)
    write_text_file(f"{agent_name}_{call_number}.json", json.dumps(payload, indent=2, ensure_ascii=False))


def _request_text(url: str, timeout: int = 30) -> str:
    request = Request(url, headers={"User-Agent": os.getenv("RESEARCH_USER_AGENT", "multi-agent-gateway/1.0")})
    with urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8", errors="ignore")


def _playwright_available() -> bool:
    return importlib.util.find_spec("playwright") is not None


def _extract_page_payload(url: str, state: dict) -> dict:
    timeout = int(state.get("browser_timeout", 45))
    if _playwright_available() and state.get("browser_use_playwright", True):
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, wait_until="networkidle", timeout=timeout * 1000)
            title = page.title()
            html = page.content()
            links = [{"text": link.inner_text().strip()[:200], "href": link.get_attribute("href") or ""} for link in page.locator("a").all()[:50]]
            screenshot_path = ""
            if state.get("browser_capture_screenshot"):
                filename = f"browser_automation_{uuid.uuid4().hex}.png"
                screenshot_path = resolve_output_path(filename)
                page.screenshot(path=screenshot_path, full_page=True)
            browser.close()
        return {
            "engine": "playwright",
            "url": url,
            "title": title,
            "text_excerpt": html_to_text(html)[:6000],
            "links": links,
            "screenshot_path": screenshot_path,
        }

    html = _request_text(url, timeout=timeout)
    title_match = re.search(r"(?is)<title>(.*?)</title>", html)
    title = title_match.group(1).strip() if title_match else ""
    links = []
    if importlib.util.find_spec("bs4") is not None:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        if soup.title:
            title = soup.title.get_text(strip=True)
        for tag in soup.select("a[href]")[:50]:
            href = tag.get("href", "")
            links.append({"text": tag.get_text(" ", strip=True)[:200], "href": urljoin(url, href)})
    else:
        for href in re.findall(r'(?is)<a[^>]+href=["\\\'](.*?)["\\\']', html)[:50]:
            links.append({"text": "", "href": urljoin(url, href)})
    return {
        "engine": "http-html",
        "url": url,
        "title": title,
        "text_excerpt": html_to_text(html)[:6000],
        "links": links,
        "screenshot_path": "",
    }


def _headed_browser_supported() -> bool:
    if os.name == "nt":
        return True
    if os.getenv("DISPLAY") or os.getenv("WAYLAND_DISPLAY"):
        return True
    return os.uname().sysname.lower() == "darwin" if hasattr(os, "uname") else False


def _execute_browser_actions(page, base_url: str, actions: list[dict], state: dict) -> tuple[list[dict], list[dict], str]:
    timeout_ms = int(state.get("browser_timeout", 45)) * 1000
    execution_log = []
    extracted_items = []
    screenshot_path = ""

    if base_url:
        page.goto(base_url, wait_until="networkidle", timeout=timeout_ms)
        execution_log.append({"action": "goto", "url": base_url, "status": "ok"})

    for step in actions:
        if not isinstance(step, dict):
            continue
        action = str(step.get("action", "")).strip().lower()
        selector = str(step.get("selector", "")).strip()
        try:
            if action == "goto":
                page.goto(str(step.get("url", "")), wait_until="networkidle", timeout=timeout_ms)
            elif action == "click":
                page.click(selector, timeout=timeout_ms)
            elif action == "fill":
                page.fill(selector, str(step.get("value", "")), timeout=timeout_ms)
            elif action == "type":
                page.type(selector, str(step.get("value", "")), timeout=timeout_ms)
            elif action == "press":
                page.press(selector, str(step.get("key", "Enter")), timeout=timeout_ms)
            elif action == "wait_for_selector":
                page.wait_for_selector(selector, timeout=timeout_ms)
            elif action == "wait_for_timeout":
                page.wait_for_timeout(int(step.get("milliseconds", 1000)))
            elif action == "select_option":
                page.select_option(selector, str(step.get("value", "")), timeout=timeout_ms)
            elif action == "extract_text":
                text = page.locator(selector).inner_text(timeout=timeout_ms)
                extracted_items.append({"selector": selector, "text": text[:4000]})
            elif action == "screenshot":
                filename = step.get("filename") or f"interactive_browser_{uuid.uuid4().hex}.png"
                screenshot_path = resolve_output_path(str(filename))
                page.screenshot(path=screenshot_path, full_page=bool(step.get("full_page", True)))
            else:
                execution_log.append({"action": action or "unknown", "status": "skipped", "detail": "Unsupported action"})
                continue
            execution_log.append({"action": action, "selector": selector, "status": "ok"})
        except Exception as exc:
            execution_log.append({"action": action, "selector": selector, "status": "error", "detail": str(exc)})

    return execution_log, extracted_items, screenshot_path


def _require_notification_authorized(state: dict):
    if not state.get("notification_authorized", False):
        raise PermissionError(
            "Notification agents require explicit authorization. Set state['notification_authorized']=True only for approved outbound messaging."
        )


def _send_telegram(recipient: str, content: str) -> dict:
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not bot_token:
        raise ValueError("TELEGRAM_BOT_TOKEN is required for Telegram notifications.")
    payload = json.dumps({"chat_id": recipient, "text": content}).encode("utf-8")
    request = Request(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        data=payload,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _send_slack(recipient: str, content: str) -> dict:
    token = get_slack_bot_token()
    if not token:
        raise ValueError("SLACK_BOT_TOKEN is required for Slack notifications.")
    payload = json.dumps({"channel": recipient, "text": content}).encode("utf-8")
    request = Request(
        "https://slack.com/api/chat.postMessage",
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _send_whatsapp(recipient: str, content: str) -> dict:
    access_token = os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip()
    phone_number_id = os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()
    if not (access_token and phone_number_id):
        raise ValueError("WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID are required for WhatsApp notifications.")
    payload = json.dumps(
        {
            "messaging_product": "whatsapp",
            "to": recipient,
            "type": "text",
            "text": {"body": content},
        }
    ).encode("utf-8")
    request = Request(
        f"https://graph.facebook.com/v20.0/{phone_number_id}/messages",
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def channel_gateway_agent(state):
    _, task_content, _ = begin_agent_session(state, "channel_gateway_agent")
    state["channel_gateway_calls"] = state.get("channel_gateway_calls", 0) + 1
    call_number = state["channel_gateway_calls"]

    payload = state.get("incoming_payload", {})
    if not isinstance(payload, dict):
        payload = {}
    channel = _normalize_channel(state.get("incoming_channel") or payload.get("channel") or "webchat")
    sender_id = str(state.get("incoming_sender_id") or payload.get("sender_id") or payload.get("from") or "")
    chat_id = str(state.get("incoming_chat_id") or payload.get("chat_id") or payload.get("thread_id") or sender_id)
    workspace_id = str(state.get("incoming_workspace_id") or payload.get("workspace_id") or "")
    text = (
        state.get("incoming_text")
        or payload.get("text")
        or payload.get("message")
        or task_content
        or state.get("user_query", "")
    )
    is_group = bool(state.get("incoming_is_group", payload.get("is_group", False)))
    mention_token = (state.get("gateway_trigger_tag") or "@assistant").strip().lower()
    text_lower = str(text).lower()
    mentioned = bool(state.get("incoming_mentions_assistant", False) or mention_token in text_lower)
    should_activate = not is_group or mentioned or state.get("gateway_force_activate", False)

    normalized = {
        "channel": channel,
        "sender_id": sender_id,
        "chat_id": chat_id,
        "workspace_id": workspace_id,
        "text": text,
        "is_group": is_group,
        "mentioned": mentioned,
        "should_activate": should_activate,
    }
    if should_activate and text:
        state["user_query"] = text
        state["current_objective"] = text
    state["gateway_message"] = normalized
    try:
        summary = llm_text(
            f"""You are a channel gateway agent.

Summarize this inbound channel message normalization result.
Explain whether the message should activate the main workflow and why.

Payload:
{json.dumps(normalized, indent=2, ensure_ascii=False)}
"""
        )
    except Exception as exc:
        summary = (
            f"Channel gateway normalization completed (LLM summary unavailable: {type(exc).__name__}). "
            f"channel={normalized.get('channel')}, should_activate={normalized.get('should_activate')}, "
            f"sender_id={normalized.get('sender_id', 'unknown')}."
        )
    _write_outputs("channel_gateway_agent", call_number, summary, normalized)
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "channel_gateway_agent",
        summary,
        f"channel_gateway_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent", "session_router_agent"],
    )


def session_router_agent(state):
    _, task_content, _ = begin_agent_session(state, "session_router_agent")
    state["session_router_calls"] = state.get("session_router_calls", 0) + 1
    call_number = state["session_router_calls"]
    initialize_db()

    message = state.get("gateway_message", {})
    channel = _normalize_channel(message.get("channel") or state.get("incoming_channel") or "webchat")
    sender_id = str(message.get("sender_id") or state.get("incoming_sender_id") or "")
    chat_id = str(message.get("chat_id") or state.get("incoming_chat_id") or sender_id)
    workspace_id = str(message.get("workspace_id") or state.get("incoming_workspace_id") or "")
    is_group = bool(message.get("is_group", state.get("incoming_is_group", False)))
    session_key = session_id_for_payload(
        {
            "channel": channel,
            "workspace_id": workspace_id,
            "sender_id": sender_id,
            "chat_id": chat_id,
            "is_group": is_group,
        }
    )

    previous_session = get_channel_session(session_key) or {}
    previous_state = previous_session.get("state", {}) if isinstance(previous_session, dict) else {}
    if not isinstance(previous_state, dict):
        previous_state = {}
    history = previous_state.get("history", [])
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "timestamp": _now_iso(),
            "text": message.get("text") or task_content or state.get("user_query", ""),
            "run_id": state.get("run_id", ""),
        }
    )
    history = history[-20:]

    session_payload = {
        "session_key": session_key,
        "channel": channel,
        "chat_id": chat_id,
        "sender_id": sender_id,
        "workspace_id": workspace_id,
        "is_group": is_group,
        "state": {
            "last_text": message.get("text") or task_content or state.get("user_query", ""),
            "last_run_id": state.get("run_id", ""),
            "history": history,
            "last_objective": state.get("current_objective", state.get("user_query", "")),
            "last_plan": state.get("plan", ""),
            "awaiting_user_input": state_awaiting_user_input(state),
            "pending_user_input_kind": state.get("pending_user_input_kind", ""),
            "approval_pending_scope": state.get("approval_pending_scope", ""),
            "pending_user_question": state.get("pending_user_question", ""),
        },
        "updated_at": _now_iso(),
    }
    upsert_channel_session(session_key, session_payload)
    state["channel_session"] = session_payload
    state["channel_session_key"] = session_key
    summary = (
        f"Channel: {channel}\n"
        f"Session Key: {session_key}\n"
        f"Scope: {'group-isolated' if is_group else 'main-direct'}\n"
        f"Sender: {sender_id or 'unknown'}\n"
        f"Chat: {chat_id or 'unknown'}"
    )
    _write_outputs("session_router_agent", call_number, summary, session_payload)
    state["draft_response"] = summary
    log_task_update("Session Router", f"Session {session_key} routed and persisted.")
    return publish_agent_output(
        state,
        "session_router_agent",
        summary,
        f"session_router_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent", "channel_gateway_agent"],
    )


def browser_automation_agent(state):
    _, task_content, _ = begin_agent_session(state, "browser_automation_agent")
    state["browser_automation_calls"] = state.get("browser_automation_calls", 0) + 1
    call_number = state["browser_automation_calls"]
    url = state.get("browser_url") or state.get("target_url") or task_content
    if not url or not str(url).startswith(("http://", "https://")):
        raise ValueError("browser_automation_agent requires browser_url or an http(s) task content.")

    payload = _extract_page_payload(str(url), state)
    summary = llm_text(
        f"""You are a browser automation agent.

Summarize this browser run. Mention the page title, useful links, important visible content, and whether the run used Playwright or HTTP fallback.

Payload:
{json.dumps(payload, indent=2, ensure_ascii=False)[:40000]}
"""
    )
    _write_outputs("browser_automation_agent", call_number, summary, payload)
    state["browser_result"] = payload
    state["browser_summary"] = summary
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "browser_automation_agent",
        summary,
        f"browser_automation_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "report_agent"],
    )


def interactive_browser_agent(state):
    _, task_content, _ = begin_agent_session(state, "interactive_browser_agent")
    state["interactive_browser_calls"] = state.get("interactive_browser_calls", 0) + 1
    call_number = state["interactive_browser_calls"]
    url = state.get("browser_url") or state.get("interactive_browser_url") or task_content
    if not url or not str(url).startswith(("http://", "https://")):
        raise ValueError("interactive_browser_agent requires browser_url or an http(s) task content.")
    if not _playwright_available():
        raise RuntimeError("interactive_browser_agent requires Playwright to be installed.")

    headless = bool(state.get("browser_headless", False))
    if not headless and not _headed_browser_supported():
        raise RuntimeError(
            "Headed browser mode requires a desktop display session or Xvfb. Set browser_headless=True or provide DISPLAY/WAYLAND_DISPLAY."
        )

    from playwright.sync_api import sync_playwright

    actions = state.get("interactive_browser_actions") or state.get("browser_actions") or []
    payload = {
        "engine": "playwright",
        "mode": "headed" if not headless else "headless",
        "url": url,
        "actions": actions,
        "execution_log": [],
        "extracted_items": [],
        "screenshot_path": "",
    }

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless, slow_mo=int(state.get("browser_slow_mo_ms", 0)))
        page = browser.new_page()
        execution_log, extracted_items, screenshot_path = _execute_browser_actions(page, str(url), actions, state)
        payload["execution_log"] = execution_log
        payload["extracted_items"] = extracted_items
        payload["title"] = page.title()
        payload["final_url"] = page.url
        payload["text_excerpt"] = page.locator("body").inner_text(timeout=int(state.get("browser_timeout", 45)) * 1000)[:6000]
        if state.get("browser_capture_screenshot") and not screenshot_path:
            filename = f"interactive_browser_{uuid.uuid4().hex}.png"
            screenshot_path = resolve_output_path(filename)
            page.screenshot(path=screenshot_path, full_page=True)
        payload["screenshot_path"] = screenshot_path
        browser.close()

    summary = llm_text(
        f"""You are an interactive browser control agent.

Summarize this browser control run.
Explain what page was opened, whether headed mode was used, what actions ran, what content was extracted, and any failures.

Payload:
{json.dumps(payload, indent=2, ensure_ascii=False)[:50000]}
"""
    )
    _write_outputs("interactive_browser_agent", call_number, summary, payload)
    state["interactive_browser_result"] = payload
    state["draft_response"] = summary
    log_task_update("Interactive Browser", f"Interactive browser pass #{call_number} completed in {payload['mode']} mode.")
    return publish_agent_output(
        state,
        "interactive_browser_agent",
        summary,
        f"interactive_browser_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "report_agent"],
    )


def scheduler_agent(state):
    _, task_content, _ = begin_agent_session(state, "scheduler_agent")
    state["scheduler_calls"] = state.get("scheduler_calls", 0) + 1
    call_number = state["scheduler_calls"]
    initialize_db()

    content = state.get("schedule_task") or task_content or state.get("current_objective") or state.get("user_query", "")
    cron_expr = state.get("schedule_cron", "")
    schedule_time = state.get("schedule_time", "")
    if schedule_time:
        next_run_at = schedule_time
    elif state.get("schedule_in_minutes") is not None:
        next_run_at = (datetime.now(UTC) + timedelta(minutes=int(state["schedule_in_minutes"]))).isoformat()
    else:
        next_run_at = ""

    job = {
        "job_id": f"job_{uuid.uuid4().hex}",
        "run_id": state.get("run_id", ""),
        "created_at": _now_iso(),
        "next_run_at": next_run_at,
        "cron_expr": cron_expr,
        "channel": state.get("schedule_channel", ""),
        "recipient": state.get("schedule_recipient", ""),
        "content": content,
        "payload": {
            "schedule_note": state.get("schedule_note", ""),
            "schedule_metadata": state.get("schedule_metadata", {}),
        },
        "status": "scheduled",
    }
    insert_scheduled_job(job)
    summary = (
        f"Scheduled job created.\n"
        f"Job ID: {job['job_id']}\n"
        f"Next Run: {job['next_run_at'] or 'not specified'}\n"
        f"Cron: {job['cron_expr'] or 'none'}\n"
        f"Channel: {job['channel'] or 'none'}\n"
        f"Recipient: {job['recipient'] or 'none'}"
    )
    _write_outputs("scheduler_agent", call_number, summary, job)
    state["scheduled_job"] = job
    state["draft_response"] = summary
    log_task_update("Scheduler", f"Scheduled job {job['job_id']} persisted.")
    return publish_agent_output(
        state,
        "scheduler_agent",
        summary,
        f"scheduler_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent", "reviewer_agent", "notification_dispatch_agent"],
    )


def notification_dispatch_agent(state):
    _, task_content, _ = begin_agent_session(state, "notification_dispatch_agent")
    _require_notification_authorized(state)
    state["notification_dispatch_calls"] = state.get("notification_dispatch_calls", 0) + 1
    call_number = state["notification_dispatch_calls"]
    initialize_db()

    channel = _normalize_channel(state.get("notification_channel") or "console")
    recipient = str(state.get("notification_recipient") or "")
    content = (
        state.get("notification_message")
        or state.get("draft_response")
        or state.get("final_output")
        or task_content
        or state.get("user_query", "")
    ).strip()
    if not content:
        raise ValueError("notification_dispatch_agent requires notification_message or draft/final content.")

    if channel == "telegram":
        response = _send_telegram(recipient, content)
        status = "sent"
    elif channel == "slack":
        response = _send_slack(recipient, content)
        status = "sent"
    elif channel == "whatsapp":
        response = _send_whatsapp(recipient, content)
        status = "sent"
    else:
        response = {"channel": channel, "status": "recorded_only"}
        status = "recorded"

    notification = {
        "notification_id": f"notification_{uuid.uuid4().hex}",
        "run_id": state.get("run_id", ""),
        "timestamp": _now_iso(),
        "channel": channel,
        "recipient": recipient,
        "status": status,
        "content": content,
        "metadata": response,
    }
    insert_notification(notification)
    summary = (
        f"Notification {status}.\n"
        f"Channel: {channel}\n"
        f"Recipient: {recipient or 'n/a'}\n"
        f"Notification ID: {notification['notification_id']}"
    )
    _write_outputs("notification_dispatch_agent", call_number, summary, notification)
    state["notification_result"] = notification
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "notification_dispatch_agent",
        summary,
        f"notification_dispatch_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent", "report_agent"],
    )


def whatsapp_agent(state):
    _, task_content, _ = begin_agent_session(state, "whatsapp_agent")
    _require_notification_authorized(state)
    state["whatsapp_calls"] = state.get("whatsapp_calls", 0) + 1
    call_number = state["whatsapp_calls"]

    recipient = str(state.get("whatsapp_to") or state.get("notification_recipient") or "")
    content = (
        state.get("whatsapp_message")
        or state.get("notification_message")
        or state.get("draft_response")
        or task_content
        or state.get("user_query", "")
    ).strip()
    if not recipient:
        raise ValueError("whatsapp_agent requires whatsapp_to or notification_recipient.")
    if not content:
        raise ValueError("whatsapp_agent requires whatsapp_message or other outbound content.")

    response = _send_whatsapp(recipient, content)
    payload = {
        "recipient": recipient,
        "message_length": len(content),
        "response": response,
    }
    summary = llm_text(
        f"""You are a WhatsApp delivery agent.

Summarize this WhatsApp dispatch result for the operator.

Payload:
{json.dumps(payload, indent=2, ensure_ascii=False)}
"""
    )
    _write_outputs("whatsapp_agent", call_number, summary, payload)
    state["whatsapp_result"] = payload
    state["draft_response"] = summary
    return publish_agent_output(
        state,
        "whatsapp_agent",
        summary,
        f"whatsapp_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent", "notification_dispatch_agent"],
    )
