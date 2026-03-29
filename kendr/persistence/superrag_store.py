from __future__ import annotations

import json

from .core import DB_PATH, _connect, initialize_db


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
