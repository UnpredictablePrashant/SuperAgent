import io
import json
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch


os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

from superagent.cli import main


class CliSmokeTests(unittest.TestCase):
    def test_main_without_command_prints_help(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main([])
        self.assertEqual(exit_code, 0)
        self.assertIn("usage: superagent", buffer.getvalue())

    def test_help_topic(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["help", "setup"])
        self.assertEqual(exit_code, 0)
        self.assertIn("usage: superagent setup", buffer.getvalue())

    def test_status_json(self):
        with (
            patch("superagent.cli._gateway_ready", return_value=True),
            patch("superagent.cli._listener_pids_for_port", return_value=[1234]),
            patch("superagent.cli._configured_working_dir", return_value="/tmp/work"),
            patch("superagent.cli._resolve_working_dir", return_value="/tmp/work"),
            patch(
                "superagent.cli.setup_overview",
                return_value={
                    "components": [
                        {"enabled": True, "filled_fields": 2, "total_fields": 2},
                        {"enabled": False, "filled_fields": 1, "total_fields": 2},
                    ]
                },
            ),
        ):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(["status", "--json"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertTrue(payload["gateway"]["running"])
        self.assertEqual(payload["gateway"]["listener_pids"], [1234])
        self.assertEqual(payload["setup"]["components_total"], 2)

    def test_agents_show_json(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["agents", "show", "recon_agent", "--json"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["name"], "recon_agent")

    def test_plugins_list_json(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["plugins", "list", "--json"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertIsInstance(payload, list)
        self.assertTrue(payload)

    def test_setup_components_json(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["setup", "components", "--json"])
        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertIn("components", payload)
        self.assertIsInstance(payload["components"], list)

    def test_workdir_set_and_clear(self):
        with (
            patch("superagent.cli.save_component_values") as save_values,
            patch("superagent.cli._resolve_working_dir", return_value="/tmp/superagent-workdir"),
        ):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(["workdir", "set", "rumki"])
            self.assertEqual(exit_code, 0)
            self.assertIn("Working directory set to", buffer.getvalue())
            save_values.assert_called_with("core_runtime", {"SUPERAGENT_WORKING_DIR": "/tmp/superagent-workdir"})

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(["workdir", "clear"])
            self.assertEqual(exit_code, 0)
            self.assertIn("Cleared SUPERAGENT_WORKING_DIR", buffer.getvalue())
            self.assertEqual(save_values.call_args_list[-1].args, ("core_runtime", {"SUPERAGENT_WORKING_DIR": ""}))

    def test_gateway_restart(self):
        with (
            patch("superagent.cli._terminate_gateway_on_port", return_value=1),
            patch("superagent.cli._start_gateway_process") as start_gateway,
        ):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(["gateway", "restart"])
            self.assertEqual(exit_code, 0)
            self.assertIn("Gateway restarted", buffer.getvalue())
            start_gateway.assert_called_once()

    def test_setup_oauth_no_browser_outputs_url(self):
        with (
            patch("superagent.cli._setup_ui_ready", return_value=True),
            patch("superagent.cli._oauth_missing_env", return_value=[]),
        ):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(["setup", "oauth", "google", "--no-browser"])
            self.assertEqual(exit_code, 0)
            self.assertIn("/oauth/google/start", buffer.getvalue())


if __name__ == "__main__":
    unittest.main()
