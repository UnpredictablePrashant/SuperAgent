import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from kendr.discovery import build_registry
from kendr.runtime import AgentRuntime
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
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
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
                    patch("kendr.runtime.append_daily_memory_note"),
                    patch("kendr.runtime.append_session_event"),
                    patch("kendr.runtime.record_work_note"),
                    patch("kendr.runtime.log_task_update"),
                    patch("kendr.runtime.insert_agent_execution"),
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
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
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

    def test_apply_runtime_setup_filters_unavailable_agents_from_agent_cards(self):
        registry = build_registry()
        snapshot = {
            "available_agents": ["worker_agent"],
            "disabled_agents": {"scanner_agent": {"available": False, "missing_services": ["nmap_or_zap"]}},
            "setup_actions": [{"service": "nmap", "action": "manual"}],
            "summary_text": "worker_agent only",
        }

        with patch("kendr.runtime.build_setup_snapshot", return_value=snapshot):
            runtime = AgentRuntime(registry)
            state = runtime.apply_runtime_setup({})

        self.assertEqual(state["available_agents"], ["worker_agent"])
        self.assertEqual([card["agent_name"] for card in state["available_agent_cards"]], ["worker_agent"])

    def test_explicit_deep_research_request_routes_to_long_document_lane(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Do deep research on OpenAI's enterprise strategy with citations.")

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "long_document_agent")
        self.assertIn("deep research", routed_state["orchestrator_reason"].lower())
        self.assertFalse(mock_invoke.called, "Direct deep-research routing should not call the generic orchestrator LLM.")
        self.assertTrue(routed_state.get("a2a", {}).get("tasks"), "Expected an A2A task to be created.")
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "long_document_agent")
        self.assertEqual(routed_state["workflow_type"], "deep_research")

    def test_preloaded_gateway_message_skips_channel_gateway_agent(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
            patch("kendr.runtime.append_privileged_audit_event"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state(
                "Scan this site.",
                incoming_payload={"channel": "webchat", "text": "Scan this site."},
                incoming_channel="webchat",
                incoming_sender_id="user-1",
                incoming_chat_id="chat-1",
                gateway_message={
                    "channel": "webchat",
                    "sender_id": "user-1",
                    "chat_id": "chat-1",
                    "workspace_id": "",
                    "text": "Scan this site.",
                    "is_group": False,
                    "mentioned": False,
                    "should_activate": True,
                    "activation_reason": "direct message",
                },
            )

            routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "session_router_agent")
        self.assertTrue(routed_state.get("a2a", {}).get("tasks"))
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "session_router_agent")

    def test_project_workbench_request_routes_directly_to_master_coding_agent(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state(
                "Review the auth flow in this repo and trace where login can fail.",
                incoming_channel="project_ui",
                project_root="D:/repo",
                working_directory="D:/repo",
            )

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "master_coding_agent")
        self.assertIn("project workbench request", routed_state["orchestrator_reason"].lower())
        self.assertTrue(routed_state.get("codebase_mode"))
        self.assertFalse(mock_invoke.called, "Direct project workbench routing should not call the generic orchestrator LLM.")
        self.assertTrue(routed_state.get("a2a", {}).get("tasks"))
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "master_coding_agent")
        self.assertEqual(task["intent"], "project-workbench-dispatch")

    def test_project_workbench_deep_research_request_stays_in_long_document_lane(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state(
                (
                    "Do an exhaustive and deep study of what data Facebook, Instagram, WhatsApp, and TikTok capture, "
                    "what they use it for, and what an Indian microOTT can legally capture and monetise."
                ),
                incoming_channel="project_ui",
                project_root="D:/repo",
                working_directory="D:/repo",
            )
            state["deep_research_mode"] = True
            state["long_document_mode"] = True

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "long_document_agent")
        self.assertIn("deep research report objective", routed_state["orchestrator_reason"].lower())
        self.assertFalse(mock_invoke.called)
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "long_document_agent")
        self.assertEqual(task["intent"], "long-document-dispatch")
        self.assertEqual(routed_state["workflow_type"], "deep_research")

    def test_reviewer_approval_finishes_when_no_planned_steps_remain(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
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

    def test_planned_step_dispatch_includes_step_context_for_review(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Create a funding report from local files.")
            state["plan_ready"] = True
            state["plan_approval_status"] = "approved"
            state["plan_steps"] = [
                {
                    "id": "step-1",
                    "title": "Catalog files",
                    "agent": "local_drive_agent",
                    "task": "Catalog the local files and summarize the evidence.",
                    "success_criteria": "A file catalog and evidence summary exist.",
                }
            ]

            routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "local_drive_agent")
        self.assertEqual(routed_state["planned_active_step_id"], "step-1")
        self.assertEqual(routed_state["planned_active_step_title"], "Catalog files")
        self.assertEqual(routed_state["planned_active_step_success_criteria"], "A file catalog and evidence summary exist.")
        self.assertTrue(routed_state.get("a2a", {}).get("tasks"))
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "local_drive_agent")
        self.assertEqual(task["state_updates"]["current_plan_step_id"], "step-1")
        self.assertEqual(task["state_updates"]["current_plan_step_title"], "Catalog files")
        self.assertEqual(
            task["state_updates"]["current_plan_step_success_criteria"],
            "A file catalog and evidence summary exist.",
        )

    def test_reviewer_revision_limit_raises_after_too_many_retries(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Create a funding report from local files.")
            state["plan_ready"] = True
            state["plan_approval_status"] = "approved"
            state["last_agent"] = "reviewer_agent"
            state["review_decision"] = "revise"
            state["review_target_agent"] = "local_drive_agent"
            state["review_subject_step_id"] = "step-1"
            state["review_subject_agent"] = "local_drive_agent"
            state["review_reason"] = "Still missing the structured file catalog."
            state["review_revision_counts"] = {"step-1|local_drive_agent": 3}
            state["max_step_revisions"] = 3

            with self.assertRaises(RuntimeError):
                runtime.orchestrator_agent(state)

    def test_extension_handler_generation_routes_to_agent_factory_when_enabled(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Process mixed local-drive files.")
            state["plan_ready"] = True
            state["plan_steps"] = []
            state["review_pending"] = False
            state["last_agent"] = "local_drive_agent"
            state["extension_handler_generation_requested"] = True
            state["extension_handler_generation_dispatched"] = False
            state["local_drive_unknown_extensions"] = [".abc"]
            state["agent_factory_request"] = "Create handler for .abc."
            state["missing_capability"] = "File extension handling: .abc"

            routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "agent_factory_agent")
        self.assertTrue(routed_state.get("extension_handler_generation_dispatched"))
        self.assertTrue(routed_state.get("a2a", {}).get("tasks"))
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "agent_factory_agent")
        self.assertEqual(task["intent"], "extension-handler-generation")

    def test_superrag_request_routes_to_planner_first(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Build a superRAG session from these URLs and chat with that data.")
            state["superrag_urls"] = ["https://example.com"]

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "planner_agent")
        self.assertIn("plan", routed_state["orchestrator_reason"].lower())
        self.assertFalse(mock_invoke.called, "Planning-first routing should not call the generic orchestrator LLM.")
        self.assertTrue(routed_state.get("a2a", {}).get("tasks"), "Expected an A2A task to be created.")
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "planner_agent")

    def test_stuck_agent_message_classifies_missing_state_contract_errors(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Analyze local documents.")
            state["_consecutive_failures"] = {
                "document_ingestion_agent": {
                    "count": 3,
                    "last_error": "document_ingestion_agent requires 'document_paths' or 'doc_paths'.",
                }
            }
            message = runtime._stuck_agent_message(state, "document_ingestion_agent")
        self.assertIn("input-contract mismatch", message)

    def test_stuck_agent_message_classifies_missing_module_errors(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Build a MERN app.")
            state["_consecutive_failures"] = {
                "project_blueprint_agent": {
                    "count": 3,
                    "last_error": "No module named 'plugin_templates'",
                }
            }
            message = runtime._stuck_agent_message(state, "project_blueprint_agent")
        self.assertIn("packaging/import issue", message)

    def test_explicit_os_command_routes_to_os_agent(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Run a local command to inspect the repository.")
            state["os_command"] = "Get-Location"

            routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "os_agent")
        self.assertTrue(routed_state.get("a2a", {}).get("tasks"))
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "os_agent")

    def test_local_drive_request_routes_to_planner_first(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
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
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
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

    def test_deep_research_confirmation_pending_pauses_execution(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Research the social media data market in depth.")
            state["workflow_type"] = "deep_research"
            state["pending_user_input_kind"] = "deep_research_confirmation"
            state["approval_pending_scope"] = "deep_research_confirmation"
            state["pending_user_question"] = "Reply approve to start deep research."
            state["approval_request"] = {
                "scope": "deep_research_confirmation",
                "summary": "Review scope before expensive execution.",
            }

            routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "__finish__")
        self.assertIn("approve", routed_state["final_output"].lower())

    def test_deep_research_confirmation_scope_only_pauses_execution(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Research the social media data market in depth.")
            state["workflow_type"] = "deep_research"
            state["pending_user_input_kind"] = ""
            state["approval_pending_scope"] = "deep_research_confirmation"
            state["pending_user_question"] = "Reply approve to start deep research."
            state["approval_request"] = {
                "scope": "deep_research_confirmation",
                "summary": "Review scope before expensive execution.",
            }

            routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "__finish__")
        self.assertIn("approve", routed_state["final_output"].lower())

    def test_build_initial_state_approves_pending_plan_from_session(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
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
                "blueprint_json": {"project_name": "new-project", "tech_stack": {"framework": "fastapi"}},
                "project_root": "/tmp/new-project",
            }
            state = runtime.build_initial_state("approve", channel_session={"state": prior_state})

        self.assertTrue(state["plan_ready"])
        self.assertFalse(state["plan_waiting_for_approval"])
        self.assertEqual(state["plan_approval_status"], "approved")
        self.assertEqual(state["current_objective"], "Build a pricing strategy memo.")
        self.assertEqual(state["pending_user_input_kind"], "")
        self.assertEqual(state["blueprint_json"], prior_state["blueprint_json"])
        self.assertEqual(state["project_root"], prior_state["project_root"])

    def test_build_initial_state_revisions_pending_plan_from_session(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
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
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
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

    def test_build_initial_state_restores_scope_only_pending_deep_research_confirmation(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            prior_state = {
                "last_objective": "Create a 25-page social media data report.",
                "awaiting_user_input": True,
                "pending_user_input_kind": "",
                "approval_pending_scope": "deep_research_confirmation",
                "pending_user_question": "Review and approve deep research confirmation.",
                "approval_request": {
                    "scope": "deep_research_confirmation",
                    "summary": "Review scope before expensive execution.",
                },
            }
            state = runtime.build_initial_state(
                "Create a 25-page social media data report.",
                channel_session={"state": prior_state},
            )

        self.assertEqual(state["pending_user_input_kind"], "deep_research_confirmation")
        self.assertEqual(state["approval_pending_scope"], "deep_research_confirmation")
        self.assertIn("approve", state["pending_user_question"].lower())

    def test_build_initial_state_resume_checkpoint_restores_scope_only_pending_approval(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            checkpoint = {
                "summary": {
                    "run_id": "run-1",
                    "status": "awaiting_user_input",
                    "awaiting_user_input": True,
                },
                "state_snapshot": {
                    "current_objective": "Create a 25-page social media data report.",
                    "pending_user_input_kind": "",
                    "approval_pending_scope": "deep_research_confirmation",
                    "pending_user_question": "Review and approve deep research confirmation.",
                    "approval_request": {
                        "scope": "deep_research_confirmation",
                        "summary": "Review scope before expensive execution.",
                    },
                },
            }
            state = runtime.build_initial_state(
                "Create a 25-page social media data report.",
                resume_checkpoint_payload=checkpoint,
            )

        self.assertEqual(state["pending_user_input_kind"], "deep_research_confirmation")
        self.assertEqual(state["approval_pending_scope"], "deep_research_confirmation")
        self.assertIn("approve", state["pending_user_question"].lower())

    def test_build_initial_state_does_not_reuse_failed_approved_plan_for_fresh_run(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            prior_state = {
                "last_plan": "Summary: stale plan",
                "last_plan_data": {"summary": "stale", "steps": [{"id": "step-1", "agent": "document_ingestion_agent", "task": "Do stale work"}]},
                "last_plan_steps": [{"id": "step-1", "agent": "document_ingestion_agent", "task": "Do stale work"}],
                "last_plan_step_index": 0,
                "last_objective": "Old failed objective.",
                "last_status": "failed",
                "plan_waiting_for_approval": False,
                "plan_approval_status": "approved",
                "failure_checkpoint": {
                    "agent": "document_ingestion_agent",
                    "step_index": 0,
                    "task_content": "Do stale work",
                    "can_resume": True,
                },
            }
            query = "Analyze Twenty4 Jewelry from the latest drive documents."
            state = runtime.build_initial_state(query, channel_session={"state": prior_state})

        self.assertEqual(state["current_objective"], query)
        self.assertEqual(state["plan_steps"], [])
        self.assertFalse(state["plan_ready"])
        self.assertFalse(state["resume_requested"])
        self.assertEqual(state["plan_approval_status"], "not_started")

    def test_build_initial_state_restores_failed_plan_only_for_explicit_resume_request(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            prior_state = {
                "last_plan": "Summary: stale plan",
                "last_plan_data": {"summary": "stale", "steps": [{"id": "step-1", "agent": "worker_agent", "task": "Recover work"}]},
                "last_plan_steps": [{"id": "step-1", "agent": "worker_agent", "task": "Recover work"}],
                "last_plan_step_index": 0,
                "last_objective": "Old failed objective.",
                "last_status": "failed",
                "plan_waiting_for_approval": False,
                "plan_approval_status": "approved",
                "failure_checkpoint": {
                    "agent": "worker_agent",
                    "step_index": 0,
                    "task_content": "Recover work",
                    "can_resume": True,
                },
            }
            state = runtime.build_initial_state("resume the failed run", channel_session={"state": prior_state})

        self.assertEqual(state["plan_steps"], prior_state["last_plan_steps"])
        self.assertTrue(state["plan_ready"])
        self.assertTrue(state["resume_requested"])
        self.assertTrue(state["resume_ready"])
        self.assertEqual(state["current_objective"], "Recover work")

    def test_session_payload_uses_stable_current_step_number_across_agent_state_changes(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Build a funding report from local files.")
            state["effective_steps"] = 1
            state["agent_history"] = [{"agent": "channel_gateway_agent", "status": "completed"}]
            state["last_agent"] = "channel_gateway_agent"

            started_payload = runtime._session_payload(state, status="running", active_agent="reviewer_agent")

            state["effective_steps"] = 2
            state["agent_history"].append({"agent": "reviewer_agent", "status": "completed"})
            state["last_agent"] = "reviewer_agent"
            completed_payload = runtime._session_payload(state, status="running", active_agent="reviewer_agent")

        self.assertEqual(started_payload["step_count"], 2)
        self.assertEqual(completed_payload["step_count"], 2)

    def test_run_query_accepts_working_directory_in_state_overrides(self):
        runtime = AgentRuntime(build_registry())

        with TemporaryDirectory() as tmp:
            mock_app = SimpleNamespace(invoke=lambda state: {**state, "final_output": "ok"})
            with (
                patch("kendr.runtime.initialize_db"),
                patch("kendr.runtime.insert_run"),
                patch("kendr.runtime.update_run"),
                patch("kendr.runtime.reset_text_file"),
                patch("kendr.runtime.write_text_file"),
                patch("kendr.runtime.append_daily_memory_note"),
                patch("kendr.runtime.append_long_term_memory"),
                patch("kendr.runtime.close_session_memory"),
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

    def test_execute_agent_skips_reviewer_for_channel_gateway_agent(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
            patch("kendr.runtime.append_daily_memory_note"),
            patch("kendr.runtime.append_session_event"),
            patch("kendr.runtime.record_work_note"),
            patch("kendr.runtime.log_task_update"),
            patch("kendr.runtime.insert_agent_execution"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("hello")
            state = append_task(
                state,
                make_task(
                    sender="orchestrator_agent",
                    recipient="channel_gateway_agent",
                    intent="channel-ingest-normalization",
                    content="Normalize payload",
                ),
            )

            original_handler = runtime.registry.agents["channel_gateway_agent"].handler
            runtime.registry.agents["channel_gateway_agent"].handler = lambda current_state: {**current_state, "draft_response": "normalized"}
            try:
                with patch.object(runtime, "_write_session_record"):
                    result = runtime._execute_agent(state, "channel_gateway_agent")
            finally:
                runtime.registry.agents["channel_gateway_agent"].handler = original_handler

        self.assertFalse(result.get("review_pending", True))


if __name__ == "__main__":
    unittest.main()
