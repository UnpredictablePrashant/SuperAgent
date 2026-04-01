import json
import os
import sqlite3
import time

from typing import Any
from uuid import uuid4


class AlphaTaskRepository:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        self._init_db()

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS alpha_tasks (
                    local_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_query TEXT NOT NULL,
                    planner_brief TEXT NOT NULL,
                    beta_task_id TEXT,
                    beta_status TEXT NOT NULL,
                    beta_result TEXT,
                    beta_last_payload TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                )
                """
            )
            self._ensure_column(conn, "alpha_tasks", "completed_at", "REAL")
            conn.commit()

    def _ensure_column(
        self, conn: sqlite3.Connection, table: str, column: str, column_type: str
    ) -> None:
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        col_names = {str(col[1]) for col in cols}
        if column not in col_names:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def insert_task(
        self,
        user_query: str,
        planner_brief: str,
        beta_task_id: str,
        beta_status: str,
        beta_last_payload: dict[str, Any],
    ) -> int:
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO alpha_tasks (
                    user_query, planner_brief, beta_task_id, beta_status,
                    beta_result, beta_last_payload, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_query,
                    planner_brief,
                    beta_task_id,
                    beta_status,
                    None,
                    json.dumps(beta_last_payload, ensure_ascii=False),
                    now,
                    now,
                ),
            )
            conn.commit()
            return int(cur.lastrowid)

    def update_task(
        self,
        local_id: int,
        beta_status: str,
        beta_last_payload: dict[str, Any],
        beta_result: str | None = None,
    ) -> None:
        now = time.time()
        is_terminal = beta_status in {"completed", "failed", "not_found", "invalid_request"}
        completed_at = now if is_terminal else None
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE alpha_tasks
                SET beta_status = ?,
                    beta_result = COALESCE(?, beta_result),
                    beta_last_payload = ?,
                    updated_at = ?,
                    completed_at = COALESCE(?, completed_at)
                WHERE local_id = ?
                """,
                (
                    beta_status,
                    beta_result,
                    json.dumps(beta_last_payload, ensure_ascii=False),
                    now,
                    completed_at,
                    local_id,
                ),
            )
            conn.commit()


class BetaTaskRepository:
    def __init__(self, db_path: str, task_delay_seconds: float) -> None:
        self.db_path = db_path
        self.task_delay_seconds = task_delay_seconds
        self._init_db()

    def _init_db(self) -> None:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS beta_tasks (
                    task_id TEXT PRIMARY KEY,
                    source_agent TEXT NOT NULL,
                    request_text TEXT NOT NULL,
                    user_query TEXT NOT NULL,
                    planner_brief TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_text TEXT,
                    error_text TEXT,
                    created_at REAL NOT NULL,
                    ready_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                )
                """
            )
            self._ensure_column(conn, "beta_tasks", "completed_at", "REAL")
            conn.commit()

    def _ensure_column(
        self, conn: sqlite3.Connection, table: str, column: str, column_type: str
    ) -> None:
        cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
        col_names = {str(col[1]) for col in cols}
        if column not in col_names:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    def insert_task(self, source_agent: str, request_text: str, user_query: str, planner_brief: str) -> tuple[str, str]:
        task_id = uuid4().hex
        status = "queued"
        now = time.time()
        ready_at = now + self.task_delay_seconds
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO beta_tasks (
                    task_id, source_agent, request_text, user_query, planner_brief,
                    status, result_text, error_text, created_at, ready_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    task_id,
                    source_agent,
                    request_text,
                    user_query,
                    planner_brief,
                    status,
                    None,
                    None,
                    now,
                    ready_at,
                    now,
                ),
            )
            conn.commit()
        return task_id, status

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                """
                SELECT task_id, source_agent, request_text, user_query, planner_brief,
                       status, result_text, error_text, created_at, ready_at, updated_at, completed_at
                FROM beta_tasks
                WHERE task_id = ?
                """,
                (task_id,),
            ).fetchone()
        if row is None:
            return None
        return dict(row)

    def update_task_status(
        self, task_id: str, status: str, result_text: str | None = None, error_text: str | None = None
    ) -> None:
        now = time.time()
        completed_at = now if status in {"completed", "failed"} else None
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE beta_tasks
                SET status = ?,
                    result_text = COALESCE(?, result_text),
                    error_text = COALESCE(?, error_text),
                    updated_at = ?,
                    completed_at = COALESCE(?, completed_at)
                WHERE task_id = ?
                """,
                (status, result_text, error_text, now, completed_at, task_id),
            )
            conn.commit()
