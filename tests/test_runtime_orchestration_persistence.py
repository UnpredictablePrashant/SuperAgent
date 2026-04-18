import os
import tempfile
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from kendr.discovery import build_registry
from kendr.definitions import AgentDefinition
from kendr.persistence import (
    initialize_db,
    insert_run,
    list_orchestration_events,
    list_plan_tasks,
    replace_plan_tasks,
    upsert_execution_plan,
)
from kendr.registry import Registry
from kendr.runtime import AgentRuntime


class RuntimeOrchestrationPersistenceTests(unittest.TestCase):
    @staticmethod
    def _fake_setup_snapshot(agent_cards: list[dict]) -> dict:
        return {
            "available_agents": [str(card.get("agent_name", "")) for card in agent_cards if isinstance(card, dict)],
            "disabled_agents": {},
            "setup_actions": [],
            "summary_text": "",
        }

    @staticmethod
    def _custom_registry() -> Registry:
        registry = Registry()

        def read_one_agent(state: dict) -> dict:
            time.sleep(0.02)
            state["read_one_result"] = "alpha"
            state["used_execution_surfaces"] = [{"label": "skill:read-one"}]
            return state

        def read_two_agent(state: dict) -> dict:
            time.sleep(0.02)
            state["read_two_result"] = "beta"
            state["used_execution_surfaces"] = [{"label": "skill:read-two"}]
            return state

        registry.register_agent(
            AgentDefinition(
                name="read_one_agent",
                handler=read_one_agent,
                description="Reads and catalogs evidence.",
                output_keys=["read_one_result"],
                metadata={"read_only": True},
            )
        )
        registry.register_agent(
            AgentDefinition(
                name="read_two_agent",
                handler=read_two_agent,
                description="Reads and summarizes evidence.",
                output_keys=["read_two_result"],
                metadata={"read_only": True},
            )
        )
        return registry

    def test_plan_step_lifecycle_updates_persisted_plan_tasks(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "workflow.sqlite3")
            initialize_db(db_path)
            insert_run("run-1", "Build the project", "2026-04-15T00:00:00+00:00", "running", db_path=db_path)

            with (
                patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
                patch("kendr.mcp_manager.list_servers_safe", return_value=[]),
                patch("tasks.a2a_protocol.upsert_agent_card"),
                patch("tasks.a2a_protocol.insert_message"),
                patch("tasks.a2a_protocol.upsert_task"),
                patch("tasks.a2a_protocol.insert_artifact"),
            ):
                runtime = AgentRuntime(build_registry())
                state = runtime.build_initial_state("Build the project", run_id="run-1", db_path=db_path)

            plan_id = "run-1:plan:v1"
            upsert_execution_plan(
                plan_id,
                run_id="run-1",
                intent_id="intent-project",
                version=1,
                status="approved",
                approval_status="approved",
                objective="Build the project",
                summary="Initial plan",
                db_path=db_path,
            )
            replace_plan_tasks(
                plan_id,
                "run-1",
                [
                    {
                        "id": "step-1",
                        "title": "Scaffold project",
                        "agent": "worker_agent",
                        "task": "Scaffold the project.",
                        "success_criteria": "Project structure exists.",
                    }
                ],
                db_path=db_path,
            )

            state["orchestration_plan_id"] = plan_id
            state["orchestration_plan_version"] = 1
            state["plan_steps"] = [
                {
                    "id": "step-1",
                    "title": "Scaffold project",
                    "agent": "worker_agent",
                    "task": "Scaffold the project.",
                    "success_criteria": "Project structure exists.",
                }
            ]
            state["plan_step_index"] = 0
            state["plan_approval_status"] = "approved"

            runtime._mark_step_running(state, 0)
            runtime._mark_planned_step_complete(state, "Project scaffold created.")

            steps = list_plan_tasks(plan_id=plan_id, db_path=db_path)
            events = list_orchestration_events("run-1", db_path=db_path)

            self.assertEqual(len(steps), 1)
            self.assertEqual(steps[0]["status"], "completed")
            self.assertEqual(steps[0]["result_summary"], "Project scaffold created.")
            self.assertTrue(any(event["event_type"] == "plan_task.started" for event in events))
            self.assertTrue(any(event["event_type"] == "plan_task.completed" for event in events))

    def test_next_ready_step_becomes_ready_after_dependency_completion(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "workflow.sqlite3")
            initialize_db(db_path)
            insert_run("run-2", "Build the project", "2026-04-15T00:00:00+00:00", "running", db_path=db_path)

            with (
                patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
                patch("kendr.mcp_manager.list_servers_safe", return_value=[]),
                patch("tasks.a2a_protocol.upsert_agent_card"),
                patch("tasks.a2a_protocol.insert_message"),
                patch("tasks.a2a_protocol.upsert_task"),
                patch("tasks.a2a_protocol.insert_artifact"),
            ):
                runtime = AgentRuntime(build_registry())
                state = runtime.build_initial_state("Build the project", run_id="run-2", db_path=db_path)

            plan_id = "run-2:plan:v1"
            upsert_execution_plan(
                plan_id,
                run_id="run-2",
                intent_id="intent-project",
                version=1,
                status="approved",
                approval_status="approved",
                objective="Build the project",
                summary="Initial plan",
                db_path=db_path,
            )
            replace_plan_tasks(
                plan_id,
                "run-2",
                [
                    {
                        "id": "step-1",
                        "title": "Scaffold project",
                        "agent": "worker_agent",
                        "task": "Scaffold the project.",
                        "success_criteria": "Project structure exists.",
                    },
                    {
                        "id": "step-2",
                        "title": "Run checks",
                        "agent": "worker_agent",
                        "task": "Run the project checks.",
                        "depends_on": ["step-1"],
                        "success_criteria": "Checks pass.",
                    },
                ],
                db_path=db_path,
            )

            state["orchestration_plan_id"] = plan_id
            state["orchestration_plan_version"] = 1
            state["plan_steps"] = [
                {
                    "id": "step-1",
                    "title": "Scaffold project",
                    "agent": "worker_agent",
                    "task": "Scaffold the project.",
                    "success_criteria": "Project structure exists.",
                },
                {
                    "id": "step-2",
                    "title": "Run checks",
                    "agent": "worker_agent",
                    "task": "Run the project checks.",
                    "depends_on": ["step-1"],
                    "success_criteria": "Checks pass.",
                },
            ]
            state["plan_step_index"] = 0
            state["plan_approval_status"] = "approved"

            runtime._mark_step_running(state, 0)
            runtime._mark_planned_step_complete(state, "Project scaffold created.")

            steps = list_plan_tasks(plan_id=plan_id, db_path=db_path)

            self.assertEqual(state["plan_step_index"], 1)
            self.assertEqual(steps[0]["status"], "completed")
            self.assertEqual(steps[1]["status"], "ready")

    def test_parallel_read_only_batch_executes_and_merges_outputs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "workflow.sqlite3")
            initialize_db(db_path)
            insert_run("run-parallel", "Inspect evidence", "2026-04-15T00:00:00+00:00", "running", db_path=db_path)

            with (
                patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
                patch("kendr.mcp_manager.list_servers_safe", return_value=[]),
                patch("tasks.a2a_protocol.upsert_agent_card"),
                patch("tasks.a2a_protocol.insert_message"),
                patch("tasks.a2a_protocol.upsert_task"),
                patch("tasks.a2a_protocol.insert_artifact"),
            ):
                runtime = AgentRuntime(self._custom_registry())
                state = runtime.build_initial_state("Inspect evidence", run_id="run-parallel", db_path=db_path)

            plan_id = "run-parallel:plan:v1"
            upsert_execution_plan(
                plan_id,
                run_id="run-parallel",
                version=1,
                status="approved",
                approval_status="approved",
                objective="Inspect evidence",
                summary="Parallel read-only plan",
                db_path=db_path,
            )
            replace_plan_tasks(
                plan_id,
                "run-parallel",
                [
                    {
                        "id": "step-1",
                        "title": "Catalog evidence",
                        "agent": "read_one_agent",
                        "task": "Catalog the local evidence.",
                        "success_criteria": "The catalog exists.",
                        "parallel_group": "read-batch",
                        "side_effect_level": "read_only",
                        "conflict_keys": ["agent:read_one_agent"],
                    },
                    {
                        "id": "step-2",
                        "title": "Summarize evidence",
                        "agent": "read_two_agent",
                        "task": "Summarize the gathered evidence.",
                        "success_criteria": "The summary exists.",
                        "parallel_group": "read-batch",
                        "side_effect_level": "read_only",
                        "conflict_keys": ["agent:read_two_agent"],
                    },
                ],
                db_path=db_path,
            )

            state["orchestration_plan_id"] = plan_id
            state["orchestration_plan_version"] = 1
            state["plan_approval_status"] = "approved"
            state["plan_ready"] = True
            state["parallel_read_only_enabled"] = True
            state["max_parallel_read_tasks"] = 3
            state["plan_steps"] = [
                {
                    "id": "step-1",
                    "title": "Catalog evidence",
                    "agent": "read_one_agent",
                    "task": "Catalog the local evidence.",
                    "success_criteria": "The catalog exists.",
                    "parallel_group": "read-batch",
                    "side_effect_level": "read_only",
                    "conflict_keys": ["agent:read_one_agent"],
                },
                {
                    "id": "step-2",
                    "title": "Summarize evidence",
                    "agent": "read_two_agent",
                    "task": "Summarize the gathered evidence.",
                    "success_criteria": "The summary exists.",
                    "parallel_group": "read-batch",
                    "side_effect_level": "read_only",
                    "conflict_keys": ["agent:read_two_agent"],
                },
            ]

            with (
                patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
                patch("kendr.mcp_manager.list_servers_safe", return_value=[]),
            ):
                routed_state = runtime.orchestrator_agent(state)
                routed_next_agent = routed_state["next_agent"]
                result = runtime._execute_parallel_plan_batch(routed_state)
            steps = list_plan_tasks(plan_id=plan_id, db_path=db_path)

            self.assertEqual(routed_next_agent, runtime._PARALLEL_PLAN_EXECUTOR)
            self.assertEqual(result["read_one_result"], "alpha")
            self.assertEqual(result["read_two_result"], "beta")
            self.assertEqual(result["effective_steps"], 2)
            self.assertEqual(steps[0]["status"], "completed")
            self.assertEqual(steps[1]["status"], "completed")
            self.assertEqual(result["parallel_step_results"]["step-1"]["status"], "completed")
            self.assertEqual(result["parallel_step_results"]["step-2"]["status"], "completed")

    def test_no_progress_watchdog_terminates_repeated_stall(self):
        with (
            patch("kendr.runtime.build_setup_snapshot", side_effect=self._fake_setup_snapshot),
            patch("kendr.mcp_manager.list_servers_safe", return_value=[]),
        ):
            runtime = AgentRuntime(self._custom_registry())
            state = runtime.build_initial_state("Inspect evidence")

        state["no_progress_watchdog_enabled"] = True
        state["max_no_progress_cycles"] = 2
        state["last_agent"] = "read_one_agent"
        state["last_agent_status"] = "success"
        state["review_pending"] = False
        state["plan_steps"] = []

        self.assertIsNone(runtime._handle_no_progress_watchdog(state, "Inspect evidence"))
        self.assertIsNone(runtime._handle_no_progress_watchdog(state, "Inspect evidence"))
        stalled = runtime._handle_no_progress_watchdog(state, "Inspect evidence")

        self.assertIsNotNone(stalled)
        self.assertEqual(stalled["next_agent"], "__finish__")
        self.assertIn("stalled", stalled["final_output"].lower())

    def test_run_query_writes_final_output_to_the_run_output_directory(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            run_output_dir = os.path.join(tmpdir, "run-output")
            stray_output_dir = os.path.join(tmpdir, "stray-output")
            os.makedirs(run_output_dir, exist_ok=True)
            os.makedirs(stray_output_dir, exist_ok=True)

            registry = Registry()
            registry.register_agent(
                AgentDefinition(
                    name="worker_agent",
                    handler=lambda state: state,
                    description="Minimal worker.",
                )
            )
            runtime = AgentRuntime(registry)

            class _FakeApp:
                def invoke(self, initial_state: dict) -> dict:
                    from tasks.utils import set_active_output_dir

                    set_active_output_dir(stray_output_dir, append=False)
                    result = dict(initial_state)
                    result["final_output"] = "Persisted final output."
                    return result

            with (
                patch("kendr.runtime.initialize_db"),
                patch("kendr.runtime.insert_run"),
                patch("kendr.runtime.update_run"),
                patch("kendr.runtime.get_channel_session", return_value=None),
                patch("kendr.runtime.write_text_file") as mock_write_text_file,
                patch("kendr.runtime.update_planning_file"),
                patch("kendr.runtime.close_session_memory"),
                patch("kendr.runtime.append_privileged_audit_event"),
                patch("kendr.runtime.append_daily_memory_note"),
                patch("kendr.runtime.append_long_term_memory"),
                patch("kendr.runtime.record_work_note"),
                patch.object(runtime, "build_workflow", return_value=_FakeApp()),
                patch.object(runtime, "save_graph"),
                patch.object(runtime, "_record_orchestration_event"),
                patch.object(runtime, "_sync_orchestration_plan_record", side_effect=lambda state, final_status="": state),
                patch.object(runtime, "_write_session_record"),
                patch.object(runtime, "_refresh_mcp_agents"),
                patch.object(runtime, "_refresh_skill_agents"),
            ):
                runtime.run_query(
                    "Summarize the findings.",
                    state_overrides={
                        "working_directory": tmpdir,
                        "run_output_dir": run_output_dir,
                        "available_agents": ["worker_agent"],
                    },
                )

            mock_write_text_file.assert_called_once_with(
                os.path.join(run_output_dir, "final_output.txt"),
                "Persisted final output.",
            )


if __name__ == "__main__":
    unittest.main()
