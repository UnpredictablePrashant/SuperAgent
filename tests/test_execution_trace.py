from __future__ import annotations

import unittest

from kendr.execution_trace import append_execution_event, render_execution_event_line


class TestExecutionTrace(unittest.TestCase):
    def test_append_execution_event_adds_duration_label(self):
        state: dict = {}

        event = append_execution_event(
            state,
            kind="command",
            actor="os_agent",
            status="completed",
            title="Shell command completed",
            command="pytest -q",
            started_at="2026-04-03T10:00:00+00:00",
            completed_at="2026-04-03T10:00:02.500000+00:00",
        )

        self.assertEqual(event["duration_ms"], 2500)
        self.assertEqual(event["duration_label"], "2.5s")
        self.assertEqual(len(state["execution_trace"]), 1)

    def test_render_execution_event_line_includes_command_and_exit_code(self):
        line = render_execution_event_line(
            {
                "timestamp": "2026-04-03T10:00:04+00:00",
                "actor": "os_agent",
                "title": "Shell command completed",
                "command": "nmap -Pn herovired.com",
                "duration_label": "4.0s",
                "exit_code": 0,
            }
        )

        self.assertIn("Shell command completed", line)
        self.assertIn("nmap -Pn herovired.com", line)
        self.assertIn("4.0s", line)
        self.assertIn("exit 0", line)
