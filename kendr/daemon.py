from __future__ import annotations

import os
import time
from datetime import datetime, timezone, timedelta
from pathlib import Path

from kendr.persistence import initialize_db, list_monitor_rules
from tasks.utils import OUTPUT_DIR, log_task_update, set_active_output_dir

from .discovery import build_registry


def _parse_iso(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return None


def _daemon_state() -> dict:
    return {
        "run_id": "daemon",
        "notification_authorized": True,
    }


def _should_run_rule(rule: dict, now: datetime) -> bool:
    if str(rule.get("status", "active")).lower() != "active":
        return False
    interval_seconds = int(rule.get("interval_seconds", 300) or 300)
    last_checked = _parse_iso(str(rule.get("last_checked_at", "")))
    if last_checked is None:
        return True
    return now >= last_checked + timedelta(seconds=interval_seconds)


def _rule_state(rule: dict) -> dict:
    return {
        **_daemon_state(),
        "monitor_rule": {
            "rule_id": rule.get("rule_id", ""),
            "created_at": rule.get("created_at", ""),
            "updated_at": rule.get("updated_at", ""),
            "monitor_type": rule.get("monitor_type", ""),
            "name": rule.get("name", ""),
            "subject": rule.get("subject", ""),
            "interval_seconds": int(rule.get("interval_seconds", 300) or 300),
            "channel": rule.get("channel", ""),
            "recipient": rule.get("recipient", ""),
            "config": {},
            "last_checked_at": rule.get("last_checked_at", ""),
            "last_value": {},
            "status": rule.get("status", "active"),
        },
    }


def _load_rule_payload(rule: dict, state: dict) -> dict:
    import json

    try:
        state["monitor_rule"]["config"] = json.loads(rule.get("config_json") or "{}")
    except Exception:
        state["monitor_rule"]["config"] = {}
    try:
        state["monitor_rule"]["last_value"] = json.loads(rule.get("last_value_json") or "{}")
    except Exception:
        state["monitor_rule"]["last_value"] = {}
    return state


def run_daemon(*, poll_interval_seconds: int = 30, heartbeat_interval_seconds: int = 300, once: bool = False) -> int:
    initialize_db()
    daemon_output_dir = str(Path(OUTPUT_DIR) / "daemon")
    set_active_output_dir(daemon_output_dir)
    registry = build_registry()
    heartbeat_agent = registry.agents.get("heartbeat_agent")
    log_task_update("Daemon", f"Kendr daemon started. poll={poll_interval_seconds}s heartbeat={heartbeat_interval_seconds}s")
    last_heartbeat_at: datetime | None = None

    while True:
        now = datetime.now(timezone.utc)
        if heartbeat_agent and (
            last_heartbeat_at is None or now >= last_heartbeat_at + timedelta(seconds=heartbeat_interval_seconds)
        ):
            try:
                heartbeat_agent.handler(
                    {
                        **_daemon_state(),
                        "heartbeat_service_name": "kendr-daemon",
                        "user_query": "Record daemon heartbeat.",
                    }
                )
            except Exception as exc:
                log_task_update("Daemon", "Heartbeat failed.", str(exc))
            last_heartbeat_at = now

        for rule in list_monitor_rules(500):
            if not _should_run_rule(rule, now):
                continue
            monitor_type = str(rule.get("monitor_type", "")).strip().lower()
            agent_name = {
                "stock_price": "stock_monitor_agent",
                "stock": "stock_monitor_agent",
            }.get(monitor_type)
            if not agent_name or agent_name not in registry.agents:
                log_task_update("Daemon", f"Skipping rule {rule.get('rule_id')}: unsupported monitor type {monitor_type}.")
                continue
            state = _load_rule_payload(rule, _rule_state(rule))
            try:
                registry.agents[agent_name].handler(state)
            except Exception as exc:
                log_task_update("Daemon", f"Monitor rule {rule.get('rule_id')} failed.", str(exc))

        if once:
            break
        time.sleep(max(5, int(poll_interval_seconds or 30)))

    log_task_update("Daemon", "Kendr daemon finished.")
    return 0
