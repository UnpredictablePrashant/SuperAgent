import io
import json
import os
import tempfile
import unittest
from contextlib import ExitStack, redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from kendr.cli import main


class _GatewayResponse:
    def __init__(self, body: str):
        self._body = body.encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self._body


class _FakeResearchResponse:
    def __init__(self, *, response_id: str, status: str, output_text: str):
        self.id = response_id
        self.status = status
        self.output_text = output_text

    def model_dump(self):
        return {"id": self.id, "status": self.status, "output_text": self.output_text}


class _FakeLLMResponse:
    def __init__(self, content: str):
        self.content = content


class Phase0CliSmokeTests(unittest.TestCase):
    @staticmethod
    def _fake_setup_snapshot(agent_cards: list[dict]) -> dict:
        return {
            "available_agents": [str(card.get("agent_name", "")) for card in agent_cards if isinstance(card, dict)],
            "disabled_agents": {},
            "setup_actions": [],
            "summary_text": "",
        }

    @staticmethod
    def _finish_from_prompt(prompt) -> _FakeLLMResponse:
        prompt_text = str(prompt)
        marker = "Current draft response:\n"
        end_marker = "\n\nCurrent review decision:"
        draft_response = ""
        if marker in prompt_text and end_marker in prompt_text:
            draft_response = prompt_text.split(marker, 1)[1].split(end_marker, 1)[0].strip()
        payload = {
            "agent": "finish",
            "reason": "Research synthesis complete.",
            "state_updates": {},
            "task_content": "",
            "final_response": draft_response or "No final response was generated.",
        }
        return _FakeLLMResponse(json.dumps(payload))

    def test_run_cli_executes_phase0_deep_research_flow_via_runtime(self):
        captured: dict[str, object] = {}
        payload: dict[str, object] = {}
        fake_client = MagicMock()
        fake_client.responses.create.return_value = _FakeResearchResponse(
            response_id="resp-phase0-cli",
            status="completed",
            output_text="grounded answer",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            working_dir = Path(tmpdir)

            def _fake_worker_handler(state: dict) -> dict:
                state["draft_response"] = str(state.get("research_result") or "").strip()
                return state

            def _fake_long_document_handler(state: dict) -> dict:
                state["workflow_type"] = "deep_research"
                state["deep_research_mode"] = True
                state["long_document_mode"] = True
                state["pending_user_input_kind"] = ""
                state["approval_pending_scope"] = ""
                state["deep_research_result_card"] = {
                    "kind": "plan",
                    "status": "approved",
                    "title": "Deep Research Report",
                }
                state["long_document_outline_md_path"] = (
                    "output/deep_research_runs/deep_research_run_1/deep_research_outline.md"
                )
                state["long_document_subplan_md_path"] = (
                    "output/deep_research_runs/deep_research_run_1/deep_research_subplan.md"
                )
                state["draft_response"] = (
                    "Auto-approved section plan; continuing to evidence collection.\n\n"
                    "Saved artifacts\n"
                    "- Outline: output/deep_research_runs/deep_research_run_1/deep_research_outline.md\n"
                    "- Step-by-step plan: output/deep_research_runs/deep_research_run_1/deep_research_subplan.md"
                )
                return state

            def _fake_urlopen(request, timeout=0):  # noqa: ARG001
                body = request.data.decode("utf-8") if getattr(request, "data", None) else "{}"
                payload = json.loads(body)
                captured["ingest_payload"] = payload

                from kendr.discovery import build_registry
                from kendr.runtime import AgentRuntime

                overrides = {key: value for key, value in payload.items() if key not in {"text", "new_session"}}
                overrides["_phase0_handoff_only"] = True
                with ExitStack() as stack:
                    stack.enter_context(patch("builtins.print"))
                    stack.enter_context(patch("kendr.discovery._register_skill_agents"))
                    stack.enter_context(patch("kendr.runtime.initialize_db"))
                    stack.enter_context(patch("kendr.runtime.insert_run"))
                    stack.enter_context(patch("kendr.runtime.update_run"))
                    stack.enter_context(patch("kendr.runtime.update_planning_file"))
                    stack.enter_context(patch("kendr.runtime.close_session_memory"))
                    stack.enter_context(patch("kendr.runtime.append_privileged_audit_event"))
                    stack.enter_context(patch("kendr.runtime.append_long_term_memory"))
                    stack.enter_context(patch("kendr.runtime.append_daily_memory_note"))
                    stack.enter_context(patch("kendr.runtime.append_session_event"))
                    stack.enter_context(patch("kendr.runtime.record_work_note"))
                    stack.enter_context(patch("kendr.runtime.update_session_file"))
                    stack.enter_context(patch("kendr.runtime.bootstrap_file_memory", side_effect=lambda state: state))
                    stack.enter_context(patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot))
                    stack.enter_context(patch("kendr.mcp_manager.list_servers_safe", return_value=[]))
                    stack.enter_context(patch("kendr.connector_registry.build_connector_catalog", return_value=[]))
                    stack.enter_context(patch("kendr.connector_registry.connector_catalog_prompt_block", return_value=""))
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
                    stack.enter_context(patch("kendr.runtime.llm.invoke", side_effect=self._finish_from_prompt))

                    runtime = AgentRuntime(build_registry())
                    runtime.registry.agents["worker_agent"].handler = _fake_worker_handler
                    runtime.registry.agents["long_document_agent"].handler = _fake_long_document_handler

                    stack.enter_context(patch.object(runtime, "_sync_orchestration_plan_record", side_effect=lambda state, final_status="": state))
                    stack.enter_context(patch.object(runtime, "_record_orchestration_event"))
                    stack.enter_context(patch.object(runtime, "_write_session_record"))
                    stack.enter_context(patch.object(runtime, "_record_execution_trace"))
                    stack.enter_context(patch.object(runtime, "_refresh_mcp_agents"))
                    stack.enter_context(patch.object(runtime, "_refresh_skill_agents"))
                    stack.enter_context(patch.object(runtime, "save_graph"))
                    stack.enter_context(patch.object(runtime, "_ensure_workflow_type", return_value=""))
                    stack.enter_context(
                        patch.object(runtime, "_should_run_planner", return_value=(False, "phase0 cli smoke", {"mode": "test"}))
                    )
                    stack.enter_context(patch.object(runtime, "_should_request_review", return_value=(False, "", {})))

                    result = runtime.run_query(payload["text"], state_overrides=overrides, create_outputs=True)
                    captured["runtime_result"] = result
                    return _GatewayResponse(json.dumps(result, ensure_ascii=False, default=str))

            with (
                patch("kendr.cli._gateway_ready", return_value=True),
                patch("kendr.cli._configured_working_dir", return_value=str(working_dir)),
                patch("kendr.cli._resolve_working_dir", return_value=str(working_dir)),
                patch(
                    "kendr.cli._workflow_setup_snapshot",
                    return_value={"available_agents": ["deep_research_agent", "long_document_agent", "worker_agent"], "agents": {}},
                ),
                patch("kendr.cli._http_json_get", return_value=[]),
                patch("kendr.cli._load_cli_session", return_value={}),
                patch("kendr.cli._save_cli_session"),
                patch("kendr.cli.urllib.request.urlopen", side_effect=_fake_urlopen),
            ):
                buffer = io.StringIO()
                with redirect_stdout(buffer):
                    exit_code = main(
                        [
                            "run",
                            "--json",
                            "--quiet",
                            "--auto-approve",
                            "--research-use-active-kb",
                            "--research-kb-top-k",
                            "5",
                            "Do deep research on telecom privacy policy trends with citations.",
                        ]
                    )
                rendered = buffer.getvalue()
                payload = json.loads(rendered[rendered.find("{"):])

        self.assertEqual(exit_code, 0)
        ingest_payload = captured["ingest_payload"]
        agent_names = [item.get("agent") for item in payload.get("agent_history", []) if isinstance(item, dict)]

        self.assertTrue(ingest_payload["research_kb_enabled"])
        self.assertEqual(ingest_payload["research_kb_top_k"], 5)
        self.assertTrue(ingest_payload["auto_approve"])
        self.assertTrue(ingest_payload["auto_approve_plan"])
        self.assertIn("long_document_agent", agent_names)
        self.assertIn(payload["last_agent"], {"worker_agent", "long_document_agent"})
        self.assertEqual(payload["workflow_type"], "deep_research")
        self.assertTrue(payload["deep_research_mode"])
        self.assertTrue(payload["long_document_mode"])
        self.assertEqual(payload["approval_pending_scope"], "")
        self.assertEqual(payload["pending_user_input_kind"], "")
        self.assertIn("auto-approved", payload["final_output"].lower())
        self.assertIn("evidence collection", payload["final_output"].lower())
        self.assertIn("saved artifacts", payload["final_output"].lower())
        self.assertIn("deep_research_outline.md", payload["final_output"])
        self.assertIn("deep_research_subplan.md", payload["final_output"])
        self.assertEqual(payload["deep_research_result_card"]["kind"], "plan")
        self.assertEqual(payload["deep_research_result_card"]["status"], "approved")
        self.assertIn("deep_research_outline.md", payload["long_document_outline_md_path"])
        self.assertIn("deep_research_subplan.md", payload["long_document_subplan_md_path"])
        self.assertNotIn("section plan is ready for approval", payload["final_output"].lower())


if __name__ == "__main__":
    unittest.main()
