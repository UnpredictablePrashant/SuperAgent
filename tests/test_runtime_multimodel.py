import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from kendr.discovery import build_registry
from kendr.runtime import AgentRuntime


class RuntimeMultiModelTests(unittest.TestCase):
    @staticmethod
    def _fake_setup_snapshot(agent_cards: list[dict]) -> dict:
        return {
            "available_agents": [str(card.get("agent_name", "")) for card in agent_cards if isinstance(card, dict)],
            "disabled_agents": {},
            "setup_actions": [],
            "summary_text": "",
        }

    def test_multi_model_plan_is_only_created_when_enabled(self):
        statuses = [
            {
                "provider": "openai",
                "ready": True,
                "model": "gpt-5.4-mini",
                "selectable_model_details": [
                    {
                        "name": "gpt-5.4-mini",
                        "family": "openai",
                        "context_window": 400000,
                        "capabilities": {
                            "tool_calling": True,
                            "vision": True,
                            "structured_output": True,
                            "reasoning": True,
                            "native_web_search": True,
                        },
                        "agent_capable": True,
                    }
                ],
            }
        ]
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("kendr.llm_router.all_provider_statuses", return_value=statuses),
        ):
            runtime = AgentRuntime(build_registry())
            disabled_state = runtime.build_initial_state(
                "Do deep research on climate resilience policy.",
                multi_model_enabled=False,
            )
            enabled_state = runtime.build_initial_state(
                "Do deep research on climate resilience policy.",
                multi_model_enabled=True,
            )

        self.assertEqual(disabled_state.get("multi_model_plan"), {})
        self.assertTrue(enabled_state.get("multi_model_plan", {}).get("enabled"))
        self.assertEqual(enabled_state.get("multi_model_active_workflow"), "deep_research_report")

    def test_multi_model_plan_seeds_research_model_and_stage_override(self):
        statuses = [
            {
                "provider": "openai",
                "ready": True,
                "model": "gpt-5.4",
                "selectable_model_details": [
                    {
                        "name": "gpt-5.4",
                        "family": "openai",
                        "context_window": 400000,
                        "capabilities": {
                            "tool_calling": True,
                            "vision": True,
                            "structured_output": True,
                            "reasoning": True,
                            "native_web_search": True,
                        },
                        "agent_capable": True,
                    },
                    {
                        "name": "gpt-5.4-mini",
                        "family": "openai",
                        "context_window": 400000,
                        "capabilities": {
                            "tool_calling": True,
                            "vision": True,
                            "structured_output": True,
                            "reasoning": True,
                            "native_web_search": True,
                        },
                        "agent_capable": True,
                    },
                ],
            }
        ]
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("kendr.llm_router.all_provider_statuses", return_value=statuses),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state(
                "Create a 50-page market report.",
                multi_model_enabled=True,
                multi_model_strategy="best",
                workflow_type="deep_research",
                deep_research_mode=True,
            )
            override = runtime._multi_model_override_for_agent(state, "long_document_agent")

        self.assertEqual(state.get("research_model_source"), "multi_model_plan")
        self.assertEqual(state.get("research_provider"), "openai")
        self.assertTrue(str(state.get("research_model") or "").strip())
        self.assertEqual(override.get("stage"), "merge")
        self.assertEqual(override.get("provider"), "openai")
        self.assertTrue(str(override.get("model") or "").strip())

    def test_multi_model_plan_allows_non_openai_deep_research_stage_override(self):
        statuses = [
            {
                "provider": "google",
                "ready": True,
                "model": "gemini-2.5-pro",
                "selectable_model_details": [
                    {
                        "name": "gemini-2.5-pro",
                        "family": "google",
                        "context_window": 1048576,
                        "capabilities": {
                            "tool_calling": True,
                            "vision": True,
                            "structured_output": True,
                            "reasoning": True,
                            "native_web_search": False,
                        },
                        "agent_capable": True,
                    }
                ],
            }
        ]
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("kendr.llm_router.all_provider_statuses", return_value=statuses),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state(
                "Investigate the competitive landscape for frontier AI labs.",
                multi_model_enabled=True,
                multi_model_strategy="best",
                workflow_type="deep_research",
                deep_research_mode=True,
            )
            override = runtime._multi_model_override_for_agent(state, "deep_research_agent")

        self.assertEqual(state.get("research_model_source"), "multi_model_plan")
        self.assertEqual(state.get("research_provider"), "google")
        self.assertEqual(state.get("research_model"), "gemini-2.5-pro")
        self.assertEqual(override.get("stage"), "evidence")
        self.assertEqual(override.get("provider"), "google")
        self.assertEqual(override.get("model"), "gemini-2.5-pro")

    def test_multi_model_plan_selects_ocr_stage_for_supported_provider(self):
        statuses = [
            {
                "provider": "glm",
                "ready": True,
                "model": "glm-4-flash",
                "selectable_model_details": [
                    {
                        "name": "glm-4-flash",
                        "family": "glm",
                        "context_window": 131072,
                        "capabilities": {
                            "tool_calling": True,
                            "vision": True,
                            "structured_output": True,
                            "reasoning": True,
                            "native_web_search": False,
                        },
                        "agent_capable": True,
                    }
                ],
            },
            {
                "provider": "openai",
                "ready": True,
                "model": "gpt-4o-mini",
                "selectable_model_details": [
                    {
                        "name": "gpt-4o-mini",
                        "family": "openai",
                        "context_window": 128000,
                        "capabilities": {
                            "tool_calling": True,
                            "vision": True,
                            "structured_output": True,
                            "reasoning": False,
                            "native_web_search": True,
                        },
                        "agent_capable": True,
                    }
                ],
            },
        ]
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("kendr.llm_router.all_provider_statuses", return_value=statuses),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state(
                "Extract text from these scans.",
                multi_model_enabled=True,
                multi_model_strategy="best",
                local_drive_paths=["/tmp/scan.png"],
            )
            override = runtime._multi_model_override_for_agent(state, "ocr_agent")

        self.assertEqual(state.get("multi_model_active_workflow"), "ocr_ingestion")
        self.assertEqual(override.get("stage"), "ocr")
        self.assertEqual(override.get("provider"), "glm")
        self.assertEqual(override.get("model"), "glm-4-flash")

    def test_manual_stage_override_replaces_recommended_stage_model(self):
        statuses = [
            {
                "provider": "openai",
                "ready": True,
                "model": "gpt-5.4-mini",
                "selectable_model_details": [
                    {
                        "name": "gpt-5.4-mini",
                        "family": "openai",
                        "context_window": 400000,
                        "capabilities": {
                            "tool_calling": True,
                            "vision": True,
                            "structured_output": True,
                            "reasoning": True,
                            "native_web_search": True,
                        },
                        "agent_capable": True,
                    }
                ],
            },
            {
                "provider": "anthropic",
                "ready": True,
                "model": "claude-sonnet-4-6",
                "selectable_model_details": [
                    {
                        "name": "claude-sonnet-4-6",
                        "family": "anthropic",
                        "context_window": 200000,
                        "capabilities": {
                            "tool_calling": True,
                            "vision": True,
                            "structured_output": True,
                            "reasoning": True,
                            "native_web_search": False,
                        },
                        "agent_capable": True,
                    }
                ],
            },
        ]
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("kendr.llm_router.all_provider_statuses", return_value=statuses),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state(
                "Create a 50-page market report.",
                multi_model_enabled=True,
                multi_model_strategy="best",
                workflow_type="deep_research",
                deep_research_mode=True,
                multi_model_stage_overrides={
                    "merge": {
                        "provider": "anthropic",
                        "model": "claude-sonnet-4-6",
                    }
                },
            )
            override = runtime._multi_model_override_for_agent(state, "long_document_agent")

        plan = state.get("multi_model_plan", {})
        self.assertEqual(plan.get("manual_stage_overrides", {}).get("merge", {}).get("provider"), "anthropic")
        self.assertEqual(plan.get("stage_models", {}).get("merge", {}).get("model"), "claude-sonnet-4-6")
        self.assertEqual(override.get("provider"), "anthropic")
        self.assertEqual(override.get("model"), "claude-sonnet-4-6")


if __name__ == "__main__":
    unittest.main()
