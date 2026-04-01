from __future__ import annotations

import html as _html
import json
import logging
import os
import queue
import threading
import time
import traceback

import urllib.error
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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
        list_agent_executions_for_run as _list_run_steps,
        list_artifacts_for_run as _list_run_artifacts,
        get_run as _db_get_run,
    )
    _HAS_PERSISTENCE = True
except Exception:
    _HAS_PERSISTENCE = False
    def _list_run_steps(run_id):  # type: ignore[misc]
        return []
    def _list_run_artifacts(run_id):  # type: ignore[misc]
        return []
    def _db_get_run(run_id):  # type: ignore[misc]
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

try:
    from kendr.mcp_manager import (
        list_servers as _mcp_list_servers,
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
        read_file_tree as _pm_file_tree,
        read_file_content as _pm_read_file,
        run_shell as _pm_shell,
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


def _gateway_get(path: str, timeout: float = 5.0) -> dict | list:
    req = urllib.request.Request(f"{_gateway_url()}{path}", method="GET")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


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
    agent = step.get("agent_name", "agent")
    return {
        "agent": agent,
        "status": step.get("status", "running"),
        "message": excerpt or f"Running {agent}...",
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
            with _pending_lock:
                _pending_runs[run_id] = {"status": "completed", "result": result}
            _push_event(run_id, "result", result)
            _push_event(run_id, "done", {"run_id": run_id, "status": "completed"})
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
.chat-main { flex: 1; display: flex; flex-direction: column; overflow: hidden; background: var(--bg); }
.chat-header { padding: 16px 24px; border-bottom: 1px solid var(--border); display: flex; align-items: center; justify-content: space-between; background: var(--surface); }
.chat-title { font-size: 15px; font-weight: 600; color: var(--text); }
.chat-subtitle { font-size: 12px; color: var(--muted); }
.header-status { display: flex; align-items: center; gap: 8px; font-size: 12px; color: var(--muted); }
.status-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--crimson); }
.status-dot.online { background: var(--teal); animation: pulse 2s infinite; }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.5; } }
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
.steps-wrapper { display: flex; flex-direction: column; gap: 6px; margin-top: 10px; }
.step-card { background: var(--surface2); border: 1px solid var(--border); border-radius: 10px; padding: 8px 12px; font-size: 12px; display: flex; align-items: center; gap: 8px; }
.step-card.running { border-color: rgba(255,179,71,0.4); }
.step-card.done { border-color: rgba(0,201,167,0.3); }
.step-card.failed { border-color: rgba(255,71,87,0.4); }
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
<body>
<div class="sidebar">
  <div class="sidebar-header">
    <div class="logo">kendr<span>.</span></div>
    <div class="tagline">Multi-agent intelligence runtime</div>
  </div>
  <div class="sidebar-nav">
    <a href="/" class="nav-btn active"><span class="icon">💬</span> Chat</a>
    <a href="/setup" class="nav-btn"><span class="icon">⚙️</span> Setup & Config</a>
    <a href="/runs" class="nav-btn"><span class="icon">📋</span> Run History</a>
    <a href="/rag" class="nav-btn"><span class="icon">🧠</span> Super-RAG</a>
    <a href="/mcp" class="nav-btn"><span class="icon">🧩</span> MCP Servers</a>
    <a href="/projects" class="nav-btn"><span class="icon">📁</span> Projects</a>
  </div>
  <button class="new-chat-btn" onclick="newChat()">+ New Chat</button>
  <div class="sidebar-section">Recent Runs</div>
  <div class="run-list" id="runList"></div>
</div>
<div class="chat-main">
  <div class="chat-header">
    <div>
      <div class="chat-title" id="chatTitle">New Chat</div>
      <div class="chat-subtitle">Powered by kendr multi-agent runtime</div>
    </div>
    <div class="header-status">
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
    <div class="input-row">
      <textarea class="input-box" id="userInput" placeholder="Ask kendr anything &#x2014; research, code, deploy, analyze..." rows="1" onkeydown="handleKey(event)" oninput="autoResize(this)"></textarea>
      <button class="send-btn" id="sendBtn" onclick="sendMessage()" title="Send (Enter)">&#x27A4;</button>
    </div>
    <div class="input-hint">Enter to send &#xB7; Shift+Enter for new line &#xB7; Gateway auto-starts if not running</div>
  </div>
</div>
<script>
const API = '';
let currentRunId = null;
let isRunning = false;
let gatewayOnline = false;
let workingDir = '';
let activeEvtSource = null;

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

async function loadRuns() {
  try {
    const r = await fetch(API + '/api/runs');
    if (!r.ok) return;
    const runs = await r.json();
    const list = document.getElementById('runList');
    list.innerHTML = '';
    (runs || []).slice(0, 20).forEach(run => {
      const div = document.createElement('div');
      div.className = 'run-item' + (run.run_id === currentRunId ? ' active' : '');
      const text = (run.query || run.text || 'Run').substring(0, 50);
      const ts = run.created_at ? new Date(run.created_at).toLocaleTimeString() : '';
      const status = (run.status || 'completed').toLowerCase();
      div.innerHTML = '<div class="run-item-title">' + esc(text) + '</div>' +
        '<div class="run-item-meta"><span class="run-badge ' + status + '">' + status + '</span>' + (ts ? ' \xB7 ' + ts : '') + '</div>';
      div.onclick = () => loadRun(run.run_id);
      list.appendChild(div);
    });
  } catch(e) {}
}

async function loadRun(runId) {
  try {
    const r = await fetch(API + '/api/runs/' + runId);
    const d = await r.json();
    const output = d.final_output || d.output || '';
    const query = d.query || d.text || '';
    if (query) { clearMessages(); appendUserMsg(query); if (output) appendKendrMsg(output, runId); }
  } catch(e) {}
}

function esc(s) {
  return String(s || '').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
}

function newChat() {
  currentRunId = null;
  if (activeEvtSource) { activeEvtSource.close(); activeEvtSource = null; }
  clearMessages();
  document.getElementById('chatTitle').textContent = 'New Chat';
  document.getElementById('userInput').focus();
}

function clearMessages() {
  const msgs = document.getElementById('messages');
  msgs.innerHTML = '';
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

function formatOutput(text) {
  if (!text) return '';
  let h = esc(text);
  h = h.replace(/```([\s\S]*?)```/g, '<pre>$1</pre>');
  h = h.replace(/`([^`]+)`/g, '<code style="background:rgba(0,0,0,0.3);padding:2px 6px;border-radius:4px;font-family:monospace">$1</code>');
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
  row.innerHTML = '<div class="avatar kendr">&#x26A1;</div><div class="bubble" id="stream-bubble-' + runId + '">' +
    '<div class="typing-indicator"><div class="typing-dot"></div><div class="typing-dot"></div><div class="typing-dot"></div></div>' +
    '<div class="streaming-status" id="stream-status-' + runId + '">Starting agents...</div>' +
    '<div class="steps-wrapper" id="stream-steps-' + runId + '"></div>' +
    '<div id="stream-result-' + runId + '"></div></div>';
  msgs.appendChild(row);
  scrollDown();
  return row;
}

function updateStreamStatus(runId, msg) {
  const el = document.getElementById('stream-status-' + runId);
  if (el) el.textContent = msg;
}

function addStreamStep(runId, step) {
  const container = document.getElementById('stream-steps-' + runId);
  if (!container) return;
  const icons = { running: '\u2699\uFE0F', done: '\u2713', failed: '\u2717', completed: '\u2713' };
  const cssClass = step.status || 'running';
  const icon = icons[cssClass] || '\u2699\uFE0F';
  const div = document.createElement('div');
  div.className = 'step-card ' + cssClass;
  div.id = 'step-' + runId + '-' + (step.agent || step.name || Math.random().toString(36).slice(2));
  div.innerHTML = '<div class="step-icon">' + icon + '</div><div class="step-info"><div class="step-name">' +
    esc(step.agent || step.name || 'agent') + '</div>' +
    (step.message ? '<div class="step-desc">' + esc(step.message) + '</div>' : '') + '</div>';
  container.appendChild(div);
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

function finalizeStreamRow(runId, output, error, artifactFiles, testReport) {
  const row = document.getElementById('stream-row-' + runId);
  if (!row) return;
  const typing = row.querySelector('.typing-indicator');
  if (typing) typing.remove();
  const statusEl = document.getElementById('stream-status-' + runId);
  if (statusEl) statusEl.remove();
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
    if (artifactFiles && artifactFiles.length > 0) {
      let artHtml = '<div style="margin-top:10px;padding:10px;background:var(--surface2);border:1px solid var(--border);border-radius:8px"><div style="font-size:11px;font-weight:700;color:var(--muted);text-transform:uppercase;letter-spacing:0.08em;margin-bottom:6px">\ud83d\udcc1 Artifact Files</div>';
      artHtml += artifactFiles.map(f => '<div style="display:flex;align-items:center;gap:8px;padding:4px 0;font-size:12px">' +
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

function openEventStream(runId) {
  if (activeEvtSource) { activeEvtSource.close(); activeEvtSource = null; }
  const evtSrc = new EventSource(API + '/api/stream?run_id=' + encodeURIComponent(runId));
  activeEvtSource = evtSrc;

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
      updateStreamStatus(runId, 'Completed.');
      finalizeStreamRow(runId, output, '', d.artifact_files || [], d.test_report || null);
    } catch(_) {}
  });

  evtSrc.addEventListener('error', e => {
    try {
      const d = JSON.parse(e.data);
      finalizeStreamRow(runId, '', d.message || 'Run failed');
    } catch(_) {
      finalizeStreamRow(runId, '', 'Stream error');
    }
    evtSrc.close();
    activeEvtSource = null;
    isRunning = false;
    document.getElementById('sendBtn').disabled = false;
    loadRuns();
  });

  evtSrc.addEventListener('done', e => {
    evtSrc.close();
    activeEvtSource = null;
    isRunning = false;
    document.getElementById('sendBtn').disabled = false;
    loadRuns();
  });

  evtSrc.addEventListener('ping', () => {});

  evtSrc.onerror = () => {
    if (evtSrc.readyState === EventSource.CLOSED) {
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

  appendUserMsg(text);
  const runId = 'ui-' + Date.now() + '-' + Math.random().toString(36).slice(2, 8);
  currentRunId = runId;
  document.getElementById('chatTitle').textContent = text.substring(0, 40) + (text.length > 40 ? '...' : '');
  createStreamingRow(runId);

  try {
    const payload = { text, channel: 'webchat', sender_id: 'ui_user', chat_id: 'web_chat_1', run_id: runId, working_directory: workingDir };
    const resp = await fetch(API + '/api/chat', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) });
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
      finalizeStreamRow(runId, output, '');
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
setInterval(checkGateway, 30000);
setInterval(loadRuns, 10000);
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
<body>
<div class="sidebar">
  <div class="sidebar-header"><div class="logo">kendr<span>.</span></div><div class="tagline">Multi-agent intelligence runtime</div></div>
  <div class="sidebar-nav">
    <a href="/" class="nav-btn"><span class="icon">&#x1F4AC;</span> Chat</a>
    <a href="/setup" class="nav-btn active"><span class="icon">&#x2699;&#xFE0F;</span> Setup &amp; Config</a>
    <a href="/runs" class="nav-btn"><span class="icon">&#x1F4CB;</span> Run History</a>
    <a href="/rag" class="nav-btn"><span class="icon">&#x1F9E0;</span> Super-RAG</a>
    <a href="/mcp" class="nav-btn"><span class="icon">&#x1F9E9;</span> MCP Servers</a>
    <a href="/projects" class="nav-btn"><span class="icon">&#x1F4C1;</span> Projects</a>
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
      const t = c.total_fields || 0, f = c.filled_fields || 0;
      if (t === 0 || f === t) configured++;
      else if (f > 0) partial++;
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
  const total = comp.total_fields || 0, filled = comp.filled_fields || 0;
  const isConfigured = total === 0 || filled === total;
  const isPartial = filled > 0 && filled < total;
  const enabled = comp.enabled !== false;
  const div = document.createElement('div');
  div.className = 'int-card' + (isConfigured ? ' configured' : '');
  div.id = 'card-' + comp.id;
  let statusBadge = total === 0 ? '<span class="badge ok">\u2713 Ready</span>' :
    isConfigured ? '<span class="badge ok">\u2713 Configured</span>' :
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
  const oauthPath = (snapshot.component || {}).oauth_start_path || '';
  let html = '';
  if (fields.length > 0) {
    fields.forEach(f => {
      const val = values[f.key] || '';
      const type = f.secret ? 'password' : 'text';
      const badges = [f.secret ? '<span class="secret-badge">SECRET</span>' : '', f.required ? '<span class="required-badge">REQUIRED</span>' : ''].filter(Boolean).join(' ');
      html += '<div class="field-row"><div class="field-label">' + esc(f.label) + ' ' + badges + '</div>' +
        (f.description ? '<div class="field-desc">' + esc(f.description) + '</div>' : '') +
        '<input class="field-input" type="' + type + '" id="fld-' + esc(compId) + '-' + esc(f.key) + '" value="' + esc(val) + '" placeholder="' + esc(f.key) + '" autocomplete="off"></div>';
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
.msg-bubble { max-width: 75%; padding: 10px 14px; border-radius: 12px; font-size: 13px; line-height: 1.55; white-space: pre-wrap; word-break: break-word; }
.msg-row.user .msg-bubble { background: rgba(0,201,167,0.15); border: 1px solid rgba(0,201,167,0.3); color: var(--text); border-radius: 12px 12px 3px 12px; }
.msg-row.agent .msg-bubble { background: var(--surface2); border: 1px solid var(--border); color: var(--text); border-radius: 12px 12px 12px 3px; }
.msg-row.system .msg-bubble { background: var(--surface3); border: 1px solid var(--border); color: var(--muted); font-size: 12px; font-style: italic; border-radius: 8px; }
.chat-input-bar { padding: 12px 20px; border-top: 1px solid var(--border); display: flex; gap: 10px; background: var(--surface); }
.chat-input { flex: 1; background: var(--surface2); border: 1px solid var(--border); border-radius: 8px; padding: 9px 13px; color: var(--text); font-size: 13px; outline: none; resize: none; min-height: 40px; max-height: 120px; font-family: inherit; transition: border-color 0.15s; }
.chat-input:focus { border-color: var(--teal); }
.send-btn { background: var(--teal); color: #0d0f14; border: none; border-radius: 8px; padding: 9px 16px; font-size: 13px; font-weight: 700; cursor: pointer; }
.send-btn:disabled { opacity: 0.4; cursor: not-allowed; }
/* Terminal panel */
.terminal-output { flex: 1; overflow-y: auto; padding: 12px 16px; background: #0a0c10; font-family: "Cascadia Code","Fira Code",monospace; font-size: 12px; color: #b5c4de; white-space: pre-wrap; word-break: break-word; }
.terminal-output .cmd-line { color: var(--teal); margin-top: 8px; }
.terminal-output .err-line { color: var(--crimson); }
.terminal-input-bar { padding: 10px 12px; background: #0a0c10; border-top: 1px solid var(--border); display: flex; align-items: center; gap: 8px; }
.terminal-prompt { color: var(--teal); font-family: monospace; font-size: 13px; flex-shrink: 0; }
.terminal-input { flex: 1; background: transparent; border: none; color: var(--text); font-family: "Cascadia Code","Fira Code",monospace; font-size: 13px; outline: none; }
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
.form-field input, .form-field select { width: 100%; background: var(--surface2); border: 1px solid var(--border); border-radius: 7px; padding: 9px 12px; color: var(--text); font-size: 13px; outline: none; transition: border-color 0.15s; }
.form-field input:focus, .form-field select:focus { border-color: var(--teal); }
.modal-actions { display: flex; gap: 10px; justify-content: flex-end; margin-top: 16px; }
.status-dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.status-dot.green { background: var(--teal); }
.status-dot.amber { background: var(--amber); }
.status-dot.red { background: var(--crimson); }
.spinner { display: inline-block; width: 14px; height: 14px; border: 2px solid var(--border); border-top-color: var(--teal); border-radius: 50%; animation: spin 0.7s linear infinite; vertical-align: middle; }
@keyframes spin { to { transform: rotate(360deg); } }
::-webkit-scrollbar { width: 5px; height: 5px; } ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 3px; }
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
    <a href="/rag" class="nav-btn"><span class="icon">&#x1F9E0;</span> Super-RAG</a>
    <a href="/mcp" class="nav-btn"><span class="icon">&#x1F9E9;</span> MCP Servers</a>
    <a href="/projects" class="nav-btn active"><span class="icon">&#x1F4C1;</span> Projects</a>
  </div>
  <div class="proj-list-nav">
    <div class="proj-list-label">My Projects</div>
    <div id="navProjList"></div>
    <button class="proj-add-btn" onclick="openAddModal('dir')">+ Add / Clone Project</button>
  </div>
</div>

<!-- File panel -->
<div class="file-panel">
  <div class="file-panel-header">
    <span class="file-panel-title" id="filePanelTitle">No project open</span>
  </div>
  <div class="file-tree" id="fileTree"><div style="padding:14px;font-size:12px;color:var(--muted)">Open a project to see its files.</div></div>
</div>

<!-- Main workspace -->
<div class="workspace">
  <div class="workspace-top">
    <span class="ws-title" id="wsTitle">Projects</span>
    <span class="ws-badge" id="wsBranch" style="display:none">&#x1F533; <span id="wsBranchName">main</span></span>
    <span class="ws-badge" id="wsPath" style="display:none;font-family:monospace;font-size:11px;color:var(--muted)"></span>
  </div>
  <div class="tab-bar">
    <div class="tab active" onclick="switchTab('chat')">&#x1F4AC; Agent Chat</div>
    <div class="tab" onclick="switchTab('file')">&#x1F4C4; File Viewer</div>
    <div class="tab" onclick="switchTab('terminal')">&#x1F4BB; Terminal</div>
    <div class="tab" onclick="switchTab('git')">&#x1F500; Git</div>
  </div>
  <div class="tab-panels">

    <!-- Chat tab -->
    <div class="tab-panel active" id="panel-chat">
      <div class="chat-messages" id="chatMessages">
        <div class="msg-row system"><div class="msg-bubble">Open a project, then ask me anything about it — review code, explain files, find bugs, add features.</div></div>
      </div>
      <div class="chat-input-bar">
        <textarea class="chat-input" id="chatInput" rows="1" placeholder="Ask about your project..." onkeydown="chatKeydown(event)"></textarea>
        <button class="send-btn" id="sendBtn" onclick="sendChat()">&#x27A4;</button>
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

    <!-- Git tab -->
    <div class="tab-panel" id="panel-git">
      <div class="git-panel" id="gitPanel">
        <div style="color:var(--muted);font-size:13px">Open a project to see git status.</div>
      </div>
    </div>

  </div>
</div>

<!-- Add / Clone modal -->
<div class="modal-overlay" id="addModal">
  <div class="modal">
    <div class="modal-title">Add Project</div>
    <div style="display:flex;gap:10px;margin-bottom:18px">
      <button class="btn btn-outline" id="tabDir" onclick="setAddMode('dir')" style="flex:1">&#x1F4C1; Open Directory</button>
      <button class="btn btn-outline" id="tabClone" onclick="setAddMode('clone')" style="flex:1">&#x2B07; Clone from GitHub</button>
    </div>
    <div id="formDir">
      <div class="form-field"><label>Project Path</label><input type="text" id="inputPath" placeholder="/home/user/my-project"></div>
      <div class="form-field"><label>Display Name (optional)</label><input type="text" id="inputName" placeholder="My Project"></div>
    </div>
    <div id="formClone" style="display:none">
      <div class="form-field"><label>GitHub Repository URL</label><input type="text" id="inputCloneUrl" placeholder="https://github.com/user/repo.git"></div>
      <div class="form-field"><label>Clone into directory</label><input type="text" id="inputCloneDest" placeholder="/home/user/projects"></div>
    </div>
    <div id="addModalMsg" style="font-size:12px;color:var(--muted);min-height:18px"></div>
    <div class="modal-actions">
      <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
      <button class="btn btn-primary" id="addModalBtn" onclick="submitAddProject()">Add Project</button>
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

// ── Tab switching ─────────────────────────────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.tab').forEach((t, i) => {
    const tabs = ['chat','file','terminal','git'];
    t.classList.toggle('active', tabs[i] === name);
  });
  document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
  document.getElementById('panel-' + name).classList.add('active');
  if (name === 'git') loadGitStatus();
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
        <span style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap" title="${esc(p.path)}">${esc(p.name)}</span>
      </div>`
    ).join('') || '<div style="padding:8px 10px;font-size:12px;color:var(--muted)">No projects yet.</div>';
  } catch(e) { console.warn('load projects error', e); }
}

async function openProject(id, path, name) {
  _activeProjectId = id;
  _activeProjectPath = path;
  _activeProjectName = name;
  document.getElementById('wsTitle').textContent = name;
  document.getElementById('wsPath').textContent = path;
  document.getElementById('wsPath').style.display = '';
  document.getElementById('filePanelTitle').textContent = name;
  document.getElementById('termPrompt').textContent = name.substring(0,12) + ' $';
  await fetch(API + '/api/projects/' + id + '/activate', { method: 'POST' });
  await loadProjects();
  await loadFileTree();
  appendSysMsg('Opened project: ' + name + ' (' + path + ')');
  const gitBadge = document.getElementById('wsBranch');
  const status = await fetch(API + '/api/projects/' + id + '/git/status').then(r => r.json()).catch(() => null);
  if (status && status.is_git) {
    document.getElementById('wsBranchName').textContent = status.branch || 'main';
    gitBadge.style.display = '';
  } else {
    gitBadge.style.display = 'none';
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
        <div class="tree-row" style="padding-left:${12 + indent}px" onclick="toggleDir('${id}', this)">
          <span class="icon" id="icon-${id}">&#x25B8;</span>
          <span style="font-size:13px">&#x1F4C2;</span>
          <span class="fname">${esc(n.name)}</span>
        </div>
        <div class="tree-children" id="${id}" style="display:none">${childHtml}</div>
      </div>`;
    } else {
      const fileIcon = getFileIcon(n.name);
      return `<div class="tree-row" style="padding-left:${12 + indent}px" onclick="openFile('${esc(n.path)}','${esc(n.name)}')">
        <span class="icon">&nbsp;</span>
        <span style="font-size:12px">${fileIcon}</span>
        <span class="fname">${esc(n.name)}</span>
        <span style="margin-left:auto;font-size:10px;color:var(--muted)">${fmtSize(n.size)}</span>
      </div>`;
    }
  }).join('');
}

function toggleDir(id, row) {
  const el = document.getElementById(id);
  const icon = document.getElementById('icon-' + id);
  const open = el.style.display !== 'none';
  el.style.display = open ? 'none' : 'block';
  icon.textContent = open ? '\u25B8' : '\u25BE';
}

async function openFile(path, name) {
  document.querySelectorAll('.tree-row').forEach(r => r.classList.remove('selected'));
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
function appendMsg(role, text) {
  const box = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = 'msg-row ' + role;
  div.innerHTML = '<div class="msg-bubble">' + esc(text).replace(/\n/g,'<br>') + '</div>';
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
  return div;
}
function appendSysMsg(text) {
  const box = document.getElementById('chatMessages');
  const div = document.createElement('div');
  div.className = 'msg-row system';
  div.innerHTML = '<div class="msg-bubble">' + esc(text) + '</div>';
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function chatKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); sendChat(); }
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
  appendMsg('user', text);
  const agentDiv = appendMsg('agent', '');
  const bubble = agentDiv.querySelector('.msg-bubble');
  bubble.innerHTML = '<span class="spinner"></span>';
  _runId = 'proj-' + Math.random().toString(36).slice(2, 10);
  try {
    const resp = await fetch(API + '/api/chat', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ text, run_id: _runId, working_directory: _activeProjectPath, channel: 'project_chat', sender_id: 'project_ui' })
    });
    const d = await resp.json();
    if (!d.run_id) { bubble.textContent = 'Error: ' + (d.error || 'No run id'); btn.disabled = false; return; }
    _runId = d.run_id;
    let collected = '';
    const sse = new EventSource(API + '/api/stream?run_id=' + encodeURIComponent(_runId));
    sse.addEventListener('result', e => {
      const data = JSON.parse(e.data || '{}');
      const reply = data.final_response || data.response || data.result || data.output || '';
      collected = reply;
      bubble.innerHTML = esc(reply).replace(/\n/g,'<br>') || '<em style="color:var(--muted)">No response</em>';
      document.getElementById('chatMessages').scrollTop = 999999;
    });
    sse.addEventListener('step', e => {
      const data = JSON.parse(e.data || '{}');
      if (!collected) bubble.innerHTML = '<span style="color:var(--muted);font-size:11px">&#x1F504; ' + esc(data.agent || 'working') + '...</span>';
    });
    sse.addEventListener('done', () => { sse.close(); btn.disabled = false; });
    sse.addEventListener('error', () => { sse.close(); if (!collected) bubble.textContent = 'Connection error'; btn.disabled = false; });
  } catch(e) { bubble.textContent = 'Error: ' + e; btn.disabled = false; }
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

// ── Git ───────────────────────────────────────────────────────────────────────
async function loadGitStatus() {
  if (!_activeProjectId) return;
  const panel = document.getElementById('gitPanel');
  panel.innerHTML = '<div style="color:var(--muted);font-size:13px"><span class="spinner"></span> Loading git status...</div>';
  try {
    const r = await fetch(API + '/api/projects/' + _activeProjectId + '/git/status');
    const s = await r.json();
    if (!s.is_git) {
      panel.innerHTML = '<div class="git-section"><div style="color:var(--muted)">&#x26A0; Not a git repository.</div><button class="btn btn-outline" style="margin-top:10px" onclick="gitRun(\'git init\')">Initialize git repo</button></div>';
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
  } catch(e) { panel.innerHTML = '<div style="color:var(--crimson)">Error: ' + e + '</div>'; }
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
let _addMode = 'dir';
function openAddModal(mode) { setAddMode(mode || 'dir'); document.getElementById('addModal').classList.add('open'); }
function closeModal() { document.getElementById('addModal').classList.remove('open'); document.getElementById('addModalMsg').textContent = ''; }
function setAddMode(mode) {
  _addMode = mode;
  document.getElementById('formDir').style.display = mode === 'dir' ? '' : 'none';
  document.getElementById('formClone').style.display = mode === 'clone' ? '' : 'none';
  document.getElementById('tabDir').style.borderColor = mode === 'dir' ? 'var(--teal)' : '';
  document.getElementById('tabDir').style.color = mode === 'dir' ? 'var(--teal)' : '';
  document.getElementById('tabClone').style.borderColor = mode === 'clone' ? 'var(--teal)' : '';
  document.getElementById('tabClone').style.color = mode === 'clone' ? 'var(--teal)' : '';
}

async function submitAddProject() {
  const msg = document.getElementById('addModalMsg');
  const btn = document.getElementById('addModalBtn');
  btn.disabled = true;
  msg.textContent = 'Working...'; msg.style.color = 'var(--muted)';
  try {
    let r, d;
    if (_addMode === 'dir') {
      const path = document.getElementById('inputPath').value.trim();
      const name = document.getElementById('inputName').value.trim();
      if (!path) { msg.textContent = 'Path is required'; msg.style.color = 'var(--crimson)'; btn.disabled = false; return; }
      r = await fetch(API + '/api/projects', { method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({ path, name }) });
    } else {
      const url = document.getElementById('inputCloneUrl').value.trim();
      const dest = document.getElementById('inputCloneDest').value.trim();
      if (!url || !dest) { msg.textContent = 'URL and destination are required'; msg.style.color = 'var(--crimson)'; btn.disabled = false; return; }
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
  await loadProjects();
  // Try to open the active project
  try {
    const r = await fetch(API + '/api/projects/active');
    const p = await r.json();
    if (p && p.id) await openProject(p.id, p.path, p.name);
  } catch(e) {}
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
    <a href="/rag" class="nav-btn active"><span class="icon">&#x1F9E0;</span> Super-RAG</a>
    <a href="/mcp" class="nav-btn"><span class="icon">&#x1F9E9;</span> MCP Servers</a>
    <a href="/projects" class="nav-btn"><span class="icon">&#x1F4C1;</span> Projects</a>
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
    <a href="/rag" class="nav-btn"><span class="icon">&#x1F9E0;</span> Super-RAG</a>
    <a href="/mcp" class="nav-btn active"><span class="icon">&#x1F9E9;</span> MCP Servers</a>
    <a href="/projects" class="nav-btn"><span class="icon">&#x1F4C1;</span> Projects</a>
  </div>
</div>
<div class="main">
  <div class="page-title">MCP Servers</div>
  <div class="page-subtitle">Connect kendr to any MCP server &mdash; kendr acts as the client, just like Cursor. Tools are auto-discovered.</div>

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
    <div class="form-full">
      <label>Description (optional)</label>
      <textarea id="addDesc" rows="2" placeholder="What does this server provide?"></textarea>
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
  const msg = document.getElementById('addMsg');
  if (!name) { showMsg(msg, 'Server name is required', 'err'); return; }
  if (!conn) { showMsg(msg, 'Connection is required', 'err'); return; }
  showMsg(msg, '<span class="disc-spinner"></span> Connecting and discovering tools…', 'ok');
  try {
    const r = await fetch(API + '/api/mcp/servers', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({ name, type, connection: conn, description: desc })
    });
    const d = await r.json();
    if (d.ok || d.server_id) {
      showMsg(msg, '&#x2713; Connected — ' + (d.tool_count || 0) + ' tool(s) discovered', 'ok');
      document.getElementById('addName').value = '';
      document.getElementById('addConn').value = '';
      document.getElementById('addDesc').value = '';
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

function esc(s) { return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

loadServers();
loadScaffold();
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
    <a href="/rag" class="nav-btn"><span class="icon">&#x1F9E0;</span> Super-RAG</a>
    <a href="/mcp" class="nav-btn"><span class="icon">&#x1F9E9;</span> MCP Servers</a>
    <a href="/projects" class="nav-btn"><span class="icon">&#x1F4C1;</span> Projects</a>
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
        pass

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
        if path == "/projects":
            self._html(200, _PROJECTS_HTML)
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
            if not run_id or not name or "/" in name or "\\" in name or name.startswith("."):
                self._json(400, {"error": "invalid_request"})
                return
            try:
                run_row = _db_get_run(run_id)
                output_dir = run_row.get("run_output_dir", "") if run_row else ""
            except Exception:
                output_dir = ""
            if not output_dir:
                self._json(404, {"error": "run_not_found_or_no_output_dir"})
                return
            file_path = os.path.join(output_dir, name)
            if not os.path.isfile(file_path):
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
        if path == "/api/projects/file":
            params = parse_qs(parsed.query or "")
            file_path = (params.get("path") or [""])[0]
            project_root = (params.get("root") or [""])[0]
            self._handle_project_read_file(file_path, project_root)
            return
        if path.startswith("/api/projects/") and path.endswith("/files"):
            project_id = path[len("/api/projects/"):-len("/files")]
            self._handle_project_file_tree(project_id)
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
        if path == "/api/projects/shell":
            self._handle_project_shell(body)
            return
        if path.startswith("/api/projects/") and path.endswith("/activate"):
            project_id = path[len("/api/projects/"):-len("/activate")]
            self._handle_project_activate(project_id)
            return
        if path.startswith("/api/projects/") and path.endswith("/remove"):
            project_id = path[len("/api/projects/"):-len("/remove")]
            self._handle_project_remove(project_id)
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
            # multipart handled separately; body is empty here — handled in do_POST via raw read
            self._handle_rag_upload(body)
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
            "chat_id": str(body.get("chat_id", "web_chat_1")),
        }
        if working_directory:
            payload["working_directory"] = working_directory
        if project_build_mode:
            payload["project_build_mode"] = True
        for key in ("project_name", "project_stack", "stack", "project_root",
                    "github_repo", "auto_approve", "skip_test_agent", "skip_devops_agent"):
            if body.get(key) is not None:
                payload[key] = body[key]
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
        if not name or not connection:
            self._json(400, {"error": "name and connection are required"})
            return
        try:
            entry = _mcp_add_server(name, connection, server_type, description)
            server_id = entry["id"]
            result = _mcp_discover_tools(server_id)
            result["server"] = _mcp_get_server(server_id)
            self._json(200, result)
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

    def _handle_rag_upload(self, body: dict) -> None:
        if not self._rag_check():
            return
        self._json(400, {"error": "Use multipart/form-data POST to /api/rag/upload with fields: file, kb_id"})

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
    server.serve_forever()


if __name__ == "__main__":
    main()
