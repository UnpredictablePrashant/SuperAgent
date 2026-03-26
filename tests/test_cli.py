import io
import json
import os
import unittest
import argparse
from contextlib import redirect_stdout
from unittest.mock import patch


os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

import superagent.cli as cli
from superagent.cli import main


class CliSmokeTests(unittest.TestCase):
    def test_style_status_message_colors_warning_and_error_levels(self):
        class _FakeStdout(io.StringIO):
            def isatty(self):
                return True

        args = argparse.Namespace(quiet=False, no_color=False)
        stdout = _FakeStdout()
        with (
            patch.object(cli.sys, "stdout", stdout),
            patch.dict(cli.os.environ, {"NO_COLOR": ""}, clear=False),
        ):
            warning = cli._style_status_message(args, "[gateway] not running at http://127.0.0.1:8790; starting gateway...")
            failure = cli._style_status_message(args, "Gateway ingest failed: connection refused")

        self.assertIn("\x1b[1;33m", warning)
        self.assertIn("\x1b[1;31m", failure)

    def test_style_status_message_respects_no_color(self):
        class _FakeStdout(io.StringIO):
            def isatty(self):
                return True

        args = argparse.Namespace(quiet=False, no_color=True)
        stdout = _FakeStdout()
        with (
            patch.object(cli.sys, "stdout", stdout),
            patch.dict(cli.os.environ, {"NO_COLOR": ""}, clear=False),
        ):
            message = cli._style_status_message(args, "[run] completed run_id=test last_agent=worker_agent")

        self.assertNotIn("\x1b[", message)

    def test_emit_status_transient_updates_single_line_when_tty(self):
        class _FakeStderr(io.StringIO):
            def isatty(self):
                return True

        args = argparse.Namespace(quiet=False)
        stderr = _FakeStderr()
        with patch.object(cli.sys, "stderr", stderr):
            cli._clear_transient_status_line()
            try:
                cli._emit_status(args, "[run] waiting for completion... 1s elapsed", transient=True)
                cli._emit_status(args, "[run] waiting for completion... 9s elapsed", transient=True)
                cli._emit_status(args, "[run] status=running active_agent=worker_agent steps=1")
            finally:
                cli._clear_transient_status_line()

        output = stderr.getvalue()
        self.assertEqual(output.count("\n"), 1)
        self.assertIn("\r", output)
        self.assertIn("[run] status=running active_agent=worker_agent steps=1", output)

    def test_emit_status_transient_uses_stdout_tty_fallback(self):
        class _FakeStderr(io.StringIO):
            def isatty(self):
                return False

            def fileno(self):
                raise OSError("no fileno")

        class _FakeStdout(io.StringIO):
            def isatty(self):
                return True

        args = argparse.Namespace(quiet=False)
        stderr = _FakeStderr()
        stdout = _FakeStdout()
        with (
            patch.object(cli.sys, "stderr", stderr),
            patch.object(cli.sys, "stdout", stdout),
        ):
            cli._clear_transient_status_line()
            try:
                cli._emit_status(args, "[run] waiting for completion... 17s elapsed", transient=True)
            finally:
                cli._clear_transient_status_line()

        self.assertIn("\r[run] waiting for completion... 17s elapsed", stderr.getvalue())

    def test_run_progress_message_includes_active_task_summary(self):
        message = cli._build_run_progress_message(
            {
                "status": "running",
                "active_agent": "local_drive_agent",
                "step_count": 2,
                "summary_json": json.dumps(
                    {
                        "active_task": "Scan local-drive documents and extract the funding signals most relevant to the report.",
                    }
                ),
            }
        )

        self.assertIn("active_agent=local_drive_agent", message)
        self.assertIn("steps=2", message)
        self.assertIn("task=Scan local-drive documents and extract the funding signals", message)

    def test_run_progress_message_surfaces_pending_approval(self):
        message = cli._build_run_progress_message(
            {
                "status": "awaiting_user_input",
                "active_agent": "planner_agent",
                "step_count": 1,
                "summary_json": json.dumps(
                    {
                        "awaiting_user_input": True,
                        "pending_user_input_kind": "plan_approval",
                        "approval_pending_scope": "root_plan",
                        "active_task": "Reply approve to continue.",
                    }
                ),
            }
        )

        self.assertIn("awaiting=plan_approval", message)
        self.assertIn("scope=root_plan", message)

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

    def test_run_drive_sets_local_drive_payload_and_infers_long_document(self):
        captured = {"payload": {}}

        class _FakeResponse:
            def __init__(self, body: str):
                self._body = body.encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self._body

        def _fake_urlopen(request, timeout=0):  # noqa: ARG001
            body = request.data.decode("utf-8") if getattr(request, "data", None) else "{}"
            captured["payload"] = json.loads(body)
            return _FakeResponse(json.dumps({"run_id": "run_test", "final_output": "ok", "last_agent": "local_drive_agent"}))

        with (
            patch("superagent.cli._gateway_ready", return_value=True),
            patch("superagent.cli._configured_working_dir", return_value="/tmp/work"),
            patch("superagent.cli._resolve_working_dir", return_value="/tmp/work"),
            patch("superagent.cli._http_json_get", return_value=[]),
            patch("superagent.cli.urllib.request.urlopen", side_effect=_fake_urlopen),
        ):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(
                    [
                        "run",
                        "--drive=D:/xyz/folder",
                        "--json",
                        "--quiet",
                        "Do a deep analysis and create a 50 pages report",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = captured["payload"]
        self.assertEqual(payload.get("local_drive_paths"), ["D:/xyz/folder"])
        self.assertTrue(payload.get("local_drive_force_long_document"))
        self.assertTrue(payload.get("long_document_mode"))
        self.assertEqual(payload.get("long_document_pages"), 50)


if __name__ == "__main__":
    unittest.main()
