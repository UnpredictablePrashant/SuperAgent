import os
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from kendr.discovery import build_registry
from kendr.runtime import AgentRuntime
from kendr.workflow_registry import match_explicit_workflow


class WorkflowRegistryTests(unittest.TestCase):
    @staticmethod
    def _fake_setup_snapshot(agent_cards: list[dict]) -> dict:
        return {
            "available_agents": [str(card.get("agent_name", "")) for card in agent_cards if isinstance(card, dict)],
            "disabled_agents": {},
            "setup_actions": [],
            "summary_text": "",
        }

    def test_match_explicit_workflow_returns_local_command_dispatch_plan(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("which folders are there in my D drive?")
            plan = match_explicit_workflow(runtime, state)

        self.assertIsNotNone(plan)
        self.assertEqual(plan.agent_name, "os_agent")
        self.assertEqual(plan.intent, "local-command-dispatch")
        self.assertIn("/mnt/d", str(plan.state_updates.get("os_command", "")))

    def test_match_explicit_workflow_routes_multistep_setup_to_shell_plan_agent(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state(
                "Install docker if missing, then start it and run an nginx container."
            )
            plan = match_explicit_workflow(runtime, state)

        self.assertIsNotNone(plan)
        self.assertEqual(plan.agent_name, "shell_plan_agent")
        self.assertEqual(plan.intent, "shell-plan-dispatch")
        self.assertIn("multi-step local setup", plan.reason.lower())

    def test_match_explicit_workflow_allows_follow_up_local_command_after_os_agent(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("what is the largest file in the folder edscanner?")
            state["last_agent"] = "os_agent"
            plan = match_explicit_workflow(runtime, state)

        self.assertIsNotNone(plan)
        self.assertEqual(plan.agent_name, "os_agent")
        self.assertEqual(plan.intent, "local-command-dispatch")
        self.assertIn("find ", str(plan.state_updates.get("os_command", "")))

    def test_match_explicit_workflow_returns_github_dispatch_plan(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("open a pull request on openai/sample for the bugfix")
            plan = match_explicit_workflow(runtime, state)

        self.assertIsNotNone(plan)
        self.assertEqual(plan.agent_name, "github_agent")
        self.assertEqual(plan.intent, "github-operation")
        self.assertIn("github / git repository workflow", plan.reason.lower())

    def test_match_explicit_workflow_returns_project_audit_dispatch_plan(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Audit this repository for production readiness and architecture risks.")
            plan = match_explicit_workflow(runtime, state, stage="pre_planner")

        self.assertIsNotNone(plan)
        self.assertEqual(plan.agent_name, "master_coding_agent")
        self.assertEqual(plan.intent, "project-audit-dispatch")
        self.assertIn("audit", plan.reason.lower())

    def test_match_explicit_workflow_returns_document_generation_dispatch_plan(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Write a report on EV battery recycling and export it as a PDF.")
            plan = match_explicit_workflow(runtime, state, stage="pre_planner")

        self.assertIsNotNone(plan)
        self.assertEqual(plan.agent_name, "long_document_agent")
        self.assertEqual(plan.intent, "long-document-dispatch")
        self.assertTrue(plan.state_mutations["long_document_job_started"])
        self.assertTrue(plan.state_updates["long_document_collect_sources_first"])

    def test_match_explicit_workflow_blocks_project_blueprint_when_deep_research_mode_is_active(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Build a project for chaos engineering failure simulation on AWS.")
            state["workflow_type"] = "deep_research"
            state["deep_research_mode"] = True
            plan = match_explicit_workflow(runtime, state, stage="early")

        self.assertIsNone(plan)

    def test_match_explicit_workflow_returns_deep_research_resume_plan(self):
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
            plan = match_explicit_workflow(runtime, state, stage="resume")

        self.assertIsNotNone(plan)
        self.assertEqual(plan.agent_name, "long_document_agent")
        self.assertEqual(plan.intent, "long-document-resume")
        self.assertTrue(plan.state_mutations["deep_research_mode"])
        self.assertTrue(plan.state_mutations["long_document_mode"])
        self.assertTrue(plan.state_mutations["long_document_job_started"])

    def test_match_explicit_workflow_returns_research_pipeline_dispatch_plan(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Tell me about the current state of sodium-ion batteries.")
            plan = match_explicit_workflow(runtime, state, stage="pre_planner")

        self.assertIsNotNone(plan)
        self.assertEqual(plan.agent_name, "research_pipeline_agent")
        self.assertEqual(plan.intent, "research-pipeline-dispatch")
        self.assertTrue(plan.state_mutations["research_pipeline_enabled"])
        self.assertEqual(plan.state_updates["research_sources"], ["web"])

    def test_match_explicit_workflow_returns_long_document_for_deep_research_request(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Do deep research on OpenAI's enterprise strategy with citations.")
            plan = match_explicit_workflow(runtime, state, stage="late")

        self.assertIsNotNone(plan)
        self.assertEqual(plan.agent_name, "long_document_agent")
        self.assertEqual(plan.intent, "deep-research-dispatch")
        self.assertEqual(plan.state_mutations["workflow_type"], "deep_research")
        self.assertTrue(plan.state_mutations["deep_research_mode"])
        self.assertTrue(plan.state_mutations["long_document_mode"])
        self.assertTrue(plan.state_mutations["long_document_job_started"])

    def test_match_explicit_workflow_returns_drive_informed_long_document_plan(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Do deep research on this dataset and produce a full report.")
            state["local_drive_force_long_document"] = True
            state["local_drive_calls"] = 1
            state["long_document_mode"] = True
            state["local_drive_summary"] = "Quarterly revenue and churn evidence from uploaded spreadsheets."
            plan = match_explicit_workflow(runtime, state, stage="post_approval")

        self.assertIsNotNone(plan)
        self.assertEqual(plan.agent_name, "long_document_agent")
        self.assertEqual(plan.intent, "drive-informed-long-document")
        self.assertEqual(plan.state_updates["long_document_pages"], 50)
        self.assertTrue(plan.state_mutations["long_document_mode"])
        self.assertTrue(plan.state_mutations["long_document_job_started"])
        self.assertIn("Quarterly revenue and churn evidence", plan.content)

    def test_match_explicit_workflow_blocks_drive_informed_long_document_after_completion(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Do deep research on this dataset and produce a full report.")
            state["local_drive_force_long_document"] = True
            state["local_drive_calls"] = 1
            state["long_document_mode"] = True
            state["local_drive_summary"] = "Quarterly revenue and churn evidence from uploaded spreadsheets."
            state["long_document_compiled_path"] = "output/final_report.md"
            state["last_agent"] = "reviewer_agent"
            plan = match_explicit_workflow(runtime, state, stage="post_approval")

        self.assertIsNone(plan)

    def test_match_explicit_workflow_returns_research_pipeline_continue_plan(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Tell me about the current state of sodium-ion batteries.")
            state["research_pipeline_enabled"] = True
            state["research_pipeline_completed"] = False
            plan = match_explicit_workflow(runtime, state, stage="continuation")

        self.assertIsNotNone(plan)
        self.assertEqual(plan.agent_name, "research_pipeline_agent")
        self.assertEqual(plan.intent, "research-pipeline-dispatch")
        self.assertEqual(plan.state_updates["research_sources"], ["web"])

    def test_match_explicit_workflow_returns_research_synthesis_plan(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Tell me about the current state of sodium-ion batteries.")
            state["last_agent"] = "research_pipeline_agent"
            state["last_agent_status"] = "success"
            state["research_pipeline_report"] = "Source A says X. Source B says Y."
            plan = match_explicit_workflow(runtime, state, stage="continuation")

        self.assertIsNotNone(plan)
        self.assertEqual(plan.agent_name, "worker_agent")
        self.assertEqual(plan.intent, "research-synthesis")
        self.assertTrue(plan.state_mutations["research_synthesis_done"])
        self.assertIn("Source A says X", plan.content)

    def test_match_explicit_workflow_does_not_route_research_synthesis_from_stale_draft_response(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("tasks.a2a_protocol.upsert_agent_card"),
            patch("tasks.a2a_protocol.insert_message"),
            patch("tasks.a2a_protocol.upsert_task"),
            patch("tasks.a2a_protocol.insert_artifact"),
        ):
            runtime = AgentRuntime(build_registry())
            state = runtime.build_initial_state("Tell me about the current state of sodium-ion batteries.")
            state["last_agent"] = "deep_research_agent"
            state["last_agent_status"] = "error"
            state["draft_response"] = "Reply `approve` to continue."
            plan = match_explicit_workflow(runtime, state, stage="continuation")

        self.assertIsNone(plan)
