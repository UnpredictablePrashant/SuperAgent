import io
import time
import unittest
from unittest.mock import patch

import scripts.release_gate_non_socket as release_gate


def _passing_test_case() -> unittest.FunctionTestCase:
    return unittest.FunctionTestCase(lambda: None)


def _failing_test_case() -> unittest.FunctionTestCase:
    def _fail():
        raise AssertionError("boom")

    return unittest.FunctionTestCase(_fail)


class ReleaseGateNonSocketTests(unittest.TestCase):
    def test_run_suite_logs_start_and_finish(self):
        suite = unittest.TestSuite([_passing_test_case()])
        stream = io.StringIO()

        result = release_gate.run_suite(
            suite,
            stream=stream,
            failfast=True,
            timeout_seconds=30.0,
            start_dir="tests",
            pattern="test_demo.py",
            use_watchdog=False,
        )

        output = stream.getvalue()
        self.assertTrue(result.wasSuccessful())
        self.assertIn("[release-gate] suite started start_dir=tests pattern=test_demo.py", output)
        self.assertIn("[release-gate] START", output)
        self.assertIn("[release-gate] PASS", output)
        self.assertIn("[release-gate] suite finished success=true", output)

    def test_run_suite_logs_failures(self):
        suite = unittest.TestSuite([_failing_test_case()])
        stream = io.StringIO()

        result = release_gate.run_suite(
            suite,
            stream=stream,
            failfast=True,
            timeout_seconds=30.0,
            use_watchdog=False,
        )

        output = stream.getvalue()
        self.assertFalse(result.wasSuccessful())
        self.assertIn("[release-gate] FAIL", output)
        self.assertIn("FAILED", output)

    def test_emit_timeout_diagnostics_includes_current_test_and_children(self):
        state = release_gate.SuiteState(suite_started_at=time.monotonic() - 120.0)
        state.start_test("tests.test_demo.ReleaseGateTests.test_hang")
        stream = io.StringIO()

        with (
            patch.object(release_gate, "_list_child_process_lines", return_value=["123 456 00:10 S python child.py"]),
            patch.object(release_gate.faulthandler, "dump_traceback") as dump_traceback,
        ):
            release_gate.emit_timeout_diagnostics(state, timeout_seconds=60.0, stream=stream)

        output = stream.getvalue()
        self.assertIn("[release-gate] TIMEOUT after 60.0s", output)
        self.assertIn("current_test=tests.test_demo.ReleaseGateTests.test_hang", output)
        self.assertIn("123 456 00:10 S python child.py", output)
        dump_traceback.assert_called_once()


if __name__ == "__main__":
    unittest.main()
