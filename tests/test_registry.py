import os
import unittest


os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from superagent.discovery import build_registry


class RegistryDiscoveryTests(unittest.TestCase):
    def test_build_registry_discovers_expected_agents(self):
        registry = build_registry()
        for agent_name in [
            "planner_agent",
            "worker_agent",
            "reviewer_agent",
            "report_agent",
            "recon_agent",
            "scanner_agent",
            "exploit_agent",
            "evidence_agent",
            "security_report_agent",
            "heartbeat_agent",
            "monitor_rule_agent",
            "stock_monitor_agent",
            "local_drive_agent",
            "superrag_agent",
        ]:
            self.assertIn(agent_name, registry.agents)

    def test_build_registry_discovers_expected_providers(self):
        registry = build_registry()
        for provider_name in ["openai", "playwright", "nmap", "zap", "cve_database"]:
            self.assertIn(provider_name, registry.providers)

    def test_provider_metadata_comes_from_integration_catalog(self):
        registry = build_registry()
        openai = registry.providers["openai"]
        self.assertEqual(openai.metadata.get("component_id"), "openai")
        self.assertIn("docs/integrations.md", openai.metadata.get("docs_path", ""))

    def test_agent_cards_include_declared_requirements(self):
        registry = build_registry()
        cards = {card["agent_name"]: card for card in registry.agent_cards()}
        self.assertEqual(cards["superrag_agent"]["requirements"], ["openai", "qdrant"])


if __name__ == "__main__":
    unittest.main()
