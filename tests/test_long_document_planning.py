import os
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from kendr.discovery import build_registry
from kendr.runtime import AgentRuntime
from tasks.long_document_tasks import _build_compiled_markdown, long_document_agent


class LongDocumentPlanningTests(unittest.TestCase):
    def test_build_compiled_markdown_escapes_quoted_title(self):
        markdown = _build_compiled_markdown(
            title='Market "Structure" Report',
            objective="Summarize the market structure.",
            section_outputs=[
                {
                    "index": 1,
                    "title": "Industry Baseline",
                    "section_text": "Baseline findings.",
                }
            ],
            executive_summary="Executive summary.",
            consolidated_references=[],
            citation_style="apa",
            methodology_text="Methodology.",
            plagiarism_report={"overall_score": 0.0, "ai_content_score": 0.0, "status": "PASS", "sections": []},
            source_entries=[],
            research_log_lines=[],
            generated_at="2026-04-02T00:00:00Z",
            model_name="gpt-test",
            deep_research_tier=2,
        )

        self.assertIn('title: "Market \\"Structure\\" Report"', markdown)

    def test_long_document_agent_requires_subplan_approval_before_execution(self):
        fake_setup_snapshot = {
            "available_agents": [str(card.get("agent_name", "")) for card in build_registry().agent_cards()],
            "disabled_agents": {},
            "setup_actions": [],
            "summary_text": "",
        }
        with patch("kendr.runtime.build_setup_snapshot", return_value=fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Create a 50-page market structure report.")
            state["current_objective"] = "Create a 50-page market structure report."
            state["long_document_mode"] = True
            state["long_document_pages"] = 50

            fake_outline = {
                "title": "Market Structure Report",
                "sections": [
                    {
                        "id": 1,
                        "title": "Industry Baseline",
                        "objective": "Set the baseline facts and market structure.",
                        "key_questions": ["What defines the market?", "Who are the major players?"],
                        "target_pages": 5,
                    }
                ],
            }

            with (
                patch("tasks.long_document_tasks._build_outline", return_value=fake_outline),
                patch("tasks.long_document_tasks.write_text_file"),
                patch("tasks.long_document_tasks.update_planning_file"),
                patch("tasks.long_document_tasks.log_task_update"),
            ):
                result = long_document_agent(state)

        self.assertTrue(result["long_document_plan_waiting_for_approval"])
        self.assertEqual(result["long_document_plan_status"], "pending")
        self.assertEqual(result["pending_user_input_kind"], "subplan_approval")
        self.assertEqual(result["approval_pending_scope"], "long_document_plan")
        self.assertIn("approve", result["draft_response"].lower())

    def test_long_document_agent_local_only_skips_web_research_and_uses_local_sources(self):
        state = {
            "current_objective": "Create a 30-page diligence report from the supplied files.",
            "user_query": "Create a 30-page diligence report from the supplied files.",
            "memory_soul_file": __file__,
            "deep_research_mode": True,
            "deep_research_confirmed": True,
            "long_document_mode": True,
            "long_document_pages": 30,
            "long_document_plan_status": "approved",
            "research_web_search_enabled": False,
            "deep_research_analysis": {
                "tier": 2,
                "requires_deep_research": True,
                "estimated_pages": 30,
                "estimated_sources": 6,
                "estimated_duration_minutes": 15,
                "subtopics": ["Financial Review"],
            },
            "long_document_outline": {
                "title": "Local Diligence Report",
                "sections": [
                    {
                        "id": 1,
                        "title": "Financial Review",
                        "objective": "Summarize the financial findings from local evidence.",
                        "key_questions": ["What changed year over year?"],
                        "target_pages": 3,
                    }
                ],
            },
            "local_drive_document_summaries": [
                {
                    "path": "/tmp/local-brief.txt",
                    "file_name": "local-brief.txt",
                    "type": "text/plain",
                    "char_count": 128,
                    "summary": "Revenue grew 30% in 2024 while churn declined by 4 percentage points.",
                    "error": "",
                }
            ],
        }

        def _fake_llm_text(prompt: str) -> str:
            prompt = str(prompt)
            if "Create a concise executive summary" in prompt:
                return "Local-only executive summary."
            if "without open web search" in prompt:
                return "Local evidence memo citing the uploaded file."
            return "## Financial Review\n\nThe uploaded file shows revenue growth and lower churn. [S1]"

        correlation = {
            "briefing": "Correlation briefing",
            "knowledge_graph": {"nodes": [], "edges": []},
            "cross_cutting_themes": [],
            "contradictions": [],
            "section_order": ["Financial Review"],
        }

        with (
            patch("tasks.long_document_tasks.OpenAI", return_value=Mock()),
            patch("tasks.long_document_tasks.llm_text", side_effect=_fake_llm_text),
            patch("tasks.long_document_tasks._build_correlation_package", return_value=correlation),
            patch("tasks.long_document_tasks._build_plagiarism_report", return_value={"overall_score": 0.0, "ai_content_score": 0.0, "status": "PASS", "sections": []}),
            patch("tasks.long_document_tasks._generate_visual_assets", return_value={"tables": [], "flowcharts": [], "notes": ""}),
            patch("tasks.long_document_tasks._export_long_document_formats", return_value={}),
            patch("tasks.long_document_tasks._run_research_pass") as mock_research_pass,
            patch("tasks.long_document_tasks._collect_google_search_evidence") as mock_google_search,
            patch("tasks.long_document_tasks.write_text_file"),
            patch("tasks.long_document_tasks.update_planning_file"),
            patch("tasks.long_document_tasks.log_task_update"),
            patch("tasks.long_document_tasks.publish_agent_output", side_effect=lambda current_state, *args, **kwargs: current_state),
        ):
            result = long_document_agent(state)

        mock_research_pass.assert_not_called()
        mock_google_search.assert_not_called()
        self.assertFalse(result["deep_research_result_card"]["web_search_enabled"])
        self.assertEqual(result["deep_research_result_card"]["local_sources"], 1)
        self.assertTrue(result["long_document_evidence_sources"])
        self.assertTrue(result["long_document_evidence_sources"][0]["url"].startswith("file:"))
        self.assertIn("Web search: disabled", result["draft_response"])


if __name__ == "__main__":
    unittest.main()
