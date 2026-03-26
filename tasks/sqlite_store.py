from __future__ import annotations

import json
import os
import sqlite3
from contextlib import contextmanager


DB_PATH = os.path.join("output", "agent_workflow.sqlite3")


def _ensure_parent_dir(db_path: str):
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


@contextmanager
def _connect(db_path: str = DB_PATH):
    _ensure_parent_dir(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def initialize_db(db_path: str = DB_PATH):
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                user_query TEXT,
                started_at TEXT,
                completed_at TEXT,
                status TEXT,
                final_output TEXT
            );

            CREATE TABLE IF NOT EXISTS agent_cards (
                agent_name TEXT PRIMARY KEY,
                description TEXT,
                skills_json TEXT,
                input_keys_json TEXT,
                output_keys_json TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS tasks (
                task_id TEXT PRIMARY KEY,
                run_id TEXT,
                timestamp TEXT,
                completed_at TEXT,
                sender TEXT,
                recipient TEXT,
                intent TEXT,
                content TEXT,
                state_updates_json TEXT,
                status TEXT,
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS messages (
                message_id TEXT PRIMARY KEY,
                run_id TEXT,
                timestamp TEXT,
                sender TEXT,
                recipient TEXT,
                role TEXT,
                content TEXT,
                task_id TEXT,
                FOREIGN KEY(run_id) REFERENCES runs(run_id),
                FOREIGN KEY(task_id) REFERENCES tasks(task_id)
            );

            CREATE TABLE IF NOT EXISTS artifacts (
                artifact_id TEXT PRIMARY KEY,
                run_id TEXT,
                timestamp TEXT,
                name TEXT,
                kind TEXT,
                content TEXT,
                metadata_json TEXT,
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS agent_executions (
                execution_id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id TEXT,
                timestamp TEXT,
                agent_name TEXT,
                status TEXT,
                reason TEXT,
                output_excerpt TEXT,
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS channel_sessions (
                session_key TEXT PRIMARY KEY,
                channel TEXT,
                chat_id TEXT,
                sender_id TEXT,
                workspace_id TEXT,
                is_group INTEGER,
                state_json TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS task_sessions (
                session_id TEXT PRIMARY KEY,
                run_id TEXT,
                channel TEXT,
                session_key TEXT,
                started_at TEXT,
                updated_at TEXT,
                completed_at TEXT,
                status TEXT,
                active_agent TEXT,
                step_count INTEGER,
                summary_json TEXT,
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS scheduled_jobs (
                job_id TEXT PRIMARY KEY,
                run_id TEXT,
                created_at TEXT,
                next_run_at TEXT,
                cron_expr TEXT,
                channel TEXT,
                recipient TEXT,
                content TEXT,
                payload_json TEXT,
                status TEXT,
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS notifications (
                notification_id TEXT PRIMARY KEY,
                run_id TEXT,
                timestamp TEXT,
                channel TEXT,
                recipient TEXT,
                status TEXT,
                content TEXT,
                metadata_json TEXT,
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS monitor_rules (
                rule_id TEXT PRIMARY KEY,
                created_at TEXT,
                updated_at TEXT,
                monitor_type TEXT,
                name TEXT,
                subject TEXT,
                interval_seconds INTEGER,
                channel TEXT,
                recipient TEXT,
                config_json TEXT,
                last_checked_at TEXT,
                last_value_json TEXT,
                status TEXT
            );

            CREATE TABLE IF NOT EXISTS monitor_events (
                event_id TEXT PRIMARY KEY,
                rule_id TEXT,
                timestamp TEXT,
                severity TEXT,
                triggered INTEGER,
                title TEXT,
                details TEXT,
                notification_status TEXT,
                metadata_json TEXT,
                FOREIGN KEY(rule_id) REFERENCES monitor_rules(rule_id)
            );

            CREATE TABLE IF NOT EXISTS heartbeat_events (
                heartbeat_id TEXT PRIMARY KEY,
                service_name TEXT,
                timestamp TEXT,
                status TEXT,
                message TEXT,
                metadata_json TEXT
            );

            CREATE TABLE IF NOT EXISTS setup_components (
                component_id TEXT PRIMARY KEY,
                enabled INTEGER,
                notes TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS setup_config_values (
                component_id TEXT,
                config_key TEXT,
                config_value TEXT,
                is_secret INTEGER,
                updated_at TEXT,
                PRIMARY KEY (component_id, config_key)
            );

            CREATE TABLE IF NOT EXISTS setup_provider_tokens (
                provider TEXT PRIMARY KEY,
                token_json TEXT,
                updated_at TEXT
            );

            CREATE TABLE IF NOT EXISTS privileged_audit_events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT,
                timestamp TEXT,
                actor TEXT,
                action TEXT,
                status TEXT,
                detail_json TEXT,
                prev_hash TEXT,
                event_hash TEXT
            );

            CREATE TABLE IF NOT EXISTS superrag_sessions (
                session_id TEXT PRIMARY KEY,
                collection_name TEXT,
                owner_key TEXT,
                title TEXT,
                status TEXT,
                source_summary_json TEXT,
                stats_json TEXT,
                schema_kb_json TEXT,
                created_at TEXT,
                updated_at TEXT,
                last_used_at TEXT
            );

            CREATE TABLE IF NOT EXISTS superrag_ingestions (
                ingestion_id TEXT PRIMARY KEY,
                session_id TEXT,
                run_id TEXT,
                source_type TEXT,
                source_ref TEXT,
                item_count INTEGER,
                chunk_count INTEGER,
                status TEXT,
                detail_json TEXT,
                created_at TEXT,
                FOREIGN KEY(session_id) REFERENCES superrag_sessions(session_id),
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            );

            CREATE TABLE IF NOT EXISTS superrag_chat_messages (
                message_id TEXT PRIMARY KEY,
                session_id TEXT,
                run_id TEXT,
                role TEXT,
                content TEXT,
                citations_json TEXT,
                created_at TEXT,
                FOREIGN KEY(session_id) REFERENCES superrag_sessions(session_id),
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            );
            """
        )


def upsert_agent_card(card: dict, updated_at: str, db_path: str = DB_PATH):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO agent_cards (
                agent_name,
                description,
                skills_json,
                input_keys_json,
                output_keys_json,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_name) DO UPDATE SET
                description=excluded.description,
                skills_json=excluded.skills_json,
                input_keys_json=excluded.input_keys_json,
                output_keys_json=excluded.output_keys_json,
                updated_at=excluded.updated_at
            """,
            (
                card["agent_name"],
                card["description"],
                json.dumps(card.get("skills", [])),
                json.dumps(card.get("input_keys", [])),
                json.dumps(card.get("output_keys", [])),
                updated_at,
            ),
        )


def insert_run(run_id: str, user_query: str, started_at: str, status: str, db_path: str = DB_PATH):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO runs (run_id, user_query, started_at, status)
            VALUES (?, ?, ?, ?)
            """,
            (run_id, user_query, started_at, status),
        )


def update_run(
    run_id: str,
    *,
    status: str | None = None,
    completed_at: str | None = None,
    final_output: str | None = None,
    db_path: str = DB_PATH,
):
    initialize_db(db_path)
    fields = []
    values = []
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if completed_at is not None:
        fields.append("completed_at = ?")
        values.append(completed_at)
    if final_output is not None:
        fields.append("final_output = ?")
        values.append(final_output)
    if not fields:
        return

    values.append(run_id)
    with _connect(db_path) as conn:
        conn.execute(f"UPDATE runs SET {', '.join(fields)} WHERE run_id = ?", values)


def upsert_task(run_id: str, task: dict, db_path: str = DB_PATH):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO tasks (
                task_id, run_id, timestamp, completed_at, sender, recipient,
                intent, content, state_updates_json, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                completed_at=excluded.completed_at,
                sender=excluded.sender,
                recipient=excluded.recipient,
                intent=excluded.intent,
                content=excluded.content,
                state_updates_json=excluded.state_updates_json,
                status=excluded.status
            """,
            (
                task["task_id"],
                run_id,
                task.get("timestamp"),
                task.get("completed_at"),
                task.get("sender"),
                task.get("recipient"),
                task.get("intent"),
                task.get("content"),
                json.dumps(task.get("state_updates", {})),
                task.get("status"),
            ),
        )


def insert_message(run_id: str, message: dict, task_id: str | None = None, db_path: str = DB_PATH):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO messages (
                message_id, run_id, timestamp, sender, recipient, role, content, task_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message["message_id"],
                run_id,
                message.get("timestamp"),
                message.get("sender"),
                message.get("recipient"),
                message.get("role"),
                message.get("content"),
                task_id,
            ),
        )


def insert_artifact(run_id: str, artifact: dict, db_path: str = DB_PATH):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO artifacts (
                artifact_id, run_id, timestamp, name, kind, content, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                artifact["artifact_id"],
                run_id,
                artifact.get("timestamp"),
                artifact.get("name"),
                artifact.get("kind"),
                artifact.get("content"),
                json.dumps(artifact.get("metadata", {})),
            ),
        )


def insert_agent_execution(
    run_id: str,
    timestamp: str,
    agent_name: str,
    status: str,
    reason: str,
    output_excerpt: str,
    db_path: str = DB_PATH,
):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO agent_executions (
                run_id, timestamp, agent_name, status, reason, output_excerpt
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (run_id, timestamp, agent_name, status, reason, output_excerpt),
        )


def upsert_channel_session(session_key: str, payload: dict, db_path: str = DB_PATH):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO channel_sessions (
                session_key, channel, chat_id, sender_id, workspace_id, is_group, state_json, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_key) DO UPDATE SET
                channel=excluded.channel,
                chat_id=excluded.chat_id,
                sender_id=excluded.sender_id,
                workspace_id=excluded.workspace_id,
                is_group=excluded.is_group,
                state_json=excluded.state_json,
                updated_at=excluded.updated_at
            """,
            (
                session_key,
                payload.get("channel", ""),
                payload.get("chat_id", ""),
                payload.get("sender_id", ""),
                payload.get("workspace_id", ""),
                1 if payload.get("is_group") else 0,
                json.dumps(payload.get("state", {}), ensure_ascii=False),
                payload.get("updated_at", ""),
            ),
        )


def upsert_task_session(session: dict, db_path: str = DB_PATH):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO task_sessions (
                session_id, run_id, channel, session_key, started_at, updated_at,
                completed_at, status, active_agent, step_count, summary_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                run_id=excluded.run_id,
                channel=excluded.channel,
                session_key=excluded.session_key,
                started_at=excluded.started_at,
                updated_at=excluded.updated_at,
                completed_at=excluded.completed_at,
                status=excluded.status,
                active_agent=excluded.active_agent,
                step_count=excluded.step_count,
                summary_json=excluded.summary_json
            """,
            (
                session.get("session_id", ""),
                session.get("run_id", ""),
                session.get("channel", ""),
                session.get("session_key", ""),
                session.get("started_at", ""),
                session.get("updated_at", ""),
                session.get("completed_at", ""),
                session.get("status", ""),
                session.get("active_agent", ""),
                int(session.get("step_count", 0) or 0),
                json.dumps(session.get("summary", {}), ensure_ascii=False),
            ),
        )


def insert_scheduled_job(job: dict, db_path: str = DB_PATH):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO scheduled_jobs (
                job_id, run_id, created_at, next_run_at, cron_expr, channel, recipient, content, payload_json, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job["job_id"],
                job.get("run_id", ""),
                job.get("created_at", ""),
                job.get("next_run_at", ""),
                job.get("cron_expr", ""),
                job.get("channel", ""),
                job.get("recipient", ""),
                job.get("content", ""),
                json.dumps(job.get("payload", {}), ensure_ascii=False),
                job.get("status", ""),
            ),
        )


def insert_notification(notification: dict, db_path: str = DB_PATH):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO notifications (
                notification_id, run_id, timestamp, channel, recipient, status, content, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                notification["notification_id"],
                notification.get("run_id", ""),
                notification.get("timestamp", ""),
                notification.get("channel", ""),
                notification.get("recipient", ""),
                notification.get("status", ""),
                notification.get("content", ""),
                json.dumps(notification.get("metadata", {}), ensure_ascii=False),
            ),
        )


def upsert_monitor_rule(rule: dict, db_path: str = DB_PATH):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO monitor_rules (
                rule_id, created_at, updated_at, monitor_type, name, subject, interval_seconds,
                channel, recipient, config_json, last_checked_at, last_value_json, status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(rule_id) DO UPDATE SET
                updated_at=excluded.updated_at,
                monitor_type=excluded.monitor_type,
                name=excluded.name,
                subject=excluded.subject,
                interval_seconds=excluded.interval_seconds,
                channel=excluded.channel,
                recipient=excluded.recipient,
                config_json=excluded.config_json,
                last_checked_at=excluded.last_checked_at,
                last_value_json=excluded.last_value_json,
                status=excluded.status
            """,
            (
                rule["rule_id"],
                rule.get("created_at", ""),
                rule.get("updated_at", ""),
                rule.get("monitor_type", ""),
                rule.get("name", ""),
                rule.get("subject", ""),
                int(rule.get("interval_seconds", 0) or 0),
                rule.get("channel", ""),
                rule.get("recipient", ""),
                json.dumps(rule.get("config", {}), ensure_ascii=False),
                rule.get("last_checked_at", ""),
                json.dumps(rule.get("last_value", {}), ensure_ascii=False),
                rule.get("status", ""),
            ),
        )


def insert_monitor_event(event: dict, db_path: str = DB_PATH):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO monitor_events (
                event_id, rule_id, timestamp, severity, triggered, title, details, notification_status, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event["event_id"],
                event.get("rule_id", ""),
                event.get("timestamp", ""),
                event.get("severity", ""),
                1 if event.get("triggered") else 0,
                event.get("title", ""),
                event.get("details", ""),
                event.get("notification_status", ""),
                json.dumps(event.get("metadata", {}), ensure_ascii=False),
            ),
        )


def insert_heartbeat_event(event: dict, db_path: str = DB_PATH):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO heartbeat_events (
                heartbeat_id, service_name, timestamp, status, message, metadata_json
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event["heartbeat_id"],
                event.get("service_name", ""),
                event.get("timestamp", ""),
                event.get("status", ""),
                event.get("message", ""),
                json.dumps(event.get("metadata", {}), ensure_ascii=False),
            ),
        )


def list_recent_runs(limit: int = 20, db_path: str = DB_PATH) -> list[dict]:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT run_id, user_query, started_at, completed_at, status, final_output
            FROM runs
            ORDER BY started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_channel_sessions(limit: int = 50, db_path: str = DB_PATH) -> list[dict]:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT session_key, channel, chat_id, sender_id, workspace_id, is_group, state_json, updated_at
            FROM channel_sessions
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    payload: list[dict] = []
    for row in rows:
        item = dict(row)
        raw_state = item.get("state_json", "")
        try:
            item["state"] = json.loads(raw_state) if raw_state else {}
        except Exception:
            item["state"] = {}
        payload.append(item)
    return payload


def get_channel_session(session_key: str, db_path: str = DB_PATH) -> dict | None:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT session_key, channel, chat_id, sender_id, workspace_id, is_group, state_json, updated_at
            FROM channel_sessions
            WHERE session_key = ?
            LIMIT 1
            """,
            (session_key,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    raw_state = item.get("state_json", "")
    try:
        item["state"] = json.loads(raw_state) if raw_state else {}
    except Exception:
        item["state"] = {}
    return item


def list_task_sessions(limit: int = 50, db_path: str = DB_PATH) -> list[dict]:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT session_id, run_id, channel, session_key, started_at, updated_at,
                   completed_at, status, active_agent, step_count, summary_json
            FROM task_sessions
            ORDER BY updated_at DESC, started_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_scheduled_jobs(limit: int = 50, db_path: str = DB_PATH) -> list[dict]:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT job_id, run_id, created_at, next_run_at, cron_expr, channel, recipient, content, payload_json, status
            FROM scheduled_jobs
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_monitor_rules(limit: int = 50, db_path: str = DB_PATH) -> list[dict]:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT rule_id, created_at, updated_at, monitor_type, name, subject, interval_seconds,
                   channel, recipient, config_json, last_checked_at, last_value_json, status
            FROM monitor_rules
            ORDER BY updated_at DESC, created_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_monitor_events(limit: int = 50, db_path: str = DB_PATH) -> list[dict]:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT event_id, rule_id, timestamp, severity, triggered, title, details, notification_status, metadata_json
            FROM monitor_events
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_heartbeat_events(limit: int = 50, db_path: str = DB_PATH) -> list[dict]:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT heartbeat_id, service_name, timestamp, status, message, metadata_json
            FROM heartbeat_events
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_setup_component(
    component_id: str,
    *,
    enabled: bool = True,
    notes: str = "",
    updated_at: str = "",
    db_path: str = DB_PATH,
):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO setup_components (component_id, enabled, notes, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(component_id) DO UPDATE SET
                enabled=excluded.enabled,
                notes=excluded.notes,
                updated_at=excluded.updated_at
            """,
            (component_id, 1 if enabled else 0, notes, updated_at),
        )


def get_setup_component(component_id: str, db_path: str = DB_PATH) -> dict:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT component_id, enabled, notes, updated_at
            FROM setup_components
            WHERE component_id = ?
            """,
            (component_id,),
        ).fetchone()
    return dict(row) if row else {}


def list_setup_components(db_path: str = DB_PATH) -> list[dict]:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT component_id, enabled, notes, updated_at
            FROM setup_components
            ORDER BY component_id ASC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def upsert_setup_config_value(
    component_id: str,
    config_key: str,
    config_value: str,
    *,
    is_secret: bool = False,
    updated_at: str = "",
    db_path: str = DB_PATH,
):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO setup_config_values (component_id, config_key, config_value, is_secret, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(component_id, config_key) DO UPDATE SET
                config_value=excluded.config_value,
                is_secret=excluded.is_secret,
                updated_at=excluded.updated_at
            """,
            (component_id, config_key, config_value, 1 if is_secret else 0, updated_at),
        )


def delete_setup_config_value(component_id: str, config_key: str, db_path: str = DB_PATH):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            DELETE FROM setup_config_values
            WHERE component_id = ? AND config_key = ?
            """,
            (component_id, config_key),
        )


def list_setup_config_values(*, include_secrets: bool = True, db_path: str = DB_PATH) -> list[dict]:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT component_id, config_key, config_value, is_secret, updated_at
            FROM setup_config_values
            ORDER BY component_id ASC, config_key ASC
            """
        ).fetchall()
    payload = []
    for row in rows:
        item = dict(row)
        if not include_secrets and int(item.get("is_secret", 0)) == 1:
            item["config_value"] = "********"
        payload.append(item)
    return payload


def get_setup_config_value(component_id: str, config_key: str, db_path: str = DB_PATH) -> dict:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT component_id, config_key, config_value, is_secret, updated_at
            FROM setup_config_values
            WHERE component_id = ? AND config_key = ?
            """,
            (component_id, config_key),
        ).fetchone()
    return dict(row) if row else {}


def set_setup_provider_tokens(provider: str, token_payload: dict, updated_at: str = "", db_path: str = DB_PATH):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO setup_provider_tokens (provider, token_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(provider) DO UPDATE SET
                token_json=excluded.token_json,
                updated_at=excluded.updated_at
            """,
            (provider, json.dumps(token_payload, ensure_ascii=False), updated_at),
        )


def get_setup_provider_tokens(provider: str, db_path: str = DB_PATH) -> dict:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT token_json
            FROM setup_provider_tokens
            WHERE provider = ?
            """,
            (provider,),
        ).fetchone()
    if not row:
        return {}
    raw = row["token_json"]
    try:
        payload = json.loads(raw) if raw else {}
    except Exception:
        payload = {}
    return payload if isinstance(payload, dict) else {}


def list_setup_provider_tokens(*, include_secrets: bool = False, db_path: str = DB_PATH) -> dict:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT provider, token_json, updated_at
            FROM setup_provider_tokens
            ORDER BY provider ASC
            """
        ).fetchall()
    payload: dict[str, dict] = {}
    for row in rows:
        provider = row["provider"]
        try:
            value = json.loads(row["token_json"] or "{}")
        except Exception:
            value = {}
        if not include_secrets and isinstance(value, dict):
            scrubbed = {}
            for key, token_value in value.items():
                if "token" in key or "secret" in key:
                    scrubbed[key] = "********"
                else:
                    scrubbed[key] = token_value
            value = scrubbed
        payload[provider] = {
            "token_payload": value,
            "updated_at": row["updated_at"],
        }
    return payload


def insert_privileged_audit_event(event: dict, db_path: str = DB_PATH):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO privileged_audit_events (
                event_id, run_id, timestamp, actor, action, status, detail_json, prev_hash, event_hash
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.get("event_id", ""),
                event.get("run_id", ""),
                event.get("timestamp", ""),
                event.get("actor", ""),
                event.get("action", ""),
                event.get("status", ""),
                json.dumps(event.get("detail", {}), ensure_ascii=False),
                event.get("prev_hash", ""),
                event.get("event_hash", ""),
            ),
        )


def list_privileged_audit_events(limit: int = 100, db_path: str = DB_PATH) -> list[dict]:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT event_id, run_id, timestamp, actor, action, status, detail_json, prev_hash, event_hash
            FROM privileged_audit_events
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    payload: list[dict] = []
    for row in rows:
        item = dict(row)
        try:
            item["detail"] = json.loads(item.get("detail_json") or "{}")
        except Exception:
            item["detail"] = {}
        payload.append(item)
    return payload


def upsert_superrag_session(session: dict, db_path: str = DB_PATH):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO superrag_sessions (
                session_id,
                collection_name,
                owner_key,
                title,
                status,
                source_summary_json,
                stats_json,
                schema_kb_json,
                created_at,
                updated_at,
                last_used_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(session_id) DO UPDATE SET
                collection_name=excluded.collection_name,
                owner_key=excluded.owner_key,
                title=excluded.title,
                status=excluded.status,
                source_summary_json=excluded.source_summary_json,
                stats_json=excluded.stats_json,
                schema_kb_json=excluded.schema_kb_json,
                updated_at=excluded.updated_at,
                last_used_at=excluded.last_used_at
            """,
            (
                session.get("session_id", ""),
                session.get("collection_name", ""),
                session.get("owner_key", ""),
                session.get("title", ""),
                session.get("status", ""),
                json.dumps(session.get("source_summary", {}), ensure_ascii=False),
                json.dumps(session.get("stats", {}), ensure_ascii=False),
                json.dumps(session.get("schema_kb", {}), ensure_ascii=False),
                session.get("created_at", ""),
                session.get("updated_at", ""),
                session.get("last_used_at", ""),
            ),
        )


def get_superrag_session(session_id: str, db_path: str = DB_PATH) -> dict | None:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT session_id, collection_name, owner_key, title, status,
                   source_summary_json, stats_json, schema_kb_json,
                   created_at, updated_at, last_used_at
            FROM superrag_sessions
            WHERE session_id = ?
            LIMIT 1
            """,
            (session_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    for key in ("source_summary_json", "stats_json", "schema_kb_json"):
        raw = item.get(key, "")
        try:
            parsed = json.loads(raw) if raw else {}
        except Exception:
            parsed = {}
        item[key.replace("_json", "")] = parsed
    return item


def list_superrag_sessions(limit: int = 50, owner_key: str = "", db_path: str = DB_PATH) -> list[dict]:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        if owner_key:
            rows = conn.execute(
                """
                SELECT session_id, collection_name, owner_key, title, status,
                       source_summary_json, stats_json, schema_kb_json,
                       created_at, updated_at, last_used_at
                FROM superrag_sessions
                WHERE owner_key = ?
                ORDER BY last_used_at DESC, updated_at DESC
                LIMIT ?
                """,
                (owner_key, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT session_id, collection_name, owner_key, title, status,
                       source_summary_json, stats_json, schema_kb_json,
                       created_at, updated_at, last_used_at
                FROM superrag_sessions
                ORDER BY last_used_at DESC, updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    payload: list[dict] = []
    for row in rows:
        item = dict(row)
        for key in ("source_summary_json", "stats_json", "schema_kb_json"):
            raw = item.get(key, "")
            try:
                parsed = json.loads(raw) if raw else {}
            except Exception:
                parsed = {}
            item[key.replace("_json", "")] = parsed
        payload.append(item)
    return payload


def insert_superrag_ingestion(event: dict, db_path: str = DB_PATH):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO superrag_ingestions (
                ingestion_id,
                session_id,
                run_id,
                source_type,
                source_ref,
                item_count,
                chunk_count,
                status,
                detail_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.get("ingestion_id", ""),
                event.get("session_id", ""),
                event.get("run_id", ""),
                event.get("source_type", ""),
                event.get("source_ref", ""),
                int(event.get("item_count", 0) or 0),
                int(event.get("chunk_count", 0) or 0),
                event.get("status", ""),
                json.dumps(event.get("detail", {}), ensure_ascii=False),
                event.get("created_at", ""),
            ),
        )


def list_superrag_ingestions(session_id: str = "", limit: int = 100, db_path: str = DB_PATH) -> list[dict]:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        if session_id:
            rows = conn.execute(
                """
                SELECT ingestion_id, session_id, run_id, source_type, source_ref,
                       item_count, chunk_count, status, detail_json, created_at
                FROM superrag_ingestions
                WHERE session_id = ?
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (session_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT ingestion_id, session_id, run_id, source_type, source_ref,
                       item_count, chunk_count, status, detail_json, created_at
                FROM superrag_ingestions
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
    payload = []
    for row in rows:
        item = dict(row)
        raw = item.get("detail_json", "")
        try:
            item["detail"] = json.loads(raw) if raw else {}
        except Exception:
            item["detail"] = {}
        payload.append(item)
    return payload


def insert_superrag_chat_message(message: dict, db_path: str = DB_PATH):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO superrag_chat_messages (
                message_id,
                session_id,
                run_id,
                role,
                content,
                citations_json,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.get("message_id", ""),
                message.get("session_id", ""),
                message.get("run_id", ""),
                message.get("role", ""),
                message.get("content", ""),
                json.dumps(message.get("citations", []), ensure_ascii=False),
                message.get("created_at", ""),
            ),
        )


def list_superrag_chat_messages(session_id: str, limit: int = 40, db_path: str = DB_PATH) -> list[dict]:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT message_id, session_id, run_id, role, content, citations_json, created_at
            FROM superrag_chat_messages
            WHERE session_id = ?
            ORDER BY created_at DESC
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
    payload = []
    for row in rows:
        item = dict(row)
        raw = item.get("citations_json", "")
        try:
            item["citations"] = json.loads(raw) if raw else []
        except Exception:
            item["citations"] = []
        payload.append(item)
    return payload
