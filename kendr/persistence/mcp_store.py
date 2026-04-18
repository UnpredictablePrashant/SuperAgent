"""SQLite-backed MCP server registry.

All MCP server state is stored in the shared agent_workflow.sqlite3 database
under the `mcp_servers` table.  A one-time migration from the legacy JSON
registry (``~/.kendr/mcp_registry.json``) runs automatically on first use.
"""

from __future__ import annotations

import json
import logging
import os
import shlex
import time
from hashlib import sha1
from typing import Any

from .core import DB_PATH, _connect, initialize_db, resolve_db_path
from kendr.secret_store import build_secret_ref, delete_secret, get_secret, is_secret_ref, put_secret

_log = logging.getLogger("kendr.persistence.mcp_store")


def _kendr_home_dir() -> str:
    root = str(os.getenv("KENDR_HOME", "")).strip()
    if root:
        return str(os.path.expanduser(root))
    return os.path.join(os.path.expanduser("~"), ".kendr")


def _mcp_auth_ref(server_id: str) -> str:
    return build_secret_ref("mcp", server_id, "auth_token")


def _store_mcp_auth_token(server_id: str, auth_token: str) -> str:
    token = str(auth_token or "").strip()
    if not token:
        return ""
    if is_secret_ref(token):
        return token
    ref = _mcp_auth_ref(server_id)
    put_secret(ref, token)
    return ref


def _resolve_mcp_auth_token(server_id: str, raw_auth_token: str, db_path: str) -> str:
    token = str(raw_auth_token or "").strip()
    if not token:
        return ""
    if is_secret_ref(token):
        value = get_secret(token, default="")
        return str(value or "")
    try:
        ref = _store_mcp_auth_token(server_id, token)
        with _connect(db_path) as conn:
            conn.execute("UPDATE mcp_servers SET auth_token=? WHERE server_id=?", (ref, server_id))
        return token
    except Exception:
        return token


def _unwrap_fastmcp_command(command: str, args: list[Any]) -> tuple[str, str] | None:
    cmd = str(command or "").strip().lower()
    argv = [str(arg or "").strip() for arg in (args or [])]
    if cmd not in {"uvx", "uv"}:
        return None
    if len(argv) < 3:
        return None
    if argv[0].lower() != "fastmcp" or argv[1].lower() != "run":
        return None
    target = argv[2].strip()
    if target.startswith("http://") or target.startswith("https://"):
        return "http", target
    return None


def _unwrap_fastmcp_connection(connection: str) -> tuple[str, str] | None:
    try:
        parts = shlex.split(str(connection or ""))
    except Exception:
        return None
    if not parts:
        return None
    return _unwrap_fastmcp_command(parts[0], parts[1:])


def _migrated_flag_path(db_path: str) -> str:
    resolved = resolve_db_path(db_path)
    digest = sha1(resolved.encode("utf-8"), usedforsecurity=False).hexdigest()[:12]
    return os.path.join(_kendr_home_dir(), f"mcp_migrated_{digest}.flag")


def _registry_json_candidates() -> list[str]:
    registry_json = os.path.join(_kendr_home_dir(), "mcp.json")
    legacy_json = os.path.join(_kendr_home_dir(), "mcp_registry.json")
    candidates = []
    for path in (registry_json, legacy_json):
        if path not in candidates:
            candidates.append(path)
    return candidates


def _read_registry_payload() -> tuple[str | None, dict | None]:
    candidates = []
    for path in _registry_json_candidates():
        if os.path.isfile(path):
            try:
                candidates.append((os.path.getmtime(path), path))
            except Exception:
                candidates.append((0.0, path))
    for _, path in sorted(candidates, reverse=True):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                payload = json.load(fh)
            if isinstance(payload, dict):
                return path, payload
        except Exception as exc:
            _log.warning("Failed to read MCP registry JSON %s: %s", path, exc)
    return None, None


def _normalize_registry_entry(server_name: str, raw: dict) -> dict | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("name") or raw.get("server_name") or server_name or "").strip()
    if not name:
        return None
    description = str(raw.get("description", "") or "").strip()
    auth_token = str(raw.get("auth_token", "") or "").strip()
    enabled = bool(raw.get("enabled", not bool(raw.get("disabled", False))))
    server_id = str(raw.get("id") or raw.get("server_id") or "").strip()

    if raw.get("command"):
        command = str(raw.get("command", "") or "").strip()
        args = raw.get("args", [])
        if not command or not isinstance(args, list):
            return None
        unwrapped = _unwrap_fastmcp_command(command, args)
        if unwrapped:
            server_type, connection = unwrapped
        else:
            connection = shlex.join([command, *[str(arg) for arg in args]])
            server_type = "stdio"
    else:
        connection = str(raw.get("connection") or raw.get("url") or raw.get("endpoint") or "").strip()
        server_type = str(raw.get("type") or "http").strip().lower() or "http"
        if server_type not in {"http", "stdio"}:
            server_type = "http"
    if not connection:
        return None
    return {
        "id": server_id,
        "name": name,
        "type": server_type,
        "connection": connection,
        "description": description,
        "auth_token": auth_token,
        "enabled": enabled,
    }


def _parse_registry_payload(payload: dict) -> list[dict]:
    entries: list[dict] = []
    if not isinstance(payload, dict):
        return entries
    raw_servers = payload.get("mcpServers")
    if isinstance(raw_servers, dict):
        for server_name, raw in raw_servers.items():
            entry = _normalize_registry_entry(server_name, raw)
            if entry:
                entries.append(entry)
        return entries
    legacy_servers = payload.get("servers")
    if isinstance(legacy_servers, dict):
        for server_name, raw in legacy_servers.items():
            entry = _normalize_registry_entry(server_name, raw)
            if entry:
                entries.append(entry)
    return entries


def _registry_payload_from_rows(rows: list[dict]) -> dict:
    mcp_servers: dict[str, dict] = {}
    used_keys: set[str] = set()
    for row in rows:
        key = str(row.get("name") or row.get("id") or "server").strip() or "server"
        if key in used_keys:
            key = f"{key}-{str(row.get('id', 'srv'))[:6]}"
        used_keys.add(key)
        entry: dict[str, Any]
        if row.get("type") == "stdio":
            try:
                parts = shlex.split(str(row.get("connection", "") or ""))
            except Exception:
                parts = []
            if parts:
                entry = {"command": parts[0], "args": parts[1:]}
            else:
                entry = {"command": str(row.get("connection", "") or ""), "args": []}
        else:
            entry = {"url": str(row.get("connection", "") or ""), "type": "http"}
        entry["id"] = str(row.get("id") or "")
        entry["disabled"] = not bool(row.get("enabled", True))
        if row.get("description"):
            entry["description"] = str(row.get("description") or "")
        mcp_servers[key] = entry
    return {"mcpServers": mcp_servers}


def _write_registry_payload(db_path: str = DB_PATH) -> None:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM mcp_servers ORDER BY LOWER(name)").fetchall()
    payload = _registry_payload_from_rows([_row_to_dict(r, db_path=db_path) for r in rows])
    for path in _registry_json_candidates():
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(payload, fh, indent=2, ensure_ascii=True)
                fh.write("\n")
        except Exception as exc:
            _log.warning("Failed to write MCP registry JSON %s: %s", path, exc)


def _normalize_fastmcp_rows(db_path: str = DB_PATH) -> None:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT server_id, type, connection FROM mcp_servers WHERE LOWER(type)='stdio'"
        ).fetchall()
        changed = False
        for row in rows:
            unwrapped = _unwrap_fastmcp_connection(str(row["connection"] or ""))
            if not unwrapped:
                continue
            server_type, connection = unwrapped
            conn.execute(
                "UPDATE mcp_servers SET type=?, connection=? WHERE server_id=?",
                (server_type, connection, str(row["server_id"])),
            )
            changed = True
    if changed:
        _write_registry_payload(db_path)


def _sync_db_from_registry_json(db_path: str = DB_PATH) -> None:
    initialize_db(db_path)
    _, payload = _read_registry_payload()
    if not payload:
        return
    entries = _parse_registry_payload(payload)
    has_registry_shape = isinstance(payload.get("mcpServers"), dict) or isinstance(payload.get("servers"), dict)
    if not entries and not has_registry_shape:
        return
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with _connect(db_path) as conn:
        existing_rows = conn.execute("SELECT * FROM mcp_servers").fetchall()
        existing_by_id = {str(row["server_id"]): row for row in existing_rows}
        existing_by_name = {str(row["name"]): str(row["server_id"]) for row in existing_rows}
        keep_ids: set[str] = set()
        for entry in entries:
            server_id = (
                entry.get("id")
                or existing_by_name.get(entry["name"])
                or sha1(
                    f"{entry['name']}\0{entry['type']}\0{entry['connection']}".encode("utf-8"),
                    usedforsecurity=False,
                ).hexdigest()[:12]
            )
            keep_ids.add(server_id)
            if server_id in existing_by_id:
                conn.execute(
                    """
                    UPDATE mcp_servers
                       SET name=?, type=?, connection=?, description=?, auth_token=?, enabled=?
                     WHERE server_id=?
                    """,
                    (
                        entry["name"],
                        entry["type"],
                        entry["connection"],
                        entry["description"],
                        _store_mcp_auth_token(server_id, entry["auth_token"]) if entry["auth_token"] else str(existing_by_id[server_id]["auth_token"] or ""),
                        1 if entry["enabled"] else 0,
                        server_id,
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO mcp_servers
                        (server_id, name, type, connection, description,
                         auth_token, enabled, tools_json, tool_count,
                         status, error, last_discovered, created_at)
                    VALUES (?,?,?,?,?,?,?,'[]',0,'unknown','','',?)
                    """,
                    (
                        server_id,
                        entry["name"],
                        entry["type"],
                        entry["connection"],
                        entry["description"],
                        _store_mcp_auth_token(server_id, entry["auth_token"]),
                        1 if entry["enabled"] else 0,
                        now,
                    ),
                )
        for server_id in existing_by_id:
            if server_id not in keep_ids:
                conn.execute("DELETE FROM mcp_servers WHERE server_id=?", (server_id,))


_DEFAULT_MCP_SERVERS: list[dict] = [
    {
        "id": "scpr-web-scraper",
        "name": "web-scraper (scpr)",
        "type": "stdio",
        "connection": "scpr mcp",
        "description": (
            "Converts any webpage to markdown. "
            "Install: npm install -g @cle-does-things/scpr  "
            "or  go install github.com/AstraBert/scpr@latest"
        ),
        "auth_token": "",
        "enabled": True,
    },
]

_DEFAULT_SERVER_IDS: frozenset[str] = frozenset(s["id"] for s in _DEFAULT_MCP_SERVERS)


def is_default_server(server_id: str) -> bool:
    return str(server_id) in _DEFAULT_SERVER_IDS


def _is_legacy_browser_use_connection(connection: str) -> bool:
    text = str(connection or "").strip().lower()
    if not text:
        return False
    return text.startswith("uvx --from browser-use[cli] browser-use --mcp") or text.startswith(
        "uvx browser-use --mcp"
    )


def _normalize_browser_use_rows(db_path: str = DB_PATH) -> None:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT server_id, name, type, connection FROM mcp_servers WHERE LOWER(type)='stdio'"
        ).fetchall()
        changed = False
        for row in rows:
            server_id = str(row["server_id"] or "").strip().lower()
            name = str(row["name"] or "").strip().lower()
            if server_id != "browser-use-mcp" and name != "browser-use":
                continue
            connection = str(row["connection"] or "")
            if not _is_legacy_browser_use_connection(connection):
                continue
            conn.execute(
                "UPDATE mcp_servers SET connection=? WHERE server_id=?",
                ("python -m browser_use --mcp", str(row["server_id"])),
            )
            changed = True
    if changed:
        _write_registry_payload(db_path)


def _row_to_dict(row, *, db_path: str = DB_PATH) -> dict:
    d = dict(row)
    tools_json = d.pop("tools_json", "[]") or "[]"
    try:
        d["tools"] = json.loads(tools_json)
    except Exception:
        d["tools"] = []
    d["enabled"] = bool(d.get("enabled", 1))
    d["tool_count"] = d.get("tool_count", 0) or 0
    d["id"] = d.pop("server_id")
    d["auth_token"] = _resolve_mcp_auth_token(d["id"], str(d.get("auth_token", "") or ""), db_path)
    d["is_default"] = d["id"] in _DEFAULT_SERVER_IDS
    return d


def _maybe_migrate(db_path: str = DB_PATH) -> None:
    migrated_flag = _migrated_flag_path(db_path)
    if os.path.exists(migrated_flag):
        return
    legacy_json = os.path.join(_kendr_home_dir(), "mcp_registry.json")
    if not os.path.isfile(legacy_json):
        try:
            os.makedirs(os.path.dirname(migrated_flag), exist_ok=True)
            open(migrated_flag, "w").close()
        except Exception:
            pass
        return
    try:
        with open(legacy_json, "r", encoding="utf-8") as fh:
            legacy = json.load(fh)
        servers = legacy.get("servers", {})
        if servers:
            initialize_db(db_path)
            with _connect(db_path) as conn:
                existing = {
                    r["server_id"]
                    for r in conn.execute("SELECT server_id FROM mcp_servers").fetchall()
                }
                for srv in servers.values():
                    sid = srv.get("id") or srv.get("server_id", "")
                    if not sid or sid in existing:
                        continue
                    conn.execute(
                        """
                        INSERT OR IGNORE INTO mcp_servers
                            (server_id, name, type, connection, description,
                             auth_token, enabled, tools_json, tool_count,
                             status, error, last_discovered, created_at)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                        """,
                        (
                            sid,
                            srv.get("name", ""),
                            srv.get("type", "http"),
                            srv.get("connection", ""),
                            srv.get("description", ""),
                            _store_mcp_auth_token(sid, str(srv.get("auth_token", "") or "")),
                            1 if srv.get("enabled", True) else 0,
                            json.dumps(srv.get("tools", [])),
                            srv.get("tool_count", 0),
                            srv.get("status", "unknown"),
                            srv.get("error") or "",
                            srv.get("last_discovered") or "",
                            srv.get("created_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
                        ),
                    )
        _log.info("MCP registry migrated from JSON (%d servers)", len(servers))
        try:
            os.makedirs(os.path.dirname(migrated_flag), exist_ok=True)
            open(migrated_flag, "w").close()
        except Exception:
            pass
    except Exception as exc:
        _log.warning("MCP JSON migration failed (will retry next run): %s", exc)


def _seed_default_servers(db_path: str = DB_PATH) -> None:
    """Insert built-in default MCP servers the first time Kendr runs.

    Each default entry is inserted only once, identified by its stable ``id``.
    If the user later removes an entry it will NOT be re-added (the seed flag
    for that id is written after insertion).
    """
    seed_flag_dir = _kendr_home_dir()
    os.makedirs(seed_flag_dir, exist_ok=True)

    initialize_db(db_path)
    for server in _DEFAULT_MCP_SERVERS:
        sid = server["id"]
        flag = os.path.join(seed_flag_dir, f"mcp_seeded_{sid}.flag")
        if os.path.exists(flag):
            continue  # already seeded (or user removed it intentionally)
        with _connect(db_path) as conn:
            existing = conn.execute(
                "SELECT 1 FROM mcp_servers WHERE server_id=? OR LOWER(name)=?",
                (sid, server["name"].lower()),
            ).fetchone()
        if existing:
            # Server already present — just write the flag so we don't check again
            try:
                open(flag, "w").close()
            except Exception:
                pass
            continue
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        with _connect(db_path) as conn:
            conn.execute(
                """
                INSERT INTO mcp_servers
                    (server_id, name, type, connection, description,
                     auth_token, enabled, tools_json, tool_count,
                     status, error, last_discovered, created_at)
                VALUES (?,?,?,?,?,?,?,'[]',0,'unknown','','',?)
                """,
                (
                    sid,
                    server["name"],
                    server["type"],
                    server["connection"],
                    server["description"],
                    _store_mcp_auth_token(sid, server["auth_token"]),
                    1 if server["enabled"] else 0,
                    now,
                ),
            )
        _log.info("Seeded default MCP server: %s", server["name"])
        _write_registry_payload(db_path)
        try:
            open(flag, "w").close()
        except Exception:
            pass
        # Best-effort tool discovery so the server is immediately usable
        try:
            from kendr.mcp_manager import discover_tools as _discover
            _discover(sid)
        except Exception as exc:
            _log.debug("Auto-discovery for %s skipped: %s", server["name"], exc)


def list_mcp_servers(db_path: str = DB_PATH) -> list[dict]:
    initialize_db(db_path)
    _maybe_migrate(db_path)
    _seed_default_servers(db_path)
    _normalize_fastmcp_rows(db_path)
    _normalize_browser_use_rows(db_path)
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM mcp_servers ORDER BY LOWER(name)"
        ).fetchall()
    return [_row_to_dict(r, db_path=db_path) for r in rows]


def get_mcp_server(server_id: str, db_path: str = DB_PATH) -> dict | None:
    initialize_db(db_path)
    _maybe_migrate(db_path)
    _normalize_fastmcp_rows(db_path)
    _normalize_browser_use_rows(db_path)
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM mcp_servers WHERE server_id=?", (server_id,)
        ).fetchone()
    return _row_to_dict(row, db_path=db_path) if row else None


def add_mcp_server(
    server_id: str,
    name: str,
    connection: str,
    server_type: str = "http",
    description: str = "",
    auth_token: str = "",
    enabled: bool = True,
    db_path: str = DB_PATH,
) -> dict:
    initialize_db(db_path)
    _maybe_migrate(db_path)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO mcp_servers
                (server_id, name, type, connection, description,
                 auth_token, enabled, tools_json, tool_count,
                 status, error, last_discovered, created_at)
            VALUES (?,?,?,?,?,?,?,'[]',0,'unknown','','',?)
            """,
            (
                server_id,
                name,
                server_type,
                connection,
                description,
                _store_mcp_auth_token(server_id, auth_token),
                1 if enabled else 0,
                now,
            ),
        )
    _write_registry_payload(db_path)
    return get_mcp_server(server_id, db_path) or {}


def remove_mcp_server(server_id: str, db_path: str = DB_PATH) -> bool:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        row = conn.execute("SELECT auth_token FROM mcp_servers WHERE server_id=?", (server_id,)).fetchone()
    old_value = str(row["auth_token"] or "") if row else ""
    with _connect(db_path) as conn:
        changed = conn.execute(
            "DELETE FROM mcp_servers WHERE server_id=?", (server_id,)
        ).rowcount
    if changed > 0:
        if is_secret_ref(old_value):
            delete_secret(old_value)
        _write_registry_payload(db_path)
    return changed > 0


def toggle_mcp_server(server_id: str, enabled: bool, db_path: str = DB_PATH) -> bool:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        changed = conn.execute(
            "UPDATE mcp_servers SET enabled=? WHERE server_id=?",
            (1 if enabled else 0, server_id),
        ).rowcount
    if changed > 0:
        _write_registry_payload(db_path)
    return changed > 0


def update_mcp_server_tools(
    server_id: str,
    tools: list[dict],
    status: str,
    error: str | None,
    last_discovered: str,
    db_path: str = DB_PATH,
) -> bool:
    initialize_db(db_path)
    with _connect(db_path) as conn:
        changed = conn.execute(
            """
            UPDATE mcp_servers
               SET tools_json=?, tool_count=?, status=?, error=?, last_discovered=?
             WHERE server_id=?
            """,
            (
                json.dumps(tools),
                len(tools),
                status,
                error or "",
                last_discovered,
                server_id,
            ),
        ).rowcount
    return changed > 0
