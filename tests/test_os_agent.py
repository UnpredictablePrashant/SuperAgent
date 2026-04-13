import os
import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch


os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from tasks.os_tasks import os_agent


class OsAgentTests(unittest.TestCase):
    def test_policy_blocked_command_still_publishes_execution_report(self):
        with TemporaryDirectory() as tmp:
            state = {
                "user_query": "Run a local command.",
                "os_command": "rm -rf temp-output",
                "working_directory": tmp,
            }

            with (
                patch("tasks.os_tasks.begin_agent_session", return_value=(None, state["user_query"], "orchestrator_agent")),
                patch("tasks.os_tasks.publish_agent_output", side_effect=lambda current_state, *_args, **_kwargs: current_state),
                patch("tasks.os_tasks.write_text_file"),
                patch("tasks.os_tasks.log_task_update"),
                patch("tasks.os_tasks.append_privileged_audit_event"),
            ):
                result = os_agent(state)

        self.assertFalse(result["os_success"])
        self.assertIsNone(result["os_return_code"])
        self.assertIn("policy_blocked", result["draft_response"])
        self.assertIn("Thought:", result["draft_response"])
        self.assertIn("Mutating:", result["draft_response"])

    def test_updates_software_inventory_and_command_history_after_execution(self):
        with TemporaryDirectory() as tmp:
            state = {
                "user_query": "Check if VS Code is installed.",
                "os_command": "echo installed:/usr/bin/code",
                "working_directory": tmp,
                "os_working_directory": tmp,
                "privileged_approved": True,
                "privileged_approval_note": "test approval",
            }

            with (
                patch("tasks.os_tasks.begin_agent_session", return_value=(None, state["user_query"], "orchestrator_agent")),
                patch("tasks.os_tasks.publish_agent_output", side_effect=lambda current_state, *_args, **_kwargs: current_state),
                patch("tasks.os_tasks.write_text_file"),
                patch("tasks.os_tasks.log_task_update"),
                patch("tasks.os_tasks.append_privileged_audit_event"),
                patch("tasks.os_tasks._resolve_shell", return_value=("/bin/sh", ["-lc"], "sh")),
                patch("tasks.os_tasks.subprocess.run") as mock_run,
            ):
                mock_run.return_value = type(
                    "Completed",
                    (),
                    {"returncode": 0, "stdout": "installed:/usr/bin/code\n", "stderr": ""},
                )()
                result = os_agent(state)

            self.assertIn("last_shell_command", result)
            self.assertTrue(result["recent_shell_commands"])
            self.assertIn("vscode", result.get("software_inventory", {}))
            inventory_file = Path(tmp) / ".kendr" / "software_inventory.json"
            self.assertTrue(inventory_file.is_file())
            payload = json.loads(inventory_file.read_text(encoding="utf-8"))
            self.assertTrue(payload["software"]["vscode"]["installed"])

    def test_machine_sync_internal_command_runs_without_shell(self):
        with TemporaryDirectory() as tmp:
            state = {
                "user_query": "sync my machine",
                "os_command": "__KENDR_SYNC_MACHINE__",
                "machine_sync_scope": "machine",
                "working_directory": tmp,
                "os_working_directory": tmp,
            }

            with (
                patch("tasks.os_tasks.begin_agent_session", return_value=(None, state["user_query"], "orchestrator_agent")),
                patch("tasks.os_tasks.publish_agent_output", side_effect=lambda current_state, *_args, **_kwargs: current_state),
                patch("tasks.os_tasks.write_text_file"),
                patch("tasks.os_tasks.log_task_update"),
                patch("tasks.os_tasks.run_software_inventory_sync", return_value={"software_inventory_last_synced": "now", "software": {}, "installed_count": 0}),
                patch("tasks.os_tasks.run_file_index_sync", return_value={"file_index_last_synced": "now", "scanned_files": 1, "created": 1, "modified": 0, "deleted": 0, "errors": 0}),
                patch("tasks.os_tasks.machine_sync_status", return_value={"indexed_files": 1, "recent_changes_24h": 1}),
                patch("tasks.os_tasks._resolve_shell") as resolve_shell,
            ):
                result = os_agent(state)

            resolve_shell.assert_not_called()
            self.assertTrue(result["os_success"])
            self.assertEqual(result["os_return_code"], 0)
            self.assertIn("Machine sync complete", result["draft_response"])

    def test_scope_block_retries_non_mutating_command_in_allowed_path(self):
        with TemporaryDirectory() as tmp:
            blocked = str(Path(tmp) / "blocked")
            os.makedirs(blocked, exist_ok=True)
            state = {
                "user_query": "check vscode",
                "os_command": "which code || true",
                "os_working_directory": blocked,
                "working_directory": tmp,
                "privileged_approved": True,
                "privileged_approval_note": "ok",
            }

            calls = []

            def _ensure(cmd, wd, policy):
                calls.append(wd)
                if wd == os.path.abspath(blocked):
                    raise PermissionError("Working directory is outside the allowed path scope.")
                return None

            with (
                patch("tasks.os_tasks.begin_agent_session", return_value=(None, state["user_query"], "orchestrator_agent")),
                patch("tasks.os_tasks.publish_agent_output", side_effect=lambda current_state, *_args, **_kwargs: current_state),
                patch("tasks.os_tasks.write_text_file"),
                patch("tasks.os_tasks.log_task_update"),
                patch("tasks.os_tasks.append_privileged_audit_event"),
                patch("tasks.os_tasks._resolve_shell", return_value=("/bin/sh", ["-lc"], "sh")),
                patch("tasks.os_tasks.ensure_command_allowed", side_effect=_ensure),
                patch("tasks.os_tasks.subprocess.run") as mock_run,
            ):
                mock_run.return_value = type(
                    "Completed",
                    (),
                    {"returncode": 0, "stdout": "/usr/bin/code\n", "stderr": ""},
                )()
                result = os_agent(state)

            self.assertTrue(result["os_success"])
            self.assertNotIn("deterministic_failure", result)
            self.assertGreaterEqual(len(calls), 2)

    def test_scope_block_sets_deterministic_failure_when_no_safe_fallback(self):
        with TemporaryDirectory() as tmp:
            state = {
                "user_query": "check vscode",
                "os_command": "echo ok",
                "os_working_directory": str(Path(tmp) / "blocked"),
                "working_directory": "",
                "privileged_approved": True,
                "privileged_approval_note": "ok",
            }

            with (
                patch("tasks.os_tasks.begin_agent_session", return_value=(None, state["user_query"], "orchestrator_agent")),
                patch("tasks.os_tasks.publish_agent_output", side_effect=lambda current_state, *_args, **_kwargs: current_state),
                patch("tasks.os_tasks.write_text_file"),
                patch("tasks.os_tasks.log_task_update"),
                patch("tasks.os_tasks.append_privileged_audit_event"),
                patch("tasks.os_tasks.ensure_command_allowed", side_effect=PermissionError("Working directory is outside the allowed path scope.")),
            ):
                result = os_agent(state)

            self.assertFalse(result["os_success"])
            self.assertIn("deterministic_failure", result)
            self.assertEqual(result["deterministic_failure"].get("kind"), "policy_blocked_outside_scope")


if __name__ == "__main__":
    unittest.main()
