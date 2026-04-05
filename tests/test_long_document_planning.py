import os
import time
import unittest
from unittest.mock import Mock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from kendr.discovery import build_registry
from kendr.runtime import AgentRuntime
from tasks.long_document_tasks import (
    _build_compiled_markdown,
    _build_deep_research_analysis_request,
    _default_subtopics,
    long_document_agent,
)


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
                patch("tasks.long_document_tasks.llm_json", side_effect=lambda *_args, **_kwargs: {}),
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
        self.assertIn("Section Outline", result["draft_response"])
        self.assertIn("Execution Plan", result["draft_response"])
        self.assertNotIn("**Steps", result["draft_response"])
        self.assertIn("approval_request", result)
        self.assertEqual(result["approval_request"]["scope"], "long_document_plan")

    def test_default_subtopics_extracts_clean_numbered_research_questions(self):
        objective = (
            "So I am looking to research all the data that social media platforms like Facebook, Instagram, WhatsApp, "
            "or TikTok capture pertaining to the users. Now what I'm trying to figure out is 1. What data are they capturing, "
            "2. What are they using the data sets for? 3. Who are they directly or indirectly selling the data to? "
            "4. What services a new microOTT or platform can capture in India, what to do with the data, and where we can sell the data directly or insights?"
        )

        topics = _default_subtopics(objective)

        self.assertGreaterEqual(len(topics), 4)
        self.assertIn("What data are they capturing", topics)
        self.assertIn("What are they using the data sets for", topics)
        self.assertIn("Who are they directly or indirectly selling the data to", topics)
        self.assertTrue(any("microOTT" in topic or "India" in topic for topic in topics))
        self.assertFalse(any(topic.lower().startswith("so i am looking") for topic in topics))

    def test_long_document_agent_uses_compact_deep_research_confirmation_prompt(self):
        fake_setup_snapshot = {
            "available_agents": [str(card.get("agent_name", "")) for card in build_registry().agent_cards()],
            "disabled_agents": {},
            "setup_actions": [],
            "summary_text": "",
        }
        with patch("kendr.runtime.build_setup_snapshot", return_value=fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Do exhaustive research on social-platform data collection and monetisation.")
            state["current_objective"] = state["user_query"]
            state["deep_research_mode"] = True
            state["long_document_mode"] = True
            state["long_document_pages"] = 25

            with (
                patch("tasks.long_document_tasks.llm_json", side_effect=lambda *_args, **_kwargs: {}),
                patch("tasks.long_document_tasks.write_text_file"),
                patch("tasks.long_document_tasks.update_planning_file"),
                patch("tasks.long_document_tasks.log_task_update"),
            ):
                result = long_document_agent(state)

        self.assertEqual(result["approval_pending_scope"], "deep_research_confirmation")
        self.assertIn("Deep Research Analysis", result["draft_response"])
        self.assertIn("Artifacts", result["draft_response"])
        self.assertNotIn("## Detected Subtopics", result["draft_response"])
        self.assertIn("approval_request", result)
        self.assertEqual(result["approval_request"]["scope"], "deep_research_confirmation")

    def test_deep_research_analysis_request_reflects_requested_scope_and_caps(self):
        request = _build_deep_research_analysis_request(
            title="Social Platform Data Study",
            analysis={
                "tier": 5,
                "reason": "query length suggests broad scope; explicit deep-analysis wording",
                "estimated_pages": 10,
                "estimated_sources": 50,
                "estimated_duration_minutes": 120,
                "requested_target_pages": 10,
                "subtopics": ["What data is captured"],
                "date_range": "all_time",
                "execution_budget": {"max_tokens": 0, "max_sources": 50, "max_duration_minutes": 0},
            },
            formats=["pdf", "md"],
            citation_style="apa",
            plagiarism_enabled=True,
            web_search_enabled=True,
            local_source_count=0,
            provided_url_count=0,
            analysis_storage_path="D:/tmp/analysis.md",
            version=1,
        )

        sections = {section["title"]: section["items"] for section in request["sections"]}
        self.assertIn("Page target: 10.", sections["Overview"])
        self.assertIn("Max sources: 50.", sections["Session Budget"])
        self.assertIn("Max tokens: not explicitly capped.", sections["Session Budget"])
        self.assertIn("query length suggests broad scope", sections["Why This Tier"][0])

    def test_long_document_agent_recomputes_analysis_when_requested_scope_changes(self):
        state = {
            "current_objective": "Create a deep research report on social platform data collection.",
            "user_query": "Create a deep research report on social platform data collection.",
            "memory_soul_file": __file__,
            "deep_research_mode": True,
            "long_document_mode": True,
            "long_document_pages": 10,
            "research_max_sources": 50,
            "research_date_range": "all_time",
            "research_output_formats": ["md"],
            "research_citation_style": "apa",
            "research_enable_plagiarism_check": True,
            "research_web_search_enabled": True,
            "deep_research_analysis": {
                "tier": 5,
                "estimated_pages": 25,
                "estimated_sources": 200,
                "estimated_duration_minutes": 120,
                "subtopics": ["stale analysis"],
                "requires_deep_research": True,
                "request_signature": {
                    "objective": "older objective",
                    "target_pages": 25,
                    "requested_sources": ["web"],
                    "date_range": "all_time",
                    "max_sources": 0,
                },
            },
        }

        with (
            patch("tasks.long_document_tasks.llm_json", side_effect=lambda *_args, **_kwargs: {}),
            patch("tasks.long_document_tasks.write_text_file"),
            patch("tasks.long_document_tasks.update_planning_file"),
            patch("tasks.long_document_tasks.log_task_update"),
        ):
            result = long_document_agent(state)

        sections = {section["title"]: section["items"] for section in result["approval_request"]["sections"]}
        self.assertIn("Page target: 10.", sections["Overview"])
        self.assertIn("Estimated pages: 10.", sections["Overview"])
        self.assertIn("Max sources: 50.", sections["Session Budget"])

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
        trace_titles = [event.get("title", "") for event in result.get("execution_trace", [])]
        self.assertIn("Deep research run started", trace_titles)
        self.assertIn("Collecting evidence bank", trace_titles)
        self.assertIn("Researching section 1/1", trace_titles)
        self.assertIn("Drafting section 1/1", trace_titles)
        self.assertIn("Compiling final report", trace_titles)

    def test_long_document_agent_records_search_queries_and_urls_in_trace(self):
        state = {
            "current_objective": "Create a web-backed market report.",
            "user_query": "Create a web-backed market report.",
            "memory_soul_file": __file__,
            "deep_research_mode": True,
            "deep_research_confirmed": True,
            "long_document_mode": True,
            "long_document_pages": 20,
            "long_document_plan_status": "approved",
            "research_web_search_enabled": True,
            "deep_research_analysis": {
                "tier": 3,
                "requires_deep_research": True,
                "estimated_pages": 20,
                "estimated_sources": 8,
                "estimated_duration_minutes": 20,
                "subtopics": ["Market Structure"],
            },
            "long_document_outline": {
                "title": "Web Market Report",
                "sections": [
                    {
                        "id": 1,
                        "title": "Market Structure",
                        "objective": "Explain market structure and major players.",
                        "key_questions": ["Who leads the market?"],
                        "target_pages": 3,
                    }
                ],
            },
        }

        def _fake_llm_text(prompt: str) -> str:
            prompt = str(prompt)
            if "Create a concise executive summary" in prompt:
                return "Web-backed executive summary."
            return "## Market Structure\n\nThe market is led by several major players. [S1]"

        search_payload = {
            "results": [
                {
                    "title": "Example Source",
                    "url": "https://example.com/market-report",
                    "snippet": "Market structure summary.",
                    "source": "Example",
                    "date": "2026-01-01",
                }
            ],
            "error": "",
        }
        research_pass = {
            "response_id": "resp-1",
            "status": "completed",
            "elapsed_seconds": 3,
            "output_text": "Research notes about market structure.",
            "raw": {},
        }
        correlation = {
            "briefing": "Correlation briefing",
            "knowledge_graph": {"nodes": [], "edges": []},
            "cross_cutting_themes": [],
            "contradictions": [],
            "section_order": ["Market Structure"],
        }

        with (
            patch("tasks.long_document_tasks.OpenAI", return_value=Mock()),
            patch("tasks.long_document_tasks.llm_text", side_effect=_fake_llm_text),
            patch("tasks.long_document_tasks._collect_google_search_evidence", return_value=search_payload),
            patch("tasks.long_document_tasks._run_research_pass", return_value=research_pass),
            patch("tasks.long_document_tasks._extract_source_entries", return_value=[{"id": "S1", "url": "https://example.com/market-report", "label": "Example Source"}]),
            patch("tasks.long_document_tasks._build_correlation_package", return_value=correlation),
            patch("tasks.long_document_tasks._build_plagiarism_report", return_value={"overall_score": 0.0, "ai_content_score": 0.0, "status": "PASS", "sections": []}),
            patch("tasks.long_document_tasks._generate_visual_assets", return_value={"tables": [], "flowcharts": [], "notes": ""}),
            patch("tasks.long_document_tasks._export_long_document_formats", return_value={}),
            patch("tasks.long_document_tasks.write_text_file"),
            patch("tasks.long_document_tasks.update_planning_file"),
            patch("tasks.long_document_tasks.log_task_update"),
            patch("tasks.long_document_tasks.publish_agent_output", side_effect=lambda current_state, *args, **kwargs: current_state),
        ):
            result = long_document_agent(state)

        trace_events = result.get("execution_trace", [])
        evidence_search = next(event for event in trace_events if event.get("title") == "Google search results gathered")
        section_search = next(event for event in trace_events if event.get("title") == "Google search results for section 1")
        self.assertEqual(evidence_search.get("command"), "Create a web-backed market report.")
        self.assertIn("https://example.com/market-report", evidence_search.get("metadata", {}).get("urls", []))
        self.assertEqual(section_search.get("command"), "Market Structure Explain market structure and major players.")
        self.assertIn("https://example.com/market-report", section_search.get("metadata", {}).get("urls", []))

    def test_long_document_agent_parallel_section_research_preserves_section_order(self):
        state = {
            "current_objective": "Create a two-section report.",
            "user_query": "Create a two-section report.",
            "memory_soul_file": __file__,
            "deep_research_mode": True,
            "deep_research_confirmed": True,
            "long_document_mode": True,
            "long_document_pages": 20,
            "long_document_plan_status": "approved",
            "long_document_collect_sources_first": False,
            "research_web_search_enabled": True,
            "research_section_concurrency": 2,
            "deep_research_analysis": {
                "tier": 3,
                "requires_deep_research": True,
                "estimated_pages": 20,
                "estimated_sources": 8,
                "estimated_duration_minutes": 20,
                "subtopics": ["Section One", "Section Two"],
            },
            "long_document_outline": {
                "title": "Parallel Report",
                "sections": [
                    {
                        "id": 1,
                        "title": "Section One",
                        "objective": "First objective.",
                        "key_questions": ["Q1"],
                        "target_pages": 3,
                    },
                    {
                        "id": 2,
                        "title": "Section Two",
                        "objective": "Second objective.",
                        "key_questions": ["Q2"],
                        "target_pages": 3,
                    },
                ],
            },
        }

        def _fake_llm_text(prompt: str) -> str:
            prompt = str(prompt)
            if "Create a concise executive summary" in prompt:
                return "Parallel executive summary."
            return "## Draft\n\nSection content. [S1]"

        def _fake_collect_section_package(**kwargs):
            index = int(kwargs["section_index"])
            if index == 1:
                time.sleep(0.05)
            return {
                "index": index,
                "title": str(kwargs["section"].get("title", f"Section {index}")),
                "objective": str(kwargs["section"].get("objective", "")),
                "key_questions": list(kwargs["section"].get("key_questions", [])),
                "target_pages": int(kwargs["section"].get("target_pages", 3)),
                "research_pass": {
                    "response_id": f"resp-{index}",
                    "status": "completed",
                    "elapsed_seconds": index,
                    "output_text": f"Research output for section {index}.",
                    "raw": {},
                },
                "research_text": f"Research output for section {index}.",
                "sources": [{"id": f"S{index}", "url": f"https://example.com/{index}", "label": f"Source {index}"}],
                "source_ledger_md": f"- [S{index}] Source {index}",
                "search_query": f"query {index}",
                "section_search_results": {"results": [{"url": f"https://example.com/{index}"}], "error": ""},
            }

        def _fake_record_section_package(*args, **kwargs):
            package = dict(kwargs["package"])
            package.pop("section_search_results", None)
            return package

        correlation = {
            "briefing": "Correlation briefing",
            "knowledge_graph": {"nodes": [], "edges": []},
            "cross_cutting_themes": [],
            "contradictions": [],
            "section_order": ["Section One", "Section Two"],
        }

        with (
            patch("tasks.long_document_tasks.OpenAI", return_value=Mock()),
            patch("tasks.long_document_tasks.llm_text", side_effect=_fake_llm_text),
            patch("tasks.long_document_tasks._collect_google_search_evidence", return_value={"results": [], "error": ""}),
            patch("tasks.long_document_tasks._collect_section_research_package", side_effect=_fake_collect_section_package),
            patch("tasks.long_document_tasks._record_section_research_package", side_effect=_fake_record_section_package),
            patch("tasks.long_document_tasks._build_correlation_package", return_value=correlation) as mock_correlation,
            patch("tasks.long_document_tasks._build_plagiarism_report", return_value={"overall_score": 0.0, "ai_content_score": 0.0, "status": "PASS", "sections": []}),
            patch("tasks.long_document_tasks._generate_visual_assets", return_value={"tables": [], "flowcharts": [], "notes": ""}),
            patch("tasks.long_document_tasks._export_long_document_formats", return_value={}),
            patch("tasks.long_document_tasks.write_text_file"),
            patch("tasks.long_document_tasks.update_planning_file"),
            patch("tasks.long_document_tasks.log_task_update"),
            patch("tasks.long_document_tasks.publish_agent_output", side_effect=lambda current_state, *args, **kwargs: current_state),
        ):
            long_document_agent(state)

        section_packages = mock_correlation.call_args.args[1]
        self.assertEqual([item["index"] for item in section_packages], [1, 2])


if __name__ == "__main__":
    unittest.main()
