from __future__ import annotations

import html
import json
import os
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from kendr import AgentRuntime, build_registry
from kendr.http import (
    build_resume_state_overrides,
    infer_resume_working_directory,
    resume_candidate_requires_branch,
    resume_candidate_requires_force,
    resume_candidate_requires_reply,
    session_id_for_payload,
)
from kendr.persistence import (
    get_run,
    list_channel_sessions,
    list_heartbeat_events,
    list_monitor_events,
    list_monitor_rules,
    list_privileged_audit_events,
    list_recent_runs,
    list_scheduled_jobs,
    list_task_sessions,
)
from kendr.recovery import discover_resume_candidates, load_resume_candidate


REGISTRY = build_registry()
RUNTIME = AgentRuntime(REGISTRY)
SKILL_REGISTRY = RUNTIME.skill_registry


def _html_page(title: str, body: str) -> bytes:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{html.escape(title)}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 32px; line-height: 1.5; }}
    .grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 16px; }}
    .card {{ border: 1px solid #ddd; border-radius: 8px; padding: 16px; }}
    code, pre {{ background: #f5f5f5; border-radius: 6px; padding: 4px 6px; }}
    pre {{ white-space: pre-wrap; }}
  </style>
</head>
<body>
{body}
</body>
</html>""".encode("utf-8")


class GatewayHandler(BaseHTTPRequestHandler):
    def _send_json(self, status: int, payload: dict | list):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, status: int, title: str, body: str):
        page = _html_page(title, body)
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(page)))
        self.end_headers()
        self.wfile.write(page)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self._handle_home()
            return
        if parsed.path == "/health":
            self._send_json(200, {"status": "ok"})
            return
        if parsed.path == "/registry/skills":
            cards = SKILL_REGISTRY.get_all_cards()
            summary = SKILL_REGISTRY.summary()
            self._send_json(200, {
                "summary": summary,
                "cards": [c.to_dict() for c in cards],
            })
            return
        if parsed.path == "/registry/agents":
            self._send_json(
                200,
                [
                    {
                        "name": agent.name,
                        "description": agent.description,
                        "plugin": agent.plugin_name,
                        "skills": agent.skills,
                    }
                    for agent in REGISTRY.agents.values()
                ],
            )
            return
        if parsed.path == "/registry/plugins":
            self._send_json(
                200,
                [
                    {
                        "name": plugin.name,
                        "source": plugin.source,
                        "description": plugin.description,
                        "version": plugin.version,
                        "sdk_version": plugin.sdk_version,
                        "runtime_api": plugin.runtime_api,
                        "kind": plugin.kind,
                    }
                    for plugin in REGISTRY.plugins.values()
                ],
            )
            return
        if parsed.path == "/runs":
            self._send_json(200, list_recent_runs())
            return
        if parsed.path.startswith("/runs/"):
            run_id = parsed.path.split("/runs/", 1)[1].strip()
            if not run_id:
                self._send_json(400, {"error": "missing_run_id"})
                return
            match = get_run(run_id)
            if not match:
                self._send_json(404, {"error": "run_not_found", "run_id": run_id})
                return
            self._send_json(200, match)
            return
        if parsed.path == "/resume-candidates":
            params = parse_qs(parsed.query or "")
            search_path = str((params.get("path") or [""])[0] or "").strip()
            if not search_path:
                self._send_json(400, {"error": "missing_path", "detail": "Provide ?path=<output-folder-or-working-directory>."})
                return
            limit = int(str((params.get("limit") or ["20"])[0] or "20"))
            self._send_json(200, discover_resume_candidates(search_path, limit=limit))
            return
        if parsed.path == "/sessions":
            self._send_json(200, list_channel_sessions())
            return
        if parsed.path == "/jobs":
            self._send_json(200, list_scheduled_jobs())
            return
        if parsed.path == "/task-sessions":
            self._send_json(200, list_task_sessions())
            return
        if parsed.path.startswith("/task-sessions/by-run/"):
            run_id = parsed.path.split("/task-sessions/by-run/", 1)[1].strip()
            if not run_id:
                self._send_json(400, {"error": "missing_run_id"})
                return
            sessions = [item for item in list_task_sessions(500) if str(item.get("run_id", "")) == run_id]
            if not sessions:
                self._send_json(404, {"error": "task_session_not_found", "run_id": run_id})
                return
            self._send_json(200, sessions[0])
            return
        if parsed.path == "/monitors":
            self._send_json(200, list_monitor_rules())
            return
        if parsed.path == "/monitor-events":
            self._send_json(200, list_monitor_events())
            return
        if parsed.path == "/heartbeats":
            self._send_json(200, list_heartbeat_events())
            return
        if parsed.path == "/audit/privileged":
            self._send_json(200, list_privileged_audit_events())
            return
        self._send_json(404, {"error": "not_found"})

    def do_POST(self):
        if self.path not in {"/ingest", "/resume"}:
            self._send_json(404, {"error": "not_found"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0") or 0)
            raw = self.rfile.read(content_length)
            payload = json.loads(raw.decode("utf-8")) if raw else {}
            if not isinstance(payload, dict):
                raise ValueError("JSON body must be an object.")
        except Exception as exc:
            self._send_json(400, {"error": "invalid_json", "detail": str(exc)})
            return

        if self.path == "/resume":
            search_path = str(
                payload.get("output_folder")
                or payload.get("working_directory")
                or payload.get("path")
                or ""
            ).strip()
            if not search_path:
                self._send_json(400, {"error": "missing_path", "detail": "Provide output_folder, working_directory, or path."})
                return
            candidate = load_resume_candidate(search_path)
            if not candidate:
                self._send_json(404, {"error": "resume_candidate_not_found", "path": search_path})
                return

            branch = bool(payload.get("branch", False))
            force = bool(payload.get("force", False))
            if resume_candidate_requires_branch(candidate, branch=branch):
                self._send_json(409, {"error": "completed_run_requires_branch", "candidate": candidate})
                return
            if resume_candidate_requires_force(candidate, force=force):
                self._send_json(409, {"error": "takeover_required", "candidate": candidate})
                return
            if resume_candidate_requires_reply(candidate):
                pending_text = str(payload.get("reply") or payload.get("text") or "").strip()
                if not pending_text:
                    self._send_json(409, {"error": "reply_required", "candidate": candidate})
                    return
                text = pending_text
            else:
                text = str(payload.get("text") or payload.get("message") or payload.get("user_query") or "").strip() or "resume"

            working_directory = infer_resume_working_directory(candidate)
            if not working_directory:
                self._send_json(400, {"error": "working_directory_required", "candidate": candidate})
                return

            state_overrides = build_resume_state_overrides(
                candidate,
                branch=branch,
                working_directory=working_directory,
                incoming_channel=str(payload.get("channel", "webchat") or "webchat"),
                incoming_sender_id=str(payload.get("sender_id", "") or ""),
                incoming_chat_id=str(payload.get("chat_id", "") or ""),
                incoming_workspace_id=str(payload.get("workspace_id", "") or ""),
                incoming_is_group=bool(payload.get("is_group", False)),
            )
        else:
            text = str(payload.get("text") or payload.get("message") or payload.get("user_query") or "").strip()
            if not text:
                self._send_json(400, {"error": "missing_text", "detail": "Provide text, message, or user_query."})
                return
        force_new_session = bool(payload.get("new_session", False) or text.lower() == "/new")
        if text.lower() == "/new":
            text = str(payload.get("next_text") or "Started a new session.")
        working_directory = str(
            (state_overrides.get("working_directory", "") if self.path == "/resume" else payload.get("working_directory"))
            or os.getenv("KENDR_WORKING_DIR", "")
        ).strip()
        if not working_directory:
            self._send_json(
                400,
                {
                    "error": "working_directory_required",
                    "detail": (
                        "Working folder is required before tasks can run. "
                        "Configure KENDR_WORKING_DIR in Setup UI (Core Runtime) "
                        "or send working_directory in this request."
                    ),
                    "setup_url": "/component/core_runtime",
                },
            )
            return

        if self.path != "/resume":
            state_overrides = {
                "run_id": str(payload.get("run_id", "")).strip(),
                "max_steps": int(payload.get("max_steps", 20)),
                "incoming_channel": payload.get("channel", "webchat"),
                "incoming_sender_id": payload.get("sender_id", ""),
                "incoming_chat_id": payload.get("chat_id", ""),
                "incoming_workspace_id": payload.get("workspace_id", ""),
                "incoming_text": text,
                "incoming_is_group": bool(payload.get("is_group", False)),
                "incoming_mentions_assistant": bool(payload.get("mentions_assistant", False)),
                "incoming_payload": payload,
                "session_id": session_id_for_payload(payload, force_new=force_new_session),
                "channel_session_key": session_id_for_payload(payload, force_new=False),
                "memory_force_new_session": force_new_session,
                "working_directory": working_directory,
            }
        else:
            state_overrides["max_steps"] = int(payload.get("max_steps", 20))
            state_overrides["incoming_text"] = text
            state_overrides["incoming_mentions_assistant"] = bool(payload.get("mentions_assistant", False))
            state_overrides["incoming_payload"] = payload
        if not str(state_overrides.get("run_id", "")).strip():
            state_overrides.pop("run_id", None)
        passthrough_keys = [
            "privileged_mode",
            "privileged_approved",
            "privileged_approval_note",
            "privileged_require_approvals",
            "privileged_read_only",
            "privileged_allow_root",
            "privileged_allow_destructive",
            "privileged_enable_backup",
            "privileged_allowed_paths",
            "privileged_allowed_domains",
            "kill_switch_file",
            "auto_approve",
            "auto_approve_blueprint",
            "auto_approve_plan",
            "skip_reviews",
            "max_step_revisions",
            "long_document_mode",
            "long_document_pages",
            "long_document_sections",
            "long_document_section_pages",
            "long_document_title",
            "long_document_collect_sources_first",
            "long_document_disable_visuals",
            "long_document_section_search",
            "long_document_section_search_results",
            "research_max_wait_seconds",
            "research_poll_interval_seconds",
            "research_max_tool_calls",
            "research_max_output_tokens",
            "research_model",
            "research_instructions",
            "research_heartbeat_seconds",
            "local_drive_paths",
            "local_drive_recursive",
            "local_drive_include_hidden",
            "local_drive_max_files",
            "local_drive_extensions",
            "local_drive_enable_image_ocr",
            "local_drive_ocr_instruction",
            "local_drive_working_directory",
            "local_drive_index_to_memory",
            "local_drive_auto_generate_extension_handlers",
            "local_drive_force_long_document",
            "codebase_mode",
            "superrag_mode",
            "superrag_action",
            "superrag_session_id",
            "superrag_new_session",
            "superrag_session_title",
            "superrag_local_paths",
            "superrag_paths",
            "superrag_local_recursive",
            "superrag_local_include_hidden",
            "superrag_local_max_files",
            "superrag_local_extensions",
            "superrag_include_working_directory",
            "superrag_urls",
            "superrag_url_max_pages",
            "superrag_url_same_domain",
            "superrag_db_url",
            "superrag_db_schema",
            "superrag_db_tables",
            "superrag_db_sample_rows",
            "superrag_db_max_tables",
            "superrag_onedrive_enabled",
            "superrag_onedrive_path",
            "superrag_onedrive_max_files",
            "superrag_onedrive_max_download_mb",
            "superrag_chat_query",
            "superrag_top_k",
            "superrag_chunk_size",
            "superrag_chunk_overlap",
        ]
        for key in passthrough_keys:
            if key in payload:
                state_overrides[key] = payload.get(key)
        if bool(payload.get("security_authorized", False)):
            state_overrides["security_authorized"] = True
        if payload.get("security_target_url"):
            state_overrides["security_target_url"] = str(payload.get("security_target_url")).strip()
        if payload.get("security_authorization_note"):
            state_overrides["security_authorization_note"] = str(payload.get("security_authorization_note")).strip()
        if payload.get("security_scan_profile"):
            state_overrides["security_scan_profile"] = str(payload.get("security_scan_profile")).strip().lower()
        try:
            result = RUNTIME.run_query(text, state_overrides=state_overrides)
            awaiting_user_input = bool(
                result.get("plan_needs_clarification", False)
                or result.get("plan_waiting_for_approval", False)
                or result.get("long_document_plan_waiting_for_approval", False)
                or str(result.get("pending_user_input_kind", "")).strip()
            )
            self._send_json(
                200,
                {
                    "run_id": result.get("run_id"),
                    "output_dir": result.get("run_output_dir", ""),
                    "final_output": result.get("final_output") or result.get("draft_response", ""),
                    "last_agent": result.get("last_agent", ""),
                    "status": "awaiting_user_input" if awaiting_user_input else "completed",
                    "awaiting_user_input": awaiting_user_input,
                    "pending_user_input_kind": result.get("pending_user_input_kind", ""),
                    "pending_user_question": result.get("pending_user_question", ""),
                    "resume_candidate": candidate if self.path == "/resume" else {},
                },
            )
        except Exception as exc:
            self._send_json(500, {"error": "workflow_failed", "detail": str(exc)})

    def _handle_home(self):
        agents = list(REGISTRY.agents.values())
        plugins = list(REGISTRY.plugins.values())
        runs = list_recent_runs(8)
        sessions = list_channel_sessions(8)
        jobs = list_scheduled_jobs(8)
        task_sessions = list_task_sessions(8)
        monitors = list_monitor_rules(8)
        heartbeats = list_heartbeat_events(8)
        body = f"""
        <h1>Kendr Gateway</h1>
        <p>Plugin-driven agent runtime with dynamic discovery, CLI control, and HTTP ingress.</p>
        <div class="grid">
          <div class="card">
            <h2>Registry</h2>
            <p>Agents: <strong>{len(agents)}</strong></p>
            <p>Plugins: <strong>{len(plugins)}</strong></p>
            <p><a href="/registry/agents">/registry/agents</a></p>
            <p><a href="/registry/plugins">/registry/plugins</a></p>
          </div>
          <div class="card">
            <h2>Gateway</h2>
            <p>POST channel payloads to <code>/ingest</code>.</p>
<pre>{html.escape(json.dumps({"channel": "webchat", "sender_id": "u1", "chat_id": "c1", "text": "hello"}, indent=2))}</pre>
          </div>
          <div class="card">
            <h2>Activity</h2>
            <p><a href="/runs">/runs</a></p>
            <p><a href="/sessions">/sessions</a></p>
            <p><a href="/task-sessions">/task-sessions</a></p>
            <p><a href="/resume-candidates?path=output">/resume-candidates?path=output</a></p>
            <p><a href="/jobs">/jobs</a></p>
            <p><a href="/monitors">/monitors</a></p>
            <p><a href="/monitor-events">/monitor-events</a></p>
            <p><a href="/heartbeats">/heartbeats</a></p>
            <p><a href="/audit/privileged">/audit/privileged</a></p>
          </div>
        </div>
        <div class="grid">
          <div class="card">
            <h2>Recent Runs</h2>
            <pre>{html.escape(json.dumps(runs, indent=2, ensure_ascii=False))}</pre>
          </div>
          <div class="card">
            <h2>Recent Sessions</h2>
            <pre>{html.escape(json.dumps(sessions, indent=2, ensure_ascii=False))}</pre>
          </div>
          <div class="card">
            <h2>Task Sessions</h2>
            <pre>{html.escape(json.dumps(task_sessions, indent=2, ensure_ascii=False))}</pre>
          </div>
          <div class="card">
            <h2>Scheduled Jobs</h2>
            <pre>{html.escape(json.dumps(jobs, indent=2, ensure_ascii=False))}</pre>
          </div>
          <div class="card">
            <h2>Monitor Rules</h2>
            <pre>{html.escape(json.dumps(monitors, indent=2, ensure_ascii=False))}</pre>
          </div>
          <div class="card">
            <h2>Heartbeats</h2>
            <pre>{html.escape(json.dumps(heartbeats, indent=2, ensure_ascii=False))}</pre>
          </div>
        </div>
        """
        self._send_html(200, "Kendr Gateway", body)


def main() -> None:
    import threading as _threading

    host = os.getenv("GATEWAY_HOST", "127.0.0.1")
    port = int(os.getenv("GATEWAY_PORT", "8790"))
    server = ThreadingHTTPServer((host, port), GatewayHandler)
    print(f"Gateway server running at http://{host}:{port}")

    if os.getenv("KENDR_UI_ENABLED", "1") != "0":
        def _start_ui() -> None:
            try:
                from kendr.ui_server import main as _ui_main
                _ui_main()
            except OSError as exc:
                if "Address already in use" in str(exc):
                    pass
                else:
                    print(f"[kendr-ui] startup error: {exc}")
            except Exception as exc:
                print(f"[kendr-ui] startup error: {exc}")

        _ui_thread = _threading.Thread(target=_start_ui, daemon=True, name="kendr-ui")
        _ui_thread.start()

    server.serve_forever()


if __name__ == "__main__":
    main()
