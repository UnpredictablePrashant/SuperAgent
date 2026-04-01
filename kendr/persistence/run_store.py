from __future__ import annotations

import json
import shutil
from pathlib import Path

from .core import DB_PATH, _connect, initialize_db


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


def insert_run(
    run_id: str,
    user_query: str,
    started_at: str,
    status: str,
    *,
    updated_at: str | None = None,
    working_directory: str = "",
    run_output_dir: str = "",
    session_id: str = "",
    parent_run_id: str = "",
    resumable: bool | None = None,
    checkpoint_json: str = "",
    db_path: str = DB_PATH,
):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO runs (
                run_id, user_query, started_at, updated_at, status,
                working_directory, run_output_dir, session_id, parent_run_id, resumable, checkpoint_json
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                user_query,
                started_at,
                updated_at or started_at,
                status,
                working_directory,
                run_output_dir,
                session_id,
                parent_run_id,
                None if resumable is None else (1 if resumable else 0),
                checkpoint_json,
            ),
        )


def update_run(
    run_id: str,
    *,
    status: str | None = None,
    updated_at: str | None = None,
    completed_at: str | None = None,
    final_output: str | None = None,
    working_directory: str | None = None,
    run_output_dir: str | None = None,
    session_id: str | None = None,
    parent_run_id: str | None = None,
    resumable: bool | None = None,
    checkpoint_json: str | None = None,
    db_path: str = DB_PATH,
):
    initialize_db(db_path)
    fields = []
    values = []
    if status is not None:
        fields.append("status = ?")
        values.append(status)
    if updated_at is not None:
        fields.append("updated_at = ?")
        values.append(updated_at)
    if completed_at is not None:
        fields.append("completed_at = ?")
        values.append(completed_at)
    if final_output is not None:
        fields.append("final_output = ?")
        values.append(final_output)
    if working_directory is not None:
        fields.append("working_directory = ?")
        values.append(working_directory)
    if run_output_dir is not None:
        fields.append("run_output_dir = ?")
        values.append(run_output_dir)
    if session_id is not None:
        fields.append("session_id = ?")
        values.append(session_id)
    if parent_run_id is not None:
        fields.append("parent_run_id = ?")
        values.append(parent_run_id)
    if resumable is not None:
        fields.append("resumable = ?")
        values.append(1 if resumable else 0)
    if checkpoint_json is not None:
        fields.append("checkpoint_json = ?")
        values.append(checkpoint_json)
    if not fields:
        return

    values.append(run_id)
    with _connect(db_path) as conn:
        conn.execute(f"UPDATE runs SET {', '.join(fields)} WHERE run_id = ?", values)


def get_run(run_id: str, db_path: str = DB_PATH) -> dict | None:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT run_id, user_query, started_at, updated_at, completed_at, status, final_output,
                   working_directory, run_output_dir, session_id, parent_run_id, resumable, checkpoint_json
            FROM runs
            WHERE run_id = ?
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
    return dict(row) if row else None


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
    completed_at: str | None = None,
) -> int:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO agent_executions (
                run_id, timestamp, completed_at, agent_name, status, reason, output_excerpt
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (run_id, timestamp, completed_at, agent_name, status, reason, output_excerpt),
        )
        return cursor.lastrowid or 0


def update_agent_execution_completed(
    execution_id: int,
    completed_at: str,
    status: str,
    output_excerpt: str | None = None,
    db_path: str = DB_PATH,
) -> None:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        if output_excerpt is not None:
            conn.execute(
                """
                UPDATE agent_executions
                SET completed_at = ?, status = ?, output_excerpt = ?
                WHERE execution_id = ?
                """,
                (completed_at, status, output_excerpt, execution_id),
            )
        else:
            conn.execute(
                """
                UPDATE agent_executions
                SET completed_at = ?, status = ?
                WHERE execution_id = ?
                """,
                (completed_at, status, execution_id),
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


def insert_run_checkpoint(checkpoint: dict, db_path: str = DB_PATH):
    initialize_db(db_path)
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO run_checkpoints (
                checkpoint_id, run_id, created_at, checkpoint_kind, step_index, status, data_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                checkpoint.get("checkpoint_id", ""),
                checkpoint.get("run_id", ""),
                checkpoint.get("created_at", ""),
                checkpoint.get("checkpoint_kind", ""),
                int(checkpoint.get("step_index", 0) or 0),
                checkpoint.get("status", ""),
                json.dumps(checkpoint.get("data", {}), ensure_ascii=False),
            ),
        )


def get_latest_run_checkpoint(run_id: str, db_path: str = DB_PATH) -> dict | None:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT checkpoint_id, run_id, created_at, checkpoint_kind, step_index, status, data_json
            FROM run_checkpoints
            WHERE run_id = ?
            ORDER BY created_at DESC
            LIMIT 1
            """,
            (run_id,),
        ).fetchone()
    if not row:
        return None
    item = dict(row)
    raw_data = item.get("data_json", "")
    try:
        item["data"] = json.loads(raw_data) if raw_data else {}
    except Exception:
        item["data"] = {}
    return item


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


def list_agent_executions_for_run(run_id: str, db_path: str = DB_PATH) -> list[dict]:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT execution_id, run_id, timestamp, completed_at, agent_name, status, reason, output_excerpt
            FROM agent_executions
            WHERE run_id = ?
            ORDER BY execution_id ASC
            """,
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_artifacts_for_run(run_id: str, db_path: str = DB_PATH) -> list[dict]:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT artifact_id, run_id, timestamp, name, kind
            FROM artifacts
            WHERE run_id = ?
            ORDER BY timestamp ASC
            """,
            (run_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def list_recent_runs(limit: int = 20, db_path: str = DB_PATH) -> list[dict]:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT run_id, user_query, started_at, updated_at, completed_at, status, final_output,
                   working_directory, run_output_dir, session_id, parent_run_id, resumable
            FROM runs
            ORDER BY COALESCE(updated_at, started_at) DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def cleanup_stale_runs(stale_minutes: int = 20, db_path: str = DB_PATH) -> int:
    """Mark runs that have been stuck in 'running'/'started' status for too long as failed."""
    import datetime as _dt
    initialize_db(db_path)
    cutoff = (_dt.datetime.utcnow() - _dt.timedelta(minutes=stale_minutes)).strftime("%Y-%m-%dT%H:%M:%S")
    now = _dt.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S")
    with _connect(db_path) as conn:
        result = conn.execute(
            """
            UPDATE runs
            SET status = 'failed',
                completed_at = ?,
                final_output = 'Run was interrupted (server restart or timeout).'
            WHERE status IN ('running', 'started')
              AND COALESCE(updated_at, started_at) < ?
            """,
            (now, cutoff),
        )
        return result.rowcount


def list_run_messages(run_id: str, limit: int = 200, db_path: str = DB_PATH) -> list[dict]:
    """Return messages for a run ordered by timestamp."""
    initialize_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT message_id, run_id, timestamp, sender, recipient, role, content, task_id
            FROM messages
            WHERE run_id = ?
            ORDER BY timestamp ASC
            LIMIT ?
            """,
            (run_id, limit),
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


def delete_chat_session(
    chat_session_id: str,
    channel: str = "webchat",
    workspace_id: str = "default",
    db_path: str = DB_PATH,
) -> dict:
    initialize_db(db_path)
    session_key = f"{channel}:{workspace_id}:{chat_session_id}:main"
    deleted_runs: list[str] = []
    deleted_dirs: list[str] = []
    errors: list[str] = []

    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT run_id, run_output_dir FROM runs WHERE session_id = ? OR session_id = ?",
            (session_key, chat_session_id),
        ).fetchall()
        run_ids = [row["run_id"] for row in rows]
        run_dirs = [row["run_output_dir"] for row in rows if row["run_output_dir"]]

    for run_dir in run_dirs:
        try:
            p = Path(run_dir)
            if p.exists() and p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
                deleted_dirs.append(str(p))
        except Exception as exc:
            errors.append(str(exc))

    if run_ids:
        placeholders = ",".join("?" * len(run_ids))
        with _connect(db_path) as conn:
            for table in ("run_checkpoints", "artifacts", "agent_executions", "messages", "tasks"):
                conn.execute(f"DELETE FROM {table} WHERE run_id IN ({placeholders})", run_ids)
            try:
                conn.execute(f"DELETE FROM task_sessions WHERE run_id IN ({placeholders})", run_ids)
            except Exception:
                pass
            conn.execute(f"DELETE FROM runs WHERE run_id IN ({placeholders})", run_ids)
            deleted_runs = run_ids

    with _connect(db_path) as conn:
        conn.execute("DELETE FROM channel_sessions WHERE session_key = ?", (session_key,))

    return {
        "deleted_runs": deleted_runs,
        "deleted_dirs": deleted_dirs,
        "session_key": session_key,
        "errors": errors,
    }
