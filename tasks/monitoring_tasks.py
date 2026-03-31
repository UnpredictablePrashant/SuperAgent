from __future__ import annotations

import csv
import io
import json
import os
import uuid
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.request import Request, urlopen

from kendr.persistence import initialize_db, insert_heartbeat_event, insert_monitor_event, upsert_monitor_rule
from kendr.setup import build_setup_snapshot

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.file_memory import bootstrap_file_memory, run_memory_maintenance
from tasks.gateway_tasks import notification_dispatch_agent
from tasks.research_infra import llm_text
from tasks.utils import log_task_update, write_text_file


AGENT_METADATA = {
    "heartbeat_agent": {
        "description": "Writes a heartbeat/status record for the always-on system and its configured services.",
        "requirements": ["openai"],
        "input_keys": ["heartbeat_service_name"],
        "output_keys": ["heartbeat_status"],
    },
    "monitor_rule_agent": {
        "description": "Creates or updates persistent monitor rules for 24/7 watch workflows.",
        "requirements": ["openai"],
        "input_keys": ["monitor_type", "monitor_subject", "monitor_channel", "monitor_recipient"],
        "output_keys": ["monitor_rule"],
    },
    "stock_monitor_agent": {
        "description": "Checks stock prices against configured thresholds and emits proactive events.",
        "requirements": ["openai"],
        "input_keys": ["monitor_rule", "stock_symbol"],
        "output_keys": ["stock_monitor_result"],
    },
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write_outputs(agent_name: str, call_number: int, summary: str, payload: dict):
    write_text_file(f"{agent_name}_{call_number}.txt", summary)
    write_text_file(f"{agent_name}_{call_number}.json", json.dumps(payload, indent=2, ensure_ascii=False))


def _to_float(value, default: float | None = None) -> float | None:
    try:
        if value in ("", None, "N/D"):
            return default
        return float(value)
    except Exception:
        return default


def _fetch_stooq_quote(symbol: str) -> dict:
    normalized = (symbol or "").strip().lower()
    if not normalized:
        raise ValueError("stock_symbol is required.")
    if "." not in normalized:
        normalized = f"{normalized}.us"
    url = f"https://stooq.com/q/l/?s={normalized}&f=sd2t2ohlcv&h&e=csv"
    request = Request(url, headers={"User-Agent": os.getenv("RESEARCH_USER_AGENT", "multi-agent-monitor/1.0")})
    try:
        with urlopen(request, timeout=20) as response:
            body = response.read().decode("utf-8", errors="ignore")
    except URLError as exc:
        raise RuntimeError(f"Unable to fetch stock data for {symbol}: {exc}") from exc
    rows = list(csv.DictReader(io.StringIO(body)))
    if not rows:
        raise RuntimeError(f"No stock data returned for {symbol}.")
    row = rows[0]
    return {
        "symbol": row.get("Symbol", normalized).upper(),
        "date": row.get("Date", ""),
        "time": row.get("Time", ""),
        "open": _to_float(row.get("Open")),
        "high": _to_float(row.get("High")),
        "low": _to_float(row.get("Low")),
        "close": _to_float(row.get("Close")),
        "volume": _to_float(row.get("Volume")),
        "raw": row,
    }


def heartbeat_agent(state):
    _, task_content, _ = begin_agent_session(state, "heartbeat_agent")
    initialize_db()
    state = bootstrap_file_memory(state)
    state["heartbeat_agent_calls"] = state.get("heartbeat_agent_calls", 0) + 1
    call_number = state["heartbeat_agent_calls"]
    service_name = state.get("heartbeat_service_name") or "kendr-daemon"
    snapshot = build_setup_snapshot(state.get("available_agent_cards", []))
    configured_services = [name for name, item in snapshot.get("services", {}).items() if item.get("configured")]
    disabled_agents = list((snapshot.get("disabled_agents") or {}).keys())[:10]
    payload = {
        "heartbeat_id": f"heartbeat_{uuid.uuid4().hex}",
        "service_name": service_name,
        "timestamp": _now_iso(),
        "status": "ok",
        "message": task_content or "System heartbeat recorded.",
        "metadata": {
            "configured_services": configured_services,
            "available_agent_count": len(snapshot.get("available_agents", [])),
            "disabled_agents": disabled_agents,
        },
    }
    payload["memory_maintenance"] = run_memory_maintenance(
        state,
        force=bool(state.get("memory_compaction_force", False)),
    )
    insert_heartbeat_event(payload)
    summary = llm_text(
        f"""You are a heartbeat monitoring agent.

Summarize this heartbeat status for the operator in 2-4 lines. Mention whether the system appears healthy and what integrations are currently configured.

Payload:
{json.dumps(payload, indent=2, ensure_ascii=False)}
"""
    )
    _write_outputs("heartbeat_agent", call_number, summary, payload)
    state["heartbeat_status"] = payload
    state["draft_response"] = summary
    log_task_update("Heartbeat", f"Heartbeat #{call_number} recorded for {service_name}.")
    return publish_agent_output(
        state,
        "heartbeat_agent",
        summary,
        f"heartbeat_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent", "notification_dispatch_agent"],
    )


def monitor_rule_agent(state):
    _, task_content, _ = begin_agent_session(state, "monitor_rule_agent")
    initialize_db()
    state["monitor_rule_agent_calls"] = state.get("monitor_rule_agent_calls", 0) + 1
    call_number = state["monitor_rule_agent_calls"]

    rule_id = state.get("monitor_rule_id") or f"rule_{uuid.uuid4().hex}"
    now = _now_iso()
    config = dict(state.get("monitor_config") or {})
    if state.get("stock_symbol"):
        config.setdefault("stock_symbol", state.get("stock_symbol"))
    if state.get("monitor_threshold_above") is not None:
        config["threshold_above"] = state.get("monitor_threshold_above")
    if state.get("monitor_threshold_below") is not None:
        config["threshold_below"] = state.get("monitor_threshold_below")
    if state.get("monitor_percent_change") is not None:
        config["percent_change_threshold"] = state.get("monitor_percent_change")

    rule = {
        "rule_id": rule_id,
        "created_at": state.get("monitor_created_at") or now,
        "updated_at": now,
        "monitor_type": state.get("monitor_type") or "stock_price",
        "name": state.get("monitor_name") or task_content or f"Monitor {rule_id}",
        "subject": state.get("monitor_subject") or state.get("stock_symbol") or task_content or "",
        "interval_seconds": int(state.get("monitor_interval_seconds", 300) or 300),
        "channel": state.get("monitor_channel") or state.get("notification_channel") or "",
        "recipient": state.get("monitor_recipient") or state.get("notification_recipient") or "",
        "config": config,
        "last_checked_at": state.get("last_checked_at", ""),
        "last_value": state.get("last_value", {}),
        "status": state.get("monitor_status") or "active",
    }
    upsert_monitor_rule(rule)
    summary = (
        f"Monitor rule saved.\n"
        f"Rule ID: {rule['rule_id']}\n"
        f"Type: {rule['monitor_type']}\n"
        f"Subject: {rule['subject'] or 'n/a'}\n"
        f"Interval Seconds: {rule['interval_seconds']}\n"
        f"Channel: {rule['channel'] or 'none'}\n"
        f"Recipient: {rule['recipient'] or 'none'}"
    )
    _write_outputs("monitor_rule_agent", call_number, summary, rule)
    state["monitor_rule"] = rule
    state["draft_response"] = summary
    log_task_update("Monitor Rule", f"Rule {rule_id} saved.")
    return publish_agent_output(
        state,
        "monitor_rule_agent",
        summary,
        f"monitor_rule_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent", "stock_monitor_agent"],
    )


def stock_monitor_agent(state):
    _, task_content, _ = begin_agent_session(state, "stock_monitor_agent")
    initialize_db()
    state["stock_monitor_agent_calls"] = state.get("stock_monitor_agent_calls", 0) + 1
    call_number = state["stock_monitor_agent_calls"]

    rule = dict(state.get("monitor_rule") or {})
    config = dict(rule.get("config") or {})
    symbol = (
        state.get("stock_symbol")
        or config.get("stock_symbol")
        or rule.get("subject")
        or task_content
        or state.get("user_query", "")
    )
    quote = _fetch_stooq_quote(symbol)
    close_price = quote.get("close")
    previous = state.get("last_value") or rule.get("last_value") or {}
    previous_close = _to_float((previous or {}).get("close"))
    percent_change = None
    if close_price is not None and previous_close not in (None, 0):
        percent_change = ((close_price - previous_close) / previous_close) * 100.0

    threshold_above = _to_float(config.get("threshold_above"))
    threshold_below = _to_float(config.get("threshold_below"))
    percent_threshold = _to_float(config.get("percent_change_threshold"))

    triggered_reasons = []
    if close_price is not None and threshold_above is not None and close_price >= threshold_above:
        triggered_reasons.append(f"price {close_price:.2f} >= {threshold_above:.2f}")
    if close_price is not None and threshold_below is not None and close_price <= threshold_below:
        triggered_reasons.append(f"price {close_price:.2f} <= {threshold_below:.2f}")
    if percent_change is not None and percent_threshold is not None and abs(percent_change) >= percent_threshold:
        triggered_reasons.append(f"change {percent_change:.2f}% exceeds {percent_threshold:.2f}%")

    event = {
        "event_id": f"event_{uuid.uuid4().hex}",
        "rule_id": rule.get("rule_id", ""),
        "timestamp": _now_iso(),
        "severity": "info" if not triggered_reasons else "high",
        "triggered": bool(triggered_reasons),
        "title": f"Stock monitor for {quote['symbol']}",
        "details": "; ".join(triggered_reasons) if triggered_reasons else "No trigger fired.",
        "notification_status": "not_sent",
        "metadata": {
            "quote": quote,
            "previous_close": previous_close,
            "percent_change": percent_change,
            "config": config,
        },
    }

    rule["last_checked_at"] = event["timestamp"]
    rule["last_value"] = quote
    if rule.get("rule_id"):
        upsert_monitor_rule(rule)
    insert_monitor_event(event)

    if event["triggered"] and (rule.get("channel") or state.get("notification_channel")) and (rule.get("recipient") or state.get("notification_recipient")):
        notification_state = dict(state)
        notification_state["notification_authorized"] = True
        notification_state["notification_channel"] = rule.get("channel") or state.get("notification_channel")
        notification_state["notification_recipient"] = rule.get("recipient") or state.get("notification_recipient")
        notification_state["notification_message"] = (
            f"{event['title']}\n"
            f"Price: {close_price if close_price is not None else 'n/a'}\n"
            f"Reason: {event['details']}"
        )
        try:
            notification_state = notification_dispatch_agent(notification_state)
            event["notification_status"] = "sent"
            state["notification_result"] = notification_state.get("notification_result", {})
            insert_monitor_event(event)
        except Exception as exc:
            event["notification_status"] = f"failed: {exc}"
            insert_monitor_event(event)

    summary = llm_text(
        f"""You are a stock monitoring agent.

Summarize this stock watch check. Mention the latest price, prior checkpoint if available, whether any trigger fired, and whether a notification was sent.

Payload:
{json.dumps(event, indent=2, ensure_ascii=False)}
"""
    )
    _write_outputs("stock_monitor_agent", call_number, summary, event)
    state["stock_monitor_result"] = event
    state["monitor_rule"] = rule
    state["draft_response"] = summary
    log_task_update("Stock Monitor", f"Checked {quote['symbol']} trigger={event['triggered']}.")
    return publish_agent_output(
        state,
        "stock_monitor_agent",
        summary,
        f"stock_monitor_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent", "notification_dispatch_agent", "report_agent"],
    )
