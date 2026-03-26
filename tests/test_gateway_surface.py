import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch


os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

import superagent.gateway_server as gateway


class _QuietGatewayHandler(gateway.GatewayHandler):
    def log_message(self, format, *args):  # noqa: A003
        return


class GatewaySurfaceSmokeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _QuietGatewayHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.base_url = f"http://{host}:{port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)

    def _json_get(self, path: str) -> tuple[int, object]:
        with urllib.request.urlopen(f"{self.base_url}{path}", timeout=5) as response:
            return response.status, json.loads(response.read().decode("utf-8"))

    def test_health_endpoint_returns_ok(self):
        status, payload = self._json_get("/health")
        self.assertEqual(status, 200)
        self.assertEqual(payload, {"status": "ok"})

    def test_registry_agents_endpoint_returns_agent_inventory(self):
        status, payload = self._json_get("/registry/agents")
        self.assertEqual(status, 200)
        self.assertTrue(any(item["name"] == "worker_agent" for item in payload))

    def test_runs_endpoint_returns_patched_recent_runs(self):
        with patch("superagent.gateway_server.list_recent_runs", return_value=[{"run_id": "run_smoke"}]):
            status, payload = self._json_get("/runs")
        self.assertEqual(status, 200)
        self.assertEqual(payload, [{"run_id": "run_smoke"}])

    def test_ingest_requires_working_directory_when_not_configured(self):
        request = urllib.request.Request(
            f"{self.base_url}/ingest",
            data=json.dumps({"text": "hello"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with (
            patch.dict("superagent.gateway_server.os.environ", {"SUPERAGENT_WORKING_DIR": ""}, clear=False),
            self.assertRaises(urllib.error.HTTPError) as exc,
        ):
            urllib.request.urlopen(request, timeout=5)

        self.assertEqual(exc.exception.code, 400)
        payload = json.loads(exc.exception.read().decode("utf-8"))
        self.assertEqual(payload["error"], "working_directory_required")


if __name__ == "__main__":
    unittest.main()
