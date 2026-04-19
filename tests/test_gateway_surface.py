import json
import os
import threading
import tempfile
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

    def test_registry_discovery_endpoint_returns_unified_snapshot(self):
        fake_caps = [
            {
                "id": "cap-1",
                "type": "mcp_server",
                "key": "mcp.server.s1",
                "name": "MCP Server 1",
                "description": "Test server",
                "status": "active",
                "health_status": "healthy",
                "visibility": "workspace",
                "version": 1,
                "tags": ["mcp"],
                "metadata": {"managed_by": "mcp_sync"},
            }
        ]
        with (
            patch("kendr.gateway_server.sync_mcp_capabilities", return_value={"servers_synced": 1}),
            patch.object(gateway.CAPABILITY_REGISTRY, "list", return_value=fake_caps),
        ):
            status, payload = self._json_get("/registry/discovery?workspace_id=default")
        self.assertEqual(status, 200)
        self.assertEqual(payload["workspace_id"], "default")
        self.assertEqual(payload["summary"]["total"], 1)
        self.assertEqual(payload["summary"]["by_type"]["mcp_server"], 1)

    def test_registry_discovery_cards_endpoint_returns_cards(self):
        fake_caps = [
            {
                "id": "cap-1",
                "type": "tool",
                "key": "mcp.tool.s1.echo",
                "name": "echo",
                "description": "Echo tool",
                "status": "active",
                "health_status": "healthy",
                "visibility": "workspace",
                "version": 1,
                "tags": ["mcp", "tool"],
                "metadata": {"managed_by": "mcp_sync"},
            }
        ]
        with (
            patch("kendr.gateway_server.sync_mcp_capabilities", return_value={"tools_synced": 1}),
            patch.object(gateway.CAPABILITY_REGISTRY, "list", return_value=fake_caps),
        ):
            status, payload = self._json_get("/registry/discovery/cards")
        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["cards"][0]["key"], "mcp.tool.s1.echo")

    def test_create_auth_profile_endpoint(self):
        fake_auth = {"id": "auth-1", "provider": "github", "auth_type": "api_key"}
        request = urllib.request.Request(
            f"{self.base_url}/registry/auth-profiles",
            data=json.dumps(
                {
                    "workspace_id": "default",
                    "auth_type": "api_key",
                    "provider": "github",
                    "secret_ref": "vault://default/github/token",
                    "scopes": ["repo:read"],
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with patch.object(gateway.CAPABILITY_REGISTRY, "create_auth_profile", return_value=fake_auth):
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["auth_profile"]["id"], "auth-1")

    def test_import_openapi_endpoint(self):
        request = urllib.request.Request(
            f"{self.base_url}/registry/apis/import-openapi",
            data=json.dumps(
                {
                    "workspace_id": "default",
                    "owner_user_id": "u1",
                    "openapi": {
                        "openapi": "3.0.0",
                        "info": {"title": "Sample API"},
                        "paths": {"/health": {"get": {"summary": "Health check", "responses": {"200": {"description": "ok"}}}}},
                    },
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with patch(
            "kendr.gateway_server.import_openapi_as_capabilities",
            return_value={"operations_synced": 1, "service_capability_id": "cap-1"},
        ):
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["import_result"]["operations_synced"], 1)

    def test_skill_test_endpoint_returns_approval_required_response(self):
        request = urllib.request.Request(
            f"{self.base_url}/api/marketplace/skills/skill-approval/test",
            data=json.dumps({"inputs": {"command": "pwd"}, "session_id": "sess-1"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        approval_payload = {
            "success": False,
            "error_type": "approval_required",
            "error": "Approval required.",
            "awaiting_user_input": True,
            "pending_user_input_kind": "skill_approval",
            "approval_pending_scope": "skill_permission:demo",
            "approval_request": {"scope": "skill_permission:demo", "summary": "Approve skill."},
        }
        with (
            patch("kendr.gateway_server.test_skill", return_value=approval_payload),
            self.assertRaises(urllib.error.HTTPError) as exc,
        ):
            urllib.request.urlopen(request, timeout=5)
        self.assertEqual(exc.exception.code, 409)
        payload = json.loads(exc.exception.read().decode("utf-8"))
        self.assertEqual(payload["error_type"], "approval_required")
        self.assertTrue(payload["awaiting_user_input"])

    def test_skill_approve_endpoint_returns_grant_payload(self):
        request = urllib.request.Request(
            f"{self.base_url}/api/marketplace/skills/skill-approval/approve",
            data=json.dumps({"scope": "session", "note": "Allow for this session", "session_id": "sess-1"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        fake_grant = {"grant_id": "grant-1", "scope": "session", "session_id": "sess-1", "status": "active"}
        with patch("kendr.gateway_server.grant_skill_approval", return_value=fake_grant):
            with urllib.request.urlopen(request, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["grant"]["grant_id"], "grant-1")

    def test_capability_crud_and_lifecycle_endpoints(self):
        created = {
            "id": "cap-skill-1",
            "type": "skill",
            "key": "skill.code.review",
            "name": "Code Review Skill",
            "description": "Reviews code quality.",
            "status": "draft",
        }
        verified = {**created, "status": "verified"}
        active = {**created, "status": "active"}
        disabled = {**created, "status": "disabled"}
        listed = [disabled]

        create_req = urllib.request.Request(
            f"{self.base_url}/registry/capabilities",
            data=json.dumps(
                {
                    "workspace_id": "default",
                    "actor_user_id": "u1",
                    "type": "skill",
                    "key": "skill.code.review",
                    "name": "Code Review Skill",
                    "description": "Reviews code quality.",
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        verify_req = urllib.request.Request(
            f"{self.base_url}/registry/capabilities/cap-skill-1/verify",
            data=json.dumps({"workspace_id": "default", "actor_user_id": "u1"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        publish_req = urllib.request.Request(
            f"{self.base_url}/registry/capabilities/cap-skill-1/publish",
            data=json.dumps({"workspace_id": "default", "actor_user_id": "u1"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        disable_req = urllib.request.Request(
            f"{self.base_url}/registry/capabilities/cap-skill-1/disable",
            data=json.dumps({"workspace_id": "default", "actor_user_id": "u1"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        with (
            patch.object(gateway.CAPABILITY_REGISTRY, "create", return_value=created),
            patch.object(gateway.CAPABILITY_REGISTRY, "verify", return_value=verified),
            patch.object(gateway.CAPABILITY_REGISTRY, "publish", return_value=active),
            patch.object(gateway.CAPABILITY_REGISTRY, "disable", return_value=disabled),
            patch.object(gateway.CAPABILITY_REGISTRY, "list", return_value=listed),
            patch.object(gateway.CAPABILITY_REGISTRY, "get", return_value=disabled),
        ):
            with urllib.request.urlopen(create_req, timeout=5) as response:
                create_payload = json.loads(response.read().decode("utf-8"))
            with urllib.request.urlopen(verify_req, timeout=5) as response:
                verify_payload = json.loads(response.read().decode("utf-8"))
            with urllib.request.urlopen(publish_req, timeout=5) as response:
                publish_payload = json.loads(response.read().decode("utf-8"))
            with urllib.request.urlopen(disable_req, timeout=5) as response:
                disable_payload = json.loads(response.read().decode("utf-8"))
            with urllib.request.urlopen(f"{self.base_url}/registry/capabilities?workspace_id=default", timeout=5) as response:
                list_payload = json.loads(response.read().decode("utf-8"))
            with urllib.request.urlopen(f"{self.base_url}/registry/capabilities/cap-skill-1", timeout=5) as response:
                get_payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(create_payload["ok"])
        self.assertEqual(verify_payload["capability"]["status"], "verified")
        self.assertEqual(publish_payload["capability"]["status"], "active")
        self.assertEqual(disable_payload["capability"]["status"], "disabled")
        self.assertEqual(list_payload["count"], 1)
        self.assertEqual(get_payload["id"], "cap-skill-1")

    def test_capability_invalid_transition_returns_400(self):
        publish_req = urllib.request.Request(
            f"{self.base_url}/registry/capabilities/cap-skill-1/publish",
            data=json.dumps({"workspace_id": "default", "actor_user_id": "u1"}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with (
            patch.object(gateway.CAPABILITY_REGISTRY, "publish", side_effect=ValueError("Invalid status transition: error -> active")),
            self.assertRaises(urllib.error.HTTPError) as exc,
        ):
            urllib.request.urlopen(publish_req, timeout=5)
        self.assertEqual(exc.exception.code, 400)
        payload = json.loads(exc.exception.read().decode("utf-8"))
        self.assertFalse(payload["ok"])
        self.assertIn("Invalid status transition", payload["error"])

    def test_policy_profile_endpoints(self):
        create_req = urllib.request.Request(
            f"{self.base_url}/registry/policy-profiles",
            data=json.dumps(
                {
                    "workspace_id": "default",
                    "name": "readonly-policy",
                    "rules": {"deny_write": True},
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        fake_created = {"id": "pp-1", "name": "readonly-policy", "rules": {"deny_write": True}}
        fake_list = [fake_created]
        with (
            patch.object(gateway.CAPABILITY_REGISTRY, "create_policy_profile", return_value=fake_created),
            patch.object(gateway.CAPABILITY_REGISTRY, "list_policy_profiles", return_value=fake_list),
        ):
            with urllib.request.urlopen(create_req, timeout=5) as response:
                create_payload = json.loads(response.read().decode("utf-8"))
            with urllib.request.urlopen(f"{self.base_url}/registry/policy-profiles?workspace_id=default", timeout=5) as response:
                list_payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(create_payload["ok"])
        self.assertEqual(create_payload["policy_profile"]["id"], "pp-1")
        self.assertEqual(list_payload["count"], 1)

    def test_capability_health_and_audit_get_endpoints(self):
        fake_health = [{"health_run_id": "hr-1", "status": "healthy"}]
        fake_audit = [{"id": "ae-1", "action": "capability.health"}]
        with (
            patch.object(gateway.CAPABILITY_REGISTRY, "list_health_runs", return_value=fake_health),
            patch.object(gateway.CAPABILITY_REGISTRY, "list_audit_events", return_value=fake_audit),
        ):
            with urllib.request.urlopen(f"{self.base_url}/registry/capabilities/cap-1/health?workspace_id=default", timeout=5) as response:
                health_payload = json.loads(response.read().decode("utf-8"))
            with urllib.request.urlopen(f"{self.base_url}/registry/capabilities/cap-1/audit?workspace_id=default", timeout=5) as response:
                audit_payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(health_payload["count"], 1)
        self.assertEqual(health_payload["items"][0]["status"], "healthy")
        self.assertEqual(audit_payload["count"], 1)
        self.assertEqual(audit_payload["items"][0]["action"], "capability.health")

    def test_capability_health_and_audit_limit_clamp_allows_up_to_ten_thousand(self):
        with (
            patch.object(gateway.CAPABILITY_REGISTRY, "list_health_runs", return_value=[]) as mock_health,
            patch.object(gateway.CAPABILITY_REGISTRY, "list_audit_events", return_value=[]) as mock_audit,
        ):
            with urllib.request.urlopen(
                f"{self.base_url}/registry/capabilities/cap-1/health?workspace_id=default&limit=20000",
                timeout=5,
            ) as response:
                health_payload = json.loads(response.read().decode("utf-8"))
            with urllib.request.urlopen(
                f"{self.base_url}/registry/capabilities/cap-1/audit?workspace_id=default&limit=20000",
                timeout=5,
            ) as response:
                audit_payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(health_payload["count"], 0)
        self.assertEqual(audit_payload["count"], 0)
        self.assertEqual(mock_health.call_args.kwargs["limit"], 10_000)
        self.assertEqual(mock_audit.call_args.kwargs["limit"], 10_000)

    def test_capability_health_check_endpoint(self):
        health_req = urllib.request.Request(
            f"{self.base_url}/registry/capabilities/cap-skill-1/health-check",
            data=json.dumps(
                {
                    "workspace_id": "default",
                    "actor_user_id": "u1",
                    "status": "healthy",
                    "latency_ms": 25,
                }
            ).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        fake_cap = {"id": "cap-skill-1", "health_status": "healthy"}
        with patch.object(gateway.CAPABILITY_REGISTRY, "record_health", return_value=fake_cap):
            with urllib.request.urlopen(health_req, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))

        self.assertTrue(payload["ok"])
        self.assertEqual(payload["capability"]["health_status"], "healthy")

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
        ):
            result = channel_gateway_agent(state)

        self.assertEqual(result["gateway_message"]["channel"], "web chat")
        self.assertTrue(result["gateway_message"]["should_activate"])
        self.assertIn("activation enabled", result["draft_response"].lower())
        self.assertEqual(result["gateway_message"]["activation_reason"], "direct message")

    def test_ingest_prepopulates_gateway_message_for_webchat(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            request = urllib.request.Request(
                f"{self.base_url}/ingest",
                data=json.dumps(
                    {
                        "text": "hello",
                        "channel": "webchat",
                        "sender_id": "user-1",
                        "chat_id": "chat-1",
                        "working_directory": tmpdir,
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with patch.object(gateway.RUNTIME, "run_query", return_value={"run_id": "run-1", "final_output": "ok"}) as run_query:
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(payload["run_id"], "run-1")
        _, kwargs = run_query.call_args
        overrides = kwargs["state_overrides"]
        self.assertEqual(overrides["gateway_message"]["channel"], "webchat")
        self.assertEqual(overrides["gateway_message"]["activation_reason"], "direct message")
        self.assertTrue(overrides["gateway_message"]["should_activate"])

    def test_ingest_preserves_provider_and_model_overrides(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            request = urllib.request.Request(
                f"{self.base_url}/ingest",
                data=json.dumps(
                    {
                        "text": "inspect the repo",
                        "channel": "project_ui",
                        "sender_id": "user-1",
                        "chat_id": "chat-1",
                        "working_directory": tmpdir,
                        "provider": "openai",
                        "model": "gpt-5.1",
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with patch.object(gateway.RUNTIME, "run_query", return_value={"run_id": "run-2", "final_output": "ok"}) as run_query:
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(payload["run_id"], "run-2")
        _, kwargs = run_query.call_args
        overrides = kwargs["state_overrides"]
        self.assertEqual(overrides["provider"], "openai")
        self.assertEqual(overrides["model"], "gpt-5.1")

    def test_ingest_preserves_execution_mode_override(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            request = urllib.request.Request(
                f"{self.base_url}/ingest",
                data=json.dumps(
                    {
                        "text": "inspect the repo",
                        "channel": "webchat",
                        "sender_id": "user-1",
                        "chat_id": "chat-1",
                        "working_directory": tmpdir,
                        "execution_mode": "direct_tools",
                    }
                ).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )

            with patch.object(gateway.RUNTIME, "run_query", return_value={"run_id": "run-3", "final_output": "ok"}) as run_query:
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode("utf-8"))

        self.assertEqual(payload["run_id"], "run-3")
        _, kwargs = run_query.call_args
        overrides = kwargs["state_overrides"]
        self.assertEqual(overrides["execution_mode"], "direct_tools")

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
