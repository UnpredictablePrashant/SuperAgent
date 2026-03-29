import json
import os
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch


os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

import kendr.gateway_server as gateway
from tasks.gateway_tasks import channel_gateway_agent, session_router_agent


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
        with patch("kendr.gateway_server.list_recent_runs", return_value=[{"run_id": "run_smoke"}]):
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
            patch.dict("kendr.gateway_server.os.environ", {"KENDR_WORKING_DIR": ""}, clear=False),
            self.assertRaises(urllib.error.HTTPError) as exc,
        ):
            urllib.request.urlopen(request, timeout=5)

        self.assertEqual(exc.exception.code, 400)
        payload = json.loads(exc.exception.read().decode("utf-8"))
        self.assertEqual(payload["error"], "working_directory_required")

    def test_channel_gateway_agent_normalizes_channel_without_crashing(self):
        state = {
            "incoming_payload": {"channel": "Web Chat", "sender_id": "user-1", "chat_id": "chat-1", "text": "hello"},
            "incoming_channel": "Web Chat",
            "incoming_sender_id": "user-1",
            "incoming_chat_id": "chat-1",
            "incoming_workspace_id": "workspace-1",
            "incoming_text": "hello",
            "incoming_is_group": False,
            "user_query": "hello",
            "current_objective": "hello",
        }

        with (
            patch("tasks.gateway_tasks.write_text_file"),
            patch("tasks.gateway_tasks.llm_text", return_value="normalized"),
        ):
            result = channel_gateway_agent(state)

        self.assertEqual(result["gateway_message"]["channel"], "web chat")
        self.assertTrue(result["gateway_message"]["should_activate"])
        self.assertEqual(result["draft_response"], "normalized")

    def test_session_router_preserves_existing_session_state_keys(self):
        persisted_payload = {}

        def _capture_upsert(_session_key, payload):
            persisted_payload.update(payload)

        prior_session = {
            "session_key": "webchat::chat-1:main",
            "state": {
                "blueprint_json": {"project_name": "new-project"},
                "project_root": "D:/kendrTasks/web/new-project",
                "custom_marker": "keep-me",
                "history": [],
            },
        }
        state = {
            "gateway_message": {
                "channel": "web chat",
                "sender_id": "user-1",
                "chat_id": "chat-1",
                "workspace_id": "",
                "is_group": False,
                "text": "approve",
            },
            "incoming_channel": "web chat",
            "incoming_sender_id": "user-1",
            "incoming_chat_id": "chat-1",
            "incoming_workspace_id": "",
            "incoming_is_group": False,
            "user_query": "approve",
            "current_objective": "approve",
        }

        with (
            patch("tasks.gateway_tasks.initialize_db"),
            patch("tasks.gateway_tasks.get_channel_session", return_value=prior_session),
            patch("tasks.gateway_tasks.upsert_channel_session", side_effect=_capture_upsert),
            patch("tasks.gateway_tasks.write_text_file"),
        ):
            result = session_router_agent(state)

        session_state = persisted_payload.get("state", {})
        self.assertEqual(session_state.get("custom_marker"), "keep-me")
        self.assertEqual(session_state.get("blueprint_json"), prior_session["state"]["blueprint_json"])
        self.assertEqual(session_state.get("project_root"), prior_session["state"]["project_root"])
        self.assertEqual(result["channel_session"]["state"].get("custom_marker"), "keep-me")


if __name__ == "__main__":
    unittest.main()
