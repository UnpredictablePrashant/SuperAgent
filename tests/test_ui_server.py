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
        self.assertIn("Agent-Focused Workbench", ui_server._PROJECTS_HTML)
        self.assertIn('data-project-tab="chat"', ui_server._PROJECTS_HTML)
        self.assertIn("renderMarkdown", ui_server._PROJECTS_HTML)
        self.assertIn("handleFileTreeClick", ui_server._PROJECTS_HTML)


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


if __name__ == "__main__":
    unittest.main()
