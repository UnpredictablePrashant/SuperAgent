import os
import json
import time
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from kendr.discovery import build_registry
from kendr.runtime import AgentRuntime
from tasks.long_document_tasks import (
    _build_coverage_report,
    _build_evidence_ledger,
    _build_compiled_markdown,
    _build_deep_research_analysis_request,
    _collect_google_search_evidence,
    _collect_user_url_evidence,
    _collect_section_research_package,
    _default_subtopics,
    _ensure_local_source_manifest,
    _log_web_review,
    _strip_leading_section_heading,
    long_document_agent,
)
from tasks.utils import set_active_output_dir, suppress_console_logging


class LongDocumentPlanningTests(unittest.TestCase):
    def test_build_evidence_ledger_carries_metadata_and_section_links(self):
        ledger = _build_evidence_ledger(
            consolidated_references=[{"id": "S1", "url": "https://example.com/report", "label": "Market Report"}],
            section_outputs=[
                {
                    "index": 1,
                    "title": "Findings",
                    "references": [{"id": "S1", "url": "https://example.com/report", "label": "Market Report"}],
                }
            ],
            local_entries=[
                {
                    "path": "/tmp/data.xlsx",
                    "file_name": "data.xlsx",
                    "type": "xlsx",
                    "char_count": 520,
                    "reader": "openpyxl",
                    "summary": "Revenue table.",
                    "error": "",
                    "error_kind": "",
                }
            ],
            url_entries=[],
        )

        self.assertEqual(len(ledger), 2)
        web_entry = next(item for item in ledger if item["source_id"] == "S1")
        local_entry = next(item for item in ledger if item["source_id"].startswith("L"))
        self.assertIn("section-01", web_entry["used_in_sections"])
        self.assertIn("section-01", web_entry["claim_links"])
        self.assertEqual(local_entry["reader"], "openpyxl")
        self.assertEqual(local_entry["char_count"], 520)
        self.assertEqual(local_entry["extract_quality"], "high")

    def test_build_coverage_report_adds_revisit_plan_for_missing_and_failed_sources(self):
        coverage = _build_coverage_report(
            objective="Analyze spreadsheet evidence and diagrams.",
            intent={"source_needs": ["tables", "images"]},
            source_strategy={"summary": "docs first", "web_search_needed": False, "selection_notes": {}, "skip_notes": {}},
            local_manifest={
                "file_count": 6,
                "selected_file_count": 2,
                "selected_family_counts": {"document": 2},
                "excluded_reason_counts": {"family_budget_exhausted": 4},
                "files": [
                    {"name": "notes.txt", "exclusion_reason": ""},
                    {"name": "financials.xlsx", "exclusion_reason": "family_budget_exhausted"},
                    {"name": "deck.pptx", "exclusion_reason": "family_budget_exhausted"},
                ],
            },
            local_entries=[
                {"path": "/tmp/notes.txt", "file_name": "notes.txt", "error": "", "error_kind": ""},
                {"path": "/tmp/financials.xlsx", "file_name": "financials.xlsx", "error": "bad zip", "error_kind": "corrupt"},
            ],
            url_entries=[],
            kb_grounding={"requested": True, "kb_name": "finance-kb", "kb_status": "indexed", "hit_count": 0, "citations": []},
            kb_warning="Knowledge base returned no relevant results.",
            evidence_sources=[],
            consolidated_references=[],
        )

        self.assertEqual(coverage["failed_selected_files"], 1)
        self.assertIn("spreadsheet", coverage["missing_families"])
        self.assertTrue(coverage["revisit_plan"])
        self.assertEqual(coverage["failed_extractions"][0]["reason"], "corrupt")
        self.assertEqual(coverage["failed_extractions"][0]["message"], "bad zip")
        self.assertIn("financials.xlsx", json.dumps(coverage["revisit_plan"]))
        self.assertIn("deck.pptx", coverage["skipped_examples"]["family_budget_exhausted"])
        self.assertTrue(coverage["kb_enabled"])
        self.assertEqual(coverage["kb_hit_count"], 0)
        self.assertEqual(coverage["kb_warning"], "Knowledge base returned no relevant results.")

    def test_build_compiled_markdown_uses_linked_toc_and_footer_without_internal_metadata(self):
        markdown = _build_compiled_markdown(
            title='Market "Structure" Report',
            objective="Summarize the market structure.",
            section_outputs=[
                {
                    "index": 1,
                    "title": "Industry Baseline",
                    "section_text": "## Industry Baseline\n\nBaseline findings.",
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

        self.assertIn('# Market "Structure" Report {#report-title}', markdown)
        self.assertIn('- [1. Industry Baseline](#section-1-industry-baseline)', markdown)
        self.assertNotIn('title: "Market \\"Structure\\" Report"', markdown)
        self.assertNotIn("model: gpt-test", markdown)
        self.assertNotIn("Generated by Kendr Deep Research", markdown)
        self.assertIn("_Prepared with Kendr Deep Research on 2026-04-02T00:00:00Z._", markdown)
        self.assertEqual(markdown.count("## 1. Industry Baseline {#section-1-industry-baseline}"), 1)

    def test_strip_leading_section_heading_removes_duplicate_wrapper_title(self):
        section_text = "Section 3: Risk Outlook\n\nThis section analyzes downside cases."
        cleaned = _strip_leading_section_heading(section_text, section_title="Risk Outlook", section_index=3)
        self.assertEqual(cleaned, "This section analyzes downside cases.")

    def test_collect_section_research_package_merges_kb_sources(self):
        with patch(
            "tasks.long_document_tasks.build_research_grounding",
            return_value={
                "kb_id": "kb-1",
                "kb_name": "finance-kb",
                "kb_status": "indexed",
                "hit_count": 1,
                "prompt_context": "Knowledge Base Grounding:\n- KB: finance-kb",
                "citations": [
                    {
                        "source_id": "file:///tmp/report.md",
                        "url": "file:///tmp/report.md",
                        "path": "/tmp/report.md",
                        "label": "report.md",
                        "source_type": "local_file",
                        "kb_provenance": {"kb_id": "kb-1", "kb_name": "finance-kb"},
                        "chunk_index": 0,
                        "score": 0.9,
                    }
                ],
            },
        ):
            package = _collect_section_research_package(
                api_key="test-openai-key",
                objective="Analyze the market",
                section={"title": "Industry Baseline", "objective": "Summarize the baseline", "key_questions": []},
                section_index=1,
                total_sections=1,
                section_pages=5,
                use_section_search=False,
                section_search_results_count=3,
                collect_sources_first=False,
                evidence_excerpt="",
                evidence_sources=[],
                explicit_source_entries=[],
                local_entries=[],
                url_entries=[],
                continuity_notes=[],
                coherence_context_md="",
                web_search_enabled=False,
                native_web_search_enabled=False,
                research_model="o4-mini-deep-research",
                research_instructions="Be careful.",
                max_tool_calls=4,
                max_output_tokens_int=None,
                poll_interval_seconds=1,
                max_wait_seconds=60,
                heartbeat_seconds=30,
                max_sources=20,
                research_kb_enabled=True,
                research_kb_id="finance-kb",
                research_kb_top_k=8,
            )

        self.assertEqual(package["research_kb"]["kb_name"], "finance-kb")
        self.assertIn("Knowledge Base Grounding", package["research_text"])
        self.assertTrue(package["sources"])
        self.assertEqual(package["sources"][0]["url"], "file:///tmp/report.md")

    def test_collect_section_research_package_falls_back_to_kendr_search_when_native_search_is_unavailable(self):
        search_payload = {
            "results": [
                {
                    "title": "Example Source",
                    "url": "https://example.com/fallback",
                    "snippet": "Fallback search evidence.",
                    "evidence_excerpt": "Viewed evidence excerpt.",
                }
            ],
            "viewed_pages": [{"url": "https://example.com/fallback", "excerpt": "Viewed evidence excerpt."}],
            "provider": "duckduckgo",
            "providers_tried": ["duckduckgo"],
            "error": "",
        }

        with (
            patch("tasks.long_document_tasks._collect_google_search_evidence", return_value=search_payload) as mock_search,
            patch("tasks.long_document_tasks._run_research_pass") as mock_native_search,
        ):
            package = _collect_section_research_package(
                api_key="",
                objective="Analyze the market",
                section={"title": "Industry Baseline", "objective": "Summarize the baseline", "key_questions": []},
                section_index=1,
                total_sections=1,
                section_pages=5,
                use_section_search=False,
                section_search_results_count=3,
                collect_sources_first=False,
                evidence_excerpt="",
                evidence_sources=[],
                explicit_source_entries=[],
                local_entries=[],
                url_entries=[],
                continuity_notes=[],
                coherence_context_md="",
                web_search_enabled=True,
                native_web_search_enabled=False,
                research_model="llama3.2",
                research_instructions="Be careful.",
                max_tool_calls=4,
                max_output_tokens_int=None,
                poll_interval_seconds=1,
                max_wait_seconds=60,
                heartbeat_seconds=30,
                max_sources=20,
                research_kb_enabled=False,
                research_kb_id="",
                research_kb_top_k=8,
            )

        mock_search.assert_called_once()
        mock_native_search.assert_not_called()
        self.assertEqual(package["research_pass"]["status"], "fallback_web_search")
        self.assertIn("Web search results", package["research_text"])
        self.assertEqual(package["sources"][0]["url"], "https://example.com/fallback")

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

    def test_long_document_agent_honors_explicit_research_provider_for_native_search_mode(self):
        fake_setup_snapshot = {
            "available_agents": [str(card.get("agent_name", "")) for card in build_registry().agent_cards()],
            "disabled_agents": {},
            "setup_actions": [],
            "summary_text": "",
        }
        with patch("kendr.runtime.build_setup_snapshot", return_value=fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Create a sourced market structure report.")
            state["current_objective"] = "Create a sourced market structure report."
            state["long_document_mode"] = True
            state["long_document_pages"] = 25
            state["provider"] = "anthropic"
            state["model"] = "claude-sonnet-4-6"
            state["research_provider"] = "openai"
            state["research_model"] = "gpt-5.1"

            fake_outline = {
                "title": "Market Structure Report",
                "sections": [
                    {
                        "id": 1,
                        "title": "Industry Baseline",
                        "objective": "Set the baseline facts and market structure.",
                        "key_questions": ["What defines the market?"],
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

        self.assertEqual(result["research_provider"], "openai")
        self.assertEqual(result["research_model"], "gpt-5.1")
        self.assertEqual(result["research_web_search_mode"], "native_model")

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
                "depth_mode": "brief",
                "depth_label": "Focused Brief",
                "depth_description": "Tight synthesis of the most important findings with a narrower evidence sweep.",
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
        self.assertIn("Research depth: Focused Brief.", sections["Overview"])
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
        self.assertIn("Research depth: Focused Brief.", sections["Overview"])
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
        self.assertIn("deep_research_intent", result)
        self.assertIn("deep_research_source_strategy", result)
        self.assertIn("deep_research_evidence_ledger", result)
        self.assertIn("deep_research_coverage_report", result)
        self.assertIn("deep_research_quality_report", result)
        self.assertIn("deep_research_artifacts_manifest", result)
        self.assertIn("source_ledger_path", result["deep_research_result_card"])
        self.assertIn("coverage_status", result["deep_research_result_card"])
        self.assertIn("quality_status", result["deep_research_result_card"])
        self.assertIn("intent_summary", result["deep_research_result_card"])
        self.assertIn("strategy_summary", result["deep_research_result_card"])
        self.assertIn("family_budgets", result["deep_research_result_card"])
        self.assertIn("source_needs", result["deep_research_result_card"])
        self.assertTrue(result["deep_research_artifacts_manifest"]["created_artifacts"])
        self.assertTrue(result["long_document_evidence_sources"])
        self.assertTrue(result["long_document_evidence_sources"][0]["url"].startswith("file:"))
        self.assertIn("Web search: disabled", result["draft_response"])
        trace_titles = [event.get("title", "") for event in result.get("execution_trace", [])]
        self.assertIn("Deep research run started", trace_titles)
        self.assertIn("Research intent discovered", trace_titles)
        self.assertIn("Source strategy planned", trace_titles)
        self.assertIn("Coverage report updated", trace_titles)
        self.assertIn("Researching section 1/1", trace_titles)
        self.assertIn("Drafting section 1/1", trace_titles)
        self.assertIn("Compiling final report", trace_titles)

    def test_long_document_agent_local_only_does_not_require_openai_key(self):
        state = {
            "current_objective": "Draft a report from local files only.",
            "user_query": "Draft a report from local files only.",
            "memory_soul_file": __file__,
            "deep_research_mode": True,
            "deep_research_confirmed": True,
            "long_document_mode": True,
            "long_document_pages": 15,
            "long_document_plan_status": "approved",
            "research_web_search_enabled": False,
            "provider": "ollama",
            "model": "llama3.2",
            "long_document_outline": {
                "title": "Local Report",
                "sections": [
                    {
                        "id": 1,
                        "title": "Local Findings",
                        "objective": "Summarize the local evidence.",
                        "key_questions": [],
                        "target_pages": 2,
                    }
                ],
            },
            "deep_research_analysis": {
                "tier": 2,
                "requires_deep_research": True,
                "estimated_pages": 15,
                "estimated_sources": 4,
                "estimated_duration_minutes": 10,
                "subtopics": ["Local Findings"],
            },
            "local_drive_document_summaries": [
                {
                    "path": "/tmp/local.txt",
                    "file_name": "local.txt",
                    "type": "text/plain",
                    "char_count": 120,
                    "summary": "Local evidence summary.",
                    "error": "",
                }
            ],
        }

        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": ""}),
            patch("tasks.long_document_tasks.llm_text", return_value="Local findings with citations. [S1]"),
            patch("tasks.long_document_tasks._build_correlation_package", return_value={
                "briefing": "Correlation briefing",
                "knowledge_graph": {"nodes": [], "edges": []},
                "cross_cutting_themes": [],
                "contradictions": [],
                "section_order": ["Local Findings"],
            }),
            patch("tasks.long_document_tasks._build_plagiarism_report", return_value={"overall_score": 0.0, "ai_content_score": 0.0, "status": "PASS", "sections": []}),
            patch("tasks.long_document_tasks._generate_visual_assets", return_value={"tables": [], "flowcharts": [], "notes": ""}),
            patch("tasks.long_document_tasks._export_long_document_formats", return_value={}),
            patch("tasks.long_document_tasks.update_planning_file"),
            patch("tasks.long_document_tasks.publish_agent_output", side_effect=lambda current_state, *args, **kwargs: current_state),
        ):
            result = long_document_agent(state)

        self.assertFalse(result["deep_research_result_card"]["web_search_enabled"])
        self.assertEqual(result["long_document_title"], "Deep Research Report")

    def test_long_document_agent_builds_source_manifest_from_local_folder_inputs(self):
        objective = "Draft a report from the attached nested local folder."
        correlation = {
            "briefing": "Correlation briefing",
            "knowledge_graph": {"nodes": [], "edges": []},
            "cross_cutting_themes": [],
            "contradictions": [],
            "section_order": ["Local Findings"],
        }

        with tempfile.TemporaryDirectory() as tmp_source, tempfile.TemporaryDirectory() as tmp_output:
            nested_dir = Path(tmp_source) / "nested"
            nested_dir.mkdir(parents=True, exist_ok=True)
            first_path = nested_dir / "financials.txt"
            second_path = Path(tmp_source) / "notes.md"
            first_path.write_text("Revenue grew 22% and margins improved in 2025.", encoding="utf-8")
            second_path.write_text("Decision: prioritize regional expansion and cost controls.", encoding="utf-8")

            state = {
                "current_objective": objective,
                "user_query": objective,
                "memory_soul_file": __file__,
                "deep_research_mode": True,
                "deep_research_confirmed": True,
                "long_document_mode": True,
                "long_document_pages": 15,
                "long_document_plan_status": "approved",
                "research_web_search_enabled": False,
                "local_drive_paths": [tmp_source],
                "local_drive_working_directory": tmp_source,
                "deep_research_analysis": {
                    "tier": 2,
                    "requires_deep_research": True,
                    "estimated_pages": 15,
                    "estimated_sources": 4,
                    "estimated_duration_minutes": 10,
                    "subtopics": ["Local Findings"],
                },
                "long_document_outline": {
                    "title": "Nested Folder Report",
                    "sections": [
                        {
                            "id": 1,
                            "title": "Local Findings",
                            "objective": "Summarize the local evidence.",
                            "key_questions": [],
                            "target_pages": 2,
                        }
                    ],
                },
            }

            def _fake_llm_text(prompt: str) -> str:
                prompt = str(prompt)
                if "document-reading sub-agent" in prompt:
                    if "financials.txt" in prompt:
                        return "Financials summary with revenue growth and margin improvement."
                    if "notes.md" in prompt:
                        return "Notes summary with decisions about expansion and cost controls."
                    return "Generic local file summary."
                if "knowledge-synthesis agent. Build one actionable summary" in prompt:
                    return "- Key finding: local files show growth and operational priorities."
                if "without open web search" in prompt:
                    return "Local-only evidence memo anchored in the attached folder."
                if "Create a concise executive summary" in prompt:
                    return "Nested folder executive summary."
                return "## Local Findings\n\nNested local folder findings. [S1]"

            set_active_output_dir(tmp_output)
            try:
                with (
                    patch("tasks.long_document_tasks.llm_text", side_effect=_fake_llm_text),
                    patch("tasks.long_document_tasks._build_correlation_package", return_value=correlation),
                    patch("tasks.long_document_tasks._build_plagiarism_report", return_value={"overall_score": 0.0, "ai_content_score": 0.0, "status": "PASS", "sections": []}),
                    patch("tasks.long_document_tasks._generate_visual_assets", return_value={"tables": [], "flowcharts": [], "notes": ""}),
                    patch("tasks.long_document_tasks._export_long_document_formats", return_value={}),
                    patch("tasks.long_document_tasks.update_planning_file"),
                    patch("tasks.long_document_tasks.log_task_update"),
                    patch("tasks.long_document_tasks.publish_agent_output", side_effect=lambda current_state, *args, **kwargs: current_state),
                ):
                    result = long_document_agent(state)
            finally:
                set_active_output_dir("output")

            artifact_dir = Path(tmp_output) / "deep_research_runs" / "deep_research_run_1"
            source_manifest_path = artifact_dir / "source_manifest.md"
            source_manifest_json_path = artifact_dir / "source_manifest.json"

            self.assertTrue(source_manifest_path.exists())
            self.assertTrue(source_manifest_json_path.exists())

            source_manifest = json.loads(source_manifest_json_path.read_text(encoding="utf-8"))
            source_manifest_md = source_manifest_path.read_text(encoding="utf-8")

        self.assertEqual(result["deep_research_result_card"]["selected_local_files"], 2)
        self.assertEqual(result["deep_research_result_card"]["discovered_files"], 2)
        self.assertTrue(result["long_document_source_manifest_path"].endswith("source_manifest.md"))
        self.assertTrue(result["long_document_source_manifest_json_path"].endswith("source_manifest.json"))
        self.assertIn("Source manifest", result["draft_response"])
        self.assertEqual(source_manifest["manifest"]["selected_file_count"], 2)
        self.assertEqual(len(source_manifest["document_summaries"]), 2)
        self.assertIn("nested/", source_manifest_md)
        self.assertIn("financials.txt [selected]", source_manifest_md)
        self.assertIn("notes.md [selected]", source_manifest_md)

    def test_ensure_local_source_manifest_logs_each_reviewed_local_file(self):
        objective = "Review the attached local files."

        with tempfile.TemporaryDirectory() as tmp_source, tempfile.TemporaryDirectory() as tmp_output:
            alpha_path = Path(tmp_source) / "alpha.txt"
            beta_path = Path(tmp_source) / "nested" / "beta.md"
            beta_path.parent.mkdir(parents=True, exist_ok=True)
            alpha_path.write_text("Alpha evidence.", encoding="utf-8")
            beta_path.write_text("Beta evidence.", encoding="utf-8")

            state = {
                "current_objective": objective,
                "user_query": objective,
                "local_drive_paths": [tmp_source],
                "local_drive_working_directory": tmp_source,
                "local_drive_recursive": True,
            }

            set_active_output_dir(tmp_output)
            try:
                with (
                    suppress_console_logging(),
                    patch("tasks.long_document_tasks.llm_text", return_value="Concise local summary."),
                ):
                    manifest = _ensure_local_source_manifest(
                        state,
                        objective=objective,
                        artifact_dir="deep_research_runs/deep_research_run_1",
                        source_strategy={},
                    )
                log_text = (Path(tmp_output) / "execution.log").read_text(encoding="utf-8")
            finally:
                set_active_output_dir("output")

        self.assertTrue(manifest["manifest"]["selected_file_count"] >= 2)
        self.assertIn("Reviewing local file [1/2]: alpha.txt", log_text)
        self.assertIn("Reviewing local file [2/2]: nested/beta.md", log_text)
        self.assertIn("Reviewed local file [1/2]: alpha.txt", log_text)
        self.assertIn("Reviewed local file [2/2]: nested/beta.md", log_text)

    def test_collect_user_url_evidence_logs_each_reviewed_website(self):
        objective = "Review user-provided websites."
        state = {
            "deep_research_source_urls": [
                "https://example.com/report",
                "https://sample.org/brief",
            ]
        }

        def _fake_fetch(url: str, timeout: int = 20) -> dict:
            return {"url": url, "text": f"Evidence from {url}", "content_type": "text/html"}

        with tempfile.TemporaryDirectory() as tmp_output:
            set_active_output_dir(tmp_output)
            try:
                with (
                    suppress_console_logging(),
                    patch("tasks.long_document_tasks.fetch_url_content", side_effect=_fake_fetch),
                    patch("tasks.long_document_tasks.llm_text", return_value="Website summary."),
                ):
                    entries = _collect_user_url_evidence(objective, state)
                log_text = (Path(tmp_output) / "execution.log").read_text(encoding="utf-8")
            finally:
                set_active_output_dir("output")

        self.assertEqual(len(entries), 2)
        self.assertIn("Reviewing website [1/2]: example.com/report", log_text)
        self.assertIn("Reviewing website [2/2]: sample.org/brief", log_text)
        self.assertIn("Reviewed website [1/2]: example.com/report", log_text)
        self.assertIn("Reviewed website [2/2]: sample.org/brief", log_text)

    def test_collect_google_search_evidence_logs_each_reviewed_search_page(self):
        def _fake_search(query: str, *, num: int = 10, fetch_pages: int = 3, progress_callback=None, **kwargs) -> dict:
            viewed_pages = [
                {"url": "https://who.int/nutrition", "text": "WHO evidence", "content_type": "text/html"},
                {"url": "https://nih.gov/health", "text": "NIH evidence", "content_type": "text/html"},
            ]
            for idx, page in enumerate(viewed_pages, start=1):
                if progress_callback:
                    progress_callback(page["url"], "started", None, idx, len(viewed_pages))
                    progress_callback(page["url"], "completed", page, idx, len(viewed_pages))
            return {
                "provider": "duckduckgo_html",
                "providers_tried": ["duckduckgo_html"],
                "query_plan": [
                    {"query": "banana health effects", "scope": "web", "timelimit": ""},
                    {"query": "banana health effects clinical evidence", "scope": "academic", "timelimit": "m"},
                ],
                "results": [
                    {"title": "WHO page", "url": "https://who.int/nutrition", "snippet": ""},
                    {"title": "NIH page", "url": "https://nih.gov/health", "snippet": ""},
                ],
                "viewed_pages": viewed_pages,
                "error": "",
            }

        with tempfile.TemporaryDirectory() as tmp_output:
            set_active_output_dir(tmp_output)
            try:
                with (
                    suppress_console_logging(),
                    patch("tasks.long_document_tasks.fetch_search_results", side_effect=_fake_search),
                ):
                    payload = _collect_google_search_evidence(
                        "banana health effects",
                        progress_callback=lambda url, status, payload, position, total: _log_web_review(
                            url,
                            status=status,
                            position=position,
                            total=total,
                            payload=payload,
                            context="search result website",
                        ),
                    )
                log_text = (Path(tmp_output) / "execution.log").read_text(encoding="utf-8")
            finally:
                set_active_output_dir("output")

        self.assertEqual(len(payload["viewed_pages"]), 2)
        self.assertIn("Search query [1/2] via duckduckgo_html: banana health effects", log_text)
        self.assertIn(
            "Search query [2/2] via duckduckgo_html: banana health effects clinical evidence (academic, timelimit=m)",
            log_text,
        )
        self.assertIn("Collected search result [1/2] via duckduckgo_html: who.int/nutrition — WHO page", log_text)
        self.assertIn("Collected search result [2/2] via duckduckgo_html: nih.gov/health — NIH page", log_text)
        self.assertIn("Reviewing search result website [1/2]: who.int/nutrition", log_text)
        self.assertIn("Reviewing search result website [2/2]: nih.gov/health", log_text)
        self.assertIn("Reviewed search result website [1/2]: who.int/nutrition", log_text)
        self.assertIn("Reviewed search result website [2/2]: nih.gov/health", log_text)

    def test_collect_google_search_evidence_respects_selected_search_backend(self):
        captured = {}

        def _fake_search(query: str, *, num: int = 10, fetch_pages: int = 3, progress_callback=None, **kwargs) -> dict:
            captured["provider_hint"] = kwargs.get("provider_hint")
            return {
                "provider": "serpapi",
                "providers_tried": ["serpapi"],
                "results": [{"title": "Example", "url": "https://example.com/report", "snippet": ""}],
                "viewed_pages": [],
                "error": "",
            }

        with patch("tasks.long_document_tasks.fetch_search_results", side_effect=_fake_search):
            payload = _collect_google_search_evidence(
                "banana health effects",
                search_backend="serpapi",
            )

        self.assertEqual(captured.get("provider_hint"), "serpapi")
        self.assertEqual(payload["provider"], "serpapi")

    def test_long_document_agent_uses_kendr_search_for_non_openai_web_research(self):
        state = {
            "current_objective": "Run a web-backed research report.",
            "user_query": "Run a web-backed research report.",
            "memory_soul_file": __file__,
            "deep_research_mode": True,
            "deep_research_confirmed": True,
            "long_document_mode": True,
            "long_document_pages": 20,
            "long_document_plan_status": "approved",
            "research_web_search_enabled": True,
            "provider": "ollama",
            "model": "llama3.2",
            "deep_research_analysis": {
                "tier": 3,
                "requires_deep_research": True,
                "estimated_pages": 20,
                "estimated_sources": 8,
                "estimated_duration_minutes": 20,
                "subtopics": ["Market Structure"],
            },
            "long_document_outline": {
                "title": "Fallback Search Report",
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
                return "Fallback-search executive summary."
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
            "viewed_pages": [{"url": "https://example.com/market-report", "excerpt": "Viewed evidence excerpt."}],
            "provider": "duckduckgo",
            "providers_tried": ["duckduckgo"],
            "error": "",
        }
        correlation = {
            "briefing": "Correlation briefing",
            "knowledge_graph": {"nodes": [], "edges": []},
            "cross_cutting_themes": [],
            "contradictions": [],
            "section_order": ["Market Structure"],
        }

        with (
            patch.dict(os.environ, {"OPENAI_API_KEY": ""}),
            patch("tasks.long_document_tasks.llm_text", side_effect=_fake_llm_text),
            patch("tasks.long_document_tasks._collect_google_search_evidence", return_value=search_payload) as mock_search,
            patch("tasks.long_document_tasks._run_research_pass") as mock_native_search,
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

        mock_search.assert_called()
        mock_native_search.assert_not_called()
        self.assertTrue(result["deep_research_result_card"]["web_search_enabled"])
        self.assertEqual(result["deep_research_result_card"]["web_search_mode"], "kendr_search")
        self.assertIn("Report downloads in chat", result["draft_response"])
        self.assertIn("Artifact bundle: deep_research_runs/deep_research_run_1", result["draft_response"])
        self.assertIn("Markdown report: deep_research_runs/deep_research_run_1/report.md", result["draft_response"])
        self.assertIn("Research manifest: deep_research_runs/deep_research_run_1/deep_research_manifest.json", result["draft_response"])
        self.assertIn("Kendr search client", result["draft_response"])
        self.assertNotIn("output/", result["draft_response"])

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

    def test_long_document_agent_resume_reuses_completed_evidence_and_sections(self):
        objective = "Create a resumed deep research report."
        state = {
            "current_objective": objective,
            "user_query": objective,
            "memory_soul_file": __file__,
            "deep_research_mode": True,
            "deep_research_confirmed": True,
            "long_document_mode": True,
            "long_document_pages": 10,
            "long_document_plan_status": "approved",
            "long_document_collect_sources_first": True,
            "research_web_search_enabled": True,
            "resume_source_run_id": "ui-old-run",
            "long_document_calls": 1,
            "deep_research_analysis": {
                "tier": 3,
                "requires_deep_research": True,
                "estimated_pages": 10,
                "estimated_sources": 8,
                "estimated_duration_minutes": 20,
                "subtopics": ["Market Structure"],
                "request_signature": {
                    "objective": objective,
                    "target_pages": 10,
                    "requested_sources": [],
                    "date_range": "all_time",
                    "max_sources": 0,
                },
            },
            "long_document_outline": {
                "title": "Resume Report",
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

        correlation = {
            "briefing": "Correlation briefing",
            "knowledge_graph": {"nodes": [], "edges": []},
            "cross_cutting_themes": [],
            "contradictions": [],
            "section_order": ["Market Structure"],
        }

        with tempfile.TemporaryDirectory() as tmp_output:
            set_active_output_dir(tmp_output)
            try:
                artifact_root = Path(tmp_output) / "deep_research_runs" / "deep_research_run_1"
                section_dir = artifact_root / "section_01"
                section_dir.mkdir(parents=True, exist_ok=True)
                (artifact_root / "evidence_bank.md").write_text("# Evidence Bank\n\nCached evidence.", encoding="utf-8")
                (artifact_root / "evidence_bank.json").write_text(
                    json.dumps(
                        {
                            "objective": objective,
                            "source_ledger": [{"id": "S1", "url": "https://example.com/source", "label": "Example Source"}],
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                (section_dir / "research.json").write_text(
                    json.dumps(
                        {
                            "response_id": "resp-cached-1",
                            "status": "completed",
                            "elapsed_seconds": 2,
                            "output_text": "Cached section research output.",
                            "raw": {},
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                (section_dir / "sources.json").write_text(
                    json.dumps([{"id": "S1", "url": "https://example.com/source", "label": "Example Source"}], indent=2),
                    encoding="utf-8",
                )
                (section_dir / "section.md").write_text("## Market Structure\n\nCached section draft. [S1]\n", encoding="utf-8")
                (section_dir / "continuity.txt").write_text("- Cached continuity note.", encoding="utf-8")
                (section_dir / "visual_assets.json").write_text(json.dumps({"tables": [], "flowcharts": [], "notes": ""}, indent=2), encoding="utf-8")
                (section_dir / "section_metadata.json").write_text(
                    json.dumps({"section_index": 1, "section_title": "Market Structure", "flowchart_files": [], "section_images": []}, indent=2),
                    encoding="utf-8",
                )

                def _fake_llm_text(prompt: str) -> str:
                    if "Create a concise executive summary" in str(prompt):
                        return "Resume-aware executive summary."
                    raise AssertionError("Section drafting LLM call should be skipped on resume.")

                with (
                    patch("tasks.long_document_tasks.OpenAI", return_value=Mock()),
                    patch("tasks.long_document_tasks.llm_text", side_effect=_fake_llm_text),
                    patch("tasks.long_document_tasks._collect_section_research_package") as mock_collect_section_research,
                    patch("tasks.long_document_tasks._run_research_pass") as mock_research_pass,
                    patch("tasks.long_document_tasks._collect_google_search_evidence") as mock_google_search,
                    patch("tasks.long_document_tasks._build_correlation_package", return_value=correlation),
                    patch("tasks.long_document_tasks._build_plagiarism_report", return_value={"overall_score": 0.0, "ai_content_score": 0.0, "status": "PASS", "sections": []}),
                    patch("tasks.long_document_tasks._generate_visual_assets", return_value={"tables": [], "flowcharts": [], "notes": ""}) as mock_visuals,
                    patch("tasks.long_document_tasks._export_long_document_formats", return_value={}),
                    patch("tasks.long_document_tasks.update_planning_file"),
                    patch("tasks.long_document_tasks.log_task_update"),
                    patch("tasks.long_document_tasks.publish_agent_output", side_effect=lambda current_state, *args, **kwargs: current_state),
                ):
                    result = long_document_agent(state)
            finally:
                set_active_output_dir("output")

        mock_collect_section_research.assert_not_called()
        mock_research_pass.assert_not_called()
        mock_google_search.assert_not_called()
        mock_visuals.assert_not_called()
        self.assertTrue(str(result.get("long_document_artifact_dir", "")).endswith("deep_research_runs/deep_research_run_1"))
        self.assertEqual(result.get("long_document_sections_data", [{}])[0].get("title"), "Market Structure")

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

    def test_long_document_agent_kb_only_pipeline_writes_kb_backed_report_artifacts(self):
        objective = "Create a private-knowledge market report."
        state = {
            "current_objective": objective,
            "user_query": objective,
            "memory_soul_file": __file__,
            "deep_research_mode": True,
            "deep_research_confirmed": True,
            "long_document_mode": True,
            "long_document_pages": 12,
            "long_document_plan_status": "approved",
            "research_web_search_enabled": False,
            "research_kb_enabled": True,
            "research_kb_id": "finance-kb",
            "research_kb_top_k": 6,
            "deep_research_analysis": {
                "tier": 3,
                "requires_deep_research": True,
                "estimated_pages": 12,
                "estimated_sources": 6,
                "estimated_duration_minutes": 10,
                "subtopics": ["Industry Baseline"],
            },
            "long_document_outline": {
                "title": "KB-Only Market Report",
                "sections": [
                    {
                        "id": 1,
                        "title": "Industry Baseline",
                        "objective": "Summarize the baseline using private knowledge.",
                        "key_questions": ["What did private documents say about 2024 market changes?"],
                        "target_pages": 3,
                    }
                ],
            },
        }

        def _fake_grounding(query: str, **_kwargs):
            citations = [
                {
                    "source_id": "file:///tmp/private-market-report.md",
                    "url": "file:///tmp/private-market-report.md",
                    "path": "/tmp/private-market-report.md",
                    "label": "private-market-report.md",
                    "source_type": "local_file",
                    "kb_provenance": {"kb_id": "kb-1", "kb_name": "finance-kb"},
                    "chunk_index": 0 if "Industry Baseline" not in str(query) else 1,
                    "score": 0.91,
                }
            ]
            return {
                "requested": True,
                "used": True,
                "kb_id": "kb-1",
                "kb_name": "finance-kb",
                "kb_status": "indexed",
                "hit_count": len(citations),
                "raw_hits": [{"score": 0.91, "text": "Private market report evidence."}],
                "citations": citations,
                "deduped_source_ids": ["file:///tmp/private-market-report.md"],
                "prompt_context": "Knowledge Base Grounding:\n- KB: finance-kb\n- Source: private-market-report.md",
            }

        def _fake_llm_text(prompt: str) -> str:
            prompt = str(prompt)
            if "Create a concise executive summary" in prompt:
                return "KB-backed executive summary."
            if "without open web search" in prompt:
                return "KB-only evidence memo anchored in private-market-report.md."
            return "## Industry Baseline\n\nPrivate knowledge shows margin expansion and stronger retention."

        correlation = {
            "briefing": "Correlation briefing",
            "knowledge_graph": {"nodes": [], "edges": []},
            "cross_cutting_themes": [],
            "contradictions": [],
            "section_order": ["Industry Baseline"],
        }

        with tempfile.TemporaryDirectory() as tmp_output:
            set_active_output_dir(tmp_output)
            try:
                with (
                    patch("tasks.long_document_tasks.OpenAI", return_value=Mock()),
                    patch("tasks.long_document_tasks.build_research_grounding", side_effect=_fake_grounding),
                    patch("tasks.long_document_tasks.llm_text", side_effect=_fake_llm_text),
                    patch("tasks.long_document_tasks._build_correlation_package", return_value=correlation),
                    patch("tasks.long_document_tasks._build_plagiarism_report", return_value={"overall_score": 0.0, "ai_content_score": 0.0, "status": "PASS", "sections": []}),
                    patch("tasks.long_document_tasks._generate_visual_assets", return_value={"tables": [], "flowcharts": [], "notes": ""}),
                    patch("tasks.long_document_tasks._export_long_document_formats", return_value={}),
                    patch("tasks.long_document_tasks.update_planning_file"),
                    patch("tasks.long_document_tasks.log_task_update"),
                    patch("tasks.long_document_tasks.publish_agent_output", side_effect=lambda current_state, *args, **kwargs: current_state),
                ):
                    result = long_document_agent(state)
            finally:
                set_active_output_dir("output")

            artifact_dir = Path(tmp_output) / "deep_research_runs" / "deep_research_run_1"
            report_path = artifact_dir / "deep_research_report.md"
            evidence_path = artifact_dir / "evidence_bank.json"
            coverage_path = artifact_dir / "coverage_report.json"

            self.assertTrue(report_path.exists())
            self.assertTrue(evidence_path.exists())
            self.assertTrue(coverage_path.exists())

            coverage = json.loads(coverage_path.read_text(encoding="utf-8"))
            evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
            report_text = report_path.read_text(encoding="utf-8")

        self.assertTrue(result["research_kb_used"])
        self.assertEqual(result["research_kb_name"], "finance-kb")
        self.assertEqual(result["research_kb_hit_count"], 1)
        self.assertTrue(result["deep_research_result_card"]["research_kb_used"])
        self.assertEqual(result["deep_research_result_card"]["research_kb_name"], "finance-kb")
        self.assertEqual(result["deep_research_result_card"]["provided_urls"], 0)
        self.assertFalse(result["deep_research_result_card"]["web_search_enabled"])
        self.assertTrue(coverage["kb_enabled"])
        self.assertEqual(coverage["kb_name"], "finance-kb")
        self.assertEqual(coverage["kb_hit_count"], 1)
        self.assertGreaterEqual(coverage["kb_source_count"], 1)
        self.assertEqual(evidence["research_kb"]["kb_name"], "finance-kb")
        self.assertEqual(evidence["source_ledger"][0]["url"], "file:///tmp/private-market-report.md")
        self.assertIn("private-market-report.md", report_text)
        self.assertIn("file:///tmp/private-market-report.md", json.dumps(result["long_document_references"]))


if __name__ == "__main__":
    unittest.main()
