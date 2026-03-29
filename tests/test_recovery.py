import json
import os
import unittest
from datetime import UTC, datetime, timedelta
from tempfile import TemporaryDirectory
from unittest.mock import patch

os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from kendr.discovery import build_registry
from kendr.recovery import (
    RUN_MANIFEST_FILE,
    discover_resume_candidates,
    load_resume_candidate,
    write_recovery_files,
)
from kendr.runtime import AgentRuntime


class RecoveryWorkflowTests(unittest.TestCase):
    @staticmethod
    def _fake_setup_snapshot() -> dict:
        registry = build_registry()
        return {
            "available_agents": [str(card.get("agent_name", "")) for card in registry.agent_cards()],
            "disabled_agents": {},
            "setup_actions": [],
            "summary_text": "",
        }

    def test_write_and_load_recovery_candidate_from_run_folder(self):
        with TemporaryDirectory() as tmp:
            state = {
                "run_id": "run_test_1",
                "session_id": "session_test_1",
                "run_output_dir": tmp,
                "working_directory": tmp,
                "user_query": "Create a report.",
                "current_objective": "Create a report.",
                "pending_user_input_kind": "plan_approval",
                "pending_user_question": "Reply approve to continue.",
                "approval_pending_scope": "root_plan",
                "plan_waiting_for_approval": True,
                "plan_approval_status": "pending",
                "plan_steps": [{"id": "step-1", "agent": "worker_agent", "task": "Do work"}],
            }

            write_recovery_files(state, status="awaiting_user_input")
            candidate = load_resume_candidate(tmp)

        self.assertEqual(candidate["run_id"], "run_test_1")
        self.assertEqual(candidate["resume_status"], "awaiting_user_input")
        self.assertTrue(candidate["resumable"])
        self.assertIn("approve", candidate["pending_user_question"].lower())

    def test_discovery_marks_running_candidate_as_stale_when_heartbeat_is_old(self):
        with TemporaryDirectory() as tmp:
            run_dir = os.path.join(tmp, "runs", "run_test_stale")
            os.makedirs(run_dir, exist_ok=True)
            state = {
                "run_id": "run_test_stale",
                "session_id": "session_test_stale",
                "run_output_dir": run_dir,
                "working_directory": tmp,
                "user_query": "Continue research.",
                "current_objective": "Continue research.",
            }
            write_recovery_files(state, status="running")

            manifest_path = os.path.join(run_dir, RUN_MANIFEST_FILE)
            with open(manifest_path, encoding="utf-8") as handle:
                manifest = json.loads(handle.read())
            manifest["summary"]["updated_at"] = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
            with open(manifest_path, "w", encoding="utf-8") as handle:
                json.dump(manifest, handle, indent=2, ensure_ascii=False)

            candidates = discover_resume_candidates(tmp, stale_after_seconds=60)

        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["resume_status"], "running_stale")
        self.assertTrue(candidates[0]["resumable"])
        self.assertTrue(candidates[0]["requires_takeover"])

    def test_runtime_restores_failed_checkpoint_for_resume(self):
        checkpoint = {
            "summary": {
                "run_id": "run_resume_failed",
                "status": "failed",
            },
            "state_snapshot": {
                "run_id": "run_resume_failed",
                "session_id": "session_resume_failed",
                "user_query": "Build the report.",
                "current_objective": "Build the report.",
                "plan_steps": [
                    {"id": "step-1", "agent": "worker_agent", "task": "Catalog the files."},
                    {"id": "step-2", "agent": "worker_agent", "task": "Write the report."},
                ],
                "plan_step_index": 1,
                "plan_approval_status": "approved",
                "failure_checkpoint": {
                    "can_resume": True,
                    "step_index": 1,
                    "task_content": "Write the report.",
                },
            },
        }
        with TemporaryDirectory() as tmp:
            with patch("kendr.runtime.build_setup_snapshot", return_value=self._fake_setup_snapshot()):
                runtime = AgentRuntime(build_registry())
                state = runtime.build_initial_state(
                    "resume",
                    working_directory=tmp,
                    resume_checkpoint_payload=checkpoint,
                    run_output_dir=tmp,
                )

        self.assertTrue(state["resume_requested"])
        self.assertTrue(state["resume_ready"])
        self.assertEqual(state["plan_step_index"], 1)
        self.assertEqual(state["current_objective"], "Write the report.")

    def test_runtime_restores_paused_checkpoint_and_applies_reply(self):
        checkpoint = {
            "summary": {
                "run_id": "run_resume_paused",
                "status": "awaiting_user_input",
                "awaiting_user_input": True,
            },
            "state_snapshot": {
                "run_id": "run_resume_paused",
                "session_id": "session_resume_paused",
                "user_query": "Build the report.",
                "current_objective": "Build the report.",
                "plan_steps": [{"id": "step-1", "agent": "worker_agent", "task": "Do work"}],
                "pending_user_input_kind": "plan_approval",
                "approval_pending_scope": "root_plan",
                "pending_user_question": "Reply approve to continue.",
                "plan_waiting_for_approval": True,
                "plan_approval_status": "pending",
            },
        }
        with TemporaryDirectory() as tmp:
            with patch("kendr.runtime.build_setup_snapshot", return_value=self._fake_setup_snapshot()):
                runtime = AgentRuntime(build_registry())
                state = runtime.build_initial_state(
                    "approve",
                    working_directory=tmp,
                    resume_checkpoint_payload=checkpoint,
                    run_output_dir=tmp,
                )

        self.assertFalse(state["plan_waiting_for_approval"])
        self.assertEqual(state["plan_approval_status"], "approved")
        self.assertTrue(state["plan_ready"])


if __name__ == "__main__":
    unittest.main()
