import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from superagent.discovery import build_registry
from superagent.runtime import AgentRuntime
from tasks.a2a_protocol import append_task, make_task


class RuntimeRoutingTests(unittest.TestCase):
    @staticmethod
    def _fake_setup_snapshot(agent_cards: list[dict]) -> dict:
        return {
            "available_agents": [str(card.get("agent_name", "")) for card in agent_cards if isinstance(card, dict)],
            "disabled_agents": {},
            "setup_actions": [],
            "summary_text": "",
        }

    def test_execute_agent_publishes_active_task_to_session_record_before_handler_runs(self):
        with (
            patch("superagent.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Build an investor-focused analysis from the uploaded files.")
            state = append_task(
                state,
                make_task(
                    sender="orchestrator_agent",
                    recipient="worker_agent",
                    intent="planned-step",
                    content="Review the uploaded files and extract the metrics most relevant to the next funding round.",
                ),
            )

            writes: list[tuple[str, str, str]] = []

            def _capture_write(current_state: dict, *, status: str, active_agent: str = "", completed_at: str = "") -> None:
                writes.append((status, active_agent, str(current_state.get("active_agent_task", ""))))

            original_handler = runtime.registry.agents["worker_agent"].handler
            runtime.registry.agents["worker_agent"].handler = lambda current_state: {**current_state, "draft_response": "ok"}
            try:
                with (
                    patch.object(runtime, "_write_session_record", side_effect=_capture_write),
                    patch("superagent.runtime.append_daily_memory_note"),
                    patch("superagent.runtime.append_session_event"),
                    patch("superagent.runtime.record_work_note"),
                    patch("superagent.runtime.log_task_update"),
                    patch("superagent.runtime.insert_agent_execution"),
                ):
                    runtime._execute_agent(state, "worker_agent")
            finally:
                runtime.registry.agents["worker_agent"].handler = original_handler

        self.assertTrue(writes)
        self.assertEqual(writes[0][0], "running")
        self.assertEqual(writes[0][1], "worker_agent")
        self.assertIn("extract the metrics most relevant to the next funding round", writes[0][2])

    def test_active_task_summary_uses_agent_activity_label_for_generic_dispatch(self):
        with (
            patch("superagent.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Create a funding report from the local drive files.")
            task = make_task(
                sender="orchestrator_agent",
                recipient="local_drive_agent",
                intent="local-drive-ingestion",
                content="Create a funding report from the local drive files.",
            )

        summary = runtime._active_task_summary(state, task)
        self.assertIn("Scan the configured drive files", summary)

    def test_explicit_deep_research_request_routes_to_planner_first(self):
        with patch("superagent.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Do deep research on OpenAI's enterprise strategy with citations.")

            with patch("superagent.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "planner_agent")
        self.assertIn("plan", routed_state["orchestrator_reason"].lower())
        self.assertFalse(mock_invoke.called, "Planning-first routing should not call the generic orchestrator LLM.")
        self.assertTrue(routed_state.get("a2a", {}).get("tasks"), "Expected an A2A task to be created.")
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "planner_agent")

    def test_reviewer_approval_finishes_when_no_planned_steps_remain(self):
        with patch("superagent.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Do deep research on battery recycling market trends.")
            state["last_agent"] = "reviewer_agent"
            state["review_pending"] = False
            state["review_decision"] = "approve"
            state["draft_response"] = "Research completed."
            state["plan_ready"] = True
            state["plan_approval_status"] = "approved"
            state["plan_steps"] = []

            routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "__finish__")
        self.assertEqual(routed_state["final_output"], "Research completed.")

    def test_superrag_request_routes_to_planner_first(self):
        with patch("superagent.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Build a superRAG session from these URLs and chat with that data.")
            state["superrag_urls"] = ["https://example.com"]

            with patch("superagent.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "planner_agent")
        self.assertIn("plan", routed_state["orchestrator_reason"].lower())
        self.assertFalse(mock_invoke.called, "Planning-first routing should not call the generic orchestrator LLM.")
        self.assertTrue(routed_state.get("a2a", {}).get("tasks"), "Expected an A2A task to be created.")
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "planner_agent")

    def test_local_drive_request_routes_to_planner_first(self):
        with patch("superagent.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state(
                "Create a deep analysis report from local files.",
                local_drive_paths=["/tmp/folder"],
                working_directory="/tmp",
            )

            with patch.object(runtime, "_is_agent_available", side_effect=lambda _state, name: name == "planner_agent"):
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "planner_agent")
        self.assertIn("plan", routed_state["orchestrator_reason"].lower())
        self.assertTrue(routed_state.get("a2a", {}).get("tasks"), "Expected an A2A task to be created.")
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "planner_agent")

    def test_plan_waiting_for_approval_pauses_execution(self):
        with patch("superagent.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Build a competitive market brief.")
            state["last_agent"] = "planner_agent"
            state["plan"] = "Summary: test plan"
            state["plan_steps"] = [{"id": "step-1", "agent": "worker_agent", "task": "Do work"}]
            state["plan_waiting_for_approval"] = True
            state["plan_approval_status"] = "pending"
            state["pending_user_input_kind"] = "plan_approval"
            state["approval_pending_scope"] = "root_plan"
            state["pending_user_question"] = "Reply approve to continue."

            routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "__finish__")
        self.assertIn("approve", routed_state["final_output"].lower())

    def test_build_initial_state_approves_pending_plan_from_session(self):
        with patch("superagent.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            prior_state = {
                "last_plan": "Summary: test plan",
                "last_plan_data": {"summary": "test", "steps": [{"id": "step-1", "agent": "worker_agent", "task": "Do work"}]},
                "last_plan_steps": [{"id": "step-1", "agent": "worker_agent", "task": "Do work"}],
                "last_objective": "Build a pricing strategy memo.",
                "awaiting_user_input": True,
                "pending_user_input_kind": "plan_approval",
                "approval_pending_scope": "root_plan",
                "pending_user_question": "Reply approve to continue.",
                "plan_waiting_for_approval": True,
                "plan_approval_status": "pending",
            }
            state = runtime.build_initial_state("approve", channel_session={"state": prior_state})

        self.assertTrue(state["plan_ready"])
        self.assertFalse(state["plan_waiting_for_approval"])
        self.assertEqual(state["plan_approval_status"], "approved")
        self.assertEqual(state["current_objective"], "Build a pricing strategy memo.")
        self.assertEqual(state["pending_user_input_kind"], "")

    def test_build_initial_state_revisions_pending_plan_from_session(self):
        with patch("superagent.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            prior_state = {
                "last_plan": "Summary: test plan",
                "last_plan_data": {"summary": "test", "steps": [{"id": "step-1", "agent": "worker_agent", "task": "Do work"}]},
                "last_plan_steps": [{"id": "step-1", "agent": "worker_agent", "task": "Do work"}],
                "last_objective": "Build a pricing strategy memo.",
                "awaiting_user_input": True,
                "pending_user_input_kind": "plan_approval",
                "approval_pending_scope": "root_plan",
                "pending_user_question": "Reply approve to continue.",
                "plan_waiting_for_approval": True,
                "plan_approval_status": "pending",
            }
            state = runtime.build_initial_state("Change step 1 to emphasize competitors.", channel_session={"state": prior_state})

        self.assertFalse(state["plan_ready"])
        self.assertEqual(state["plan_approval_status"], "revision_requested")
        self.assertIn("emphasize competitors", state["plan_revision_feedback"].lower())
        self.assertIn("Plan revision instructions", state["current_objective"])

    def test_build_initial_state_approves_pending_long_document_subplan(self):
        with patch("superagent.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            prior_state = {
                "last_plan": "Summary: test plan",
                "last_plan_data": {"summary": "test", "steps": [{"id": "step-1", "agent": "long_document_agent", "task": "Write report"}]},
                "last_plan_steps": [{"id": "step-1", "agent": "long_document_agent", "task": "Write report"}],
                "last_objective": "Create a 50-page market report.",
                "awaiting_user_input": True,
                "pending_user_input_kind": "subplan_approval",
                "approval_pending_scope": "long_document_plan",
                "pending_user_question": "Approve the section plan.",
                "plan_approval_status": "approved",
                "long_document_plan_waiting_for_approval": True,
                "long_document_plan_status": "pending",
                "long_document_outline": {"title": "Report", "sections": [{"id": 1, "title": "Intro", "objective": "Set context"}]},
            }
            state = runtime.build_initial_state("approve", channel_session={"state": prior_state})

        self.assertTrue(state["plan_ready"])
        self.assertFalse(state["long_document_plan_waiting_for_approval"])
        self.assertEqual(state["long_document_plan_status"], "approved")
        self.assertTrue(state["long_document_execute_from_saved_outline"])

    def test_run_query_accepts_working_directory_in_state_overrides(self):
        runtime = AgentRuntime(build_registry())

        with TemporaryDirectory() as tmp:
            mock_app = SimpleNamespace(invoke=lambda state: {**state, "final_output": "ok"})
            with (
                patch("superagent.runtime.initialize_db"),
                patch("superagent.runtime.insert_run"),
                patch("superagent.runtime.update_run"),
                patch("superagent.runtime.reset_text_file"),
                patch("superagent.runtime.write_text_file"),
                patch("superagent.runtime.append_daily_memory_note"),
                patch("superagent.runtime.append_long_term_memory"),
                patch("superagent.runtime.close_session_memory"),
                patch.object(runtime, "_write_session_record"),
                patch.object(runtime, "_is_agent_available", return_value=True),
                patch.object(runtime, "build_workflow", return_value=mock_app),
            ):
                result = runtime.run_query(
                    "Test query",
                    state_overrides={"working_directory": tmp},
                    create_outputs=False,
                )

        self.assertEqual(result.get("working_directory"), str(Path(tmp).resolve()))
        self.assertEqual(result.get("final_output"), "ok")


if __name__ == "__main__":
    unittest.main()
