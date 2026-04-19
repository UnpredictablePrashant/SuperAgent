import os
import unittest
from unittest.mock import MagicMock, patch


os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")


class _FakeResponse:
    def __init__(self, *, response_id: str, status: str, output_text: str):
        self.id = response_id
        self.status = status
        self.output_text = output_text

    def model_dump(self):
        return {"id": self.id, "status": self.status, "output_text": self.output_text}


class DeepResearchAgentTests(unittest.TestCase):
    def test_deep_research_agent_delegates_public_workflow_to_long_document_agent(self):
        from tasks import research_tasks

        active_task = {
            "task_id": "task-1",
            "sender": "orchestrator_agent",
            "recipient": "deep_research_agent",
            "intent": "deep-research",
            "content": "Analyze the market structure",
            "status": "pending",
            "state_updates": {},
        }
        state = {
            "user_query": "Analyze the market structure",
            "workflow_type": "deep_research",
            "deep_research_mode": True,
            "long_document_mode": True,
            "active_task": active_task,
            "a2a": {"messages": [], "tasks": [active_task], "artifacts": []},
        }

        with (
            patch("tasks.research_tasks.begin_agent_session", return_value=(active_task, "Analyze the market structure", "orchestrator_agent")),
            patch("tasks.long_document_tasks.long_document_agent", side_effect=lambda current_state: {**current_state, "delegated_to": "long_document_agent"}),
            patch("tasks.research_tasks.log_task_update"),
        ):
            result = research_tasks.deep_research_agent(state)

        self.assertEqual(result["delegated_to"], "long_document_agent")
        self.assertEqual(state["active_task"]["recipient"], "long_document_agent")
        self.assertEqual(state["a2a"]["tasks"][0]["recipient"], "long_document_agent")

    def test_deep_research_agent_injects_kb_grounding_into_web_research(self):
        from tasks import research_tasks

        captured = {}
        fake_client = MagicMock()

        def _create(**kwargs):
            captured.update(kwargs)
            return _FakeResponse(response_id="resp-1", status="completed", output_text="grounded answer")

        fake_client.responses.create.side_effect = _create

        state = {
            "user_query": "Analyze the market structure",
            "research_kb_enabled": True,
            "research_web_search_enabled": True,
        }

        with (
            patch("tasks.research_tasks.begin_agent_session", return_value=(None, "", None)),
            patch("tasks.research_tasks.OpenAI", return_value=fake_client),
            patch(
                "tasks.research_tasks.build_research_grounding",
                return_value={
                    "kb_id": "kb-1",
                    "kb_name": "finance-kb",
                    "prompt_context": "Knowledge Base Grounding:\n- KB: finance-kb",
                    "hit_count": 2,
                    "citations": [{"source_id": "file:///tmp/report.md"}],
                },
            ),
            patch("tasks.research_tasks.write_text_file"),
            patch("tasks.research_tasks.publish_agent_output", side_effect=lambda state, *args, **kwargs: state),
        ):
            result = research_tasks.deep_research_agent(state)

        self.assertIn("Knowledge Base Grounding", captured["instructions"])
        self.assertTrue(result["research_kb_used"])
        self.assertEqual(result["research_kb_name"], "finance-kb")
        self.assertEqual(result["research_kb_hit_count"], 2)
        self.assertIn("Deep Research Brief", result["research_result"])
        self.assertIn("Coverage:", result["research_result"])
        self.assertIn("Sources:", result["research_result"])
        self.assertIn("Knowledge base: finance-kb (2 hits)", result["research_result"])
        self.assertIn("Web evidence: live web research enabled via", result["research_result"])
        self.assertIn("KB source: file:///tmp/report.md", result["research_result"])
        self.assertIn("Recommended Next Steps:", result["research_result"])
        self.assertIn("Knowledge base: finance-kb (2 hits)", result["research_source_summary"][0])
        self.assertTrue(any("Web evidence: live web research enabled via" in line for line in result["research_source_summary"]))
        self.assertEqual(result["deep_research_result_card"]["kind"], "brief")
        self.assertTrue(result["deep_research_result_card"]["web_search_enabled"])

    def test_deep_research_agent_rejects_kb_only_run_when_kb_fails(self):
        from tasks import research_tasks

        state = {
            "user_query": "Analyze the market structure",
            "research_kb_enabled": True,
            "research_web_search_enabled": False,
        }

        with (
            patch("tasks.research_tasks.begin_agent_session", return_value=(None, "", None)),
            patch("tasks.research_tasks.build_research_grounding", side_effect=ValueError("Knowledge base is not indexed yet.")),
        ):
            with self.assertRaises(ValueError) as exc:
                research_tasks.deep_research_agent(state)

        self.assertIn("no other evidence sources", str(exc.exception).lower())

    def test_deep_research_agent_supports_local_only_with_kb_and_explicit_urls(self):
        from tasks import research_tasks

        state = {
            "user_query": "Analyze the market structure",
            "research_kb_enabled": True,
            "research_web_search_enabled": False,
            "deep_research_source_urls": ["https://example.com/report"],
        }

        with (
            patch("tasks.research_tasks.begin_agent_session", return_value=(None, "", None)),
            patch(
                "tasks.research_tasks.build_research_grounding",
                return_value={
                    "kb_id": "kb-1",
                    "kb_name": "finance-kb",
                    "prompt_context": "Knowledge Base Grounding:\n- KB: finance-kb",
                    "hit_count": 1,
                    "citations": [{"source_id": "file:///tmp/report.md"}],
                },
            ),
            patch("tasks.research_tasks.fetch_url_content", return_value={"text": "Explicit URL evidence", "content_type": "text/html"}),
            patch("tasks.research_tasks.llm_text", return_value="local memo"),
            patch("tasks.research_tasks.write_text_file"),
            patch("tasks.research_tasks.publish_agent_output", side_effect=lambda state, *args, **kwargs: state),
        ):
            result = research_tasks.deep_research_agent(state)

        self.assertEqual(result["research_status"], "completed")
        self.assertTrue(result["research_kb_used"])
        self.assertEqual(result["research_kb_hit_count"], 1)
        self.assertEqual(result["research_raw"]["provided_url_count"], 1)
        self.assertIn("Deep Research Brief", result["research_result"])
        self.assertIn("Coverage:", result["research_result"])
        self.assertIn("Sources:", result["research_result"])
        self.assertIn("Knowledge base: finance-kb (1 hit)", result["research_result"])
        self.assertIn("Web evidence: disabled for this run", result["research_result"])
        self.assertIn("Provided URL: https://example.com/report", result["research_result"])
        self.assertIn("Recommended Next Steps:", result["research_result"])
        self.assertIn("- Provided URL: https://example.com/report", result["research_source_summary"])
        self.assertTrue(any("Web evidence: disabled for this run" in line for line in result["research_source_summary"]))
        self.assertEqual(result["deep_research_result_card"]["mode"], "local_only")

    def test_deep_research_agent_falls_back_to_kendr_web_search_for_non_native_models(self):
        from tasks import research_tasks

        state = {
            "user_query": "Analyze the market structure",
            "research_web_search_enabled": True,
        }

        with (
            patch("tasks.research_tasks.begin_agent_session", return_value=(None, "", None)),
            patch(
                "tasks.research_tasks.model_selection_for_agent",
                return_value={"provider": "ollama", "model": "lfm2.5-thinking:latest", "source": "runtime_override"},
            ),
            patch(
                "tasks.research_tasks.duckduckgo_html_search",
                return_value={
                    "results": [
                        {
                            "title": "Example report",
                            "url": "https://example.com/report",
                            "snippet": "Market structure analysis",
                            "source": "DuckDuckGo",
                            "date": "",
                        }
                    ]
                },
            ),
            patch(
                "tasks.research_tasks.fetch_urls_content",
                return_value=[
                    {
                        "url": "https://example.com/report",
                        "text": "Evidence about market structure and concentration trends.",
                        "content_type": "text/html",
                    }
                ],
            ),
            patch(
                "tasks.research_tasks.llm_text",
                return_value=(
                    "Findings section.\n\n"
                    "Sources:\n"
                    "- https://example.com/report"
                ),
            ),
            patch("tasks.research_tasks.write_text_file"),
            patch("tasks.research_tasks.publish_agent_output", side_effect=lambda current_state, *_args, **_kwargs: current_state),
        ):
            result = research_tasks.deep_research_agent(state)

        self.assertEqual(result["research_status"], "completed")
        self.assertEqual(result["research_model"], "lfm2.5-thinking:latest")
        self.assertEqual(result["research_provider"], "ollama")
        self.assertEqual(result["research_response_id"], "kendr_search_1")
        self.assertEqual(result["deep_research_result_card"]["search_backend"], "kendr_search")
        self.assertIn("Deep Research Brief", result["research_result"])
        self.assertTrue(any("Web source: Example report (https://example.com/report)" in line for line in result["research_source_summary"]))
