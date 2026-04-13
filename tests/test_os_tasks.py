import unittest
from unittest.mock import patch

from tasks.os_tasks import _plan_shell_steps, shell_plan_agent


class ShellPlanAgentTests(unittest.TestCase):
    def test_plan_shell_steps_repairs_powershell_incompatible_syntax(self):
        bad_plan = "\n".join([
            "STEP 1",
            "Description: Check docker",
            "Command: `which docker || echo missing`",
            "Optional: no",
            "Check: /dev/null",
        ])
        fixed_plan = "\n".join([
            "STEP 1",
            "Description: Check docker",
            "Command: if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { Write-Output 'missing' }",
            "Optional: no",
            "Check: ",
        ])

        with patch("tasks.os_tasks.llm.invoke", side_effect=[type("R", (), {"content": bad_plan})(), type("R", (), {"content": fixed_plan})()]):
            steps = _plan_shell_steps("check docker", "windows", shell_name="powershell", known_tools="")

        self.assertEqual(len(steps), 1)
        self.assertIn("Get-Command docker", steps[0]["command"])
        self.assertNotIn("which docker", steps[0]["command"])

    def test_shell_plan_pause_exposes_full_checklist(self):
        state = {
            "user_query": "Start docker and run nginx",
            "current_objective": "Start docker and run nginx",
            "working_directory": "/tmp",
        }

        with (
            patch("tasks.os_tasks.begin_agent_session", return_value=(None, state["user_query"], None)),
            patch("tasks.os_tasks.publish_agent_output", side_effect=lambda current_state, *args, **kwargs: current_state),
            patch("tasks.os_tasks.log_task_update"),
            patch("tasks.os_tasks.build_privileged_policy", return_value={}),
            patch("tasks.os_tasks._resolve_shell", return_value=("/bin/bash", ["-lc"], "bash")),
            patch(
                "tasks.os_tasks._plan_shell_steps",
                return_value=[
                    {"description": "Start Docker Engine", "command": "start-docker"},
                    {"description": "Pull nginx", "command": "docker pull nginx:latest"},
                    {"description": "Run nginx", "command": "docker run -p 9090:80 nginx:latest"},
                ],
            ),
            patch(
                "tasks.os_tasks.ensure_command_allowed",
                side_effect=[
                    None,
                    PermissionError("approval_required: networking command needs approval"),
                ],
            ),
            patch("tasks.os_tasks._run_step", return_value=(0, "docker started", "")),
            patch("tasks.os_tasks.update_inventory_from_command_result", return_value={}),
            patch("tasks.os_tasks.append_privileged_audit_event"),
        ):
            result = shell_plan_agent(state)

        self.assertFalse(result["shell_plan_success"])
        self.assertEqual(len(result["shell_plan_steps"]), 3)
        self.assertEqual(result["shell_plan_steps"][0]["status"], "completed")
        self.assertTrue(result["shell_plan_steps"][0]["done"])
        self.assertEqual(result["shell_plan_steps"][1]["status"], "awaiting_approval")
        self.assertIn("Waiting for approval", result["shell_plan_steps"][1]["detail"])
        self.assertEqual(result["shell_plan_steps"][2]["status"], "pending")
        self.assertFalse(result["shell_plan_steps"][2]["done"])


if __name__ == "__main__":
    unittest.main()
