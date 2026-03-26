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


if __name__ == "__main__":
    unittest.main()
