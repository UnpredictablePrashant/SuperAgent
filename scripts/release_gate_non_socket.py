#!/usr/bin/env python3
from __future__ import annotations

import argparse
import contextlib
import faulthandler
import os
import signal
import subprocess
import sys
import threading
import time
import unittest
from dataclasses import dataclass, field
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_START_DIR = "tests"
DEFAULT_PATTERN = "test_*.py"
DEFAULT_TOP_LEVEL_DIR = str(ROOT)
DEFAULT_LOG_FILE = ROOT / "output" / "release_gate_non_socket.log"
DEFAULT_TIMEOUT_SECONDS = 3600.0


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("OPENAI_API_KEY", "test-openai-key")
    pythonpath = env.get("PYTHONPATH", "").strip()
    env["PYTHONPATH"] = str(ROOT) if not pythonpath else f"{ROOT}{os.pathsep}{pythonpath}"
    return env


class TeeStream:
    def __init__(self, *streams):
        self._streams = streams

    def write(self, data: str) -> int:
        for stream in self._streams:
            stream.write(data)
        return len(data)

    def flush(self) -> None:
        for stream in self._streams:
            stream.flush()

    def isatty(self) -> bool:
        return any(getattr(stream, "isatty", lambda: False)() for stream in self._streams)

    def fileno(self) -> int:
        for stream in reversed(self._streams):
            fileno = getattr(stream, "fileno", None)
            if fileno is None:
                continue
            try:
                return fileno()
            except Exception:
                continue
        raise OSError("TeeStream does not expose a file descriptor")

    @property
    def encoding(self) -> str:
        for stream in self._streams:
            encoding = getattr(stream, "encoding", None)
            if encoding:
                return encoding
        return "utf-8"


@contextlib.contextmanager
def tee_stdouterr(log_path: Path):
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("w", encoding="utf-8") as log_handle:
        tee_out = TeeStream(sys.__stdout__, log_handle)
        tee_err = TeeStream(sys.__stderr__, log_handle)
        with contextlib.redirect_stdout(tee_out), contextlib.redirect_stderr(tee_err):
            yield tee_out


@dataclass
class SuiteState:
    suite_started_at: float = field(default_factory=time.monotonic)
    completed: int = 0
    failures: int = 0
    errors: int = 0
    skipped: int = 0
    current_test_id: str = ""
    current_test_started_at: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def start_test(self, test_id: str) -> None:
        with self._lock:
            self.current_test_id = test_id
            self.current_test_started_at = time.monotonic()

    def finish_test(self, *, status: str) -> None:
        with self._lock:
            self.completed += 1
            if status == "FAIL":
                self.failures += 1
            elif status == "ERROR":
                self.errors += 1
            elif status == "SKIP":
                self.skipped += 1
            self.current_test_id = ""
            self.current_test_started_at = 0.0

    def snapshot(self) -> dict[str, float | int | str]:
        with self._lock:
            return {
                "suite_elapsed": time.monotonic() - self.suite_started_at,
                "completed": self.completed,
                "failures": self.failures,
                "errors": self.errors,
                "skipped": self.skipped,
                "current_test_id": self.current_test_id,
                "current_test_elapsed": (time.monotonic() - self.current_test_started_at)
                if self.current_test_id and self.current_test_started_at
                else 0.0,
            }


def _list_child_process_lines(parent_pid: int) -> list[str]:
    if os.name != "posix":
        return ["child-process diagnostics unavailable on this platform"]
    try:
        result = subprocess.run(
            ["ps", "-o", "pid=,ppid=,etime=,stat=,command=", "--ppid", str(parent_pid)],
            capture_output=True,
            text=True,
            check=False,
        )
    except Exception as exc:
        return [f"unable to enumerate child processes: {exc}"]
    lines = [line.rstrip() for line in result.stdout.splitlines() if line.strip()]
    return lines or ["no child processes found"]


def _child_pids(parent_pid: int) -> list[int]:
    pids: list[int] = []
    for line in _list_child_process_lines(parent_pid):
        first = line.strip().split(maxsplit=1)[0]
        if first.isdigit():
            pids.append(int(first))
    return pids


def _terminate_child_processes(parent_pid: int, stream) -> None:
    if os.name != "posix":
        return
    for child_pid in _child_pids(parent_pid):
        try:
            os.kill(child_pid, signal.SIGTERM)
            print(f"[release-gate] sent SIGTERM to child pid={child_pid}", file=stream)
        except ProcessLookupError:
            continue
        except Exception as exc:
            print(f"[release-gate] failed to terminate child pid={child_pid}: {exc}", file=stream)


def emit_timeout_diagnostics(state: SuiteState, *, timeout_seconds: float, stream) -> None:
    snapshot = state.snapshot()
    print(
        f"[release-gate] TIMEOUT after {timeout_seconds:.1f}s "
        f"(completed={snapshot['completed']} failures={snapshot['failures']} "
        f"errors={snapshot['errors']} skipped={snapshot['skipped']})",
        file=stream,
    )
    current_test_id = str(snapshot["current_test_id"] or "<none>")
    print(f"[release-gate] current_test={current_test_id}", file=stream)
    if snapshot["current_test_elapsed"]:
        print(
            f"[release-gate] current_test_elapsed={float(snapshot['current_test_elapsed']):.1f}s",
            file=stream,
        )
    print("[release-gate] child_processes:", file=stream)
    for line in _list_child_process_lines(os.getpid()):
        print(f"[release-gate]   {line}", file=stream)
    print("[release-gate] thread stacks:", file=stream)
    stream.flush()
    faulthandler.dump_traceback(file=stream, all_threads=True)
    stream.flush()


class TimeoutWatchdog(threading.Thread):
    def __init__(self, *, state: SuiteState, timeout_seconds: float, stream):
        super().__init__(name="release-gate-timeout-watchdog", daemon=True)
        self._state = state
        self._timeout_seconds = timeout_seconds
        self._stream = stream
        self._stop_event = threading.Event()

    def stop(self) -> None:
        self._stop_event.set()

    def run(self) -> None:
        deadline = self._state.suite_started_at + self._timeout_seconds
        while not self._stop_event.wait(1.0):
            if time.monotonic() < deadline:
                continue
            emit_timeout_diagnostics(self._state, timeout_seconds=self._timeout_seconds, stream=self._stream)
            _terminate_child_processes(os.getpid(), self._stream)
            self._stream.flush()
            os._exit(124)


class ReleaseGateResult(unittest.TextTestResult):
    def __init__(self, stream, descriptions, verbosity, *, state: SuiteState):
        super().__init__(stream, descriptions, verbosity)
        self._state = state
        self._started_at: dict[str, float] = {}
        self._statuses: dict[str, str] = {}

    def startTest(self, test) -> None:
        super().startTest(test)
        test_id = test.id()
        self._started_at[test_id] = time.monotonic()
        self._statuses[test_id] = "PASS"
        self._state.start_test(test_id)
        self.stream.writeln(f"[release-gate] START {test_id}")

    def addSuccess(self, test) -> None:
        super().addSuccess(test)
        self._statuses[test.id()] = "PASS"

    def addFailure(self, test, err) -> None:
        super().addFailure(test, err)
        self._statuses[test.id()] = "FAIL"

    def addError(self, test, err) -> None:
        super().addError(test, err)
        self._statuses[test.id()] = "ERROR"

    def addSkip(self, test, reason) -> None:
        super().addSkip(test, reason)
        self._statuses[test.id()] = "SKIP"

    def addExpectedFailure(self, test, err) -> None:
        super().addExpectedFailure(test, err)
        self._statuses[test.id()] = "XFAIL"

    def addUnexpectedSuccess(self, test) -> None:
        super().addUnexpectedSuccess(test)
        self._statuses[test.id()] = "UNEXPECTED-SUCCESS"

    def stopTest(self, test) -> None:
        test_id = test.id()
        started_at = self._started_at.pop(test_id, time.monotonic())
        status = self._statuses.pop(test_id, "PASS")
        elapsed = time.monotonic() - started_at
        self.stream.writeln(f"[release-gate] {status} {test_id} ({elapsed:.2f}s)")
        self._state.finish_test(status="SKIP" if status == "SKIP" else ("FAIL" if status in {"FAIL", "UNEXPECTED-SUCCESS"} else ("ERROR" if status == "ERROR" else "PASS")))
        super().stopTest(test)


class ReleaseGateRunner(unittest.TextTestRunner):
    resultclass = ReleaseGateResult

    def __init__(self, *, state: SuiteState, **kwargs):
        self._state = state
        super().__init__(**kwargs)

    def _makeResult(self):
        return self.resultclass(self.stream, self.descriptions, self.verbosity, state=self._state)


def build_suite(start_dir: str, pattern: str, top_level_dir: str) -> unittest.TestSuite:
    loader = unittest.defaultTestLoader
    return loader.discover(start_dir=start_dir, pattern=pattern, top_level_dir=top_level_dir)


def run_suite(
    suite: unittest.TestSuite,
    *,
    stream,
    failfast: bool,
    timeout_seconds: float,
    start_dir: str = DEFAULT_START_DIR,
    pattern: str = DEFAULT_PATTERN,
    use_watchdog: bool = True,
) -> unittest.TestResult:
    state = SuiteState()
    watchdog = TimeoutWatchdog(state=state, timeout_seconds=timeout_seconds, stream=stream) if use_watchdog else None
    runner = ReleaseGateRunner(
        state=state,
        stream=stream,
        verbosity=0,
        failfast=failfast,
        descriptions=False,
    )
    if watchdog is not None:
        watchdog.start()
    try:
        print(
            f"[release-gate] suite started start_dir={start_dir} pattern={pattern} "
            f"timeout_seconds={timeout_seconds:.1f} failfast={str(failfast).lower()}",
            file=stream,
        )
        result = runner.run(suite)
    finally:
        if watchdog is not None:
            watchdog.stop()
            watchdog.join(timeout=1.0)
    snapshot = state.snapshot()
    print(
        f"[release-gate] suite finished success={str(result.wasSuccessful()).lower()} "
        f"completed={snapshot['completed']} failures={snapshot['failures']} "
        f"errors={snapshot['errors']} skipped={snapshot['skipped']} "
        f"duration={float(snapshot['suite_elapsed']):.1f}s",
        file=stream,
    )
    stream.flush()
    return result


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the wider non-socket unittest gate with diagnostics.")
    parser.add_argument("--start-dir", default=DEFAULT_START_DIR, help="unittest discovery start directory")
    parser.add_argument("--pattern", default=DEFAULT_PATTERN, help="unittest discovery filename pattern")
    parser.add_argument("--top-level-dir", default=DEFAULT_TOP_LEVEL_DIR, help="unittest discovery top-level directory")
    parser.add_argument(
        "--timeout-seconds",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="hard timeout for the entire suite",
    )
    parser.add_argument(
        "--log-file",
        default=str(DEFAULT_LOG_FILE),
        help="path to the combined stdout/stderr log file",
    )
    parser.add_argument(
        "--failfast",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="stop on the first failure",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    os.environ.update(_env())
    suite = build_suite(args.start_dir, args.pattern, args.top_level_dir)
    log_path = Path(args.log_file).expanduser().resolve()
    with tee_stdouterr(log_path) as stream:
        print(f"[release-gate] log_file={log_path}", file=stream)
        faulthandler.enable(file=stream, all_threads=True)
        try:
            result = run_suite(
                suite,
                stream=stream,
                failfast=bool(args.failfast),
                timeout_seconds=float(args.timeout_seconds),
                start_dir=args.start_dir,
                pattern=args.pattern,
            )
        finally:
            faulthandler.disable()
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
