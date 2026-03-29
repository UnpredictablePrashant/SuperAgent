from __future__ import annotations

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


def _table_columns(conn: sqlite3.Connection, table_name: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {str(row["name"]) for row in rows}


def _ensure_column(conn: sqlite3.Connection, table_name: str, column_name: str, column_sql: str) -> None:
    if column_name in _table_columns(conn, table_name):
        return
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}")


def initialize_db(db_path: str = DB_PATH):
    with _connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                user_query TEXT,
                started_at TEXT,
                updated_at TEXT,
                completed_at TEXT,
                status TEXT,
                final_output TEXT,
                working_directory TEXT,
                run_output_dir TEXT,
                session_id TEXT,
                parent_run_id TEXT,
                resumable INTEGER,
                checkpoint_json TEXT
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

            CREATE TABLE IF NOT EXISTS run_checkpoints (
                checkpoint_id TEXT PRIMARY KEY,
                run_id TEXT,
                created_at TEXT,
                checkpoint_kind TEXT,
                step_index INTEGER,
                status TEXT,
                data_json TEXT,
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
        _ensure_column(conn, "runs", "updated_at", "TEXT")
        _ensure_column(conn, "runs", "working_directory", "TEXT")
        _ensure_column(conn, "runs", "run_output_dir", "TEXT")
        _ensure_column(conn, "runs", "session_id", "TEXT")
        _ensure_column(conn, "runs", "parent_run_id", "TEXT")
        _ensure_column(conn, "runs", "resumable", "INTEGER")
        _ensure_column(conn, "runs", "checkpoint_json", "TEXT")
