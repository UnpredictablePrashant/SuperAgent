from __future__ import annotations

import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable

from kendr.unicode_utils import sanitize_text


_LOG = logging.getLogger(__name__)


sqlite3.register_adapter(str, sanitize_text)


def _repo_root() -> Path:
    # .../kendr/persistence/core.py -> repo root
    return Path(__file__).resolve().parents[2]


def resolve_db_path(db_path: str = "") -> str:
    """Resolve the runtime SQLite path to a single absolute location.

    Priority:
    1) explicit argument
    2) KENDR_DB_PATH
    3) KENDR_HOME/agent_workflow.sqlite3
    4) <repo_root>/output/agent_workflow.sqlite3
    """
    explicit = str(db_path or "").strip()
    if explicit:
        return str(Path(explicit).expanduser().resolve())

    env_override = str(os.getenv("KENDR_DB_PATH", "")).strip()
    if env_override:
        return str(Path(env_override).expanduser().resolve())

    kendr_home = str(os.getenv("KENDR_HOME", "")).strip()
    if kendr_home:
        return str((Path(kendr_home).expanduser().resolve() / "agent_workflow.sqlite3"))

    return str((_repo_root() / "output" / "agent_workflow.sqlite3").resolve())


DB_PATH = resolve_db_path()


_MIGRATION_LOCK = threading.Lock()
_MIGRATED_PRIMARY_DB_PATHS: set[str] = set()
_INITIALIZE_LOCK = threading.Lock()
_INITIALIZED_PRIMARY_DB_PATHS: set[str] = set()
_MIGRATION_TABLE_NAME = "_db_migration_sources"
_CORE_TABLES = (
    "runs",
    "agent_cards",
    "tasks",
    "messages",
    "artifacts",
    "agent_executions",
    "run_checkpoints",
    "channel_sessions",
    "task_sessions",
    "scheduled_jobs",
    "notifications",
    "monitor_rules",
    "monitor_events",
    "heartbeat_events",
    "intent_candidates",
    "execution_plans",
    "plan_tasks",
    "task_dependencies",
    "orchestration_events",
    "setup_components",
    "setup_config_values",
    "setup_provider_tokens",
    "privileged_audit_events",
    "superrag_sessions",
    "superrag_ingestions",
    "superrag_chat_messages",
    "mcp_servers",
    "capabilities",
    "capability_relations",
    "auth_profiles",
    "policy_profiles",
    "capability_health_runs",
    "capability_audit_events",
    "user_skills",
    "assistants",
    "approval_grants",
)


def _parse_bool_env(name: str, default: bool) -> bool:
    raw = str(os.getenv(name, "")).strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def _candidate_legacy_db_paths(primary_db_path: str, extra_paths: Iterable[str] | None = None) -> list[str]:
    primary = str(Path(primary_db_path).expanduser().resolve())
    candidates: dict[str, None] = {}

    def _add(path_value: str) -> None:
        value = str(path_value or "").strip()
        if not value:
            return
        try:
            resolved = str(Path(value).expanduser().resolve())
        except Exception:
            return
        if resolved == primary:
            return
        if not os.path.isfile(resolved):
            return
        candidates[resolved] = None

    explicit_sources = [str(entry or "").strip() for entry in list(extra_paths or []) if str(entry or "").strip()]
    # Explicit migration sources take precedence.
    for entry in explicit_sources:
        _add(entry)
    if explicit_sources:
        return list(candidates.keys())

    env_legacy = str(os.getenv("KENDR_DB_LEGACY_PATHS", "")).strip()
    if env_legacy:
        for item in env_legacy.split(os.pathsep):
            _add(item)

    working_dir = str(os.getenv("KENDR_WORKING_DIR", "")).strip()
    implicit_targets = {
        str((Path.cwd() / "output" / "agent_workflow.sqlite3").resolve()),
        str((_repo_root() / "output" / "agent_workflow.sqlite3").resolve()),
    }
    if working_dir:
        implicit_targets.add(str((Path(working_dir).expanduser().resolve() / "output" / "agent_workflow.sqlite3")))

    # Only auto-scan the common workspace output locations when the target DB
    # itself lives in one of those locations. Explicit/custom DB paths should
    # not silently ingest unrelated workspace databases.
    if primary in implicit_targets:
        for candidate in implicit_targets:
            _add(candidate)

    # Optional recursive search roots for one-time consolidation.
    recursive_enabled = _parse_bool_env("KENDR_DB_ENABLE_RECURSIVE_SEARCH", False)
    search_roots_raw = str(os.getenv("KENDR_DB_SEARCH_ROOTS", "")).strip()
    search_roots: list[Path] = []
    if search_roots_raw:
        for item in search_roots_raw.split(os.pathsep):
            if str(item or "").strip():
                search_roots.append(Path(item).expanduser())
    elif recursive_enabled and working_dir:
        search_roots.append(Path(working_dir).expanduser())

    for root in search_roots:
        try:
            resolved_root = root.resolve()
            if not resolved_root.exists():
                continue
            for match in resolved_root.glob("**/agent_workflow.sqlite3"):
                _add(str(match))
        except Exception:
            continue

    return list(candidates.keys())


def _ensure_parent_dir(db_path: str):
    parent = os.path.dirname(resolve_db_path(db_path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def _pragma_scalar(row: object) -> str:
    if row is None:
        return ""
    if isinstance(row, sqlite3.Row):
        try:
            return str(next(iter(row))).strip()
        except Exception:
            values = list(row)
            return str(values[0]).strip() if values else ""
    if isinstance(row, (tuple, list)):
        return str(row[0]).strip() if row else ""
    return str(row).strip()


def _apply_connection_pragmas(conn: sqlite3.Connection, resolved_db_path: str) -> str:
    conn.execute("PRAGMA busy_timeout = 30000")

    journal_mode = ""
    wal_error: Exception | None = None
    try:
        journal_mode = _pragma_scalar(conn.execute("PRAGMA journal_mode = WAL").fetchone()).lower()
    except sqlite3.OperationalError as exc:
        wal_error = exc

    if wal_error is not None:
        _LOG.warning(
            "WAL mode unavailable for %s: %s. Falling back to DELETE journal mode.",
            resolved_db_path,
            wal_error,
        )
    elif journal_mode and journal_mode != "wal":
        _LOG.warning(
            "SQLite kept journal_mode=%s for %s instead of WAL. Falling back to DELETE journal mode.",
            journal_mode,
            resolved_db_path,
        )

    if wal_error is not None or journal_mode != "wal":
        try:
            fallback_mode = _pragma_scalar(conn.execute("PRAGMA journal_mode = DELETE").fetchone()).lower()
            journal_mode = fallback_mode or "delete"
        except sqlite3.OperationalError as exc:
            _LOG.warning(
                "DELETE journal mode fallback failed for %s: %s. Continuing with SQLite defaults.",
                resolved_db_path,
                exc,
            )
            journal_mode = journal_mode or "unknown"

    try:
        conn.execute("PRAGMA synchronous = NORMAL")
    except sqlite3.OperationalError as exc:
        _LOG.warning(
            "SQLite synchronous pragma failed for %s: %s. Continuing with SQLite defaults.",
            resolved_db_path,
            exc,
        )
    return journal_mode or "unknown"


@contextmanager
def _connect(db_path: str = DB_PATH):
    resolved_db_path = resolve_db_path(db_path)
    _ensure_parent_dir(resolved_db_path)
    conn = sqlite3.connect(resolved_db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        _apply_connection_pragmas(conn, resolved_db_path)
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


def _table_names(conn: sqlite3.Connection) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    names: set[str] = set()
    for row in rows:
        if isinstance(row, sqlite3.Row):
            names.add(str(row["name"]))
        else:
            names.add(str(row[0]))
    return names


def _table_columns_any(conn: sqlite3.Connection, table_name: str) -> list[str]:
    table_ref = str(table_name or "").strip()
    db_name = "main"
    bare_table = table_ref
    if "." in table_ref:
        maybe_db, maybe_table = table_ref.split(".", 1)
        if maybe_db and maybe_table:
            db_name = maybe_db
            bare_table = maybe_table
    rows = conn.execute(f'PRAGMA "{db_name}".table_info("{bare_table}")').fetchall()
    cols: list[str] = []
    for row in rows:
        if isinstance(row, sqlite3.Row):
            cols.append(str(row["name"]))
        else:
            cols.append(str(row[1]))
    return cols


def _ensure_migration_table(conn: sqlite3.Connection) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {_MIGRATION_TABLE_NAME} (
            source_path TEXT PRIMARY KEY,
            source_mtime REAL,
            migrated_at TEXT
        )
        """
    )


def _copy_common_rows(dst: sqlite3.Connection, src_path: str) -> tuple[int, list[str]]:
    copied_total = 0
    copied_tables: list[str] = []
    alias = f"legacy_db_{abs(hash(src_path)) % 1_000_000_000}"
    dst.execute(f"ATTACH DATABASE ? AS {alias}", (src_path,))
    try:
        src_tables = {
            str(row[0])
            for row in dst.execute(f"SELECT name FROM {alias}.sqlite_master WHERE type='table'").fetchall()
        }
        for table_name in _CORE_TABLES:
            if table_name not in src_tables:
                continue
            dst_cols = _table_columns_any(dst, table_name)
            src_cols = _table_columns_any(dst, f"{alias}.{table_name}")
            common_cols = [col for col in src_cols if col in dst_cols]
            if not common_cols:
                continue
            quoted_cols = ", ".join(f'"{col}"' for col in common_cols)
            before = dst.total_changes
            dst.execute(
                f'INSERT OR IGNORE INTO "{table_name}" ({quoted_cols}) '
                f'SELECT {quoted_cols} FROM {alias}."{table_name}"'
            )
            inserted = dst.total_changes - before
            if inserted > 0:
                copied_total += int(inserted)
                copied_tables.append(table_name)
        # SQLite can reject DETACH during an active write transaction.
        dst.commit()
    finally:
        dst.execute(f"DETACH DATABASE {alias}")
    return copied_total, copied_tables


def migrate_legacy_databases(
    db_path: str = DB_PATH,
    *,
    legacy_paths: Iterable[str] | None = None,
    delete_legacy: bool = False,
) -> dict:
    resolved_db_path = resolve_db_path(db_path)
    migrated: list[dict] = []
    skipped: list[str] = []

    with _connect(resolved_db_path) as conn:
        _ensure_migration_table(conn)
        seen_rows = conn.execute(
            f"SELECT source_path, source_mtime FROM {_MIGRATION_TABLE_NAME}"
        ).fetchall()
        seen: dict[str, float] = {}
        for row in seen_rows:
            if isinstance(row, sqlite3.Row):
                seen[str(row["source_path"])] = float(row["source_mtime"] or 0.0)
            else:
                seen[str(row[0])] = float(row[1] or 0.0)

        for source in _candidate_legacy_db_paths(resolved_db_path, legacy_paths):
            try:
                source_path = str(Path(source).expanduser().resolve())
                source_mtime = float(os.path.getmtime(source_path))
            except Exception:
                skipped.append(source)
                continue

            if source_path in seen and float(seen.get(source_path, 0.0)) >= source_mtime:
                skipped.append(source_path)
                continue

            try:
                inserted, touched_tables = _copy_common_rows(conn, source_path)
                conn.execute(
                    f"""
                    INSERT INTO {_MIGRATION_TABLE_NAME}(source_path, source_mtime, migrated_at)
                    VALUES(?, ?, datetime('now'))
                    ON CONFLICT(source_path) DO UPDATE SET
                        source_mtime=excluded.source_mtime,
                        migrated_at=excluded.migrated_at
                    """,
                    (source_path, source_mtime),
                )
                migrated.append({
                    "source_path": source_path,
                    "rows_inserted": inserted,
                    "tables": touched_tables,
                })
            except Exception as exc:
                _LOG.warning("Skipping legacy DB migration from %s: %s", source_path, exc)
                skipped.append(source_path)
                continue

    if delete_legacy:
        for item in migrated:
            source_path = str(item.get("source_path", "")).strip()
            if not source_path:
                continue
            for candidate in (source_path, source_path + "-wal", source_path + "-shm"):
                try:
                    if os.path.isfile(candidate):
                        os.remove(candidate)
                except Exception:
                    continue

    return {
        "target_db_path": resolved_db_path,
        "migrated": migrated,
        "skipped": skipped,
        "deleted_legacy": bool(delete_legacy),
    }


def list_legacy_databases(db_path: str = DB_PATH, *, legacy_paths: Iterable[str] | None = None) -> list[str]:
    return _candidate_legacy_db_paths(resolve_db_path(db_path), legacy_paths)


def _migrate_legacy_databases_once(db_path: str) -> None:
    resolved_db_path = resolve_db_path(db_path)
    if not _parse_bool_env("KENDR_DB_AUTO_MIGRATE", True):
        return
    with _MIGRATION_LOCK:
        if resolved_db_path in _MIGRATED_PRIMARY_DB_PATHS:
            return
        _MIGRATED_PRIMARY_DB_PATHS.add(resolved_db_path)
    delete_legacy = _parse_bool_env("KENDR_DB_DELETE_LEGACY", False)
    try:
        result = migrate_legacy_databases(
            resolved_db_path,
            delete_legacy=delete_legacy,
        )
        if result.get("migrated"):
            _LOG.info(
                "Migrated %d legacy DB source(s) into %s",
                len(result["migrated"]),
                resolved_db_path,
            )
    except Exception as exc:
        with _MIGRATION_LOCK:
            _MIGRATED_PRIMARY_DB_PATHS.discard(resolved_db_path)
        _LOG.warning("Legacy DB auto-migration skipped for %s: %s", resolved_db_path, exc)


def _bootstrap_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                workflow_id TEXT,
                attempt_id TEXT,
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
                completed_at TEXT,
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
                workflow_id TEXT,
                attempt_id TEXT,
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

            CREATE TABLE IF NOT EXISTS mcp_servers (
                server_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                type TEXT NOT NULL DEFAULT 'http',
                connection TEXT NOT NULL,
                description TEXT DEFAULT '',
                auth_token TEXT DEFAULT '',
                enabled INTEGER NOT NULL DEFAULT 1,
                tools_json TEXT DEFAULT '[]',
                tool_count INTEGER DEFAULT 0,
                status TEXT DEFAULT 'unknown',
                error TEXT DEFAULT '',
                last_discovered TEXT DEFAULT '',
                created_at TEXT NOT NULL
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

            CREATE TABLE IF NOT EXISTS capabilities (
                capability_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                type TEXT NOT NULL,
                capability_key TEXT NOT NULL,
                name TEXT NOT NULL,
                description TEXT NOT NULL,
                owner_user_id TEXT NOT NULL,
                status TEXT NOT NULL,
                visibility TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                tags_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                schema_in_json TEXT NOT NULL DEFAULT '{}',
                schema_out_json TEXT NOT NULL DEFAULT '{}',
                auth_profile_id TEXT,
                policy_profile_id TEXT,
                health_status TEXT NOT NULL DEFAULT 'unknown',
                health_last_checked_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_capabilities_workspace_key_version
                ON capabilities (workspace_id, capability_key, version);
            CREATE INDEX IF NOT EXISTS idx_capabilities_workspace_type_status
                ON capabilities (workspace_id, type, status);

            CREATE TABLE IF NOT EXISTS capability_relations (
                relation_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                parent_capability_id TEXT NOT NULL,
                child_capability_id TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_capability_relations_parent
                ON capability_relations (workspace_id, parent_capability_id);
            CREATE INDEX IF NOT EXISTS idx_capability_relations_child
                ON capability_relations (workspace_id, child_capability_id);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_capability_relations_unique
                ON capability_relations (workspace_id, parent_capability_id, child_capability_id, relation_type);

            CREATE TABLE IF NOT EXISTS auth_profiles (
                auth_profile_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                auth_type TEXT NOT NULL,
                provider TEXT NOT NULL,
                secret_ref TEXT NOT NULL,
                scopes_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_auth_profiles_workspace_provider
                ON auth_profiles (workspace_id, provider);

            CREATE TABLE IF NOT EXISTS policy_profiles (
                policy_profile_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                name TEXT NOT NULL,
                rules_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_policy_profiles_workspace_name
                ON policy_profiles (workspace_id, name);

            CREATE TABLE IF NOT EXISTS capability_health_runs (
                health_run_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                capability_id TEXT NOT NULL,
                status TEXT NOT NULL,
                latency_ms INTEGER,
                error TEXT,
                checked_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_capability_health_runs_capability
                ON capability_health_runs (workspace_id, capability_id, checked_at);

            CREATE TABLE IF NOT EXISTS capability_audit_events (
                audit_event_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                capability_id TEXT,
                actor_user_id TEXT NOT NULL,
                action TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_capability_audit_events_workspace_created
                ON capability_audit_events (workspace_id, created_at);

            CREATE TABLE IF NOT EXISTS user_skills (
                skill_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                slug TEXT UNIQUE NOT NULL,
                description TEXT DEFAULT '',
                category TEXT DEFAULT 'Custom',
                icon TEXT DEFAULT '',
                skill_type TEXT NOT NULL DEFAULT 'catalog',
                catalog_id TEXT DEFAULT '',
                code TEXT DEFAULT '',
                input_schema TEXT DEFAULT '{}',
                output_schema TEXT DEFAULT '{}',
                is_installed INTEGER DEFAULT 0,
                status TEXT DEFAULT 'active',
                tags TEXT DEFAULT '[]',
                metadata TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_user_skills_slug ON user_skills (slug);
            CREATE INDEX IF NOT EXISTS idx_user_skills_type_installed ON user_skills (skill_type, is_installed);

            CREATE TABLE IF NOT EXISTS approval_grants (
                grant_id TEXT PRIMARY KEY,
                subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                manifest_hash TEXT NOT NULL,
                scope TEXT NOT NULL,
                session_id TEXT DEFAULT '',
                actor TEXT NOT NULL,
                note TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                permissions_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_used_at TEXT,
                use_count INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS idx_approval_grants_subject_manifest
                ON approval_grants (subject_type, subject_id, manifest_hash, status);
            CREATE INDEX IF NOT EXISTS idx_approval_grants_session
                ON approval_grants (session_id, status, updated_at);

            CREATE TABLE IF NOT EXISTS assistants (
                assistant_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                owner_user_id TEXT NOT NULL,
                slug TEXT NOT NULL UNIQUE,
                name TEXT NOT NULL,
                description TEXT DEFAULT '',
                goal TEXT DEFAULT '',
                system_prompt TEXT DEFAULT '',
                model_provider TEXT DEFAULT '',
                model_name TEXT DEFAULT '',
                routing_policy TEXT DEFAULT 'balanced',
                status TEXT DEFAULT 'draft',
                attached_capabilities_json TEXT DEFAULT '[]',
                memory_config_json TEXT DEFAULT '{}',
                metadata_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                last_tested_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_assistants_workspace_status
                ON assistants (workspace_id, status, updated_at);
            CREATE INDEX IF NOT EXISTS idx_assistants_workspace_slug
                ON assistants (workspace_id, slug);

            CREATE TABLE IF NOT EXISTS intent_candidates (
                intent_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                objective_signature TEXT NOT NULL,
                intent_type TEXT NOT NULL,
                label TEXT NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                selected INTEGER NOT NULL DEFAULT 0,
                execution_mode TEXT NOT NULL DEFAULT 'adaptive',
                requires_planner INTEGER NOT NULL DEFAULT 0,
                risk_level TEXT NOT NULL DEFAULT 'low',
                reasons_json TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            );
            CREATE INDEX IF NOT EXISTS idx_intent_candidates_run_created
                ON intent_candidates (run_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_intent_candidates_run_signature
                ON intent_candidates (run_id, objective_signature);

            CREATE TABLE IF NOT EXISTS execution_plans (
                plan_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                intent_id TEXT DEFAULT '',
                version INTEGER NOT NULL DEFAULT 1,
                status TEXT NOT NULL DEFAULT 'draft',
                approval_status TEXT NOT NULL DEFAULT 'not_started',
                needs_clarification INTEGER NOT NULL DEFAULT 0,
                objective TEXT NOT NULL DEFAULT '',
                summary TEXT NOT NULL DEFAULT '',
                plan_markdown TEXT NOT NULL DEFAULT '',
                plan_json TEXT NOT NULL DEFAULT '{}',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_execution_plans_run_version
                ON execution_plans (run_id, version);
            CREATE INDEX IF NOT EXISTS idx_execution_plans_run_updated
                ON execution_plans (run_id, updated_at DESC);

            CREATE TABLE IF NOT EXISTS plan_tasks (
                plan_task_id TEXT PRIMARY KEY,
                plan_id TEXT NOT NULL,
                run_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                parent_step_id TEXT DEFAULT '',
                step_index INTEGER NOT NULL DEFAULT 0,
                title TEXT NOT NULL DEFAULT '',
                agent_name TEXT NOT NULL DEFAULT '',
                task_content TEXT NOT NULL DEFAULT '',
                success_criteria TEXT NOT NULL DEFAULT '',
                rationale TEXT NOT NULL DEFAULT '',
                parallel_group TEXT NOT NULL DEFAULT '',
                side_effect_level TEXT NOT NULL DEFAULT 'unknown',
                conflict_keys_json TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'pending',
                lease_owner TEXT DEFAULT '',
                lease_expires_at TEXT,
                attempt_count INTEGER NOT NULL DEFAULT 0,
                last_attempt_at TEXT,
                started_at TEXT,
                completed_at TEXT,
                result_summary TEXT,
                error_text TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(plan_id) REFERENCES execution_plans(plan_id),
                FOREIGN KEY(run_id) REFERENCES runs(run_id)
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_plan_tasks_plan_step
                ON plan_tasks (plan_id, step_id);
            CREATE INDEX IF NOT EXISTS idx_plan_tasks_run_status
                ON plan_tasks (run_id, status, step_index);

            CREATE TABLE IF NOT EXISTS task_dependencies (
                plan_id TEXT NOT NULL,
                step_id TEXT NOT NULL,
                depends_on_step_id TEXT NOT NULL,
                PRIMARY KEY (plan_id, step_id, depends_on_step_id),
                FOREIGN KEY(plan_id) REFERENCES execution_plans(plan_id)
            );
            CREATE INDEX IF NOT EXISTS idx_task_dependencies_plan_step
                ON task_dependencies (plan_id, step_id);

            CREATE TABLE IF NOT EXISTS orchestration_events (
                event_id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL,
                plan_id TEXT DEFAULT '',
                subject_type TEXT NOT NULL,
                subject_id TEXT NOT NULL,
                event_type TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT '',
                source TEXT NOT NULL DEFAULT '',
                timestamp TEXT NOT NULL,
                payload_json TEXT NOT NULL DEFAULT '{}',
                FOREIGN KEY(run_id) REFERENCES runs(run_id),
                FOREIGN KEY(plan_id) REFERENCES execution_plans(plan_id)
            );
            CREATE INDEX IF NOT EXISTS idx_orchestration_events_run_time
                ON orchestration_events (run_id, timestamp DESC);
            CREATE INDEX IF NOT EXISTS idx_orchestration_events_subject
                ON orchestration_events (subject_type, subject_id, timestamp DESC);
        """
    )
    _ensure_column(conn, "runs", "workflow_id", "TEXT")
    _ensure_column(conn, "runs", "attempt_id", "TEXT")
    _ensure_column(conn, "task_sessions", "workflow_id", "TEXT")
    _ensure_column(conn, "task_sessions", "attempt_id", "TEXT")
    _ensure_column(conn, "runs", "updated_at", "TEXT")
    _ensure_column(conn, "runs", "working_directory", "TEXT")
    _ensure_column(conn, "runs", "run_output_dir", "TEXT")
    _ensure_column(conn, "runs", "session_id", "TEXT")
    _ensure_column(conn, "runs", "parent_run_id", "TEXT")
    _ensure_column(conn, "runs", "resumable", "INTEGER")
    _ensure_column(conn, "runs", "checkpoint_json", "TEXT")
    _ensure_column(conn, "agent_executions", "completed_at", "TEXT")
    _ensure_column(conn, "plan_tasks", "side_effect_level", "TEXT NOT NULL DEFAULT 'unknown'")
    _ensure_column(conn, "plan_tasks", "conflict_keys_json", "TEXT NOT NULL DEFAULT '[]'")
    _ensure_column(conn, "plan_tasks", "lease_owner", "TEXT DEFAULT ''")
    _ensure_column(conn, "plan_tasks", "lease_expires_at", "TEXT")
    _ensure_column(conn, "plan_tasks", "attempt_count", "INTEGER NOT NULL DEFAULT 0")
    _ensure_column(conn, "plan_tasks", "last_attempt_at", "TEXT")


def _is_retryable_bootstrap_error(exc: sqlite3.OperationalError) -> bool:
    message = str(exc).strip().lower()
    retryable_markers = (
        "database is locked",
        "database schema is locked",
        "database table is locked",
        "database busy",
        "locking protocol",
    )
    return any(marker in message for marker in retryable_markers)


def initialize_db(db_path: str = DB_PATH):
    resolved_db_path = resolve_db_path(db_path)
    if resolved_db_path in _INITIALIZED_PRIMARY_DB_PATHS and os.path.isfile(resolved_db_path):
        _migrate_legacy_databases_once(resolved_db_path)
        return

    attempts_raw = str(os.getenv("KENDR_DB_INIT_RETRIES", "")).strip()
    delay_raw = str(os.getenv("KENDR_DB_INIT_RETRY_DELAY_SECONDS", "")).strip()
    try:
        attempts = max(1, int(attempts_raw or "3"))
    except ValueError:
        attempts = 3
    try:
        base_delay = max(0.0, float(delay_raw or "0.1"))
    except ValueError:
        base_delay = 0.1

    with _INITIALIZE_LOCK:
        if resolved_db_path in _INITIALIZED_PRIMARY_DB_PATHS and os.path.isfile(resolved_db_path):
            _migrate_legacy_databases_once(resolved_db_path)
            return

        for attempt in range(attempts):
            try:
                with _connect(resolved_db_path) as conn:
                    _bootstrap_schema(conn)
                _INITIALIZED_PRIMARY_DB_PATHS.add(resolved_db_path)
                break
            except sqlite3.OperationalError as exc:
                if not _is_retryable_bootstrap_error(exc) or attempt >= attempts - 1:
                    raise
                sleep_for = base_delay * (2 ** attempt)
                _LOG.warning(
                    "SQLite bootstrap locked for %s (attempt %d/%d): %s. Retrying in %.2fs.",
                    resolved_db_path,
                    attempt + 1,
                    attempts,
                    exc,
                    sleep_for,
                )
                time.sleep(sleep_for)
    _migrate_legacy_databases_once(resolved_db_path)
