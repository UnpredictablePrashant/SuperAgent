import os
import tempfile
import textwrap
import unittest
from pathlib import Path
from unittest.mock import patch


os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from kendr.discovery import build_registry


class PluginSdkTests(unittest.TestCase):
    def test_external_plugin_manifest_registers_agent_and_provider(self):
        plugin_source = textwrap.dedent(
            """
            from kendr.types import AgentDefinition, PluginManifest, ProviderDefinition

            PLUGIN = PluginManifest(
                name="acme.test_plugin",
                description="Test plugin",
                version="1.2.3",
                sdk_version="1.0",
                runtime_api="registry-v1",
                capabilities=["agent", "provider"],
            )

            def test_plugin_agent(state: dict) -> dict:
                state["draft_response"] = "ok"
                return state

            def register(registry) -> None:
                registry.register_provider(
                    ProviderDefinition(
                        name="acme_provider",
                        description="Acme provider",
                        plugin_name=PLUGIN.name,
                    )
                )
                registry.register_agent(
                    AgentDefinition(
                        name="test_plugin_agent",
                        handler=test_plugin_agent,
                        description="Plugin test agent",
                        plugin_name=PLUGIN.name,
                    )
                )
            """
        )

        with tempfile.TemporaryDirectory() as tmp:
            plugin_path = Path(tmp) / "acme_test_plugin.py"
            plugin_path.write_text(plugin_source, encoding="utf-8")

            with patch.dict(os.environ, {"KENDR_PLUGIN_PATHS": tmp}, clear=False):
                registry = build_registry()

        self.assertIn("acme.test_plugin", registry.plugins)
        plugin = registry.plugins["acme.test_plugin"]
        self.assertEqual(plugin.version, "1.2.3")
        self.assertEqual(plugin.sdk_version, "1.0")
        self.assertEqual(plugin.runtime_api, "registry-v1")
        self.assertIn("agent", plugin.metadata.get("capabilities", []))
        self.assertIn("provider", plugin.metadata.get("capabilities", []))
        self.assertIn("test_plugin_agent", registry.agents)
        self.assertIn("acme_provider", registry.providers)


if __name__ == "__main__":
    unittest.main()
