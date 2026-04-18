import json
import os
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from kendr.persistence import initialize_db, list_execution_plans, list_orchestration_events, list_plan_tasks
from tasks.planning_tasks import normalize_plan_data, planner_agent
from tasks.project_blueprint_tasks import project_blueprint_agent
from tasks.utils import model_selection_for_agent, runtime_model_override


class PlanningTaskTests(unittest.TestCase):
    def test_normalize_plan_data_excludes_planner_from_execution_steps(self):
        raw_plan = {
            "summary": "Test plan",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Lock scope",
                    "agent": "planner_agent",
                    "task": "Refine the scope note.",
                    "substeps": [
                        {
                            "id": "step-1.1",
                            "title": "List requirements",
                            "agent": "planner_agent",
                            "task": "List the report requirements.",
                        }
                    ],
                },
                {
                    "id": "step-2",
                    "title": "Catalog files",
                    "agent": "local_drive_agent",
                    "task": "Catalog the local files and summarize the usable evidence.",
                    "success_criteria": "A file catalog and evidence summary exist.",
                },
            ],
        }

        plan_data = normalize_plan_data(raw_plan, "Build a fundraising report.")

        self.assertEqual(len(plan_data["steps"]), 2)
        self.assertEqual(len(plan_data["execution_steps"]), 1)
        self.assertEqual(plan_data["execution_steps"][0]["id"], "step-2")
        self.assertEqual(plan_data["execution_steps"][0]["agent"], "local_drive_agent")

    def test_normalize_plan_data_flattens_wrapper_steps_to_leaf_execution_steps(self):
        raw_plan = {
            "summary": "Test plan",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Ingest documents",
                    "agent": "document_ingestion_agent",
                    "task": "Ingest and structure the document corpus.",
                    "success_criteria": "The corpus is ready for analysis.",
                    "substeps": [
                        {
                            "id": "step-1.1",
                            "title": "Catalog drive files",
                            "agent": "local_drive_agent",
                            "task": "Build the local file inventory.",
                            "success_criteria": "A file manifest exists.",
                        },
                        {
                            "id": "step-1.2",
                            "title": "OCR scans",
                            "agent": "ocr_agent",
                            "task": "OCR image-based documents.",
                            "success_criteria": "Scanned documents are readable.",
                        },
                        {
                            "id": "step-1.3",
                            "title": "Structure corpus",
                            "agent": "structured_data_agent",
                            "task": "Structure the extracted content for analysis.",
                            "depends_on": ["step-1.1", "step-1.2"],
                            "success_criteria": "Structured extracts are available.",
                        },
                    ],
                },
                {
                    "id": "step-2",
                    "title": "Map evidence",
                    "agent": "claim_evidence_mapping_agent",
                    "task": "Map the findings to report sections.",
                    "depends_on": ["step-1"],
                    "success_criteria": "Evidence is mapped to the report.",
                },
            ],
        }

        plan_data = normalize_plan_data(raw_plan, "Build a fundraising report.")

        execution_steps = plan_data["execution_steps"]
        self.assertEqual([step["id"] for step in execution_steps], ["step-1.1", "step-1.2", "step-1.3", "step-2"])
        self.assertEqual(execution_steps[0]["agent"], "local_drive_agent")
        self.assertEqual(execution_steps[1]["depends_on"], ["step-1.1"])
        self.assertEqual(execution_steps[2]["depends_on"], ["step-1.1", "step-1.2"])
        self.assertEqual(execution_steps[3]["depends_on"], ["step-1.1", "step-1.2", "step-1.3"])

    def test_parallel_substeps_keep_shared_parent_dependencies_when_flattened(self):
        raw_plan = {
            "summary": "Parallel OCR plan",
            "steps": [
                {
                    "id": "step-1",
                    "title": "Ingest documents",
                    "agent": "document_ingestion_agent",
                    "task": "Ingest documents.",
                    "substeps": [
                        {
                            "id": "step-1.1",
                            "title": "OCR invoices",
                            "agent": "ocr_agent",
                            "task": "OCR invoices.",
                            "parallel_group": "group-a",
                        },
                        {
                            "id": "step-1.2",
                            "title": "OCR bank statements",
                            "agent": "ocr_agent",
                            "task": "OCR bank statements.",
                            "parallel_group": "group-a",
                        },
                    ],
                },
                {
                    "id": "step-2",
                    "title": "Summarize evidence",
                    "agent": "structured_data_agent",
                    "task": "Summarize the extracted evidence.",
                    "depends_on": ["step-1"],
                },
            ],
        }

        plan_data = normalize_plan_data(raw_plan, "Build a fundraising report.")

        execution_steps = plan_data["execution_steps"]
        self.assertEqual([step["id"] for step in execution_steps], ["step-1.1", "step-1.2", "step-2"])
        self.assertEqual(execution_steps[0]["depends_on"], [])
        self.assertEqual(execution_steps[1]["depends_on"], [])
        self.assertEqual(execution_steps[2]["depends_on"], ["step-1.1", "step-1.2"])

    def test_planner_agent_fails_fast_when_provider_is_not_ready(self):
        state = {"user_query": "Build a deployment plan.", "current_objective": "Build a deployment plan."}

        with (
            patch("tasks.planning_tasks.begin_agent_session", return_value=("", "Build a deployment plan.", "")),
            patch("tasks.planning_tasks.log_task_update"),
            patch("tasks.planning_tasks.model_selection_for_agent", return_value={"provider": "openai", "model": "gpt-4o-mini", "source": "OPENAI_MODEL_GENERAL"}),
            patch("tasks.planning_tasks.provider_status", return_value={"provider": "openai", "ready": False, "note": "Set OPENAI_API_KEY", "base_url": "", "model": "gpt-4o-mini"}),
        ):
            with self.assertRaises(RuntimeError) as exc:
                planner_agent(state)

        self.assertIn("Planner preflight failed", str(exc.exception))
        self.assertIn("Set OPENAI_API_KEY", str(exc.exception))

    def test_planner_agent_wraps_provider_connection_errors_with_context(self):
        state = {"user_query": "Build a deployment plan.", "current_objective": "Build a deployment plan."}

        with (
            patch("tasks.planning_tasks.begin_agent_session", return_value=("", "Build a deployment plan.", "")),
            patch("tasks.planning_tasks.log_task_update"),
            patch("tasks.planning_tasks.model_selection_for_agent", return_value={"provider": "openai", "model": "gpt-4o-mini", "source": "OPENAI_MODEL_GENERAL"}),
            patch("tasks.planning_tasks.provider_status", return_value={"provider": "openai", "ready": True, "note": "API key configured", "base_url": "", "model": "gpt-4o-mini"}),
            patch("tasks.planning_tasks.llm.invoke", side_effect=RuntimeError("Connection error")),
        ):
            with self.assertRaises(RuntimeError) as exc:
                planner_agent(state)

        message = str(exc.exception)
        self.assertIn("provider 'openai'", message)
        self.assertIn("model 'gpt-4o-mini'", message)
        self.assertIn("Connection error", message)

    def test_planner_agent_blocks_security_flow_when_plan_json_is_invalid(self):
        state = {
            "user_query": "Scan https://example.com for vulnerabilities",
            "current_objective": "Scan https://example.com for vulnerabilities",
            "available_agents": [
                "security_scope_guard_agent",
                "recon_agent",
                "scanner_agent",
                "security_report_agent",
                "worker_agent",
            ],
            "security_authorized": True,
            "security_target_url": "https://example.com",
            "security_authorization_note": "SEC-123 approved by owner",
        }

        with (
            patch("tasks.planning_tasks.begin_agent_session", return_value=("", state["user_query"], "")),
            patch("tasks.planning_tasks.log_task_update"),
            patch("tasks.planning_tasks.write_text_file"),
            patch("tasks.planning_tasks.update_planning_file"),
            patch("tasks.planning_tasks.publish_agent_output", side_effect=lambda s, *_args, **_kwargs: s),
            patch("tasks.planning_tasks.model_selection_for_agent", return_value={"provider": "openai", "model": "gpt-4o-mini", "source": "OPENAI_MODEL_GENERAL"}),
            patch("tasks.planning_tasks.provider_status", return_value={"provider": "openai", "ready": True, "note": "", "base_url": "", "model": "gpt-4o-mini"}),
            patch("tasks.planning_tasks.llm.invoke", return_value="not-json-at-all"),
        ):
            result = planner_agent(state)

        self.assertTrue(result["plan_needs_clarification"])
        self.assertEqual(result["pending_user_input_kind"], "clarification")
        self.assertEqual(result["plan_approval_status"], "clarification_needed")
        self.assertEqual(result["plan_steps"], [])
        self.assertIn("security request", result["pending_user_question"].lower())
        self.assertIn("security_scope_guard_agent", result["pending_user_question"])
        self.assertNotIn("worker_agent", result["pending_user_question"])

    def test_planner_agent_sanitizes_project_build_steps_in_deep_research_mode(self):
        state = {
            "user_query": "Do deep research on chaos engineering failure simulation in AWS and export the report.",
            "current_objective": "Do deep research on chaos engineering failure simulation in AWS and export the report.",
            "workflow_type": "deep_research",
            "deep_research_mode": True,
        }
        planner_payload = json.dumps(
            {
                "summary": "Research first, then create a project blueprint.",
                "steps": [
                    {
                        "id": "step-1",
                        "title": "Research topic",
                        "agent": "long_document_agent",
                        "task": "Research the topic and compile the report.",
                        "success_criteria": "Research findings are compiled.",
                    },
                    {
                        "id": "step-2",
                        "title": "Create blueprint",
                        "agent": "project_blueprint_agent",
                        "task": "Create a project blueprint for the implementation.",
                        "depends_on": ["step-1"],
                        "success_criteria": "A blueprint is ready for approval.",
                    },
                ],
            }
        )

        with (
            patch("tasks.planning_tasks.begin_agent_session", return_value=("", state["user_query"], "")),
            patch("tasks.planning_tasks.log_task_update"),
            patch("tasks.planning_tasks.write_text_file"),
            patch("tasks.planning_tasks.update_planning_file"),
            patch("tasks.planning_tasks.publish_agent_output", side_effect=lambda current_state, *_args, **_kwargs: current_state),
            patch("tasks.planning_tasks.model_selection_for_agent", return_value={"provider": "openai", "model": "gpt-4o-mini", "source": "OPENAI_MODEL_GENERAL"}),
            patch("tasks.planning_tasks.provider_status", return_value={"provider": "openai", "ready": True, "note": "", "base_url": "", "model": "gpt-4o-mini"}),
            patch("tasks.planning_tasks.llm.invoke", return_value=planner_payload),
        ):
            result = planner_agent(state)

        self.assertEqual(len(result["plan_steps"]), 1)
        self.assertEqual(result["plan_steps"][0]["agent"], "long_document_agent")
        self.assertNotIn("project_blueprint_agent", result["plan"])

    def test_planner_agent_replaces_placeholder_plan_with_safe_research_fallback(self):
        state = {
            "user_query": "Do deep research on supply-chain resilience.",
            "current_objective": "Do deep research on supply-chain resilience.",
            "workflow_type": "deep_research",
            "deep_research_mode": True,
            "available_agents": ["deep_research_agent", "worker_agent"],
        }
        planner_payload = json.dumps(
            {
                "summary": "Placeholder plan.",
                "steps": [
                    {
                        "id": "step-1",
                        "title": "Do work",
                        "agent": "agent_name",
                        "task": "Perform specified actions.",
                        "success_criteria": "Confirm completion.",
                    }
                ],
            }
        )

        with (
            patch("tasks.planning_tasks.begin_agent_session", return_value=("", state["user_query"], "")),
            patch("tasks.planning_tasks.log_task_update"),
            patch("tasks.planning_tasks.write_text_file"),
            patch("tasks.planning_tasks.update_planning_file"),
            patch("tasks.planning_tasks.publish_agent_output", side_effect=lambda current_state, *_args, **_kwargs: current_state),
            patch("tasks.planning_tasks.model_selection_for_agent", return_value={"provider": "ollama", "model": "lfm2.5-thinking:latest", "source": "runtime_override"}),
            patch("tasks.planning_tasks.provider_status", return_value={"provider": "ollama", "ready": True, "note": "", "base_url": "", "model": "lfm2.5-thinking:latest"}),
            patch("tasks.planning_tasks.llm.invoke", return_value=planner_payload),
        ):
            result = planner_agent(state)

        self.assertEqual(len(result["plan_steps"]), 1)
        self.assertEqual(result["plan_steps"][0]["agent"], "deep_research_agent")
        self.assertNotIn("agent_name", result["plan"])
        self.assertIn("safe research-only execution plan", result["plan_data"]["summary"].lower())

    def test_project_blueprint_agent_refuses_to_run_in_deep_research_workflow(self):
        state = {
            "workflow_type": "deep_research",
            "deep_research_mode": True,
            "blueprint_request": "Build an AWS chaos engineering service.",
        }

        with (
            patch("tasks.project_blueprint_tasks.begin_agent_session", return_value=("", state["blueprint_request"], "")),
            patch("tasks.project_blueprint_tasks.log_task_update"),
            patch("tasks.project_blueprint_tasks.publish_agent_output", side_effect=lambda current_state, *_args, **_kwargs: current_state),
        ):
            result = project_blueprint_agent(state)

        self.assertEqual(result["blueprint_status"], "blocked_in_research_workflow")
        self.assertFalse(result["blueprint_waiting_for_approval"])
        self.assertIn("Project blueprint generation is disabled", result["draft_response"])

    def test_normalize_plan_data_keeps_non_security_fallback_behavior(self):
        plan_data = normalize_plan_data({}, "Build a fundraising report.")

        self.assertEqual(len(plan_data["execution_steps"]), 1)
        self.assertEqual(plan_data["execution_steps"][0]["agent"], "worker_agent")

    def test_runtime_model_override_changes_agent_model_selection(self):
        with runtime_model_override(provider="anthropic", model="claude-sonnet-test"):
            selection = model_selection_for_agent("planner_agent")

        self.assertEqual(selection["provider"], "anthropic")
        self.assertEqual(selection["model"], "claude-sonnet-test")
        self.assertEqual(selection["source"], "runtime_override")

    def test_planner_agent_persists_execution_plan_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "workflow.sqlite3")
            initialize_db(db_path)
            state = {
                "run_id": "run-plan-1",
                "db_path": db_path,
                "selected_intent_id": "intent-1",
                "user_query": "Build a deployment plan.",
                "current_objective": "Build a deployment plan.",
            }
            planner_payload = json.dumps(
                {
                    "summary": "Deployment plan",
                    "steps": [
                        {
                            "id": "step-1",
                            "title": "Prepare manifests",
                            "agent": "worker_agent",
                            "task": "Prepare the deployment manifests.",
                            "success_criteria": "Deployment manifests are ready.",
                        },
                        {
                            "id": "step-2",
                            "title": "Run verification",
                            "agent": "worker_agent",
                            "task": "Run verification checks.",
                            "depends_on": ["step-1"],
                            "success_criteria": "Verification checks pass.",
                        },
                    ],
                }
            )

            with (
                patch("tasks.planning_tasks.begin_agent_session", return_value=("", state["user_query"], "")),
                patch("tasks.planning_tasks.log_task_update"),
                patch("tasks.planning_tasks.write_text_file"),
                patch("tasks.planning_tasks.update_planning_file"),
                patch("tasks.planning_tasks.publish_agent_output", side_effect=lambda current_state, *_args, **_kwargs: current_state),
                patch("tasks.planning_tasks.model_selection_for_agent", return_value={"provider": "openai", "model": "gpt-4o-mini", "source": "OPENAI_MODEL_GENERAL"}),
                patch("tasks.planning_tasks.provider_status", return_value={"provider": "openai", "ready": True, "note": "", "base_url": "", "model": "gpt-4o-mini"}),
                patch("tasks.planning_tasks.llm.invoke", return_value=planner_payload),
            ):
                result = planner_agent(state)

            plans = list_execution_plans("run-plan-1", db_path=db_path)
            steps = list_plan_tasks(plan_id=result["orchestration_plan_id"], db_path=db_path)
            events = list_orchestration_events("run-plan-1", db_path=db_path)

            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0]["intent_id"], "intent-1")
            self.assertEqual(plans[0]["status"], "awaiting_approval")
            self.assertEqual(plans[0]["approval_status"], "pending")
            self.assertEqual(len(steps), 2)
            self.assertEqual(steps[1]["depends_on"], ["step-1"])
            self.assertEqual(events[-1]["event_type"], "plan.generated")
            self.assertEqual(result["orchestration_plan_version"], 1)

    def test_planner_auto_approves_conservative_read_only_plan(self):
        state = {
            "run_id": "run-plan-read-only",
            "db_path": "",
            "user_query": "Research the local evidence and summarize it.",
            "current_objective": "Research the local evidence and summarize it.",
        }
        planner_payload = json.dumps(
            {
                "summary": "Inspect and summarize the available evidence.",
                "steps": [
                    {
                        "id": "step-1",
                        "title": "Catalog files",
                        "agent": "local_drive_agent",
                        "task": "Catalog the local files and extract the relevant evidence.",
                        "success_criteria": "A file catalog exists.",
                    },
                    {
                        "id": "step-2",
                        "title": "Research findings",
                        "agent": "people_research_agent",
                        "task": "Research and summarize the evidence from the collected notes.",
                        "depends_on": ["step-1"],
                        "success_criteria": "A concise findings summary exists.",
                    },
                ],
            }
        )

        with (
            patch("tasks.planning_tasks.begin_agent_session", return_value=("", state["user_query"], "")),
            patch("tasks.planning_tasks.log_task_update"),
            patch("tasks.planning_tasks.write_text_file"),
            patch("tasks.planning_tasks.update_planning_file"),
            patch("tasks.planning_tasks.publish_agent_output", side_effect=lambda current_state, *_args, **_kwargs: current_state),
            patch("tasks.planning_tasks.model_selection_for_agent", return_value={"provider": "openai", "model": "gpt-4o-mini", "source": "OPENAI_MODEL_GENERAL"}),
            patch("tasks.planning_tasks.provider_status", return_value={"provider": "openai", "ready": True, "note": "", "base_url": "", "model": "gpt-4o-mini"}),
            patch("tasks.planning_tasks.llm.invoke", return_value=planner_payload),
        ):
            result = planner_agent(state)

        self.assertTrue(result["plan_ready"])
        self.assertFalse(result["plan_waiting_for_approval"])
        self.assertEqual(result["plan_approval_status"], "approved")
        self.assertEqual(result["plan_steps"][0]["side_effect_level"], "read_only")
        self.assertEqual(result["plan_steps"][1]["side_effect_level"], "read_only")


if __name__ == "__main__":
    unittest.main()
