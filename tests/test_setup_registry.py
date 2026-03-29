import os
import unittest
from unittest.mock import patch


os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from kendr.discovery import build_registry
from kendr.setup import build_setup_snapshot


class SetupRegistryTests(unittest.TestCase):
    def test_setup_snapshot_includes_agent_and_service_status(self):
        registry = build_registry()
        snapshot = build_setup_snapshot(registry.agent_cards())
        self.assertIn("services", snapshot)
        self.assertIn("agents", snapshot)
        self.assertIn("available_agents", snapshot)
        self.assertIn("openai", snapshot["services"])
        self.assertIn("status", snapshot["services"]["openai"])
        self.assertIn("health", snapshot["services"]["openai"])
        self.assertIn("routing_eligible", snapshot["services"]["openai"])
        self.assertIn("docs_path", snapshot["services"]["openai"])

    def test_scanner_agent_disabled_without_scan_tools(self):
        registry = build_registry()
        with patch("shutil.which", return_value=None):
            snapshot = build_setup_snapshot(registry.agent_cards())
        scanner_status = snapshot["agents"].get("scanner_agent", {})
        self.assertIn("available", scanner_status)
        self.assertFalse(scanner_status["available"])
        self.assertIn("nmap_or_zap", scanner_status.get("missing_services", []))

    def test_disabled_integration_surfaces_enable_action_and_blocks_routing(self):
        registry = build_registry()

        def _component_snapshot(component_id: str) -> dict:
            if component_id == "serpapi":
                return {"enabled": False}
            return {}

        with (
            patch.dict("tasks.setup_registry.os.environ", {"SERP_API_KEY": "test-serp-key"}, clear=False),
            patch("tasks.setup_registry.get_setup_component_snapshot", side_effect=_component_snapshot),
        ):
            snapshot = build_setup_snapshot(registry.agent_cards())

        self.assertEqual(snapshot["services"]["serpapi"]["status"], "disabled")
        self.assertFalse(snapshot["services"]["serpapi"]["routing_eligible"])
        self.assertFalse(snapshot["agents"]["google_search_agent"]["available"])
        self.assertIn("serpapi", snapshot["agents"]["google_search_agent"]["missing_services"])
        self.assertTrue(any(item["service"] == "serpapi" and item["action"] == "enable" for item in snapshot["setup_actions"]))

    def test_coding_agents_allow_codex_cli_fallback_when_openai_missing(self):
        registry = build_registry()

        def _which(command: str) -> str | None:
            return "C:/bin/codex.exe" if command == "codex" else None

        with (
            patch.dict("tasks.setup_registry.os.environ", {"OPENAI_API_KEY": ""}, clear=False),
            patch("tasks.setup_registry.shutil.which", side_effect=_which),
        ):
            snapshot = build_setup_snapshot(registry.agent_cards())

        self.assertIn("coding_agent", snapshot["available_agents"])
        self.assertIn("master_coding_agent", snapshot["available_agents"])

    def test_snapshot_reports_legacy_requirement_fallbacks(self):
        registry = build_registry()
        snapshot = build_setup_snapshot(registry.agent_cards())
        self.assertTrue(any("local_drive_agent" in warning for warning in snapshot.get("contract_warnings", [])))

    def test_superrag_agent_is_hidden_when_qdrant_is_unconfigured(self):
        registry = build_registry()
        with patch.dict("tasks.setup_registry.os.environ", {"OPENAI_API_KEY": "test-openai-key", "QDRANT_URL": ""}, clear=False):
            snapshot = build_setup_snapshot(registry.agent_cards())

        self.assertFalse(snapshot["services"]["qdrant"]["routing_eligible"])
        self.assertFalse(snapshot["agents"]["superrag_agent"]["available"])
        self.assertIn("qdrant", snapshot["agents"]["superrag_agent"]["missing_services"])


if __name__ == "__main__":
    unittest.main()
