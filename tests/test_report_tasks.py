import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch


os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")


class _FakeResearchResponse:
    def __init__(self, *, response_id: str, status: str, output_text: str):
        self.id = response_id
        self.status = status
        self.output_text = output_text

    def model_dump(self):
        return {"id": self.id, "status": self.status, "output_text": self.output_text}


class ReportAgentSmokeTests(unittest.TestCase):
    def test_report_agent_preserves_deep_research_brief_card_and_sources_in_export(self):
        from tasks import report_tasks, research_tasks

        state = {
            "user_query": "Analyze the market structure",
            "current_objective": "Analyze the market structure and export a report.",
            "research_kb_enabled": True,
            "research_web_search_enabled": True,
            "report_requirement": "Create an HTML report from the latest deep research brief.",
            "report_title": "Phase 0 Launch Report",
            "report_formats": ["html"],
            "report_output_basename": "phase0_launch_report",
        }

        fake_client = MagicMock()
        fake_client.responses.create.return_value = _FakeResearchResponse(
            response_id="resp-1",
            status="completed",
            output_text="grounded answer",
        )

        with TemporaryDirectory() as tmp:
            captured_prompt: dict[str, str] = {}

            def _write_tmp_file(filename: str, content):
                path = Path(tmp) / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(str(content), encoding="utf-8")

            def _resolve_tmp_path(filename: str) -> str:
                return str(Path(tmp) / filename)

            def _invoke(prompt):
                captured_prompt["text"] = str(prompt)
                return "not-json"

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
                patch("tasks.research_tasks.publish_agent_output", side_effect=lambda current_state, *args, **kwargs: current_state),
            ):
                research_state = research_tasks.deep_research_agent(dict(state))

            with (
                patch("tasks.report_tasks.begin_agent_session", return_value=(None, state["report_requirement"], None)),
                patch("tasks.report_tasks.publish_agent_output", side_effect=lambda current_state, *args, **kwargs: current_state),
                patch("tasks.report_tasks.log_task_update"),
                patch("tasks.report_tasks.write_text_file", side_effect=_write_tmp_file),
                patch("tasks.report_tasks.resolve_output_path", side_effect=_resolve_tmp_path),
                patch("tasks.report_tasks.llm.invoke", side_effect=_invoke),
            ):
                report_state = report_tasks.report_agent(research_state)

            prompt_text = captured_prompt.get("text", "")
            self.assertIn("deep_research_result_card", prompt_text)
            self.assertIn("research_source_summary", prompt_text)
            self.assertIn("Report export complete.", report_state["draft_response"])
            self.assertIn("Generated report 'Phase 0 Launch Report'", report_state["draft_response"])
            self.assertIn("HTML report: phase0_launch_report_1.html", report_state["draft_response"])
            self.assertIn("Manifest: phase0_launch_report_manifest_1.json", report_state["draft_response"])
            self.assertNotIn(tmp, report_state["draft_response"])

            report_data = report_state["report_data"]
            headings = [section["heading"] for section in report_data["sections"]]
            self.assertIn("Research Brief Card", headings)
            self.assertIn("Research Sources", headings)
            self.assertIn("Deep Research Brief", report_data["summary"])

            card_section = next(section for section in report_data["sections"] if section["heading"] == "Research Brief Card")
            self.assertIn("Knowledge base name: finance-kb", card_section["body"])

            source_section = next(section for section in report_data["sections"] if section["heading"] == "Research Sources")
            self.assertIn("Knowledge base: finance-kb (2 hits)", source_section["body"])
            self.assertIn("KB source: file:///tmp/report.md", source_section["body"])

            html_path = Path(report_state["report_files"]["html"])
            self.assertTrue(html_path.exists())
            html_text = html_path.read_text(encoding="utf-8")
            self.assertIn("Phase 0 Launch Report", html_text)
            self.assertIn("Research Brief Card", html_text)
            self.assertIn("finance-kb", html_text)
            self.assertIn("file:///tmp/report.md", html_text)


if __name__ == "__main__":
    unittest.main()
