import io
import json
import os
import unittest
import argparse
from contextlib import redirect_stdout
from unittest.mock import Mock, patch


os.environ.setdefault("OPENAI_API_KEY", "test-openai-key")

import kendr.cli as cli
from kendr.cli import main


class CliSmokeTests(unittest.TestCase):
    @staticmethod
    def _resume_candidate(*, status: str = "failed", resumable: bool = True) -> dict:
        return {
            "run_id": "run_resume_test",
            "session_id": "session_resume_test",
            "status": status,
            "resume_status": status,
            "resumable": resumable,
            "branchable": True,
            "resume_strategy": "step_resume",
            "working_directory": "/tmp/work",
            "run_output_dir": "/tmp/work/runs/run_resume_test",
            "updated_at": "2026-03-26T00:00:00+00:00",
            "completed_at": "",
            "objective": "Resume the previous run",
            "user_query": "Resume the previous run",
            "active_agent": "worker_agent",
            "last_agent": "worker_agent",
            "last_error": "",
            "pending_user_input_kind": "",
            "pending_user_question": "",
            "approval_pending_scope": "",
            "plan_step_index": 1,
            "plan_step_count": 3,
            "current_plan_step_id": "step-2",
            "current_plan_step_title": "Draft the report",
            "last_completed_plan_step_id": "step-1",
            "last_completed_plan_step_title": "Catalog the files",
            "failure_checkpoint": {"can_resume": True, "step_index": 1, "task_content": "Draft the report"},
            "channel_session_key": "cli_user:default:cli_user:cli_user:direct",
            "parent_run_id": "",
            "checkpoint": {
                "summary": {
                    "run_id": "run_resume_test",
                    "status": status,
                },
                "state_snapshot": {
                    "run_id": "run_resume_test",
                    "session_id": "session_resume_test",
                    "working_directory": "/tmp/work",
                    "plan_steps": [{"id": "step-2", "agent": "worker_agent", "task": "Draft the report"}],
                    "plan_step_index": 0,
                },
            },
        }

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
        self.assertIn("\r", output)
        self.assertIn("[run]\n", output)
        self.assertIn("|- status: running", output)
        self.assertIn("|- agent: worker_agent", output)
        self.assertIn("`- step: 1", output)

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

        rendered = cli._ANSI_ESCAPE_RE.sub("", stderr.getvalue())
        self.assertIn("\r[run] |- waiting: 17s elapsed", rendered)
        self.assertIn("still chewing through the task", rendered)

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

        self.assertIn("[run]\n", message)
        self.assertIn("|- agent: local_drive_agent", message)
        self.assertIn("|- step: 2", message)
        self.assertIn("`- task: Scan local-drive documents and extract the funding signals", message)

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

        self.assertIn("|- awaiting: plan_approval @ root_plan", message)

    def test_run_progress_message_includes_plan_overview(self):
        message = cli._build_run_progress_message(
            {
                "status": "running",
                "active_agent": "planner_agent",
                "step_count": 3,
                "summary_json": json.dumps(
                    {
                        "active_task": "Execute the next planned step with local_drive_agent.",
                        "plan_steps": [
                            {"id": "step-1", "title": "Ingest local files", "agent": "local_drive_agent"},
                            {"id": "step-2", "title": "Analyze financials", "agent": "financial_mis_analysis_agent"},
                            {"id": "step-3", "title": "Draft report", "agent": "report_agent"},
                        ],
                        "plan_step_index": 1,
                        "plan_step_total": 3,
                    }
                ),
            }
        )

        self.assertIn("|- major: 2/3", message)
        self.assertIn("|- current: Analyze financials", message)
        self.assertIn("|- done: Ingest local files", message)
        self.assertIn("|- remaining: Draft report", message)

    def test_main_without_command_prints_help(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main([])
        self.assertEqual(exit_code, 0)
        self.assertIn("usage: kendr", buffer.getvalue())

    def test_help_topic(self):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            exit_code = main(["help", "setup"])
        self.assertEqual(exit_code, 0)
        self.assertIn("usage: kendr setup", buffer.getvalue())

    def test_status_json(self):
        with (
            patch("kendr.cli._gateway_ready", return_value=True),
            patch("kendr.cli._listener_pids_for_port", return_value=[1234]),
            patch("kendr.cli._configured_working_dir", return_value="/tmp/work"),
            patch("kendr.cli._resolve_working_dir", return_value="/tmp/work"),
            patch(
                "kendr.cli.setup_overview",
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
            patch("kendr.cli.save_component_values") as save_values,
            patch("kendr.cli._resolve_working_dir", return_value="/tmp/kendr-workdir"),
        ):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(["workdir", "set", "rumki"])
            self.assertEqual(exit_code, 0)
            self.assertIn("Working directory set to", buffer.getvalue())
            save_values.assert_called_with("core_runtime", {"KENDR_WORKING_DIR": "/tmp/kendr-workdir"})

            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(["workdir", "clear"])
            self.assertEqual(exit_code, 0)
            self.assertIn("Cleared KENDR_WORKING_DIR", buffer.getvalue())
            self.assertEqual(save_values.call_args_list[-1].args, ("core_runtime", {"KENDR_WORKING_DIR": ""}))

    def test_gateway_restart(self):
        with (
            patch("kendr.cli._terminate_gateway_on_port", return_value=1),
            patch("kendr.cli._start_gateway_process") as start_gateway,
        ):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(["gateway", "restart"])
            self.assertEqual(exit_code, 0)
            self.assertIn("Gateway restarted", buffer.getvalue())
            start_gateway.assert_called_once()

    def test_start_gateway_process_cleans_stale_listener_before_launch(self):
        fake_process = Mock()
        fake_process.poll.return_value = None
        with (
            patch("kendr.cli._gateway_ready", side_effect=[False, False, True, True]),
            patch("kendr.cli._listener_pids_for_port", side_effect=[[4321], []]),
            patch("kendr.cli._terminate_gateway_on_port", return_value=1) as terminate_gateway,
            patch("kendr.cli._wait_for_listener_shutdown", return_value=True) as wait_shutdown,
            patch("kendr.cli.subprocess.Popen", return_value=fake_process) as popen,
        ):
            cli._start_gateway_process()

        terminate_gateway.assert_called_once()
        wait_shutdown.assert_called_once()
        popen.assert_called_once()

    def test_start_gateway_process_failure_points_to_background_start_and_log(self):
        fake_process = Mock()
        fake_process.poll.return_value = 3
        with (
            patch("kendr.cli._gateway_ready", return_value=False),
            patch("kendr.cli._listener_pids_for_port", return_value=[]),
            patch("kendr.cli.subprocess.Popen", return_value=fake_process),
        ):
            with self.assertRaises(SystemExit) as exc:
                cli._start_gateway_process()

        message = str(exc.exception)
        self.assertIn("kendr gateway start", message)
        self.assertIn("gateway.log", message)

    def test_run_superrag_chat_requires_session(self):
        with (
            patch("kendr.cli._configured_working_dir", return_value="/tmp/work"),
            patch("kendr.cli._resolve_working_dir", return_value="/tmp/work"),
            patch(
                "kendr.cli._workflow_setup_snapshot",
                return_value={"available_agents": ["superrag_agent"], "agents": {"superrag_agent": {"missing_services": []}}},
            ),
        ):
            with self.assertRaises(SystemExit) as exc:
                main(["run", "--superrag-mode", "chat", "What are the top risks?"])

        self.assertIn("--superrag-session", str(exc.exception))

    def test_run_os_command_requires_explicit_privileged_approval(self):
        with (
            patch("kendr.cli._configured_working_dir", return_value="/tmp/work"),
            patch("kendr.cli._resolve_working_dir", return_value="/tmp/work"),
        ):
            with self.assertRaises(SystemExit) as exc:
                main(["run", "--os-command", "Get-Location", "Show the working directory"])

        self.assertIn("--privileged-approved", str(exc.exception))

    def test_setup_oauth_no_browser_outputs_url(self):
        with (
            patch("kendr.cli._setup_ui_ready", return_value=True),
            patch("kendr.cli._oauth_missing_env", return_value=[]),
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
            patch("kendr.cli._gateway_ready", return_value=True),
            patch("kendr.cli._configured_working_dir", return_value="/tmp/work"),
            patch("kendr.cli._resolve_working_dir", return_value="/tmp/work"),
            patch("kendr.cli._http_json_get", return_value=[]),
            patch("kendr.cli._validate_run_workflows", return_value={}),
            patch("kendr.cli.urllib.request.urlopen", side_effect=_fake_urlopen),
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

    def test_run_forwards_coding_and_research_controls(self):
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
            return _FakeResponse(json.dumps({"run_id": "run_code", "final_output": "ok", "last_agent": "coding_agent"}))

        with (
            patch("kendr.cli._gateway_ready", return_value=True),
            patch("kendr.cli._configured_working_dir", return_value="/tmp/work"),
            patch("kendr.cli._resolve_working_dir", return_value="/tmp/work"),
            patch("kendr.cli._http_json_get", return_value=[]),
            patch(
                "kendr.cli._workflow_setup_snapshot",
                return_value={"available_agents": ["coding_agent", "master_coding_agent", "deep_research_agent"], "agents": {}},
            ),
            patch("kendr.cli.urllib.request.urlopen", side_effect=_fake_urlopen),
        ):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(
                    [
                        "run",
                        "--json",
                        "--quiet",
                        "--coding-context-file",
                        "README.md",
                        "--coding-write-path",
                        "app/main.py",
                        "--coding-instructions",
                        "Prefer FastAPI.",
                        "--coding-language",
                        "python",
                        "--research-model",
                        "o4-mini-deep-research",
                        "--research-instructions",
                        "Cite concrete sources.",
                        "Build a production-ready API starter.",
                    ]
                )

        self.assertEqual(exit_code, 0)
        payload = captured["payload"]
        self.assertEqual(payload.get("coding_context_files"), ["README.md"])
        self.assertEqual(payload.get("coding_write_path"), "app/main.py")
        self.assertEqual(payload.get("coding_instructions"), "Prefer FastAPI.")
        self.assertEqual(payload.get("coding_language"), "python")
        self.assertEqual(payload.get("research_model"), "o4-mini-deep-research")
        self.assertEqual(payload.get("research_instructions"), "Cite concrete sources.")

    def test_run_interactive_follow_up_resubmits_paused_session(self):
        captured_payloads = []

        class _FakeResponse:
            def __init__(self, body: str):
                self._body = body.encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return self._body

        responses = iter(
            [
                {
                    "run_id": "run_test_first",
                    "final_output": "Please confirm the reporting period.",
                    "last_agent": "planner_agent",
                    "status": "awaiting_user_input",
                    "awaiting_user_input": True,
                    "pending_user_input_kind": "clarification",
                    "pending_user_question": "Please confirm the reporting period.",
                },
                {
                    "run_id": "run_test_second",
                    "final_output": "analysis complete",
                    "last_agent": "long_document_agent",
                    "status": "completed",
                    "awaiting_user_input": False,
                },
            ]
        )

        def _fake_urlopen(request, timeout=0):  # noqa: ARG001
            body = request.data.decode("utf-8") if getattr(request, "data", None) else "{}"
            captured_payloads.append(json.loads(body))
            return _FakeResponse(json.dumps(next(responses)))

        class _FakeStdin(io.StringIO):
            def isatty(self):
                return True

        with (
            patch("kendr.cli._gateway_ready", return_value=True),
            patch("kendr.cli._configured_working_dir", return_value="/tmp/work"),
            patch("kendr.cli._resolve_working_dir", return_value="/tmp/work"),
            patch("kendr.cli._http_json_get", return_value=[]),
            patch("kendr.cli._load_cli_session", return_value={}),
            patch("kendr.cli._save_cli_session"),
            patch("kendr.cli.urllib.request.urlopen", side_effect=_fake_urlopen),
            patch("builtins.input", side_effect=["Last 3 fiscal years plus TTM"]),
            patch.object(cli.sys, "stdin", _FakeStdin()),
        ):
            buffer = io.StringIO()
            with redirect_stdout(buffer):
                exit_code = main(
                    [
                        "run",
                        "--quiet",
                        "Prepare the investment memo",
                    ]
                )

        self.assertEqual(exit_code, 0)
        self.assertEqual(len(captured_payloads), 2)
        self.assertEqual(captured_payloads[0]["text"], "Prepare the investment memo")
        self.assertEqual(captured_payloads[1]["text"], "Last 3 fiscal years plus TTM")
        self.assertEqual(captured_payloads[0]["channel"], captured_payloads[1]["channel"])
        self.assertEqual(captured_payloads[0]["workspace_id"], captured_payloads[1]["workspace_id"])
        self.assertEqual(captured_payloads[0]["chat_id"], captured_payloads[1]["chat_id"])
        output = buffer.getvalue()
        self.assertIn("Please confirm the reporting period.", output)
        self.assertIn("analysis complete", output)

    def test_resume_inspect_json_outputs_single_candidate_document(self):
        candidate = self._resume_candidate()
        buffer = io.StringIO()
        with (
            patch("kendr.cli.discover_resume_candidates", return_value=[candidate]),
            redirect_stdout(buffer),
        ):
            exit_code = main(["resume", "--inspect", "--json", "/tmp/work"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["run_id"], "run_resume_test")
        self.assertEqual(payload["resume_status"], "failed")

    def test_resume_json_outputs_final_result_only(self):
        candidate = self._resume_candidate()
        result = {
            "status": "completed",
            "run_id": "run_resume_test",
            "final_output": "done",
            "last_agent": "worker_agent",
        }

        class _FakeRuntime:
            def __init__(self, registry):  # noqa: ARG002
                pass

            def run_query(self, current_query, *, state_overrides=None, create_outputs=True):  # noqa: ARG002
                self.current_query = current_query
                return result

        buffer = io.StringIO()
        with (
            patch("kendr.cli.discover_resume_candidates", return_value=[candidate]),
            patch("kendr.AgentRuntime", _FakeRuntime),
            redirect_stdout(buffer),
        ):
            exit_code = main(["resume", "--json", "/tmp/work"])

        self.assertEqual(exit_code, 0)
        payload = json.loads(buffer.getvalue())
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["final_output"], "done")

    def test_resume_stale_run_requires_force_when_not_interactive(self):
        candidate = self._resume_candidate(status="running_stale", resumable=True)

        class _FakeStdin(io.StringIO):
            def isatty(self):
                return False

        buffer = io.StringIO()
        with (
            patch("kendr.cli.discover_resume_candidates", return_value=[candidate]),
            patch.object(cli.sys, "stdin", _FakeStdin()),
            redirect_stdout(buffer),
        ):
            with self.assertRaises(SystemExit) as exc:
                main(["resume", "/tmp/work"])

        self.assertEqual(str(exc.exception), "This run looks stale. Re-run with --force to take it over.")


if __name__ == "__main__":
    unittest.main()
