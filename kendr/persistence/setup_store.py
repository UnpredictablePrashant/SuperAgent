from __future__ import annotations

import json

from .core import DB_PATH, _connect, initialize_db


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
