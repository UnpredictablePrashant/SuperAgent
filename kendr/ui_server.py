from __future__ import annotations

import cgi
import html as _html
import http.client
import json
import logging
import os
import queue
import re
import shlex
import subprocess
import tempfile
import threading
import time
import traceback
from datetime import datetime, timezone

import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from urllib.parse import parse_qs, urlparse

_log = logging.getLogger("kendr.ui")
from kendr.chat_context import (
    build_chat_context_block as _build_chat_context_block,
    build_chat_summary_markdown as _build_chat_summary_markdown,
    estimate_token_count as _estimate_chat_tokens,
    normalize_chat_messages as _normalize_chat_messages,
    summary_file_path as _chat_summary_file_path,
)
from kendr.path_utils import bundled_resource_path, normalize_host_path_str

from tasks.setup_config_store import (
    apply_setup_env_defaults,
    export_env_lines,
    get_setup_component_snapshot,
    save_component_values,
    set_component_enabled,
    setup_overview,
)
from kendr.machine_index import machine_sync_details, machine_sync_status, run_machine_sync

try:
    from kendr.persistence import (
        create_assistant as _db_create_assistant,
        cleanup_stale_runs as _db_cleanup_stale_runs,
        delete_assistant as _db_delete_assistant,
        delete_chat_session as _db_delete_chat_session,
        delete_run as _db_delete_run,
        get_assistant as _db_get_assistant,
        get_channel_session as _db_get_channel_session,
        list_agent_executions_for_run as _list_run_steps,
        list_assistants as _db_list_assistants,
        list_artifacts_for_run as _list_run_artifacts,
        list_run_messages as _db_list_run_messages,
        get_run as _db_get_run,
        update_assistant as _db_update_assistant,
        upsert_channel_session as _db_upsert_channel_session,
    )
    from kendr.persistence.run_store import get_run_output_dir_from_manifest as _get_run_output_dir_from_manifest
    _HAS_PERSISTENCE = True
except Exception:
    _HAS_PERSISTENCE = False
    def _db_cleanup_stale_runs(**kw):  # type: ignore[misc]
        return 0
    def _db_create_assistant(**kw):  # type: ignore[misc]
        return {}
    def _db_delete_assistant(assistant_id, **kw):  # type: ignore[misc]
        return False
    def _db_delete_chat_session(chat_session_id, **kw):  # type: ignore[misc]
        return {"deleted_runs": [], "deleted_dirs": [], "errors": []}
    def _db_delete_run(run_id, **kw):  # type: ignore[misc]
        return {"ok": True, "deleted_run": run_id, "errors": []}
    def _db_get_assistant(assistant_id, **kw):  # type: ignore[misc]
        return None
    def _db_get_channel_session(session_key, **kw):  # type: ignore[misc]
        return None
    def _db_list_assistants(**kw):  # type: ignore[misc]
        return []
    def _list_run_steps(run_id):  # type: ignore[misc]
        return []
    def _list_run_artifacts(run_id):  # type: ignore[misc]
        return []
    def _db_list_run_messages(run_id, **kw):  # type: ignore[misc]
        return []
    def _db_get_run(run_id):  # type: ignore[misc]
        return None
    def _db_upsert_channel_session(session_key, payload, **kw):  # type: ignore[misc]
        return None
    def _db_update_assistant(assistant_id, **kw):  # type: ignore[misc]
        return None
    def _get_run_output_dir_from_manifest(run_id, **kw):  # type: ignore[misc]
        return ""

try:
    from kendr.providers import (
        build_google_oauth_config,
        build_google_oauth_start_url,
        build_microsoft_oauth_config,
        build_microsoft_oauth_start_url,
        build_slack_oauth_config,
        build_slack_oauth_start_url,
        exchange_google_oauth_code,
        exchange_microsoft_oauth_code,
        exchange_slack_oauth_code,
    )
    from kendr.setup import issue_oauth_state_token
    _HAS_OAUTH = True
except Exception:
    _HAS_OAUTH = False

try:
    from kendr.setup.catalog import INTEGRATION_DEFINITIONS as _INTEGRATION_DEFS
    _OAUTH_PATH_MAP: dict[str, str] = {
        d.id: d.oauth_start_path
        for d in _INTEGRATION_DEFS
        if getattr(d, "oauth_start_path", "")
    }
except Exception:
    _OAUTH_PATH_MAP = {}

_UI_PORT = int(os.getenv("KENDR_UI_PORT", "2151"))
_UI_HOST = os.getenv("KENDR_UI_HOST", "127.0.0.1")


def _configure_ui_logging() -> str:
    log_path = str(os.getenv("KENDR_UI_LOG_PATH", "") or "").strip()
    if not log_path:
        return ""

    resolved = os.path.abspath(os.path.expanduser(log_path))
    os.makedirs(os.path.dirname(resolved), exist_ok=True)
    root_logger = logging.getLogger()
    if not any(
        isinstance(handler, RotatingFileHandler)
        and os.path.abspath(getattr(handler, "baseFilename", "")) == resolved
        for handler in root_logger.handlers
    ):
        max_bytes = int(str(os.getenv("KENDR_UI_LOG_MAX_BYTES", "2097152") or "2097152"))
        backup_count = int(str(os.getenv("KENDR_UI_LOG_BACKUP_COUNT", "3") or "3"))
        handler = RotatingFileHandler(
            resolved,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        root_logger.addHandler(handler)

    level_name = str(os.getenv("KENDR_LOG_LEVEL", "info") or "info").upper()
    level = getattr(logging, level_name, logging.INFO)
    root_logger.setLevel(level)
    _log.setLevel(level)
    return resolved

try:
    from kendr.mcp_manager import (
        list_servers_safe as _mcp_list_servers,
        get_server as _mcp_get_server,
        add_server as _mcp_add_server,
        remove_server as _mcp_remove_server,
        toggle_server as _mcp_toggle_server,
        discover_tools as _mcp_discover_tools,
        SCAFFOLD_CODE as _MCP_SCAFFOLD_CODE,
    )
    _HAS_MCP_MANAGER = True
except Exception as _mcp_import_exc:
    _HAS_MCP_MANAGER = False
    _log.warning("MCP manager not available: %s", _mcp_import_exc)

try:
    from kendr.project_manager import (
        list_projects as _pm_list_projects,
        get_active_project as _pm_get_active,
        set_active_project as _pm_set_active,
        add_project as _pm_add_project,
        remove_project as _pm_remove_project,
        delete_project_and_files as _pm_delete_files,
        get_project as _pm_get_project,
        init_project_from_scratch as _pm_init_project,
        read_file_tree as _pm_file_tree,
        read_file_content as _pm_read_file,
        run_shell as _pm_shell,
        list_project_services as _pm_list_services,
        start_project_service as _pm_start_service,
        stop_project_service as _pm_stop_service,
        restart_project_service as _pm_restart_service,
        read_project_service_log as _pm_read_service_log,
        git_status as _pm_git_status,
        git_pull as _pm_git_pull,
        git_push as _pm_git_push,
        git_add_all as _pm_git_add,
        git_commit as _pm_git_commit,
        git_commit_and_push as _pm_git_commit_push,
        git_clone as _pm_git_clone,
        git_branches as _pm_git_branches,
        git_checkout as _pm_git_checkout,
    )
    _HAS_PROJECT_MANAGER = True
except Exception as _pm_import_exc:
    _HAS_PROJECT_MANAGER = False
    _log.warning("Project manager not available: %s", _pm_import_exc)

try:
    from kendr.rag_manager import (
        list_kbs as _rag_list_kbs,
        get_kb as _rag_get_kb,
        get_active_kb as _rag_get_active_kb,
        set_active_kb as _rag_set_active_kb,
        create_kb as _rag_create_kb,
        delete_kb as _rag_delete_kb,
        update_kb_field as _rag_update_kb,
        add_source as _rag_add_source,
        remove_source as _rag_remove_source,
        upload_file_to_kb as _rag_upload_file,
        update_vector_config as _rag_update_vector,
        update_reranker_config as _rag_update_reranker,
        toggle_agent as _rag_toggle_agent,
        index_kb as _rag_index_kb,
        get_index_job as _rag_get_index_job,
        query_kb as _rag_query_kb,
        generate_answer as _rag_generate_answer,
        kb_status as _rag_kb_status,
        get_supported_agents as _rag_get_agents,
    )
    _HAS_RAG = True
except Exception as _rag_import_exc:
    _HAS_RAG = False
    _log.warning("RAG manager not available: %s", _rag_import_exc)

_GATEWAY_HOST = os.getenv("GATEWAY_HOST", "127.0.0.1")
_GATEWAY_PORT = int(os.getenv("GATEWAY_PORT", "8790"))


def _gateway_url() -> str:
    return f"http://{_GATEWAY_HOST}:{_GATEWAY_PORT}"


def _gateway_long_timeout_seconds() -> float | None:
    raw = str(os.getenv("KENDR_GATEWAY_LONG_TIMEOUT_SECONDS", "21600") or "").strip()
    if not raw:
        return 21600.0
    try:
        timeout = float(raw)
    except Exception:
        return 21600.0
    return None if timeout <= 0 else timeout


def _assistant_workspace_id(body: dict | None = None, parsed=None) -> str:
    if isinstance(body, dict):
        raw = str(body.get("workspace_id") or body.get("workspace") or "").strip()
        if raw:
            return raw
    if parsed is not None:
        params = parse_qs(parsed.query or "")
        raw = str((params.get("workspace_id") or params.get("workspace") or [""])[0] or "").strip()
        if raw:
            return raw
    return "default"


def _assistant_local_paths(memory_config: dict | None) -> list[str]:
    config = memory_config if isinstance(memory_config, dict) else {}
    values = config.get("local_paths") or config.get("paths") or []
    if not isinstance(values, list):
        return []
    return [normalize_host_path_str(str(item or "").strip()) for item in values if str(item or "").strip()]


def _collect_local_attachment_notes(local_paths: list[str]) -> list[str]:
    notes: list[str] = []
    for raw_path in local_paths[:8]:
        candidate = normalize_host_path_str(str(raw_path or "").strip())
        if not candidate:
            continue
        try:
            if os.path.isfile(candidate):
                with open(candidate, "r", encoding="utf-8", errors="replace") as fh:
                    excerpt = fh.read(2000)
                notes.append(
                    f"=== Attached file: {os.path.basename(candidate)} ===\nPath: {candidate}\n{excerpt}"
                )
            elif os.path.isdir(candidate):
                entries = sorted(os.listdir(candidate))[:40]
                notes.append(
                    f"=== Attached folder: {os.path.basename(candidate)} ===\nPath: {candidate}\nEntries: {entries}"
                )
        except Exception:
            notes.append(f"Attached path: {candidate}")
    return notes


def _assistant_system_prompt(assistant: dict) -> str:
    name = str(assistant.get("name", "") or "").strip() or "Untitled Assistant"
    description = str(assistant.get("description", "") or "").strip()
    goal = str(assistant.get("goal", "") or "").strip()
    system_prompt = str(assistant.get("system_prompt", "") or "").strip()
    routing_policy = str(assistant.get("routing_policy", "") or "balanced").strip()
    attached_capabilities = assistant.get("attached_capabilities") or []
    memory_config = assistant.get("memory_config") or {}

    lines = [
        f"You are {name}, a configured assistant inside Kendr.",
        "Answer directly, clearly, and practically.",
        f"Execution profile: {routing_policy}.",
    ]
    if description:
        lines.append(f"Description: {description}")
    if goal:
        lines.append(f"Primary goal: {goal}")
    if attached_capabilities:
        capability_labels = []
        for item in attached_capabilities[:12]:
            if isinstance(item, dict):
                label = str(item.get("name") or item.get("capability_key") or item.get("capability_id") or "").strip()
                if label:
                    capability_labels.append(label)
        if capability_labels:
            lines.append("Attached capabilities: " + ", ".join(capability_labels))
    if isinstance(memory_config, dict):
        summary = str(memory_config.get("summary") or memory_config.get("notes") or "").strip()
        if summary:
            lines.append(f"Memory guidance: {summary}")
    if system_prompt:
        lines.append("")
        lines.append("Additional instructions:")
        lines.append(system_prompt)
    return "\n".join(lines).strip()


def _normalize_mcp_add_payload(body: dict) -> list[dict]:
    def _clean_bool(value, default: bool) -> bool:
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        text = str(value).strip().lower()
        if text in {"1", "true", "yes", "on"}:
            return True
        if text in {"0", "false", "no", "off"}:
            return False
        return default

    def _normalize_entry(server_name: str, raw: dict) -> dict:
        if not isinstance(raw, dict):
            raise ValueError(f"Invalid MCP config for '{server_name}'")

        name = str(raw.get("name") or server_name or "").strip()
        if not name:
            raise ValueError("MCP server name is required")

        description = str(raw.get("description", "") or "").strip()
        auth_token = str(raw.get("auth_token", "") or "").strip()
        enabled = _clean_bool(raw.get("enabled"), not _clean_bool(raw.get("disabled"), False))

        if raw.get("command"):
            command = str(raw.get("command", "") or "").strip()
            if not command:
                raise ValueError(f"MCP server '{name}' is missing a command")
            args = raw.get("args", [])
            if args is None:
                args = []
            if not isinstance(args, list):
                raise ValueError(f"MCP server '{name}' has invalid args")
            cmd = command.lower()
            argv = [str(arg or "").strip() for arg in args]
            if (
                cmd in {"uvx", "uv"}
                and len(argv) >= 3
                and argv[0].lower() == "fastmcp"
                and argv[1].lower() == "run"
                and (argv[2].startswith("http://") or argv[2].startswith("https://"))
            ):
                connection = argv[2]
                server_type = "http"
            else:
                connection = shlex.join([command, *argv])
                server_type = "stdio"
        else:
            connection = str(
                raw.get("connection")
                or raw.get("url")
                or raw.get("endpoint")
                or ""
            ).strip()
            server_type = str(raw.get("type") or "http").strip().lower() or "http"
            if server_type not in {"http", "stdio"}:
                server_type = "http"

        if not connection:
            raise ValueError(f"MCP server '{name}' is missing a connection")

        return {
            "name": name,
            "connection": connection,
            "type": server_type,
            "description": description,
            "auth_token": auth_token,
            "enabled": enabled,
        }

    raw_config = body.get("config_json")
    if isinstance(raw_config, str) and raw_config.strip():
        try:
            parsed = json.loads(raw_config)
        except Exception as exc:
            raise ValueError(f"Invalid MCP JSON: {exc}") from exc
    else:
        parsed = body

    if not isinstance(parsed, dict):
        raise ValueError("MCP payload must be a JSON object")

    mcp_servers = parsed.get("mcpServers")
    if isinstance(mcp_servers, dict):
        entries = [_normalize_entry(server_name, raw) for server_name, raw in mcp_servers.items()]
        if not entries:
            raise ValueError("mcpServers is empty")
        return entries

    return [_normalize_entry(str(parsed.get("name", "") or ""), parsed)]


def _gateway_open_json(req: urllib.request.Request, *, timeout: float | None) -> dict | list:
    kwargs: dict[str, float] = {}
    if timeout is not None:
        kwargs["timeout"] = timeout
    with urllib.request.urlopen(req, **kwargs) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _gateway_ready(timeout: float = 1.0) -> bool:
    try:
        req = urllib.request.Request(f"{_gateway_url()}/health", method="GET")
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status == 200
    except Exception:
        return False


def _safe_upload_path_component(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._ -]+", "_", str(value or "").strip()).strip(" .")
    return cleaned[:120] or "item"


def _sanitize_relative_upload_path(value: str, fallback_name: str) -> str:
    raw = str(value or "").replace("\\", "/").strip("/")
    parts = []
    for item in raw.split("/"):
        cleaned = str(item or "").strip()
        if not cleaned or cleaned in {".", ".."}:
            continue
        parts.append(_safe_upload_path_component(cleaned))
    if not parts:
        parts = [_safe_upload_path_component(fallback_name or "upload.bin")]
    return os.path.join(*parts)


def _deep_research_upload_root(chat_id: str) -> str:
    safe_chat = _safe_upload_path_component(chat_id or "default-chat")
    root = os.path.abspath(os.path.join("output", "ui_deep_research_uploads", safe_chat))
    os.makedirs(root, exist_ok=True)
    return root


def _save_deep_research_upload_batch(
    *,
    chat_id: str,
    files: list[tuple[str, bytes]],
    relative_paths: list[str] | None = None,
) -> dict:
    batch_id = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    batch_dir = os.path.join(_deep_research_upload_root(chat_id), batch_id)
    os.makedirs(batch_dir, exist_ok=True)
    saved_files = []
    relative_paths = list(relative_paths or [])
    for index, (filename, data) in enumerate(files, start=1):
        preferred_rel = relative_paths[index - 1] if index - 1 < len(relative_paths) else filename
        safe_rel = _sanitize_relative_upload_path(preferred_rel, filename)
        dest = os.path.join(batch_dir, safe_rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(data)
        saved_files.append(
            {
                "name": os.path.basename(dest),
                "relative_path": safe_rel.replace("\\", "/"),
                "path": dest,
                "size": len(data),
            }
        )
    return {
        "upload_root": batch_dir,
        "file_count": len(saved_files),
        "saved_files": saved_files,
        "kind": "folder" if any("/" in item.get("relative_path", "") for item in saved_files) else "files",
    }


def _project_chat_session_key(project_id: str) -> str:
    return f"project_ui:{str(project_id or '').strip()}"


def _utc_now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _project_chat_guess_format(text: str) -> str:
    body = str(text or "")
    if not body.strip():
        return "text"
    patterns = (
        r"(?m)^\s{0,3}(#{1,6}\s|[-*+]\s|>\s|\d+\.\s|```)",
        r"\[[^\]]+\]\([^)]+\)",
        r"`[^`]+`",
        r"\*\*[^*]+\*\*",
        r"(?m)^\|.+\|",
    )
    return "markdown" if any(re.search(pattern, body) for pattern in patterns) else "text"


def _normalise_project_chat_message(message: dict) -> dict | None:
    role = str(message.get("role") or "system").strip().lower()
    if role not in {"user", "agent", "system"}:
        role = "system"
    content = str(message.get("content") or message.get("text") or "")
    if not content and role != "system":
        return None
    content_format = str(message.get("content_format") or "").strip().lower()
    if content_format not in {"text", "markdown"}:
        content_format = _project_chat_guess_format(content)
    created_at = str(message.get("created_at") or "").strip() or _utc_now_iso()
    message_id = str(message.get("message_id") or "").strip() or f"msg-{int(time.time() * 1000)}-{uuid.uuid4().hex[:8]}"
    item = {
        "message_id": message_id,
        "role": role,
        "content": content,
        "content_format": content_format,
        "created_at": created_at,
    }
    if message.get("run_id"):
        item["run_id"] = str(message.get("run_id"))
    if message.get("long_document_exports") and isinstance(message["long_document_exports"], list):
        item["long_document_exports"] = message["long_document_exports"]
    if message.get("deep_research_result_card") and isinstance(message["deep_research_result_card"], dict):
        item["deep_research_result_card"] = message["deep_research_result_card"]
    return item


def _load_project_chat_history(project_id: str) -> dict:
    project_id = str(project_id or "").strip()
    if not project_id:
        return {"project_id": "", "project_path": "", "project_name": "", "messages": [], "updated_at": ""}
    if not _HAS_PERSISTENCE:
        return {"project_id": project_id, "project_path": "", "project_name": "", "messages": [], "updated_at": ""}
    row = _db_get_channel_session(_project_chat_session_key(project_id))
    state = dict((row or {}).get("state") or {})
    messages = []
    for raw_message in state.get("messages") or []:
        normalised = _normalise_project_chat_message(raw_message or {})
        if normalised is not None:
            messages.append(normalised)
    updated_at = str(state.get("updated_at") or (row or {}).get("updated_at") or "").strip()
    return {
        "project_id": project_id,
        "project_path": str(state.get("project_path") or "").strip(),
        "project_name": str(state.get("project_name") or "").strip(),
        "messages": messages[-200:],
        "updated_at": updated_at,
    }


def _save_project_chat_history(
    project_id: str,
    *,
    project_path: str = "",
    project_name: str = "",
    messages: list[dict] | None = None,
) -> dict:
    project_id = str(project_id or "").strip()
    if not project_id:
        return {"project_id": "", "project_path": "", "project_name": "", "messages": [], "updated_at": ""}
    existing = _load_project_chat_history(project_id)
    normalised_messages = []
    for raw_message in messages or []:
        normalised = _normalise_project_chat_message(raw_message or {})
        if normalised is not None:
            normalised_messages.append(normalised)
    updated_at = _utc_now_iso()
    payload = {
        "project_id": project_id,
        "project_path": str(project_path or existing.get("project_path") or "").strip(),
        "project_name": str(project_name or existing.get("project_name") or "").strip(),
        "messages": normalised_messages[-200:],
        "updated_at": updated_at,
    }
    if _HAS_PERSISTENCE:
        _db_upsert_channel_session(
            _project_chat_session_key(project_id),
            {
                "channel": "project_ui",
                "chat_id": project_id,
                "sender_id": "ui_user",
                "workspace_id": payload["project_path"],
                "is_group": False,
                "state": payload,
                "updated_at": updated_at,
            },
        )
    return payload


def _append_project_chat_messages(
    project_id: str,
    *,
    project_path: str = "",
    project_name: str = "",
    messages: list[dict],
) -> dict:
    existing = _load_project_chat_history(project_id)
    merged = list(existing.get("messages") or [])
    for raw_message in messages or []:
        normalised = _normalise_project_chat_message(raw_message or {})
        if normalised is not None:
            merged.append(normalised)
    return _save_project_chat_history(
        project_id,
        project_path=project_path or str(existing.get("project_path") or ""),
        project_name=project_name or str(existing.get("project_name") or ""),
        messages=merged,
    )


def _resolve_project_chat_identity(
    project_id: str = "",
    project_path: str = "",
    project_name: str = "",
) -> tuple[str, str, str]:
    resolved_id = str(project_id or "").strip()
    resolved_path = str(project_path or "").strip()
    resolved_name = str(project_name or "").strip()
    project = None
    if _HAS_PROJECT_MANAGER:
        try:
            if resolved_id:
                project = _pm_get_project(resolved_id)
            elif resolved_path:
                project = next(
                    (item for item in _pm_list_projects() if str(item.get("path") or "").strip() == resolved_path),
                    None,
                )
            elif _pm_get_active():
                active = _pm_get_active() or {}
                project = active if (
                    resolved_name and str(active.get("name") or "").strip() == resolved_name
                ) else active
        except Exception:
            project = None
    if project:
        resolved_id = resolved_id or str(project.get("id") or "").strip()
        resolved_path = resolved_path or str(project.get("path") or "").strip()
        resolved_name = resolved_name or str(project.get("name") or "").strip()
    return resolved_id, resolved_path, resolved_name


def _project_chat_result_text(result: dict) -> str:
    if not isinstance(result, dict):
        return str(result or "")
    for key in ("final_output", "output", "draft_response", "answer"):
        value = str(result.get(key) or "").strip()
        if value:
            return value
    summary = str(result.get("summary") or "").strip()
    if summary:
        return summary
    return ""


def _channel_session_key_from_payload(payload: dict) -> str:
    channel = str(payload.get("channel") or "webchat").strip().lower() or "webchat"
    workspace_id = str(payload.get("workspace_id") or "default").strip() or "default"
    sender_id = str(payload.get("sender_id") or "unknown").strip() or "unknown"
    chat_id = str(payload.get("chat_id") or sender_id or "unknown").strip() or sender_id or "unknown"
    scope = "group" if bool(payload.get("is_group", False)) else "main"
    return ":".join([channel, workspace_id, chat_id, scope])


def _summary_budget_tokens(context_limit: int | str | None) -> int:
    try:
        limit = int(context_limit or 0)
    except Exception:
        limit = 0
    if limit <= 0:
        return 2048
    return max(768, min(12000, int(limit * 0.2)))


def _load_channel_chat_context(payload: dict) -> dict:
    session_key = _channel_session_key_from_payload(payload)
    row = _db_get_channel_session(session_key) if _HAS_PERSISTENCE else None
    state = dict((row or {}).get("state") or {})
    history = _normalize_chat_messages(state.get("chat_history_messages") or [])
    summary_text = str(state.get("chat_summary_text") or "").strip()
    summary_file = str(state.get("chat_summary_file") or "").strip()
    return {
        "session_key": session_key,
        "row": row or {},
        "state": state,
        "history": history,
        "summary_text": summary_text,
        "summary_file": summary_file,
        "compaction_level": int(state.get("chat_summary_compaction_level", 0) or 0),
    }


def _sync_channel_chat_context(
    payload: dict,
    *,
    supplied_history: list[dict] | None = None,
    append_messages: list[dict] | None = None,
    context_limit: int | str | None = None,
    compact_increment: int = 0,
) -> dict:
    context = _load_channel_chat_context(payload)
    state = dict(context.get("state") or {})
    history = _normalize_chat_messages(context.get("history") or [])
    if isinstance(supplied_history, list) and supplied_history:
        history = _merge_chat_history(history, supplied_history)
    if append_messages:
        history = _merge_chat_history(history, append_messages)
    requested_level = max(0, int(state.get("chat_summary_compaction_level", 0) or 0) + int(compact_increment or 0))
    summary_text, effective_level = _build_chat_summary_markdown(
        history,
        requested_level=requested_level,
        max_tokens=_summary_budget_tokens(context_limit or state.get("chat_context_limit_tokens")),
    )
    summary_file = _chat_summary_file_path(str(context.get("session_key") or "default"))
    summary_file.parent.mkdir(parents=True, exist_ok=True)
    summary_file.write_text(summary_text, encoding="utf-8")

    state["chat_history_messages"] = history
    state["chat_summary_text"] = summary_text
    state["chat_summary_file"] = str(summary_file)
    state["chat_summary_updated_at"] = _utc_now_iso()
    state["chat_summary_compaction_level"] = effective_level
    if context_limit:
        try:
            state["chat_context_limit_tokens"] = int(context_limit)
        except Exception:
            pass
    if _HAS_PERSISTENCE:
        _db_upsert_channel_session(
            str(context.get("session_key") or ""),
            {
                "channel": str(payload.get("channel") or "webchat"),
                "chat_id": str(payload.get("chat_id") or ""),
                "sender_id": str(payload.get("sender_id") or "ui_user"),
                "workspace_id": str(payload.get("workspace_id") or ""),
                "is_group": bool(payload.get("is_group", False)),
                "state": state,
                "updated_at": _utc_now_iso(),
            },
        )
    return {
        **context,
        "state": state,
        "history": history,
        "summary_text": summary_text,
        "summary_file": str(summary_file),
        "compaction_level": effective_level,
        "summary_tokens": _estimate_chat_tokens(summary_text),
    }


def _merge_chat_history(existing: list[dict], incoming: list[dict]) -> list[dict]:
    left = _normalize_chat_messages(existing)
    right = _normalize_chat_messages(incoming)
    if not left:
        return right[-200:]
    if not right:
        return left[-200:]
    overlap = 0
    max_overlap = min(len(left), len(right))
    for size in range(max_overlap, 0, -1):
        if left[-size:] == right[:size]:
            overlap = size
            break
    merged = [*left, *right[overlap:]]
    return merged[-200:]


def _persist_channel_chat_turn(
    payload: dict,
    *,
    user_text: str,
    assistant_text: str,
    context_limit: int | str | None = None,
) -> dict:
    messages = []
    if str(user_text or "").strip():
        messages.append({"role": "user", "content": str(user_text).strip(), "created_at": _utc_now_iso()})
    if str(assistant_text or "").strip():
        messages.append({"role": "assistant", "content": str(assistant_text).strip(), "created_at": _utc_now_iso()})
    if not messages:
        return _load_channel_chat_context(payload)
    return _sync_channel_chat_context(
        payload,
        append_messages=messages,
        context_limit=context_limit,
    )


def _persist_project_chat_user_request(payload: dict, text: str) -> tuple[str, str, str]:
    channel = str(payload.get("channel") or "").strip().lower()
    if channel != "project_ui":
        return "", "", ""
    project_id, project_path, project_name = _resolve_project_chat_identity(
        str(payload.get("project_id") or "").strip(),
        str(payload.get("project_root") or payload.get("working_directory") or "").strip(),
        str(payload.get("project_name") or "").strip(),
    )
    if not project_id:
        return "", project_path, project_name
    try:
        _append_project_chat_messages(
            project_id,
            project_path=project_path,
            project_name=project_name,
            messages=[{
                "role": "user",
                "content": text,
                "content_format": _project_chat_guess_format(text),
            }],
        )
    except Exception as exc:
        _log.debug("Project chat user persistence failed for %s: %s", project_id, exc)
    return project_id, project_path, project_name


def _persist_project_chat_result(
    payload: dict,
    *,
    result: dict | None = None,
    error: str = "",
    run_id: str = "",
) -> None:
    channel = str(payload.get("channel") or "").strip().lower()
    if channel != "project_ui":
        return
    project_id, project_path, project_name = _resolve_project_chat_identity(
        str(payload.get("project_id") or "").strip(),
        str(payload.get("project_root") or payload.get("working_directory") or "").strip(),
        str(payload.get("project_name") or "").strip(),
    )
    if not project_id:
        return
    content = ""
    if error:
        content = "Error: " + str(error)
    else:
        content = _project_chat_result_text(result or {})
    if not content:
        return
    message: dict = {
        "role": "agent",
        "content": content,
        "content_format": _project_chat_guess_format(content),
        "run_id": run_id,
    }
    if result:
        doc_exports = result.get("long_document_exports")
        if doc_exports and isinstance(doc_exports, list):
            message["long_document_exports"] = doc_exports
        dr_card = result.get("deep_research_result_card")
        if dr_card and isinstance(dr_card, dict):
            message["deep_research_result_card"] = dr_card
    try:
        _append_project_chat_messages(
            project_id,
            project_path=project_path,
            project_name=project_name,
            messages=[message],
        )
    except Exception as exc:
        _log.debug("Project chat result persistence failed for %s: %s", project_id, exc)


def _resolve_run_artifact_path(run_id: str, name: str) -> str:
    file_path = ""
    try:
        run_row = _db_get_run(run_id)
        output_dir = run_row.get("run_output_dir", "") if run_row else ""
        if not output_dir:
            output_dir = _get_run_output_dir_from_manifest(run_id)
        if output_dir:
            candidate = os.path.join(output_dir, name)
            if os.path.isfile(candidate):
                return candidate
    except Exception:
        pass

    with _pending_lock:
        run_state = _pending_runs.get(run_id, {})
    result_data = run_state.get("result", {})
    for af in result_data.get("artifact_files", []):
        if af.get("name") == name:
            candidate = af.get("path", "")
            if candidate and os.path.isfile(candidate):
                return candidate

    for key in (
        "long_document_compiled_path",
        "long_document_compiled_html_path",
        "long_document_compiled_pdf_path",
        "long_document_compiled_docx_path",
    ):
        candidate = str(result_data.get(key) or "").strip()
        if candidate and os.path.basename(candidate) == name and os.path.isfile(candidate):
            return candidate
    return file_path


def _gateway_ingest(payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{_gateway_url()}/ingest",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    return _gateway_open_json(req, timeout=_gateway_long_timeout_seconds())


def _gateway_resume(payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{_gateway_url()}/resume",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    return _gateway_open_json(req, timeout=_gateway_long_timeout_seconds())


def _gateway_get(path: str, timeout: float = 5.0) -> dict | list:
    req = urllib.request.Request(f"{_gateway_url()}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _gateway_forward_json(
    method: str,
    path: str,
    *,
    payload: dict | None = None,
    timeout: float = 5.0,
) -> tuple[int, dict | list]:
    body = None
    headers: dict[str, str] = {}
    if payload is not None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(f"{_gateway_url()}{path}", data=body, method=method.upper(), headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw) if raw else {"error": exc.reason}
        except Exception:
            data = {"error": raw or str(exc.reason or "gateway_error")}
        return int(getattr(exc, "code", 500) or 500), data


def _gateway_refresh_mcp(timeout: float = 5.0) -> None:
    """POST /registry/mcp-refresh so the gateway re-registers MCP synthetic agents."""
    try:
        req = urllib.request.Request(
            f"{_gateway_url()}/registry/mcp-refresh",
            data=b"{}",
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=timeout):
            pass
    except Exception:
        pass


_pending_runs: dict[str, dict] = {}
_run_event_queues: dict[str, "queue.Queue[dict]"] = {}
_pending_lock = threading.Lock()
_ollama_pull_lock = threading.Lock()
_ollama_pull_state: dict[str, object] = {
    "active": False,
    "status": "idle",
    "model": "",
    "digest": "",
    "message": "",
    "error": "",
    "completed": 0,
    "total": 0,
    "started_at": "",
    "updated_at": "",
    "completed_at": "",
    "cancel_requested": False,
}
_OAUTH_PENDING_STATES: dict[str, str] = {}
_PENDING_TERMINAL_TTL_SECONDS = max(
    0,
    int(str(os.getenv("KENDR_UI_PENDING_TERMINAL_TTL_SECONDS", "180") or "180")),
)
_PENDING_TERMINAL_STATES = {"completed", "failed", "cancelled"}


def _run_control_dir() -> str:
    root = os.path.join(tempfile.gettempdir(), "kendr_run_controls")
    os.makedirs(root, exist_ok=True)
    return root


def _kill_switch_path_for_run(run_id: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", str(run_id or "").strip()) or "run"
    return os.path.join(_run_control_dir(), f"{safe}.stop")


def _ollama_base_url() -> str:
    return str(os.getenv("OLLAMA_BASE_URL", "http://localhost:11434") or "http://localhost:11434").strip().rstrip("/")


def _ollama_pull_public_state() -> dict[str, object]:
    with _ollama_pull_lock:
        state = dict(_ollama_pull_state)
    state = _sanitize_ollama_pull_state(state)
    return state


def _sanitize_ollama_pull_state(state: dict[str, object] | None) -> dict[str, object]:
    state = dict(state or {})
    state.pop("connection", None)
    state.pop("response", None)
    total = int(state.get("total") or 0)
    completed = int(state.get("completed") or 0)
    percent = 0.0
    if total > 0:
        percent = max(0.0, min(100.0, (completed / total) * 100.0))
    state["percent"] = percent
    state["cancellable"] = bool(state.get("active")) and str(state.get("status") or "") in {"starting", "running", "cancelling"}
    return state


def _set_ollama_pull_state(**updates: object) -> dict[str, object]:
    with _ollama_pull_lock:
        _ollama_pull_state.update(updates)
        _ollama_pull_state["updated_at"] = _utc_now_iso()
        return dict(_ollama_pull_state)


def _apply_ollama_pull_event(event: dict) -> dict[str, object]:
    if not isinstance(event, dict):
        return _ollama_pull_public_state()

    updates: dict[str, object] = {}
    status = str(event.get("status") or "").strip()
    digest = str(event.get("digest") or "").strip()
    if status:
        updates["message"] = status
        lowered = status.lower()
        if lowered in {"success", "verifying sha256 digest", "writing manifest", "removing any unused layers"}:
            updates["status"] = "running"
        elif "pulling" in lowered or "download" in lowered:
            updates["status"] = "running"
    if digest:
        updates["digest"] = digest
    total = event.get("total")
    completed = event.get("completed")
    if isinstance(total, (int, float)):
        updates["total"] = max(0, int(total))
    if isinstance(completed, (int, float)):
        updates["completed"] = max(0, int(completed))
    if str(event.get("status") or "").strip().lower() == "success":
        updates.update({
            "active": False,
            "status": "completed",
            "message": "Download complete",
            "completed_at": _utc_now_iso(),
        })
        final_total = int(updates.get("total") or _ollama_pull_state.get("total") or 0)
        if final_total > 0:
            updates["completed"] = final_total
    _set_ollama_pull_state(**updates)
    return _ollama_pull_public_state()


def _start_ollama_pull_job(model_name: str) -> tuple[bool, dict[str, object], int]:
    model = str(model_name or "").strip()
    if not model:
        return False, {"error": "missing_model"}, 400

    with _ollama_pull_lock:
        current_status = str(_ollama_pull_state.get("status") or "")
        if bool(_ollama_pull_state.get("active")) and current_status in {"starting", "running", "cancelling"}:
            current_model = str(_ollama_pull_state.get("model") or "").strip()
            current_pull = _sanitize_ollama_pull_state(_ollama_pull_state)
            return False, {
                "error": "pull_already_running",
                "detail": f"Model pull already in progress for {current_model or 'another model'}",
                "pull": current_pull,
            }, 409
        _ollama_pull_state.clear()
        _ollama_pull_state.update({
            "active": True,
            "status": "starting",
            "model": model,
            "digest": "",
            "message": "Starting download",
            "error": "",
            "completed": 0,
            "total": 0,
            "started_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
            "completed_at": "",
            "cancel_requested": False,
            "connection": None,
            "response": None,
        })

    def _run() -> None:
        conn: http.client.HTTPConnection | http.client.HTTPSConnection | None = None
        response: http.client.HTTPResponse | None = None
        try:
            parsed = urlparse(_ollama_base_url())
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"Invalid OLLAMA_BASE_URL: {_ollama_base_url()}")
            connection_cls = http.client.HTTPSConnection if parsed.scheme == "https" else http.client.HTTPConnection
            conn = connection_cls(parsed.netloc, timeout=60)
            target_path = (parsed.path.rstrip("/") or "") + "/api/pull"
            payload = json.dumps({"name": model, "stream": True}).encode("utf-8")
            conn.request("POST", target_path, body=payload, headers={"Content-Type": "application/json"})
            response = conn.getresponse()
            _set_ollama_pull_state(connection=conn, response=response, status="running", message="Connecting to Ollama")
            if response.status >= 400:
                raw = response.read().decode("utf-8", errors="replace").strip()
                raise RuntimeError(raw or f"Ollama pull failed ({response.status})")

            while True:
                line = response.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace").strip()
                if not decoded:
                    continue
                try:
                    event = json.loads(decoded)
                except Exception:
                    _set_ollama_pull_state(message=decoded, status="running")
                    continue
                if isinstance(event, dict):
                    _apply_ollama_pull_event(event)

            public_state = _ollama_pull_public_state()
            if str(public_state.get("status") or "") not in {"completed", "cancelled"}:
                _set_ollama_pull_state(
                    active=False,
                    status="completed",
                    message="Download complete",
                    completed_at=_utc_now_iso(),
                )
        except Exception as exc:
            public_state = _ollama_pull_public_state()
            cancelled = bool(public_state.get("cancel_requested"))
            _set_ollama_pull_state(
                active=False,
                status="cancelled" if cancelled else "failed",
                error="" if cancelled else str(exc),
                message="Download cancelled" if cancelled else "Download failed",
                completed_at=_utc_now_iso(),
            )
        finally:
            try:
                if response is not None:
                    response.close()
            except Exception:
                pass
            try:
                if conn is not None:
                    conn.close()
            except Exception:
                pass
            _set_ollama_pull_state(connection=None, response=None)

    threading.Thread(target=_run, daemon=True).start()
    return True, {"ok": True, "pull": _ollama_pull_public_state()}, 202


def _cancel_ollama_pull_job() -> tuple[bool, dict[str, object], int]:
    with _ollama_pull_lock:
        state = dict(_ollama_pull_state)
        if not bool(state.get("active")) or str(state.get("status") or "") not in {"starting", "running", "cancelling"}:
            return False, {"error": "pull_not_running", "pull": _sanitize_ollama_pull_state(state)}, 409
        _ollama_pull_state["cancel_requested"] = True
        _ollama_pull_state["status"] = "cancelling"
        _ollama_pull_state["message"] = "Cancelling download"
        _ollama_pull_state["updated_at"] = _utc_now_iso()
        response = _ollama_pull_state.get("response")
        connection = _ollama_pull_state.get("connection")
    try:
        if response is not None:
            response.close()
    except Exception:
        pass
    try:
        if connection is not None:
            connection.close()
    except Exception:
        pass
    return True, {"ok": True, "pull": _ollama_pull_public_state()}, 200


_MODEL_GUIDE_CACHE_TTL_SECONDS = 15 * 60
_MODEL_GUIDE_CACHE: dict[str, object] = {
    "fetched_at": 0.0,
    "payload": None,
}
_MODEL_GUIDE_LOCK = threading.Lock()

_OPENROUTER_RANKINGS_FALLBACK = [
    {"rank": 1, "name": "Qwen3.6 Plus (free)", "author": "qwen", "tokens": "1.66T", "share": "64%"},
    {"rank": 2, "name": "Deepseek V3.2", "author": "deepseek", "tokens": "1.27T", "share": "7%"},
    {"rank": 3, "name": "Claude Opus 4.6", "author": "anthropic", "tokens": "1.19T", "share": "17%"},
    {"rank": 4, "name": "Minimax M2.7", "author": "minimax", "tokens": "1.19T", "share": "0%"},
    {"rank": 5, "name": "Claude Sonnet 4.6", "author": "anthropic", "tokens": "1.16T", "share": "13%"},
    {"rank": 6, "name": "Minimax M2.5", "author": "minimax", "tokens": "1.10T", "share": "30%"},
    {"rank": 7, "name": "Gemini 3 Flash Preview", "author": "google", "tokens": "1.06T", "share": "8%"},
    {"rank": 8, "name": "Nemotron 3 Super 120B A12B (free)", "author": "nvidia", "tokens": "659B", "share": "43%"},
    {"rank": 9, "name": "Mimo V2 Pro", "author": "xiaomi", "tokens": "606B", "share": "80%"},
    {"rank": 10, "name": "Gemini 2.5 Flash", "author": "google", "tokens": "543B", "share": "14%"},
]

_OLLAMA_MODEL_GUIDE = [
    {
        "id": "llama3.2:latest",
        "label": "Llama 3.2",
        "access": "local",
        "family": "llama",
        "size_gb": 2.0,
        "min_memory_gb": 8,
        "speed": "fast",
        "cost": "free-local",
        "reasoning": "basic",
        "best_for": ["general chat", "offline fallback", "low-memory laptop"],
        "agent_fit": ["small helper agents", "drafting", "classification"],
        "notes": "Best cheap local default when machine small. Not best for heavy coding agents.",
    },
    {
        "id": "gemma4:4b",
        "label": "Gemma 4 4B",
        "access": "local",
        "family": "gemma",
        "size_gb": 9.6,
        "min_memory_gb": 16,
        "speed": "medium",
        "cost": "free-local",
        "reasoning": "good",
        "best_for": ["general work", "summaries", "light coding"],
        "agent_fit": ["planner", "research helper", "doc generation"],
        "notes": "Good balance if you can spare ~16 GB RAM and want stronger local quality.",
    },
    {
        "id": "qwen2.5-coder:7b",
        "label": "Qwen 2.5 Coder 7B",
        "access": "local",
        "family": "qwen",
        "size_gb": 4.7,
        "min_memory_gb": 12,
        "speed": "fast",
        "cost": "free-local",
        "reasoning": "good",
        "best_for": ["coding", "refactors", "CLI help"],
        "agent_fit": ["code agent", "fixer", "test writer"],
        "notes": "Best local coding-first pull for mid-range machine.",
    },
    {
        "id": "deepseek-r1:8b",
        "label": "DeepSeek R1 8B",
        "access": "local",
        "family": "deepseek",
        "size_gb": 4.9,
        "min_memory_gb": 12,
        "speed": "medium",
        "cost": "free-local",
        "reasoning": "strong",
        "best_for": ["reasoning", "math", "step-by-step work"],
        "agent_fit": ["reasoning agent", "analysis agent"],
        "notes": "Useful when you want better reasoning locally and can trade some speed.",
    },
    {
        "id": "kimi-k2.5:cloud",
        "label": "Kimi K2.5",
        "access": "cloud",
        "family": "kimi",
        "size_gb": 0,
        "min_memory_gb": 0,
        "speed": "medium",
        "cost": "paid-cloud",
        "reasoning": "frontier",
        "best_for": ["agent workflows", "coding with vision", "complex multi-step tasks"],
        "agent_fit": ["tool-using agents", "code agent", "multimodal agent"],
        "notes": "Runs through Ollama cloud alias. No local weights download; needs Ollama cloud access.",
    },
    {
        "id": "kimi-k2-thinking:cloud",
        "label": "Kimi K2 Thinking",
        "access": "cloud",
        "family": "kimi",
        "size_gb": 0,
        "min_memory_gb": 0,
        "speed": "slow",
        "cost": "paid-cloud",
        "reasoning": "frontier",
        "best_for": ["deep reasoning", "agent chains", "long-horizon coding"],
        "agent_fit": ["reasoning agent", "research agent", "debug agent"],
        "notes": "Cloud-only thinking model. Use with Ollama alias like any other model name.",
    },
    {
        "id": "glm-5:cloud",
        "label": "GLM 5",
        "access": "cloud",
        "family": "glm",
        "size_gb": 0,
        "min_memory_gb": 0,
        "speed": "medium",
        "cost": "paid-cloud",
        "reasoning": "frontier",
        "best_for": ["coding", "reasoning", "multilingual"],
        "agent_fit": ["code agent", "browser agent", "general agent"],
        "notes": "Strong cloud pick when you want agentic + coding focus without local RAM pressure.",
    },
    {
        "id": "minimax-m2.7:cloud",
        "label": "MiniMax M2.7",
        "access": "cloud",
        "family": "minimax",
        "size_gb": 0,
        "min_memory_gb": 0,
        "speed": "fast",
        "cost": "paid-cloud",
        "reasoning": "strong",
        "best_for": ["coding", "fast responses", "professional writing"],
        "agent_fit": ["code agent", "ops agent", "writer agent"],
        "notes": "High-usage cloud model on Ollama library; good if speed matters more than local-only.",
    },
]


def _detect_system_memory_gb() -> int:
    try:
        if hasattr(os, "sysconf"):
            page_size = int(os.sysconf("SC_PAGE_SIZE"))
            page_count = int(os.sysconf("SC_PHYS_PAGES"))
            total_bytes = page_size * page_count
            if total_bytes > 0:
                return max(1, int(round(total_bytes / (1024 ** 3))))
    except Exception:
        pass
    return 0


def _fetch_json(url: str, timeout: float = 2.0, headers: dict[str, str] | None = None) -> dict | list | None:
    req = urllib.request.Request(url, method="GET", headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="replace")
        return json.loads(raw)


def _fetch_text(url: str, timeout: float = 2.0, headers: dict[str, str] | None = None) -> str:
    req = urllib.request.Request(url, method="GET", headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _fetch_openrouter_models() -> tuple[list[dict], str]:
    try:
        payload = _fetch_json(
            "https://openrouter.ai/api/v1/models",
            timeout=2.5,
            headers={"User-Agent": "kendr-ui/1.0"},
        )
        items = payload.get("data") if isinstance(payload, dict) else []
        return items if isinstance(items, list) else [], ""
    except Exception as exc:
        return [], str(exc)


def _fetch_openrouter_rankings() -> tuple[list[dict], str]:
    try:
        html = _fetch_text(
            "https://openrouter.ai/rankings",
            timeout=2.5,
            headers={"User-Agent": "kendr-ui/1.0"},
        )
        pattern = re.compile(
            r">\s*(\d+)\.\s*<.*?>\s*([^<]+?)\s*</a>\s*.*?>\s*by\s*<.*?>\s*([^<]+?)\s*</a>\s*.*?([0-9.]+[TBM])\s*tokens\s*.*?([0-9]+%)",
            re.IGNORECASE | re.DOTALL,
        )
        rows: list[dict] = []
        for rank_text, name, author, tokens, share in pattern.findall(html):
            rank = int(rank_text)
            rows.append({
                "rank": rank,
                "name": re.sub(r"\s+", " ", name).strip(),
                "author": re.sub(r"\s+", " ", author).strip(),
                "tokens": tokens.strip(),
                "share": share.strip(),
            })
            if len(rows) >= 10:
                break
        return rows, ""
    except Exception as exc:
        return [], str(exc)


def _to_million_token_price(raw_value: object) -> float | None:
    try:
        value = float(str(raw_value or "0").strip())
    except Exception:
        return None
    if value < 0:
        return None
    return round(value * 1_000_000, 4)


def _format_price_band(prompt_price_per_million: float | None) -> str:
    if prompt_price_per_million is None:
        return "unknown"
    if prompt_price_per_million == 0:
        return "free"
    if prompt_price_per_million <= 0.5:
        return "very-low"
    if prompt_price_per_million <= 3:
        return "low"
    if prompt_price_per_million <= 10:
        return "mid"
    return "high"


def _normalize_openrouter_model(item: dict) -> dict:
    pricing = item.get("pricing") if isinstance(item.get("pricing"), dict) else {}
    architecture = item.get("architecture") if isinstance(item.get("architecture"), dict) else {}
    prompt_price = _to_million_token_price(pricing.get("prompt"))
    completion_price = _to_million_token_price(pricing.get("completion"))
    modalities_in = architecture.get("input_modalities") if isinstance(architecture.get("input_modalities"), list) else []
    supported_parameters = item.get("supported_parameters") if isinstance(item.get("supported_parameters"), list) else []
    return {
        "id": str(item.get("id") or "").strip(),
        "name": str(item.get("name") or item.get("id") or "").strip(),
        "context_length": int(item.get("context_length") or 0),
        "prompt_price_per_million": prompt_price,
        "completion_price_per_million": completion_price,
        "price_band": _format_price_band(prompt_price),
        "supports_tools": any(str(param).strip() in {"tools", "tool_choice"} for param in supported_parameters),
        "supports_structured_output": any(str(param).strip() == "response_format" for param in supported_parameters),
        "supports_vision": any(str(modality).strip() == "image" for modality in modalities_in),
    }


def _build_openrouter_comparison(openrouter_models: list[dict]) -> list[dict]:
    preferred = [
        "openai/gpt-5.4",
        "openai/gpt-5.4-mini",
        "anthropic/claude-opus-4.6",
        "anthropic/claude-sonnet-4.6",
        "google/gemini-2.5-flash",
        "google/gemini-2.5-pro",
        "qwen/qwen3.6-plus",
        "deepseek/deepseek-chat-v3.2",
        "minimax/minimax-m2.7",
    ]
    by_id = {
        str(item.get("id") or "").strip().lower(): _normalize_openrouter_model(item)
        for item in openrouter_models
        if isinstance(item, dict)
    }
    rows = [by_id[key] for key in preferred if key in by_id]
    if len(rows) >= 6:
        return rows[:6]
    extras = [value for key, value in by_id.items() if key not in {item["id"].lower() for item in rows}]
    extras.sort(key=lambda item: (item.get("price_band") != "free", -(item.get("context_length") or 0), item.get("name") or ""))
    return (rows + extras)[:6]


def _build_ollama_recommendations(pulled_models: list[dict]) -> list[dict]:
    pulled_names = {
        str(item.get("name") or "").strip().lower()
        for item in pulled_models
        if isinstance(item, dict) and str(item.get("name") or "").strip()
    }
    system_memory_gb = _detect_system_memory_gb()
    rows: list[dict] = []
    for item in _OLLAMA_MODEL_GUIDE:
        min_memory = int(item.get("min_memory_gb") or 0)
        access = str(item.get("access") or "local")
        fits = access == "cloud" or system_memory_gb <= 0 or system_memory_gb >= min_memory
        status = "pulled" if str(item.get("id") or "").strip().lower() in pulled_names else "available"
        rows.append({
            **item,
            "fits_system": fits,
            "fit_label": (
                "No local RAM limit"
                if access == "cloud"
                else (f"Fits {system_memory_gb} GB RAM" if fits and system_memory_gb > 0 else f"Needs about {min_memory}+ GB RAM")
            ),
            "status": status,
        })
    rows.sort(key=lambda item: (not item.get("fits_system"), item.get("access") != "local", item.get("status") == "pulled", item.get("min_memory_gb") or 0))
    return rows


def _build_model_guide_payload() -> dict[str, object]:
    from kendr.llm_router import is_ollama_running, list_ollama_models

    running = is_ollama_running()
    pulled_models = list_ollama_models() if running else []
    rankings, ranking_error = _fetch_openrouter_rankings()
    models, models_error = _fetch_openrouter_models()
    rankings_fresh = bool(rankings)
    if not rankings_fresh:
        rankings = list(_OPENROUTER_RANKINGS_FALLBACK)

    return {
        "generated_at": _utc_now_iso(),
        "system_memory_gb": _detect_system_memory_gb(),
        "ollama_running": running,
        "pulled_models": pulled_models,
        "recommendations": _build_ollama_recommendations(pulled_models),
        "openrouter_rankings": rankings,
        "rankings_source": "live" if rankings_fresh else "fallback",
        "openrouter_comparison": _build_openrouter_comparison(models),
        "cloud_usage": [
            {
                "title": "Cloud models in Ollama",
                "body": "Models ending with :cloud do not download full local weights. Ollama routes requests to the cloud model through the Ollama API surface, so you use the same model name in chat/run APIs.",
            },
            {
                "title": "How to run them",
                "body": "Use the same command shape as local models, for example ollama run kimi-k2.5:cloud or POST /api/chat with model kimi-k2.5:cloud.",
            },
            {
                "title": "When to choose them",
                "body": "Pick cloud aliases when your machine RAM is too small, when you need better reasoning or vision, or when agent workflows need stronger tool use than small local models can provide.",
            },
        ],
        "notes": {
            "rankings_error": ranking_error,
            "models_error": models_error,
        },
    }


def _get_model_guide(force: bool = False) -> dict[str, object]:
    now = time.time()
    with _MODEL_GUIDE_LOCK:
        cached_payload = _MODEL_GUIDE_CACHE.get("payload")
        fetched_at = float(_MODEL_GUIDE_CACHE.get("fetched_at") or 0.0)
        if not force and isinstance(cached_payload, dict) and (now - fetched_at) < _MODEL_GUIDE_CACHE_TTL_SECONDS:
            return dict(cached_payload)
    payload = _build_model_guide_payload()
    with _MODEL_GUIDE_LOCK:
        _MODEL_GUIDE_CACHE["payload"] = dict(payload)
        _MODEL_GUIDE_CACHE["fetched_at"] = now
    return payload


def _comparison_rows_from_provider_statuses(statuses: list[dict]) -> list[dict]:
    rows: list[dict] = []
    for status in statuses:
        if not isinstance(status, dict):
            continue
        source_provider = str(status.get("provider") or "").strip()
        configured_model = str(status.get("model") or "").strip()
        configured_models = {
            str(item or "").strip()
            for item in (status.get("configured_models") or [])
            if str(item or "").strip()
        }
        if configured_model:
            configured_models.add(configured_model)

        details = status.get("selectable_model_details")
        if not isinstance(details, list) or not details:
            fallback_name = configured_model
            if fallback_name:
                details = [{
                    "name": fallback_name,
                    "family": str(status.get("model_family") or source_provider or "").strip(),
                    "context_window": int(status.get("context_window") or 0),
                    "capabilities": dict(status.get("model_capabilities") or {}),
                    "agent_capable": bool(status.get("agent_capable")),
                }]
            else:
                details = []

        badges = status.get("model_badges") if isinstance(status.get("model_badges"), dict) else {}
        suggested_latest = next((model for model, tags in badges.items() if "latest" in (tags or [])), "—")
        suggested_best = next((model for model, tags in badges.items() if "best" in (tags or [])), "—")
        suggested_cheapest = next((model for model, tags in badges.items() if "cheapest" in (tags or [])), "—")
        note = str(status.get("note") or "").strip()
        model_fetch_error = str(status.get("model_fetch_error") or "").strip()

        for detail in details:
            if not isinstance(detail, dict):
                continue
            model_name = str(detail.get("name") or "").strip()
            if not model_name:
                continue
            family = str(detail.get("family") or status.get("model_family") or source_provider or "").strip()
            model_capabilities = detail.get("capabilities") if isinstance(detail.get("capabilities"), dict) else {}
            rows.append({
                "provider": family or source_provider,
                "source_provider": source_provider,
                "model": model_name,
                "model_badges": list(badges.get(model_name) or []),
                "status": (f"Error: {model_fetch_error}" if model_fetch_error else ("Ready" if status.get("ready") else note or "Not ready")),
                "context_window": int(detail.get("context_window") or status.get("context_window") or 0),
                "model_capabilities": model_capabilities,
                "agent_capable": bool(detail.get("agent_capable")),
                "selected": model_name == configured_model,
                "configured": model_name in configured_models,
                "suggested_latest": suggested_latest,
                "suggested_best": suggested_best,
                "suggested_cheapest": suggested_cheapest,
                "model_fetch_error": model_fetch_error,
            })

    rows.sort(
        key=lambda item: (
            0 if item.get("configured") else 1,
            0 if item.get("selected") else 1,
            str(item.get("provider") or ""),
            str(item.get("source_provider") or ""),
            str(item.get("model") or "").lower(),
        )
    )
    return rows


def _delete_ollama_model(model_name: str) -> tuple[bool, dict[str, object], int]:
    model = str(model_name or "").strip()
    if not model:
        return False, {"error": "missing_model"}, 400
    try:
        result = subprocess.run(
            ["ollama", "rm", model],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except FileNotFoundError:
        return False, {"error": "ollama_not_found"}, 500
    except Exception as exc:
        return False, {"error": str(exc)}, 500
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip() or f"ollama rm failed ({result.returncode})"
        return False, {"error": "delete_failed", "detail": detail}, 500
    with _MODEL_GUIDE_LOCK:
        _MODEL_GUIDE_CACHE["payload"] = None
        _MODEL_GUIDE_CACHE["fetched_at"] = 0.0
    return True, {"ok": True, "model": model}, 200


def _clear_kill_switch_file(path_value: str) -> None:
    target = str(path_value or "").strip()
    if not target:
        return
    try:
        if os.path.exists(target):
            os.remove(target)
    except Exception:
        pass


def _trigger_kill_switch_file(path_value: str) -> None:
    target = str(path_value or "").strip()
    if not target:
        return
    try:
        os.makedirs(os.path.dirname(target), exist_ok=True)
        with open(target, "w", encoding="utf-8") as handle:
            handle.write(_utc_now_iso())
    except Exception:
        pass


def _is_cancelled_error_message(message: str) -> bool:
    lowered = str(message or "").strip().lower()
    if not lowered:
        return False
    markers = (
        "kill switch triggered",
        "run stopped by user",
        "stopped by user",
        "cancelled by user",
        "run cancelled",
        "run canceled",
    )
    return any(marker in lowered for marker in markers)


def _terminal_run_status(*, result: dict | None = None, error: str = "", default: str = "completed") -> str:
    if _is_cancelled_error_message(error):
        return "cancelled"
    payload = result if isinstance(result, dict) else {}
    approval_request = payload.get("approval_request")
    if bool(
        payload.get("awaiting_user_input")
        or payload.get("plan_waiting_for_approval")
        or payload.get("plan_needs_clarification")
        or str(payload.get("approval_pending_scope", "")).strip()
        or (isinstance(approval_request, dict) and bool(approval_request))
        or str(payload.get("pending_user_question", "")).strip()
        or str(payload.get("pending_user_input_kind", "")).strip()
    ):
        return "awaiting_user_input"
    explicit = str(payload.get("status", "")).strip().lower()
    if explicit in {"cancelled", "canceled", "failed", "completed", "cancelling"}:
        return "cancelled" if explicit == "canceled" else explicit
    return default


def _run_log_paths(run_output_dir: str) -> dict[str, str]:
    base = str(run_output_dir or "").strip()
    if not base:
        return {}
    resolved = os.path.abspath(os.path.expanduser(base))
    return {
        "run_output_dir": resolved,
        "execution_log": os.path.join(resolved, "execution.log"),
        "agent_work_notes": os.path.join(resolved, "agent_work_notes.txt"),
        "final_output": os.path.join(resolved, "final_output.txt"),
        "privileged_audit": os.path.join(resolved, "privileged_audit.log"),
        "run_manifest": os.path.join(resolved, "run_manifest.json"),
        "checkpoint": os.path.join(resolved, "checkpoint.json"),
        "resume_summary": os.path.join(resolved, "resume_summary.json"),
        "heartbeat": os.path.join(resolved, "heartbeat.json"),
    }


def _prune_pending_runs_locked() -> None:
    if not _pending_runs:
        return
    if _PENDING_TERMINAL_TTL_SECONDS <= 0:
        for run_id, state in list(_pending_runs.items()):
            status = str((state or {}).get("status", "")).strip().lower()
            if status in _PENDING_TERMINAL_STATES:
                _pending_runs.pop(run_id, None)
        return
    now = datetime.now(timezone.utc)
    for run_id, state in list(_pending_runs.items()):
        status = str((state or {}).get("status", "")).strip().lower()
        if status not in _PENDING_TERMINAL_STATES:
            continue
        updated_at = str((state or {}).get("updated_at") or (state or {}).get("completed_at") or "").strip()
        updated_dt = _parse_iso_timestamp(updated_at)
        if updated_dt is None:
            _pending_runs.pop(run_id, None)
            continue
        if updated_dt.tzinfo is None:
            updated_dt = updated_dt.replace(tzinfo=timezone.utc)
        age_seconds = (now - updated_dt).total_seconds()
        if age_seconds >= _PENDING_TERMINAL_TTL_SECONDS:
            _pending_runs.pop(run_id, None)


def _push_event(run_id: str, event_type: str, data: dict) -> None:
    with _pending_lock:
        q = _run_event_queues.get(run_id)
    if q is not None:
        q.put({"type": event_type, "data": data})


def _pending_run_state(
    run_id: str,
    *,
    payload: dict | None = None,
    status: str = "running",
    result: dict | None = None,
    error: str = "",
) -> dict:
    now = _utc_now_iso()
    previous = _pending_runs.get(run_id, {})
    base_payload = payload or previous.get("payload") or {}
    resolved_status = str(status or previous.get("status") or "running").strip() or "running"
    started_at = str(previous.get("started_at") or now).strip() or now
    completed_at = ""
    if resolved_status not in {"running", "started", "cancelling"}:
        completed_at = str(previous.get("completed_at") or now).strip() or now
    result_data = result if isinstance(result, dict) else (previous.get("result") if isinstance(previous.get("result"), dict) else {})
    workflow_id = (
        str((result_data or {}).get("workflow_id", "")).strip()
        or str(base_payload.get("workflow_id", "")).strip()
        or str(previous.get("workflow_id", "")).strip()
        or run_id
    )
    attempt_id = (
        str((result_data or {}).get("attempt_id", "")).strip()
        or str(base_payload.get("attempt_id", "")).strip()
        or str(previous.get("attempt_id", "")).strip()
        or run_id
    )
    return {
        "run_id": run_id,
        "workflow_id": workflow_id,
        "attempt_id": attempt_id,
        "status": resolved_status,
        "started_at": started_at,
        "updated_at": now,
        "completed_at": completed_at,
        "payload": base_payload,
        "result": result if result is not None else previous.get("result"),
        "error": error or str(previous.get("error") or "").strip(),
    }


def _task_session_summary(task_session: dict | None) -> dict:
    if not isinstance(task_session, dict):
        return {}
    summary = task_session.get("summary")
    if isinstance(summary, dict):
        return summary
    raw = task_session.get("summary_json")
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            return {}
    return {}


def _overlay_run_with_pending(run_row: dict | None, pending: dict | None) -> dict | None:
    if not run_row and not pending:
        return None
    base = dict(run_row or {})
    pending = pending or {}
    payload = pending.get("payload") if isinstance(pending.get("payload"), dict) else {}
    if pending:
        base["run_id"] = base.get("run_id") or pending.get("run_id")
        base["workflow_id"] = (
            base.get("workflow_id")
            or pending.get("workflow_id")
            or payload.get("workflow_id")
            or base.get("run_id")
        )
        base["attempt_id"] = (
            base.get("attempt_id")
            or pending.get("attempt_id")
            or payload.get("attempt_id")
            or base.get("run_id")
        )
        base["status"] = pending.get("status") or base.get("status") or "running"
        base["started_at"] = pending.get("started_at") or base.get("started_at") or base.get("created_at") or ""
        base["updated_at"] = pending.get("updated_at") or base.get("updated_at") or base.get("started_at") or ""
        if pending.get("completed_at"):
            base["completed_at"] = pending.get("completed_at")
        elif str(base.get("status") or "").strip().lower() in {"running", "started"}:
            base["completed_at"] = ""
        if pending.get("error"):
            base["error"] = pending.get("error")
        if pending.get("result") is not None:
            base["result"] = pending.get("result")
    if payload:
        base["user_query"] = base.get("user_query") or payload.get("text") or payload.get("message") or ""
        base["working_directory"] = base.get("working_directory") or payload.get("working_directory") or payload.get("project_root") or ""
        base["resume_output_dir"] = base.get("resume_output_dir") or payload.get("output_folder") or payload.get("resume_output_dir") or ""
        resolved_session_id = str(base.get("session_id") or "").strip()
        if not resolved_session_id:
            payload_session_id = str(payload.get("session_id") or "").strip()
            if payload_session_id:
                resolved_session_id = payload_session_id
            else:
                channel = str(payload.get("channel") or "webchat").strip().lower() or "webchat"
                workspace_id = str(payload.get("workspace_id") or "default").strip() or "default"
                chat_id = str(payload.get("chat_id") or payload.get("sender_id") or "").strip()
                if chat_id:
                    scope = "group" if bool(payload.get("is_group")) else "main"
                    resolved_session_id = ":".join([channel, workspace_id, chat_id, scope])
        base["session_id"] = resolved_session_id
        base["channel"] = base.get("channel") or payload.get("channel") or ""
        base["workflow_id"] = base.get("workflow_id") or payload.get("workflow_id") or base.get("run_id") or ""
        base["attempt_id"] = base.get("attempt_id") or payload.get("attempt_id") or base.get("run_id") or ""
        base["workflow_type"] = base.get("workflow_type") or payload.get("workflow_type") or ""
        base["run_output_dir"] = (
            base.get("run_output_dir")
            or payload.get("output_folder")
            or payload.get("resume_output_dir")
            or ""
        )
    if str(base.get("run_output_dir") or "").strip():
        if not isinstance(base.get("log_paths"), dict) or not base.get("log_paths"):
            base["log_paths"] = _run_log_paths(str(base.get("run_output_dir") or ""))
    result = base.get("result") if isinstance(base.get("result"), dict) else {}
    if result:
        base["workflow_id"] = base.get("workflow_id") or result.get("workflow_id") or base.get("run_id") or ""
        base["attempt_id"] = base.get("attempt_id") or result.get("attempt_id") or base.get("run_id") or ""
        base["workflow_type"] = base.get("workflow_type") or result.get("workflow_type") or ""
        if isinstance(result.get("approval_request"), dict):
            base["approval_request"] = result.get("approval_request")
    task_session_summary = _task_session_summary(base.get("task_session") if isinstance(base.get("task_session"), dict) else None)
    if task_session_summary:
        if not base.get("pending_user_input_kind"):
            base["pending_user_input_kind"] = str(task_session_summary.get("pending_user_input_kind", "") or "").strip()
        if not base.get("approval_pending_scope"):
            base["approval_pending_scope"] = str(task_session_summary.get("approval_pending_scope", "") or "").strip()
        if not base.get("pending_user_question"):
            base["pending_user_question"] = str(task_session_summary.get("pending_user_question", "") or "").strip()
        if not isinstance(base.get("approval_request"), dict) or not base.get("approval_request"):
            summary_request = task_session_summary.get("approval_request")
            if isinstance(summary_request, dict):
                base["approval_request"] = summary_request
        if task_session_summary.get("awaiting_user_input"):
            base["awaiting_user_input"] = True
    awaiting = bool(
        base.get("awaiting_user_input")
        or str(base.get("pending_user_input_kind", "")).strip()
        or str(base.get("approval_pending_scope", "")).strip()
        or (isinstance(base.get("approval_request"), dict) and bool(base.get("approval_request")))
        or result.get("awaiting_user_input")
        or result.get("plan_waiting_for_approval")
        or result.get("plan_needs_clarification")
        or str(result.get("pending_user_input_kind", "")).strip()
    )
    if awaiting:
        base["status"] = "awaiting_user_input"
        base["awaiting_user_input"] = True
    return base


def _live_recent_runs(runs: list[dict] | None) -> list[dict]:
    return _live_recent_runs_with_pending(runs, collapse_workflows=True)


def _live_recent_runs_with_pending(
    runs: list[dict] | None,
    *,
    collapse_workflows: bool = False,
) -> list[dict]:
    merged: dict[str, dict] = {}
    for run in runs or []:
        if not isinstance(run, dict):
            continue
        run_id = str(run.get("run_id") or "").strip()
        if not run_id:
            continue
        merged[run_id] = dict(run)
    with _pending_lock:
        _prune_pending_runs_locked()
        pending_snapshot = {rid: dict(data) for rid, data in _pending_runs.items()}
    for run_id, pending in pending_snapshot.items():
        # Keep pending data as an overlay for persisted runs only.
        # Long-running visibility must come from durable DB/session state.
        if run_id not in merged:
            continue
        merged[run_id] = _overlay_run_with_pending(merged.get(run_id), pending) or {}
    rows = [row for row in merged.values() if isinstance(row, dict) and str(row.get("run_id") or "").strip()]
    _active_statuses = {"running", "started", "cancelling", "awaiting_user_input"}

    def _run_sort_key(row: dict) -> tuple:
        status = str(row.get("status") or "").strip().lower()
        # Active runs first (rank 1), then terminal runs by timestamp descending
        active_rank = 1 if status in _active_statuses else 0
        ts = str(row.get("updated_at") or row.get("started_at") or "")
        return (active_rank, ts)

    if not collapse_workflows:
        rows.sort(key=_run_sort_key, reverse=True)
        return rows
    latest_by_workflow: dict[str, dict] = {}
    for row in rows:
        workflow_id = str(row.get("workflow_id") or row.get("run_id") or "").strip()
        if not workflow_id:
            continue
        previous = latest_by_workflow.get(workflow_id)
        if previous is None:
            latest_by_workflow[workflow_id] = row
            continue
        row_key = _run_sort_key(row)
        prev_key = _run_sort_key(previous)
        if row_key >= prev_key:
            latest_by_workflow[workflow_id] = row
    rows = list(latest_by_workflow.values())
    rows.sort(key=_run_sort_key, reverse=True)
    return rows


def _extract_chat_session_id(session_id: str) -> str:
    value = str(session_id or "").strip()
    if not value:
        return ""
    parts = value.split(":")
    if len(parts) >= 4 and parts[-1] == "main" and parts[0] == "webchat":
        candidate = parts[-2].strip()
        if candidate:
            return candidate
    return value


def _is_chat_control_reply(text: str) -> bool:
    value = str(text or "").strip().lower()
    if not value:
        return True
    return value in {
        "approve",
        "approved",
        "reject",
        "rejected",
        "continue",
        "yes",
        "ok",
        "okay",
        "quick summary",
    }


def _live_recent_chat_threads(runs: list[dict] | None, sessions: list[dict] | None = None) -> list[dict]:
    rows = _live_recent_runs_with_pending(runs, collapse_workflows=False)
    threads: dict[str, dict] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        session_id = str(row.get("session_id") or "").strip()
        if "project_ui" in session_id:
            continue
        chat_session_id = _extract_chat_session_id(session_id) or str(row.get("workflow_id") or row.get("run_id") or "").strip()
        if not chat_session_id:
            continue
        entry = threads.get(chat_session_id)
        if entry is None:
            entry = {
                "chat_session_id": chat_session_id,
                "session_id": session_id,
                "latest_run_id": str(row.get("run_id") or "").strip(),
                "run_id": str(row.get("run_id") or "").strip(),
                "workflow_id": str(row.get("workflow_id") or "").strip() or str(row.get("run_id") or "").strip(),
                "attempt_id": str(row.get("attempt_id") or "").strip() or str(row.get("run_id") or "").strip(),
                "status": str(row.get("status") or "").strip(),
                "started_at": str(row.get("started_at") or "").strip(),
                "updated_at": str(row.get("updated_at") or row.get("started_at") or "").strip(),
                "completed_at": str(row.get("completed_at") or "").strip(),
                "working_directory": str(row.get("working_directory") or "").strip(),
                "run_output_dir": str(row.get("run_output_dir") or row.get("output_dir") or "").strip(),
                "log_paths": row.get("log_paths") if isinstance(row.get("log_paths"), dict) else {},
                "user_query": str(row.get("user_query") or "").strip(),
                "_queries": [],
            }
            threads[chat_session_id] = entry

        query = str(row.get("user_query") or "").strip()
        if query:
            entry["_queries"].append(query)

        current_ts = str(row.get("updated_at") or row.get("started_at") or "").strip()
        existing_ts = str(entry.get("updated_at") or entry.get("started_at") or "").strip()
        if current_ts >= existing_ts:
            entry.update(
                {
                    "session_id": session_id or entry.get("session_id", ""),
                    "latest_run_id": str(row.get("run_id") or "").strip() or entry.get("latest_run_id", ""),
                    "run_id": str(row.get("run_id") or "").strip() or entry.get("run_id", ""),
                    "workflow_id": str(row.get("workflow_id") or "").strip() or entry.get("workflow_id", ""),
                    "attempt_id": str(row.get("attempt_id") or "").strip() or entry.get("attempt_id", ""),
                    "status": str(row.get("status") or "").strip() or entry.get("status", ""),
                    "started_at": str(row.get("started_at") or "").strip() or entry.get("started_at", ""),
                    "updated_at": current_ts or entry.get("updated_at", ""),
                    "completed_at": str(row.get("completed_at") or "").strip(),
                    "working_directory": str(row.get("working_directory") or "").strip() or entry.get("working_directory", ""),
                    "run_output_dir": str(row.get("run_output_dir") or row.get("output_dir") or "").strip() or entry.get("run_output_dir", ""),
                }
            )
            if isinstance(row.get("log_paths"), dict) and row.get("log_paths"):
                entry["log_paths"] = dict(row.get("log_paths"))

    for session in sessions or []:
        if not isinstance(session, dict):
            continue
        channel = str(session.get("channel") or "").strip().lower()
        if channel in {"project_ui", "projectui", "project"}:
            continue
        chat_session_id = str(session.get("chat_id") or "").strip()
        if not chat_session_id:
            continue
        state = session.get("state") if isinstance(session.get("state"), dict) else {}
        session_run_id = str(state.get("last_run_id") or "").strip()
        session_status = str(state.get("last_status") or "").strip()
        session_updated_at = str(session.get("updated_at") or "").strip()
        session_objective = str(state.get("last_objective") or state.get("last_text") or "").strip()
        session_run_output_dir = str(state.get("run_output_dir") or "").strip()
        session_log_paths = state.get("log_paths") if isinstance(state.get("log_paths"), dict) else {}
        entry = threads.get(chat_session_id)
        if entry is None:
            entry = {
                "chat_session_id": chat_session_id,
                "session_id": str(session.get("session_key") or "").strip(),
                "latest_run_id": session_run_id,
                "run_id": session_run_id,
                "workflow_id": str(state.get("last_workflow_id") or session_run_id).strip(),
                "attempt_id": str(state.get("last_attempt_id") or session_run_id).strip(),
                "status": session_status,
                "started_at": "",
                "updated_at": session_updated_at,
                "completed_at": str(state.get("completed_at") or "").strip(),
                "working_directory": "",
                "run_output_dir": session_run_output_dir,
                "log_paths": dict(session_log_paths) if session_log_paths else (_run_log_paths(session_run_output_dir) if session_run_output_dir else {}),
                "user_query": session_objective,
                "_queries": [session_objective] if session_objective else [],
            }
            threads[chat_session_id] = entry
            continue
        existing_ts = str(entry.get("updated_at") or entry.get("started_at") or "").strip()
        if session_updated_at >= existing_ts:
            if session_run_id:
                entry["latest_run_id"] = session_run_id
                entry["run_id"] = session_run_id
            if session_status:
                entry["status"] = session_status
            entry["updated_at"] = session_updated_at or entry.get("updated_at", "")
            if session_run_output_dir:
                entry["run_output_dir"] = session_run_output_dir
            if session_log_paths:
                entry["log_paths"] = dict(session_log_paths)
        if session_objective and not str(entry.get("user_query") or "").strip():
            entry["user_query"] = session_objective

    results: list[dict] = []
    for entry in threads.values():
        queries = [q for q in entry.pop("_queries", []) if q]
        representative = ""
        for query in queries:
            if not _is_chat_control_reply(query):
                representative = query
                break
        if not representative and queries:
            representative = queries[0]
        entry["user_query"] = representative or str(entry.get("user_query") or "").strip()
        if not entry["user_query"]:
            status_label = str(entry.get("status") or "").strip().lower().replace("_", " ")
            entry["user_query"] = status_label.capitalize() + " run" if status_label else "Untitled run"
        if (not isinstance(entry.get("log_paths"), dict) or not entry.get("log_paths")) and str(entry.get("run_output_dir") or "").strip():
            entry["log_paths"] = _run_log_paths(str(entry.get("run_output_dir") or ""))
        results.append(entry)

    def _thread_sort_key(row: dict) -> tuple:
        status = str(row.get("status") or "").strip().lower()
        # Active runs float to top; among terminal runs (completed/failed/cancelled) sort purely by time
        active_rank = 1 if status in {"running", "started", "cancelling", "awaiting_user_input"} else 0
        ts = str(row.get("updated_at") or row.get("started_at") or "")
        return (active_rank, ts)

    results.sort(key=_thread_sort_key, reverse=True)
    return results


def _live_run(run_row: dict | None) -> dict | None:
    if not run_row:
        return None
    run_id = str(run_row.get("run_id") or "").strip()
    if not run_id:
        return run_row
    with _pending_lock:
        pending = dict(_pending_runs.get(run_id, {})) if run_id in _pending_runs else None
    return _overlay_run_with_pending(run_row, pending)


def _parse_iso_timestamp(value: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    normalized = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(normalized)
    except Exception:
        return None


def _duration_label(duration_ms: int | None) -> str:
    if duration_ms is None or duration_ms < 0:
        return ""
    if duration_ms < 1000:
        return f"{duration_ms} ms"
    seconds = duration_ms / 1000.0
    if seconds < 10:
        return f"{seconds:.1f}s"
    if seconds < 60:
        return f"{round(seconds)}s"
    minutes, remainder = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes}m {remainder}s"
    hours, minute_remainder = divmod(minutes, 60)
    return f"{hours}h {minute_remainder}m"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _project_activity_event(
    *,
    kind: str,
    title: str,
    status: str = "completed",
    actor: str = "",
    detail: str = "",
    command: str = "",
    cwd: str = "",
    task: str = "",
    subtask: str = "",
    started_at: str = "",
    completed_at: str = "",
    duration_ms: int | None = None,
    exit_code: int | None = None,
    metadata: dict | None = None,
) -> dict:
    started = str(started_at or _utc_now_iso()).strip()
    completed = str(completed_at or ("" if str(status).lower() == "running" else _utc_now_iso())).strip()
    resolved_duration = duration_ms
    if resolved_duration is None and started and completed:
        started_dt = _parse_iso_timestamp(started)
        completed_dt = _parse_iso_timestamp(completed)
        if started_dt and completed_dt:
            resolved_duration = max(0, int((completed_dt - started_dt).total_seconds() * 1000))
    return {
        "id": f"proj-{uuid.uuid4().hex[:10]}",
        "kind": str(kind or "activity"),
        "title": str(title or "Activity"),
        "status": str(status or "completed"),
        "actor": str(actor or "").strip(),
        "detail": str(detail or "").strip(),
        "command": str(command or "").strip(),
        "cwd": str(cwd or "").strip(),
        "task": str(task or "").strip(),
        "subtask": str(subtask or "").strip(),
        "started_at": started,
        "completed_at": completed,
        "duration_ms": resolved_duration,
        "duration_label": _duration_label(resolved_duration),
        "exit_code": exit_code,
        "metadata": metadata or {},
    }


def _emit_project_activity(emit, activities: list[dict], **kwargs) -> dict:
    event = _project_activity_event(**kwargs)
    activities.append(event)
    emit("activity", event)
    return event


def _project_listing_command(is_git_repo: bool) -> str:
    if is_git_repo:
        return "git ls-files | Select-Object -First 120" if os.name == "nt" else "git ls-files | head -n 120"
    return "Get-ChildItem -Name | Select-Object -First 120" if os.name == "nt" else "find . -maxdepth 2 -mindepth 1 | sed 's#^\\./##' | sort | head -n 120"


def _format_step(step: dict) -> dict:
    excerpt = str(step.get("output_excerpt") or "").strip()
    reason = str(step.get("reason") or "").strip()
    agent = step.get("agent_name", "agent")
    started_at = str(step.get("timestamp") or step.get("started_at") or "").strip()
    completed_at = str(step.get("completed_at") or "").strip()
    started_dt = _parse_iso_timestamp(started_at)
    completed_dt = _parse_iso_timestamp(completed_at)
    effective_end = completed_dt or (datetime.now(timezone.utc) if started_dt else None)
    duration_ms = None
    if started_dt and effective_end:
        duration_ms = max(0, int((effective_end - started_dt).total_seconds() * 1000))
    status = step.get("status", "running")
    failure_reason = excerpt or reason
    if not reason:
        agent_slug = str(agent or "").lower()
        if "plan" in agent_slug:
            reason = "Define the execution approach before running tasks."
        elif "research" in agent_slug:
            reason = "Gather and validate the information needed for this objective."
        elif "draft" in agent_slug or "write" in agent_slug:
            reason = "Turn the gathered inputs into a clear deliverable."
        elif "review" in agent_slug or "qa" in agent_slug or "test" in agent_slug:
            reason = "Validate quality and catch errors before completion."
        elif "code" in agent_slug or "build" in agent_slug:
            reason = "Implement or refine the solution requested."
        else:
            reason = "Advance the run toward the final requested outcome."
    return {
        "agent": agent,
        "status": status,
        "message": excerpt or "",
        "reason": reason,
        "execution_id": step.get("execution_id"),
        "started_at": started_at,
        "completed_at": completed_at,
        "duration_ms": duration_ms,
        "duration_label": _duration_label(duration_ms),
        "failure_reason": failure_reason if str(status).lower() in {"failed", "error"} else "",
    }


def _step_stream_key(step: dict, idx: int) -> str:
    execution_id = str(step.get("execution_id") or "").strip()
    if execution_id:
        return execution_id
    agent = str(step.get("agent_name") or "agent").strip()
    started = str(step.get("timestamp") or step.get("started_at") or "").strip()
    if started:
        return f"{agent}:{started}"
    return f"{agent}:{idx}"


def _step_stream_signature(step: dict) -> tuple[str, str, str, str]:
    return (
        str(step.get("status") or "").strip().lower(),
        str(step.get("completed_at") or "").strip(),
        str(step.get("output_excerpt") or "").strip(),
        str(step.get("reason") or "").strip(),
    )


def _launch_step_stream_poller(run_id: str, interval_seconds: float = 0.6) -> threading.Thread:
    """Emit SSE step updates for a run while it is active, including status changes."""

    def _poll() -> None:
        seen_signatures: dict[str, tuple[str, str, str, str]] = {}
        terminal_statuses = {"completed", "failed", "cancelled", "awaiting_user_input"}
        while True:
            with _pending_lock:
                current = _pending_runs.get(run_id, {})
            current_status = str(current.get("status") or "").strip().lower()
            should_stop = current_status in terminal_statuses
            try:
                for idx, step in enumerate(_list_run_steps(run_id)):
                    key = _step_stream_key(step, idx)
                    signature = _step_stream_signature(step)
                    if seen_signatures.get(key) == signature:
                        continue
                    seen_signatures[key] = signature
                    _push_event(run_id, "step", _format_step(step))
            except Exception as _step_exc:
                _log.debug("Step poll error for run %s: %s", run_id, _step_exc)
            if should_stop:
                break
            time.sleep(interval_seconds)

    poller = threading.Thread(target=_poll, daemon=True)
    poller.start()
    return poller


def _collect_artifacts(run_id: str, output_dir: str) -> tuple[list[dict], list[dict]]:
    db_artifacts: list[dict] = []
    file_list: list[dict] = []
    try:
        db_artifacts = _list_run_artifacts(run_id)
    except Exception:
        pass
    try:
        if output_dir and os.path.isdir(output_dir):
            for fname in sorted(os.listdir(output_dir))[:50]:
                fp = os.path.join(output_dir, fname)
                if os.path.isfile(fp):
                    file_list.append({
                        "name": fname,
                        "path": fp,
                        "size": os.path.getsize(fp),
                    })
    except Exception:
        pass
    return db_artifacts, file_list


def _start_run_background(run_id: str, payload: dict) -> None:
    def _run() -> None:
        _push_event(run_id, "status", {"status": "running", "message": "Agents mobilizing..."})
        _launch_step_stream_poller(run_id)
        try:
            result = _gateway_ingest(payload)
            db_artifacts, file_list = _collect_artifacts(run_id, result.get("output_dir", ""))
            result["artifacts"] = db_artifacts
            result["artifact_files"] = file_list
            test_report = None
            if isinstance(result.get("test_report"), dict):
                test_report = result["test_report"]
            if not test_report:
                for art in db_artifacts:
                    if art.get("kind") == "test_report" or "test_report" in str(art.get("name", "")):
                        candidate = art.get("data") or art.get("payload") or art.get("content")
                        if isinstance(candidate, dict):
                            test_report = candidate
                            break
                        json_path = (art.get("metadata") or {}).get("json_report") or ""
                        if not test_report and json_path and os.path.isfile(json_path):
                            try:
                                with open(json_path, encoding="utf-8") as _jf:
                                    candidate = json.load(_jf)
                                if isinstance(candidate, dict):
                                    test_report = candidate
                                    break
                            except Exception:
                                pass
            if test_report:
                result["test_report"] = test_report
            try:
                mcp_invocations = []
                for step in _list_run_steps(run_id):
                    aname = step.get("agent_name", "")
                    if aname.startswith("mcp_") and aname.endswith("_agent"):
                        inner = aname[4:-6]
                        parts = inner.split("_", 1)
                        server_slug = parts[0] if parts else ""
                        tool_slug = parts[1] if len(parts) > 1 else inner
                        mcp_invocations.append({
                            "tool": tool_slug.replace("_", " "),
                            "server": server_slug.replace("_", " "),
                            "ok": step.get("status") not in ("failed", "error"),
                            "error": step.get("error") or "",
                        })
                if mcp_invocations:
                    result["mcp_invocations"] = mcp_invocations
            except Exception:
                pass
            # Inject long_document exports into artifact_files for download
            try:
                doc_files = result.get("artifact_files") or []
                existing_names = {f.get("name") for f in doc_files}
                doc_keys = [
                    ("long_document_compiled_path", "md", "Markdown"),
                    ("long_document_compiled_html_path", "html", "HTML"),
                    ("long_document_compiled_pdf_path", "pdf", "PDF"),
                    ("long_document_compiled_docx_path", "docx", "Word (DOCX)"),
                ]
                long_doc_exports = []
                for key, ext, label in doc_keys:
                    fpath = str(result.get(key) or "").strip()
                    if fpath and os.path.isfile(fpath):
                        fname = os.path.basename(fpath)
                        if fname not in existing_names:
                            doc_files.append({
                                "name": fname,
                                "path": fpath,
                                "size": os.path.getsize(fpath),
                                "label": label,
                                "ext": ext,
                            })
                            existing_names.add(fname)
                            long_doc_exports.append({"ext": ext, "label": label, "name": fname})
                if long_doc_exports:
                    result["artifact_files"] = doc_files
                    result["long_document_exports"] = long_doc_exports
            except Exception:
                pass
            _run_status = _terminal_run_status(result=result, default="completed")
            _run_awaiting = _run_status == "awaiting_user_input"
            with _pending_lock:
                _pending_runs[run_id] = _pending_run_state(run_id, payload=payload, status=_run_status, result=result)
            _persist_channel_chat_turn(
                payload,
                user_text=str(payload.get("text") or ""),
                assistant_text=_project_chat_result_text(result),
                context_limit=payload.get("context_limit"),
            )
            _persist_project_chat_result(payload, result=result, run_id=run_id)
            _push_event(run_id, "result", result)
            _push_event(run_id, "done", {"run_id": run_id, "status": _run_status, "awaiting_user_input": _run_awaiting})
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8") if hasattr(exc, "read") else str(exc)
            try:
                err_data = json.loads(err_body)
                err_msg = str(err_data.get("detail") or err_data.get("error") or str(exc))
            except Exception:
                err_data = {}
                err_msg = err_body or str(exc)
            run_status = _terminal_run_status(error=err_msg, default="failed")
            if run_status == "cancelled":
                cancel_result = {
                    "run_id": run_id,
                    "workflow_id": str(payload.get("workflow_id") or run_id),
                    "attempt_id": str(payload.get("attempt_id") or run_id),
                    "workflow_type": str(payload.get("workflow_type") or ""),
                    "working_directory": str(payload.get("working_directory") or ""),
                    "status": "cancelled",
                    "final_output": "Run stopped by user.",
                }
                with _pending_lock:
                    _pending_runs[run_id] = _pending_run_state(run_id, payload=payload, status="cancelled", result=cancel_result)
                _persist_channel_chat_turn(
                    payload,
                    user_text=str(payload.get("text") or ""),
                    assistant_text=_project_chat_result_text(cancel_result),
                    context_limit=payload.get("context_limit"),
                )
                _persist_project_chat_result(payload, result=cancel_result, run_id=run_id)
                _push_event(run_id, "result", cancel_result)
                _push_event(run_id, "done", {"run_id": run_id, "status": "cancelled", "awaiting_user_input": False})
                return
            with _pending_lock:
                _pending_runs[run_id] = _pending_run_state(run_id, payload=payload, status="failed", error=err_msg)
            _persist_channel_chat_turn(
                payload,
                user_text=str(payload.get("text") or ""),
                assistant_text="Error: " + str(err_msg),
                context_limit=payload.get("context_limit"),
            )
            _persist_project_chat_result(payload, error=err_msg, run_id=run_id)
            _push_event(run_id, "error", {"message": err_msg})
            _push_event(run_id, "done", {"run_id": run_id, "status": "failed"})
        except urllib.error.URLError as exc:
            err = str(exc)
            with _pending_lock:
                _pending_runs[run_id] = _pending_run_state(run_id, payload=payload, status="failed", error=err)
            _persist_channel_chat_turn(
                payload,
                user_text=str(payload.get("text") or ""),
                assistant_text="Error: " + str(err),
                context_limit=payload.get("context_limit"),
            )
            _persist_project_chat_result(payload, error=err, run_id=run_id)
            _push_event(run_id, "error", {"message": err})
            _push_event(run_id, "done", {"run_id": run_id, "status": "failed"})
        except Exception as exc:
            err = traceback.format_exc()
            with _pending_lock:
                _pending_runs[run_id] = _pending_run_state(run_id, payload=payload, status="failed", error=str(exc))
            _persist_channel_chat_turn(
                payload,
                user_text=str(payload.get("text") or ""),
                assistant_text="Error: " + str(exc),
                context_limit=payload.get("context_limit"),
            )
            _persist_project_chat_result(payload, error=str(exc), run_id=run_id)
            _push_event(run_id, "error", {"message": str(exc)})
            _push_event(run_id, "done", {"run_id": run_id, "status": "failed"})

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def _start_standalone_run_background(run_id: str, payload: dict) -> None:
    """Run ProjectGenerationOrchestrator in a background thread, streaming progress via SSE."""

    def _run() -> None:
        _push_event(run_id, "status", {"status": "running", "message": "Standalone generator starting…"})
        try:
            from tasks.project_generation_orchestrator import ProjectGenerationOrchestrator

            def _cb(msg: str) -> None:
                try:
                    import json as _json
                    data = _json.loads(msg)
                    event_type = data.get("type", "step")
                    if event_type == "progress":
                        event_type = "step"
                except Exception:
                    data = {"text": msg, "type": "progress"}
                    event_type = "step"
                _push_event(run_id, event_type, data)

            description = str(payload.get("text") or payload.get("description") or "")
            stack = str(payload.get("project_stack") or payload.get("stack") or "")
            project_name = str(payload.get("project_name") or "")
            project_root = str(payload.get("project_root") or payload.get("working_directory") or "")
            github_repo = str(payload.get("github_repo") or "")
            auto_approve = bool(payload.get("auto_approve", True))
            skip_tests = bool(payload.get("skip_test_agent", False))
            skip_devops = bool(payload.get("skip_devops_agent", False))

            orch = ProjectGenerationOrchestrator(
                description=description,
                stack=stack,
                project_root=project_root,
                project_name=project_name,
                auto_approve=auto_approve,
                skip_tests=skip_tests,
                skip_devops=skip_devops,
                max_fix_iters=3,
                github_repo=github_repo,
                progress_cb=_cb,
            )
            result = orch.run()
            result.setdefault("output_dir", result.get("project_root", ""))
            with _pending_lock:
                _pending_runs[run_id] = _pending_run_state(run_id, payload=payload, status="completed", result=result)
            _persist_channel_chat_turn(
                payload,
                user_text=str(payload.get("text") or payload.get("description") or ""),
                assistant_text=_project_chat_result_text(result),
                context_limit=payload.get("context_limit"),
            )
            _persist_project_chat_result(payload, result=result, run_id=run_id)
            _push_event(run_id, "result", result)
            _push_event(run_id, "done", {"run_id": run_id, "status": "completed"})
        except Exception as exc:
            err = str(exc)
            with _pending_lock:
                _pending_runs[run_id] = _pending_run_state(run_id, payload=payload, status="failed", error=err)
            _persist_channel_chat_turn(
                payload,
                user_text=str(payload.get("text") or payload.get("description") or ""),
                assistant_text="Error: " + err,
                context_limit=payload.get("context_limit"),
            )
            _persist_project_chat_result(payload, error=err, run_id=run_id)
            _push_event(run_id, "error", {"message": err})
            _push_event(run_id, "done", {"run_id": run_id, "status": "failed"})

    t = threading.Thread(target=_run, daemon=True)
    t.start()


def _llm_chunk_text(chunk: object) -> str:
    content = getattr(chunk, "content", chunk)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                txt = item.get("text") or item.get("content") or item.get("value") or ""
                if txt:
                    parts.append(str(txt))
                continue
            if item is not None:
                parts.append(str(item))
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def _start_simple_chat_stream_background(run_id: str, payload: dict) -> None:
    def _run() -> None:
        _push_event(run_id, "status", {"status": "running", "message": "Generating response..."})
        try:
            from kendr.llm_router import build_llm, get_active_provider, get_model_for_provider
            from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

            text = str(payload.get("text") or payload.get("message") or "").strip()
            model_override = str(payload.get("model") or "").strip() or None
            provider_override = str(payload.get("provider") or "").strip() or None
            local_paths = payload.get("local_drive_paths") or []
            if not isinstance(local_paths, list):
                local_paths = []
            history = payload.get("history") if isinstance(payload.get("history"), list) else []
            context = _sync_channel_chat_context(
                payload,
                supplied_history=history,
                context_limit=payload.get("context_limit"),
            )

            provider = provider_override or get_active_provider()
            model = model_override or get_model_for_provider(provider)
            llm = build_llm(provider, model)

            attachment_notes: list[str] = []
            for raw_path in local_paths[:8]:
                candidate = normalize_host_path_str(str(raw_path or "").strip())
                if not candidate:
                    continue
                try:
                    if os.path.isfile(candidate):
                        with open(candidate, "r", encoding="utf-8", errors="replace") as fh:
                            excerpt = fh.read(2000)
                        attachment_notes.append(
                            f"=== Attached file: {os.path.basename(candidate)} ===\nPath: {candidate}\n{excerpt}"
                        )
                    elif os.path.isdir(candidate):
                        entries = sorted(os.listdir(candidate))[:40]
                        attachment_notes.append(
                            f"=== Attached folder: {os.path.basename(candidate)} ===\nPath: {candidate}\nEntries: {entries}"
                        )
                except Exception:
                    attachment_notes.append(f"Attached path: {candidate}")

            system_ctx = (
                "You are Kendr in simple chat mode. "
                "Answer directly and helpfully. "
                "Do not mention agents, orchestration, runs, artifacts, plans, or internal workflows. "
                "Only provide a plain assistant answer. "
                "If attached local files or folders are available, use their excerpts or path summaries when relevant."
            )
            if attachment_notes:
                system_ctx += "\n\nAttached local context:\n" + "\n\n".join(attachment_notes)
            summary_block = _build_chat_context_block(context.get("summary_text", ""), context.get("history", []))
            if summary_block:
                system_ctx += "\n\nChat continuity context:\n" + summary_block

            messages = [SystemMessage(content=system_ctx)]
            for item in (context.get("history") or [])[-14:]:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "").strip().lower()
                content = str(item.get("content") or "").strip()
                if not content:
                    continue
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
            messages.append(HumanMessage(content=text))

            answer_parts: list[str] = []
            try:
                for chunk in llm.stream(messages):
                    delta = _llm_chunk_text(chunk)
                    if not delta:
                        continue
                    answer_parts.append(delta)
                    _push_event(run_id, "delta", {"delta": delta})
            except Exception:
                answer_parts = []

            answer = "".join(answer_parts).strip()
            if not answer:
                response = llm.invoke(messages)
                answer = _llm_chunk_text(response).strip()

            result = {
                "run_id": run_id,
                "status": "completed",
                "provider": provider,
                "model": model,
                "answer": answer,
                "final_output": answer,
            }
            with _pending_lock:
                _pending_runs[run_id] = _pending_run_state(run_id, payload=payload, status="completed", result=result)
            _persist_channel_chat_turn(
                payload,
                user_text=text,
                assistant_text=answer,
                context_limit=payload.get("context_limit"),
            )
            _push_event(run_id, "result", result)
            _push_event(run_id, "done", {"run_id": run_id, "status": "completed", "awaiting_user_input": False})
        except Exception as exc:
            err = str(exc)
            with _pending_lock:
                _pending_runs[run_id] = _pending_run_state(run_id, payload=payload, status="failed", error=err)
            _persist_channel_chat_turn(
                payload,
                user_text=str(payload.get("text") or payload.get("message") or ""),
                assistant_text="Error: " + err,
                context_limit=payload.get("context_limit"),
            )
            _push_event(run_id, "error", {"message": err})
            _push_event(run_id, "done", {"run_id": run_id, "status": "failed"})

    t = threading.Thread(target=_run, daemon=True)
    t.start()


_CHAT_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kendr — Chat</title>
<style>
:root {
  --teal: #00C9A7; --amber: #FFB347; --crimson: #FF4757; --blue: #5352ED;
  --bg: #0d0f14; --surface: #161b22; --surface2: #1e2530; --border: #2a3140;
  --text: #e6edf3; --muted: #7d8590; --sidebar-w: 280px; --inspector-w: 320px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "Segoe UI", system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; height: 100dvh; display: flex; overflow: hidden; }
a { color: var(--teal); text-decoration: none; }
a:hover { text-decoration: underline; }
.sidebar { width: var(--sidebar-w); min-width: var(--sidebar-w); background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; overflow: hidden; }
.sidebar-header { padding: 20px 16px 12px; border-bottom: 1px solid var(--border); }
.logo { font-size: 22px; font-weight: 800; color: var(--teal); letter-spacing: 0.05em; }
.logo span { color: var(--amber); }
.tagline { font-size: 11px; color: var(--muted); margin-top: 4px; }
.sidebar-nav { padding: 12px 8px; border-bottom: 1px solid var(--border); display: flex; flex-direction: column; gap: 4px; }
.nav-btn { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-radius: 8px; font-size: 13px; font-weight: 500; color: var(--muted); cursor: pointer; border: none; background: transparent; width: 100%; text-align: left; text-decoration: none; transition: background 0.15s, color 0.15s; }
.nav-btn:hover { background: var(--surface2); color: var(--text); }
.nav-btn.active { background: rgba(0, 201, 167, 0.12); color: var(--teal); }
.nav-btn .icon { font-size: 16px; width: 20px; text-align: center; }
.sidebar-section { padding: 10px 16px 6px; font-size: 10px; font-weight: 700; color: var(--muted); letter-spacing: 0.08em; text-transform: uppercase; }
.run-list { overflow-y: auto; flex: 1; padding: 0 8px 16px; }
.run-item { padding: 10px 12px; border-radius: 8px; cursor: pointer; margin-bottom: 2px; border: 1px solid transparent; transition: background 0.15s; }
.run-item:hover { background: var(--surface2); }
.run-item.active { background: rgba(83, 82, 237, 0.12); border-color: rgba(83, 82, 237, 0.3); }
.run-item-title { font-size: 12px; font-weight: 500; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.run-item-meta { font-size: 11px; color: var(--muted); margin-top: 2px; }
.run-badge { display: inline-block; padding: 1px 6px; border-radius: 4px; font-size: 10px; font-weight: 600; }
.run-badge.completed { background: rgba(0,201,167,0.15); color: var(--teal); }
.run-badge.failed { background: rgba(255,71,87,0.15); color: var(--crimson); }
.run-badge.running { background: rgba(255,179,71,0.15); color: var(--amber); }
.run-badge.awaiting { background: rgba(83,82,237,0.16); color: #b8b7ff; }
.run-badge.cancelled, .run-badge.cancelling { background: rgba(255,179,71,0.15); color: var(--amber); }
.new-chat-btn { display: flex; align-items: center; justify-content: center; gap: 8px; margin: 12px 8px 4px; padding: 10px; background: rgba(0,201,167,0.1); border: 1px solid rgba(0,201,167,0.3); color: var(--teal); border-radius: 10px; font-size: 13px; font-weight: 600; cursor: pointer; transition: background 0.15s; }
.new-chat-btn:hover { background: rgba(0,201,167,0.2); }
/* Project context panel in chat sidebar */
.proj-panel { margin: 0 8px 4px; border: 1px solid var(--border); border-radius: 10px; background: var(--surface2); overflow: hidden; }
.proj-panel-header { display: flex; align-items: center; gap: 6px; padding: 8px 10px; cursor: pointer; user-select: none; }
.proj-panel-icon { font-size: 14px; }
.proj-panel-name { flex: 1; font-size: 11px; font-weight: 700; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.proj-panel-badge { font-size: 9px; font-weight: 700; background: rgba(0,201,167,.15); color: var(--teal); padding: 1px 5px; border-radius: 10px; flex-shrink: 0; }
.proj-panel-none { font-size: 11px; color: var(--muted); font-style: italic; }
.proj-panel-body { border-top: 1px solid var(--border); padding: 8px 10px; display: none; }
.proj-panel.open .proj-panel-body { display: block; }
.proj-stack { font-size: 10px; color: var(--muted); margin-bottom: 6px; }
.proj-md-status { font-size: 10px; margin-bottom: 6px; display: flex; align-items: center; gap: 5px; }
.proj-md-dot { width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0; }
.proj-md-dot.green { background: var(--teal); }
.proj-md-dot.amber { background: var(--amber); }
.proj-action-row { display: flex; gap: 5px; flex-wrap: wrap; margin-top: 4px; }
.proj-action-btn { font-size: 10px; font-weight: 600; padding: 3px 8px; border-radius: 5px; border: 1px solid var(--border); background: var(--surface); color: var(--muted); cursor: pointer; white-space: nowrap; }
.proj-action-btn:hover { background: rgba(0,201,167,.08); color: var(--teal); border-color: rgba(0,201,167,.3); }
.proj-action-btn.primary { background: rgba(0,201,167,.1); color: var(--teal); border-color: rgba(0,201,167,.3); }
/* kendr.md editor modal */
.kdmd-modal { display: none; position: fixed; inset: 0; background: rgba(0,0,0,.7); z-index: 2000; align-items: center; justify-content: center; }
.kdmd-box { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; width: 680px; max-height: 85vh; display: flex; flex-direction: column; }
.kdmd-header { padding: 16px 20px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; }
.kdmd-title { font-size: 14px; font-weight: 700; }
.kdmd-close { background: none; border: none; color: var(--muted); font-size: 20px; cursor: pointer; }
.kdmd-textarea { flex: 1; margin: 0; padding: 16px; background: var(--surface2); color: var(--text); border: none; border-radius: 0; font-family: 'JetBrains Mono', 'Fira Code', monospace; font-size: 12px; line-height: 1.6; resize: none; min-height: 380px; outline: none; }
.kdmd-footer { padding: 12px 20px; border-top: 1px solid var(--border); display: flex; gap: 10px; justify-content: flex-end; }
.kdmd-save { background: var(--teal); color: #0d1117; border: none; border-radius: 8px; padding: 8px 20px; font-size: 13px; font-weight: 700; cursor: pointer; }
.kdmd-save:hover { opacity: .85; }
.kdmd-cancel { background: var(--surface2); border: 1px solid var(--border); color: var(--muted); border-radius: 8px; padding: 8px 16px; font-size: 13px; cursor: pointer; }
.chat-main { flex: 1; min-width: 0; min-height: 0; display: flex; flex-direction: column; overflow: hidden; background: var(--bg); }
.chat-header { padding: 16px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; background: var(--surface); }
.chat-title { font-size: 15px; font-weight: 600; color: var(--text); }
.chat-subtitle { font-size: 12px; color: var(--muted); }
.chat-command-bar { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:10px 24px; border-bottom:1px solid var(--border); background:linear-gradient(90deg, rgba(0,201,167,0.10), rgba(16,21,28,0.98) 34%, #10151c 100%); }
.chat-command-track { font-size:12px; color:var(--muted); flex:1; min-width:220px; }
.chat-command-modes { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
.chat-command-chip { padding:6px 10px; border-radius:999px; border:1px solid var(--border); background:rgba(255,255,255,0.03); color:var(--text); font-size:11px; font-weight:700; }
.chat-command-chip.active { border-color: rgba(0,201,167,0.35); color: var(--teal); background: rgba(0,201,167,0.08); }
.header-status { display: flex; align-items: center; gap: 10px; font-size: 12px; color: var(--muted); }
.clear-chat-btn { display: flex; align-items: center; gap: 5px; padding: 5px 12px; border-radius: 8px; border: 1px solid var(--border); background: transparent; color: var(--muted); font-size: 12px; cursor: pointer; transition: all 0.15s; }
.clear-chat-btn:hover { border-color: var(--crimson); color: var(--crimson); background: rgba(255,71,87,0.08); }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--crimson); }
.status-dot.online { background: var(--teal); animation: pulse 2s infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
/* Shell Mode toggle */
.shell-mode-btn { display: flex; align-items: center; gap: 5px; padding: 5px 12px; border-radius: 8px; border: 1px solid var(--border); background: transparent; color: var(--muted); font-size: 12px; cursor: pointer; transition: all 0.2s; font-weight: 500; }
.shell-mode-btn:hover { border-color: var(--amber); color: var(--amber); background: rgba(255,179,71,0.08); }
.shell-mode-btn.active { border-color: var(--amber); color: #0d0f14; background: var(--amber); font-weight: 700; }
.shell-mode-btn.active .shell-mode-icon { filter: none; }
/* Terminal output block */
.terminal-block { font-family: "Cascadia Code", "Fira Code", "SF Mono", Consolas, monospace; font-size: 12px; background: #0a0c0f; border: 1px solid #2a3140; border-radius: 8px; overflow: hidden; margin: 10px 0; }
.terminal-header { display: flex; align-items: center; gap: 8px; padding: 7px 14px; background: #111418; border-bottom: 1px solid #1e2530; }
.terminal-dot { width: 10px; height: 10px; border-radius: 50%; }
.terminal-title { font-size: 11px; color: #7d8590; flex: 1; margin-left: 4px; }
.terminal-body { padding: 12px 16px; overflow-x: auto; max-height: 500px; overflow-y: auto; }
.terminal-line { line-height: 1.5; white-space: pre-wrap; word-break: break-word; }
.terminal-line.cmd { color: #00C9A7; }
.terminal-line.cmd::before { content: "$ "; opacity: 0.6; }
.terminal-line.out { color: #b5c4de; }
.terminal-line.err { color: #FF4757; }
.terminal-line.ok { color: #00C9A7; }
.terminal-line.skip { color: #7d8590; font-style: italic; }
.terminal-line.blocked { color: #FFB347; }
.terminal-step { margin-bottom: 10px; padding-bottom: 10px; border-bottom: 1px solid #1e2530; }
.terminal-step:last-child { margin-bottom: 0; padding-bottom: 0; border-bottom: none; }
.terminal-step-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; font-size: 12px; font-weight: 600; }
.shell-mode-banner { display: none; background: rgba(255,179,71,0.08); border: 1px solid rgba(255,179,71,0.25); border-radius: 8px; padding: 8px 14px; margin: 8px 0 0; font-size: 12px; color: var(--amber); }
.shell-mode-banner.visible { display: flex; align-items: center; gap: 8px; }
.messages { flex: 1; min-height: 0; overflow-y: auto; padding: 24px; display: flex; flex-direction: column; gap: 16px; scroll-behavior: smooth; }
.message-row { display: flex; gap: 12px; max-width: 900px; }
.message-row.user { flex-direction: row-reverse; margin-left: auto; }
.message-row.user .bubble { background: rgba(83,82,237,0.2); border-color: rgba(83,82,237,0.4); border-radius: 18px 4px 18px 18px; }
.avatar { width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 16px; flex-shrink: 0; }
.avatar.kendr { background: rgba(0,201,167,0.15); border: 1px solid rgba(0,201,167,0.3); }
.avatar.user { background: rgba(83,82,237,0.2); border: 1px solid rgba(83,82,237,0.3); }
.bubble { padding: 14px 18px; border-radius: 4px 18px 18px 18px; border: 1px solid var(--border); background: var(--surface); max-width: 680px; font-size: 14px; line-height: 1.65; }
.bubble-meta { font-size: 11px; color: var(--muted); margin-top: 8px; }
.run-hero { padding: 12px 14px; border-radius: 12px; border: 1px solid rgba(0,201,167,0.16); background: linear-gradient(145deg, rgba(0,201,167,0.10), rgba(83,82,237,0.06)); margin-bottom: 10px; }
.run-hero-eyebrow { font-size: 10px; font-weight: 700; color: var(--teal); letter-spacing: 0.08em; text-transform: uppercase; }
.run-hero-title { font-size: 14px; font-weight: 700; color: var(--text); margin-top: 5px; line-height: 1.45; }
.run-hero-meta { font-size: 11px; color: var(--muted); margin-top: 6px; display:flex; gap:8px; flex-wrap:wrap; }
.bubble pre { background: rgba(0,0,0,0.3); border: 1px solid var(--border); border-radius: 8px; padding: 12px; overflow-x: auto; font-size: 13px; margin: 8px 0; white-space: pre-wrap; }
.steps-wrapper { display: flex; flex-direction: column; gap: 0; margin-top: 10px; position: relative; }
.step-card { background: transparent; border: none; border-radius: 0; padding: 0 0 4px 28px; font-size: 12px; position: relative; }
.step-card::before { content: ''; position: absolute; left: 7px; top: 20px; bottom: -4px; width: 1px; background: var(--border); }
.step-card:last-child::before { display: none; }
.step-dot { position: absolute; left: 0; top: 6px; width: 15px; height: 15px; border-radius: 50%; background: var(--surface2); border: 2px solid var(--border); display: flex; align-items: center; justify-content: center; font-size: 9px; }
.step-card.running .step-dot { border-color: var(--amber); background: rgba(255,179,71,0.15); }
.step-card.done .step-dot, .step-card.completed .step-dot, .step-card.success .step-dot { border-color: var(--teal); background: rgba(0,201,167,0.15); }
.step-card.failed .step-dot, .step-card.error .step-dot { border-color: var(--crimson); background: rgba(255,71,87,0.15); }
.step-card.mcp-step .step-dot { border-color: #a78bfa; background: rgba(167,139,250,0.15); }
.step-inner { background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; margin-left: 4px; }
.step-card.running .step-inner { border-color: rgba(255,179,71,0.35); }
.step-card.done .step-inner, .step-card.completed .step-inner, .step-card.success .step-inner { border-color: rgba(0,201,167,0.25); }
.step-card.failed .step-inner, .step-card.error .step-inner { border-color: rgba(255,71,87,0.3); }
.step-card.mcp-step .step-inner { border-color: rgba(167,139,250,0.3); background: rgba(167,139,250,0.04); }
.step-reason { margin-top: 5px; font-size: 11px; color: var(--muted); }
.step-reason summary { cursor: pointer; color: var(--teal); font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: .05em; user-select: none; list-style: none; display: flex; align-items: center; gap: 4px; }
.step-reason summary::after { content: '▸'; font-size: 9px; transition: transform .2s; }
.step-reason[open] summary::after { transform: rotate(90deg); }
.step-reason p { margin: 4px 0 0; padding: 5px 8px; background: rgba(255,255,255,0.03); border-left: 2px solid var(--teal); border-radius: 0 4px 4px 0; line-height: 1.5; }
.step-output { margin-top: 5px; font-size: 11px; color: var(--muted); }
.step-output summary { cursor: pointer; color: var(--muted); font-size: 10px; font-weight: 600; list-style: none; display: flex; align-items: center; gap: 4px; user-select: none; }
.step-output summary::after { content: '▸'; font-size: 9px; transition: transform .2s; }
.step-output[open] summary::after { transform: rotate(90deg); }
.step-output p { margin: 4px 0 0; padding: 5px 8px; background: rgba(0,0,0,0.2); border-radius: 4px; line-height: 1.5; white-space: pre-wrap; word-break: break-word; }
@keyframes thinking-pulse { 0%,100%{opacity:.4} 50%{opacity:1} }
.thinking-dots span { animation: thinking-pulse 1.2s ease-in-out infinite; }
.thinking-dots span:nth-child(2){animation-delay:.2s}
.thinking-dots span:nth-child(3){animation-delay:.4s}
.step-icon { font-size: 14px; flex-shrink: 0; }
.step-info { flex: 1; }
.step-name { font-weight: 600; color: var(--text); }
.step-desc { color: var(--muted); font-size: 11px; margin-top: 2px; }
.typing-indicator { display: flex; align-items: center; gap: 4px; padding: 4px 0 8px; }
.typing-dot { width: 6px; height: 6px; border-radius: 50%; background: var(--muted); animation: typing 1.4s infinite; }
.typing-dot:nth-child(2) { animation-delay: 0.2s; }
.typing-dot:nth-child(3) { animation-delay: 0.4s; }
@keyframes typing { 0%,100% { transform: translateY(0); opacity: 0.5; } 50% { transform: translateY(-4px); opacity: 1; } }
.welcome { display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100%; gap: 20px; padding: 40px; text-align: center; }
.welcome-logo { font-size: 56px; color: var(--teal); filter: drop-shadow(0 0 20px rgba(0,201,167,0.4)); }
.welcome h2 { font-size: 24px; font-weight: 700; color: var(--text); }
.welcome p { font-size: 14px; color: var(--muted); max-width: 480px; line-height: 1.7; }
.suggestions { display: flex; flex-wrap: wrap; gap: 8px; justify-content: center; margin-top: 8px; }
.suggest-chip { padding: 8px 16px; border: 1px solid var(--border); border-radius: 20px; font-size: 13px; color: var(--muted); cursor: pointer; transition: all 0.15s; background: var(--surface); }
.suggest-chip:hover { border-color: var(--teal); color: var(--teal); background: rgba(0,201,167,0.06); }
.input-area { padding: 16px 24px 20px; border-top: 1px solid var(--border); background: var(--surface); max-height: min(58vh, 680px); overflow-y: auto; overscroll-behavior: contain; }
.mode-row { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }
.mode-pill { border:1px solid var(--border); background:var(--bg); color:var(--muted); border-radius:999px; padding:7px 12px; font-size:12px; font-weight:600; cursor:pointer; transition:all .15s; }
.mode-pill:hover { border-color: var(--teal); color: var(--teal); }
.mode-pill.active { background: rgba(0,201,167,0.12); border-color: rgba(0,201,167,0.45); color: var(--teal); }
.mode-pill:disabled { cursor:not-allowed; opacity:.45; border-color: var(--border); color: var(--muted); background: rgba(255,255,255,0.03); }
.deep-research-panel { display:none; margin-bottom:12px; padding:14px; border:1px solid rgba(0,201,167,0.18); border-radius:12px; background:linear-gradient(180deg, rgba(0,201,167,0.06), rgba(83,82,237,0.05)); }
.deep-research-panel.visible { display:block; max-height:min(46vh, 560px); overflow-y:auto; }
.deep-research-panel.collapsed { max-height:none; overflow:visible; }
.deep-research-panel.collapsed .dr-body { display:none; }
.security-panel { display:none; margin-bottom:12px; padding:14px; border:1px solid rgba(251,113,133,0.3); border-radius:12px; background:linear-gradient(180deg, rgba(251,113,133,0.06), rgba(239,68,68,0.04)); }
.security-panel.visible { display:block; }
.sec-head { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:12px; }
.sec-title { font-size:13px; font-weight:700; color:#f87171; margin-bottom:2px; }
.sec-subtitle { font-size:11px; color:var(--muted); line-height:1.4; }
.sec-grid { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
.sec-field { display:flex; flex-direction:column; gap:4px; }
.sec-field label { font-size:11px; font-weight:600; color:var(--muted); text-transform:uppercase; letter-spacing:.04em; }
.sec-input { background:var(--bg); border:1px solid var(--border); border-radius:7px; padding:7px 10px; font-size:12px; color:var(--text); width:100%; box-sizing:border-box; }
.sec-input:focus { outline:none; border-color:rgba(251,113,133,0.6); }
.sec-auth-row { display:flex; align-items:center; gap:8px; margin-top:10px; padding:10px 12px; background:rgba(251,113,133,0.08); border:1px solid rgba(251,113,133,0.2); border-radius:8px; }
.sec-auth-row input[type=checkbox] { width:16px; height:16px; accent-color:#f87171; cursor:pointer; flex-shrink:0; }
.sec-auth-label { font-size:12px; color:#f87171; font-weight:600; line-height:1.4; }
.sec-warn { font-size:11px; color:var(--muted); margin-top:8px; line-height:1.4; padding:8px 10px; background:rgba(251,113,133,0.05); border-radius:6px; border-left:3px solid rgba(251,113,133,0.4); }
.dr-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; margin-bottom:10px; flex-wrap:wrap; }
.dr-head > div:first-child { flex:1 1 320px; min-width:0; }
.dr-title { font-size:12px; font-weight:700; color:var(--teal); letter-spacing:.08em; text-transform:uppercase; }
.dr-subtitle { font-size:12px; color:var(--muted); line-height:1.5; max-width:none; }
.dr-head-actions { display:flex; align-items:center; gap:10px; flex:1 1 260px; flex-wrap:wrap; justify-content:flex-end; }
.dr-summary-bar { display:flex; flex-wrap:wrap; gap:8px; justify-content:flex-end; min-width:0; }
.dr-summary-pill { display:inline-flex; align-items:center; gap:6px; padding:6px 10px; border-radius:999px; border:1px solid rgba(255,255,255,0.08); background:rgba(255,255,255,0.04); font-size:11px; color:var(--muted); max-width:100%; white-space:normal; }
.dr-summary-pill strong { white-space:nowrap; }
.dr-toggle-btn { border:1px solid var(--border); background:rgba(0,0,0,0.16); color:var(--text); border-radius:999px; padding:7px 12px; font-size:11px; font-weight:700; cursor:pointer; transition:all .15s; }
.dr-toggle-btn:hover { border-color: var(--teal); color: var(--teal); }
.dr-grid { display:grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap:10px; }
.dr-field { display:flex; flex-direction:column; gap:6px; }
.dr-field label { font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.05em; }
.dr-select, .dr-input { background: var(--bg); border:1px solid var(--border); color:var(--text); border-radius:8px; padding:8px 10px; font-size:12px; }
.dr-textarea { min-height: 88px; resize: vertical; font-family: inherit; }
.dr-checks { display:flex; flex-wrap:wrap; gap:8px; }
.dr-check { display:inline-flex; align-items:center; gap:6px; padding:6px 8px; border:1px solid var(--border); border-radius:8px; background:rgba(255,255,255,0.02); font-size:12px; color:var(--text); }
.dr-check input { accent-color: var(--teal); }
.dr-actions { display:flex; gap:8px; flex-wrap:wrap; }
.dr-action-btn { border:1px solid var(--border); background:var(--bg); color:var(--text); border-radius:8px; padding:8px 12px; font-size:12px; font-weight:600; cursor:pointer; transition:all .15s; }
.dr-action-btn:hover { border-color: var(--teal); color: var(--teal); }
.dr-chip-list { display:flex; flex-wrap:wrap; gap:8px; }
.dr-chip { display:inline-flex; align-items:center; gap:8px; padding:6px 10px; border-radius:999px; background:rgba(0,201,167,0.08); border:1px solid rgba(0,201,167,0.18); font-size:12px; color:var(--text); }
.dr-chip button { border:none; background:transparent; color:var(--muted); cursor:pointer; font-size:12px; padding:0; }
.dr-chip button:hover { color: var(--crimson); }
.dr-note { font-size:11px; color:var(--muted); line-height:1.5; }
.input-row { display: flex; gap: 12px; align-items: stretch; }
.input-box { flex: 1; background: var(--bg); border: 1px solid var(--border); border-radius: 14px; padding: 14px 18px; color: var(--text); font-size: 14px; font-family: inherit; resize: none; min-height: 52px; max-height: min(32vh, 260px); overflow-y: auto; line-height: 1.5; transition: border-color 0.15s, opacity 0.15s; outline: none; }
.input-box:focus { border-color: var(--teal); }
.input-box::placeholder { color: var(--muted); }
.input-box.locked { opacity: 0.75; cursor: not-allowed; }
.send-btn { width: 48px; min-height: 48px; border-radius: 12px; background: var(--teal); border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; transition: background 0.15s, opacity 0.15s; color: #0d0f14; align-self: flex-end; }
.send-btn:hover { background: #00b396; }
.send-btn.stop-mode { background: rgba(255,71,87,0.92); color: #fff; }
.send-btn.stop-mode:hover { background: rgba(255,71,87,1); }
.send-btn.cancelling { background: rgba(255,179,71,0.95); color: #0d0f14; }
.send-btn.cancelling:hover { background: rgba(255,179,71,0.95); }
.send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.input-hint { font-size: 11px; color: var(--muted); margin-top: 8px; }
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
.error-banner { background: rgba(255,71,87,0.1); border: 1px solid rgba(255,71,87,0.3); color: var(--crimson); border-radius: 8px; padding: 10px 14px; font-size: 13px; display: flex; gap: 8px; align-items: flex-start; }
.streaming-status { font-size: 11px; color: var(--amber); margin-top: 4px; font-style: italic; }
.chat-inspector { width: var(--inspector-w); min-width: var(--inspector-w); border-left: 1px solid var(--border); background: linear-gradient(180deg, rgba(255,255,255,0.03), transparent 18%), #10151c; padding: 16px; display:flex; flex-direction:column; gap:12px; overflow-y:auto; }
.chat-inspector-header { padding: 6px 2px 4px; }
.chat-inspector-title { font-size: 13px; font-weight: 700; color: var(--text); }
.chat-inspector-sub { font-size: 11px; color: var(--muted); margin-top: 3px; line-height: 1.45; }
.chat-inspector-card { border-radius: 14px; border: 1px solid var(--border); background: var(--surface); padding: 14px; display:flex; flex-direction:column; gap:10px; }
.chat-inspector-label { font-size: 10px; font-weight: 700; color: var(--muted); letter-spacing: 0.08em; text-transform: uppercase; }
.chat-inspector-title-row { font-size: 14px; font-weight: 700; color: var(--text); }
.chat-inspector-copy { font-size: 12px; line-height: 1.55; color: var(--muted); }
.chat-inspector-stat-grid { display:grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap:8px; }
.chat-inspector-stat { padding: 10px; border-radius: 10px; background: var(--surface2); border: 1px solid rgba(255,255,255,0.04); }
.chat-inspector-stat span { display:block; font-size:10px; color:var(--muted); text-transform:uppercase; letter-spacing:0.05em; }
.chat-inspector-stat strong { display:block; font-size:13px; color:var(--text); margin-top:5px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.chat-activity-list { display:flex; flex-direction:column; gap:8px; }
.chat-activity-empty { font-size:12px; color:var(--muted); line-height:1.5; }
.chat-activity-card { padding: 10px 11px; border-radius: 10px; background: var(--surface2); border: 1px solid rgba(255,255,255,0.05); }
.chat-activity-title { font-size: 12px; font-weight: 700; color: var(--text); }
.chat-activity-meta { font-size: 10px; color: var(--muted); margin-top: 4px; line-height: 1.45; }
.chat-activity-detail { font-size: 11px; color: var(--muted); margin-top: 6px; line-height: 1.45; white-space: pre-wrap; word-break: break-word; }
.chat-activity-command { margin-top: 6px; padding: 8px 9px; border-radius: 8px; border: 1px solid var(--border); background: rgba(0,0,0,0.16); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; color: #d7e3ff; white-space: pre-wrap; word-break: break-word; }
.chat-activity-status { font-size: 10px; font-weight: 700; padding: 3px 7px; border-radius: 999px; }
.chat-activity-status.running, .chat-activity-status.completed { color: var(--teal); background: rgba(0,201,167,0.12); }
.chat-activity-status.failed { color: var(--crimson); background: rgba(255,71,87,0.12); }
.chat-activity-status.pending, .chat-activity-status.queued, .chat-activity-status.info { color: var(--muted); background: rgba(255,255,255,0.06); }
.chat-command-preview { min-height: 70px; padding: 10px 12px; border-radius: 10px; background: rgba(0,0,0,0.18); border: 1px solid var(--border); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; color: #d7e3ff; white-space: pre-wrap; word-break: break-word; }
.approval-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,0.7); z-index:2200; align-items:center; justify-content:center; padding:20px; overflow:auto; }
.approval-overlay.open { display:flex; }
.approval-modal { width:min(560px, 100%); max-height:min(84vh, 920px); display:flex; flex-direction:column; background:var(--surface); border:1px solid var(--border); border-radius:16px; box-shadow:0 24px 60px rgba(0,0,0,0.45); overflow:hidden; }
.approval-modal-head { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:18px 20px 14px; border-bottom:1px solid var(--border); }
.approval-modal-title { font-size:15px; font-weight:700; color:var(--text); }
.approval-modal-sub { font-size:11px; color:var(--muted); margin-top:4px; }
.approval-modal-close { background:none; border:none; color:var(--muted); font-size:20px; cursor:pointer; line-height:1; }
.approval-modal-body { padding:18px 20px; overflow-y:auto; min-height:0; }
.approval-scope { display:inline-flex; align-items:center; gap:6px; padding:4px 9px; border-radius:999px; background:rgba(83,82,237,0.14); border:1px solid rgba(83,82,237,0.35); color:#b8b7ff; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:0.05em; }
.approval-prompt { margin-top:12px; font-size:13px; color:var(--text); line-height:1.6; white-space:pre-wrap; }
.approval-help { margin-top:10px; font-size:12px; color:var(--muted); line-height:1.5; }
.approval-suggest-box { display:none; margin-top:14px; }
.approval-suggest-box.open { display:block; }
.approval-textarea { width:100%; min-height:100px; resize:vertical; background:var(--bg); border:1px solid var(--border); border-radius:12px; color:var(--text); font:inherit; padding:12px 14px; line-height:1.5; outline:none; }
.approval-textarea:focus { border-color: var(--teal); }
.approval-actions { display:flex; flex-wrap:wrap; gap:10px; margin-top:16px; }
.approval-btn { border:none; border-radius:10px; padding:10px 16px; font-size:13px; font-weight:700; cursor:pointer; transition:opacity .15s, transform .15s; }
.approval-btn:hover { opacity:.92; transform:translateY(-1px); }
.approval-btn.accept { background:var(--teal); color:#0d0f14; }
.approval-btn.reject { background:rgba(255,71,87,0.16); border:1px solid rgba(255,71,87,0.35); color:var(--crimson); }
.approval-btn.suggest { background:rgba(83,82,237,0.16); border:1px solid rgba(83,82,237,0.35); color:#b8b7ff; }
.approval-btn.submit { background:rgba(255,255,255,0.08); border:1px solid var(--border); color:var(--text); }
@media (max-width: 1280px) {
  :root { --inspector-w: 0px; }
  .chat-inspector { display:none; }
}
@media (max-height: 900px) {
  .messages { padding: 16px; gap: 12px; }
  .welcome { padding: 20px 18px; gap: 12px; }
  .welcome-logo { font-size: 44px; }
  .welcome h2 { font-size: 20px; }
  .input-area { padding: 12px 16px 14px; max-height: min(66vh, 760px); }
  .deep-research-panel.visible { max-height: min(50vh, 500px); }
}
</style>
</head>
<body class="mode-agent">
<div class="sidebar">
  <div class="sidebar-header">
    <div class="logo">kendr<span>.</span></div>
    <div class="tagline">Multi-agent intelligence runtime</div>
  </div>
  <div class="sidebar-nav">
    <a href="/" class="nav-btn active"><span class="icon">💬</span> Chat</a>
    <a href="/setup" class="nav-btn"><span class="icon">⚙️</span> Setup & Config</a>
    <a href="/runs" class="nav-btn"><span class="icon">📋</span> Run History</a>
    <a href="/skills" class="nav-btn"><span class="icon">🧠</span> Skill Cards</a>
    <a href="/rag" class="nav-btn"><span class="icon">🔬</span> Super-RAG</a>
    <a href="/models" class="nav-btn"><span class="icon">&#x1F916;</span> LLM Models</a>
    <a href="/capabilities" class="nav-btn"><span class="icon">&#x2692;&#xFE0F;</span> Capabilities</a>
    <a href="/projects" class="nav-btn"><span class="icon">📁</span> Projects</a>
    <a href="/docs" class="nav-btn"><span class="icon">📖</span> Docs</a>
  </div>
  <button class="new-chat-btn" onclick="newChat()">+ New Chat</button>
  <!-- Active project context panel -->
  <div class="proj-panel" id="projPanel">
    <div class="proj-panel-header" onclick="toggleProjPanel()">
      <span class="proj-panel-icon">&#x1F4C1;</span>
      <span class="proj-panel-name" id="projPanelName"><span class="proj-panel-none">No project active</span></span>
      <span class="proj-panel-badge" id="projPanelBadge" style="display:none">Active</span>
      <span style="font-size:11px;color:var(--muted)" id="projPanelChevron">&#x25BE;</span>
    </div>
    <div class="proj-panel-body" id="projPanelBody">
      <div class="proj-stack" id="projStack"></div>
      <div class="proj-md-status" id="projMdStatus">
        <div class="proj-md-dot amber" id="projMdDot"></div>
        <span id="projMdText">kendr.md not generated yet</span>
      </div>
      <div class="proj-action-row">
        <button class="proj-action-btn primary" onclick="generateKendrMd()" id="btnGenMd">&#x2728; Generate kendr.md</button>
        <button class="proj-action-btn" onclick="openKendrMdEditor()" id="btnEditMd">&#x270F; Edit</button>
        <button class="proj-action-btn" onclick="loadProjContext()">&#x21BB; Refresh</button>
      </div>
    </div>
  </div>
  <div class="sidebar-section">Recent Chats</div>
  <div class="run-list" id="runList"></div>
</div>

<!-- kendr.md editor modal -->
<div class="kdmd-modal" id="kdmdModal">
  <div class="kdmd-box">
    <div class="kdmd-header">
      <div class="kdmd-title">&#x1F4DD; Edit kendr.md &mdash; Project Context File</div>
      <button class="kdmd-close" onclick="closeKendrMdEditor()">&times;</button>
    </div>
    <textarea class="kdmd-textarea" id="kdmdTextarea" placeholder="kendr.md content..."></textarea>
    <div class="kdmd-footer">
      <button class="kdmd-cancel" onclick="closeKendrMdEditor()">Cancel</button>
      <button class="kdmd-save" onclick="saveKendrMd()">&#x2714; Save kendr.md</button>
    </div>
  </div>
</div>

<div class="chat-main">
  <div class="chat-header">
    <div>
      <div class="chat-title" id="chatTitle">New Chat</div>
      <div class="chat-subtitle">Powered by kendr multi-agent runtime</div>
    </div>
    <div class="header-status">
      <button id="shellModeBtn" class="shell-mode-btn" onclick="toggleShellMode()" title="Enable shell automation — lets agents install tools, run commands, and execute multi-step workflows">
        <span class="shell-mode-icon">&#x1F4BB;</span> Shell
      </button>
      <button class="clear-chat-btn" id="clearChatBtn" onclick="deleteChat()" title="Delete this chat and all its data" style="display:none">&#x1F5D1; Delete</button>
      <div class="status-dot" id="gatewayDot"></div>
      <span id="gatewayStatus">Checking gateway...</span>
    </div>
  </div>
  <div class="chat-command-bar">
    <div class="chat-command-track" id="chatCommandTrack">Ask a question or launch a task. Kendr will show the live task, substeps, commands, and timing as the run progresses.</div>
    <div class="chat-command-modes">
      <div class="chat-command-chip active" id="chatModeChip">Chat</div>
      <div class="chat-command-chip" id="chatExecutionChip">Adaptive</div>
      <div class="chat-command-chip" id="chatResearchChip">Auto</div>
      <div class="chat-command-chip" id="chatShellChip">Shell Off</div>
      <div class="chat-command-chip" id="chatSecurityChip" style="display:none">Security Off</div>
    </div>
  </div>
  <div class="messages" id="messages">
    <div class="welcome" id="welcome">
      <div class="welcome-logo">&#x26A1;</div>
      <h2>What would you like help with today?</h2>
      <p>Kendr helps with everyday work: reading files, summarizing documents, organizing tasks, drafting messages, checking schedules, and finding up-to-date information.</p>
      <div class="suggestions">
        <div class="suggest-chip" onclick="fillInput('Summarize this PDF and extract action items')">&#x1F4C4; PDF action items</div>
        <div class="suggest-chip" onclick="fillInput('Find the latest version of our leave policy online')">&#x1F310; Policy web search</div>
        <div class="suggest-chip" onclick="fillInput('Read this spreadsheet and tell me the totals')">&#x1F4CA; Spreadsheet totals</div>
        <div class="suggest-chip" onclick="fillInput('Draft an email reply to this customer update')">&#x1F4EC; Draft reply</div>
        <div class="suggest-chip" onclick="fillInput('Organize my tasks for today')">&#x2705; Plan my day</div>
        <div class="suggest-chip" onclick="fillInput('Plan a simple weekend trip itinerary')">&#x1F9F3; Travel helper</div>
      </div>
    </div>
  </div>
  <div class="input-area">
    <div class="mode-row">
      <button class="mode-pill" id="modeDirectToolsBtn" onclick="setExecutionMode('direct_tools')">Direct Tools</button>
      <button class="mode-pill" id="modePlanModeBtn" onclick="setExecutionMode('plan')">Plan Mode</button>
      <button class="mode-pill active" id="modeAutoBtn" onclick="setResearchMode('auto')">Auto</button>
      <button class="mode-pill" id="modeDeepResearchBtn" onclick="setResearchMode('deep_research')">Deep Research</button>
      <button class="mode-pill" id="modeSecurityBtn" onclick="setSecurityMode(!securityMode)" title="Security Assessment — requires explicit authorization before any scan runs">&#x1F6E1; Security</button>
    </div>
    <div class="security-panel" id="securityPanel">
      <div class="sec-head">
        <div>
          <div class="sec-title">&#x1F7E2; Security Assessment — Authorized</div>
          <div class="sec-subtitle">Target URL and authorization note are auto-filled from your message. Override below if needed.</div>
        </div>
      </div>
      <div class="sec-grid">
        <div class="sec-field">
          <label for="secTargetUrl">Target URL <span style="font-weight:400;opacity:.6">(auto-detected from message)</span></label>
          <input id="secTargetUrl" class="sec-input" type="url" placeholder="https://example.com — or leave blank to auto-detect" oninput="_renderChatInspector()">
        </div>
        <div class="sec-field">
          <label for="secAuthNote">Authorization Note <span style="font-weight:400;opacity:.6">(auto-filled)</span></label>
          <input id="secAuthNote" class="sec-input" type="text" placeholder="Auto: Authorized via Security Assessment mode in Web UI" oninput="_renderChatInspector()">
        </div>
      </div>
      <input type="checkbox" id="secAuthorized" style="display:none" checked>
      <div class="sec-warn">Only use this mode on targets you own or have explicit written permission to assess. Enabling Security mode confirms authorization.</div>
    </div>
    <div class="deep-research-panel" id="deepResearchPanel">
      <div class="dr-head">
        <div>
          <div class="dr-title">Deep Research Mode</div>
          <div class="dr-subtitle">Tiered research flow with planning, sectioned writing, citations, plagiarism reporting, and multi-format exports.</div>
        </div>
        <div class="dr-head-actions">
          <div class="dr-summary-bar" id="deepResearchSummaryBar"></div>
          <button type="button" class="dr-toggle-btn" id="deepResearchToggleBtn" onclick="toggleDeepResearchPanel()">Collapse</button>
        </div>
      </div>
      <div class="dr-body" id="deepResearchPanelBody">
      <div class="dr-grid">
        <div class="dr-field">
          <label for="drPages">Approx. Length</label>
          <select id="drPages" class="dr-select" onchange="updateDeepResearchPanelSummary()">
            <option value="10">~10 pages</option>
            <option value="25" selected>~25 pages</option>
            <option value="50">~50 pages</option>
            <option value="100">~100 pages</option>
            <option value="150">~150 pages</option>
            <option value="200">~200 pages</option>
          </select>
          <div class="dr-note">This is a soft target. Final length can shift with citations, formatting, and source density.</div>
        </div>
        <div class="dr-field">
          <label for="drCitation">Citation Style</label>
          <select id="drCitation" class="dr-select" onchange="updateDeepResearchPanelSummary()">
            <option value="apa" selected>APA</option>
            <option value="mla">MLA</option>
            <option value="chicago">Chicago</option>
            <option value="ieee">IEEE</option>
            <option value="vancouver">Vancouver</option>
            <option value="harvard">Harvard</option>
          </select>
        </div>
        <div class="dr-field">
          <label for="drDateRange">Date Range</label>
          <select id="drDateRange" class="dr-select" onchange="updateDeepResearchPanelSummary()">
            <option value="all_time" selected>All time</option>
            <option value="1y">Last year</option>
            <option value="2y">Last 2 years</option>
            <option value="5y">Last 5 years</option>
          </select>
        </div>
        <div class="dr-field">
          <label for="drMaxSources">Max Sources</label>
          <input id="drMaxSources" class="dr-input" type="number" min="0" step="10" value="0" placeholder="0 = tier default" oninput="updateDeepResearchPanelSummary()">
        </div>
      </div>
      <div class="dr-grid" style="margin-top:10px">
        <div class="dr-field">
          <label>Output Formats</label>
          <div class="dr-checks">
            <label class="dr-check"><input type="checkbox" value="pdf" class="dr-format" checked onchange="updateDeepResearchPanelSummary()"> PDF</label>
            <label class="dr-check"><input type="checkbox" value="docx" class="dr-format" checked onchange="updateDeepResearchPanelSummary()"> DOCX</label>
            <label class="dr-check"><input type="checkbox" value="html" class="dr-format" checked onchange="updateDeepResearchPanelSummary()"> HTML</label>
            <label class="dr-check"><input type="checkbox" value="md" class="dr-format" checked onchange="updateDeepResearchPanelSummary()"> Markdown</label>
          </div>
        </div>
        <div class="dr-field">
          <label>Source Families</label>
          <div class="dr-checks">
            <label class="dr-check"><input type="checkbox" id="drWebSearch" checked onchange="toggleDeepResearchWebSearch()"> Web Search</label>
            <label class="dr-check"><input type="checkbox" value="web" class="dr-source dr-remote-source" checked onchange="updateDeepResearchPanelSummary()"> Web</label>
            <label class="dr-check"><input type="checkbox" value="arxiv" class="dr-source dr-remote-source" onchange="updateDeepResearchPanelSummary()"> Academic</label>
            <label class="dr-check"><input type="checkbox" value="patents" class="dr-source dr-remote-source" onchange="updateDeepResearchPanelSummary()"> Patents</label>
            <label class="dr-check"><input type="checkbox" value="news" class="dr-source dr-remote-source" onchange="updateDeepResearchPanelSummary()"> News</label>
            <label class="dr-check"><input type="checkbox" value="reddit" class="dr-source dr-remote-source" onchange="updateDeepResearchPanelSummary()"> Community</label>
          </div>
          <div class="dr-note" id="drWebModeNote">Web search and explicit links are enabled. Disable this to restrict the report to local files/folders only.</div>
        </div>
        <div class="dr-field">
          <label>Quality Gates</label>
          <div class="dr-checks">
            <label class="dr-check"><input type="checkbox" id="drPlagiarism" checked onchange="updateDeepResearchPanelSummary()"> Plagiarism Check</label>
            <label class="dr-check"><input type="checkbox" id="drCheckpoint" onchange="updateDeepResearchPanelSummary()"> Checkpointing</label>
          </div>
        </div>
      </div>
      <div class="dr-grid" style="margin-top:10px">
        <div class="dr-field">
          <label>Local Files And Folders</label>
          <div class="dr-actions">
            <button type="button" class="dr-action-btn" onclick="document.getElementById('drFileUploadInput').click()">Upload Files</button>
            <button type="button" class="dr-action-btn" onclick="document.getElementById('drFolderUploadInput').click()">Upload Folder</button>
          </div>
          <input type="file" id="drFileUploadInput" multiple style="display:none" onchange="handleDeepResearchUpload('files')">
          <input type="file" id="drFolderUploadInput" multiple webkitdirectory directory style="display:none" onchange="handleDeepResearchUpload('folder')">
          <div class="dr-note">Uploaded folders keep their directory tree. Images are OCR processed automatically during local-file ingestion.</div>
        </div>
        <div class="dr-field">
          <label>Add Local Path</label>
          <div class="dr-actions">
            <input id="drLocalPathInput" class="dr-input" type="text" placeholder="/path/to/folder or /path/to/file.pdf" style="flex:1;min-width:220px">
            <button type="button" class="dr-action-btn" onclick="addDeepResearchLocalPath()">Add Path</button>
          </div>
          <div class="dr-note">Use this when the folder or file is already on the machine running Kendr.</div>
        </div>
      </div>
      <div class="dr-grid" style="margin-top:10px">
        <div class="dr-field">
          <label>Explicit Content Links</label>
          <textarea id="drLinks" class="dr-input dr-textarea" placeholder="https://example.com/report&#10;https://example.com/dataset" oninput="renderDeepResearchSourceSummary()"></textarea>
          <div class="dr-note">These exact URLs will be fetched and extracted as part of the report only when Web Search is enabled.</div>
        </div>
      </div>
      <div class="dr-grid" style="margin-top:10px">
        <div class="dr-field">
          <label>Attached Sources</label>
          <div id="drSourceSummary" class="dr-chip-list"></div>
        </div>
      </div>
      </div>
    </div>
    <div id="mainChatAttachChips" class="chat-attach-chips"></div>
    <div class="input-row">
      <input type="file" id="mainChatFileInput" multiple style="display:none" onchange="handleMainChatFileSelect(this)">
      <button class="attach-btn" onclick="document.getElementById('mainChatFileInput').click()" title="Attach files">&#x1F4CE;</button>
      <textarea class="input-box" id="userInput" placeholder="Ask kendr anything &#x2014; research, code, deploy, analyze..." rows="1" onkeydown="handleKey(event)" oninput="autoResize(this)"></textarea>
      <button class="send-btn" id="sendBtn" onclick="handleSendButton()" title="Send (Enter)">&#x27A4;</button>
    </div>
    <div class="input-hint">Enter to send &#xB7; Shift+Enter for new line &#xB7; Start gateway if offline: <code>kendr gateway start</code></div>
    <div class="shell-mode-banner" id="shellModeBanner">&#x26A0;&#xFE0F; Shell Automation is ON &#x2014; agents may install tools and run commands on this machine</div>
  </div>
</div>
<aside class="chat-inspector">
  <div class="chat-inspector-header">
    <div class="chat-inspector-title">Execution Lens</div>
    <div class="chat-inspector-sub">Codex-style visibility for normal chat runs: current task, recent activity, latest command, and runtime status without leaving the conversation.</div>
  </div>
  <div class="chat-inspector-card">
    <div class="chat-inspector-label">Run Pulse</div>
    <div class="chat-inspector-title-row" id="chatInspectorRunTitle">No active run</div>
    <div class="chat-inspector-copy" id="chatInspectorRunSubtitle">Start a run to see live execution state, timing, and command activity.</div>
    <div class="chat-inspector-stat-grid">
      <div class="chat-inspector-stat"><span>Status</span><strong id="chatInspectorStatus">Idle</strong></div>
      <div class="chat-inspector-stat"><span>Mode</span><strong id="chatInspectorMode">Auto</strong></div>
      <div class="chat-inspector-stat"><span>Run</span><strong id="chatInspectorRunId">-</strong></div>
      <div class="chat-inspector-stat"><span>Gateway</span><strong id="chatInspectorGateway">Offline</strong></div>
    </div>
  </div>
  <div class="chat-inspector-card">
    <div class="chat-inspector-label">Active Task</div>
    <div class="chat-inspector-title-row" id="chatInspectorTask">No active task</div>
    <div class="chat-inspector-copy" id="chatInspectorTaskMeta">The current run objective, plan summary, and elapsed timing will appear here.</div>
  </div>
  <div class="chat-inspector-card">
    <div class="chat-inspector-label">Latest Command</div>
    <div class="chat-inspector-copy" id="chatInspectorCommandMeta">No shell command has executed in this chat yet.</div>
    <div class="chat-command-preview" id="chatInspectorCommand">No command activity yet.</div>
  </div>
  <div class="chat-inspector-card">
    <div class="chat-inspector-label">Recent Activity</div>
    <div class="chat-activity-list" id="chatInspectorActivityList">
      <div class="chat-activity-empty">Runs, task steps, command executions, and failures will appear here with timestamps and durations.</div>
    </div>
  </div>
</aside>
<div class="approval-overlay" id="chatApprovalModal">
  <div class="approval-modal">
    <div class="approval-modal-head">
      <div>
        <div class="approval-modal-title">Awaiting Approval</div>
        <div class="approval-modal-sub">Review the pending request, then accept, reject, or send guidance.</div>
      </div>
      <button class="approval-modal-close" type="button" onclick="_closeChatApprovalModal()">&times;</button>
    </div>
    <div class="approval-modal-body">
      <div class="approval-scope" id="chatApprovalScope">Approval</div>
      <div class="approval-prompt" id="chatApprovalPrompt">This run is waiting for your response.</div>
      <div class="approval-help" id="chatApprovalHelp">Accept continues immediately. Reject asks the runtime to revise instead of continuing. Suggestion sends your guidance back into the paused run.</div>
      <div class="approval-suggest-box" id="chatApprovalSuggestBox">
        <textarea class="approval-textarea" id="chatApprovalSuggestion" placeholder="Tell Kendr what to change before continuing..."></textarea>
      </div>
      <div class="approval-actions">
        <button class="approval-btn accept" id="chatApprovalAcceptBtn" type="button" onclick="_submitChatApproval('approve')">Accept</button>
        <button class="approval-btn reject" id="chatApprovalRejectBtn" type="button" onclick="_submitChatApproval('reject')">Reject</button>
        <button class="approval-btn suggest" id="chatApprovalSuggestBtn" type="button" onclick="_toggleChatApprovalSuggestion()">Suggestion</button>
        <button class="approval-btn submit" type="button" id="chatApprovalSuggestSubmit" onclick="_submitChatApproval('suggest')" style="display:none">Send Suggestion</button>
      </div>
    </div>
  </div>
</div>
<script>
const API = '';
let currentRunId = null;
let currentWorkflowId = null;
let isRunning = false;
let isAwaitingInput = false;
let isStopping = false;
let gatewayOnline = false;
let workingDir = '';
let activeEvtSource = null;
let _loadRunToken = 0;
let shellModeActive = false;
let securityMode = false;
let researchMode = 'auto';
let executionMode = (localStorage.getItem('kendr_execution_mode') || 'adaptive').toLowerCase();
if (!['direct_tools', 'plan', 'adaptive'].includes(executionMode)) executionMode = 'adaptive';
let deepResearchUploadedRoots = [];
let deepResearchLocalPaths = [];
let deepResearchPanelCollapsed = (localStorage.getItem('kendr_deep_research_collapsed') || '0') === '1';
let _chatActivityFeed = [];
let _chatPlanState = { total: 0, completed: 0, running: 0, failed: 0 };
let _chatRunState = { runId: '', status: 'idle', title: '', task: '', startedAt: '', completedAt: '', lastCommand: '', lastCommandMeta: '' };
let _runStepJournal = {};
let _runLiveUpdates = {};
let _runTraceFeed = {};
let _runWorkingTimers = {};
let _runRecoveryAttempts = {};
let _lastFailedRunContext = null;
let _chatAwaitingContext = null;
// Track the last completed deep research result for inline file-request handling
let _lastDeepResearchCard = null;
let _lastDocExports = null;
let _lastCompletedRunId = '';
let _mainChatAttachments = [];
let _projChatAttachments = [];

function _defaultChatPlaceholder() {
  return researchMode === 'deep_research'
    ? 'Describe the deep research task, scope, and output you want...'
    : 'Ask kendr anything — research, code, deploy, analyze…';
}

function _setChatComposerState() {
  const input = document.getElementById('userInput');
  const button = document.getElementById('sendBtn');
  if (!input || !button) return;
  const locked = isRunning;
  const modeButtons = [
    'modeDirectToolsBtn',
    'modePlanModeBtn',
    'modeAutoBtn',
    'modeDeepResearchBtn',
    'modeSecurityBtn',
  ];
  input.readOnly = locked;
  input.classList.toggle('locked', locked);
  button.disabled = isStopping;
  button.classList.toggle('stop-mode', locked && !isStopping);
  button.classList.toggle('cancelling', isStopping);
  modeButtons.forEach(id => {
    const el = document.getElementById(id);
    if (!el) return;
    el.disabled = locked;
    el.title = locked ? 'Mode changes are disabled while a run is active.' : '';
  });
  if (locked) {
    button.innerHTML = '&#x25A0;';
    button.title = isStopping ? 'Stopping active run…' : 'Stop active run';
    input.placeholder = isStopping
      ? 'Stopping the active run…'
      : 'Kendr is working on this run. Stop it before typing a new request.';
  } else {
    button.innerHTML = '&#x27A4;';
    button.title = 'Send (Enter)';
    input.placeholder = isAwaitingInput
      ? 'Type your response to continue…'
      : _defaultChatPlaceholder();
  }
}

function _chatStatusLabel(status) {
  const normalized = String(status || 'idle').replace(/_/g, ' ').trim();
  return normalized ? normalized.charAt(0).toUpperCase() + normalized.slice(1) : 'Idle';
}

function _chatActivityKey(item) {
  return [
    item.id || '',
    item.title || '',
    item.status || '',
    item.command || '',
    item.detail || '',
    item.started_at || item.timestamp || '',
    item.completed_at || '',
  ].join('|');
}

function _chatActivityTimestamp(item) {
  return item && (item.completed_at || item.started_at || item.timestamp || '');
}

function _normalizeChatActivity(item, defaults = {}) {
  const merged = Object.assign({}, defaults || {}, item || {});
  if (!merged.status) merged.status = 'info';
  if (!merged.title) merged.title = merged.kind || 'Activity';
  if (!merged.timestamp) merged.timestamp = _chatActivityTimestamp(merged) || new Date().toISOString();
  return merged;
}

function _chatActivitySortValue(item) {
  const ts = _chatActivityTimestamp(item);
  const parsed = ts ? Date.parse(ts) : NaN;
  return Number.isFinite(parsed) ? parsed : Date.now();
}

function _chatActivityMetaParts(item) {
  const parts = [];
  const task = String(item.task || '').trim();
  const subtask = String(item.subtask || '').trim();
  const actor = String(item.actor || '').trim();
  const started = _formatStepTimestamp(item.started_at || item.timestamp);
  const completed = _formatStepTimestamp(item.completed_at);
  const duration = item.duration_label || _formatStepDuration(item);
  if (task) parts.push(task);
  if (subtask) parts.push(subtask);
  else if (actor) parts.push(actor);
  if (started) parts.push(started);
  if (completed && completed !== started) parts.push('done ' + completed);
  if (duration) parts.push(duration);
  if (item.exit_code !== undefined && item.exit_code !== null && item.exit_code !== '') parts.push('exit ' + item.exit_code);
  return parts;
}

function _chatActivityStatusClass(status) {
  const normalized = String(status || 'info').toLowerCase();
  if (['running', 'completed', 'failed', 'pending', 'queued', 'info'].includes(normalized)) return normalized;
  return 'info';
}

function _renderChatActivityList() {
  const box = document.getElementById('chatInspectorActivityList');
  if (!box) return;
  const items = Array.isArray(_chatActivityFeed) ? _chatActivityFeed.slice(0, 7) : [];
  if (!items.length) {
    box.innerHTML = '<div class="chat-activity-empty">Runs, task steps, command executions, and failures will appear here with timestamps and durations.</div>';
    return;
  }
  box.innerHTML = items.map(item => {
    const meta = _chatActivityMetaParts(item).map(esc).join(' &middot; ');
    const detail = item.detail ? '<div class="chat-activity-detail">' + esc(String(item.detail).slice(0, 220)) + '</div>' : '';
    const command = item.command ? '<div class="chat-activity-command">' + esc(item.command) + '</div>' : '';
    const status = _chatActivityStatusClass(item.status);
    return `
      <div class="chat-activity-card">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px">
          <div class="chat-activity-title">${esc(item.title || item.kind || 'Activity')}</div>
          <div class="chat-activity-status ${esc(status)}">${esc(status)}</div>
        </div>
        ${meta ? '<div class="chat-activity-meta">' + meta + '</div>' : ''}
        ${detail}
        ${command}
      </div>
    `;
  }).join('');
}

function _runTraceKey(item) {
  return [
    item.id || '',
    item.title || '',
    item.status || '',
    item.command || '',
    item.detail || '',
    item.started_at || item.timestamp || '',
    item.completed_at || '',
  ].join('|');
}

function _recordRunTraceEvents(runId, items, defaults = {}) {
  if (!runId) return;
  const next = Array.isArray(items) ? items.map(item => _normalizeChatActivity(item, defaults)) : [];
  if (!next.length) return;
  const merged = next.concat(_runTraceFeed[runId] || []);
  const deduped = [];
  const seen = new Set();
  for (const item of merged.sort((a, b) => _chatActivitySortValue(b) - _chatActivitySortValue(a))) {
    const key = _runTraceKey(item);
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(item);
    if (deduped.length >= 40) break;
  }
  _runTraceFeed[runId] = deduped;
}

function _runTraceListHtml(items) {
  const normalized = Array.isArray(items) ? items.slice(0, 10) : [];
  if (!normalized.length) {
    return '<div style="font-size:12px;color:var(--muted)">Research trace will appear here as searches, evidence fetches, drafting, and exports run.</div>';
  }
  return normalized.map(item => {
    const status = String(item.status || 'info').toLowerCase();
    const title = String(item.title || item.kind || 'Activity').trim() || 'Activity';
    const detail = String(item.detail || '').trim();
    const command = String(item.command || '').trim();
    const metadata = (item && typeof item.metadata === 'object' && item.metadata) ? item.metadata : {};
    const phase = String(metadata.phase || '').trim();
    const searchQuery = String(metadata.search_query || '').trim();
    const searchProvider = String(metadata.search_provider || '').trim();
    const providersTried = Array.isArray(metadata.search_providers_tried) ? metadata.search_providers_tried.filter(Boolean) : [];
    const candidateUrls = Array.isArray(metadata.candidate_urls) ? metadata.candidate_urls.filter(Boolean) : [];
    const viewedUrls = Array.isArray(metadata.viewed_urls) ? metadata.viewed_urls.filter(Boolean) : [];
    const failedUrls = Array.isArray(metadata.failed_urls) ? metadata.failed_urls.filter(Boolean) : [];
    const displayCommand = command || searchQuery;
    const meta = _chatActivityMetaParts(item).map(esc).join(' &middot; ');
    const color = status === 'failed' ? 'var(--crimson)' : status === 'completed' ? 'var(--teal)' : status === 'running' ? 'var(--amber)' : '#9aa4b2';
    const badge = status === 'failed' ? 'failed' : status === 'completed' ? 'done' : status === 'running' ? 'live' : 'info';
    const phaseHtml = phase ? '<span style="padding:2px 7px;border-radius:999px;background:rgba(255,255,255,0.06);font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">' + esc(String(phase).replace(/_/g, ' ')) + '</span>' : '';
    const statusHtml = '<span style="padding:2px 7px;border-radius:999px;background:' + (badge === 'failed' ? 'rgba(255,71,87,0.12)' : badge === 'done' ? 'rgba(0,201,167,0.12)' : badge === 'live' ? 'rgba(255,179,71,0.12)' : 'rgba(255,255,255,0.06)') + ';font-size:10px;color:' + color + ';text-transform:uppercase;letter-spacing:.06em">' + esc(status) + '</span>';
    const providerHtml = searchProvider
      ? '<div style="margin-top:6px;font-size:11px;color:var(--muted)">Search provider: <span style="color:var(--text)">' + esc(searchProvider) + '</span>' + (providersTried.length ? ' &middot; tried: ' + esc(providersTried.join(', ')) : '') + '</div>'
      : '';
    const commandHtml = displayCommand
      ? '<div style="margin-top:7px;padding:8px 10px;border-radius:8px;border:1px solid var(--border);background:rgba(0,0,0,0.16);font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;color:#d7e3ff;white-space:pre-wrap;word-break:break-word">' + esc(displayCommand) + '</div>'
      : '';
    const detailHtml = detail && detail !== displayCommand
      ? '<div style="margin-top:6px;font-size:11px;color:var(--muted);line-height:1.5;white-space:pre-wrap;word-break:break-word">' + esc(detail) + '</div>'
      : '';
    const listBlock = (label, urls, tone) => {
      if (!urls.length) return '';
      const itemColor = tone === 'bad' ? 'var(--crimson)' : tone === 'good' ? '#9ad7ff' : 'var(--text)';
      return '<div style="margin-top:8px">'
        + '<div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:4px">' + esc(label) + '</div>'
        + urls.slice(0, 6).map(url => '<div style="font-size:11px;color:' + itemColor + ';white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(url) + '</div>').join('')
        + '</div>';
    };
    return '<div style="padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.05)">'
      + '<div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px">'
      + '<div>'
      + '<div style="font-size:12px;font-weight:700;color:var(--text)">' + esc(title) + '</div>'
      + (meta ? '<div style="margin-top:3px;font-size:10px;color:var(--muted)">' + meta + '</div>' : '')
      + '</div>'
      + '<div style="display:flex;gap:6px;flex-wrap:wrap;justify-content:flex-end">' + phaseHtml + statusHtml + '</div>'
      + '</div>'
      + providerHtml
      + detailHtml
      + commandHtml
      + listBlock('Search results', candidateUrls, 'good')
      + listBlock('Viewed links', viewedUrls, 'good')
      + listBlock('Failed links', failedUrls, 'bad')
      + '</div>';
  }).join('');
}

function _upsertRunTracePanel(runId, title = '') {
  if (!runId) return;
  const panel = document.getElementById('stream-trace-' + runId);
  if (!panel) return;
  const items = Array.isArray(_runTraceFeed[runId]) ? _runTraceFeed[runId] : [];
  const runningCount = items.filter(item => String(item.status || '').toLowerCase() === 'running').length;
  const heading = title || (runningCount > 1 ? 'Live Research Trace · overlapping tasks' : 'Live Research Trace');
  panel.innerHTML = '<div style="font-size:11px;font-weight:700;color:var(--amber);letter-spacing:.08em;text-transform:uppercase;margin-bottom:8px">' + esc(heading) + '</div>'
    + _runTraceListHtml(items);
}

function _recordChatActivities(items, defaults = {}) {
  const next = Array.isArray(items) ? items.map(item => _normalizeChatActivity(item, defaults)) : [];
  if (!next.length) return;
  const merged = next.concat(_chatActivityFeed || []);
  const deduped = [];
  const seen = new Set();
  for (const item of merged.sort((a, b) => _chatActivitySortValue(b) - _chatActivitySortValue(a))) {
    const key = _chatActivityKey(item);
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(item);
    if (deduped.length >= 40) break;
  }
  _chatActivityFeed = deduped;
  const latestCommand = deduped.find(item => item.command);
  if (latestCommand) {
    _chatRunState.lastCommand = latestCommand.command || '';
    _chatRunState.lastCommandMeta = _chatActivityMetaParts(latestCommand).join(' · ');
  }
  _renderChatActivityList();
  _renderChatInspector();
}

function _recordChatActivity(item, defaults = {}) {
  _recordChatActivities([item], defaults);
}

function _resetChatInspectorState() {
  _chatActivityFeed = [];
  _chatPlanState = { total: 0, completed: 0, running: 0, failed: 0 };
  _chatRunState = { runId: '', workflowId: '', attemptId: '', status: 'idle', title: '', task: '', startedAt: '', completedAt: '', lastCommand: '', lastCommandMeta: '' };
  _runTraceFeed = {};
  _runRecoveryAttempts = {};
  _renderChatActivityList();
  _renderChatInspector();
  isStopping = false;
  _setChatComposerState();
}

function _renderChatInspector() {
  const runTitle = document.getElementById('chatInspectorRunTitle');
  const runSubtitle = document.getElementById('chatInspectorRunSubtitle');
  const statusEl = document.getElementById('chatInspectorStatus');
  const modeEl = document.getElementById('chatInspectorMode');
  const runIdEl = document.getElementById('chatInspectorRunId');
  const gatewayEl = document.getElementById('chatInspectorGateway');
  const taskEl = document.getElementById('chatInspectorTask');
  const taskMetaEl = document.getElementById('chatInspectorTaskMeta');
  const cmdMetaEl = document.getElementById('chatInspectorCommandMeta');
  const cmdEl = document.getElementById('chatInspectorCommand');
  const trackEl = document.getElementById('chatCommandTrack');
  const shellChip = document.getElementById('chatShellChip');
  const executionChip = document.getElementById('chatExecutionChip');
  const modeChip = document.getElementById('chatResearchChip');
  const chatChip = document.getElementById('chatModeChip');
  if (runTitle) runTitle.textContent = _chatRunState.title || 'No active run';
  if (runSubtitle) {
    if (_chatRunState.runId) {
      const timing = [];
      const started = _formatStepTimestamp(_chatRunState.startedAt);
      const completed = _formatStepTimestamp(_chatRunState.completedAt);
      if (started) timing.push('Started ' + started);
      if (completed && completed !== started) timing.push('Finished ' + completed);
      runSubtitle.textContent = timing.join(' · ') || 'Live execution details for this run.';
    } else {
      runSubtitle.textContent = 'Start a run to see live execution state, timing, and command activity.';
    }
  }
  if (statusEl) statusEl.textContent = _chatStatusLabel(_chatRunState.status);
  const execLabel = executionMode === 'plan' ? 'Plan Mode' : (executionMode === 'adaptive' ? 'Adaptive' : 'Direct Tools');
  if (modeEl) modeEl.textContent = execLabel + ' · ' + (researchMode === 'deep_research' ? 'Deep Research' : 'Auto');
  if (runIdEl) {
    const workflowText = _chatRunState.workflowId || _chatRunState.runId || '-';
    const attemptText = _chatRunState.attemptId && _chatRunState.attemptId !== workflowText ? ' / ' + _chatRunState.attemptId : '';
    runIdEl.textContent = workflowText + attemptText;
  }
  if (gatewayEl) gatewayEl.textContent = gatewayOnline ? 'Online' : 'Offline';
  if (taskEl) taskEl.textContent = _chatRunState.task || 'No active task';
  if (taskMetaEl) {
    const parts = [];
    if (_chatPlanState.total) parts.push(_chatPlanState.completed + '/' + _chatPlanState.total + ' steps complete');
    if (_chatPlanState.running) parts.push(_chatPlanState.running + ' running');
    if (_chatPlanState.failed) parts.push(_chatPlanState.failed + ' failed');
    if (_chatRunState.startedAt && !_chatRunState.completedAt && _chatRunState.status === 'running') {
      const elapsed = _formatStepDuration({ started_at: _chatRunState.startedAt });
      if (elapsed) parts.push('elapsed ' + elapsed);
    }
    taskMetaEl.textContent = parts.join(' · ') || 'The current run objective, plan summary, and elapsed timing will appear here.';
  }
  if (cmdMetaEl) cmdMetaEl.textContent = _chatRunState.lastCommandMeta || 'No shell command has executed in this chat yet.';
  if (cmdEl) cmdEl.textContent = _chatRunState.lastCommand || 'No command activity yet.';
  if (trackEl) {
    trackEl.textContent = _chatRunState.task
      ? _chatRunState.task
      : 'Ask a question or launch a task. Kendr will show the live task, substeps, commands, and timing as the run progresses.';
  }
  if (shellChip) {
    shellChip.textContent = shellModeActive ? 'Shell On' : 'Shell Off';
    shellChip.classList.toggle('active', shellModeActive);
  }
  if (modeChip) {
    modeChip.textContent = researchMode === 'deep_research' ? 'Deep Research' : 'Auto';
    modeChip.classList.toggle('active', researchMode === 'deep_research');
  }
  if (executionChip) {
    executionChip.textContent = execLabel;
    executionChip.classList.toggle('active', executionMode === 'direct_tools' || executionMode === 'plan');
  }
  const secChip = document.getElementById('chatSecurityChip');
  if (secChip) {
    secChip.style.display = securityMode ? '' : 'none';
    secChip.textContent = securityMode ? 'Security: Authorized' : 'Security Off';
    secChip.classList.toggle('active', securityMode);
  }
  if (chatChip) chatChip.classList.add('active');
  if (_chatRunState.runId) {
    const heroTitle = document.getElementById('run-hero-title-' + _chatRunState.runId);
    const heroMeta = document.getElementById('run-hero-meta-' + _chatRunState.runId);
    if (heroTitle && _chatRunState.task) heroTitle.textContent = _chatRunState.task;
    if (heroMeta) {
      const parts = ['Run ' + _chatRunState.runId, _chatStatusLabel(_chatRunState.status)];
      if (_chatRunState.startedAt) parts.push(_formatStepTimestamp(_chatRunState.startedAt));
      if (_chatRunState.startedAt && !_chatRunState.completedAt && _chatRunState.status === 'running') {
        const elapsed = _formatStepDuration({ started_at: _chatRunState.startedAt });
        if (elapsed) parts.push('elapsed ' + elapsed);
      }
      heroMeta.innerHTML = parts.map(part => '<span>' + esc(part) + '</span>').join('');
    }
  }
}

function setResearchMode(mode) {
  if (isRunning) return;
  researchMode = mode || 'auto';
  const autoBtn = document.getElementById('modeAutoBtn');
  const drBtn = document.getElementById('modeDeepResearchBtn');
  const panel = document.getElementById('deepResearchPanel');
  if (autoBtn) autoBtn.classList.toggle('active', researchMode === 'auto');
  if (drBtn) drBtn.classList.toggle('active', researchMode === 'deep_research');
  if (panel) panel.classList.toggle('visible', researchMode === 'deep_research');
  updateDeepResearchPanelSummary();
  const input = document.getElementById('userInput');
  if (!input) return;
  input.placeholder = researchMode === 'deep_research'
    ? 'Describe the deep research task, scope, and output you want...'
    : 'Ask kendr anything — research, code, deploy, analyze...';
  if (researchMode === 'deep_research') {
    toggleDeepResearchWebSearch();
    renderDeepResearchSourceSummary();
  }
  _renderChatInspector();
}

function setExecutionMode(mode) {
  if (isRunning) return;
  const normalized = String(mode || 'direct_tools').toLowerCase();
  executionMode = normalized === 'plan' ? 'plan' : (normalized === 'adaptive' ? 'adaptive' : 'direct_tools');
  localStorage.setItem('kendr_execution_mode', executionMode);
  const directBtn = document.getElementById('modeDirectToolsBtn');
  const planBtn = document.getElementById('modePlanModeBtn');
  if (directBtn) directBtn.classList.toggle('active', executionMode === 'direct_tools');
  if (planBtn) planBtn.classList.toggle('active', executionMode === 'plan');
  _renderChatInspector();
}

function _deepResearchSummaryPill(label, value) {
  return '<span class="dr-summary-pill"><strong style="color:var(--text)">' + esc(label) + '</strong><span>' + esc(value) + '</span></span>';
}

function updateDeepResearchPanelSummary() {
  const panel = document.getElementById('deepResearchPanel');
  const body = document.getElementById('deepResearchPanelBody');
  const summary = document.getElementById('deepResearchSummaryBar');
  const toggleBtn = document.getElementById('deepResearchToggleBtn');
  if (panel) {
    panel.classList.toggle('visible', researchMode === 'deep_research');
    panel.classList.toggle('collapsed', !!deepResearchPanelCollapsed);
  }
  if (body) body.style.display = deepResearchPanelCollapsed ? 'none' : '';
  if (toggleBtn) toggleBtn.textContent = deepResearchPanelCollapsed ? 'Expand' : 'Collapse';
  if (!summary) return;
  const pages = '~' + (((document.getElementById('drPages') || {}).value || '50')) + ' pages';
  const citation = ((document.getElementById('drCitation') || {}).value || 'apa').toUpperCase();
  const maxSources = parseInt((document.getElementById('drMaxSources') || {}).value || '0', 10) || 0;
  const formatCount = _selectedDeepResearchFormats().length;
  const webEnabled = !!((document.getElementById('drWebSearch') || {}).checked);
  const localCount = _allDeepResearchLocalPaths().length;
  const linkCount = _deepResearchLinks().length;
  const sourceSummary = (webEnabled ? 'Web on' : 'Local only') + ' · ' + (localCount + linkCount) + ' attached';
  const maxSummary = maxSources > 0 ? String(maxSources) : 'tier default';
  summary.innerHTML = [
    _deepResearchSummaryPill('Scope', pages),
    _deepResearchSummaryPill('Citation', citation),
    _deepResearchSummaryPill('Sources', sourceSummary),
    _deepResearchSummaryPill('Formats', formatCount + ' selected'),
    _deepResearchSummaryPill('Cap', maxSummary),
  ].join('');
}

function toggleDeepResearchPanel() {
  deepResearchPanelCollapsed = !deepResearchPanelCollapsed;
  localStorage.setItem('kendr_deep_research_collapsed', deepResearchPanelCollapsed ? '1' : '0');
  updateDeepResearchPanelSummary();
}

function _selectedDeepResearchFormats() {
  return Array.from(document.querySelectorAll('.dr-format:checked')).map(el => el.value);
}

function _allDeepResearchLocalPaths() {
  return Array.from(new Set([...(deepResearchLocalPaths || []), ...(deepResearchUploadedRoots || [])]));
}

function _selectedDeepResearchSources() {
  const selected = Array.from(document.querySelectorAll('.dr-source:checked')).map(el => el.value);
  if (_allDeepResearchLocalPaths().length) selected.push('local');
  return Array.from(new Set(selected));
}

function _deepResearchLinks() {
  const raw = ((document.getElementById('drLinks') || {}).value || '').trim();
  if (!raw) return [];
  return Array.from(new Set(raw.split(/[\n,\s]+/).map(item => item.trim()).filter(item => /^https?:\/\//i.test(item))));
}

function toggleDeepResearchWebSearch() {
  const enabled = !!((document.getElementById('drWebSearch') || {}).checked);
  document.querySelectorAll('.dr-remote-source').forEach(el => {
    el.disabled = !enabled;
    if (!enabled) el.checked = false;
  });
  const linksEl = document.getElementById('drLinks');
  const noteEl = document.getElementById('drWebModeNote');
  if (linksEl) linksEl.disabled = !enabled;
  if (noteEl) {
    noteEl.textContent = enabled
      ? 'Web search and explicit links are enabled. Disable this to restrict the report to local files/folders only.'
      : 'Web search is disabled. This report will use only attached local files/folders and added local paths.';
  }
  renderDeepResearchSourceSummary();
  updateDeepResearchPanelSummary();
}

function addDeepResearchLocalPath() {
  const input = document.getElementById('drLocalPathInput');
  const value = (input && input.value || '').trim();
  if (!value) return;
  deepResearchLocalPaths.push(value);
  deepResearchLocalPaths = Array.from(new Set(deepResearchLocalPaths));
  if (input) input.value = '';
  renderDeepResearchSourceSummary();
  updateDeepResearchPanelSummary();
}

function removeDeepResearchLocalPath(value) {
  deepResearchLocalPaths = deepResearchLocalPaths.filter(item => item !== value);
  deepResearchUploadedRoots = deepResearchUploadedRoots.filter(item => item !== value);
  renderDeepResearchSourceSummary();
  updateDeepResearchPanelSummary();
}

async function handleDeepResearchUpload(kind) {
  const input = document.getElementById(kind === 'folder' ? 'drFolderUploadInput' : 'drFileUploadInput');
  const files = Array.from((input && input.files) || []);
  if (!files.length) return;
  const fd = new FormData();
  fd.append('chat_id', chatSessionId);
  fd.append('kind', kind);
  files.forEach(file => {
    fd.append('files', file, file.name);
    fd.append('relative_path', (kind === 'folder' && file.webkitRelativePath) ? file.webkitRelativePath : file.name);
  });
  try {
    const resp = await fetch(API + '/api/deep-research/upload', { method: 'POST', body: fd });
    const data = await resp.json();
    if (data.error) {
      alert('Upload error: ' + data.error);
      return;
    }
    if (data.upload_root) {
      deepResearchUploadedRoots.push(data.upload_root);
      deepResearchUploadedRoots = Array.from(new Set(deepResearchUploadedRoots));
    }
    renderDeepResearchSourceSummary();
    updateDeepResearchPanelSummary();
  } catch (err) {
    alert('Upload failed: ' + String(err));
  } finally {
    if (input) input.value = '';
  }
}

function renderDeepResearchSourceSummary() {
  const el = document.getElementById('drSourceSummary');
  if (!el) return;
  const chips = [];
  _allDeepResearchLocalPaths().forEach(path => {
    chips.push('<span class="dr-chip"><span>📁 ' + esc(path) + '</span><button type="button" onclick="removeDeepResearchLocalPath(' + JSON.stringify(path).replace(/"/g, '&quot;') + ')">✕</button></span>');
  });
  if (!!((document.getElementById('drWebSearch') || {}).checked)) {
    _deepResearchLinks().forEach(url => {
      chips.push('<span class="dr-chip"><span>🌐 ' + esc(url) + '</span></span>');
    });
  }
  if (!chips.length) {
    chips.push('<span class="dr-note">No local files, folders, paths, or explicit links attached yet.</span>');
  }
  el.innerHTML = chips.join('');
  updateDeepResearchPanelSummary();
}

function sendQuickReply(text) {
  const input = document.getElementById('userInput');
  if (!input || isRunning) return;
  input.value = text;
  autoResize(input);
  sendMessage();
}

function toggleShellMode() {
  shellModeActive = !shellModeActive;
  const btn = document.getElementById('shellModeBtn');
  const banner = document.getElementById('shellModeBanner');
  if (shellModeActive) {
    btn.classList.add('active');
    btn.title = 'Shell Automation ON \u2014 click to disable';
    if (banner) banner.classList.add('visible');
  } else {
    btn.classList.remove('active');
    btn.title = 'Enable shell automation \u2014 lets agents install tools, run commands, and execute multi-step workflows';
    if (banner) banner.classList.remove('visible');
  }
  _renderChatInspector();
}

function setSecurityMode(on) {
  if (isRunning) return;
  securityMode = !!on;
  const btn = document.getElementById('modeSecurityBtn');
  const panel = document.getElementById('securityPanel');
  const chip = document.getElementById('chatSecurityChip');
  if (btn) btn.classList.toggle('active', securityMode);
  if (panel) panel.classList.toggle('visible', securityMode);
  if (securityMode) {
    // One-click authorization: pre-check consent and pre-fill note automatically
    const authBox = document.getElementById('secAuthorized');
    const noteBox = document.getElementById('secAuthNote');
    if (authBox) authBox.checked = true;
    if (noteBox && !noteBox.value.trim()) noteBox.value = 'Authorized via Security Assessment mode in Web UI';
  }
  if (chip) {
    chip.style.display = securityMode ? '' : 'none';
    chip.textContent = securityMode ? 'Security: Authorized' : 'Security Off';
    chip.classList.toggle('active', securityMode);
  }
  _renderChatInspector();
}

function _renderTerminalBlock(text) {
  const lines = text.split(/\r?\n/);
  let steps = [];
  let curStep = null;
  for (const raw of lines) {
    const line = raw;
    if (/^\[STEP\s+\d+\]/i.test(line)) {
      curStep = { header: line, lines: [] };
      steps.push(curStep);
    } else if (curStep) {
      curStep.lines.push(line);
    } else {
      if (steps.length === 0) steps.push({ header: null, lines: [] });
      steps[steps.length - 1].lines.push(line);
    }
  }
  const makeLineClass = (l) => {
    if (/^\$\s/.test(l) || /^Running:/i.test(l)) return 'cmd';
    if (/^(error|Error|ERROR|traceback|Traceback|failed|FAILED)/i.test(l) || l.includes('stderr:')) return 'err';
    if (/^(\u2713|OK|Success|Done|Completed|SKIP|Already)/i.test(l.trim())) return 'ok';
    if (/^(BLOCKED|Permission|Not allowed)/i.test(l.trim())) return 'blocked';
    if (/^(Skipping|Skipped)/i.test(l.trim())) return 'skip';
    return 'out';
  };
  const esc2 = s => s.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  let html = '<div class="terminal-block"><div class="terminal-header">'
    + '<div class="terminal-dot" style="background:#FF5F57"></div>'
    + '<div class="terminal-dot" style="background:#FFBD2E"></div>'
    + '<div class="terminal-dot" style="background:#28CA41"></div>'
    + '<div class="terminal-title">kendr \u2014 shell automation</div></div>'
    + '<div class="terminal-body">';
  for (const step of steps) {
    html += '<div class="terminal-step">';
    if (step.header) {
      html += '<div class="terminal-step-header"><span style="color:#FFB347;font-size:11px">' + esc2(step.header) + '</span></div>';
    }
    for (const ln of step.lines) {
      if (!ln && !step.header) continue;
      const cls = makeLineClass(ln);
      const content = cls === 'cmd' ? esc2(ln.replace(/^\$\s/, '')) : esc2(ln);
      html += '<div class="terminal-line ' + cls + '">' + content + '</div>';
    }
    html += '</div>';
  }
  html += '</div></div>';
  return html;
}

function _looksLikeShellOutput(text) {
  if (!text) return false;
  var stepPat = new RegExp('\\[STEP\\s+\\d+\\]', 'i');
  var cmdPat = new RegExp('^\\$\\s', 'm');
  var stdoutPat = new RegExp('\\bstdout:', 'i');
  var stderrPat = new RegExp('\\bstderr:', 'i');
  var runPat = new RegExp('^Running:\\s+\\S+', 'm');
  return stepPat.test(text)
    || (cmdPat.test(text) && text.split(/\r?\n/).length > 2)
    || stdoutPat.test(text)
    || stderrPat.test(text)
    || runPat.test(text);
}

// ── Project context (kendr.md) ────────────────────────────────────────────
let _projCtx = null;      // last fetched context from /api/projects/active/context
let _projPanelOpen = false;

async function loadProjContext() {
  try {
    const r = await fetch('/api/projects/active/context');
    const d = await r.json();
    _projCtx = d;
    const proj = d.project;
    const nameEl = document.getElementById('projPanelName');
    const badgeEl = document.getElementById('projPanelBadge');
    const stackEl = document.getElementById('projStack');
    const dotEl = document.getElementById('projMdDot');
    const txtEl = document.getElementById('projMdText');
    const genBtn = document.getElementById('btnGenMd');
    if (!proj || !proj.path) {
      nameEl.innerHTML = '<span class="proj-panel-none">No project active</span>';
      badgeEl.style.display = 'none';
      stackEl.textContent = '';
      dotEl.className = 'proj-md-dot amber';
      txtEl.textContent = 'No active project';
      return;
    }
    nameEl.textContent = proj.name || proj.path;
    badgeEl.style.display = 'inline-flex';
    stackEl.textContent = d.stack || '';
    if (d.kendr_md_exists && d.kendr_md) {
      dotEl.className = 'proj-md-dot green';
      const lines = (d.kendr_md || '').split('\n').length;
      txtEl.textContent = 'kendr.md ready (' + lines + ' lines)';
      genBtn.textContent = '\u2728 Regenerate kendr.md';
    } else {
      dotEl.className = 'proj-md-dot amber';
      txtEl.textContent = 'kendr.md not generated yet';
      genBtn.textContent = '\u2728 Generate kendr.md';
    }
  } catch (e) {
    // silent - no project system
  }
}

function toggleProjPanel() {
  _projPanelOpen = !_projPanelOpen;
  const panel = document.getElementById('projPanel');
  const chevron = document.getElementById('projPanelChevron');
  if (_projPanelOpen) {
    panel.classList.add('open');
    chevron.textContent = '\u25B4';
  } else {
    panel.classList.remove('open');
    chevron.textContent = '\u25BE';
  }
}

async function generateKendrMd() {
  const btn = document.getElementById('btnGenMd');
  const orig = btn.textContent;
  btn.textContent = 'Generating...';
  btn.disabled = true;
  try {
    const r = await fetch('/api/projects/active/context/generate', {
      method: 'POST', headers: {'Content-Type': 'application/json'}, body: '{}'
    });
    const d = await r.json();
    if (d.ok) {
      await loadProjContext();
      showProjToast('\u2714 kendr.md generated successfully');
    } else {
      showProjToast((d.error || 'Failed'), true);
    }
  } catch(e) { showProjToast('Error: ' + e.message, true); }
  finally { btn.textContent = orig; btn.disabled = false; }
}

function openKendrMdEditor() {
  const md = (_projCtx && _projCtx.kendr_md) || '';
  document.getElementById('kdmdTextarea').value = md;
  document.getElementById('kdmdModal').style.display = 'flex';
}
function closeKendrMdEditor() {
  document.getElementById('kdmdModal').style.display = 'none';
}
async function saveKendrMd() {
  const content = document.getElementById('kdmdTextarea').value;
  try {
    const r = await fetch('/api/projects/active/context/update', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ content })
    });
    const d = await r.json();
    closeKendrMdEditor();
    if (d.ok) { await loadProjContext(); showProjToast('\u2714 kendr.md saved'); }
    else { showProjToast(d.error || 'Save failed', true); }
  } catch(e) { showProjToast('Error: ' + e.message, true); }
}

let _projToastTimer = null;
function showProjToast(msg, err) {
  let t = document.getElementById('projToast');
  if (!t) {
    t = document.createElement('div');
    t.id = 'projToast';
    t.style.cssText = 'position:fixed;bottom:24px;left:50%;transform:translateX(-50%);padding:8px 20px;border-radius:8px;font-size:12px;font-weight:700;z-index:3000;transition:opacity .3s';
    document.body.appendChild(t);
  }
  t.textContent = msg;
  t.style.background = err ? 'var(--crimson)' : 'var(--teal)';
  t.style.color = err ? '#fff' : '#0d1117';
  t.style.opacity = '1';
  clearTimeout(_projToastTimer);
  _projToastTimer = setTimeout(() => { t.style.opacity = '0'; }, 3000);
}

// ── End project context ──────────────────────────────────────────────────

function _newChatSessionId() {
  return 'chat-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
}
let chatSessionId = sessionStorage.getItem('kendr_chat_session_id') || _newChatSessionId();
sessionStorage.setItem('kendr_chat_session_id', chatSessionId);

function _approvalScopeLabel(scope, pendingKind) {
  const normalizedScope = String(scope || '').trim();
  if (normalizedScope === 'project_blueprint') return 'Blueprint Approval';
  if (normalizedScope === 'root_plan') return 'Plan Approval';
  if (normalizedScope === 'long_document_plan') return 'Research Plan';
  if (normalizedScope === 'deep_research_confirmation') return 'Research Confirmation';
  if (normalizedScope === 'drive_data_sufficiency') return 'Data Sufficiency';
  if (String(pendingKind || '').trim() === 'clarification') return 'Clarification';
  return 'Approval';
}

function _escapeApprovalHtml(value) {
  return String(value || '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function _renderApprovalRequestHtml(request, fallbackPrompt) {
  const req = request && typeof request === 'object' ? request : {};
  const title = String(req.title || '').trim();
  const summary = String(req.summary || '').trim();
  const sections = Array.isArray(req.sections) ? req.sections : [];
  const artifactPaths = Array.isArray(req.artifact_paths) ? req.artifact_paths : [];
  const parts = [];
  if (title) parts.push('<div style="font-size:18px;font-weight:700;color:var(--text);margin-bottom:10px">' + _escapeApprovalHtml(title) + '</div>');
  if (summary) parts.push('<div style="font-size:13px;line-height:1.6;color:var(--text);margin-bottom:14px">' + _escapeApprovalHtml(summary) + '</div>');
  sections.forEach(section => {
    const sectionTitle = _escapeApprovalHtml((section && section.title) || '');
    const items = Array.isArray(section && section.items) ? section.items : [];
    if (!sectionTitle && !items.length) return;
    let html = '<div style="margin:0 0 16px">';
    if (sectionTitle) html += '<div style="font-size:12px;font-weight:700;color:#b8b7ff;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px">' + sectionTitle + '</div>';
    if (items.length) {
      html += '<ul style="margin:0;padding-left:18px;display:grid;gap:6px">';
      items.forEach(item => {
        html += '<li style="font-size:13px;line-height:1.55;color:var(--text)">' + _escapeApprovalHtml(item) + '</li>';
      });
      html += '</ul>';
    }
    html += '</div>';
    parts.push(html);
  });
  if (artifactPaths.length) {
    let html = '<div style="margin:0 0 12px"><div style="font-size:12px;font-weight:700;color:#b8b7ff;text-transform:uppercase;letter-spacing:.08em;margin-bottom:8px">Artifacts</div><ul style="margin:0;padding-left:18px;display:grid;gap:6px">';
    artifactPaths.forEach(path => {
      html += '<li style="font-size:12px;line-height:1.5;color:var(--muted);word-break:break-word">' + _escapeApprovalHtml(path) + '</li>';
    });
    html += '</ul></div>';
    parts.push(html);
  }
  if (!parts.length) {
    return '<div style="font-size:13px;line-height:1.6;color:var(--text);white-space:pre-wrap">' + _escapeApprovalHtml(fallbackPrompt || 'This run is waiting for your response.') + '</div>';
  }
  return parts.join('');
}

function _approvalActionLabel(request, key, fallback) {
  const actions = request && typeof request === 'object' && request.actions && typeof request.actions === 'object'
    ? request.actions
    : {};
  const raw = String(actions[key] || '').trim();
  return raw || fallback;
}

function _openChatApprovalModal(meta) {
  const modal = document.getElementById('chatApprovalModal');
  if (!modal) return;
  _chatAwaitingContext = Object.assign({}, _chatAwaitingContext || {}, meta || {});
  document.getElementById('chatApprovalScope').textContent = _approvalScopeLabel(_chatAwaitingContext.scope, _chatAwaitingContext.pendingKind);
  document.getElementById('chatApprovalPrompt').innerHTML = _renderApprovalRequestHtml(_chatAwaitingContext.approvalRequest, _chatAwaitingContext.prompt);
  document.getElementById('chatApprovalAcceptBtn').textContent = _approvalActionLabel(_chatAwaitingContext.approvalRequest, 'accept_label', 'Accept');
  document.getElementById('chatApprovalRejectBtn').textContent = _approvalActionLabel(_chatAwaitingContext.approvalRequest, 'reject_label', 'Reject');
  document.getElementById('chatApprovalSuggestBtn').textContent = _approvalActionLabel(_chatAwaitingContext.approvalRequest, 'suggest_label', 'Suggestion');
  document.getElementById('chatApprovalSuggestion').value = '';
  document.getElementById('chatApprovalSuggestBox').classList.remove('open');
  document.getElementById('chatApprovalSuggestSubmit').style.display = 'none';
  modal.classList.add('open');
}

function _closeChatApprovalModal() {
  const modal = document.getElementById('chatApprovalModal');
  if (modal) modal.classList.remove('open');
}

function _toggleChatApprovalSuggestion() {
  const box = document.getElementById('chatApprovalSuggestBox');
  const submit = document.getElementById('chatApprovalSuggestSubmit');
  if (!box || !submit) return;
  const opening = !box.classList.contains('open');
  box.classList.toggle('open', opening);
  submit.style.display = opening ? '' : 'none';
  if (opening) {
    const input = document.getElementById('chatApprovalSuggestion');
    if (input) input.focus();
  }
}

function _setChatAwaitingContext(meta) {
  _chatAwaitingContext = Object.assign({
    runId: currentRunId || '',
    workflowId: currentWorkflowId || currentRunId || '',
    attemptId: currentRunId || '',
    workingDir: workingDir || _pendingResumeDir || '',
    prompt: '',
    approvalRequest: null,
    pendingKind: '',
    scope: '',
    task: _chatRunState.task || _chatRunState.title || '',
    title: _chatRunState.title || _chatRunState.task || '',
  }, meta || {});
  isAwaitingInput = true;
  _showAwaitingBanner();
  _openChatApprovalModal(_chatAwaitingContext);
}

function _submitChatApproval(action) {
  if (!_chatAwaitingContext || isRunning) return;
  let reply = '';
  if (action === 'approve') reply = 'approve';
  else if (action === 'reject') reply = 'no, reject this and revise it';
  else {
    reply = (document.getElementById('chatApprovalSuggestion') || {}).value || '';
    reply = String(reply).trim();
    if (!reply) return;
  }
  _pendingResumeDir = _chatAwaitingContext.workingDir || workingDir || null;
  _closeChatApprovalModal();
  sendQuickReply(reply);
}

function _showAwaitingBanner() {
  if (document.getElementById('awaiting-input-banner')) return;
  const msgs = document.getElementById('messages');
  if (!msgs) return;
  const banner = document.createElement('div');
  banner.id = 'awaiting-input-banner';
  banner.style.cssText = 'margin:8px 0 4px 52px;padding:10px 14px;background:rgba(83,82,237,0.1);border:1px solid rgba(83,82,237,0.3);border-radius:8px;font-size:13px;color:var(--text)';
  banner.innerHTML = '<span style="color:#8b8af0;font-weight:600">&#x23F3; Awaiting your input</span> &mdash; review the approval request or type your response below to continue this run.';
  msgs.appendChild(banner);
  scrollDown();
  _setChatComposerState();
}

function _removeAwaitingBanner() {
  const b = document.getElementById('awaiting-input-banner');
  if (b) b.remove();
  _setChatComposerState();
}

async function checkGateway() {
  try {
    const r = await fetch(API + '/api/gateway/status');
    const d = await r.json();
    gatewayOnline = d.online;
    workingDir = d.working_dir || '';
    const dot = document.getElementById('gatewayDot');
    const status = document.getElementById('gatewayStatus');
    if (gatewayOnline) {
      dot.classList.add('online');
      status.textContent = 'Gateway online';
    } else {
      dot.classList.remove('online');
      status.textContent = 'Gateway offline \u2014 run: kendr gateway start';
    }
  } catch(e) {
    document.getElementById('gatewayDot').classList.remove('online');
    document.getElementById('gatewayStatus').textContent = 'UI server error';
  }
  _renderChatInspector();
}

function _relTime(iso) {
  if (!iso) return '';
  const diff = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
  if (diff < 5) return 'just now';
  if (diff < 60) return diff + 's ago';
  if (diff < 3600) return Math.floor(diff/60) + 'm ago';
  if (diff < 86400) return Math.floor(diff/3600) + 'h ago';
  return Math.floor(diff/86400) + 'd ago';
}

async function _hydrateChatInspectorRunData(runId) {
  try {
    const r = await fetch('/api/task-sessions/by-run/' + encodeURIComponent(runId));
    if (!r.ok) return;
    const session = await r.json();
    const summary = _taskSessionSummary(session);
    const events = Array.isArray(summary.execution_trace) ? summary.execution_trace : [];
    if (events.length) {
      _recordChatActivities(events, { run_id: runId, task: summary.active_task || summary.objective || '' });
    }
    if (summary.active_task || summary.objective) {
      _chatRunState.task = summary.active_task || summary.objective || '';
    }
    _renderChatInspector();
  } catch(_) {}
}

async function loadRuns() {
  try {
    const r = await fetch(API + '/api/chat/threads');
    if (!r.ok) return;
    const runs = await r.json();
    const list = document.getElementById('runList');
    list.innerHTML = '';
    if (!runs || !runs.length) {
      list.innerHTML = '<div style="padding:12px 10px;font-size:12px;color:var(--muted)">No runs yet. Start a chat to begin.</div>';
      return;
    }
    const chatRuns = runs || [];
    if (!chatRuns.length) {
      list.innerHTML = '<div style="padding:12px 10px;font-size:12px;color:var(--muted)">No chat history yet.</div>';
      return;
    }
    chatRuns.sort((a, b) => {
      const rankDelta = _runStatusRank(b.status) - _runStatusRank(a.status);
      if (rankDelta) return rankDelta;
      const aTs = new Date(a.updated_at || a.started_at || a.created_at || 0).getTime();
      const bTs = new Date(b.updated_at || b.started_at || b.created_at || 0).getTime();
      return bTs - aTs;
    });
    chatRuns.slice(0, 30).forEach(run => {
      const div = document.createElement('div');
      const status = (run.status || 'completed').toLowerCase();
      const workflowId = run.workflow_id || run.run_id || '';
      const threadId = run.chat_session_id || '';
      const latestRunId = run.latest_run_id || run.run_id || '';
      const isActive = threadId === chatSessionId || workflowId === (currentWorkflowId || currentRunId) || latestRunId === currentRunId;
      const isRunning = status === 'running' || status === 'started';
      const isAwaiting = status === 'awaiting_user_input';
      const isCancelling = status === 'cancelling';
      const isCancelled = status === 'cancelled';
      div.className = 'run-item' + (isActive ? ' active' : '');
      const rawText = run.user_query || run.query || run.text || '';
      const title = rawText.trim().split('\n')[0].substring(0, 70) || 'Untitled run';
      const ts = _relTime(run.started_at || run.updated_at || run.created_at);
      const statusColor = isAwaiting ? '#b8b7ff' : (isRunning || isCancelling || isCancelled) ? 'var(--amber)' : status === 'failed' ? '#ef4444' : status === 'completed' ? 'var(--teal)' : '#6b7280';
      const statusDot = isRunning
        ? '<span class="spinner" style="width:10px;height:10px;display:inline-block;flex-shrink:0"></span>'
        : isCancelling
          ? '<span class="spinner" style="width:10px;height:10px;display:inline-block;flex-shrink:0"></span>'
        : isAwaiting
          ? '<span style="width:8px;height:8px;border-radius:50%;display:inline-block;flex-shrink:0;background:#b8b7ff;box-shadow:0 0 0 3px rgba(83,82,237,0.16)"></span>'
        : '<span style="width:8px;height:8px;border-radius:50%;display:inline-block;flex-shrink:0;background:' + statusColor + '"></span>';
      const statusLabel = isRunning ? 'Running' : isCancelling ? 'Stopping' : isAwaiting ? 'Waiting' : isCancelled ? 'Stopped' : status === 'completed' ? 'Completed' : status === 'failed' ? 'Failed' : status;
      const badgeClass = isRunning ? 'running' : isCancelling ? 'cancelling' : isAwaiting ? 'awaiting' : isCancelled ? 'cancelled' : status === 'failed' ? 'failed' : 'completed';
      const wdLabel = run.working_directory ? '<span style="color:var(--muted);font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:120px" title="' + esc(run.working_directory) + '">&#x1F4C1; ' + esc(run.working_directory.split('/').pop()) + '</span>' : '';
      const runDir = String(run.run_output_dir || run.output_dir || run.resume_output_dir || '').trim();
      const runDirName = runDir ? (runDir.split(/[\\/]/).pop() || runDir) : '';
      const runDirLabel = runDir ? '<span style="color:var(--muted);font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:180px" title="' + esc(runDir) + '">&#x1F5C2;&#xFE0F; ' + esc(runDirName) + '</span>' : '';
      const delBtn = document.createElement('button');
      delBtn.title = 'Delete this run';
      delBtn.innerHTML = '&#x1F5D1;';
      delBtn.style.cssText = 'display:none;background:none;border:none;cursor:pointer;color:var(--muted);font-size:13px;padding:2px 4px;border-radius:4px;flex-shrink:0;line-height:1';
      delBtn.onmouseenter = () => delBtn.style.color = 'var(--crimson)';
      delBtn.onmouseleave = () => delBtn.style.color = 'var(--muted)';
      delBtn.onclick = (e) => { e.stopPropagation(); deleteRun(run.run_id, div); };

      div.innerHTML =
        '<div style="display:flex;align-items:center;gap:6px;margin-bottom:3px">'
        + statusDot
        + '<div class="run-item-title" style="flex:1;font-size:12px;font-weight:' + ((isRunning || isAwaiting) ? '600' : '500') + ';color:' + ((isRunning || isAwaiting) ? statusColor : '#ccc') + '">' + esc(title) + '</div></div>'
        + '<div class="run-item-meta" style="display:flex;justify-content:space-between;align-items:center">'
        + '<span class="run-badge ' + badgeClass + '">' + esc(statusLabel) + '</span>'
        + '<span style="font-size:10px;color:var(--muted)">' + ts + '</span>'
        + '</div>'
        + ((wdLabel || runDirLabel) ? '<div style="margin-top:2px;display:flex;gap:8px;align-items:center;flex-wrap:wrap">' + wdLabel + runDirLabel + '</div>' : '');
      div.appendChild(delBtn);
      div.onmouseenter = () => delBtn.style.display = 'inline';
      div.onmouseleave = () => delBtn.style.display = 'none';
      div.onclick = () => loadRun(latestRunId, threadId);
      list.appendChild(div);
    });
  } catch(e) {}
}

let _pendingResumeDir = null;

function continueRun(runId, workingDir) {
  _pendingResumeDir = workingDir || null;
  isAwaitingInput = true;
  const b = document.getElementById('awaiting-input-banner');
  if (b) b.remove();
  _showAwaitingBanner();
  _openChatApprovalModal({
    runId: runId || currentRunId || '',
    workingDir: workingDir || _pendingResumeDir || workingDir || '',
    prompt: (_chatAwaitingContext && _chatAwaitingContext.prompt) || 'This run is waiting for your approval or feedback.',
    pendingKind: (_chatAwaitingContext && _chatAwaitingContext.pendingKind) || '',
    scope: (_chatAwaitingContext && _chatAwaitingContext.scope) || '',
  });
  document.getElementById('userInput').focus();
}

function _syncChatSessionId(sessionId) {
  const value = String(sessionId || '').trim();
  if (!value) return;
  chatSessionId = value;
  sessionStorage.setItem('kendr_chat_session_id', chatSessionId);
}

function _chatSessionIdFromRun(run) {
  const sessionId = String((run && run.session_id) || '').trim();
  if (!sessionId) return '';
  const parts = sessionId.split(':');
  if (parts.length >= 4 && parts[0] === 'webchat' && parts[parts.length - 1] === 'main') {
    return String(parts[parts.length - 2] || '').trim();
  }
  return sessionId;
}

function _chatResumePathFromRun(run) {
  if (!run) return '';
  return String(
    run.run_output_dir
    || run.resume_output_dir
    || (((run.task_session || {}).summary || {}).resume_output_dir)
    || (((run.task_session || {}).summary || {}).run_output_dir)
    || run.working_directory
    || ''
  ).trim();
}

function _isRunActiveStatus(status) {
  const normalized = String(status || '').toLowerCase();
  return normalized === 'running' || normalized === 'started' || normalized === 'cancelling';
}

function _isRetryCommand(text) {
  const normalized = String(text || '').trim().toLowerCase();
  return normalized === 'retry' || normalized === 'resume' || normalized === 'continue';
}

function _isControlReplyText(text) {
  const value = String(text || '').trim().toLowerCase();
  if (!value) return true;
  return ['approve','approved','reject','rejected','continue','yes','ok','okay','quick summary'].includes(value);
}

async function _loadThreadRuns(chatSessionId) {
  const id = String(chatSessionId || '').trim();
  if (!id) return [];
  try {
    const rr = await fetch(API + '/api/runs?raw=1');
    if (!rr.ok) return [];
    const allRuns = await rr.json();
    const rows = (Array.isArray(allRuns) ? allRuns : []).filter(run => _chatSessionIdFromRun(run) === id);
    rows.sort((a, b) => {
      const aTs = new Date(a.started_at || a.created_at || a.updated_at || 0).getTime();
      const bTs = new Date(b.started_at || b.created_at || b.updated_at || 0).getTime();
      return aTs - bTs;
    });
    return rows;
  } catch(_) {
    return [];
  }
}

function _threadRepresentativeQuery(runs) {
  const rows = Array.isArray(runs) ? runs : [];
  const queries = rows.map(r => String(r.user_query || r.query || r.text || '').trim()).filter(Boolean);
  for (const q of queries) {
    if (!_isControlReplyText(q)) return q;
  }
  return queries.length ? queries[0] : '';
}

async function loadRun(runId, sessionIdOverride) {
  if (activeEvtSource) { activeEvtSource.close(); activeEvtSource = null; }
  stopPlanPolling();
  stopActivityPolling();
  isRunning = false;
  isAwaitingInput = false;
  isStopping = false;
  _pendingResumeDir = null;
  _chatAwaitingContext = null;
  _closeChatApprovalModal();
  _removeAwaitingBanner();
  currentRunId = runId;
  currentWorkflowId = null;
  _setChatComposerState();
  const myToken = ++_loadRunToken;
  loadRuns();

  const msgs = document.getElementById('messages');
  msgs.innerHTML = '<div style="display:flex;align-items:center;gap:8px;color:var(--muted);font-size:13px;padding:20px"><span class="spinner"></span> Loading run...</div>';

  try {
    const r = await fetch(API + '/api/runs/' + runId);
    const d = await r.json();
    if (_loadRunToken !== myToken) return;
    const threadRuns = sessionIdOverride ? await _loadThreadRuns(sessionIdOverride) : [];
    const representativeQuery = _threadRepresentativeQuery(threadRuns);
    const query = representativeQuery || d.user_query || d.query || d.text || '';
    const output = d.final_output || d.output || d.draft_response || '';
    const status = (d.status || 'completed').toLowerCase();
    _syncChatSessionId(sessionIdOverride || _chatSessionIdFromRun(d));
    currentWorkflowId = d.workflow_id || runId;
    const lastAgent = d.last_agent || '';
    const createdAt = d.created_at ? new Date(d.created_at).toLocaleString() : '';
    const completedAt = d.completed_at ? new Date(d.completed_at).toLocaleString() : '';
    _chatRunState = {
      runId,
      workflowId: d.workflow_id || runId,
      attemptId: d.attempt_id || runId,
      status,
      title: query ? (query.substring(0, 80) + (query.length > 80 ? '…' : '')) : 'Loaded run',
      task: query || '',
      startedAt: d.created_at || d.started_at || '',
      completedAt: d.completed_at || '',
      lastCommand: '',
      lastCommandMeta: '',
    };
    _chatPlanState = { total: 0, completed: 0, running: 0, failed: 0 };
    _chatActivityFeed = [];
    _renderChatActivityList();
    _renderChatInspector();

    clearMessages();
    if (threadRuns.length > 1) {
      threadRuns.forEach(item => {
        const turnQuery = String(item.user_query || item.query || item.text || '').trim();
        const turnOutput = String(item.final_output || item.output || item.draft_response || '').trim();
        const turnRunId = String(item.run_id || '').trim();
        if (turnQuery) appendUserMsg(turnQuery);
        if (turnOutput) appendKendrMsg(turnOutput, turnRunId || runId);
      });
      if (query) {
        document.getElementById('chatTitle').textContent = query.substring(0, 50) + (query.length > 50 ? '...' : '');
      }
    } else if (query) {
      appendUserMsg(query);
      document.getElementById('chatTitle').textContent = query.substring(0, 50) + (query.length > 50 ? '...' : '');
    }

    if (threadRuns.length <= 1 && output) {
      appendKendrMsg(output, runId);
    } else if (threadRuns.length <= 1 && !query) {
      msgs.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:20px;text-align:center">No content found for this run.</div>';
      document.getElementById('clearChatBtn').style.display = 'none';
      return;
    }

    const statusColors = {completed:'var(--teal)',failed:'var(--crimson)',running:'var(--amber)',awaiting_user_input:'var(--blue)',cancelled:'var(--amber)',cancelling:'var(--amber)'};
    const statusColor = statusColors[status] || 'var(--muted)';
    const metaRow = document.createElement('div');
    metaRow.style.cssText = 'padding: 0 0 8px; display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-left:52px;';
    const statusPill = `<span style="padding:3px 10px;border-radius:999px;font-size:11px;font-weight:600;background:rgba(0,0,0,0.2);color:${statusColor};border:1px solid ${statusColor}">${status}</span>`;
    const agentPill = lastAgent ? `<span style="font-size:11px;color:var(--muted)">via ${esc(lastAgent)}</span>` : '';
    const timePill = createdAt ? `<span style="font-size:11px;color:var(--muted)">&#x1F551; ${esc(createdAt)}</span>` : '';
    const idPill = `<span style="font-size:11px;font-family:monospace;color:var(--muted);opacity:0.6">${esc(runId)}</span>`;
    metaRow.innerHTML = statusPill + agentPill + timePill + idPill;
    msgs.appendChild(metaRow);

    const runOutputDir = String(d.run_output_dir || d.output_dir || d.resume_output_dir || '').trim();
    const logPaths = (d.log_paths && typeof d.log_paths === 'object') ? d.log_paths : {};
    const logEntries = Object.entries(logPaths).filter(([key, value]) => key !== 'run_output_dir' && String(value || '').trim());
    if (runOutputDir || logEntries.length) {
      const logCard = document.createElement('div');
      logCard.style.cssText = 'margin:4px 0 10px 52px;padding:10px 12px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;';
      let html = '<div style="font-size:10px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px">&#x1F4DD; Run Storage</div>';
      if (runOutputDir) {
        html += '<div style="font-size:11px;color:var(--text);word-break:break-all"><strong style="color:var(--muted);font-weight:600">Output folder:</strong> ' + esc(runOutputDir) + '</div>';
      }
      if (logEntries.length) {
        html += '<div style="margin-top:6px;display:flex;flex-direction:column;gap:3px">';
        logEntries.forEach(([key, value]) => {
          const label = String(key || '').replace(/_/g, ' ');
          html += '<div style="font-size:11px;color:var(--muted);word-break:break-all"><strong style="font-weight:600;color:var(--text)">' + esc(label) + ':</strong> ' + esc(String(value || '')) + '</div>';
        });
        html += '</div>';
      }
      logCard.innerHTML = html;
      msgs.appendChild(logCard);
    }

    if (_isRunActiveStatus(status)) {
      currentRunId = runId;
      currentWorkflowId = d.workflow_id || runId;
      _syncChatSessionId(sessionIdOverride || _chatSessionIdFromRun(d));
      _chatRunState = {
        runId,
        workflowId: d.workflow_id || runId,
        attemptId: d.attempt_id || runId,
        status,
        title: query ? (query.substring(0, 80) + (query.length > 80 ? '…' : '')) : 'Active run',
        task: query || _chatRunState.task || '',
        startedAt: d.created_at || d.started_at || new Date().toISOString(),
        completedAt: '',
        lastCommand: _chatRunState.lastCommand || '',
        lastCommandMeta: _chatRunState.lastCommandMeta || '',
      };
      createStreamingRow(runId, query || 'Running…');
      updateStreamStatus(runId, status === 'cancelling' ? 'Stopping run…' : 'Reconnecting to active run…');
      isRunning = true;
      isStopping = status === 'cancelling';
      _setChatComposerState();
      openEventStream(runId);
    } else if (status === 'awaiting_user_input') {
      const runWorkDir = _chatResumePathFromRun(d);
      _setChatAwaitingContext({
        runId,
        workflowId: d.workflow_id || runId,
        attemptId: d.attempt_id || runId,
        workingDir: runWorkDir,
        prompt: d.pending_user_question || output || 'This run is waiting for your approval or feedback.',
        approvalRequest: d.approval_request || ((d.task_session || {}).approval_request) || null,
        pendingKind: ((d.task_session || {}).pending_user_input_kind || ''),
        scope: ((d.task_session || {}).approval_pending_scope || ''),
      });
    }

    scrollDown();
    await _hydrateChatInspectorRunData(runId);
  } catch(e) {
    msgs.innerHTML = '<div style="color:var(--crimson);font-size:13px;padding:20px">Failed to load run: ' + esc(String(e)) + '</div>';
    _chatRunState.status = 'failed';
    _chatRunState.task = 'Failed to load run';
    _recordChatActivity({ title: 'Run load failed', status: 'failed', detail: String(e), completed_at: new Date().toISOString(), task: 'Load run history' });
  }
}

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function newChat() {
  _loadRunToken++;
  currentRunId = null;
  currentWorkflowId = null;
  isAwaitingInput = false;
  deepResearchUploadedRoots = [];
  deepResearchLocalPaths = [];
  chatSessionId = _newChatSessionId();
  sessionStorage.setItem('kendr_chat_session_id', chatSessionId);
  if (activeEvtSource) { activeEvtSource.close(); activeEvtSource = null; }
  stopPlanPolling();
  stopActivityPolling();
  isRunning = false;
  isStopping = false;
  _removeAwaitingBanner();
  _closeChatApprovalModal();
  _chatAwaitingContext = null;
  _resetChatInspectorState();
  clearMessages();
  document.getElementById('chatTitle').textContent = 'New Chat';
  document.getElementById('clearChatBtn').style.display = 'none';
  renderDeepResearchSourceSummary();
  document.getElementById('userInput').focus();
  _setChatComposerState();
}

async function deleteChat() {
  const msgs = document.getElementById('messages');
  const welcome = document.getElementById('welcome');
  const alreadyClear = welcome && msgs.contains(welcome) && msgs.children.length === 1;
  if (alreadyClear) return;
  if (!confirm('Delete this chat? This will permanently remove all messages, runs, and output files.')) return;
  const sessionToDelete = chatSessionId;
  _loadRunToken++;
  isAwaitingInput = false;
  if (activeEvtSource) { activeEvtSource.close(); activeEvtSource = null; }
  stopPlanPolling();
  stopActivityPolling();
  isRunning = false;
  isStopping = false;
  currentRunId = null;
  currentWorkflowId = null;
  _removeAwaitingBanner();
  _closeChatApprovalModal();
  _chatAwaitingContext = null;
  _resetChatInspectorState();
  clearMessages();
  document.getElementById('chatTitle').textContent = 'New Chat';
  document.getElementById('clearChatBtn').style.display = 'none';
  deepResearchUploadedRoots = [];
  deepResearchLocalPaths = [];
  chatSessionId = _newChatSessionId();
  sessionStorage.setItem('kendr_chat_session_id', chatSessionId);
  renderDeepResearchSourceSummary();
  document.getElementById('userInput').focus();
  _setChatComposerState();
  try {
    await fetch(API + '/api/chat/delete', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ chat_session_id: sessionToDelete })
    });
  } catch(e) { }
  loadRuns();
}

function clearChat() { deleteChat(); }

async function deleteRun(runId, itemEl) {
  if (!confirm('Delete this run? This will permanently remove all messages and output files for this run.')) return;
  if (itemEl) {
    itemEl.style.opacity = '0.4';
    itemEl.style.pointerEvents = 'none';
  }
  try {
    const r = await fetch(API + '/api/runs/delete', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({ run_id: runId })
    });
    const d = await r.json();
    if (d.ok) {
      if (currentRunId === runId) {
        currentRunId = null;
        currentWorkflowId = null;
        _chatAwaitingContext = null;
        _closeChatApprovalModal();
        _resetChatInspectorState();
        clearMessages();
        document.getElementById('chatTitle').textContent = 'New Chat';
        document.getElementById('clearChatBtn').style.display = 'none';
      }
      if (itemEl) itemEl.remove();
      loadRuns();
    } else {
      if (itemEl) { itemEl.style.opacity = '1'; itemEl.style.pointerEvents = ''; }
      alert('Failed to delete run: ' + (d.error || 'unknown error'));
    }
  } catch(e) {
    if (itemEl) { itemEl.style.opacity = '1'; itemEl.style.pointerEvents = ''; }
    alert('Failed to delete run: ' + e);
  }
}

function clearMessages() {
  const msgs = document.getElementById('messages');
  msgs.innerHTML = '<div class="welcome" id="welcome"><div class="welcome-logo">&#x26A1;</div><h2>What would you like help with today?</h2><p>Kendr helps with everyday work: reading files, summarizing documents, organizing tasks, drafting messages, checking schedules, and finding up-to-date information.</p><div class="suggestions"><div class="suggest-chip" onclick="fillInput(\'Summarize this PDF and extract action items\')">&#x1F4C4; PDF action items</div><div class="suggest-chip" onclick="fillInput(\'Find the latest version of our leave policy online\')">&#x1F310; Policy web search</div><div class="suggest-chip" onclick="fillInput(\'Read this spreadsheet and tell me the totals\')">&#x1F4CA; Spreadsheet totals</div><div class="suggest-chip" onclick="fillInput(\'Draft an email reply to this customer update\')">&#x1F4EC; Draft reply</div><div class="suggest-chip" onclick="fillInput(\'Organize my tasks for today\')">&#x2705; Plan my day</div><div class="suggest-chip" onclick="fillInput(\'Plan a simple weekend trip itinerary\')">&#x1F9F3; Travel helper</div></div></div>';
  _renderChatInspector();
}

function fillInput(text) {
  const input = document.getElementById('userInput');
  input.value = text;
  autoResize(input);
  input.focus();
  const w = document.getElementById('welcome');
  if (w) w.style.display = 'none';
}

function _chatInputMaxHeight() {
  const viewportCap = Math.floor(window.innerHeight * 0.32);
  return Math.max(160, Math.min(viewportCap, 300));
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, _chatInputMaxHeight()) + 'px';
}

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleSendButton(); }
}

function scrollDown() {
  const msgs = document.getElementById('messages');
  msgs.scrollTop = msgs.scrollHeight;
}

function appendUserMsg(text) {
  const w = document.getElementById('welcome');
  if (w) w.remove();
  const msgs = document.getElementById('messages');
  const row = document.createElement('div');
  row.className = 'message-row user';
  row.innerHTML = '<div class="avatar user">&#x1F9D1;</div><div class="bubble"><div style="white-space:pre-wrap">' + esc(text) + '</div></div>';
  msgs.appendChild(row);
  scrollDown();
  const clearBtn = document.getElementById('clearChatBtn');
  if (clearBtn) clearBtn.style.display = 'flex';
}

function appendKendrMsg(output, runId) {
  const msgs = document.getElementById('messages');
  const row = document.createElement('div');
  row.className = 'message-row kendr';
  row.innerHTML = '<div class="avatar kendr">&#x26A1;</div><div class="bubble"><div>' + formatOutput(output) + '</div>' +
    (runId ? '<div class="bubble-meta">Run: ' + esc(runId) + '</div>' : '') + '</div>';
  msgs.appendChild(row);
  scrollDown();
}

function _renderPlanCard(plan) {
  const steps = plan.steps || plan.plan_steps || (plan.plan_data && plan.plan_data.execution_steps) || [];
  const summary = plan.summary || (plan.plan_data && plan.plan_data.summary) || '';
  const scope = plan.scope || 'execution plan';
  const msg = plan.message || 'Reply <code>approve</code> to continue, or describe changes to regenerate.';
  const STATUS_ICON = { pending:'\u23F3', running:'\u25B6\uFE0F', done:'\u2705', failed:'\u274C', skipped:'\u23ED\uFE0F' };
  let html = '<div style="border:1px solid var(--teal);border-radius:10px;overflow:hidden;margin-top:8px">';
  html += '<div style="background:rgba(0,201,167,0.12);padding:10px 14px;display:flex;align-items:center;gap:8px">';
  html += '<span style="font-size:16px">\uD83D\uDDFA\uFE0F</span>';
  html += '<div><div style="font-weight:700;font-size:13px;color:var(--teal)">' + esc(scope) + '</div>';
  if (summary) html += '<div style="font-size:12px;color:var(--muted);margin-top:2px">' + esc(summary) + '</div>';
  html += '</div></div>';
  if (steps.length) {
    html += '<div style="padding:10px 14px;display:flex;flex-direction:column;gap:6px">';
    for (const s of steps) {
      const icon = STATUS_ICON[s.status || 'pending'] || '\u23F3';
      const sid = esc(s.id || '');
      const title = esc(s.title || s.id || 'Step');
      const agent = esc(s.agent || '');
      const task = esc(s.task || '');
      html += '<div style="background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px">';
      html += '<div style="display:flex;align-items:center;gap:6px">';
      html += '<span>' + icon + '</span>';
      html += '<span style="font-weight:600;font-size:12px">' + (sid ? sid + ': ' : '') + title + '</span>';
      if (agent) html += '<span style="margin-left:auto;font-size:10px;color:var(--muted);background:var(--surface3);padding:1px 6px;border-radius:4px">' + agent + '</span>';
      html += '</div>';
      if (task) html += '<div style="font-size:11px;color:var(--muted);margin-top:4px;padding-left:20px">' + task + '</div>';
      html += '</div>';
    }
    html += '</div>';
  }
  html += '<div style="padding:10px 14px;border-top:1px solid var(--border);font-size:12px;color:var(--muted)">' + msg + '</div>';
  html += '</div>';
  return html;
}

function formatOutput(text) {
  if (!text) return '';
  const trimmed = text.trim();
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) {
    try {
      const parsed = JSON.parse(trimmed);
      if (parsed && parsed.type === 'plan_approval') return _renderPlanCard(parsed);
      if (parsed && parsed.type === 'clarification') {
        const qs = (parsed.questions || []).map(q => '<li>' + esc(q) + '</li>').join('');
        return '<div style="padding:10px;border:1px solid var(--amber);border-radius:8px"><b>\uD83D\uDCCB Clarification needed:</b><ul style="margin:8px 0 0 16px;padding:0">' + qs + '</ul></div>';
      }
    } catch(_) {}
  }
  if (_looksLikeShellOutput(text)) return _renderTerminalBlock(text);
  let h = esc(text);
  h = h.replace(/```([\s\S]*?)```/g, '<pre style="background:rgba(0,0,0,0.3);padding:10px;border-radius:6px;overflow-x:auto;font-family:monospace;font-size:12px;margin:6px 0">$1</pre>');
  h = h.replace(/`([^`\n]+)`/g, '<code style="background:rgba(0,0,0,0.3);padding:2px 6px;border-radius:4px;font-family:monospace;font-size:12px">$1</code>');
  h = h.replace(/^### (.+)$/gm, '<div style="font-size:14px;font-weight:700;color:var(--text);margin:10px 0 4px">$1</div>');
  h = h.replace(/^## (.+)$/gm, '<div style="font-size:15px;font-weight:700;color:var(--text);margin:12px 0 5px">$1</div>');
  h = h.replace(/^# (.+)$/gm, '<div style="font-size:17px;font-weight:800;color:var(--text);margin:14px 0 6px">$1</div>');
  h = h.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  h = h.replace(/\*([^*\n]+)\*/g, '<em>$1</em>');
  h = h.replace(/^→ /gm, '<span style="color:var(--muted)">→ </span>');
  h = h.replace(/\n/g, '<br>');
  return h;
}

function createStreamingRow(runId, taskText = '') {
  const w = document.getElementById('welcome');
  if (w) w.remove();
  _runStepJournal[runId] = {};
  _runLiveUpdates[runId] = [];
  _runTraceFeed[runId] = [];
  const msgs = document.getElementById('messages');
  const row = document.createElement('div');
  row.className = 'message-row kendr';
  row.id = 'stream-row-' + runId;
  row.innerHTML = '<div class="avatar kendr">&#x26A1;</div><div class="bubble" id="stream-bubble-' + runId + '">'
    + '<div class="run-hero" id="run-hero-' + runId + '">'
    + '<div class="run-hero-eyebrow">Task</div>'
    + '<div class="run-hero-title" id="run-hero-title-' + runId + '">' + esc(taskText || 'Preparing task…') + '</div>'
    + '<div class="run-hero-meta" id="run-hero-meta-' + runId + '"><span>' + esc(runId) + '</span><span>' + esc(_formatStepTimestamp(new Date().toISOString()) || 'starting') + '</span></div>'
    + '</div>'
    + '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">'
    + '<span class="spinner" style="width:14px;height:14px;flex-shrink:0"></span>'
    + '<div class="streaming-status" id="stream-status-' + runId + '" style="font-size:12px;color:var(--teal);font-weight:600">Starting agents\u2026</div>'
    + '</div>'
    + '<div id="run-worklog-' + runId + '" style="margin:8px 0 10px;padding:8px 0;border-top:1px solid rgba(255,255,255,0.08)">'
    + '<div id="run-working-' + runId + '" style="font-size:12px;color:var(--muted);margin-bottom:8px">Working for 0s</div>'
    + '<div id="run-work-items-' + runId + '" style="display:flex;flex-direction:column"></div>'
    + '</div>'
    + '<div id="stream-trace-' + runId + '" style="margin:10px 0 12px;padding:12px 14px;background:rgba(255,179,71,0.05);border:1px solid rgba(255,179,71,0.2);border-radius:10px"></div>'
    + '<div class="steps-wrapper" id="stream-steps-' + runId + '" style="display:flex;flex-direction:column;gap:6px"></div>'
    + '<div id="stream-result-' + runId + '"></div></div>';
  msgs.appendChild(row);
  _startRunWorkingTimer(runId);
  _pushRunLiveUpdate(runId, 'Run started', taskText || 'Preparing execution context.');
  _upsertRunTracePanel(runId);
  scrollDown();
  return row;
}

function updateStreamStatus(runId, msg) {
  const el = document.getElementById('stream-status-' + runId);
  if (el) el.textContent = msg;
  const meta = document.getElementById('run-hero-meta-' + runId);
  if (meta) {
    const parts = ['Run ' + runId];
    if (msg) parts.push(msg);
    if (_chatRunState.startedAt && !_chatRunState.completedAt && _chatRunState.status === 'running') {
      const elapsed = _formatStepDuration({ started_at: _chatRunState.startedAt });
      if (elapsed) parts.push('elapsed ' + elapsed);
    }
    meta.innerHTML = parts.map(part => '<span>' + esc(part) + '</span>').join('');
  }
}

function _agentDisplayName(agentName) {
  return agentName.replace(/_agent$/, '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function _formatStepTimestamp(value) {
  if (!value) return '';
  const dt = new Date(value);
  if (Number.isNaN(dt.getTime())) return '';
  return dt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function _formatStepDuration(step) {
  if (!step || typeof step !== 'object') return '';
  const direct = Number(step.duration_ms || 0);
  let ms = Number.isFinite(direct) && direct > 0 ? direct : 0;
  if (!ms && step.started_at) {
    const started = new Date(step.started_at);
    const ended = step.completed_at ? new Date(step.completed_at) : new Date();
    if (!Number.isNaN(started.getTime()) && !Number.isNaN(ended.getTime())) {
      ms = Math.max(0, ended.getTime() - started.getTime());
    }
  }
  if (!ms) return '';
  if (ms < 1000) return ms + ' ms';
  const seconds = ms / 1000;
  if (seconds < 10) return seconds.toFixed(1) + 's';
  if (seconds < 60) return Math.round(seconds) + 's';
  const minutes = Math.floor(seconds / 60);
  const remainder = Math.round(seconds % 60);
  if (minutes < 60) return minutes + 'm ' + remainder + 's';
  const hours = Math.floor(minutes / 60);
  return hours + 'h ' + (minutes % 60) + 'm';
}

function _formatElapsedMs(ms) {
  const safe = Math.max(0, Number(ms) || 0);
  const totalSec = Math.floor(safe / 1000);
  const mins = Math.floor(totalSec / 60);
  const secs = totalSec % 60;
  if (!mins) return secs + 's';
  if (mins < 60) return mins + 'm ' + secs + 's';
  const hrs = Math.floor(mins / 60);
  return hrs + 'h ' + (mins % 60) + 'm';
}

function _renderRunLiveUpdates(runId) {
  const container = document.getElementById('run-work-items-' + runId);
  if (!container) return;
  const entries = (_runLiveUpdates[runId] || []).slice(0, 6);
  if (!entries.length) {
    container.innerHTML = '<div style="font-size:12px;color:var(--muted)">Preparing execution…</div>';
    return;
  }
  container.innerHTML = entries.map(item => {
    const detail = item.detail
      ? '<div style="margin-top:2px;font-size:12px;color:var(--muted);line-height:1.45">' + esc(item.detail) + '</div>'
      : '';
    return '<div style="padding:6px 0;border-bottom:1px solid rgba(255,255,255,0.05)">'
      + '<div style="font-size:13px;color:var(--text);line-height:1.45">' + esc(item.text) + '</div>'
      + detail
      + '</div>';
  }).join('');
}

function _pushRunLiveUpdate(runId, text, detail = '') {
  if (!runId) return;
  const summary = String(text || '').trim();
  const extra = String(detail || '').trim();
  if (!summary) return;
  if (!_runLiveUpdates[runId]) _runLiveUpdates[runId] = [];
  const feed = _runLiveUpdates[runId];
  const previous = feed[0];
  if (previous && previous.text === summary && previous.detail === extra) return;
  feed.unshift({ text: summary, detail: extra, ts: Date.now() });
  if (feed.length > 14) feed.length = 14;
  _renderRunLiveUpdates(runId);
}

function _startRunWorkingTimer(runId) {
  _stopRunWorkingTimer(runId);
  const startedAt = Date.now();
  const tick = () => {
    const el = document.getElementById('run-working-' + runId);
    if (!el) return;
    el.textContent = 'Working for ' + _formatElapsedMs(Date.now() - startedAt);
  };
  tick();
  _runWorkingTimers[runId] = setInterval(tick, 1000);
}

function _stopRunWorkingTimer(runId, completed = false) {
  const timer = _runWorkingTimers[runId];
  if (timer) {
    clearInterval(timer);
    delete _runWorkingTimers[runId];
  }
  const el = document.getElementById('run-working-' + runId);
  if (el && completed) {
    const current = String(el.textContent || '').replace(/^Working/, 'Worked');
    el.textContent = current || 'Completed';
  }
}

function _stepJournalKey(step) {
  if (!step || typeof step !== 'object') return 'unknown-step';
  const raw = step.execution_id
    || [step.agent || step.name || 'agent', step.started_at || step.timestamp || '', step.reason || ''].join(':');
  return String(raw || 'unknown-step').replace(/[^a-zA-Z0-9:_-]/g, '_').slice(0, 140);
}

function _recordRunStep(runId, step) {
  if (!runId || !step || typeof step !== 'object') return;
  if (!_runStepJournal[runId]) _runStepJournal[runId] = {};
  const key = _stepJournalKey(step);
  const existing = _runStepJournal[runId][key] || {};
  _runStepJournal[runId][key] = {
    key,
    agent: step.agent || step.name || existing.agent || 'agent',
    status: step.status || existing.status || 'running',
    reason: step.reason || existing.reason || '',
    message: step.message || existing.message || '',
    started_at: step.started_at || existing.started_at || '',
    completed_at: step.completed_at || existing.completed_at || '',
    duration_label: step.duration_label || existing.duration_label || '',
    duration_ms: step.duration_ms || existing.duration_ms || 0,
  };
}

function _runStepSummary(runId) {
  const entries = Object.values(_runStepJournal[runId] || {});
  if (!entries.length) return { total: 0, completed: 0, running: 0, failed: 0, entries: [] };
  const completed = entries.filter(s => ['done', 'completed', 'success'].includes(String(s.status || '').toLowerCase())).length;
  const failed = entries.filter(s => ['failed', 'error'].includes(String(s.status || '').toLowerCase())).length;
  const running = entries.filter(s => ['running', 'started'].includes(String(s.status || '').toLowerCase())).length;
  const ordered = entries.slice().sort((a, b) => {
    const ta = Date.parse(a.started_at || '') || 0;
    const tb = Date.parse(b.started_at || '') || 0;
    return ta - tb;
  });
  return { total: entries.length, completed, running, failed, entries: ordered };
}

function _renderRunExecutionSummary(runId) {
  const summary = _runStepSummary(runId);
  if (!summary.total) return '';
  const headline = `${summary.completed}/${summary.total} tasks completed`
    + (summary.running ? ` · ${summary.running} running` : '')
    + (summary.failed ? ` · ${summary.failed} failed` : '');
  const top = summary.entries.slice(-8).map(step => {
    const agent = _agentDisplayName(step.agent || 'agent');
    const reason = String(step.reason || step.message || '').trim();
    const reasonShort = reason ? (reason.length > 160 ? reason.slice(0, 160) + '…' : reason) : 'Progress update received.';
    const status = String(step.status || 'running').toLowerCase();
    const icon = ['done', 'completed', 'success'].includes(status) ? '&#x2713;' : (['failed', 'error'].includes(status) ? '&#x2717;' : '&#x2022;');
    const tone = ['done', 'completed', 'success'].includes(status) ? 'var(--teal)' : (['failed', 'error'].includes(status) ? 'var(--crimson)' : 'var(--amber)');
    return '<div style="display:flex;align-items:flex-start;gap:8px;padding:4px 0;font-size:12px">'
      + '<span style="color:' + tone + ';font-weight:700;line-height:1.2">' + icon + '</span>'
      + '<div><span style="font-weight:600;color:var(--text)">' + esc(agent) + ':</span> <span style="color:var(--muted)">' + esc(reasonShort) + '</span></div>'
      + '</div>';
  }).join('');
  return '<div style="margin-top:10px;padding:10px;background:var(--surface2);border:1px solid var(--border);border-radius:8px">'
    + '<div style="font-size:11px;font-weight:700;color:var(--teal);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px">&#x1F4CB; Execution Summary</div>'
    + '<div style="font-size:11px;color:var(--muted);margin-bottom:6px">' + esc(headline) + '</div>'
    + top
    + '</div>';
}

function addStreamStep(runId, step) {
  const container = document.getElementById('stream-steps-' + runId);
  if (!container) return;
  _recordRunStep(runId, step);
  const runState = _runStepSummary(runId);
  const agentLabel = _agentDisplayName(step.agent || step.name || 'agent');
  const reasonText = String(step.reason || step.message || '').trim();
  const statusNorm = String(step.status || 'running').toLowerCase();
  if (['completed', 'done', 'success'].includes(statusNorm)) {
    _pushRunLiveUpdate(runId, agentLabel + ' completed a task', reasonText || 'Step finished successfully.');
  } else if (['failed', 'error'].includes(statusNorm)) {
    _pushRunLiveUpdate(runId, agentLabel + ' reported a failure', reasonText || 'Step failed. Review details below.');
  } else {
    const progressText = runState.total ? (runState.completed + '/' + runState.total + ' tasks completed') : 'Task in progress';
    _pushRunLiveUpdate(runId, agentLabel + ' is working', reasonText || progressText);
  }
  const rawStatus = step.status || 'running';
  const agentName = step.agent || step.name || 'agent';
  const isMcp = agentName.startsWith('mcp_') && agentName.endsWith('_agent');
  const isRunning = rawStatus === 'running' || rawStatus === 'started';
  const isDone = rawStatus === 'done' || rawStatus === 'completed' || rawStatus === 'success';
  const isFailed = rawStatus === 'failed' || rawStatus === 'error';
  const cssClass = isRunning ? 'running' : isDone ? 'done' : isFailed ? 'failed' : rawStatus;
  const idSeed = step.execution_id
    || [agentName, step.started_at || step.timestamp || '', step.reason || '', step.message || ''].join(':');
  const safeSeed = String(idSeed || agentName).replace(/[^a-zA-Z0-9_-]/g, '_').slice(0, 120);
  const existingId = 'step-' + runId + '-' + safeSeed;
  const existing = document.getElementById(existingId);
  let div = existing || document.createElement('div');
  if (!existing) {
    div.id = existingId;
    container.appendChild(div);
  }
  div.className = 'step-card ' + cssClass + (isMcp ? ' mcp-step' : '');

  let displayName = isMcp
    ? agentName.replace(/^mcp_/, '').replace(/_agent$/, '').split('_').join(' \u2192 ')
    : _agentDisplayName(agentName);

  const dotIcon = isRunning
    ? '<span class="spinner" style="width:9px;height:9px;display:inline-block;vertical-align:middle"></span>'
    : isDone ? '\u2713' : '\u2717';
  const nameColor = isRunning ? 'var(--teal)' : isDone ? '#ccc' : 'var(--crimson)';

  const mcpPill = isMcp
    ? '<span style="display:inline-block;padding:1px 6px;border-radius:4px;font-size:9px;font-weight:700;background:rgba(167,139,250,0.15);color:#a78bfa;margin-left:6px">\uD83E\uDDE9 MCP</span>'
    : '';

  const reason = step.reason || '';
  const message = step.message || '';
  const startedAt = _formatStepTimestamp(step.started_at);
  const completedAt = _formatStepTimestamp(step.completed_at);
  const durationLabel = step.duration_label || _formatStepDuration(step);
  const failureReason = step.failure_reason || (isFailed ? (message || reason || '') : '');

  let reasonHtml = '';
  if (reason) {
    const reasonShort = reason.slice(0, 160) + (reason.length > 160 ? '…' : '');
    const reasonFull = reason.length > 160
      ? '<details class="step-reason"><summary>Why</summary><p>' + esc(reason) + '</p></details>'
      : '<div class="step-reason" style="margin-top:5px"><span style="color:var(--teal);font-size:10px;font-weight:700;text-transform:uppercase;letter-spacing:.05em">Why </span>' + esc(reasonShort) + '</div>';
    reasonHtml = reasonFull;
  }

  let outputHtml = '';
  if (message && message !== reason) {
    if (isRunning) {
      outputHtml = '<div style="margin-top:5px;font-size:11px;color:var(--muted)">' + esc(message.slice(0, 180)) + (message.length > 180 ? '…' : '') + '</div>';
    } else if (message.length > 320) {
      const preview = esc(message.slice(0, 320));
      outputHtml = '<details class="step-output"><summary>Output (' + message.length.toLocaleString() + ' chars)</summary><p>' + esc(message) + '</p></details>';
    } else {
      outputHtml = '<div style="margin-top:5px;font-size:11px;color:var(--muted);white-space:pre-wrap;word-break:break-word">' + esc(message) + '</div>';
    }
  }

  let pulseHtml = '';
  if (isRunning && !message) {
    pulseHtml = '<div class="thinking-dots" style="margin-top:5px;font-size:11px;color:var(--muted)">'
      + 'Thinking<span>.</span><span>.</span><span>.</span></div>';
  }

  const metaParts = [];
  if (startedAt) metaParts.push('Started ' + esc(startedAt));
  if (completedAt && !isRunning) metaParts.push('Finished ' + esc(completedAt));
  if (durationLabel) metaParts.push('Elapsed ' + esc(durationLabel));
  const metaHtml = metaParts.length
    ? '<div style="margin-top:6px;font-size:10px;color:var(--muted)">' + metaParts.join(' &middot; ') + '</div>'
    : '';
  const failureHtml = isFailed && failureReason
    ? '<div style="margin-top:6px;font-size:11px;color:var(--crimson);white-space:pre-wrap;word-break:break-word"><strong>Failure:</strong> ' + esc(failureReason) + '</div>'
    : '';

  div.innerHTML = '<div class="step-dot">' + dotIcon + '</div>'
    + '<div class="step-inner">'
    + '<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">'
    + '<span style="font-size:12px;font-weight:600;color:' + nameColor + '">' + esc(displayName) + '</span>'
    + mcpPill
    + '</div>'
    + reasonHtml
    + outputHtml
    + pulseHtml
    + metaHtml
    + failureHtml
    + '</div>';
  scrollDown();
}

function renderTestReportCard(report) {
  if (!report) return '';
  const status = report.status || 'unknown';
  const isPass = status === 'PASS' || status === 'generated';
  const statusColor = isPass ? 'var(--green, #22c55e)' : (status === 'FAIL' ? '#ef4444' : 'var(--muted)');
  const statusIcon = isPass ? '\u2705' : (status === 'FAIL' ? '\u274c' : '\u23f3');
  const total = report.total || 0;
  const passed = report.passed || 0;
  const failed = report.failed || 0;
  const skipped = report.skipped || 0;
  const duration = report.duration != null ? (parseFloat(report.duration).toFixed(2) + 's') : '';
  const runner = report.runner || '';
  const agentName = report.agent || '';

  const summaryLabel = statusIcon + ' <b style="color:' + statusColor + '">' + esc(status) + '</b>'
    + (runner ? ' <span style="color:var(--muted);font-size:11px">' + esc(runner) + '</span>' : '')
    + (total > 0 ? ' &mdash; ' + passed + ' passed' + (failed > 0 ? ', ' + failed + ' failed' : '') : '')
    + (agentName ? ' <span style="color:var(--muted);font-size:11px;float:right">' + esc(agentName) + '</span>' : '');
  let cardHtml = '<details style="margin-top:10px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;overflow:hidden">';
  cardHtml += '<summary style="padding:10px 12px;cursor:pointer;font-size:13px;font-weight:600;list-style:none;display:flex;align-items:center;gap:6px">' + summaryLabel + '</summary>';
  cardHtml += '<div style="padding:10px 12px;border-top:1px solid var(--border)">';

  if (total > 0) {
    cardHtml += '<div style="display:flex;gap:16px;font-size:12px;margin-bottom:8px">';
    cardHtml += '<span>\ud83d\udcca Total: <b>' + total + '</b></span>';
    cardHtml += '<span style="color:#22c55e">\u2713 ' + passed + ' passed</span>';
    if (failed > 0) cardHtml += '<span style="color:#ef4444">\u2717 ' + failed + ' failed</span>';
    if (skipped > 0) cardHtml += '<span style="color:var(--muted)">\u25e6 ' + skipped + ' skipped</span>';
    if (duration) cardHtml += '<span style="color:var(--muted);margin-left:auto">\u23f1 ' + duration + '</span>';
    cardHtml += '</div>';
  }

  const failures = report.failures || [];
  if (failures.length > 0) {
    cardHtml += '<details style="margin-top:6px"><summary style="font-size:12px;cursor:pointer;color:#ef4444">' + failures.length + ' failure(s)</summary>';
    cardHtml += '<div style="margin-top:6px;font-size:11px;font-family:monospace;max-height:200px;overflow-y:auto;background:var(--surface);padding:8px;border-radius:4px">';
    cardHtml += failures.slice(0, 10).map(f => '<div style="margin-bottom:6px"><b style="color:#ef4444">' + esc(f.name || f.test || '') + '</b><br>' + esc((f.message || f.error || '').slice(0, 300)) + '</div>').join('');
    cardHtml += '</div></details>';
  }

  const files = report.generated_files || [];
  if (files.length > 0) {
    cardHtml += '<div style="margin-top:8px;font-size:12px;color:var(--muted)">\ud83d\udcc4 Generated: ' + files.slice(0, 5).map(f => '<code>' + esc(f) + '</code>').join(', ') + '</div>';
  }

  cardHtml += '</div></details>';
  return cardHtml;
}

function renderMcpInvocationsCard(invocations) {
  if (!invocations || !invocations.length) return '';
  let html = '<details style="margin-top:10px;background:rgba(167,139,250,0.05);border:1px solid rgba(167,139,250,0.3);border-radius:8px;overflow:hidden">';
  html += '<summary style="padding:9px 12px;cursor:pointer;font-size:13px;font-weight:600;list-style:none;display:flex;align-items:center;gap:6px">';
  html += '\uD83E\uDDE9 <span style="color:#a78bfa">MCP Tools Invoked</span> <span style="color:var(--muted);font-size:11px;margin-left:4px">(' + invocations.length + ')</span></summary>';
  html += '<div style="padding:8px 12px;border-top:1px solid rgba(167,139,250,0.2)">';
  invocations.forEach(inv => {
    const ok = inv.ok !== false;
    const dotColor = ok ? '#a78bfa' : '#ef4444';
    html += '<div style="display:flex;align-items:flex-start;gap:8px;padding:5px 0;border-bottom:1px solid rgba(167,139,250,0.1)">';
    html += '<span style="color:' + dotColor + ';font-size:12px">' + (ok ? '\u2713' : '\u2717') + '</span>';
    html += '<div style="flex:1"><div style="font-family:monospace;font-size:12px;color:#a78bfa">' + esc(inv.tool || inv.name || '?') + '</div>';
    if (inv.server) html += '<div style="font-size:11px;color:var(--muted)">via ' + esc(inv.server) + '</div>';
    if (!ok && inv.error) html += '<div style="font-size:11px;color:#ef4444;margin-top:2px">' + esc(inv.error) + '</div>';
    html += '</div></div>';
  });
  html += '</div></details>';
  return html;
}

function renderDocumentDownloadCard(runId, exports) {
  if (!exports || !exports.length) return '';
  const EXT_ICON = { md: '📝', html: '🌐', pdf: '📄', docx: '📘' };
  const EXT_COLOR = { md: '#4ade80', html: '#fbbf24', pdf: '#f87171', docx: '#60a5fa' };
  let html = '<div style="margin-top:12px;padding:14px 16px;background:linear-gradient(135deg,#1a2a1a,#0d1f2d);border:1px solid #2dd4bf44;border-radius:10px">';
  html += '<div style="font-size:12px;font-weight:700;color:#2dd4bf;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:10px">📥 Download Document</div>';
  html += '<div style="display:flex;gap:10px;flex-wrap:wrap">';
  for (const ex of exports) {
    const icon = EXT_ICON[ex.ext] || '📄';
    const color = EXT_COLOR[ex.ext] || '#a3a3a3';
    html += '<a href="/api/artifacts/download?run_id=' + encodeURIComponent(runId) + '&name=' + encodeURIComponent(ex.name) + '" download="' + esc(ex.name) + '" ';
    html += 'style="display:inline-flex;align-items:center;gap:6px;padding:8px 14px;background:#ffffff12;border:1px solid ' + color + '44;border-radius:7px;color:' + color + ';text-decoration:none;font-size:13px;font-weight:600;transition:background 0.15s" ';
    html += 'onmouseover="this.style.background=\'#ffffff20\'" onmouseout="this.style.background=\'#ffffff12\'">';
    html += icon + ' ' + esc(ex.label || ex.ext.toUpperCase());
    html += '</a>';
  }
  html += '</div></div>';
  return html;
}

function renderDocumentPreviewCard(runId, exports) {
  if (!exports || !exports.length) return '';
  const htmlExport = exports.find(ex => ex.ext === 'html');
  if (!htmlExport) return '';
  let html = '<div style="margin-top:12px;padding:14px 16px;background:var(--surface2);border:1px solid var(--border);border-radius:10px">';
  html += '<div style="display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px">';
  html += '<div style="font-size:12px;font-weight:700;color:var(--amber);text-transform:uppercase;letter-spacing:0.1em">Preview</div>';
  html += '<a href="/api/artifacts/view?run_id=' + encodeURIComponent(runId) + '&name=' + encodeURIComponent(htmlExport.name) + '" target="_blank" rel="noopener" style="font-size:12px;color:var(--teal);text-decoration:underline">Open full preview</a>';
  html += '</div>';
  html += '<iframe sandbox="allow-same-origin" src="/api/artifacts/view?run_id=' + encodeURIComponent(runId) + '&name=' + encodeURIComponent(htmlExport.name) + '" style="width:100%;height:560px;border:1px solid var(--border);border-radius:8px;background:#fff"></iframe>';
  html += '</div>';
  return html;
}

function renderDeepResearchCard(card, runId) {
  if (!card || typeof card !== 'object') return '';
  const kind = card.kind || 'result';
  let html = '<div style="margin-top:12px;padding:14px 16px;background:linear-gradient(135deg,#0f172a,#111827);border:1px solid rgba(83,82,237,0.28);border-radius:12px">';
  html += '<div style="display:flex;justify-content:space-between;gap:12px;align-items:flex-start">';
  html += '<div><div style="font-size:12px;font-weight:700;color:#8b8af0;text-transform:uppercase;letter-spacing:.08em;margin-bottom:6px">Deep Research</div>';
  html += '<div style="font-size:16px;font-weight:700;color:var(--text)">' + esc(card.title || 'Deep Research') + '</div></div>';
  if (card.tier) html += '<div style="padding:5px 10px;border-radius:999px;background:rgba(139,138,240,.14);color:#c4b5fd;font-size:12px;font-weight:700">Tier ' + esc(String(card.tier)) + '</div>';
  html += '</div>';
  if (kind === 'analysis' || kind === 'plan') {
    html += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-top:12px">';
    const metrics = [
      ['Pages', card.estimated_pages || card.section_count || '—'],
      ['Sources', card.estimated_sources || '—'],
      ['Minutes', card.estimated_duration_minutes || '—'],
      ['Style', (card.citation_style || '').toUpperCase() || 'APA']
    ];
    metrics.forEach(([label,val]) => {
      html += '<div style="padding:10px;background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:10px"><div style="font-size:10px;color:var(--muted);text-transform:uppercase">' + esc(label) + '</div><div style="font-size:16px;font-weight:700;color:var(--text);margin-top:2px">' + esc(String(val)) + '</div></div>';
    });
    html += '</div>';
    if (card.subtopics && card.subtopics.length) {
      html += '<div style="margin-top:12px;font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em">Detected Subtopics</div>';
      html += '<div style="display:flex;gap:8px;flex-wrap:wrap;margin-top:8px">';
      card.subtopics.forEach(topic => {
        html += '<span style="padding:6px 10px;border-radius:999px;background:rgba(0,201,167,0.10);border:1px solid rgba(0,201,167,0.20);font-size:12px;color:#9ae6d8">' + esc(String(topic)) + '</span>';
      });
      html += '</div>';
    }
    if (kind === 'analysis') {
      html += '<div style="display:flex;gap:10px;flex-wrap:wrap;margin-top:14px">';
      html += '<button onclick="sendQuickReply(\'approve\')" style="padding:9px 14px;border:none;border-radius:8px;background:#00c9a7;color:#04130f;font-weight:700;cursor:pointer">Start Deep Research</button>';
      html += '<button onclick="sendQuickReply(\'quick summary\')" style="padding:9px 14px;border:1px solid rgba(255,255,255,.12);border-radius:8px;background:transparent;color:var(--text);font-weight:600;cursor:pointer">Quick Summary</button>';
      html += '</div>';
    }
  } else {
    html += '<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(110px,1fr));gap:10px;margin-top:12px">';
    const metrics = [
      ['Pages', card.pages || '—'],
      ['Words', card.words || '—'],
      ['Sources', card.sources || '—'],
      ['Citations', card.citations || '—'],
      ['Plagiarism', ((card.plagiarism_score ?? '—') + '%')],
      ['Minutes', card.duration_minutes || '—']
    ];
    metrics.forEach(([label,val]) => {
      html += '<div style="padding:10px;background:rgba(255,255,255,0.03);border:1px solid var(--border);border-radius:10px"><div style="font-size:10px;color:var(--muted);text-transform:uppercase">' + esc(label) + '</div><div style="font-size:16px;font-weight:700;color:var(--text);margin-top:2px">' + esc(String(val)) + '</div></div>';
    });
    html += '</div>';
    // Download buttons for available report files
    const EXT_ICON = { md: '📝', html: '🌐', pdf: '📄', docx: '📘' };
    const EXT_COLOR = { md: '#4ade80', html: '#fbbf24', pdf: '#f87171', docx: '#60a5fa' };
    const EXT_LABEL = { md: 'Markdown', html: 'HTML', pdf: 'PDF', docx: 'Word (DOCX)' };
    const fileEntries = [
      { ext: 'md', path: card.report_path },
      { ext: 'html', path: card.html_path },
      { ext: 'pdf', path: card.pdf_path },
      { ext: 'docx', path: card.docx_path },
    ].filter(e => e.path);
    const exportErrors = card.export_errors || {};
    const missingFormats = (card.formats || []).filter(fmt => {
      if (fmt === 'md') return false; // md always available if report exists
      const pathKey = fmt + '_path';
      return !card[pathKey];
    });
    if (fileEntries.length > 0 || Object.keys(exportErrors).length > 0) {
      html += '<div style="margin-top:14px">';
      html += '<div style="font-size:11px;font-weight:700;color:#2dd4bf;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:8px">📥 Download Report</div>';
      html += '<div style="display:flex;gap:8px;flex-wrap:wrap">';
      for (const entry of fileEntries) {
        const fname = entry.path.replace(/\\\\/g, '/').split('/').pop() || ('report.' + entry.ext);
        const icon = EXT_ICON[entry.ext] || '📄';
        const color = EXT_COLOR[entry.ext] || '#a3a3a3';
        const label = EXT_LABEL[entry.ext] || entry.ext.toUpperCase();
        html += '<a href="/api/artifacts/download?run_id=' + encodeURIComponent(runId) + '&name=' + encodeURIComponent(fname) + '" download="' + esc(fname) + '" ';
        html += 'style="display:inline-flex;align-items:center;gap:6px;padding:8px 14px;background:#ffffff12;border:1px solid ' + color + '44;border-radius:7px;color:' + color + ';text-decoration:none;font-size:13px;font-weight:600" ';
        html += 'onmouseover="this.style.background=\'#ffffff20\'" onmouseout="this.style.background=\'#ffffff12\'">';
        html += icon + ' ' + esc(label) + '</a>';
      }
      // Show failed format errors with re-export option
      for (const [fmt, errMsg] of Object.entries(exportErrors)) {
        const icon = EXT_ICON[fmt] || '📄';
        const label = EXT_LABEL[fmt] || fmt.toUpperCase();
        html += '<span style="display:inline-flex;align-items:center;gap:6px;padding:8px 14px;background:rgba(239,68,68,0.1);border:1px solid rgba(239,68,68,0.3);border-radius:7px;font-size:12px;color:#f87171" title="' + esc(errMsg) + '">' + icon + ' ' + esc(label) + ' failed</span>';
        html += '<button onclick="sendQuickReply(\'Re-export the deep research report as ' + fmt.toUpperCase() + '\')" style="padding:7px 12px;background:rgba(251,191,36,0.12);border:1px solid rgba(251,191,36,0.3);border-radius:7px;color:#fbbf24;font-size:12px;font-weight:600;cursor:pointer">↺ Retry ' + esc(label) + '</button>';
      }
      html += '</div></div>';
    }
  }
  html += '<div style="margin-top:12px;font-size:12px;color:var(--muted)">';
  html += 'Web search: <strong style="color:var(--text)">' + (card.web_search_enabled === false ? 'disabled' : 'enabled') + '</strong>';
  if (card.local_sources != null) html += ' · Local files: <strong style="color:var(--text)">' + esc(String(card.local_sources)) + '</strong>';
  if (card.provided_urls != null) html += ' · Explicit URLs: <strong style="color:var(--text)">' + esc(String(card.provided_urls)) + '</strong>';
  html += '</div>';
  html += '</div>';
  return html;
}

function finalizeStreamRow(runId, output, error, artifactFiles, testReport, mcpInvocations, docExports, deepResearchCard, finalStatus) {
  const row = document.getElementById('stream-row-' + runId);
  if (!row) return;
  const typing = row.querySelector('.typing-indicator');
  if (typing) typing.remove();
  const statusEl = document.getElementById('stream-status-' + runId);
  if (statusEl) {
    const statusWrapper = statusEl.closest('div[style]') || statusEl.parentElement;
    if (statusWrapper && statusWrapper !== document.getElementById('stream-bubble-' + runId)) {
      statusWrapper.remove();
    } else {
      statusEl.remove();
    }
  }
  const resultEl = document.getElementById('stream-result-' + runId);
  const resolvedStatus = error ? 'failed' : (finalStatus || _chatRunState.status || (isAwaitingInput ? 'awaiting_user_input' : 'completed'));
  _chatRunState.status = resolvedStatus;
  _chatRunState.completedAt = ['completed', 'failed', 'cancelled'].includes(resolvedStatus) ? new Date().toISOString() : '';
  _stopRunWorkingTimer(runId, resolvedStatus !== 'awaiting_user_input' && resolvedStatus !== 'cancelling');
  if (error) {
    _lastFailedRunContext = {
      runId,
      workflowId: currentWorkflowId || _chatRunState.workflowId || runId,
      task: _chatRunState.task || _chatRunState.title || '',
    };
    _pushRunLiveUpdate(runId, resolvedStatus === 'cancelled' ? 'Run stopped by user' : 'Run failed', error);
    _recordChatActivity({
      title: resolvedStatus === 'cancelled' ? 'Run stopped' : 'Run failed',
      status: resolvedStatus === 'cancelled' ? 'cancelled' : 'failed',
      detail: error,
      completed_at: _chatRunState.completedAt,
      task: _chatRunState.task || _chatRunState.title,
    });
  } else {
    _lastFailedRunContext = null;
    const activityStatus = resolvedStatus === 'awaiting_user_input'
      ? 'pending'
      : resolvedStatus === 'cancelled'
        ? 'cancelled'
        : resolvedStatus === 'cancelling'
          ? 'pending'
          : 'completed';
    const activityDetail = resolvedStatus === 'awaiting_user_input'
      ? 'The runtime is waiting for your response before continuing.'
      : resolvedStatus === 'cancelled'
        ? 'Run stopped by user.'
        : resolvedStatus === 'cancelling'
          ? 'Stop requested. Waiting for the active task to exit.'
          : output ? 'Final response generated.' : 'Run completed without final text output.';
    _recordChatActivity({
      title: resolvedStatus === 'awaiting_user_input' ? 'Run paused for input' : resolvedStatus === 'cancelled' ? 'Run stopped' : 'Run completed',
      status: activityStatus,
      detail: activityDetail,
      completed_at: _chatRunState.completedAt,
      task: _chatRunState.task || _chatRunState.title,
    });
    _pushRunLiveUpdate(
      runId,
      resolvedStatus === 'awaiting_user_input' ? 'Waiting for your input' : resolvedStatus === 'cancelled' ? 'Run stopped' : 'Run completed',
      activityDetail,
    );
  }
  _renderChatInspector();
  if (resultEl) {
    if (error) {
      resultEl.innerHTML = '<div class="error-banner" style="margin-top:8px">\u26A0\uFE0F ' + esc(error) + '</div>';
      if (_lastFailedRunContext && _lastFailedRunContext.runId === runId) {
        resultEl.innerHTML += '<div style="margin-top:10px"><button onclick="sendQuickReply(\'retry\')" style="padding:8px 12px;border:none;border-radius:8px;background:#fbbf24;color:#1f1400;font-weight:700;cursor:pointer">Retry From Checkpoint</button></div>';
      }
    } else if (output) {
      resultEl.innerHTML = '<div style="margin-top:10px;border-top:1px solid var(--border);padding-top:10px">' + formatOutput(output) + '</div>';
    }
    if (testReport) {
      resultEl.innerHTML += renderTestReportCard(testReport);
    }
    if (mcpInvocations && mcpInvocations.length) {
      resultEl.innerHTML += renderMcpInvocationsCard(mcpInvocations);
    }
    if (deepResearchCard) {
      resultEl.innerHTML += renderDeepResearchCard(deepResearchCard, runId);
    }
    if (docExports && docExports.length > 0) {
      resultEl.innerHTML += renderDocumentPreviewCard(runId, docExports);
    }
    if (docExports && docExports.length > 0) {
      resultEl.innerHTML += renderDocumentDownloadCard(runId, docExports);
    }
    const executionSummary = _renderRunExecutionSummary(runId);
    if (executionSummary) {
      resultEl.innerHTML += executionSummary;
    }
    // Remember last completed run for inline file-request handling
    if (deepResearchCard && deepResearchCard.kind === 'result') { _lastDeepResearchCard = deepResearchCard; _lastCompletedRunId = runId; }
    if (docExports && docExports.length) { _lastDocExports = docExports; _lastCompletedRunId = runId; }
  }
  const meta = document.createElement('div');
  meta.className = 'bubble-meta';
  meta.textContent = 'Run: ' + runId;
  const bubble = document.getElementById('stream-bubble-' + runId);
  if (bubble) bubble.appendChild(meta);
  scrollDown();
}

let _planPollInterval = null;
let _activityPollInterval = null;

function startPlanPolling(runId) {
  stopPlanPolling();
  let lastStepCount = 0;
  _planPollInterval = setInterval(async () => {
    try {
      const r = await fetch('/api/plan');
      if (!r.ok) return;
      const plan = await r.json();
      if (!plan.has_plan || !plan.steps || plan.steps.length === 0) return;
      _chatPlanState = {
        total: Number(plan.total_steps || plan.steps.length || 0),
        completed: Number(plan.completed_steps || 0),
        running: Number(plan.running_steps || 0),
        failed: Number(plan.failed_steps || 0),
      };
      if (plan.summary || plan.scope) {
        _chatRunState.task = [plan.scope, plan.summary].filter(Boolean).join(' — ') || _chatRunState.task;
      }
      _renderChatInspector();
      const panelId = 'plan-panel-' + runId;
      let panel = document.getElementById(panelId);
      if (!panel) {
        const wrapper = document.getElementById('stream-steps-' + runId);
        if (!wrapper) return;
        panel = document.createElement('div');
        panel.id = panelId;
        panel.style.cssText = 'background:rgba(0,201,167,0.05);border:1px solid rgba(0,201,167,0.2);border-radius:10px;padding:12px 14px;margin:10px 0 6px;';
        panel.innerHTML = '<div style="font-size:11px;font-weight:700;color:var(--teal);letter-spacing:.08em;text-transform:uppercase;margin-bottom:8px">Plan Progress</div><div id="plan-steps-' + runId + '"></div>';
        wrapper.insertBefore(panel, wrapper.firstChild);
      }
      const stepsEl = document.getElementById('plan-steps-' + runId);
      if (!stepsEl) return;
      const statusIcon = {pending:'⏳',running:'🔄',completed:'✅',failed:'❌',skipped:'⏭'};
      const statusColor = {pending:'var(--muted)',running:'var(--amber)',completed:'var(--teal)',failed:'var(--crimson)',skipped:'var(--muted)'};
      stepsEl.innerHTML = plan.steps.map((s,i) => {
        const st = s.status || 'pending';
        const icon = statusIcon[st] || '⏳';
        const color = statusColor[st] || 'var(--muted)';
        const title = esc(s.title || s.id || ('Step ' + (i+1)));
        const agent = esc(s.agent || '');
        const startedAt = _formatStepTimestamp(s.started_at);
        const completedAt = _formatStepTimestamp(s.completed_at);
        const durationLabel = _formatStepDuration(s);
        const metaParts = [];
        if (startedAt) metaParts.push('Started ' + esc(startedAt));
        if (completedAt && st !== 'running') metaParts.push('Finished ' + esc(completedAt));
        if (durationLabel) metaParts.push('Elapsed ' + esc(durationLabel));
        const meta = metaParts.length ? '<div style="font-size:10px;color:var(--muted);margin-top:3px">' + metaParts.join(' &middot; ') + '</div>' : '';
        const result = s.result_summary ? '<div style="font-size:11px;color:var(--muted);margin-top:2px;padding-left:4px;border-left:2px solid var(--border)">' + esc(s.result_summary.slice(0,120)) + '</div>' : '';
        const err = s.error ? '<div style="font-size:11px;color:var(--crimson);margin-top:2px">\u26A0 ' + esc(s.error.slice(0,120)) + '</div>' : '';
        return '<div style="display:flex;gap:8px;align-items:flex-start;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.04)">' +
          '<span style="font-size:13px;min-width:18px">' + icon + '</span>' +
          '<div style="flex:1;min-width:0"><div style="font-size:12px;color:' + color + ';font-weight:' + (st==='running'?'600':'400') + '">' + title + '</div>' +
          '<div style="font-size:11px;color:var(--muted)">' + agent + '</div>' + meta + result + err + '</div></div>';
      }).join('');
      const summary = '<div style="font-size:11px;color:var(--muted);margin-top:6px">' + plan.completed_steps + '/' + plan.total_steps + ' done' + (plan.running_steps > 0 ? ' &middot; ' + plan.running_steps + ' running' : '') + (plan.failed_steps > 0 ? ' &middot; <span style=\'color:var(--crimson)\'>' + plan.failed_steps + ' failed</span>' : '') + '</div>';
      stepsEl.insertAdjacentHTML('beforeend', summary);
    } catch(_) {}
  }, 2000);
}

function stopPlanPolling() {
  if (_planPollInterval) { clearInterval(_planPollInterval); _planPollInterval = null; }
}

function _taskSessionSummary(session) {
  if (!session || typeof session !== 'object') return {};
  if (session.summary && typeof session.summary === 'object') return session.summary;
  if (typeof session.summary_json === 'string' && session.summary_json) {
    try { return JSON.parse(session.summary_json); } catch (_) {}
  }
  return {};
}

function _runStatusRank(status) {
  const normalized = String(status || '').toLowerCase();
  if (normalized === 'running' || normalized === 'started' || normalized === 'cancelling') return 2;
  if (normalized === 'awaiting_user_input') return 1;
  // terminal statuses (completed, failed, cancelled) all rank 0 — sort by time only
  return 0;
}

function _renderTraceActivity(runId, session) {
  const summary = _taskSessionSummary(session);
  const events = Array.isArray(summary.execution_trace) ? summary.execution_trace : [];
  if (!events.length) return '';
  const activeTask = summary.active_task || summary.objective || '';
  const rows = events.map(event => {
    const status = String(event.status || 'info');
    const title = event.title || event.kind || 'Activity';
    const actor = event.actor || 'system';
    const metadata = (event && typeof event.metadata === 'object' && event.metadata) ? event.metadata : {};
    const startedAt = _formatStepTimestamp(event.started_at || event.timestamp);
    const completedAt = _formatStepTimestamp(event.completed_at);
    const durationLabel = event.duration_label || _formatStepDuration(event);
    const command = event.command || '';
    const cwd = event.cwd || '';
    const detail = event.detail || '';
    const searchQuery = metadata.search_query || '';
    const urlList = Array.isArray(metadata.urls) ? metadata.urls.filter(Boolean) : [];
    const failedUrlList = Array.isArray(metadata.failed_urls) ? metadata.failed_urls.filter(Boolean) : [];
    const metaParts = [];
    if (startedAt) metaParts.push(startedAt);
    if (completedAt && completedAt !== startedAt) metaParts.push('done ' + completedAt);
    if (durationLabel) metaParts.push(durationLabel);
    if (event.exit_code !== null && event.exit_code !== undefined && event.exit_code !== '') metaParts.push('exit ' + event.exit_code);
    const meta = metaParts.length ? '<div style="font-size:10px;color:var(--muted);margin-top:3px">' + metaParts.join(' &middot; ') + '</div>' : '';
    const commandLabel = searchQuery ? 'query' : 'command';
    const commandValue = command || searchQuery || '';
    const commandHtml = commandValue
      ? '<div style="margin-top:6px"><div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">' + esc(commandLabel) + '</div><div style="padding:8px 10px;background:#ffffff0a;border:1px solid var(--border);border-radius:8px;font-family:ui-monospace,SFMono-Regular,Menlo,monospace;font-size:11px;color:#d7e3ff;white-space:pre-wrap;word-break:break-word">' + esc(commandValue) + '</div></div>'
      : '';
    const cwdHtml = cwd
      ? '<div style="margin-top:4px;font-size:10px;color:var(--muted)">cwd: ' + esc(cwd) + '</div>'
      : '';
    const detailHtml = detail && detail !== commandValue
      ? '<div style="margin-top:5px;font-size:11px;color:var(--muted);white-space:pre-wrap;word-break:break-word">' + esc(detail) + '</div>'
      : '';
    const urlsHtml = urlList.length
      ? '<div style="margin-top:7px"><div style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">URLs</div>' +
        urlList.map(url => '<div style="font-size:11px;color:#9ad7ff;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(url) + '</div>').join('') +
        '</div>'
      : '';
    const failedUrlsHtml = failedUrlList.length
      ? '<div style="margin-top:7px"><div style="font-size:10px;color:var(--crimson);text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">Failed URLs</div>' +
        failedUrlList.map(url => '<div style="font-size:11px;color:var(--crimson);white-space:nowrap;overflow:hidden;text-overflow:ellipsis">' + esc(url) + '</div>').join('') +
        '</div>'
      : '';
    const color = status === 'failed' ? 'var(--crimson)' : status === 'completed' ? 'var(--teal)' : status === 'running' ? 'var(--amber)' : 'var(--muted)';
    const icon = status === 'failed' ? '\u2717' : status === 'completed' ? '\u2713' : status === 'running' ? '\u25CF' : '\u2022';
    return '<div style="padding:10px 0;border-bottom:1px solid rgba(255,255,255,0.05)">' +
      '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap">' +
      '<span style="font-size:12px;color:' + color + '">' + icon + '</span>' +
      '<span style="font-size:12px;font-weight:700;color:var(--text)">' + esc(title) + '</span>' +
      '<span style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">' + esc(actor) + '</span>' +
      '</div>' + meta + detailHtml + commandHtml + urlsHtml + failedUrlsHtml + cwdHtml + '</div>';
  }).join('');

  let html = '<div style="font-size:11px;font-weight:700;color:var(--amber);letter-spacing:.08em;text-transform:uppercase;margin-bottom:8px">Run Activity</div>';
  if (activeTask) {
    html += '<div style="font-size:11px;color:var(--muted);margin-bottom:10px">Current task: <span style="color:var(--text)">' + esc(activeTask) + '</span></div>';
  }
  html += rows;
  return html;
}

function startActivityPolling(runId) {
  stopActivityPolling();
  _activityPollInterval = setInterval(async () => {
    try {
      const r = await fetch('/api/task-sessions/by-run/' + encodeURIComponent(runId));
      if (!r.ok) return;
      const session = await r.json();
      const summary = _taskSessionSummary(session);
      const events = Array.isArray(summary.execution_trace) ? summary.execution_trace : [];
      if (!events.length) return;
      if (summary.active_task || summary.objective) _chatRunState.task = summary.active_task || summary.objective || _chatRunState.task;
      _recordRunTraceEvents(runId, events, { run_id: runId, task: summary.active_task || summary.objective || '' });
      _recordChatActivities(events, { run_id: runId, task: summary.active_task || summary.objective || '' });
      _upsertRunTracePanel(runId, summary.active_task || summary.objective || '');
    } catch(_) {}
  }, 2000);
}

function stopActivityPolling() {
  if (_activityPollInterval) { clearInterval(_activityPollInterval); _activityPollInterval = null; }
}

function _markRunDisconnected(runId, reason = '') {
  const activeRunId = String(runId || currentRunId || '').trim();
  if (!activeRunId) return;
  sessionStorage.removeItem('kendr_active_run_id');
  const message = reason || 'Connection to the server was lost. Retry to resume from the last checkpoint.';
  _lastFailedRunContext = {
    runId: activeRunId,
    workflowId: currentWorkflowId || activeRunId,
    task: _chatRunState.task || _chatRunState.title || '',
  };
  _chatRunState.status = 'failed';
  finalizeStreamRow(activeRunId, '', message, [], null, null, null, null, 'failed');
  isRunning = false;
  isStopping = false;
  _setChatComposerState();
}

function openEventStream(runId) {
  if (activeEvtSource) { activeEvtSource.close(); activeEvtSource = null; }
  const evtSrc = new EventSource(API + '/api/stream?run_id=' + encodeURIComponent(runId));
  activeEvtSource = evtSrc;
  _chatRunState.status = 'running';
  _renderChatInspector();
  startPlanPolling(runId);
  startActivityPolling(runId);

  evtSrc.addEventListener('status', e => {
    try {
      const d = JSON.parse(e.data);
      const normalizedStatus = String(d.status || '').toLowerCase();
      if (normalizedStatus === 'cancelling') {
        _chatRunState.status = 'cancelling';
      }
      if (d.message || d.status) {
        _pushRunLiveUpdate(runId, 'Runtime update', d.message || d.status || '');
        _recordChatActivity({
          title: 'Runtime status updated',
          status: normalizedStatus === 'cancelling' ? 'pending' : 'running',
          detail: d.message || d.status || '',
          started_at: _chatRunState.startedAt || new Date().toISOString(),
          task: _chatRunState.task || _chatRunState.title,
        });
      }
      updateStreamStatus(runId, d.message || d.status || '');
      _renderChatInspector();
    } catch(_) {}
  });

  evtSrc.addEventListener('activity', e => {
    try {
      const item = JSON.parse(e.data);
      const title = String(item.title || item.kind || 'Activity').trim();
      const detail = String(item.detail || '').trim();
      const command = String(item.command || '').trim();
      _pushRunLiveUpdate(runId, title, detail || command || '');
      _recordRunTraceEvents(runId, [item], { run_id: runId, task: _chatRunState.task || _chatRunState.title });
      _upsertRunTracePanel(runId);
      _recordChatActivity(Object.assign({}, item, { run_id: runId, task: _chatRunState.task || _chatRunState.title }));
    } catch(_) {}
  });

  evtSrc.addEventListener('step', e => {
    try {
      const step = JSON.parse(e.data);
      addStreamStep(runId, step);
      const summary = _runStepSummary(runId);
      if (summary.total > 0) {
        const progress = summary.completed + '/' + summary.total + ' tasks done'
          + (summary.running > 0 ? ' · ' + summary.running + ' running' : '')
          + (summary.failed > 0 ? ' · ' + summary.failed + ' failed' : '');
        updateStreamStatus(runId, progress);
      }
      _recordChatActivity({
        title: (step.agent || step.name || 'agent') + ' step',
        status: step.status || 'running',
        detail: step.message || step.reason || '',
        started_at: step.started_at || '',
        completed_at: step.completed_at || '',
        duration_ms: step.duration_ms,
        duration_label: step.duration_label,
        actor: step.agent || step.name || '',
        task: _chatRunState.task || _chatRunState.title,
      });
    } catch(_) {}
  });

  evtSrc.addEventListener('result', e => {
    try {
      const d = JSON.parse(e.data);
      const output = d.final_output || d.output || d.draft_response || '';
      const runStatus = String(d.status || '').toLowerCase();
      const awaiting = runStatus === 'awaiting_user_input'
        || d.awaiting_user_input
        || d.plan_waiting_for_approval
        || d.plan_needs_clarification
        || !!d.pending_user_input_kind
        || !!d.approval_pending_scope
        || !!d.pending_user_question
        || (d.approval_request && typeof d.approval_request === 'object' && Object.keys(d.approval_request).length > 0)
        || false;
      currentWorkflowId = d.workflow_id || currentWorkflowId || runId;
      _chatRunState.workflowId = currentWorkflowId;
      _chatRunState.attemptId = d.attempt_id || runId;
        if (awaiting) {
          _setChatAwaitingContext({
            runId: d.run_id || runId,
            workflowId: d.workflow_id || currentWorkflowId || runId,
            attemptId: d.attempt_id || runId,
            workingDir: _chatResumePathFromRun(d) || workingDir || _pendingResumeDir || '',
            prompt: d.pending_user_question || output || 'This run is waiting for your approval or feedback.',
            approvalRequest: d.approval_request || null,
            pendingKind: d.pending_user_input_kind || '',
          scope: d.approval_pending_scope || '',
        });
        _chatRunState.status = 'awaiting_user_input';
        updateStreamStatus(runId, 'Awaiting your input…');
      } else {
        _chatRunState.status = runStatus || 'completed';
        updateStreamStatus(runId, _chatRunState.status === 'cancelled' ? 'Stopped.' : 'Completed.');
      }
      finalizeStreamRow(runId, output, '', d.artifact_files || [], d.test_report || null, d.mcp_invocations || null, d.long_document_exports || null, d.deep_research_result_card || null, _chatRunState.status);
    } catch(_) {}
  });

  evtSrc.addEventListener('error', e => {
    try {
      const d = JSON.parse(e.data);
      _chatRunState.status = 'failed';
      _chatAwaitingContext = null;
      _closeChatApprovalModal();
      finalizeStreamRow(runId, '', d.message || 'Run failed', [], null, null, null, null, 'failed');
    } catch(_) {
      _chatRunState.status = 'failed';
      _chatAwaitingContext = null;
      _closeChatApprovalModal();
      finalizeStreamRow(runId, '', 'Stream error', [], null, null, null, null, 'failed');
    }
    stopPlanPolling();
    stopActivityPolling();
    _stopRunWorkingTimer(runId, true);
    evtSrc.close();
    activeEvtSource = null;
    isRunning = false;
    isStopping = false;
    _setChatComposerState();
    loadRuns();
  });

  evtSrc.addEventListener('done', e => {
    try {
      const d = JSON.parse(e.data);
      const doneStatus = String(d.status || '').toLowerCase();
      if (d.awaiting_user_input || doneStatus === 'awaiting_user_input') {
        isAwaitingInput = true;
        _chatRunState.status = 'awaiting_user_input';
        _showAwaitingBanner();
      } else {
        isAwaitingInput = false;
        _chatAwaitingContext = null;
        _closeChatApprovalModal();
        _chatRunState.status = doneStatus || (_chatRunState.status === 'failed' ? 'failed' : 'completed');
        sessionStorage.removeItem('kendr_active_run_id');
      }
    } catch(_) { sessionStorage.removeItem('kendr_active_run_id'); }
    delete _runRecoveryAttempts[runId];
    stopPlanPolling();
    stopActivityPolling();
    _stopRunWorkingTimer(runId, true);
    evtSrc.close();
    activeEvtSource = null;
    isRunning = false;
    isStopping = false;
    _setChatComposerState();
    loadRuns();
  });

  evtSrc.addEventListener('ping', () => {});

  evtSrc.onerror = async () => {
    stopPlanPolling();
    stopActivityPolling();
    _stopRunWorkingTimer(runId, true);
    try { evtSrc.close(); } catch (_) {}
    activeEvtSource = null;
    _markRunDisconnected(runId, 'Connection lost. Server or gateway restarted. Type retry to resume from the last checkpoint.');
    loadRuns();
  };
}

async function stopCurrentRun() {
  if (!currentRunId || !isRunning || isStopping) return;
  isStopping = true;
  _chatRunState.status = 'cancelling';
  _recordChatActivity({
    title: 'Stop requested',
    status: 'pending',
    detail: 'Waiting for the runtime to halt the active run.',
    started_at: new Date().toISOString(),
    task: _chatRunState.task || _chatRunState.title,
  });
  updateStreamStatus(currentRunId, 'Stopping run…');
  _renderChatInspector();
  _setChatComposerState();
  try {
    const resp = await fetch(API + '/api/runs/stop', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ run_id: currentRunId }),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok || data.error) {
      throw new Error((data && (data.error || data.detail)) || ('Stop request failed (' + resp.status + ')'));
    }
    updateStreamStatus(currentRunId, 'Stopping run…');
  } catch (err) {
    isStopping = false;
    _chatRunState.status = 'running';
    _recordChatActivity({
      title: 'Stop request failed',
      status: 'failed',
      detail: String(err),
      completed_at: new Date().toISOString(),
      task: _chatRunState.task || _chatRunState.title,
    });
    _renderChatInspector();
    _setChatComposerState();
  }
}

function handleSendButton() {
  if (isRunning) {
    stopCurrentRun();
    return;
  }
  sendMessage();
}

// Returns HTML string with download cards if the text looks like a file request and we have files,
// otherwise returns null so the caller can fall through to the normal agent path.
function _tryHandleFileRequest(text) {
  const lower = text.toLowerCase();
  const isAction = /\b(give\s+me|download|get|send\s+me|share|export|show\s+me|fetch|retrieve|provide)\b/.test(lower);
  const isFileRef = /\b(pdf|docx|doc|word|html|md|markdown|report|document|file|output|result)\b/.test(lower);
  if (!isAction && !/\b(download|report|file)\b/.test(lower)) return null;
  if (!isFileRef) return null;

  // Determine which format(s) were requested
  const wantsPdf  = /\bpdf\b/.test(lower);
  const wantsDocx = /\b(docx|doc|word)\b/.test(lower);
  const wantsHtml = /\bhtml\b/.test(lower);
  const wantsMd   = /\b(md|markdown)\b/.test(lower);
  const wantsAny  = !wantsPdf && !wantsDocx && !wantsHtml && !wantsMd;

  // Gather files: prefer session state, fall back to persisted project chat history
  let card = _lastDeepResearchCard;
  let docExports = _lastDocExports ? _lastDocExports.slice() : [];
  let runId = _lastCompletedRunId;
  if (!card && !docExports.length && typeof _projectChatMessages !== 'undefined') {
    for (let i = (_projectChatMessages || []).length - 1; i >= 0; i--) {
      const msg = _projectChatMessages[i];
      if (msg.role === 'agent') {
        if (!card && msg.deep_research_result_card) { card = msg.deep_research_result_card; runId = msg.run_id || ''; }
        if (!docExports.length && msg.long_document_exports) { docExports = msg.long_document_exports; runId = msg.run_id || runId; }
        if (card || docExports.length) break;
      }
    }
  }

  if (!card && !docExports.length) return null;

  // Filter exports to requested formats
  const filteredExports = wantsAny ? docExports : docExports.filter(ex =>
    (wantsPdf && ex.ext === 'pdf') || (wantsDocx && ex.ext === 'docx') ||
    (wantsHtml && ex.ext === 'html') || (wantsMd && ex.ext === 'md')
  );
  // Also filter card paths to requested formats when building the card display
  let displayCard = card;
  if (card && !wantsAny) {
    displayCard = Object.assign({}, card);
    if (!wantsMd) displayCard.report_path = '';
    if (!wantsHtml) displayCard.html_path = '';
    if (!wantsPdf) displayCard.pdf_path = '';
    if (!wantsDocx) displayCard.docx_path = '';
  }

  let html = '';
  if (displayCard && displayCard.kind === 'result') html += renderDeepResearchCard(displayCard, runId);
  if (filteredExports.length) {
    html += renderDocumentPreviewCard(runId, filteredExports);
    html += renderDocumentDownloadCard(runId, filteredExports);
  } else if (!displayCard) {
    return null; // Nothing to show after filtering
  }
  return html || null;
}

// ── Chat file attachment helpers ──────────────────────────────────────────────
function _readFileAsText(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = e => resolve(e.target.result);
    reader.onerror = () => reject(new Error('Could not read ' + file.name));
    reader.readAsText(file);
  });
}

function _renderAttachChips(attachments, containerId, removeFn) {
  const el = document.getElementById(containerId);
  if (!el) return;
  el.innerHTML = attachments.map((a, i) =>
    `<span class="chat-attach-chip">&#x1F4CE; ${escapeHtml(a.name)}<button onclick="${removeFn}(${i})" title="Remove">&#x2715;</button></span>`
  ).join('');
}

async function handleMainChatFileSelect(input) {
  for (const file of Array.from(input.files)) {
    try { _mainChatAttachments.push({ name: file.name, content: await _readFileAsText(file) }); }
    catch(e) { console.warn('Attach error:', e); }
  }
  input.value = '';
  _renderAttachChips(_mainChatAttachments, 'mainChatAttachChips', 'removeMainChatAttachment');
}

function removeMainChatAttachment(idx) {
  _mainChatAttachments.splice(idx, 1);
  _renderAttachChips(_mainChatAttachments, 'mainChatAttachChips', 'removeMainChatAttachment');
}

async function handleProjChatFileSelect(input) {
  for (const file of Array.from(input.files)) {
    try { _projChatAttachments.push({ name: file.name, content: await _readFileAsText(file) }); }
    catch(e) { console.warn('Attach error:', e); }
  }
  input.value = '';
  _renderAttachChips(_projChatAttachments, 'projChatAttachChips', 'removeProjChatAttachment');
}

function removeProjChatAttachment(idx) {
  _projChatAttachments.splice(idx, 1);
  _renderAttachChips(_projChatAttachments, 'projChatAttachChips', 'removeProjChatAttachment');
}

function _buildTextWithAttachments(text, attachments) {
  if (!attachments.length) return text;
  const parts = attachments.map(a => {
    const ext = (a.name.split('.').pop() || '').toLowerCase();
    return ext === 'md'
      ? `[Attached: ${a.name}]\n\n${a.content}`
      : `[Attached: ${a.name}]\n\`\`\`${ext}\n${a.content}\n\`\`\``;
  });
  const joined = parts.join('\n\n---\n\n');
  return text ? joined + '\n\n---\n\n' + text : joined;
}

async function sendMessage() {
  const input = document.getElementById('userInput');
  const rawText = input.value.trim();
  const text = _buildTextWithAttachments(rawText, _mainChatAttachments);
  if (!text || isRunning) return;
  const retryRequested = _isRetryCommand(rawText) && !!_lastFailedRunContext;

  input.value = '';
  autoResize(input);
  _mainChatAttachments = [];
  _renderAttachChips(_mainChatAttachments, 'mainChatAttachChips', 'removeMainChatAttachment');
  isRunning = true;
  isStopping = false;
  _setChatComposerState();

  const isContinuation = isAwaitingInput;
  const continuationContext = isContinuation ? Object.assign({}, _chatAwaitingContext || {}) : null;
  const continuationRunId = continuationContext && continuationContext.runId ? continuationContext.runId : '';
  const continuationWorkflowId = continuationContext && continuationContext.workflowId ? continuationContext.workflowId : '';
  const continuationTask = continuationContext && continuationContext.task ? continuationContext.task : (_chatRunState.task || '');
  const continuationTitle = continuationContext && continuationContext.title ? continuationContext.title : (_chatRunState.title || '');
  isAwaitingInput = false;
  _closeChatApprovalModal();
  _removeAwaitingBanner();

  appendUserMsg(text);
  // Every message turn (including approval/resume replies) gets a fresh run id.
  // Keeping workflow_id stable preserves thread identity without overwriting prior runs.
  const runId = 'ui-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
  const workflowId = continuationWorkflowId || continuationRunId || runId;
  currentRunId = runId;
  currentWorkflowId = workflowId;
  sessionStorage.setItem('kendr_active_run_id', runId);
  _chatRunState = {
    runId,
    workflowId,
    attemptId: runId,
    status: 'running',
    title: text.substring(0, 80) + (text.length > 80 ? '…' : ''),
    task: text,
    startedAt: new Date().toISOString(),
    completedAt: '',
    lastCommand: '',
    lastCommandMeta: '',
  };
  if (isContinuation) {
    _chatRunState.title = continuationTitle || continuationTask || 'Continuing paused run';
    _chatRunState.task = continuationTask || continuationTitle || text;
  }
  _chatPlanState = { total: 0, completed: 0, running: 0, failed: 0 };
  _chatActivityFeed = [];
  _renderChatActivityList();
  _recordChatActivity({
    title: isContinuation ? 'Approval reply submitted' : 'User request submitted',
    status: 'running',
    detail: text,
    started_at: _chatRunState.startedAt,
    task: _chatRunState.task || text,
  });
  if (!isContinuation) {
    document.getElementById('chatTitle').textContent = text.substring(0, 40) + (text.length > 40 ? '...' : '');
  }
  createStreamingRow(runId, isContinuation ? (_chatRunState.task || text) : text);

  // Intercept file-download requests: resolve locally without hitting the agent
  if (!isContinuation) {
    const fileReqHtml = _tryHandleFileRequest(text);
    if (fileReqHtml) {
      const resultEl = document.getElementById('stream-result-' + runId);
      if (resultEl) resultEl.innerHTML = '<div style="margin-top:10px;border-top:1px solid var(--border);padding-top:10px">Here are the available report files:</div>' + fileReqHtml;
      finalizeStreamRow(runId, '', '', [], null, null, null, null, 'completed');
      isRunning = false;
      isStopping = false;
      _setChatComposerState();
      return;
    }
  }

  try {
    const resumeDir = _pendingResumeDir;
    _pendingResumeDir = null;
    let endpoint = API + '/api/chat';
    const payload = {
      text,
      channel: 'webchat',
      sender_id: 'ui_user',
      chat_id: chatSessionId,
      run_id: runId,
      workflow_id: workflowId,
      attempt_id: runId,
      working_directory: workingDir
    };
    if (retryRequested && _lastFailedRunContext) {
      const failedResp = await fetch(API + '/api/runs/' + encodeURIComponent(_lastFailedRunContext.runId));
      const failedRun = await failedResp.json();
      const retryResumeDir = _chatResumePathFromRun(failedRun);
      if (!failedResp.ok || !failedRun || !failedRun.run_id || !retryResumeDir) {
        throw new Error('Missing checkpoint for retry');
      }
      endpoint = API + '/api/chat/resume';
      payload.run_id = _lastFailedRunContext.runId;
      payload.workflow_id = _lastFailedRunContext.workflowId || failedRun.workflow_id || workflowId;
      payload.resume_dir = retryResumeDir;
      payload.output_folder = retryResumeDir;
      payload.resume_output_dir = retryResumeDir;
      payload.force = true;
    }
    payload.execution_mode = executionMode;
    if (executionMode === 'plan') {
      payload.planner_mode = 'always';
      payload.auto_approve_plan = false;
    } else if (executionMode === 'direct_tools') {
      payload.planner_mode = 'never';
    }
    if (researchMode === 'deep_research') {
      const webSearchEnabled = !!((document.getElementById('drWebSearch') || {}).checked);
      const localPaths = _allDeepResearchLocalPaths();
      const explicitLinks = webSearchEnabled ? _deepResearchLinks() : [];
      if (!webSearchEnabled && !localPaths.length) {
        finalizeStreamRow(runId, '', 'Deep Research with web search disabled requires at least one local file, uploaded folder, or local path.');
        isRunning = false;
        isStopping = false;
        _setChatComposerState();
        return;
      }
      payload.deep_research_mode = true;
      payload.long_document_mode = true;
      payload.workflow_type = 'deep_research';
      payload.long_document_pages = parseInt((document.getElementById('drPages') || {}).value || '25', 10) || 25;
      payload.research_output_formats = _selectedDeepResearchFormats();
      payload.research_citation_style = ((document.getElementById('drCitation') || {}).value || 'apa');
      payload.research_enable_plagiarism_check = !!((document.getElementById('drPlagiarism') || {}).checked);
      payload.research_web_search_enabled = webSearchEnabled;
      payload.research_date_range = ((document.getElementById('drDateRange') || {}).value || 'all_time');
      payload.research_sources = _selectedDeepResearchSources();
      payload.research_max_sources = parseInt((document.getElementById('drMaxSources') || {}).value || '0', 10) || 0;
      payload.research_checkpoint_enabled = !!((document.getElementById('drCheckpoint') || {}).checked);
      payload.deep_research_source_urls = explicitLinks;
      if (localPaths.length) {
        payload.local_drive_paths = localPaths;
        payload.local_drive_recursive = true;
        payload.local_drive_force_long_document = true;
      }
    }
    if (shellModeActive) {
      payload.shell_auto_approve = true;
      payload.privileged_approval_note = 'Approved via Shell Automation mode in chat UI';
    }
    // Always inject security authorization from the webchat UI (operator-controlled).
    // Explicit Security mode overrides the target URL field; otherwise auto-extract from message.
    {
      const secTarget = securityMode
        ? (((document.getElementById('secTargetUrl') || {}).value || '').trim() || (() => { const m = text.match(/https?:\/\/[^\s]+|(?:^|\s)([\w.-]+\.[a-z]{2,}(?:\/[^\s]*)?)/i); return m ? (m[0] || m[1] || '').trim() : ''; })())
        : (() => { const m = text.match(/https?:\/\/[^\s]+|(?:^|\s)([\w.-]+\.[a-z]{2,}(?:\/[^\s]*)?)/i); return m ? (m[0] || m[1] || '').trim() : ''; })();
      const secNote = ((document.getElementById('secAuthNote') || {}).value || '').trim()
                      || 'Authorized via Web UI (operator session)';
      payload.security_authorized = true;
      if (secTarget) payload.security_target_url = secTarget;
      payload.security_authorization_note = secNote;
    }
    if (resumeDir) {
      endpoint = API + '/api/chat/resume';
      payload.resume_dir = resumeDir;
      if (isContinuation) {
        // Approval replies should take over stale/running candidates after reconnects.
        payload.force = true;
      }
    }
    const resp = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const d = await resp.json();

    if (d.error) {
      _chatRunState.status = 'failed';
      finalizeStreamRow(runId, '', d.error + (d.detail ? ': ' + d.detail : ''));
      isRunning = false;
      isStopping = false;
      _setChatComposerState();
      return;
    }

    if (d.streaming) {
      const streamRunId = d.run_id || runId;
      currentRunId = streamRunId;
      currentWorkflowId = d.workflow_id || currentWorkflowId || workflowId;
      _chatRunState.runId = streamRunId;
      _chatRunState.workflowId = currentWorkflowId;
      _chatRunState.attemptId = d.attempt_id || _chatRunState.attemptId || streamRunId;
      sessionStorage.setItem('kendr_active_run_id', streamRunId);
      if (streamRunId !== runId) {
        if (_runStepJournal[runId]) {
          _runStepJournal[streamRunId] = _runStepJournal[runId];
          delete _runStepJournal[runId];
        }
        if (_runLiveUpdates[runId]) {
          _runLiveUpdates[streamRunId] = _runLiveUpdates[runId];
          delete _runLiveUpdates[runId];
        }
        if (_runTraceFeed[runId]) {
          _runTraceFeed[streamRunId] = _runTraceFeed[runId];
          delete _runTraceFeed[runId];
        }
        if (_runWorkingTimers[runId]) {
          _runWorkingTimers[streamRunId] = _runWorkingTimers[runId];
          delete _runWorkingTimers[runId];
        }
        const row = document.getElementById('stream-row-' + runId);
        if (row) row.id = 'stream-row-' + streamRunId;
        const bubble = document.getElementById('stream-bubble-' + runId);
        if (bubble) bubble.id = 'stream-bubble-' + streamRunId;
        const statusEl = document.getElementById('stream-status-' + runId);
        if (statusEl) statusEl.id = 'stream-status-' + streamRunId;
        const worklog = document.getElementById('run-worklog-' + runId);
        if (worklog) worklog.id = 'run-worklog-' + streamRunId;
        const working = document.getElementById('run-working-' + runId);
        if (working) working.id = 'run-working-' + streamRunId;
        const workItems = document.getElementById('run-work-items-' + runId);
        if (workItems) workItems.id = 'run-work-items-' + streamRunId;
        const trace = document.getElementById('stream-trace-' + runId);
        if (trace) trace.id = 'stream-trace-' + streamRunId;
        const steps = document.getElementById('stream-steps-' + runId);
        if (steps) steps.id = 'stream-steps-' + streamRunId;
        const result = document.getElementById('stream-result-' + runId);
        if (result) result.id = 'stream-result-' + streamRunId;
      }
      if (retryRequested) _lastFailedRunContext = null;
      openEventStream(streamRunId);
    } else {
      const output = d.final_output || d.output || d.draft_response || '(Run completed)';
      finalizeStreamRow(runId, output, '', d.artifact_files || [], d.test_report || null, d.mcp_invocations || null, d.long_document_exports || null, d.deep_research_result_card || null);
      isRunning = false;
      isStopping = false;
      _setChatComposerState();
      loadRuns();
    }
  } catch(err) {
    _chatRunState.status = 'failed';
    finalizeStreamRow(runId, '', 'Request failed: ' + String(err));
    isRunning = false;
    isStopping = false;
    _setChatComposerState();
  }
}

checkGateway();
loadRuns();
loadProjContext();
setResearchMode('auto');
setExecutionMode(executionMode);
renderDeepResearchSourceSummary();
_renderChatInspector();
_setChatComposerState();
window.addEventListener('resize', () => {
  const input = document.getElementById('userInput');
  if (input) autoResize(input);
});
setInterval(checkGateway, 30000);
setInterval(loadRuns, 15000);
setInterval(loadProjContext, 60000);

// ── Reconnect to active run on page load ──────────────────────────────────────
(async () => {
  const savedRunId = sessionStorage.getItem('kendr_active_run_id');
  if (!savedRunId) return;
  try {
    const r = await fetch(API + '/api/runs/' + encodeURIComponent(savedRunId));
    if (!r.ok) { sessionStorage.removeItem('kendr_active_run_id'); return; }
    const run = await r.json();
    if (!run || !run.run_id) { sessionStorage.removeItem('kendr_active_run_id'); return; }
    const status = (run.status || '').toLowerCase();
    if (_isRunActiveStatus(status)) {
      currentRunId = run.run_id;
      _syncChatSessionId(_chatSessionIdFromRun(run));
      currentWorkflowId = run.workflow_id || run.run_id;
      const query = run.user_query || run.query || 'Running…';
      document.getElementById('chatTitle').textContent = query.substring(0, 40) + (query.length > 40 ? '...' : '');
      document.getElementById('clearChatBtn').style.display = '';
      _chatRunState = {
        runId: run.run_id,
        workflowId: run.workflow_id || run.run_id,
        attemptId: run.attempt_id || run.run_id,
        status: 'running',
        title: query.substring(0, 80) + (query.length > 80 ? '…' : ''),
        task: query,
        startedAt: run.created_at || run.started_at || new Date().toISOString(),
        completedAt: '',
        lastCommand: '',
        lastCommandMeta: '',
      };
      _chatPlanState = { total: 0, completed: 0, running: 0, failed: 0 };
      _chatActivityFeed = [];
      _renderChatActivityList();
      _renderChatInspector();
      createStreamingRow(run.run_id, query);
      updateStreamStatus(run.run_id, status === 'cancelling' ? 'Stopping run…' : 'Reconnecting to active run\u2026');
      isRunning = true;
      isStopping = status === 'cancelling';
      _setChatComposerState();
      openEventStream(run.run_id);
    } else if (status === 'awaiting_user_input' || status === 'completed' || status === 'failed' || status === 'cancelled') {
      sessionStorage.removeItem('kendr_active_run_id');
      loadRun(run.run_id);
    } else {
      sessionStorage.removeItem('kendr_active_run_id');
    }
  } catch(e) { sessionStorage.removeItem('kendr_active_run_id'); }
})();
</script>
</body>
</html>"""


_SETUP_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kendr &#x2014; Setup &amp; Config</title>
<style>
:root { --teal: #00C9A7; --amber: #FFB347; --crimson: #FF4757; --blue: #5352ED; --bg: #0d0f14; --surface: #161b22; --surface2: #1e2530; --border: #2a3140; --text: #e6edf3; --muted: #7d8590; --sidebar-w: 280px; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "Segoe UI", system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; }
a { color: var(--teal); }
.sidebar { width: var(--sidebar-w); min-width: var(--sidebar-w); background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; position: fixed; top: 0; bottom: 0; left: 0; }
.sidebar-header { padding: 20px 16px 12px; border-bottom: 1px solid var(--border); }
.logo { font-size: 22px; font-weight: 800; color: var(--teal); }
.logo span { color: var(--amber); }
.tagline { font-size: 11px; color: var(--muted); margin-top: 4px; }
.sidebar-nav { padding: 12px 8px; border-bottom: 1px solid var(--border); display: flex; flex-direction: column; gap: 4px; }
.nav-btn { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-radius: 8px; font-size: 13px; font-weight: 500; color: var(--muted); cursor: pointer; border: none; background: transparent; width: 100%; text-align: left; text-decoration: none; transition: background 0.15s, color 0.15s; }
.nav-btn:hover { background: var(--surface2); color: var(--text); }
.nav-btn.active { background: rgba(0,201,167,0.12); color: var(--teal); }
.nav-btn .icon { font-size: 16px; width: 20px; text-align: center; }
.category-nav { overflow-y: auto; flex: 1; padding: 8px; }
.cat-btn { width: 100%; padding: 8px 12px; background: transparent; border: none; color: var(--muted); font-size: 12px; text-align: left; border-radius: 6px; cursor: pointer; transition: all 0.15s; }
.cat-btn:hover { background: var(--surface2); color: var(--text); }
.cat-btn.active { color: var(--teal); font-weight: 600; }
.main { flex: 1; margin-left: var(--sidebar-w); padding: 32px; max-width: 1100px; }
.page-title { font-size: 26px; font-weight: 700; color: var(--text); }
.page-sub { color: var(--muted); font-size: 14px; margin-top: 6px; margin-bottom: 28px; }
.section-title { font-size: 11px; font-weight: 700; color: var(--muted); letter-spacing: 0.08em; text-transform: uppercase; margin: 28px 0 12px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
.card-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(340px, 1fr)); gap: 16px; }
.int-card { background: var(--surface); border: 1px solid var(--border); border-radius: 14px; padding: 18px; transition: border-color 0.15s; }
.int-card:hover { border-color: var(--blue); }
.int-card.configured { border-color: rgba(0,201,167,0.35); }
.int-card.expanded { border-color: var(--blue); }
.card-header { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; cursor: pointer; }
.card-title-row { flex: 1; }
.card-title { font-size: 15px; font-weight: 600; color: var(--text); }
.card-desc { font-size: 12px; color: var(--muted); margin-top: 4px; line-height: 1.5; }
.card-badges { display: flex; gap: 6px; align-items: center; flex-shrink: 0; }
.badge { display: inline-flex; align-items: center; gap: 4px; padding: 3px 10px; border-radius: 999px; font-size: 11px; font-weight: 600; }
.badge.ok { background: rgba(0,201,167,0.15); color: var(--teal); }
.badge.warn { background: rgba(255,179,71,0.15); color: var(--amber); }
.badge.err { background: rgba(255,71,87,0.15); color: var(--crimson); }
.toggle { width: 38px; height: 22px; border-radius: 11px; background: var(--border); border: none; cursor: pointer; position: relative; flex-shrink: 0; transition: background 0.2s; }
.toggle::after { content: ''; position: absolute; top: 3px; left: 3px; width: 16px; height: 16px; border-radius: 50%; background: #fff; transition: transform 0.2s; }
.toggle.on { background: var(--teal); }
.toggle.on::after { transform: translateX(16px); }
.card-body { margin-top: 16px; display: none; }
.card-body.open { display: block; }
.field-row { margin-bottom: 12px; }
.field-label { font-size: 12px; font-weight: 600; color: var(--text); margin-bottom: 5px; display: flex; align-items: center; gap: 6px; }
.field-desc { font-size: 11px; color: var(--muted); margin-bottom: 5px; }
.secret-badge { font-size: 9px; padding: 1px 5px; border-radius: 3px; background: rgba(255,71,87,0.15); color: var(--crimson); font-weight: 700; }
.required-badge { font-size: 9px; padding: 1px 5px; border-radius: 3px; background: rgba(255,179,71,0.15); color: var(--amber); font-weight: 700; }
.field-input { width: 100%; padding: 9px 12px; background: var(--bg); border: 1px solid var(--border); border-radius: 8px; color: var(--text); font-size: 13px; font-family: monospace; transition: border-color 0.15s; outline: none; }
.field-input:focus { border-color: var(--teal); }
.card-actions { display: flex; gap: 8px; margin-top: 16px; flex-wrap: wrap; align-items: center; }
.btn { padding: 8px 16px; border-radius: 8px; font-size: 13px; font-weight: 600; cursor: pointer; border: none; transition: all 0.15s; }
.btn.primary { background: var(--teal); color: #0d0f14; }
.btn.primary:hover { background: #00b396; }
.btn.secondary { background: var(--surface2); color: var(--text); border: 1px solid var(--border); }
.save-msg { font-size: 12px; padding: 4px 10px; border-radius: 6px; display: inline-flex; align-items: center; }
.save-msg.ok { background: rgba(0,201,167,0.1); color: var(--teal); }
.save-msg.err { background: rgba(255,71,87,0.1); color: var(--crimson); }
.summary-bar { background: var(--surface2); border: 1px solid var(--border); border-radius: 12px; padding: 16px 20px; display: flex; gap: 24px; flex-wrap: wrap; margin-bottom: 28px; }
.summary-stat { text-align: center; }
.stat-val { font-size: 24px; font-weight: 700; }
.stat-val.teal { color: var(--teal); }
.stat-val.amber { color: var(--amber); }
.stat-val.crimson { color: var(--crimson); }
.stat-label { font-size: 11px; color: var(--muted); margin-top: 2px; }
.env-export { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 16px; margin-top: 32px; }
.env-export pre { background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 16px; font-size: 12px; overflow-x: auto; white-space: pre-wrap; max-height: 300px; font-family: monospace; }
::-webkit-scrollbar { width: 6px; } ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
</head>
<body class="mode-agent" data-project-tab="chat">
<div class="sidebar">
  <div class="sidebar-header"><div class="logo">kendr<span>.</span></div><div class="tagline">Multi-agent intelligence runtime</div></div>
  <div class="sidebar-nav">
    <a href="/" class="nav-btn"><span class="icon">&#x1F4AC;</span> Chat</a>
    <a href="/setup" class="nav-btn active"><span class="icon">&#x2699;&#xFE0F;</span> Setup &amp; Config</a>
    <a href="/runs" class="nav-btn"><span class="icon">&#x1F4CB;</span> Run History</a>
    <a href="/skills" class="nav-btn"><span class="icon">&#x1F9E0;</span> Skill Cards</a>
    <a href="/rag" class="nav-btn"><span class="icon">&#x1F52C;</span> Super-RAG</a>
    <a href="/models" class="nav-btn"><span class="icon">&#x1F916;</span> LLM Models</a>
    <a href="/capabilities" class="nav-btn"><span class="icon">&#x2692;&#xFE0F;</span> Capabilities</a>
    <a href="/projects" class="nav-btn"><span class="icon">&#x1F4C1;</span> Projects</a>
    <a href="/docs" class="nav-btn"><span class="icon">&#x1F4D6;</span> Docs</a>
  </div>
  <div class="category-nav" id="categoryNav"></div>
</div>
<div class="main">
  <div class="page-title">Setup &amp; Configuration</div>
  <div class="page-sub">Configure integrations, API keys, and runtime settings. All values are stored locally.</div>
  <div class="summary-bar">
    <div class="summary-stat"><div class="stat-val teal" id="statConfigured">-</div><div class="stat-label">Configured</div></div>
    <div class="summary-stat"><div class="stat-val amber" id="statPartial">-</div><div class="stat-label">Partial</div></div>
    <div class="summary-stat"><div class="stat-val crimson" id="statMissing">-</div><div class="stat-label">Missing</div></div>
    <div class="summary-stat"><div class="stat-val" id="statTotal" style="color:var(--muted)">-</div><div class="stat-label">Total</div></div>
  </div>
  <div id="integrations"></div>
  <div class="env-export">
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:12px">
      <div style="font-size:14px;font-weight:600">Export .env</div>
      <button class="btn secondary" onclick="loadEnvExport()">Refresh</button>
    </div>
    <pre id="envExport">Loading...</pre>
  </div>
</div>
<script>
const API = '';
let allComponents = [];

async function loadSetup() {
  try {
    const r = await fetch(API + '/api/setup/overview');
    const d = await r.json();
    allComponents = d.components || [];
    let configured = 0, partial = 0, missing = 0;
    allComponents.forEach(c => {
      const t = c.total_fields || 0, f = c.filled_fields || 0, d = c.defaulted_fields || 0;
      if (t === 0 || f + d >= t) configured++;
      else if (f > 0 || d > 0) partial++;
      else missing++;
    });
    document.getElementById('statConfigured').textContent = configured;
    document.getElementById('statPartial').textContent = partial;
    document.getElementById('statMissing').textContent = missing;
    document.getElementById('statTotal').textContent = allComponents.length;
    renderCategories(d.categories || {});
    renderIntegrations(allComponents);
  } catch(e) {
    document.getElementById('integrations').innerHTML = '<div style="color:var(--crimson);padding:16px">Failed to load: ' + String(e) + '</div>';
  }
}

function slugify(s) { return s.toLowerCase().replace(/[^a-z0-9]+/g, '-'); }

function renderCategories(categories) {
  const nav = document.getElementById('categoryNav');
  nav.innerHTML = '<div style="padding:10px 12px 4px;font-size:10px;font-weight:700;color:var(--muted);letter-spacing:0.08em;text-transform:uppercase">Categories</div>';
  Object.keys(categories).forEach(cat => {
    const btn = document.createElement('button');
    btn.className = 'cat-btn';
    btn.textContent = cat + ' (' + categories[cat].length + ')';
    btn.onclick = () => { document.querySelectorAll('.cat-btn').forEach(b => b.classList.remove('active')); btn.classList.add('active'); document.getElementById('sec-' + slugify(cat))?.scrollIntoView({ behavior: 'smooth', block: 'start' }); };
    nav.appendChild(btn);
  });
}

function renderIntegrations(components) {
  const byCategory = {};
  components.forEach(c => { const cat = c.category || 'Other'; if (!byCategory[cat]) byCategory[cat] = []; byCategory[cat].push(c); });
  const container = document.getElementById('integrations');
  container.innerHTML = '';
  Object.entries(byCategory).forEach(([cat, comps]) => {
    const section = document.createElement('div');
    section.id = 'sec-' + slugify(cat);
    section.innerHTML = '<div class="section-title">' + esc(cat) + '</div>';
    const grid = document.createElement('div');
    grid.className = 'card-grid';
    comps.forEach(c => grid.appendChild(makeCard(c)));
    section.appendChild(grid);
    container.appendChild(section);
  });
}

function makeCard(comp) {
  const total = comp.total_fields || 0, filled = comp.filled_fields || 0, defaulted = comp.defaulted_fields || 0;
  const isConfigured = total === 0 || filled === total;
  const isDefaulted = !isConfigured && filled + defaulted >= total;
  const isPartial = !isConfigured && !isDefaulted && (filled > 0 || defaulted > 0);
  const enabled = comp.enabled !== false;
  const div = document.createElement('div');
  div.className = 'int-card' + (isConfigured || isDefaulted ? ' configured' : '');
  div.id = 'card-' + comp.id;
  let statusBadge = total === 0 ? '<span class="badge ok">\u2713 Ready</span>' :
    isConfigured ? '<span class="badge ok">\u2713 Configured</span>' :
    isDefaulted ? '<span class="badge ok" title="Using built-in defaults. Override via .env or edit here.">\u2713 Has Defaults</span>' :
    isPartial ? '<span class="badge warn">\u26A1 Partial</span>' :
    '<span class="badge err">\u25CB Not set</span>';
  div.innerHTML = '<div class="card-header" onclick="toggleCard(\'' + esc(comp.id) + '\')">' +
    '<div class="card-title-row"><div class="card-title">' + esc(comp.title) + '</div><div class="card-desc">' + esc(comp.description) + '</div></div>' +
    '<div class="card-badges">' + statusBadge +
    '<button class="toggle ' + (enabled ? 'on' : '') + '" onclick="event.stopPropagation();toggleEnabled(\'' + esc(comp.id) + '\',this)"></button></div></div>' +
    '<div class="card-body" id="body-' + esc(comp.id) + '"></div>';
  return div;
}

async function toggleCard(compId) {
  const body = document.getElementById('body-' + compId);
  if (!body) return;
  const card = document.getElementById('card-' + compId);
  if (body.classList.contains('open')) { body.classList.remove('open'); card.classList.remove('expanded'); return; }
  body.classList.add('open'); card.classList.add('expanded');
  body.innerHTML = '<div style="color:var(--muted);font-size:12px;padding:8px">Loading...</div>';
  try {
    const r = await fetch(API + '/api/setup/component/' + compId);
    const d = await r.json();
    renderCardBody(body, d, compId);
  } catch(e) { body.innerHTML = '<div style="color:var(--crimson);font-size:12px">Failed: ' + String(e) + '</div>'; }
}

function renderCardBody(body, snapshot, compId) {
  const fields = (snapshot.component || {}).fields || [];
  const values = snapshot.values || {};
  const defaults = snapshot.defaults || {};
  const oauthPath = (snapshot.component || {}).oauth_start_path || '';
  let html = '';
  if (fields.length > 0) {
    fields.forEach(f => {
      const val = values[f.key] || '';
      const fieldDefault = f.default || defaults[f.key] || '';
      const type = f.secret ? 'password' : 'text';
      const placeholder = fieldDefault ? 'default: ' + fieldDefault : f.key;
      const defaultHint = (!val && fieldDefault) ? '<span style="font-size:10px;color:var(--teal);opacity:0.7;margin-left:6px">(default: ' + esc(fieldDefault) + ')</span>' : '';
      const badges = [f.secret ? '<span class="secret-badge">SECRET</span>' : '', f.required ? '<span class="required-badge">REQUIRED</span>' : ''].filter(Boolean).join(' ');
      html += '<div class="field-row"><div class="field-label">' + esc(f.label) + defaultHint + ' ' + badges + '</div>' +
        (f.description ? '<div class="field-desc">' + esc(f.description) + '</div>' : '') +
        '<input class="field-input" type="' + type + '" id="fld-' + esc(compId) + '-' + esc(f.key) + '" value="' + esc(val) + '" placeholder="' + esc(placeholder) + '" autocomplete="off"></div>';
    });
  } else {
    html = '<div style="font-size:12px;color:var(--muted);margin-bottom:12px">No configurable fields.</div>';
  }
  let actionsHtml = fields.length > 0 ? '<button class="btn primary" onclick="saveComponent(\'' + esc(compId) + '\')">Save</button>' : '';
  if (oauthPath) {
    actionsHtml += ' <a class="btn oauth" href="' + esc(oauthPath) + '" target="_blank" style="display:inline-flex;align-items:center;gap:6px;padding:7px 14px;border-radius:8px;background:rgba(0,201,167,0.15);border:1px solid rgba(0,201,167,0.4);color:var(--teal);font-size:12px;font-weight:600;text-decoration:none;cursor:pointer">\u{1F517} OAuth Connect</a>';
  }
  const testableComponents = ['github'];
  if (testableComponents.includes(compId)) {
    actionsHtml += ' <button class="btn" id="test-btn-' + esc(compId) + '" onclick="testConnection(\'' + esc(compId) + '\')" style="background:rgba(255,179,71,0.12);border:1px solid rgba(255,179,71,0.4);color:var(--amber)">Test connection</button>';
  }
  actionsHtml += '<span class="save-msg" id="save-msg-' + esc(compId) + '" style="display:none"></span>';
  body.innerHTML = html + '<div class="card-actions">' + actionsHtml + '</div>';
}

async function testConnection(compId) {
  const msg = document.getElementById('save-msg-' + compId);
  const btn = document.getElementById('test-btn-' + compId);
  if (btn) btn.disabled = true;
  try {
    const r = await fetch(API + '/api/setup/test-connection/' + compId);
    const d = await r.json();
    if (msg) {
      msg.style.display = 'inline-flex';
      if (d.ok) {
        msg.className = 'save-msg ok';
        msg.textContent = '\u2713 ' + (d.detail || d.login || 'Connected');
      } else {
        msg.className = 'save-msg err';
        msg.textContent = '\u2717 ' + (d.error || 'Connection failed');
      }
      setTimeout(() => { msg.style.display = 'none'; }, 4000);
    }
  } catch(e) {
    if (msg) { msg.style.display = 'inline-flex'; msg.className = 'save-msg err'; msg.textContent = '\u2717 ' + String(e); }
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function saveComponent(compId) {
  const r = await fetch(API + '/api/setup/component/' + compId).catch(() => null);
  if (!r) return;
  const d = await r.json();
  const fields = (d.component || {}).fields || [];
  const values = {};
  fields.forEach(f => { const el = document.getElementById('fld-' + compId + '-' + f.key); if (el && !(f.secret && el.value === '********')) values[f.key] = el.value; });
  const msg = document.getElementById('save-msg-' + compId);
  try {
    const resp = await fetch(API + '/api/setup/save', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ component_id: compId, values }) });
    const res = await resp.json();
    if (res.error) throw new Error(res.error);
    if (msg) { msg.style.display = 'inline-flex'; msg.className = 'save-msg ok'; msg.textContent = '\u2713 Saved'; setTimeout(() => { msg.style.display = 'none'; }, 2500); }
    loadSetup();
  } catch(e) { if (msg) { msg.style.display = 'inline-flex'; msg.className = 'save-msg err'; msg.textContent = '\u2717 ' + String(e); } }
}

async function toggleEnabled(compId, btn) {
  const newState = !btn.classList.contains('on');
  try {
    await fetch(API + '/api/setup/enabled', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ component_id: compId, enabled: newState }) });
    btn.classList.toggle('on', newState);
  } catch(e) { alert('Failed: ' + e); }
}

async function loadEnvExport() {
  try {
    const r = await fetch(API + '/api/setup/env-export');
    const d = await r.json();
    document.getElementById('envExport').textContent = (d.lines || []).join('\n') || '# No configuration stored yet.';
  } catch(e) { document.getElementById('envExport').textContent = '# Error: ' + e; }
}

function esc(s) { return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
loadSetup();
loadEnvExport();
</script>
</body>
</html>"""


_PROJECTS_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kendr &mdash; Projects</title>
<style>
:root { --teal: #00C9A7; --amber: #FFB347; --crimson: #FF4757; --purple: #A78BFA; --blue: #58A6FF; --bg: #0d0f14; --surface: #161b22; --surface2: #1e2530; --surface3: #252d3a; --border: #2a3140; --text: #e6edf3; --muted: #7d8590; --sidebar-w: 220px; --file-w: 260px; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "Segoe UI", system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; overflow: hidden; height: 100vh; }
/* Left nav sidebar */
.nav-sidebar { width: var(--sidebar-w); min-width: var(--sidebar-w); background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; position: fixed; top: 0; bottom: 0; left: 0; z-index: 10; }
.nav-header { padding: 20px 16px 12px; border-bottom: 1px solid var(--border); }
.logo { font-size: 20px; font-weight: 800; color: var(--teal); }
.logo span { color: var(--amber); }
.tagline { font-size: 11px; color: var(--muted); margin-top: 3px; }
.nav-links { padding: 10px 8px; display: flex; flex-direction: column; gap: 3px; border-bottom: 1px solid var(--border); }
.nav-btn { display: flex; align-items: center; gap: 9px; padding: 8px 11px; border-radius: 7px; font-size: 13px; font-weight: 500; color: var(--muted); cursor: pointer; border: none; background: transparent; width: 100%; text-align: left; text-decoration: none; transition: background 0.15s, color 0.15s; }
.nav-btn:hover { background: var(--surface2); color: var(--text); }
.nav-btn.active { background: rgba(0,201,167,0.12); color: var(--teal); }
.nav-btn .icon { font-size: 15px; width: 18px; text-align: center; }
/* Project list in nav */
.proj-list-nav { padding: 8px; flex: 1; overflow-y: auto; }
.proj-list-label { font-size: 10px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; padding: 6px 8px 4px; }
.proj-item { display: flex; align-items: center; gap: 7px; padding: 7px 10px; border-radius: 7px; cursor: pointer; font-size: 12px; color: var(--muted); transition: background 0.12s, color 0.12s; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.proj-item:hover { background: var(--surface2); color: var(--text); }
.proj-item.active { background: rgba(0,201,167,0.1); color: var(--teal); }
.proj-add-btn { display: flex; align-items: center; gap: 6px; padding: 7px 10px; font-size: 12px; color: var(--muted); cursor: pointer; border-radius: 7px; border: 1px dashed var(--border); margin: 6px 8px; background: none; width: calc(100% - 16px); transition: color 0.12s, border-color 0.12s; }
.proj-add-btn:hover { color: var(--teal); border-color: var(--teal); }
/* File panel */
.file-panel { width: var(--file-w); min-width: var(--file-w); background: var(--surface); border-right: 1px solid var(--border); position: fixed; top: 0; bottom: 0; left: var(--sidebar-w); display: flex; flex-direction: column; }
.file-panel-header { padding: 14px 14px 10px; border-bottom: 1px solid var(--border); display: flex; align-items: center; gap: 8px; }
.file-panel-title { font-size: 12px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.file-tree { flex: 1; overflow-y: auto; padding: 6px 0; }
.tree-node { cursor: pointer; user-select: none; }
.tree-row { display: flex; align-items: center; gap: 5px; padding: 3px 12px; font-size: 12px; color: var(--muted); transition: background 0.1s, color 0.1s; white-space: nowrap; overflow: hidden; }
.tree-row:hover { background: var(--surface2); color: var(--text); }
.tree-row.selected { background: rgba(0,201,167,0.08); color: var(--teal); }
.tree-row .icon { font-size: 12px; width: 14px; text-align: center; flex-shrink: 0; }
.tree-row .fname { overflow: hidden; text-overflow: ellipsis; }
.tree-children { padding-left: 14px; }
/* Main workspace */
.workspace { margin-left: calc(var(--sidebar-w) + var(--file-w)); flex: 1; display: flex; flex-direction: column; height: 100vh; overflow: hidden; }
.workspace-top { background: var(--surface); border-bottom: 1px solid var(--border); padding: 0 20px; display: flex; align-items: center; gap: 16px; min-height: 48px; }
.ws-title { font-size: 14px; font-weight: 600; flex: 1; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.ws-badge { display: inline-flex; align-items: center; gap: 5px; font-size: 11px; color: var(--muted); background: var(--surface2); border: 1px solid var(--border); border-radius: 5px; padding: 3px 8px; }
/* Tabs */
.tab-bar { display: flex; border-bottom: 1px solid var(--border); background: var(--surface); }
.tab { padding: 10px 20px; font-size: 13px; font-weight: 500; color: var(--muted); cursor: pointer; border-bottom: 2px solid transparent; transition: color 0.15s, border-color 0.15s; }
.tab:hover { color: var(--text); }
.tab.active { color: var(--teal); border-bottom-color: var(--teal); }
.tab-panels { flex: 1; overflow: hidden; }
.tab-panel { display: none; height: 100%; flex-direction: column; overflow: hidden; }
.tab-panel.active { display: flex; }
/* Chat panel */
.chat-messages { flex: 1; overflow-y: auto; padding: 16px 20px; display: flex; flex-direction: column; gap: 12px; }
.msg-row { display: flex; gap: 10px; }
.msg-row.user { flex-direction: row-reverse; }
.msg-bubble { max-width: 75%; padding: 10px 14px; border-radius: 12px; font-size: 13px; line-height: 1.55; word-break: break-word; overflow-wrap: anywhere; }
.msg-row.user .msg-bubble { background: rgba(0,201,167,0.15); border: 1px solid rgba(0,201,167,0.3); color: var(--text); border-radius: 12px 12px 3px 12px; }
.msg-row.agent .msg-bubble { background: var(--surface2); border: 1px solid var(--border); color: var(--text); border-radius: 12px 12px 12px 3px; }
.msg-row.system .msg-bubble { background: var(--surface3); border: 1px solid var(--border); color: var(--muted); font-size: 12px; font-style: italic; border-radius: 8px; }
.msg-bubble .plain-text { white-space: pre-wrap; }
.msg-bubble .markdown-body { display: block; }
.msg-bubble .markdown-body > :first-child { margin-top: 0; }
.msg-bubble .markdown-body > :last-child { margin-bottom: 0; }
.msg-bubble .markdown-body h1,
.msg-bubble .markdown-body h2,
.msg-bubble .markdown-body h3,
.msg-bubble .markdown-body h4,
.msg-bubble .markdown-body h5,
.msg-bubble .markdown-body h6 { margin: 0 0 10px; font-size: 14px; line-height: 1.35; }
.msg-bubble .markdown-body p { margin: 0 0 10px; }
.msg-bubble .markdown-body ul,
.msg-bubble .markdown-body ol { margin: 0 0 10px 18px; padding: 0; }
.msg-bubble .markdown-body li { margin: 0 0 4px; }
.msg-bubble .markdown-body blockquote { margin: 0 0 10px; padding: 0 0 0 12px; border-left: 3px solid rgba(88,166,255,0.35); color: #c8d3e0; }
.msg-bubble .markdown-body code { font-family: "Cascadia Code","Fira Code",monospace; font-size: 12px; background: rgba(10,12,16,0.55); border: 1px solid rgba(255,255,255,0.05); border-radius: 6px; padding: 1px 5px; }
.msg-bubble .markdown-body pre { margin: 0 0 10px; background: #0a0c10; border: 1px solid var(--border); border-radius: 8px; padding: 10px 12px; overflow: auto; }
.msg-bubble .markdown-body pre code { background: transparent; border: none; border-radius: 0; padding: 0; display: block; white-space: pre; }
.msg-bubble .markdown-body a { color: #7ed3ff; text-decoration: none; }
.msg-bubble .markdown-body a:hover { text-decoration: underline; }
.msg-bubble .markdown-body hr { border: none; border-top: 1px solid rgba(255,255,255,0.08); margin: 10px 0; }
.chat-input-bar { padding: 10px 20px; border-top: 1px solid var(--border); display: flex; flex-direction: column; gap: 8px; background: var(--surface); }
.chat-input-row { display: flex; gap: 10px; align-items: flex-end; }
.chat-input { flex: 1; background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 9px 13px; color: var(--text); font-size: 13px; outline: none; resize: none; min-height: 40px; max-height: 120px; font-family: inherit; transition: border-color 0.15s; }
.chat-input:focus { border-color: var(--teal); }
.chat-bar-meta { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.chat-mode-group { display: inline-flex; align-items: center; gap: 4px; padding: 3px; border-radius: 9px; border: 1px solid var(--border); background: var(--surface2); }
.chat-mode-chip { padding: 5px 9px; border: 1px solid transparent; border-radius: 7px; background: transparent; color: var(--muted); font-size: 11px; font-weight: 700; cursor: pointer; transition: background 0.15s, color 0.15s, border-color 0.15s; }
.chat-mode-chip:hover { color: var(--text); }
.chat-mode-chip.active { background: rgba(0,201,167,0.12); border-color: rgba(0,201,167,0.3); color: var(--teal); }
.chat-toggle-chip { display: inline-flex; align-items: center; gap: 6px; padding: 5px 9px; border-radius: 8px; border: 1px solid var(--border); background: var(--surface2); color: var(--muted); font-size: 11px; font-weight: 600; cursor: pointer; user-select: none; transition: border-color 0.15s, color 0.15s, background 0.15s; }
.chat-toggle-chip input { margin: 0; accent-color: var(--amber); }
.chat-toggle-chip.active { border-color: rgba(255,179,71,0.35); color: var(--amber); background: rgba(255,179,71,0.08); }
.chat-toggle-chip.danger input { accent-color: var(--crimson); }
.chat-toggle-chip.danger.active { border-color: rgba(255,71,87,0.35); color: var(--crimson); background: rgba(255,71,87,0.08); }
.chat-mode-note { font-size: 11px; color: var(--muted); flex: 1 1 240px; min-width: 220px; }
.chat-model-select { background: var(--surface2); border: 1px solid var(--border); color: var(--text); border-radius: 6px; padding: 3px 8px; font-size: 11px; cursor: pointer; outline: none; max-width: 180px; }
.chat-model-select:focus { border-color: var(--teal); }
.ctx-badge { font-size: 10px; color: var(--muted); display: flex; align-items: center; gap: 5px; }
.ctx-bar-wrap { width: 60px; height: 4px; background: var(--border); border-radius: 2px; overflow: hidden; }
.ctx-bar-fill { height: 100%; background: var(--teal); border-radius: 2px; transition: width 0.4s; }
.attach-btn { background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 8px 10px; font-size: 15px; cursor: pointer; color: var(--muted); transition: color 0.15s, border-color 0.15s; flex-shrink: 0; line-height: 1; }
.attach-btn:hover { color: var(--text); border-color: var(--teal); }
.chat-attach-chips { display: flex; flex-wrap: wrap; gap: 6px; padding: 0 0 4px 0; min-height: 0; }
.chat-attach-chip { display: inline-flex; align-items: center; gap: 5px; background: rgba(0,201,167,0.1); border: 1px solid rgba(0,201,167,0.25); border-radius: 6px; padding: 3px 8px; font-size: 11px; color: var(--teal); }
.chat-attach-chip button { background: none; border: none; color: var(--muted); cursor: pointer; font-size: 12px; line-height: 1; padding: 0 0 0 3px; }
.chat-attach-chip button:hover { color: var(--crimson); }
.ctx-bar-fill.warn { background: var(--amber); }
.ctx-bar-fill.full { background: var(--crimson); }
.msg-ctx { font-size: 10px; color: var(--muted); margin-top: 4px; display: flex; align-items: center; gap: 6px; }
.send-btn { background: var(--teal); color: #0d0f14; border: none; border-radius: 8px; padding: 9px 16px; font-size: 13px; font-weight: 700; cursor: pointer; }
.send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
/* Terminal panel */
.terminal-output { flex: 1; overflow-y: auto; padding: 12px 16px; background: #0a0c10; font-family: "Cascadia Code","Fira Code",monospace; font-size: 12px; color: #b5c4de; white-space: pre-wrap; word-break: break-word; }
.terminal-output .cmd-line { color: var(--teal); margin-top: 8px; }
.terminal-output .err-line { color: var(--crimson); }
.terminal-input-bar { padding: 10px 12px; background: #0a0c10; border-top: 1px solid var(--border); display: flex; align-items: center; gap: 8px; }
.terminal-prompt { color: var(--teal); font-family: monospace; font-size: 13px; flex-shrink: 0; }
.terminal-input { flex: 1; background: transparent; border: none; color: var(--text); font-family: "Cascadia Code","Fira Code",monospace; font-size: 13px; outline: none; }
.service-panel { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 16px; }
.service-section { background: var(--surface2); border: 1px solid var(--border); border-radius: 9px; padding: 14px 16px; }
.service-form-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px 12px; }
.service-meta { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
.service-pill { display: inline-flex; align-items: center; gap: 5px; padding: 3px 8px; border-radius: 999px; font-size: 11px; border: 1px solid var(--border); background: var(--surface); color: var(--muted); }
.service-pill.running { color: var(--teal); border-color: rgba(0,201,167,0.35); }
.service-pill.stopped { color: var(--amber); border-color: rgba(255,179,71,0.35); }
.service-pill.degraded { color: var(--crimson); border-color: rgba(255,71,87,0.35); }
.service-command { font-family: "Cascadia Code","Fira Code",monospace; font-size: 12px; background: var(--surface); border: 1px solid var(--border); border-radius: 7px; padding: 8px 10px; color: var(--text); white-space: pre-wrap; word-break: break-word; margin-top: 10px; }
.service-log { background: #0a0c10; border: 1px solid var(--border); border-radius: 8px; min-height: 180px; max-height: 320px; overflow: auto; padding: 12px; font-family: "Cascadia Code","Fira Code",monospace; font-size: 12px; color: #b5c4de; white-space: pre-wrap; word-break: break-word; }
.service-empty { color: var(--muted); font-size: 13px; }
/* Git panel */
.git-panel { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 16px; }
.git-section { background: var(--surface2); border: 1px solid var(--border); border-radius: 9px; padding: 14px 16px; }
.git-section-title { font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 10px; }
.git-info-row { display: flex; align-items: center; gap: 8px; font-size: 13px; margin-bottom: 6px; }
.git-info-label { color: var(--muted); font-size: 12px; min-width: 80px; }
.git-info-val { font-family: monospace; font-size: 12px; color: var(--text); }
.file-badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-family: monospace; margin: 2px 4px 2px 0; }
.file-badge.changed { background: rgba(255,179,71,0.12); color: var(--amber); }
.file-badge.staged { background: rgba(0,201,167,0.1); color: var(--teal); }
.file-badge.untracked { background: rgba(125,133,144,0.12); color: var(--muted); }
.git-commit-area { display: flex; flex-direction: column; gap: 10px; }
.git-msg-input { background: var(--surface); border: 1px solid var(--border); border-radius: 7px; padding: 9px 12px; color: var(--text); font-size: 13px; outline: none; resize: none; min-height: 60px; font-family: inherit; transition: border-color 0.15s; width: 100%; }
.git-msg-input:focus { border-color: var(--teal); }
.git-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.btn { padding: 8px 15px; border-radius: 7px; font-size: 12px; font-weight: 600; cursor: pointer; border: none; transition: opacity 0.15s; }
.btn:hover { opacity: 0.85; }
.btn:disabled { opacity: 0.4; cursor: not-allowed; }
.btn-primary { background: var(--teal); color: #0d0f14; }
.btn-outline { background: none; border: 1px solid var(--border); color: var(--text); }
.btn-danger { background: rgba(255,71,87,0.1); border: 1px solid rgba(255,71,87,0.3); color: var(--crimson); }
.btn-purple { background: rgba(167,139,250,0.12); border: 1px solid rgba(167,139,250,0.3); color: var(--purple); }
.git-output { font-family: monospace; font-size: 12px; color: var(--muted); background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; white-space: pre-wrap; max-height: 120px; overflow-y: auto; display: none; }
.git-output.show { display: block; }
/* File viewer (inside chat or modal) */
.file-viewer { flex: 1; overflow: auto; padding: 16px 20px; background: #0a0c10; }
.file-viewer pre { font-family: "Cascadia Code","Fira Code",monospace; font-size: 12px; color: #b5c4de; white-space: pre; }
.file-viewer-header { padding: 10px 20px; background: var(--surface); border-bottom: 1px solid var(--border); font-size: 12px; color: var(--muted); display: flex; align-items: center; gap: 10px; }
.file-viewer-header .fpath { font-family: monospace; color: var(--teal); }
/* Modals */
.modal-overlay { position: fixed; inset: 0; background: rgba(0,0,0,0.55); display: flex; align-items: center; justify-content: center; z-index: 100; display: none; }
.modal-overlay.open { display: flex; }
.modal { background: var(--surface); border: 1px solid var(--border); border-radius: 12px; padding: 24px; width: 460px; max-width: 95vw; }
.modal-title { font-size: 16px; font-weight: 700; margin-bottom: 16px; }
.form-field { margin-bottom: 14px; }
.form-field label { display: block; font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 5px; }
.form-field input, .form-field select, .form-field textarea { width: 100%; background: var(--surface2); border: 1px solid var(--border); border-radius: 7px; padding: 9px 12px; color: var(--text); font-size: 13px; outline: none; transition: border-color 0.15s; font-family: inherit; }
.form-field textarea { min-height: 84px; resize: vertical; }
.form-field input:focus, .form-field select:focus, .form-field textarea:focus { border-color: var(--teal); }
.modal-actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 16px; }
.approval-overlay { display:none; position:fixed; inset:0; background:rgba(0,0,0,0.72); z-index:2400; align-items:center; justify-content:center; padding:20px; overflow:auto; }
.approval-overlay.open { display:flex; }
.approval-box { width:min(560px, 100%); max-height:min(84vh, 920px); display:flex; flex-direction:column; background:var(--surface); border:1px solid var(--border); border-radius:16px; box-shadow:0 24px 60px rgba(0,0,0,.45); overflow:hidden; }
.approval-head { display:flex; align-items:center; justify-content:space-between; gap:12px; padding:18px 20px 14px; border-bottom:1px solid var(--border); }
.approval-title { font-size:15px; font-weight:700; color:var(--text); }
.approval-subtitle { font-size:11px; color:var(--muted); margin-top:4px; }
.approval-close { background:none; border:none; color:var(--muted); font-size:20px; cursor:pointer; line-height:1; }
.approval-body { padding:18px 20px; overflow-y:auto; min-height:0; }
.approval-scope-pill { display:inline-flex; align-items:center; gap:6px; padding:4px 9px; border-radius:999px; background:rgba(83,82,237,.14); border:1px solid rgba(83,82,237,.35); color:#b8b7ff; font-size:11px; font-weight:700; text-transform:uppercase; letter-spacing:.05em; }
.approval-copy { margin-top:12px; font-size:13px; color:var(--text); line-height:1.6; white-space:pre-wrap; }
.approval-hint { margin-top:10px; font-size:12px; color:var(--muted); line-height:1.5; }
.approval-suggest-wrap { display:none; margin-top:14px; }
.approval-suggest-wrap.open { display:block; }
.approval-suggest-wrap textarea { width:100%; min-height:100px; resize:vertical; background:var(--surface2); border:1px solid var(--border); border-radius:12px; color:var(--text); font:inherit; padding:12px 14px; line-height:1.5; }
.approval-suggest-wrap textarea:focus { outline:none; border-color:var(--teal); }
.approval-actions-row { display:flex; flex-wrap:wrap; gap:10px; margin-top:16px; }
.approval-action-btn { border:none; border-radius:10px; padding:10px 16px; font-size:13px; font-weight:700; cursor:pointer; transition:opacity .15s, transform .15s; }
.approval-action-btn:hover { opacity:.92; transform:translateY(-1px); }
.approval-action-btn.accept { background:var(--teal); color:#071411; }
.approval-action-btn.reject { background:rgba(255,71,87,.16); border:1px solid rgba(255,71,87,.35); color:var(--crimson); }
.approval-action-btn.suggest { background:rgba(83,82,237,.16); border:1px solid rgba(83,82,237,.35); color:#b8b7ff; }
.approval-action-btn.submit { background:rgba(255,255,255,.08); border:1px solid var(--border); color:var(--text); }
.status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.status-dot.green { background: var(--teal); }
.status-dot.amber { background: var(--amber); }
.status-dot.red { background: var(--crimson); }
.spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--border); border-top-color: var(--teal); border-radius: 50%; animation: spin 0.7s linear infinite; vertical-align: middle; }
@keyframes spin { to { transform: rotate(360deg); } }
::-webkit-scrollbar { width: 5px; height: 5px; } ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
/* IDE workbench overrides */
:root { --activity-w: 56px; --inspector-w: 320px; --statusbar-h: 28px; }
body { background:
  radial-gradient(circle at top left, rgba(88,166,255,0.11), transparent 26%),
  radial-gradient(circle at top right, rgba(0,201,167,0.10), transparent 22%),
  linear-gradient(180deg, rgba(255,255,255,0.02), transparent 16%),
  var(--bg);
}
body.mode-agent { --file-w: 276px; --inspector-w: 320px; }
body.mode-code { --file-w: 340px; --inspector-w: 0px; }
.activity-rail { position: fixed; top: 0; bottom: 0; left: var(--sidebar-w); width: var(--activity-w); background: #11161e; border-right: 1px solid var(--border); display: flex; flex-direction: column; align-items: center; gap: 8px; padding: 76px 8px 12px; z-index: 9; }
.activity-btn { width: 40px; height: 40px; border-radius: 10px; border: 1px solid transparent; background: transparent; color: var(--muted); cursor: pointer; display: inline-flex; align-items: center; justify-content: center; font-size: 17px; transition: background 0.15s, color 0.15s, border-color 0.15s, transform 0.15s; }
.activity-btn:hover { background: var(--surface2); color: var(--text); transform: translateY(-1px); }
.activity-btn.active { color: var(--text); background: rgba(88,166,255,0.12); border-color: rgba(88,166,255,0.28); box-shadow: inset 0 1px 0 rgba(255,255,255,0.06); }
.activity-spacer { flex: 1; }
.file-panel { left: calc(var(--sidebar-w) + var(--activity-w)); width: var(--file-w); background: linear-gradient(180deg, rgba(255,255,255,0.03), transparent 30%), var(--surface); transition: width 0.25s ease, left 0.25s ease; }
.file-panel-header { flex-direction: column; align-items: flex-start; gap: 4px; padding-bottom: 12px; }
.file-panel-subtitle { font-size: 11px; color: var(--muted); }
.agent-lens-card { margin: 12px; padding: 14px; border-radius: 14px; border: 1px solid rgba(88,166,255,0.18); background: linear-gradient(145deg, rgba(88,166,255,0.13), rgba(0,201,167,0.08)); display: flex; flex-direction: column; gap: 10px; box-shadow: inset 0 1px 0 rgba(255,255,255,0.04); }
.agent-lens-top { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
.agent-lens-title { font-size: 12px; font-weight: 700; letter-spacing: 0.05em; text-transform: uppercase; color: #dbe9ff; }
.agent-lens-mode { font-size: 10px; color: var(--teal); border: 1px solid rgba(0,201,167,0.25); background: rgba(0,0,0,0.18); border-radius: 999px; padding: 3px 7px; }
.agent-lens-copy { font-size: 12px; line-height: 1.55; color: rgba(230,237,243,0.92); }
.agent-lens-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.mini-btn { padding: 6px 10px; border-radius: 8px; border: 1px solid rgba(255,255,255,0.1); background: rgba(10,12,16,0.24); color: var(--text); font-size: 11px; font-weight: 600; cursor: pointer; transition: border-color 0.15s, background 0.15s; }
.mini-btn:hover { border-color: rgba(0,201,167,0.32); background: rgba(0,0,0,0.26); }
.side-section-label { padding: 0 14px 8px; font-size: 10px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.08em; }
body.mode-code .agent-lens-card { display: none; }
.workspace { margin-left: calc(var(--sidebar-w) + var(--activity-w) + var(--file-w)); margin-right: var(--inspector-w); padding-bottom: var(--statusbar-h); transition: margin 0.25s ease; }
.workspace-top { min-height: 68px; padding: 12px 20px; align-items: center; justify-content: space-between; flex-wrap: wrap; gap: 12px; background: linear-gradient(180deg, rgba(255,255,255,0.04), transparent), var(--surface); }
.workspace-top-left, .workspace-top-right { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; }
.workspace-top-left { min-width: 0; flex: 1; align-items: flex-start; flex-direction: column; gap: 4px; }
.ws-eyebrow { font-size: 10px; font-weight: 700; color: var(--muted); letter-spacing: 0.1em; text-transform: uppercase; }
.mode-switch { display: inline-flex; align-items: center; gap: 4px; padding: 4px; border-radius: 12px; border: 1px solid var(--border); background: var(--surface2); }
.mode-chip { padding: 7px 11px; border-radius: 9px; background: transparent; border: none; color: var(--muted); font-size: 12px; font-weight: 700; cursor: pointer; transition: background 0.15s, color 0.15s; }
.mode-chip.active { background: #0f141b; color: var(--text); box-shadow: inset 0 1px 0 rgba(255,255,255,0.04); }
.mode-chip:hover { color: var(--text); }
.command-bar { min-height: 46px; padding: 8px 20px; display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; border-bottom: 1px solid var(--border); background: #10151c; }
.command-track { font-size: 12px; color: var(--muted); flex: 1; min-width: 220px; }
.command-actions { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.command-pill { padding: 7px 11px; border-radius: 999px; border: 1px solid var(--border); background: var(--surface2); color: var(--text); font-size: 11px; font-weight: 700; cursor: pointer; transition: border-color 0.15s, color 0.15s, transform 0.15s; }
.command-pill:hover { border-color: rgba(88,166,255,0.35); transform: translateY(-1px); }
.tab-bar { padding: 0 10px; gap: 6px; background: #10151c; }
.tab { padding: 11px 14px; border-radius: 10px 10px 0 0; border: 1px solid transparent; border-bottom: none; }
.tab.active { color: var(--text); border-color: var(--border); background: var(--surface2); }
.tab-panels { background: var(--surface); }
body[data-project-tab="chat"] .command-bar { background: linear-gradient(90deg, rgba(0,201,167,0.12), rgba(16,21,28,0.98) 34%, #10151c 100%); }
body[data-project-tab="chat"] .workspace-top { box-shadow: inset 0 -2px 0 rgba(0,201,167,0.16); }
body[data-project-tab="file"] .command-bar { background: linear-gradient(90deg, rgba(88,166,255,0.12), rgba(16,21,28,0.98) 34%, #10151c 100%); }
body[data-project-tab="file"] .workspace-top { box-shadow: inset 0 -2px 0 rgba(88,166,255,0.18); }
body[data-project-tab="terminal"] .command-bar { background: linear-gradient(90deg, rgba(21,28,37,0.98), rgba(10,12,16,0.98) 45%, #0a0c10 100%); }
body[data-project-tab="terminal"] .tab-panels { background: #0a0c10; }
body[data-project-tab="services"] .command-bar { background: linear-gradient(90deg, rgba(0,201,167,0.08), rgba(255,179,71,0.08), #10151c 70%); }
body[data-project-tab="services"] .workspace-top { box-shadow: inset 0 -2px 0 rgba(255,179,71,0.18); }
body[data-project-tab="git"] .command-bar { background: linear-gradient(90deg, rgba(255,179,71,0.10), rgba(16,21,28,0.98) 34%, #10151c 100%); }
body[data-project-tab="git"] .workspace-top { box-shadow: inset 0 -2px 0 rgba(255,179,71,0.2); }
.inspector-panel { position: fixed; top: 0; right: 0; bottom: 0; width: var(--inspector-w); background: linear-gradient(180deg, rgba(255,255,255,0.03), transparent 18%), #10151c; border-left: 1px solid var(--border); padding: 16px; display: flex; flex-direction: column; gap: 12px; overflow-y: auto; transition: width 0.25s ease, opacity 0.25s ease, transform 0.25s ease; }
body.mode-code .inspector-panel { opacity: 0; pointer-events: none; transform: translateX(18px); }
.inspector-header { padding: 6px 2px 4px; }
.inspector-title { font-size: 13px; font-weight: 700; color: var(--text); }
.inspector-sub { font-size: 11px; color: var(--muted); margin-top: 3px; line-height: 1.45; }
.inspector-card { border-radius: 14px; border: 1px solid var(--border); background: var(--surface); padding: 14px; display: flex; flex-direction: column; gap: 10px; }
.inspector-card-label { font-size: 10px; font-weight: 700; color: var(--muted); letter-spacing: 0.08em; text-transform: uppercase; }
.inspector-card-title { font-size: 14px; font-weight: 700; color: var(--text); }
.inspector-copy { font-size: 12px; line-height: 1.55; color: var(--muted); }
.inspector-stat-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.inspector-stat { padding: 10px; border-radius: 10px; background: var(--surface2); border: 1px solid rgba(255,255,255,0.04); }
.inspector-stat span { display: block; font-size: 10px; color: var(--muted); text-transform: uppercase; letter-spacing: 0.05em; }
.inspector-stat strong { display: block; font-size: 13px; color: var(--text); margin-top: 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.inspector-actions { display: flex; flex-wrap: wrap; gap: 8px; }
.inspector-list { display: flex; flex-direction: column; gap: 8px; }
.inspector-item { display: flex; align-items: center; justify-content: space-between; gap: 10px; padding: 10px; border-radius: 10px; background: var(--surface2); border: 1px solid rgba(255,255,255,0.04); }
.inspector-item-main { min-width: 0; }
.inspector-item-title { font-size: 12px; font-weight: 700; color: var(--text); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.inspector-item-sub { font-size: 10px; color: var(--muted); margin-top: 3px; }
.inspector-item-status { font-size: 10px; font-weight: 700; padding: 3px 7px; border-radius: 999px; }
.inspector-item-status.running { color: var(--teal); background: rgba(0,201,167,0.12); }
.inspector-item-status.stopped { color: var(--amber); background: rgba(255,179,71,0.12); }
.inspector-item-status.degraded { color: var(--crimson); background: rgba(255,71,87,0.12); }
.inspector-item-status.completed { color: var(--teal); background: rgba(0,201,167,0.12); }
.inspector-item-status.failed { color: var(--crimson); background: rgba(255,71,87,0.12); }
.inspector-item-status.pending, .inspector-item-status.queued, .inspector-item-status.info { color: var(--muted); background: rgba(255,255,255,0.06); }
.inspector-activity-card { padding: 10px 11px; border-radius: 10px; background: var(--surface2); border: 1px solid rgba(255,255,255,0.05); }
.inspector-activity-title { font-size: 12px; font-weight: 700; color: var(--text); }
.inspector-activity-meta { font-size: 10px; color: var(--muted); margin-top: 4px; line-height: 1.45; }
.inspector-activity-detail { font-size: 11px; color: var(--muted); margin-top: 6px; line-height: 1.45; white-space: pre-wrap; word-break: break-word; }
.inspector-activity-command { margin-top: 6px; padding: 8px 9px; border-radius: 8px; border: 1px solid var(--border); background: rgba(0,0,0,0.16); font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 11px; color: #d7e3ff; white-space: pre-wrap; word-break: break-word; }
.trace-card { margin-top: 10px; padding: 11px 12px; border-radius: 10px; border: 1px solid rgba(88,166,255,0.18); background: rgba(88,166,255,0.06); }
.trace-card-title { font-size: 11px; font-weight: 700; color: #dbe9ff; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 8px; }
.inspector-empty { font-size: 12px; color: var(--muted); line-height: 1.5; }
.status-bar { height: var(--statusbar-h); display: flex; align-items: center; gap: 14px; padding: 0 12px; background: linear-gradient(90deg, #096d87, #0a7f92 38%, #0e639c 100%); color: #eef9ff; font-size: 11px; border-top: 1px solid rgba(255,255,255,0.08); }
.status-pill { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.status-pill strong { font-weight: 800; letter-spacing: 0.04em; }
@media (max-width: 1220px) {
  body { --inspector-w: 0px; }
  .inspector-panel { display: none; }
  .workspace { margin-right: 0; }
}
@media (max-width: 980px) {
  .activity-rail { display: none; }
  .file-panel { left: var(--sidebar-w); }
  .workspace { margin-left: calc(var(--sidebar-w) + var(--file-w)); }
}
@media (max-width: 760px) {
  body { --sidebar-w: 72px; --file-w: 0px; }
  .tagline, .proj-list-nav, .file-panel, .activity-rail { display: none; }
  .nav-sidebar { width: var(--sidebar-w); min-width: var(--sidebar-w); }
  .nav-header { padding: 16px 10px 12px; }
  .nav-btn { font-size: 0; justify-content: center; padding: 10px 0; }
  .nav-btn .icon { width: auto; font-size: 17px; }
  .workspace { margin-left: var(--sidebar-w); }
  .workspace-top, .command-bar { padding-left: 14px; padding-right: 14px; }
  .tab-bar { overflow-x: auto; }
  .status-bar { padding-left: 10px; padding-right: 10px; gap: 10px; overflow-x: auto; }
}
</style>
</head>
<body>

<!-- Left nav sidebar -->
<div class="nav-sidebar">
  <div class="nav-header"><div class="logo">kendr<span>.</span></div><div class="tagline">Multi-agent intelligence runtime</div></div>
  <div class="nav-links">
    <a href="/" class="nav-btn"><span class="icon">&#x1F4AC;</span> Chat</a>
    <a href="/setup" class="nav-btn"><span class="icon">&#x2699;&#xFE0F;</span> Setup &amp; Config</a>
    <a href="/runs" class="nav-btn"><span class="icon">&#x1F4CB;</span> Run History</a>
    <a href="/skills" class="nav-btn"><span class="icon">&#x1F9E0;</span> Skill Cards</a>
    <a href="/rag" class="nav-btn"><span class="icon">&#x1F52C;</span> Super-RAG</a>
    <a href="/models" class="nav-btn"><span class="icon">&#x1F916;</span> LLM Models</a>
    <a href="/capabilities" class="nav-btn"><span class="icon">&#x2692;&#xFE0F;</span> Capabilities</a>
    <a href="/projects" class="nav-btn active"><span class="icon">&#x1F4C1;</span> Projects</a>
    <a href="/docs" class="nav-btn"><span class="icon">&#x1F4D6;</span> Docs</a>
  </div>
  <div class="proj-list-nav">
    <div class="proj-list-label">My Projects</div>
    <div id="navProjList"></div>
    <button class="proj-add-btn" onclick="openAddModal('dir')">+ Add / Clone Project</button>
  </div>
</div>

<div class="activity-rail">
  <button class="activity-btn active" data-tab="chat" title="Agent Workspace" onclick="openAgentSurface('chat')">&#x1F916;</button>
  <button class="activity-btn" data-tab="file" title="Explorer" onclick="switchTab('file')">&#x1F4C2;</button>
  <button class="activity-btn" data-tab="terminal" title="Terminal" onclick="openCodingSurface('terminal')">&#x2328;</button>
  <button class="activity-btn" data-tab="services" title="Services" onclick="openAgentSurface('services')">&#x2699;&#xFE0F;</button>
  <button class="activity-btn" data-tab="git" title="Source Control" onclick="openCodingSurface('git')">&#x1F500;</button>
  <div class="activity-spacer"></div>
  <button class="activity-btn" title="Switch To Agent Mode" onclick="setWorkspaceMode('agent')">&#x2728;</button>
  <button class="activity-btn" title="Switch To Coding Mode" onclick="setWorkspaceMode('code')">&#x1F4BB;</button>
</div>

<!-- File panel -->
<div class="file-panel">
  <div class="file-panel-header">
    <span class="file-panel-title" id="filePanelTitle">No project open</span>
    <span class="file-panel-subtitle" id="filePanelSubtitle">Agent-first explorer</span>
  </div>
  <div class="agent-lens-card" id="agentLensCard">
    <div class="agent-lens-top">
      <div class="agent-lens-title">Agent Lens</div>
      <div class="agent-lens-mode" id="agentLensMode">Agent mode</div>
    </div>
    <div class="agent-lens-copy" id="agentLensCopy">Open a project to start in an agent-guided workspace, then switch to coding mode when you want to edit, debug, or ship changes directly.</div>
    <div class="agent-lens-actions">
      <button class="mini-btn" onclick="openAgentSurface('chat')">Agent Chat</button>
      <button class="mini-btn" onclick="openAgentSurface('services')">Services</button>
      <button class="mini-btn" onclick="openCodingSurface('file')">Open Code</button>
      <button class="mini-btn" onclick="openCodingSurface('terminal')">Terminal</button>
    </div>
  </div>
  <div class="side-section-label">Explorer</div>
  <div class="file-tree" id="fileTree"><div style="padding:14px;font-size:12px;color:var(--muted)">Open a project to see its files.</div></div>
</div>

<!-- Main workspace -->
<div class="workspace">
  <div class="workspace-top">
    <div class="workspace-top-left">
      <span class="ws-eyebrow">Project Workbench</span>
      <span class="ws-title" id="wsTitle">Projects</span>
    </div>
    <div class="workspace-top-right">
      <span class="ws-badge" id="wsBranch" style="display:none">&#x1F533; <span id="wsBranchName">main</span></span>
      <span class="ws-badge" id="wsPath" style="display:none;font-family:monospace;font-size:11px;color:var(--muted)"></span>
      <span class="ws-badge" id="wsModeBadge">Agent priority</span>
      <div class="mode-switch">
        <button class="mode-chip active" data-mode="agent" onclick="setWorkspaceMode('agent')">Agent Mode</button>
        <button class="mode-chip" data-mode="code" onclick="setWorkspaceMode('code')">Coding Mode</button>
      </div>
    </div>
  </div>
  <div class="command-bar">
    <div class="command-track" id="commandTrack">Open a project and start from the agent workspace. Use coding mode when you want a denser editor flow.</div>
    <div class="command-actions">
      <button class="command-pill" onclick="openAgentSurface('chat')">Agent Workspace</button>
      <button class="command-pill" onclick="openCodingSurface('file')">Code Viewer</button>
      <button class="command-pill" onclick="openCodingSurface('terminal')">Terminal</button>
      <button class="command-pill" onclick="openAgentSurface('services')">Service Pulse</button>
    </div>
  </div>
  <div class="tab-bar">
    <div class="tab active" onclick="switchTab('chat')">&#x1F4AC; Agent Chat</div>
    <div class="tab" onclick="switchTab('file')">&#x1F4C4; File Viewer</div>
    <div class="tab" onclick="switchTab('terminal')">&#x1F4BB; Terminal</div>
    <div class="tab" onclick="switchTab('services')">&#x2699;&#xFE0F; Services</div>
    <div class="tab" onclick="switchTab('git')">&#x1F500; Git</div>
  </div>
  <div class="tab-panels">

    <!-- Chat tab -->
    <div class="tab-panel active" id="panel-chat">
      <!-- Recent chats history bar -->
      <div id="projChatHistory" style="display:none;border-bottom:1px solid var(--border);flex-shrink:0">
        <div style="display:flex;align-items:center;justify-content:space-between;padding:6px 14px;cursor:pointer;user-select:none" onclick="toggleChatHistory()">
          <span style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.05em">&#x1F4DC; Recent Chats</span>
          <span id="chatHistoryToggle" style="font-size:10px;color:var(--muted)">&#x25BC;</span>
        </div>
        <div id="projChatHistoryList" style="max-height:160px;overflow-y:auto;padding:0 8px 6px"></div>
      </div>
      <div class="chat-messages" id="chatMessages" style="flex:1;overflow-y:auto">
        <div class="msg-row system"><div class="msg-bubble">Open a project, then ask me anything about it — review code, explain files, find bugs, add features.</div></div>
      </div>
      <div class="chat-input-bar" style="flex-shrink:0">
        <div id="projChatAttachChips" class="chat-attach-chips"></div>
        <div class="chat-input-row">
          <input type="file" id="projChatFileInput" multiple style="display:none" onchange="handleProjChatFileSelect(this)">
          <button class="attach-btn" onclick="document.getElementById('projChatFileInput').click()" title="Attach files">&#x1F4CE;</button>
          <textarea class="chat-input" id="chatInput" rows="1" placeholder="Ask about your project..." onkeydown="chatKeydown(event)"></textarea>
          <button class="send-btn" id="sendBtn" onclick="sendChat()">&#x27A4;</button>
        </div>
        <div class="chat-bar-meta">
          <div class="chat-mode-group" id="projChatModeGroup">
            <button class="chat-mode-chip active" data-chat-mode="auto" onclick="setProjectChatMode('auto')">Auto</button>
            <button class="chat-mode-chip" data-chat-mode="ask" onclick="setProjectChatMode('ask')">Ask</button>
            <button class="chat-mode-chip" data-chat-mode="ai" onclick="setProjectChatMode('ai')">AI Mode</button>
          </div>
          <label class="chat-toggle-chip active" id="projShellToggleChip">
            <input type="checkbox" id="projShellToggle" checked onchange="setProjectChatShell(this.checked)">
            <span>Shell</span>
          </label>
          <label class="chat-toggle-chip danger" id="projDestructiveToggleChip">
            <input type="checkbox" id="projDestructiveToggle" onchange="setProjectChatDestructive(this.checked)">
            <span>Destructive</span>
          </label>
          <div class="chat-mode-note" id="projChatModeNote">Auto routes questions to quick analysis and action requests to the execution runtime.</div>
          <select class="chat-model-select" id="projModelSelect" title="Select model" onchange="projModelChanged()">
            <option value="">Default model</option>
          </select>
          <div class="ctx-badge" id="ctxBadge" style="display:none">
            <div class="ctx-bar-wrap"><div class="ctx-bar-fill" id="ctxBarFill" style="width:0%"></div></div>
            <span id="ctxLabel">0k ctx</span>
          </div>
        </div>
      </div>
    </div>

    <!-- File viewer tab -->
    <div class="tab-panel" id="panel-file">
      <div class="file-viewer-header">
        <span id="fileViewerPath" class="fpath">No file selected — click a file in the tree</span>
      </div>
      <div class="file-viewer"><pre id="fileViewerContent" style="color:var(--muted)">Select a file from the tree on the left.</pre></div>
    </div>

    <!-- Terminal tab -->
    <div class="tab-panel" id="panel-terminal">
      <div class="terminal-output" id="termOutput">kendr project terminal — type a command below and press Enter.
</div>
      <div class="terminal-input-bar">
        <span class="terminal-prompt" id="termPrompt">$</span>
        <input class="terminal-input" id="termInput" placeholder="ls -la" autocomplete="off" onkeydown="termKeydown(event)">
      </div>
    </div>

    <!-- Services tab -->
    <div class="tab-panel" id="panel-services">
      <div class="service-panel">
        <div class="service-section">
          <div class="git-section-title">Start Or Resume A Service</div>
          <div class="service-form-grid">
            <div class="form-field">
              <label>Service Name</label>
              <input type="text" id="svcName" placeholder="frontend">
            </div>
            <div class="form-field">
              <label>Kind</label>
              <select id="svcKind">
                <option value="">service</option>
                <option value="frontend">frontend</option>
                <option value="backend">backend</option>
                <option value="database">database</option>
                <option value="worker">worker</option>
                <option value="proxy">proxy</option>
              </select>
            </div>
            <div class="form-field">
              <label>Port</label>
              <input type="number" id="svcPort" placeholder="3000">
            </div>
            <div class="form-field">
              <label>Health URL</label>
              <input type="text" id="svcHealthUrl" placeholder="http://127.0.0.1:3000/health">
            </div>
          </div>
          <div class="form-field" style="margin-top:10px">
            <label>Command</label>
            <textarea id="svcCommand" placeholder="npm run dev"></textarea>
          </div>
          <div class="form-field" style="margin-top:10px">
            <label>Working Directory <span style="color:var(--muted);font-weight:400">(optional; defaults to project root)</span></label>
            <input type="text" id="svcCwd" placeholder="apps/web">
          </div>
          <div class="git-actions" style="margin-top:6px">
            <button class="btn btn-primary" onclick="createProjectService()">Start Service</button>
            <button class="btn btn-outline" onclick="loadProjectServices()">Refresh</button>
          </div>
          <div id="svcMsg" style="font-size:12px;color:var(--muted);min-height:18px;margin-top:10px"></div>
        </div>
        <div class="service-section">
          <div class="git-section-title">Tracked Services</div>
          <div id="servicesList" class="service-empty">Open a project to manage its services.</div>
        </div>
        <div class="service-section">
          <div class="git-section-title">Service Log Tail</div>
          <div id="serviceLogMeta" style="font-size:12px;color:var(--muted);margin-bottom:10px">Select a service to inspect its recent logs.</div>
          <pre id="serviceLogOutput" class="service-log">No log selected.</pre>
        </div>
      </div>
    </div>

    <!-- Git tab -->
    <div class="tab-panel" id="panel-git">
      <div class="git-panel" id="gitPanel">
        <div style="color:var(--muted);font-size:13px">Open a project to see git status.</div>
      </div>
    </div>

  </div>
  <div class="status-bar">
    <span class="status-pill" id="statusMode"><strong>AGENT</strong> mode</span>
    <span class="status-pill" id="statusProject">No project selected</span>
    <span class="status-pill" id="statusBranch">No branch</span>
    <span class="status-pill" id="statusServices">0 services tracked</span>
    <span class="status-pill" id="statusView">Agent Chat</span>
  </div>
</div>

<aside class="inspector-panel">
  <div class="inspector-header">
    <div class="inspector-title">Agent-Focused Workbench</div>
    <div class="inspector-sub">VSCode-inspired shell, but biased toward orchestration, debugging, and agent-guided iteration before raw file editing.</div>
  </div>
  <div class="inspector-card">
    <div class="inspector-card-label">Current Mode</div>
    <div class="inspector-card-title" id="inspectorMode">Agent Mode</div>
    <div class="inspector-copy" id="inspectorQuickTip">Agent mode keeps chat, services, and project context prominent so the assistant can steer the work before you drop into code.</div>
  </div>
  <div class="inspector-card">
    <div class="inspector-card-label">Project Pulse</div>
    <div class="inspector-card-title" id="inspectorProjectName">No project</div>
    <div class="inspector-copy" id="inspectorProjectPath">Open a project to populate the workbench.</div>
    <div class="inspector-stat-grid">
      <div class="inspector-stat"><span>Branch</span><strong id="inspectorBranch">-</strong></div>
      <div class="inspector-stat"><span>Services</span><strong id="inspectorServices">0</strong></div>
      <div class="inspector-stat"><span>Chats</span><strong id="inspectorRuns">0</strong></div>
      <div class="inspector-stat"><span>View</span><strong id="inspectorView">Agent Chat</strong></div>
    </div>
  </div>
  <div class="inspector-card">
    <div class="inspector-card-label">Recent Activity</div>
    <div class="inspector-list" id="inspectorActivityList">
      <div class="inspector-empty">Project analysis, file reads, terminal commands, runtime steps, and failures will appear here with timestamps and durations.</div>
    </div>
  </div>
  <div class="inspector-card">
    <div class="inspector-card-label">Service Pulse</div>
    <div class="inspector-list" id="inspectorServiceList">
      <div class="inspector-empty">Tracked project services will appear here once a project is open.</div>
    </div>
  </div>
  <div class="inspector-card">
    <div class="inspector-card-label">Quick Actions</div>
    <div class="inspector-actions">
      <button class="mini-btn" onclick="openAgentSurface('chat')">Ask Agent</button>
      <button class="mini-btn" onclick="openAgentSurface('services')">Check Services</button>
      <button class="mini-btn" onclick="openCodingSurface('file')">Review Code</button>
      <button class="mini-btn" onclick="openCodingSurface('git')">Source Control</button>
    </div>
    <div class="inspector-copy" id="inspectorRunSummary">Open a project and start from chat, then switch to coding mode when you want tighter file, terminal, and git focus.</div>
  </div>
</aside>

<!-- Delete project confirmation modal -->
<div class="modal-overlay" id="projDeleteModal">
  <div class="modal" style="max-width:420px">
    <div class="modal-title" style="color:var(--crimson)">Remove Project</div>
    <p style="margin:0 0 12px;font-size:14px;line-height:1.5">What would you like to do with <strong id="deleteProjName"></strong>?</p>
    <div style="font-size:12px;color:var(--muted);margin-bottom:16px;padding:10px 12px;background:rgba(255,255,255,0.04);border-radius:6px;border-left:3px solid var(--crimson)">
      <strong>Delete files</strong> permanently removes the folder and all its contents from disk. This cannot be undone.
    </div>
    <div id="deleteProjMsg" style="font-size:12px;min-height:18px;margin-bottom:8px"></div>
    <div class="modal-actions" style="flex-wrap:wrap;gap:8px">
      <button class="btn btn-outline" onclick="closeDeleteProjModal()" style="flex:0">Cancel</button>
      <button class="btn btn-outline" onclick="removeProjectFromList()" style="flex:1">Remove from list only</button>
      <button class="btn" onclick="deleteProjectAndFiles()" style="flex:1;background:var(--crimson);border-color:var(--crimson);color:#fff">&#x1F5D1; Delete files &amp; remove</button>
    </div>
  </div>
</div>

<!-- Download project modal -->
<div class="modal-overlay" id="projDownloadModal">
  <div class="modal" style="max-width:380px">
    <div class="modal-title">&#x2B07; Download Project</div>
    <p style="margin:0 0 14px;font-size:14px"><strong id="downloadProjName"></strong></p>
    <div class="form-field">
      <label>Archive format</label>
      <select id="downloadFmtSelect" style="width:100%;padding:8px 10px;background:var(--surface2);border:1px solid var(--border);border-radius:6px;color:var(--fg);font-size:13px">
        <option value="zip">ZIP (.zip) — most compatible</option>
        <option value="tar.gz">Gzip tarball (.tar.gz) — common on Linux/Mac</option>
        <option value="tar.bz2">Bzip2 tarball (.tar.bz2) — smaller size</option>
      </select>
    </div>
    <div style="font-size:11px;color:var(--muted);margin-top:4px;margin-bottom:16px">Excludes <code>.git</code>, <code>node_modules</code>, <code>__pycache__</code>, and virtual environments.</div>
    <div class="modal-actions">
      <button class="btn btn-outline" onclick="closeDownloadModal()">Cancel</button>
      <button class="btn btn-primary" onclick="downloadProject()">&#x2B07; Download</button>
    </div>
  </div>
</div>

<!-- Add / Clone modal -->
<div class="modal-overlay" id="addModal">
  <div class="modal">
    <div class="modal-title">Add Project</div>
    <div style="display:flex;gap:8px;margin-bottom:18px">
      <button class="btn btn-outline" id="tabNew" onclick="setAddMode('new')" style="flex:1;font-size:12px">&#x2728; New Project</button>
      <button class="btn btn-outline" id="tabDir" onclick="setAddMode('dir')" style="flex:1;font-size:12px">&#x1F4C1; Open Existing</button>
      <button class="btn btn-outline" id="tabClone" onclick="setAddMode('clone')" style="flex:1;font-size:12px">&#x2B07; Clone Repo</button>
    </div>
    <div id="formNew">
      <div class="form-field"><label>Project Name</label><input type="text" id="inputNewName" placeholder="my-awesome-app"></div>
      <div class="form-field"><label>Parent Directory <span style="color:var(--muted);font-weight:400">(where folder will be created)</span></label><input type="text" id="inputNewParent" placeholder="leave blank to use current directory"></div>
      <div class="form-field"><label>Stack / Language <span style="color:var(--muted);font-weight:400">(optional)</span></label><input type="text" id="inputNewStack" placeholder="e.g. Python, React, Go, Rust"></div>
      <div style="font-size:11px;color:var(--muted);margin-top:4px">Creates the folder, initializes git, adds <code>output/</code> to .gitignore.</div>
    </div>
    <div id="formDir" style="display:none">
      <div class="form-field"><label>Project Path</label><input type="text" id="inputPath" placeholder="/home/user/my-project"></div>
      <div class="form-field"><label>Display Name <span style="color:var(--muted);font-weight:400">(optional)</span></label><input type="text" id="inputName" placeholder="My Project"></div>
    </div>
    <div id="formClone" style="display:none">
      <div class="form-field"><label>Repository URL</label><input type="text" id="inputCloneUrl" placeholder="https://github.com/user/repo.git"></div>
      <div class="form-field"><label>Clone into directory</label><input type="text" id="inputCloneDest" placeholder="/home/user/projects"></div>
    </div>
    <div id="addModalMsg" style="font-size:12px;color:var(--muted);min-height:18px"></div>
    <div class="modal-actions">
      <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="addModalBtn" onclick="submitAddProject()">Create Project</button>
    </div>
  </div>
</div>
<div class="approval-overlay" id="projectApprovalModal">
  <div class="approval-box">
    <div class="approval-head">
      <div>
        <div class="approval-title">Awaiting Approval</div>
        <div class="approval-subtitle">Review the paused run, then accept, reject, or send guidance back into it.</div>
      </div>
      <button class="approval-close" type="button" onclick="_closeProjectApprovalModal()">&times;</button>
    </div>
    <div class="approval-body">
      <div class="approval-scope-pill" id="projectApprovalScope">Approval</div>
      <div class="approval-copy" id="projectApprovalPrompt">This project run is waiting for your response.</div>
      <div class="approval-hint">Accept continues immediately. Reject tells the runtime to revise instead of continuing. Suggestion sends your changes back into the paused run.</div>
      <div class="approval-suggest-wrap" id="projectApprovalSuggestWrap">
        <textarea id="projectApprovalSuggestion" placeholder="Tell Kendr what to change before continuing..."></textarea>
      </div>
      <div class="approval-actions-row">
        <button class="approval-action-btn accept" id="projectApprovalAcceptBtn" type="button" onclick="_submitProjectApproval('approve')">Accept</button>
        <button class="approval-action-btn reject" id="projectApprovalRejectBtn" type="button" onclick="_submitProjectApproval('reject')">Reject</button>
        <button class="approval-action-btn suggest" id="projectApprovalSuggestBtn" type="button" onclick="_toggleProjectApprovalSuggestion()">Suggestion</button>
        <button class="approval-action-btn submit" type="button" id="projectApprovalSuggestSubmit" onclick="_submitProjectApproval('suggest')" style="display:none">Send Suggestion</button>
      </div>
    </div>
  </div>
</div>

<script>
const API = '';
let _activeProjectId = null;
let _activeProjectPath = null;
let _activeProjectName = '';
let _runId = null;
let _sseSource = null;
let _termHistory = [];
let _termHistIdx = -1;
let _activeServiceLogId = '';
let _activeTab = 'chat';
let _workspaceMode = 'agent';
let _servicesCache = [];
let _gitStatusCache = null;
let _projectRunCount = 0;
let _projectChatMessages = [];
let _projectChatMode = 'auto';
let _projectChatShell = true;
let _projectChatAllowDestructive = false;
let _projectActivityFeed = [];
let _projectRuntimeActivityPoll = null;
let _projectAwaitingContext = null;

function _formatStepTimestamp(value) {
  if (!value) return '';
  try {
    return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
  } catch(_) { return String(value); }
}

function _formatStepDuration(step) {
  const durationMs = step && Number(step.duration_ms);
  if (Number.isFinite(durationMs) && durationMs >= 0) {
    if (durationMs < 1000) return durationMs + ' ms';
    if (durationMs < 60000) return (durationMs / 1000).toFixed(durationMs >= 10000 ? 0 : 1) + ' s';
    return (durationMs / 60000).toFixed(1) + ' min';
  }
  return step && step.duration_label ? String(step.duration_label) : '';
}

function _projectApprovalScopeLabel(scope, pendingKind) {
  const normalizedScope = String(scope || '').trim();
  if (normalizedScope === 'project_blueprint') return 'Blueprint Approval';
  if (normalizedScope === 'root_plan') return 'Plan Approval';
  if (normalizedScope === 'long_document_plan') return 'Research Plan';
  if (normalizedScope === 'deep_research_confirmation') return 'Research Confirmation';
  if (normalizedScope === 'drive_data_sufficiency') return 'Data Sufficiency';
  if (String(pendingKind || '').trim() === 'clarification') return 'Clarification';
  return 'Approval';
}

function _openProjectApprovalModal(meta) {
  const modal = document.getElementById('projectApprovalModal');
  if (!modal) return;
  _projectAwaitingContext = Object.assign({}, _projectAwaitingContext || {}, meta || {});
  document.getElementById('projectApprovalScope').textContent = _projectApprovalScopeLabel(_projectAwaitingContext.scope, _projectAwaitingContext.pendingKind);
  document.getElementById('projectApprovalPrompt').innerHTML = _renderApprovalRequestHtml(_projectAwaitingContext.approvalRequest, _projectAwaitingContext.prompt);
  document.getElementById('projectApprovalAcceptBtn').textContent = _approvalActionLabel(_projectAwaitingContext.approvalRequest, 'accept_label', 'Accept');
  document.getElementById('projectApprovalRejectBtn').textContent = _approvalActionLabel(_projectAwaitingContext.approvalRequest, 'reject_label', 'Reject');
  document.getElementById('projectApprovalSuggestBtn').textContent = _approvalActionLabel(_projectAwaitingContext.approvalRequest, 'suggest_label', 'Suggestion');
  document.getElementById('projectApprovalSuggestion').value = '';
  document.getElementById('projectApprovalSuggestWrap').classList.remove('open');
  document.getElementById('projectApprovalSuggestSubmit').style.display = 'none';
  modal.classList.add('open');
}

function _closeProjectApprovalModal() {
  const modal = document.getElementById('projectApprovalModal');
  if (modal) modal.classList.remove('open');
}

function _toggleProjectApprovalSuggestion() {
  const wrap = document.getElementById('projectApprovalSuggestWrap');
  const submit = document.getElementById('projectApprovalSuggestSubmit');
  if (!wrap || !submit) return;
  const opening = !wrap.classList.contains('open');
  wrap.classList.toggle('open', opening);
  submit.style.display = opening ? '' : 'none';
  if (opening) {
    const input = document.getElementById('projectApprovalSuggestion');
    if (input) input.focus();
  }
}

function _taskSessionSummary(session) {
  if (!session || typeof session !== 'object') return {};
  if (session.summary && typeof session.summary === 'object') return session.summary;
  if (typeof session.summary_json === 'string' && session.summary_json) {
    try { return JSON.parse(session.summary_json); } catch (_) {}
  }
  return {};
}

function _currentViewLabel() {
  return {
    chat: 'Agent Chat',
    file: 'File Viewer',
    terminal: 'Terminal',
    services: 'Services',
    git: 'Git',
  }[_activeTab] || 'Workspace';
}

function _renderInspectorServices() {
  const box = document.getElementById('inspectorServiceList');
  if (!box) return;
  if (!_servicesCache.length) {
    box.innerHTML = '<div class="inspector-empty">No tracked services yet. Start your frontend, backend, or database here so agents can reason about the live stack.</div>';
    return;
  }
  box.innerHTML = _servicesCache.slice(0, 5).map(service => {
    const status = service.status || (service.running ? 'running' : 'stopped');
    return `
      <div class="inspector-item">
        <div class="inspector-item-main">
          <div class="inspector-item-title">${esc(service.name || service.id || 'service')}</div>
          <div class="inspector-item-sub">${esc(service.kind || 'service')} · ${esc(service.port ? ('port ' + service.port) : 'no port')}</div>
        </div>
        <div class="inspector-item-status ${esc(status)}">${esc(status)}</div>
      </div>
    `;
  }).join('');
}

function _projectActivityTimestamp(item) {
  const candidate = item && (item.completed_at || item.started_at || item.timestamp || item.created_at);
  return candidate || '';
}

function _projectActivityKey(item) {
  return [
    item.kind || '',
    item.title || '',
    item.status || '',
    item.command || '',
    item.cwd || '',
    item.detail || '',
    _projectActivityTimestamp(item),
  ].join('|');
}

function _normalizeProjectActivity(item, defaults = {}) {
  const merged = Object.assign({}, defaults || {}, item || {});
  if (!merged.timestamp) merged.timestamp = _projectActivityTimestamp(merged) || new Date().toISOString();
  if (!merged.status) merged.status = 'info';
  if (!merged.title) merged.title = merged.kind || 'Activity';
  return merged;
}

function _projectActivitySortValue(item) {
  const iso = _projectActivityTimestamp(item);
  const value = iso ? Date.parse(iso) : NaN;
  return Number.isFinite(value) ? value : Date.now();
}

function _activityStatusClass(status) {
  const normalized = String(status || 'info').toLowerCase();
  if (['running', 'completed', 'failed', 'pending', 'queued', 'info', 'stopped', 'degraded'].includes(normalized)) return normalized;
  return 'info';
}

function _projectActivityMeta(item) {
  const parts = [];
  const task = String(item.task || '').trim();
  const subtask = String(item.subtask || '').trim();
  const actor = String(item.actor || '').trim();
  const started = _formatStepTimestamp(item.started_at || item.timestamp);
  const completed = _formatStepTimestamp(item.completed_at);
  const duration = item.duration_label || _formatStepDuration(item);
  if (task) parts.push(task);
  if (subtask) parts.push(subtask);
  else if (actor) parts.push(actor);
  if (started) parts.push(started);
  if (completed && completed !== started) parts.push('done ' + completed);
  if (duration) parts.push(duration);
  if (item.exit_code !== undefined && item.exit_code !== null && item.exit_code !== '') parts.push('exit ' + item.exit_code);
  return parts;
}

function _renderProjectActivityList(containerId, items, emptyMessage, limit = 6) {
  const box = document.getElementById(containerId);
  if (!box) return;
  const list = Array.isArray(items) ? items.slice(0, limit) : [];
  if (!list.length) {
    box.innerHTML = '<div class="inspector-empty">' + esc(emptyMessage) + '</div>';
    return;
  }
  box.innerHTML = list.map(item => {
    const status = _activityStatusClass(item.status);
    const meta = _projectActivityMeta(item).map(esc).join(' &middot; ');
    const detail = item.detail ? '<div class="inspector-activity-detail">' + esc(String(item.detail).slice(0, 220)) + '</div>' : '';
    const command = item.command ? '<div class="inspector-activity-command">' + esc(item.command) + '</div>' : '';
    return `
      <div class="inspector-activity-card">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px">
          <div class="inspector-activity-title">${esc(item.title || item.kind || 'Activity')}</div>
          <div class="inspector-item-status ${esc(status)}">${esc(status)}</div>
        </div>
        ${meta ? '<div class="inspector-activity-meta">' + meta + '</div>' : ''}
        ${detail}
        ${command}
      </div>
    `;
  }).join('');
}

function _renderInspectorActivities() {
  _renderProjectActivityList(
    'inspectorActivityList',
    _projectActivityFeed,
    'Project analysis, file reads, terminal commands, runtime steps, and failures will appear here with timestamps and durations.',
    7,
  );
}

function _recordProjectActivities(items, defaults = {}) {
  const next = Array.isArray(items) ? items.map(item => _normalizeProjectActivity(item, defaults)) : [];
  if (!next.length) return;
  const merged = next.concat(_projectActivityFeed || []);
  const deduped = [];
  const seen = new Set();
  for (const item of merged.sort((a, b) => _projectActivitySortValue(b) - _projectActivitySortValue(a))) {
    const key = _projectActivityKey(item);
    if (seen.has(key)) continue;
    seen.add(key);
    deduped.push(item);
    if (deduped.length >= 40) break;
  }
  _projectActivityFeed = deduped;
  _renderInspectorActivities();
  updateWorkbenchChrome();
}

function _recordProjectActivity(item, defaults = {}) {
  _recordProjectActivities([item], defaults);
}

function _countTreeNodes(nodes) {
  const list = Array.isArray(nodes) ? nodes : [];
  let count = 0;
  for (const node of list) {
    count += 1;
    if (node && node.type === 'dir' && Array.isArray(node.children)) count += _countTreeNodes(node.children);
  }
  return count;
}

function _renderProjectTraceCard(items, title = 'Recent Activity') {
  const normalized = Array.isArray(items) ? items.slice(0, 6).map(item => _normalizeProjectActivity(item)) : [];
  if (!normalized.length) return '';
  const rows = normalized.map(item => {
    const status = _activityStatusClass(item.status);
    const meta = _projectActivityMeta(item).map(esc).join(' &middot; ');
    const detail = item.detail ? '<div class="inspector-activity-detail">' + esc(String(item.detail).slice(0, 320)) + '</div>' : '';
    const command = item.command ? '<div class="inspector-activity-command">' + esc(item.command) + '</div>' : '';
    return `
      <div class="inspector-activity-card" style="margin-top:8px">
        <div style="display:flex;align-items:flex-start;justify-content:space-between;gap:10px">
          <div class="inspector-activity-title">${esc(item.title || item.kind || 'Activity')}</div>
          <div class="inspector-item-status ${esc(status)}">${esc(status)}</div>
        </div>
        ${meta ? '<div class="inspector-activity-meta">' + meta + '</div>' : ''}
        ${detail}
        ${command}
      </div>
    `;
  }).join('');
  return `<div class="trace-card"><div class="trace-card-title">${esc(title)}</div>${rows}</div>`;
}

function _upsertProjectBubbleTrace(bubble, items, title = 'Recent Activity') {
  if (!bubble) return;
  const html = _renderProjectTraceCard(items, title);
  const existing = bubble.querySelector('.trace-card');
  if (!html) {
    if (existing) existing.remove();
    return;
  }
  if (existing) existing.remove();
  bubble.insertAdjacentHTML('beforeend', html);
}

function _stopProjectRuntimeActivityPolling() {
  if (_projectRuntimeActivityPoll) {
    clearInterval(_projectRuntimeActivityPoll);
    _projectRuntimeActivityPoll = null;
  }
}

function _startProjectRuntimeActivityPolling(runId, bubble) {
  _stopProjectRuntimeActivityPolling();
  const poll = async () => {
    try {
      const r = await fetch(API + '/api/task-sessions/by-run/' + encodeURIComponent(runId));
      if (!r.ok) return;
      const session = await r.json();
      const summary = _taskSessionSummary(session);
      const events = Array.isArray(summary.execution_trace) ? summary.execution_trace : [];
      if (!events.length) return;
      _recordProjectActivities(events, { run_id: runId, task: summary.objective || summary.active_task || '' });
      _upsertProjectBubbleTrace(bubble, events, summary.active_task || summary.objective || 'Runtime Activity');
    } catch(_) {}
  };
  poll();
  _projectRuntimeActivityPoll = setInterval(poll, 2000);
}

function updateWorkbenchChrome() {
  const modeLabel = _workspaceMode === 'code' ? 'Coding Mode' : 'Agent Mode';
  const modeBadge = _workspaceMode === 'code' ? 'Code priority' : 'Agent priority';
  const tip = _workspaceMode === 'code'
    ? 'Coding mode widens the explorer and keeps the editor, terminal, git, and live stack closer together.'
    : 'Agent mode keeps chat, services, and project context prominent so the assistant can guide the work before you edit directly.';
  const viewTrack = {
    chat: 'Agent Chat is active. Ask for reviews, summaries, debugging help, or implementation guidance against the open project.',
    file: 'File Viewer is active. Open source files from the explorer and inspect code without leaving the workbench.',
    terminal: 'Terminal is active. Run project commands here and keep the output tied to the active project context.',
    services: 'Services is active. Start, stop, restart, and inspect tracked frontend, backend, and database processes from here.',
    git: 'Git is active. Review repository state and ship changes without leaving the workspace.',
  }[_activeTab] || 'Switch between agent, code, service, and git surfaces from the workbench.';
  const track = !_activeProjectName
    ? 'Open a project and start from the agent workspace. Use coding mode when you want a denser editor flow.'
    : viewTrack;
  const branch = (_gitStatusCache && _gitStatusCache.is_git && _gitStatusCache.branch) ? _gitStatusCache.branch : 'No git';
  const runningServices = _servicesCache.filter(service => service.running).length;

  const wsModeBadge = document.getElementById('wsModeBadge');
  const agentLensMode = document.getElementById('agentLensMode');
  const agentLensCopy = document.getElementById('agentLensCopy');
  const commandTrack = document.getElementById('commandTrack');
  const statusMode = document.getElementById('statusMode');
  const statusProject = document.getElementById('statusProject');
  const statusBranch = document.getElementById('statusBranch');
  const statusServices = document.getElementById('statusServices');
  const statusView = document.getElementById('statusView');
  const inspectorMode = document.getElementById('inspectorMode');
  const inspectorQuickTip = document.getElementById('inspectorQuickTip');
  const inspectorProjectName = document.getElementById('inspectorProjectName');
  const inspectorProjectPath = document.getElementById('inspectorProjectPath');
  const inspectorBranch = document.getElementById('inspectorBranch');
  const inspectorServices = document.getElementById('inspectorServices');
  const inspectorRuns = document.getElementById('inspectorRuns');
  const inspectorView = document.getElementById('inspectorView');
  const inspectorRunSummary = document.getElementById('inspectorRunSummary');
  const filePanelSubtitle = document.getElementById('filePanelSubtitle');

  if (wsModeBadge) wsModeBadge.textContent = modeBadge;
  if (agentLensMode) agentLensMode.textContent = modeLabel.toLowerCase();
  if (agentLensCopy) {
    agentLensCopy.textContent = _activeProjectName
      ? `${tip} Current focus: ${_currentViewLabel()}.`
      : 'Open a project to start in an agent-guided workspace, then switch to coding mode when you want to edit, debug, or ship changes directly.';
  }
  if (commandTrack) commandTrack.textContent = track;
  if (statusMode) statusMode.innerHTML = `<strong>${_workspaceMode === 'code' ? 'CODE' : 'AGENT'}</strong> mode`;
  if (statusProject) statusProject.textContent = _activeProjectName || 'No project selected';
  if (statusBranch) statusBranch.textContent = branch;
  if (statusServices) statusServices.textContent = `${runningServices}/${_servicesCache.length} services running`;
  if (statusView) statusView.textContent = _currentViewLabel();
  if (inspectorMode) inspectorMode.textContent = modeLabel;
  if (inspectorQuickTip) inspectorQuickTip.textContent = tip;
  if (inspectorProjectName) inspectorProjectName.textContent = _activeProjectName || 'No project';
  if (inspectorProjectPath) inspectorProjectPath.textContent = _activeProjectPath || 'Open a project to populate the workbench.';
  if (inspectorBranch) inspectorBranch.textContent = branch;
  if (inspectorServices) inspectorServices.textContent = `${runningServices}/${_servicesCache.length}`;
  if (inspectorRuns) inspectorRuns.textContent = String(_projectRunCount || 0);
  if (inspectorView) inspectorView.textContent = _currentViewLabel();
  if (inspectorRunSummary) {
    const latestActivity = (_projectActivityFeed && _projectActivityFeed.length) ? _projectActivityFeed[0] : null;
    inspectorRunSummary.textContent = !_activeProjectName
      ? 'Open a project and start from chat, then switch to coding mode when you want tighter file, terminal, and git focus.'
      : latestActivity
        ? `${_projectRunCount} saved chat turn${_projectRunCount === 1 ? '' : 's'}. Latest activity: ${latestActivity.title || latestActivity.kind || 'activity'}.`
        : `${_projectRunCount} saved chat turn${_projectRunCount === 1 ? '' : 's'}. Active surface: ${_currentViewLabel()}.`;
  }
  if (filePanelSubtitle) {
    filePanelSubtitle.textContent = _workspaceMode === 'code'
      ? 'Code-first explorer and editor support'
      : 'Agent-first explorer and project context';
  }
  _renderInspectorServices();
}

function setWorkspaceMode(mode, opts = {}) {
  _workspaceMode = mode === 'code' ? 'code' : 'agent';
  document.body.classList.toggle('mode-agent', _workspaceMode === 'agent');
  document.body.classList.toggle('mode-code', _workspaceMode === 'code');
  document.querySelectorAll('.mode-chip').forEach(btn => btn.classList.toggle('active', btn.dataset.mode === _workspaceMode));
  try { localStorage.setItem('kendr.project_ui_mode', _workspaceMode); } catch(_) {}
  if (!(opts && opts.keepTab)) {
    if (_workspaceMode === 'code' && (_activeTab === 'chat' || _activeTab === 'services')) switchTab('file');
    else if (_workspaceMode === 'agent' && (_activeTab === 'file' || _activeTab === 'terminal' || _activeTab === 'git')) switchTab('chat');
  }
  updateWorkbenchChrome();
}

function openAgentSurface(tab = 'chat') {
  setWorkspaceMode('agent', { keepTab: true });
  switchTab(tab);
}

function openCodingSurface(tab = 'file') {
  setWorkspaceMode('code', { keepTab: true });
  switchTab(tab);
}

// ── Tab switching ─────────────────────────────────────────────────────────────
function switchTab(name) {
  _activeTab = name;
  document.querySelectorAll('.tab').forEach((t, i) => {
    const tabs = ['chat','file','terminal','services','git'];
    t.classList.toggle('active', tabs[i] === name);
  });
  document.querySelectorAll('.activity-btn[data-tab]').forEach(btn => btn.classList.toggle('active', btn.dataset.tab === name));
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  document.body.dataset.projectTab = name;
  if (name === 'services') loadProjectServices();
  if (name === 'git') loadGitStatus();
  updateWorkbenchChrome();
}

// ── Projects ─────────────────────────────────────────────────────────────────
async function loadProjects() {
  try {
    const r = await fetch(API + '/api/projects');
    const projects = await r.json();
    const box = document.getElementById('navProjList');
    box.innerHTML = projects.map(p =>
      `<div class="proj-item ${p.id === _activeProjectId ? 'active' : ''}" onclick="openProject('${p.id}','${esc(p.path)}','${esc(p.name)}')">
        <span style="font-size:14px">&#x1F4C1;</span>
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;flex:1" title="${esc(p.path)}">${esc(p.name)}</span>
        <button onclick="event.stopPropagation();openDownloadModal('${p.id}','${esc(p.name)}')" title="Download / export project" style="background:none;border:none;color:var(--muted);cursor:pointer;padding:0 2px;font-size:12px;line-height:1;opacity:0.6" onmouseover="this.style.color='var(--teal)';this.style.opacity='1'" onmouseout="this.style.color='var(--muted)';this.style.opacity='0.6'">&#x2B07;</button>
        <button onclick="event.stopPropagation();openDeleteProjectModal('${p.id}','${esc(p.name)}')" title="Remove / delete project" style="background:none;border:none;color:var(--muted);cursor:pointer;padding:0 2px;font-size:13px;line-height:1;opacity:0.6" onmouseover="this.style.color='var(--crimson)';this.style.opacity='1'" onmouseout="this.style.color='var(--muted)';this.style.opacity='0.6'">&#x1F5D1;</button>
      </div>`
    ).join('') || '<div style="padding:8px 10px;font-size:12px;color:var(--muted)">No projects yet.</div>';
  } catch(e) { console.warn('load projects error', e); }
}

let _deleteProjId = null, _deleteProjName = '';
function openDeleteProjectModal(id, name) {
  _deleteProjId = id; _deleteProjName = name;
  document.getElementById('deleteProjName').textContent = name;
  document.getElementById('deleteProjMsg').textContent = '';
  document.getElementById('projDeleteModal').classList.add('open');
}
function closeDeleteProjModal() { document.getElementById('projDeleteModal').classList.remove('open'); }

async function _clearProjectUI(id) {
  if (_activeProjectId === id) {
    _activeProjectId = null; _activeProjectPath = null; _activeProjectName = '';
    _activeServiceLogId = '';
    _servicesCache = [];
    _gitStatusCache = null;
    _projectRunCount = 0;
    _projectChatMessages = [];
    _projectActivityFeed = [];
    _stopProjectRuntimeActivityPolling();
    document.getElementById('wsTitle').textContent = 'Projects';
    document.getElementById('wsPath').style.display = 'none';
    document.getElementById('wsBranch').style.display = 'none';
    document.getElementById('filePanelTitle').textContent = 'No project open';
    document.getElementById('filePanelSubtitle').textContent = 'Agent-first explorer';
    document.getElementById('fileTree').innerHTML = '<div style="padding:14px;font-size:12px;color:var(--muted)">Open a project to see its files.</div>';
    document.getElementById('chatMessages').innerHTML = '<div class="msg-row system"><div class="msg-bubble">Open a project, then ask me anything about it — review code, explain files, find bugs, add features.</div></div>';
    document.getElementById('projChatHistory').style.display = 'none';
    document.getElementById('projChatHistoryList').innerHTML = '';
    document.getElementById('servicesList').innerHTML = 'Open a project to manage its services.';
    document.getElementById('serviceLogMeta').textContent = 'Select a service to inspect its recent logs.';
    document.getElementById('serviceLogOutput').textContent = 'No log selected.';
    _renderInspectorActivities();
    updateWorkbenchChrome();
  }
}
async function removeProjectFromList() {
  closeDeleteProjModal();
  await fetch(API + '/api/projects/' + _deleteProjId + '/remove', { method: 'POST' });
  await _clearProjectUI(_deleteProjId);
  await loadProjects();
}
async function deleteProjectAndFiles() {
  const msg = document.getElementById('deleteProjMsg');
  msg.style.color = 'var(--muted)'; msg.textContent = 'Deleting files...';
  const r = await fetch(API + '/api/projects/' + _deleteProjId + '/delete-files', { method: 'POST' });
  const d = await r.json();
  if (!d.ok) { msg.style.color = 'var(--crimson)'; msg.textContent = d.error || 'Delete failed'; return; }
  closeDeleteProjModal();
  await _clearProjectUI(_deleteProjId);
  await loadProjects();
}

// ── Download modal ────────────────────────────────────────────────────────────
let _downloadProjId = null;
function openDownloadModal(id, name) {
  _downloadProjId = id;
  document.getElementById('downloadProjName').textContent = name;
  document.getElementById('projDownloadModal').classList.add('open');
}
function closeDownloadModal() { document.getElementById('projDownloadModal').classList.remove('open'); }
function downloadProject() {
  const fmt = document.getElementById('downloadFmtSelect').value;
  const url = API + '/api/projects/' + _downloadProjId + '/download?format=' + encodeURIComponent(fmt);
  const a = document.createElement('a'); a.href = url; a.download = ''; document.body.appendChild(a); a.click(); a.remove();
  closeDownloadModal();
}

async function openProject(id, path, name) {
  _activeProjectId = id;
  _activeProjectPath = path;
  _activeProjectName = name;
  _activeServiceLogId = '';
  _projectChatMessages = [];
  _projectActivityFeed = [];
  _stopProjectRuntimeActivityPolling();
  document.getElementById('wsTitle').textContent = name;
  document.getElementById('wsPath').textContent = path;
  document.getElementById('wsPath').style.display = '';
  document.getElementById('filePanelTitle').textContent = name;
  document.getElementById('termPrompt').textContent = name.substring(0,12) + ' $';
  _recordProjectActivity({
    kind: 'project',
    title: 'Project opened',
    status: 'completed',
    detail: path,
    cwd: path,
    task: 'Open project workbench',
    subtask: name,
    completed_at: new Date().toISOString(),
  });
  await fetch(API + '/api/projects/' + id + '/activate', { method: 'POST' });
  await loadProjects();
  await loadFileTree();
  const gitBadge = document.getElementById('wsBranch');
  const status = await fetch(API + '/api/projects/' + id + '/git/status').then(r => r.json()).catch(() => null);
  _gitStatusCache = status;
  if (status && status.is_git) {
    document.getElementById('wsBranchName').textContent = status.branch || 'main';
    gitBadge.style.display = '';
  } else {
    gitBadge.style.display = 'none';
  }
  loadProjectServices();
  await loadProjectChatHistory();
  updateWorkbenchChrome();
}

let _projHistoryOpen = true;
function toggleChatHistory() {
  _projHistoryOpen = !_projHistoryOpen;
  document.getElementById('projChatHistoryList').style.display = _projHistoryOpen ? '' : 'none';
  document.getElementById('chatHistoryToggle').textContent = _projHistoryOpen ? '\u25BC' : '\u25B6';
}

function scrollToChatMessage(messageId) {
  const box = document.getElementById('chatMessages');
  const node = box.querySelector('[data-message-id="' + esc(messageId) + '"]');
  if (!node) return;
  node.scrollIntoView({ behavior: 'smooth', block: 'center' });
}

function renderProjectChatHistoryRail() {
  const historyBar = document.getElementById('projChatHistory');
  const listEl = document.getElementById('projChatHistoryList');
  const turns = (_projectChatMessages || []).filter(message => message.role === 'user');
  _projectRunCount = turns.length;
  if (!turns.length) {
    historyBar.style.display = 'none';
    listEl.innerHTML = '';
    updateWorkbenchChrome();
    return;
  }
  historyBar.style.display = '';
  listEl.style.display = _projHistoryOpen ? '' : 'none';
  listEl.innerHTML = '';
  turns.slice().reverse().slice(0, 20).forEach(message => {
    const title = String(message.content || '').trim().split('\n')[0].substring(0, 80) || 'Untitled';
    const ts = _relTime(message.created_at || '');
    const item = document.createElement('div');
    item.style.cssText = 'display:flex;align-items:center;gap:6px;padding:5px 8px;border-radius:6px;cursor:pointer;font-size:12px;color:#ccc;transition:background 0.15s';
    item.innerHTML = '<span style="width:7px;height:7px;border-radius:50%;display:inline-block;flex-shrink:0;background:var(--teal)"></span>'
      + '<span style="flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">' + esc(title) + '</span>'
      + '<span style="font-size:10px;color:var(--muted);flex-shrink:0">' + esc(ts) + '</span>';
    item.onmouseenter = () => item.style.background = 'rgba(255,255,255,0.05)';
    item.onmouseleave = () => item.style.background = '';
    item.onclick = () => scrollToChatMessage(message.message_id || '');
    listEl.appendChild(item);
  });
  updateWorkbenchChrome();
}

function _relTime(iso) {
  if (!iso) return '';
  try {
    const diff = Date.now() - new Date(iso).getTime();
    const m = Math.floor(diff / 60000);
    if (m < 1) return 'just now';
    if (m < 60) return m + 'm ago';
    const h = Math.floor(m / 60);
    if (h < 24) return h + 'h ago';
    return Math.floor(h / 24) + 'd ago';
  } catch(_) { return ''; }
}

function renderProjectChatMessages(messages) {
  const box = document.getElementById('chatMessages');
  _projectChatMessages = Array.isArray(messages) ? messages.slice() : [];
  _projectRunCount = _projectChatMessages.filter(message => message.role === 'user').length;
  if (!_projectChatMessages.length) {
    box.innerHTML = '<div class="msg-row system"><div class="msg-bubble">This project chat is persisted. Ask about the codebase, running services, debugging, or next changes.</div></div>';
    renderProjectChatHistoryRail();
    return;
  }
  box.innerHTML = '';
  _projectChatMessages.forEach(message => {
    const row = document.createElement('div');
    const role = message.role || 'system';
    row.className = 'msg-row ' + role;
    if (message.message_id) row.dataset.messageId = message.message_id;
    row.innerHTML = '<div class="msg-bubble"></div>';
    const bubble = row.querySelector('.msg-bubble');
    setChatBubbleContent(bubble, message.content || '', message.content_format || '', role);
    // Re-render deep research result card and download links from persisted data
    if (role === 'agent' && message.deep_research_result_card) {
      const runId = message.run_id || '';
      const cardHtml = renderDeepResearchCard(message.deep_research_result_card, runId);
      if (cardHtml) bubble.insertAdjacentHTML('beforeend', cardHtml);
    }
    if (role === 'agent' && message.long_document_exports && message.long_document_exports.length) {
      const runId = message.run_id || '';
      const previewHtml = renderDocumentPreviewCard(runId, message.long_document_exports);
      if (previewHtml) bubble.insertAdjacentHTML('beforeend', previewHtml);
      const dlHtml = renderDocumentDownloadCard(runId, message.long_document_exports);
      if (dlHtml) bubble.insertAdjacentHTML('beforeend', dlHtml);
    }
    if (message.created_at && role !== 'system') {
      const meta = document.createElement('div');
      meta.className = 'msg-ctx';
      meta.innerHTML = '<span>' + esc(_relTime(message.created_at) || new Date(message.created_at).toLocaleString()) + '</span>';
      bubble.appendChild(meta);
    }
    box.appendChild(row);
  });
  box.scrollTop = box.scrollHeight;
  renderProjectChatHistoryRail();
}

async function loadProjectChatHistory() {
  const box = document.getElementById('chatMessages');
  const historyBar = document.getElementById('projChatHistory');
  if (!_activeProjectId) {
    _projectChatMessages = [];
    _projectRunCount = 0;
    historyBar.style.display = 'none';
    box.innerHTML = '<div class="msg-row system"><div class="msg-bubble">Open a project, then ask me anything about it — review code, explain files, find bugs, add features.</div></div>';
    updateWorkbenchChrome();
    return;
  }
  box.innerHTML = '<div class="msg-row system"><div class="msg-bubble"><span class="spinner"></span> Loading saved project chat...</div></div>';
  try {
    const r = await fetch(API + '/api/projects/' + encodeURIComponent(_activeProjectId) + '/chat/history');
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || 'Failed to load project chat history');
    renderProjectChatMessages(d.messages || []);
  } catch(e) {
    _projectChatMessages = [];
    _projectRunCount = 0;
    historyBar.style.display = 'none';
    box.innerHTML = '<div class="msg-row system"><div class="msg-bubble" style="color:var(--crimson)">Error: ' + esc(String(e)) + '</div></div>';
    updateWorkbenchChrome();
  }
}

// ── File tree ─────────────────────────────────────────────────────────────────
async function loadFileTree() {
  if (!_activeProjectId) return;
  const box = document.getElementById('fileTree');
  box.innerHTML = '<div style="padding:10px 12px;font-size:12px;color:var(--muted)"><span class="spinner"></span> Loading...</div>';
  const startedAt = new Date().toISOString();
  const startedTs = Date.now();
  try {
    const r = await fetch(API + '/api/projects/' + _activeProjectId + '/files');
    const tree = await r.json();
    box.innerHTML = renderTree(tree, 0);
    _recordProjectActivity({
      kind: 'file_tree',
      title: 'Explorer loaded',
      status: 'completed',
      detail: `Loaded ${_countTreeNodes(tree)} nodes from the project explorer.`,
      started_at: startedAt,
      completed_at: new Date().toISOString(),
      duration_ms: Math.max(0, Date.now() - startedTs),
      duration_label: _formatStepDuration({ duration_ms: Math.max(0, Date.now() - startedTs) }),
      cwd: _activeProjectPath || '',
      task: 'Inspect project files',
      subtask: 'Load explorer tree',
    });
  } catch(e) {
    box.innerHTML = '<div style="padding:10px;color:var(--crimson);font-size:12px">Error: ' + e + '</div>';
    _recordProjectActivity({
      kind: 'file_tree',
      title: 'Explorer load failed',
      status: 'failed',
      detail: String(e),
      started_at: startedAt,
      completed_at: new Date().toISOString(),
      duration_ms: Math.max(0, Date.now() - startedTs),
      duration_label: _formatStepDuration({ duration_ms: Math.max(0, Date.now() - startedTs) }),
      cwd: _activeProjectPath || '',
      task: 'Inspect project files',
      subtask: 'Load explorer tree',
    });
  }
}

function renderTree(nodes, depth) {
  return nodes.map(n => {
    const indent = depth * 14;
    if (n.type === 'dir') {
      const childHtml = renderTree(n.children || [], depth + 1);
      const id = 'tree-' + btoa(n.path).replace(/[^a-zA-Z0-9]/g,'').slice(-10);
      return `<div class="tree-node">
        <div class="tree-row" data-node-type="dir" data-tree-id="${id}" style="padding-left:${12 + indent}px">
          <span class="icon" id="icon-${id}">&#x25B8;</span>
          <span style="font-size:13px">&#x1F4C2;</span>
          <span class="fname">${esc(n.name)}</span>
        </div>
        <div class="tree-children" id="${id}" style="display:none">${childHtml}</div>
      </div>`;
    } else {
      const fileIcon = getFileIcon(n.name);
      return `<div class="tree-row" data-node-type="file" data-path="${esc(n.path)}" data-name="${esc(n.name)}" style="padding-left:${12 + indent}px">
        <span class="icon">&nbsp;</span>
        <span style="font-size:12px">${fileIcon}</span>
        <span class="fname">${esc(n.name)}</span>
        <span style="margin-left:auto;font-size:10px;color:var(--muted)">${fmtSize(n.size)}</span>
      </div>`;
    }
  }).join('');
}

function handleFileTreeClick(event) {
  const row = event.target.closest('.tree-row');
  if (!row) return;
  if (row.dataset.nodeType === 'dir') {
    toggleDir(row.dataset.treeId || '');
    return;
  }
  if (row.dataset.nodeType === 'file') {
    openFile(row.dataset.path || '', row.dataset.name || '', row);
  }
}

function toggleDir(id) {
  if (!id) return;
  const el = document.getElementById(id);
  const icon = document.getElementById('icon-' + id);
  if (!el || !icon) return;
  const open = el.style.display !== 'none';
  el.style.display = open ? 'none' : 'block';
  icon.textContent = open ? '\u25B8' : '\u25BE';
}

async function openFile(path, name, rowEl = null) {
  document.querySelectorAll('.file-tree .tree-row').forEach(r => r.classList.remove('selected'));
  if (rowEl) rowEl.classList.add('selected');
  switchTab('file');
  document.getElementById('fileViewerPath').textContent = path;
  document.getElementById('fileViewerContent').textContent = 'Loading...';
  const startedAt = new Date().toISOString();
  const startedTs = Date.now();
  try {
    const r = await fetch(API + '/api/projects/file?path=' + encodeURIComponent(path) + '&root=' + encodeURIComponent(_activeProjectPath || ''));
    const d = await r.json();
    if (d.ok) {
      document.getElementById('fileViewerContent').textContent = d.content;
      _recordProjectActivity({
        kind: 'file_read',
        title: 'File opened',
        status: 'completed',
        detail: `${name || path} (${(d.content || '').length} chars)`,
        started_at: startedAt,
        completed_at: new Date().toISOString(),
        duration_ms: Math.max(0, Date.now() - startedTs),
        duration_label: _formatStepDuration({ duration_ms: Math.max(0, Date.now() - startedTs) }),
        cwd: _activeProjectPath || '',
        command: path,
        task: 'Inspect project files',
        subtask: 'Open file',
      });
    } else {
      document.getElementById('fileViewerContent').textContent = 'Error: ' + d.error;
      _recordProjectActivity({
        kind: 'file_read',
        title: 'File open failed',
        status: 'failed',
        detail: d.error || 'Unknown file read error',
        started_at: startedAt,
        completed_at: new Date().toISOString(),
        duration_ms: Math.max(0, Date.now() - startedTs),
        duration_label: _formatStepDuration({ duration_ms: Math.max(0, Date.now() - startedTs) }),
        cwd: _activeProjectPath || '',
        command: path,
        task: 'Inspect project files',
        subtask: 'Open file',
      });
    }
  } catch(e) {
    document.getElementById('fileViewerContent').textContent = 'Error: ' + e;
    _recordProjectActivity({
      kind: 'file_read',
      title: 'File open failed',
      status: 'failed',
      detail: String(e),
      started_at: startedAt,
      completed_at: new Date().toISOString(),
      duration_ms: Math.max(0, Date.now() - startedTs),
      duration_label: _formatStepDuration({ duration_ms: Math.max(0, Date.now() - startedTs) }),
      cwd: _activeProjectPath || '',
      command: path,
      task: 'Inspect project files',
      subtask: 'Open file',
    });
  }
}

function getFileIcon(name) {
  const ext = name.split('.').pop().toLowerCase();
  const icons = { py:'&#x1F40D;', js:'&#x1F7E1;', ts:'&#x1F535;', tsx:'&#x1F535;', jsx:'&#x1F7E1;', html:'&#x1F4C4;', css:'&#x1F3A8;', json:'&#x1F4CB;', md:'&#x1F4DD;', yml:'&#x2699;', yaml:'&#x2699;', sh:'&#x1F4DC;', env:'&#x1F512;', txt:'&#x1F4C4;', go:'&#x1F535;', rs:'&#x1F7E0;', java:'&#x2615;', sql:'&#x1F5C3;', dockerfile:'&#x1F433;', toml:'&#x2699;' };
  return icons[ext] || '&#x1F4C4;';
}

function fmtSize(bytes) {
  if (!bytes) return '';
  if (bytes < 1024) return bytes + 'B';
  if (bytes < 1048576) return (bytes / 1024).toFixed(0) + 'KB';
  return (bytes / 1048576).toFixed(1) + 'MB';
}

// ── Chat ──────────────────────────────────────────────────────────────────────
function escapeHtml(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function isLikelyMarkdown(text) {
  return /(^|\n)\s{0,3}(#{1,6}\s|[-*+]\s|>\s|\d+\.\s|```)|\[[^\]]+\]\((https?:\/\/|\/)[^)]+\)|`[^`]+`|\*\*[^*]+\*\*|(^|\n)\|.+\|/m.test(String(text || ''));
}

function renderInlineMarkdown(text) {
  let html = escapeHtml(text);
  html = html.replace(/\[([^\]]+)\]\((https?:\/\/[^)\s]+|\/[^)\s]*)\)/g, '<a href="$2" target="_blank" rel="noreferrer">$1</a>');
  html = html.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  html = html.replace(/__([^_]+)__/g, '<strong>$1</strong>');
  html = html.replace(/(^|[^*])\*([^*\n]+)\*(?!\*)/g, '$1<em>$2</em>');
  html = html.replace(/(^|[^_])_([^_\n]+)_(?!_)/g, '$1<em>$2</em>');
  html = html.replace(/~~([^~]+)~~/g, '<del>$1</del>');
  html = html.replace(/`([^`]+)`/g, '<code>$1</code>');
  return html;
}

function renderMarkdown(text) {
  const source = String(text || '').replace(/\r\n?/g, '\n');
  const codeBlocks = [];
  let working = source.replace(/```([\w.+-]+)?\n([\s\S]*?)```/g, (_, lang, code) => {
    const index = codeBlocks.length;
    const langAttr = lang ? ` data-lang="${escapeHtml(lang)}"` : '';
    codeBlocks.push(`<pre><code${langAttr}>${escapeHtml(String(code || '').replace(/\n$/, ''))}</code></pre>`);
    return `@@CODEBLOCK${index}@@`;
  });
  const lines = working.split('\n');
  const out = [];
  let paragraph = [];
  let inUl = false;
  let inOl = false;

  function flushParagraph() {
    if (!paragraph.length) return;
    out.push('<p>' + paragraph.map(renderInlineMarkdown).join('<br>') + '</p>');
    paragraph = [];
  }

  function closeLists() {
    if (inUl) { out.push('</ul>'); inUl = false; }
    if (inOl) { out.push('</ol>'); inOl = false; }
  }

  for (const rawLine of lines) {
    const line = rawLine || '';
    const trimmed = line.trim();
    const codeMatch = trimmed.match(/^@@CODEBLOCK(\d+)@@$/);
    if (!trimmed) {
      flushParagraph();
      closeLists();
      continue;
    }
    if (codeMatch) {
      flushParagraph();
      closeLists();
      out.push(codeBlocks[Number(codeMatch[1])] || '');
      continue;
    }
    const headingMatch = line.match(/^\s{0,3}(#{1,6})\s+(.*)$/);
    if (headingMatch) {
      flushParagraph();
      closeLists();
      const level = headingMatch[1].length;
      out.push(`<h${level}>${renderInlineMarkdown(headingMatch[2])}</h${level}>`);
      continue;
    }
    const quoteMatch = line.match(/^\s{0,3}>\s?(.*)$/);
    if (quoteMatch) {
      flushParagraph();
      closeLists();
      out.push('<blockquote>' + renderInlineMarkdown(quoteMatch[1]) + '</blockquote>');
      continue;
    }
    const ulMatch = line.match(/^\s{0,3}[-*+]\s+(.*)$/);
    if (ulMatch) {
      flushParagraph();
      if (inOl) { out.push('</ol>'); inOl = false; }
      if (!inUl) { out.push('<ul>'); inUl = true; }
      out.push('<li>' + renderInlineMarkdown(ulMatch[1]) + '</li>');
      continue;
    }
    const olMatch = line.match(/^\s{0,3}(\d+)\.\s+(.*)$/);
    if (olMatch) {
      flushParagraph();
      if (inUl) { out.push('</ul>'); inUl = false; }
      if (!inOl) { out.push('<ol>'); inOl = true; }
      out.push('<li>' + renderInlineMarkdown(olMatch[2]) + '</li>');
      continue;
    }
    if (/^\s{0,3}---+\s*$/.test(line)) {
      flushParagraph();
      closeLists();
      out.push('<hr>');
      continue;
    }
    paragraph.push(line);
  }
  flushParagraph();
  closeLists();
  return out.join('');
}

function renderChatContent(text, contentFormat = '') {
  const body = String(text || '');
  const wantsMarkdown = contentFormat === 'markdown' || (!contentFormat && isLikelyMarkdown(body));
  if (!wantsMarkdown) return `<div class="plain-text">${escapeHtml(body)}</div>`;
  return `<div class="markdown-body">${renderMarkdown(body)}</div>`;
}

function setChatBubbleContent(bubble, text, contentFormat = '', role = 'agent') {
  if (!bubble) return;
  const format = role === 'system' ? 'text' : contentFormat;
  bubble.innerHTML = renderChatContent(text, format);
}

function appendMsg(role, text, contentFormat = '') {
  const box = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = 'msg-row ' + role;
  div.innerHTML = '<div class="msg-bubble"></div>';
  setChatBubbleContent(div.querySelector('.msg-bubble'), text, contentFormat, role);
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
  return div;
}
function appendSysMsg(text) {
  const box = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = 'msg-row system';
  div.innerHTML = '<div class="msg-bubble"></div>';
  setChatBubbleContent(div.querySelector('.msg-bubble'), text, 'text', 'system');
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function chatKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
}

let _projModelInfo = null;
let _projSelectedModel = '';
let _projSelectedProvider = '';

function projModelChanged() {
  const sel = document.getElementById('projModelSelect');
  const val = sel.value;
  if (!val) { _projSelectedModel = ''; _projSelectedProvider = ''; return; }
  const parts = val.split('::');
  _projSelectedProvider = parts[0] || '';
  _projSelectedModel = parts[1] || '';
}

function _fmtTokens(n) {
  if (n >= 1000000) return (n/1000000).toFixed(1) + 'M';
  if (n >= 1000) return (n/1000).toFixed(0) + 'k';
  return String(n);
}

function _updateCtxBadge(ctxTokens, ctxLimit, model) {
  const badge = document.getElementById('ctxBadge');
  const fill = document.getElementById('ctxBarFill');
  const label = document.getElementById('ctxLabel');
  if (!badge) return;
  badge.style.display = 'flex';
  const pct = Math.min(ctxTokens / Math.max(ctxLimit, 1) * 100, 100);
  fill.style.width = pct + '%';
  fill.classList.remove('warn', 'full');
  if (pct > 85) fill.classList.add('full');
  else if (pct > 60) fill.classList.add('warn');
  label.textContent = _fmtTokens(ctxTokens) + ' / ' + _fmtTokens(ctxLimit) + ' ctx';
  label.title = 'Model: ' + model + ' — Context used: ' + ctxTokens + ' / ' + ctxLimit + ' tokens (' + pct.toFixed(1) + '%)';
}

async function loadProjModels() {
  try {
    const r = await fetch(API + '/api/models');
    if (!r.ok) return;
    const d = await r.json();
    _projModelInfo = d;
    const sel = document.getElementById('projModelSelect');
    if (!sel) return;
    sel.innerHTML = '';
    const readyProviders = (d.providers || []).filter(p => p && p.ready);
    for (const p of readyProviders) {
      const models = Array.isArray(p.selectable_models) && p.selectable_models.length ? p.selectable_models : [p.model].filter(Boolean);
      for (const modelName of models) {
        const opt = document.createElement('option');
        opt.value = p.provider + '::' + modelName;
        opt.textContent = p.provider + ' / ' + modelName;
        opt.title = (p.note || 'Ready') + ' · Context: ' + _fmtTokens(p.context_window || 128000);
        sel.appendChild(opt);
      }
    }
    const defaultValue = ((d.active_provider || '') && (d.active_model || '')) ? (d.active_provider + '::' + d.active_model) : '';
    if (defaultValue && Array.from(sel.options).some(opt => opt.value === defaultValue)) {
      sel.value = defaultValue;
    } else if (sel.options.length) {
      sel.selectedIndex = 0;
    } else {
      const defOpt = document.createElement('option');
      defOpt.value = '';
      defOpt.textContent = 'No ready models';
      defOpt.title = 'Configure an API key or start a local runtime to use project AI mode.';
      sel.appendChild(defOpt);
    }
    projModelChanged();
    if (d.active_context_window) {
      _updateCtxBadge(0, d.active_context_window, d.active_model || '');
    }
  } catch(_) {}
}

function updateProjectChatControls() {
  document.querySelectorAll('.chat-mode-chip').forEach(btn => btn.classList.toggle('active', btn.dataset.chatMode === _projectChatMode));
  const shellChip = document.getElementById('projShellToggleChip');
  const shellToggle = document.getElementById('projShellToggle');
  const destructiveChip = document.getElementById('projDestructiveToggleChip');
  const destructiveToggle = document.getElementById('projDestructiveToggle');
  const note = document.getElementById('projChatModeNote');
  if (shellToggle) shellToggle.checked = !!_projectChatShell;
  if (destructiveToggle) destructiveToggle.checked = !!_projectChatAllowDestructive;
  if (shellChip) shellChip.classList.toggle('active', !!_projectChatShell);
  if (destructiveChip) destructiveChip.classList.toggle('active', !!_projectChatAllowDestructive);
  if (note) {
    const modeCopy = {
      auto: 'Auto routes questions to quick analysis and action requests to the execution runtime.',
      ask: 'Ask keeps the chat read-only and uses fast project-aware answers.',
      ai: 'AI Mode uses the runtime so Kendr can edit files, run commands, and handle git work inside the open project.',
    }[_projectChatMode] || '';
    const shellCopy = _projectChatShell ? 'Shell automation is enabled.' : 'Shell automation is disabled.';
    const destructiveCopy = _projectChatAllowDestructive ? 'Destructive changes are allowed.' : 'Destructive changes stay blocked.';
    note.textContent = modeCopy + ' ' + shellCopy + ' ' + destructiveCopy;
  }
}

function setProjectChatMode(mode) {
  _projectChatMode = ['auto', 'ask', 'ai'].includes(mode) ? mode : 'auto';
  try { localStorage.setItem('kendr.project_chat_mode', _projectChatMode); } catch(_) {}
  updateProjectChatControls();
}

function setProjectChatShell(enabled) {
  _projectChatShell = !!enabled;
  try { localStorage.setItem('kendr.project_chat_shell', _projectChatShell ? '1' : '0'); } catch(_) {}
  updateProjectChatControls();
}

function setProjectChatDestructive(enabled) {
  _projectChatAllowDestructive = !!enabled;
  try { localStorage.setItem('kendr.project_chat_destructive', _projectChatAllowDestructive ? '1' : '0'); } catch(_) {}
  updateProjectChatControls();
}

function _projectChatRequestIntent(text) {
  const body = String(text || '').trim().toLowerCase();
  if (!body) return 'ask';
  const actionPatterns = [
    /^\s*(please\s+)?(delete|remove|rename|move|create|add|update|change|edit|fix|refactor|implement|write|generate|scaffold|commit|push|pull|merge|install|run|start|stop|restart|build|test|deploy|ship)\b/,
    /\b(can you|could you|please|go ahead and|try to|help me)\s+(delete|remove|rename|move|create|add|update|change|edit|fix|refactor|implement|write|generate|scaffold|commit|push|pull|merge|install|run|start|stop|restart|build|test|deploy|ship)\b/,
    /\b(make the change|apply the change|make these changes|ship it|open a pr)\b/,
  ];
  const questionPatterns = [
    /^\s*(what|why|how|where|which|who|when|analyse|analyze|review|explain|summari[sz]e|tell me|walk me through|inspect|compare|find)\b/,
    /\bwhat does\b/,
    /\bhow does\b/,
  ];
  const actionWords = /\b(delete|remove|rename|move|create|add|update|change|edit|fix|refactor|implement|write|generate|scaffold|commit|push|pull|merge|install|run|start|stop|restart|build|test|deploy|ship)\b/;
  const isAction = actionPatterns.some(pattern => pattern.test(body)) || (!questionPatterns.some(pattern => pattern.test(body)) && actionWords.test(body));
  if (isAction) return 'execute';
  if (questionPatterns.some(pattern => pattern.test(body)) || body.includes('?')) return 'ask';
  return 'ask';
}

function _projectChatLooksDestructive(text) {
  return /\b(delete|remove|rm|erase|wipe|drop|destroy|purge|clean out|reset)\b/i.test(String(text || ''));
}

function _projectChatRoute(text) {
  if (_projectChatMode === 'ask') return 'ask';
  if (_projectChatMode === 'ai') return 'execute';
  return _projectChatRequestIntent(text);
}

function _setProjectChatProgress(bubble, text) {
  if (!bubble) return;
  bubble.innerHTML = '<div class="plain-text" style="color:var(--muted);font-size:11px">' + escapeHtml(text || 'Working...') + '</div>';
}

function _projectChatProgressText(payload, fallback = 'Working...') {
  const data = payload || {};
  const agent = String(data.agent || '').trim();
  const message = String(data.message || data.text || '').trim();
  const status = String(data.status || '').trim();
  if (message && agent) return agent + ': ' + message;
  if (message) return message;
  if (agent && status) return agent + ' · ' + status;
  if (agent) return agent;
  return status || fallback;
}

async function _sendProjectAsk(text, bubble) {
  const payload = {
    text,
    project_id: _activeProjectId,
    project_root: _activeProjectPath,
    project_name: _activeProjectName || '',
  };
  if (_projSelectedModel) payload.model = _projSelectedModel;
  if (_projSelectedProvider) payload.provider = _projSelectedProvider;
  _recordProjectActivity({
    kind: 'analysis',
    title: 'Project question received',
    status: 'running',
    detail: text,
    started_at: new Date().toISOString(),
    cwd: _activeProjectPath || '',
    task: 'Inspect project and answer the question',
    subtask: 'Project ask',
  });
  const resp = await fetch(API + '/api/project/ask', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  if (!resp.ok || !resp.body) {
    const txt = await resp.text();
    _recordProjectActivity({
      kind: 'analysis',
      title: 'Project ask failed',
      status: 'failed',
      detail: txt.slice(0, 200) || 'Server error',
      completed_at: new Date().toISOString(),
      cwd: _activeProjectPath || '',
      task: 'Inspect project and answer the question',
      subtask: 'Project ask',
    });
    bubble.innerHTML = '<span style="color:var(--crimson)">\u26A0 Server error: ' + escapeHtml(txt.slice(0, 200)) + '</span>';
    return;
  }
  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  const scroller = document.getElementById('chatMessages');
  let buf = '';
  let answered = false;
  const streamedActivities = [];

  function _parseSseLine(chunk) {
    const lines = chunk.split('\n');
    let evName = '', evData = '';
    for (const line of lines) {
      if (line.startsWith('event: ')) evName = line.slice(7).trim();
      else if (line.startsWith('data: ')) evData = line.slice(6).trim();
    }
    return { evName, evData };
  }

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const parts = buf.split('\n\n');
    buf = parts.pop() || '';
    for (const chunk of parts) {
      if (!chunk.trim()) continue;
      const { evName, evData } = _parseSseLine(chunk);
      if (!evName || !evData) continue;
      try {
        const data = JSON.parse(evData);
        if (evName === 'log') {
          if (!answered) {
            _setProjectChatProgress(bubble, data.msg || 'Processing...');
            scroller.scrollTop = 999999;
          }
        } else if (evName === 'activity') {
          streamedActivities.unshift(data || {});
          _recordProjectActivity(data, { task: 'Inspect project and answer the question' });
          _upsertProjectBubbleTrace(bubble, streamedActivities, 'Project Analysis');
        } else if (evName === 'result') {
          answered = true;
          const answer = data.answer || '(No response)';
          setChatBubbleContent(bubble, answer, isLikelyMarkdown(answer) ? 'markdown' : 'text', 'agent');
          if (Array.isArray(data.activities) && data.activities.length) {
            _recordProjectActivities(data.activities, { task: 'Inspect project and answer the question' });
            _upsertProjectBubbleTrace(bubble, data.activities, 'Project Analysis');
          } else if (streamedActivities.length) {
            _upsertProjectBubbleTrace(bubble, streamedActivities, 'Project Analysis');
          }
          if (data.context_tokens && data.model_context_limit) {
            const ctxMeta = document.createElement('div');
            ctxMeta.className = 'msg-ctx';
            const pct = Math.round(data.context_pct || 0);
            ctxMeta.innerHTML = '<span>\uD83D\uDCAC ' + escapeHtml(data.model || '') + '</span>'
              + '<span style="opacity:0.6">\u2022</span>'
              + '<span>' + _fmtTokens(data.context_tokens) + ' / ' + _fmtTokens(data.model_context_limit) + ' ctx (' + pct + '%)'
              + (data.kendr_md_generated ? ' \u2728 kendr.md created' : data.kendr_md_loaded ? ' \uD83D\uDCCB kendr.md' : '') + '</span>';
            bubble.appendChild(ctxMeta);
            _updateCtxBadge(data.context_tokens, data.model_context_limit, data.model || '');
          }
          scroller.scrollTop = 999999;
        } else if (evName === 'error') {
          bubble.innerHTML = '<span style="color:var(--crimson)">\u26A0 ' + escapeHtml(data.error || 'Unknown error') + '</span>';
          if (Array.isArray(data.activities) && data.activities.length) {
            _recordProjectActivities(data.activities, { task: 'Inspect project and answer the question' });
            _upsertProjectBubbleTrace(bubble, data.activities, 'Project Analysis');
          } else if (streamedActivities.length) {
            _upsertProjectBubbleTrace(bubble, streamedActivities, 'Project Analysis');
          }
        }
      } catch(_) {}
    }
  }
  if (!answered) bubble.innerHTML = '<em style="color:var(--muted)">No response received.</em>';
}

function _streamProjectRuntime(runId, bubble) {
  return new Promise(resolve => {
    if (_sseSource) {
      try { _sseSource.close(); } catch(_) {}
      _sseSource = null;
    }
    const evtSrc = new EventSource(API + '/api/stream?run_id=' + encodeURIComponent(runId));
    _sseSource = evtSrc;
    let finished = false;

    function finish() {
      if (finished) return;
      finished = true;
      _stopProjectRuntimeActivityPolling();
      if (_sseSource === evtSrc) _sseSource = null;
      try { evtSrc.close(); } catch(_) {}
      resolve();
    }

    _startProjectRuntimeActivityPolling(runId, bubble);

    evtSrc.addEventListener('status', event => {
      try {
        const data = JSON.parse(event.data);
        _setProjectChatProgress(bubble, _projectChatProgressText(data, 'Agents mobilizing...'));
      } catch(_) {}
    });

    evtSrc.addEventListener('step', event => {
      try {
        const data = JSON.parse(event.data);
        _setProjectChatProgress(bubble, _projectChatProgressText(data, 'Working...'));
      } catch(_) {}
    });

    evtSrc.addEventListener('result', event => {
      try {
        const data = JSON.parse(event.data);
        const output = data.final_output || data.output || data.draft_response || data.summary || '(Run completed)';
        setChatBubbleContent(bubble, output, isLikelyMarkdown(output) ? 'markdown' : 'text', 'agent');
        const awaiting = !!(
          data.awaiting_user_input
          || String(data.status || '').toLowerCase() === 'awaiting_user_input'
          || data.plan_waiting_for_approval
          || data.plan_needs_clarification
          || data.pending_user_input_kind
          || data.approval_pending_scope
          || data.pending_user_question
          || (data.approval_request && typeof data.approval_request === 'object' && Object.keys(data.approval_request).length > 0)
        );
        if (awaiting) {
          _recordProjectActivity({
            kind: 'runtime',
            title: 'Runtime awaiting approval',
            status: 'pending',
            detail: data.pending_user_question || 'This run is waiting for your response.',
            completed_at: new Date().toISOString(),
            task: 'Execute project task',
            subtask: runId,
            run_id: data.run_id || runId,
          });
          _projectAwaitingContext = {
            runId: data.run_id || runId,
            workflowId: data.workflow_id || runId,
            attemptId: data.attempt_id || runId,
            workingDir: data.working_directory || _activeProjectPath || '',
            prompt: data.pending_user_question || output || 'This project run is waiting for your response.',
            approvalRequest: data.approval_request || null,
            pendingKind: data.pending_user_input_kind || '',
            scope: data.approval_pending_scope || '',
          };
          _openProjectApprovalModal(_projectAwaitingContext);
        } else if (data.run_id || runId) {
          _projectAwaitingContext = null;
          _closeProjectApprovalModal();
          _recordProjectActivity({
            kind: 'runtime',
            title: 'Runtime completed',
            status: 'completed',
            detail: 'Agent execution finished and returned a final output.',
            completed_at: new Date().toISOString(),
            task: 'Execute project task',
            subtask: runId,
            run_id: data.run_id || runId,
          });
        }
      } catch(_) {}
    });

    evtSrc.addEventListener('error', event => {
      let message = 'Execution failed';
      try {
        const data = JSON.parse(event.data);
        message = data.message || data.error || message;
      } catch(_) {}
      bubble.innerHTML = '<span style="color:var(--crimson)">\u26A0 ' + escapeHtml(message) + '</span>';
      _projectAwaitingContext = null;
      _closeProjectApprovalModal();
      _recordProjectActivity({
        kind: 'runtime',
        title: 'Runtime failed',
        status: 'failed',
        detail: message,
        completed_at: new Date().toISOString(),
        task: 'Execute project task',
        subtask: runId,
        run_id: runId,
      });
      finish();
    });

    evtSrc.addEventListener('done', () => finish());

    evtSrc.onerror = () => {
      if (evtSrc.readyState === EventSource.CLOSED) finish();
    };
  });
}

async function _sendProjectResume(replyText, approvalContext, existingBubble, appendUserBubble = true) {
  const context = approvalContext || _projectAwaitingContext;
  if (!context || !_activeProjectPath) return;
  if (appendUserBubble) appendMsg('user', replyText, isLikelyMarkdown(replyText) ? 'markdown' : 'text');
  const bubble = existingBubble || (() => {
    const agentDiv = appendMsg('agent', '');
    const created = agentDiv.querySelector('.msg-bubble');
    created.innerHTML = '<span class="spinner"></span>';
    return created;
  })();
  bubble.innerHTML = '<span class="spinner"></span>';
  // Every continuation turn should create a new run record.
  const runId = 'project-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
  const workflowId = (context && context.workflowId) ? context.workflowId : ((context && context.runId) ? context.runId : runId);
  const payload = {
    text: replyText,
    channel: 'project_ui',
    sender_id: 'project_ui_user',
    chat_id: _activeProjectId || '',
    run_id: runId,
    workflow_id: workflowId,
    attempt_id: runId,
    workflow_type: 'project_workbench',
    resume_dir: context.workingDir || _activeProjectPath || '',
    working_directory: context.workingDir || _activeProjectPath || '',
    project_id: _activeProjectId || '',
    project_root: _activeProjectPath || '',
    project_name: _activeProjectName || '',
    force: true,
  };
  if (_projSelectedModel) payload.model = _projSelectedModel;
  if (_projSelectedProvider) payload.provider = _projSelectedProvider;
  if (_activeProjectPath) payload.privileged_allowed_paths = [_activeProjectPath];
  if (_projectChatShell) {
    payload.shell_auto_approve = true;
    payload.privileged_approval_note = 'Approved via project workbench AI Mode';
  }
  if (_projectChatAllowDestructive) payload.privileged_allow_destructive = true;
  _recordProjectActivity({
    kind: 'runtime',
    title: 'Approval reply submitted',
    status: 'running',
    detail: replyText,
    started_at: new Date().toISOString(),
    cwd: _activeProjectPath || '',
    task: 'Resume project task',
    subtask: runId,
    run_id: runId,
  });
  _setProjectChatProgress(bubble, 'Resuming paused run...');
  const resp = await fetch(API + '/api/chat/resume', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || data.error) {
    const detail = data.detail ? ': ' + data.detail : '';
    bubble.innerHTML = '<span style="color:var(--crimson)">\u26A0 ' + escapeHtml((data.error || 'Resume failed') + detail) + '</span>';
    _recordProjectActivity({
      kind: 'runtime',
      title: 'Resume request rejected',
      status: 'failed',
      detail: (data.error || 'Resume failed') + detail,
      completed_at: new Date().toISOString(),
      cwd: _activeProjectPath || '',
      task: 'Resume project task',
      subtask: runId,
      run_id: runId,
    });
    return;
  }
  if (data.streaming) {
    await _streamProjectRuntime(runId, bubble);
    return;
  }
  const output = data.final_output || data.output || data.draft_response || data.summary || '(Run completed)';
  setChatBubbleContent(bubble, output, isLikelyMarkdown(output) ? 'markdown' : 'text', 'agent');
}

function _submitProjectApproval(action) {
  if (!_projectAwaitingContext) return;
  let reply = '';
  if (action === 'approve') reply = 'approve';
  else if (action === 'reject') reply = 'no, reject this and revise it';
  else {
    reply = String((document.getElementById('projectApprovalSuggestion') || {}).value || '').trim();
    if (!reply) return;
  }
  _closeProjectApprovalModal();
  const previousContext = _projectAwaitingContext;
  _projectAwaitingContext = null;
  _sendProjectResume(reply, previousContext).catch(err => {
    _projectAwaitingContext = previousContext;
    appendSysMsg('Resume failed: ' + String(err));
  });
}

async function _sendProjectRuntime(text, bubble) {
  const runId = 'project-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
  const workflowId = runId;
  const payload = {
    text,
    channel: 'project_ui',
    sender_id: 'project_ui_user',
    chat_id: _activeProjectId || '',
    run_id: runId,
    workflow_id: workflowId,
    attempt_id: runId,
    workflow_type: 'project_workbench',
    project_id: _activeProjectId || '',
    project_root: _activeProjectPath || '',
    project_name: _activeProjectName || '',
    working_directory: _activeProjectPath || '',
  };
  if (_projSelectedModel) payload.model = _projSelectedModel;
  if (_projSelectedProvider) payload.provider = _projSelectedProvider;
  if (_activeProjectPath) payload.privileged_allowed_paths = [_activeProjectPath];
  if (_projectChatShell) {
    payload.shell_auto_approve = true;
    payload.privileged_approval_note = 'Approved via project workbench AI Mode';
  }
  if (_projectChatAllowDestructive) payload.privileged_allow_destructive = true;
  _recordProjectActivity({
    kind: 'runtime',
    title: 'Runtime started',
    status: 'running',
    detail: text,
    started_at: new Date().toISOString(),
    cwd: _activeProjectPath || '',
    task: 'Execute project task',
    subtask: runId,
    run_id: runId,
  });
  _setProjectChatProgress(bubble, 'Agents mobilizing...');
  const resp = await fetch(API + '/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload)
  });
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok || data.error) {
    const detail = data.detail ? ': ' + data.detail : '';
    _recordProjectActivity({
      kind: 'runtime',
      title: 'Runtime request rejected',
      status: 'failed',
      detail: (data.error || 'Execution failed') + detail,
      completed_at: new Date().toISOString(),
      cwd: _activeProjectPath || '',
      task: 'Execute project task',
      subtask: runId,
      run_id: runId,
    });
    bubble.innerHTML = '<span style="color:var(--crimson)">\u26A0 ' + escapeHtml((data.error || 'Execution failed') + detail) + '</span>';
    return;
  }
  if (data.streaming) {
    await _streamProjectRuntime(runId, bubble);
    return;
  }
  const output = data.final_output || data.output || data.draft_response || data.summary || '(Run completed)';
  setChatBubbleContent(bubble, output, isLikelyMarkdown(output) ? 'markdown' : 'text', 'agent');
  _recordProjectActivity({
    kind: 'runtime',
    title: 'Runtime completed',
    status: 'completed',
    detail: 'Execution returned a non-streaming result.',
    completed_at: new Date().toISOString(),
    cwd: _activeProjectPath || '',
    task: 'Execute project task',
    subtask: runId,
    run_id: runId,
  });
}

async function sendChat() {
  const inp = document.getElementById('chatInput');
  const btn = document.getElementById('sendBtn');
  const rawText = inp.value.trim();
  const text = _buildTextWithAttachments(rawText, _projChatAttachments);
  if (!text) return;
  if (!_activeProjectPath) { appendSysMsg('Please open a project first.'); return; }
  const pendingApprovalContext = _projectAwaitingContext;
  const resumingApproval = !!pendingApprovalContext;
  const route = _projectChatRoute(rawText || text);
  if (route === 'execute' && _projectChatLooksDestructive(text) && !_projectChatAllowDestructive) {
    appendSysMsg('This request looks destructive. Enable Destructive in the project chat controls before asking Kendr to delete, remove, reset, or wipe project files.');
    return;
  }
  inp.value = '';
  inp.style.height = 'auto';
  _projChatAttachments = [];
  _renderAttachChips(_projChatAttachments, 'projChatAttachChips', 'removeProjChatAttachment');
  btn.disabled = true;
  _closeProjectApprovalModal();
  appendMsg('user', text, isLikelyMarkdown(text) ? 'markdown' : 'text');
  // Intercept file-download requests: resolve locally without hitting the agent
  if (!resumingApproval) {
    const fileReqHtml = _tryHandleFileRequest(text);
    if (fileReqHtml) {
      const agentDiv = appendMsg('agent', '');
      agentDiv.querySelector('.msg-bubble').innerHTML = '<div>Here are the available report files:</div>' + fileReqHtml;
      btn.disabled = false;
      return;
    }
  }
  const agentDiv = appendMsg('agent', '');
  const bubble = agentDiv.querySelector('.msg-bubble');
  bubble.innerHTML = '<span class="spinner"></span>';
  try {
    if (resumingApproval) {
      _projectAwaitingContext = null;
      await _sendProjectResume(text, pendingApprovalContext, bubble, false);
    } else if (route === 'execute') await _sendProjectRuntime(text, bubble);
    else await _sendProjectAsk(text, bubble);
    if (_activeProjectId) await loadProjectChatHistory();
    btn.disabled = false;
  } catch(e) {
    bubble.innerHTML = '<span style="color:var(--crimson)">Error: ' + escapeHtml(String(e)) + '</span>';
    btn.disabled = false;
  }
}

// ── Terminal ──────────────────────────────────────────────────────────────────
function termKeydown(e) {
  if (e.key === 'Enter') { e.preventDefault(); runTermCmd(); }
  else if (e.key === 'ArrowUp') { e.preventDefault(); if (_termHistIdx < _termHistory.length-1) { _termHistIdx++; document.getElementById('termInput').value = _termHistory[_termHistIdx]; } }
  else if (e.key === 'ArrowDown') { e.preventDefault(); if (_termHistIdx > 0) { _termHistIdx--; document.getElementById('termInput').value = _termHistory[_termHistIdx]; } else { _termHistIdx = -1; document.getElementById('termInput').value = ''; } }
}

async function runTermCmd() {
  const input = document.getElementById('termInput');
  const output = document.getElementById('termOutput');
  const cmd = input.value.trim();
  if (!cmd) return;
  if (!_activeProjectPath) { output.textContent += '\n\u26A0 Open a project first.'; return; }
  _termHistory.unshift(cmd); _termHistIdx = -1;
  input.value = '';
  output.textContent += '\n$ ' + cmd + '\n';
  output.scrollTop = output.scrollHeight;
  const startedAt = new Date().toISOString();
  const startedTs = Date.now();
  _recordProjectActivity({
    kind: 'command',
    title: 'Running terminal command',
    status: 'running',
    command: cmd,
    started_at: startedAt,
    cwd: _activeProjectPath || '',
    task: 'Execute terminal command',
    subtask: 'Project terminal',
  });
  try {
    const r = await fetch(API + '/api/projects/shell', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ command: cmd, project_id: _activeProjectId, cwd: _activeProjectPath })
    });
    const d = await r.json();
    if (d.stdout) output.textContent += d.stdout;
    if (d.stderr) output.textContent += d.stderr;
    if (!d.ok && !d.stderr && !d.stdout) output.textContent += '(exit code ' + d.returncode + ')';
    _recordProjectActivity({
      kind: 'command',
      title: d.ok ? 'Terminal command completed' : 'Terminal command failed',
      status: d.ok ? 'completed' : 'failed',
      detail: d.stderr || d.stdout || ('Exit code ' + d.returncode),
      command: d.command || cmd,
      cwd: d.cwd || _activeProjectPath || '',
      started_at: d.started_at || startedAt,
      completed_at: d.completed_at || new Date().toISOString(),
      duration_ms: d.duration_ms,
      duration_label: d.duration_label,
      exit_code: d.returncode,
      task: 'Execute terminal command',
      subtask: 'Project terminal',
    });
  } catch(e) {
    output.textContent += 'Request error: ' + e;
    _recordProjectActivity({
      kind: 'command',
      title: 'Terminal command failed',
      status: 'failed',
      detail: String(e),
      command: cmd,
      cwd: _activeProjectPath || '',
      started_at: startedAt,
      completed_at: new Date().toISOString(),
      duration_ms: Math.max(0, Date.now() - startedTs),
      duration_label: _formatStepDuration({ duration_ms: Math.max(0, Date.now() - startedTs) }),
      task: 'Execute terminal command',
      subtask: 'Project terminal',
    });
  }
  output.scrollTop = output.scrollHeight;
  if (output.textContent.length > 30000) output.textContent = output.textContent.slice(-20000);
}

// ── Services ─────────────────────────────────────────────────────────────────
function serviceStateClass(status) {
  if (status === 'running') return 'running';
  if (status === 'degraded') return 'degraded';
  return 'stopped';
}

function serviceStateText(service) {
  return service.status || (service.running ? 'running' : 'stopped');
}

async function loadProjectServices() {
  const listEl = document.getElementById('servicesList');
  if (!_activeProjectId) {
    _servicesCache = [];
    listEl.innerHTML = 'Open a project to manage its services.';
    updateWorkbenchChrome();
    return;
  }
  listEl.innerHTML = '<div class="service-empty"><span class="spinner"></span> Loading tracked services...</div>';
  const startedAt = new Date().toISOString();
  const startedTs = Date.now();
  try {
    const r = await fetch(API + '/api/projects/' + _activeProjectId + '/services');
    const payload = await r.json();
    const services = payload.services || [];
    _servicesCache = services;
    _recordProjectActivity({
      kind: 'service_scan',
      title: 'Services refreshed',
      status: 'completed',
      detail: `Loaded ${services.length} tracked services.`,
      started_at: startedAt,
      completed_at: new Date().toISOString(),
      duration_ms: Math.max(0, Date.now() - startedTs),
      duration_label: _formatStepDuration({ duration_ms: Math.max(0, Date.now() - startedTs) }),
      cwd: _activeProjectPath || '',
      task: 'Inspect project services',
      subtask: 'Refresh tracked services',
    });
    if (!services.length) {
      listEl.innerHTML = '<div class="service-empty">No tracked services yet. Start one above so Kendr can monitor it, include it in project context, and surface it in <code>kendr gateway status</code>.</div>';
      if (!_activeServiceLogId) {
        document.getElementById('serviceLogMeta').textContent = 'Select a service to inspect its recent logs.';
        document.getElementById('serviceLogOutput').textContent = 'No log selected.';
      }
      updateWorkbenchChrome();
      return;
    }
    listEl.innerHTML = services.map(service => {
      const state = serviceStateText(service);
      const stateClass = serviceStateClass(state);
      const port = service.port ? ('port ' + service.port) : 'no port';
      const pid = service.pid ? ('pid ' + service.pid) : 'pid -';
      const kind = service.kind || 'service';
      const health = service.health_ok ? 'healthy' : (service.health_url ? 'health unknown' : 'no healthcheck');
      const command = esc(service.command || '(no command stored)');
      const logPath = esc(service.log_path || '-');
      const url = service.url ? `<a href="${esc(service.url)}" target="_blank" rel="noreferrer" style="color:var(--teal);text-decoration:none">${esc(service.url)}</a>` : '<span style="color:var(--muted)">no URL</span>';
      const startBtn = service.running
        ? `<button class="btn btn-outline" onclick="restartProjectService('${esc(service.id)}')">&#x21BB; Restart</button>`
        : `<button class="btn btn-primary" onclick="startTrackedProjectService('${esc(service.id)}')">&#x25B6; Start</button>`;
      const stopBtn = service.running
        ? `<button class="btn btn-danger" onclick="stopProjectService('${esc(service.id)}')">&#x23F9; Stop</button>`
        : `<button class="btn btn-outline" onclick="stopProjectService('${esc(service.id)}')">Mark Stopped</button>`;
      return `
      <div class="service-section">
        <div style="display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap">
          <div>
            <div style="font-size:14px;font-weight:700">${esc(service.name || service.id)}</div>
            <div style="font-size:11px;color:var(--muted);margin-top:4px">id: <code>${esc(service.id)}</code></div>
          </div>
          <div class="service-pill ${stateClass}">${esc(state)}</div>
        </div>
        <div class="service-meta">
          <div class="service-pill">${esc(kind)}</div>
          <div class="service-pill">${esc(port)}</div>
          <div class="service-pill">${esc(pid)}</div>
          <div class="service-pill">${esc(health)}</div>
        </div>
        <div class="service-command">${command}</div>
        <div style="font-size:12px;color:var(--muted);margin-top:10px">cwd: ${esc(service.cwd || _activeProjectPath || '-')}</div>
        <div style="font-size:12px;color:var(--muted);margin-top:6px">url: ${url}</div>
        <div style="font-size:12px;color:var(--muted);margin-top:6px">log: <code>${logPath}</code></div>
        <div class="git-actions" style="margin-top:12px">
          ${startBtn}
          ${stopBtn}
          <button class="btn btn-outline" onclick="loadProjectServiceLog('${esc(service.id)}')">&#x1F4DC; View Logs</button>
        </div>
      </div>`;
    }).join('');
    if (_activeServiceLogId) {
      const exists = services.some(service => service.id === _activeServiceLogId);
      if (exists) loadProjectServiceLog(_activeServiceLogId);
    }
  } catch(e) {
    _servicesCache = [];
    listEl.innerHTML = '<div class="service-empty" style="color:var(--crimson)">Error: ' + esc(String(e)) + '</div>';
    _recordProjectActivity({
      kind: 'service_scan',
      title: 'Services refresh failed',
      status: 'failed',
      detail: String(e),
      started_at: startedAt,
      completed_at: new Date().toISOString(),
      duration_ms: Math.max(0, Date.now() - startedTs),
      duration_label: _formatStepDuration({ duration_ms: Math.max(0, Date.now() - startedTs) }),
      cwd: _activeProjectPath || '',
      task: 'Inspect project services',
      subtask: 'Refresh tracked services',
    });
  }
  updateWorkbenchChrome();
}

async function createProjectService() {
  const msg = document.getElementById('svcMsg');
  if (!_activeProjectId) { msg.style.color = 'var(--crimson)'; msg.textContent = 'Open a project first.'; return; }
  const name = document.getElementById('svcName').value.trim();
  const command = document.getElementById('svcCommand').value.trim();
  const kind = document.getElementById('svcKind').value.trim();
  const portVal = document.getElementById('svcPort').value.trim();
  const health_url = document.getElementById('svcHealthUrl').value.trim();
  let cwd = document.getElementById('svcCwd').value.trim();
  if (!name || !command) {
    msg.style.color = 'var(--crimson)';
    msg.textContent = 'Service name and command are required.';
    return;
  }
  if (cwd && _activeProjectPath && !cwd.startsWith('/') && !cwd.match(/^[A-Za-z]:\\/)) {
    cwd = (_activeProjectPath.replace(/[\\\/]+$/, '')) + '/' + cwd.replace(/^\.?\//, '');
  }
  msg.style.color = 'var(--muted)';
  msg.textContent = 'Starting service...';
  try {
    const payload = { name, command, kind, cwd, health_url };
    if (portVal) payload.port = Number(portVal);
    const r = await fetch(API + '/api/projects/' + _activeProjectId + '/services/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || 'Failed to start service');
    msg.style.color = 'var(--teal)';
    msg.textContent = 'Service started: ' + (d.name || d.id);
    _activeServiceLogId = d.id || '';
    document.getElementById('svcCommand').value = '';
    await loadProjectServices();
    if (_activeServiceLogId) await loadProjectServiceLog(_activeServiceLogId);
  } catch(e) {
    msg.style.color = 'var(--crimson)';
    msg.textContent = 'Error: ' + e;
  }
}

async function startTrackedProjectService(serviceId) {
  const msg = document.getElementById('svcMsg');
  msg.style.color = 'var(--muted)';
  msg.textContent = 'Starting tracked service...';
  try {
    const r = await fetch(API + '/api/projects/' + _activeProjectId + '/services/' + encodeURIComponent(serviceId) + '/start', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({}),
    });
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || 'Failed to start service');
    msg.style.color = 'var(--teal)';
    msg.textContent = 'Service started: ' + (d.name || d.id || serviceId);
    _activeServiceLogId = d.id || serviceId;
    await loadProjectServices();
    await loadProjectServiceLog(_activeServiceLogId);
  } catch(e) {
    msg.style.color = 'var(--crimson)';
    msg.textContent = 'Error: ' + e;
  }
}

async function stopProjectService(serviceId) {
  const msg = document.getElementById('svcMsg');
  msg.style.color = 'var(--muted)';
  msg.textContent = 'Stopping service...';
  try {
    const r = await fetch(API + '/api/projects/' + _activeProjectId + '/services/' + encodeURIComponent(serviceId) + '/stop', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({}),
    });
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || 'Failed to stop service');
    msg.style.color = 'var(--teal)';
    msg.textContent = 'Service stopped: ' + (d.name || d.id || serviceId);
    _activeServiceLogId = d.id || serviceId;
    await loadProjectServices();
    await loadProjectServiceLog(_activeServiceLogId);
  } catch(e) {
    msg.style.color = 'var(--crimson)';
    msg.textContent = 'Error: ' + e;
  }
}

async function restartProjectService(serviceId) {
  const msg = document.getElementById('svcMsg');
  msg.style.color = 'var(--muted)';
  msg.textContent = 'Restarting service...';
  try {
    const r = await fetch(API + '/api/projects/' + _activeProjectId + '/services/' + encodeURIComponent(serviceId) + '/restart', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({}),
    });
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || 'Failed to restart service');
    msg.style.color = 'var(--teal)';
    msg.textContent = 'Service restarted: ' + (d.name || d.id || serviceId);
    _activeServiceLogId = d.id || serviceId;
    await loadProjectServices();
    await loadProjectServiceLog(_activeServiceLogId);
  } catch(e) {
    msg.style.color = 'var(--crimson)';
    msg.textContent = 'Error: ' + e;
  }
}

async function loadProjectServiceLog(serviceId) {
  if (!_activeProjectId || !serviceId) return;
  _activeServiceLogId = serviceId;
  const meta = document.getElementById('serviceLogMeta');
  const out = document.getElementById('serviceLogOutput');
  meta.textContent = 'Loading log tail for ' + serviceId + '...';
  out.textContent = '';
  const startedAt = new Date().toISOString();
  const startedTs = Date.now();
  try {
    const r = await fetch(API + '/api/projects/' + _activeProjectId + '/services/' + encodeURIComponent(serviceId) + '/log');
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || 'Failed to load log');
    meta.textContent = (d.log_path || serviceId) + (d.truncated ? ' (tail)' : '');
    out.textContent = d.content || '(log file is empty)';
    out.scrollTop = out.scrollHeight;
    _recordProjectActivity({
      kind: 'service_log',
      title: 'Service log loaded',
      status: 'completed',
      detail: d.log_path || serviceId,
      started_at: startedAt,
      completed_at: new Date().toISOString(),
      duration_ms: Math.max(0, Date.now() - startedTs),
      duration_label: _formatStepDuration({ duration_ms: Math.max(0, Date.now() - startedTs) }),
      cwd: _activeProjectPath || '',
      task: 'Inspect project services',
      subtask: 'Read service log',
    });
  } catch(e) {
    meta.textContent = 'Log load failed';
    out.textContent = 'Error: ' + e;
    _recordProjectActivity({
      kind: 'service_log',
      title: 'Service log load failed',
      status: 'failed',
      detail: String(e),
      started_at: startedAt,
      completed_at: new Date().toISOString(),
      duration_ms: Math.max(0, Date.now() - startedTs),
      duration_label: _formatStepDuration({ duration_ms: Math.max(0, Date.now() - startedTs) }),
      cwd: _activeProjectPath || '',
      task: 'Inspect project services',
      subtask: 'Read service log',
    });
  }
}

// ── Git ───────────────────────────────────────────────────────────────────────
async function loadGitStatus() {
  if (!_activeProjectId) return;
  const panel = document.getElementById('gitPanel');
  panel.innerHTML = '<div style="color:var(--muted);font-size:13px"><span class="spinner"></span> Loading git status...</div>';
  const startedAt = new Date().toISOString();
  const startedTs = Date.now();
  try {
    const r = await fetch(API + '/api/projects/' + _activeProjectId + '/git/status');
    const s = await r.json();
    _gitStatusCache = s;
    _recordProjectActivity({
      kind: 'git',
      title: s.is_git ? 'Git status loaded' : 'Project is not a git repo',
      status: s.is_git ? 'completed' : 'info',
      detail: s.is_git ? `Branch ${s.branch || 'unknown'} with ${((s.changed || []).length + (s.staged || []).length + (s.untracked || []).length)} visible changes.` : 'Initialize git to unlock source-control workflows.',
      started_at: startedAt,
      completed_at: new Date().toISOString(),
      duration_ms: Math.max(0, Date.now() - startedTs),
      duration_label: _formatStepDuration({ duration_ms: Math.max(0, Date.now() - startedTs) }),
      cwd: _activeProjectPath || '',
      task: 'Inspect git state',
      subtask: 'Load repository status',
    });
    if (!s.is_git) {
      panel.innerHTML = '<div class="git-section"><div style="color:var(--muted)">&#x26A0; Not a git repository.</div><button class="btn btn-outline" style="margin-top:10px" onclick="gitRun(\'git init\')">Initialize git repo</button></div>';
      updateWorkbenchChrome();
      return;
    }
    const changed = (s.changed || []).map(f => `<span class="file-badge changed">M ${esc(f)}</span>`).join('');
    const staged = (s.staged || []).map(f => `<span class="file-badge staged">&#x2713; ${esc(f)}</span>`).join('');
    const untracked = (s.untracked || []).map(f => `<span class="file-badge untracked">? ${esc(f)}</span>`).join('');
    const aheadBehind = s.ahead > 0 ? `<span style="color:var(--teal)">&#x2B06; ${s.ahead} ahead</span> ` : '';
    const behindStr = s.behind > 0 ? `<span style="color:var(--amber)">&#x2B07; ${s.behind} behind</span>` : '';
    panel.innerHTML = `
    <div class="git-section">
      <div class="git-section-title">Repository Status</div>
      <div class="git-info-row"><span class="git-info-label">Branch</span><span class="git-info-val">&#x1F533; ${esc(s.branch)}</span> ${aheadBehind}${behindStr}</div>
      <div class="git-info-row"><span class="git-info-label">Remote</span><span class="git-info-val" style="color:var(--muted)">${esc(s.remote || 'none')}</span></div>
      <div class="git-info-row"><span class="git-info-label">Last commit</span><span class="git-info-val" style="color:var(--muted)">${esc(s.last_commit)}</span></div>
      <div class="git-info-row"><span class="git-info-label">Status</span><span class="${s.clean ? 'git-info-val' : ''}" style="color:${s.clean ? 'var(--teal)' : 'var(--amber)'}">${s.clean ? '&#x2713; Clean' : 'Modified'}</span></div>
    </div>
    ${!s.clean ? `<div class="git-section">
      <div class="git-section-title">Changed Files</div>
      <div style="margin-bottom:6px">${staged || '<span style="color:var(--muted);font-size:12px">No staged files</span>'}</div>
      <div style="margin-bottom:6px">${changed}</div>
      <div>${untracked}</div>
    </div>` : ''}
    <div class="git-section">
      <div class="git-section-title">Commit &amp; Push</div>
      <div class="git-commit-area">
        <textarea class="git-msg-input" id="commitMsg" placeholder="Commit message..."></textarea>
        <div class="git-actions">
          <button class="btn btn-primary" onclick="gitCommitPush()">&#x2B06; Stage All &amp; Commit &amp; Push</button>
          <button class="btn btn-outline" onclick="gitPull()">&#x2B07; Pull</button>
          <button class="btn btn-outline" onclick="gitPush()">&#x2B06; Push only</button>
        </div>
        <div class="git-output" id="gitOutput"></div>
      </div>
    </div>
    <div class="git-section">
      <div class="git-section-title">Quick Actions</div>
      <div class="git-actions">
        <button class="btn btn-outline" onclick="gitRun('git status')">git status</button>
        <button class="btn btn-outline" onclick="gitRun('git log --oneline -10')">git log</button>
        <button class="btn btn-outline" onclick="gitRun('git diff')">git diff</button>
        <button class="btn btn-purple" onclick="switchTab(\'terminal\')">&#x1F4BB; Open Terminal</button>
      </div>
    </div>`;
  } catch(e) {
    panel.innerHTML = '<div style="color:var(--crimson)">Error: ' + e + '</div>'; _gitStatusCache = null;
    _recordProjectActivity({
      kind: 'git',
      title: 'Git status failed',
      status: 'failed',
      detail: String(e),
      started_at: startedAt,
      completed_at: new Date().toISOString(),
      duration_ms: Math.max(0, Date.now() - startedTs),
      duration_label: _formatStepDuration({ duration_ms: Math.max(0, Date.now() - startedTs) }),
      cwd: _activeProjectPath || '',
      task: 'Inspect git state',
      subtask: 'Load repository status',
    });
  }
  updateWorkbenchChrome();
}

async function gitCommitPush() {
  const msg = document.getElementById('commitMsg').value.trim();
  if (!msg) { alert('Enter a commit message first.'); return; }
  await doGitAction('/api/projects/' + _activeProjectId + '/git/commit-push', { message: msg });
}
async function gitPull() { await doGitAction('/api/projects/' + _activeProjectId + '/git/pull'); }
async function gitPush() { await doGitAction('/api/projects/' + _activeProjectId + '/git/push'); }
async function gitRun(cmd) {
  switchTab('terminal');
  document.getElementById('termInput').value = cmd;
  await runTermCmd();
}

async function doGitAction(url, body = {}) {
  const outEl = document.getElementById('gitOutput');
  if (outEl) { outEl.textContent = 'Running...'; outEl.classList.add('show'); }
  const startedAt = new Date().toISOString();
  const startedTs = Date.now();
  try {
    const r = await fetch(API + url, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
    const d = await r.json();
    const text = [d.stdout, d.stderr].filter(Boolean).join('\n').trim() || (d.ok ? 'Done.' : 'Failed.');
    if (outEl) { outEl.textContent = text; }
    _recordProjectActivity({
      kind: 'git',
      title: d.ok ? 'Git action completed' : 'Git action failed',
      status: d.ok ? 'completed' : 'failed',
      detail: text,
      started_at: startedAt,
      completed_at: new Date().toISOString(),
      duration_ms: Math.max(0, Date.now() - startedTs),
      duration_label: _formatStepDuration({ duration_ms: Math.max(0, Date.now() - startedTs) }),
      cwd: _activeProjectPath || '',
      command: url,
      task: 'Execute git action',
      subtask: body.message || url.split('/').pop() || 'git',
    });
    await loadGitStatus();
    const badge = document.getElementById('wsBranchName');
    if (badge && d.branch) badge.textContent = d.branch;
  } catch(e) {
    if (outEl) outEl.textContent = 'Error: ' + e;
    _recordProjectActivity({
      kind: 'git',
      title: 'Git action failed',
      status: 'failed',
      detail: String(e),
      started_at: startedAt,
      completed_at: new Date().toISOString(),
      duration_ms: Math.max(0, Date.now() - startedTs),
      duration_label: _formatStepDuration({ duration_ms: Math.max(0, Date.now() - startedTs) }),
      cwd: _activeProjectPath || '',
      command: url,
      task: 'Execute git action',
      subtask: body.message || url.split('/').pop() || 'git',
    });
  }
}

// ── Add project modal ─────────────────────────────────────────────────────────
let _addMode = 'new';
function openAddModal(mode) { setAddMode(mode || 'new'); document.getElementById('addModal').classList.add('open'); }
function closeModal() { document.getElementById('addModal').classList.remove('open'); document.getElementById('addModalMsg').textContent = ''; }
function setAddMode(mode) {
  _addMode = mode;
  document.getElementById('formNew').style.display = mode === 'new' ? '' : 'none';
  document.getElementById('formDir').style.display = mode === 'dir' ? '' : 'none';
  document.getElementById('formClone').style.display = mode === 'clone' ? '' : 'none';
  ['new','dir','clone'].forEach(function(m) {
    var el = document.getElementById('tab' + m.charAt(0).toUpperCase() + m.slice(1));
    if (!el) return;
    el.style.borderColor = m === mode ? 'var(--teal)' : '';
    el.style.color = m === mode ? 'var(--teal)' : '';
  });
  var labels = { new: 'Create Project', dir: 'Add Project', clone: 'Clone & Add' };
  document.getElementById('addModalBtn').textContent = labels[mode] || 'Add Project';
  document.getElementById('addModalMsg').textContent = '';
}

async function submitAddProject() {
  const msg = document.getElementById('addModalMsg');
  const btn = document.getElementById('addModalBtn');
  btn.disabled = true;
  msg.textContent = 'Working...'; msg.style.color = 'var(--muted)';
  try {
    let r, d;
    if (_addMode === 'new') {
      const name = document.getElementById('inputNewName').value.trim();
      const parent_dir = document.getElementById('inputNewParent').value.trim();
      const stack = document.getElementById('inputNewStack').value.trim();
      if (!name) { msg.textContent = 'Project name is required'; msg.style.color = 'var(--crimson)'; btn.disabled = false; return; }
      msg.textContent = 'Creating project...';
      r = await fetch(API + '/api/projects/new', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ name, parent_dir, stack }) });
    } else if (_addMode === 'dir') {
      const path = document.getElementById('inputPath').value.trim();
      const name = document.getElementById('inputName').value.trim();
      if (!path) { msg.textContent = 'Path is required'; msg.style.color = 'var(--crimson)'; btn.disabled = false; return; }
      r = await fetch(API + '/api/projects', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ path, name }) });
    } else {
      const url = document.getElementById('inputCloneUrl').value.trim();
      const dest = document.getElementById('inputCloneDest').value.trim();
      if (!url || !dest) { msg.textContent = 'URL and destination are required'; msg.style.color = 'var(--crimson)'; btn.disabled = false; return; }
      msg.textContent = 'Cloning repository...';
      r = await fetch(API + '/api/projects/clone', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ url, dest }) });
    }
    d = await r.json();
    if (d.id || d.project) {
      closeModal();
      await loadProjects();
      const p = d.id ? d : d.project;
      if (p && p.id) await openProject(p.id, p.path, p.name);
    } else { msg.textContent = d.error || 'Failed'; msg.style.color = 'var(--crimson)'; }
  } catch(e) { msg.textContent = 'Error: ' + e; msg.style.color = 'var(--crimson)'; }
  btn.disabled = false;
}

function esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

// ── Startup ───────────────────────────────────────────────────────────────────
(async () => {
  try {
    const savedMode = localStorage.getItem('kendr.project_ui_mode');
    if (savedMode === 'code' || savedMode === 'agent') {
      setWorkspaceMode(savedMode, { keepTab: true });
    } else {
      updateWorkbenchChrome();
    }
  } catch(_) {
    updateWorkbenchChrome();
  }
  try {
    const savedChatMode = localStorage.getItem('kendr.project_chat_mode');
    const savedShell = localStorage.getItem('kendr.project_chat_shell');
    const savedDestructive = localStorage.getItem('kendr.project_chat_destructive');
    if (savedChatMode === 'ask' || savedChatMode === 'ai' || savedChatMode === 'auto') {
      _projectChatMode = savedChatMode;
    }
    if (savedShell === '0' || savedShell === '1') {
      _projectChatShell = savedShell === '1';
    }
    if (savedDestructive === '0' || savedDestructive === '1') {
      _projectChatAllowDestructive = savedDestructive === '1';
    }
  } catch(_) {}
  updateProjectChatControls();
  const fileTree = document.getElementById('fileTree');
  if (fileTree) fileTree.addEventListener('click', handleFileTreeClick);
  await loadProjects();
  loadProjModels();
  // Try to open the active project
  try {
    const r = await fetch(API + '/api/projects/active');
    const p = await r.json();
    if (p && p.id) await openProject(p.id, p.path, p.name);
  } catch(e) {}
  updateWorkbenchChrome();
})();
</script>
</body>
</html>"""


_RAG_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>kendr · Super-RAG</title>
<style>
:root{--teal:#00C9A7;--amber:#FFB347;--crimson:#FF4757;--purple:#A78BFA;--blue:#58A6FF;--green:#3FB950;--bg:#0d0f14;--surface:#161b22;--surface2:#1e2530;--surface3:#252d3a;--border:#2a3140;--text:#e6edf3;--muted:#7d8590;--sidebar-w:220px;--kb-panel-w:260px;}
*{box-sizing:border-box;margin:0;padding:0;}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;font-size:14px;display:flex;height:100vh;overflow:hidden;}
/* Nav sidebar */
.nav-sidebar{width:var(--sidebar-w);min-width:var(--sidebar-w);background:var(--surface);border-right:1px solid var(--border);display:flex;flex-direction:column;position:fixed;top:0;bottom:0;left:0;z-index:10;}
.nav-header{padding:18px 14px 12px;border-bottom:1px solid var(--border);}
.logo{font-size:20px;font-weight:800;color:var(--teal);}
.logo span{color:var(--amber);}
.tagline{font-size:10px;color:var(--muted);margin-top:2px;}
.nav-links{padding:10px 8px;display:flex;flex-direction:column;gap:3px;}
.nav-btn{display:flex;align-items:center;gap:8px;padding:8px 10px;border-radius:6px;text-decoration:none;color:var(--muted);font-size:13px;transition:all .15s;}
.nav-btn:hover{background:var(--surface2);color:var(--text);}
.nav-btn.active{background:rgba(0,201,167,.12);color:var(--teal);font-weight:600;}
.icon{font-size:15px;width:18px;text-align:center;}
/* KB panel */
.kb-panel{width:var(--kb-panel-w);min-width:var(--kb-panel-w);background:var(--surface);border-right:1px solid var(--border);position:fixed;top:0;bottom:0;left:var(--sidebar-w);display:flex;flex-direction:column;}
.kb-panel-head{padding:14px 12px 10px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between;}
.kb-panel-title{font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;}
.btn-xs{background:var(--surface2);border:1px solid var(--border);color:var(--teal);border-radius:5px;padding:4px 10px;font-size:11px;cursor:pointer;transition:all .15s;}
.btn-xs:hover{background:rgba(0,201,167,.12);}
.kb-list{flex:1;overflow-y:auto;padding:6px;}
.kb-item{padding:9px 10px;border-radius:6px;cursor:pointer;border:1px solid transparent;margin-bottom:3px;transition:all .15s;}
.kb-item:hover{background:var(--surface2);}
.kb-item.active{background:rgba(0,201,167,.1);border-color:rgba(0,201,167,.3);}
.kb-item-name{font-size:13px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.kb-item-meta{font-size:10px;color:var(--muted);margin-top:2px;}
.kb-badge{display:inline-block;font-size:9px;padding:1px 5px;border-radius:3px;margin-left:4px;font-weight:600;}
.badge-indexed{background:rgba(63,185,80,.15);color:var(--green);}
.badge-empty{background:rgba(125,133,144,.12);color:var(--muted);}
.badge-running{background:rgba(255,179,71,.15);color:var(--amber);animation:pulse 1.2s infinite;}
.badge-error{background:rgba(255,71,87,.12);color:var(--crimson);}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.5}}
/* Workspace */
.workspace{margin-left:calc(var(--sidebar-w) + var(--kb-panel-w));flex:1;display:flex;flex-direction:column;height:100vh;overflow:hidden;}
.ws-head{padding:14px 20px 10px;border-bottom:1px solid var(--border);display:flex;align-items:center;gap:12px;flex-shrink:0;}
.ws-title{font-size:16px;font-weight:700;color:var(--text);}
.ws-meta{font-size:11px;color:var(--muted);}
.tab-bar{display:flex;gap:2px;padding:0 20px;border-bottom:1px solid var(--border);flex-shrink:0;}
.tab{padding:10px 16px;font-size:13px;color:var(--muted);cursor:pointer;border-bottom:2px solid transparent;transition:all .15s;}
.tab.active{color:var(--teal);border-bottom-color:var(--teal);}
.tab:hover:not(.active){color:var(--text);}
.ws-body{flex:1;overflow-y:auto;padding:20px;}
/* Form styles */
.section{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:14px;}
.section-title{font-size:12px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:.06em;margin-bottom:12px;}
.form-row{margin-bottom:12px;}
.form-row label{display:block;font-size:12px;color:var(--muted);margin-bottom:4px;}
.form-row input,.form-row select,.form-row textarea{width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:5px;color:var(--text);padding:7px 10px;font-size:13px;outline:none;}
.form-row input:focus,.form-row select:focus,.form-row textarea:focus{border-color:var(--teal);}
.form-row select option{background:var(--surface2);}
.form-row textarea{resize:vertical;min-height:60px;}
.form-hint{font-size:11px;color:var(--muted);margin-top:3px;}
.btn{padding:8px 18px;border-radius:6px;border:none;cursor:pointer;font-size:13px;font-weight:600;transition:all .15s;}
.btn-primary{background:var(--teal);color:#000;}
.btn-primary:hover{filter:brightness(1.1);}
.btn-secondary{background:var(--surface2);border:1px solid var(--border);color:var(--text);}
.btn-secondary:hover{background:var(--surface3);}
.btn-danger{background:rgba(255,71,87,.15);border:1px solid rgba(255,71,87,.3);color:var(--crimson);}
.btn-danger:hover{background:rgba(255,71,87,.25);}
.btn-sm{padding:5px 12px;font-size:12px;}
.row{display:flex;gap:10px;align-items:flex-end;flex-wrap:wrap;}
/* Source list */
.source-list{display:flex;flex-direction:column;gap:8px;margin-top:12px;}
.source-item{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:10px 12px;display:flex;align-items:flex-start;gap:10px;}
.source-icon{font-size:18px;flex-shrink:0;margin-top:1px;}
.source-info{flex:1;min-width:0;}
.source-label{font-size:13px;font-weight:600;color:var(--text);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.source-type{font-size:10px;color:var(--muted);text-transform:uppercase;margin-top:1px;}
.source-stat{font-size:11px;color:var(--muted);margin-top:3px;}
.source-actions{display:flex;gap:6px;flex-shrink:0;}
.dot-status{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:4px;}
.dot-indexed{background:var(--green);}
.dot-pending{background:var(--muted);}
.dot-indexing{background:var(--amber);animation:pulse 1s infinite;}
.dot-error{background:var(--crimson);}
/* Query tab */
.query-box{display:flex;gap:8px;margin-bottom:14px;}
.query-box input{flex:1;background:var(--surface2);border:1px solid var(--border);border-radius:6px;color:var(--text);padding:10px 14px;font-size:14px;outline:none;}
.query-box input:focus{border-color:var(--teal);}
.results{display:flex;flex-direction:column;gap:10px;}
.result-card{background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:14px;}
.result-header{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px;}
.result-source{font-size:12px;color:var(--blue);word-break:break-all;}
.result-score{font-size:11px;color:var(--teal);font-weight:700;}
.result-text{font-size:13px;color:var(--muted);line-height:1.5;}
.answer-box{background:var(--surface);border:1px solid var(--border);border-left:3px solid var(--teal);border-radius:8px;padding:16px;margin-bottom:14px;line-height:1.6;}
.agent-list{display:flex;flex-direction:column;gap:8px;}
.agent-item{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:10px 14px;display:flex;align-items:center;justify-content:space-between;}
.agent-name{font-size:13px;font-weight:600;}
.toggle{position:relative;display:inline-block;width:40px;height:22px;}
.toggle input{opacity:0;width:0;height:0;}
.slider{position:absolute;inset:0;background:var(--border);border-radius:22px;cursor:pointer;transition:.2s;}
.slider:before{position:absolute;content:"";height:16px;width:16px;left:3px;bottom:3px;background:white;border-radius:50%;transition:.2s;}
input:checked + .slider{background:var(--teal);}
input:checked + .slider:before{transform:translateX(18px);}
.upload-zone{border:2px dashed var(--border);border-radius:8px;padding:24px;text-align:center;cursor:pointer;transition:all .15s;}
.upload-zone:hover,.upload-zone.drag{border-color:var(--teal);background:rgba(0,201,167,.05);}
.upload-zone input{display:none;}
.index-log{background:var(--surface2);border-radius:6px;padding:10px;font-size:11px;font-family:monospace;color:var(--muted);max-height:180px;overflow-y:auto;margin-top:10px;white-space:pre-wrap;}
.alert{padding:10px 14px;border-radius:6px;font-size:13px;margin-bottom:10px;}
.alert-info{background:rgba(88,166,255,.1);border:1px solid rgba(88,166,255,.25);color:var(--blue);}
.alert-success{background:rgba(63,185,80,.1);border:1px solid rgba(63,185,80,.25);color:var(--green);}
.alert-error{background:rgba(255,71,87,.1);border:1px solid rgba(255,71,87,.25);color:var(--crimson);}
.hidden{display:none!important;}
/* Modal */
.modal-overlay{position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:100;display:flex;align-items:center;justify-content:center;}
.modal{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:24px;min-width:380px;max-width:520px;width:90%;}
.modal-title{font-size:16px;font-weight:700;margin-bottom:16px;}
.modal-actions{display:flex;justify-content:flex-end;gap:8px;margin-top:20px;}
</style>
</head>
<body>

<!-- Nav sidebar -->
<div class="nav-sidebar">
  <div class="nav-header"><div class="logo">kendr<span>.</span></div><div class="tagline">Multi-agent intelligence runtime</div></div>
  <div class="nav-links">
    <a href="/chat" class="nav-btn"><span class="icon">&#x1F4AC;</span> Chat</a>
    <a href="/setup" class="nav-btn"><span class="icon">&#x2699;&#xFE0F;</span> Setup &amp; Config</a>
    <a href="/runs" class="nav-btn"><span class="icon">&#x1F4D6;</span> Run History</a>
    <a href="/skills" class="nav-btn"><span class="icon">&#x1F9E0;</span> Skill Cards</a>
    <a href="/rag" class="nav-btn active"><span class="icon">&#x1F52C;</span> Super-RAG</a>
    <a href="/models" class="nav-btn"><span class="icon">&#x1F916;</span> LLM Models</a>
    <a href="/capabilities" class="nav-btn"><span class="icon">&#x2692;&#xFE0F;</span> Capabilities</a>
    <a href="/projects" class="nav-btn"><span class="icon">&#x1F4C1;</span> Projects</a>
    <a href="/docs" class="nav-btn"><span class="icon">&#x1F4D6;</span> Docs</a>
  </div>
</div>

<!-- KB panel -->
<div class="kb-panel">
  <div class="kb-panel-head">
    <span class="kb-panel-title">Knowledge Bases</span>
    <button class="btn-xs" onclick="showCreateModal()">+ New</button>
  </div>
  <div class="kb-list" id="kbList"></div>
</div>

<!-- Workspace -->
<div class="workspace">
  <div class="ws-head">
    <div>
      <div class="ws-title" id="wsTitle">Select a knowledge base</div>
      <div class="ws-meta" id="wsMeta">Create or select a KB from the left panel to get started.</div>
    </div>
    <div style="margin-left:auto;display:flex;gap:8px;align-items:center;">
      <button class="btn btn-primary btn-sm hidden" id="btnIndex" onclick="triggerIndex()">&#x26A1; Index All Sources</button>
      <button class="btn btn-danger btn-sm hidden" id="btnDeleteKb" onclick="deleteKb()">Delete KB</button>
    </div>
  </div>

  <div class="tab-bar">
    <div class="tab active" id="tab-sources" onclick="switchTab('sources')">&#x1F4C2; Sources</div>
    <div class="tab" id="tab-vector" onclick="switchTab('vector')">&#x1F5C4; Vector DB</div>
    <div class="tab" id="tab-reranker" onclick="switchTab('reranker')">&#x1F3AF; Reranker</div>
    <div class="tab" id="tab-agents" onclick="switchTab('agents')">&#x1F916; Agents</div>
    <div class="tab" id="tab-query" onclick="switchTab('query')">&#x1F50D; Query / Test</div>
  </div>

  <div class="ws-body">

    <!-- SOURCES TAB -->
    <div id="pane-sources">
      <div class="alert alert-info" id="noKbAlert">Select or create a knowledge base to manage sources.</div>

      <div class="hidden" id="sourcesContent">
        <!-- Index status bar -->
        <div id="indexStatus" class="section hidden" style="padding:12px 16px;">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <span id="indexStatusText" style="font-size:13px;font-weight:600;"></span>
            <button class="btn-xs" onclick="refreshIndexStatus()">Refresh</button>
          </div>
          <div class="index-log" id="indexLog"></div>
        </div>

        <!-- Add source -->
        <div class="section">
          <div class="section-title">Add Source</div>
          <div class="form-row">
            <label>Source Type</label>
            <select id="srcType" onchange="updateSourceForm()">
              <option value="folder">📂 Local Folder</option>
              <option value="file">📄 Single File</option>
              <option value="url">🌐 URL / Website</option>
              <option value="database">🗄️ Database</option>
              <option value="onedrive">☁️ OneDrive</option>
            </select>
          </div>
          <!-- Folder / File fields -->
          <div id="src-folder-fields">
            <div class="form-row"><label>Path on this machine</label><input type="text" id="srcPath" placeholder="/home/user/documents or /path/to/file.pdf"></div>
            <div class="row">
              <div class="form-row" style="flex:1"><label>Max files</label><input type="number" id="srcMaxFiles" value="300" min="1" max="3000"></div>
              <div class="form-row" style="flex:1"><label>Extensions (comma-sep, blank=all)</label><input type="text" id="srcExtensions" placeholder=".pdf,.md,.txt"></div>
              <div class="form-row" style="flex:0;white-space:nowrap;padding-bottom:1px"><label>&nbsp;</label>
                <label style="display:flex;align-items:center;gap:6px;padding:8px 0;cursor:pointer;"><input type="checkbox" id="srcRecursive" checked> Recursive</label>
              </div>
            </div>
            <!-- Upload zone (for file type) -->
            <div id="uploadZone" class="upload-zone hidden" onclick="document.getElementById('fileUploadInput').click()">
              <input type="file" id="fileUploadInput" onchange="handleFileUpload()" multiple>
              <div style="font-size:24px;margin-bottom:6px;">📁</div>
              <div style="font-size:13px;color:var(--muted)">Drop files here or click to upload</div>
              <div style="font-size:11px;color:var(--muted);margin-top:4px">PDF, DOCX, TXT, MD, XLSX, CSV, PPTX supported</div>
            </div>
          </div>
          <!-- URL fields -->
          <div id="src-url-fields" class="hidden">
            <div class="form-row"><label>URL</label><input type="text" id="srcUrl" placeholder="https://docs.example.com"></div>
            <div class="row">
              <div class="form-row" style="flex:1"><label>Max pages to crawl</label><input type="number" id="srcMaxPages" value="20" min="1" max="200"></div>
              <div class="form-row" style="flex:0;white-space:nowrap;padding-bottom:1px"><label>&nbsp;</label>
                <label style="display:flex;align-items:center;gap:6px;padding:8px 0;cursor:pointer;"><input type="checkbox" id="srcSameDomain" checked> Same domain only</label>
              </div>
            </div>
          </div>
          <!-- DB fields -->
          <div id="src-db-fields" class="hidden">
            <div class="form-row"><label>Database URL</label><input type="text" id="srcDbUrl" placeholder="postgresql://user:pass@host:5432/dbname"></div>
            <div class="row">
              <div class="form-row" style="flex:1"><label>Tables (comma-sep, blank=all)</label><input type="text" id="srcTables" placeholder="users, orders, products"></div>
              <div class="form-row" style="flex:1"><label>Schema (optional)</label><input type="text" id="srcSchema" placeholder="public"></div>
            </div>
          </div>
          <!-- OneDrive fields -->
          <div id="src-onedrive-fields" class="hidden">
            <div class="form-row"><label>OneDrive path (blank = root)</label><input type="text" id="srcOnedrivePath" placeholder="Documents/Reports"></div>
            <div class="alert alert-info" style="margin-top:6px">Requires Microsoft integration to be configured in Setup.</div>
          </div>
          <div class="form-row"><label>Label (optional)</label><input type="text" id="srcLabel" placeholder="Friendly name for this source"></div>
          <button class="btn btn-primary" onclick="addSource()">Add Source</button>
        </div>

        <!-- Source list -->
        <div class="section">
          <div class="section-title" style="display:flex;justify-content:space-between;align-items:center;">
            <span>Indexed Sources</span>
            <button class="btn-xs" onclick="loadSources()">Refresh</button>
          </div>
          <div class="source-list" id="sourceList"><div style="color:var(--muted);font-size:12px">No sources yet.</div></div>
        </div>
      </div>
    </div>

    <!-- VECTOR DB TAB -->
    <div id="pane-vector" class="hidden">
      <div class="section">
        <div class="section-title">Vector Store Backend</div>
        <div class="form-row">
          <label>Backend</label>
          <select id="vecBackend" onchange="updateVectorForm()">
            <option value="chromadb">ChromaDB (local, default)</option>
            <option value="qdrant">Qdrant (local or cloud)</option>
            <option value="pgvector">pgvector (PostgreSQL)</option>
          </select>
          <div class="form-hint">ChromaDB runs locally with no setup. Qdrant and pgvector support remote deployments.</div>
        </div>
        <div id="vec-chroma-fields">
          <div class="form-row"><label>ChromaDB persist path</label><input type="text" id="vecChromaPath" placeholder="~/.kendr/chroma"></div>
        </div>
        <div id="vec-qdrant-fields" class="hidden">
          <div class="form-row"><label>Qdrant URL</label><input type="text" id="vecQdrantUrl" placeholder="http://localhost:6333"></div>
          <div class="form-row"><label>API Key (Qdrant Cloud)</label><input type="text" id="vecQdrantKey" placeholder="optional"></div>
        </div>
        <div id="vec-pgvector-fields" class="hidden">
          <div class="form-row"><label>PostgreSQL URL (with pgvector)</label><input type="text" id="vecPgUrl" placeholder="postgresql://user:pass@host/dbname"></div>
        </div>
        <div class="form-row" style="margin-top:12px">
          <label>Embedding Model</label>
          <select id="vecEmbedModel">
            <option value="openai:text-embedding-3-small">OpenAI text-embedding-3-small (default)</option>
            <option value="openai:text-embedding-3-large">OpenAI text-embedding-3-large</option>
            <option value="openai:text-embedding-ada-002">OpenAI text-embedding-ada-002</option>
          </select>
          <div class="form-hint">OpenAI embeddings require OPENAI_API_KEY to be configured.</div>
        </div>
        <button class="btn btn-primary" onclick="saveVectorConfig()">Save Vector Config</button>
      </div>
      <div class="section" style="padding:12px 16px">
        <div class="section-title">Backend Status</div>
        <div id="vecStatus" style="color:var(--muted);font-size:12px">Load a KB to see status.</div>
      </div>
    </div>

    <!-- RERANKER TAB -->
    <div id="pane-reranker" class="hidden">
      <div class="section">
        <div class="section-title">Reranking Algorithm</div>
        <div class="form-row">
          <label>Algorithm</label>
          <select id="rerankerAlgo" onchange="updateRerankerForm()">
            <option value="none">None (raw vector similarity)</option>
            <option value="keyword">Keyword Boost (vector + keyword overlap)</option>
            <option value="rrf">RRF — Reciprocal Rank Fusion</option>
            <option value="cross_encoder">Cross-Encoder (requires sentence-transformers)</option>
            <option value="cohere">Cohere Rerank API</option>
          </select>
        </div>
        <div class="form-row">
          <label>Top-K results to return</label>
          <input type="number" id="rerankerTopK" value="8" min="1" max="50">
        </div>
        <div class="form-row">
          <label>Fetch K (candidates before reranking)</label>
          <input type="number" id="rerankerFetchK" value="20" min="1" max="100">
          <div class="form-hint">Fetch this many from the vector store, then rerank down to Top-K.</div>
        </div>
        <!-- Keyword boost option -->
        <div id="rr-keyword-fields" class="hidden">
          <div class="form-row">
            <label>Keyword weight (0 = pure vector, 1 = pure keyword)</label>
            <input type="range" id="rerankerKeywordWeight" min="0" max="1" step="0.05" value="0.3" oninput="document.getElementById('kwWeightLabel').textContent=this.value">
            <span id="kwWeightLabel" style="font-size:12px;color:var(--teal);margin-left:6px">0.3</span>
          </div>
        </div>
        <!-- Cross-encoder options -->
        <div id="rr-crossenc-fields" class="hidden">
          <div class="form-row">
            <label>Cross-encoder model</label>
            <input type="text" id="rerankerCEModel" value="cross-encoder/ms-marco-MiniLM-L-6-v2">
          </div>
          <div class="alert alert-info">Install sentence-transformers: <code>pip install sentence-transformers</code></div>
        </div>
        <!-- Cohere options -->
        <div id="rr-cohere-fields" class="hidden">
          <div class="form-row">
            <label>Cohere API Key</label>
            <input type="text" id="rerankerCohereKey" placeholder="or set COHERE_API_KEY env var">
          </div>
        </div>
        <button class="btn btn-primary" onclick="saveRerankerConfig()">Save Reranker Config</button>
      </div>
    </div>

    <!-- AGENTS TAB -->
    <div id="pane-agents" class="hidden">
      <div class="section">
        <div class="section-title">Agent Connections (Super-RAG)</div>
        <div class="form-hint" style="margin-bottom:14px">Enable agents to automatically query this knowledge base when answering tasks. This transforms kendr into a Super-RAG — every enabled agent can retrieve context from this KB.</div>
        <div class="agent-list" id="agentList"></div>
      </div>
      <div class="section">
        <div class="section-title">Active KB used by agents</div>
        <div style="font-size:13px;color:var(--muted);">Enabled agents will use the <strong>active KB</strong> (marked with ★ in the left panel). Switch the active KB to change which knowledge base agents access.</div>
        <button class="btn btn-secondary btn-sm" style="margin-top:10px" onclick="setActiveKb()">★ Set this KB as Active</button>
      </div>
    </div>

    <!-- QUERY TAB -->
    <div id="pane-query" class="hidden">
      <div class="query-box">
        <input type="text" id="queryInput" placeholder="Ask a question about your knowledge base…" onkeydown="if(event.key==='Enter')runQuery()">
        <button class="btn btn-secondary" onclick="runQuery(false)" style="white-space:nowrap">&#x1F50D; Search</button>
        <button class="btn btn-primary" onclick="runQuery(true)" style="white-space:nowrap">&#x1F916; Ask AI</button>
      </div>
      <div id="queryStatus" style="font-size:12px;color:var(--muted);margin-bottom:10px"></div>
      <div id="answerSection" class="hidden">
        <div class="section-title" style="margin-bottom:8px">AI Answer</div>
        <div class="answer-box" id="answerBox"></div>
      </div>
      <div id="resultsSection" class="hidden">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;">
          <div class="section-title" style="margin-bottom:0">Retrieved Chunks</div>
          <span id="resultsMeta" style="font-size:11px;color:var(--muted)"></span>
        </div>
        <div class="results" id="resultsList"></div>
      </div>
    </div>

  </div><!-- ws-body -->
</div><!-- workspace -->

<!-- Create KB Modal -->
<div class="modal-overlay hidden" id="createModal">
  <div class="modal">
    <div class="modal-title">Create Knowledge Base</div>
    <div class="form-row"><label>Name</label><input type="text" id="newKbName" placeholder="My Documentation KB"></div>
    <div class="form-row"><label>Description (optional)</label><input type="text" id="newKbDesc" placeholder="What this KB contains…"></div>
    <div class="modal-actions">
      <button class="btn btn-secondary" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" onclick="createKb()">Create</button>
    </div>
  </div>
</div>

<script>
const API = '';
let _activeKbId = null;
let _currentTab = 'sources';
let _indexPollTimer = null;
const SOURCE_ICONS = {folder:'📂',file:'📄',url:'🌐',database:'🗄️',onedrive:'☁️'};

// ── Bootstrap ──────────────────────────────────────────────────────────────
async function init() {
  await loadKbList();
}

// ── KB List ────────────────────────────────────────────────────────────────
async function loadKbList() {
  const r = await fetch(API + '/api/rag/kbs').then(r => r.json()).catch(() => []);
  const el = document.getElementById('kbList');
  el.innerHTML = '';
  if (!r.length) {
    el.innerHTML = '<div style="padding:12px;color:var(--muted);font-size:12px">No knowledge bases yet. Click + New to create one.</div>';
    return;
  }
  for (const kb of r) {
    const isActive = kb.id === _activeKbId;
    const status = kb.status || 'empty';
    const d = document.createElement('div');
    d.className = 'kb-item' + (isActive ? ' active' : '');
    d.onclick = () => selectKb(kb.id);
    const badgeCls = status === 'indexed' ? 'badge-indexed' : status === 'empty' ? 'badge-empty' : 'badge-running';
    d.innerHTML = `<div class="kb-item-name">${kb.name}</div>
      <div class="kb-item-meta"><span class="kb-badge ${badgeCls}">${status}</span> ${kb.stats?.total_chunks||0} chunks · ${(kb.sources||[]).length} sources</div>`;
    el.appendChild(d);
  }
}

async function selectKb(kbId) {
  _activeKbId = kbId;
  await loadKbList();
  await renderKb();
  switchTab(_currentTab);
}

async function renderKb() {
  if (!_activeKbId) return;
  const kb = await fetch(API + '/api/rag/kbs/' + _activeKbId).then(r => r.json()).catch(() => null);
  if (!kb || kb.error) return;
  document.getElementById('wsTitle').textContent = kb.name;
  document.getElementById('wsMeta').textContent = (kb.description || '') + ' · ' + (kb.stats?.total_chunks||0) + ' chunks · ' + (kb.sources?.length||0) + ' sources';
  document.getElementById('noKbAlert').classList.add('hidden');
  document.getElementById('sourcesContent').classList.remove('hidden');
  document.getElementById('btnIndex').classList.remove('hidden');
  document.getElementById('btnDeleteKb').classList.remove('hidden');
  loadSources(kb);
  loadVectorConfig(kb);
  loadRerankerConfig(kb);
  loadAgents(kb);
  checkIndexJob();
}

// ── Sources tab ────────────────────────────────────────────────────────────
function updateSourceForm() {
  const t = document.getElementById('srcType').value;
  document.getElementById('src-folder-fields').classList.toggle('hidden', t === 'url' || t === 'database' || t === 'onedrive');
  document.getElementById('uploadZone').classList.toggle('hidden', t !== 'file');
  document.getElementById('src-url-fields').classList.toggle('hidden', t !== 'url');
  document.getElementById('src-db-fields').classList.toggle('hidden', t !== 'database');
  document.getElementById('src-onedrive-fields').classList.toggle('hidden', t !== 'onedrive');
  document.getElementById('srcPath').placeholder = t === 'folder' ? '/home/user/documents' : '/path/to/file.pdf';
}

async function addSource() {
  if (!_activeKbId) { alert('No KB selected'); return; }
  const type = document.getElementById('srcType').value;
  const body = { type, label: document.getElementById('srcLabel').value.trim() };
  if (type === 'folder') {
    body.path = document.getElementById('srcPath').value.trim();
    body.recursive = document.getElementById('srcRecursive').checked;
    body.max_files = parseInt(document.getElementById('srcMaxFiles').value);
    body.extensions = document.getElementById('srcExtensions').value.trim();
  } else if (type === 'file') {
    body.path = document.getElementById('srcPath').value.trim();
  } else if (type === 'url') {
    body.url = document.getElementById('srcUrl').value.trim();
    body.max_pages = parseInt(document.getElementById('srcMaxPages').value);
    body.same_domain = document.getElementById('srcSameDomain').checked;
  } else if (type === 'database') {
    body.db_url = document.getElementById('srcDbUrl').value.trim();
    body.tables = document.getElementById('srcTables').value.trim();
    body.schema = document.getElementById('srcSchema').value.trim();
  } else if (type === 'onedrive') {
    body.onedrive_path = document.getElementById('srcOnedrivePath').value.trim();
  }
  const r = await fetch(API + '/api/rag/kbs/' + _activeKbId + '/sources', {
    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body)
  }).then(r => r.json()).catch(() => ({error:'network error'}));
  if (r.error) { alert('Error: ' + r.error); return; }
  document.getElementById('srcLabel').value = '';
  document.getElementById('srcPath').value = '';
  document.getElementById('srcUrl').value = '';
  document.getElementById('srcDbUrl').value = '';
  await loadSources();
}

async function handleFileUpload() {
  if (!_activeKbId) { alert('No KB selected'); return; }
  const inp = document.getElementById('fileUploadInput');
  for (const file of inp.files) {
    const fd = new FormData();
    fd.append('file', file);
    fd.append('kb_id', _activeKbId);
    const r = await fetch(API + '/api/rag/upload', { method: 'POST', body: fd }).then(r => r.json()).catch(() => ({error:'upload failed'}));
    if (r.error) { alert('Upload error: ' + r.error); }
  }
  inp.value = '';
  await loadSources();
}

async function loadSources(kb) {
  if (!kb) kb = await fetch(API + '/api/rag/kbs/' + _activeKbId).then(r => r.json()).catch(() => null);
  if (!kb) return;
  const el = document.getElementById('sourceList');
  const sources = kb.sources || [];
  if (!sources.length) { el.innerHTML = '<div style="color:var(--muted);font-size:12px">No sources yet. Add a folder, URL, or database above.</div>'; return; }
  el.innerHTML = sources.map(s => {
    const dotCls = 'dot-' + (s.status || 'pending');
    const statText = s.status === 'indexed' ? `${s.stats?.items||0} items · ${s.stats?.chunks||0} chunks` : (s.error || s.status || 'pending');
    return `<div class="source-item">
      <div class="source-icon">${SOURCE_ICONS[s.type]||'📄'}</div>
      <div class="source-info">
        <div class="source-label">${escHtml(s.label||s.source_id)}</div>
        <div class="source-type">${s.type}</div>
        <div class="source-stat"><span class="dot-status ${dotCls}"></span>${escHtml(statText)}</div>
      </div>
      <div class="source-actions">
        <button class="btn btn-danger btn-sm" onclick="removeSource('${s.source_id}')">✕</button>
      </div>
    </div>`;
  }).join('');
}

async function removeSource(sourceId) {
  if (!confirm('Remove this source?')) return;
  await fetch(API + '/api/rag/kbs/' + _activeKbId + '/sources/' + sourceId, { method: 'DELETE' }).then(r => r.json()).catch(() => null);
  await loadSources();
}

// ── Index ──────────────────────────────────────────────────────────────────
async function triggerIndex() {
  if (!_activeKbId) return;
  await fetch(API + '/api/rag/kbs/' + _activeKbId + '/index', { method: 'POST' });
  document.getElementById('indexStatus').classList.remove('hidden');
  document.getElementById('indexStatusText').textContent = 'Indexing started…';
  startIndexPoll();
}

function startIndexPoll() {
  if (_indexPollTimer) clearInterval(_indexPollTimer);
  _indexPollTimer = setInterval(checkIndexJob, 2500);
}

async function checkIndexJob() {
  if (!_activeKbId) return;
  const job = await fetch(API + '/api/rag/kbs/' + _activeKbId + '/index/status').then(r => r.json()).catch(() => null);
  if (!job || !job.status) return;
  document.getElementById('indexStatus').classList.remove('hidden');
  const statusText = {running:'⚡ Indexing in progress…', done:'✅ Indexing complete', done_with_errors:'⚠️ Done with errors', error:'❌ Indexing failed'}[job.status] || job.status;
  document.getElementById('indexStatusText').textContent = statusText + ` (${job.chunks_indexed||0} chunks, ${job.sources_done||0}/${job.sources_total||0} sources)`;
  document.getElementById('indexLog').textContent = (job.log || []).join('\n');
  if (job.status !== 'running') {
    if (_indexPollTimer) { clearInterval(_indexPollTimer); _indexPollTimer = null; }
    await loadKbList();
    await loadSources();
  }
}

async function refreshIndexStatus() { await checkIndexJob(); }

// ── Vector config ──────────────────────────────────────────────────────────
function updateVectorForm() {
  const b = document.getElementById('vecBackend').value;
  document.getElementById('vec-chroma-fields').classList.toggle('hidden', b !== 'chromadb');
  document.getElementById('vec-qdrant-fields').classList.toggle('hidden', b !== 'qdrant');
  document.getElementById('vec-pgvector-fields').classList.toggle('hidden', b !== 'pgvector');
}

async function loadVectorConfig(kb) {
  const vc = kb?.vector_config || {};
  document.getElementById('vecBackend').value = vc.backend || 'chromadb';
  document.getElementById('vecChromaPath').value = vc.chromadb_path || '';
  document.getElementById('vecQdrantUrl').value = vc.qdrant_url || '';
  document.getElementById('vecQdrantKey').value = vc.qdrant_api_key || '';
  document.getElementById('vecPgUrl').value = vc.pgvector_url || '';
  document.getElementById('vecEmbedModel').value = vc.embedding_model || 'openai:text-embedding-3-small';
  updateVectorForm();
  // Show status
  const s = await fetch(API + '/api/rag/kbs/' + _activeKbId + '/status').then(r => r.json()).catch(() => null);
  if (s) {
    const color = s.backend_ok ? 'var(--green)' : 'var(--crimson)';
    document.getElementById('vecStatus').innerHTML = `<span style="color:${color}">${s.backend_ok ? '✅' : '❌'} Backend (${s.vector_backend})</span><br><span style="color:var(--muted)">${s.backend_note || ''}</span>`;
  }
}

async function saveVectorConfig() {
  if (!_activeKbId) return;
  const cfg = {
    backend: document.getElementById('vecBackend').value,
    chromadb_path: document.getElementById('vecChromaPath').value.trim(),
    qdrant_url: document.getElementById('vecQdrantUrl').value.trim(),
    qdrant_api_key: document.getElementById('vecQdrantKey').value.trim(),
    pgvector_url: document.getElementById('vecPgUrl').value.trim(),
    embedding_model: document.getElementById('vecEmbedModel').value,
  };
  const r = await fetch(API + '/api/rag/kbs/' + _activeKbId + '/vector', {
    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(cfg)
  }).then(r => r.json()).catch(() => ({error:'failed'}));
  if (r.error) { alert('Error: ' + r.error); return; }
  alert('Vector config saved.');
}

// ── Reranker config ────────────────────────────────────────────────────────
function updateRerankerForm() {
  const a = document.getElementById('rerankerAlgo').value;
  document.getElementById('rr-keyword-fields').classList.toggle('hidden', a !== 'keyword');
  document.getElementById('rr-crossenc-fields').classList.toggle('hidden', a !== 'cross_encoder');
  document.getElementById('rr-cohere-fields').classList.toggle('hidden', a !== 'cohere');
}

function loadRerankerConfig(kb) {
  const rc = kb?.reranker_config || {};
  document.getElementById('rerankerAlgo').value = rc.algorithm || 'none';
  document.getElementById('rerankerTopK').value = rc.top_k || 8;
  document.getElementById('rerankerFetchK').value = rc.rerank_top_k || 20;
  document.getElementById('rerankerKeywordWeight').value = rc.keyword_weight || 0.3;
  document.getElementById('kwWeightLabel').textContent = rc.keyword_weight || 0.3;
  document.getElementById('rerankerCEModel').value = rc.cross_encoder_model || 'cross-encoder/ms-marco-MiniLM-L-6-v2';
  document.getElementById('rerankerCohereKey').value = rc.cohere_api_key || '';
  updateRerankerForm();
}

async function saveRerankerConfig() {
  if (!_activeKbId) return;
  const cfg = {
    algorithm: document.getElementById('rerankerAlgo').value,
    top_k: parseInt(document.getElementById('rerankerTopK').value),
    rerank_top_k: parseInt(document.getElementById('rerankerFetchK').value),
    keyword_weight: parseFloat(document.getElementById('rerankerKeywordWeight').value),
    cross_encoder_model: document.getElementById('rerankerCEModel').value.trim(),
    cohere_api_key: document.getElementById('rerankerCohereKey').value.trim(),
  };
  const r = await fetch(API + '/api/rag/kbs/' + _activeKbId + '/reranker', {
    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(cfg)
  }).then(r => r.json()).catch(() => ({error:'failed'}));
  if (r.error) { alert('Error: ' + r.error); return; }
  alert('Reranker config saved.');
}

// ── Agents tab ─────────────────────────────────────────────────────────────
async function loadAgents(kb) {
  const agents = await fetch(API + '/api/rag/agents').then(r => r.json()).catch(() => []);
  const enabled = new Set(kb?.enabled_agents || []);
  const el = document.getElementById('agentList');
  if (!agents.length) { el.innerHTML = '<div style="color:var(--muted);font-size:12px">No agents discovered.</div>'; return; }
  el.innerHTML = agents.map(a => `
    <div class="agent-item">
      <div>
        <div class="agent-name">🤖 ${a}</div>
        <div style="font-size:11px;color:var(--muted)">${a.replace('_agent','').replace('_',' ')}</div>
      </div>
      <label class="toggle">
        <input type="checkbox" ${enabled.has(a)?'checked':''} onchange="toggleAgent('${a}', this.checked)">
        <span class="slider"></span>
      </label>
    </div>`).join('');
}

async function toggleAgent(agentName, enabled) {
  if (!_activeKbId) return;
  await fetch(API + '/api/rag/kbs/' + _activeKbId + '/agents', {
    method: 'POST', headers: {'Content-Type':'application/json'},
    body: JSON.stringify({agent: agentName, enabled})
  }).then(r => r.json()).catch(() => null);
}

async function setActiveKb() {
  if (!_activeKbId) return;
  await fetch(API + '/api/rag/kbs/' + _activeKbId + '/activate', { method: 'POST' }).then(r => r.json()).catch(() => null);
  await loadKbList();
  alert('Active KB set to: ' + document.getElementById('wsTitle').textContent);
}

// ── Query tab ──────────────────────────────────────────────────────────────
async function runQuery(withAI) {
  const query = document.getElementById('queryInput').value.trim();
  if (!query) return;
  if (!_activeKbId) { alert('No KB selected'); return; }
  document.getElementById('queryStatus').textContent = withAI ? '🤖 Generating AI answer…' : '🔍 Searching…';
  document.getElementById('answerSection').classList.add('hidden');
  document.getElementById('resultsSection').classList.add('hidden');
  const endpoint = withAI ? '/api/rag/kbs/' + _activeKbId + '/answer' : '/api/rag/kbs/' + _activeKbId + '/query';
  const r = await fetch(API + endpoint, {
    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({query})
  }).then(r => r.json()).catch(() => ({error:'network error'}));
  document.getElementById('queryStatus').textContent = '';
  if (r.error) { document.getElementById('queryStatus').textContent = '❌ ' + r.error; return; }
  if (withAI && r.answer) {
    document.getElementById('answerSection').classList.remove('hidden');
    document.getElementById('answerBox').textContent = r.answer;
  }
  const hits = r.hits || [];
  document.getElementById('resultsSection').classList.remove('hidden');
  document.getElementById('resultsMeta').textContent = `${hits.length} chunks · ${r.algorithm || 'none'} reranking`;
  document.getElementById('resultsList').innerHTML = hits.map((h,i) => {
    const source = h.source || (h.metadata||{}).source || '?';
    const score = h.score != null ? h.score.toFixed(4) : '?';
    const text = (h.text || '').slice(0, 500);
    return `<div class="result-card">
      <div class="result-header">
        <span class="result-source">[${i+1}] ${escHtml(source)}</span>
        <span class="result-score">score: ${score}</span>
      </div>
      <div class="result-text">${escHtml(text)}${h.text?.length > 500 ? '…' : ''}</div>
    </div>`;
  }).join('');
}

// ── Delete KB ──────────────────────────────────────────────────────────────
async function deleteKb() {
  if (!_activeKbId) return;
  const name = document.getElementById('wsTitle').textContent;
  if (!confirm(`Delete KB "${name}"? This removes config but does NOT delete vector data.`)) return;
  await fetch(API + '/api/rag/kbs/' + _activeKbId, { method: 'DELETE' }).then(r => r.json()).catch(() => null);
  _activeKbId = null;
  document.getElementById('wsTitle').textContent = 'Select a knowledge base';
  document.getElementById('wsMeta').textContent = 'Create or select a KB from the left panel to get started.';
  document.getElementById('noKbAlert').classList.remove('hidden');
  document.getElementById('sourcesContent').classList.add('hidden');
  document.getElementById('btnIndex').classList.add('hidden');
  document.getElementById('btnDeleteKb').classList.add('hidden');
  await loadKbList();
}

// ── Tabs ───────────────────────────────────────────────────────────────────
function switchTab(name) {
  _currentTab = name;
  ['sources','vector','reranker','agents','query'].forEach(t => {
    document.getElementById('tab-' + t).classList.toggle('active', t === name);
    document.getElementById('pane-' + t).classList.toggle('hidden', t !== name);
  });
}

// ── Create modal ───────────────────────────────────────────────────────────
function showCreateModal() { document.getElementById('createModal').classList.remove('hidden'); document.getElementById('newKbName').focus(); }
function closeModal() { document.getElementById('createModal').classList.add('hidden'); }
async function createKb() {
  const name = document.getElementById('newKbName').value.trim();
  const desc = document.getElementById('newKbDesc').value.trim();
  if (!name) { alert('Name required'); return; }
  const r = await fetch(API + '/api/rag/kbs', {
    method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({name, description: desc})
  }).then(r => r.json()).catch(() => ({error:'failed'}));
  if (r.error) { alert('Error: ' + r.error); return; }
  closeModal();
  document.getElementById('newKbName').value = '';
  document.getElementById('newKbDesc').value = '';
  await loadKbList();
  selectKb(r.id);
}

// ── Utils ──────────────────────────────────────────────────────────────────
function escHtml(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

init();
</script>
</body>
</html>"""


_MODELS_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kendr &mdash; LLM Models</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
:root{--bg:#0d1117;--surface:#161b22;--surface2:#1c2128;--border:#30363d;--text:#e6edf3;--muted:#8b949e;--teal:#00c9a7;--amber:#ffb347;--red:#f85149;--violet:#7b61ff}
body{background:var(--bg);color:var(--text);font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;display:flex;height:100vh;overflow:hidden}
.sidebar{width:200px;flex-shrink:0;background:var(--surface);border-right:1px solid var(--border);display:flex;flex-direction:column;padding:16px 0;gap:4px}
.logo{padding:0 16px 14px;border-bottom:1px solid var(--border);margin-bottom:10px}
.logo h1{font-size:18px;font-weight:800;color:var(--teal)}
.logo small{font-size:10px;color:var(--muted)}
.nav-btn{display:flex;align-items:center;gap:8px;padding:8px 16px;color:var(--muted);text-decoration:none;font-size:13px;border-radius:0;transition:all .15s}
.nav-btn:hover{background:var(--surface2);color:var(--text)}
.nav-btn.active{background:rgba(0,201,167,.1);color:var(--teal);border-left:2px solid var(--teal)}
.nav-btn .icon{font-size:15px}
.main{flex:1;overflow-y:auto;padding:24px}
.page-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:18px}
.page-title{font-size:20px;font-weight:800}
.active-bar{background:var(--surface);border:1px solid var(--teal);border-radius:10px;padding:14px 20px;margin-bottom:20px;display:flex;align-items:center;gap:18px}
.active-provider-name{font-size:16px;font-weight:700;color:var(--teal)}
.active-model-name{font-size:13px;color:var(--muted);margin-left:4px}
.active-badge{background:rgba(0,201,167,.15);color:var(--teal);font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px}
.providers-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(260px,1fr));gap:14px;margin-bottom:30px}
.provider-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px;display:flex;flex-direction:column;gap:10px;transition:border-color .2s,box-shadow .2s;cursor:pointer}
.provider-card:hover{border-color:rgba(0,201,167,.4);box-shadow:0 4px 18px rgba(0,201,167,.08)}
.provider-card.active-card{border-color:var(--teal);box-shadow:0 0 0 1px var(--teal)}
.provider-card.needs-key{border-color:rgba(255,179,71,.3);opacity:.75}
.provider-card.needs-key:hover{border-color:rgba(255,179,71,.6);opacity:1}
.pcard-header{display:flex;align-items:flex-start;gap:10px}
.pcard-emoji{font-size:24px;flex-shrink:0}
.pcard-info{flex:1}
.pcard-name{font-size:14px;font-weight:700;margin-bottom:2px}
.pcard-type{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.pcard-status{display:inline-flex;align-items:center;gap:4px;padding:2px 8px;border-radius:20px;font-size:10px;font-weight:700;white-space:nowrap}
.st-active{background:rgba(0,201,167,.15);color:var(--teal)}
.st-ready{background:rgba(0,201,167,.10);color:var(--teal)}
.st-nokey{background:rgba(255,179,71,.12);color:var(--amber)}
.pcard-model{font-size:11px;color:var(--muted);background:var(--surface2);border:1px solid var(--border);border-radius:5px;padding:2px 8px;display:inline-block;margin-top:2px;max-width:100%;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.pcard-note{font-size:11px;color:var(--muted)}
.set-btn{background:var(--teal);color:#0d1117;border:none;border-radius:6px;padding:6px 14px;font-size:11px;font-weight:700;cursor:pointer;width:100%}
.set-btn:hover{opacity:.85}
.cfg-btn{background:transparent;color:var(--amber);border:1px solid rgba(255,179,71,.4);border-radius:6px;padding:6px 14px;font-size:11px;font-weight:600;cursor:pointer;width:100%}
.cfg-btn:hover{background:rgba(255,179,71,.08)}
/* Ollama section */
.section-title{font-size:14px;font-weight:700;margin-bottom:12px;display:flex;align-items:center;gap:8px}
.ollama-box{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:18px;margin-bottom:24px}
.ollama-status{display:flex;align-items:center;gap:8px;margin-bottom:14px;padding-bottom:12px;border-bottom:1px solid var(--border)}
.dot{width:8px;height:8px;border-radius:50%;flex-shrink:0}
.dot.green{background:var(--teal)}
.dot.red{background:var(--red)}
.ollama-models-list{display:flex;flex-wrap:wrap;gap:8px;margin-bottom:14px}
.ollama-model-chip{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:4px 10px;font-size:12px;display:flex;align-items:center;gap:6px}
.use-chip-btn{background:none;border:none;color:var(--teal);font-size:11px;font-weight:700;cursor:pointer;padding:0}
.use-chip-btn:hover{text-decoration:underline}
.pull-row{display:flex;gap:8px;align-items:center;margin-top:10px}
.pull-input{flex:1;background:var(--surface2);border:1px solid var(--border);border-radius:7px;padding:8px 12px;font-size:12px;color:var(--text);outline:none}
.pull-input:focus{border-color:var(--teal)}
.pull-btn{background:var(--violet);color:#fff;border:none;border-radius:7px;padding:8px 18px;font-size:12px;font-weight:700;cursor:pointer;white-space:nowrap}
.pull-btn:hover{opacity:.85}
.pull-status{font-size:12px;color:var(--muted);margin-top:6px}
/* cfg modal */
.modal-overlay{display:none;position:fixed;inset:0;background:rgba(0,0,0,.65);z-index:1000;align-items:center;justify-content:center}
.modal-box{background:var(--surface);border:1px solid var(--border);border-radius:14px;width:460px;max-height:85vh;overflow-y:auto;padding:22px}
.modal-title{font-size:15px;font-weight:700;margin-bottom:14px;display:flex;align-items:center;justify-content:space-between}
.modal-close{background:none;border:none;color:var(--muted);font-size:20px;cursor:pointer;line-height:1}
.field-row{margin-bottom:14px}
.field-label{font-size:11px;font-weight:700;color:var(--teal);text-transform:uppercase;letter-spacing:.04em;margin-bottom:3px;display:block}
.field-hint{font-size:11px;color:var(--muted);margin-bottom:4px}
.field-input{width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;font-size:12px;color:var(--text);outline:none}
.field-input:focus{border-color:var(--teal)}
.modal-actions{display:flex;gap:10px;margin-top:18px}
.btn-save{flex:1;background:var(--teal);color:#0d1117;border:none;border-radius:8px;padding:10px;font-size:13px;font-weight:700;cursor:pointer}
.btn-save:hover{opacity:.85}
.btn-cancel{background:var(--surface2);border:1px solid var(--border);color:var(--muted);border-radius:8px;padding:10px 18px;font-size:13px;cursor:pointer}
.toast{position:fixed;bottom:24px;right:24px;background:var(--teal);color:#0d1117;padding:10px 20px;border-radius:8px;font-size:13px;font-weight:700;z-index:2000;display:none}
</style>
</head>
<body>
<nav class="sidebar">
  <div class="logo"><h1>kendr</h1><small>multi-agent runtime</small></div>
  <a href="/" class="nav-btn"><span class="icon">&#x1F4AC;</span> Chat</a>
  <a href="/setup" class="nav-btn"><span class="icon">&#x2699;&#xFE0F;</span> Setup &amp; Config</a>
  <a href="/runs" class="nav-btn"><span class="icon">&#x1F4CB;</span> Run History</a>
  <a href="/skills" class="nav-btn"><span class="icon">&#x1F9E0;</span> Skill Cards</a>
  <a href="/models" class="nav-btn active"><span class="icon">&#x1F916;</span> LLM Models</a>
    <a href="/capabilities" class="nav-btn"><span class="icon">&#x2692;&#xFE0F;</span> Capabilities</a>
  <a href="/projects" class="nav-btn"><span class="icon">&#x1F4C1;</span> Projects</a>
  <a href="/docs" class="nav-btn"><span class="icon">&#x1F4D6;</span> Docs</a>
</nav>

<main class="main">
  <div class="page-header">
    <div class="page-title">&#x1F916; LLM Models &amp; Providers</div>
    <div style="display:flex;gap:10px">
      <button onclick="loadModels()" style="background:var(--surface);border:1px solid var(--border);color:var(--muted);padding:6px 14px;border-radius:8px;font-size:12px;cursor:pointer">&#x21BB; Refresh</button>
    </div>
  </div>

  <!-- Active provider bar -->
  <div class="active-bar" id="activeBar">
    <div>
      <div style="font-size:11px;color:var(--muted);margin-bottom:2px">Active Provider</div>
      <div style="display:flex;align-items:center;gap:8px">
        <span class="active-provider-name" id="activeProviderName">loading...</span>
        <span class="active-badge">ACTIVE</span>
      </div>
    </div>
    <div style="width:1px;height:36px;background:var(--border)"></div>
    <div>
      <div style="font-size:11px;color:var(--muted);margin-bottom:2px">Model</div>
      <span class="active-model-name" id="activeModelName">...</span>
    </div>
    <div style="margin-left:auto">
      <button onclick="openTestModal()" style="background:rgba(0,201,167,.12);color:var(--teal);border:1px solid rgba(0,201,167,.3);border-radius:8px;padding:6px 14px;font-size:12px;font-weight:700;cursor:pointer">&#x26A1; Test</button>
    </div>
  </div>

  <!-- Providers grid -->
  <div class="section-title">All Providers</div>
  <div class="providers-grid" id="providersGrid"></div>

  <!-- Ollama section -->
  <div class="section-title" id="ollamaTitle">&#x1F4BB; Ollama &mdash; Local Models</div>
  <div class="ollama-box" id="ollamaBox">
    <!-- Server status row -->
    <div class="ollama-status" id="ollamaStatus">
      <div class="dot red" id="ollamaDot"></div>
      <span id="ollamaStatusText">Checking...</span>
      <span style="margin-left:auto;font-size:11px;color:var(--muted)">localhost:11434</span>
    </div>

    <!-- Docker control panel -->
    <div id="dockerPanel" style="background:var(--surface2);border:1px solid var(--border);border-radius:10px;padding:14px;margin-bottom:14px">
      <div style="display:flex;align-items:center;gap:8px;margin-bottom:10px">
        <span style="font-size:13px;font-weight:700">&#x1F433; Docker Container</span>
        <span id="dockerStatusBadge" style="font-size:11px;padding:2px 8px;border-radius:999px;background:rgba(255,255,255,.08);color:var(--muted)">checking...</span>
        <span id="dockerModeBadge" style="display:none;font-size:11px;padding:2px 8px;border-radius:999px"></span>
      </div>
      <div id="dockerContainerInfo" style="font-size:11px;color:var(--muted);margin-bottom:10px;display:none"></div>
      <div style="display:flex;gap:8px;flex-wrap:wrap">
        <button id="dockerStartCpuBtn" onclick="dockerStart(false)"
          style="background:rgba(0,201,167,.12);color:var(--teal);border:1px solid rgba(0,201,167,.3);border-radius:7px;padding:7px 14px;font-size:12px;font-weight:700;cursor:pointer">
          &#x25B6; Start (CPU)
        </button>
        <button id="dockerStartGpuBtn" onclick="dockerStart(true)"
          style="background:rgba(139,92,246,.12);color:#a78bfa;border:1px solid rgba(139,92,246,.3);border-radius:7px;padding:7px 14px;font-size:12px;font-weight:700;cursor:pointer">
          &#x26A1; Start (GPU)
        </button>
        <button id="dockerStopBtn" onclick="dockerStop()" style="display:none;background:rgba(239,68,68,.12);color:#f87171;border:1px solid rgba(239,68,68,.3);border-radius:7px;padding:7px 14px;font-size:12px;font-weight:700;cursor:pointer">
          &#x25A0; Stop Container
        </button>
      </div>
      <div id="dockerActionStatus" style="font-size:11px;color:var(--muted);margin-top:8px"></div>
      <div style="margin-top:10px;padding-top:10px;border-top:1px solid var(--border);font-size:11px;color:var(--muted)">
        CLI: <code style="background:var(--surface);padding:1px 5px;border-radius:3px">kendr model ollama docker start</code> &nbsp;|&nbsp;
        <code style="background:var(--surface);padding:1px 5px;border-radius:3px">kendr model ollama docker start --gpu</code> &nbsp;|&nbsp;
        <code style="background:var(--surface);padding:1px 5px;border-radius:3px">kendr model ollama docker stop</code>
      </div>
    </div>

    <!-- Installed models -->
    <div id="ollamaModelsArea">
      <div style="font-size:12px;color:var(--muted);margin-bottom:8px">Installed models:</div>
      <div class="ollama-models-list" id="ollamaModelsList"></div>
    </div>
    <div class="pull-row">
      <input class="pull-input" id="pullInput" placeholder="llama3.2, mistral, deepseek-r1, qwen2.5..." onkeydown="if(event.key==='Enter')pullOllamaModel()">
      <button class="pull-btn" onclick="pullOllamaModel()">&#x2193; Pull Model</button>
    </div>
    <div class="pull-status" id="pullStatus"></div>
  </div>
</main>

<!-- Configure modal -->
<div class="modal-overlay" id="cfgModal">
  <div class="modal-box">
    <div class="modal-title">
      <span id="cfgModalTitle">Configure Provider</span>
      <button class="modal-close" onclick="closeCfgModal()">&times;</button>
    </div>
    <div id="cfgModalBody"></div>
    <div class="modal-actions">
      <button class="btn-save" onclick="saveCfgModal()">Save &amp; Activate</button>
      <button class="btn-cancel" onclick="closeCfgModal()">Cancel</button>
    </div>
  </div>
</div>

<!-- Test modal -->
<div class="modal-overlay" id="testModal">
  <div class="modal-box" style="width:520px">
    <div class="modal-title">
      <span>&#x26A1; Test Current Model</span>
      <button class="modal-close" onclick="closeTestModal()">&times;</button>
    </div>
    <div id="testResult" style="font-size:13px;color:var(--muted);min-height:80px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:14px;line-height:1.6;white-space:pre-wrap">Click "Run Test" to send a hello prompt to the active model.</div>
    <div class="modal-actions">
      <button class="btn-save" onclick="runModelTest()">&#x25B6; Run Test</button>
      <button class="btn-cancel" onclick="closeTestModal()">Close</button>
    </div>
  </div>
</div>

<div class="toast" id="toast"></div>

<script>
const PROVIDER_META = {
  openai:      { emoji: '\uD83D\uDFE2', label: 'OpenAI',              type: 'Cloud API',     models: ['gpt-4o','gpt-4o-mini','gpt-5','o3'], keyEnv: 'OPENAI_API_KEY',      hint: 'platform.openai.com/api-keys' },
  anthropic:   { emoji: '\uD83D\uDCA0', label: 'Anthropic (Claude)',  type: 'Cloud API',     models: ['claude-opus-4-6','claude-sonnet-4-6','claude-haiku-4-5'], keyEnv: 'ANTHROPIC_API_KEY', hint: 'console.anthropic.com' },
  google:      { emoji: '\uD83D\uDD35', label: 'Google Gemini',       type: 'Cloud API',     models: ['gemini-2.5-pro','gemini-2.0-flash','gemini-1.5-pro'], keyEnv: 'GOOGLE_API_KEY', hint: 'aistudio.google.com' },
  xai:         { emoji: '\u274E',       label: 'xAI (Grok)',          type: 'Cloud API',     models: ['grok-4','grok-4.20-beta-latest-non-reasoning','grok-4-1-fast-reasoning'], keyEnv: 'XAI_API_KEY',       hint: 'docs.x.ai/developers/models' },
  minimax:     { emoji: '\uD83C\uDF00', label: 'MiniMax',             type: 'Cloud API',     models: ['MiniMax-M2','image-01'], keyEnv: 'MINIMAX_API_KEY',   hint: 'platform.minimaxi.com' },
  qwen:        { emoji: '\uD83D\uDCCA', label: 'Qwen (Alibaba)',      type: 'Cloud API',     models: ['qwen-max','qwen-plus','qwen-turbo'], keyEnv: 'QWEN_API_KEY',    hint: 'dashscope.aliyuncs.com' },
  glm:         { emoji: '\u26A1',       label: 'GLM (Zhipu AI)',      type: 'Cloud API',     models: ['glm-5','glm-4','glm-4-flash'], keyEnv: 'GLM_API_KEY',     hint: 'bigmodel.cn' },
  ollama:      { emoji: '\uD83D\uDCBB', label: 'Ollama',              type: 'Local (no key)',models: ['llama3.2','mistral','deepseek-r1','qwen2.5','gemma3'], keyEnv: '', hint: 'ollama.ai' },
  openrouter:  { emoji: '\uD83D\uDEE3', label: 'OpenRouter',          type: 'Multi-provider',models: ['openai/gpt-4o','anthropic/claude-3-5-sonnet','meta-llama/llama-3.1-8b-instruct'], keyEnv: 'OPENROUTER_API_KEY', hint: 'openrouter.ai/keys' },
  custom:      { emoji: '\uD83D\uDD27', label: 'Custom / Self-hosted',type: 'Self-hosted',   models: [], keyEnv: '', hint: 'Any OpenAI-compatible server' },
};

let _data = {};

function showToast(msg, err) {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.style.background = err ? 'var(--red)' : 'var(--teal)';
  t.style.color = err ? '#fff' : '#0d1117';
  t.style.display = 'block';
  setTimeout(() => { t.style.display = 'none'; }, 3200);
}

function esc(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

async function loadModels() {
  try {
    const r = await fetch('/api/models');
    _data = await r.json();
    renderActiveBar(_data);
    renderProviders(_data);
    renderOllama(_data);
  } catch(e) {
    document.getElementById('providersGrid').innerHTML = '<div style="color:var(--muted);grid-column:1/-1;padding:30px 0">Could not load provider data.</div>';
  }
}

function renderActiveBar(d) {
  const meta = PROVIDER_META[d.active_provider] || {};
  document.getElementById('activeProviderName').textContent = (meta.label || d.active_provider) + ' ' + (meta.emoji || '');
  document.getElementById('activeModelName').textContent = d.active_model || '(default)';
}

function selectedProviderModel(providerId, fallbackModel) {
  const sel = document.getElementById('providerModelSelect-' + providerId);
  return sel && sel.value ? sel.value : (fallbackModel || '');
}

function renderProviders(d) {
  const grid = document.getElementById('providersGrid');
  const active = d.active_provider;
  const statuses = {};
  (d.providers || []).forEach(s => { statuses[s.provider] = s; });

  grid.innerHTML = Object.entries(PROVIDER_META).map(([id, meta]) => {
    const st = statuses[id] || {};
    const isActive = id === active;
    const ready = st.ready;
    const model = st.model || (meta.models[0] || '');
    const selectable = Array.isArray(st.selectable_models) && st.selectable_models.length ? st.selectable_models : (ready && model ? [model] : []);
    const statusCls = isActive ? 'st-active' : ready ? 'st-ready' : 'st-nokey';
    const statusLabel = isActive
      ? '\u2714 Active'
      : ready
        ? '\u2714 Ready'
        : id === 'ollama'
          ? '\u25A0 Offline'
          : id === 'custom'
            ? '\u2699 Configure'
            : '\u26A1 Add Key';
    const cardCls = isActive ? 'provider-card active-card' : ready ? 'provider-card' : 'provider-card needs-key';

    let btn = '';
    if (!isActive && ready) {
      btn = `<button class="set-btn" onclick="setActive('${id}', selectedProviderModel('${id}','${esc(model)}'))">Set as Active</button>`;
    } else if (!ready && id !== 'ollama' && id !== 'custom') {
      btn = `<button class="cfg-btn" onclick="openCfg('${id}')">Add API Key</button>`;
    } else if (id === 'custom') {
      btn = `<button class="cfg-btn" onclick="openCfg('${id}')">Configure Endpoint</button>`;
    } else if (id === 'ollama') {
      btn = ready
        ? `<button class="set-btn" onclick="setActive('ollama', selectedProviderModel('ollama','${esc(model)}'))">Use Ollama</button>`
        : `<button class="cfg-btn" onclick="document.getElementById('ollamaTitle').scrollIntoView({behavior:'smooth'})">Start Ollama</button>`;
    } else {
      btn = ready
        ? `<button class="cfg-btn" onclick="setActive('${id}', selectedProviderModel('${id}','${esc(model)}'))">Save Default</button>`
        : `<button class="cfg-btn" onclick="openCfg('${id}')">Edit Settings</button>`;
    }

    const modelSelect = ready && selectable.length
      ? `<select class="chat-model-select" id="providerModelSelect-${id}" title="Choose default model">${selectable.map(name => `<option value="${esc(name)}" ${name === model ? 'selected' : ''}>${esc(name)}</option>`).join('')}</select>`
      : `<div class="pcard-model" title="${esc(model)}">${esc(model) || '(not set)'}</div>`;

    return `<div class="${cardCls}">
      <div class="pcard-header">
        <div class="pcard-emoji">${meta.emoji}</div>
        <div class="pcard-info">
          <div class="pcard-name">${esc(meta.label)}</div>
          <div class="pcard-type">${esc(meta.type)}</div>
        </div>
        <div class="pcard-status ${statusCls}">${statusLabel}</div>
      </div>
      ${modelSelect}
      <div class="pcard-note">${esc(st.note || meta.hint || '')}</div>
      ${btn}
    </div>`;
  }).join('');
}

function renderOllama(d) {
  const running = d.ollama_running;
  document.getElementById('ollamaDot').className = 'dot ' + (running ? 'green' : 'red');
  document.getElementById('ollamaStatusText').textContent = running ? 'Running \u2714' : 'Not running \u2014 use Docker below or run: ollama serve';
  const models = d.ollama_models || [];
  const list = document.getElementById('ollamaModelsList');
  if (models.length === 0) {
    list.innerHTML = '<div style="font-size:12px;color:var(--muted)">' + (running ? 'No models installed yet. Pull one below.' : 'Start Ollama to see installed models.') + '</div>';
  } else {
    list.innerHTML = models.map(m =>
      `<div class="ollama-model-chip">
         ${esc(m)}
         <button class="use-chip-btn" onclick="setActive('ollama','${esc(m)}')">Use</button>
       </div>`
    ).join('');
  }
  loadDockerStatus();
}

async function loadDockerStatus() {
  try {
    const d = await fetch('/api/models/ollama/docker/status').then(r => r.json());
    renderDockerStatus(d);
  } catch(e) {
    document.getElementById('dockerStatusBadge').textContent = 'docker unavailable';
  }
}

function renderDockerStatus(d) {
  const badge = document.getElementById('dockerStatusBadge');
  const modeBadge = document.getElementById('dockerModeBadge');
  const infoEl = document.getElementById('dockerContainerInfo');
  const startCpu = document.getElementById('dockerStartCpuBtn');
  const startGpu = document.getElementById('dockerStartGpuBtn');
  const stopBtn = document.getElementById('dockerStopBtn');

  if (d.running) {
    badge.textContent = 'running';
    badge.style.background = 'rgba(0,201,167,.15)';
    badge.style.color = 'var(--teal)';
    const gpu = d.gpu;
    modeBadge.style.display = 'inline';
    modeBadge.textContent = gpu ? '\u26A1 GPU' : '\uD83D\uDCBB CPU';
    modeBadge.style.background = gpu ? 'rgba(139,92,246,.15)' : 'rgba(255,255,255,.06)';
    modeBadge.style.color = gpu ? '#a78bfa' : 'var(--muted)';
    infoEl.style.display = 'block';
    infoEl.textContent = 'Container: ' + (d.name || 'kendr-ollama') + '  \u00b7  Port: 11434  \u00b7  Image: ' + (d.image || 'ollama/ollama');
    startCpu.style.display = 'none';
    startGpu.style.display = 'none';
    stopBtn.style.display = 'inline-block';
  } else {
    badge.textContent = d.docker_available ? 'stopped' : 'docker not found';
    badge.style.background = 'rgba(255,255,255,.06)';
    badge.style.color = 'var(--muted)';
    modeBadge.style.display = 'none';
    infoEl.style.display = 'none';
    startCpu.style.display = 'inline-block';
    startGpu.style.display = 'inline-block';
    stopBtn.style.display = 'none';
  }
}

async function dockerStart(gpu) {
  const statusEl = document.getElementById('dockerActionStatus');
  const startCpu = document.getElementById('dockerStartCpuBtn');
  const startGpu = document.getElementById('dockerStartGpuBtn');
  statusEl.textContent = (gpu ? '\u26A1 Starting with GPU...' : '\u25B6 Starting with CPU...') + ' (pulling image if needed, ~30s)';
  startCpu.disabled = true;
  startGpu.disabled = true;
  try {
    const r = await fetch('/api/models/ollama/docker/start', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ gpu })
    });
    const d = await r.json();
    if (d.ok) {
      statusEl.textContent = '\u2714 Container started! Ollama is now running on port 11434.';
      showToast('\u2714 Ollama Docker container started');
      await loadModels();
    } else {
      statusEl.textContent = '\u274C ' + (d.error || 'Start failed');
    }
  } catch(e) {
    statusEl.textContent = '\u274C Error: ' + e.message;
  }
  startCpu.disabled = false;
  startGpu.disabled = false;
}

async function dockerStop() {
  const statusEl = document.getElementById('dockerActionStatus');
  const stopBtn = document.getElementById('dockerStopBtn');
  statusEl.textContent = 'Stopping container...';
  stopBtn.disabled = true;
  try {
    const r = await fetch('/api/models/ollama/docker/stop', { method: 'POST' });
    const d = await r.json();
    if (d.ok) {
      statusEl.textContent = '\u2714 Container stopped.';
      showToast('\u25A0 Ollama Docker container stopped');
      await loadModels();
    } else {
      statusEl.textContent = '\u274C ' + (d.error || 'Stop failed');
    }
  } catch(e) {
    statusEl.textContent = '\u274C Error: ' + e.message;
  }
  stopBtn.disabled = false;
}

async function setActive(provider, model) {
  try {
    const r = await fetch('/api/models/set', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ provider, model })
    });
    const d = await r.json();
    if (d.saved) {
      showToast('\u2714 Switched to ' + provider + (model ? ' / ' + model : ''));
      await loadModels();
    } else {
      showToast(d.error || 'Save failed', true);
    }
  } catch(e) { showToast('Error: ' + e.message, true); }
}

async function pullOllamaModel() {
  const input = document.getElementById('pullInput');
  const model = input.value.trim();
  if (!model) return;
  const status = document.getElementById('pullStatus');
  status.textContent = 'Pulling ' + model + '... (this may take a minute)';
  try {
    const r = await fetch('/api/models/ollama/pull', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ model })
    });
    const d = await r.json();
    if (d.ok) {
      status.textContent = '\u2714 Pulled ' + model + ' successfully!';
      input.value = '';
      showToast('\u2714 ' + model + ' is ready');
      await loadModels();
    } else {
      status.textContent = '\u274C ' + (d.error || 'Pull failed');
    }
  } catch(e) { status.textContent = '\u274C Error: ' + e.message; }
}

// Config modal
const CFG_FIELDS = {
  openai:     [{ key:'OPENAI_API_KEY', label:'API Key', secret:true, hint:'From platform.openai.com/api-keys' },
               { key:'OPENAI_MODEL_GENERAL', label:'General Model', hint:'e.g. gpt-4o, gpt-4o-mini, gpt-5' },
               { key:'OPENAI_MODEL_CODING', label:'Coding Model', hint:'e.g. gpt-4o (for coding agents)' }],
  anthropic:  [{ key:'ANTHROPIC_API_KEY', label:'API Key', secret:true, hint:'From console.anthropic.com' },
               { key:'ANTHROPIC_MODEL', label:'Default Model', hint:'e.g. claude-opus-4-6, claude-haiku-4-5' }],
  google:     [{ key:'GOOGLE_API_KEY', label:'API Key', secret:true, hint:'From aistudio.google.com' },
               { key:'GOOGLE_MODEL', label:'Default Model', hint:'e.g. gemini-2.5-pro, gemini-2.0-flash' }],
  xai:        [{ key:'XAI_API_KEY', label:'API Key', secret:true, hint:'From console.x.ai' },
               { key:'XAI_MODEL', label:'Default Model', hint:'e.g. grok-4, grok-4.20-beta-latest-non-reasoning' }],
  minimax:    [{ key:'MINIMAX_API_KEY', label:'API Key', secret:true, hint:'From platform.minimaxi.com' },
               { key:'MINIMAX_MODEL', label:'Default Model', hint:'e.g. MiniMax-M2' }],
  qwen:       [{ key:'QWEN_API_KEY', label:'API Key', secret:true, hint:'From dashscope.aliyuncs.com' },
               { key:'QWEN_MODEL', label:'Default Model', hint:'e.g. qwen-max, qwen-plus' }],
  glm:        [{ key:'GLM_API_KEY', label:'API Key', secret:true, hint:'From bigmodel.cn' },
               { key:'GLM_MODEL', label:'Default Model', hint:'e.g. glm-5, glm-4' }],
  ollama:     [{ key:'OLLAMA_BASE_URL', label:'Server URL', hint:'Default: http://localhost:11434' },
               { key:'OLLAMA_MODEL', label:'Default Model', hint:'e.g. llama3.2, mistral, deepseek-r1' }],
  openrouter: [{ key:'OPENROUTER_API_KEY', label:'API Key', secret:true, hint:'From openrouter.ai/keys' },
               { key:'OPENROUTER_MODEL', label:'Default Model', hint:'e.g. openai/gpt-4o, anthropic/claude-3-5-sonnet' }],
  custom:     [{ key:'CUSTOM_LLM_BASE_URL', label:'Base URL', hint:'e.g. http://localhost:1234/v1' },
               { key:'CUSTOM_LLM_MODEL', label:'Model Name', hint:'As expected by the server' },
               { key:'CUSTOM_LLM_API_KEY', label:'API Key (optional)', secret:true, hint:'Bearer token if required' }],
};

let _cfgProvider = null;

function openCfg(provider) {
  _cfgProvider = provider;
  const meta = PROVIDER_META[provider] || {};
  document.getElementById('cfgModalTitle').textContent = (meta.emoji || '') + ' Configure ' + (meta.label || provider);
  const fields = CFG_FIELDS[provider] || [];
  document.getElementById('cfgModalBody').innerHTML = fields.map(f => `
    <div class="field-row">
      <label class="field-label">${esc(f.label)}</label>
      <div class="field-hint">${esc(f.hint || '')}</div>
      <input id="cfg-${f.key}" class="field-input" type="${f.secret?'password':'text'}" placeholder="${esc(f.key)}"
             style="${f.secret?'font-family:monospace':''}">
    </div>`).join('');
  document.getElementById('cfgModal').style.display = 'flex';
}

function closeCfgModal() { document.getElementById('cfgModal').style.display = 'none'; }

async function saveCfgModal() {
  const fields = CFG_FIELDS[_cfgProvider] || [];
  const values = {};
  fields.forEach(f => {
    const el = document.getElementById('cfg-' + f.key);
    if (el && el.value.trim()) values[f.key] = el.value.trim();
  });
  try {
    const r = await fetch('/api/setup/save', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ component_id: _cfgProvider === 'google' ? 'google_gemini' : _cfgProvider, values })
    });
    const d = await r.json();
    closeCfgModal();
    showToast('\u2714 Saved ' + _cfgProvider + ' configuration');
    // If credentials now complete, set as active
    await fetch('/api/models/set', { method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ provider: _cfgProvider, model: '' }) });
    await loadModels();
  } catch(e) { showToast('\u274C Save failed: ' + e.message, true); }
}

function openTestModal() { document.getElementById('testModal').style.display = 'flex'; }
function closeTestModal() { document.getElementById('testModal').style.display = 'none'; }

async function runModelTest() {
  const el = document.getElementById('testResult');
  el.textContent = 'Sending test prompt...';
  try {
    const r = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ query: 'Say hello in one sentence.', session_id: '__model_test__' })
    });
    const d = await r.json();
    el.textContent = d.reply || d.content || d.answer || JSON.stringify(d, null, 2);
  } catch(e) { el.textContent = 'Error: ' + e.message; }
}

loadModels();
</script>
</body>
</html>"""


_MCP_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kendr &mdash; MCP Servers</title>
<style>
:root { --teal: #00C9A7; --amber: #FFB347; --crimson: #FF4757; --purple: #A78BFA; --bg: #0d0f14; --surface: #161b22; --surface2: #1e2530; --surface3: #252d3a; --border: #2a3140; --text: #e6edf3; --muted: #7d8590; --sidebar-w: 280px; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "Segoe UI", system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; }
.sidebar { width: var(--sidebar-w); min-width: var(--sidebar-w); background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; position: fixed; top: 0; bottom: 0; left: 0; }
.sidebar-header { padding: 20px 16px 12px; border-bottom: 1px solid var(--border); }
.logo { font-size: 22px; font-weight: 800; color: var(--teal); }
.logo span { color: var(--amber); }
.tagline { font-size: 11px; color: var(--muted); margin-top: 4px; }
.sidebar-nav { padding: 12px 8px; border-bottom: 1px solid var(--border); display: flex; flex-direction: column; gap: 4px; }
.nav-btn { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-radius: 8px; font-size: 13px; font-weight: 500; color: var(--muted); cursor: pointer; border: none; background: transparent; width: 100%; text-align: left; text-decoration: none; transition: background 0.15s, color 0.15s; }
.nav-btn:hover { background: var(--surface2); color: var(--text); }
.nav-btn.active { background: rgba(167,139,250,0.12); color: var(--purple); }
.nav-btn .icon { font-size: 16px; width: 20px; text-align: center; }
.main { flex: 1; margin-left: var(--sidebar-w); padding: 32px; max-width: 960px; }
.page-title { font-size: 26px; font-weight: 700; margin-bottom: 6px; }
.page-subtitle { font-size: 13px; color: var(--muted); margin-bottom: 28px; }
/* Cards */
.section-title { font-size: 13px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.07em; margin: 28px 0 12px; }
.card { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 18px 20px; margin-bottom: 12px; }
.card-header { display: flex; align-items: center; gap: 12px; }
.server-name { font-size: 15px; font-weight: 600; flex: 1; }
.server-meta { font-size: 12px; color: var(--muted); margin-top: 3px; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.badge.connected { background: rgba(0,201,167,0.15); color: var(--teal); }
.badge.error { background: rgba(255,71,87,0.15); color: var(--crimson); }
.badge.unknown { background: rgba(125,133,144,0.15); color: var(--muted); }
.badge.http { background: rgba(0,201,167,0.1); color: var(--teal); }
.badge.stdio { background: rgba(167,139,250,0.1); color: var(--purple); }
.tools-toggle { background: none; border: 1px solid var(--border); color: var(--teal); border-radius: 6px; padding: 4px 10px; cursor: pointer; font-size: 12px; }
.tools-toggle:hover { background: var(--surface2); }
.btn { padding: 8px 16px; border-radius: 7px; font-size: 13px; font-weight: 600; cursor: pointer; border: none; transition: opacity 0.15s; }
.btn:hover { opacity: 0.85; }
.btn-primary { background: var(--teal); color: #0d0f14; }
.btn-sm { padding: 5px 12px; font-size: 12px; }
.btn-danger { background: rgba(255,71,87,0.12); color: var(--crimson); border: 1px solid rgba(255,71,87,0.3); }
.btn-ghost { background: none; color: var(--muted); border: 1px solid var(--border); }
.tool-list { margin-top: 14px; border-top: 1px solid var(--border); padding-top: 12px; display: none; }
.tool-list.open { display: block; }
.tool-item { display: flex; gap: 10px; padding: 8px 0; border-bottom: 1px solid var(--border); }
.tool-item:last-child { border-bottom: none; }
.tool-name { font-family: monospace; font-size: 13px; color: var(--teal); font-weight: 600; min-width: 160px; }
.tool-desc { font-size: 12px; color: var(--muted); flex: 1; }
/* Add form */
.form-section { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 20px; margin-bottom: 24px; }
.form-row { display: grid; grid-template-columns: 1fr 1fr; gap: 14px; margin-bottom: 14px; }
.form-full { margin-bottom: 14px; }
label { display: block; font-size: 12px; font-weight: 600; color: var(--muted); margin-bottom: 5px; text-transform: uppercase; letter-spacing: 0.05em; }
input, select, textarea { width: 100%; background: var(--surface2); border: 1px solid var(--border); border-radius: 7px; padding: 9px 12px; color: var(--text); font-size: 13px; outline: none; transition: border-color 0.15s; }
input:focus, select:focus, textarea:focus { border-color: var(--teal); }
textarea { resize: vertical; min-height: 60px; font-family: inherit; }
.form-actions { display: flex; gap: 10px; align-items: center; }
.msg { font-size: 12px; padding: 6px 10px; border-radius: 6px; }
.msg.ok { background: rgba(0,201,167,0.1); color: var(--teal); }
.msg.err { background: rgba(255,71,87,0.1); color: var(--crimson); }
/* Scaffold */
.scaffold-box { background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 16px; position: relative; }
.scaffold-box pre { font-family: "Cascadia Code", "Fira Code", monospace; font-size: 12px; color: #b5c4de; white-space: pre-wrap; word-break: break-word; max-height: 420px; overflow-y: auto; }
.copy-btn { position: absolute; top: 10px; right: 10px; background: var(--surface); border: 1px solid var(--border); color: var(--teal); border-radius: 6px; padding: 4px 10px; font-size: 11px; cursor: pointer; }
.copy-btn:hover { background: var(--surface2); }
/* Toggle switch */
.toggle { position: relative; display: inline-block; width: 34px; height: 20px; }
.toggle input { opacity: 0; width: 0; height: 0; }
.slider { position: absolute; cursor: pointer; inset: 0; background: var(--border); border-radius: 20px; transition: 0.2s; }
.slider:before { position: absolute; content: ""; height: 14px; width: 14px; left: 3px; bottom: 3px; background: #fff; border-radius: 50%; transition: 0.2s; }
input:checked + .slider { background: var(--teal); }
input:checked + .slider:before { transform: translateX(14px); }
.disc-spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--border); border-top-color: var(--teal); border-radius: 50%; animation: spin 0.7s linear infinite; vertical-align: middle; }
@keyframes spin { to { transform: rotate(360deg); } }
.error-box { background: rgba(255,71,87,0.07); border: 1px solid rgba(255,71,87,0.25); border-radius: 6px; padding: 8px 12px; font-size: 12px; color: var(--crimson); margin-top: 10px; }
::-webkit-scrollbar { width: 6px; } ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
</head>
<body>
<div class="sidebar">
  <div class="sidebar-header"><div class="logo">kendr<span>.</span></div><div class="tagline">Multi-agent intelligence runtime</div></div>
  <div class="sidebar-nav">
    <a href="/" class="nav-btn"><span class="icon">&#x1F4AC;</span> Chat</a>
    <a href="/setup" class="nav-btn"><span class="icon">&#x2699;&#xFE0F;</span> Setup &amp; Config</a>
    <a href="/runs" class="nav-btn"><span class="icon">&#x1F4CB;</span> Run History</a>
    <a href="/skills" class="nav-btn"><span class="icon">&#x1F9E0;</span> Skill Cards</a>
    <a href="/rag" class="nav-btn"><span class="icon">&#x1F52C;</span> Super-RAG</a>
    <a href="/models" class="nav-btn"><span class="icon">&#x1F916;</span> LLM Models</a>
    <a href="/capabilities" class="nav-btn"><span class="icon">&#x2692;&#xFE0F;</span> Capabilities</a>
    <a href="/projects" class="nav-btn"><span class="icon">&#x1F4C1;</span> Projects</a>
    <a href="/docs" class="nav-btn"><span class="icon">&#x1F4D6;</span> Docs</a>
  </div>
</div>
<div class="main">
  <div class="page-title">MCP Servers</div>
  <div class="page-subtitle">Connect kendr to any MCP server &mdash; kendr acts as the client, just like Cursor. Tools are auto-discovered.</div>

  <!-- Featured: Zapier -->
  <div class="section-title">&#x26A1; Featured Integration</div>
  <div class="card" style="border-color:rgba(255,100,30,0.35);background:linear-gradient(135deg,#1a1208 0%,var(--surface) 100%)">
    <div class="card-header" style="align-items:flex-start;gap:16px">
      <div style="font-size:32px;line-height:1">&#x26A1;</div>
      <div style="flex:1">
        <div class="server-name" style="font-size:17px">Zapier MCP</div>
        <div class="server-meta" style="margin-top:4px">Connect 7,000+ apps via Zapier&rsquo;s official MCP server &mdash; Gmail, Slack, Notion, GitHub, Salesforce, and more.</div>
        <div style="margin-top:12px;display:flex;gap:10px;align-items:center;flex-wrap:wrap">
          <button class="btn btn-primary btn-sm" onclick="openZapierSetup()">&#x26A1; Quick Connect</button>
          <a href="https://zapier.com/mcp" target="_blank" style="font-size:12px;color:var(--teal);text-decoration:none">Get your MCP URL &#x2197;</a>
          <span style="font-size:11px;color:var(--muted)">CLI: <code style="color:var(--teal)">kendr mcp zapier &lt;your-url&gt;</code></span>
        </div>
      </div>
    </div>
    <!-- Zapier setup panel -->
    <div id="zapierSetupPanel" style="display:none;margin-top:16px;border-top:1px solid var(--border);padding-top:16px">
      <div style="font-size:12px;color:var(--muted);margin-bottom:12px">
        1. Visit <a href="https://zapier.com/mcp" target="_blank" style="color:var(--teal)">zapier.com/mcp</a> to get your personal MCP URL.<br>
        2. Paste it below &mdash; it looks like <code style="color:var(--teal)">https://mcp.zapier.com/api/mcp/s/…/mcp</code>
      </div>
      <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
        <input type="text" id="zapierUrl" placeholder="https://mcp.zapier.com/api/mcp/s/your-token/mcp" style="flex:1;min-width:260px">
        <button class="btn btn-primary btn-sm" onclick="connectZapier()">Connect &amp; Discover</button>
        <span id="zapierMsg"></span>
      </div>
    </div>
  </div>

  <!-- Add server form -->
  <div class="section-title">Connect a New MCP Server</div>
  <div class="form-section">
    <div class="form-row">
      <div>
        <label>Server Name</label>
        <input type="text" id="addName" placeholder="e.g. My Research Server">
      </div>
      <div>
        <label>Type</label>
        <select id="addType" onchange="toggleTypeHint()">
          <option value="http">HTTP / SSE</option>
          <option value="stdio">Stdio (shell command)</option>
        </select>
      </div>
    </div>
    <div class="form-full">
      <label id="connLabel">Connection URL</label>
      <input type="text" id="addConn" placeholder="http://localhost:8000/mcp">
      <div id="connHint" style="font-size:11px;color:var(--muted);margin-top:4px">HTTP or SSE endpoint — e.g. http://localhost:8000/mcp</div>
    </div>
    <div class="form-row">
      <div>
        <label>Auth Token (optional)</label>
        <input type="password" id="addToken" placeholder="Bearer token for HTTP servers" autocomplete="off">
        <div style="font-size:11px;color:var(--muted);margin-top:4px">Sent as <code>Authorization: Bearer ...</code> — leave blank if not required</div>
      </div>
      <div>
        <label>Description (optional)</label>
        <textarea id="addDesc" rows="2" placeholder="What does this server provide?"></textarea>
      </div>
    </div>
    <div class="form-actions">
      <button class="btn btn-primary" onclick="addServer()">Connect &amp; Discover Tools</button>
      <span id="addMsg"></span>
    </div>
  </div>

  <!-- Registered servers -->
  <div class="section-title">Registered Servers</div>
  <div id="serverList"><div style="color:var(--muted);font-size:13px">Loading...</div></div>

  <!-- Scaffold section -->
  <div class="section-title" style="margin-top:36px">How to Build Your Own MCP Server</div>
  <p style="font-size:13px;color:var(--muted);margin-bottom:14px">
    Any Python function decorated with <code style="color:var(--teal)">@mcp.tool</code> becomes a discoverable tool.
    Run the server, then add it above. Uses <a href="https://github.com/jlowin/fastmcp" target="_blank" style="color:var(--teal)">FastMCP</a>.
  </p>
  <div class="scaffold-box">
    <button class="copy-btn" onclick="copyScaffold()">Copy</button>
    <pre id="scaffoldCode">Loading...</pre>
  </div>
  <p style="font-size:12px;color:var(--muted);margin-top:10px">
    Add your own MCP server by pointing Kendr at its command or URL, for example <code style="color:var(--teal)">python mcp_servers/my_server.py</code>
  </p>
</div>

<script>
const API = '';

function toggleTypeHint() {
  const t = document.getElementById('addType').value;
  const lbl = document.getElementById('connLabel');
  const inp = document.getElementById('addConn');
  const hint = document.getElementById('connHint');
  if (t === 'stdio') {
    lbl.textContent = 'Shell Command';
    inp.placeholder = 'python mcp_servers/my_server.py';
    hint.textContent = 'Shell command to launch the stdio MCP server process';
  } else {
    lbl.textContent = 'Connection URL';
    inp.placeholder = 'http://localhost:8000/mcp';
    hint.textContent = 'HTTP or SSE endpoint — e.g. http://localhost:8000/mcp';
  }
}

async function addServer() {
  const name = document.getElementById('addName').value.trim();
  const type = document.getElementById('addType').value;
  const conn = document.getElementById('addConn').value.trim();
  const desc = document.getElementById('addDesc').value.trim();
  const token = document.getElementById('addToken').value.trim();
  const msg = document.getElementById('addMsg');
  if (!name) { showMsg(msg, 'Server name is required', 'err'); return; }
  if (!conn) { showMsg(msg, 'Connection is required', 'err'); return; }
  showMsg(msg, '<span class="disc-spinner"></span> Connecting and discovering tools…', 'ok');
  try {
    const payload = { name, type, connection: conn, description: desc };
    if (token) payload.auth_token = token;
    const r = await fetch(API + '/api/mcp/servers', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    const d = await r.json();
    if (d.ok || d.server_id) {
      showMsg(msg, '&#x2713; Connected — ' + (d.tool_count || 0) + ' tool(s) discovered', 'ok');
      document.getElementById('addName').value = '';
      document.getElementById('addConn').value = '';
      document.getElementById('addDesc').value = '';
      document.getElementById('addToken').value = '';
      await loadServers();
    } else {
      showMsg(msg, 'Error: ' + (d.error || JSON.stringify(d)), 'err');
    }
  } catch(e) { showMsg(msg, 'Request failed: ' + e, 'err'); }
}

function showMsg(el, text, cls) {
  el.className = 'msg ' + cls;
  el.innerHTML = text;
}

async function loadServers() {
  const box = document.getElementById('serverList');
  try {
    const r = await fetch(API + '/api/mcp/servers');
    const servers = await r.json();
    if (!servers.length) {
      box.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:16px 0">No servers registered yet. Add one above.</div>';
      return;
    }
    box.innerHTML = servers.map(s => renderServer(s)).join('');
  } catch(e) {
    box.innerHTML = '<div style="color:var(--crimson);font-size:13px">Failed to load servers: ' + e + '</div>';
  }
}

function renderServer(s) {
  const statusCls = s.status === 'connected' ? 'connected' : s.status === 'error' ? 'error' : 'unknown';
  const statusLabel = s.status === 'connected' ? '&#x25CF; Connected' : s.status === 'error' ? '&#x25CF; Error' : '&#x25CB; Unknown';
  const typeBadge = '<span class="badge ' + s.type + '">' + (s.type === 'http' ? 'HTTP' : 'stdio') + '</span>';
  const lastDisc = s.last_discovered ? 'Last discovered: ' + s.last_discovered.replace('T',' ').replace('Z','') + ' UTC' : 'Not yet discovered';
  const toolCount = s.tool_count || 0;
  const toolsId = 'tools-' + s.id;
  const toolRows = (s.tools || []).map(t =>
    '<div class="tool-item"><span class="tool-name">' + esc(t.name) + '</span><span class="tool-desc">' + esc(t.description || '—') + '</span></div>'
  ).join('');
  const errorBox = (s.error && s.status === 'error') ? '<div class="error-box">&#x26A0; ' + esc(s.error) + '</div>' : '';
  return `<div class="card" id="srv-${s.id}">
  <div class="card-header">
    <div style="flex:1">
      <div class="server-name">${esc(s.name)} ${typeBadge}</div>
      <div class="server-meta">${esc(s.connection)} &mdash; <span class="badge ${statusCls}">${statusLabel}</span> &mdash; ${toolCount} tool${toolCount !== 1 ? 's' : ''} &mdash; ${esc(lastDisc)}</div>
      ${s.description ? '<div class="server-meta" style="margin-top:2px">' + esc(s.description) + '</div>' : ''}
    </div>
    <label class="toggle" title="${s.enabled ? 'Enabled' : 'Disabled'}">
      <input type="checkbox" ${s.enabled ? 'checked' : ''} onchange="toggleServer('${s.id}', this.checked)">
      <span class="slider"></span>
    </label>
  </div>
  ${errorBox}
  <div style="display:flex;gap:8px;margin-top:12px;align-items:center">
    <button class="btn btn-sm btn-ghost" onclick="discoverTools('${s.id}', this)">&#x1F50D; Re-discover Tools</button>
    ${toolCount > 0 ? '<button class="tools-toggle" onclick="toggleTools(\'' + toolsId + '\', this)">\u25bc ' + toolCount + ' tools</button>' : ''}
    <button class="btn btn-sm btn-danger" onclick="removeServer('${s.id}')">Remove</button>
  </div>
  <div class="tool-list" id="${toolsId}">
    ${toolRows || '<div style="color:var(--muted);font-size:12px">No tools discovered yet. Click Re-discover.</div>'}
  </div>
</div>`;
}

function toggleTools(id, btn) {
  const el = document.getElementById(id);
  el.classList.toggle('open');
  btn.textContent = el.classList.contains('open') ? '\u25b2 hide tools' : '\u25bc ' + btn.textContent.replace(/[▼▲]\s*/,'');
}

async function discoverTools(serverId, btn) {
  const orig = btn.textContent;
  btn.disabled = true;
  btn.innerHTML = '<span class="disc-spinner"></span> Discovering…';
  try {
    const r = await fetch(API + '/api/mcp/servers/' + serverId + '/discover', { method: 'POST' });
    const d = await r.json();
    await loadServers();
  } catch(e) { alert('Discovery failed: ' + e); }
  btn.disabled = false;
  btn.textContent = orig;
}

async function removeServer(serverId) {
  if (!confirm('Remove this MCP server?')) return;
  try {
    await fetch(API + '/api/mcp/servers/' + serverId + '/remove', { method: 'POST' });
    await loadServers();
  } catch(e) { alert('Remove failed: ' + e); }
}

async function toggleServer(serverId, enabled) {
  try {
    await fetch(API + '/api/mcp/servers/' + serverId + '/toggle', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ enabled })
    });
  } catch(e) { console.warn('Toggle failed', e); }
}

async function loadScaffold() {
  try {
    const r = await fetch(API + '/api/mcp/scaffold');
    const d = await r.json();
    document.getElementById('scaffoldCode').textContent = d.code || '';
  } catch(e) {
    document.getElementById('scaffoldCode').textContent = '# Could not load scaffold: ' + e;
  }
}

function copyScaffold() {
  const code = document.getElementById('scaffoldCode').textContent;
  navigator.clipboard.writeText(code).then(() => {
    const btn = document.querySelector('.copy-btn');
    btn.textContent = 'Copied!';
    setTimeout(() => btn.textContent = 'Copy', 1800);
  });
}

function openZapierSetup() {
  const panel = document.getElementById('zapierSetupPanel');
  panel.style.display = panel.style.display === 'none' ? 'block' : 'none';
  if (panel.style.display !== 'none') document.getElementById('zapierUrl').focus();
}

async function connectZapier() {
  const url = document.getElementById('zapierUrl').value.trim();
  const msg = document.getElementById('zapierMsg');
  if (!url) { showMsg(msg, 'Paste your Zapier MCP URL first', 'err'); return; }
  showMsg(msg, '<span class="disc-spinner"></span> Connecting…', 'ok');
  try {
    const payload = { name: 'Zapier', type: 'http', connection: url, description: 'Zapier automation tools via MCP' };
    const r = await fetch(API + '/api/mcp/servers', {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(payload)
    });
    const d = await r.json();
    if (d.ok || d.server_id) {
      showMsg(msg, '&#x26A1; Connected &mdash; ' + (d.tool_count || 0) + ' tool(s) discovered', 'ok');
      document.getElementById('zapierUrl').value = '';
      document.getElementById('zapierSetupPanel').style.display = 'none';
      await loadServers();
    } else {
      showMsg(msg, 'Error: ' + (d.error || JSON.stringify(d)), 'err');
    }
  } catch(e) { showMsg(msg, 'Request failed: ' + e, 'err'); }
}

function esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

loadServers();
loadScaffold();
</script>
</body>
</html>"""


_CAPABILITIES_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kendr &mdash; Capability Studio</title>
<style>
:root { --teal: #00C9A7; --amber: #FFB347; --crimson: #FF4757; --purple: #A78BFA; --bg: #0d0f14; --surface: #161b22; --surface2: #1e2530; --border: #2a3140; --text: #e6edf3; --muted: #7d8590; --sidebar-w: 280px; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "Segoe UI", system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; }
.sidebar { width: var(--sidebar-w); min-width: var(--sidebar-w); background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; position: fixed; top: 0; bottom: 0; left: 0; }
.sidebar-header { padding: 20px 16px 12px; border-bottom: 1px solid var(--border); }
.logo { font-size: 22px; font-weight: 800; color: var(--teal); }
.logo span { color: var(--amber); }
.tagline { font-size: 11px; color: var(--muted); margin-top: 4px; }
.sidebar-nav { padding: 12px 8px; border-bottom: 1px solid var(--border); display: flex; flex-direction: column; gap: 4px; }
.nav-btn { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-radius: 8px; font-size: 13px; font-weight: 500; color: var(--muted); cursor: pointer; border: none; background: transparent; width: 100%; text-align: left; text-decoration: none; transition: background 0.15s, color 0.15s; }
.nav-btn:hover { background: var(--surface2); color: var(--text); }
.nav-btn.active { background: rgba(167,139,250,0.12); color: var(--purple); }
.nav-btn .icon { font-size: 16px; width: 20px; text-align: center; }
.main { flex: 1; margin-left: var(--sidebar-w); padding: 28px 30px; }
.page-title { font-size: 25px; font-weight: 700; margin-bottom: 6px; }
.page-subtitle { font-size: 13px; color: var(--muted); margin-bottom: 18px; }
.panel { background: var(--surface); border: 1px solid var(--border); border-radius: 10px; padding: 16px; margin-bottom: 14px; }
.panel-title { font-size: 12px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 10px; }
.row { display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 10px; }
.col2 { grid-column: span 2; }
.col3 { grid-column: span 3; }
.col6 { grid-column: span 6; }
label { display: block; font-size: 11px; font-weight: 700; color: var(--muted); margin-bottom: 5px; letter-spacing: 0.04em; text-transform: uppercase; }
input, select, textarea { width: 100%; background: var(--surface2); border: 1px solid var(--border); border-radius: 7px; padding: 8px 10px; color: var(--text); font-size: 13px; outline: none; }
input:focus, select:focus, textarea:focus { border-color: var(--teal); }
textarea { min-height: 110px; resize: vertical; font-family: "Cascadia Code", "Fira Code", monospace; font-size: 12px; }
.btn { border: 1px solid var(--border); border-radius: 7px; padding: 7px 11px; font-size: 12px; font-weight: 600; color: var(--text); background: var(--surface2); cursor: pointer; }
.btn:hover { opacity: 0.86; }
.btn-primary { background: var(--teal); color: #091017; border-color: rgba(0,0,0,0); }
.btn-danger { background: rgba(255,71,87,0.1); border-color: rgba(255,71,87,0.4); color: var(--crimson); }
.btn-amber { background: rgba(255,179,71,0.1); border-color: rgba(255,179,71,0.35); color: var(--amber); }
.toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 8px; }
.summary { font-size: 12px; color: var(--muted); }
.summary strong { color: var(--teal); }
table { width: 100%; border-collapse: collapse; font-size: 12px; }
th { text-align: left; color: var(--muted); text-transform: uppercase; font-size: 11px; letter-spacing: 0.04em; border-bottom: 1px solid var(--border); padding: 9px 8px; }
td { border-bottom: 1px solid var(--border); padding: 9px 8px; vertical-align: top; }
tr:hover td { background: rgba(0,201,167,0.03); }
.mono { font-family: "Cascadia Code", "Fira Code", monospace; font-size: 11px; color: #b7c6df; }
.badge { display: inline-block; padding: 2px 8px; border-radius: 999px; font-size: 10px; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; }
.status-draft { color: var(--amber); background: rgba(255,179,71,0.12); }
.status-verified { color: var(--teal); background: rgba(0,201,167,0.12); }
.status-active { color: var(--teal); background: rgba(0,201,167,0.2); }
.status-disabled, .status-deprecated { color: var(--crimson); background: rgba(255,71,87,0.15); }
.actions { display: flex; gap: 6px; flex-wrap: wrap; }
.msg { margin-top: 8px; font-size: 12px; padding: 7px 9px; border-radius: 7px; }
.msg.ok { background: rgba(0,201,167,0.1); color: var(--teal); }
.msg.err { background: rgba(255,71,87,0.12); color: var(--crimson); }
.detail { font-size: 12px; color: #ced8e6; line-height: 1.5; white-space: pre-wrap; background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 12px; max-height: 260px; overflow: auto; }
.subgrid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 10px; }
.subcard { background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 10px; }
.subcard h4 { font-size: 13px; margin-bottom: 6px; }
.server-card { background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 10px; margin-top: 8px; }
.server-title { font-size: 13px; font-weight: 700; }
.server-meta { font-size: 11px; color: var(--muted); margin-top: 3px; }
.server-actions { display: flex; gap: 6px; flex-wrap: wrap; margin-top: 8px; }
@media (max-width: 1200px) { .row { grid-template-columns: repeat(2, minmax(0, 1fr)); } .col2,.col3,.col6{grid-column:span 2;} }
</style>
</head>
<body>
<div class="sidebar">
  <div class="sidebar-header"><div class="logo">kendr<span>.</span></div><div class="tagline">Multi-agent intelligence runtime</div></div>
  <div class="sidebar-nav">
    <a href="/" class="nav-btn"><span class="icon">&#x1F4AC;</span> Chat</a>
    <a href="/setup" class="nav-btn"><span class="icon">&#x2699;&#xFE0F;</span> Setup &amp; Config</a>
    <a href="/runs" class="nav-btn"><span class="icon">&#x1F4CB;</span> Run History</a>
    <a href="/skills" class="nav-btn"><span class="icon">&#x1F9E0;</span> Skill Cards</a>
    <a href="/rag" class="nav-btn"><span class="icon">&#x1F52C;</span> Super-RAG</a>
    <a href="/models" class="nav-btn"><span class="icon">&#x1F916;</span> LLM Models</a>
    <a href="/capabilities" class="nav-btn active"><span class="icon">&#x2692;&#xFE0F;</span> Capabilities</a>
    <a href="/projects" class="nav-btn"><span class="icon">&#x1F4C1;</span> Projects</a>
    <a href="/docs" class="nav-btn"><span class="icon">&#x1F4D6;</span> Docs</a>
  </div>
</div>
<div class="main">
  <div class="page-title">Capability Studio</div>
  <div class="page-subtitle">Single place to add MCP servers, import OpenAPI specs, and manage capability records.</div>

  <div class="panel">
    <div class="panel-title">Add MCP Server</div>
    <div class="row">
      <div class="col2"><label>Server Name</label><input id="mcpName" placeholder="my-mcp-server"></div>
      <div><label>Type</label><select id="mcpType"><option value="http">HTTP/SSE</option><option value="stdio">Stdio</option></select></div>
      <div class="col3"><label>Connection</label><input id="mcpConnection" placeholder="http://localhost:8000/mcp or python my_server.py"></div>
      <div class="col2"><label>Auth Token (optional)</label><input id="mcpToken" type="password" placeholder="Bearer token"></div>
      <div class="col3"><label>Description (optional)</label><input id="mcpDescription" placeholder="What this server provides"></div>
    </div>
    <div style="margin-top:10px;display:flex;gap:8px;align-items:center">
      <button class="btn btn-primary" onclick="addMcpServer()">Connect &amp; Discover</button>
      <button class="btn" onclick="loadMcpServers()">Refresh MCP List</button>
    </div>
    <div id="mcpMsg"></div>
    <div id="mcpList" style="margin-top:8px;color:var(--muted)">Loading MCP servers...</div>
  </div>

  <div class="panel">
    <div class="panel-title">Search</div>
    <div class="row">
      <div><label>Type</label><select id="fltType"><option value="">Any</option><option value="skill">skill</option><option value="mcp_server">mcp_server</option><option value="mcp_tool">mcp_tool</option><option value="api_service">api_service</option><option value="api_operation">api_operation</option><option value="agent">agent</option><option value="integration">integration</option><option value="workflow">workflow</option></select></div>
      <div><label>Status</label><select id="fltStatus"><option value="">Any</option><option value="draft">draft</option><option value="verified">verified</option><option value="active">active</option><option value="disabled">disabled</option><option value="deprecated">deprecated</option></select></div>
      <div><label>Visibility</label><select id="fltVisibility"><option value="">Any</option><option value="private">private</option><option value="workspace">workspace</option><option value="public">public</option></select></div>
      <div class="col3"><label>Search</label><input id="fltQ" placeholder="name, key, description"></div>
      <div><label>Limit</label><input id="fltLimit" value="200"></div>
    </div>
    <div style="margin-top:10px;display:flex;gap:8px;align-items:center">
      <button class="btn btn-primary" onclick="loadCapabilities()">Refresh</button>
      <button class="btn" onclick="loadDiscoveryCards()">Discovery Cards</button>
      <div id="discoverySummary" class="summary"></div>
    </div>
  </div>

  <div class="panel">
    <div class="toolbar">
      <div class="panel-title" style="margin:0">Capabilities</div>
      <div id="listSummary" class="summary"></div>
    </div>
    <table>
      <thead><tr><th>Name</th><th>Type</th><th>Status</th><th>Visibility</th><th>Key</th><th>Updated</th><th>Actions</th></tr></thead>
      <tbody id="capRows"><tr><td colspan="7" style="color:var(--muted)">Loading...</td></tr></tbody>
    </table>
    <div id="capMsg"></div>
  </div>

  <div class="panel">
    <div class="panel-title">Capability Detail</div>
    <div id="capDetail" class="detail">Select a capability row to inspect full metadata.</div>
  </div>

  <div class="row">
    <div class="col3 panel">
      <div class="panel-title">Create Capability</div>
      <div class="row">
        <div class="col2"><label>Type</label><input id="newType" placeholder="api_operation"></div>
        <div class="col2"><label>Key</label><input id="newKey" placeholder="billing.invoice.get"></div>
        <div class="col2"><label>Name</label><input id="newName" placeholder="Get Invoice"></div>
        <div class="col2"><label>Owner User ID</label><input id="newOwner" value="ui:capabilities"></div>
        <div><label>Status</label><select id="newStatus"><option value="draft">draft</option><option value="verified">verified</option><option value="active">active</option><option value="disabled">disabled</option></select></div>
        <div><label>Visibility</label><select id="newVisibility"><option value="workspace">workspace</option><option value="private">private</option><option value="public">public</option></select></div>
        <div class="col6"><label>Description</label><input id="newDescription" placeholder="Capability description"></div>
      </div>
      <div style="margin-top:10px"><button class="btn btn-primary" onclick="createCapability()">Create</button></div>
      <div id="createMsg"></div>
    </div>

    <div class="col3 panel">
      <div class="panel-title">Create Auth Profile</div>
      <div class="row">
        <div class="col2"><label>Auth Type</label><input id="authType" placeholder="oauth2_bearer"></div>
        <div class="col2"><label>Provider</label><input id="authProvider" placeholder="openai"></div>
        <div class="col2"><label>Secret Ref</label><input id="authSecretRef" placeholder="vault://prod/openai/token"></div>
      </div>
      <div style="margin-top:10px"><button class="btn btn-primary" onclick="createAuthProfile()">Create</button></div>
      <div id="authMsg"></div>

      <div class="panel-title" style="margin-top:16px">Create Policy Profile</div>
      <div class="row">
        <div class="col2"><label>Policy Name</label><input id="policyName" placeholder="readonly-policy"></div>
        <div class="col6"><label>Rules JSON</label><textarea id="policyRules" placeholder='{"deny_write": true, "allow_tools": ["mcp.tool.docs.search"]}'></textarea></div>
      </div>
      <div style="margin-top:10px"><button class="btn btn-primary" onclick="createPolicyProfile()">Create</button></div>
      <div id="policyMsg"></div>

      <div class="panel-title" style="margin-top:16px">Import OpenAPI</div>
      <div class="row">
        <div class="col2"><label>Owner User ID</label><input id="openapiOwner" value="ui:openapi-import"></div>
        <div><label>Status</label><select id="openapiStatus"><option value="draft">draft</option><option value="verified">verified</option><option value="active">active</option></select></div>
        <div><label>Visibility</label><select id="openapiVisibility"><option value="workspace">workspace</option><option value="private">private</option><option value="public">public</option></select></div>
        <div class="col2"><label>Auth Profile ID (optional)</label><input id="openapiAuthProfile" placeholder="AP_..."></div>
        <div class="col6"><label>OpenAPI JSON/YAML</label><textarea id="openapiText" placeholder="openapi: 3.0.3..."></textarea></div>
      </div>
      <div style="margin-top:10px"><button class="btn btn-amber" onclick="importOpenApi()">Import OpenAPI</button></div>
      <div id="openapiMsg"></div>
    </div>
  </div>
</div>

<script>
const API = '';
const WORKSPACE_ID = 'default';
const ACTOR_USER_ID = 'ui:capability-registry';
let _caps = [];
let _mcpServers = [];

function esc(s) { return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }
function msg(elId, text, kind) { const el = document.getElementById(elId); el.className = 'msg ' + (kind || 'ok'); el.textContent = text; }
function clearMsg(elId) { const el = document.getElementById(elId); el.className = ''; el.textContent = ''; }
function encodeQuery(params) {
  const items = Object.entries(params).filter(([k,v]) => String(v || '').trim() !== '');
  return items.length ? ('?' + items.map(([k,v]) => encodeURIComponent(k) + '=' + encodeURIComponent(String(v))).join('&')) : '';
}
function statusClass(status) { return 'status-' + String(status || '').toLowerCase(); }

function setInlineMsg(elId, text, kind) {
  const el = document.getElementById(elId);
  el.className = 'msg ' + (kind || 'ok');
  el.textContent = text;
}

async function loadMcpServers() {
  try {
    const r = await fetch(API + '/api/mcp/servers');
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || ('Request failed: ' + r.status));
    _mcpServers = Array.isArray(d) ? d : [];
    renderMcpServers();
  } catch (e) {
    document.getElementById('mcpList').innerHTML = '<div style="color:var(--crimson)">Failed to load MCP servers: ' + esc(e.message || e) + '</div>';
  }
}

function renderMcpServers() {
  const box = document.getElementById('mcpList');
  if (!_mcpServers.length) {
    box.innerHTML = '<div style="color:var(--muted)">No MCP servers configured yet.</div>';
    return;
  }
  box.innerHTML = _mcpServers.map((s) => {
    const sid = String(s.id || '');
    const status = String(s.status || 'unknown');
    const tools = Number(s.tool_count || 0);
    return '<div class="server-card">' +
      '<div class="server-title">' + esc(s.name || sid) + '</div>' +
      '<div class="server-meta">' + esc(s.connection || '') + ' | ' + esc(status) + ' | ' + tools + ' tool(s)</div>' +
      '<div class="server-actions">' +
      '<button class="btn" onclick="discoverMcpServer(\\'' + esc(sid) + '\\')">Discover</button>' +
      '<button class="btn" onclick="toggleMcpServer(\\'' + esc(sid) + '\\',' + (s.enabled ? 'false' : 'true') + ')">' + (s.enabled ? 'Disable' : 'Enable') + '</button>' +
      '<button class="btn btn-danger" onclick="removeMcpServer(\\'' + esc(sid) + '\\')">Remove</button>' +
      '</div></div>';
  }).join('');
}

async function addMcpServer() {
  const name = document.getElementById('mcpName').value.trim();
  const type = document.getElementById('mcpType').value;
  const connection = document.getElementById('mcpConnection').value.trim();
  const description = document.getElementById('mcpDescription').value.trim();
  const authToken = document.getElementById('mcpToken').value.trim();
  if (!name || !connection) {
    setInlineMsg('mcpMsg', 'Server name and connection are required.', 'err');
    return;
  }
  const payload = { name, type, connection, description };
  if (authToken) payload.auth_token = authToken;
  try {
    const r = await fetch(API + '/api/mcp/servers', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || ('Request failed: ' + r.status));
    setInlineMsg('mcpMsg', 'MCP server connected and discovered.', 'ok');
    document.getElementById('mcpName').value = '';
    document.getElementById('mcpConnection').value = '';
    document.getElementById('mcpDescription').value = '';
    document.getElementById('mcpToken').value = '';
    await loadMcpServers();
    await loadCapabilities();
  } catch (e) {
    setInlineMsg('mcpMsg', 'MCP connect failed: ' + String(e.message || e), 'err');
  }
}

async function discoverMcpServer(serverId) {
  try {
    const r = await fetch(API + '/api/mcp/servers/' + encodeURIComponent(serverId) + '/discover', { method: 'POST' });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || ('Request failed: ' + r.status));
    setInlineMsg('mcpMsg', 'Re-discovery completed for ' + serverId + '.', 'ok');
    await loadMcpServers();
    await loadCapabilities();
  } catch (e) {
    setInlineMsg('mcpMsg', 'Discovery failed: ' + String(e.message || e), 'err');
  }
}

async function toggleMcpServer(serverId, enabled) {
  try {
    const r = await fetch(API + '/api/mcp/servers/' + encodeURIComponent(serverId) + '/toggle', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ enabled: Boolean(enabled) }),
    });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || ('Request failed: ' + r.status));
    setInlineMsg('mcpMsg', 'Updated MCP server state for ' + serverId + '.', 'ok');
    await loadMcpServers();
    await loadCapabilities();
  } catch (e) {
    setInlineMsg('mcpMsg', 'Toggle failed: ' + String(e.message || e), 'err');
  }
}

async function removeMcpServer(serverId) {
  try {
    const r = await fetch(API + '/api/mcp/servers/' + encodeURIComponent(serverId) + '/remove', { method: 'POST' });
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || ('Request failed: ' + r.status));
    setInlineMsg('mcpMsg', 'Removed MCP server ' + serverId + '.', 'ok');
    await loadMcpServers();
    await loadCapabilities();
  } catch (e) {
    setInlineMsg('mcpMsg', 'Remove failed: ' + String(e.message || e), 'err');
  }
}

async function loadCapabilities() {
  clearMsg('capMsg');
  const q = encodeQuery({
    type: document.getElementById('fltType').value,
    status: document.getElementById('fltStatus').value,
    visibility: document.getElementById('fltVisibility').value,
    q: document.getElementById('fltQ').value,
    limit: document.getElementById('fltLimit').value || '200',
  });
  try {
    const r = await fetch(API + '/api/capabilities' + q);
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || ('Request failed: ' + r.status));
    _caps = d.items || [];
    document.getElementById('listSummary').innerHTML = '<strong>' + (_caps.length || 0) + '</strong> capability record(s)';
    renderCapabilities();
  } catch (e) {
    document.getElementById('capRows').innerHTML = '<tr><td colspan="7" style="color:var(--crimson)">Failed to load capabilities: ' + esc(e.message || e) + '</td></tr>';
  }
}

function renderCapabilities() {
  const body = document.getElementById('capRows');
  if (!_caps.length) {
    body.innerHTML = '<tr><td colspan="7" style="color:var(--muted)">No capabilities match the current filters.</td></tr>';
    return;
  }
  body.innerHTML = _caps.map((c) => {
    const capId = String(c.id || '');
    return '<tr>' +
      '<td><div><strong>' + esc(c.name || capId) + '</strong></div><div class="mono">' + esc(capId) + '</div></td>' +
      '<td>' + esc(c.type || '') + '</td>' +
      '<td><span class="badge ' + statusClass(c.status) + '">' + esc(c.status || '') + '</span></td>' +
      '<td>' + esc(c.visibility || '') + '</td>' +
      '<td class="mono">' + esc(c.key || '') + '</td>' +
      '<td class="mono">' + esc(c.updated_at || c.created_at || '') + '</td>' +
      '<td><div class="actions">' +
      '<button class="btn" onclick="viewCapability(\'' + esc(capId) + '\')">View</button>' +
      '<button class="btn" onclick="viewHealth(\'' + esc(capId) + '\')">Health</button>' +
      '<button class="btn" onclick="viewAudit(\'' + esc(capId) + '\')">Audit</button>' +
      '<button class="btn" onclick="runHealthCheck(\'' + esc(capId) + '\',\'healthy\')">Mark Healthy</button>' +
      '<button class="btn btn-amber" onclick="capAction(\'' + esc(capId) + '\',\'verify\')">Verify</button>' +
      '<button class="btn btn-primary" onclick="capAction(\'' + esc(capId) + '\',\'publish\')">Publish</button>' +
      '<button class="btn btn-danger" onclick="capAction(\'' + esc(capId) + '\',\'disable\')">Disable</button>' +
      '</div></td>' +
      '</tr>';
  }).join('');
}

async function viewCapability(capabilityId) {
  try {
    const r = await fetch(API + '/api/capabilities/' + encodeURIComponent(capabilityId));
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || ('Request failed: ' + r.status));
    document.getElementById('capDetail').textContent = JSON.stringify(d, null, 2);
  } catch (e) {
    document.getElementById('capDetail').textContent = 'Detail load failed: ' + String(e.message || e);
  }
}

async function capAction(capabilityId, action) {
  try {
    const r = await fetch(API + '/api/capabilities/' + encodeURIComponent(capabilityId) + '/' + action, {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ workspace_id: WORKSPACE_ID, actor_user_id: ACTOR_USER_ID })
    });
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.error || ('Request failed: ' + r.status));
    msg('capMsg', 'Capability ' + capabilityId + ' ' + action + ' succeeded.', 'ok');
    if (d.capability) document.getElementById('capDetail').textContent = JSON.stringify(d.capability, null, 2);
    await loadCapabilities();
  } catch (e) {
    msg('capMsg', 'Action failed: ' + String(e.message || e), 'err');
  }
}

async function viewHealth(capabilityId) {
  try {
    const r = await fetch(API + '/api/capabilities/' + encodeURIComponent(capabilityId) + '/health?limit=20');
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || ('Request failed: ' + r.status));
    document.getElementById('capDetail').textContent = JSON.stringify({ capability_id: capabilityId, health_runs: d.items || [] }, null, 2);
  } catch (e) {
    document.getElementById('capDetail').textContent = 'Health load failed: ' + String(e.message || e);
  }
}

async function viewAudit(capabilityId) {
  try {
    const r = await fetch(API + '/api/capabilities/' + encodeURIComponent(capabilityId) + '/audit?limit=40');
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || ('Request failed: ' + r.status));
    document.getElementById('capDetail').textContent = JSON.stringify({ capability_id: capabilityId, audit_events: d.items || [] }, null, 2);
  } catch (e) {
    document.getElementById('capDetail').textContent = 'Audit load failed: ' + String(e.message || e);
  }
}

async function runHealthCheck(capabilityId, status) {
  try {
    const r = await fetch(API + '/api/capabilities/' + encodeURIComponent(capabilityId) + '/health-check', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        workspace_id: WORKSPACE_ID,
        actor_user_id: ACTOR_USER_ID,
        status: status || 'healthy'
      })
    });
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.error || ('Request failed: ' + r.status));
    msg('capMsg', 'Health check recorded for ' + capabilityId + ': ' + (d.capability && d.capability.health_status ? d.capability.health_status : 'ok'), 'ok');
    await viewHealth(capabilityId);
    await loadCapabilities();
  } catch (e) {
    msg('capMsg', 'Health check failed: ' + String(e.message || e), 'err');
  }
}

async function createCapability() {
  clearMsg('createMsg');
  const payload = {
    workspace_id: WORKSPACE_ID,
    actor_user_id: ACTOR_USER_ID,
    owner_user_id: document.getElementById('newOwner').value.trim() || ACTOR_USER_ID,
    type: document.getElementById('newType').value.trim(),
    key: document.getElementById('newKey').value.trim(),
    name: document.getElementById('newName').value.trim(),
    description: document.getElementById('newDescription').value.trim(),
    status: document.getElementById('newStatus').value,
    visibility: document.getElementById('newVisibility').value,
  };
  if (!payload.type || !payload.key || !payload.name) {
    msg('createMsg', 'Type, key, and name are required.', 'err');
    return;
  }
  try {
    const r = await fetch(API + '/api/capabilities', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.error || ('Request failed: ' + r.status));
    msg('createMsg', 'Created capability: ' + (d.capability && d.capability.id ? d.capability.id : payload.key), 'ok');
    await loadCapabilities();
  } catch (e) {
    msg('createMsg', 'Create failed: ' + String(e.message || e), 'err');
  }
}

async function createAuthProfile() {
  clearMsg('authMsg');
  const payload = {
    workspace_id: WORKSPACE_ID,
    auth_type: document.getElementById('authType').value.trim(),
    provider: document.getElementById('authProvider').value.trim(),
    secret_ref: document.getElementById('authSecretRef').value.trim(),
  };
  if (!payload.auth_type || !payload.provider || !payload.secret_ref) {
    msg('authMsg', 'Auth type, provider, and secret ref are required.', 'err');
    return;
  }
  try {
    const r = await fetch(API + '/api/capabilities/auth-profiles', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.error || ('Request failed: ' + r.status));
    msg('authMsg', 'Auth profile created: ' + ((d.auth_profile || {}).id || 'ok'), 'ok');
  } catch (e) {
    msg('authMsg', 'Auth profile failed: ' + String(e.message || e), 'err');
  }
}

async function createPolicyProfile() {
  clearMsg('policyMsg');
  const name = document.getElementById('policyName').value.trim();
  const rawRules = document.getElementById('policyRules').value.trim();
  if (!name) {
    msg('policyMsg', 'Policy name is required.', 'err');
    return;
  }
  let rules = {};
  if (rawRules) {
    try {
      rules = JSON.parse(rawRules);
    } catch (e) {
      msg('policyMsg', 'Rules must be valid JSON.', 'err');
      return;
    }
  }
  try {
    const r = await fetch(API + '/api/capabilities/policy-profiles', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({
        workspace_id: WORKSPACE_ID,
        name,
        rules,
      })
    });
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.error || ('Request failed: ' + r.status));
    msg('policyMsg', 'Policy profile created: ' + ((d.policy_profile || {}).id || 'ok'), 'ok');
  } catch (e) {
    msg('policyMsg', 'Policy profile failed: ' + String(e.message || e), 'err');
  }
}

async function importOpenApi() {
  clearMsg('openapiMsg');
  const openapiText = document.getElementById('openapiText').value.trim();
  if (!openapiText) {
    msg('openapiMsg', 'OpenAPI JSON/YAML text is required.', 'err');
    return;
  }
  const payload = {
    workspace_id: WORKSPACE_ID,
    owner_user_id: document.getElementById('openapiOwner').value.trim() || ACTOR_USER_ID,
    status: document.getElementById('openapiStatus').value,
    visibility: document.getElementById('openapiVisibility').value,
    auth_profile_id: document.getElementById('openapiAuthProfile').value.trim(),
    openapi_text: openapiText,
  };
  try {
    const r = await fetch(API + '/api/capabilities/import-openapi', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify(payload)
    });
    const d = await r.json();
    if (!r.ok || !d.ok) throw new Error(d.error || ('Request failed: ' + r.status));
    const serviceCap = (((d.import_result || {}).service_capability || {}).id || '');
    msg('openapiMsg', 'OpenAPI imported successfully. Service capability: ' + (serviceCap || 'created'), 'ok');
    await loadCapabilities();
  } catch (e) {
    msg('openapiMsg', 'OpenAPI import failed: ' + String(e.message || e), 'err');
  }
}

async function loadDiscoveryCards() {
  try {
    const r = await fetch(API + '/api/capabilities/discovery/cards');
    const d = await r.json();
    if (!r.ok) throw new Error(d.error || ('Request failed: ' + r.status));
    const count = Number(d.count || 0);
    document.getElementById('discoverySummary').innerHTML = '<strong>' + count + '</strong> discovery card(s) published to chat';
  } catch (e) {
    document.getElementById('discoverySummary').textContent = 'Discovery load failed: ' + String(e.message || e);
  }
}

loadCapabilities();
loadMcpServers();
loadDiscoveryCards();
</script>
</body>
</html>"""


_SKILLS_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kendr &mdash; Skill Cards</title>
<style>
:root{--teal:#00C9A7;--amber:#FFB347;--crimson:#FF4757;--bg:#0d0f14;--surface:#161b22;--surface2:#1e2530;--border:#2a3140;--text:#e6edf3;--muted:#7d8590;--sidebar-w:280px}
*{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--text);font-family:'Segoe UI',system-ui,sans-serif;min-height:100vh}
.sidebar{position:fixed;top:0;left:0;width:var(--sidebar-w);height:100vh;background:var(--surface);border-right:1px solid var(--border);display:flex;flex-direction:column;padding:20px 0;z-index:100}
.logo{padding:0 20px 20px;border-bottom:1px solid var(--border);margin-bottom:16px}
.logo h1{font-size:22px;font-weight:800;color:var(--teal)}
.logo small{font-size:11px;color:var(--muted)}
.nav-btn{display:flex;align-items:center;gap:10px;padding:10px 20px;color:var(--text);text-decoration:none;font-size:14px;border-radius:6px;margin:2px 8px;transition:background .15s}
.nav-btn:hover{background:var(--surface2)}
.nav-btn.active{background:rgba(0,201,167,.15);color:var(--teal);font-weight:600}
.nav-btn .icon{font-size:16px;width:20px;text-align:center}
.main{margin-left:var(--sidebar-w);padding:32px}
.page-header{display:flex;align-items:center;justify-content:space-between;margin-bottom:24px;flex-wrap:wrap;gap:12px}
.page-title{font-size:24px;font-weight:700}
.summary-bar{display:flex;gap:16px;flex-wrap:wrap;margin-bottom:28px}
.stat{background:var(--surface);border:1px solid var(--border);border-radius:10px;padding:14px 22px;display:flex;flex-direction:column;gap:4px}
.stat .num{font-size:28px;font-weight:700;color:var(--teal)}
.stat .lbl{font-size:12px;color:var(--muted);text-transform:uppercase;letter-spacing:.05em}
.stat.inactive .num{color:var(--amber)}
.filter-bar{display:flex;gap:10px;flex-wrap:wrap;margin-bottom:20px}
.filter-btn{background:var(--surface);border:1px solid var(--border);color:var(--muted);padding:6px 14px;border-radius:20px;cursor:pointer;font-size:13px;transition:all .15s}
.filter-btn:hover,.filter-btn.active{background:var(--teal);border-color:var(--teal);color:#000;font-weight:600}
.cards-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(300px,1fr));gap:16px}
.skill-card{background:var(--surface);border:1px solid var(--border);border-radius:12px;padding:16px 18px;display:flex;flex-direction:column;gap:8px;transition:box-shadow .2s,border-color .2s}
.skill-card:hover{box-shadow:0 4px 20px rgba(0,201,167,.10);border-color:rgba(0,201,167,.25)}
.skill-card.needs-config{border-color:rgba(255,179,71,.3)}
.skill-card.needs-config:hover{border-color:rgba(255,179,71,.6);box-shadow:0 4px 20px rgba(255,179,71,.10)}
.skill-card.inactive{opacity:.5}
.card-header{display:flex;align-items:flex-start;gap:10px}
.card-emoji{font-size:26px;line-height:1;flex-shrink:0;margin-top:2px}
.card-info{flex:1;min-width:0}
.card-name{font-size:14px;font-weight:700;margin-bottom:1px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.card-category{font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.06em}
.card-status{display:inline-flex;align-items:center;gap:4px;padding:2px 9px;border-radius:20px;font-size:10px;font-weight:700;letter-spacing:.03em;white-space:nowrap;flex-shrink:0}
.status-ready{background:rgba(0,201,167,.15);color:var(--teal)}
.status-needs-config{background:rgba(255,179,71,.12);color:var(--amber)}
.status-inactive{background:rgba(120,120,120,.12);color:var(--muted)}
.card-desc{font-size:12px;color:var(--muted);line-height:1.5;flex:1}
.card-hint{background:rgba(255,179,71,.06);border:1px solid rgba(255,179,71,.18);border-radius:6px;padding:6px 10px;font-size:11px;color:var(--amber)}
.skills-chips{display:flex;flex-wrap:wrap;gap:4px}
.chip{background:var(--surface2);border:1px solid var(--border);color:var(--muted);padding:1px 7px;border-radius:10px;font-size:10px}
.empty-msg{text-align:center;color:var(--muted);padding:60px 20px;grid-column:1/-1}
.setup-btn{display:inline-flex;align-items:center;gap:5px;padding:5px 12px;border-radius:6px;border:1px solid rgba(255,179,71,.4);background:rgba(255,179,71,.06);color:var(--amber);font-size:11px;font-weight:600;cursor:pointer;transition:background .15s;margin-top:2px;width:fit-content}
.setup-btn:hover{background:rgba(255,179,71,.14)}
/* setup panel */
.skills-layout{display:flex;gap:20px;align-items:flex-start;min-height:0}
.skills-left{flex:1;min-width:0;display:flex;flex-direction:column;gap:0}
.setup-panel{width:340px;flex-shrink:0;background:var(--surface);border:1px solid var(--border);border-radius:12px;display:flex;flex-direction:column;height:calc(100vh - 120px);position:sticky;top:20px}
.setup-panel-header{padding:14px 16px 10px;border-bottom:1px solid var(--border);display:flex;align-items:center;justify-content:space-between}
.setup-panel-title{font-size:14px;font-weight:700}
.setup-chat{flex:1;overflow-y:auto;padding:14px 16px;display:flex;flex-direction:column;gap:10px}
.setup-msg{max-width:90%;padding:8px 12px;border-radius:8px;font-size:12px;line-height:1.5}
.setup-msg.bot{background:var(--surface2);border:1px solid var(--border);align-self:flex-start}
.setup-msg.user{background:rgba(83,82,237,.18);border:1px solid rgba(83,82,237,.3);align-self:flex-end}
.setup-input-row{padding:10px 12px;border-top:1px solid var(--border);display:flex;gap:8px}
.setup-input{flex:1;background:var(--surface2);border:1px solid var(--border);border-radius:8px;padding:8px 12px;font-size:12px;color:var(--text);outline:none}
.setup-input:focus{border-color:var(--teal)}
.setup-send{background:var(--teal);color:#0d1117;border:none;border-radius:8px;padding:8px 14px;font-size:12px;font-weight:700;cursor:pointer}
.setup-send:hover{opacity:.85}
/* field rows in setup */
.setup-field{background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;display:flex;flex-direction:column;gap:4px}
.setup-field label{font-size:10px;font-weight:700;color:var(--teal);text-transform:uppercase;letter-spacing:.05em}
.setup-field input{background:transparent;border:none;color:var(--text);font-size:12px;outline:none;width:100%}
.setup-field.secret input{font-family:monospace}
</style>
</head>
<body>
<nav class="sidebar">
  <div class="logo"><h1>kendr</h1><small>multi-agent runtime</small></div>
  <a href="/" class="nav-btn"><span class="icon">&#x1F4AC;</span> Chat</a>
  <a href="/setup" class="nav-btn"><span class="icon">&#x2699;&#xFE0F;</span> Setup &amp; Config</a>
  <a href="/runs" class="nav-btn"><span class="icon">&#x1F4CB;</span> Run History</a>
  <a href="/skills" class="nav-btn active"><span class="icon">&#x1F9E0;</span> Skill Cards</a>
  <a href="/models" class="nav-btn"><span class="icon">&#x1F916;</span> LLM Models</a>
    <a href="/capabilities" class="nav-btn"><span class="icon">&#x2692;&#xFE0F;</span> Capabilities</a>
  <a href="/projects" class="nav-btn"><span class="icon">&#x1F4C1;</span> Projects</a>
  <a href="/docs" class="nav-btn"><span class="icon">&#x1F4D6;</span> Docs</a>
</nav>
<main class="main" style="padding:20px 24px;overflow-y:auto">
  <div class="page-header" style="margin-bottom:14px">
    <div class="page-title">&#x1F9E0; Skill Cards</div>
    <div style="display:flex;align-items:center;gap:10px">
      <div style="cursor:pointer;background:var(--surface);border:1px solid var(--border);padding:6px 14px;border-radius:8px;font-size:12px;color:var(--muted)" onclick="loadSkills()">&#x21BB; Refresh</div>
    </div>
  </div>
  <div class="summary-bar" id="summaryBar" style="margin-bottom:14px"></div>
  <div class="skills-layout">
    <div class="skills-left">
      <div class="filter-bar" id="filterBar" style="margin-bottom:14px">
        <button class="filter-btn active" data-cat="all" onclick="setFilter('all',this)">All</button>
      </div>
      <div class="cards-grid" id="cardsGrid"><div class="empty-msg">Loading skill cards&#x2026;</div></div>
    </div>
    <div class="setup-panel" id="setupPanel">
      <div class="setup-panel-header">
        <div class="setup-panel-title">&#x26A1; Setup Assistant</div>
        <div style="font-size:10px;color:var(--muted)">Type to activate skills</div>
      </div>
      <div class="setup-chat" id="setupChat"></div>
      <div class="setup-input-row">
        <input class="setup-input" id="setupInput" placeholder='e.g. "set up Slack" or "activate GitHub"' onkeydown="if(event.key==='Enter')sendSetup()">
        <button class="setup-send" onclick="sendSetup()">&#x27A4;</button>
      </div>
    </div>
  </div>
</main>

<!-- Configure modal -->
<div id="cfgModal" style="display:none;position:fixed;inset:0;background:rgba(0,0,0,.6);z-index:1000;display:none;align-items:center;justify-content:center">
  <div style="background:var(--surface);border:1px solid var(--border);border-radius:14px;width:500px;max-height:80vh;overflow-y:auto;padding:24px">
    <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:16px">
      <div style="font-size:16px;font-weight:700" id="cfgModalTitle">Configure Integration</div>
      <button onclick="closeCfgModal()" style="background:none;border:none;color:var(--muted);font-size:20px;cursor:pointer">&times;</button>
    </div>
    <div id="cfgModalBody"></div>
    <div style="display:flex;gap:10px;margin-top:20px">
      <button onclick="saveCfgModal()" style="flex:1;background:var(--teal);color:#0d1117;border:none;border-radius:8px;padding:10px;font-size:13px;font-weight:700;cursor:pointer">Save &amp; Activate</button>
      <button onclick="closeCfgModal()" style="background:var(--surface2);border:1px solid var(--border);color:var(--muted);border-radius:8px;padding:10px 18px;font-size:13px;cursor:pointer">Cancel</button>
    </div>
  </div>
</div>

<script>
let _allCards = [];
let _activeFilter = 'all';
let _setupState = { step: 'idle', integration: null, fields: [], current: 0, values: {} };

// Integration metadata for setup wizard
const INTEGRATION_META = {
  slack: {
    title: 'Slack',
    emoji: '💬',
    description: 'Connect your Slack workspace to enable the Slack agent.',
    fields: [
      { key: 'SLACK_BOT_TOKEN', label: 'Bot Token', description: 'Slack Bot User OAuth Token (starts with xoxb-)', secret: true },
      { key: 'SLACK_SIGNING_SECRET', label: 'Signing Secret', description: 'From your Slack app\'s Basic Information page.', secret: true },
      { key: 'SLACK_APP_TOKEN', label: 'App-Level Token (optional)', description: 'For socket mode (starts with xapp-).', secret: true, optional: true },
    ]
  },
  github: {
    title: 'GitHub',
    emoji: '🐙',
    description: 'Authenticate with GitHub to enable the GitHub agent.',
    fields: [
      { key: 'GITHUB_TOKEN', label: 'Personal Access Token', description: 'A GitHub PAT with repo and read:org scopes.', secret: true },
    ]
  },
  whatsapp: {
    title: 'WhatsApp',
    emoji: '📱',
    description: 'Connect WhatsApp via Meta Business API.',
    fields: [
      { key: 'WHATSAPP_ACCESS_TOKEN', label: 'Access Token', description: 'Meta Graph API access token.', secret: true },
      { key: 'WHATSAPP_PHONE_NUMBER_ID', label: 'Phone Number ID', description: 'From Meta Business Suite > WhatsApp.', secret: false },
    ]
  },
  telegram: {
    title: 'Telegram',
    emoji: '✈️',
    description: 'Connect a Telegram bot via BotFather.',
    fields: [
      { key: 'TELEGRAM_BOT_TOKEN', label: 'Bot Token', description: 'Get from @BotFather on Telegram.', secret: true },
    ]
  },
  aws: {
    title: 'AWS',
    emoji: '☁️',
    description: 'AWS credentials for cloud automation agents.',
    fields: [
      { key: 'AWS_ACCESS_KEY_ID', label: 'Access Key ID', description: 'AWS IAM access key.', secret: false },
      { key: 'AWS_SECRET_ACCESS_KEY', label: 'Secret Access Key', description: 'AWS IAM secret key.', secret: true },
      { key: 'AWS_DEFAULT_REGION', label: 'Region (optional)', description: 'Default AWS region e.g. us-east-1.', secret: false, optional: true },
    ]
  },
  qdrant: {
    title: 'Qdrant',
    emoji: '🔍',
    description: 'Connect to a Qdrant vector database for Super-RAG.',
    fields: [
      { key: 'QDRANT_URL', label: 'Qdrant URL', description: 'e.g. http://localhost:6333 or your cloud URL.', secret: false },
      { key: 'QDRANT_API_KEY', label: 'API Key (optional)', description: 'Only needed for cloud deployments.', secret: true, optional: true },
    ]
  },
  elevenlabs: {
    title: 'ElevenLabs',
    emoji: '🎙️',
    description: 'AI voice generation via ElevenLabs.',
    fields: [
      { key: 'ELEVENLABS_API_KEY', label: 'API Key', description: 'From elevenlabs.io > Profile.', secret: true },
    ]
  },
  serpapi: {
    title: 'SerpApi',
    emoji: '🔍',
    description: 'Web search via SerpApi (Google, Bing, etc.).',
    fields: [
      { key: 'SERPAPI_API_KEY', label: 'API Key', description: 'From serpapi.com > Dashboard.', secret: true },
    ]
  },
  microsoft_graph: {
    title: 'Microsoft 365',
    emoji: '🪟',
    description: 'Access Microsoft 365, Teams, OneDrive via Graph API.',
    fields: [
      { key: 'MICROSOFT_CLIENT_ID', label: 'Client ID', description: 'Azure AD app registration Client ID.', secret: false },
      { key: 'MICROSOFT_CLIENT_SECRET', label: 'Client Secret', description: 'Azure AD app secret.', secret: true },
      { key: 'MICROSOFT_TENANT_ID', label: 'Tenant ID', description: 'Your Azure AD tenant ID.', secret: false },
    ]
  },
  google_workspace: {
    title: 'Google Workspace',
    emoji: '🔵',
    description: 'Gmail, Google Drive, Google Calendar integration.',
    fields: [
      { key: 'GOOGLE_CLIENT_ID', label: 'Client ID', description: 'From Google Cloud Console OAuth credentials.', secret: false },
      { key: 'GOOGLE_CLIENT_SECRET', label: 'Client Secret', description: 'Google OAuth client secret.', secret: true },
    ]
  },
};

function escHtml(s) { const d = document.createElement('div'); d.textContent = s; return d.innerHTML; }

async function loadSkills() {
  try {
    const r = await fetch('/api/skills');
    const d = await r.json();
    _allCards = d.cards || [];
    renderSummary(d.summary || {});
    renderFilters(_allCards);
    renderCards(_allCards, _activeFilter);
    if (_setupState.step === 'idle') {
      _initSetupChat();
    }
  } catch(e) {
    document.getElementById('cardsGrid').innerHTML = '<div class="empty-msg">Gateway is offline. Start it with <code>kendr gateway start</code>.</div>';
  }
}

function renderSummary(s) {
  const bar = document.getElementById('summaryBar');
  const needsCfg = s.needs_config || 0;
  bar.innerHTML = `
    <div class="stat"><div class="num">${s.total||0}</div><div class="lbl">Total Agents</div></div>
    <div class="stat"><div class="num" style="color:var(--teal)">${s.active||0}</div><div class="lbl">Ready to Use</div></div>
    <div class="stat"><div class="num" style="color:var(--amber)">${needsCfg}</div><div class="lbl">Need Setup</div></div>
    <div class="stat inactive"><div class="num">${s.inactive - needsCfg >= 0 ? s.inactive - needsCfg : 0}</div><div class="lbl">Inactive</div></div>
  `;
}

function renderFilters(cards) {
  const cats = {};
  cards.forEach(c => {
    const key = c.category || 'general';
    cats[key] = cats[key] || { label: c.category_label || key, emoji: c.category_emoji || '✨', count: 0 };
    cats[key].count++;
  });
  const bar = document.getElementById('filterBar');
  const total = cards.length;
  bar.innerHTML = `<button class="filter-btn ${_activeFilter==='all'?'active':''}" data-cat="all" onclick="setFilter('all',this)">All (${total})</button>`
    + `<button class="filter-btn ${_activeFilter==='__ready'?'active':''}" data-cat="__ready" onclick="setFilter('__ready',this)" style="color:var(--teal)">\u2714 Ready</button>`
    + `<button class="filter-btn ${_activeFilter==='__setup'?'active':''}" data-cat="__setup" onclick="setFilter('__setup',this)" style="color:var(--amber)">\u26A0 Needs Setup</button>`;
  Object.entries(cats).sort((a,b)=>b[1].count-a[1].count).forEach(([cat,meta]) => {
    bar.innerHTML += `<button class="filter-btn ${_activeFilter===cat?'active':''}" data-cat="${cat}" onclick="setFilter('${cat}',this)">${meta.emoji} ${meta.label} (${meta.count})</button>`;
  });
}

function setFilter(cat, btn) {
  _activeFilter = cat;
  document.querySelectorAll('.filter-btn').forEach(b => b.classList.remove('active'));
  btn.classList.add('active');
  renderCards(_allCards, cat);
}

function _cardSortKey(c) {
  if (c.is_active && !c.needs_config) return 0;
  if (c.needs_config) return 1;
  return 2;
}

function renderCards(cards, filter) {
  const grid = document.getElementById('cardsGrid');
  let filtered;
  if (filter === 'all') filtered = cards;
  else if (filter === '__ready') filtered = cards.filter(c => c.is_active && !c.needs_config);
  else if (filter === '__setup') filtered = cards.filter(c => c.needs_config);
  else filtered = cards.filter(c => (c.category||'general') === filter);
  if (!filtered.length) { grid.innerHTML = '<div class="empty-msg">No agents in this category.</div>'; return; }
  filtered.sort((a,b) => _cardSortKey(a) - _cardSortKey(b));

  grid.innerHTML = filtered.map(c => {
    const ready = c.is_active && !c.needs_config;
    const needsCfg = c.needs_config;
    const statusCls = ready ? 'status-ready' : needsCfg ? 'status-needs-config' : 'status-inactive';
    const statusLabel = ready ? '\u2714 Ready' : needsCfg ? '\u26A1 Set Up to Enable' : '\u25CB Inactive';
    const cardCls = needsCfg ? 'needs-config' : ready ? '' : 'inactive';
    const chips = (c.skills||[]).slice(0,5).map(s => `<span class="chip">${escHtml(s)}</span>`).join('');
    const hint = (needsCfg && c.config_hint) ? `<div class="card-hint">\uD83D\uDCA1 ${escHtml(c.config_hint)}</div>` : '';
    const cfgBtn = needsCfg
      ? `<button class="setup-btn" onclick="openSetupFor('${escHtml(c.integration_id)}','${escHtml(c.display_name)}')">&#x2699;&#xFE0F; Configure ${escHtml(c.integration_id||'')}</button>`
      : '';
    return `<div class="skill-card ${cardCls}">
      <div class="card-header">
        <div class="card-emoji">${c.category_emoji||'\u2728'}</div>
        <div class="card-info">
          <div class="card-name" title="${escHtml(c.agent_name)}">${escHtml(c.display_name)}</div>
          <div class="card-category">${escHtml(c.category_label||c.category||'general')}</div>
        </div>
        <div class="card-status ${statusCls}">${statusLabel}</div>
      </div>
      <div class="card-desc">${escHtml(c.description||'')}</div>
      ${hint}
      ${cfgBtn}
      ${chips ? `<div class="skills-chips">${chips}</div>` : ''}
    </div>`;
  }).join('');
}

// ── Setup modal ──────────────────────────────────────────────────────────────
let _cfgIntegration = null;

function openSetupFor(integrationId, agentName) {
  const meta = INTEGRATION_META[integrationId];
  if (!meta) {
    // fallback: redirect to setup page
    window.location.href = '/setup';
    return;
  }
  _cfgIntegration = integrationId;
  document.getElementById('cfgModalTitle').textContent = meta.emoji + ' Configure ' + meta.title;
  const body = document.getElementById('cfgModalBody');
  body.innerHTML = `<div style="font-size:13px;color:var(--muted);margin-bottom:16px">${escHtml(meta.description)}</div>`
    + meta.fields.map(f => `
    <div style="margin-bottom:14px">
      <label style="display:block;font-size:11px;font-weight:700;color:var(--teal);text-transform:uppercase;letter-spacing:.05em;margin-bottom:4px">${escHtml(f.label)}${f.optional?' <span style="color:var(--muted);font-weight:400">optional</span>':''}</label>
      <div style="font-size:11px;color:var(--muted);margin-bottom:4px">${escHtml(f.description)}</div>
      <input id="cfg-field-${f.key}" type="${f.secret?'password':'text'}" placeholder="${f.key}"
        style="width:100%;background:var(--surface2);border:1px solid var(--border);border-radius:6px;padding:8px 10px;font-size:12px;color:var(--text);font-family:${f.secret?'monospace':'inherit'};box-sizing:border-box;outline:none">
    </div>`).join('');
  const modal = document.getElementById('cfgModal');
  modal.style.display = 'flex';
}

function closeCfgModal() {
  document.getElementById('cfgModal').style.display = 'none';
}

async function saveCfgModal() {
  const meta = INTEGRATION_META[_cfgIntegration];
  if (!meta) return;
  const values = {};
  for (const f of meta.fields) {
    const el = document.getElementById('cfg-field-' + f.key);
    if (el && el.value.trim()) values[f.key] = el.value.trim();
  }
  if (!Object.keys(values).length) return;
  try {
    const r = await fetch('/api/setup/save', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ component_id: _cfgIntegration, values })
    });
    const d = await r.json();
    closeCfgModal();
    _addSetupMsg('bot', '\u2705 Saved! Refreshing skill status\u2026');
    await loadSkills();
    _addSetupMsg('bot', 'Done. ' + meta.title + ' integration is now configured. Relevant agents should now show as Ready.');
  } catch(e) {
    _addSetupMsg('bot', '\u274C Save failed: ' + e.message + '. Try Setup & Config page directly.');
    closeCfgModal();
  }
}

// ── Setup Chat Panel ─────────────────────────────────────────────────────────
function _addSetupMsg(role, text) {
  const chat = document.getElementById('setupChat');
  const div = document.createElement('div');
  div.className = 'setup-msg ' + role;
  div.textContent = text;
  chat.appendChild(div);
  chat.scrollTop = chat.scrollHeight;
}

function _initSetupChat() {
  const chat = document.getElementById('setupChat');
  if (chat.children.length) return;
  const needsSetup = _allCards.filter(c => c.needs_config);
  if (needsSetup.length) {
    const intIds = [...new Set(needsSetup.map(c => c.integration_id).filter(Boolean))];
    _addSetupMsg('bot', 'Hi! I can help you activate more skills. You have ' + needsSetup.length + ' agent(s) waiting for credentials.');
    _addSetupMsg('bot', 'Integrations that need setup: ' + intIds.join(', ') + '.\n\nType the name of one to get started, or click "Configure" on any card.');
  } else {
    _addSetupMsg('bot', 'All your skills are active! If you add a new integration, I\'ll help you configure it here.');
  }
}

function _matchIntegration(text) {
  const t = text.toLowerCase();
  for (const [id, meta] of Object.entries(INTEGRATION_META)) {
    if (t.includes(id.replace('_', ' ')) || t.includes(meta.title.toLowerCase()) || t.includes(id)) {
      return id;
    }
  }
  return null;
}

function sendSetup() {
  const input = document.getElementById('setupInput');
  const text = input.value.trim();
  if (!text) return;
  input.value = '';
  _addSetupMsg('user', text);

  const matched = _matchIntegration(text);
  if (matched) {
    const meta = INTEGRATION_META[matched];
    _addSetupMsg('bot', 'Great! Let me help you set up ' + meta.title + '.');
    setTimeout(() => {
      openSetupFor(matched, meta.title);
    }, 300);
  } else if (text.toLowerCase().includes('list') || text.toLowerCase().includes('what')) {
    const all = Object.entries(INTEGRATION_META).map(([id,m]) => m.emoji + ' ' + m.title).join(', ');
    _addSetupMsg('bot', 'Available integrations: ' + all + '.\n\nType any name to start configuring it.');
  } else if (text.toLowerCase().includes('help')) {
    _addSetupMsg('bot', 'Type the name of an integration you want to set up, like "set up GitHub" or "configure AWS". I\'ll open a setup form for it. You can also click the "Configure" button on any skill card directly.');
  } else {
    _addSetupMsg('bot', 'I didn\'t recognise that integration. Try: GitHub, Slack, WhatsApp, Telegram, AWS, Qdrant, ElevenLabs, SerpApi, or Google Workspace. Or type "list" to see all options.');
  }
}

loadSkills();
</script>
</body>
</html>"""


_RUNS_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kendr &#x2014; Run History</title>
<style>
:root { --teal: #00C9A7; --amber: #FFB347; --crimson: #FF4757; --bg: #0d0f14; --surface: #161b22; --surface2: #1e2530; --border: #2a3140; --text: #e6edf3; --muted: #7d8590; --sidebar-w: 280px; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "Segoe UI", system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; }
.sidebar { width: var(--sidebar-w); min-width: var(--sidebar-w); background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; position: fixed; top: 0; bottom: 0; left: 0; }
.sidebar-header { padding: 20px 16px 12px; border-bottom: 1px solid var(--border); }
.logo { font-size: 22px; font-weight: 800; color: var(--teal); }
.logo span { color: var(--amber); }
.tagline { font-size: 11px; color: var(--muted); margin-top: 4px; }
.sidebar-nav { padding: 12px 8px; display: flex; flex-direction: column; gap: 4px; }
.nav-btn { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-radius: 8px; font-size: 13px; font-weight: 500; color: var(--muted); cursor: pointer; border: none; background: transparent; width: 100%; text-align: left; text-decoration: none; transition: background 0.15s, color 0.15s; }
.nav-btn:hover { background: var(--surface2); color: var(--text); }
.nav-btn.active { background: rgba(0,201,167,0.12); color: var(--teal); }
.nav-btn .icon { font-size: 16px; width: 20px; text-align: center; }
.main { flex: 1; margin-left: var(--sidebar-w); padding: 32px; }
.page-title { font-size: 26px; font-weight: 700; margin-bottom: 24px; }
.run-table { width: 100%; border-collapse: collapse; }
.run-table th { text-align: left; padding: 10px 16px; font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.06em; border-bottom: 1px solid var(--border); }
.run-table td { padding: 12px 16px; border-bottom: 1px solid var(--border); font-size: 13px; vertical-align: top; }
.run-table tr:hover td { background: var(--surface); }
.badge { display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: 600; }
.badge.completed { background: rgba(0,201,167,0.15); color: var(--teal); }
.badge.failed { background: rgba(255,71,87,0.15); color: var(--crimson); }
.badge.running { background: rgba(255,179,71,0.15); color: var(--amber); }
::-webkit-scrollbar { width: 6px; } ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
</head>
<body>
<div class="sidebar">
  <div class="sidebar-header"><div class="logo">kendr<span>.</span></div><div class="tagline">Multi-agent intelligence runtime</div></div>
  <div class="sidebar-nav">
    <a href="/" class="nav-btn"><span class="icon">&#x1F4AC;</span> Chat</a>
    <a href="/setup" class="nav-btn"><span class="icon">&#x2699;&#xFE0F;</span> Setup &amp; Config</a>
    <a href="/runs" class="nav-btn active"><span class="icon">&#x1F4CB;</span> Run History</a>
    <a href="/skills" class="nav-btn"><span class="icon">&#x1F9E0;</span> Skill Cards</a>
    <a href="/rag" class="nav-btn"><span class="icon">&#x1F52C;</span> Super-RAG</a>
    <a href="/models" class="nav-btn"><span class="icon">&#x1F916;</span> LLM Models</a>
    <a href="/capabilities" class="nav-btn"><span class="icon">&#x2692;&#xFE0F;</span> Capabilities</a>
    <a href="/projects" class="nav-btn"><span class="icon">&#x1F4C1;</span> Projects</a>
    <a href="/docs" class="nav-btn"><span class="icon">&#x1F4D6;</span> Docs</a>
  </div>
</div>
<div class="main">
  <div class="page-title">Run History</div>
  <table class="run-table">
    <thead><tr><th>Query</th><th>Run ID</th><th>Status</th><th>Agent</th><th>Created</th><th>Files</th></tr></thead>
    <tbody id="runBody"><tr><td colspan="5" style="color:var(--muted);text-align:center;padding:24px">Loading...</td></tr></tbody>
  </table>
</div>
<script>
function esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
async function load() {
  try {
    const r = await fetch('/api/runs');
    const runs = await r.json();
    const body = document.getElementById('runBody');
    if (!runs || !runs.length) { body.innerHTML = '<tr><td colspan="6" style="color:var(--muted);text-align:center;padding:24px">No runs yet. Start a chat to create your first run.</td></tr>'; return; }
    body.innerHTML = runs.map(run => {
      const status = (run.status || 'completed').toLowerCase();
      const rid = run.run_id || '';
      const query = run.user_query || run.query || run.text || '';
      const createdAt = run.started_at || run.created_at || run.updated_at || '';
      return '<tr><td style="max-width:280px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="' + esc(query) + '">' + esc((query||'\u2014').substring(0,70)) + '</td><td style="font-family:monospace;font-size:11px;color:var(--muted)">' + esc(rid) + '</td><td><span class="badge ' + status + '">' + status + '</span></td><td style="color:var(--muted)">' + esc(run.last_agent||run.active_task||'') + '</td><td style="color:var(--muted);white-space:nowrap">' + esc(createdAt) + '</td><td><button onclick="showArtifacts(\'' + rid + '\', this)" style="background:none;border:1px solid var(--border);color:var(--teal);border-radius:6px;padding:3px 8px;cursor:pointer;font-size:11px">\ud83d\udcc1</button></td></tr>';
    }).join('');
  } catch(e) { document.getElementById('runBody').innerHTML = '<tr><td colspan="6" style="color:var(--crimson)">Error: ' + String(e) + '</td></tr>'; }
}
async function showArtifacts(runId, btn) {
  btn.disabled = true;
  try {
    const r = await fetch('/api/runs/' + runId + '/artifacts');
    const d = await r.json();
    const files = (d.files || []);
    if (!files.length) { btn.textContent = '\u2205 none'; return; }
    const row = btn.closest('tr');
    const extra = document.createElement('tr');
    extra.innerHTML = '<td colspan="6" style="background:var(--surface2);padding:10px 16px"><strong style="font-size:11px;color:var(--muted)">ARTIFACTS</strong> ' +
      files.map(f => '<a href="/api/artifacts/download?run_id=' + encodeURIComponent(runId) + '&name=' + encodeURIComponent(f.name) + '" download="' + esc(f.name) + '" style="color:var(--teal);text-decoration:underline;margin-right:12px;font-size:12px">' + esc(f.name) + '</a>').join('') + '</td>';
    row.insertAdjacentElement('afterend', extra);
    btn.style.display = 'none';
  } catch(e) { btn.disabled = false; }
}
load();
</script>
</body>
</html>"""


class KendrUIHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        try:
            rendered = fmt % args
        except Exception:
            rendered = fmt
        client = self.client_address[0] if getattr(self, "client_address", None) else "-"
        _log.info("[request] %s %s", client, rendered)

    _CORS_SAFE_PREFIXES = ("/api/stream", "/stream")

    def _send(self, status: int, content_type: str, body: bytes, cors: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if cors:
            self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status: int, payload: dict | list) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        path = getattr(self, "path", "")
        cors = any(path.startswith(p) for p in self._CORS_SAFE_PREFIXES)
        self._send(status, "application/json; charset=utf-8", body, cors=cors)

    def _html(self, status: int, content: str) -> None:
        self._send(status, "text/html; charset=utf-8", content.encode("utf-8"), cors=False)

    def _handle_docs(self) -> None:
        import re, html as _html_mod
        docs_path = bundled_resource_path("docs", "cli.md")
        if not docs_path.exists():
            self._html(404, "<html><body><h1>docs/cli.md not found</h1></body></html>")
            return
        raw = docs_path.read_text(encoding="utf-8")

        def _md_to_html(text: str) -> str:
            lines = text.split("\n")
            out = []
            in_code = False
            in_table = False
            code_buf = []
            para_buf = []

            def flush_para():
                if para_buf:
                    joined = " ".join(para_buf).strip()
                    if joined:
                        out.append("<p>" + joined + "</p>")
                    para_buf.clear()

            def flush_table():
                nonlocal in_table
                if in_table:
                    out.append("</tbody></table>")
                    in_table = False

            def inline(s: str) -> str:
                s = _html_mod.escape(s)
                s = re.sub(r"`([^`]+)`", r'<code>\1</code>', s)
                s = re.sub(r"\*\*([^*]+)\*\*", r'<strong>\1</strong>', s)
                s = re.sub(r"\*([^*]+)\*", r'<em>\1</em>', s)
                s = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2" target="_blank">\1</a>', s)
                return s

            first_table_row = False
            for line in lines:
                if line.startswith("```"):
                    if not in_code:
                        flush_para()
                        flush_table()
                        lang = line[3:].strip() or "bash"
                        out.append('<div class="code-block"><div class="code-lang">' + _html_mod.escape(lang) + '</div><pre><code>')
                        in_code = True
                    else:
                        out.append("</code></pre></div>")
                        in_code = False
                    continue
                if in_code:
                    out.append(_html_mod.escape(line))
                    continue
                if line.startswith("# "):
                    flush_para(); flush_table()
                    anchor = re.sub(r"[^a-z0-9]+", "-", line[2:].lower()).strip("-")
                    out.append('<h1 id="' + anchor + '">' + inline(line[2:]) + '</h1>')
                    continue
                if line.startswith("## "):
                    flush_para(); flush_table()
                    anchor = re.sub(r"[^a-z0-9]+", "-", line[3:].lower()).strip("-")
                    out.append('<h2 id="' + anchor + '">' + inline(line[3:]) + '</h2>')
                    continue
                if line.startswith("### "):
                    flush_para(); flush_table()
                    anchor = re.sub(r"[^a-z0-9]+", "-", line[4:].lower()).strip("-")
                    out.append('<h3 id="' + anchor + '">' + inline(line[4:]) + '</h3>')
                    continue
                if re.match(r"^-{3,}$", line.strip()):
                    flush_para(); flush_table()
                    out.append("<hr>")
                    continue
                if line.startswith("|"):
                    flush_para()
                    cells = [c.strip() for c in line.split("|")[1:-1]]
                    if re.match(r"^[\s\-|:]+$", line):
                        first_table_row = False
                        continue
                    if not in_table:
                        out.append('<table><thead><tr>' + "".join("<th>" + inline(c) + "</th>" for c in cells) + "</tr></thead><tbody>")
                        in_table = True
                        first_table_row = False
                    else:
                        out.append("<tr>" + "".join("<td>" + inline(c) + "</td>" for c in cells) + "</tr>")
                    continue
                flush_table()
                if line.strip() == "":
                    flush_para()
                    continue
                para_buf.append(inline(line))
            flush_para()
            flush_table()
            return "\n".join(out)

        body_html = _md_to_html(raw)

        sections = re.findall(r'<h2 id="([^"]+)">([^<]+)</h2>', body_html)
        toc_items = "".join(
            '<li><a href="#' + sid + '">' + label + '</a></li>'
            for sid, label in sections
        )
        toc_html = '<nav class="toc"><div class="toc-title">On this page</div><ul>' + toc_items + '</ul></nav>' if toc_items else ""

        page = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Kendr &mdash; CLI Reference</title>
<style>
:root { --teal: #00C9A7; --amber: #FFB347; --purple: #A78BFA; --bg: #0d0f14; --surface: #161b22; --surface2: #1e2530; --border: #2a3140; --text: #e6edf3; --muted: #7d8590; --sidebar-w: 220px; }
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "Segoe UI", system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); min-height: 100vh; display: flex; }
.sidebar { width: var(--sidebar-w); min-width: var(--sidebar-w); background: var(--surface); border-right: 1px solid var(--border); display: flex; flex-direction: column; position: fixed; top: 0; bottom: 0; left: 0; overflow-y: auto; }
.sidebar-header { padding: 20px 16px 12px; border-bottom: 1px solid var(--border); }
.logo { font-size: 22px; font-weight: 800; color: var(--teal); }
.logo span { color: var(--amber); }
.tagline { font-size: 11px; color: var(--muted); margin-top: 4px; }
.sidebar-nav { padding: 12px 8px; border-bottom: 1px solid var(--border); display: flex; flex-direction: column; gap: 4px; }
.nav-btn { display: flex; align-items: center; gap: 10px; padding: 9px 12px; border-radius: 8px; font-size: 13px; font-weight: 500; color: var(--muted); cursor: pointer; border: none; background: transparent; width: 100%; text-align: left; text-decoration: none; transition: background 0.15s, color 0.15s; }
.nav-btn:hover { background: var(--surface2); color: var(--text); }
.nav-btn.active { background: rgba(167,139,250,0.12); color: var(--purple); }
.nav-btn .icon { font-size: 16px; width: 20px; text-align: center; }
.content-wrap { flex: 1; margin-left: var(--sidebar-w); display: flex; }
.doc-content { flex: 1; padding: 32px 40px; max-width: 860px; min-width: 0; }
.toc { width: 200px; min-width: 200px; padding: 32px 16px 32px 0; position: sticky; top: 0; height: 100vh; overflow-y: auto; }
.toc-title { font-size: 11px; font-weight: 700; color: var(--muted); text-transform: uppercase; letter-spacing: 0.07em; margin-bottom: 10px; }
.toc ul { list-style: none; }
.toc li { margin-bottom: 4px; }
.toc a { font-size: 12px; color: var(--muted); text-decoration: none; display: block; padding: 3px 8px; border-radius: 5px; }
.toc a:hover { color: var(--teal); background: var(--surface); }
h1 { font-size: 28px; font-weight: 800; color: var(--text); margin: 0 0 6px; }
h2 { font-size: 19px; font-weight: 700; color: var(--teal); margin: 40px 0 10px; padding-bottom: 8px; border-bottom: 1px solid var(--border); }
h3 { font-size: 14px; font-weight: 700; color: var(--purple); margin: 22px 0 8px; }
p { font-size: 13px; color: #c5d0db; line-height: 1.7; margin: 8px 0; }
hr { border: none; border-top: 1px solid var(--border); margin: 28px 0; }
code { font-family: "Cascadia Code", "Fira Code", monospace; font-size: 12px; background: var(--surface2); border: 1px solid var(--border); border-radius: 4px; padding: 1px 5px; color: var(--teal); }
.code-block { background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; margin: 14px 0; overflow: hidden; }
.code-lang { font-size: 10px; font-weight: 700; color: var(--muted); text-transform: uppercase; padding: 6px 14px; border-bottom: 1px solid var(--border); }
.code-block pre { margin: 0; padding: 14px 16px; overflow-x: auto; }
.code-block code { background: none; border: none; padding: 0; color: #b5c4de; font-size: 12.5px; white-space: pre; }
table { width: 100%; border-collapse: collapse; font-size: 12.5px; margin: 14px 0; }
th { background: var(--surface2); color: var(--muted); text-align: left; padding: 8px 12px; font-weight: 600; border: 1px solid var(--border); text-transform: uppercase; font-size: 11px; letter-spacing: 0.04em; }
td { padding: 8px 12px; border: 1px solid var(--border); color: #c5d0db; vertical-align: top; }
td code { font-size: 11.5px; }
tr:hover td { background: rgba(0,201,167,0.03); }
a { color: var(--teal); }
strong { color: var(--text); }
::-webkit-scrollbar { width: 5px; } ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
</style>
</head>
<body>
<div class="sidebar">
  <div class="sidebar-header"><div class="logo">kendr<span>.</span></div><div class="tagline">Multi-agent intelligence runtime</div></div>
  <div class="sidebar-nav">
    <a href="/" class="nav-btn"><span class="icon">&#x1F4AC;</span> Chat</a>
    <a href="/setup" class="nav-btn"><span class="icon">&#x2699;&#xFE0F;</span> Setup &amp; Config</a>
    <a href="/runs" class="nav-btn"><span class="icon">&#x1F4CB;</span> Run History</a>
    <a href="/skills" class="nav-btn"><span class="icon">&#x1F9E0;</span> Skill Cards</a>
    <a href="/rag" class="nav-btn"><span class="icon">&#x1F52C;</span> Super-RAG</a>
    <a href="/models" class="nav-btn"><span class="icon">&#x1F916;</span> LLM Models</a>
    <a href="/capabilities" class="nav-btn"><span class="icon">&#x2692;&#xFE0F;</span> Capabilities</a>
    <a href="/projects" class="nav-btn"><span class="icon">&#x1F4C1;</span> Projects</a>
    <a href="/docs" class="nav-btn active"><span class="icon">&#x1F4D6;</span> Docs</a>
  </div>
</div>
<div class="content-wrap">
  <div class="doc-content">
""" + body_html + """
  </div>
""" + toc_html + """
</div>
</body>
</html>"""
        self._html(200, page)

    def do_OPTIONS(self):
        self.send_response(200)
        path = getattr(self, "path", "")
        if any(path.startswith(p) for p in self._CORS_SAFE_PREFIXES):
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        if path in ("/", "/chat"):
            self._html(200, _CHAT_HTML)
            return
        if path == "/setup":
            self._html(200, _SETUP_HTML)
            return
        if path == "/runs":
            self._html(200, _RUNS_HTML)
            return
        if path == "/rag":
            self._html(200, _RAG_HTML)
            return
        if path == "/mcp":
            self.send_response(302)
            self.send_header("Location", "/capabilities")
            self.end_headers()
            return
        if path == "/capabilities":
            self._html(200, _CAPABILITIES_HTML)
            return
        if path == "/skills":
            self._html(200, _SKILLS_HTML)
            return
        if path == "/projects":
            self._html(200, _PROJECTS_HTML)
            return
        if path == "/models":
            self._html(200, _MODELS_HTML)
            return
        if path == "/docs":
            self._handle_docs()
            return
        if path == "/api/rag/kbs":
            self._handle_rag_list_kbs()
            return
        if path.startswith("/api/rag/kbs/") and path.endswith("/sources"):
            kb_id = path[len("/api/rag/kbs/"):-len("/sources")]
            self._handle_rag_list_sources(kb_id)
            return
        if path.startswith("/api/rag/kbs/") and path.endswith("/index/status"):
            kb_id = path[len("/api/rag/kbs/"):-len("/index/status")]
            self._handle_rag_index_status(kb_id)
            return
        if path.startswith("/api/rag/kbs/") and path.endswith("/status"):
            kb_id = path[len("/api/rag/kbs/"):-len("/status")]
            self._handle_rag_kb_status(kb_id)
            return
        if path.startswith("/api/rag/kbs/") and not path.endswith("/"):
            # Single KB detail: /api/rag/kbs/<id>
            parts = path[len("/api/rag/kbs/"):].split("/")
            if len(parts) == 1:
                self._handle_rag_get_kb(parts[0])
                return
        if path == "/api/rag/agents":
            self._handle_rag_list_agents()
            return
        if path == "/api/health":
            self._json(200, {"service": "kendr-ui", "status": "ok"})
            return
        if path == "/api/machine/status":
            params = parse_qs(parsed.query or "")
            working_directory = str((params.get("working_directory") or [""])[0] or "").strip()
            if not working_directory:
                working_directory = os.path.abspath(os.getcwd())
            try:
                status = machine_sync_status(working_directory)
                self._json(200, {"working_directory": working_directory, "status": status})
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        if path == "/api/machine/details":
            params = parse_qs(parsed.query or "")
            working_directory = str((params.get("working_directory") or [""])[0] or "").strip()
            if not working_directory:
                working_directory = os.path.abspath(os.getcwd())
            try:
                max_files_raw = str((params.get("max_files") or [""])[0] or "").strip()
                max_files = max(100, min(int(max_files_raw or 20000), 50000))
                self._json(200, machine_sync_details(working_directory, max_files=max_files))
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        if path == "/api/models":
            try:
                from kendr.llm_router import (
                    all_provider_statuses,
                    get_active_provider,
                    get_model_for_provider,
                    get_context_window,
                    is_ollama_running,
                    list_ollama_models,
                )
                configured_provider = get_active_provider()
                configured_model = get_model_for_provider(configured_provider)
                statuses = all_provider_statuses()
                status_by_provider = {
                    str(item.get("provider") or "").strip(): dict(item)
                    for item in statuses
                    if isinstance(item, dict)
                }
                configured_status = dict(status_by_provider.get(configured_provider) or {})
                configured_ready = bool(configured_status.get("ready"))
                active = configured_provider
                active_model = configured_model
                active_note = str(configured_status.get("note") or "").strip()
                if not configured_ready:
                    fallback = next(
                        (
                            item
                            for item in statuses
                            if isinstance(item, dict) and bool(item.get("ready")) and str(item.get("provider") or "").strip()
                        ),
                        None,
                    )
                    if isinstance(fallback, dict):
                        active = str(fallback.get("provider") or configured_provider).strip() or configured_provider
                        active_model = str(fallback.get("model") or get_model_for_provider(active)).strip() or get_model_for_provider(active)
                        active_note = (
                            f"Configured provider '{configured_provider}' is offline. "
                            f"Showing the first ready provider instead."
                        )
                ollama_running = is_ollama_running()
                ollama_models = list_ollama_models() if ollama_running else []
                for s in statuses:
                    s["context_window"] = get_context_window(s.get("model", ""))
                comparison_rows = _comparison_rows_from_provider_statuses(statuses)
                self._json(200, {
                    "active_provider": active,
                    "active_model": active_model,
                    "active_context_window": get_context_window(active_model),
                    "active_provider_ready": bool((status_by_provider.get(active) or {}).get("ready")),
                    "active_provider_note": active_note,
                    "configured_provider": configured_provider,
                    "configured_model": configured_model,
                    "configured_provider_ready": configured_ready,
                    "configured_provider_note": str(configured_status.get("note") or "").strip(),
                    "providers": statuses,
                    "comparison_rows": comparison_rows,
                    "ollama_running": ollama_running,
                    "ollama_models": [m.get("name", "") for m in ollama_models],
                })
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        if path == "/api/models/ollama":
            try:
                from kendr.llm_router import is_ollama_running, list_ollama_models

                running = is_ollama_running()
                models = list_ollama_models() if running else []
                self._json(200, {
                    "running": running,
                    "models": models,
                })
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        if path == "/api/models/guide":
            try:
                params = parse_qs(parsed.query or "")
                force = str((params.get("refresh") or [""])[0] or "").strip().lower() in {"1", "true", "yes"}
                self._json(200, _get_model_guide(force=force))
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        if path == "/api/models/ollama/pull/status":
            self._json(200, _ollama_pull_public_state())
            return
        if path == "/api/models/ollama/docker/status":
            self._handle_ollama_docker_status()
            return
        if path == "/api/assistants":
            workspace_id = _assistant_workspace_id(parsed=parsed)
            params = parse_qs(parsed.query or "")
            status_filter = str((params.get("status") or [""])[0] or "").strip()
            search = str((params.get("q") or [""])[0] or "").strip()
            items = _db_list_assistants(workspace_id=workspace_id, status=status_filter, search=search, limit=200)
            self._json(200, {"assistants": items, "workspace_id": workspace_id, "count": len(items)})
            return
        if path.startswith("/api/assistants/"):
            assistant_id = path[len("/api/assistants/"):].strip()
            if assistant_id and "/" not in assistant_id:
                item = _db_get_assistant(assistant_id)
                if not item:
                    self._json(404, {"error": "assistant_not_found"})
                    return
                self._json(200, item)
                return
        if path == "/api/skills":
            try:
                data = _gateway_get("/registry/skills", timeout=5.0)
                self._json(200, data)
            except Exception:
                self._json(503, {"error": "Gateway offline", "summary": {}, "cards": []})
            return
        # ── Unified connector catalog ─────────────────────────────────────────
        if path == "/api/connectors":
            status, data = _gateway_forward_json("GET", "/registry/connectors", timeout=8.0)
            self._json(status, data)
            return
        # ── Skill marketplace (proxied to gateway) ────────────────────────────
        if path == "/api/marketplace/skills":
            suffix = f"?{parsed.query}" if parsed.query else ""
            status, data = _gateway_forward_json("GET", f"/api/marketplace/skills{suffix}", timeout=8.0)
            self._json(status, data)
            return
        if path == "/api/marketplace/skills/installed":
            status, data = _gateway_forward_json("GET", "/api/marketplace/skills/installed", timeout=8.0)
            self._json(status, data)
            return
        if path.startswith("/api/marketplace/skills/"):
            rest = path[len("/api/marketplace/skills/"):]
            if rest:
                status, data = _gateway_forward_json("GET", f"/api/marketplace/skills/{rest}", timeout=8.0)
                self._json(status, data)
                return
        if path == "/api/capabilities":
            suffix = f"?{parsed.query}" if parsed.query else ""
            status, data = _gateway_forward_json("GET", f"/registry/capabilities{suffix}", timeout=8.0)
            self._json(status, data)
            return
        if path == "/api/capabilities/auth-profiles":
            suffix = f"?{parsed.query}" if parsed.query else ""
            status, data = _gateway_forward_json("GET", f"/registry/auth-profiles{suffix}", timeout=8.0)
            self._json(status, data)
            return
        if path == "/api/capabilities/policy-profiles":
            suffix = f"?{parsed.query}" if parsed.query else ""
            status, data = _gateway_forward_json("GET", f"/registry/policy-profiles{suffix}", timeout=8.0)
            self._json(status, data)
            return
        if path == "/api/capabilities/discovery":
            suffix = f"?{parsed.query}" if parsed.query else ""
            status, data = _gateway_forward_json("GET", f"/registry/discovery{suffix}", timeout=8.0)
            self._json(status, data)
            return
        if path == "/api/capabilities/discovery/cards":
            suffix = f"?{parsed.query}" if parsed.query else ""
            status, data = _gateway_forward_json("GET", f"/registry/discovery/cards{suffix}", timeout=8.0)
            self._json(status, data)
            return
        if path.startswith("/api/capabilities/"):
            rest = path[len("/api/capabilities/"):].strip()
            if "/" in rest:
                capability_id, action = rest.split("/", 1)
                action = action.strip().lower()
                if action in {"health", "audit"}:
                    suffix = f"?{parsed.query}" if parsed.query else ""
                    status, data = _gateway_forward_json(
                        "GET",
                        f"/registry/capabilities/{capability_id}/{action}{suffix}",
                        timeout=8.0,
                    )
                    self._json(status, data)
                    return
            capability_id = rest
            if capability_id and "/" not in capability_id:
                status, data = _gateway_forward_json(
                    "GET",
                    f"/registry/capabilities/{capability_id}",
                    timeout=8.0,
                )
                self._json(status, data)
                return
        if path == "/api/plan":
            try:
                data = _gateway_get("/registry/plan", timeout=3.0)
                self._json(200, data)
            except Exception:
                self._json(200, {"has_plan": False, "steps": [], "total_steps": 0, "completed_steps": 0})
            return
        if path == "/api/gateway/status":
            working_dir = os.getenv("KENDR_WORKING_DIR", "").strip()
            self._json(200, {
                "online": _gateway_ready(),
                "gateway_url": _gateway_url(),
                "working_dir": working_dir,
                "ui_port": _UI_PORT,
            })
            return
        if path == "/api/runs":
            try:
                runs = _gateway_get("/runs", timeout=5.0)
            except Exception:
                runs = []
            run_rows = runs if isinstance(runs, list) else []
            params = parse_qs(parsed.query or "")
            raw_mode = str((params.get("raw") or [""])[0] or "").strip().lower() in {"1", "true", "yes", "on"}
            if raw_mode:
                self._json(200, _live_recent_runs_with_pending(run_rows, collapse_workflows=False))
            else:
                self._json(200, _live_recent_runs(run_rows))
            return
        if path == "/api/chat/threads":
            try:
                runs = _gateway_get("/runs", timeout=5.0)
            except Exception:
                runs = []
            try:
                sessions = _gateway_get("/sessions", timeout=5.0)
            except Exception:
                sessions = []
            self._json(
                200,
                _live_recent_chat_threads(
                    runs if isinstance(runs, list) else [],
                    sessions if isinstance(sessions, list) else [],
                ),
            )
            return
        if path == "/api/artifacts/download":
            params = parse_qs(parsed.query or "")
            run_id = (params.get("run_id") or [""])[0]
            name = (params.get("name") or [""])[0]
            if not run_id or not name or "\\" in name or name.startswith(".") or ".." in name:
                self._json(400, {"error": "invalid_request"})
                return
            file_path = _resolve_run_artifact_path(run_id, name)
            if not file_path:
                self._json(404, {"error": "file_not_found", "name": name})
                return
            try:
                with open(file_path, "rb") as fh:
                    data = fh.read()
                import mimetypes
                mime_type, _ = mimetypes.guess_type(file_path)
                content_type = mime_type or "application/octet-stream"
                safe_name = os.path.basename(file_path)
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", f'attachment; filename="{safe_name}"')
                self.end_headers()
                self.wfile.write(data)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        if path == "/api/artifacts/view":
            params = parse_qs(parsed.query or "")
            run_id = (params.get("run_id") or [""])[0]
            name = (params.get("name") or [""])[0]
            if not run_id or not name or "\\" in name or name.startswith(".") or ".." in name:
                self._json(400, {"error": "invalid_request"})
                return
            file_path = _resolve_run_artifact_path(run_id, name)
            if not file_path:
                self._json(404, {"error": "file_not_found", "name": name})
                return
            try:
                with open(file_path, "rb") as fh:
                    data = fh.read()
                import mimetypes
                mime_type, _ = mimetypes.guess_type(file_path)
                content_type = mime_type or "application/octet-stream"
                safe_name = os.path.basename(file_path)
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Content-Disposition", f'inline; filename="{safe_name}"')
                self.send_header("X-Frame-Options", "SAMEORIGIN")
                if content_type.startswith("text/html"):
                    self.send_header(
                        "Content-Security-Policy",
                        "default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; frame-ancestors 'self'; base-uri 'none'",
                    )
                self.end_headers()
                self.wfile.write(data)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        if path.startswith("/api/runs/") and path.endswith("/messages"):
            run_id = path[len("/api/runs/"):-len("/messages")]
            try:
                msgs = _db_list_run_messages(run_id, limit=300)
            except Exception:
                msgs = []
            self._json(200, {"run_id": run_id, "messages": msgs})
            return
        if path.startswith("/api/runs/") and path.endswith("/artifacts"):
            run_id = path[len("/api/runs/"):-len("/artifacts")]
            db_artifacts, file_list = [], []
            output_dir = ""
            try:
                run_row = _db_get_run(run_id)
                if run_row:
                    output_dir = run_row.get("run_output_dir", "")
                if not output_dir:
                    output_dir = _get_run_output_dir_from_manifest(run_id)
                db_artifacts, file_list = _collect_artifacts(run_id, output_dir)
            except Exception:
                pass
            self._json(200, {
                "run_id": run_id,
                "output_dir": output_dir,
                "artifacts": db_artifacts,
                "files": file_list,
            })
            return
        if path.startswith("/api/task-sessions/by-run/"):
            run_id = path[len("/api/task-sessions/by-run/"):]
            try:
                data = _gateway_get(f"/task-sessions/by-run/{run_id}")
            except Exception as exc:
                self._json(500, {"error": str(exc)})
                return
            self._json(200, data)
            return
        if path.startswith("/api/runs/"):
            run_id = path[len("/api/runs/"):]
            try:
                data = _gateway_get(f"/runs/{run_id}")
            except Exception as exc:
                with _pending_lock:
                    pending = dict(_pending_runs.get(run_id, {})) if run_id in _pending_runs else None
                live_only = _overlay_run_with_pending(None, pending)
                if live_only:
                    self._json(200, live_only)
                    return
                self._json(500, {"error": str(exc)})
                return
            self._json(200, _live_run(data if isinstance(data, dict) else None) or data)
            return
        if path == "/api/setup/overview":
            try:
                apply_setup_env_defaults()
                overview = setup_overview()
            except Exception as exc:
                self._json(500, {"error": str(exc)})
                return
            self._json(200, overview)
            return
        if path.startswith("/api/setup/component/"):
            comp_id = path[len("/api/setup/component/"):]
            try:
                snap = get_setup_component_snapshot(comp_id)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
                return
            if not snap:
                self._json(404, {"error": "component_not_found"})
                return
            snap = dict(snap)
            snap.pop("raw_values", None)
            oauth_path = _OAUTH_PATH_MAP.get(comp_id, "")
            if oauth_path and snap.get("component") is not None:
                parts = oauth_path.strip("/").split("/")
                provider = parts[1] if len(parts) >= 2 else ""
                snap["component"] = dict(snap["component"])
                if provider:
                    snap["component"]["oauth_start_path"] = f"/api/oauth/{provider}/start"
                    snap["component"]["oauth_provider"] = provider
            self._json(200, snap)
            return
        if path == "/api/setup/env-export":
            try:
                lines = export_env_lines(include_secrets=False)
            except Exception as exc:
                lines = []
            self._json(200, {"lines": lines})
            return
        if path.startswith("/api/setup/test-connection/"):
            comp_id = path[len("/api/setup/test-connection/"):]
            self._handle_test_connection(comp_id)
            return
        if path.startswith("/api/oauth/") and path.endswith("/start"):
            provider = path[len("/api/oauth/"):-len("/start")]
            self._handle_oauth_start(provider)
            return
        if path.startswith("/api/oauth/") and path.endswith("/callback"):
            provider = path[len("/api/oauth/"):-len("/callback")]
            self._handle_oauth_callback(provider, parse_qs(parsed.query or ""))
            return
        if path == "/api/projects":
            self._handle_projects_list()
            return
        if path == "/api/projects/active":
            self._handle_project_active()
            return
        if path == "/api/projects/active/context":
            self._handle_project_context_get()
            return
        if path == "/api/projects/file":
            params = parse_qs(parsed.query or "")
            file_path = (params.get("path") or [""])[0]
            project_root = (params.get("root") or [""])[0]
            self._handle_project_read_file(file_path, project_root)
            return
        if path.startswith("/api/projects/") and path.endswith("/chat/history"):
            project_id = path[len("/api/projects/"):-len("/chat/history")]
            self._handle_project_chat_history(project_id)
            return
        if path.startswith("/api/projects/") and path.endswith("/services"):
            project_id = path[len("/api/projects/"):-len("/services")]
            self._handle_project_services_list(project_id)
            return
        if path.startswith("/api/projects/") and path.endswith("/log"):
            rest = path[len("/api/projects/"):]
            marker = "/services/"
            if marker in rest and rest.endswith("/log"):
                project_id, service_rest = rest.split(marker, 1)
                service_id = service_rest[:-len("/log")].strip("/")
                self._handle_project_service_log(project_id, service_id)
                return
        if path.startswith("/api/projects/") and path.endswith("/files"):
            project_id = path[len("/api/projects/"):-len("/files")]
            self._handle_project_file_tree(project_id)
            return
        if path.startswith("/api/projects/") and path.endswith("/download"):
            project_id = path[len("/api/projects/"):-len("/download")]
            params = parse_qs(parsed.query or "")
            fmt = (params.get("format") or ["zip"])[0].lower().strip()
            self._handle_project_download(project_id, fmt)
            return
        if path.startswith("/api/projects/") and path.endswith("/git/status"):
            project_id = path[len("/api/projects/"):-len("/git/status")]
            self._handle_project_git_status(project_id)
            return
        if path == "/api/mcp/servers":
            if not _HAS_MCP_MANAGER:
                self._json(503, {"error": "MCP manager not available"})
                return
            try:
                self._json(200, _mcp_list_servers())
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        if path == "/api/mcp/scaffold":
            code = _MCP_SCAFFOLD_CODE if _HAS_MCP_MANAGER else "# fastmcp not installed"
            self._json(200, {"code": code})
            return
        if path in ("/api/stream", "/stream"):
            params = parse_qs(parsed.query or "")
            run_id = (params.get("run_id") or [""])[0]
            if not run_id:
                self._json(400, {"error": "missing_run_id"})
                return
            self._handle_sse(run_id)
            return
        self._json(404, {"error": "not_found", "path": path})

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        content_type = str(self.headers.get("Content-Type", "") or "")
        if content_type.startswith("multipart/form-data"):
            if path == "/api/rag/upload":
                self._handle_rag_upload({})
                return
            if path == "/api/deep-research/upload":
                self._handle_deep_research_upload()
                return
            self._json(415, {"error": "multipart_not_supported", "path": path})
            return

        try:
            length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(length)
            body = json.loads(raw.decode("utf-8")) if raw else {}
        except Exception as exc:
            self._json(400, {"error": "invalid_json", "detail": str(exc)})
            return

        if path == "/api/chat":
            self._handle_chat(body)
            return
        if path == "/api/chat/compact":
            self._handle_chat_compact(body)
            return
        if path == "/api/machine/sync":
            working_directory = str(body.get("working_directory", "") or "").strip()
            if not working_directory:
                working_directory = os.path.abspath(os.getcwd())
            scope = str(body.get("scope", "machine") or "machine").strip().lower()
            roots = body.get("roots")
            if not isinstance(roots, list):
                roots = []
            try:
                result = run_machine_sync(
                    working_directory=working_directory,
                    scope=scope,
                    roots=[str(item) for item in roots if str(item).strip()],
                    max_files=int(body.get("max_files", 250000) or 250000),
                )
                self._json(200, result)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        if path == "/api/chat/resume":
            self._handle_chat_resume(body)
            return
        if path == "/api/runs/stop":
            self._handle_stop_run(body)
            return
        if path == "/api/chat/delete":
            chat_session_id = str(body.get("chat_session_id", "")).strip()
            if not chat_session_id:
                self._json(400, {"error": "missing_chat_session_id"})
                return
            try:
                result = _db_delete_chat_session(chat_session_id)
                self._json(200, {"ok": True, **result})
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        if path == "/api/runs/delete":
            run_id = str(body.get("run_id", "")).strip()
            if not run_id:
                self._json(400, {"error": "missing_run_id"})
                return
            try:
                result = _db_delete_run(run_id)
                self._json(200, result)
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        if path == "/api/projects/active/context/generate":
            self._handle_project_context_generate(body)
            return
        if path == "/api/projects/active/context/update":
            self._handle_project_context_update(body)
            return
        if path == "/api/project/ask":
            self._handle_project_ask(body)
            return
        if path == "/api/chat/simple":
            self._handle_simple_chat(body)
            return
        if path == "/api/assistants":
            self._handle_assistants_create(body)
            return
        if path == "/api/models/set":
            self._handle_models_set(body)
            return
        if path == "/api/models/ollama/pull":
            self._handle_ollama_pull(body)
            return
        if path == "/api/models/ollama/delete":
            self._handle_ollama_delete(body)
            return
        if path == "/api/models/ollama/pull/cancel":
            self._handle_ollama_pull_cancel()
            return
        if path == "/api/models/ollama/docker/start":
            self._handle_ollama_docker_start(body)
            return
        if path == "/api/models/ollama/docker/stop":
            self._handle_ollama_docker_stop()
            return
        if path == "/api/setup/save":
            self._handle_setup_save(body)
            return
        if path == "/api/setup/enabled":
            self._handle_setup_enabled(body)
            return
        if path == "/api/projects":
            self._handle_project_add(body)
            return
        if path == "/api/projects/clone":
            self._handle_project_clone(body)
            return
        if path == "/api/projects/new":
            self._handle_project_new(body)
            return
        if path == "/api/projects/shell":
            self._handle_project_shell(body)
            return
        if path.startswith("/api/projects/") and path.endswith("/services/start"):
            project_id = path[len("/api/projects/"):-len("/services/start")]
            self._handle_project_service_start(project_id, body)
            return
        if path.startswith("/api/projects/") and "/services/" in path:
            rest = path[len("/api/projects/"):]
            project_id, tail = rest.split("/services/", 1)
            if tail.endswith("/stop"):
                service_id = tail[:-len("/stop")].strip("/")
                self._handle_project_service_stop(project_id, service_id)
                return
            if tail.endswith("/restart"):
                service_id = tail[:-len("/restart")].strip("/")
                self._handle_project_service_restart(project_id, service_id)
                return
            if tail.endswith("/start"):
                service_id = tail[:-len("/start")].strip("/")
                body = dict(body)
                body["service_id"] = service_id
                self._handle_project_service_start(project_id, body)
                return
        if path.startswith("/api/projects/") and path.endswith("/activate"):
            project_id = path[len("/api/projects/"):-len("/activate")]
            self._handle_project_activate(project_id)
            return
        if path.startswith("/api/projects/") and path.endswith("/remove"):
            project_id = path[len("/api/projects/"):-len("/remove")]
            self._handle_project_remove(project_id)
            return
        if path.startswith("/api/projects/") and path.endswith("/delete-files"):
            project_id = path[len("/api/projects/"):-len("/delete-files")]
            self._handle_project_delete_files(project_id)
            return
        if path.startswith("/api/projects/") and path.endswith("/git/pull"):
            project_id = path[len("/api/projects/"):-len("/git/pull")]
            self._handle_project_git_pull(project_id)
            return
        if path.startswith("/api/assistants/"):
            rest = path[len("/api/assistants/"):].strip()
            if "/" not in rest:
                self._json(404, {"error": "not_found"})
                return
            assistant_id, action = rest.split("/", 1)
            action = action.strip().lower()
            if action == "update":
                self._handle_assistants_update(assistant_id, body)
                return
            if action == "delete":
                self._handle_assistants_delete(assistant_id)
                return
            if action == "test":
                self._handle_assistants_test(assistant_id, body)
                return
            self._json(404, {"error": "not_found"})
            return
        if path.startswith("/api/projects/") and path.endswith("/git/push"):
            project_id = path[len("/api/projects/"):-len("/git/push")]
            self._handle_project_git_push(project_id)
            return
        if path.startswith("/api/projects/") and path.endswith("/git/commit-push"):
            project_id = path[len("/api/projects/"):-len("/git/commit-push")]
            self._handle_project_git_commit_push(project_id, body)
            return
        if path == "/api/mcp/servers":
            self._handle_mcp_add(body)
            return
        if path == "/api/capabilities":
            status, data = _gateway_forward_json("POST", "/registry/capabilities", payload=body, timeout=8.0)
            self._json(status, data)
            return
        if path == "/api/capabilities/auth-profiles":
            status, data = _gateway_forward_json("POST", "/registry/auth-profiles", payload=body, timeout=8.0)
            self._json(status, data)
            return
        if path == "/api/capabilities/policy-profiles":
            status, data = _gateway_forward_json("POST", "/registry/policy-profiles", payload=body, timeout=8.0)
            self._json(status, data)
            return
        if path == "/api/capabilities/import-openapi":
            status, data = _gateway_forward_json("POST", "/registry/apis/import-openapi", payload=body, timeout=12.0)
            self._json(status, data)
            return
        if path.startswith("/api/capabilities/"):
            rest = path[len("/api/capabilities/"):].strip()
            if "/" in rest:
                capability_id, action = rest.split("/", 1)
                action = action.strip().lower()
                if action in {"update", "verify", "publish", "disable", "health-check"}:
                    status, data = _gateway_forward_json(
                        "POST",
                        f"/registry/capabilities/{capability_id}/{action}",
                        payload=body,
                        timeout=8.0,
                    )
                    self._json(status, data)
                    return
            self._json(404, {"error": "not_found"})
            return
        if path.startswith("/api/mcp/servers/"):
            rest = path[len("/api/mcp/servers/"):]
            if rest.endswith("/discover"):
                server_id = rest[:-len("/discover")]
                self._handle_mcp_discover(server_id)
            elif rest.endswith("/remove"):
                server_id = rest[:-len("/remove")]
                self._handle_mcp_remove(server_id)
            elif rest.endswith("/toggle"):
                server_id = rest[:-len("/toggle")]
                self._handle_mcp_toggle(server_id, body)
            else:
                self._json(404, {"error": "not_found"})
            return
        # ── Skill marketplace POST routes (proxied to gateway) ───────────────
        if path == "/api/marketplace/skills/create":
            status, data = _gateway_forward_json("POST", "/api/marketplace/skills/create", payload=body, timeout=8.0)
            self._json(status, data)
            return
        if path.startswith("/api/marketplace/skills/"):
            rest = path[len("/api/marketplace/skills/"):]
            action = rest.rsplit("/", 1)[-1] if "/" in rest else ""
            if action in {"install", "uninstall", "test", "approve", "revoke-approval", "edit", "delete"}:
                status, data = _gateway_forward_json("POST", f"/api/marketplace/skills/{rest}", payload=body, timeout=10.0)
                self._json(status, data)
                return
        # ── RAG routes ──────────────────────────────────────────────────────
        if path == "/api/rag/kbs":
            self._handle_rag_create_kb(body)
            return
        if path == "/api/rag/upload":
            self._handle_rag_upload(body)
            return
        if path == "/api/deep-research/upload":
            self._json(400, {"error": "Use multipart/form-data POST to /api/deep-research/upload with fields: files, chat_id"})
            return
        if path.startswith("/api/rag/kbs/"):
            rest = path[len("/api/rag/kbs/"):]
            if rest.endswith("/sources"):
                kb_id = rest[:-len("/sources")]
                self._handle_rag_add_source(kb_id, body)
            elif rest.endswith("/index"):
                kb_id = rest[:-len("/index")]
                self._handle_rag_trigger_index(kb_id, body)
            elif rest.endswith("/vector"):
                kb_id = rest[:-len("/vector")]
                self._handle_rag_update_vector(kb_id, body)
            elif rest.endswith("/reranker"):
                kb_id = rest[:-len("/reranker")]
                self._handle_rag_update_reranker(kb_id, body)
            elif rest.endswith("/agents"):
                kb_id = rest[:-len("/agents")]
                self._handle_rag_toggle_agent(kb_id, body)
            elif rest.endswith("/activate"):
                kb_id = rest[:-len("/activate")]
                self._handle_rag_activate(kb_id)
            elif rest.endswith("/query"):
                kb_id = rest[:-len("/query")]
                self._handle_rag_query(kb_id, body, with_answer=False)
            elif rest.endswith("/answer"):
                kb_id = rest[:-len("/answer")]
                self._handle_rag_query(kb_id, body, with_answer=True)
            else:
                self._json(404, {"error": "not_found"})
            return
        if path.startswith("/api/rag/kbs") and body.get("_method") == "DELETE":
            self._json(405, {"error": "use DELETE method"})
            return
        self._json(404, {"error": "not_found"})

    def _handle_chat(self, body: dict) -> None:
        text = str(body.get("text") or body.get("message") or "").strip()
        if not text:
            self._json(400, {"error": "missing_text"})
            return

        project_build_mode = bool(body.get("project_build_mode") or body.get("standalone"))

        working_directory = str(
            body.get("working_directory") or os.getenv("KENDR_WORKING_DIR", "")
        ).strip()
        if working_directory:
            working_directory = normalize_host_path_str(working_directory)
        payload = {
            "text": text,
            "channel": str(body.get("channel", "webchat")),
            "sender_id": str(body.get("sender_id", "ui_user")),
            "chat_id": str(body.get("chat_id", "")),
        }
        if working_directory:
            payload["working_directory"] = working_directory
        for key in ("provider", "model"):
            value = str(body.get(key) or "").strip()
            if value:
                payload[key] = value
        if body.get("context_limit") is not None:
            payload["context_limit"] = body.get("context_limit")
        if project_build_mode:
            payload["project_build_mode"] = True
        for key in ("project_id", "project_name", "project_stack", "stack", "project_root",
                    "github_repo", "auto_approve", "auto_approve_plan", "skip_test_agent", "skip_devops_agent",
                    "shell_auto_approve", "privileged_mode", "privileged_approved",
                    "privileged_approval_note", "privileged_approval_mode",
                    "privileged_require_approvals", "privileged_read_only",
                    "privileged_allow_root", "privileged_allow_destructive",
                    "privileged_enable_backup", "privileged_allowed_paths", "privileged_allowed_domains",
                    "workflow_type", "deep_research_mode",
                    "execution_mode", "planner_mode",
                    "long_document_mode", "long_document_pages", "long_document_title",
                    "research_output_formats", "research_citation_style",
                    "research_enable_plagiarism_check", "research_web_search_enabled", "research_date_range",
                    "research_sources", "research_max_sources", "research_checkpoint_enabled",
                    "deep_research_source_urls", "local_drive_paths", "local_drive_recursive",
                    "local_drive_force_long_document",
                    "communication_authorized",
                    "security_authorized", "security_target_url", "security_authorization_note",
                    "use_mcp"):
            if body.get(key) is not None:
                payload[key] = body[key]
        channel_name = str(payload.get("channel") or "").strip().lower()

        # Auto-inject active project context only for project workbench requests.
        # Generic web chat should remain project-agnostic by default.
        project_root_value = str(payload.get("project_root") or "").strip()
        if project_root_value:
            payload["project_root"] = normalize_host_path_str(project_root_value, base_dir=working_directory)
        if payload.get("working_directory"):
            payload["working_directory"] = normalize_host_path_str(str(payload.get("working_directory") or "").strip())
        if channel_name == "project_ui" and not payload.get("project_root"):
            try:
                active_proj = _pm_get_active()
                if active_proj:
                    proj_path = str(active_proj.get("path", "")).strip()
                    proj_name = str(active_proj.get("name", "")).strip()
                    if proj_path:
                        payload["project_root"] = proj_path
                        if proj_name and not payload.get("project_name"):
                            payload["project_name"] = proj_name
                        if not working_directory:
                            payload.setdefault("working_directory", proj_path)
            except Exception:
                pass
        if channel_name == "project_ui":
            project_id, project_path, project_name = _resolve_project_chat_identity(
                str(payload.get("project_id") or "").strip(),
                str(payload.get("project_root") or payload.get("working_directory") or "").strip(),
                str(payload.get("project_name") or "").strip(),
            )
            if project_id:
                payload["project_id"] = project_id
                if not payload.get("chat_id"):
                    payload["chat_id"] = project_id
            if project_path:
                if not payload.get("project_root"):
                    payload["project_root"] = project_path
                if not payload.get("working_directory"):
                    payload["working_directory"] = project_path
            if project_name and not payload.get("project_name"):
                payload["project_name"] = project_name

        _sync_channel_chat_context(
            payload,
            supplied_history=body.get("history") if isinstance(body.get("history"), list) else None,
            context_limit=body.get("context_limit"),
        )

        gateway_up = _gateway_ready(timeout=0.5)
        if not gateway_up and not project_build_mode:
            if channel_name == "project_ui":
                _persist_project_chat_user_request(payload, text)
                _persist_project_chat_result(
                    payload,
                    error="Gateway not running. Start it with: kendr gateway start",
                )
            self._json(503, {
                "error": "Gateway not running",
                "detail": "Start it with: kendr gateway start",
            })
            return
        if channel_name == "project_ui":
            _persist_project_chat_user_request(payload, text)
        run_id = str(body.get("run_id") or "").strip() or f"ui-{uuid.uuid4().hex[:8]}"
        payload["run_id"] = run_id
        payload["workflow_id"] = str(body.get("workflow_id") or "").strip() or run_id
        payload["attempt_id"] = str(body.get("attempt_id") or "").strip() or run_id
        payload["kill_switch_file"] = str(body.get("kill_switch_file") or "").strip() or _kill_switch_path_for_run(run_id)
        _clear_kill_switch_file(payload["kill_switch_file"])

        q: "queue.Queue[dict]" = queue.Queue()
        with _pending_lock:
            _run_event_queues[run_id] = q
            _pending_runs[run_id] = _pending_run_state(run_id, payload=payload, status="running")

        use_standalone = project_build_mode and (not gateway_up or bool(body.get("standalone")))
        if use_standalone:
            _start_standalone_run_background(run_id, payload)
        else:
            _start_run_background(run_id, payload)
        self._json(
            200,
            {
                "run_id": run_id,
                "workflow_id": str(payload.get("workflow_id") or run_id),
                "attempt_id": str(payload.get("attempt_id") or run_id),
                "streaming": True,
                "status": "started",
            },
        )

    def _handle_chat_compact(self, body: dict) -> None:
        channel = str(body.get("channel") or "webchat").strip().lower() or "webchat"
        payload = {
            "channel": channel,
            "sender_id": str(body.get("sender_id") or ("desktop_user" if channel == "webchat" else "ui_user")),
            "chat_id": str(body.get("chat_id") or body.get("project_id") or "").strip(),
            "workspace_id": str(body.get("workspace_id") or "").strip(),
        }
        if channel == "project_ui" and not payload["chat_id"]:
            payload["chat_id"] = str(body.get("project_id") or "").strip()
        if not payload["chat_id"]:
            self._json(400, {"error": "missing_chat_id"})
            return
        context = _sync_channel_chat_context(
            payload,
            supplied_history=body.get("history") if isinstance(body.get("history"), list) else None,
            context_limit=body.get("context_limit"),
            compact_increment=1,
        )
        self._json(200, {
            "ok": True,
            "chat_id": payload["chat_id"],
            "summary_file": context.get("summary_file", ""),
            "summary_tokens": int(context.get("summary_tokens", 0) or 0),
            "message_count": len(context.get("history") or []),
            "compaction_level": int(context.get("compaction_level", 0) or 0),
        })

    def _handle_chat_resume(self, body: dict) -> None:
        text = str(body.get("text") or body.get("message") or "").strip()
        if not text:
            self._json(400, {"error": "missing_text"})
            return
        requested_run_id = str(body.get("run_id") or "").strip()
        run_id = requested_run_id or f"ui-{uuid.uuid4().hex[:8]}"
        workflow_id = str(body.get("workflow_id") or "").strip() or run_id
        attempt_id = str(body.get("attempt_id") or "").strip() or run_id
        resume_dir = str(body.get("resume_dir") or body.get("working_directory") or os.getenv("KENDR_WORKING_DIR", "")).strip()
        resume_output_dir = str(body.get("output_folder") or body.get("resume_output_dir") or "").strip()
        run_row = None
        if requested_run_id:
            try:
                run_row = _db_get_run(requested_run_id)
            except Exception:
                run_row = None
            if isinstance(run_row, dict):
                # Preserve history: if client resumes using an existing run_id,
                # fork the continuation into a new run row.
                run_id = f"ui-{uuid.uuid4().hex[:8]}"
                if not str(body.get("workflow_id") or "").strip():
                    workflow_id = str(run_row.get("workflow_id") or requested_run_id).strip() or run_id
                if not str(body.get("attempt_id") or "").strip():
                    attempt_id = run_id
                resume_output_dir = (
                    resume_output_dir
                    or str(run_row.get("run_output_dir") or "").strip()
                    or str(run_row.get("resume_output_dir") or "").strip()
                )
                resume_dir = resume_dir or str(run_row.get("working_directory") or "").strip()
            if not resume_output_dir:
                resume_output_dir = _get_run_output_dir_from_manifest(requested_run_id)
        if not resume_dir and not resume_output_dir:
            self._json(400, {"error": "missing_resume_dir", "detail": "Provide resume_dir, output_folder, or working_directory."})
            return
        if not _gateway_ready(timeout=0.5):
            self._json(503, {"error": "Gateway not running", "detail": "Start it with: kendr gateway start"})
            return
        kill_switch_file = str(body.get("kill_switch_file") or "").strip() or _kill_switch_path_for_run(run_id)
        _clear_kill_switch_file(kill_switch_file)
        q: "queue.Queue[dict]" = queue.Queue()
        with _pending_lock:
            _run_event_queues[run_id] = q
            _pending_runs[run_id] = _pending_run_state(
                run_id,
                payload={
                    "text": text,
                    **body,
                    "working_directory": resume_dir,
                    "output_folder": resume_output_dir or resume_dir,
                    "resume_output_dir": resume_output_dir or resume_dir,
                    "workflow_id": workflow_id,
                    "attempt_id": attempt_id,
                    "kill_switch_file": kill_switch_file,
                },
                status="running",
            )

        def _run() -> None:
            _push_event(run_id, "status", {"status": "running", "message": "Continuing approved plan..."})
            _launch_step_stream_poller(run_id)
            heartbeat_stop = threading.Event()

            def _heartbeat() -> None:
                phases = (
                    "Loading paused checklist...",
                    "Running remaining checklist steps...",
                    "Wrapping up final answer...",
                )
                idx = 0
                while not heartbeat_stop.wait(12.0):
                    phase = phases[min(idx, len(phases) - 1)]
                    _push_event(run_id, "status", {"status": "running", "message": phase})
                    idx += 1

            heartbeat = threading.Thread(target=_heartbeat, daemon=True)
            heartbeat.start()
            try:
                resume_payload = {
                    "text": text,
                    "reply": text,
                    "working_directory": resume_dir,
                    "output_folder": resume_output_dir or resume_dir,
                    "resume_output_dir": resume_output_dir or resume_dir,
                    "channel": str(body.get("channel", "webchat")),
                    "sender_id": str(body.get("sender_id", "ui_user")),
                    "chat_id": str(body.get("chat_id", "")),
                    "run_id": run_id,
                    "workflow_id": workflow_id,
                    "attempt_id": attempt_id,
                    "kill_switch_file": kill_switch_file,
                }
                for key in ("force", "branch"):
                    if key in body:
                        resume_payload[key] = bool(body.get(key))
                for key in (
                    "provider", "model", "project_id", "project_root", "project_name", "workflow_type",
                    "execution_mode", "planner_mode", "auto_approve_plan",
                    "shell_auto_approve", "privileged_mode", "privileged_approved", "privileged_approval_note",
                    "privileged_approval_mode", "privileged_require_approvals", "privileged_read_only",
                    "privileged_allow_root", "privileged_allow_destructive", "privileged_enable_backup",
                    "privileged_allowed_paths", "privileged_allowed_domains",
                ):
                    value = body.get(key)
                    if value is not None and str(value).strip():
                        resume_payload[key] = value
                for key in ("security_authorized", "security_target_url", "security_authorization_note", "security_scan_profile"):
                    value = body.get(key)
                    if value is not None:
                        resume_payload[key] = value
                result = _gateway_resume(resume_payload)
                _run_status = _terminal_run_status(result=result, default="completed")
                _run_awaiting = _run_status == "awaiting_user_input"
                with _pending_lock:
                    _pending_runs[run_id] = _pending_run_state(run_id, payload=resume_payload, status=_run_status, result=result)
                _persist_channel_chat_turn(
                    resume_payload,
                    user_text=text,
                    assistant_text=_project_chat_result_text(result),
                    context_limit=body.get("context_limit"),
                )
                _push_event(run_id, "result", result)
                _push_event(run_id, "done", {"run_id": run_id, "status": _run_status, "awaiting_user_input": _run_awaiting})
            except urllib.error.HTTPError as exc:
                err_body = exc.read().decode("utf-8") if hasattr(exc, "read") else str(exc)
                try:
                    err_data = json.loads(err_body)
                    err_msg = err_data.get("error", "") or err_data.get("detail", "") or str(exc)
                except Exception:
                    err_msg = err_body or str(exc)
                run_status = _terminal_run_status(error=err_msg, default="failed")
                if run_status == "cancelled":
                    cancel_result = {
                        "run_id": run_id,
                        "workflow_id": workflow_id,
                        "attempt_id": attempt_id,
                        "workflow_type": str(resume_payload.get("workflow_type") or ""),
                        "working_directory": resume_dir,
                        "status": "cancelled",
                        "final_output": "Run stopped by user.",
                    }
                    with _pending_lock:
                        _pending_runs[run_id] = _pending_run_state(run_id, payload=resume_payload, status="cancelled", result=cancel_result)
                    _persist_channel_chat_turn(
                        resume_payload,
                        user_text=text,
                        assistant_text=_project_chat_result_text(cancel_result),
                        context_limit=body.get("context_limit"),
                    )
                    _push_event(run_id, "result", cancel_result)
                    _push_event(run_id, "done", {"run_id": run_id, "status": "cancelled", "awaiting_user_input": False})
                    return
                with _pending_lock:
                    _pending_runs[run_id] = _pending_run_state(run_id, payload=resume_payload, status="failed", error=err_msg)
                _persist_channel_chat_turn(
                    resume_payload,
                    user_text=text,
                    assistant_text="Error: " + str(err_msg),
                    context_limit=body.get("context_limit"),
                )
                _push_event(run_id, "error", {"message": err_msg})
                _push_event(run_id, "done", {"run_id": run_id, "status": "failed"})
            except Exception as exc:
                err = str(exc)
                with _pending_lock:
                    _pending_runs[run_id] = _pending_run_state(run_id, payload=resume_payload, status="failed", error=err)
                _persist_channel_chat_turn(
                    resume_payload,
                    user_text=text,
                    assistant_text="Error: " + err,
                    context_limit=body.get("context_limit"),
                )
                _push_event(run_id, "error", {"message": err})
                _push_event(run_id, "done", {"run_id": run_id, "status": "failed"})
            finally:
                heartbeat_stop.set()

        import threading as _threading
        t = _threading.Thread(target=_run, daemon=True)
        t.start()
        self._json(
            200,
            {
                "run_id": run_id,
                "workflow_id": workflow_id,
                "attempt_id": attempt_id,
                "streaming": True,
                "status": "started",
            },
        )

    def _handle_stop_run(self, body: dict) -> None:
        run_id = str(body.get("run_id") or "").strip()
        if not run_id:
            self._json(400, {"error": "missing_run_id"})
            return
        with _pending_lock:
            current = dict(_pending_runs.get(run_id, {})) if run_id in _pending_runs else {}
        if not current:
            self._json(404, {"error": "run_not_found", "run_id": run_id})
            return
        current_status = str(current.get("status") or "").strip().lower()
        if current_status in {"completed", "failed", "cancelled", "awaiting_user_input"}:
            self._json(409, {"error": "run_not_running", "run_id": run_id, "status": current_status})
            return
        payload = current.get("payload") if isinstance(current.get("payload"), dict) else {}
        kill_switch_file = str(payload.get("kill_switch_file") or _kill_switch_path_for_run(run_id)).strip()
        if not kill_switch_file:
            self._json(409, {"error": "stop_not_supported", "run_id": run_id})
            return
        _trigger_kill_switch_file(kill_switch_file)
        with _pending_lock:
            _pending_runs[run_id] = _pending_run_state(run_id, payload=payload, status="cancelling", result=current.get("result"), error="")
        _push_event(run_id, "status", {"status": "cancelling", "message": "Stopping run..."})
        self._json(200, {"ok": True, "run_id": run_id, "status": "cancelling"})

    def _handle_sse(self, run_id: str) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        def write_event(event_type: str, data: dict) -> bool:
            try:
                msg = f"event: {event_type}\ndata: {json.dumps(data)}\n\n"
                self.wfile.write(msg.encode("utf-8"))
                self.wfile.flush()
                return True
            except Exception:
                return False

        with _pending_lock:
            q = _run_event_queues.get(run_id)
            run_data = _pending_runs.get(run_id)

        if q is None and run_data:
            result_payload = dict(run_data.get("result", {})) if isinstance(run_data.get("result"), dict) else {}
            status_value = str(run_data.get("status", "") or result_payload.get("status", "")).strip().lower()
            awaiting = bool(
                run_data.get("awaiting_user_input")
                or result_payload.get("awaiting_user_input")
                or result_payload.get("plan_waiting_for_approval")
                or result_payload.get("plan_needs_clarification")
                or str(result_payload.get("approval_pending_scope", "")).strip()
                or (
                    isinstance(result_payload.get("approval_request"), dict)
                    and bool(result_payload.get("approval_request"))
                )
                or str(result_payload.get("pending_user_question", "")).strip()
                or str(result_payload.get("pending_user_input_kind", "")).strip()
                or status_value == "awaiting_user_input"
            )
            if awaiting and status_value != "awaiting_user_input":
                status_value = "awaiting_user_input"
            if result_payload:
                if status_value:
                    result_payload["status"] = status_value
                result_payload["awaiting_user_input"] = awaiting
            write_event("result", result_payload)
            write_event("done", {"run_id": run_id, "status": status_value or "completed", "awaiting_user_input": awaiting})
            return
        if q is None:
            write_event("error", {"message": "Run not found"})
            return

        write_event("status", {"status": "connected", "run_id": run_id})
        while True:
            try:
                event = q.get(timeout=1.0)
                if not write_event(event["type"], event["data"]):
                    break
                if event["type"] == "done":
                    with _pending_lock:
                        _run_event_queues.pop(run_id, None)
                    break
            except queue.Empty:
                if not write_event("ping", {"ts": int(time.time())}):
                    break

    def _handle_oauth_start(self, provider: str) -> None:
        if not _HAS_OAUTH:
            self._html(503, "<h1>OAuth not available</h1><p>kendr.providers module not loaded.</p>")
            return
        try:
            missing: list[str] = []
            if provider == "google":
                config = build_google_oauth_config()
                for k in ("client_id", "client_secret", "redirect_uri", "scopes"):
                    if not str(config.get(k, "")).strip():
                        missing.append({"client_id": "GOOGLE_CLIENT_ID", "client_secret": "GOOGLE_CLIENT_SECRET",
                                        "redirect_uri": "GOOGLE_REDIRECT_URI", "scopes": "GOOGLE_OAUTH_SCOPES"}.get(k, k))
            elif provider == "microsoft":
                config = build_microsoft_oauth_config()
                for k in ("client_id", "client_secret", "redirect_uri", "scopes"):
                    if not str(config.get(k, "")).strip():
                        missing.append({"client_id": "MICROSOFT_CLIENT_ID", "client_secret": "MICROSOFT_CLIENT_SECRET",
                                        "redirect_uri": "MICROSOFT_REDIRECT_URI", "scopes": "MICROSOFT_OAUTH_SCOPES"}.get(k, k))
            elif provider == "slack":
                config = build_slack_oauth_config()
                for k in ("client_id", "client_secret", "redirect_uri", "scopes"):
                    if not str(config.get(k, "")).strip():
                        missing.append({"client_id": "SLACK_CLIENT_ID", "client_secret": "SLACK_CLIENT_SECRET",
                                        "redirect_uri": "SLACK_REDIRECT_URI", "scopes": "SLACK_OAUTH_SCOPES"}.get(k, k))
            else:
                self._html(400, f"<h1>Unknown provider: {_html.escape(provider)}</h1>")
                return
            if missing:
                body_txt = (
                    f"<h1>{_html.escape(provider.title())} OAuth not configured</h1>"
                    "<p>Set the following environment variables before connecting:</p>"
                    f"<pre>{_html.escape(chr(10).join(missing))}</pre>"
                    '<p><a href="/setup">Return to Setup</a></p>'
                )
                self._html(400, body_txt)
                return
            state_token = issue_oauth_state_token()
            _OAUTH_PENDING_STATES[state_token] = provider
            if provider == "google":
                url = build_google_oauth_start_url(state_token)
            elif provider == "microsoft":
                url = build_microsoft_oauth_start_url(state_token)
            else:
                url = build_slack_oauth_start_url(state_token)
            self.send_response(302)
            self.send_header("Location", url)
            self.end_headers()
        except Exception as exc:
            self._html(500, f"<h1>OAuth error</h1><p>{_html.escape(str(exc))}</p>")

    def _handle_oauth_callback(self, provider: str, query: dict) -> None:
        if not _HAS_OAUTH:
            self._html(503, "<h1>OAuth not available</h1>")
            return
        state_token = (query.get("state") or [""])[0]
        code = (query.get("code") or [""])[0]
        error = (query.get("error") or [""])[0]
        if error:
            self._html(400, f"<h1>OAuth failed</h1><p>{_html.escape(error)}</p>")
            return
        if not code:
            self._html(400, "<h1>OAuth failed</h1><p>Missing authorization code.</p>")
            return
        if _OAUTH_PENDING_STATES.get(state_token) != provider:
            self._html(400, "<h1>OAuth failed</h1><p>Invalid or expired state token.</p>")
            return
        try:
            if provider == "google":
                exchange_google_oauth_code(code)
            elif provider == "microsoft":
                exchange_microsoft_oauth_code(code)
            elif provider == "slack":
                exchange_slack_oauth_code(code)
            else:
                self._html(400, f"<h1>Unknown provider: {_html.escape(provider)}</h1>")
                return
            _OAUTH_PENDING_STATES.pop(state_token, None)
            self._html(200, (
                f"<h1>{_html.escape(provider.title())} connected</h1>"
                "<p>Tokens saved to the kendr setup database.</p>"
                '<p><a href="/setup">Return to Setup</a></p>'
            ))
        except Exception as exc:
            self._html(500, f"<h1>OAuth failed</h1><p>{_html.escape(str(exc))}</p>")

    def _handle_models_set(self, body: dict) -> None:
        provider = str(body.get("provider", "")).strip().lower()
        model = str(body.get("model", "")).strip()
        if not provider:
            self._json(400, {"error": "missing_provider"})
            return
        try:
            from kendr.llm_router import get_model_for_provider, get_model_setting_env

            values: dict[str, str] = {"KENDR_LLM_PROVIDER": provider, "KENDR_MODEL": ""}
            model_env_key = get_model_setting_env(provider)
            if model and model_env_key:
                values[model_env_key] = model
            result = save_component_values("core_runtime", values)
            os.environ["KENDR_LLM_PROVIDER"] = provider
            os.environ.pop("KENDR_PROVIDER", None)
            os.environ.pop("KENDR_MODEL", None)
            if model and model_env_key:
                os.environ[model_env_key] = model
            apply_setup_env_defaults()
            effective_model = model or get_model_for_provider(provider)
            self._json(200, {"saved": True, "provider": provider, "model": effective_model})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_ollama_pull(self, body: dict) -> None:
        model_name = str(body.get("model", "")).strip()
        ok, payload, status = _start_ollama_pull_job(model_name)
        self._json(status, payload)

    def _handle_ollama_delete(self, body: dict) -> None:
        model_name = str(body.get("model", "")).strip()
        _ok, payload, status = _delete_ollama_model(model_name)
        self._json(status, payload)

    def _handle_ollama_pull_cancel(self) -> None:
        _ok, payload, status = _cancel_ollama_pull_job()
        self._json(status, payload)

    _OLLAMA_CONTAINER = "kendr-ollama"
    _OLLAMA_IMAGE = "ollama/ollama"

    def _docker_available(self) -> bool:
        import subprocess
        try:
            r = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
            return r.returncode == 0
        except Exception:
            return False

    def _ollama_container_info(self) -> dict:
        import subprocess, json as _json
        try:
            r = subprocess.run(
                ["docker", "inspect", self._OLLAMA_CONTAINER],
                capture_output=True, text=True, timeout=5,
            )
            if r.returncode != 0:
                return {"running": False, "docker_available": True}
            data = _json.loads(r.stdout)
            if not data:
                return {"running": False, "docker_available": True}
            c = data[0]
            running = c.get("State", {}).get("Running", False)
            env = c.get("Config", {}).get("Env", [])
            gpu = any("NVIDIA" in e or "gpu" in e.lower() for e in env)
            # also check HostConfig for GPU
            host_cfg = c.get("HostConfig", {})
            device_requests = host_cfg.get("DeviceRequests") or []
            if device_requests:
                gpu = True
            return {
                "running": running,
                "docker_available": True,
                "gpu": gpu,
                "name": self._OLLAMA_CONTAINER,
                "image": c.get("Config", {}).get("Image", self._OLLAMA_IMAGE),
            }
        except FileNotFoundError:
            return {"running": False, "docker_available": False}
        except Exception:
            return {"running": False, "docker_available": True}

    def _handle_ollama_docker_status(self) -> None:
        if not self._docker_available():
            self._json(200, {"running": False, "docker_available": False})
            return
        self._json(200, self._ollama_container_info())

    def _handle_ollama_docker_start(self, body: dict) -> None:
        import subprocess
        gpu = bool(body.get("gpu", False))
        if not self._docker_available():
            self._json(503, {"error": "Docker is not running or not installed"})
            return
        # Stop any existing container with the same name first
        subprocess.run(
            ["docker", "rm", "-f", self._OLLAMA_CONTAINER],
            capture_output=True, timeout=15,
        )
        cmd = ["docker", "run", "-d", "--name", self._OLLAMA_CONTAINER,
               "-p", "11434:11434",
               "-v", "ollama:/root/.ollama"]
        if gpu:
            cmd = ["docker", "run", "-d", "--gpus=all",
                   "--name", self._OLLAMA_CONTAINER,
                   "-p", "11434:11434",
                   "-v", "ollama:/root/.ollama"]
        cmd.append(self._OLLAMA_IMAGE)
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            if r.returncode == 0:
                self._json(200, {"ok": True, "gpu": gpu, "container": self._OLLAMA_CONTAINER})
            else:
                err = r.stderr.strip() or r.stdout.strip() or "Start failed"
                self._json(500, {"error": err})
        except subprocess.TimeoutExpired:
            self._json(500, {"error": "Docker start timed out — image may still be pulling"})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_ollama_docker_stop(self) -> None:
        import subprocess
        if not self._docker_available():
            self._json(503, {"error": "Docker is not running or not installed"})
            return
        try:
            subprocess.run(["docker", "stop", self._OLLAMA_CONTAINER],
                           capture_output=True, timeout=30)
            subprocess.run(["docker", "rm", self._OLLAMA_CONTAINER],
                           capture_output=True, timeout=15)
            self._json(200, {"ok": True})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_setup_save(self, body: dict) -> None:
        comp_id = str(body.get("component_id", "")).strip()
        values = body.get("values", {})
        if not comp_id:
            self._json(400, {"error": "missing_component_id"})
            return
        try:
            result = save_component_values(comp_id, values)
            apply_setup_env_defaults()
            safe_result = dict(result)
            safe_result.pop("raw_values", None)
            self._json(200, {"saved": True, "snapshot": safe_result})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_setup_enabled(self, body: dict) -> None:
        comp_id = str(body.get("component_id", "")).strip()
        enabled = bool(body.get("enabled", True))
        if not comp_id:
            self._json(400, {"error": "missing_component_id"})
            return
        try:
            set_component_enabled(comp_id, enabled)
            self._json(200, {"component_id": comp_id, "enabled": enabled})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_projects_list(self) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        try:
            self._json(200, _pm_list_projects())
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_project_active(self) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(404, {})
            return
        try:
            proj = _pm_get_active()
            self._json(200, proj or {})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_project_context_get(self) -> None:
        try:
            from kendr.project_context import (
                read_kendr_md, kendr_md_path, ensure_kendr_md, _detect_stack, _file_tree_lines
            )
            from pathlib import Path
            proj = _pm_get_active() if _HAS_PROJECT_MANAGER else None
            if not proj:
                self._json(200, {"project": None, "kendr_md": "", "kendr_md_exists": False})
                return
            root = str(proj.get("path", "")).strip()
            name = str(proj.get("name", "")).strip()
            if not root:
                self._json(200, {"project": proj, "kendr_md": "", "kendr_md_exists": False})
                return
            kpath = kendr_md_path(root)
            md = read_kendr_md(root)
            exists = kpath.exists()
            stack = _detect_stack(Path(root))
            tree_lines = _file_tree_lines(Path(root))[:80]
            self._json(200, {
                "project": proj,
                "kendr_md": md,
                "kendr_md_exists": exists,
                "kendr_md_path": str(kpath),
                "stack": stack,
                "file_tree": "\n".join(tree_lines),
            })
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_project_ask(self, body: dict) -> None:
        text = str(body.get("text") or "").strip()
        if not text:
            self._json(400, {"error": "missing_text"})
            return
        model_override = str(body.get("model") or "").strip() or None
        provider_override = str(body.get("provider") or "").strip() or None

        # ── SSE setup ─────────────────────────────────────────────────────────
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        def emit(event: str, data: dict) -> None:
            msg = "event: " + event + "\ndata: " + json.dumps(data) + "\n\n"
            try:
                self.wfile.write(msg.encode("utf-8"))
                self.wfile.flush()
            except Exception:
                pass

        proj_id = ""
        proj_root = ""
        proj_name = ""
        user_saved = False
        try:
            from kendr.llm_router import (
                build_llm, get_active_provider, get_model_for_provider, get_context_window
            )
            from langchain_core.messages import HumanMessage, SystemMessage

            proj = _pm_get_active() if _HAS_PROJECT_MANAGER else None
            proj_id = str(body.get("project_id") or (proj.get("id") if proj else "") or "").strip()
            proj_root = str(body.get("project_root") or (proj.get("path") if proj else "") or "").strip()
            if proj_root:
                proj_root = normalize_host_path_str(proj_root)
            proj_name = str(body.get("project_name") or (proj.get("name") if proj else "") or "").strip()
            if not proj_id and proj_root and _HAS_PROJECT_MANAGER:
                try:
                    matched = next(
                        (item for item in _pm_list_projects() if str(item.get("path") or "").strip() == proj_root),
                        None,
                    )
                    if matched:
                        proj_id = str(matched.get("id") or "").strip()
                        proj_name = proj_name or str(matched.get("name") or "").strip()
                except Exception:
                    pass

            if proj_id:
                try:
                    _append_project_chat_messages(
                        proj_id,
                        project_path=proj_root,
                        project_name=proj_name,
                        messages=[{
                            "role": "user",
                            "content": text,
                            "content_format": _project_chat_guess_format(text),
                        }],
                    )
                    user_saved = True
                except Exception as persist_exc:
                    _log.debug("Project chat history save failed for %s: %s", proj_id, persist_exc)

            activities: list[dict] = []
            task_title = f"Inspect {proj_name or 'the project'} and answer the question"

            emit("log", {"msg": "\U0001f4c1 Checking project directory...", "step": "init"})
            _emit_project_activity(
                emit,
                activities,
                kind="task",
                title="Project question received",
                status="running",
                detail=text,
                task=task_title,
                subtask="Initialize project-aware analysis",
                cwd=proj_root,
            )

            kendr_md = ""
            kendr_md_generated = False
            file_tree = ""
            git_status_text = ""
            service_lines = ""
            key_file_notes: list[str] = []
            if proj_root and os.path.isdir(proj_root):
                kpath = os.path.join(proj_root, "kendr.md")
                kendr_started = _utc_now_iso()
                if os.path.isfile(kpath):
                    emit("log", {"msg": "\U0001f4cb Reading kendr.md context file...", "step": "kendr_md"})
                    try:
                        with open(kpath, "r", encoding="utf-8", errors="replace") as f:
                            kendr_md = f.read()[:12000]
                        _emit_project_activity(
                            emit,
                            activities,
                            kind="file_read",
                            title="Loaded kendr.md",
                            status="completed",
                            detail=f"Loaded {len(kendr_md)} characters of persistent project context.",
                            cwd=proj_root,
                            task=task_title,
                            subtask="Load persistent project context",
                            started_at=kendr_started,
                            completed_at=_utc_now_iso(),
                            metadata={"path": kpath},
                        )
                        emit("log", {"msg": "\u2705 kendr.md loaded (" + str(len(kendr_md)) + " chars)", "step": "kendr_md_ok"})
                    except Exception as e:
                        _emit_project_activity(
                            emit,
                            activities,
                            kind="file_read",
                            title="kendr.md read failed",
                            status="failed",
                            detail=str(e),
                            cwd=proj_root,
                            task=task_title,
                            subtask="Load persistent project context",
                            started_at=kendr_started,
                            completed_at=_utc_now_iso(),
                            metadata={"path": kpath},
                        )
                        emit("log", {"msg": "\u26a0 Could not read kendr.md: " + str(e), "step": "kendr_md_err"})
                else:
                    emit("log", {"msg": "\U0001f527 kendr.md not found — generating project context...", "step": "kendr_md_gen"})
                    try:
                        from kendr.project_context import ensure_kendr_md
                        kendr_md = ensure_kendr_md(proj_root, proj_name)[:12000]
                        kendr_md_generated = True
                        _emit_project_activity(
                            emit,
                            activities,
                            kind="file_generate",
                            title="Generated kendr.md",
                            status="completed",
                            detail=f"Generated {len(kendr_md)} characters of structural project context.",
                            cwd=proj_root,
                            task=task_title,
                            subtask="Generate persistent project context",
                            started_at=kendr_started,
                            completed_at=_utc_now_iso(),
                            metadata={"path": kpath},
                        )
                        emit("log", {"msg": "\u2728 kendr.md created and loaded (" + str(len(kendr_md)) + " chars)", "step": "kendr_md_gen_ok"})
                    except Exception as e:
                        _emit_project_activity(
                            emit,
                            activities,
                            kind="file_generate",
                            title="kendr.md generation failed",
                            status="failed",
                            detail=str(e),
                            cwd=proj_root,
                            task=task_title,
                            subtask="Generate persistent project context",
                            started_at=kendr_started,
                            completed_at=_utc_now_iso(),
                            metadata={"path": kpath},
                        )
                        emit("log", {"msg": "\u26a0 Could not generate kendr.md: " + str(e), "step": "kendr_md_gen_err"})

                emit("log", {"msg": "\U0001f4c2 Inspecting project files...", "step": "file_tree"})
                is_git_repo = os.path.isdir(os.path.join(proj_root, ".git"))
                listing_command = _project_listing_command(is_git_repo)
                listing_result = _pm_shell(listing_command, proj_root, timeout=20) if _HAS_PROJECT_MANAGER else {}
                if listing_result.get("stdout"):
                    file_tree = str(listing_result.get("stdout") or "").strip()
                else:
                    try:
                        entries = sorted(os.listdir(proj_root))[:60]
                        file_tree = "\n".join(entries)
                    except Exception:
                        file_tree = ""
                _emit_project_activity(
                    emit,
                    activities,
                    kind="command" if listing_result else "filesystem",
                    title="Enumerated project files",
                    status="completed" if (not listing_result or listing_result.get("ok")) else "failed",
                    detail=(str(listing_result.get("stderr") or "") or f"Collected {len([line for line in file_tree.splitlines() if line.strip()])} file paths.")[:240],
                    command=str(listing_result.get("command") or listing_command if listing_result else ""),
                    cwd=proj_root,
                    task=task_title,
                    subtask="Enumerate candidate files",
                    started_at=str(listing_result.get("started_at") or _utc_now_iso()),
                    completed_at=str(listing_result.get("completed_at") or _utc_now_iso()),
                    duration_ms=listing_result.get("duration_ms"),
                    exit_code=listing_result.get("returncode"),
                )
                emit("log", {"msg": "\u2705 File inventory ready (" + str(len([line for line in file_tree.splitlines() if line.strip()])) + " entries)", "step": "file_tree_ok"})
                if is_git_repo and _HAS_PROJECT_MANAGER:
                    git_result = _pm_shell("git status --short --branch", proj_root, timeout=15)
                    git_status_text = str(git_result.get("stdout") or "").strip()
                    _emit_project_activity(
                        emit,
                        activities,
                        kind="command",
                        title="Checked git status",
                        status="completed" if git_result.get("ok") else "failed",
                        detail=(git_status_text or str(git_result.get("stderr") or "No git status output available."))[:240],
                        command=str(git_result.get("command") or "git status --short --branch"),
                        cwd=proj_root,
                        task=task_title,
                        subtask="Inspect repository state",
                        started_at=str(git_result.get("started_at") or _utc_now_iso()),
                        completed_at=str(git_result.get("completed_at") or _utc_now_iso()),
                        duration_ms=git_result.get("duration_ms"),
                        exit_code=git_result.get("returncode"),
                    )
                for candidate in ("README.md", "pyproject.toml", "package.json", "requirements.txt"):
                    candidate_path = os.path.join(proj_root, candidate)
                    if not os.path.isfile(candidate_path):
                        continue
                    read_started = _utc_now_iso()
                    read_result = _pm_read_file(candidate_path, proj_root) if _HAS_PROJECT_MANAGER else {"ok": False, "error": "Project manager unavailable"}
                    if read_result.get("ok"):
                        content = str(read_result.get("content") or "")
                        key_file_notes.append(f"=== {candidate} ===\n{content[:3000]}")
                        _emit_project_activity(
                            emit,
                            activities,
                            kind="file_read",
                            title=f"Read {candidate}",
                            status="completed",
                            detail=f"Loaded {len(content)} characters from {candidate}.",
                            cwd=proj_root,
                            task=task_title,
                            subtask="Read key project files",
                            started_at=read_started,
                            completed_at=_utc_now_iso(),
                            metadata={"path": candidate_path},
                        )
                    else:
                        _emit_project_activity(
                            emit,
                            activities,
                            kind="file_read",
                            title=f"Read {candidate} failed",
                            status="failed",
                            detail=str(read_result.get("error") or "Unknown read error"),
                            cwd=proj_root,
                            task=task_title,
                            subtask="Read key project files",
                            started_at=read_started,
                            completed_at=_utc_now_iso(),
                            metadata={"path": candidate_path},
                        )
                    if len(key_file_notes) >= 3:
                        break
                if proj and proj.get("id"):
                    try:
                        services = _pm_list_services(str(proj.get("id")), include_stopped=True)
                        if services:
                            lines = []
                            for service in services:
                                lines.append(
                                    "- "
                                    + str(service.get("name") or service.get("id") or "service")
                                    + " | "
                                    + str(service.get("kind") or "service")
                                    + " | "
                                    + str(service.get("status") or ("running" if service.get("running") else "stopped"))
                                    + " | port="
                                    + str(service.get("port") or "-")
                                    + " | url="
                                    + str(service.get("url") or "-")
                                    + " | cwd="
                                    + str(service.get("cwd") or "-")
                                )
                            service_lines = "\n".join(lines)
                            _emit_project_activity(
                                emit,
                                activities,
                                kind="service_scan",
                                title="Loaded tracked services",
                                status="completed",
                                detail=f"Loaded {len(services)} tracked services.",
                                cwd=proj_root,
                                task=task_title,
                                subtask="Inspect project services",
                            )
                            emit("log", {"msg": "\u2705 Loaded " + str(len(services)) + " tracked project services", "step": "services_ok"})
                    except Exception as e:
                        _emit_project_activity(
                            emit,
                            activities,
                            kind="service_scan",
                            title="Project services load failed",
                            status="failed",
                            detail=str(e),
                            cwd=proj_root,
                            task=task_title,
                            subtask="Inspect project services",
                        )
                        emit("log", {"msg": "\u26a0 Could not load project services: " + str(e), "step": "services_err"})

            llm_started = _utc_now_iso()
            llm_started_ts = time.time()
            _emit_project_activity(
                emit,
                activities,
                kind="analysis",
                title="Calling project analysis model",
                status="running",
                detail="Synthesizing command-based project observations into a direct answer.",
                started_at=llm_started,
                cwd=proj_root,
                actor="project_ask",
                task=task_title,
                subtask="Answer project question",
            )
            emit("log", {"msg": "\U0001f9e0 Building context and calling LLM...", "step": "llm"})

            system_ctx = "You are a knowledgeable assistant for the software project '" + (proj_name or "this project") + "'."
            if kendr_md:
                system_ctx += "\n\nProject context (kendr.md):\n" + kendr_md
            if file_tree:
                system_ctx += "\n\nProject root files:\n" + file_tree
            if git_status_text:
                system_ctx += "\n\nGit status:\n" + git_status_text
            if key_file_notes:
                system_ctx += "\n\nKey file excerpts:\n" + "\n\n".join(key_file_notes)
            if service_lines:
                system_ctx += "\n\nTracked project services:\n" + service_lines
            system_ctx += (
                "\n\nAnswer the user's question concisely and accurately. "
                "If asked about what the project is or does, summarise from the kendr.md context above. "
                "Ground the answer in the observed files, git state, and service status when relevant. "
                "Do NOT generate execution plans or project scaffolds - just answer the question."
            )

            provider = provider_override or get_active_provider()
            model = model_override or get_model_for_provider(provider)
            llm = build_llm(provider, model)

            ctx_chars = len(system_ctx) + len(text)
            ctx_tokens = ctx_chars // 4
            ctx_limit = get_context_window(model)

            messages = [SystemMessage(content=system_ctx), HumanMessage(content=text)]
            response = llm.invoke(messages)
            answer = response.content if hasattr(response, "content") else str(response)
            _emit_project_activity(
                emit,
                activities,
                kind="analysis",
                title="Project answer ready",
                status="completed",
                detail=f"Returned {len(answer or '')} characters from the project analysis model.",
                started_at=llm_started,
                completed_at=_utc_now_iso(),
                duration_ms=max(0, int((time.time() - llm_started_ts) * 1000)),
                cwd=proj_root,
                actor=model or provider or "project_ask",
                task=task_title,
                subtask="Answer project question",
            )

            if proj_id:
                try:
                    _append_project_chat_messages(
                        proj_id,
                        project_path=proj_root,
                        project_name=proj_name,
                        messages=[{
                            "role": "agent",
                            "content": answer,
                            "content_format": _project_chat_guess_format(answer),
                        }],
                    )
                except Exception as persist_exc:
                    _log.debug("Project chat history save failed for %s: %s", proj_id, persist_exc)

            emit("result", {
                "answer": answer,
                "model": model,
                "provider": provider,
                "context_tokens": ctx_tokens,
                "model_context_limit": ctx_limit,
                "context_pct": round(ctx_tokens / max(ctx_limit, 1) * 100, 1),
                "kendr_md_loaded": bool(kendr_md),
                "kendr_md_generated": kendr_md_generated,
                "activities": activities,
            })
            emit("done", {})
        except Exception as exc:
            if proj_id:
                try:
                    pending_messages = []
                    if not user_saved:
                        pending_messages.append({
                            "role": "user",
                            "content": text,
                            "content_format": _project_chat_guess_format(text),
                        })
                    pending_messages.append({
                        "role": "agent",
                        "content": "Error: " + str(exc),
                        "content_format": "text",
                    })
                    _append_project_chat_messages(
                        proj_id,
                        project_path=proj_root,
                        project_name=proj_name,
                        messages=pending_messages,
                    )
                except Exception as persist_exc:
                    _log.debug("Project chat history error save failed for %s: %s", proj_id, persist_exc)
            _emit_project_activity(
                emit,
                activities if 'activities' in locals() and isinstance(activities, list) else [],
                kind="analysis",
                title="Project ask failed",
                status="failed",
                detail=str(exc),
                completed_at=_utc_now_iso(),
                cwd=proj_root if 'proj_root' in locals() else "",
                actor="project_ask",
                task=task_title if 'task_title' in locals() else "Inspect project and answer the question",
                subtask="Answer project question",
            )
            emit("error", {"error": str(exc), "activities": activities if 'activities' in locals() and isinstance(activities, list) else []})
            emit("done", {})

    def _handle_simple_chat(self, body: dict) -> None:
        text = str(body.get("text") or body.get("message") or "").strip()
        if not text:
            self._json(400, {"error": "missing_text"})
            return

        stream = bool(body.get("stream"))
        if stream:
            run_id = str(body.get("run_id") or "").strip() or f"ui-{uuid.uuid4().hex[:8]}"
            payload = dict(body)
            payload["run_id"] = run_id
            payload["text"] = text
            q: "queue.Queue[dict]" = queue.Queue()
            with _pending_lock:
                _run_event_queues[run_id] = q
                _pending_runs[run_id] = _pending_run_state(run_id, payload=payload, status="running")
            _start_simple_chat_stream_background(run_id, payload)
            self._json(
                200,
                {
                    "run_id": run_id,
                    "streaming": True,
                    "status": "started",
                },
            )
            return

        model_override = str(body.get("model") or "").strip() or None
        provider_override = str(body.get("provider") or "").strip() or None
        local_paths = body.get("local_drive_paths") or []
        if not isinstance(local_paths, list):
            local_paths = []
        history = body.get("history") if isinstance(body.get("history"), list) else []
        payload = {
            "channel": str(body.get("channel") or "webchat"),
            "sender_id": str(body.get("sender_id") or "desktop_user"),
            "chat_id": str(body.get("chat_id") or ""),
            "workspace_id": str(body.get("workspace_id") or ""),
            "context_limit": body.get("context_limit"),
        }

        try:
            from kendr.llm_router import build_llm, get_active_provider, get_model_for_provider
            from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

            context = _sync_channel_chat_context(
                payload,
                supplied_history=history,
                context_limit=body.get("context_limit"),
            )
            provider = provider_override or get_active_provider()
            model = model_override or get_model_for_provider(provider)
            llm = build_llm(provider, model)

            attachment_notes: list[str] = []
            for raw_path in local_paths[:8]:
                candidate = normalize_host_path_str(str(raw_path or "").strip())
                if not candidate:
                    continue
                try:
                    if os.path.isfile(candidate):
                        with open(candidate, "r", encoding="utf-8", errors="replace") as fh:
                            excerpt = fh.read(2000)
                        attachment_notes.append(
                            f"=== Attached file: {os.path.basename(candidate)} ===\nPath: {candidate}\n{excerpt}"
                        )
                    elif os.path.isdir(candidate):
                        entries = sorted(os.listdir(candidate))[:40]
                        attachment_notes.append(
                            f"=== Attached folder: {os.path.basename(candidate)} ===\nPath: {candidate}\nEntries: {entries}"
                        )
                except Exception:
                    attachment_notes.append(f"Attached path: {candidate}")

            system_ctx = (
                "You are Kendr in simple chat mode. "
                "Answer directly and helpfully. "
                "Do not mention agents, orchestration, runs, artifacts, plans, or internal workflows. "
                "Only provide a plain assistant answer. "
                "If attached local files or folders are available, use their excerpts or path summaries when relevant."
            )
            if attachment_notes:
                system_ctx += "\n\nAttached local context:\n" + "\n\n".join(attachment_notes)
            summary_block = _build_chat_context_block(context.get("summary_text", ""), context.get("history", []))
            if summary_block:
                system_ctx += "\n\nChat continuity context:\n" + summary_block

            messages = [SystemMessage(content=system_ctx)]
            for item in (context.get("history") or [])[-14:]:
                if not isinstance(item, dict):
                    continue
                role = str(item.get("role") or "").strip().lower()
                content = str(item.get("content") or "").strip()
                if not content:
                    continue
                if role == "user":
                    messages.append(HumanMessage(content=content))
                elif role == "assistant":
                    messages.append(AIMessage(content=content))
            messages.append(HumanMessage(content=text))
            response = llm.invoke(messages)
            answer = response.content if hasattr(response, "content") else str(response)
            _persist_channel_chat_turn(
                payload,
                user_text=text,
                assistant_text=answer,
                context_limit=body.get("context_limit"),
            )
            self._json(200, {"answer": answer, "provider": provider, "model": model})
        except Exception as exc:
            _persist_channel_chat_turn(
                payload,
                user_text=text,
                assistant_text="Error: " + str(exc),
                context_limit=body.get("context_limit"),
            )
            self._json(500, {"error": str(exc)})

    def _handle_assistants_create(self, body: dict) -> None:
        name = str(body.get("name") or "").strip()
        if not name:
            self._json(400, {"error": "name is required"})
            return
        try:
            item = _db_create_assistant(
                workspace_id=_assistant_workspace_id(body=body),
                owner_user_id=str(body.get("owner_user_id") or "desktop_user").strip() or "desktop_user",
                name=name,
                description=str(body.get("description") or "").strip(),
                goal=str(body.get("goal") or "").strip(),
                system_prompt=str(body.get("system_prompt") or "").strip(),
                model_provider=str(body.get("model_provider") or "").strip(),
                model_name=str(body.get("model_name") or "").strip(),
                routing_policy=str(body.get("routing_policy") or "balanced").strip() or "balanced",
                status=str(body.get("status") or "draft").strip() or "draft",
                attached_capabilities=body.get("attached_capabilities") if isinstance(body.get("attached_capabilities"), list) else [],
                memory_config=body.get("memory_config") if isinstance(body.get("memory_config"), dict) else {},
                metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else {},
            )
            self._json(200, item)
        except Exception as exc:
            self._json(400, {"error": str(exc)})

    def _handle_assistants_update(self, assistant_id: str, body: dict) -> None:
        if not assistant_id:
            self._json(400, {"error": "missing_assistant_id"})
            return
        try:
            item = _db_update_assistant(
                assistant_id,
                name=str(body.get("name")).strip() if body.get("name") is not None else None,
                description=str(body.get("description")).strip() if body.get("description") is not None else None,
                goal=str(body.get("goal")).strip() if body.get("goal") is not None else None,
                system_prompt=str(body.get("system_prompt")).strip() if body.get("system_prompt") is not None else None,
                model_provider=str(body.get("model_provider")).strip() if body.get("model_provider") is not None else None,
                model_name=str(body.get("model_name")).strip() if body.get("model_name") is not None else None,
                routing_policy=str(body.get("routing_policy")).strip() if body.get("routing_policy") is not None else None,
                status=str(body.get("status")).strip() if body.get("status") is not None else None,
                attached_capabilities=body.get("attached_capabilities") if isinstance(body.get("attached_capabilities"), list) else None,
                memory_config=body.get("memory_config") if isinstance(body.get("memory_config"), dict) else None,
                metadata=body.get("metadata") if isinstance(body.get("metadata"), dict) else None,
            )
            if not item:
                self._json(404, {"error": "assistant_not_found"})
                return
            self._json(200, item)
        except Exception as exc:
            self._json(400, {"error": str(exc)})

    def _handle_assistants_delete(self, assistant_id: str) -> None:
        if not assistant_id:
            self._json(400, {"error": "missing_assistant_id"})
            return
        try:
            ok = _db_delete_assistant(assistant_id)
            if not ok:
                self._json(404, {"error": "assistant_not_found"})
                return
            self._json(200, {"ok": True, "assistant_id": assistant_id})
        except Exception as exc:
            self._json(400, {"error": str(exc)})

    def _handle_assistants_test(self, assistant_id: str, body: dict) -> None:
        assistant = _db_get_assistant(assistant_id)
        if not assistant:
            self._json(404, {"error": "assistant_not_found"})
            return

        message = str(body.get("message") or body.get("text") or "").strip()
        if not message:
            self._json(400, {"error": "message is required"})
            return

        model_override = str(body.get("model") or assistant.get("model_name") or "").strip() or None
        provider_override = str(body.get("provider") or assistant.get("model_provider") or "").strip() or None
        local_paths = _assistant_local_paths(assistant.get("memory_config"))

        try:
            from kendr.llm_router import build_llm, get_active_provider, get_model_for_provider
            from langchain_core.messages import HumanMessage, SystemMessage

            provider = provider_override or get_active_provider()
            model = model_override or get_model_for_provider(provider)
            llm = build_llm(provider, model)

            attachment_notes = _collect_local_attachment_notes(local_paths)
            system_ctx = _assistant_system_prompt(assistant)
            if attachment_notes:
                system_ctx += "\n\nAttached local context:\n" + "\n\n".join(attachment_notes)

            messages = [SystemMessage(content=system_ctx), HumanMessage(content=message)]
            response = llm.invoke(messages)
            answer = response.content if hasattr(response, "content") else str(response)
            _db_update_assistant(assistant_id, last_tested_at=_utc_now_iso())
            self._json(200, {
                "assistant_id": assistant_id,
                "answer": answer,
                "provider": provider,
                "model": model,
                "system_prompt_preview": system_ctx[:3000],
            })
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_project_context_generate(self, body: dict) -> None:
        try:
            from kendr.project_context import generate_kendr_md, write_kendr_md
            proj = _pm_get_active() if _HAS_PROJECT_MANAGER else None
            root = str((proj or {}).get("path", "") or body.get("project_root", "")).strip()
            if not root:
                self._json(400, {"error": "No active project"})
                return
            root = normalize_host_path_str(root)
            name = str((proj or {}).get("name", "") or body.get("project_name", "")).strip()
            extra_notes = str(body.get("notes", "")).strip()
            content = generate_kendr_md(root, name, extra_notes)
            write_kendr_md(root, content)
            self._json(200, {"ok": True, "kendr_md": content, "path": f"{root}/kendr.md"})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_project_context_update(self, body: dict) -> None:
        try:
            from kendr.project_context import write_kendr_md, read_kendr_md
            proj = _pm_get_active() if _HAS_PROJECT_MANAGER else None
            root = str((proj or {}).get("path", "") or body.get("project_root", "")).strip()
            if not root:
                self._json(400, {"error": "No active project"})
                return
            root = normalize_host_path_str(root)
            content = str(body.get("content", "")).strip()
            if not content:
                self._json(400, {"error": "content is required"})
                return
            write_kendr_md(root, content)
            self._json(200, {"ok": True, "kendr_md": content})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_project_add(self, body: dict) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        path = str(body.get("path", "")).strip()
        name = str(body.get("name", "")).strip()
        if not path:
            self._json(400, {"error": "path is required"})
            return
        try:
            entry = _pm_add_project(path, name)
            self._json(200, entry)
        except Exception as exc:
            self._json(400, {"error": str(exc)})

    def _handle_project_clone(self, body: dict) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        url = str(body.get("url", "")).strip()
        dest = str(body.get("dest", "")).strip()
        name = str(body.get("name", "")).strip()
        if not url or not dest:
            self._json(400, {"error": "url and dest are required"})
            return
        try:
            result = _pm_git_clone(url, dest, name)
            self._json(200, result)
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_project_new(self, body: dict) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        name = str(body.get("name", "")).strip()
        parent_dir = str(body.get("parent_dir", "")).strip()
        stack = str(body.get("stack", "")).strip()
        if not name:
            self._json(400, {"error": "name is required"})
            return
        try:
            entry = _pm_init_project(name, parent_dir, stack)
            self._json(200, entry)
        except Exception as exc:
            self._json(400, {"error": str(exc)})

    def _handle_project_delete_files(self, project_id: str) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        try:
            result = _pm_delete_files(project_id)
            self._json(200, result)
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_project_download(self, project_id: str, fmt: str) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        import io as _io
        import zipfile as _zipfile
        import tarfile as _tarfile
        entry = _pm_get_project(project_id)
        if not entry:
            self._json(404, {"error": "Project not found"})
            return
        project_path = entry.get("path", "")
        proj_name = entry.get("name", project_id)
        if not os.path.isdir(project_path):
            self._json(404, {"error": "Project directory not found on disk"})
            return
        valid_fmts = ("zip", "tar.gz", "tar.bz2", "tgz")
        if fmt not in valid_fmts:
            fmt = "zip"
        buf = _io.BytesIO()
        arcname_root = proj_name.replace(" ", "_")
        try:
            if fmt == "zip":
                with _zipfile.ZipFile(buf, "w", _zipfile.ZIP_DEFLATED) as zf:
                    for dirpath, dirnames, filenames in os.walk(project_path):
                        dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", "node_modules", ".venv", "venv")]
                        for fname in filenames:
                            full = os.path.join(dirpath, fname)
                            rel = os.path.relpath(full, project_path)
                            zf.write(full, os.path.join(arcname_root, rel))
                content_type = "application/zip"
                dl_name = arcname_root + ".zip"
            else:
                mode = "w:bz2" if fmt == "tar.bz2" else "w:gz"
                with _tarfile.open(fileobj=buf, mode=mode) as tf:
                    for dirpath, dirnames, filenames in os.walk(project_path):
                        dirnames[:] = [d for d in dirnames if d not in (".git", "__pycache__", "node_modules", ".venv", "venv")]
                        for fname in filenames:
                            full = os.path.join(dirpath, fname)
                            rel = os.path.relpath(full, project_path)
                            tf.add(full, arcname=os.path.join(arcname_root, rel))
                content_type = "application/x-bzip2" if fmt == "tar.bz2" else "application/gzip"
                ext = ".tar.bz2" if fmt == "tar.bz2" else ".tar.gz"
                dl_name = arcname_root + ext
        except Exception as exc:
            self._json(500, {"error": str(exc)})
            return
        data = buf.getvalue()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Content-Disposition", f'attachment; filename="{dl_name}"')
        self.end_headers()
        self.wfile.write(data)

    def _handle_project_activate(self, project_id: str) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        try:
            ok = _pm_set_active(project_id)
            self._json(200, {"ok": ok, "project_id": project_id})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_project_remove(self, project_id: str) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        try:
            removed = _pm_remove_project(project_id)
            self._json(200, {"removed": removed, "project_id": project_id})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_project_file_tree(self, project_id: str) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        try:
            import kendr.project_manager as _pm_mod
            projects = {p["id"]: p for p in _pm_mod.list_projects()}
            proj = projects.get(project_id)
            if not proj:
                self._json(404, {"error": "Project not found"})
                return
            tree = _pm_file_tree(proj["path"])
            self._json(200, tree)
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_project_read_file(self, file_path: str, project_root: str) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        if not file_path:
            self._json(400, {"error": "path is required"})
            return
        try:
            result = _pm_read_file(file_path, project_root)
            self._json(200, result)
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_project_shell(self, body: dict) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        command = str(body.get("command", "")).strip()
        cwd = str(body.get("cwd", "")).strip() or os.getcwd()
        if not command:
            self._json(400, {"error": "command is required"})
            return
        try:
            result = _pm_shell(command, cwd, timeout=30)
            self._json(200, result)
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_project_chat_history(self, project_id: str) -> None:
        project_id = str(project_id or "").strip()
        if not project_id:
            self._json(400, {"error": "project_id is required"})
            return
        try:
            history = _load_project_chat_history(project_id)
            project = _pm_get_project(project_id) if _HAS_PROJECT_MANAGER else None
            if project:
                history["project_path"] = history.get("project_path") or str(project.get("path") or "")
                history["project_name"] = history.get("project_name") or str(project.get("name") or "")
            user_turns = len([msg for msg in history.get("messages", []) if msg.get("role") == "user"])
            self._json(200, {
                **history,
                "message_count": len(history.get("messages", [])),
                "turn_count": user_turns,
            })
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_project_services_list(self, project_id: str) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        try:
            services = _pm_list_services(project_id, include_stopped=True)
            self._json(200, {"project_id": project_id, "services": services})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_project_service_start(self, project_id: str, body: dict) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        name = str(body.get("name", "")).strip()
        command = str(body.get("command", "")).strip()
        service_id = str(body.get("service_id", "")).strip()
        if not name and not service_id:
            self._json(400, {"error": "name or service_id is required"})
            return
        try:
            result = _pm_start_service(
                project_id,
                name=name,
                command=command,
                kind=str(body.get("kind", "")).strip(),
                cwd=str(body.get("cwd", "")).strip(),
                port=body.get("port"),
                health_url=str(body.get("health_url", "")).strip(),
                service_id=service_id,
            )
            self._json(200, result)
        except Exception as exc:
            self._json(400, {"error": str(exc)})

    def _handle_project_service_stop(self, project_id: str, service_id: str) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        try:
            result = _pm_stop_service(project_id, service_id)
            self._json(200, result)
        except Exception as exc:
            self._json(400, {"error": str(exc)})

    def _handle_project_service_restart(self, project_id: str, service_id: str) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        try:
            result = _pm_restart_service(project_id, service_id)
            self._json(200, result)
        except Exception as exc:
            self._json(400, {"error": str(exc)})

    def _handle_project_service_log(self, project_id: str, service_id: str) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        try:
            result = _pm_read_service_log(project_id, service_id)
            status = 200 if result.get("ok") else 404
            self._json(status, result)
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_project_git_status(self, project_id: str) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        try:
            import kendr.project_manager as _pm_mod
            projects = {p["id"]: p for p in _pm_mod.list_projects()}
            proj = projects.get(project_id)
            if not proj:
                self._json(404, {"error": "Project not found"})
                return
            status = _pm_git_status(proj["path"])
            self._json(200, status)
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_project_git_pull(self, project_id: str) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        try:
            import kendr.project_manager as _pm_mod
            projects = {p["id"]: p for p in _pm_mod.list_projects()}
            proj = projects.get(project_id)
            if not proj:
                self._json(404, {"error": "Project not found"})
                return
            result = _pm_git_pull(proj["path"])
            self._json(200, result)
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_project_git_push(self, project_id: str) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        try:
            import kendr.project_manager as _pm_mod
            projects = {p["id"]: p for p in _pm_mod.list_projects()}
            proj = projects.get(project_id)
            if not proj:
                self._json(404, {"error": "Project not found"})
                return
            result = _pm_git_push(proj["path"])
            self._json(200, result)
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_project_git_commit_push(self, project_id: str, body: dict) -> None:
        if not _HAS_PROJECT_MANAGER:
            self._json(503, {"error": "Project manager not available"})
            return
        message = str(body.get("message", "")).strip()
        if not message:
            self._json(400, {"error": "commit message is required"})
            return
        try:
            import kendr.project_manager as _pm_mod
            projects = {p["id"]: p for p in _pm_mod.list_projects()}
            proj = projects.get(project_id)
            if not proj:
                self._json(404, {"error": "Project not found"})
                return
            result = _pm_git_commit_push(proj["path"], message)
            self._json(200, result)
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_mcp_add(self, body: dict) -> None:
        if not _HAS_MCP_MANAGER:
            self._json(503, {"error": "MCP manager not available"})
            return
        try:
            entries = _normalize_mcp_add_payload(body)
        except ValueError as exc:
            self._json(400, {"error": str(exc)})
            return
        try:
            added_servers = []
            for item in entries:
                entry = _mcp_add_server(
                    item["name"],
                    item["connection"],
                    item["type"],
                    item["description"],
                    item["auth_token"],
                    item["enabled"],
                )
                server_id = entry["id"]
                if item["enabled"]:
                    result = _mcp_discover_tools(server_id)
                else:
                    result = {
                        "ok": True,
                        "error": None,
                        "tools": [],
                        "tool_count": 0,
                        "last_discovered": "",
                        "server_id": server_id,
                    }
                srv = _mcp_get_server(server_id) or {}
                if srv.get("auth_token"):
                    srv = dict(srv)
                    srv["auth_token"] = "****"
                added_servers.append({**result, "server": srv})
            primary = added_servers[0]
            result = {
                **primary,
                "added_count": len(added_servers),
                "added_servers": added_servers,
            }
            self._json(200, result)
            _gateway_refresh_mcp()
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_mcp_discover(self, server_id: str) -> None:
        if not _HAS_MCP_MANAGER:
            self._json(503, {"error": "MCP manager not available"})
            return
        server_id = server_id.strip().rstrip("/")
        if not server_id:
            self._json(400, {"error": "missing_server_id"})
            return
        try:
            result = _mcp_discover_tools(server_id)
            self._json(200, result)
            _gateway_refresh_mcp()
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_mcp_remove(self, server_id: str) -> None:
        if not _HAS_MCP_MANAGER:
            self._json(503, {"error": "MCP manager not available"})
            return
        server_id = server_id.strip().rstrip("/")
        try:
            from kendr.persistence.mcp_store import is_default_server as _is_default_mcp
            if _is_default_mcp(server_id):
                self._json(403, {"error": "Default MCP servers cannot be removed."})
                return
        except Exception:
            pass
        try:
            removed = _mcp_remove_server(server_id)
            self._json(200, {"removed": removed, "server_id": server_id})
            _gateway_refresh_mcp()
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_mcp_toggle(self, server_id: str, body: dict) -> None:
        if not _HAS_MCP_MANAGER:
            self._json(503, {"error": "MCP manager not available"})
            return
        server_id = server_id.strip().rstrip("/")
        enabled = bool(body.get("enabled", True))
        try:
            ok = _mcp_toggle_server(server_id, enabled)
            self._json(200, {"ok": ok, "server_id": server_id, "enabled": enabled})
            _gateway_refresh_mcp()
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_test_connection(self, comp_id: str) -> None:
        comp_id = comp_id.strip().rstrip("/")
        if comp_id == "github":
            try:
                from tasks.github_client import GitHubClient
                from tasks.setup_config_store import get_component_values
                stored = get_component_values("github", include_secrets=True)
                kv = {item["config_key"]: item["config_value"] for item in stored}
                token = str(kv.get("GITHUB_TOKEN") or "").strip()
                if not token or token == "********":
                    token = os.getenv("GITHUB_TOKEN", "")
                client = GitHubClient(token=token)
                result = client.test_connection()
                self._json(200, result)
            except Exception as exc:
                self._json(200, {"ok": False, "error": str(exc)})
        else:
            self._json(200, {"ok": False, "error": f"No connection test available for '{comp_id}'."})

    # ── RAG handler methods ────────────────────────────────────────────────
    def _rag_check(self) -> bool:
        if not _HAS_RAG:
            self._json(503, {"error": "RAG manager not available"})
            return False
        return True

    def _handle_rag_list_kbs(self) -> None:
        if not self._rag_check():
            return
        try:
            self._json(200, _rag_list_kbs())
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_rag_get_kb(self, kb_id: str) -> None:
        if not self._rag_check():
            return
        try:
            kb = _rag_get_kb(kb_id)
            if not kb:
                self._json(404, {"error": "KB not found"})
                return
            self._json(200, kb)
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_rag_list_sources(self, kb_id: str) -> None:
        if not self._rag_check():
            return
        try:
            kb = _rag_get_kb(kb_id)
            if not kb:
                self._json(404, {"error": "KB not found"})
                return
            self._json(200, kb.get("sources", []))
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_rag_kb_status(self, kb_id: str) -> None:
        if not self._rag_check():
            return
        try:
            self._json(200, _rag_kb_status(kb_id))
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_rag_index_status(self, kb_id: str) -> None:
        if not self._rag_check():
            return
        try:
            job = _rag_get_index_job(kb_id)
            self._json(200, job or {"status": "idle"})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_rag_list_agents(self) -> None:
        if not self._rag_check():
            return
        try:
            self._json(200, _rag_get_agents())
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_rag_create_kb(self, body: dict) -> None:
        if not self._rag_check():
            return
        name = str(body.get("name") or "").strip()
        if not name:
            self._json(400, {"error": "name is required"})
            return
        try:
            kb = _rag_create_kb(name, description=str(body.get("description") or ""))
            self._json(200, kb)
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_rag_add_source(self, kb_id: str, body: dict) -> None:
        if not self._rag_check():
            return
        source_type = str(body.get("type") or "").strip()
        if not source_type:
            self._json(400, {"error": "type is required"})
            return
        try:
            source = _rag_add_source(
                kb_id,
                source_type,
                label=str(body.get("label") or ""),
                path=str(body.get("path") or ""),
                url=str(body.get("url") or ""),
                db_url=str(body.get("db_url") or ""),
                recursive=bool(body.get("recursive", True)),
                max_files=int(body.get("max_files") or 300),
                max_pages=int(body.get("max_pages") or 20),
                extensions=str(body.get("extensions") or ""),
                tables=str(body.get("tables") or ""),
                schema=str(body.get("schema") or ""),
                same_domain=bool(body.get("same_domain", False)),
                onedrive_path=str(body.get("onedrive_path") or ""),
            )
            self._json(200, source)
        except Exception as exc:
            self._json(400, {"error": str(exc)})

    def _handle_rag_trigger_index(self, kb_id: str, body: dict) -> None:
        if not self._rag_check():
            return
        try:
            source_ids = body.get("source_ids") or None
            job = _rag_index_kb(kb_id, source_ids=source_ids)
            self._json(200, job)
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_rag_update_vector(self, kb_id: str, body: dict) -> None:
        if not self._rag_check():
            return
        try:
            kb = _rag_update_vector(kb_id, body)
            if not kb:
                self._json(404, {"error": "KB not found"})
                return
            self._json(200, {"ok": True, "vector_config": kb.get("vector_config", {})})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_rag_update_reranker(self, kb_id: str, body: dict) -> None:
        if not self._rag_check():
            return
        try:
            kb = _rag_update_reranker(kb_id, body)
            if not kb:
                self._json(404, {"error": "KB not found"})
                return
            self._json(200, {"ok": True, "reranker_config": kb.get("reranker_config", {})})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_rag_toggle_agent(self, kb_id: str, body: dict) -> None:
        if not self._rag_check():
            return
        agent = str(body.get("agent") or "").strip()
        enabled = bool(body.get("enabled", True))
        if not agent:
            self._json(400, {"error": "agent is required"})
            return
        try:
            kb = _rag_toggle_agent(kb_id, agent, enabled)
            if not kb:
                self._json(404, {"error": "KB not found"})
                return
            self._json(200, {"ok": True, "enabled_agents": kb.get("enabled_agents", [])})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_rag_activate(self, kb_id: str) -> None:
        if not self._rag_check():
            return
        try:
            _rag_set_active_kb(kb_id)
            self._json(200, {"ok": True, "active_kb_id": kb_id})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_rag_query(self, kb_id: str, body: dict, with_answer: bool) -> None:
        if not self._rag_check():
            return
        query = str(body.get("query") or "").strip()
        if not query:
            self._json(400, {"error": "query is required"})
            return
        top_k = int(body.get("top_k") or 0) or None
        try:
            if with_answer:
                result = _rag_generate_answer(kb_id, query, top_k=top_k or 8)
            else:
                result = _rag_query_kb(kb_id, query, top_k=top_k)
            self._json(200, result)
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _parse_multipart_form(self):
        try:
            return cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                    "CONTENT_LENGTH": self.headers.get("Content-Length", "0"),
                },
            )
        except Exception as exc:
            self._json(400, {"error": "invalid_multipart", "detail": str(exc)})
            return None

    @staticmethod
    def _multipart_items(form, name: str) -> list:
        if not form or name not in form:
            return []
        items = form[name]
        return items if isinstance(items, list) else [items]

    @staticmethod
    def _multipart_values(form, name: str) -> list[str]:
        values = []
        for item in KendrUIHandler._multipart_items(form, name):
            try:
                values.append(str(getattr(item, "value", "") or "").strip())
            except Exception:
                continue
        return values

    def _handle_rag_upload(self, body: dict) -> None:
        if not self._rag_check():
            return
        content_type = str(self.headers.get("Content-Type", "") or "")
        if not content_type.startswith("multipart/form-data"):
            self._json(400, {"error": "Use multipart/form-data POST to /api/rag/upload with fields: file, kb_id"})
            return
        form = self._parse_multipart_form()
        if form is None:
            return
        kb_id = (self._multipart_values(form, "kb_id") or [""])[0]
        file_items = self._multipart_items(form, "file")
        if not kb_id:
            self._json(400, {"error": "missing_kb_id"})
            return
        if not file_items:
            self._json(400, {"error": "missing_file"})
            return
        uploaded = []
        try:
            for item in file_items:
                filename = os.path.basename(str(getattr(item, "filename", "") or "").strip())
                data = item.file.read() if getattr(item, "file", None) else b""
                if not filename:
                    continue
                uploaded.append(_rag_upload_file(kb_id, filename, data))
        except Exception as exc:
            self._json(500, {"error": str(exc)})
            return
        self._json(200, {"ok": True, "uploaded": uploaded})

    def _handle_deep_research_upload(self) -> None:
        form = self._parse_multipart_form()
        if form is None:
            return
        chat_id = (self._multipart_values(form, "chat_id") or [""])[0] or "webchat"
        file_items = self._multipart_items(form, "files") or self._multipart_items(form, "file")
        relative_paths = self._multipart_values(form, "relative_path")
        if not file_items:
            self._json(400, {"error": "missing_files"})
            return
        files = []
        for item in file_items:
            filename = os.path.basename(str(getattr(item, "filename", "") or "").strip())
            if not filename:
                continue
            data = item.file.read() if getattr(item, "file", None) else b""
            files.append((filename, data))
        if not files:
            self._json(400, {"error": "missing_files"})
            return
        try:
            payload = _save_deep_research_upload_batch(
                chat_id=chat_id,
                files=files,
                relative_paths=relative_paths,
            )
        except Exception as exc:
            self._json(500, {"error": str(exc)})
            return
        self._json(200, {"ok": True, **payload})

    def _handle_rag_delete_kb(self, kb_id: str) -> None:
        if not self._rag_check():
            return
        try:
            ok = _rag_delete_kb(kb_id)
            self._json(200, {"ok": ok})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_rag_remove_source(self, kb_id: str, source_id: str) -> None:
        if not self._rag_check():
            return
        try:
            ok = __import__("kendr.rag_manager", fromlist=["remove_source"]).remove_source(kb_id, source_id)
            self._json(200, {"ok": ok})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        # RAG KB delete
        if path.startswith("/api/rag/kbs/"):
            rest = path[len("/api/rag/kbs/"):]
            parts = rest.split("/")
            if len(parts) == 1 and parts[0]:
                self._handle_rag_delete_kb(parts[0])
                return
            if len(parts) == 3 and parts[1] == "sources" and parts[2]:
                self._handle_rag_remove_source(parts[0], parts[2])
                return
        self._json(404, {"error": "not_found"})


def main() -> None:
    apply_setup_env_defaults()
    ui_log_path = _configure_ui_logging()
    try:
        cleaned = _db_cleanup_stale_runs(stale_minutes=20)
        if cleaned:
            import logging as _logging
            _logging.getLogger(__name__).info("[ui] Cleaned up %d stale run(s) on startup", cleaned)
    except Exception:
        pass
    host = os.getenv("KENDR_UI_HOST", _UI_HOST)
    port = int(os.getenv("KENDR_UI_PORT", str(_UI_PORT)))
    server = ThreadingHTTPServer((host, port), KendrUIHandler)
    _display_host = "localhost" if host in ("0.0.0.0", "") else host
    display_url = f"http://{_display_host}:{port}"
    print(f"Kendr UI running at {display_url}  (bound to {host}:{port})")
    print(f"  Chat:   {display_url}/")
    print(f"  Setup:  {display_url}/setup")
    print(f"  Runs:   {display_url}/runs")
    print(f"  Cap:    {display_url}/capabilities")
    print(f"  Projects: {display_url}/projects")
    print(f"  Gateway: {_gateway_url()} ({'online' if _gateway_ready(timeout=0.5) else 'offline — run: kendr gateway start'})")
    if ui_log_path:
        print(f"  Logs:   {ui_log_path}")
        _log.info("Kendr UI log file: %s", ui_log_path)
    _log.info("Kendr UI running at %s (bound to %s:%s)", display_url, host, port)
    server.serve_forever()


if __name__ == "__main__":
    main()
