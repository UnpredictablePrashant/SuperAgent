from __future__ import annotations

import io
import json
import os
import socket
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
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


if __name__ == "__main__":
    unittest.main()
