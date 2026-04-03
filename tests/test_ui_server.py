from __future__ import annotations

import io
import json
import os
import socket
import tempfile
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")


class TestSecretSentinelHandling(unittest.TestCase):
    def test_save_component_values_skips_masked_sentinel(self):
        from tasks.setup_config_store import save_component_values

        with (
            patch("tasks.setup_config_store.get_component") as mock_get,
            patch("tasks.setup_config_store.upsert_setup_config_value") as mock_upsert,
            patch("tasks.setup_config_store.delete_setup_config_value"),
            patch("tasks.setup_config_store.get_setup_component_snapshot") as mock_snap,
        ):
            mock_get.return_value = {
                "id": "test_comp",
                "fields": [
                    {"key": "API_KEY", "secret": True},
                    {"key": "MODEL_NAME", "secret": False},
                ],
            }
            mock_snap.return_value = {
                "component": {"id": "test_comp", "fields": []},
                "values": {},
                "enabled": True,
                "notes": "",
                "updated_at": "",
                "filled_fields": 0,
                "total_fields": 2,
            }
            save_component_values("test_comp", {
                "API_KEY": "********",
                "MODEL_NAME": "gpt-4o",
            })

            calls = [c.args[1] for c in mock_upsert.call_args_list]
            self.assertNotIn("API_KEY", calls, "Secret sentinel must not be saved")
            self.assertIn("MODEL_NAME", calls, "Non-secret field must be saved")

    def test_save_component_values_updates_non_sentinel_secret(self):
        from tasks.setup_config_store import save_component_values

        with (
            patch("tasks.setup_config_store.get_component") as mock_get,
            patch("tasks.setup_config_store.upsert_setup_config_value") as mock_upsert,
            patch("tasks.setup_config_store.delete_setup_config_value"),
            patch("tasks.setup_config_store.get_setup_component_snapshot") as mock_snap,
        ):
            mock_get.return_value = {
                "id": "test_comp",
                "fields": [{"key": "API_KEY", "secret": True}],
            }
            mock_snap.return_value = {
                "component": {"id": "test_comp", "fields": []},
                "values": {},
                "enabled": True,
                "notes": "",
                "updated_at": "",
                "filled_fields": 0,
                "total_fields": 1,
            }
            save_component_values("test_comp", {"API_KEY": "sk-new-real-key"})

            calls = [c.args[1] for c in mock_upsert.call_args_list]
            self.assertIn("API_KEY", calls, "New real secret value must be persisted")


class TestUICmdHealthProbe(unittest.TestCase):
    def _make_running_check(self):
        import urllib.request as _req
        import json as _json

        def _kendr_ui_running(port: int, host: str) -> bool:
            _probe_hosts = ["127.0.0.1"]
            if host not in ("0.0.0.0", "", "127.0.0.1"):
                _probe_hosts.append(host)
            for _h in _probe_hosts:
                try:
                    with _req.urlopen(f"http://{_h}:{port}/api/health", timeout=1) as r:
                        data = _json.loads(r.read())
                        if data.get("service") == "kendr-ui":
                            return True
                except Exception:
                    pass
            return False

        return _kendr_ui_running

    def test_detects_kendr_ui_on_loopback(self):
        from kendr.ui_server import KendrUIHandler

        srv = ThreadingHTTPServer(("127.0.0.1", 0), KendrUIHandler)
        _, port = srv.server_address

        t = threading.Thread(target=srv.handle_request, daemon=True)
        t.start()

        try:
            check = self._make_running_check()
            result = check(port, "0.0.0.0")
        finally:
            srv.server_close()
            t.join(timeout=3)

        self.assertTrue(result, "Should detect running kendr-ui via /api/health probe")

    def test_returns_false_for_non_kendr_service(self):
        class _DummyHandler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"service": "other"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        srv = ThreadingHTTPServer(("127.0.0.1", 0), _DummyHandler)
        _, port = srv.server_address
        t = threading.Thread(target=srv.handle_request, daemon=True)
        t.start()
        try:
            check = self._make_running_check()
            result = check(port, "0.0.0.0")
        finally:
            srv.server_close()
            t.join(timeout=3)

        self.assertFalse(result, "Must not detect non-kendr service as kendr-ui")

    def test_returns_false_when_nothing_listening(self):
        tmp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        tmp.bind(("127.0.0.1", 0))
        _, port = tmp.getsockname()
        tmp.close()

        check = self._make_running_check()
        result = check(port, "0.0.0.0")
        self.assertFalse(result, "Should return False when no server is listening")


class TestUIRequestLogging(unittest.TestCase):
    def test_log_message_writes_request_summary(self):
        from kendr.ui_server import KendrUIHandler

        handler = object.__new__(KendrUIHandler)
        handler.client_address = ("127.0.0.1", 32100)

        with patch("kendr.ui_server._log") as mock_log:
            handler.log_message('"%s" %s %s', "GET /api/health HTTP/1.1", "200", "17")

        mock_log.info.assert_called_once()
        logged = mock_log.info.call_args.args[1:]
        self.assertIn("127.0.0.1", logged[0])


class TestUIStepFormatting(unittest.TestCase):
    def test_format_step_includes_timing_and_failure_reason(self):
        import kendr.ui_server as ui_server

        step = {
            "execution_id": 42,
            "agent_name": "planner_agent",
            "status": "failed",
            "reason": "Create a detailed step-by-step plan before execution.",
            "output_excerpt": "Planner failed while calling provider 'openai' with model 'gpt-4o-mini' (APIConnectionError): Connection error.",
            "timestamp": "2026-04-03T10:00:00+00:00",
            "completed_at": "2026-04-03T10:00:02.500000+00:00",
        }

        formatted = ui_server._format_step(step)

        self.assertEqual(formatted["execution_id"], 42)
        self.assertEqual(formatted["started_at"], step["timestamp"])
        self.assertEqual(formatted["completed_at"], step["completed_at"])
        self.assertEqual(formatted["duration_ms"], 2500)
        self.assertEqual(formatted["duration_label"], "2.5s")
        self.assertIn("Connection error", formatted["failure_reason"])


class TestProjectActivityFormatting(unittest.TestCase):
    def test_project_activity_event_includes_actor_and_duration(self):
        import kendr.ui_server as ui_server

        event = ui_server._project_activity_event(
            kind="analysis",
            title="Calling project analysis model",
            actor="project_ask",
            status="completed",
            task="Inspect project and answer the question",
            subtask="Answer project question",
            started_at="2026-04-03T10:00:00+00:00",
            completed_at="2026-04-03T10:00:01.250000+00:00",
        )

        self.assertEqual(event["actor"], "project_ask")
        self.assertEqual(event["duration_ms"], 1250)
        self.assertEqual(event["duration_label"], "1.2s")

    def test_project_activity_event_keeps_running_events_open(self):
        import kendr.ui_server as ui_server

        event = ui_server._project_activity_event(
            kind="command",
            title="Running terminal command",
            status="running",
            command="git status",
            cwd="/workspace",
        )

        self.assertEqual(event["status"], "running")
        self.assertEqual(event["completed_at"], "")
        self.assertEqual(event["command"], "git status")


class TestChatHtmlExecutionLens(unittest.TestCase):
    def test_chat_html_includes_execution_lens_surface(self):
        import kendr.ui_server as ui_server

        self.assertIn("Execution Lens", ui_server._CHAT_HTML)
        self.assertIn("chatInspectorActivityList", ui_server._CHAT_HTML)
        self.assertIn("chatCommandTrack", ui_server._CHAT_HTML)

    def test_chat_html_includes_collapsible_deep_research_panel(self):
        import kendr.ui_server as ui_server

        self.assertIn("deepResearchToggleBtn", ui_server._CHAT_HTML)
        self.assertIn("deepResearchPanelBody", ui_server._CHAT_HTML)
        self.assertIn("toggleDeepResearchPanel()", ui_server._CHAT_HTML)
        self.assertIn("updateDeepResearchPanelSummary()", ui_server._CHAT_HTML)

    def test_chat_html_includes_approval_modal(self):
        import kendr.ui_server as ui_server

        self.assertIn("chatApprovalModal", ui_server._CHAT_HTML)
        self.assertIn("_submitChatApproval('approve')", ui_server._CHAT_HTML)
        self.assertIn("Send Suggestion", ui_server._CHAT_HTML)


class TestProjectsHtmlApprovalModal(unittest.TestCase):
    def test_projects_html_includes_approval_modal(self):
        import kendr.ui_server as ui_server

        self.assertIn("projectApprovalModal", ui_server._PROJECTS_HTML)
        self.assertIn("_submitProjectApproval('approve')", ui_server._PROJECTS_HTML)
        self.assertIn("Suggestion", ui_server._PROJECTS_HTML)


class TestGatewayTimeoutHelpers(unittest.TestCase):
    def test_gateway_long_timeout_accepts_zero_as_unbounded(self):
        import kendr.ui_server as ui_server

        with patch.dict(os.environ, {"KENDR_GATEWAY_LONG_TIMEOUT_SECONDS": "0"}, clear=False):
            self.assertIsNone(ui_server._gateway_long_timeout_seconds())


class TestLiveRunOverlay(unittest.TestCase):
    def test_live_recent_runs_prefers_running_pending_state(self):
        import kendr.ui_server as ui_server

        runs = [{
            "run_id": "run-1",
            "user_query": "Old query",
            "status": "completed",
            "started_at": "2026-04-03T10:00:00+00:00",
            "updated_at": "2026-04-03T10:01:00+00:00",
            "completed_at": "2026-04-03T10:01:00+00:00",
        }]
        pending = {
            "run_id": "run-1",
            "status": "running",
            "started_at": "2026-04-03T10:00:00+00:00",
            "updated_at": "2026-04-03T10:02:00+00:00",
            "completed_at": "",
            "payload": {"text": "Fresh query", "working_directory": "/tmp/demo"},
        }

        with patch.dict("kendr.ui_server._pending_runs", {"run-1": pending}, clear=True):
            merged = ui_server._live_recent_runs(runs)

        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0]["status"], "running")
        self.assertEqual(merged[0]["user_query"], "Old query")
        self.assertEqual(merged[0]["working_directory"], "/tmp/demo")
        self.assertEqual(merged[0]["completed_at"], "")

    def test_live_run_marks_awaiting_input_from_pending_result(self):
        import kendr.ui_server as ui_server

        run_row = {
            "run_id": "run-2",
            "user_query": "Need approval",
            "status": "running",
            "started_at": "2026-04-03T10:00:00+00:00",
            "updated_at": "2026-04-03T10:01:00+00:00",
            "completed_at": "",
        }
        pending = {
            "run_id": "run-2",
            "status": "completed",
            "started_at": "2026-04-03T10:00:00+00:00",
            "updated_at": "2026-04-03T10:02:00+00:00",
            "completed_at": "2026-04-03T10:02:00+00:00",
            "payload": {"text": "Need approval"},
            "result": {"awaiting_user_input": True, "pending_user_input_kind": "approval"},
        }

        with patch.dict("kendr.ui_server._pending_runs", {"run-2": pending}, clear=True):
            merged = ui_server._live_run(run_row)

        self.assertEqual(merged["status"], "awaiting_user_input")
        self.assertTrue(merged["awaiting_user_input"])


class TestUIServerRawValuesStripped(unittest.TestCase):
    def setUp(self):
        self._patch_snapshot = patch(
            "kendr.ui_server.get_setup_component_snapshot",
            return_value={
                "component": {"id": "core_runtime", "fields": []},
                "enabled": True,
                "notes": "",
                "updated_at": "",
                "values": {"API_KEY": "********"},
                "raw_values": {"API_KEY": "sk-real-secret"},
                "filled_fields": 1,
                "total_fields": 1,
            },
        )
        self._patch_overview = patch(
            "kendr.ui_server.setup_overview", return_value=[]
        )
        self._patch_oauth = patch(
            "kendr.ui_server._OAUTH_PATH_MAP", {}
        )
        self._patch_snapshot.start()
        self._patch_overview.start()
        self._patch_oauth.start()

    def tearDown(self):
        self._patch_snapshot.stop()
        self._patch_overview.stop()
        self._patch_oauth.stop()

    def test_raw_values_not_in_component_api_response(self):
        from kendr.ui_server import KendrUIHandler
        from http.client import HTTPConnection

        srv = ThreadingHTTPServer(("127.0.0.1", 0), KendrUIHandler)
        _, port = srv.server_address
        t = threading.Thread(target=srv.handle_request, daemon=True)
        t.start()

        try:
            conn = HTTPConnection("127.0.0.1", port)
            conn.request("GET", "/api/setup/component/core_runtime")
            resp = conn.getresponse()
            body = json.loads(resp.read())
            conn.close()
        finally:
            srv.server_close()
            t.join(timeout=2)

        self.assertNotIn("raw_values", body, "raw_values must not appear in API response")
        self.assertIn("values", body, "masked values must still be present")
        self.assertNotEqual(body.get("values", {}).get("API_KEY"), "sk-real-secret",
                            "Plaintext secret must not appear in response")


class TestSetupSaveRawValuesStripped(unittest.TestCase):
    def test_save_endpoint_does_not_return_raw_values(self):
        from kendr.ui_server import KendrUIHandler
        from http.client import HTTPConnection

        save_result = {
            "component": {"id": "core_runtime", "fields": [{"key": "API_KEY", "secret": True}]},
            "enabled": True,
            "notes": "",
            "updated_at": "",
            "values": {"API_KEY": "********"},
            "raw_values": {"API_KEY": "sk-real-secret"},
            "filled_fields": 1,
            "total_fields": 1,
        }

        with (
            patch("kendr.ui_server.save_component_values", return_value=save_result),
            patch("kendr.ui_server.apply_setup_env_defaults"),
        ):
            srv = ThreadingHTTPServer(("127.0.0.1", 0), KendrUIHandler)
            _, port = srv.server_address
            t = threading.Thread(target=srv.handle_request, daemon=True)
            t.start()
            try:
                conn = HTTPConnection("127.0.0.1", port, timeout=3)
                payload = json.dumps({"component_id": "core_runtime", "values": {"API_KEY": "sk-new"}}).encode()
                conn.request("POST", "/api/setup/save", body=payload,
                             headers={"Content-Type": "application/json", "Content-Length": str(len(payload))})
                resp = conn.getresponse()
                body = json.loads(resp.read())
                conn.close()
            finally:
                srv.server_close()
                t.join(timeout=3)

        self.assertEqual(resp.status, 200)
        self.assertTrue(body.get("saved"))
        snapshot = body.get("snapshot", {})
        self.assertNotIn("raw_values", snapshot, "raw_values must be stripped from /api/setup/save response")
        self.assertNotEqual(snapshot.get("values", {}).get("API_KEY"), "sk-real-secret",
                            "Plaintext secret must not appear in save response")


class TestHealthEndpoint(unittest.TestCase):
    def test_health_returns_kendr_ui_service(self):
        from kendr.ui_server import KendrUIHandler
        from http.client import HTTPConnection

        srv = ThreadingHTTPServer(("127.0.0.1", 0), KendrUIHandler)
        _, port = srv.server_address

        t = threading.Thread(target=srv.handle_request, daemon=True)
        t.start()
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("GET", "/api/health")
            resp = conn.getresponse()
            body = json.loads(resp.read())
            conn.close()
        finally:
            srv.server_close()
            t.join(timeout=3)

        self.assertEqual(resp.status, 200)
        self.assertEqual(body.get("service"), "kendr-ui")
        self.assertEqual(body.get("status"), "ok")


class TestUIModelInventory(unittest.TestCase):
    def test_models_endpoint_uses_ready_provider_when_configured_provider_is_offline(self):
        from kendr.ui_server import KendrUIHandler
        from http.client import HTTPConnection

        with (
            patch("kendr.llm_router.get_active_provider", return_value="ollama"),
            patch("kendr.llm_router.get_model_for_provider", side_effect=lambda provider, role="general": {
                "ollama": "llama3.2",
                "openai": "gpt-5.1",
            }.get(provider, "gpt-4o-mini")),
            patch("kendr.llm_router.is_ollama_running", return_value=False),
            patch("kendr.llm_router.list_ollama_models", return_value=[]),
            patch("kendr.llm_router.all_provider_statuses", return_value=[
                {"provider": "ollama", "ready": False, "model": "llama3.2", "note": "Not running"},
                {"provider": "openai", "ready": True, "model": "gpt-5.1", "note": "API key configured"},
            ]),
        ):
            srv = ThreadingHTTPServer(("127.0.0.1", 0), KendrUIHandler)
            _, port = srv.server_address
            t = threading.Thread(target=srv.handle_request, daemon=True)
            t.start()
            try:
                conn = HTTPConnection("127.0.0.1", port, timeout=3)
                conn.request("GET", "/api/models")
                resp = conn.getresponse()
                body = json.loads(resp.read())
                conn.close()
            finally:
                srv.server_close()
                t.join(timeout=3)

        self.assertEqual(resp.status, 200)
        self.assertEqual(body.get("configured_provider"), "ollama")
        self.assertFalse(body.get("configured_provider_ready"))
        self.assertEqual(body.get("active_provider"), "openai")
        self.assertEqual(body.get("active_model"), "gpt-5.1")


class TestUIChatPayloads(unittest.TestCase):
    def test_chat_endpoint_forwards_provider_and_model_to_runtime_payload(self):
        from kendr.ui_server import KendrUIHandler
        from http.client import HTTPConnection

        captured = {}

        def _capture(run_id, payload):
            captured["run_id"] = run_id
            captured["payload"] = dict(payload)

        with patch("kendr.ui_server._gateway_ready", return_value=True), patch("kendr.ui_server._start_run_background", side_effect=_capture):
            srv = ThreadingHTTPServer(("127.0.0.1", 0), KendrUIHandler)
            _, port = srv.server_address
            t = threading.Thread(target=srv.handle_request, daemon=True)
            t.start()
            try:
                conn = HTTPConnection("127.0.0.1", port, timeout=3)
                payload = json.dumps({
                    "text": "inspect the project",
                    "channel": "project_ui",
                    "working_directory": os.getcwd(),
                    "provider": "openai",
                    "model": "gpt-5.1",
                }).encode()
                conn.request(
                    "POST",
                    "/api/chat",
                    body=payload,
                    headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
                )
                resp = conn.getresponse()
                body = json.loads(resp.read())
                conn.close()
            finally:
                srv.server_close()
                t.join(timeout=3)

        self.assertEqual(resp.status, 200)
        self.assertTrue(body.get("streaming"))
        self.assertEqual(captured["payload"]["provider"], "openai")
        self.assertEqual(captured["payload"]["model"], "gpt-5.1")


class TestUIModelSelectionPersistence(unittest.TestCase):
    def test_models_set_saves_provider_specific_model_key(self):
        from kendr.ui_server import KendrUIHandler
        from http.client import HTTPConnection

        save_calls = {}

        def _capture(component_id, values):
            save_calls["component_id"] = component_id
            save_calls["values"] = dict(values)
            return {}

        with (
            patch("kendr.ui_server.save_component_values", side_effect=_capture),
            patch("kendr.ui_server.apply_setup_env_defaults"),
            patch("kendr.llm_router.get_model_setting_env", return_value="OPENAI_MODEL_GENERAL"),
            patch("kendr.llm_router.get_model_for_provider", return_value="gpt-5.1"),
        ):
            srv = ThreadingHTTPServer(("127.0.0.1", 0), KendrUIHandler)
            _, port = srv.server_address
            t = threading.Thread(target=srv.handle_request, daemon=True)
            t.start()
            try:
                conn = HTTPConnection("127.0.0.1", port, timeout=3)
                payload = json.dumps({"provider": "openai", "model": "gpt-5.1"}).encode()
                conn.request(
                    "POST",
                    "/api/models/set",
                    body=payload,
                    headers={"Content-Type": "application/json", "Content-Length": str(len(payload))},
                )
                resp = conn.getresponse()
                body = json.loads(resp.read())
                conn.close()
            finally:
                srv.server_close()
                t.join(timeout=3)

        self.assertEqual(resp.status, 200)
        self.assertTrue(body.get("saved"))
        self.assertEqual(save_calls["component_id"], "core_runtime")
        self.assertEqual(save_calls["values"]["KENDR_LLM_PROVIDER"], "openai")
        self.assertEqual(save_calls["values"]["KENDR_MODEL"], "")
        self.assertEqual(save_calls["values"]["OPENAI_MODEL_GENERAL"], "gpt-5.1")


class TestStreamAlias(unittest.TestCase):
    def test_stream_alias_rejects_missing_run_id(self):
        from kendr.ui_server import KendrUIHandler
        from http.client import HTTPConnection

        srv = ThreadingHTTPServer(("127.0.0.1", 0), KendrUIHandler)
        _, port = srv.server_address

        t = threading.Thread(target=srv.handle_request, daemon=True)
        t.start()
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("GET", "/stream")
            resp = conn.getresponse()
            body = json.loads(resp.read())
            conn.close()
        finally:
            srv.server_close()
            t.join(timeout=3)

        self.assertEqual(resp.status, 400)
        self.assertEqual(body.get("error"), "missing_run_id",
                         "/stream alias must validate run_id just like /api/stream")

    def test_api_stream_alias_rejects_missing_run_id(self):
        from kendr.ui_server import KendrUIHandler
        from http.client import HTTPConnection

        srv = ThreadingHTTPServer(("127.0.0.1", 0), KendrUIHandler)
        _, port = srv.server_address

        t = threading.Thread(target=srv.handle_request, daemon=True)
        t.start()
        try:
            conn = HTTPConnection("127.0.0.1", port, timeout=3)
            conn.request("GET", "/api/stream")
            resp = conn.getresponse()
            body = json.loads(resp.read())
            conn.close()
        finally:
            srv.server_close()
            t.join(timeout=3)

        self.assertEqual(resp.status, 400)
        self.assertEqual(body.get("error"), "missing_run_id")


class TestProjectsWorkbenchHtml(unittest.TestCase):
    def test_projects_html_includes_agent_and_coding_modes(self):
        import kendr.ui_server as ui_server

        self.assertIn("Agent Mode", ui_server._PROJECTS_HTML)
        self.assertIn("Coding Mode", ui_server._PROJECTS_HTML)
        self.assertIn("AI Mode", ui_server._PROJECTS_HTML)
        self.assertIn("Agent-Focused Workbench", ui_server._PROJECTS_HTML)
        self.assertIn('data-project-tab="chat"', ui_server._PROJECTS_HTML)
        self.assertIn("renderMarkdown", ui_server._PROJECTS_HTML)
        self.assertIn("handleFileTreeClick", ui_server._PROJECTS_HTML)
        self.assertIn('id="projShellToggle"', ui_server._PROJECTS_HTML)
        self.assertIn('id="projDestructiveToggle"', ui_server._PROJECTS_HTML)


class TestProjectChatPersistence(unittest.TestCase):
    def test_append_project_chat_messages_persists_to_channel_sessions(self):
        import kendr.ui_server as ui_server

        existing = {
            "state": {
                "project_id": "proj-1",
                "project_path": "/tmp/demo",
                "project_name": "Demo",
                "messages": [],
                "updated_at": "2026-04-01T00:00:00Z",
            },
            "updated_at": "2026-04-01T00:00:00Z",
        }

        with (
            patch("kendr.ui_server._HAS_PERSISTENCE", True),
            patch("kendr.ui_server._db_get_channel_session", return_value=existing),
            patch("kendr.ui_server._db_upsert_channel_session") as upsert,
        ):
            saved = ui_server._append_project_chat_messages(
                "proj-1",
                project_path="/tmp/demo",
                project_name="Demo",
                messages=[{"role": "agent", "content": "## Summary\n- Item"}],
            )

        upsert.assert_called_once()
        self.assertEqual(saved["project_id"], "proj-1")
        self.assertEqual(saved["messages"][0]["content_format"], "markdown")


class TestProjectChatHistoryEndpoints(unittest.TestCase):
    def test_project_chat_history_endpoint(self):
        from kendr.ui_server import KendrUIHandler

        history = {
            "project_id": "proj-1",
            "project_path": "/tmp/demo",
            "project_name": "Demo",
            "messages": [
                {"message_id": "msg-1", "role": "user", "content": "How does auth work?", "content_format": "text", "created_at": "2026-04-01T00:00:00Z"},
                {"message_id": "msg-2", "role": "agent", "content": "It uses JWT.", "content_format": "text", "created_at": "2026-04-01T00:00:05Z"},
            ],
            "updated_at": "2026-04-01T00:00:05Z",
        }

        handler = object.__new__(KendrUIHandler)
        handler._json = MagicMock()

        with (
            patch("kendr.ui_server._HAS_PROJECT_MANAGER", True),
            patch("kendr.ui_server._load_project_chat_history", return_value=history),
            patch("kendr.ui_server._pm_get_project", return_value={"id": "proj-1", "path": "/tmp/demo", "name": "Demo"}),
        ):
            handler._handle_project_chat_history("proj-1")

        handler._json.assert_called_once_with(
            200,
            {
                **history,
                "message_count": 2,
                "turn_count": 1,
            },
        )


class TestProjectServiceEndpoints(unittest.TestCase):
    def test_project_services_list_endpoint(self):
        from kendr.ui_server import KendrUIHandler

        services = [{"id": "frontend", "name": "frontend", "running": True, "status": "running"}]

        handler = object.__new__(KendrUIHandler)
        handler._json = MagicMock()

        with patch("kendr.ui_server._pm_list_services", return_value=services):
            handler._handle_project_services_list("proj-1")

        handler._json.assert_called_once_with(200, {"project_id": "proj-1", "services": services})

    def test_project_service_start_endpoint(self):
        from kendr.ui_server import KendrUIHandler

        result = {"id": "frontend", "name": "frontend", "running": True}

        handler = object.__new__(KendrUIHandler)
        handler._json = MagicMock()

        with patch("kendr.ui_server._pm_start_service", return_value=result) as start_service:
            handler._handle_project_service_start(
                "proj-1",
                {
                    "name": "frontend",
                    "command": "npm run dev",
                    "kind": "frontend",
                    "port": 3000,
                    "health_url": "http://127.0.0.1:3000/health",
                },
            )

        handler._json.assert_called_once_with(200, result)
        start_service.assert_called_once_with(
            "proj-1",
            name="frontend",
            command="npm run dev",
            kind="frontend",
            cwd="",
            port=3000,
            health_url="http://127.0.0.1:3000/health",
            service_id="",
        )


class TestDeepResearchUploads(unittest.TestCase):
    def test_save_upload_batch_preserves_relative_paths(self):
        from kendr.ui_server import _save_deep_research_upload_batch

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("kendr.ui_server._deep_research_upload_root", return_value=tmpdir):
                result = _save_deep_research_upload_batch(
                    chat_id="chat-1",
                    files=[
                        ("brief.txt", b"alpha"),
                        ("chart.png", b"beta"),
                    ],
                    relative_paths=[
                        "folder/brief.txt",
                        "../images/chart.png",
                    ],
                )
                self.assertEqual(result["file_count"], 2)
                self.assertEqual(result["kind"], "folder")
                saved_paths = [item["relative_path"] for item in result["saved_files"]]
                self.assertIn("folder/brief.txt", saved_paths)
                self.assertIn("images/chart.png", saved_paths)
                for item in result["saved_files"]:
                    self.assertNotIn("..", item["relative_path"])
                    self.assertTrue(Path(item["path"]).is_file())

    def test_chat_html_exposes_deep_research_controls_and_preview(self):
        import kendr.ui_server as ui_server

        html = ui_server._CHAT_HTML
        self.assertIn('id="drWebSearch"', html)
        self.assertIn('id="drFileUploadInput"', html)
        self.assertIn('id="drFolderUploadInput"', html)
        self.assertIn("/api/deep-research/upload", html)
        self.assertIn("renderDocumentPreviewCard", html)
        self.assertIn("/api/artifacts/view", html)


class TestDeepResearchChatPayload(unittest.TestCase):
    def test_handle_chat_forwards_deep_research_fields(self):
        from kendr.ui_server import KendrUIHandler

        handler = object.__new__(KendrUIHandler)
        handler._json = MagicMock()

        body = {
            "text": "Create the report",
            "chat_id": "chat-123",
            "run_id": "ui-test-run",
            "working_directory": "/tmp/work",
            "deep_research_mode": True,
            "long_document_mode": True,
            "long_document_pages": 40,
            "research_web_search_enabled": False,
            "deep_research_source_urls": ["https://example.com/ignored-when-local-only"],
            "local_drive_paths": ["/tmp/work/research-inputs"],
            "local_drive_recursive": True,
            "local_drive_force_long_document": True,
        }

        with (
            patch("kendr.ui_server._gateway_ready", return_value=True),
            patch("kendr.ui_server._start_run_background") as start_run,
            patch.dict("kendr.ui_server._pending_runs", {}, clear=True),
            patch.dict("kendr.ui_server._run_event_queues", {}, clear=True),
        ):
            handler._handle_chat(body)

        handler._json.assert_called_once_with(200, {"run_id": "ui-test-run", "streaming": True, "status": "started"})
        forwarded = start_run.call_args.args[1]
        self.assertTrue(forwarded["deep_research_mode"])
        self.assertTrue(forwarded["long_document_mode"])
        self.assertFalse(forwarded["research_web_search_enabled"])
        self.assertEqual(forwarded["deep_research_source_urls"], ["https://example.com/ignored-when-local-only"])
        self.assertEqual(forwarded["local_drive_paths"], ["/tmp/work/research-inputs"])
        self.assertTrue(forwarded["local_drive_recursive"])
        self.assertTrue(forwarded["local_drive_force_long_document"])

    def test_handle_chat_project_ui_starts_runtime_and_persists_request(self):
        from kendr.ui_server import KendrUIHandler

        handler = object.__new__(KendrUIHandler)
        handler._json = MagicMock()

        body = {
            "text": "Delete agentgamma and push the code",
            "channel": "project_ui",
            "project_id": "proj-1",
            "project_root": "/tmp/demo",
            "project_name": "Demo",
            "run_id": "ui-project-run",
            "shell_auto_approve": True,
            "privileged_allow_destructive": True,
            "privileged_allowed_paths": ["/tmp/demo"],
        }

        with (
            patch("kendr.ui_server._gateway_ready", return_value=True),
            patch("kendr.ui_server._persist_project_chat_user_request", return_value=("proj-1", "/tmp/demo", "Demo")) as persist_user,
            patch("kendr.ui_server._start_run_background") as start_run,
            patch.dict("kendr.ui_server._pending_runs", {}, clear=True),
            patch.dict("kendr.ui_server._run_event_queues", {}, clear=True),
        ):
            handler._handle_chat(body)

        handler._json.assert_called_once_with(200, {"run_id": "ui-project-run", "streaming": True, "status": "started"})
        persist_user.assert_called_once()
        forwarded = start_run.call_args.args[1]
        self.assertEqual(forwarded["channel"], "project_ui")
        self.assertEqual(forwarded["chat_id"], "proj-1")
        self.assertEqual(forwarded["project_id"], "proj-1")
        self.assertEqual(forwarded["project_root"], "/tmp/demo")
        self.assertEqual(forwarded["working_directory"], "/tmp/demo")
        self.assertEqual(forwarded["project_name"], "Demo")
        self.assertTrue(forwarded["shell_auto_approve"])
        self.assertTrue(forwarded["privileged_allow_destructive"])
        self.assertEqual(forwarded["privileged_allowed_paths"], ["/tmp/demo"])

    def test_handle_chat_project_ui_persists_gateway_error(self):
        from kendr.ui_server import KendrUIHandler

        handler = object.__new__(KendrUIHandler)
        handler._json = MagicMock()

        body = {
            "text": "Delete agentgamma and push the code",
            "channel": "project_ui",
            "project_id": "proj-1",
            "project_root": "/tmp/demo",
            "project_name": "Demo",
        }

        with (
            patch("kendr.ui_server._gateway_ready", return_value=False),
            patch("kendr.ui_server._persist_project_chat_user_request") as persist_user,
            patch("kendr.ui_server._persist_project_chat_result") as persist_result,
        ):
            handler._handle_chat(body)

        handler._json.assert_called_once_with(
            503,
            {"error": "Gateway not running", "detail": "Start it with: kendr gateway start"},
        )
        persist_user.assert_called_once()
        persist_result.assert_called_once()


if __name__ == "__main__":
    unittest.main()
