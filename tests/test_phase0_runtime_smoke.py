import os
import unittest
from contextlib import ExitStack
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from kendr.discovery import build_registry
from kendr.runtime import AgentRuntime
from tasks.a2a_protocol import append_task, make_task


class _FakeResearchResponse:
    def __init__(self, *, response_id: str, status: str, output_text: str):
        self.id = response_id
        self.status = status
        self.output_text = output_text

    def model_dump(self):
        return {"id": self.id, "status": self.status, "output_text": self.output_text}


class Phase0RuntimeSmokeTests(unittest.TestCase):
    @staticmethod
    def _fake_setup_snapshot(agent_cards: list[dict]) -> dict:
        return {
            "available_agents": [str(card.get("agent_name", "")) for card in agent_cards if isinstance(card, dict)],
            "disabled_agents": {},
            "setup_actions": [],
            "summary_text": "",
        }

    def test_runtime_routes_deep_research_then_exports_report_via_agent_runtime(self):
        fake_client = MagicMock()
        fake_client.responses.create.return_value = _FakeResearchResponse(
            response_id="resp-phase0",
            status="completed",
            output_text="grounded answer",
        )

        with ExitStack() as stack:
            stack.enter_context(patch("kendr.discovery._register_skill_agents"))
            stack.enter_context(patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot))
            stack.enter_context(patch("kendr.mcp_manager.list_servers_safe", return_value=[]))
            stack.enter_context(patch("kendr.connector_registry.build_connector_catalog", return_value=[]))
            stack.enter_context(patch("kendr.connector_registry.connector_catalog_prompt_block", return_value=""))
            stack.enter_context(patch("tasks.a2a_protocol.upsert_agent_card"))
            stack.enter_context(patch("tasks.a2a_protocol.insert_message"))
            stack.enter_context(patch("tasks.a2a_protocol.upsert_task"))
            stack.enter_context(patch("tasks.a2a_protocol.insert_artifact"))
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Do deep research on telecom privacy policy trends with citations.")
            state["plan_steps"] = []
            state["plan_ready"] = False
            state["last_agent"] = ""
            state["workflow_type"] = ""
            state["deep_research_mode"] = False
            state["long_document_mode"] = False
            state["deep_research_analysis"] = {}
            state["deep_research_intent"] = {}
            state["deep_research_source_strategy"] = {}
            state["session_id"] = ""
            state["run_id"] = ""
            state["_suppress_session_record"] = True
            state["_suppress_agent_execution_persistence"] = True
            state["research_kb_enabled"] = True
            state["research_kb_id"] = "kb-1"
            state["research_kb_top_k"] = 5

            stack.enter_context(patch.object(runtime, "apply_runtime_setup", side_effect=lambda current: current))
            stack.enter_context(patch.object(runtime, "_ensure_workflow_type", return_value=""))
            stack.enter_context(patch.object(runtime, "_should_run_planner", return_value=(False, "phase0 smoke", {"mode": "test"})))
            mock_orchestrator_llm = stack.enter_context(patch("kendr.runtime.llm.invoke"))
            routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "long_document_agent")
        self.assertEqual(routed_state["workflow_type"], "deep_research")
        self.assertFalse(mock_orchestrator_llm.called, "Explicit deep-research routing should not call orchestrator LLM.")
        self.assertTrue(routed_state.get("a2a", {}).get("tasks"))
        self.assertEqual(routed_state["a2a"]["tasks"][-1]["recipient"], "long_document_agent")

        with TemporaryDirectory() as tmp:
            captured_report_prompt: dict[str, str] = {}

            def _write_tmp_file(filename: str, content):
                path = Path(tmp) / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(str(content), encoding="utf-8")

            def _resolve_tmp_path(filename: str) -> str:
                return str(Path(tmp) / filename)

            def _report_llm(prompt):
                captured_report_prompt["text"] = str(prompt)
                return "not-json"

            with ExitStack() as stack:
                stack.enter_context(patch.object(runtime, "apply_runtime_setup", side_effect=lambda current: current))
                stack.enter_context(patch.object(runtime, "_write_session_record"))
                stack.enter_context(patch.object(runtime, "_record_execution_trace"))
                stack.enter_context(patch("kendr.runtime.append_daily_memory_note"))
                stack.enter_context(patch("kendr.runtime.append_session_event"))
                stack.enter_context(patch("kendr.runtime.record_work_note"))
                stack.enter_context(patch("kendr.runtime.log_task_update"))
                stack.enter_context(patch("kendr.runtime.insert_agent_execution"))
                stack.enter_context(patch("tasks.a2a_protocol.upsert_agent_card"))
                stack.enter_context(patch("tasks.a2a_protocol.insert_message"))
                stack.enter_context(patch("tasks.a2a_protocol.upsert_task"))
                stack.enter_context(patch("tasks.a2a_protocol.insert_artifact"))
                stack.enter_context(patch("tasks.a2a_agent_utils.record_work_note"))
                stack.enter_context(patch("tasks.research_tasks.OpenAI", return_value=fake_client))
                stack.enter_context(
                    patch(
                        "tasks.research_tasks.build_research_grounding",
                        return_value={
                            "kb_id": "kb-1",
                            "kb_name": "finance-kb",
                            "prompt_context": "Knowledge Base Grounding:\n- KB: finance-kb",
                            "hit_count": 2,
                            "citations": [{"source_id": "file:///tmp/report.md"}],
                        },
                    )
                )
                stack.enter_context(patch("tasks.research_tasks.write_text_file"))
                stack.enter_context(patch("tasks.research_tasks.log_task_update"))
                stack.enter_context(patch("tasks.report_tasks.write_text_file", side_effect=_write_tmp_file))
                stack.enter_context(patch("tasks.report_tasks.resolve_output_path", side_effect=_resolve_tmp_path))
                stack.enter_context(patch("tasks.report_tasks.llm.invoke", side_effect=_report_llm))
                stack.enter_context(patch("tasks.report_tasks.log_task_update"))
                helper_state = append_task(
                    routed_state,
                    make_task(
                        sender="test_harness",
                        recipient="deep_research_agent",
                        intent="deep-research-dispatch",
                        content="Do deep research on telecom privacy policy trends with citations.",
                        state_updates={
                            "research_query": "Do deep research on telecom privacy policy trends with citations.",
                        },
                    ),
                )
                research_state = runtime._execute_agent(helper_state, "deep_research_agent")
                report_state = append_task(
                    research_state,
                    make_task(
                        sender="orchestrator_agent",
                        recipient="report_agent",
                        intent="report-export",
                        content="Create an HTML report from the latest deep research brief.",
                        state_updates={
                            "report_requirement": "Create an HTML report from the latest deep research brief.",
                            "report_title": "Phase 0 Runtime Launch Report",
                            "report_formats": ["html"],
                            "report_output_basename": "phase0_runtime_launch",
                        },
                    ),
                )
                report_state = runtime._execute_agent(report_state, "report_agent")

            self.assertIn("Deep Research Brief", research_state["research_result"])
            self.assertEqual(research_state["deep_research_result_card"]["kind"], "brief")
            self.assertIn("Knowledge base: finance-kb (2 hits)", "\n".join(research_state["research_source_summary"]))

            self.assertIn("deep_research_result_card", captured_report_prompt.get("text", ""))
            self.assertIn("research_source_summary", captured_report_prompt.get("text", ""))
            self.assertIn("Report export complete.", report_state["draft_response"])
            self.assertIn("Generated report 'Phase 0 Runtime Launch Report'", report_state["draft_response"])
            self.assertIn("HTML report: phase0_runtime_launch_1.html", report_state["draft_response"])
            self.assertIn("html", report_state["report_files"])

            html_path = Path(report_state["report_files"]["html"])
            self.assertTrue(html_path.exists())
            html_text = html_path.read_text(encoding="utf-8")
            self.assertIn("Phase 0 Runtime Launch Report", html_text)
            self.assertIn("Research Brief Card", html_text)
            self.assertIn("Research Sources", html_text)
            self.assertIn("finance-kb", html_text)
            self.assertIn("file:///tmp/report.md", html_text)

            headings = [section["heading"] for section in report_state["report_data"]["sections"]]
            self.assertIn("Research Brief Card", headings)
            self.assertIn("Research Sources", headings)

            tasks_by_recipient = {task["recipient"]: task["status"] for task in report_state.get("a2a", {}).get("tasks", [])}
            self.assertEqual(tasks_by_recipient.get("deep_research_agent"), "completed")
            self.assertEqual(tasks_by_recipient.get("report_agent"), "completed")

            artifact_names = [artifact.get("name") for artifact in report_state.get("a2a", {}).get("artifacts", [])]
            self.assertIn("deep_research_result_1", artifact_names)
            self.assertIn("report_result_1", artifact_names)


if __name__ == "__main__":
    unittest.main()
