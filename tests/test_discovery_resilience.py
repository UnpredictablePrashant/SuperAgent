from __future__ import annotations

import importlib
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from kendr.discovery import DiscoveryOptions, RegistryDiscoveryError, build_registry


class DiscoveryResilienceTests(unittest.TestCase):
    def test_build_registry_records_broken_builtin_module_when_not_strict(self):
        real_import_module = importlib.import_module

        def _fake_import_module(name: str, package: str | None = None):
            if name == "tasks.broken_module":
                raise ModuleNotFoundError("missing optional dependency")
            return real_import_module(name, package)

        with patch(
            "kendr.discovery.pkgutil.iter_modules",
            return_value=[SimpleNamespace(name="broken_module")],
        ), patch("kendr.discovery.importlib.import_module", side_effect=_fake_import_module):
            registry = build_registry(
                DiscoveryOptions(
                    discover_external_plugins=False,
                    discover_mcp_tools=False,
                    discover_skill_agents=False,
                )
            )

        self.assertEqual(len(registry.discovery_issues), 1)
        issue = registry.discovery_issues[0]
        self.assertEqual(issue.source, "builtin_task_module")
        self.assertEqual(issue.target, "tasks.broken_module")
        self.assertIn("missing optional dependency", issue.error)

    def test_build_registry_strict_mode_raises_on_broken_builtin_module(self):
        with patch(
            "kendr.discovery.pkgutil.iter_modules",
            return_value=[SimpleNamespace(name="broken_module")],
        ), patch(
            "kendr.discovery.importlib.import_module",
            side_effect=ModuleNotFoundError("missing optional dependency"),
        ):
            with self.assertRaises(RegistryDiscoveryError) as ctx:
                build_registry(
                    DiscoveryOptions(
                        discover_external_plugins=False,
                        discover_mcp_tools=False,
                        discover_skill_agents=False,
                        strict=True,
                    )
                )

        self.assertEqual(ctx.exception.source, "builtin_task_module")
        self.assertEqual(ctx.exception.target, "tasks.broken_module")

    def test_tasks_utils_imports_without_langchain_openai_at_module_load(self):
        original_module = sys.modules.pop("tasks.utils", None)
        try:
            with patch.dict(sys.modules, {"langchain_openai": None}):
                module = importlib.import_module("tasks.utils")
            self.assertTrue(hasattr(module, "RoutedLLM"))
            self.assertTrue(callable(getattr(module, "_fallback_openai_client")))
        finally:
            sys.modules.pop("tasks.utils", None)
            if original_module is not None:
                sys.modules["tasks.utils"] = original_module

    def test_build_registry_includes_core_web_search_skill_without_install(self):
        with patch("kendr.skill_manager.list_user_skills", return_value=[]):
            registry = build_registry(
                DiscoveryOptions(
                    discover_external_plugins=False,
                    discover_mcp_tools=False,
                    discover_skill_agents=True,
                )
            )

        self.assertIn("skill_web_search_agent", registry.agents)


if __name__ == "__main__":
    unittest.main()
