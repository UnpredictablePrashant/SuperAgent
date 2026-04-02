from __future__ import annotations

import cgi
import html as _html
import json
import logging
import os
import queue
import re
import threading
import time
import traceback

import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from logging.handlers import RotatingFileHandler
from urllib.parse import parse_qs, urlparse

_log = logging.getLogger("kendr.ui")

from tasks.setup_config_store import (
    apply_setup_env_defaults,
    export_env_lines,
    get_setup_component_snapshot,
    save_component_values,
    set_component_enabled,
    setup_overview,
)

try:
    from kendr.persistence import (
        cleanup_stale_runs as _db_cleanup_stale_runs,
        delete_chat_session as _db_delete_chat_session,
        delete_run as _db_delete_run,
        get_channel_session as _db_get_channel_session,
        list_agent_executions_for_run as _list_run_steps,
        list_artifacts_for_run as _list_run_artifacts,
        list_run_messages as _db_list_run_messages,
        get_run as _db_get_run,
        upsert_channel_session as _db_upsert_channel_session,
    )
    _HAS_PERSISTENCE = True
except Exception:
    _HAS_PERSISTENCE = False
    def _db_cleanup_stale_runs(**kw):  # type: ignore[misc]
        return 0
    def _db_delete_chat_session(chat_session_id, **kw):  # type: ignore[misc]
        return {"deleted_runs": [], "deleted_dirs": [], "errors": []}
    def _db_delete_run(run_id, **kw):  # type: ignore[misc]
        return {"ok": True, "deleted_run": run_id, "errors": []}
    def _db_get_channel_session(session_key, **kw):  # type: ignore[misc]
        return None
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


def _resolve_run_artifact_path(run_id: str, name: str) -> str:
    file_path = ""
    try:
        run_row = _db_get_run(run_id)
        output_dir = run_row.get("run_output_dir", "") if run_row else ""
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
    with urllib.request.urlopen(req, timeout=360) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _gateway_resume(payload: dict) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        f"{_gateway_url()}/resume",
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=360) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _gateway_get(path: str, timeout: float = 5.0) -> dict | list:
    req = urllib.request.Request(f"{_gateway_url()}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
_OAUTH_PENDING_STATES: dict[str, str] = {}


def _push_event(run_id: str, event_type: str, data: dict) -> None:
    with _pending_lock:
        q = _run_event_queues.get(run_id)
    if q is not None:
        q.put({"type": event_type, "data": data})


def _format_step(step: dict) -> dict:
    excerpt = str(step.get("output_excerpt") or "").strip()
    reason = str(step.get("reason") or "").strip()
    agent = step.get("agent_name", "agent")
    return {
        "agent": agent,
        "status": step.get("status", "running"),
        "message": excerpt or (f"Running {agent}..." if not reason else ""),
        "reason": reason,
        "execution_id": step.get("execution_id"),
    }


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
    def _poll_db_steps() -> None:
        seen: set = set()
        while True:
            with _pending_lock:
                current = _pending_runs.get(run_id, {})
            done = current.get("status") in ("completed", "failed")
            try:
                for step in _list_run_steps(run_id):
                    eid = step.get("execution_id")
                    if eid and eid not in seen:
                        seen.add(eid)
                        _push_event(run_id, "step", _format_step(step))
            except Exception as _step_exc:
                _log.debug("Step poll error for run %s: %s", run_id, _step_exc)
            if done:
                break
            time.sleep(0.6)

    def _run() -> None:
        _push_event(run_id, "status", {"status": "running", "message": "Agents mobilizing..."})
        poll = threading.Thread(target=_poll_db_steps, daemon=True)
        poll.start()
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
            _run_awaiting = bool(
                result.get("awaiting_user_input")
                or result.get("plan_waiting_for_approval")
                or result.get("plan_needs_clarification")
                or str(result.get("pending_user_input_kind", "")).strip()
            )
            _run_status = "awaiting_user_input" if _run_awaiting else "completed"
            with _pending_lock:
                _pending_runs[run_id] = {"status": _run_status, "result": result}
            _push_event(run_id, "result", result)
            _push_event(run_id, "done", {"run_id": run_id, "status": _run_status, "awaiting_user_input": _run_awaiting})
        except urllib.error.URLError as exc:
            err = str(exc)
            with _pending_lock:
                _pending_runs[run_id] = {"status": "failed", "error": err}
            _push_event(run_id, "error", {"message": err})
            _push_event(run_id, "done", {"run_id": run_id, "status": "failed"})
        except Exception as exc:
            err = traceback.format_exc()
            with _pending_lock:
                _pending_runs[run_id] = {"status": "failed", "error": err}
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
                _pending_runs[run_id] = {"status": "completed", "result": result}
            _push_event(run_id, "result", result)
            _push_event(run_id, "done", {"run_id": run_id, "status": "completed"})
        except Exception as exc:
            err = str(exc)
            with _pending_lock:
                _pending_runs[run_id] = {"status": "failed", "error": err}
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
  --text: #e6edf3; --muted: #7d8590; --sidebar-w: 280px;
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: "Segoe UI", system-ui, -apple-system, sans-serif; background: var(--bg); color: var(--text); height: 100vh; display: flex; overflow: hidden; }
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
.chat-main { flex: 1; display: flex; flex-direction: column; overflow: hidden; background: var(--bg); }
.chat-header { padding: 16px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; background: var(--surface); }
.chat-title { font-size: 15px; font-weight: 600; color: var(--text); }
.chat-subtitle { font-size: 12px; color: var(--muted); }
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
.messages { flex: 1; overflow-y: auto; padding: 24px; display: flex; flex-direction: column; gap: 16px; scroll-behavior: smooth; }
.message-row { display: flex; gap: 12px; max-width: 900px; }
.message-row.user { flex-direction: row-reverse; margin-left: auto; }
.message-row.user .bubble { background: rgba(83,82,237,0.2); border-color: rgba(83,82,237,0.4); border-radius: 18px 4px 18px 18px; }
.avatar { width: 36px; height: 36px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 16px; flex-shrink: 0; }
.avatar.kendr { background: rgba(0,201,167,0.15); border: 1px solid rgba(0,201,167,0.3); }
.avatar.user { background: rgba(83,82,237,0.2); border: 1px solid rgba(83,82,237,0.3); }
.bubble { padding: 14px 18px; border-radius: 4px 18px 18px 18px; border: 1px solid var(--border); background: var(--surface); max-width: 680px; font-size: 14px; line-height: 1.65; }
.bubble-meta { font-size: 11px; color: var(--muted); margin-top: 8px; }
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
.input-area { padding: 16px 24px 20px; border-top: 1px solid var(--border); background: var(--surface); }
.mode-row { display:flex; gap:8px; flex-wrap:wrap; margin-bottom:12px; }
.mode-pill { border:1px solid var(--border); background:var(--bg); color:var(--muted); border-radius:999px; padding:7px 12px; font-size:12px; font-weight:600; cursor:pointer; transition:all .15s; }
.mode-pill:hover { border-color: var(--teal); color: var(--teal); }
.mode-pill.active { background: rgba(0,201,167,0.12); border-color: rgba(0,201,167,0.45); color: var(--teal); }
.deep-research-panel { display:none; margin-bottom:12px; padding:14px; border:1px solid rgba(0,201,167,0.18); border-radius:12px; background:linear-gradient(180deg, rgba(0,201,167,0.06), rgba(83,82,237,0.05)); }
.deep-research-panel.visible { display:block; }
.dr-head { display:flex; justify-content:space-between; gap:12px; align-items:flex-start; margin-bottom:10px; }
.dr-title { font-size:12px; font-weight:700; color:var(--teal); letter-spacing:.08em; text-transform:uppercase; }
.dr-subtitle { font-size:12px; color:var(--muted); line-height:1.5; max-width:620px; }
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
.input-row { display: flex; gap: 12px; align-items: flex-end; }
.input-box { flex: 1; background: var(--bg); border: 1px solid var(--border); border-radius: 14px; padding: 14px 18px; color: var(--text); font-size: 14px; font-family: inherit; resize: none; min-height: 52px; max-height: 200px; overflow-y: auto; line-height: 1.5; transition: border-color 0.15s; outline: none; }
.input-box:focus { border-color: var(--teal); }
.input-box::placeholder { color: var(--muted); }
.send-btn { width: 48px; height: 48px; border-radius: 12px; background: var(--teal); border: none; cursor: pointer; display: flex; align-items: center; justify-content: center; font-size: 18px; flex-shrink: 0; transition: background 0.15s, opacity 0.15s; color: #0d0f14; }
.send-btn:hover { background: #00b396; }
.send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.input-hint { font-size: 11px; color: var(--muted); margin-top: 8px; }
::-webkit-scrollbar { width: 6px; }
::-webkit-scrollbar-track { background: transparent; }
::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
.error-banner { background: rgba(255,71,87,0.1); border: 1px solid rgba(255,71,87,0.3); color: var(--crimson); border-radius: 8px; padding: 10px 14px; font-size: 13px; display: flex; gap: 8px; align-items: flex-start; }
.streaming-status { font-size: 11px; color: var(--amber); margin-top: 4px; font-style: italic; }
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
    <a href="/mcp" class="nav-btn"><span class="icon">🧩</span> MCP Servers</a>
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
  <div class="sidebar-section">Recent Runs</div>
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
  <div class="messages" id="messages">
    <div class="welcome" id="welcome">
      <div class="welcome-logo">&#x26A1;</div>
      <h2>What would you like to research or build?</h2>
      <p>Kendr orchestrates specialized AI agents to research, generate code, deploy applications, analyze data, and automate complex workflows &#x2014; all from a single query.</p>
      <div class="suggestions">
        <div class="suggest-chip" onclick="fillInput('Create a competitive intelligence brief on Stripe')">&#x1F4CA; Stripe competitive brief</div>
        <div class="suggest-chip" onclick="fillInput('Build a FastAPI REST API with JWT authentication and PostgreSQL')">&#x1F3D7;&#xFE0F; FastAPI + JWT + PostgreSQL</div>
        <div class="suggest-chip" onclick="fillInput('Write API tests for https://jsonplaceholder.typicode.com')">&#x1F9EA; API test generation</div>
        <div class="suggest-chip" onclick="fillInput('Summarize my unread emails and Slack messages from today')">&#x1F4EC; Communications digest</div>
        <div class="suggest-chip" onclick="fillInput('Dockerize a Node.js app and write a docker-compose.yml')">&#x1F433; Dockerize + compose</div>
        <div class="suggest-chip" onclick="fillInput('Deploy a React app to AWS S3 and CloudFront')">&#x2601;&#xFE0F; Deploy to AWS</div>
      </div>
    </div>
  </div>
  <div class="input-area">
    <div class="mode-row">
      <button class="mode-pill active" id="modeAutoBtn" onclick="setResearchMode('auto')">Auto</button>
      <button class="mode-pill" id="modeDeepResearchBtn" onclick="setResearchMode('deep_research')">Deep Research</button>
    </div>
    <div class="deep-research-panel" id="deepResearchPanel">
      <div class="dr-head">
        <div>
          <div class="dr-title">Deep Research Mode</div>
          <div class="dr-subtitle">Tiered research flow with planning, sectioned writing, citations, plagiarism reporting, and multi-format exports.</div>
        </div>
      </div>
      <div class="dr-grid">
        <div class="dr-field">
          <label for="drPages">Page Target</label>
          <select id="drPages" class="dr-select">
            <option value="10">10 pages</option>
            <option value="25">25 pages</option>
            <option value="50" selected>50 pages</option>
            <option value="100">100 pages</option>
            <option value="150">150 pages</option>
            <option value="200">200 pages</option>
          </select>
        </div>
        <div class="dr-field">
          <label for="drCitation">Citation Style</label>
          <select id="drCitation" class="dr-select">
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
          <select id="drDateRange" class="dr-select">
            <option value="all_time" selected>All time</option>
            <option value="1y">Last year</option>
            <option value="2y">Last 2 years</option>
            <option value="5y">Last 5 years</option>
          </select>
        </div>
        <div class="dr-field">
          <label for="drMaxSources">Max Sources</label>
          <input id="drMaxSources" class="dr-input" type="number" min="0" step="10" value="0" placeholder="0 = tier default">
        </div>
      </div>
      <div class="dr-grid" style="margin-top:10px">
        <div class="dr-field">
          <label>Output Formats</label>
          <div class="dr-checks">
            <label class="dr-check"><input type="checkbox" value="pdf" class="dr-format" checked> PDF</label>
            <label class="dr-check"><input type="checkbox" value="docx" class="dr-format" checked> DOCX</label>
            <label class="dr-check"><input type="checkbox" value="html" class="dr-format" checked> HTML</label>
            <label class="dr-check"><input type="checkbox" value="md" class="dr-format" checked> Markdown</label>
          </div>
        </div>
        <div class="dr-field">
          <label>Source Families</label>
          <div class="dr-checks">
            <label class="dr-check"><input type="checkbox" id="drWebSearch" checked onchange="toggleDeepResearchWebSearch()"> Web Search</label>
            <label class="dr-check"><input type="checkbox" value="web" class="dr-source dr-remote-source" checked> Web</label>
            <label class="dr-check"><input type="checkbox" value="arxiv" class="dr-source dr-remote-source"> Academic</label>
            <label class="dr-check"><input type="checkbox" value="patents" class="dr-source dr-remote-source"> Patents</label>
            <label class="dr-check"><input type="checkbox" value="news" class="dr-source dr-remote-source"> News</label>
            <label class="dr-check"><input type="checkbox" value="reddit" class="dr-source dr-remote-source"> Community</label>
          </div>
          <div class="dr-note" id="drWebModeNote">Web search and explicit links are enabled. Disable this to restrict the report to local files/folders only.</div>
        </div>
        <div class="dr-field">
          <label>Quality Gates</label>
          <div class="dr-checks">
            <label class="dr-check"><input type="checkbox" id="drPlagiarism" checked> Plagiarism Check</label>
            <label class="dr-check"><input type="checkbox" id="drCheckpoint"> Checkpointing</label>
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
    <div class="input-row">
      <textarea class="input-box" id="userInput" placeholder="Ask kendr anything &#x2014; research, code, deploy, analyze..." rows="1" onkeydown="handleKey(event)" oninput="autoResize(this)"></textarea>
      <button class="send-btn" id="sendBtn" onclick="sendMessage()" title="Send (Enter)">&#x27A4;</button>
    </div>
    <div class="input-hint">Enter to send &#xB7; Shift+Enter for new line &#xB7; Gateway auto-starts if not running</div>
    <div class="shell-mode-banner" id="shellModeBanner">&#x26A0;&#xFE0F; Shell Automation is ON &#x2014; agents may install tools and run commands on this machine</div>
  </div>
</div>
<script>
const API = '';
let currentRunId = null;
let isRunning = false;
let isAwaitingInput = false;
let gatewayOnline = false;
let workingDir = '';
let activeEvtSource = null;
let _loadRunToken = 0;
let shellModeActive = false;
let researchMode = 'auto';
let deepResearchUploadedRoots = [];
let deepResearchLocalPaths = [];

function setResearchMode(mode) {
  researchMode = mode || 'auto';
  const autoBtn = document.getElementById('modeAutoBtn');
  const drBtn = document.getElementById('modeDeepResearchBtn');
  const panel = document.getElementById('deepResearchPanel');
  if (autoBtn) autoBtn.classList.toggle('active', researchMode === 'auto');
  if (drBtn) drBtn.classList.toggle('active', researchMode === 'deep_research');
  if (panel) panel.classList.toggle('visible', researchMode === 'deep_research');
  const input = document.getElementById('userInput');
  if (!input) return;
  input.placeholder = researchMode === 'deep_research'
    ? 'Describe the deep research task, scope, and output you want...'
    : 'Ask kendr anything — research, code, deploy, analyze...';
  if (researchMode === 'deep_research') {
    toggleDeepResearchWebSearch();
    renderDeepResearchSourceSummary();
  }
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
}

function addDeepResearchLocalPath() {
  const input = document.getElementById('drLocalPathInput');
  const value = (input && input.value || '').trim();
  if (!value) return;
  deepResearchLocalPaths.push(value);
  deepResearchLocalPaths = Array.from(new Set(deepResearchLocalPaths));
  if (input) input.value = '';
  renderDeepResearchSourceSummary();
}

function removeDeepResearchLocalPath(value) {
  deepResearchLocalPaths = deepResearchLocalPaths.filter(item => item !== value);
  deepResearchUploadedRoots = deepResearchUploadedRoots.filter(item => item !== value);
  renderDeepResearchSourceSummary();
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
    // Update welcome message if we have a project
    const welcomeEl = document.getElementById('welcome');
    if (welcomeEl && proj.name) {
      const h2 = welcomeEl.querySelector('h2');
      if (h2 && !h2.dataset.customized) {
        h2.textContent = 'Working on: ' + proj.name;
        h2.dataset.customized = '1';
      }
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

function _showAwaitingBanner() {
  if (document.getElementById('awaiting-input-banner')) return;
  const msgs = document.getElementById('messages');
  if (!msgs) return;
  const banner = document.createElement('div');
  banner.id = 'awaiting-input-banner';
  banner.style.cssText = 'margin:8px 0 4px 52px;padding:10px 14px;background:rgba(83,82,237,0.1);border:1px solid rgba(83,82,237,0.3);border-radius:8px;font-size:13px;color:var(--text)';
  banner.innerHTML = '<span style="color:#8b8af0;font-weight:600">&#x23F3; Awaiting your input</span> &mdash; type your response below to continue this run.';
  msgs.appendChild(banner);
  scrollDown();
  const inp = document.getElementById('userInput');
  if (inp) inp.placeholder = 'Type your response to continue\u2026';
}

function _removeAwaitingBanner() {
  const b = document.getElementById('awaiting-input-banner');
  if (b) b.remove();
  const inp = document.getElementById('userInput');
  if (inp) inp.placeholder = researchMode === 'deep_research'
    ? 'Describe the deep research task, scope, and output you want...'
    : 'Ask kendr anything \u2014 research, code, deploy, analyze\u2026';
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

async function loadRuns() {
  try {
    const r = await fetch(API + '/api/runs');
    if (!r.ok) return;
    const runs = await r.json();
    const list = document.getElementById('runList');
    list.innerHTML = '';
    if (!runs || !runs.length) {
      list.innerHTML = '<div style="padding:12px 10px;font-size:12px;color:var(--muted)">No runs yet. Start a chat to begin.</div>';
      return;
    }
    const chatRuns = (runs || []).filter(r => !(r.session_id || '').includes('project_ui'));
    if (!chatRuns.length) {
      list.innerHTML = '<div style="padding:12px 10px;font-size:12px;color:var(--muted)">No chat history yet.</div>';
      return;
    }
    chatRuns.slice(0, 30).forEach(run => {
      const div = document.createElement('div');
      const status = (run.status || 'completed').toLowerCase();
      const isActive = run.run_id === currentRunId;
      const isRunning = status === 'running' || status === 'started';
      div.className = 'run-item' + (isActive ? ' active' : '');
      const rawText = run.user_query || run.query || run.text || '';
      const title = rawText.trim().split('\n')[0].substring(0, 70) || 'Untitled run';
      const ts = _relTime(run.started_at || run.updated_at || run.created_at);
      const statusColor = isRunning ? 'var(--teal)' : status === 'failed' ? '#ef4444' : '#6b7280';
      const statusDot = isRunning
        ? '<span class="spinner" style="width:10px;height:10px;display:inline-block;flex-shrink:0"></span>'
        : '<span style="width:8px;height:8px;border-radius:50%;display:inline-block;flex-shrink:0;background:' + statusColor + '"></span>';
      const statusLabel = isRunning ? 'running' : status;
      const wdLabel = run.working_directory ? '<span style="color:var(--muted);font-size:10px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:120px" title="' + esc(run.working_directory) + '">&#x1F4C1; ' + esc(run.working_directory.split('/').pop()) + '</span>' : '';
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
        + '<div class="run-item-title" style="flex:1;font-size:12px;font-weight:' + (isRunning ? '600' : '500') + ';color:' + (isRunning ? 'var(--teal)' : '#ccc') + '">' + esc(title) + '</div></div>'
        + '<div class="run-item-meta" style="display:flex;justify-content:space-between;align-items:center">'
        + '<span style="font-size:10px;color:var(--muted);text-transform:uppercase;letter-spacing:.03em">' + statusLabel + '</span>'
        + '<span style="font-size:10px;color:var(--muted)">' + ts + '</span>'
        + '</div>'
        + (wdLabel ? '<div style="margin-top:2px">' + wdLabel + '</div>' : '');
      div.appendChild(delBtn);
      div.onmouseenter = () => delBtn.style.display = 'inline';
      div.onmouseleave = () => delBtn.style.display = 'none';
      div.onclick = () => loadRun(run.run_id);
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
  document.getElementById('userInput').focus();
}

async function loadRun(runId) {
  if (activeEvtSource) { activeEvtSource.close(); activeEvtSource = null; }
  stopPlanPolling();
  isRunning = false;
  isAwaitingInput = false;
  _pendingResumeDir = null;
  _removeAwaitingBanner();
  document.getElementById('sendBtn').disabled = false;
  currentRunId = runId;
  const myToken = ++_loadRunToken;
  loadRuns();

  const msgs = document.getElementById('messages');
  msgs.innerHTML = '<div style="display:flex;align-items:center;gap:8px;color:var(--muted);font-size:13px;padding:20px"><span class="spinner"></span> Loading run...</div>';

  try {
    const r = await fetch(API + '/api/runs/' + runId);
    const d = await r.json();
    if (_loadRunToken !== myToken) return;
    const query = d.user_query || d.query || d.text || '';
    const output = d.final_output || d.output || d.draft_response || '';
    const status = (d.status || 'completed').toLowerCase();
    const lastAgent = d.last_agent || '';
    const createdAt = d.created_at ? new Date(d.created_at).toLocaleString() : '';
    const completedAt = d.completed_at ? new Date(d.completed_at).toLocaleString() : '';

    clearMessages();
    if (query) {
      appendUserMsg(query);
      document.getElementById('chatTitle').textContent = query.substring(0, 50) + (query.length > 50 ? '...' : '');
    }

    if (output) {
      appendKendrMsg(output, runId);
    } else if (!query) {
      msgs.innerHTML = '<div style="color:var(--muted);font-size:13px;padding:20px;text-align:center">No content found for this run.</div>';
      document.getElementById('clearChatBtn').style.display = 'none';
      return;
    }

    const statusColors = {completed:'var(--teal)',failed:'var(--crimson)',running:'var(--amber)',awaiting_user_input:'var(--blue)'};
    const statusColor = statusColors[status] || 'var(--muted)';
    const metaRow = document.createElement('div');
    metaRow.style.cssText = 'padding: 0 0 8px; display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-left:52px;';
    const statusPill = `<span style="padding:3px 10px;border-radius:999px;font-size:11px;font-weight:600;background:rgba(0,0,0,0.2);color:${statusColor};border:1px solid ${statusColor}">${status}</span>`;
    const agentPill = lastAgent ? `<span style="font-size:11px;color:var(--muted)">via ${esc(lastAgent)}</span>` : '';
    const timePill = createdAt ? `<span style="font-size:11px;color:var(--muted)">&#x1F551; ${esc(createdAt)}</span>` : '';
    const idPill = `<span style="font-size:11px;font-family:monospace;color:var(--muted);opacity:0.6">${esc(runId)}</span>`;
    metaRow.innerHTML = statusPill + agentPill + timePill + idPill;
    msgs.appendChild(metaRow);

    if (status === 'awaiting_user_input') {
      const runWorkDir = d.working_directory || d.run_output_dir || '';
      const banner = document.createElement('div');
      banner.style.cssText = 'margin:8px 0 0 52px;padding:10px 14px;background:rgba(83,82,237,0.1);border:1px solid rgba(83,82,237,0.3);border-radius:8px;font-size:13px;color:var(--text);display:flex;align-items:center;gap:12px;flex-wrap:wrap';
      banner.innerHTML = '<span><span style="color:#8b8af0;font-weight:600">&#x23F3; Awaiting your input</span> &mdash; this run is paused and waiting for a response.</span>' +
        '<button onclick="continueRun(' + JSON.stringify(runId) + ',' + JSON.stringify(runWorkDir) + ')" style="padding:5px 12px;border-radius:6px;border:1px solid rgba(83,82,237,0.5);background:rgba(83,82,237,0.15);color:#8b8af0;font-size:12px;font-weight:600;cursor:pointer">&#x25B6; Continue This Run</button>';
      msgs.appendChild(banner);
    }

    try {
      const ar = await fetch(API + '/api/runs/' + runId + '/artifacts');
      const artifacts = await ar.json();
      if (Array.isArray(artifacts) && artifacts.length > 0) {
        const artCard = document.createElement('div');
        artCard.style.cssText = 'margin:8px 0 0 52px;padding:10px 14px;background:var(--surface2);border:1px solid var(--border);border-radius:8px;';
        artCard.innerHTML = '<div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px">&#x1F4C1; Artifacts</div>' +
          artifacts.map(a => {
            const name = esc(a.name || a.artifact_id || 'file');
            const kind = esc(a.kind || '');
            const isFile = a.kind !== 'error' && a.kind !== 'text';
            return `<div style="display:flex;align-items:center;gap:8px;padding:3px 0;font-size:12px">` +
              (isFile ? `<a href="/api/artifacts/download?run_id=${encodeURIComponent(runId)}&name=${encodeURIComponent(a.name||'')}" download="${name}" style="color:var(--teal);text-decoration:underline">&#x1F4C4; ${name}</a>` : `<span style="color:var(--muted)">&#x1F4CB; ${name}</span>`) +
              (kind ? `<span style="color:var(--muted);font-size:10px">[${kind}]</span>` : '') + `</div>`;
          }).join('');
        msgs.appendChild(artCard);
      }
    } catch(_) {}

    scrollDown();
  } catch(e) {
    msgs.innerHTML = '<div style="color:var(--crimson);font-size:13px;padding:20px">Failed to load run: ' + esc(String(e)) + '</div>';
  }
}

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function newChat() {
  _loadRunToken++;
  currentRunId = null;
  isAwaitingInput = false;
  deepResearchUploadedRoots = [];
  deepResearchLocalPaths = [];
  chatSessionId = _newChatSessionId();
  sessionStorage.setItem('kendr_chat_session_id', chatSessionId);
  if (activeEvtSource) { activeEvtSource.close(); activeEvtSource = null; }
  stopPlanPolling();
  isRunning = false;
  document.getElementById('sendBtn').disabled = false;
  _removeAwaitingBanner();
  clearMessages();
  document.getElementById('chatTitle').textContent = 'New Chat';
  document.getElementById('clearChatBtn').style.display = 'none';
  renderDeepResearchSourceSummary();
  document.getElementById('userInput').focus();
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
  isRunning = false;
  document.getElementById('sendBtn').disabled = false;
  currentRunId = null;
  _removeAwaitingBanner();
  clearMessages();
  document.getElementById('chatTitle').textContent = 'New Chat';
  document.getElementById('clearChatBtn').style.display = 'none';
  deepResearchUploadedRoots = [];
  deepResearchLocalPaths = [];
  chatSessionId = _newChatSessionId();
  sessionStorage.setItem('kendr_chat_session_id', chatSessionId);
  renderDeepResearchSourceSummary();
  document.getElementById('userInput').focus();
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
  msgs.innerHTML = '<div class="welcome" id="welcome"><div class="welcome-logo">&#x26A1;</div><h2>What would you like to research or build?</h2><p>Kendr orchestrates specialized AI agents to research, generate code, deploy applications, analyze data, and automate complex workflows &#x2014; all from a single query.</p><div class="suggestions"><div class="suggest-chip" onclick="fillInput(\'Create a competitive intelligence brief on Stripe\')">&#x1F4CA; Stripe competitive brief</div><div class="suggest-chip" onclick="fillInput(\'Build a FastAPI REST API with JWT authentication and PostgreSQL\')">&#x1F3D7;&#xFE0F; FastAPI + JWT + PostgreSQL</div><div class="suggest-chip" onclick="fillInput(\'Write API tests for https://jsonplaceholder.typicode.com\')">&#x1F9EA; API test generation</div><div class="suggest-chip" onclick="fillInput(\'Summarize my unread emails and Slack messages from today\')">&#x1F4EC; Communications digest</div><div class="suggest-chip" onclick="fillInput(\'Dockerize a Node.js app and write a docker-compose.yml\')">&#x1F433; Dockerize + compose</div><div class="suggest-chip" onclick="fillInput(\'Deploy a React app to AWS S3 and CloudFront\')">&#x2601;&#xFE0F; Deploy to AWS</div></div></div>';
}

function fillInput(text) {
  const input = document.getElementById('userInput');
  input.value = text;
  autoResize(input);
  input.focus();
  const w = document.getElementById('welcome');
  if (w) w.style.display = 'none';
}

function autoResize(el) {
  el.style.height = 'auto';
  el.style.height = Math.min(el.scrollHeight, 200) + 'px';
}

function handleKey(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendMessage(); }
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

function createStreamingRow(runId) {
  const w = document.getElementById('welcome');
  if (w) w.remove();
  const msgs = document.getElementById('messages');
  const row = document.createElement('div');
  row.className = 'message-row kendr';
  row.id = 'stream-row-' + runId;
  row.innerHTML = '<div class="avatar kendr">&#x26A1;</div><div class="bubble" id="stream-bubble-' + runId + '">'
    + '<div style="display:flex;align-items:center;gap:8px;margin-bottom:8px">'
    + '<span class="spinner" style="width:14px;height:14px;flex-shrink:0"></span>'
    + '<div class="streaming-status" id="stream-status-' + runId + '" style="font-size:12px;color:var(--teal);font-weight:600">Starting agents\u2026</div>'
    + '</div>'
    + '<div class="steps-wrapper" id="stream-steps-' + runId + '" style="display:flex;flex-direction:column;gap:6px"></div>'
    + '<div id="stream-result-' + runId + '"></div></div>';
  msgs.appendChild(row);
  scrollDown();
  return row;
}

function updateStreamStatus(runId, msg) {
  const el = document.getElementById('stream-status-' + runId);
  if (el) el.textContent = msg;
}

function _agentDisplayName(agentName) {
  return agentName.replace(/_agent$/, '').replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
}

function addStreamStep(runId, step) {
  const container = document.getElementById('stream-steps-' + runId);
  if (!container) return;
  const rawStatus = step.status || 'running';
  const agentName = step.agent || step.name || 'agent';
  const isMcp = agentName.startsWith('mcp_') && agentName.endsWith('_agent');
  const isRunning = rawStatus === 'running' || rawStatus === 'started';
  const isDone = rawStatus === 'done' || rawStatus === 'completed' || rawStatus === 'success';
  const isFailed = rawStatus === 'failed' || rawStatus === 'error';
  const cssClass = isRunning ? 'running' : isDone ? 'done' : isFailed ? 'failed' : rawStatus;
  const existingId = 'step-' + runId + '-' + (step.execution_id || agentName);
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

  div.innerHTML = '<div class="step-dot">' + dotIcon + '</div>'
    + '<div class="step-inner">'
    + '<div style="display:flex;align-items:center;gap:6px;flex-wrap:wrap">'
    + '<span style="font-size:12px;font-weight:600;color:' + nameColor + '">' + esc(displayName) + '</span>'
    + mcpPill
    + '</div>'
    + reasonHtml
    + outputHtml
    + pulseHtml
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
  }
  html += '<div style="margin-top:12px;font-size:12px;color:var(--muted)">';
  html += 'Web search: <strong style="color:var(--text)">' + (card.web_search_enabled === false ? 'disabled' : 'enabled') + '</strong>';
  if (card.local_sources != null) html += ' · Local files: <strong style="color:var(--text)">' + esc(String(card.local_sources)) + '</strong>';
  if (card.provided_urls != null) html += ' · Explicit URLs: <strong style="color:var(--text)">' + esc(String(card.provided_urls)) + '</strong>';
  html += '</div>';
  html += '</div>';
  return html;
}

function finalizeStreamRow(runId, output, error, artifactFiles, testReport, mcpInvocations, docExports, deepResearchCard) {
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
  if (resultEl) {
    if (error) {
      resultEl.innerHTML = '<div class="error-banner" style="margin-top:8px">\u26A0\uFE0F ' + esc(error) + '</div>';
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
    const nonDocFiles = (artifactFiles || []).filter(f => {
      if (!docExports || !docExports.length) return true;
      return !docExports.some(ex => ex.name === f.name);
    });
    if (nonDocFiles.length > 0) {
      let artHtml = '<div style="margin-top:10px;padding:10px;background:var(--surface2);border:1px solid var(--border);border-radius:8px"><div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px">\ud83d\udcc1 Artifact Files</div>';
      artHtml += nonDocFiles.map(f => '<div style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:12px">' +
        '<span style="color:var(--teal)">\ud83d\udcc4</span>' +
        '<a href="/api/artifacts/download?run_id=' + encodeURIComponent(runId) + '&name=' + encodeURIComponent(f.name) + '" download="' + esc(f.name) + '" style="color:var(--teal);text-decoration:underline">' + esc(f.name) + '</a>' +
        (f.size ? '<span style="color:var(--muted)">(' + (f.size > 1024 ? Math.round(f.size/1024) + ' KB' : f.size + ' B') + ')</span>' : '') + '</div>').join('');
      artHtml += '</div>';
      resultEl.innerHTML += artHtml;
    }
  }
  const meta = document.createElement('div');
  meta.className = 'bubble-meta';
  meta.textContent = 'Run: ' + runId;
  const bubble = document.getElementById('stream-bubble-' + runId);
  if (bubble) bubble.appendChild(meta);
  scrollDown();
}

let _planPollInterval = null;

function startPlanPolling(runId) {
  stopPlanPolling();
  let lastStepCount = 0;
  _planPollInterval = setInterval(async () => {
    try {
      const r = await fetch('/api/plan');
      if (!r.ok) return;
      const plan = await r.json();
      if (!plan.has_plan || !plan.steps || plan.steps.length === 0) return;
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
        const result = s.result_summary ? '<div style="font-size:11px;color:var(--muted);margin-top:2px;padding-left:4px;border-left:2px solid var(--border)">' + esc(s.result_summary.slice(0,120)) + '</div>' : '';
        const err = s.error ? '<div style="font-size:11px;color:var(--crimson);margin-top:2px">\u26A0 ' + esc(s.error.slice(0,120)) + '</div>' : '';
        return '<div style="display:flex;gap:8px;align-items:flex-start;padding:5px 0;border-bottom:1px solid rgba(255,255,255,0.04)">' +
          '<span style="font-size:13px;min-width:18px">' + icon + '</span>' +
          '<div style="flex:1;min-width:0"><div style="font-size:12px;color:' + color + ';font-weight:' + (st==='running'?'600':'400') + '">' + title + '</div>' +
          '<div style="font-size:11px;color:var(--muted)">' + agent + '</div>' + result + err + '</div></div>';
      }).join('');
      const summary = '<div style="font-size:11px;color:var(--muted);margin-top:6px">' + plan.completed_steps + '/' + plan.total_steps + ' done' + (plan.running_steps > 0 ? ' &middot; ' + plan.running_steps + ' running' : '') + (plan.failed_steps > 0 ? ' &middot; <span style=\'color:var(--crimson)\'>' + plan.failed_steps + ' failed</span>' : '') + '</div>';
      stepsEl.insertAdjacentHTML('beforeend', summary);
    } catch(_) {}
  }, 2000);
}

function stopPlanPolling() {
  if (_planPollInterval) { clearInterval(_planPollInterval); _planPollInterval = null; }
}

function openEventStream(runId) {
  if (activeEvtSource) { activeEvtSource.close(); activeEvtSource = null; }
  const evtSrc = new EventSource(API + '/api/stream?run_id=' + encodeURIComponent(runId));
  activeEvtSource = evtSrc;
  startPlanPolling(runId);

  evtSrc.addEventListener('status', e => {
    try {
      const d = JSON.parse(e.data);
      updateStreamStatus(runId, d.message || d.status || '');
    } catch(_) {}
  });

  evtSrc.addEventListener('step', e => {
    try { addStreamStep(runId, JSON.parse(e.data)); } catch(_) {}
  });

  evtSrc.addEventListener('result', e => {
    try {
      const d = JSON.parse(e.data);
      const output = d.final_output || d.output || d.draft_response || '';
      const awaiting = d.awaiting_user_input || d.plan_waiting_for_approval || d.plan_needs_clarification || false;
      updateStreamStatus(runId, awaiting ? 'Awaiting your input\u2026' : 'Completed.');
      finalizeStreamRow(runId, output, '', d.artifact_files || [], d.test_report || null, d.mcp_invocations || null, d.long_document_exports || null, d.deep_research_result_card || null);
    } catch(_) {}
  });

  evtSrc.addEventListener('error', e => {
    try {
      const d = JSON.parse(e.data);
      finalizeStreamRow(runId, '', d.message || 'Run failed');
    } catch(_) {
      finalizeStreamRow(runId, '', 'Stream error');
    }
    stopPlanPolling();
    evtSrc.close();
    activeEvtSource = null;
    isRunning = false;
    document.getElementById('sendBtn').disabled = false;
    loadRuns();
  });

  evtSrc.addEventListener('done', e => {
    try {
      const d = JSON.parse(e.data);
      if (d.awaiting_user_input) {
        isAwaitingInput = true;
        _showAwaitingBanner();
      } else {
        isAwaitingInput = false;
        sessionStorage.removeItem('kendr_active_run_id');
      }
    } catch(_) { sessionStorage.removeItem('kendr_active_run_id'); }
    stopPlanPolling();
    evtSrc.close();
    activeEvtSource = null;
    isRunning = false;
    document.getElementById('sendBtn').disabled = false;
    loadRuns();
  });

  evtSrc.addEventListener('ping', () => {});

  evtSrc.onerror = () => {
    sessionStorage.removeItem('kendr_active_run_id');
    if (evtSrc.readyState === EventSource.CLOSED) {
      stopPlanPolling();
      isRunning = false;
      document.getElementById('sendBtn').disabled = false;
    }
  };
}

async function sendMessage() {
  const input = document.getElementById('userInput');
  const text = input.value.trim();
  if (!text || isRunning) return;

  input.value = '';
  autoResize(input);
  isRunning = true;
  document.getElementById('sendBtn').disabled = true;

  const isContinuation = isAwaitingInput;
  isAwaitingInput = false;
  _removeAwaitingBanner();

  appendUserMsg(text);
  const runId = 'ui-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
  currentRunId = runId;
  sessionStorage.setItem('kendr_active_run_id', runId);
  if (!isContinuation) {
    document.getElementById('chatTitle').textContent = text.substring(0, 40) + (text.length > 40 ? '...' : '');
  }
  createStreamingRow(runId);

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
      working_directory: workingDir
    };
    if (researchMode === 'deep_research') {
      const webSearchEnabled = !!((document.getElementById('drWebSearch') || {}).checked);
      const localPaths = _allDeepResearchLocalPaths();
      const explicitLinks = webSearchEnabled ? _deepResearchLinks() : [];
      if (!webSearchEnabled && !localPaths.length) {
        finalizeStreamRow(runId, '', 'Deep Research with web search disabled requires at least one local file, uploaded folder, or local path.');
        isRunning = false;
        document.getElementById('sendBtn').disabled = false;
        return;
      }
      payload.deep_research_mode = true;
      payload.long_document_mode = true;
      payload.long_document_pages = parseInt((document.getElementById('drPages') || {}).value || '50', 10) || 50;
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
    if (resumeDir) {
      endpoint = API + '/api/chat/resume';
      payload.resume_dir = resumeDir;
    }
    const resp = await fetch(endpoint, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
    const d = await resp.json();

    if (d.error) {
      finalizeStreamRow(runId, '', d.error + (d.detail ? ': ' + d.detail : ''));
      isRunning = false;
      document.getElementById('sendBtn').disabled = false;
      return;
    }

    if (d.streaming) {
      openEventStream(runId);
    } else {
      const output = d.final_output || d.output || d.draft_response || '(Run completed)';
      finalizeStreamRow(runId, output, '', d.artifact_files || [], d.test_report || null, d.mcp_invocations || null, d.long_document_exports || null, d.deep_research_result_card || null);
      isRunning = false;
      document.getElementById('sendBtn').disabled = false;
      loadRuns();
    }
  } catch(err) {
    finalizeStreamRow(runId, '', 'Request failed: ' + String(err));
    isRunning = false;
    document.getElementById('sendBtn').disabled = false;
  }
}

checkGateway();
loadRuns();
loadProjContext();
setResearchMode('auto');
renderDeepResearchSourceSummary();
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
    if (status === 'running' || status === 'started') {
      currentRunId = run.run_id;
      const query = run.user_query || run.query || 'Running…';
      document.getElementById('chatTitle').textContent = query.substring(0, 40) + (query.length > 40 ? '...' : '');
      document.getElementById('clearChatBtn').style.display = '';
      createStreamingRow(run.run_id);
      updateStreamStatus(run.run_id, 'Reconnecting to active run\u2026');
      isRunning = true;
      document.getElementById('sendBtn').disabled = true;
      openEventStream(run.run_id);
    } else if (status === 'completed' || status === 'failed') {
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
    <a href="/mcp" class="nav-btn"><span class="icon">&#x1F9E9;</span> MCP Servers</a>
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
.chat-model-select { background: var(--surface2); border: 1px solid var(--border); color: var(--text); border-radius: 6px; padding: 3px 8px; font-size: 11px; cursor: pointer; outline: none; max-width: 180px; }
.chat-model-select:focus { border-color: var(--teal); }
.ctx-badge { font-size: 10px; color: var(--muted); display: flex; align-items: center; gap: 5px; }
.ctx-bar-wrap { width: 60px; height: 4px; background: var(--border); border-radius: 2px; overflow: hidden; }
.ctx-bar-fill { height: 100%; background: var(--teal); border-radius: 2px; transition: width 0.4s; }
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
    <a href="/mcp" class="nav-btn"><span class="icon">&#x1F9E9;</span> MCP Servers</a>
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
        <div class="chat-input-row">
          <textarea class="chat-input" id="chatInput" rows="1" placeholder="Ask about your project..." onkeydown="chatKeydown(event)"></textarea>
          <button class="send-btn" id="sendBtn" onclick="sendChat()">&#x27A4;</button>
        </div>
        <div class="chat-bar-meta">
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
    inspectorRunSummary.textContent = !_activeProjectName
      ? 'Open a project and start from chat, then switch to coding mode when you want tighter file, terminal, and git focus.'
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
  document.getElementById('wsTitle').textContent = name;
  document.getElementById('wsPath').textContent = path;
  document.getElementById('wsPath').style.display = '';
  document.getElementById('filePanelTitle').textContent = name;
  document.getElementById('termPrompt').textContent = name.substring(0,12) + ' $';
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
  try {
    const r = await fetch(API + '/api/projects/' + _activeProjectId + '/files');
    const tree = await r.json();
    box.innerHTML = renderTree(tree, 0);
  } catch(e) { box.innerHTML = '<div style="padding:10px;color:var(--crimson);font-size:12px">Error: ' + e + '</div>'; }
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
  try {
    const r = await fetch(API + '/api/projects/file?path=' + encodeURIComponent(path) + '&root=' + encodeURIComponent(_activeProjectPath || ''));
    const d = await r.json();
    if (d.ok) {
      document.getElementById('fileViewerContent').textContent = d.content;
    } else {
      document.getElementById('fileViewerContent').textContent = 'Error: ' + d.error;
    }
  } catch(e) {
    document.getElementById('fileViewerContent').textContent = 'Error: ' + e;
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
    const defOpt = document.createElement('option');
    defOpt.value = '';
    defOpt.textContent = (d.active_provider || 'default') + ' / ' + (d.active_model || 'default');
    defOpt.title = 'Context window: ' + _fmtTokens(d.active_context_window || 128000) + ' tokens';
    sel.appendChild(defOpt);
    for (const p of (d.providers || [])) {
      if (!p.ready) continue;
      const opt = document.createElement('option');
      opt.value = p.provider + '::' + p.model;
      opt.textContent = p.provider + ' / ' + p.model;
      opt.title = 'Context: ' + _fmtTokens(p.context_window || 128000);
      sel.appendChild(opt);
    }
    for (const om of (d.ollama_models || [])) {
      const opt = document.createElement('option');
      opt.value = 'ollama::' + om;
      opt.textContent = 'ollama / ' + om;
      sel.appendChild(opt);
    }
    if (d.active_context_window) {
      _updateCtxBadge(0, d.active_context_window, d.active_model || '');
    }
  } catch(_) {}
}

async function sendChat() {
  const inp = document.getElementById('chatInput');
  const btn = document.getElementById('sendBtn');
  const text = inp.value.trim();
  if (!text) return;
  if (!_activeProjectPath) { appendSysMsg('Please open a project first.'); return; }
  inp.value = '';
  inp.style.height = 'auto';
  btn.disabled = true;
  appendMsg('user', text, isLikelyMarkdown(text) ? 'markdown' : 'text');
  const agentDiv = appendMsg('agent', '');
  const bubble = agentDiv.querySelector('.msg-bubble');
  bubble.innerHTML = '<span class="spinner"></span>';
  const scroller = document.getElementById('chatMessages');
  try {
    const payload = {
      text,
      project_id: _activeProjectId,
      project_root: _activeProjectPath,
      project_name: _activeProjectName || '',
    };
    if (_projSelectedModel) payload.model = _projSelectedModel;
    if (_projSelectedProvider) payload.provider = _projSelectedProvider;
    const resp = await fetch(API + '/api/project/ask', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    if (!resp.ok || !resp.body) {
      const txt = await resp.text();
      bubble.innerHTML = '<span style="color:var(--crimson)">\u26A0 Server error: ' + escapeHtml(txt.slice(0, 200)) + '</span>';
      btn.disabled = false; return;
    }
    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let answered = false;
    function _parseSseLine(chunk) {
      const lines = chunk.split('\n');
      let evName = '', evData = '';
      for (const l of lines) {
        if (l.startsWith('event: ')) evName = l.slice(7).trim();
        else if (l.startsWith('data: ')) evData = l.slice(6).trim();
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
          const d = JSON.parse(evData);
          if (evName === 'log') {
            if (!answered) {
              bubble.innerHTML = '<div class="plain-text" style="color:var(--muted);font-size:11px">' + escapeHtml(d.msg || 'Processing...') + '</div>';
              scroller.scrollTop = 999999;
            }
          } else if (evName === 'result') {
            answered = true;
            const answer = d.answer || '(No response)';
            setChatBubbleContent(bubble, answer, isLikelyMarkdown(answer) ? 'markdown' : 'text', 'agent');
            if (d.context_tokens && d.model_context_limit) {
              const ctxMeta = document.createElement('div');
              ctxMeta.className = 'msg-ctx';
              const pct = Math.round(d.context_pct || 0);
              ctxMeta.innerHTML = '<span>\uD83D\uDCAC ' + escapeHtml(d.model || '') + '</span>'
                + '<span style="opacity:0.6">\u2022</span>'
                + '<span>' + _fmtTokens(d.context_tokens) + ' / ' + _fmtTokens(d.model_context_limit) + ' ctx (' + pct + '%)'
                + (d.kendr_md_generated ? ' \u2728 kendr.md created' : d.kendr_md_loaded ? ' \uD83D\uDCCB kendr.md' : '') + '</span>';
              bubble.appendChild(ctxMeta);
              _updateCtxBadge(d.context_tokens, d.model_context_limit, d.model || '');
            }
            scroller.scrollTop = 999999;
          } else if (evName === 'error') {
            bubble.innerHTML = '<span style="color:var(--crimson)">\u26A0 ' + escapeHtml(d.error || 'Unknown error') + '</span>';
          }
        } catch(_) {}
      }
    }
    if (!answered) bubble.innerHTML = '<em style="color:var(--muted)">No response received.</em>';
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
  } catch(e) { output.textContent += 'Request error: ' + e; }
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
  try {
    const r = await fetch(API + '/api/projects/' + _activeProjectId + '/services');
    const payload = await r.json();
    const services = payload.services || [];
    _servicesCache = services;
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
  try {
    const r = await fetch(API + '/api/projects/' + _activeProjectId + '/services/' + encodeURIComponent(serviceId) + '/log');
    const d = await r.json();
    if (!r.ok || d.error) throw new Error(d.error || 'Failed to load log');
    meta.textContent = (d.log_path || serviceId) + (d.truncated ? ' (tail)' : '');
    out.textContent = d.content || '(log file is empty)';
    out.scrollTop = out.scrollHeight;
  } catch(e) {
    meta.textContent = 'Log load failed';
    out.textContent = 'Error: ' + e;
  }
}

// ── Git ───────────────────────────────────────────────────────────────────────
async function loadGitStatus() {
  if (!_activeProjectId) return;
  const panel = document.getElementById('gitPanel');
  panel.innerHTML = '<div style="color:var(--muted);font-size:13px"><span class="spinner"></span> Loading git status...</div>';
  try {
    const r = await fetch(API + '/api/projects/' + _activeProjectId + '/git/status');
    const s = await r.json();
    _gitStatusCache = s;
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
  } catch(e) { panel.innerHTML = '<div style="color:var(--crimson)">Error: ' + e + '</div>'; _gitStatusCache = null; }
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
  try {
    const r = await fetch(API + url, { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify(body) });
    const d = await r.json();
    const text = [d.stdout, d.stderr].filter(Boolean).join('\n').trim() || (d.ok ? 'Done.' : 'Failed.');
    if (outEl) { outEl.textContent = text; }
    await loadGitStatus();
    const badge = document.getElementById('wsBranchName');
    if (badge && d.branch) badge.textContent = d.branch;
  } catch(e) { if (outEl) outEl.textContent = 'Error: ' + e; }
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
    <a href="/mcp" class="nav-btn"><span class="icon">&#x1F9E9;</span> MCP Servers</a>
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
  <a href="/mcp" class="nav-btn"><span class="icon">&#x1F9E9;</span> MCP Servers</a>
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
  xai:         { emoji: '\u274E',       label: 'xAI (Grok)',          type: 'Cloud API',     models: ['grok-3','grok-3-mini','grok-2'], keyEnv: 'XAI_API_KEY',       hint: 'console.x.ai' },
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
    const statusCls = isActive ? 'st-active' : ready ? 'st-ready' : 'st-nokey';
    const statusLabel = isActive ? '\u2714 Active' : ready ? '\u2714 Ready' : '\u26A1 Add Key';
    const cardCls = isActive ? 'provider-card active-card' : ready ? 'provider-card' : 'provider-card needs-key';

    let btn = '';
    if (!isActive && ready) {
      btn = `<button class="set-btn" onclick="setActive('${id}','')">Set as Active</button>`;
    } else if (!ready && id !== 'ollama' && id !== 'custom') {
      btn = `<button class="cfg-btn" onclick="openCfg('${id}')">Add API Key</button>`;
    } else if (id === 'custom') {
      btn = `<button class="cfg-btn" onclick="openCfg('${id}')">Configure Endpoint</button>`;
    } else if (id === 'ollama') {
      btn = `<button class="set-btn" onclick="setActive('ollama','')">Use Ollama</button>`;
    } else {
      btn = `<button class="cfg-btn" onclick="openCfg('${id}')">Edit Settings</button>`;
    }

    return `<div class="${cardCls}">
      <div class="pcard-header">
        <div class="pcard-emoji">${meta.emoji}</div>
        <div class="pcard-info">
          <div class="pcard-name">${esc(meta.label)}</div>
          <div class="pcard-type">${esc(meta.type)}</div>
        </div>
        <div class="pcard-status ${statusCls}">${statusLabel}</div>
      </div>
      <div class="pcard-model" title="${esc(model)}">${esc(model) || '(not set)'}</div>
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
               { key:'XAI_MODEL', label:'Default Model', hint:'e.g. grok-3, grok-3-mini' }],
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
    <a href="/mcp" class="nav-btn active"><span class="icon">&#x1F9E9;</span> MCP Servers</a>
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
    The full example is at <code style="color:var(--teal)">mcp_servers/example_fastmcp_server.py</code> &mdash; run with <code style="color:var(--teal)">python mcp_servers/example_fastmcp_server.py</code>
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
    <a href="/mcp" class="nav-btn"><span class="icon">&#x1F9E9;</span> MCP Servers</a>
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
    <a href="/mcp" class="nav-btn"><span class="icon">&#x1F9E9;</span> MCP Servers</a>
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
      return '<tr><td style="max-width:280px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="' + esc(run.query||run.text||'') + '">' + esc((run.query||run.text||'\u2014').substring(0,70)) + '</td><td style="font-family:monospace;font-size:11px;color:var(--muted)">' + esc(rid) + '</td><td><span class="badge ' + status + '">' + status + '</span></td><td style="color:var(--muted)">' + esc(run.last_agent||'') + '</td><td style="color:var(--muted);white-space:nowrap">' + esc(run.created_at||'') + '</td><td><button onclick="showArtifacts(\'' + rid + '\', this)" style="background:none;border:1px solid var(--border);color:var(--teal);border-radius:6px;padding:3px 8px;cursor:pointer;font-size:11px">\ud83d\udcc1</button></td></tr>';
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
        import re, html as _html_mod, pathlib
        docs_path = pathlib.Path(__file__).parent.parent / "docs" / "cli.md"
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
    <a href="/mcp" class="nav-btn"><span class="icon">&#x1F9E9;</span> MCP Servers</a>
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
            self._html(200, _MCP_HTML)
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
                active = get_active_provider()
                active_model = get_model_for_provider(active)
                statuses = all_provider_statuses()
                ollama_running = is_ollama_running()
                ollama_models = list_ollama_models() if ollama_running else []
                for s in statuses:
                    s["context_window"] = get_context_window(s.get("model", ""))
                self._json(200, {
                    "active_provider": active,
                    "active_model": active_model,
                    "active_context_window": get_context_window(active_model),
                    "providers": statuses,
                    "ollama_running": ollama_running,
                    "ollama_models": [m.get("name", "") for m in ollama_models],
                })
            except Exception as exc:
                self._json(500, {"error": str(exc)})
            return
        if path == "/api/models/ollama/docker/status":
            self._handle_ollama_docker_status()
            return
        if path == "/api/skills":
            try:
                data = _gateway_get("/registry/skills", timeout=5.0)
                self._json(200, data)
            except Exception:
                self._json(503, {"error": "Gateway offline", "summary": {}, "cards": []})
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
            self._json(200, runs)
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
        if path.startswith("/api/runs/"):
            run_id = path[len("/api/runs/"):]
            try:
                data = _gateway_get(f"/runs/{run_id}")
            except Exception as exc:
                self._json(500, {"error": str(exc)})
                return
            self._json(200, data)
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
        if path == "/api/chat/resume":
            self._handle_chat_resume(body)
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
        if path == "/api/models/set":
            self._handle_models_set(body)
            return
        if path == "/api/models/ollama/pull":
            self._handle_ollama_pull(body)
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
        gateway_up = _gateway_ready(timeout=0.5)

        if not gateway_up and not project_build_mode:
            self._json(503, {
                "error": "Gateway not running",
                "detail": "Start it with: kendr gateway start",
            })
            return

        working_directory = str(
            body.get("working_directory") or os.getenv("KENDR_WORKING_DIR", "")
        ).strip()
        payload = {
            "text": text,
            "channel": str(body.get("channel", "webchat")),
            "sender_id": str(body.get("sender_id", "ui_user")),
            "chat_id": str(body.get("chat_id", "")),
        }
        if working_directory:
            payload["working_directory"] = working_directory
        if project_build_mode:
            payload["project_build_mode"] = True
        for key in ("project_name", "project_stack", "stack", "project_root",
                    "github_repo", "auto_approve", "skip_test_agent", "skip_devops_agent",
                    "shell_auto_approve", "privileged_approval_note", "deep_research_mode",
                    "long_document_mode", "long_document_pages", "long_document_title",
                    "research_output_formats", "research_citation_style",
                    "research_enable_plagiarism_check", "research_web_search_enabled", "research_date_range",
                    "research_sources", "research_max_sources", "research_checkpoint_enabled",
                    "deep_research_source_urls", "local_drive_paths", "local_drive_recursive",
                    "local_drive_force_long_document"):
            if body.get(key) is not None:
                payload[key] = body[key]
        # Auto-inject active project context when caller didn't supply project_root
        if not payload.get("project_root"):
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
        run_id = str(body.get("run_id") or "").strip() or f"ui-{uuid.uuid4().hex[:8]}"
        payload["run_id"] = run_id

        q: "queue.Queue[dict]" = queue.Queue()
        with _pending_lock:
            _run_event_queues[run_id] = q
            _pending_runs[run_id] = {"status": "running"}

        use_standalone = project_build_mode and (not gateway_up or bool(body.get("standalone")))
        if use_standalone:
            _start_standalone_run_background(run_id, payload)
        else:
            _start_run_background(run_id, payload)
        self._json(200, {"run_id": run_id, "streaming": True, "status": "started"})

    def _handle_chat_resume(self, body: dict) -> None:
        text = str(body.get("text") or body.get("message") or "").strip()
        if not text:
            self._json(400, {"error": "missing_text"})
            return
        resume_dir = str(body.get("resume_dir") or body.get("working_directory") or os.getenv("KENDR_WORKING_DIR", "")).strip()
        if not resume_dir:
            self._json(400, {"error": "missing_resume_dir", "detail": "Provide resume_dir or working_directory."})
            return
        if not _gateway_ready(timeout=0.5):
            self._json(503, {"error": "Gateway not running", "detail": "Start it with: kendr gateway start"})
            return
        run_id = str(body.get("run_id") or "").strip() or f"ui-{uuid.uuid4().hex[:8]}"
        q: "queue.Queue[dict]" = queue.Queue()
        with _pending_lock:
            _run_event_queues[run_id] = q
            _pending_runs[run_id] = {"status": "running"}

        def _run() -> None:
            _push_event(run_id, "status", {"status": "running", "message": "Resuming run..."})
            try:
                resume_payload = {
                    "text": text,
                    "reply": text,
                    "working_directory": resume_dir,
                    "output_folder": resume_dir,
                    "channel": str(body.get("channel", "webchat")),
                    "sender_id": str(body.get("sender_id", "ui_user")),
                    "chat_id": str(body.get("chat_id", "")),
                    "run_id": run_id,
                }
                result = _gateway_resume(resume_payload)
                _run_awaiting = bool(
                    result.get("awaiting_user_input")
                    or result.get("plan_waiting_for_approval")
                    or result.get("plan_needs_clarification")
                    or str(result.get("pending_user_input_kind", "")).strip()
                )
                _run_status = "awaiting_user_input" if _run_awaiting else "completed"
                with _pending_lock:
                    _pending_runs[run_id] = {"status": _run_status, "result": result}
                _push_event(run_id, "result", result)
                _push_event(run_id, "done", {"run_id": run_id, "status": _run_status, "awaiting_user_input": _run_awaiting})
            except urllib.error.HTTPError as exc:
                err_body = exc.read().decode("utf-8") if hasattr(exc, "read") else str(exc)
                try:
                    err_data = json.loads(err_body)
                    err_msg = err_data.get("error", "") or err_data.get("detail", "") or str(exc)
                except Exception:
                    err_msg = err_body or str(exc)
                with _pending_lock:
                    _pending_runs[run_id] = {"status": "failed", "error": err_msg}
                _push_event(run_id, "error", {"message": err_msg})
                _push_event(run_id, "done", {"run_id": run_id, "status": "failed"})
            except Exception as exc:
                err = str(exc)
                with _pending_lock:
                    _pending_runs[run_id] = {"status": "failed", "error": err}
                _push_event(run_id, "error", {"message": err})
                _push_event(run_id, "done", {"run_id": run_id, "status": "failed"})

        import threading as _threading
        t = _threading.Thread(target=_run, daemon=True)
        t.start()
        self._json(200, {"run_id": run_id, "streaming": True, "status": "started"})

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
            write_event("result", run_data.get("result", {}))
            write_event("done", {"run_id": run_id})
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
            values: dict[str, str] = {"KENDR_LLM_PROVIDER": provider}
            if model:
                values["KENDR_MODEL"] = model
            result = save_component_values("core_runtime", values)
            apply_setup_env_defaults()
            self._json(200, {"saved": True, "provider": provider, "model": model})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

    def _handle_ollama_pull(self, body: dict) -> None:
        import subprocess
        model_name = str(body.get("model", "")).strip()
        if not model_name:
            self._json(400, {"error": "missing_model"})
            return
        try:
            proc = subprocess.run(
                ["ollama", "pull", model_name],
                capture_output=True, text=True, timeout=300,
            )
            if proc.returncode == 0:
                self._json(200, {"ok": True, "model": model_name})
            else:
                self._json(500, {"error": proc.stderr.strip() or "Pull failed"})
        except FileNotFoundError:
            self._json(503, {"error": "ollama not found — install from ollama.ai"})
        except Exception as exc:
            self._json(500, {"error": str(exc)})

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

            emit("log", {"msg": "\U0001f4c1 Checking project directory...", "step": "init"})

            kendr_md = ""
            kendr_md_generated = False
            file_tree = ""
            service_lines = ""
            if proj_root and os.path.isdir(proj_root):
                kpath = os.path.join(proj_root, "kendr.md")
                if os.path.isfile(kpath):
                    emit("log", {"msg": "\U0001f4cb Reading kendr.md context file...", "step": "kendr_md"})
                    try:
                        with open(kpath, "r", encoding="utf-8", errors="replace") as f:
                            kendr_md = f.read()[:12000]
                        emit("log", {"msg": "\u2705 kendr.md loaded (" + str(len(kendr_md)) + " chars)", "step": "kendr_md_ok"})
                    except Exception as e:
                        emit("log", {"msg": "\u26a0 Could not read kendr.md: " + str(e), "step": "kendr_md_err"})
                else:
                    emit("log", {"msg": "\U0001f527 kendr.md not found — generating project context...", "step": "kendr_md_gen"})
                    try:
                        from kendr.project_context import ensure_kendr_md
                        kendr_md = ensure_kendr_md(proj_root, proj_name)[:12000]
                        kendr_md_generated = True
                        emit("log", {"msg": "\u2728 kendr.md created and loaded (" + str(len(kendr_md)) + " chars)", "step": "kendr_md_gen_ok"})
                    except Exception as e:
                        emit("log", {"msg": "\u26a0 Could not generate kendr.md: " + str(e), "step": "kendr_md_gen_err"})

                emit("log", {"msg": "\U0001f4c2 Scanning project files...", "step": "file_tree"})
                try:
                    entries = sorted(os.listdir(proj_root))[:60]
                    file_tree = "\n".join(entries)
                    emit("log", {"msg": "\u2705 Found " + str(len(entries)) + " items in project root", "step": "file_tree_ok"})
                except Exception:
                    pass
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
                            emit("log", {"msg": "\u2705 Loaded " + str(len(services)) + " tracked project services", "step": "services_ok"})
                    except Exception as e:
                        emit("log", {"msg": "\u26a0 Could not load project services: " + str(e), "step": "services_err"})

            emit("log", {"msg": "\U0001f9e0 Building context and calling LLM...", "step": "llm"})

            system_ctx = "You are a knowledgeable assistant for the software project '" + (proj_name or "this project") + "'."
            if kendr_md:
                system_ctx += "\n\nProject context (kendr.md):\n" + kendr_md
            if file_tree:
                system_ctx += "\n\nProject root files:\n" + file_tree
            if service_lines:
                system_ctx += "\n\nTracked project services:\n" + service_lines
            system_ctx += (
                "\n\nAnswer the user's question concisely and accurately. "
                "If asked about what the project is or does, summarise from the kendr.md context above. "
                "Do NOT generate execution plans or project scaffolds — just answer the question."
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
            emit("error", {"error": str(exc)})
            emit("done", {})

    def _handle_project_context_generate(self, body: dict) -> None:
        try:
            from kendr.project_context import generate_kendr_md, write_kendr_md
            proj = _pm_get_active() if _HAS_PROJECT_MANAGER else None
            root = str((proj or {}).get("path", "") or body.get("project_root", "")).strip()
            if not root:
                self._json(400, {"error": "No active project"})
                return
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
        name = str(body.get("name", "")).strip()
        connection = str(body.get("connection", "")).strip()
        server_type = str(body.get("type", "http")).strip()
        description = str(body.get("description", "")).strip()
        auth_token = str(body.get("auth_token", "")).strip()
        if not name or not connection:
            self._json(400, {"error": "name and connection are required"})
            return
        try:
            entry = _mcp_add_server(name, connection, server_type, description, auth_token)
            server_id = entry["id"]
            result = _mcp_discover_tools(server_id)
            srv = _mcp_get_server(server_id) or {}
            if srv.get("auth_token"):
                srv = dict(srv)
                srv["auth_token"] = "****"
            result["server"] = srv
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
    print(f"  MCP:    {display_url}/mcp")
    print(f"  Projects: {display_url}/projects")
    print(f"  Gateway: {_gateway_url()} ({'online' if _gateway_ready(timeout=0.5) else 'offline — run: kendr gateway start'})")
    if ui_log_path:
        print(f"  Logs:   {ui_log_path}")
        _log.info("Kendr UI log file: %s", ui_log_path)
    _log.info("Kendr UI running at %s (bound to %s:%s)", display_url, host, port)
    server.serve_forever()


if __name__ == "__main__":
    main()
