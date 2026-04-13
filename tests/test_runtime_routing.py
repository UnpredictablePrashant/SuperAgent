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

    def test_execution_mode_controls_planner_policy(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("kendr.connector_registry.build_connector_catalog", return_value=[]),
            patch("kendr.connector_registry.connector_catalog_prompt_block", return_value=""),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            direct_state = runtime.build_initial_state(
                "Inspect this project and run the best tool.",
                execution_mode="direct_tools",
            )
            run_planner_direct, reason_direct, _signals_direct = runtime._should_run_planner(direct_state)

            plan_state = runtime.build_initial_state(
                "Inspect this project and run the best tool.",
                execution_mode="plan",
            )
            run_planner_plan, reason_plan, _signals_plan = runtime._should_run_planner(plan_state)

        self.assertEqual(direct_state["execution_mode"], "direct_tools")
        self.assertEqual(direct_state["planner_policy_mode"], "never")
        self.assertFalse(run_planner_direct)
        self.assertIn("direct tool mode", reason_direct.lower())

        self.assertEqual(plan_state["execution_mode"], "plan")
        self.assertEqual(plan_state["planner_policy_mode"], "always")
        self.assertTrue(run_planner_plan)
        self.assertIn("plan mode", reason_plan.lower())

    def test_drive_listing_query_routes_to_os_agent_with_command_hint(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("kendr.connector_registry.build_connector_catalog", return_value=[]),
            patch("kendr.connector_registry.connector_catalog_prompt_block", return_value=""),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("which folders are there in my D drive?")
            state["plan_steps"] = []
            state["plan_ready"] = False
            state["last_agent"] = ""

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "os_agent")
        self.assertIn("local command execution workflow", routed_state["orchestrator_reason"].lower())
        self.assertFalse(mock_invoke.called, "Direct os_agent routing should not call orchestrator LLM.")
        self.assertTrue(routed_state.get("a2a", {}).get("tasks"))
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "os_agent")
        updates = task.get("state_updates", {})
        self.assertIn("os_command", updates)
        self.assertIn("/mnt/d", str(updates.get("os_command", "")))

    def test_largest_file_query_routes_to_os_agent_not_research_pipeline(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("kendr.connector_registry.build_connector_catalog", return_value=[]),
            patch("kendr.connector_registry.connector_catalog_prompt_block", return_value=""),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("what is the largest file in the folder edscanner?")
            state["plan_steps"] = []
            state["plan_ready"] = False
            state["last_agent"] = "os_agent"

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "os_agent")
        self.assertIn("local command execution workflow", routed_state["orchestrator_reason"].lower())
        self.assertFalse(mock_invoke.called, "Direct os_agent routing should not call orchestrator LLM.")
        self.assertTrue(routed_state.get("a2a", {}).get("tasks"))
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "os_agent")
        updates = task.get("state_updates", {})
        self.assertIn("os_command", updates)
        self.assertIn("find ", str(updates.get("os_command", "")))
        self.assertFalse(bool(routed_state.get("research_pipeline_enabled", False)))

    def test_direct_tool_mode_finishes_via_direct_tool_runtime(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("kendr.connector_registry.build_connector_catalog", return_value=[]),
            patch("kendr.connector_registry.connector_catalog_prompt_block", return_value=""),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state(
                "which folders are there in my D drive?",
                execution_mode="direct_tools",
            )

            with (
                patch(
                    "kendr.runtime.run_direct_tool_loop",
                    return_value={
                        "status": "final",
                        "reason": "Handled by direct tool runtime.",
                        "response": "The top-level folders are: Projects, Media.",
                    },
                ) as mock_direct,
                patch("kendr.runtime.llm.invoke") as mock_invoke,
            ):
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "__finish__")
        self.assertIn("Projects", routed_state["final_output"])
        self.assertTrue(routed_state.get("direct_tool_loop_attempted"))
        self.assertTrue(mock_direct.called)
        self.assertFalse(mock_invoke.called, "Direct tool runtime handling should bypass the generic orchestrator LLM.")

    def test_restore_pending_user_input_approves_integration_communication_access(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            initial_state = runtime.build_initial_state("Check my Slack channels.")
            prior_state = {
                "pending_user_input_kind": "integration_approval",
                "approval_pending_scope": "integration_communication_access",
                "approval_request": {
                    "scope": "integration_communication_access",
                    "title": "Communication Access Approval",
                    "summary": "Approve access.",
                },
                "last_objective": "Check my Slack channels.",
            }

            runtime._restore_pending_user_input(initial_state, prior_state, "approve")

        self.assertTrue(initial_state["communication_authorized"])
        self.assertEqual(initial_state["pending_user_input_kind"], "")
        self.assertEqual(initial_state["approval_pending_scope"], "")

    def test_restore_pending_user_input_approves_integration_aws_access(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            initial_state = runtime.build_initial_state("List my S3 buckets.")
            prior_state = {
                "pending_user_input_kind": "integration_approval",
                "approval_pending_scope": "integration_aws_access",
                "approval_request": {
                    "scope": "integration_aws_access",
                    "title": "AWS Access Approval",
                    "summary": "Approve access.",
                },
                "last_objective": "List my S3 buckets.",
            }

            runtime._restore_pending_user_input(initial_state, prior_state, "approve")

        self.assertTrue(initial_state["aws_authorized"])
        self.assertEqual(initial_state["pending_user_input_kind"], "")
        self.assertEqual(initial_state["approval_pending_scope"], "")

    def test_restore_pending_user_input_approves_integration_github_write_access(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            initial_state = runtime.build_initial_state("Open a pull request for openai/sample.")
            prior_state = {
                "pending_user_input_kind": "integration_approval",
                "approval_pending_scope": "integration_github_write_access",
                "approval_request": {
                    "scope": "integration_github_write_access",
                    "title": "GitHub Write Access Approval",
                    "summary": "Approve write access.",
                },
                "last_objective": "Open a pull request for openai/sample.",
            }

            runtime._restore_pending_user_input(initial_state, prior_state, "approve")

        self.assertTrue(initial_state["github_write_authorized"])
        self.assertEqual(initial_state["pending_user_input_kind"], "")
        self.assertEqual(initial_state["approval_pending_scope"], "")

    def test_restore_pending_user_input_approves_integration_github_local_git_access(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            initial_state = runtime.build_initial_state("Write to a local repo file.")
            prior_state = {
                "pending_user_input_kind": "integration_approval",
                "approval_pending_scope": "integration_github_local_git_access",
                "approval_request": {
                    "scope": "integration_github_local_git_access",
                    "title": "Local Git Mutation Approval",
                    "summary": "Approve local git changes.",
                },
                "last_objective": "Write to a local repo file.",
            }

            runtime._restore_pending_user_input(initial_state, prior_state, "approve")

        self.assertTrue(initial_state["github_local_git_authorized"])
        self.assertEqual(initial_state["pending_user_input_kind"], "")
        self.assertEqual(initial_state["approval_pending_scope"], "")

    def test_restore_pending_user_input_approves_integration_github_remote_git_access(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            initial_state = runtime.build_initial_state("Push my branch.")
            prior_state = {
                "pending_user_input_kind": "integration_approval",
                "approval_pending_scope": "integration_github_remote_git_access",
                "approval_request": {
                    "scope": "integration_github_remote_git_access",
                    "title": "Remote Git Network Approval",
                    "summary": "Approve remote git access.",
                },
                "last_objective": "Push my branch.",
            }

            runtime._restore_pending_user_input(initial_state, prior_state, "approve")

        self.assertTrue(initial_state["github_remote_git_authorized"])
        self.assertEqual(initial_state["pending_user_input_kind"], "")
        self.assertEqual(initial_state["approval_pending_scope"], "")

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

    def test_project_audit_request_routes_to_master_coding_agent(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Audit this repository for production readiness and architecture risks.")

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "master_coding_agent")
        self.assertIn("audit", routed_state["orchestrator_reason"].lower())
        self.assertFalse(mock_invoke.called)
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "master_coding_agent")
        self.assertEqual(task["intent"], "project-audit-dispatch")

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

    def test_build_initial_state_normalizes_windows_style_paths_on_non_windows_hosts(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state(
                "Inspect the project.",
                incoming_channel="project_ui",
                project_root="D:/repo",
                working_directory="D:/repo",
            )

        if os.name == "nt":
            self.assertTrue(str(state.get("project_root", "")).lower().endswith("\\repo"))
            self.assertTrue(str(state.get("working_directory", "")).lower().endswith("\\repo"))
        else:
            self.assertEqual(state.get("project_root"), str(Path("/mnt/d/repo").resolve()))
            self.assertEqual(state.get("working_directory"), str(Path("/mnt/d/repo").resolve()))

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

    def test_document_generation_request_routes_to_long_document_via_registry(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Write a report on EV battery recycling and export it as a PDF.")

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "long_document_agent")
        self.assertIn("document/report", routed_state["orchestrator_reason"].lower())
        self.assertFalse(mock_invoke.called)
        self.assertTrue(routed_state["long_document_mode"])
        self.assertTrue(routed_state["long_document_job_started"])
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "long_document_agent")
        self.assertEqual(task["intent"], "long-document-dispatch")

    def test_research_request_routes_to_research_pipeline_via_registry(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Tell me about the current state of sodium-ion batteries.")

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "research_pipeline_agent")
        self.assertIn("research / information task", routed_state["orchestrator_reason"].lower())
        self.assertFalse(mock_invoke.called)
        self.assertTrue(routed_state["research_pipeline_enabled"])
        self.assertFalse(routed_state["research_pipeline_completed"])
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "research_pipeline_agent")
        self.assertEqual(task["intent"], "research-pipeline-dispatch")

    def test_local_drive_force_long_document_routes_after_ingestion_via_registry(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Do deep research on this dataset and produce a full report.")
            state["local_drive_force_long_document"] = True
            state["local_drive_calls"] = 1
            state["long_document_mode"] = True
            state["local_drive_summary"] = "Quarterly revenue and churn evidence from uploaded spreadsheets."

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "long_document_agent")
        self.assertIn("local-drive ingestion is complete", routed_state["orchestrator_reason"].lower())
        self.assertFalse(mock_invoke.called)
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "long_document_agent")
        self.assertEqual(task["intent"], "drive-informed-long-document")
        self.assertIn("Quarterly revenue and churn evidence", task["content"])

    def test_research_pipeline_continuation_routes_via_registry(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Tell me about the current state of sodium-ion batteries.")
            state["research_pipeline_enabled"] = True
            state["research_pipeline_completed"] = False

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "research_pipeline_agent")
        self.assertIn("research_pipeline_enabled is set", routed_state["orchestrator_reason"])
        self.assertFalse(mock_invoke.called)
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "research_pipeline_agent")
        self.assertEqual(task["intent"], "research-pipeline-dispatch")

    def test_research_synthesis_routes_to_worker_via_registry(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Tell me about the current state of sodium-ion batteries.")
            state["last_agent"] = "research_pipeline_agent"
            state["research_pipeline_report"] = "Source A says X. Source B says Y."

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "worker_agent")
        self.assertIn("research collection complete", routed_state["orchestrator_reason"].lower())
        self.assertFalse(mock_invoke.called)
        self.assertTrue(routed_state["research_synthesis_done"])
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "worker_agent")
        self.assertEqual(task["intent"], "research-synthesis")
        self.assertIn("Source A says X", task["content"])

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

    def test_stuck_agent_message_classifies_communication_authorization_errors(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = {
                "_consecutive_failures": {
                    "communication_summary_agent": {
                        "count": 3,
                        "last_error": "Communication agents require explicit authorization. Set state['communication_authorized']=True.",
                    }
                }
            }
            message = runtime._stuck_agent_message(state, "communication_summary_agent")
        self.assertIn("--communication-authorized", message)
        self.assertIn("--no-communication-authorized", message)
        self.assertIn("/registry/skills", message)
        self.assertIn("/registry/discovery/cards", message)

    def test_build_initial_state_enables_communication_by_default(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Summarize my communications.")
        self.assertTrue(state.get("communication_authorized"))

    def test_build_initial_state_honors_explicit_communication_override(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state(
                "Summarize my communications.",
                communication_authorized=False,
            )
        self.assertFalse(state.get("communication_authorized"))

    def test_direct_conversational_skills_query_returns_skill_snapshot(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = {
                "available_agent_cards": [
                    {"agent_name": "worker_agent", "category_label": "General"},
                    {"agent_name": "mcp_example_tool_agent", "category_label": "MCP Tools"},
                ]
            }
            message = runtime._direct_response_if_conversational("what all skills do you have, kendr?", state)
        self.assertIsNotNone(message)
        self.assertIn("active skills/agents", message)
        self.assertIn("kendr agents list", message)
        self.assertIn("kendr mcp list", message)

    def test_communication_summary_detector_ignores_registry_discovery_query(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("what all skills do you have, kendr?")
            detected = runtime._is_communication_summary_request(state)
        self.assertFalse(detected)

    def test_registry_discovery_shortcut_triggers_after_conversational_guard_window(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state(
                "Agent 'communication_summary_agent' appears stuck in a dispatch loop. what all skills do you have, kendr?"
            )
            state["orchestrator_calls"] = 8

            routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "__finish__")
        self.assertIn("active skills/agents", routed_state.get("final_output", ""))
        self.assertIn("kendr agents list", routed_state.get("final_output", ""))

    def test_explicit_os_command_routes_to_os_agent(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Run a local command to inspect the repository.")
            state["os_command"] = "Get-Location"

            routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "os_agent")
        self.assertTrue(routed_state.get("a2a", {}).get("tasks"))
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "os_agent")

    def test_vscode_install_check_routes_directly_to_os_agent_with_hint(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Can you check if VS Code is installed on my laptop?")
            state["plan_steps"] = []
            state["plan_ready"] = False
            state["last_agent"] = ""

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "os_agent")
        self.assertIn("local command execution workflow", routed_state["orchestrator_reason"].lower())
        self.assertFalse(mock_invoke.called, "Direct os_agent routing should not call orchestrator LLM.")
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "os_agent")
        updates = task.get("state_updates", {})
        self.assertIn("os_command", updates)
        self.assertIn("code", str(updates.get("os_command", "")).lower())

    def test_vscode_do_i_have_query_routes_directly_to_os_agent_with_hint(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("do i have the vscode in my laptop?")
            state["plan_steps"] = []
            state["plan_ready"] = False
            state["last_agent"] = ""

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "os_agent")
        self.assertFalse(mock_invoke.called, "Direct os_agent routing should not call orchestrator LLM.")
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "os_agent")
        updates = task.get("state_updates", {})
        self.assertIn("os_command", updates)
        self.assertIn("code", str(updates.get("os_command", "")).lower())

    def test_successful_os_agent_local_command_finishes_without_redispatch(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("do i have the vscode in my laptop?")
            state["last_agent"] = "os_agent"
            state["os_success"] = True
            state["draft_response"] = "installed:C:\\Users\\Prashant Dey\\AppData\\Local\\Programs\\Microsoft VS Code\\Code.exe"
            state["last_agent_output"] = state["draft_response"]
            state["agent_history"] = [{"agent": "os_agent", "status": "success"}]

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "__finish__")
        self.assertIn("yes.", routed_state.get("final_output", "").lower())
        self.assertIn("Code.exe", routed_state.get("final_output", ""))
        self.assertFalse(mock_invoke.called, "Successful local command workflows should not re-enter orchestrator LLM routing.")

    def test_orchestrator_finishes_immediately_on_deterministic_scope_block(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("check if vscode installed")
            state["deterministic_failure"] = {
                "agent": "os_agent",
                "kind": "policy_blocked_outside_scope",
                "reason": "Working directory is outside the allowed path scope.",
                "working_directory": "D:\\",
            }
            routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "__finish__")
        self.assertIn("dispatch loop", routed_state.get("final_output", "").lower())
        self.assertIn("allowed path", routed_state.get("final_output", "").lower())

    def test_multistep_shell_setup_routes_to_shell_plan_agent(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state(
                "Run docker container; if docker is not running, start it; if not installed, install it and then pull nginx."
            )
            state["plan_steps"] = []
            state["plan_ready"] = False
            state["last_agent"] = ""

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "shell_plan_agent")
        self.assertIn("shell_plan_agent", routed_state["orchestrator_reason"])
        self.assertFalse(mock_invoke.called, "Shell-plan direct routing should not call orchestrator LLM.")
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "shell_plan_agent")

    def test_shell_plan_result_finishes_without_replanning_loop(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("start docker and run nginx")
            state["last_agent"] = "shell_plan_agent"
            state["shell_plan_result"] = "Docker engine not running."
            state["draft_response"] = "Docker engine not running."
            state["shell_plan_steps"] = [
                {"step": 1, "status": "failed"},
                {"step": 2, "status": "blocked"},
            ]

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "__finish__")
        self.assertIn("docker engine not running", routed_state.get("final_output", "").lower())
        self.assertFalse(mock_invoke.called, "Completed shell-plan runs should not be replanned.")

    def test_software_inventory_sync_routes_to_os_agent_with_bulk_hint(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Refresh software inventory cache for installed tools.")
            state["plan_steps"] = []
            state["plan_ready"] = False
            state["last_agent"] = ""

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "os_agent")
        self.assertFalse(mock_invoke.called, "Direct os_agent routing should not call orchestrator LLM.")
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "os_agent")
        updates = task.get("state_updates", {})
        self.assertEqual(updates.get("os_command"), "__KENDR_SYNC_MACHINE__")
        self.assertEqual(updates.get("machine_sync_scope"), "software")

    def test_machine_sync_query_routes_to_os_agent_with_internal_sync_command(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("sync my machine and track recent file changes")
            state["plan_steps"] = []
            state["plan_ready"] = False
            state["last_agent"] = ""

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "os_agent")
        self.assertFalse(mock_invoke.called, "Direct os_agent routing should not call orchestrator LLM.")
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "os_agent")
        updates = task.get("state_updates", {})
        self.assertEqual(updates.get("os_command"), "__KENDR_SYNC_MACHINE__")

    def test_session_history_summary_renders_recent_user_assistant_turns(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state(
                "Continue.",
                session_history=[
                    {"role": "user", "content": "First question"},
                    {"role": "assistant", "content": "First answer"},
                    {"role": "system", "content": "ignored"},
                ],
            )
            summary = runtime._session_history_as_text(state)
        self.assertIn("user: First question", summary)
        self.assertIn("assistant: First answer", summary)
        self.assertNotIn("system", summary)

    def test_session_history_summary_includes_persisted_summary_file_context(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state(
                "Continue.",
                session_history=[{"role": "user", "content": "Most recent question"}],
                session_history_summary="# summary.md\n\n- Latest user intent: Build the dashboard.\n",
            )
            summary = runtime._session_history_as_text(state)
        self.assertIn("Persisted summary.md context", summary)
        self.assertIn("Build the dashboard", summary)
        self.assertIn("Recent raw chat turns", summary)

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
            patch("kendr.runtime.append_privileged_audit_event"),
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

    def test_long_document_subplan_scope_only_pauses_execution(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("kendr.runtime.append_privileged_audit_event"),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Create a 50-page market report.")
            state["workflow_type"] = "deep_research"
            state["pending_user_input_kind"] = ""
            state["approval_pending_scope"] = "long_document_plan"
            state["pending_user_question"] = "Approve the section plan."
            state["approval_request"] = {
                "scope": "long_document_plan",
                "summary": "Review the section plan before long-form execution.",
            }

            routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "__finish__")
        self.assertIn("section plan", routed_state["final_output"].lower())

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
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("kendr.runtime.append_privileged_audit_event"),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
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

    def test_build_initial_state_revisions_pending_long_document_subplan(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("kendr.runtime.append_privileged_audit_event"),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
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
            }
            state = runtime.build_initial_state("Change the section flow to emphasize market sizing first.", channel_session={"state": prior_state})

        self.assertTrue(state["plan_ready"])
        self.assertEqual(state["long_document_plan_status"], "revision_requested")
        self.assertTrue(state["long_document_replan_requested"])
        self.assertIn("market sizing first", state["long_document_plan_feedback"].lower())

    def test_build_initial_state_preserves_session_id_for_pending_skill_approval(self):
        with patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot):
            runtime = AgentRuntime(build_registry())
            prior_state = {
                "session_id": "session_skill_approval_demo",
                "last_objective": "Search the web for the latest laptop CPU benchmarks.",
                "awaiting_user_input": True,
                "pending_user_input_kind": "skill_approval",
                "approval_pending_scope": "skill_permission:web-search",
                "pending_user_question": "Approve skill execution for Web Search.",
                "approval_request": {
                    "scope": "skill_permission:web-search",
                    "metadata": {
                        "approval_mode": "skill_permission_grant",
                        "skill_id": "core:web-search",
                        "skill_slug": "web-search",
                        "session_id": "session_skill_approval_demo",
                    },
                },
            }
            state = runtime.build_initial_state("approve for this session", channel_session={"state": prior_state})

        self.assertEqual(state["session_id"], "session_skill_approval_demo")
        self.assertEqual(state["current_objective"], "Search the web for the latest laptop CPU benchmarks.")
        self.assertEqual(state["pending_user_input_kind"], "")
        self.assertEqual(state["approval_pending_scope"], "")
        self.assertEqual(state["approval_request"], {})

    def test_build_initial_state_restores_scope_only_pending_deep_research_confirmation(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("kendr.runtime.append_privileged_audit_event"),
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

    def test_build_initial_state_approve_deep_research_resets_stale_long_document_flags(self):
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
                "pending_user_input_kind": "deep_research_confirmation",
                "approval_pending_scope": "deep_research_confirmation",
                "pending_user_question": "Reply approve to continue.",
                "approval_request": {
                    "scope": "deep_research_confirmation",
                    "summary": "Review scope before expensive execution.",
                },
                "workflow_type": "deep_research",
                "deep_research_mode": True,
                "long_document_mode": True,
                "long_document_job_started": True,
                "last_agent": "long_document_agent",
            }
            state = runtime.build_initial_state("approve", channel_session={"state": prior_state})

        self.assertTrue(state["deep_research_confirmed"])
        self.assertTrue(state["deep_research_mode"])
        self.assertEqual(state["workflow_type"], "deep_research")
        self.assertFalse(state["long_document_mode"])
        self.assertFalse(state["long_document_job_started"])
        self.assertEqual(state["pending_user_input_kind"], "")
        self.assertEqual(state["approval_pending_scope"], "")

    def test_orchestrator_resumes_deep_research_after_confirmation_with_analysis_card(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Investigate ESG claims for potential greenwashing.")
            state["workflow_type"] = "deep_research"
            state["deep_research_mode"] = True
            state["deep_research_confirmed"] = True
            state["deep_research_result_card"] = {"kind": "analysis"}
            state["long_document_mode"] = True
            state["long_document_job_started"] = True
            state["last_agent"] = "long_document_agent"

            with patch("kendr.runtime.llm.invoke") as mock_invoke:
                routed_state = runtime.orchestrator_agent(state)

        self.assertEqual(routed_state["next_agent"], "long_document_agent")
        self.assertIn("resuming long_document_agent", routed_state["orchestrator_reason"].lower())
        self.assertFalse(mock_invoke.called, "Resume routing should bypass the generic orchestrator LLM.")
        self.assertTrue(routed_state.get("a2a", {}).get("tasks"))
        task = routed_state["a2a"]["tasks"][-1]
        self.assertEqual(task["recipient"], "long_document_agent")
        self.assertEqual(task["intent"], "long-document-resume")

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

    def test_adaptive_planner_policy_skips_simple_single_step_task(self):
        runtime = AgentRuntime(build_registry())
        state = {
            "user_query": "Rename variable foo to bar in the script.",
            "current_objective": "Rename variable foo to bar in the script.",
            "plan_steps": [],
            "plan_ready": False,
            "adaptive_agent_selection": True,
            "planner_policy_mode": "adaptive",
            "setup_actions": [],
        }

        should_plan, reason, signals = runtime._should_run_planner(state)

        self.assertFalse(should_plan)
        self.assertIn("adaptive", reason.lower())
        self.assertLess(signals.get("score", 999), signals.get("threshold", -999))

    def test_adaptive_planner_policy_requires_plan_for_superrag(self):
        runtime = AgentRuntime(build_registry())
        state = {
            "user_query": "Build a superRAG session from these URLs.",
            "current_objective": "Build a superRAG session from these URLs.",
            "superrag_urls": ["https://example.com"],
            "plan_steps": [],
            "plan_ready": False,
            "adaptive_agent_selection": True,
            "planner_policy_mode": "adaptive",
        }

        should_plan, reason, _ = runtime._should_run_planner(state)

        self.assertTrue(should_plan)
        self.assertIn("superrag", reason.lower())

    def test_adaptive_reviewer_policy_skips_low_risk_short_output(self):
        runtime = AgentRuntime(build_registry())
        state = {
            "user_query": "Rename variable foo to bar.",
            "current_objective": "Rename variable foo to bar.",
            "adaptive_agent_selection": True,
            "reviewer_policy_mode": "adaptive",
            "skip_reviews": False,
            "review_revision_counts": {},
            "enforce_quality_gate": True,
        }

        needs_review, reason, _ = runtime._should_request_review(
            state,
            agent_name="worker_agent",
            output_text="Variable renamed successfully.",
            skip_review_once=False,
        )

        self.assertFalse(needs_review)
        self.assertIn("skipped review", reason.lower())

    def test_adaptive_reviewer_policy_enforces_quality_gate_for_project_build(self):
        runtime = AgentRuntime(build_registry())
        state = {
            "user_query": "Build a production-ready API platform.",
            "current_objective": "Build a production-ready API platform.",
            "project_build_mode": True,
            "adaptive_agent_selection": True,
            "reviewer_policy_mode": "adaptive",
            "skip_reviews": False,
            "review_revision_counts": {},
            "enforce_quality_gate": True,
        }

        needs_review, reason, _ = runtime._should_request_review(
            state,
            agent_name="backend_builder_agent",
            output_text="Implemented API routes, services, auth middleware, and persistence layer.",
            skip_review_once=False,
        )

        self.assertTrue(needs_review)
        self.assertIn("quality gate", reason.lower())

    def test_policy_gated_agents_are_removed_from_orchestrator_candidate_list(self):
        runtime = AgentRuntime(build_registry())
        state = {
            "user_query": "Rename variable foo to bar.",
            "current_objective": "Rename variable foo to bar.",
            "available_agents": ["planner_agent", "reviewer_agent", "worker_agent"],
            "plan_steps": [],
            "plan_ready": False,
            "adaptive_agent_selection": True,
            "planner_policy_mode": "adaptive",
            "reviewer_policy_mode": "adaptive",
            "review_pending": False,
        }
        state["_policy_blocked_agents"] = sorted(runtime._policy_blocked_agents(state))

        available = runtime._available_agent_descriptions(state)

        self.assertIn("worker_agent", available)
        self.assertNotIn("planner_agent", available)
        self.assertNotIn("reviewer_agent", available)


if __name__ == "__main__":
    unittest.main()
