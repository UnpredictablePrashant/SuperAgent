from __future__ import annotations

import argparse
import datetime as dt
import importlib.metadata
import json
import os
import re
import socket
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
import uuid
import zipfile
import webbrowser
from pathlib import Path
from typing import Any

from kendr.http import (
    build_resume_state_overrides,
    infer_resume_working_directory,
    resume_candidate_requires_branch,
    resume_candidate_requires_force,
    resume_candidate_requires_reply,
)
from kendr.orchestration import state_awaiting_user_input
from kendr.execution_trace import render_execution_event_line
from kendr.setup import (
    build_google_oauth_config,
    build_microsoft_oauth_config,
    build_setup_snapshot,
    build_slack_oauth_config,
)

from .recovery import discover_resume_candidates, load_resume_candidate, render_resume_candidate
from .discovery import build_registry
from tasks.security_policy import (
    SECURITY_SCAN_PROFILES,
    authorization_process_text,
    is_security_assessment_query,
)
from tasks.privileged_control import list_backup_snapshots, restore_backup_snapshot
from tasks.setup_config_store import (
    apply_setup_env_defaults,
    export_env_lines,
    get_component,
    get_setup_component_snapshot,
    save_component_values,
    set_component_enabled,
    setup_overview,
)


class _CliStyle:
    def __init__(self, enabled: bool) -> None:
        self.enabled = enabled

    def _wrap(self, text: str, code: str) -> str:
        if not self.enabled:
            return text
        return f"\033[{code}m{text}\033[0m"

    def title(self, text: str) -> str:
        return self._wrap(text, "1;36")

    def heading(self, text: str) -> str:
        return self._wrap(text, "1;34")

    def ok(self, text: str) -> str:
        return self._wrap(text, "1;32")

    def warn(self, text: str) -> str:
        return self._wrap(text, "1;33")

    def fail(self, text: str) -> str:
        return self._wrap(text, "1;31")

    def muted(self, text: str) -> str:
        return self._wrap(text, "2")


def _colors_enabled(argv: list[str] | None) -> bool:
    args = argv if argv is not None else sys.argv[1:]
    if "--no-color" in args:
        return False
    if os.getenv("NO_COLOR"):
        return False
    return bool(getattr(sys.stdout, "isatty", lambda: False)())


_STATUS_LINE_LENGTH = 0
_STATUS_LINE_ACTIVE = False
_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-9;]*m")


def _cli_style(argv: list[str] | None) -> _CliStyle:
    return _CliStyle(enabled=_colors_enabled(argv))


def _cli_version() -> str:
    try:
        return importlib.metadata.version("kendr-runtime")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


def _cli_tagline() -> str:
    options = [
        "Orchestrate agents, not terminal chaos.",
        "Structured automation for serious workflows.",
        "Reliable multi-agent execution from one command surface.",
        "If it scales, it belongs in your CLI.",
        "Research, build, communicate, and know — all from one command.",
        "Your agents are waiting. Give them a mission.",
        "Multi-source intelligence in a single invocation.",
        "From raw query to polished report, without leaving the terminal.",
        "Deploy a fleet of agents with one line.",
        "The intelligence layer your workflow was missing.",
        "Ship faster. Think deeper. Automate further.",
        "Knowledge at the speed of the command line.",
    ]
    day_index = dt.date.today().toordinal() % len(options)
    return options[day_index]


def _cli_banner(style: _CliStyle) -> str:
    version = _cli_version()
    return f"{style.title('Kendr')} {style.muted(version)} - {_cli_tagline()}"


class _KendrHelpFormatter(argparse.RawTextHelpFormatter):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault("max_help_position", 34)
        super().__init__(*args, **kwargs)


def _style_from_args(args: argparse.Namespace) -> _CliStyle:
    enabled = bool(getattr(sys.stdout, "isatty", lambda: False)()) and not bool(getattr(args, "no_color", False))
    if os.getenv("NO_COLOR"):
        enabled = False
    return _CliStyle(enabled=enabled)


def _truncate(text: str, limit: int) -> str:
    raw = " ".join(str(text or "").split())
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 3)].rstrip() + "..."


def _render_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    widths = [len(h) for h in headers]
    for row in rows:
        for idx, cell in enumerate(row):
            widths[idx] = max(widths[idx], len(cell))
    header_line = "  ".join(h.ljust(widths[idx]) for idx, h in enumerate(headers))
    divider = "  ".join("-" * widths[idx] for idx in range(len(headers)))
    body = ["  ".join(cell.ljust(widths[idx]) for idx, cell in enumerate(row)) for row in rows]
    return "\n".join([header_line, divider, *body])


def _gateway_host_port() -> tuple[str, int]:
    host = os.getenv("GATEWAY_HOST", "127.0.0.1")
    port = int(os.getenv("GATEWAY_PORT", "8790"))
    return host, port


def _gateway_base_url() -> str:
    host, port = _gateway_host_port()
    return f"http://{host}:{port}"


def _ui_host_port() -> tuple[str, int]:
    host = os.getenv("KENDR_UI_HOST", "127.0.0.1")
    port = int(os.getenv("KENDR_UI_PORT", "2151"))
    return host, port


def _ui_base_url() -> str:
    host, port = _ui_host_port()
    display_host = "localhost" if host in ("0.0.0.0", "") else host
    return f"http://{display_host}:{port}"


def _ui_ready(timeout_seconds: float = 1.0) -> bool:
    _, port = _ui_host_port()
    try:
        import urllib.request as _req
        import json as _json
        with _req.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=timeout_seconds) as r:
            data = _json.loads(r.read())
            return data.get("service") == "kendr-ui"
    except Exception:
        return False


def _http_json_get(url: str, timeout_seconds: float = 2.0):
    request = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
        return json.loads(response.read().decode("utf-8"))


def _cli_session_file() -> Path:
    return Path("output") / ".cli_session.json"


def _load_cli_session() -> dict:
    path = _cli_session_file()
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_cli_session(payload: dict) -> None:
    path = _cli_session_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _clear_cli_session() -> None:
    path = _cli_session_file()
    if path.exists():
        path.unlink()


def _session_parts_from_key(session_key: str) -> dict:
    raw = str(session_key or "").strip()
    parts = raw.split(":")
    if len(parts) < 4:
        return {}
    return {
        "channel": parts[0],
        "workspace_id": parts[1],
        "chat_id": parts[2],
        "scope": parts[3],
        "session_key": raw,
    }


def _is_timeout_error(exc: BaseException) -> bool:
    if isinstance(exc, (TimeoutError, socket.timeout)):
        return True
    reason = getattr(exc, "reason", None)
    return isinstance(reason, (TimeoutError, socket.timeout))


def _oauth_missing_env(provider: str) -> list[str]:
    provider = str(provider or "").strip().lower()
    if provider == "google":
        config = build_google_oauth_config()
        pairs = [
            ("GOOGLE_CLIENT_ID", config.get("client_id", "")),
            ("GOOGLE_CLIENT_SECRET", config.get("client_secret", "")),
            ("GOOGLE_REDIRECT_URI", config.get("redirect_uri", "")),
            ("GOOGLE_OAUTH_SCOPES", config.get("scopes", "")),
        ]
    elif provider == "microsoft":
        config = build_microsoft_oauth_config()
        pairs = [
            ("MICROSOFT_CLIENT_ID", config.get("client_id", "")),
            ("MICROSOFT_CLIENT_SECRET", config.get("client_secret", "")),
            ("MICROSOFT_REDIRECT_URI", config.get("redirect_uri", "")),
            ("MICROSOFT_OAUTH_SCOPES", config.get("scopes", "")),
        ]
    elif provider == "slack":
        config = build_slack_oauth_config()
        pairs = [
            ("SLACK_CLIENT_ID", config.get("client_id", "")),
            ("SLACK_CLIENT_SECRET", config.get("client_secret", "")),
            ("SLACK_REDIRECT_URI", config.get("redirect_uri", "")),
            ("SLACK_OAUTH_SCOPES", config.get("scopes", "")),
        ]
    else:
        return [f"Unsupported provider: {provider}"]
    return [name for name, value in pairs if not str(value or "").strip()]


def _status_stream_supports_live_updates() -> bool:
    try:
        if os.isatty(sys.stderr.fileno()):
            return True
    except Exception:
        pass
    return bool(getattr(sys.stderr, "isatty", lambda: False)()) or bool(getattr(sys.stdout, "isatty", lambda: False)())


def _clear_transient_status_line() -> None:
    global _STATUS_LINE_ACTIVE, _STATUS_LINE_LENGTH

    if not _STATUS_LINE_ACTIVE:
        return
    if _status_stream_supports_live_updates():
        sys.stderr.write("\r" + (" " * _STATUS_LINE_LENGTH) + "\r")
        sys.stderr.flush()
    _STATUS_LINE_ACTIVE = False
    _STATUS_LINE_LENGTH = 0


def _visible_status_length(text: str) -> int:
    return len(_ANSI_ESCAPE_RE.sub("", str(text or "")))


def _truncate_status_text(value: object, limit: int = 140) -> str:
    cleaned = " ".join(str(value or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: limit - 3] + "..."


def _coerce_plan_steps(summary: dict) -> list[dict]:
    raw = summary.get("plan_steps")
    if not isinstance(raw, list):
        return []
    return [step for step in raw if isinstance(step, dict)]


def _coerce_execution_trace(summary: dict) -> list[dict]:
    raw = summary.get("execution_trace")
    if not isinstance(raw, list):
        return []
    return [event for event in raw if isinstance(event, dict)]


def _plan_step_titles(steps: list[dict]) -> list[str]:
    titles: list[str] = []
    for step in steps:
        title = str(step.get("title") or step.get("id") or step.get("task") or "").strip()
        if title:
            titles.append(title)
    return titles


def _summarize_step_titles(titles: list[str], limit: int = 140) -> str:
    if not titles:
        return "none"
    joined = "; ".join(titles)
    return _truncate_status_text(joined, limit=limit)


def _event_limit() -> int:
    try:
        return max(1, int(os.getenv("KENDR_PROGRESS_LIMIT", "10")))
    except Exception:
        return 10


def _render_tree(root: str, branches: list[str], *, multiline: bool = False) -> str:
    visible = [str(branch).strip() for branch in branches if str(branch).strip()]
    if not visible:
        return root
    if not multiline:
        parts = [root]
        for branch in visible[:-1]:
            parts.append(f"|- {branch}")
        parts.append(f"`- {visible[-1]}")
        return " ".join(parts)
    lines = [root]
    for branch in visible[:-1]:
        lines.append(f"|- {branch}")
    lines.append(f"`- {visible[-1]}")
    return "\n".join(lines)


def _status_persona(status: str) -> str:
    normalized = str(status or "").strip().lower()
    personas = {
        "running": "apparently the machines are employed today.",
        "awaiting_user_input": "waiting on a human, which is always risky.",
        "completed": "done, against the odds.",
        "paused": "stopped politely before making things weirder.",
        "failed": "fell over with impressive commitment.",
    }
    return personas.get(normalized, "the plot remains unnecessarily lively.")


def _format_run_progress_tree(
    *,
    status: str,
    active_agent: str,
    steps: int | str,
    active_task: str = "",
    pending_kind: str = "",
    scope: str = "",
    plan: dict | None = None,
    activity: list[str] | None = None,
) -> str:
    branches = [
        f"status: {status} ({_status_persona(status)})",
        f"agent: {active_agent or '-'}",
    ]
    if plan:
        progress = str(plan.get("progress", "") or "").strip()
        if progress:
            branches.append(f"major: {progress}")
        current = str(plan.get("current", "") or "").strip()
        if current:
            branches.append(f"current: {current}")
        branches.append(f"done: {plan.get('done', 'none')}")
        branches.append(f"remaining: {plan.get('remaining', 'none')}")
    else:
        branches.append(f"step: {steps}")
    if activity:
        branches.extend(f"log: {item}" for item in activity if str(item or "").strip())
    if pending_kind:
        awaiting = f"awaiting: {pending_kind}"
        if scope:
            awaiting += f" @ {scope}"
        branches.append(awaiting)
    if active_task:
        branches.append(f"task: {active_task}")
    return _render_tree("[run]", branches, multiline=True)


def _decorate_status_message(message: str, *, transient: bool = False) -> str:
    text = str(message or "").strip()
    if not text:
        return text

    if transient:
        waiting_match = re.match(r"^\[run\]\s+waiting for completion\.\.\.\s+(\d+)s elapsed", text)
        if waiting_match:
            elapsed = waiting_match.group(1)
            return _render_tree(
                "[run]",
                [
                    f"waiting: {elapsed}s elapsed",
                    "still chewing through the task. apparently speed was a rumor.",
                ],
                multiline=False,
            )

    gateway_start_match = re.match(r"^\[gateway\]\s+not running at\s+(\S+); starting gateway\.\.\.$", text)
    if gateway_start_match:
        return _render_tree(
            "[gateway]",
            [
                "status: offline",
                f"url: {gateway_start_match.group(1)}",
                "note: not running, so we are waking it up. Again.",
            ],
            multiline=True,
        )

    gateway_ready_match = re.match(r"^\[gateway\]\s+ready at\s+(\S+)$", text)
    if gateway_ready_match:
        return _render_tree(
            "[gateway]",
            [
                "status: ready",
                f"url: {gateway_ready_match.group(1)}",
                "note: awake now and pretending this was always the plan.",
            ],
            multiline=True,
        )

    run_accepted_match = re.match(r"^\[run\]\s+accepted request run_id=(\S+)\s+\|\s+working_directory=(.+)$", text)
    if run_accepted_match:
        return _render_tree(
            "[run]",
            [
                f"accepted: {run_accepted_match.group(1)}",
                f"workdir: {run_accepted_match.group(2).strip()}",
                "note: paperwork filed, chaos authorized.",
            ],
            multiline=True,
        )

    run_status_match = re.match(r"^\[run\]\s+status=(\S+)\s+active_agent=(\S+)\s+steps=(\d+)(.*)$", text)
    if run_status_match:
        status = run_status_match.group(1)
        active_agent = run_status_match.group(2)
        steps = run_status_match.group(3)
        remainder = run_status_match.group(4) or ""
        pending_match = re.search(r"\sawaiting=(\S+)", remainder)
        scope_match = re.search(r"\sscope=(\S+)", remainder)
        task_match = re.search(r"\stask=(.+)$", remainder)
        return _format_run_progress_tree(
            status=status,
            active_agent=active_agent,
            steps=steps,
            active_task=task_match.group(1).strip() if task_match else "",
            pending_kind=pending_match.group(1).strip() if pending_match else "",
            scope=scope_match.group(1).strip() if scope_match else "",
        )

    run_terminal_match = re.match(r"^\[run\]\s+(paused|completed)\s+run_id=(\S+)\s+last_agent=(\S+)$", text)
    if run_terminal_match:
        terminal = run_terminal_match.group(1)
        return _render_tree(
            "[run]",
            [
                f"status: {terminal}",
                f"run_id: {run_terminal_match.group(2)}",
                f"last_agent: {run_terminal_match.group(3)}",
                f"note: {_status_persona(terminal)}",
            ],
            multiline=True,
        )

    if text.startswith("[run] ingest connection timed out;"):
        return _render_tree(
            "[run]",
            [
                "status: monitoring",
                "transport: ingest timeout",
                "note: first handshake flinched, so we are tracking the run the stubborn way.",
            ],
            multiline=True,
        )

    workflow_match = re.match(r"^\[workflow\]\s+(.+)$", text)
    if workflow_match:
        return _render_tree(
            "[workflow]",
            [
                f"active: {workflow_match.group(1).strip()}",
                "note: yes, this is the official drama report.",
            ],
            multiline=True,
        )

    return text


def _task_session_summary(session: dict) -> dict:
    summary = session.get("summary")
    if isinstance(summary, dict):
        return summary
    raw_summary = session.get("summary_json")
    if isinstance(raw_summary, str) and raw_summary.strip():
        try:
            decoded = json.loads(raw_summary)
        except Exception:
            return {}
        if isinstance(decoded, dict):
            return decoded
    return {}


def _build_run_progress_message(session: dict) -> str:
    summary = _task_session_summary(session)
    pending_kind = ""
    scope = ""
    if bool(summary.get("awaiting_user_input")):
        pending_kind = _truncate_status_text(summary.get("pending_user_input_kind") or "user_input", limit=40)
        scope = _truncate_status_text(summary.get("approval_pending_scope") or "", limit=40)
    active_task = _truncate_status_text(summary.get("active_task") or summary.get("objective") or "")
    plan_steps = _coerce_plan_steps(summary)
    plan_index = int(summary.get("plan_step_index", 0) or 0)
    plan_total = int(summary.get("plan_step_total", 0) or 0)
    plan_titles = _plan_step_titles(plan_steps)
    if plan_total <= 0 and plan_titles:
        plan_total = len(plan_titles)
    plan = None
    activity: list[str] = []
    if plan_titles:
        capped_index = max(0, min(plan_index, len(plan_titles)))
        current_title = plan_titles[capped_index] if capped_index < len(plan_titles) else ""
        done_titles = plan_titles[:capped_index] if capped_index > 0 else []
        remaining_titles = plan_titles[capped_index + 1 :] if capped_index + 1 < len(plan_titles) else []
        progress = f"{min(capped_index + 1, plan_total)}/{plan_total}" if plan_total else str(capped_index + 1)
        if plan_total > 0 and capped_index >= plan_total:
            progress = f"{plan_total}/{plan_total}"
            current_title = ""
            done_titles = plan_titles
            remaining_titles = []
        plan = {
            "progress": progress,
            "current": _truncate_status_text(current_title, limit=120),
            "done": _summarize_step_titles(done_titles, limit=160),
            "remaining": _summarize_step_titles(remaining_titles, limit=160),
        }

    recent = summary.get("recent_events") or summary.get("recent_activity") or []
    execution_trace = _coerce_execution_trace(summary)
    limit = _event_limit()
    if execution_trace:
        activity = []
        for item in execution_trace[-limit:]:
            line = render_execution_event_line(item)
            if line:
                activity.append(line)
    elif isinstance(recent, list):
        activity = [str(item) for item in recent if str(item).strip()][:limit]
    return _format_run_progress_tree(
        status=str(session.get("status", "running")),
        active_agent=str(session.get("active_agent", "") or "-"),
        steps=session.get("step_count", 0),
        active_task=active_task,
        pending_kind=pending_kind,
        scope=scope,
        plan=plan,
        activity=activity,
    )


def _status_level(message: str, *, transient: bool = False) -> str:
    text = " ".join(str(message or "").split()).lower()
    if transient or "waiting for completion" in text:
        return "muted"
    if any(token in text for token in ("failed", "gateway ingest failed", "error", "exception", "traceback")):
        return "fail"
    if any(token in text for token in ("timed out", "not running", "restarting", "stopped", "already running", "canceled", "cancelled")):
        return "warn"
    if any(token in text for token in ("ready at", "completed", "started", "running at http://")):
        return "ok"
    return "heading"


def _style_status_message(args: argparse.Namespace, message: str, *, transient: bool = False) -> str:
    if _ANSI_ESCAPE_RE.search(str(message)):
        return str(message)
    style = _style_from_args(args)
    level = _status_level(message, transient=transient)
    rendered = _decorate_status_message(message, transient=transient)
    formatter = {
        "muted": style.muted,
        "fail": style.fail,
        "warn": style.warn,
        "ok": style.ok,
        "heading": style.heading,
    }[level]
    return formatter(rendered)


def _colorize_run_progress_message(message: str, style: _CliStyle) -> str:
    if not style.enabled:
        return message
    if _ANSI_ESCAPE_RE.search(str(message)):
        return message
    lines = str(message).splitlines()
    colored: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|- done:") or stripped.startswith("`- done:"):
            colored.append(style.ok(line))
            continue
        if stripped.startswith("|- remaining:") or stripped.startswith("`- remaining:"):
            colored.append(style.warn(line))
            continue
        if stripped.startswith("|- current:") or stripped.startswith("`- current:"):
            colored.append(style.heading(line))
            continue
        if stripped.startswith("|- major:") or stripped.startswith("`- major:"):
            colored.append(style.heading(line))
            continue
        colored.append(line)
    return "\n".join(colored)


def _emit_status(args: argparse.Namespace, message: str, *, transient: bool = False) -> None:
    global _STATUS_LINE_ACTIVE, _STATUS_LINE_LENGTH

    if bool(getattr(args, "quiet", False)):
        return
    styled_message = _style_status_message(args, message, transient=transient)
    if transient and _status_stream_supports_live_updates():
        text = " ".join(str(styled_message).splitlines()).strip()
        padding = max(0, _STATUS_LINE_LENGTH - _visible_status_length(text))
        sys.stderr.write("\r" + text + (" " * padding) + "\r")
        sys.stderr.flush()
        _STATUS_LINE_ACTIVE = True
        _STATUS_LINE_LENGTH = _visible_status_length(text)
        return
    _clear_transient_status_line()
    try:
        from kendr import cli_output as _cout
        _cout.print_status(str(styled_message).strip())
    except Exception:
        print(styled_message, file=sys.stderr, flush=True)


def _gateway_ready(timeout_seconds: float = 1.0) -> bool:
    request = urllib.request.Request(f"{_gateway_base_url()}/health", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and payload.get("status") == "ok"
    except Exception:
        return False


def _kendr_state_home() -> Path:
    raw = os.getenv("KENDR_HOME", "").strip()
    candidate = Path(raw).expanduser().resolve() if raw else (Path.home() / ".kendr").resolve()
    try:
        candidate.mkdir(parents=True, exist_ok=True)
        return candidate
    except OSError:
        project_root = _discover_project_root()
        fallback = ((project_root or Path.cwd()) / ".kendr").resolve()
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def _discover_project_root(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).expanduser().resolve()
    for candidate in (current, *current.parents):
        if (candidate / ".git").exists():
            return candidate
        if (candidate / "pyproject.toml").exists():
            return candidate
        if (candidate / "package.json").exists():
            return candidate
    return None


def _service_log_dir() -> Path:
    override = str(os.getenv("KENDR_LOG_DIR", "") or "").strip()
    if override:
        target = Path(override).expanduser()
    else:
        project_root = _discover_project_root()
        target = (project_root / "logs" / "kendr") if project_root else (_kendr_state_home() / "logs")
    resolved = target.resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return resolved


def _gateway_log_path() -> Path:
    return _service_log_dir() / "gateway.log"


def _ui_log_path() -> Path:
    return _service_log_dir() / "ui.log"


def _gateway_pid_path() -> Path:
    home = _kendr_state_home()
    home.mkdir(parents=True, exist_ok=True)
    return home / "gateway.pid"


def _gateway_start_time_path() -> Path:
    home = _kendr_state_home()
    home.mkdir(parents=True, exist_ok=True)
    return home / "gateway.start_time"


_GATEWAY_OWNER_MARKER = "kendr-gateway"


def _gateway_owner_marker_path() -> Path:
    home = _kendr_state_home()
    home.mkdir(parents=True, exist_ok=True)
    return home / "gateway.owner"


def _proc_start_jiffies(pid: int) -> str:
    try:
        proc_stat = f"/proc/{pid}/stat"
        if os.path.exists(proc_stat):
            with open(proc_stat) as f:
                fields = f.read().split()
            return fields[21]
    except Exception:
        pass
    return ""


def _write_gateway_pid(pid: int) -> None:
    try:
        _gateway_pid_path().write_text(str(pid), encoding="utf-8")
        _gateway_start_time_path().write_text(str(time.time()), encoding="utf-8")
        start_jiffies = _proc_start_jiffies(pid)
        marker_content = f"{_GATEWAY_OWNER_MARKER}\n{start_jiffies}"
        _gateway_owner_marker_path().write_text(marker_content, encoding="utf-8")
    except Exception:
        pass


def _read_gateway_pid() -> int | None:
    try:
        raw = _gateway_pid_path().read_text(encoding="utf-8").strip()
        if raw.isdigit():
            return int(raw)
    except Exception:
        pass
    return None


def _read_gateway_start_time() -> float | None:
    try:
        raw = _gateway_start_time_path().read_text(encoding="utf-8").strip()
        return float(raw)
    except Exception:
        return None


def _clear_gateway_pid() -> None:
    for path in (_gateway_pid_path(), _gateway_start_time_path(), _gateway_owner_marker_path()):
        try:
            if path.exists():
                path.unlink()
        except Exception:
            pass


def _pid_is_alive(pid: int) -> bool:
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH", "/FO", "CSV"],
                capture_output=True, text=True, check=False,
            )
            return f'"{pid}"' in result.stdout
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _pid_is_gateway_owned(pid: int) -> bool:
    if os.name == "nt":
        # No /proc on Windows — trust our own PID file
        stored_pid = _read_gateway_pid()
        return stored_pid is not None and stored_pid == pid
    try:
        raw = _gateway_owner_marker_path().read_text(encoding="utf-8")
    except Exception:
        return False
    lines = raw.strip().splitlines()
    if not lines or lines[0].strip() != _GATEWAY_OWNER_MARKER:
        return False
    stored_jiffies = lines[1].strip() if len(lines) > 1 else ""
    if stored_jiffies:
        current_jiffies = _proc_start_jiffies(pid)
        if current_jiffies:
            if current_jiffies != stored_jiffies:
                return False
            return True
    cmdline_path = f"/proc/{pid}/cmdline"
    if os.path.exists(cmdline_path):
        try:
            with open(cmdline_path, "rb") as f:
                cmdline = f.read().replace(b"\x00", b" ").decode("utf-8", errors="replace")
            gateway_keywords = ("kendr", "gateway", "serve", "uvicorn")
            return any(kw in cmdline for kw in gateway_keywords)
        except Exception:
            return False
    return False


def _wait_for_listener_shutdown(port: int, timeout_seconds: float = 5.0) -> bool:
    deadline = time.time() + max(0.5, timeout_seconds)
    while time.time() < deadline:
        if not _listener_pids_for_port(port):
            return True
        time.sleep(0.2)
    return not _listener_pids_for_port(port)


def _start_gateway_process() -> None:
    if _gateway_ready(timeout_seconds=0.8):
        return

    _, port = _gateway_host_port()
    stale_pids = _listener_pids_for_port(port)
    if stale_pids:
        _terminate_gateway_on_port()
        _wait_for_listener_shutdown(port, timeout_seconds=6.0)

    log_path = _gateway_log_path()
    with log_path.open("a", encoding="utf-8") as gateway_log:
        gateway_log.write(
            f"\n[{dt.datetime.now(dt.timezone.utc).isoformat()}] launching gateway via {sys.executable}\n"
        )
        gateway_log.flush()
        process = subprocess.Popen(
            [sys.executable, "-m", "kendr.cli", "gateway", "serve"],
            stdout=gateway_log,
            stderr=gateway_log,
            start_new_session=True,
        )
        _write_gateway_pid(process.pid)

    start_timeout_seconds = max(
        5.0,
        float(os.getenv("KENDR_GATEWAY_START_TIMEOUT_SECONDS", "25") or "25"),
    )
    deadline = time.time() + start_timeout_seconds
    healthy_checks = 0
    while time.time() < deadline:
        if _gateway_ready(timeout_seconds=1.0):
            healthy_checks += 1
            if healthy_checks >= 2:
                return
        else:
            healthy_checks = 0
        if process.poll() is not None:
            break
        time.sleep(0.5)

    status_note = ""
    exit_code = process.poll()
    if exit_code is not None:
        status_note = f" Background process exited with code {exit_code}."
    raise SystemExit(
        f"Gateway did not become ready at {_gateway_base_url()}. "
        f"Start it in background with: kendr gateway start. "
        f"Startup log: {log_path}.{status_note}"
    )


def _setup_ui_base_url() -> str:
    host = os.getenv("KENDR_UI_HOST", "127.0.0.1")
    port = int(os.getenv("KENDR_UI_PORT", "5000"))
    return f"http://{host}:{port}"


def _setup_ui_ready(timeout_seconds: float = 1.0) -> bool:
    try:
        _http_json_get(f"{_setup_ui_base_url()}/api/setup/overview", timeout_seconds=timeout_seconds)
        return True
    except Exception:
        return False


def _start_setup_ui_process() -> None:
    subprocess.Popen(
        [sys.executable, "-m", "kendr.cli", "ui"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(24):
        if _setup_ui_ready(timeout_seconds=0.5):
            return
        time.sleep(0.25)
    raise SystemExit(f"Kendr UI did not become ready at {_setup_ui_base_url()}. Start it manually with: kendr ui")


def _listener_pids_for_port(port: int) -> list[int]:
    if os.name == "nt":
        try:
            result = subprocess.run(
                ["netstat", "-ano", "-p", "tcp"],
                capture_output=True,
                text=True,
                check=False,
            )
            pids: set[int] = set()
            for line in result.stdout.splitlines():
                if f":{port}" in line and "LISTENING" in line:
                    parts = line.split()
                    if parts and parts[-1].isdigit():
                        pids.add(int(parts[-1]))
            return sorted(pids)
        except Exception:
            return []

    try:
        result = subprocess.run(
            ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN", "-t"],
            capture_output=True,
            text=True,
            check=False,
        )
        pids = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line.isdigit():
                pids.append(int(line))
        return sorted(set(pids))
    except Exception:
        return []


def _terminate_gateway_on_port() -> int:
    _, port = _gateway_host_port()
    pids = _listener_pids_for_port(port)
    if not pids:
        return 0
    if os.name == "nt":
        targets = pids
    else:
        targets = [p for p in pids if _pid_is_gateway_owned(p)]
    if not targets:
        return 0
    for pid in targets:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True, check=False)
            else:
                os.kill(pid, 15)
        except Exception:
            continue
    return len(targets)


def _terminate_ui_on_port() -> int:
    """Kill any kendr UI process running on the configured UI port. Returns count killed."""
    ui_port = int(os.getenv("KENDR_UI_PORT", "2151"))
    pids = _listener_pids_for_port(ui_port)
    if not pids:
        return 0
    # Verify it's actually the kendr UI before killing
    is_kendr_ui = False
    try:
        import urllib.request as _req
        import json as _json
        with _req.urlopen(f"http://127.0.0.1:{ui_port}/api/health", timeout=1) as r:
            data = _json.loads(r.read())
            if data.get("service") == "kendr-ui":
                is_kendr_ui = True
    except Exception:
        pass
    if not is_kendr_ui:
        return 0
    killed = 0
    for pid in pids:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)
            else:
                os.kill(pid, 15)
            killed += 1
        except Exception:
            continue
    return killed


def _resolve_working_dir(path_value: str) -> str:
    resolved = Path(path_value).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return str(resolved)


def _is_test_intent(query: str) -> tuple[bool, str]:
    """Detect if the query is a testing request.
    Returns (is_test, intent_type) where intent_type in:
    'api_test', 'unit_test', 'run_tests', 'fix_tests', 'regression_test'
    """
    text = str(query or "").lower()

    api_markers = [
        "api test", "api tests", "test the api", "test api",
        "generate api test", "openapi test", "test endpoint", "test endpoint",
        "write api test", "test suite for http", "test suite for api",
    ]
    unit_markers = [
        "unit test", "write test", "write tests for", "generate test",
        "test for this file", "test the function", "test coverage",
        "write unit test", "add tests for", "test cases for",
    ]
    run_markers = [
        "run test", "run our test", "run the test", "existing test suite",
        "run pytest", "run jest", "execute test",
    ]
    fix_markers = [
        "fix test", "fix failing test", "fix the test", "make test pass",
        "fix test failure", "repair test", "auto-fix test",
        "run and fix test", "run tests and fix", "run tests, fix",
        "run test and fix", "fix any failure", "fix failing",
    ]
    regression_markers = [
        "regression test", "add regression", "write regression",
        "test for the bug", "test for bug where", "bug where",
        "test for the issue where",
    ]

    for m in regression_markers:
        if m in text:
            return True, "regression_test"
    for m in fix_markers:
        if m in text:
            return True, "fix_tests"
    for m in run_markers:
        if m in text:
            return True, "run_tests"
    for m in api_markers:
        if m in text:
            return True, "api_test"
    for m in unit_markers:
        if m in text:
            return True, "unit_test"
    return False, ""


def _run_test_intent_standalone(
    args: argparse.Namespace,
    query: str,
    intent_type: str,
    working_dir: str,
) -> int:
    """Handle a testing intent directly without the gateway."""
    style = _style_from_args(args)
    text = str(query or "").lower()

    try:
        from tasks.testing_agent_suite import (
            api_test_agent,
            unit_test_agent,
            test_runner_agent,
            test_fix_agent,
            regression_test_agent,
        )
    except ImportError as exc:
        print(style.fail(f"Cannot import testing agents: {exc}"))
        return 1

    state: dict = {"test_working_directory": working_dir, "user_query": query}
    emit_json = bool(getattr(args, "json", False))

    try:
        if intent_type == "api_test":
            import re as _re
            url_match = _re.search(r"https?://\S+", query)
            source = url_match.group(0) if url_match else ""
            if not source:
                file_match = _re.search(r"[^\s'\"]+\.(?:json|ya?ml)", query)
                if file_match:
                    candidate = file_match.group(0)
                    candidate_path = Path(working_dir) / candidate if not Path(candidate).is_absolute() else Path(candidate)
                    if candidate_path.exists():
                        source = str(candidate_path)
                    elif Path(candidate).exists():
                        source = str(Path(candidate).resolve())
                    else:
                        source = candidate
            base_url_match = _re.search(r"https?://[^/\s]+", source)
            state["test_openapi_source"] = source
            state["test_base_url"] = base_url_match.group(0) if base_url_match else "http://localhost:8000"
            state["test_output_dir"] = working_dir
            state["test_language"] = "typescript" if (
                "typescript" in text or " ts " in text or ".ts " in text or ".tsx" in text or "jest" in text or "vitest" in text
            ) else "python"
            state["test_run_after_generate"] = True
            state["test_timeout"] = 120
            _emit_status(args, f"[test] generating API tests for {source or 'URL from query'}")
            state = api_test_agent(state)

        elif intent_type == "unit_test":
            import re as _re
            file_matches = _re.findall(r"[^\s'\"]+\.(?:py|ts|tsx|js|jsx)", query)
            if not file_matches:
                cwd_files = [str(p) for p in Path(working_dir).rglob("*.py") if not any(part in _IGNORE_DIRS_CLI for part in p.parts)][:5]
                file_matches = cwd_files
            state["test_source_files"] = file_matches or []
            state["test_output_dir"] = working_dir
            state["test_language"] = "typescript" if (
                "typescript" in text or " ts " in text or ".ts " in text or ".tsx" in text or "jest" in text or "vitest" in text
                or any(str(f).endswith((".ts", ".tsx", ".js", ".jsx")) for f in file_matches)
            ) else "python"
            _emit_status(args, f"[test] generating unit tests for {file_matches[:3] if file_matches else 'project files'}")
            state = unit_test_agent(state)

        elif intent_type == "run_tests":
            state["test_working_directory"] = working_dir
            state["test_timeout"] = 300
            _emit_status(args, "[test] running test suite...")
            state = test_runner_agent(state)

        elif intent_type == "fix_tests":
            state["test_working_directory"] = working_dir
            state["test_fix_max_iterations"] = 3
            state["test_timeout"] = 300
            _emit_status(args, "[test] running and fixing test suite...")
            state = test_fix_agent(state)

        elif intent_type == "regression_test":
            state["test_bug_description"] = query
            state["test_output_dir"] = working_dir
            state["test_language"] = "typescript" if (
                "typescript" in text or " ts " in text or ".ts " in text or ".tsx" in text or "jest" in text or "vitest" in text
            ) else "python"
            _emit_status(args, "[test] writing regression test...")
            state = regression_test_agent(state)

    except Exception as exc:
        print(style.fail(f"[test] error: {exc}"))
        return 1

    report = state.get("test_report", {})

    if emit_json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return 0 if report.get("status") in ("PASS", "generated") else 1

    print()
    print(_render_test_report(report, style))
    print()

    artifacts = state.get("a2a", {}).get("artifacts", [])
    for art in artifacts[-1:]:
        meta = art.get("metadata", {})
        if meta.get("json_report"):
            print(style.muted(f"  Report: {meta['json_report']}"))
        if meta.get("md_summary"):
            print(style.muted(f"  Summary: {meta['md_summary']}"))

    ok = report.get("status") in ("PASS", "generated") or bool(state.get("test_passed"))
    return 0 if ok else 1


_IGNORE_DIRS_CLI = {"node_modules", ".git", ".venv", "venv", "__pycache__", ".pytest_cache", "dist", "build", ".next"}


def _is_project_code_request(query: str) -> bool:
    text = str(query or "").lower()
    markers = [
        "my project",
        "current project",
        "codebase",
        "repo",
        "repository",
        "production ready",
        "production-ready",
        "analyze my code",
        "analyze project",
    ]
    return any(marker in text for marker in markers)


def _looks_like_project_root(path_value: str) -> bool:
    root = Path(path_value)
    markers = [
        "pyproject.toml",
        "requirements.txt",
        "package.json",
        "Dockerfile",
        "docker-compose.yml",
        ".git",
    ]
    return any((root / marker).exists() for marker in markers)


def _extract_requested_page_count(query: str) -> int:
    text = str(query or "").lower()
    if not text.strip():
        return 0
    matches = [int(item) for item in re.findall(r"\b(\d{1,3})\s*(?:-| )?\s*pages?\b", text)]
    return max(matches) if matches else 0


def _query_requests_long_document(query: str) -> bool:
    page_count = _extract_requested_page_count(query)
    if page_count >= 20:
        return True
    text = str(query or "").lower()
    markers = (
        "deep research",
        "deep-research",
        "deep research report",
        "long document",
        "long-form",
        "long form",
        "whitepaper",
        "monograph",
        "exhaustive report",
    )
    return any(marker in text for marker in markers)


def _normalize_drive_paths(raw_values: list[str] | None) -> list[str]:
    deduped = []
    seen = set()
    for raw in raw_values or []:
        for part in str(raw or "").split(","):
            value = part.strip()
            if not value:
                continue
            if value in seen:
                continue
            seen.add(value)
            deduped.append(value)
    return deduped


def _normalize_url_inputs(raw_values: list[str] | None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in raw_values or []:
        for part in re.split(r"[\n,]", str(raw or "")):
            value = str(part or "").strip()
            if not value or not re.match(r"^https?://", value, flags=re.IGNORECASE):
                continue
            if value in seen:
                continue
            seen.add(value)
            deduped.append(value)
    return deduped


def _parse_research_formats(raw_value: str | None) -> list[str]:
    allowed = {"pdf", "docx", "html", "md"}
    formats: list[str] = []
    seen: set[str] = set()
    for item in str(raw_value or "").split(","):
        value = item.strip().lower()
        if not value or value not in allowed or value in seen:
            continue
        seen.add(value)
        formats.append(value)
    return formats


def _configured_working_dir() -> str:
    configured = str(os.getenv("KENDR_WORKING_DIR", "")).strip()
    if configured:
        return configured
    try:
        snapshot = get_setup_component_snapshot("core_runtime")
        return str(snapshot.get("values", {}).get("KENDR_WORKING_DIR", "")).strip()
    except Exception:
        return ""


def _resolved_cli_input_path(raw_path: str, base_directory: str = "") -> Path:
    path = Path(str(raw_path or "").strip()).expanduser()
    if not path.is_absolute():
        root = Path(base_directory).expanduser() if str(base_directory or "").strip() else Path.cwd()
        path = root / path
    return path.resolve()


def _workflow_setup_snapshot() -> dict:
    try:
        registry = build_registry()
        return build_setup_snapshot(registry.agent_cards())
    except Exception:
        return {}


def _agent_setup_status(snapshot: dict, agent_name: str) -> dict:
    agents = snapshot.get("agents", {})
    status = agents.get(agent_name, {}) if isinstance(agents, dict) else {}
    return status if isinstance(status, dict) else {}


def _explicit_superrag_request(args: argparse.Namespace) -> bool:
    return any(
        [
            str(args.superrag_mode or "").strip(),
            str(args.superrag_session or "").strip(),
            bool(args.superrag_new_session),
            str(args.superrag_session_title or "").strip(),
            list(args.superrag_path or []),
            list(args.superrag_url or []),
            str(args.superrag_db_url or "").strip(),
            str(args.superrag_db_schema or "").strip(),
            bool(args.superrag_onedrive),
            str(args.superrag_onedrive_path or "").strip(),
            str(args.superrag_chat or "").strip(),
            int(args.superrag_top_k or 0) > 0,
        ]
    )


def _explicit_deep_research_request(args: argparse.Namespace, query: str) -> bool:
    if any(
        [
            str(getattr(args, "research_model", "") or "").strip(),
            str(getattr(args, "research_instructions", "") or "").strip(),
            int(args.research_max_wait_seconds or 0) > 0,
            int(args.research_poll_interval_seconds or 0) > 0,
            int(args.research_max_tool_calls or 0) > 0,
            int(args.research_max_output_tokens or 0) > 0,
            bool(getattr(args, "no_web_search", False)),
            list(getattr(args, "deep_research_link", []) or []),
        ]
    ):
        return True
    text = str(query or "").lower()
    markers = (
        "deep research",
        "deep-research",
        "in-depth research",
        "comprehensive research",
        "source-backed research",
        "with citations",
    )
    return any(marker in text for marker in markers)


def _explicit_coding_request(args: argparse.Namespace, query: str) -> bool:
    if any(
        [
            list(getattr(args, "coding_context_file", []) or []),
            str(getattr(args, "coding_write_path", "") or "").strip(),
            str(getattr(args, "coding_instructions", "") or "").strip(),
            str(getattr(args, "coding_language", "") or "").strip(),
            str(getattr(args, "coding_backend", "") or "").strip(),
        ]
    ):
        return True
    text = str(query or "").lower()
    build_markers = (
        "master_coding_agent",
        "production-ready saas",
        "build a saas",
        "build a project",
        "create a project",
        "scaffold a project",
        "build an app",
        "create an app",
        "codebase audit",
        "analyze my code",
        "analyze my project",
    )
    return _is_project_code_request(query) or any(marker in text for marker in build_markers)


def _explicit_local_command_request(args: argparse.Namespace, query: str) -> bool:
    if any(
        [
            str(getattr(args, "os_command", "") or "").strip(),
            str(getattr(args, "os_shell", "") or "").strip(),
            str(getattr(args, "os_working_directory", "") or "").strip(),
            str(getattr(args, "target_os", "") or "").strip(),
            int(getattr(args, "os_timeout", 0) or 0) > 0,
        ]
    ):
        return True
    text = str(query or "").lower()
    markers = (
        "run this command",
        "execute this command",
        "run a command",
        "execute a command",
        "run in terminal",
        "execute in terminal",
        "run this locally",
        "shell command",
        "powershell command",
        "bash command",
    )
    return any(marker in text for marker in markers)


def _require_agent_available_for_workflow(snapshot: dict, agent_name: str, workflow_name: str) -> None:
    available_agents = set(snapshot.get("available_agents", []) or [])
    if agent_name in available_agents:
        return
    status = _agent_setup_status(snapshot, agent_name)
    missing = status.get("missing_services", []) if isinstance(status, dict) else []
    detail = ", ".join(str(item) for item in missing if str(item).strip()) or "see setup status for missing requirements"
    summary = str(snapshot.get("summary_text", "") or "").strip()
    message = (
        f"{workflow_name} is not currently routing-eligible. Missing setup: {detail}. "
        "Run `kendr setup status` to see the required services."
    )
    if summary:
        message += f"\n{summary}"
    raise SystemExit(message)


def _validate_run_workflows(
    args: argparse.Namespace,
    query: str,
    resolved_working_dir: str,
    drive_paths: list[str],
    superrag_paths: list[str],
) -> dict:
    missing_drive = [str(_resolved_cli_input_path(item)) for item in drive_paths if not _resolved_cli_input_path(item).exists()]
    if missing_drive:
        raise SystemExit("One or more --drive paths do not exist:\n- " + "\n- ".join(missing_drive))

    deep_research_links = _normalize_url_inputs(list(getattr(args, "deep_research_link", []) or []))
    if bool(getattr(args, "no_web_search", False)) and deep_research_links:
        raise SystemExit(
            "--no-web-search cannot be combined with --deep-research-link.\n"
            "Disable web search only when the report should rely strictly on local files/folders."
        )
    if bool(getattr(args, "no_web_search", False)) and not drive_paths:
        raise SystemExit(
            "--no-web-search requires local sources via --drive or --deep-research-path.\n"
            "Add one or more local files/folders before requesting a local-only deep research run."
        )

    missing_superrag_paths = [
        str(_resolved_cli_input_path(item))
        for item in superrag_paths
        if not _resolved_cli_input_path(item, resolved_working_dir).exists()
    ]
    if missing_superrag_paths:
        raise SystemExit("One or more --superrag-path values do not exist:\n- " + "\n- ".join(missing_superrag_paths))

    if str(args.superrag_mode or "").strip().lower() in {"chat", "switch", "status"} and not str(args.superrag_session or "").strip():
        raise SystemExit(
            "superRAG chat/switch/status requires --superrag-session.\n"
            "Example: kendr run --superrag-mode chat --superrag-session product_ops_kb --superrag-chat \"What changed?\""
        )

    if bool(args.privileged_approved) and not str(args.privileged_approval_note or "").strip():
        raise SystemExit("Privileged execution requires --privileged-approval-note with a ticket or approval reference.")

    if _explicit_local_command_request(args, query):
        if not bool(args.privileged_approved):
            raise SystemExit(
                "Local command execution requires explicit approval.\n"
                "Re-run with --privileged-approved --privileged-approval-note \"TICKET-123\"."
            )

    needs_snapshot = any(
        [
            _explicit_superrag_request(args),
            _explicit_deep_research_request(args, query),
            _explicit_coding_request(args, query),
        ]
    )
    snapshot = _workflow_setup_snapshot() if needs_snapshot else {}

    if _explicit_superrag_request(args):
        _require_agent_available_for_workflow(snapshot, "superrag_agent", "superRAG workflow")

    if _explicit_deep_research_request(args, query):
        _require_agent_available_for_workflow(snapshot, "deep_research_agent", "Deep research workflow")

    if _explicit_coding_request(args, query):
        available = set(snapshot.get("available_agents", []) or [])
        if "coding_agent" not in available and "master_coding_agent" not in available:
            summary = str(snapshot.get("summary_text", "") or "").strip()
            message = (
                "Coding builder workflow is not currently routing-eligible. "
                "Configure OpenAI or install the Codex CLI, then re-run `kendr setup status`."
            )
            if summary:
                message += f"\n{summary}"
            raise SystemExit(message)

    return snapshot


def _workflow_status_message(args: argparse.Namespace, query: str, base_ingest_payload: dict) -> str:
    items: list[str] = []
    if base_ingest_payload.get("local_drive_paths"):
        items.append(f"local-drive(paths={len(base_ingest_payload['local_drive_paths'])})")
    if base_ingest_payload.get("superrag_mode"):
        session = str(base_ingest_payload.get("superrag_session_id", "") or "").strip()
        session_hint = f", session={session}" if session else ""
        items.append(f"superrag(mode={base_ingest_payload['superrag_mode']}{session_hint})")
    if _explicit_deep_research_request(args, query):
        items.append(f"deep-research(model={str(base_ingest_payload.get('research_model') or 'default')})")
    if _explicit_coding_request(args, query):
        items.append("coding-builder")
    if _explicit_local_command_request(args, query):
        shell_name = str(base_ingest_payload.get("shell") or "auto")
        items.append(f"local-command(shell={shell_name})")
    return ", ".join(items)


def _truthy(value: str | bool | None) -> bool:
    if isinstance(value, bool):
        return value
    raw = str(value or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def _tool_available(commands: list[str]) -> bool:
    return any(shutil.which(cmd) is not None for cmd in commands)


def _run_install_command(command: list[str]) -> tuple[bool, str]:
    try:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
    except Exception as exc:
        return False, str(exc)
    if completed.returncode == 0:
        return True, (completed.stdout or "").strip()
    detail = (completed.stderr or completed.stdout or "").strip()
    return False, detail


def _kendr_home_dir() -> Path:
    raw = os.getenv("KENDR_HOME", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".kendr").resolve()


def _active_scripts_dir() -> Path:
    return Path(sys.executable).resolve().parent


def _install_dependency_check_from_release_zip() -> tuple[bool, str]:
    try:
        tools_root = _kendr_home_dir() / "tools" / "dependency-check"
        tools_root.mkdir(parents=True, exist_ok=True)
        zip_path = tools_root / "dependency-check-release.zip"
        extract_root = tools_root / "dist"
        if extract_root.exists():
            shutil.rmtree(extract_root)
        extract_root.mkdir(parents=True, exist_ok=True)

        url = "https://github.com/dependency-check/DependencyCheck/releases/latest/download/dependency-check-release.zip"
        urllib.request.urlretrieve(url, zip_path)  # nosec B310 - trusted GitHub release URL configured by tool setup flow

        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(extract_root)

        candidates = list(extract_root.glob("dependency-check*/bin/dependency-check.bat"))
        if not candidates:
            return False, "Downloaded release but dependency-check.bat was not found after extraction."
        bat_path = candidates[0].resolve()

        scripts_dir = _active_scripts_dir()
        scripts_dir.mkdir(parents=True, exist_ok=True)
        shim_path = scripts_dir / "dependency-check.cmd"
        shim_path.write_text(
            "@echo off\r\n"
            f"call \"{str(bat_path)}\" %*\r\n",
            encoding="utf-8",
        )
        return True, f"Installed from release ZIP. Shim created at {shim_path}"
    except Exception as exc:
        return False, str(exc)


def _install_candidates_for_tool(tool_name: str) -> list[list[str]]:
    if os.name == "nt":
        commands: list[list[str]] = []
        if shutil.which("choco"):
            choco_pkgs = {
                "nmap": ["nmap"],
                "zap": ["zap", "owasp-zap"],
                "dependency-check": ["dependency-check", "owasp-dependency-check", "owaspdependencycheck"],
            }.get(tool_name, [])
            for pkg in choco_pkgs:
                commands.append(["choco", "install", pkg, "-y"])
        if shutil.which("winget"):
            winget_pkgs = {
                "nmap": ["Insecure.Nmap"],
                "zap": ["OWASP.ZAP"],
                "dependency-check": ["OWASP.DependencyCheck", "DependencyCheck.DependencyCheck"],
            }.get(tool_name, [])
            for winget_pkg in winget_pkgs:
                commands.append(
                    [
                        "winget",
                        "install",
                        "--id",
                        winget_pkg,
                        "--silent",
                        "--accept-package-agreements",
                        "--accept-source-agreements",
                    ]
                )
        return commands

    if sys.platform == "darwin":
        if not shutil.which("brew"):
            return []
        mapping = {
            "nmap": [["brew", "install", "nmap"]],
            "zap": [["brew", "install", "--cask", "owasp-zap"]],
            "dependency-check": [["brew", "install", "dependency-check"]],
        }
        return mapping.get(tool_name, [])

    commands: list[list[str]] = []
    if shutil.which("apt-get"):
        apt_pkg = {
            "nmap": "nmap",
            "zap": "zaproxy",
            "dependency-check": "dependency-check",
        }.get(tool_name)
        if apt_pkg:
            commands.append(["apt-get", "update"])
            commands.append(["apt-get", "install", "-y", apt_pkg])
    if shutil.which("dnf"):
        dnf_pkg = {
            "nmap": "nmap",
            "zap": "zaproxy",
            "dependency-check": "dependency-check",
        }.get(tool_name)
        if dnf_pkg:
            commands.append(["dnf", "install", "-y", dnf_pkg])
    if shutil.which("yum"):
        yum_pkg = {
            "nmap": "nmap",
            "zap": "zaproxy",
            "dependency-check": "dependency-check",
        }.get(tool_name)
        if yum_pkg:
            commands.append(["yum", "install", "-y", yum_pkg])
    return commands


def _ensure_playwright_chromium() -> None:
    if shutil.which("playwright"):
        return
    _run_install_command([sys.executable, "-m", "playwright", "install", "chromium"])


def _auto_install_security_tools_if_needed(*, enabled: bool) -> None:
    if not enabled:
        return

    required_tools = [
        ("nmap", ["nmap"]),
        ("zap", ["zap-baseline.py", "owasp-zap", "zaproxy"]),
        ("dependency-check", ["dependency-check"]),
    ]
    missing = [(name, checks) for name, checks in required_tools if not _tool_available(checks)]
    if not missing:
        return

    print("Security tooling check: missing tools detected. Attempting automatic install...")
    for tool_name, checks in missing:
        install_errors: list[str] = []
        installed = False
        for command in _install_candidates_for_tool(tool_name):
            ok, detail = _run_install_command(command)
            if ok and _tool_available(checks):
                installed = True
                break
            if detail:
                install_errors.append(f"{' '.join(command)} -> {detail}")
        if not installed and os.name == "nt" and tool_name == "dependency-check":
            ok, detail = _install_dependency_check_from_release_zip()
            if ok and _tool_available(checks):
                installed = True
            elif detail:
                install_errors.append(f"release-zip-fallback -> {detail}")
        if installed:
            print(f"[security-tools] Installed: {tool_name}")
        else:
            print(f"[security-tools] Could not auto-install: {tool_name}")
            for item in install_errors[-3:]:
                print(f"  - {item}")
            print("  Continue with partial tooling or install manually from setup guidance.")

    _ensure_playwright_chromium()


def _build_parser(style: _CliStyle) -> tuple[argparse.ArgumentParser, dict[str, argparse.ArgumentParser]]:
    parser = argparse.ArgumentParser(
        prog="kendr",
        description=(
            f"{_cli_banner(style)}\n\n"
            "Plugin-driven multi-agent runtime and orchestration surface."
        ),
        epilog=(
            f"{style.heading('Examples')}\n"
            "  kendr run \"Summarize this repository\" --max-steps 12\n"
            "  kendr generate \"a FastAPI todo API with PostgreSQL\" --auto-approve\n"
            "  kendr research \"transformer architectures 2024\" --sources arxiv,openalex --pages 20\n"
            "  kendr agents list\n"
            "  kendr gateway start\n"
            "  kendr status\n"
            "  kendr help setup\n\n"
            f"{style.heading('Docs')}\n"
            "  README.md"
        ),
        formatter_class=_KendrHelpFormatter,
    )
    parser.add_argument("--no-color", action="store_true", help="Disable ANSI colors in CLI output.")
    parser.add_argument(
        "--log-level",
        choices=["silent", "fatal", "error", "warn", "info", "debug", "trace"],
        default="",
        help="Global log verbosity hint for runtime services.",
    )
    parser.add_argument("-V", "--version", action="version", version=f"%(prog)s {_cli_version()}")
    subparsers = parser.add_subparsers(dest="command", title=style.heading("Commands"), metavar="command")
    command_parsers: dict[str, argparse.ArgumentParser] = {}

    run_parser = subparsers.add_parser("run", help="Run the orchestrator for a single query.")
    command_parsers["run"] = run_parser
    run_parser.add_argument("query", nargs="*", help="User query to process.")
    run_parser.add_argument("--max-steps", type=int, default=20, help="Maximum orchestration steps.")
    run_parser.add_argument(
        "--background", "-b",
        action="store_true",
        help="Submit run and exit immediately (returns run_id). Check status with: kendr status <run_id>",
    )
    run_parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve blueprint and plan gates (no interactive approval prompts).",
    )
    run_parser.add_argument(
        "--skip-reviews",
        action="store_true",
        help="Skip reviewer agent checks between steps.",
    )
    run_parser.add_argument(
        "--max-step-revisions",
        type=int,
        default=0,
        help="Override max reviewer revisions per step (0 keeps default).",
    )
    run_parser.add_argument(
        "--deep-research",
        "--long-document",
        dest="long_document",
        action="store_true",
        help="Force deep research document workflow (tiered research + staged synthesis + exports).",
    )
    run_parser.add_argument(
        "--deep-research-pages",
        "--long-document-pages",
        type=int,
        dest="long_document_pages",
        default=0,
        help="Target page count for deep research mode (for example 50).",
    )
    run_parser.add_argument(
        "--deep-research-sections",
        "--long-document-sections",
        type=int,
        dest="long_document_sections",
        default=0,
        help="Optional explicit section count for deep research mode.",
    )
    run_parser.add_argument(
        "--deep-research-section-pages",
        "--long-document-section-pages",
        type=int,
        dest="long_document_section_pages",
        default=0,
        help="Approximate pages per section in deep research mode.",
    )
    run_parser.add_argument(
        "--deep-research-title",
        "--long-document-title",
        dest="long_document_title",
        default="",
        help="Optional report title override for deep research mode.",
    )
    run_parser.add_argument(
        "--deep-research-no-collect-sources",
        "--long-document-no-collect-sources",
        dest="long_document_no_collect_sources",
        action="store_true",
        help="Skip the pre-collection evidence bank step for deep research mode.",
    )
    run_parser.add_argument(
        "--deep-research-no-section-search",
        "--long-document-no-section-search",
        dest="long_document_no_section_search",
        action="store_true",
        help="Skip per-section web search results for deep research mode.",
    )
    run_parser.add_argument(
        "--deep-research-section-search-results",
        "--long-document-section-search-results",
        type=int,
        dest="long_document_section_search_results",
        default=0,
        help="Number of web search results to gather per section in deep research mode.",
    )
    run_parser.add_argument(
        "--deep-research-no-visuals",
        "--long-document-no-visuals",
        dest="long_document_no_visuals",
        action="store_true",
        help="Skip generating extra tables/flowcharts for deep research sections.",
    )
    run_parser.add_argument(
        "--format",
        default="",
        help="Comma-separated deep research output formats: pdf,docx,html,md.",
    )
    run_parser.add_argument(
        "--cite",
        default="",
        help="Deep research citation style: apa, mla, chicago, ieee, vancouver, harvard.",
    )
    run_parser.add_argument(
        "--no-plagiarism",
        action="store_true",
        help="Skip the deep research plagiarism/reuse check.",
    )
    run_parser.add_argument(
        "--date-range",
        default="",
        help="Deep research date range hint (for example 1y, 5y, 2020-2025).",
    )
    run_parser.add_argument(
        "--max-sources",
        type=int,
        default=0,
        help="Cap the total number of sources gathered for deep research mode.",
    )
    run_parser.add_argument(
        "--checkpoint",
        action="store_true",
        help="Enable checkpoint markers for deep research mode.",
    )
    run_parser.add_argument(
        "--no-web-search",
        action="store_true",
        help="Disable internet/web search for deep research and use only local files/folders.",
    )
    run_parser.add_argument(
        "--deep-research-link",
        action="append",
        default=[],
        help="Explicit URL to extract as part of deep research. Repeat for multiple links.",
    )
    run_parser.add_argument(
        "--deep-research-path",
        "--drive",
        dest="drive",
        action="append",
        default=[],
        help="Local folder or file path for deep research ingestion. Repeat for multiple paths.",
    )
    run_parser.add_argument(
        "--drive-min-files",
        type=int,
        default=0,
        help="Minimum file count expected for deep research reports before prompting for confirmation (0 uses auto heuristic).",
    )
    run_parser.add_argument(
        "--drive-max-files",
        type=int,
        default=0,
        help="Maximum files to process from drive inputs (0 keeps default).",
    )
    run_parser.add_argument(
        "--drive-extensions",
        default="",
        help="Optional comma-separated extension allowlist (for example: pdf,docx,xlsx,pptx,csv,txt,png).",
    )
    run_parser.add_argument(
        "--drive-no-recursive",
        action="store_true",
        help="Disable recursive traversal of drive folders.",
    )
    run_parser.add_argument(
        "--drive-include-hidden",
        action="store_true",
        help="Include hidden files and folders when scanning drive paths.",
    )
    run_parser.add_argument(
        "--codebase",
        action="store_true",
        help="Analyze an existing codebase before planning and modifications.",
    )
    run_parser.add_argument(
        "--codebase-path",
        default="",
        help="Path to the existing project when using --codebase (defaults to working directory).",
    )
    run_parser.add_argument(
        "--codebase-max-files",
        type=int,
        default=0,
        help="Maximum files to scan in codebase mode (0 uses 1000).",
    )
    run_parser.add_argument(
        "--drive-disable-image-ocr",
        action="store_true",
        help="Disable OCR for images discovered in drive paths.",
    )
    run_parser.add_argument(
        "--drive-ocr-instruction",
        default="",
        help="Optional OCR instruction override for image extraction in drive mode.",
    )
    run_parser.add_argument(
        "--drive-no-memory-index",
        action="store_true",
        help="Disable vector-memory indexing of local-drive extraction summaries.",
    )
    run_parser.add_argument(
        "--drive-auto-generate-extension-handlers",
        action="store_true",
        help=(
            "Enable optional dynamic agent generation for unsupported file extensions "
            "detected during local-drive scan (off by default)."
        ),
    )
    run_parser.add_argument(
        "--superrag-mode",
        choices=["build", "chat", "switch", "list", "status"],
        default="",
        help="Run superRAG in a specific mode.",
    )
    run_parser.add_argument(
        "--superrag-session",
        default="",
        help="superRAG session id to reuse or switch to.",
    )
    run_parser.add_argument(
        "--superrag-new-session",
        action="store_true",
        help="Force a new superRAG session id for build mode.",
    )
    run_parser.add_argument(
        "--superrag-session-title",
        default="",
        help="Optional title for the target superRAG session.",
    )
    run_parser.add_argument(
        "--superrag-path",
        action="append",
        default=[],
        help="Local path to ingest into superRAG. Can be repeated.",
    )
    run_parser.add_argument(
        "--superrag-url",
        action="append",
        default=[],
        help="Seed URL to crawl into superRAG. Can be repeated.",
    )
    run_parser.add_argument(
        "--superrag-db-url",
        default="",
        help="Database URL for schema and row-sample ingestion into superRAG.",
    )
    run_parser.add_argument(
        "--superrag-db-schema",
        default="",
        help="Optional database schema to target for superRAG DB ingestion.",
    )
    run_parser.add_argument(
        "--superrag-onedrive-path",
        default="",
        help="Optional OneDrive folder path to ingest (Microsoft Graph).",
    )
    run_parser.add_argument(
        "--superrag-onedrive",
        action="store_true",
        help="Enable OneDrive ingestion for superRAG.",
    )
    run_parser.add_argument(
        "--superrag-chat",
        default="",
        help="Question to ask in superRAG chat mode.",
    )
    run_parser.add_argument(
        "--superrag-top-k",
        type=int,
        default=0,
        help="Top-K vector matches used in superRAG chat mode (0 keeps defaults).",
    )
    run_parser.add_argument(
        "--research-max-wait-seconds",
        type=int,
        default=0,
        help="Max wait per deep-research call before timeout handling (0 keeps defaults).",
    )
    run_parser.add_argument(
        "--research-poll-interval-seconds",
        type=int,
        default=0,
        help="Polling interval for deep-research background status checks (0 keeps defaults).",
    )
    run_parser.add_argument(
        "--research-max-tool-calls",
        type=int,
        default=0,
        help="Maximum web tool calls per deep-research pass (0 keeps defaults).",
    )
    run_parser.add_argument(
        "--research-max-output-tokens",
        type=int,
        default=0,
        help="Optional output token cap per deep-research pass (0 keeps defaults).",
    )
    run_parser.add_argument(
        "--research-model",
        default="",
        help="Override the deep-research model for this run.",
    )
    run_parser.add_argument(
        "--research-instructions",
        default="",
        help="Extra instructions passed into the deep-research workflow.",
    )
    run_parser.add_argument(
        "--coding-context-file",
        action="append",
        default=[],
        help="Project file to load as coding context. Can be repeated.",
    )
    run_parser.add_argument(
        "--coding-write-path",
        default="",
        help="Target file path for coding output when a coding workflow writes code.",
    )
    run_parser.add_argument(
        "--coding-instructions",
        default="",
        help="Extra coding instructions for coding and master-coding workflows.",
    )
    run_parser.add_argument(
        "--coding-language",
        default="",
        help="Optional coding language hint for code generation.",
    )
    run_parser.add_argument(
        "--coding-backend",
        choices=["auto", "codex-cli", "openai-sdk", "responses-http"],
        default="",
        help="Preferred backend for coding generation.",
    )
    run_parser.add_argument(
        "--os-command",
        default="",
        help="Execute one explicit local command through os_agent.",
    )
    run_parser.add_argument(
        "--os-shell",
        default="",
        help="Preferred shell for local command execution (for example powershell, bash, cmd).",
    )
    run_parser.add_argument(
        "--os-timeout",
        type=int,
        default=0,
        help="Timeout in seconds for local command execution (0 keeps agent default).",
    )
    run_parser.add_argument(
        "--os-working-directory",
        default="",
        help="Working directory for local command execution.",
    )
    run_parser.add_argument(
        "--target-os",
        default="",
        help="Target OS hint for local command execution (linux, macos, windows).",
    )
    run_parser.add_argument("--json", action="store_true", help="Emit the final state as JSON.")
    run_parser.add_argument("--quiet", action="store_true", help="Suppress live progress messages.")
    run_parser.add_argument("--privileged-mode", action="store_true", help="Enable privileged policy controls for this run.")
    run_parser.add_argument(
        "--privileged-approved",
        action="store_true",
        help="Confirm explicit operator approval for privileged actions.",
    )
    run_parser.add_argument(
        "--privileged-approval-note",
        default="",
        help="Required approval note/ticket for privileged execution.",
    )
    run_parser.add_argument("--privileged-read-only", action="store_true", help="Force read-only execution for privileged runs.")
    run_parser.add_argument("--privileged-allow-root", action="store_true", help="Allow sudo/root escalation if needed.")
    run_parser.add_argument(
        "--privileged-allow-destructive",
        action="store_true",
        help="Allow destructive operations (blocked by default).",
    )
    run_parser.add_argument("--privileged-enable-backup", action="store_true", help="Create snapshots before mutating actions.")
    run_parser.add_argument(
        "--privileged-allowed-path",
        action="append",
        default=[],
        help="Allowed path root for privileged file/command scope. Can be repeated.",
    )
    run_parser.add_argument(
        "--privileged-allowed-domain",
        action="append",
        default=[],
        help="Allowed network domain scope for privileged runs. Can be repeated.",
    )
    run_parser.add_argument(
        "--kill-switch-file",
        default="",
        help="If this file exists, runtime stops before running additional agent steps.",
    )
    run_parser.add_argument(
        "--security-authorized",
        action="store_true",
        help="Confirm you are explicitly authorized to run defensive security assessment tasks on the provided target.",
    )
    run_parser.add_argument(
        "--security-target-url",
        default="",
        help="Optional explicit target URL for security workflows.",
    )
    run_parser.add_argument(
        "--security-authorization-note",
        default="",
        help="Required for security workflows. Ticket/approval reference proving assessment authorization.",
    )
    run_parser.add_argument(
        "--security-scan-profile",
        choices=sorted(SECURITY_SCAN_PROFILES),
        default="",
        help="Security scan depth profile: baseline, standard, deep, extensive.",
    )
    run_parser.add_argument(
        "--no-auto-install-security-tools",
        action="store_true",
        help="Disable automatic installation of missing security tools for security workflows.",
    )
    run_parser.add_argument(
        "--communication-authorized",
        action="store_true",
        help="Confirm you are authorized to access the communication channels for this run.",
    )
    run_parser.add_argument(
        "--communication-lookback-hours",
        type=int,
        default=0,
        help="Lookback window in hours for the communication summary digest (default: 24).",
    )
    run_parser.add_argument(
        "--whatsapp-to",
        default="",
        help="Recipient phone number in E.164 format for whatsapp_send_message_agent.",
    )
    run_parser.add_argument(
        "--whatsapp-message",
        default="",
        help="Plain text message body for whatsapp_send_message_agent.",
    )
    run_parser.add_argument(
        "--whatsapp-template",
        default="",
        help="WhatsApp template name for whatsapp_send_message_agent.",
    )
    run_parser.add_argument(
        "--whatsapp-template-language",
        default="",
        help="Language code for the WhatsApp template (default: en_US).",
    )
    run_parser.add_argument(
        "--working-directory",
        default="",
        help="Working folder for task outputs and intermediate artifacts.",
    )
    run_parser.add_argument(
        "--current-folder",
        action="store_true",
        help="Use the current terminal folder as working directory for this run.",
    )
    run_parser.add_argument("--channel", default="", help="Channel id for conversational session continuity (e.g. webchat, slack).")
    run_parser.add_argument("--workspace-id", default="", help="Workspace id used in session routing.")
    run_parser.add_argument("--sender-id", default="", help="Sender/user id used for session routing.")
    run_parser.add_argument("--chat-id", default="", help="Chat/thread id used for session routing.")
    run_parser.add_argument("--session-key", default="", help="Explicit session key (channel:workspace:chat:scope).")
    run_parser.add_argument("--new-session", action="store_true", help="Force creation of a fresh session for this run.")
    run_parser.add_argument(
        "--sources",
        default="",
        help=(
            "Comma-separated list of research sources for the multi-source pipeline. "
            "Supported: web, arxiv (alias: papers, academic), reddit (alias: social), "
            "scholar, patents (alias: patent), openalex, local (requires --local-drive-paths). "
            "Example: --sources web,papers,reddit or --sources local,openalex"
        ),
    )
    run_parser.add_argument(
        "--pages",
        type=int,
        default=0,
        help=(
            "Target page count for deep research report output. "
            "Implies --deep-research mode. Example: --pages 50"
        ),
    )
    run_parser.add_argument(
        "--dev",
        action="store_true",
        help=(
            "Activate the end-to-end dev pipeline mode: blueprint → scaffold → "
            "build → test → verify (with auto-fix) → zip export. "
            "Equivalent to 'kendr generate' with full pipeline orchestration."
        ),
    )
    run_parser.add_argument(
        "--stack",
        default="",
        dest="dev_stack",
        help=(
            "Optional tech stack template for dev pipeline mode (--dev). "
            "Available: fastapi_postgres, fastapi_react_postgres, nextjs_prisma_postgres, "
            "express_prisma_postgres, mern_microservices_mongodb, pern_postgres, nextjs_static_site, "
            "django_react_postgres, custom_freeform. "
            "Leave blank for LLM-driven stack selection."
        ),
    )
    run_parser.add_argument(
        "--dev-skip-tests",
        action="store_true",
        help="Skip test generation/execution in dev pipeline mode (--dev).",
    )
    run_parser.add_argument(
        "--dev-skip-devops",
        action="store_true",
        help="Skip Dockerfile/CI/CD generation in dev pipeline mode (--dev).",
    )
    run_parser.add_argument(
        "--dev-max-fix-rounds",
        type=int,
        default=3,
        help="Max auto-fix rounds when verifier fails in dev pipeline mode (default 3).",
    )

    agent_list = subparsers.add_parser("agents", help="List or inspect discovered agents.")
    command_parsers["agents"] = agent_list
    agent_list.add_argument("action", choices=["list", "show"], nargs="?", default="list")
    agent_list.add_argument("name", nargs="?")
    agent_list.add_argument("--plugin", default="", help="Filter list by plugin name.")
    agent_list.add_argument("--contains", default="", help="Filter agent name/description by substring.")
    agent_list.add_argument("--limit", type=int, default=0, help="Limit number of listed agents.")
    agent_list.add_argument("--json", action="store_true")

    plugin_list = subparsers.add_parser("plugins", help="List discovered plugins.")
    command_parsers["plugins"] = plugin_list
    plugin_list.add_argument("action", choices=["list"], nargs="?", default="list")
    plugin_list.add_argument("--kind", default="", help="Filter plugins by kind.")
    plugin_list.add_argument("--contains", default="", help="Filter plugin name/description by substring.")
    plugin_list.add_argument("--limit", type=int, default=0, help="Limit number of listed plugins.")
    plugin_list.add_argument("--json", action="store_true")

    gateway_parser = subparsers.add_parser("gateway", help="Run or control the HTTP gateway server.")
    command_parsers["gateway"] = gateway_parser
    gateway_parser.add_argument(
        "action",
        nargs="?",
        choices=["serve", "start", "stop", "restart", "status"],
        default="serve",
        help="Gateway action. 'serve' runs in foreground.",
    )
    gateway_parser.add_argument("--json", action="store_true", help="Emit machine-readable status output.")
    web_parser = subparsers.add_parser("web", help="Launch the Kendr Web UI (alias for 'kendr ui').")
    web_parser.add_argument("--port", type=int, default=0, help="Override port (default: KENDR_UI_PORT or 2151).")
    web_parser.add_argument("--host", default="", help="Override bind host.")
    web_parser.add_argument("--no-browser", action="store_true", help="Do not open a browser tab.")
    subparsers.add_parser("setup-ui", help="Launch the Kendr Web UI (alias for 'kendr ui').")
    ui_parser = subparsers.add_parser("ui", help="Launch the Kendr Web Chat & Config UI on port 2151.")
    command_parsers["ui"] = ui_parser
    ui_parser.add_argument("--port", type=int, default=0, help="Override port (default: KENDR_UI_PORT or 2151).")
    ui_parser.add_argument("--host", default="", help="Override bind host (default: KENDR_UI_HOST or localhost).")
    ui_parser.add_argument("--no-browser", action="store_true", help="Do not open a browser tab automatically.")
    status_parser = subparsers.add_parser("status", help="Show runtime status snapshot.")
    command_parsers["status"] = status_parser
    status_parser.add_argument("--json", action="store_true", help="Emit status as JSON.")
    daemon_parser = subparsers.add_parser("daemon", help="Run the always-on monitor and heartbeat loop.")
    command_parsers["daemon"] = daemon_parser
    daemon_parser.add_argument(
        "--poll-interval",
        type=int,
        default=int(os.getenv("DAEMON_POLL_INTERVAL", "30")),
        help="Main daemon poll interval in seconds.",
    )
    daemon_parser.add_argument(
        "--heartbeat-interval",
        type=int,
        default=int(os.getenv("DAEMON_HEARTBEAT_INTERVAL", "300")),
        help="Heartbeat interval in seconds.",
    )
    daemon_parser.add_argument("--once", action="store_true", help="Run one monitor pass and exit.")

    setup_parser = subparsers.add_parser("setup", help="Manage full component setup via CLI.")
    command_parsers["setup"] = setup_parser
    setup_sub = setup_parser.add_subparsers(dest="setup_action", required=True)

    setup_status = setup_sub.add_parser("status", help="Show setup status and agent availability.")
    setup_status.add_argument("--json", action="store_true")

    setup_components = setup_sub.add_parser("components", help="List all configurable components.")
    setup_components.add_argument("--json", action="store_true")

    setup_show = setup_sub.add_parser("show", help="Show one component configuration.")
    setup_show.add_argument("component")
    setup_show.add_argument("--json", action="store_true")

    setup_set = setup_sub.add_parser("set", help="Set one configuration key for a component.")
    setup_set.add_argument("component")
    setup_set.add_argument("key")
    setup_set.add_argument("value")
    setup_set.add_argument("--secret", action="store_true", help="Accepted for compatibility; secret-ness is catalog-driven.")

    setup_unset = setup_sub.add_parser("unset", help="Remove one configuration key from DB.")
    setup_unset.add_argument("component")
    setup_unset.add_argument("key")

    setup_enable = setup_sub.add_parser("enable", help="Enable a component.")
    setup_enable.add_argument("component")

    setup_disable = setup_sub.add_parser("disable", help="Disable a component.")
    setup_disable.add_argument("component")

    setup_export = setup_sub.add_parser("export-env", help="Export DB config as dotenv lines.")
    setup_export.add_argument("--include-secrets", action="store_true")

    setup_install = setup_sub.add_parser("install", help="Install auto-installable local components/tools.")
    setup_install.add_argument(
        "--yes",
        action="store_true",
        help="Install without interactive confirmation.",
    )
    setup_install.add_argument(
        "--only",
        choices=["nmap", "zap", "dependency-check", "playwright"],
        nargs="*",
        default=[],
        help="Install only selected components.",
    )

    setup_sub.add_parser("ui", help="Launch the Kendr Web UI (alias for 'kendr ui').")
    setup_sub.add_parser("wizard", help="Interactive CLI wizard to configure integrations step-by-step.")
    setup_oauth = setup_sub.add_parser("oauth", help="Run OAuth login/connect flows for supported providers.")
    setup_oauth.add_argument("provider", choices=["google", "microsoft", "slack", "all"])
    setup_oauth.add_argument("--no-browser", action="store_true", help="Print OAuth URLs without opening a browser.")
    setup_oauth.add_argument(
        "--ensure-ui",
        action="store_true",
        help="Compatibility flag. Setup UI is auto-started by default when needed.",
    )

    workdir_parser = subparsers.add_parser("workdir", help="Manage the default working directory.")
    command_parsers["workdir"] = workdir_parser
    workdir_sub = workdir_parser.add_subparsers(dest="workdir_action", required=True)
    workdir_show = workdir_sub.add_parser("show", help="Show the configured working directory.")
    workdir_show.add_argument("--json", action="store_true", help="Emit configured path as JSON.")
    workdir_set = workdir_sub.add_parser("set", help="Set and create the default working directory.")
    workdir_set.add_argument("path")
    workdir_sub.add_parser("here", help="Set current terminal folder as default working directory.")
    workdir_create = workdir_sub.add_parser("create", help="Create a working directory path.")
    workdir_create.add_argument("path")
    workdir_create.add_argument(
        "--activate",
        action="store_true",
        help="Also save this path as KENDR_WORKING_DIR.",
    )
    workdir_sub.add_parser("clear", help="Clear configured KENDR_WORKING_DIR.")
    hello_parser = subparsers.add_parser("hello", help="Quick-start welcome screen with setup guidance and example commands.")
    command_parsers["hello"] = hello_parser
    hello_parser.add_argument("--json", action="store_true", help="Emit quick-start info as JSON.")
    help_parser = subparsers.add_parser("help", help="Show help for one command.")
    command_parsers["help"] = help_parser
    help_parser.add_argument("topic", nargs="?")
    rollback_parser = subparsers.add_parser("rollback", help="List or restore privileged snapshots.")
    command_parsers["rollback"] = rollback_parser
    rollback_parser.add_argument("action", choices=["list", "apply"], nargs="?", default="list")
    rollback_parser.add_argument("--snapshot", default="", help="Snapshot path for rollback apply.")
    rollback_parser.add_argument("--target-dir", default="", help="Target directory to restore into.")
    rollback_parser.add_argument("--overwrite", action="store_true", help="Overwrite existing target directory.")
    rollback_parser.add_argument("--yes", action="store_true", help="Skip interactive confirmation.")
    sessions_parser = subparsers.add_parser("sessions", help="List and switch active conversational sessions.")
    command_parsers["sessions"] = sessions_parser
    sessions_parser.add_argument("action", choices=["list", "use", "current", "clear"], nargs="?", default="list")
    sessions_parser.add_argument("session_key", nargs="?")
    sessions_parser.add_argument("--limit", type=int, default=20)
    sessions_parser.add_argument("--json", action="store_true")

    model_parser = subparsers.add_parser("model", help="Manage LLM providers and models.")
    command_parsers["model"] = model_parser
    model_sub = model_parser.add_subparsers(dest="model_action", required=True)

    model_sub.add_parser("list", help="List all LLM providers and their status.")
    model_sub.add_parser("status", help="Show the currently active LLM provider and model.")
    model_test = model_sub.add_parser("test", help="Send a test prompt to the current (or specified) model.")
    model_test.add_argument("--provider", default="", help="Provider to test (default: active provider).")
    model_test.add_argument("--model", default="", help="Model name override.")
    model_set = model_sub.add_parser("set", help="Set the active LLM provider and/or model.")
    model_set.add_argument("provider", choices=["openai","anthropic","google","xai","minimax","qwen","glm","ollama","openrouter","custom"],
                           help="LLM provider name.")
    model_set.add_argument("model", nargs="?", default="", help="Model name (optional; uses provider default if omitted).")
    model_ollama_p = model_sub.add_parser("ollama", help="Manage local Ollama models.")
    model_ollama_sub = model_ollama_p.add_subparsers(dest="ollama_action", required=True)
    model_ollama_sub.add_parser("status", help="Show Ollama server status and installed models.")
    ollama_pull = model_ollama_sub.add_parser("pull", help="Pull (download) a model from Ollama.")
    ollama_pull.add_argument("model_name", help="Model to pull, e.g. llama3.2, mistral, deepseek-r1.")
    model_ollama_sub.add_parser("list", help="List installed Ollama models.")
    ollama_rm = model_ollama_sub.add_parser("rm", help="Remove an installed Ollama model.")
    ollama_rm.add_argument("model_name", help="Model name to remove.")
    ollama_run = model_ollama_sub.add_parser("run", help="Run Ollama with a model (interactive session).")
    ollama_run.add_argument("model_name", nargs="?", default="", help="Model to run (default: configured OLLAMA_MODEL).")
    ollama_docker = model_ollama_sub.add_parser("docker", help="Manage the Ollama Docker container (start/stop/status).")
    ollama_docker_sub = ollama_docker.add_subparsers(dest="docker_action", required=True)
    ollama_docker_start = ollama_docker_sub.add_parser("start", help="Start Ollama via Docker (CPU by default).")
    ollama_docker_start.add_argument("--gpu", action="store_true", help="Use GPU (NVIDIA) — passes --gpus=all to Docker.")
    ollama_docker_sub.add_parser("stop", help="Stop and remove the kendr-ollama Docker container.")
    ollama_docker_sub.add_parser("status", help="Show the kendr-ollama Docker container status.")

    resume_parser = subparsers.add_parser("resume", help="Inspect or resume a persisted run from an output folder.")
    command_parsers["resume"] = resume_parser
    resume_parser.add_argument("target", nargs="?", default="", help="Run folder, manifest/checkpoint file, or working directory.")
    resume_parser.add_argument("query", nargs="*", help="Optional reply or new query when resuming/branching.")
    resume_parser.add_argument("--output-folder", default="", help="Explicit run output folder or manifest/checkpoint path.")
    resume_parser.add_argument("--working-directory", default="", help="Working directory to search for persisted run folders.")
    resume_parser.add_argument("--latest", action="store_true", help="Use the newest discovered candidate automatically.")
    resume_parser.add_argument("--inspect", action="store_true", help="Only inspect the discovered session without executing it.")
    resume_parser.add_argument("--branch", action="store_true", help="Start a new child run using the saved context instead of resuming in place.")
    resume_parser.add_argument("--reply", default="", help="Explicit reply text for paused runs awaiting user input.")
    resume_parser.add_argument("--force", action="store_true", help="Take over a running or stale run.")
    resume_parser.add_argument("--json", action="store_true", help="Emit resume candidate or result as JSON.")

    generate_parser = subparsers.add_parser(
        "generate",
        help="Generate a complete multi-agent software project from a description.",
    )
    command_parsers["generate"] = generate_parser
    generate_parser.add_argument(
        "description",
        nargs="*",
        help="Natural language description of the project to generate.",
    )
    generate_parser.add_argument(
        "--name",
        default="",
        help="Project name (kebab-case). Auto-derived from description if omitted.",
    )
    generate_parser.add_argument(
        "--stack",
        default="",
        help=(
            "Tech stack template to use. "
            "Short aliases: nextjs, react-vite, fastapi, express, django, flutter, mern, pern. "
            "Full names: nextjs_prisma_postgres, react_vite, fastapi_postgres, fastapi_react_postgres, "
            "express_prisma_postgres, django_react_postgres, mern_microservices_mongodb, pern_postgres, "
            "nextjs_static_site, flutter, custom_freeform. "
            "Leave blank for LLM-driven stack selection."
        ),
    )
    generate_parser.add_argument(
        "--output",
        default="",
        help="Output directory root for the generated project. Defaults to the configured working directory.",
    )
    generate_parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve blueprint and plan gates without interactive prompts.",
    )
    generate_parser.add_argument(
        "--skip-tests",
        action="store_true",
        help="Skip test generation and execution steps.",
    )
    generate_parser.add_argument(
        "--skip-devops",
        action="store_true",
        help="Skip Dockerfile, docker-compose, and CI/CD generation steps.",
    )
    generate_parser.add_argument(
        "--skip-reviews",
        action="store_true",
        help="Skip reviewer agent checks between build steps.",
    )
    generate_parser.add_argument(
        "--max-steps",
        type=int,
        default=40,
        help="Maximum orchestration steps for the build (default 40).",
    )
    generate_parser.add_argument(
        "--working-directory",
        default="",
        help="Working directory for task outputs and build artifacts.",
    )
    generate_parser.add_argument(
        "--current-folder",
        action="store_true",
        help="Use current terminal folder as working directory.",
    )
    generate_parser.add_argument(
        "--github-repo",
        default="",
        metavar="OWNER/REPO",
        help="Push the generated project to a GitHub repository (e.g. my-org/job-board). Requires GITHUB_TOKEN.",
    )
    generate_parser.add_argument(
        "--standalone",
        action="store_true",
        help="Run the project generation pipeline locally without requiring the gateway.",
    )
    generate_parser.add_argument("--json", action="store_true", help="Emit final state as JSON.")
    generate_parser.add_argument("--quiet", action="store_true", help="Suppress live progress messages.")

    project_parser = subparsers.add_parser(
        "project",
        help="Manage coding projects: file tree, shell, GitHub, agent chat.",
    )
    command_parsers["project"] = project_parser
    project_sub = project_parser.add_subparsers(dest="project_action", required=True)

    project_sub.add_parser("list", help="List all registered projects.")

    proj_add = project_sub.add_parser("add", help="Register a directory as a project.")
    proj_add.add_argument("path", help="Absolute or relative path to the project directory.")
    proj_add.add_argument("--name", default="", help="Display name for the project.")

    proj_open = project_sub.add_parser("open", help="Set the active project and optionally open the UI.")
    proj_open.add_argument("path_or_id", help="Project path or ID.")
    proj_open.add_argument("--ui", action="store_true", help="Open the browser at the projects page.")

    proj_rm = project_sub.add_parser("remove", help="Remove a project from the registry (does not delete files).")
    proj_rm.add_argument("path_or_id", help="Project path or ID.")

    proj_shell = project_sub.add_parser("shell", help="Run a shell command inside the active project.")
    proj_shell.add_argument("command", nargs="+", help="Shell command to run.")
    proj_shell.add_argument("--project", default="", help="Project path or ID (defaults to active).")

    proj_git = project_sub.add_parser("git", help="Git operations on the active project.")
    proj_git.add_argument("git_args", nargs="+", help="Git sub-command (status | pull | push | commit -m MSG | clone URL).")
    proj_git.add_argument("--project", default="", help="Project path or ID (defaults to active).")

    proj_status = project_sub.add_parser("status", help="Show active project info and git status.")
    proj_status.add_argument("--project", default="", help="Project path or ID (defaults to active).")

    proj_service = project_sub.add_parser("service", help="Manage long-running services for a project.")
    proj_service_sub = proj_service.add_subparsers(dest="project_service_action", required=True)

    proj_service_list = proj_service_sub.add_parser("list", help="List tracked services for a project.")
    proj_service_list.add_argument("--project", default="", help="Project path or ID (defaults to active).")
    proj_service_list.add_argument("--running-only", action="store_true", help="Show only running services.")

    proj_service_start = proj_service_sub.add_parser("start", help="Start and track a project service.")
    proj_service_start.add_argument("name", nargs="?", default="", help="Service display name.")
    proj_service_start.add_argument("--command", default="", help="Command to start. Omit to reuse a stored command.")
    proj_service_start.add_argument("--project", default="", help="Project path or ID (defaults to active).")
    proj_service_start.add_argument("--kind", default="", help="Service type: backend, frontend, database, worker, proxy, service.")
    proj_service_start.add_argument("--cwd", default="", help="Working directory for the service command.")
    proj_service_start.add_argument("--port", type=int, default=0, help="Port to monitor.")
    proj_service_start.add_argument("--health-url", default="", help="Optional healthcheck URL.")
    proj_service_start.add_argument("--service-id", default="", help="Reuse an existing tracked service ID.")

    proj_service_stop = proj_service_sub.add_parser("stop", help="Stop a tracked project service.")
    proj_service_stop.add_argument("service_id", help="Tracked service ID.")
    proj_service_stop.add_argument("--project", default="", help="Project path or ID (defaults to active).")

    proj_service_restart = proj_service_sub.add_parser("restart", help="Restart a tracked project service.")
    proj_service_restart.add_argument("service_id", help="Tracked service ID.")
    proj_service_restart.add_argument("--project", default="", help="Project path or ID (defaults to active).")

    proj_service_logs = proj_service_sub.add_parser("logs", help="Show the recent log output for a tracked service.")
    proj_service_logs.add_argument("service_id", help="Tracked service ID.")
    proj_service_logs.add_argument("--project", default="", help="Project path or ID (defaults to active).")
    proj_service_logs.add_argument("--bytes", type=int, default=16000, help="Maximum log bytes to read.")

    rag_parser = subparsers.add_parser("rag", help="Manage Super-RAG knowledge bases: vector store, sources, reranker, agents.")
    command_parsers["rag"] = rag_parser
    rag_sub = rag_parser.add_subparsers(dest="rag_action", required=True)

    rag_sub.add_parser("list", help="List all knowledge bases.")

    rag_create = rag_sub.add_parser("create", help="Create a new knowledge base.")
    rag_create.add_argument("name", help="KB name.")
    rag_create.add_argument("--description", default="", help="Optional description.")

    rag_status = rag_sub.add_parser("status", help="Show status of a KB (vector backend, stats, sources).")
    rag_status.add_argument("--kb", default="", help="KB name or ID (defaults to active).")

    rag_add_src = rag_sub.add_parser("add-source", help="Add a source to a knowledge base.")
    rag_add_src.add_argument("--kb", default="", help="KB name or ID (defaults to active).")
    rag_add_src.add_argument("--type", dest="source_type", default="folder",
                             choices=["folder", "file", "url", "database", "onedrive"],
                             help="Source type.")
    rag_add_src.add_argument("--path", default="", help="File or folder path (for folder/file types).")
    rag_add_src.add_argument("--url", default="", help="URL to crawl (for url type).")
    rag_add_src.add_argument("--db-url", default="", help="Database connection URL (for database type).")
    rag_add_src.add_argument("--label", default="", help="Friendly name for the source.")
    rag_add_src.add_argument("--recursive", action="store_true", default=True, help="Recurse into subdirectories.")
    rag_add_src.add_argument("--max-files", type=int, default=300, help="Max files to ingest (folder type).")
    rag_add_src.add_argument("--max-pages", type=int, default=20, help="Max pages to crawl (url type).")
    rag_add_src.add_argument("--extensions", default="", help="Comma-separated file extensions to include.")
    rag_add_src.add_argument("--tables", default="", help="Comma-separated table names (database type).")

    rag_index = rag_sub.add_parser("index", help="Trigger indexing of all (or specific) sources.")
    rag_index.add_argument("--kb", default="", help="KB name or ID (defaults to active).")
    rag_index.add_argument("--wait", action="store_true", help="Wait for indexing to complete.")

    rag_query = rag_sub.add_parser("query", help="Search the knowledge base.")
    rag_query.add_argument("query", nargs="+", help="Search query.")
    rag_query.add_argument("--kb", default="", help="KB name or ID (defaults to active).")
    rag_query.add_argument("--top-k", type=int, default=8, help="Number of results.")
    rag_query.add_argument("--ai", action="store_true", help="Generate an AI answer from retrieved chunks.")

    rag_cfg_vec = rag_sub.add_parser("config-vector", help="Configure vector store backend.")
    rag_cfg_vec.add_argument("--kb", default="", help="KB name or ID.")
    rag_cfg_vec.add_argument("--backend", choices=["chromadb", "qdrant", "pgvector"], help="Vector backend.")
    rag_cfg_vec.add_argument("--qdrant-url", default="", help="Qdrant server URL.")
    rag_cfg_vec.add_argument("--pgvector-url", default="", help="PostgreSQL URL for pgvector.")
    rag_cfg_vec.add_argument("--embedding-model", default="", help="Embedding model (e.g. openai:text-embedding-3-small).")

    rag_cfg_rr = rag_sub.add_parser("config-reranker", help="Configure reranking algorithm.")
    rag_cfg_rr.add_argument("--kb", default="", help="KB name or ID.")
    rag_cfg_rr.add_argument("--algorithm", choices=["none", "keyword", "rrf", "cross_encoder", "cohere"],
                            help="Reranking algorithm.")
    rag_cfg_rr.add_argument("--top-k", type=int, default=0, help="Number of results to return (0=keep current).")
    rag_cfg_rr.add_argument("--keyword-weight", type=float, default=0.0, help="Keyword weight for 'keyword' algorithm (0-1).")
    rag_cfg_rr.add_argument("--cohere-api-key", default="", help="Cohere API key.")

    rag_enable_agent = rag_sub.add_parser("enable-agent", help="Enable an agent to access this KB (Super-RAG).")
    rag_enable_agent.add_argument("agent", help="Agent name (e.g. superrag_agent).")
    rag_enable_agent.add_argument("--kb", default="", help="KB name or ID.")

    rag_disable_agent = rag_sub.add_parser("disable-agent", help="Disable an agent from accessing this KB.")
    rag_disable_agent.add_argument("agent", help="Agent name.")
    rag_disable_agent.add_argument("--kb", default="", help="KB name or ID.")

    rag_activate = rag_sub.add_parser("activate", help="Set a KB as the active knowledge base.")
    rag_activate.add_argument("name_or_id", help="KB name or ID.")

    rag_delete = rag_sub.add_parser("delete", help="Delete a knowledge base (config only, not vector data).")
    rag_delete.add_argument("name_or_id", help="KB name or ID.")

    research_parser = subparsers.add_parser(
        "research",
        help="Run a multi-source research pipeline and generate a document.",
    )
    command_parsers["research"] = research_parser
    research_parser.add_argument(
        "query",
        nargs="*",
        help="Research query or topic.",
    )
    research_parser.add_argument(
        "--sources",
        default="",
        help=(
            "Comma-separated research sources. "
            "Options: web, arxiv (alias: papers), reddit, scholar, patents, openalex, local. "
            "Example: --sources arxiv,reddit,openalex"
        ),
    )
    research_parser.add_argument(
        "--pages",
        type=int,
        default=0,
        help="Target page count for the generated deep research report.",
    )
    research_parser.add_argument(
        "--format",
        default="pdf,docx,html,md",
        help="Comma-separated output formats for deep research: pdf,docx,html,md.",
    )
    research_parser.add_argument(
        "--cite",
        default="apa",
        help="Citation style: apa, mla, chicago, ieee, vancouver, harvard.",
    )
    research_parser.add_argument(
        "--no-plagiarism",
        action="store_true",
        help="Skip the plagiarism/reuse check stage.",
    )
    research_parser.add_argument(
        "--date-range",
        default="",
        help="Date range hint (for example 1y, 5y, 2020-2025).",
    )
    research_parser.add_argument(
        "--max-sources",
        type=int,
        default=0,
        help="Cap total sources gathered during deep research.",
    )
    research_parser.add_argument(
        "--checkpoint",
        action="store_true",
        help="Enable checkpoint markers for long-running deep research runs.",
    )
    research_parser.add_argument(
        "--title",
        default="",
        help="Optional report title override.",
    )
    research_parser.add_argument(
        "--drive",
        "--deep-research-path",
        dest="drive",
        action="append",
        default=[],
        help="Local folder or file path to include as a research source. Repeat for multiple paths.",
    )
    research_parser.add_argument(
        "--deep-research-link",
        action="append",
        default=[],
        help="Explicit URL to extract and include as a deep research source. Repeat for multiple links.",
    )
    research_parser.add_argument(
        "--no-web-search",
        action="store_true",
        help="Disable internet/web search and build the report only from local files/folders.",
    )
    research_parser.add_argument(
        "--research-model",
        default="",
        help="Override the deep-research model for this run.",
    )
    research_parser.add_argument(
        "--auto-approve",
        action="store_true",
        help="Auto-approve plan gates.",
    )
    research_parser.add_argument(
        "--max-steps",
        type=int,
        default=20,
        help="Maximum orchestration steps (default 20).",
    )
    research_parser.add_argument(
        "--working-directory",
        default="",
        help="Working directory for task outputs.",
    )
    research_parser.add_argument(
        "--current-folder",
        action="store_true",
        help="Use current terminal folder as working directory.",
    )
    research_parser.add_argument("--json", action="store_true", help="Emit final state as JSON.")
    research_parser.add_argument("--quiet", action="store_true", help="Suppress live progress messages.")

    test_parser = subparsers.add_parser(
        "test",
        help="Testing Agent Suite: generate, run, and fix tests from the CLI.",
        formatter_class=_KendrHelpFormatter,
    )
    command_parsers["test"] = test_parser
    test_sub = test_parser.add_subparsers(dest="test_action", metavar="ACTION")

    t_api = test_sub.add_parser("api", help="Generate API tests from an OpenAPI spec URL or file.")
    t_api.add_argument("source", help="OpenAPI spec URL or local path (JSON/YAML).")
    t_api.add_argument("--base-url", default="http://localhost:8000", help="Base URL for the API under test.")
    t_api.add_argument("--output-dir", default=".", help="Directory to write generated test files.")
    t_api.add_argument("--language", default="python", choices=["python", "typescript"], help="Test language.")
    t_api.add_argument("--no-run", action="store_true", help="Generate tests but do not run them.")
    t_api.add_argument("--timeout", type=int, default=120, help="Timeout for the test run in seconds.")
    t_api.add_argument("--json", action="store_true", help="Emit JSON report.")

    t_unit = test_sub.add_parser("unit", help="Generate unit tests for one or more source files.")
    t_unit.add_argument("files", nargs="+", help="Source file(s) to generate tests for.")
    t_unit.add_argument("--output-dir", default=".", help="Directory to write generated test files.")
    t_unit.add_argument("--language", default="auto", help="Language hint (python/typescript/javascript).")
    t_unit.add_argument("--instructions", default="", help="Additional instructions for the test generator.")
    t_unit.add_argument("--json", action="store_true", help="Emit JSON report.")

    t_run = test_sub.add_parser("run", help="Run the existing test suite and show a formatted results table.")
    t_run.add_argument("directory", nargs="?", default=".", help="Working directory containing the test suite.")
    t_run.add_argument("--command", default="", help="Custom test command (e.g. 'pytest -q' or 'npm test').")
    t_run.add_argument("--timeout", type=int, default=300, help="Timeout in seconds for the test run.")
    t_run.add_argument("--json", action="store_true", help="Emit JSON report.")

    t_fix = test_sub.add_parser("fix", help="Run tests, read failures, auto-patch, and re-run until passing.")
    t_fix.add_argument("directory", nargs="?", default=".", help="Working directory containing the test suite.")
    t_fix.add_argument("--command", default="", help="Custom test command.")
    t_fix.add_argument("--max-iterations", type=int, default=3, help="Max fix iterations.")
    t_fix.add_argument("--context-files", default="", help="Comma-separated source files to provide as context.")
    t_fix.add_argument("--timeout", type=int, default=300, help="Timeout in seconds per test run.")
    t_fix.add_argument("--json", action="store_true", help="Emit JSON report.")

    t_regression = test_sub.add_parser("regression", help="Write a targeted regression test for a bug description.")
    t_regression.add_argument("description", nargs="+", help="Bug description (natural language).")
    t_regression.add_argument("--directory", default=".", help="Working directory / project root.")
    t_regression.add_argument("--language", default="python", choices=["python", "typescript"], help="Test language.")
    t_regression.add_argument("--context-files", default="", help="Comma-separated source files to provide as context.")
    t_regression.add_argument("--json", action="store_true", help="Emit JSON report.")

    mcp_parser = subparsers.add_parser(
        "mcp",
        help="Manage MCP server connections: add, list, remove, test.",
        formatter_class=_KendrHelpFormatter,
    )
    command_parsers["mcp"] = mcp_parser
    mcp_sub = mcp_parser.add_subparsers(dest="mcp_action", metavar="ACTION")

    mcp_add = mcp_sub.add_parser(
        "add",
        help="Register a new MCP server.",
        description=(
            "Register a new MCP server.\n\n"
            "Usage (positional):  kendr mcp add <name> <connection>\n"
            "Usage (flags):       kendr mcp add --name <name> --url <connection>"
        ),
    )
    mcp_add.add_argument("name", nargs="?", default=None, help="Human-readable server name (or use --name).")
    mcp_add.add_argument("connection", nargs="?", default=None, help="HTTP endpoint or stdio command (or use --url).")
    mcp_add.add_argument("--name", dest="name_flag", default=None, metavar="NAME", help="Server name (overrides positional).")
    mcp_add.add_argument("--url", dest="url_flag", default=None, metavar="URL", help="HTTP endpoint or stdio command (overrides positional).")
    mcp_add.add_argument(
        "--type", dest="server_type", default="http", choices=["http", "stdio"],
        help="Connection type: 'http' (default) or 'stdio'.",
    )
    mcp_add.add_argument("--description", default="", help="Optional description.")
    mcp_add.add_argument(
        "--auth-token", dest="auth_token", default="",
        help="Optional bearer token for authenticated HTTP MCP servers.",
    )
    mcp_add.add_argument("--no-discover", action="store_true", help="Register without running tool discovery.")

    mcp_sub.add_parser("list", help="List all registered MCP servers and their tools.")

    mcp_rm = mcp_sub.add_parser("remove", help="Remove a registered MCP server.")
    mcp_rm.add_argument("server_id_or_name", help="Server ID or name to remove.")

    mcp_test = mcp_sub.add_parser("test", help="Ping an MCP server and list its tools.")
    mcp_test.add_argument("server_id_or_name", help="Server ID or name to test.")

    mcp_discover = mcp_sub.add_parser("discover", help="Re-run tool discovery for a registered server.")
    mcp_discover.add_argument("server_id_or_name", help="Server ID or name.")

    mcp_enable = mcp_sub.add_parser("enable", help="Enable a registered MCP server.")
    mcp_enable.add_argument("server_id_or_name", help="Server ID or name.")

    mcp_disable = mcp_sub.add_parser("disable", help="Disable a registered MCP server.")
    mcp_disable.add_argument("server_id_or_name", help="Server ID or name.")

    mcp_zapier = mcp_sub.add_parser(
        "zapier",
        help="Quick-connect a Zapier MCP server.",
        description=(
            "Register your Zapier MCP server with kendr.\n\n"
            "Get your personal MCP URL from https://zapier.com/mcp\n"
            "URL format:  https://mcp.zapier.com/api/mcp/s/<token>/mcp\n\n"
            "Usage:  kendr mcp zapier <your-zapier-mcp-url>"
        ),
    )
    mcp_zapier.add_argument(
        "mcp_url",
        nargs="?",
        default=None,
        help="Your Zapier MCP URL (from zapier.com/mcp).",
    )
    mcp_zapier.add_argument(
        "--url",
        dest="url_flag",
        default=None,
        metavar="URL",
        help="Zapier MCP URL (alternative to positional).",
    )
    mcp_zapier.add_argument(
        "--name",
        default="Zapier",
        help="Name for this server entry (default: Zapier).",
    )
    mcp_zapier.add_argument("--no-discover", action="store_true", help="Register without running tool discovery.")

    # ── new — spec Section 2.2 alias for generate --standalone ────────────────
    new_parser = subparsers.add_parser(
        "new",
        help="Scaffold a new project (alias for 'generate --standalone').",
        description=(
            "Generate a complete, runnable project from a natural language description.\n\n"
            "This is a shorthand for 'kendr generate --standalone'. The project is created\n"
            "in the current directory (or --dir) without requiring the gateway server.\n\n"
            "Examples:\n"
            "  kendr new 'A job board where employers post jobs and candidates apply' --stack nextjs\n"
            "  kendr new 'REST API for a todo app' --stack fastapi --dir ~/projects/todo-api\n"
        ),
    )
    new_parser.add_argument("description", nargs="?", default="", help="Natural language project description.")
    new_parser.add_argument("--stack", default="", help="Tech stack (e.g. nextjs, fastapi, react, django).")
    new_parser.add_argument("--dir", dest="project_root", default="", metavar="PATH",
                            help="Output directory (default: cwd/<project-name>).")
    new_parser.add_argument("--name", default="", metavar="NAME", help="Kebab-case project name.")
    new_parser.add_argument("--yes", "-y", action="store_true", help="Skip blueprint approval prompt.")
    new_parser.add_argument("--no-tests", action="store_true", help="Skip test generation.")
    new_parser.add_argument("--no-devops", action="store_true", help="Skip Dockerfile/docker-compose generation.")
    new_parser.add_argument("--github-repo", default="", metavar="OWNER/REPO",
                            help="Push to GitHub repo after generation.")
    new_parser.add_argument("--github-token", default="", metavar="TOKEN",
                            help="GitHub PAT (falls back to GITHUB_TOKEN env var).")
    command_parsers["new"] = new_parser

    # ── checkpoint — spec Section 2.2 save/restore ────────────────────────────
    checkpoint_parser = subparsers.add_parser(
        "checkpoint",
        help="Save or restore pipeline execution checkpoints.",
        description=(
            "Manage checkpoints — named snapshots of pipeline state that can be\n"
            "restored to resume from a specific stage without re-running earlier steps.\n\n"
            "Examples:\n"
            "  kendr checkpoint save my-checkpoint\n"
            "  kendr checkpoint restore my-checkpoint\n"
            "  kendr checkpoint list\n"
        ),
    )
    checkpoint_sub = checkpoint_parser.add_subparsers(dest="checkpoint_action", required=True)
    ckpt_save = checkpoint_sub.add_parser("save", help="Save current pipeline state as a named checkpoint.")
    ckpt_save.add_argument("name", nargs="?", default="", help="Checkpoint name (default: auto-timestamp).")
    ckpt_save.add_argument("--dir", default="", metavar="PATH", help="Project directory (default: cwd).")
    ckpt_restore = checkpoint_sub.add_parser("restore", help="Restore a named checkpoint.")
    ckpt_restore.add_argument("name", help="Checkpoint name to restore.")
    ckpt_restore.add_argument("--dir", default="", metavar="PATH", help="Project directory (default: cwd).")
    checkpoint_sub.add_parser("list", help="List all available checkpoints.")
    command_parsers["checkpoint"] = checkpoint_parser

    # ── doctor — spec Section 2.2 system health check ────────────────────────
    doctor_parser = subparsers.add_parser(
        "doctor",
        help="Run system health checks and diagnose configuration issues.",
        description=(
            "Verify that Kendr's runtime dependencies are correctly installed and\n"
            "configured.  Checks LLM provider connectivity, gateway server, git,\n"
            "Docker, Node.js / Python toolchains, and environment variables.\n"
        ),
    )
    doctor_parser.add_argument("--fix", action="store_true", help="Attempt to auto-fix common issues.")
    doctor_parser.add_argument("--json", action="store_true", help="Emit results as JSON.")
    command_parsers["doctor"] = doctor_parser

    # ── clean — spec Section 2.2 remove temp files ───────────────────────────
    clean_parser = subparsers.add_parser(
        "clean",
        help="Remove temporary build artifacts and cache files.",
        description=(
            "Delete .kendr-cache, __pycache__, node_modules caches, and other\n"
            "temporary files created during project generation or pipeline runs.\n\n"
            "Examples:\n"
            "  kendr clean               # clean current directory\n"
            "  kendr clean --all         # clean all known working directories\n"
            "  kendr clean --logs        # also remove pipeline log files\n"
        ),
    )
    clean_parser.add_argument("path", nargs="?", default=".", help="Directory to clean (default: cwd).")
    clean_parser.add_argument("--all", action="store_true", help="Clean all known working directories.")
    clean_parser.add_argument("--logs", action="store_true", help="Also remove pipeline log files.")
    clean_parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting.")
    command_parsers["clean"] = clean_parser

    # ── upgrade — spec Section 2.2 upgrade to latest ─────────────────────────
    upgrade_parser = subparsers.add_parser(
        "upgrade",
        help="Upgrade Kendr to the latest available version.",
        description=(
            "Check PyPI for the latest version and upgrade via pip if a newer\n"
            "version is available.  Use --check to only report without installing.\n"
        ),
    )
    upgrade_parser.add_argument("--check", action="store_true", help="Check for updates without installing.")
    upgrade_parser.add_argument("--pre", action="store_true", help="Include pre-release versions.")
    command_parsers["upgrade"] = upgrade_parser

    return parser, command_parsers


def _cmd_new(args: argparse.Namespace) -> int:
    """'kendr new' — spec Section 2.2 alias for generate --standalone."""
    style = _style_from_args(args)
    description = str(getattr(args, "description", "") or "").strip()
    if not description:
        if not sys.stdin.isatty():
            description = sys.stdin.read().strip()
        if not description:
            print(style.fail("✗ No project description provided."))
            print("  Usage: kendr new 'A job board where employers post jobs…' --stack nextjs")
            return 1

    from tasks.project_generation_orchestrator import ProjectGenerationOrchestrator

    project_root = str(getattr(args, "project_root", "") or "")
    stack = str(getattr(args, "stack", "") or "")
    name = str(getattr(args, "name", "") or "")
    github_repo = str(getattr(args, "github_repo", "") or "")
    github_token = str(getattr(args, "github_token", "") or "")

    def _progress(msg: str) -> None:
        try:
            payload = json.loads(msg)
            text = payload.get("text", msg)
        except Exception:
            text = msg
        print(text, flush=True)

    orch = ProjectGenerationOrchestrator(
        description=description,
        stack=stack,
        project_root=project_root,
        project_name=name,
        auto_approve=bool(getattr(args, "yes", False)),
        skip_tests=bool(getattr(args, "no_tests", False)),
        skip_devops=bool(getattr(args, "no_devops", False)),
        github_repo=github_repo,
        github_token=github_token,
        progress_cb=_progress,
    )
    result = orch.run()
    if result.get("ok"):
        print(style.ok(f"\n✓ Project created: {result['project_root']}"))
        if result.get("github_url"):
            print(style.ok(f"  GitHub: {result['github_url']}"))
        return 0
    else:
        print(style.fail(f"\n✗ Generation completed with errors ({len(result.get('errors', []))} issue(s))"))
        for err in result.get("errors", [])[:3]:
            print(f"  • {str(err)[:120]}")
        return 1


def _cmd_checkpoint(args: argparse.Namespace) -> int:
    """'kendr checkpoint' — save/restore/list pipeline checkpoints."""
    style = _style_from_args(args)
    action = str(getattr(args, "checkpoint_action", "") or "")
    project_dir = Path(str(getattr(args, "dir", "") or ".")).expanduser().resolve()
    checkpoints_dir = project_dir / ".kendr" / "checkpoints"

    if action == "list":
        if not checkpoints_dir.exists():
            print(style.muted("  No checkpoints found."))
            return 0
        ckpts = sorted(checkpoints_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not ckpts:
            print(style.muted("  No checkpoints found."))
            return 0
        rows = [["Name", "Created", "Size"]]
        for p in ckpts:
            mtime = dt.datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            size = f"{p.stat().st_size // 1024}KB" if p.stat().st_size >= 1024 else f"{p.stat().st_size}B"
            rows.append([p.stem, mtime, size])
        print(_render_table(rows[0], rows[1:]))
        return 0

    if action == "save":
        name = str(getattr(args, "name", "") or "").strip()
        if not name:
            name = dt.datetime.now().strftime("ckpt-%Y%m%d-%H%M%S")
        ckpt_path = checkpoints_dir / f"{name}.json"
        checkpoints_dir.mkdir(parents=True, exist_ok=True)
        # Save a metadata snapshot of the current working directory state
        snapshot: dict = {
            "name": name,
            "created": dt.datetime.now().isoformat(),
            "project_dir": str(project_dir),
            "files": [str(p.relative_to(project_dir)) for p in project_dir.rglob("*") if p.is_file()
                       and ".kendr" not in p.parts and ".git" not in p.parts][:500],
        }
        ckpt_path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
        print(style.ok(f"✓ Checkpoint saved: {name}"))
        print(style.muted(f"  {ckpt_path}"))
        return 0

    if action == "restore":
        name = str(getattr(args, "name", "") or "").strip()
        ckpt_path = checkpoints_dir / f"{name}.json"
        if not ckpt_path.exists():
            print(style.fail(f"✗ Checkpoint not found: {name}"))
            return 1
        try:
            snapshot = json.loads(ckpt_path.read_text(encoding="utf-8"))
            print(style.ok(f"✓ Checkpoint '{name}' found"))
            print(style.muted(f"  Created: {snapshot.get('created', '?')}"))
            print(style.muted(f"  Files tracked: {len(snapshot.get('files', []))}"))
            print(style.warn("  Note: checkpoint restore shows metadata only."))
            print(style.warn("  Use 'kendr resume' to resume an interrupted pipeline run."))
        except Exception as exc:
            print(style.fail(f"✗ Failed to read checkpoint: {exc}"))
            return 1
        return 0

    print(style.fail(f"✗ Unknown checkpoint action: {action}"))
    return 1


def _cmd_doctor(args: argparse.Namespace) -> int:
    """'kendr doctor' — spec Section 2.2 system health check."""
    style = _style_from_args(args)
    emit_json_out = bool(getattr(args, "json", False))
    fix = bool(getattr(args, "fix", False))

    checks: list[dict] = []

    def _check(name: str, fn) -> dict:
        try:
            ok, msg = fn()
            return {"name": name, "ok": ok, "message": msg}
        except Exception as exc:
            return {"name": name, "ok": False, "message": str(exc)}

    # LLM provider
    def _check_llm():
        try:
            from tasks.utils import llm
            _ = llm  # just importing is sufficient to verify config
            return True, "LLM provider configured"
        except Exception as exc:
            return False, str(exc)

    # Git
    def _check_git():
        found = shutil.which("git")
        if found:
            result = subprocess.run(["git", "--version"], capture_output=True, text=True, timeout=5)
            return result.returncode == 0, result.stdout.strip() or "git found"
        return False, "git not found in PATH"

    # Node.js
    def _check_node():
        found = shutil.which("node")
        if found:
            result = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5)
            return result.returncode == 0, result.stdout.strip() or "node found"
        return False, "node not found in PATH"

    # Python
    def _check_python():
        import sys as _sys
        return True, f"Python {_sys.version.split()[0]}"

    # Docker
    def _check_docker():
        found = shutil.which("docker")
        if found:
            result = subprocess.run(["docker", "info", "--format", "{{.ServerVersion}}"],
                                    capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                return True, f"Docker {result.stdout.strip()}"
            return False, "Docker daemon not running"
        return False, "docker not found in PATH"

    # Gateway
    def _check_gateway():
        host, port = _gateway_host_port()
        try:
            with socket.create_connection((host, port), timeout=2):
                return True, f"Gateway running on {host}:{port}"
        except OSError:
            return False, f"Gateway not running on {host}:{port}"

    # API key
    def _check_api_key():
        for var in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "GOOGLE_API_KEY"):
            if os.environ.get(var):
                return True, f"{var} is set"
        return False, "No LLM API key found (set ANTHROPIC_API_KEY, OPENAI_API_KEY, or GOOGLE_API_KEY)"

    checks.append(_check("Python", _check_python))
    checks.append(_check("Git", _check_git))
    checks.append(_check("Node.js", _check_node))
    checks.append(_check("Docker", _check_docker))
    checks.append(_check("API key", _check_api_key))
    checks.append(_check("LLM provider", _check_llm))
    checks.append(_check("Gateway", _check_gateway))

    if emit_json_out:
        print(json.dumps(checks, indent=2))
        return 0 if all(c["ok"] for c in checks) else 1

    _ok_mark = "OK" if sys.platform == "win32" and sys.stdout.encoding and "utf" not in sys.stdout.encoding.lower() else "OK"
    _fail_mark = "FAIL" if sys.platform == "win32" and sys.stdout.encoding and "utf" not in sys.stdout.encoding.lower() else "FAIL"

    all_ok = True
    for c in checks:
        icon = style.ok(f"[{_ok_mark}]") if c["ok"] else style.fail(f"[{_fail_mark}]")
        label = c["name"].ljust(16)
        msg = c["message"]
        line = f"  {icon}  {label}  {msg}"
        try:
            print(line)
        except UnicodeEncodeError:
            print(line.encode("ascii", errors="replace").decode("ascii"))
        if not c["ok"]:
            all_ok = False

    if all_ok:
        print()
        print(style.ok("All checks passed. Kendr is ready."))
        return 0

    print()
    if fix:
        print(style.warn("  Auto-fix is not yet implemented. Please resolve the issues above manually."))
    else:
        print(style.warn("  Some checks failed. Run 'kendr doctor --fix' to attempt auto-repair."))
    return 1


def _cmd_clean(args: argparse.Namespace) -> int:
    """'kendr clean' — spec Section 2.2 remove temporary build artifacts."""
    style = _style_from_args(args)
    dry_run = bool(getattr(args, "dry_run", False))
    clean_logs = bool(getattr(args, "logs", False))
    clean_all = bool(getattr(args, "all", False))

    target_path = Path(str(getattr(args, "path", ".") or ".")).expanduser().resolve()

    dirs_to_clean = [target_path]
    if clean_all:
        try:
            workdir_env = os.environ.get("KENDR_WORKING_DIR", "")
            if workdir_env:
                dirs_to_clean.append(Path(workdir_env))
        except Exception:
            pass

    ARTIFACT_PATTERNS = [
        "**/__pycache__",
        "**/*.pyc",
        "**/*.pyo",
        "**/.kendr-cache",
        "**/.mypy_cache",
        "**/.ruff_cache",
        "**/.pytest_cache",
        "**/*.egg-info",
        "**/dist",
        "**/build",
    ]
    if clean_logs:
        ARTIFACT_PATTERNS += ["**/*.log", "**/.kendr/logs"]

    deleted: list[str] = []
    for root_dir in dirs_to_clean:
        if not root_dir.exists():
            continue
        for pattern in ARTIFACT_PATTERNS:
            for path in root_dir.glob(pattern):
                rel = str(path.relative_to(root_dir))
                if any(p in path.parts for p in (".git", ".deps", ".venv", "venv", "node_modules", "site-packages")):
                    continue
                if dry_run:
                    deleted.append(f"[dry-run] {rel}")
                else:
                    try:
                        if path.is_dir():
                            shutil.rmtree(path, ignore_errors=True)
                        else:
                            path.unlink(missing_ok=True)
                        deleted.append(rel)
                    except Exception:
                        pass

    if deleted:
        for item in deleted[:20]:
            try:
                print(style.muted(f"  {'would delete' if dry_run else 'deleted'}  {item}"))
            except UnicodeEncodeError:
                print(style.muted(f"  {'would delete' if dry_run else 'deleted'}  {item.encode('ascii', errors='replace').decode('ascii')}"))
        if len(deleted) > 20:
            print(style.muted(f"  ... and {len(deleted) - 20} more"))
        verb = "Would delete" if dry_run else "Cleaned"
        print(style.ok(f"\n{verb} {len(deleted)} artifact(s)"))
    else:
        print(style.ok("Nothing to clean."))
    return 0


def _cmd_upgrade(args: argparse.Namespace) -> int:
    """'kendr upgrade' — spec Section 2.2 upgrade to latest version."""
    style = _style_from_args(args)
    check_only = bool(getattr(args, "check", False))
    pre = bool(getattr(args, "pre", False))

    try:
        current = importlib.metadata.version("kendr")
    except importlib.metadata.PackageNotFoundError:
        current = "dev"

    print(style.muted(f"  Current version: {current}"))

    # Check PyPI for latest
    try:
        url = "https://pypi.org/pypi/kendr/json"
        req = urllib.request.Request(url, headers={"User-Agent": "kendr-cli"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if pre:
            all_versions = list(data.get("releases", {}).keys())
            latest = sorted(all_versions)[-1] if all_versions else data["info"]["version"]
        else:
            latest = data["info"]["version"]
    except Exception as exc:
        print(style.fail(f"✗ Could not check PyPI: {exc}"))
        return 1

    print(style.muted(f"  Latest version:  {latest}"))

    if current == latest:
        print(style.ok("✓ Already up to date."))
        return 0

    if check_only:
        print(style.warn(f"  Update available: {current} → {latest}"))
        print(style.muted("  Run 'kendr upgrade' (without --check) to install."))
        return 0

    print(style.muted(f"  Upgrading {current} → {latest}…"))
    pre_flag = ["--pre"] if pre else []
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--upgrade"] + pre_flag + ["kendr"],
        capture_output=False,
    )
    if result.returncode == 0:
        print(style.ok(f"\n✓ Upgraded to kendr {latest}"))
        return 0
    else:
        print(style.fail("\n✗ Upgrade failed. Try: pip install --upgrade kendr"))
        return 1


def _render_test_report(report: dict, style: "_CliStyle") -> str:
    status = str(report.get("status", "FAIL")).upper()
    ok = status == "PASS"
    header = style.ok(f"✓ Tests {status}") if ok else style.fail(f"✗ Tests {status}")
    rows = [
        ["Metric", "Count"],
        ["Passed", str(report.get("passed", 0))],
        ["Failed", str(report.get("failed", 0))],
        ["Skipped", str(report.get("skipped", 0))],
        ["Total", str(report.get("total", 0))],
    ]
    table = _render_table(rows[0], rows[1:])
    lines = [header, "", table]
    failures = report.get("failures", [])
    if failures:
        lines.append("")
        lines.append(style.warn(f"Failures ({len(failures)}):"))
        for f in failures[:10]:
            test_name = str(f.get("test", "?"))
            msg = str(f.get("message", ""))[:80]
            lines.append(f"  {style.fail('✗')} {test_name}" + (f"  — {msg}" if msg else ""))
    patches = report.get("patches_applied", [])
    if patches:
        lines.append("")
        lines.append(style.ok(f"Patches applied: {len(patches)}"))
        for p in patches[:5]:
            lines.append(f"  • iter {p.get('iteration', '?')}: {p.get('file', '?')}")
    return "\n".join(lines)


def _cmd_test(args: argparse.Namespace) -> int:
    style = _style_from_args(args)
    action = getattr(args, "test_action", None)
    emit_json = bool(getattr(args, "json", False))

    if not action:
        style2 = _cli_style(None)
        _, cp = _build_parser(style2)
        if "test" in cp:
            cp["test"].print_help()
        return 0

    try:
        from tasks.testing_agent_suite import (
            api_test_agent,
            unit_test_agent,
            test_runner_agent,
            test_fix_agent,
            regression_test_agent,
        )
    except ImportError as exc:
        print(style.fail(f"Cannot import testing agents: {exc}"))
        return 1

    state: dict = {}

    if action == "api":
        state["test_openapi_source"] = getattr(args, "source", "")
        state["test_base_url"] = getattr(args, "base_url", "http://localhost:8000")
        state["test_output_dir"] = str(Path(getattr(args, "output_dir", ".")).resolve())
        state["test_language"] = getattr(args, "language", "python")
        state["test_run_after_generate"] = not bool(getattr(args, "no_run", False))
        state["test_timeout"] = getattr(args, "timeout", 120)
        try:
            state = api_test_agent(state)
        except Exception as exc:
            print(style.fail(f"api_test_agent error: {exc}"))
            return 1

    elif action == "unit":
        state["test_source_files"] = list(getattr(args, "files", []))
        state["test_output_dir"] = str(Path(getattr(args, "output_dir", ".")).resolve())
        state["test_language"] = getattr(args, "language", "auto")
        state["test_instructions"] = getattr(args, "instructions", "")
        try:
            state = unit_test_agent(state)
        except Exception as exc:
            print(style.fail(f"unit_test_agent error: {exc}"))
            return 1

    elif action == "run":
        state["test_working_directory"] = str(Path(getattr(args, "directory", ".")).resolve())
        state["test_runner_command"] = getattr(args, "command", "") or None
        state["test_timeout"] = getattr(args, "timeout", 300)
        try:
            state = test_runner_agent(state)
        except Exception as exc:
            print(style.fail(f"test_runner_agent error: {exc}"))
            return 1

    elif action == "fix":
        state["test_working_directory"] = str(Path(getattr(args, "directory", ".")).resolve())
        state["test_runner_command"] = getattr(args, "command", "") or None
        state["test_fix_max_iterations"] = getattr(args, "max_iterations", 3)
        state["test_context_files"] = getattr(args, "context_files", "") or []
        state["test_timeout"] = getattr(args, "timeout", 300)
        try:
            state = test_fix_agent(state)
        except Exception as exc:
            print(style.fail(f"test_fix_agent error: {exc}"))
            return 1

    elif action == "regression":
        description_parts = getattr(args, "description", [])
        state["test_bug_description"] = " ".join(str(p) for p in description_parts)
        state["test_working_directory"] = str(Path(getattr(args, "directory", ".")).resolve())
        state["test_output_dir"] = str(Path(getattr(args, "directory", ".")).resolve())
        state["test_language"] = getattr(args, "language", "python")
        state["test_context_files"] = getattr(args, "context_files", "") or []
        try:
            state = regression_test_agent(state)
        except Exception as exc:
            print(style.fail(f"regression_test_agent error: {exc}"))
            return 1

    else:
        print(style.fail(f"Unknown test action: {action}"))
        return 1

    report = state.get("test_report", {})
    summary = state.get("test_summary", "")

    if emit_json:
        print(json.dumps(report, indent=2, ensure_ascii=False, default=str))
        return 0 if report.get("status") in ("PASS", "generated") else 1

    print()
    print(_render_test_report(report, style))
    print()
    if summary:
        suite_path = state.get("test_suite_path", "")
        if suite_path:
            print(style.muted(f"  Test files: {suite_path}"))

    artifacts = state.get("a2a", {}).get("artifacts", [])
    for art in artifacts[-1:]:
        meta = art.get("metadata", {})
        json_rpt = meta.get("json_report", "")
        md_rpt = meta.get("md_summary", "")
        if json_rpt:
            print(style.muted(f"  Report: {json_rpt}"))
        if md_rpt:
            print(style.muted(f"  Summary: {md_rpt}"))

    ok = report.get("status") in ("PASS", "generated") or bool(state.get("test_passed"))
    return 0 if ok else 1


def _cmd_mcp(args: argparse.Namespace) -> int:
    style = _style_from_args(args)
    action = getattr(args, "mcp_action", None)

    if not action:
        style2 = _cli_style(None)
        _, cp = _build_parser(style2)
        if "mcp" in cp:
            cp["mcp"].print_help()
        return 0

    try:
        from kendr.mcp_manager import (
            list_servers,
            add_server,
            remove_server,
            toggle_server,
            discover_tools,
        )
    except ImportError as exc:
        print(style.fail(f"MCP manager not available: {exc}"))
        return 1

    def _resolve_server(name_or_id: str) -> dict | None:
        servers = list_servers()
        for srv in servers:
            if srv["id"] == name_or_id or srv["name"].lower() == name_or_id.lower():
                return srv
        return None

    if action == "list":
        servers = list_servers()
        if not servers:
            print(style.muted("No MCP servers registered. Use: kendr mcp add <name> <connection>"))
            return 0
        print(style.heading(f"{'NAME':<28} {'TYPE':<6} {'STATUS':<12} {'TOOLS':>5}  {'ID'}"))
        print(style.muted("-" * 72))
        for srv in servers:
            status = srv.get("status", "unknown")
            enabled = srv.get("enabled", True)
            status_label = status if enabled else "disabled"
            tool_count = srv.get("tool_count", 0)
            name_col = srv["name"][:28]
            line = f"{name_col:<28} {srv.get('type','http'):<6} {status_label:<12} {tool_count:>5}  {srv['id']}"
            if status == "connected" and enabled:
                print(style.ok(line))
            elif not enabled:
                print(style.muted(line))
            elif status == "error":
                print(style.warn(line))
            else:
                print(line)
            tools = srv.get("tools", [])
            if tools:
                for t in tools[:5]:
                    tname = t.get("name", "?")
                    tdesc = (t.get("description", "") or "")[:60]
                    print(style.muted(f"    • {tname:<20}  {tdesc}"))
                if len(tools) > 5:
                    print(style.muted(f"    … {len(tools) - 5} more tools"))
        return 0

    if action == "add":
        name = str(getattr(args, "name_flag", None) or getattr(args, "name", "") or "").strip()
        connection = str(getattr(args, "url_flag", None) or getattr(args, "connection", "") or "").strip()
        server_type = str(getattr(args, "server_type", "http"))
        description = str(getattr(args, "description", ""))
        auth_token = str(getattr(args, "auth_token", ""))
        no_discover = bool(getattr(args, "no_discover", False))

        if not name:
            print(style.fail("Server name is required."))
            return 1
        if not connection:
            print(style.fail("Connection (URL or command) is required."))
            return 1

        srv = add_server(name=name, connection=connection, server_type=server_type, description=description, auth_token=auth_token)
        print(style.ok(f"Registered: {srv['name']}  (ID: {srv['id']})"))
        print(style.muted(f"  Type:       {srv['type']}"))
        print(style.muted(f"  Connection: {srv['connection']}"))

        if not no_discover:
            print(style.muted("  Discovering tools…"))
            result = discover_tools(srv["id"])
            if result.get("ok"):
                tool_count = result.get("tool_count", 0)
                print(style.ok(f"  ✓ {tool_count} tool(s) discovered"))
                for t in result.get("tools", [])[:8]:
                    tname = t.get("name", "?")
                    tdesc = (t.get("description", "") or "")[:60]
                    print(style.muted(f"    • {tname:<20}  {tdesc}"))
                if tool_count > 8:
                    print(style.muted(f"    … {tool_count - 8} more"))
            else:
                err = result.get("error", "unknown error")
                print(style.warn(f"  ⚠ Discovery failed: {err}"))
                print(style.muted("  Server registered. Run 'kendr mcp discover <id>' later."))
        return 0

    if action == "remove":
        key = str(getattr(args, "server_id_or_name", "")).strip()
        srv = _resolve_server(key)
        if srv is None:
            print(style.fail(f"Server not found: {key}"))
            return 1
        removed = remove_server(srv["id"])
        if removed:
            print(style.ok(f"Removed: {srv['name']}  (ID: {srv['id']})"))
        else:
            print(style.fail(f"Failed to remove: {srv['name']}"))
            return 1
        return 0

    if action in ("test", "discover"):
        key = str(getattr(args, "server_id_or_name", "")).strip()
        srv = _resolve_server(key)
        if srv is None:
            print(style.fail(f"Server not found: {key}"))
            return 1
        verb = "Testing" if action == "test" else "Discovering tools on"
        print(style.muted(f"  {verb}: {srv['name']}  ({srv['connection']})"))
        result = discover_tools(srv["id"])
        if result.get("ok"):
            tool_count = result.get("tool_count", 0)
            print(style.ok(f"  ✓ {tool_count} tool(s) available"))
            for t in result.get("tools", []):
                tname = t.get("name", "?")
                tdesc = (t.get("description", "") or "")[:70]
                print(f"    {style.ok('•')} {style.heading(tname):<22}  {style.muted(tdesc)}")
        else:
            err = result.get("error", "unknown error")
            print(style.fail(f"  ✗ {err}"))
            return 1
        return 0

    if action in ("enable", "disable"):
        key = str(getattr(args, "server_id_or_name", "")).strip()
        srv = _resolve_server(key)
        if srv is None:
            print(style.fail(f"Server not found: {key}"))
            return 1
        enabled = action == "enable"
        ok = toggle_server(srv["id"], enabled)
        if ok:
            state_label = "enabled" if enabled else "disabled"
            print(style.ok(f"  {srv['name']} is now {state_label}."))
        else:
            print(style.fail(f"  Toggle failed for {srv['name']}."))
            return 1
        return 0

    if action == "zapier":
        mcp_url = str(getattr(args, "url_flag", None) or getattr(args, "mcp_url", "") or "").strip()
        server_name = str(getattr(args, "name", "Zapier")).strip() or "Zapier"
        no_discover = bool(getattr(args, "no_discover", False))

        if not mcp_url:
            print(style.heading("Zapier MCP Quick-Connect"))
            print()
            print("  Get your personal MCP URL from:")
            print(style.ok("    https://zapier.com/mcp"))
            print()
            print("  Then run:")
            print(style.muted("    kendr mcp zapier https://mcp.zapier.com/api/mcp/s/<token>/mcp"))
            print()
            return 0

        if "zapier.com" not in mcp_url and "mcp.zapier" not in mcp_url:
            print(style.warn("Warning: URL does not look like a Zapier MCP endpoint."))
            print(style.muted("  Expected something like: https://mcp.zapier.com/api/mcp/s/<token>/mcp"))

        print(style.heading(f"Connecting {server_name} MCP…"))
        srv = add_server(
            name=server_name,
            connection=mcp_url,
            server_type="http",
            description="Zapier automation tools via MCP",
            auth_token="",
        )
        print(style.ok(f"  Registered: {srv['name']}  (ID: {srv['id']})"))
        print(style.muted(f"  URL: {srv['connection']}"))

        if not no_discover:
            print(style.muted("  Discovering Zapier tools…"))
            result = discover_tools(srv["id"])
            if result.get("ok"):
                tool_count = result.get("tool_count", 0)
                print(style.ok(f"  ✓ {tool_count} Zapier tool(s) discovered"))
                for t in result.get("tools", [])[:10]:
                    tname = t.get("name", "?")
                    tdesc = (t.get("description", "") or "")[:60]
                    print(style.muted(f"    • {tname:<24}  {tdesc}"))
                if tool_count > 10:
                    print(style.muted(f"    … {tool_count - 10} more tools"))
            else:
                err = result.get("error", "unknown error")
                print(style.warn(f"  ⚠ Discovery failed: {err}"))
                print(style.muted("  Server registered. Run 'kendr mcp discover <id>' when the server is reachable."))
        return 0

    print(style.fail(f"Unknown mcp action: {action}"))
    return 1


def _cmd_generate_standalone(
    args: argparse.Namespace,
    description: str = "",
    project_name: str = "",
    project_stack: str = "",
    project_root: str = "",
    github_repo: str = "",
) -> int:
    style = _cli_style(None)

    def _progress(msg: str) -> None:
        if bool(getattr(args, "quiet", False)):
            return
        try:
            parsed = json.loads(msg)
            text = parsed.get("text", msg)
        except Exception:
            text = msg
        print(text, flush=True)

    try:
        from tasks.project_generation_orchestrator import ProjectGenerationOrchestrator
    except ImportError as exc:
        print(style.fail(f"Cannot import orchestrator: {exc}"))
        return 1

    orch = ProjectGenerationOrchestrator(
        description=description,
        stack=project_stack,
        project_root=project_root,
        project_name=project_name,
        auto_approve=bool(getattr(args, "auto_approve", False)),
        skip_tests=bool(getattr(args, "skip_tests", False)),
        skip_devops=bool(getattr(args, "skip_devops", False)),
        max_fix_iters=3,
        github_repo=github_repo,
        progress_cb=_progress,
    )

    result = orch.run()

    if bool(getattr(args, "json", False)):
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0 if result.get("ok") else 1

    if result.get("ok"):
        print(style.ok(f"\n✓ Project generated at: {result['project_root']}"))
        print(style.muted(f"  Files created: {len(result.get('files_created', []))}"))
        if result.get("github_url"):
            print(style.ok(f"  GitHub: {result['github_url']}"))
        errors = result.get("errors", [])
        if errors:
            print(style.warn(f"  Warnings: {len(errors)}"))
            for err in errors[:3]:
                print(style.muted(f"    - {err[:120]}"))
        return 0

    errors = result.get("errors", [])
    print(style.fail(f"Generation failed: {errors[0] if errors else 'unknown error'}"))
    return 1


def _cmd_generate(args: argparse.Namespace) -> int:
    description = " ".join(args.description).strip()
    if not description:
        if sys.stdin.isatty():
            description = input("Describe the project to generate: ").strip()
        if not description:
            raise SystemExit("A project description is required. Example: kendr generate 'a FastAPI todo API with PostgreSQL'")

    style = _cli_style(None)
    project_name = str(args.name or "").strip()
    project_stack = str(args.stack or "").strip()
    github_repo = str(getattr(args, "github_repo", "") or "").strip()
    standalone_mode = bool(getattr(args, "standalone", False))

    if project_stack:
        from tasks.project_generation_orchestrator import resolve_stack_name
        project_stack = resolve_stack_name(project_stack)

    if bool(args.current_folder):
        configured_working_dir = str(Path.cwd())
    else:
        configured_working_dir = str(args.working_directory or _configured_working_dir()).strip()
    if not configured_working_dir:
        configured_working_dir = input("Set a working folder for generated project output (required): ").strip()
        if not configured_working_dir:
            raise SystemExit("Working folder is required. Configure KENDR_WORKING_DIR in setup or pass --working-directory.")
        save_component_values("core_runtime", {"KENDR_WORKING_DIR": configured_working_dir})
        os.environ["KENDR_WORKING_DIR"] = configured_working_dir
    resolved_working_dir = _resolve_working_dir(configured_working_dir)

    output_root = str(args.output or "").strip()
    if output_root:
        output_root = str(_resolve_working_dir(output_root))

    project_root = output_root or resolved_working_dir

    _emit_status(args, f"[generate] project root: {project_root}")
    if project_name:
        _emit_status(args, f"[generate] project name: {project_name}")
    if project_stack:
        _emit_status(args, f"[generate] stack template: {project_stack}")
    if github_repo:
        _emit_status(args, f"[generate] github repo: {github_repo}")

    if standalone_mode or not _gateway_ready():
        if not standalone_mode:
            _emit_status(args, "[generate] gateway not running — using standalone orchestrator")
        return _cmd_generate_standalone(args, description=description, project_name=project_name,
                                        project_stack=project_stack, project_root=project_root,
                                        github_repo=github_repo)

    query = description
    base_ingest_payload: dict = {
        "max_steps": args.max_steps,
        "working_directory": resolved_working_dir,
        "project_build_mode": True,
        "dev_pipeline_mode": True,
        "project_root": project_root,
    }
    if project_name:
        base_ingest_payload["project_name"] = project_name
    if project_stack:
        base_ingest_payload["project_stack"] = project_stack
    if github_repo:
        base_ingest_payload["github_repo"] = github_repo
    if bool(args.auto_approve):
        base_ingest_payload["auto_approve"] = True
        base_ingest_payload["auto_approve_plan"] = True
    if bool(args.skip_reviews):
        base_ingest_payload["skip_reviews"] = True
    if bool(args.skip_tests):
        base_ingest_payload["skip_test_agent"] = True
    if bool(args.skip_devops):
        base_ingest_payload["skip_devops_agent"] = True

    gateway_base = _gateway_base_url()
    selected_session = _load_cli_session()
    channel = str(selected_session.get("channel", "webchat") or "webchat").strip()
    workspace_id = str(selected_session.get("workspace_id", "default") or "default").strip()
    sender_id = str(selected_session.get("sender_id", "cli_user") or "cli_user").strip()
    chat_id = str(selected_session.get("chat_id", sender_id) or sender_id).strip()
    base_ingest_payload["channel"] = channel
    base_ingest_payload["workspace_id"] = workspace_id
    base_ingest_payload["sender_id"] = sender_id
    base_ingest_payload["chat_id"] = chat_id
    base_ingest_payload["is_group"] = False

    if not _gateway_ready():
        raise SystemExit(
            f"Gateway is not running at {gateway_base}.\n"
            "Start it first with:  kendr gateway start\n"
            f"Then retry:           kendr generate ..."
        )

    client_run_id = f"run_cli_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    ingest_payload = dict(base_ingest_payload)
    ingest_payload["run_id"] = client_run_id
    ingest_payload["text"] = query
    ingest_payload["new_session"] = True

    _emit_status(args, f"[generate] launching project generation run_id={client_run_id}")
    _emit_status(args, style.muted(f"  query: {query[:120]}"))

    log_offsets: dict[str, int] = {}
    run_dir_cache: dict[str, str] = {}

    def _tail_file(path: Path, key: str) -> None:
        try:
            size = path.stat().st_size
        except Exception:
            return
        if key not in log_offsets:
            log_offsets[key] = max(0, size - 4096)
        if size < log_offsets[key]:
            log_offsets[key] = 0
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                handle.seek(log_offsets[key])
                chunk = handle.read()
                log_offsets[key] = handle.tell()
        except Exception:
            return
        for line in chunk.splitlines():
            if line.strip():
                _emit_status(args, f"[log] {line}")

    def _tail_run_logs(run_id: str) -> None:
        runs_root = Path(resolved_working_dir) / "runs"
        if not runs_root.exists():
            return
        matches = [item for item in runs_root.glob(f"{run_id}*") if item.is_dir()]
        if not matches:
            cached = run_dir_cache.get(run_id)
            if cached and Path(cached).exists():
                matches = [Path(cached)]
        if not matches:
            return
        run_path = max(matches, key=lambda p: p.stat().st_mtime)
        run_dir_cache[run_id] = str(run_path)
        for filename in ("execution.log", "agent_work_notes.txt"):
            log_path = run_path / filename
            if log_path.exists():
                _tail_file(log_path, f"{run_path}:{filename}")

    last_progress = ""

    def _poll_progress(run_id: str, prev: str) -> str:
        try:
            sessions = _http_json_get(f"{gateway_base}/task-sessions", timeout_seconds=1.2)
            if isinstance(sessions, list):
                match = next((s for s in sessions if str(s.get("run_id", "")) == run_id), None)
                if isinstance(match, dict):
                    msg = _build_run_progress_message(match)
                    if msg != prev:
                        _emit_status(args, _colorize_run_progress_message(msg, style))
                        return msg
        except Exception:
            pass
        return prev

    holder: dict = {"result": None, "error": None}

    def _submit() -> None:
        try:
            request = urllib.request.Request(
                f"{gateway_base}/ingest",
                data=json.dumps(ingest_payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=600) as response:
                holder["result"] = json.loads(response.read().decode("utf-8"))
        except BaseException as exc:  # noqa: BLE001
            holder["error"] = exc

    worker = threading.Thread(target=_submit, daemon=True)
    worker.start()

    while worker.is_alive():
        worker.join(timeout=1.0)
        last_progress = _poll_progress(client_run_id, last_progress)
        _tail_run_logs(client_run_id)

    if holder["error"]:
        raise SystemExit(f"[generate] failed: {holder['error']}")

    result = holder["result"] or {}
    if bool(args.json):
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0

    # ── Interactive blueprint approval loop (for dev pipeline mode) ───────────
    # When the pipeline pauses awaiting blueprint approval, prompt [y/n] and
    # resume or cancel accordingly. Repeats for revision re-review if needed.
    interactive = bool(getattr(sys.stdin, "isatty", lambda: False)()) and not bool(args.json)
    resume_output_dir: str | None = str(result.get("output_dir") or "").strip() or None

    def _gen_resume_payload(reply_text: str) -> dict:
        return {key: value for key, value in {
            "output_folder": resume_output_dir or "",
            "working_directory": resolved_working_dir,
            "reply": reply_text,
            "text": reply_text,
            "channel": channel,
            "workspace_id": workspace_id,
            "sender_id": sender_id,
            "chat_id": chat_id,
            "is_group": False,
            "max_steps": args.max_steps,
        }.items() if value not in ("", None)}

    max_approval_loops = 5
    approval_loop = 0
    while approval_loop < max_approval_loops:
        approval_loop += 1
        is_paused = (
            bool(result.get("awaiting_user_input"))
            or str(result.get("status", "")).strip().lower() == "awaiting_user_input"
        )
        if not is_paused:
            break
        pending_prompt = str(result.get("pending_user_question") or result.get("final_output") or "").strip()
        if not pending_prompt:
            break

        if interactive:
            # Determine if this is a blueprint approval gate
            pending_kind = str(result.get("pending_user_input_kind") or "").strip().lower()
            is_blueprint_gate = pending_kind in ("blueprint_approval",) or "blueprint" in pending_prompt[:120].lower()
            print()
            print("═" * 72)
            if is_blueprint_gate:
                print("  BLUEPRINT READY FOR REVIEW")
                print("═" * 72)
                print(f"\n{pending_prompt}\n")
                sys.stdout.write("Proceed with this blueprint? [y/n]: ")
                sys.stdout.flush()
                try:
                    answer = sys.stdin.readline().strip().lower()
                except (EOFError, KeyboardInterrupt):
                    answer = "n"
                if answer in ("y", "yes", "approve", "ok", "1"):
                    reply = "approve"
                else:
                    print("\nGeneration cancelled at blueprint review.")
                    return 0
            else:
                print("  PIPELINE PAUSED — AWAITING INPUT")
                print("═" * 72)
                print(f"\n{pending_prompt}\n")
                sys.stdout.write("Reply (or press Ctrl+C to cancel): ")
                sys.stdout.flush()
                try:
                    reply = sys.stdin.readline().strip()
                except (EOFError, KeyboardInterrupt):
                    print("\nGeneration paused. Resume with: kendr resume --reply '<reply>' "
                          f"--working-directory '{resolved_working_dir}'")
                    return 0
                if not reply:
                    print("Empty reply ignored; generation paused.")
                    print(f"Resume with: kendr resume --reply '<reply>' --working-directory '{resolved_working_dir}'")
                    return 0

            # Send resume
            resume_payload = _gen_resume_payload(reply)
            holder2: dict = {"result": None, "error": None}

            def _do_resume(payload: dict = resume_payload, h: dict = holder2) -> None:
                try:
                    req = urllib.request.Request(
                        f"{gateway_base}/resume",
                        data=json.dumps(payload).encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        method="POST",
                    )
                    with urllib.request.urlopen(req, timeout=600) as resp:
                        h["result"] = json.loads(resp.read().decode("utf-8"))
                except BaseException as exc:  # noqa: BLE001
                    h["error"] = exc

            worker2 = threading.Thread(target=_do_resume, daemon=True)
            worker2.start()
            _emit_status(args, "[generate] resuming pipeline…")
            last_progress = ""
            while worker2.is_alive():
                worker2.join(timeout=1.0)
                try:
                    sessions = _http_json_get(f"{gateway_base}/task-sessions", timeout_seconds=1.2)
                    if isinstance(sessions, list):
                        match = next(
                            (s for s in sessions if str(s.get("run_id", "")) == client_run_id), None
                        )
                        if isinstance(match, dict):
                            msg = _build_run_progress_message(match)
                            if msg != last_progress:
                                _emit_status(args, _colorize_run_progress_message(msg, style))
                                last_progress = msg
                except Exception:
                    pass

            if holder2["error"]:
                raise SystemExit(f"[generate] resume failed: {holder2['error']}")
            result = holder2["result"] or {}
            if result.get("output_dir"):
                resume_output_dir = str(result["output_dir"]).strip() or resume_output_dir
        else:
            # Non-interactive: print the pending question and exit
            print(pending_prompt)
            _emit_status(
                args,
                f"Generation paused. Resume with: kendr resume --reply 'approve' "
                f"--working-directory '{resolved_working_dir}'"
            )
            return 0

    final = str(result.get("final_output") or result.get("draft_response") or "").strip()
    pending = str(result.get("pending_user_question") or "").strip()
    built_root = str(result.get("project_root") or "").strip()

    if final:
        print(final)
    if pending and pending != final:
        print(pending)
    if built_root:
        _emit_status(args, style.ok(f"[generate] project output: {built_root}"))

    return 0


def _cmd_project(args: argparse.Namespace) -> int:
    style = _style_from_args(args)
    action = args.project_action

    try:
        from kendr.project_manager import (
            list_projects, get_active_project, set_active_project,
            add_project, remove_project, git_status, git_pull, git_push,
            git_commit, git_commit_and_push, git_clone, run_shell,
            list_project_services, start_project_service, stop_project_service,
            restart_project_service, read_project_service_log,
        )
    except ImportError as exc:
        print(style.fail(f"Project manager not available: {exc}"))
        return 1

    def _resolve_project(path_or_id: str = "") -> dict | None:
        projects = list_projects()
        if not path_or_id:
            return get_active_project()
        # Try by ID first, then by path prefix
        for p in projects:
            if p["id"] == path_or_id or os.path.abspath(path_or_id) == p["path"]:
                return p
        # Try adding it on the fly if it's a valid path
        if os.path.isdir(path_or_id):
            return add_project(path_or_id)
        return None

    def _print_services(services: list[dict]) -> None:
        if not services:
            print(style.muted("  Services: none tracked"))
            return
        print(style.heading(f"{'SERVICE':<28} {'STATE':<10} {'PORT':<6} {'PID':<7} {'TYPE':<10} {'URL'}"))
        for service in services:
            status = str(service.get("status") or ("running" if service.get("running") else "stopped"))
            state_text = status[:10]
            if status == "running":
                state_text = style.ok(state_text)
            elif status == "degraded":
                state_text = style.warn(state_text)
            else:
                state_text = style.muted(state_text)
            name = str(service.get("name") or service.get("id") or "")[:28]
            port = str(service.get("port") or "-")
            pid = str(service.get("pid") or "-")
            kind = str(service.get("kind") or "service")[:10]
            url = str(service.get("url") or service.get("log_path") or "")
            print(f"{name:<28} {state_text:<10} {port:<6} {pid:<7} {kind:<10} {url}")

    if action == "list":
        projects = list_projects()
        active = get_active_project()
        active_id = active["id"] if active else None
        if not projects:
            print(style.muted("No projects registered. Use: kendr project add <path>"))
            return 0
        print(style.heading(f"{'NAME':<30} {'PATH':<45} {'ID'}"))
        for p in projects:
            marker = "* " if p["id"] == active_id else "  "
            name = (marker + p["name"])[:30]
            path = p["path"][:45]
            print(f"{style.ok(name) if p['id']==active_id else name:<30} {path:<45} {p['id']}")
        return 0

    if action == "add":
        path = os.path.abspath(args.path)
        try:
            entry = add_project(path, args.name)
            print(style.ok(f"Added project: {entry['name']}"))
            print(style.muted(f"  Path: {entry['path']}"))
            print(style.muted(f"  ID:   {entry['id']}"))
        except Exception as exc:
            print(style.fail(f"Error: {exc}"))
            return 1
        return 0

    if action == "open":
        proj = _resolve_project(args.path_or_id)
        if not proj:
            path = os.path.abspath(args.path_or_id)
            if os.path.isdir(path):
                proj = add_project(path)
            else:
                print(style.fail(f"Project not found: {args.path_or_id}"))
                return 1
        set_active_project(proj["id"])
        print(style.ok(f"Active project: {proj['name']}  ({proj['path']})"))
        if getattr(args, "ui", False):
            ui_port = int(os.getenv("KENDR_UI_PORT", "2151"))
            url = f"http://localhost:{ui_port}/projects"
            import webbrowser
            webbrowser.open(url)
            print(style.muted(f"Opening: {url}"))
        return 0

    if action == "remove":
        proj = _resolve_project(args.path_or_id)
        if not proj:
            print(style.fail(f"Project not found: {args.path_or_id}"))
            return 1
        remove_project(proj["id"])
        print(style.ok(f"Removed: {proj['name']}"))
        return 0

    if action == "status":
        proj_arg = getattr(args, "project", "")
        proj = _resolve_project(proj_arg)
        if not proj:
            print(style.fail("No active project. Use: kendr project add <path>"))
            return 1
        print(style.heading(f"Project: {proj['name']}"))
        print(style.muted(f"  Path: {proj['path']}"))
        print(style.muted(f"  ID:   {proj['id']}"))
        s = git_status(proj["path"])
        if not s.get("is_git"):
            print(style.muted("  Git: not a git repository"))
            return 0
        print(style.ok(f"  Branch: {s.get('branch', '?')}"))
        print(style.muted(f"  Remote: {s.get('remote') or 'none'}"))
        print(style.muted(f"  Last commit: {s.get('last_commit') or 'none'}"))
        if s.get("clean"):
            print(style.ok("  Status: clean"))
        else:
            if s.get("changed"):
                print(style.warn(f"  Modified: {', '.join(s['changed'][:8])}"))
            if s.get("staged"):
                print(style.ok(f"  Staged: {', '.join(s['staged'][:8])}"))
            if s.get("untracked"):
                print(style.muted(f"  Untracked: {', '.join(s['untracked'][:8])}"))
        services = list_project_services(proj["id"], include_stopped=True)
        if services:
            print()
            _print_services(services)
        return 0

    if action == "shell":
        proj_arg = getattr(args, "project", "")
        proj = _resolve_project(proj_arg)
        if not proj:
            print(style.fail("No active project. Use: kendr project add <path>"))
            return 1
        command = " ".join(args.command)
        result = run_shell(command, proj["path"])
        if result["stdout"]:
            print(result["stdout"], end="")
        if result["stderr"]:
            print(style.fail(result["stderr"]), end="", file=sys.stderr)
        return result["returncode"]

    if action == "git":
        proj_arg = getattr(args, "project", "")
        proj = _resolve_project(proj_arg)
        if not proj:
            print(style.fail("No active project. Use: kendr project add <path>"))
            return 1
        git_cmd = " ".join(args.git_args)
        # Handle shorthand actions
        if git_cmd.startswith("status"):
            s = git_status(proj["path"])
            if not s.get("is_git"):
                print(style.fail("Not a git repository"))
                return 1
            print(style.ok(f"Branch: {s.get('branch','?')}  |  Remote: {s.get('remote') or 'none'}"))
            print(f"  Last commit: {s.get('last_commit','none')}")
            if s.get("clean"):
                print(style.ok("  Working tree clean"))
            else:
                for f in (s.get("changed") or []):
                    print(style.warn(f"  M  {f}"))
                for f in (s.get("staged") or []):
                    print(style.ok(f"  S  {f}"))
                for f in (s.get("untracked") or []):
                    print(style.muted(f"  ?  {f}"))
            return 0
        elif git_cmd == "pull":
            result = git_pull(proj["path"])
        elif git_cmd == "push":
            result = git_push(proj["path"])
        elif git_cmd.startswith("commit "):
            msg = git_cmd[len("commit "):].strip().lstrip("-m").strip().strip('"\'')
            result = git_commit(proj["path"], msg)
        else:
            # Pass raw git command
            result = run_shell(f"git {git_cmd}", proj["path"])
        if result.get("stdout"):
            print(result["stdout"], end="")
        if result.get("stderr"):
            print(result["stderr"], end="", file=sys.stderr)
        return 0 if result.get("ok") else 1

    if action == "service":
        proj_arg = getattr(args, "project", "")
        proj = _resolve_project(proj_arg)
        if not proj:
            print(style.fail("No active project. Use: kendr project add <path>"))
            return 1
        service_action = getattr(args, "project_service_action", "")

        if service_action == "list":
            services = list_project_services(proj["id"], include_stopped=not bool(getattr(args, "running_only", False)))
            _print_services(services)
            return 0

        if service_action == "start":
            try:
                service = start_project_service(
                    proj["id"],
                    name=args.name,
                    command=getattr(args, "command", ""),
                    kind=getattr(args, "kind", ""),
                    cwd=getattr(args, "cwd", ""),
                    port=(getattr(args, "port", 0) or None),
                    health_url=getattr(args, "health_url", ""),
                    service_id=getattr(args, "service_id", ""),
                )
            except Exception as exc:
                print(style.fail(f"Error: {exc}"))
                return 1
            print(style.ok(f"Started service: {service.get('name') or service.get('id')}"))
            print(style.muted(f"  ID:   {service.get('id')}"))
            print(style.muted(f"  PID:  {service.get('pid') or '-'}"))
            print(style.muted(f"  Log:  {service.get('log_path') or '-'}"))
            if service.get("url"):
                print(style.muted(f"  URL:  {service.get('url')}"))
            return 0

        if service_action == "stop":
            try:
                service = stop_project_service(proj["id"], args.service_id)
            except Exception as exc:
                print(style.fail(f"Error: {exc}"))
                return 1
            print(style.ok(f"Stopped service: {service.get('name') or service.get('id')}"))
            print(style.muted(f"  Log:  {service.get('log_path') or '-'}"))
            return 0

        if service_action == "restart":
            try:
                service = restart_project_service(proj["id"], args.service_id)
            except Exception as exc:
                print(style.fail(f"Error: {exc}"))
                return 1
            print(style.ok(f"Restarted service: {service.get('name') or service.get('id')}"))
            print(style.muted(f"  PID:  {service.get('pid') or '-'}"))
            print(style.muted(f"  Log:  {service.get('log_path') or '-'}"))
            return 0

        if service_action == "logs":
            log_result = read_project_service_log(proj["id"], args.service_id, max_bytes=max(int(args.bytes), 1024))
            if not log_result.get("ok"):
                print(style.fail(f"Error: {log_result.get('error') or 'unable to read logs'}"))
                return 1
            content = str(log_result.get("content") or "")
            if content:
                print(content, end="" if content.endswith("\n") else "\n")
            else:
                print(style.muted("(log file is empty)"))
            return 0

    print(style.fail(f"Unknown project action: {action}"))
    return 1


def _cmd_rag(args: argparse.Namespace) -> int:
    style = _style_from_args(args)
    action = args.rag_action

    try:
        from kendr.rag_manager import (
            list_kbs, get_kb, get_active_kb, set_active_kb,
            create_kb, delete_kb, add_source, update_vector_config,
            update_reranker_config, toggle_agent, index_kb, get_index_job,
            query_kb, generate_answer, kb_status,
        )
    except ImportError as exc:
        print(style.fail(f"RAG manager not available: {exc}"))
        return 1

    def _resolve_kb(name_or_id: str = "") -> dict | None:
        kbs = list_kbs()
        if not name_or_id:
            return get_active_kb()
        for kb in kbs:
            if kb["id"] == name_or_id or kb["name"].lower() == name_or_id.lower():
                return kb
        return None

    if action == "list":
        kbs = list_kbs()
        active = get_active_kb()
        active_id = active["id"] if active else None
        if not kbs:
            print(style.muted("No knowledge bases. Use: kendr rag create <name>"))
            return 0
        print(style.heading(f"{'NAME':<28} {'STATUS':<10} {'CHUNKS':>7} {'SOURCES':>8}  {'ID'}"))
        for kb in kbs:
            marker = "★ " if kb["id"] == active_id else "  "
            name = (marker + kb["name"])[:28]
            s = kb.get("stats", {})
            status = kb.get("status", "empty")
            line = f"{name:<28} {status:<10} {s.get('total_chunks',0):>7} {len(kb.get('sources',[{'':[]}])):>8}  {kb['id']}"
            if kb["id"] == active_id:
                print(style.ok(line))
            else:
                print(line)
        return 0

    if action == "create":
        try:
            kb = create_kb(args.name, description=getattr(args, "description", ""))
            print(style.ok(f"Created KB: {kb['name']}"))
            print(style.muted(f"  ID: {kb['id']}"))
            print(style.muted(f"  Collection: {kb['collection_name']}"))
        except Exception as exc:
            print(style.fail(f"Error: {exc}"))
            return 1
        return 0

    if action == "delete":
        kb = _resolve_kb(args.name_or_id)
        if not kb:
            print(style.fail(f"KB not found: {args.name_or_id}"))
            return 1
        ans = input(f"Delete '{kb['name']}'? [y/N] ")
        if ans.strip().lower() != "y":
            print("Cancelled.")
            return 0
        delete_kb(kb["id"])
        print(style.ok(f"Deleted: {kb['name']}"))
        return 0

    if action == "activate":
        kb = _resolve_kb(args.name_or_id)
        if not kb:
            print(style.fail(f"KB not found: {args.name_or_id}"))
            return 1
        set_active_kb(kb["id"])
        print(style.ok(f"Active KB: {kb['name']}"))
        return 0

    if action == "status":
        kb = _resolve_kb(getattr(args, "kb", ""))
        if not kb:
            print(style.fail("No KB found. Use: kendr rag create <name>"))
            return 1
        s = kb_status(kb["id"])
        print(style.heading(f"KB: {kb['name']}  ({kb['id']})"))
        print(style.muted(f"  Status:    {s.get('status','empty')}"))
        print(style.muted(f"  Backend:   {s.get('vector_backend','chromadb')} ({'✓' if s.get('backend_ok') else '✗'})"))
        print(style.muted(f"  Embedding: {s.get('embedding_model','')}"))
        print(style.muted(f"  Reranker:  {s.get('reranker','')}"))
        stats = s.get("stats", {})
        print(style.muted(f"  Chunks:    {stats.get('total_chunks',0)}"))
        print(style.muted(f"  Items:     {stats.get('total_items',0)}"))
        print(style.muted(f"  Agents:    {', '.join(s.get('enabled_agents',[]) or ['none'])}"))
        sources = kb.get("sources", [])
        if sources:
            print(style.heading("\n  Sources:"))
            for src in sources:
                dot = "✓" if src.get("status") == "indexed" else ("⚡" if src.get("status") == "indexing" else "○")
                print(style.muted(f"    {dot} [{src['type']}] {src['label']}  ({src.get('stats',{}).get('chunks',0)} chunks)"))
        return 0

    if action == "add-source":
        kb = _resolve_kb(getattr(args, "kb", ""))
        if not kb:
            print(style.fail("No KB found."))
            return 1
        try:
            src = add_source(
                kb["id"],
                args.source_type,
                label=args.label,
                path=getattr(args, "path", ""),
                url=getattr(args, "url", ""),
                db_url=getattr(args, "db_url", ""),
                recursive=getattr(args, "recursive", True),
                max_files=getattr(args, "max_files", 300),
                max_pages=getattr(args, "max_pages", 20),
                extensions=getattr(args, "extensions", ""),
                tables=getattr(args, "tables", ""),
            )
            print(style.ok(f"Added source: {src['label']}  [{src['type']}]  ID: {src['source_id']}"))
        except Exception as exc:
            print(style.fail(f"Error: {exc}"))
            return 1
        return 0

    if action == "index":
        kb = _resolve_kb(getattr(args, "kb", ""))
        if not kb:
            print(style.fail("No KB found."))
            return 1
        print(style.muted(f"Starting indexing for '{kb['name']}'…"))
        job = index_kb(kb["id"])
        print(style.ok(f"Indexing started. Status: {job.get('status','running')}"))
        if getattr(args, "wait", False):
            import time
            print(style.muted("Waiting for completion (Ctrl+C to stop waiting)…"))
            try:
                while True:
                    time.sleep(2)
                    j = get_index_job(kb["id"])
                    if not j:
                        break
                    status = j.get("status", "running")
                    done = j.get("sources_done", 0)
                    total = j.get("sources_total", 0)
                    chunks = j.get("chunks_indexed", 0)
                    print(f"\r  {status}  {done}/{total} sources  {chunks} chunks indexed", end="", flush=True)
                    if status != "running":
                        print()
                        break
            except KeyboardInterrupt:
                print()
        return 0

    if action == "query":
        kb = _resolve_kb(getattr(args, "kb", ""))
        if not kb:
            print(style.fail("No KB found."))
            return 1
        query_str = " ".join(args.query)
        top_k = getattr(args, "top_k", 8)
        with_ai = getattr(args, "ai", False)
        print(style.muted(f"Searching '{kb['name']}'…"))
        try:
            if with_ai:
                result = generate_answer(kb["id"], query_str, top_k=top_k)
                answer = result.get("answer", "")
                print(style.heading("\nAnswer:"))
                print(answer)
            else:
                result = query_kb(kb["id"], query_str, top_k=top_k)
            hits = result.get("hits", [])
            print(style.heading(f"\nRetrieved {len(hits)} chunks  (reranker: {result.get('algorithm','none')}):"))
            for i, hit in enumerate(hits, start=1):
                source = hit.get("source", "?")
                score = hit.get("score")
                score_str = f"{score:.4f}" if score is not None else "?"
                text = str(hit.get("text", ""))[:200].replace("\n", " ")
                print(style.ok(f"[{i}] score={score_str}  source={source}"))
                print(style.muted(f"    {text}"))
        except Exception as exc:
            print(style.fail(f"Error: {exc}"))
            return 1
        return 0

    if action == "config-vector":
        kb = _resolve_kb(getattr(args, "kb", ""))
        if not kb:
            print(style.fail("No KB found."))
            return 1
        cfg = {}
        if getattr(args, "backend", None):
            cfg["backend"] = args.backend
        if getattr(args, "qdrant_url", ""):
            cfg["qdrant_url"] = args.qdrant_url
        if getattr(args, "pgvector_url", ""):
            cfg["pgvector_url"] = args.pgvector_url
        if getattr(args, "embedding_model", ""):
            cfg["embedding_model"] = args.embedding_model
        if not cfg:
            vc = kb.get("vector_config", {})
            print(style.heading("Current vector config:"))
            for k, v in vc.items():
                print(style.muted(f"  {k}: {v}"))
            return 0
        try:
            update_vector_config(kb["id"], cfg)
            print(style.ok("Vector config updated."))
        except Exception as exc:
            print(style.fail(f"Error: {exc}"))
            return 1
        return 0

    if action == "config-reranker":
        kb = _resolve_kb(getattr(args, "kb", ""))
        if not kb:
            print(style.fail("No KB found."))
            return 1
        cfg = {}
        if getattr(args, "algorithm", None):
            cfg["algorithm"] = args.algorithm
        if getattr(args, "top_k", 0):
            cfg["top_k"] = args.top_k
        if getattr(args, "keyword_weight", 0.0):
            cfg["keyword_weight"] = args.keyword_weight
        if getattr(args, "cohere_api_key", ""):
            cfg["cohere_api_key"] = args.cohere_api_key
        if not cfg:
            rc = kb.get("reranker_config", {})
            print(style.heading("Current reranker config:"))
            for k, v in rc.items():
                print(style.muted(f"  {k}: {v}"))
            return 0
        try:
            update_reranker_config(kb["id"], cfg)
            print(style.ok("Reranker config updated."))
        except Exception as exc:
            print(style.fail(f"Error: {exc}"))
            return 1
        return 0

    if action in ("enable-agent", "disable-agent"):
        kb = _resolve_kb(getattr(args, "kb", ""))
        if not kb:
            print(style.fail("No KB found."))
            return 1
        enabled = action == "enable-agent"
        try:
            toggle_agent(kb["id"], args.agent, enabled)
            verb = "Enabled" if enabled else "Disabled"
            print(style.ok(f"{verb} agent '{args.agent}' for KB '{kb['name']}'."))
        except Exception as exc:
            print(style.fail(f"Error: {exc}"))
            return 1
        return 0

    print(style.fail(f"Unknown rag action: {action}"))
    return 1


def _cmd_research(args: argparse.Namespace) -> int:
    query = " ".join(args.query).strip()
    if not query:
        if sys.stdin.isatty():
            query = input("Enter your research query: ").strip()
        if not query:
            raise SystemExit("A research query is required. Example: kendr research 'transformer architectures 2024'")

    if bool(args.current_folder):
        configured_working_dir = str(Path.cwd())
    else:
        configured_working_dir = str(args.working_directory or _configured_working_dir()).strip()
    if not configured_working_dir:
        configured_working_dir = input("Set a working folder for research output (required): ").strip()
        if not configured_working_dir:
            raise SystemExit("Working folder is required. Configure KENDR_WORKING_DIR in setup or pass --working-directory.")
        save_component_values("core_runtime", {"KENDR_WORKING_DIR": configured_working_dir})
        os.environ["KENDR_WORKING_DIR"] = configured_working_dir
    resolved_working_dir = _resolve_working_dir(configured_working_dir)

    base_ingest_payload: dict = {
        "max_steps": args.max_steps,
        "working_directory": resolved_working_dir,
        "deep_research_mode": True,
        "long_document_mode": True,
    }

    raw_sources = str(args.sources or "").strip()
    if raw_sources:
        parsed_sources = [s.strip().lower() for s in raw_sources.split(",") if s.strip()]
        if parsed_sources:
            base_ingest_payload["research_sources"] = parsed_sources
            base_ingest_payload["research_pipeline_enabled"] = True
            base_ingest_payload["research_pipeline_completed"] = False
    else:
        base_ingest_payload["research_pipeline_enabled"] = True
        base_ingest_payload["research_pipeline_completed"] = False

    if int(args.pages or 0) > 0:
        base_ingest_payload["long_document_pages"] = int(args.pages)
        base_ingest_payload["long_document_collect_sources_first"] = True
    else:
        base_ingest_payload["long_document_collect_sources_first"] = True

    if str(args.title or "").strip():
        base_ingest_payload["long_document_title"] = str(args.title).strip()
    if str(args.research_model or "").strip():
        base_ingest_payload["research_model"] = str(args.research_model).strip()
    parsed_formats = _parse_research_formats(getattr(args, "format", ""))
    if parsed_formats:
        base_ingest_payload["research_output_formats"] = parsed_formats
    if str(getattr(args, "cite", "") or "").strip():
        base_ingest_payload["research_citation_style"] = str(args.cite).strip().lower()
    base_ingest_payload["research_enable_plagiarism_check"] = not bool(getattr(args, "no_plagiarism", False))
    base_ingest_payload["research_web_search_enabled"] = not bool(getattr(args, "no_web_search", False))
    if str(getattr(args, "date_range", "") or "").strip():
        base_ingest_payload["research_date_range"] = str(args.date_range).strip()
    if int(getattr(args, "max_sources", 0) or 0) > 0:
        base_ingest_payload["research_max_sources"] = int(args.max_sources)
    if bool(getattr(args, "checkpoint", False)):
        base_ingest_payload["research_checkpoint_enabled"] = True
    deep_research_links = _normalize_url_inputs(list(getattr(args, "deep_research_link", []) or []))
    if deep_research_links:
        base_ingest_payload["deep_research_source_urls"] = deep_research_links
    if bool(args.auto_approve):
        base_ingest_payload["auto_approve"] = True

    drive_paths = _normalize_drive_paths(args.drive)
    if bool(getattr(args, "no_web_search", False)) and deep_research_links:
        raise SystemExit(
            "--no-web-search cannot be combined with --deep-research-link.\n"
            "Use local files/folders only for a local-only deep research run."
        )
    if bool(getattr(args, "no_web_search", False)) and not drive_paths:
        raise SystemExit(
            "--no-web-search requires at least one --drive or --deep-research-path source."
        )
    if drive_paths:
        base_ingest_payload["local_drive_paths"] = drive_paths
        base_ingest_payload["local_drive_recursive"] = True
        base_ingest_payload["local_drive_working_directory"] = resolved_working_dir
        base_ingest_payload["local_drive_force_long_document"] = True
        if not raw_sources:
            base_ingest_payload.setdefault("research_sources", ["local"])

    gateway_base = _gateway_base_url()
    selected_session = _load_cli_session()
    channel = str(selected_session.get("channel", "webchat") or "webchat").strip()
    workspace_id = str(selected_session.get("workspace_id", "default") or "default").strip()
    sender_id = str(selected_session.get("sender_id", "cli_user") or "cli_user").strip()
    chat_id = str(selected_session.get("chat_id", sender_id) or sender_id).strip()
    base_ingest_payload["channel"] = channel
    base_ingest_payload["workspace_id"] = workspace_id
    base_ingest_payload["sender_id"] = sender_id
    base_ingest_payload["chat_id"] = chat_id
    base_ingest_payload["is_group"] = False

    if not _gateway_ready():
        raise SystemExit(
            f"Gateway is not running at {gateway_base}.\n"
            "Start it first with:  kendr gateway start\n"
            f"Then retry:           kendr research ..."
        )

    client_run_id = f"run_cli_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    ingest_payload = dict(base_ingest_payload)
    ingest_payload["run_id"] = client_run_id
    ingest_payload["text"] = query
    ingest_payload["new_session"] = True

    _emit_status(args, f"[research] starting research run_id={client_run_id}")

    holder: dict = {"result": None, "error": None}

    def _submit() -> None:
        try:
            request = urllib.request.Request(
                f"{gateway_base}/ingest",
                data=json.dumps(ingest_payload).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(request, timeout=600) as response:
                holder["result"] = json.loads(response.read().decode("utf-8"))
        except BaseException as exc:  # noqa: BLE001
            holder["error"] = exc

    log_offsets: dict[str, int] = {}

    def _tail_file(path: Path, key: str) -> None:
        try:
            size = path.stat().st_size
        except Exception:
            return
        if key not in log_offsets:
            log_offsets[key] = max(0, size - 4096)
        if size < log_offsets[key]:
            log_offsets[key] = 0
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                handle.seek(log_offsets[key])
                chunk = handle.read()
                log_offsets[key] = handle.tell()
        except Exception:
            return
        for line in chunk.splitlines():
            if line.strip():
                _emit_status(args, f"[log] {line}")

    def _tail_run_logs(run_id: str) -> None:
        runs_root = Path(resolved_working_dir) / "runs"
        if not runs_root.exists():
            return
        matches = [item for item in runs_root.glob(f"{run_id}*") if item.is_dir()]
        if not matches:
            return
        run_path = max(matches, key=lambda p: p.stat().st_mtime)
        for filename in ("execution.log", "agent_work_notes.txt"):
            log_path = run_path / filename
            if log_path.exists():
                _tail_file(log_path, f"{run_path}:{filename}")

    style = _cli_style(None)
    last_progress = ""

    worker = threading.Thread(target=_submit, daemon=True)
    worker.start()
    while worker.is_alive():
        worker.join(timeout=1.0)
        try:
            sessions = _http_json_get(f"{gateway_base}/task-sessions", timeout_seconds=1.2)
            if isinstance(sessions, list):
                match = next((s for s in sessions if str(s.get("run_id", "")) == client_run_id), None)
                if isinstance(match, dict):
                    msg = _build_run_progress_message(match)
                    if msg != last_progress:
                        _emit_status(args, _colorize_run_progress_message(msg, style))
                        last_progress = msg
        except Exception:
            pass
        _tail_run_logs(client_run_id)

    if holder["error"]:
        raise SystemExit(f"[research] failed: {holder['error']}")

    result = holder["result"] or {}
    if bool(args.json):
        print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        return 0

    final = str(result.get("final_output") or result.get("draft_response") or "").strip()
    pending = str(result.get("pending_user_question") or "").strip()
    compiled = str(result.get("long_document_compiled_path") or "").strip()

    if final:
        print(final)
    if pending and pending != final:
        print(pending)
    if compiled:
        _emit_status(args, style.ok(f"[research] document saved to: {compiled}"))

    return 0


def _emit_run_summary_table(run_id: str) -> None:
    if not str(run_id or "").strip():
        return
    try:
        import datetime as _dt
        from kendr.persistence import list_agent_executions_for_run, list_artifacts_for_run
        from kendr import cli_output as out

        rows = list_agent_executions_for_run(run_id)
        if not rows:
            return

        artifacts = list_artifacts_for_run(run_id)

        def _ts_float(ts_str: str) -> float:
            try:
                return _dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00")).timestamp()
            except Exception:
                return 0.0

        agent_intervals = []
        for row in rows:
            t0 = _ts_float(row.get("timestamp") or "")
            t1 = _ts_float(row.get("completed_at") or "") or t0
            agent_intervals.append((t0, t1, row.get("agent_name", "")))

        artifact_by_agent: dict = {}
        for art in artifacts:
            art_ts = _ts_float(art.get("timestamp") or "")
            best_agent = ""
            for t0, t1, agent in agent_intervals:
                if t0 <= art_ts <= t1 + 0.001:
                    best_agent = agent
                    break
            if not best_agent and agent_intervals:
                best_agent = agent_intervals[-1][2]
            artifact_by_agent.setdefault(best_agent, []).append(art.get("name") or art.get("kind") or "artifact")

        steps = []
        for row in rows:
            started = row.get("timestamp") or ""
            completed = row.get("completed_at") or ""
            dur = None
            if started and completed:
                try:
                    t0 = _dt.datetime.fromisoformat(started.replace("Z", "+00:00"))
                    t1 = _dt.datetime.fromisoformat(completed.replace("Z", "+00:00"))
                    dur = (t1 - t0).total_seconds()
                except Exception:
                    pass
            agent = row.get("agent_name", "")
            steps.append({
                "agent": agent,
                "status": row.get("status", ""),
                "duration": dur,
                "artifacts": artifact_by_agent.get(agent, []),
            })
        out.run_summary(steps)
    except ImportError:
        pass


def _cmd_run(args: argparse.Namespace) -> int:
    from kendr import cli_output as out

    query = " ".join(args.query).strip() or input("Enter your query: ").strip()

    if bool(getattr(args, "background", False)):
        bg_args = [sys.executable, "-m", "kendr.cli", "run"] + list(args.query)
        for flag_name in (
            "working_directory", "max_steps", "channel", "workspace_id",
            "sender_id", "chat_id",
        ):
            val = str(getattr(args, flag_name, "") or "").strip()
            if val:
                bg_args += [f"--{flag_name.replace('_', '-')}", val]
        for bool_flag in ("auto_approve", "skip_reviews", "current_folder"):
            if bool(getattr(args, bool_flag, False)):
                bg_args.append(f"--{bool_flag.replace('_', '-')}")
        log_dir = Path.home() / ".kendr" / "bg_runs"
        log_dir.mkdir(parents=True, exist_ok=True)
        run_ts = int(time.time())
        log_file = log_dir / f"bg_run_{run_ts}.log"
        with open(log_file, "w") as lf:
            proc = subprocess.Popen(
                bg_args,
                stdout=lf,
                stderr=lf,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
        sys.stdout.write(f"[kendr] Background run started (pid={proc.pid})\n")
        sys.stdout.write(f"[kendr] Log: {log_file}\n")
        sys.stdout.write(f"[kendr] Check status: kendr status\n")
        sys.stdout.flush()
        return 0

    configured_working_dir = ""
    if bool(args.current_folder):
        configured_working_dir = str(Path.cwd())
    else:
        configured_working_dir = str(args.working_directory or _configured_working_dir()).strip()
    if not configured_working_dir:
        configured_working_dir = input("Set a working folder for task runs (required): ").strip()
        if not configured_working_dir:
            raise SystemExit("Working folder is required. Configure KENDR_WORKING_DIR in setup or pass --working-directory.")
        save_component_values("core_runtime", {"KENDR_WORKING_DIR": configured_working_dir})
        os.environ["KENDR_WORKING_DIR"] = configured_working_dir
    resolved_working_dir = _resolve_working_dir(configured_working_dir)

    if not bool(getattr(args, "json", False)) and not bool(getattr(args, "quiet", False)):
        try:
            out.startup_banner(
                version=_cli_version(),
                model=os.getenv("KENDR_MODEL", os.getenv("OPENAI_MODEL", "")),
                working_dir=resolved_working_dir,
                tagline=_cli_tagline(),
            )
        except Exception:
            pass

    if _is_project_code_request(query):
        cwd = str(Path.cwd().resolve())
        if _looks_like_project_root(cwd) and not _looks_like_project_root(resolved_working_dir):
            _emit_status(
                args,
                (
                    "[run] detected project/code analysis request; "
                    f"switching working directory from {resolved_working_dir} to current folder {cwd}"
                ),
            )
            resolved_working_dir = cwd

    test_requested, test_intent_type = _is_test_intent(query)
    if test_requested:
        _emit_status(args, f"[run] detected testing intent ({test_intent_type}) — running test agent directly")
        return _run_test_intent_standalone(args, query, test_intent_type, resolved_working_dir)

    security_requested = bool(args.security_authorized) or bool(args.security_target_url) or is_security_assessment_query(query)
    security_target_url = str(args.security_target_url or "").strip()
    security_authorization_note = str(args.security_authorization_note or "").strip()
    security_scan_profile = str(args.security_scan_profile or "").strip()
    security_authorized = bool(args.security_authorized)

    if security_requested:
        if not security_target_url and sys.stdin.isatty():
            security_target_url = input("Security target URL (required for authorized scanning): ").strip()
        if not security_authorized:
            if not sys.stdin.isatty():
                raise SystemExit(
                    "Security workflow requested but --security-authorized was not provided in non-interactive mode.\n"
                    + authorization_process_text(security_target_url)
                )
            try:
                from kendr import cli_output as _cout
                _cout.print_text(authorization_process_text(security_target_url), style="grey62")
            except Exception:
                sys.stdout.write(authorization_process_text(security_target_url) + "\n")
                sys.stdout.flush()
            confirm = input("Type YES to confirm you have explicit written authorization for this target: ").strip()
            if confirm != "YES":
                raise SystemExit("Security workflow canceled. Authorization was not confirmed.")
            security_authorized = True
        if not security_authorization_note and sys.stdin.isatty():
            security_authorization_note = input("Authorization note/ticket reference (required): ").strip()
        if not security_target_url:
            raise SystemExit("security_target_url is required for security workflow.")
        if not security_authorization_note:
            raise SystemExit(
                "security_authorization_note is required for security workflow.\n"
                + authorization_process_text(security_target_url)
            )
        if not security_scan_profile:
            security_scan_profile = "deep"
        auto_install_security_tools = _truthy(os.getenv("SECURITY_AUTO_INSTALL_TOOLS", "true")) and not bool(
            args.no_auto_install_security_tools
        )
        _auto_install_security_tools_if_needed(enabled=auto_install_security_tools)

    gateway_base = _gateway_base_url()

    selected_session = {}
    if str(args.session_key or "").strip():
        selected_session = _session_parts_from_key(str(args.session_key))
        if not selected_session:
            raise SystemExit("Invalid --session-key format. Expected channel:workspace:chat:scope")
    else:
        selected_session = _load_cli_session()
    base_ingest_payload = {
        "max_steps": args.max_steps,
        "working_directory": resolved_working_dir,
    }
    if bool(args.long_document):
        base_ingest_payload["deep_research_mode"] = True
        base_ingest_payload["long_document_mode"] = True
        if not bool(args.long_document_no_collect_sources):
            base_ingest_payload["long_document_collect_sources_first"] = True
    if int(args.long_document_pages or 0) > 0:
        base_ingest_payload["deep_research_mode"] = True
        base_ingest_payload["long_document_pages"] = int(args.long_document_pages)
    if int(getattr(args, "pages", 0) or 0) > 0:
        base_ingest_payload["deep_research_mode"] = True
        base_ingest_payload["long_document_mode"] = True
        base_ingest_payload["long_document_pages"] = int(args.pages)
        if not bool(getattr(args, "long_document_no_collect_sources", False)):
            base_ingest_payload["long_document_collect_sources_first"] = True
    if str(getattr(args, "sources", "") or "").strip():
        parsed_sources = [
            s.strip().lower()
            for s in str(args.sources).split(",")
            if s.strip()
        ]
        if parsed_sources:
            base_ingest_payload["research_sources"] = parsed_sources
            base_ingest_payload["research_pipeline_enabled"] = True
            # Reset completed flag so the pipeline runs fresh for each new CLI invocation
            base_ingest_payload["research_pipeline_completed"] = False
    if int(args.long_document_sections or 0) > 0:
        base_ingest_payload["long_document_sections"] = int(args.long_document_sections)
    if int(args.long_document_section_pages or 0) > 0:
        base_ingest_payload["long_document_section_pages"] = int(args.long_document_section_pages)
    if str(args.long_document_title or "").strip():
        base_ingest_payload["long_document_title"] = str(args.long_document_title).strip()
    if bool(args.long_document_no_collect_sources):
        base_ingest_payload["long_document_collect_sources_first"] = False
    if bool(args.long_document_no_section_search):
        base_ingest_payload["long_document_section_search"] = False
    if int(args.long_document_section_search_results or 0) > 0:
        base_ingest_payload["long_document_section_search_results"] = int(args.long_document_section_search_results)
    if bool(args.long_document_no_visuals):
        base_ingest_payload["long_document_disable_visuals"] = True
    parsed_formats = _parse_research_formats(getattr(args, "format", ""))
    if parsed_formats:
        base_ingest_payload["research_output_formats"] = parsed_formats
    if str(getattr(args, "cite", "") or "").strip():
        base_ingest_payload["research_citation_style"] = str(args.cite).strip().lower()
    if bool(getattr(args, "no_plagiarism", False)):
        base_ingest_payload["research_enable_plagiarism_check"] = False
    if bool(getattr(args, "no_web_search", False)):
        base_ingest_payload["research_web_search_enabled"] = False
    if str(getattr(args, "date_range", "") or "").strip():
        base_ingest_payload["research_date_range"] = str(args.date_range).strip()
    if int(getattr(args, "max_sources", 0) or 0) > 0:
        base_ingest_payload["research_max_sources"] = int(args.max_sources)
    if bool(getattr(args, "checkpoint", False)):
        base_ingest_payload["research_checkpoint_enabled"] = True
    deep_research_links = _normalize_url_inputs(list(getattr(args, "deep_research_link", []) or []))
    if deep_research_links:
        base_ingest_payload["deep_research_source_urls"] = deep_research_links
    if int(args.research_max_wait_seconds or 0) > 0:
        base_ingest_payload["research_max_wait_seconds"] = int(args.research_max_wait_seconds)
    if int(args.research_poll_interval_seconds or 0) > 0:
        base_ingest_payload["research_poll_interval_seconds"] = int(args.research_poll_interval_seconds)
    if int(args.research_max_tool_calls or 0) > 0:
        base_ingest_payload["research_max_tool_calls"] = int(args.research_max_tool_calls)
    if int(args.research_max_output_tokens or 0) > 0:
        base_ingest_payload["research_max_output_tokens"] = int(args.research_max_output_tokens)
    if str(args.research_model or "").strip():
        base_ingest_payload["research_model"] = str(args.research_model).strip()
    if str(args.research_instructions or "").strip():
        base_ingest_payload["research_instructions"] = str(args.research_instructions).strip()

    drive_paths = _normalize_drive_paths(args.drive)
    if drive_paths:
        base_ingest_payload["local_drive_paths"] = drive_paths
        base_ingest_payload["local_drive_recursive"] = not bool(args.drive_no_recursive)
        if bool(args.drive_include_hidden):
            base_ingest_payload["local_drive_include_hidden"] = True
        if int(args.drive_max_files or 0) > 0:
            base_ingest_payload["local_drive_max_files"] = int(args.drive_max_files)
        if int(args.drive_min_files or 0) > 0:
            base_ingest_payload["local_drive_min_files_for_long_document"] = int(args.drive_min_files)
        if str(args.drive_extensions or "").strip():
            base_ingest_payload["local_drive_extensions"] = [
                item.strip() for item in str(args.drive_extensions).split(",") if item.strip()
            ]
        if bool(args.drive_disable_image_ocr):
            base_ingest_payload["local_drive_enable_image_ocr"] = False
        if str(args.drive_ocr_instruction or "").strip():
            base_ingest_payload["local_drive_ocr_instruction"] = str(args.drive_ocr_instruction).strip()
        if bool(args.drive_no_memory_index):
            base_ingest_payload["local_drive_index_to_memory"] = False
        if bool(args.drive_auto_generate_extension_handlers):
            base_ingest_payload["local_drive_auto_generate_extension_handlers"] = True
        base_ingest_payload["local_drive_working_directory"] = resolved_working_dir
        if bool(base_ingest_payload.get("deep_research_mode")) or bool(base_ingest_payload.get("long_document_mode")):
            base_ingest_payload["local_drive_force_long_document"] = True
        if bool(getattr(args, "no_web_search", False)):
            base_ingest_payload.setdefault("research_sources", ["local"])

    if bool(args.codebase):
        codebase_root = str(args.codebase_path or resolved_working_dir).strip()
        if codebase_root:
            codebase_root = str(_resolve_working_dir(codebase_root))
            base_ingest_payload["codebase_mode"] = True
            base_ingest_payload.setdefault("local_drive_paths", [])
            if codebase_root not in base_ingest_payload["local_drive_paths"]:
                base_ingest_payload["local_drive_paths"].append(codebase_root)
            base_ingest_payload["local_drive_recursive"] = True
            base_ingest_payload["local_drive_working_directory"] = codebase_root
            base_ingest_payload["local_drive_index_to_memory"] = True
            if int(args.codebase_max_files or 0) > 0:
                base_ingest_payload["local_drive_max_files"] = int(args.codebase_max_files)
            elif not base_ingest_payload.get("local_drive_max_files"):
                base_ingest_payload["local_drive_max_files"] = 1000

    inferred_pages = _extract_requested_page_count(query)
    inferred_long_document = _query_requests_long_document(query)
    explicit_long_document = (
        bool(args.long_document)
        or int(args.long_document_pages or 0) > 0
        or int(getattr(args, "pages", 0) or 0) > 0
    )
    has_local_drive_inputs = bool(base_ingest_payload.get("local_drive_paths"))
    if has_local_drive_inputs:
        if inferred_long_document and not explicit_long_document:
            base_ingest_payload["deep_research_mode"] = True
            base_ingest_payload["long_document_mode"] = True
            if inferred_pages >= 20:
                base_ingest_payload["long_document_pages"] = inferred_pages
            if not bool(args.long_document_no_collect_sources):
                base_ingest_payload["long_document_collect_sources_first"] = True
        if inferred_long_document or explicit_long_document:
            base_ingest_payload["local_drive_force_long_document"] = True
            if not bool(args.long_document_no_collect_sources):
                base_ingest_payload["long_document_collect_sources_first"] = True

    superrag_paths = _normalize_drive_paths(args.superrag_path)
    superrag_urls = [str(item).strip() for item in list(args.superrag_url or []) if str(item).strip()]
    if str(args.superrag_mode or "").strip():
        base_ingest_payload["superrag_mode"] = str(args.superrag_mode).strip().lower()
    if str(args.superrag_session or "").strip():
        base_ingest_payload["superrag_session_id"] = str(args.superrag_session).strip()
    if bool(args.superrag_new_session):
        base_ingest_payload["superrag_new_session"] = True
    if str(args.superrag_session_title or "").strip():
        base_ingest_payload["superrag_session_title"] = str(args.superrag_session_title).strip()
    if superrag_paths:
        base_ingest_payload["superrag_local_paths"] = superrag_paths
    if superrag_urls:
        base_ingest_payload["superrag_urls"] = superrag_urls
    if str(args.superrag_db_url or "").strip():
        base_ingest_payload["superrag_db_url"] = str(args.superrag_db_url).strip()
    if str(args.superrag_db_schema or "").strip():
        base_ingest_payload["superrag_db_schema"] = str(args.superrag_db_schema).strip()
    if bool(args.superrag_onedrive):
        base_ingest_payload["superrag_onedrive_enabled"] = True
    if str(args.superrag_onedrive_path or "").strip():
        base_ingest_payload["superrag_onedrive_path"] = str(args.superrag_onedrive_path).strip()
        base_ingest_payload["superrag_onedrive_enabled"] = True
    if str(args.superrag_chat or "").strip():
        base_ingest_payload["superrag_chat_query"] = str(args.superrag_chat).strip()
    if int(args.superrag_top_k or 0) > 0:
        base_ingest_payload["superrag_top_k"] = int(args.superrag_top_k)

    has_superrag_sources = bool(
        superrag_paths or superrag_urls or base_ingest_payload.get("superrag_db_url") or base_ingest_payload.get("superrag_onedrive_enabled")
    )
    if has_superrag_sources and not base_ingest_payload.get("superrag_mode"):
        base_ingest_payload["superrag_mode"] = "build"
    if base_ingest_payload.get("superrag_chat_query") and not base_ingest_payload.get("superrag_mode"):
        base_ingest_payload["superrag_mode"] = "chat"

    if args.coding_context_file:
        base_ingest_payload["coding_context_files"] = [str(item).strip() for item in args.coding_context_file if str(item).strip()]
    if str(args.coding_write_path or "").strip():
        base_ingest_payload["coding_write_path"] = str(args.coding_write_path).strip()
    if str(args.coding_instructions or "").strip():
        base_ingest_payload["coding_instructions"] = str(args.coding_instructions).strip()
    if str(args.coding_language or "").strip():
        base_ingest_payload["coding_language"] = str(args.coding_language).strip()
    if str(args.coding_backend or "").strip():
        base_ingest_payload["coding_backend"] = str(args.coding_backend).strip()
    if any(
        [
            base_ingest_payload.get("coding_context_files"),
            base_ingest_payload.get("coding_write_path"),
            base_ingest_payload.get("coding_instructions"),
            base_ingest_payload.get("coding_language"),
            base_ingest_payload.get("coding_backend"),
            _explicit_coding_request(args, query),
        ]
    ):
        base_ingest_payload["coding_working_directory"] = resolved_working_dir

    if str(args.os_command or "").strip():
        base_ingest_payload["os_command"] = str(args.os_command).strip()
    if str(args.os_shell or "").strip():
        base_ingest_payload["shell"] = str(args.os_shell).strip()
    if int(args.os_timeout or 0) > 0:
        base_ingest_payload["os_timeout"] = int(args.os_timeout)
    if str(args.os_working_directory or "").strip():
        base_ingest_payload["os_working_directory"] = str(_resolve_working_dir(str(args.os_working_directory).strip()))
    if str(args.target_os or "").strip():
        base_ingest_payload["target_os"] = str(args.target_os).strip().lower()
    if bool(args.auto_approve):
        base_ingest_payload["auto_approve"] = True
    if bool(args.skip_reviews):
        base_ingest_payload["skip_reviews"] = True
    if int(args.max_step_revisions or 0) > 0:
        base_ingest_payload["max_step_revisions"] = int(args.max_step_revisions)
    if bool(getattr(args, "dev", False)):
        base_ingest_payload["dev_pipeline_mode"] = True
        base_ingest_payload["project_build_mode"] = True
        base_ingest_payload["project_root"] = resolved_working_dir
        dev_stack = str(getattr(args, "dev_stack", "") or "").strip()
        if dev_stack:
            base_ingest_payload["project_stack"] = dev_stack
        if bool(getattr(args, "dev_skip_tests", False)):
            base_ingest_payload["skip_test_agent"] = True
        if bool(getattr(args, "dev_skip_devops", False)):
            base_ingest_payload["skip_devops_agent"] = True
        max_fix = int(getattr(args, "dev_max_fix_rounds", 3) or 3)
        if max_fix != 3:
            base_ingest_payload["dev_pipeline_max_fix_rounds"] = max_fix

    _ = _validate_run_workflows(args, query, resolved_working_dir, drive_paths, superrag_paths)
    workflow_status = _workflow_status_message(args, query, base_ingest_payload)
    if workflow_status:
        _emit_status(args, f"[workflow] {workflow_status}")

    if security_authorized:
        base_ingest_payload["security_authorized"] = True
    if security_target_url:
        base_ingest_payload["security_target_url"] = security_target_url
    if security_authorization_note:
        base_ingest_payload["security_authorization_note"] = security_authorization_note
    if security_scan_profile:
        base_ingest_payload["security_scan_profile"] = security_scan_profile
    if bool(getattr(args, "communication_authorized", False)):
        base_ingest_payload["communication_authorized"] = True
    _comm_lookback = int(getattr(args, "communication_lookback_hours", 0) or 0)
    if _comm_lookback > 0:
        base_ingest_payload["communication_lookback_hours"] = _comm_lookback
    if str(getattr(args, "whatsapp_to", "") or "").strip():
        base_ingest_payload["whatsapp_to"] = str(args.whatsapp_to).strip()
    if str(getattr(args, "whatsapp_message", "") or "").strip():
        base_ingest_payload["whatsapp_message"] = str(args.whatsapp_message).strip()
    if str(getattr(args, "whatsapp_template", "") or "").strip():
        base_ingest_payload["whatsapp_template_name"] = str(args.whatsapp_template).strip()
    if str(getattr(args, "whatsapp_template_language", "") or "").strip():
        base_ingest_payload["whatsapp_template_language"] = str(args.whatsapp_template_language).strip()
    if bool(args.privileged_mode):
        base_ingest_payload["privileged_mode"] = True
    if bool(args.privileged_approved):
        base_ingest_payload["privileged_approved"] = True
    if str(args.privileged_approval_note or "").strip():
        base_ingest_payload["privileged_approval_note"] = str(args.privileged_approval_note).strip()
    if bool(args.privileged_read_only):
        base_ingest_payload["privileged_read_only"] = True
    if bool(args.privileged_allow_root):
        base_ingest_payload["privileged_allow_root"] = True
    if bool(args.privileged_allow_destructive):
        base_ingest_payload["privileged_allow_destructive"] = True
    if bool(args.privileged_enable_backup):
        base_ingest_payload["privileged_enable_backup"] = True
    if args.privileged_allowed_path:
        base_ingest_payload["privileged_allowed_paths"] = list(args.privileged_allowed_path)
    if args.privileged_allowed_domain:
        base_ingest_payload["privileged_allowed_domains"] = list(args.privileged_allowed_domain)
    if str(args.kill_switch_file or "").strip():
        base_ingest_payload["kill_switch_file"] = str(args.kill_switch_file).strip()
    channel = str(args.channel or selected_session.get("channel", "webchat") or "webchat").strip()
    workspace_id = str(args.workspace_id or selected_session.get("workspace_id", "default") or "default").strip()
    stored_sender = str(selected_session.get("sender_id", "") or "").strip()
    sender_id = str(args.sender_id or stored_sender or "cli_user").strip()
    chat_id = str(args.chat_id or selected_session.get("chat_id", sender_id) or sender_id).strip()
    is_group_session = bool(selected_session.get("scope", "main") == "group")
    channel_session_key = f"{channel}:{workspace_id}:{chat_id}:{'group' if is_group_session else 'main'}"
    base_ingest_payload["channel"] = channel
    base_ingest_payload["workspace_id"] = workspace_id
    base_ingest_payload["sender_id"] = sender_id
    base_ingest_payload["chat_id"] = chat_id
    base_ingest_payload["is_group"] = is_group_session
    _save_cli_session(
        {
            "session_key": channel_session_key,
            "channel": channel,
            "workspace_id": workspace_id,
            "chat_id": chat_id,
            "sender_id": sender_id,
            "scope": "group" if is_group_session else "main",
        }
    )

    if not _gateway_ready():
        raise SystemExit(
            f"Gateway is not running at {gateway_base}.\n"
            "Start it first with:  kendr gateway start\n"
            f"Then retry:           kendr run ..."
        )

    interactive_follow_up = bool(getattr(sys.stdin, "isatty", lambda: False)()) and not bool(args.json)
    resume_output_dir: str | None = None
    run_dir_cache: dict[str, str] = {}
    log_offsets: dict[str, int] = {}

    def _new_client_run_id() -> str:
        return f"run_cli_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"

    def _build_ingest_payload(run_id: str, text: str, *, include_new_session: bool) -> dict:
        payload = dict(base_ingest_payload)
        payload["run_id"] = run_id
        payload["text"] = text
        if include_new_session:
            payload["new_session"] = True
        return payload

    def _build_resume_payload(text: str, output_dir: str | None) -> dict:
        payload = {
            "output_folder": output_dir or "",
            "working_directory": resolved_working_dir,
            "reply": text,
            "text": text,
            "channel": channel,
            "workspace_id": workspace_id,
            "sender_id": sender_id,
            "chat_id": chat_id,
            "is_group": is_group_session,
            "max_steps": args.max_steps,
        }
        return {key: value for key, value in payload.items() if value not in ("", None)}

    def _pending_question(result: dict) -> str:
        return str(result.get("pending_user_question") or result.get("final_output") or "").strip()

    def _fetch_task_session(run_id: str) -> dict:
        try:
            payload = _http_json_get(f"{gateway_base}/task-sessions/by-run/{run_id}", timeout_seconds=1.5)
        except Exception:
            return {}
        if isinstance(payload, dict):
            return payload
        return {}

    def _resolve_run_output_dir(run_id: str) -> str:
        cached = run_dir_cache.get(run_id)
        if cached and Path(cached).exists():
            return cached
        if resume_output_dir and Path(resume_output_dir).exists():
            run_dir_cache[run_id] = resume_output_dir
            return resume_output_dir
        runs_root = Path(resolved_working_dir) / "runs"
        if not runs_root.exists():
            return ""
        matches = [item for item in runs_root.glob(f"{run_id}*") if item.is_dir()]
        if matches:
            chosen = str(max(matches, key=lambda p: p.stat().st_mtime))
            run_dir_cache[run_id] = chosen
            return chosen
        for item in runs_root.iterdir():
            if not item.is_dir():
                continue
            manifest = item / "run_manifest.json"
            if not manifest.exists():
                continue
            try:
                data = json.loads(manifest.read_text(encoding="utf-8", errors="ignore"))
                summary = data.get("summary", {}) if isinstance(data, dict) else {}
                if str(summary.get("run_id", "")).strip() == run_id:
                    chosen = str(item)
                    run_dir_cache[run_id] = chosen
                    return chosen
            except Exception:
                continue
        return ""

    def _resolve_latest_session_run_id(session_key: str) -> str:
        try:
            sessions = _http_json_get(f"{gateway_base}/task-sessions", timeout_seconds=1.2)
        except Exception:
            return ""
        if isinstance(sessions, list):
            for item in sessions:
                if str(item.get("session_key", "")) == session_key:
                    run_id = str(item.get("run_id", "")).strip()
                    if run_id:
                        return run_id
        return ""

    def _tail_file(path: Path, key: str) -> None:
        try:
            size = path.stat().st_size
        except Exception:
            return
        if key not in log_offsets:
            log_offsets[key] = max(0, size - 4096)
        if size < log_offsets[key]:
            log_offsets[key] = 0
        try:
            with path.open("r", encoding="utf-8", errors="ignore") as handle:
                handle.seek(log_offsets[key])
                chunk = handle.read()
                log_offsets[key] = handle.tell()
        except Exception:
            return
        if not chunk:
            return
        for line in chunk.splitlines():
            if line.strip():
                _emit_status(args, f"[log] {line}")

    def _tail_run_logs(run_id: str) -> None:
        run_dir = _resolve_run_output_dir(run_id)
        if not run_dir:
            return
        run_path = Path(run_dir)
        for filename in ("execution.log", "agent_work_notes.txt"):
            log_path = run_path / filename
            if log_path.exists():
                _tail_file(log_path, f"{run_dir}:{filename}")

    def _ingest_once(ingest_payload: dict, client_run_id: str) -> dict:
        request = urllib.request.Request(
            f"{gateway_base}/ingest",
            data=json.dumps(ingest_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            stale_gateway_error = "multiple values for keyword argument 'working_directory'" in detail
            if stale_gateway_error:
                _emit_status(args, "[gateway] detected stale gateway process; restarting and retrying ingest...")
                _terminate_gateway_on_port()
                _start_gateway_process()
                retry_request = urllib.request.Request(
                    f"{gateway_base}/ingest",
                    data=json.dumps(ingest_payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(retry_request, timeout=600) as response:
                    return json.loads(response.read().decode("utf-8"))
            raise SystemExit(f"Gateway ingest failed ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            if _is_timeout_error(exc):
                return {"run_id": client_run_id, "_ingest_timed_out": True}
            raise SystemExit(f"Gateway ingest failed: {exc.reason}") from exc
        except TimeoutError:
            return {"run_id": client_run_id, "_ingest_timed_out": True}
        except socket.timeout:
            return {"run_id": client_run_id, "_ingest_timed_out": True}

    def _resume_once(resume_payload: dict, client_run_id: str) -> dict:
        request = urllib.request.Request(
            f"{gateway_base}/resume",
            data=json.dumps(resume_payload).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=600) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            stale_gateway_error = "multiple values for keyword argument 'working_directory'" in detail
            if stale_gateway_error:
                _emit_status(args, "[gateway] detected stale gateway process; restarting and retrying resume...")
                _terminate_gateway_on_port()
                _start_gateway_process()
                retry_request = urllib.request.Request(
                    f"{gateway_base}/resume",
                    data=json.dumps(resume_payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urllib.request.urlopen(retry_request, timeout=600) as response:
                    return json.loads(response.read().decode("utf-8"))
            raise SystemExit(f"Gateway resume failed ({exc.code}): {detail}") from exc
        except urllib.error.URLError as exc:
            if _is_timeout_error(exc):
                return {"run_id": client_run_id, "_ingest_timed_out": True}
            raise SystemExit(f"Gateway resume failed: {exc.reason}") from exc
        except TimeoutError:
            return {"run_id": client_run_id, "_ingest_timed_out": True}
        except socket.timeout:
            return {"run_id": client_run_id, "_ingest_timed_out": True}

    def _poll_task_session_progress(run_id: str, previous_message: str) -> str:
        try:
            sessions = _http_json_get(f"{gateway_base}/task-sessions", timeout_seconds=1.2)
            if isinstance(sessions, list):
                match = next((item for item in sessions if str(item.get("run_id", "")) == run_id), None)
                if isinstance(match, dict):
                    message = _build_run_progress_message(match)
                    if message != previous_message:
                        styled_message = _colorize_run_progress_message(message, _style_from_args(args))
                        _emit_status(args, styled_message)
                        return message
        except Exception:
            pass
        return previous_message

    def _submit_run(ingest_payload: dict, client_run_id: str) -> dict:
        holder: dict[str, object] = {"result": None, "error": None}

        def _submit_ingest() -> None:
            try:
                holder["result"] = _ingest_once(ingest_payload, client_run_id)
            except BaseException as exc:  # noqa: BLE001
                holder["error"] = exc

        worker = threading.Thread(target=_submit_ingest, daemon=True)
        worker.start()

        _emit_status(
            args,
            f"[run] accepted request run_id={client_run_id} | working_directory={resolved_working_dir}",
        )
        started_wait = time.time()
        last_progress = ""
        last_wait_emit = 0.0
        while worker.is_alive():
            worker.join(timeout=1.0)
            last_progress = _poll_task_session_progress(client_run_id, last_progress)
            _tail_run_logs(client_run_id)

            now = time.time()
            if now - last_wait_emit >= 8:
                elapsed = int(now - started_wait)
                _emit_status(args, f"[run] waiting for completion... {elapsed}s elapsed", transient=True)
                last_wait_emit = now

        if holder["error"] is not None:
            error = holder["error"]
            if isinstance(error, BaseException):
                raise error
            raise SystemExit(str(error))
        result = holder["result"]
        if not isinstance(result, dict):
            raise SystemExit("Gateway ingest failed: did not receive a valid JSON response.")

        if bool(result.get("_ingest_timed_out")):
            _emit_status(args, "[run] ingest connection timed out; continuing to monitor run by run_id...")
            while True:
                run_record: dict[str, object] | None = None
                last_progress = _poll_task_session_progress(client_run_id, last_progress)
                _tail_run_logs(client_run_id)
                try:
                    payload = _http_json_get(f"{gateway_base}/runs/{client_run_id}", timeout_seconds=1.5)
                    if isinstance(payload, dict):
                        run_record = payload
                except Exception:
                    run_record = None

                if run_record is not None:
                    status = str(run_record.get("status", "")).strip().lower()
                    if status in {"completed", "awaiting_user_input"}:
                        result = {
                            "run_id": run_record.get("run_id", client_run_id),
                            "final_output": run_record.get("final_output", ""),
                            "last_agent": "",
                            "status": status,
                            "awaiting_user_input": status == "awaiting_user_input",
                        }
                        if status == "awaiting_user_input":
                            task_session = _fetch_task_session(client_run_id)
                            summary = _task_session_summary(task_session)
                            result["pending_user_input_kind"] = summary.get("pending_user_input_kind", "")
                            result["pending_user_question"] = summary.get("pending_user_question", "")
                        break
                    if status == "failed":
                        raise SystemExit(
                            f"Run failed after ingest timeout. "
                            f"run_id={run_record.get('run_id', client_run_id)}"
                        )

                now = time.time()
                if now - last_wait_emit >= 8:
                    elapsed = int(now - started_wait)
                    _emit_status(args, f"[run] waiting for completion... {elapsed}s elapsed", transient=True)
                    last_wait_emit = now
                time.sleep(1.0)

        return result

    def _submit_resume(resume_payload: dict, client_run_id: str) -> dict:
        holder: dict[str, object] = {"result": None, "error": None}

        def _submit_resume_request() -> None:
            try:
                holder["result"] = _resume_once(resume_payload, client_run_id)
            except BaseException as exc:  # noqa: BLE001
                holder["error"] = exc

        worker = threading.Thread(target=_submit_resume_request, daemon=True)
        worker.start()

        _emit_status(
            args,
            f"[run] accepted resume run_id={client_run_id} | working_directory={resolved_working_dir}",
        )
        started_wait = time.time()
        last_progress = ""
        last_wait_emit = 0.0
        while worker.is_alive():
            worker.join(timeout=1.0)
            last_progress = _poll_task_session_progress(client_run_id, last_progress)
            _tail_run_logs(client_run_id)

            now = time.time()
            if now - last_wait_emit >= 8:
                elapsed = int(now - started_wait)
                _emit_status(args, f"[run] waiting for completion... {elapsed}s elapsed", transient=True)
                last_wait_emit = now

        if holder["error"] is not None:
            error = holder["error"]
            if isinstance(error, BaseException):
                raise error
            raise SystemExit(str(error))
        result = holder["result"]
        if not isinstance(result, dict):
            raise SystemExit("Gateway resume failed: did not receive a valid JSON response.")

        if bool(result.get("_ingest_timed_out")):
            _emit_status(args, "[run] resume connection timed out; continuing to monitor run by run_id...")
            target_run_id = _resolve_latest_session_run_id(channel_session_key) or client_run_id
            if target_run_id != client_run_id:
                _emit_status(args, f"[run] monitoring active session run_id={target_run_id}")
            while True:
                run_record: dict[str, object] | None = None
                last_progress = _poll_task_session_progress(target_run_id, last_progress)
                _tail_run_logs(target_run_id)
                try:
                    payload = _http_json_get(f"{gateway_base}/runs/{target_run_id}", timeout_seconds=1.5)
                    if isinstance(payload, dict):
                        run_record = payload
                except Exception:
                    run_record = None

                if run_record is not None:
                    status = str(run_record.get("status", "")).strip().lower()
                    if status in {"completed", "awaiting_user_input"}:
                        result = {
                            "run_id": run_record.get("run_id", client_run_id),
                            "final_output": run_record.get("final_output", ""),
                            "last_agent": "",
                            "status": status,
                            "awaiting_user_input": status == "awaiting_user_input",
                        }
                        if status == "awaiting_user_input":
                            task_session = _fetch_task_session(target_run_id)
                            summary = _task_session_summary(task_session)
                            result["pending_user_input_kind"] = summary.get("pending_user_input_kind", "")
                            result["pending_user_question"] = summary.get("pending_user_question", "")
                        break
                    if status == "failed":
                        raise SystemExit(
                            f"Run failed after resume timeout. "
                            f"run_id={run_record.get('run_id', target_run_id)}"
                        )

                now = time.time()
                if now - last_wait_emit >= 8:
                    elapsed = int(now - started_wait)
                    _emit_status(args, f"[run] waiting for completion... {elapsed}s elapsed", transient=True)
                    last_wait_emit = now

        return result

    current_query = query
    include_new_session = bool(args.new_session)
    use_resume = False

    try:
        while True:
            client_run_id = _new_client_run_id()
            if use_resume:
                resume_payload = _build_resume_payload(current_query, resume_output_dir)
                result = _submit_resume(resume_payload, client_run_id)
            else:
                ingest_payload = _build_ingest_payload(
                    client_run_id,
                    current_query,
                    include_new_session=include_new_session,
                )
                include_new_session = False
                result = _submit_run(ingest_payload, client_run_id)
            paused = bool(result.get("awaiting_user_input")) or str(result.get("status", "")).strip().lower() == "awaiting_user_input"
            terminal_state = "paused" if paused else "completed"
            _emit_status(
                args,
                f"[run] {terminal_state} run_id={result.get('run_id', client_run_id)} "
                f"last_agent={result.get('last_agent', '') or '-'}",
            )
            if result.get("output_dir"):
                resume_output_dir = str(result.get("output_dir") or "").strip() or resume_output_dir

            if paused and interactive_follow_up:
                prompt = _pending_question(result)
                # ── Blueprint approval gate — show [y/n] prompt for dev pipeline ──
                pending_kind = str(result.get("pending_user_input_kind") or "").strip().lower()
                is_blueprint_gate = (
                    pending_kind == "blueprint_approval"
                    or (bool(getattr(args, "dev", False)) and "blueprint" in (prompt or "")[:120].lower())
                )
                if is_blueprint_gate:
                    try:
                        from kendr import cli_output as _cout
                        _cout.print_text("")
                        _cout.rule("BLUEPRINT READY FOR REVIEW", style="#FFB347")
                        if prompt:
                            _cout.print_text(f"\n{prompt}\n", style="grey62")
                    except Exception:
                        sys.stdout.write("\n" + "═" * 72 + "\n  BLUEPRINT READY FOR REVIEW\n" + "═" * 72 + "\n")
                        if prompt:
                            sys.stdout.write(f"\n{prompt}\n")
                        sys.stdout.flush()
                    sys.stdout.write("Proceed with this blueprint? [y/n]: ")
                    sys.stdout.flush()
                    try:
                        answer = sys.stdin.readline().strip().lower()
                    except (EOFError, KeyboardInterrupt):
                        answer = "n"
                    if answer in ("y", "yes", "approve", "ok", "1"):
                        current_query = "approve"
                    else:
                        try:
                            from kendr import cli_output as _cout
                            _cout.print_text("\nGeneration cancelled at blueprint review.", style="#FF4757")
                        except Exception:
                            sys.stdout.write("\nGeneration cancelled at blueprint review.\n")
                            sys.stdout.flush()
                        return 0
                else:
                    if prompt:
                        try:
                            from kendr import cli_output as _cout
                            _cout.print_text(prompt, style="grey62")
                        except Exception:
                            sys.stdout.write(prompt + "\n")
                            sys.stdout.flush()
                    while True:
                        try:
                            current_query = input("Reply: ").strip()
                        except (EOFError, KeyboardInterrupt) as exc:
                            raise SystemExit(
                                "Run is paused and the session was preserved. "
                                f"Resume with `kendr resume --reply \"<your reply>\" --working-directory \"{resolved_working_dir}\"`."
                            ) from exc
                        if current_query:
                            break
                        _emit_status(args, "[run] empty reply ignored; enter a response or press Ctrl+C to stop.")
                use_resume = True
                continue

            if args.json:
                print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
            else:
                final_output = result.get("final_output", "")
                try:
                    from kendr import cli_output as _cout
                    _cout.print_final_output(final_output)
                except Exception:
                    if final_output:
                        sys.stdout.write(final_output + "\n")
                        sys.stdout.flush()
                if not bool(getattr(args, "quiet", False)):
                    try:
                        _emit_run_summary_table(result.get("run_id", ""))
                    except Exception:
                        pass
            return 0
    finally:
        _clear_transient_status_line()


def _resume_search_target(args: argparse.Namespace) -> str:
    explicit_output = str(getattr(args, "output_folder", "") or "").strip()
    if explicit_output:
        return explicit_output
    explicit_target = str(getattr(args, "target", "") or "").strip()
    if explicit_target:
        return explicit_target
    working_dir = str(getattr(args, "working_directory", "") or "").strip()
    if working_dir:
        return working_dir
    configured = _configured_working_dir()
    if configured:
        return configured
    return str(Path.cwd())


def _choose_resume_candidate(args: argparse.Namespace, candidates: list[dict]) -> dict:
    if not candidates:
        return {}
    if len(candidates) == 1 or bool(getattr(args, "latest", False)) or not bool(getattr(sys.stdin, "isatty", lambda: False)()):
        return candidates[0]

    rows = []
    for index, item in enumerate(candidates, start=1):
        rows.append(
            [
                str(index),
                str(item.get("run_id", "")),
                str(item.get("resume_status", "")),
                _truncate(str(item.get("objective", "")), 56),
                _truncate(str(item.get("updated_at", "")), 24),
            ]
        )
    print(_render_table(["#", "RUN_ID", "STATUS", "OBJECTIVE", "UPDATED_AT"], rows))
    while True:
        raw = input("Select session number to resume: ").strip()
        if raw.isdigit():
            choice = int(raw)
            if 1 <= choice <= len(candidates):
                return candidates[choice - 1]
        print("Enter a valid session number.")


def _cmd_resume(args: argparse.Namespace) -> int:
    style = _style_from_args(args)
    search_target = _resume_search_target(args)
    candidates = discover_resume_candidates(search_target, limit=50)
    if not candidates:
        raise SystemExit(f"No persisted run folders were found under: {search_target}")

    candidate = _choose_resume_candidate(args, candidates)
    if not candidate:
        raise SystemExit("No resumable candidate was selected.")

    rendered = render_resume_candidate(candidate)
    if bool(args.inspect) and args.json:
        print(json.dumps(candidate, indent=2, ensure_ascii=False))
    elif not args.json:
        print(style.heading("Recovered session"))
        print(rendered)
        print()

    if bool(args.inspect):
        return 0

    if resume_candidate_requires_branch(candidate, branch=bool(args.branch)):
        if not args.json:
            print(style.warn("This run is already completed. Use --branch to start a new child run from its saved context."))
        return 0

    if str(candidate.get("resume_status", "")).strip() == "running" and resume_candidate_requires_force(candidate, force=bool(args.force)):
        raise SystemExit("This run still looks active. Re-run with --force to take it over.")

    if str(candidate.get("resume_status", "")).strip() == "running_stale" and resume_candidate_requires_force(candidate, force=bool(args.force)):
        if bool(getattr(sys.stdin, "isatty", lambda: False)()):
            confirm = input("The run looks stale. Take over and resume it? [y/N]: ").strip().lower()
            if confirm not in {"y", "yes"}:
                raise SystemExit("Resume canceled.")
        else:
            raise SystemExit("This run looks stale. Re-run with --force to take it over.")

    reply_text = str(getattr(args, "reply", "") or "").strip()
    if not reply_text:
        reply_text = " ".join(getattr(args, "query", [])).strip()

    interactive = bool(getattr(sys.stdin, "isatty", lambda: False)()) and not bool(args.json)
    if resume_candidate_requires_reply(candidate) and not reply_text:
        if not interactive:
            raise SystemExit("This run is paused for user input. Pass --reply or use an interactive terminal.")
        reply_text = input("Reply: ").strip()
        if not reply_text:
            raise SystemExit("Resume canceled: empty reply.")

    run_query = reply_text or (" ".join(getattr(args, "query", [])).strip() if args.branch else "resume")
    if not run_query:
        run_query = str(candidate.get("objective", "") or candidate.get("user_query", "")).strip() or "resume"

    working_directory = _resolve_working_dir(infer_resume_working_directory(candidate, fallback=str(Path.cwd())))
    overrides = build_resume_state_overrides(
        candidate,
        branch=bool(args.branch),
        working_directory=working_directory,
        incoming_channel="local",
        incoming_workspace_id="default",
        incoming_sender_id="cli_user",
        incoming_chat_id="cli_user",
        incoming_is_group=False,
    )

    from kendr import AgentRuntime

    runtime = AgentRuntime(build_registry())
    current_query = run_query
    current_candidate = candidate

    while True:
        result = runtime.run_query(current_query, state_overrides=overrides)
        paused = state_awaiting_user_input(result)
        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        else:
            final_text = str(result.get("final_output") or result.get("draft_response") or "").strip()
            if final_text:
                print(final_text)

        if not paused or not interactive:
            return 0

        current_candidate = load_resume_candidate(str(current_candidate.get("run_output_dir", "") or ""))
        pending_question = str(
            current_candidate.get("pending_user_question", "")
            or result.get("pending_user_question", "")
            or result.get("final_output", "")
            or ""
        ).strip()
        if pending_question:
            print()
            print(pending_question)
        current_query = input("Reply: ").strip()
        if not current_query:
            raise SystemExit("Resume canceled: empty reply.")
        overrides["resume_checkpoint_payload"] = current_candidate.get("checkpoint", {})
        if not bool(args.branch):
            overrides["resume_output_dir"] = str(current_candidate.get("run_output_dir", "") or "")


def _cmd_gateway(args: argparse.Namespace) -> int:
    from kendr import cli_output as out

    action = getattr(args, "action", "serve")
    base = _gateway_base_url()
    host, port = _gateway_host_port()
    use_json = bool(getattr(args, "json", False))

    if action == "serve":
        from .gateway_server import main as gateway_main

        gateway_main()
        return 0

    if action == "status":
        pids = _listener_pids_for_port(port)
        pid = _read_gateway_pid()
        pid_alive = bool(pid and _pid_is_alive(pid))
        pid_owned = bool(pid_alive and _pid_is_gateway_owned(pid))
        port_listening = bool(pids)
        health_ok = _gateway_ready(timeout_seconds=0.8)
        running = health_ok or (pid_owned and port_listening)
        # Recover PID and start_time from port listener if state files were lost
        if running and (not pid or not pid_alive):
            recovered_pid = pids[0] if pids else None
            if recovered_pid:
                _write_gateway_pid(recovered_pid)
                pid = recovered_pid
                pid_alive = True
                pid_owned = True
        start_time = _read_gateway_start_time()
        # If start_time was lost (e.g. from a failed stop), record now as a fallback
        if running and not start_time:
            _gateway_start_time_path().write_text(str(time.time()), encoding="utf-8")
            start_time = _read_gateway_start_time()
        uptime = (time.time() - start_time) if (running and start_time) else None
        if pid and not pid_alive:
            _clear_gateway_pid()
            pid = None
        elif pid and pid_alive and not pid_owned:
            _clear_gateway_pid()
            pid = None

        ui_host, ui_port = _ui_host_port()
        ui_pids = _listener_pids_for_port(ui_port)
        ui_running = _ui_ready(timeout_seconds=0.8)
        ui_pid = ui_pids[0] if ui_pids else None

        project_services: list[dict[str, Any]] = []
        try:
            from kendr.project_manager import list_all_project_services

            project_services = list_all_project_services(include_stopped=True)
        except Exception:
            project_services = []

        servers = [
            {
                "name": "Gateway",
                "url": base,
                "port": port,
                "pid": pid,
                "running": running,
                "uptime_seconds": round(uptime, 1) if uptime is not None else None,
            },
            {
                "name": "UI",
                "url": _ui_base_url(),
                "port": ui_port,
                "pid": ui_pid,
                "running": ui_running,
                "uptime_seconds": round(uptime, 1) if (ui_running and uptime is not None) else None,
            },
        ]
        for service in project_services:
            service_name = str(service.get("name") or service.get("id") or "service")
            project_name = str(service.get("project_name") or "").strip()
            kind = str(service.get("kind") or "").strip()
            label = service_name
            if project_name:
                label = f"{project_name} / {service_name}"
            if kind:
                label = f"{label} ({kind})"
            servers.append(
                {
                    "name": label,
                    "url": str(service.get("url") or service.get("log_path") or ""),
                    "port": service.get("port"),
                    "pid": service.get("pid"),
                    "running": bool(service.get("running")),
                    "uptime_seconds": service.get("uptime_seconds"),
                }
            )
        payload = {
            "running": running,
            "health_ok": health_ok,
            "pid_alive": pid_alive,
            "pid_owned": pid_owned,
            "port_listening": port_listening,
            "host": host,
            "port": port,
            "base_url": base,
            "pids": pids,
            "pid": pid,
            "uptime_seconds": round(uptime, 1) if uptime is not None else None,
            "servers": servers,
            "project_services": project_services,
        }
        if use_json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0
        out.gateway_status(running, base, pid=pid, uptime_seconds=uptime, servers=servers)
        return 0

    if action == "stop":
        pid = _read_gateway_pid()
        killed_via_pid = False
        if pid and _pid_is_alive(pid):
            try:
                if os.name == "nt":
                    subprocess.run(["taskkill", "/PID", str(pid), "/F", "/T"], capture_output=True, check=False)
                    killed_via_pid = True
                elif _pid_is_gateway_owned(pid):
                    import signal
                    os.kill(pid, signal.SIGTERM)
                    deadline = time.time() + 5.0
                    while time.time() < deadline and _pid_is_alive(pid):
                        time.sleep(0.2)
                    if _pid_is_alive(pid) and _pid_is_gateway_owned(pid):
                        os.kill(pid, signal.SIGKILL)
                    killed_via_pid = True
                else:
                    _clear_gateway_pid()
            except Exception:
                pass
        stopped_port = _terminate_gateway_on_port()
        _terminate_ui_on_port()
        _clear_gateway_pid()
        _wait_for_listener_shutdown(port, timeout_seconds=3.0)
        stopped = max(int(killed_via_pid), stopped_port)
        if use_json:
            print(json.dumps({"action": "stop", "port": port, "stopped": stopped, "pid": pid}, indent=2, ensure_ascii=False))
            return 0
        if stopped or killed_via_pid:
            out.gateway_stopped(port, max(stopped, int(killed_via_pid)))
        else:
            out.gateway_not_running(base)
        return 0

    if action == "restart":
        _terminate_gateway_on_port()
        _terminate_ui_on_port()
        _clear_gateway_pid()
        _start_gateway_process()
        pid = _read_gateway_pid()
        if use_json:
            print(json.dumps({"action": "restart", "base_url": base, "port": port, "pid": pid}, indent=2, ensure_ascii=False))
            return 0
        out.gateway_restarted(base)
        return 0

    if action == "start":
        if _gateway_ready(timeout_seconds=0.8):
            pid = _read_gateway_pid()
            if use_json:
                print(json.dumps({"action": "start", "base_url": base, "already_running": True, "pid": pid}, indent=2, ensure_ascii=False))
                return 0
            out.gateway_already_running(base)
            return 0
        _start_gateway_process()
        pid = _read_gateway_pid()
        if use_json:
            print(json.dumps({"action": "start", "base_url": base, "started": True, "pid": pid}, indent=2, ensure_ascii=False))
            return 0
        out.gateway_started(base)
        return 0

    raise SystemExit(f"Unknown gateway action: {action}")


def _cmd_ui(args: argparse.Namespace) -> int:
    port_override = int(getattr(args, "port", 0) or 0)
    host_override = str(getattr(args, "host", "") or "").strip()
    no_browser = bool(getattr(args, "no_browser", False))
    if port_override:
        os.environ["KENDR_UI_PORT"] = str(port_override)
    if host_override:
        os.environ["KENDR_UI_HOST"] = host_override

    ui_port = int(os.getenv("KENDR_UI_PORT", "2151"))
    _display_host = os.getenv("KENDR_UI_HOST", "0.0.0.0")
    _url_host = "localhost" if _display_host in ("0.0.0.0", "") else _display_host
    ui_url = f"http://{_url_host}:{ui_port}"
    os.environ.setdefault("KENDR_UI_LOG_PATH", str(_ui_log_path()))

    if not _gateway_ready(timeout_seconds=0.8):
        print(f"[ui] Gateway not running — starting it in background...")
        try:
            os.environ["KENDR_UI_ENABLED"] = "0"
            _start_gateway_process()
        except SystemExit:
            print("[ui] Warning: gateway did not start. Chat will require 'kendr gateway start'.")
        finally:
            os.environ.pop("KENDR_UI_ENABLED", None)

    if not no_browser:
        def _open_browser() -> None:
            time.sleep(0.8)
            import webbrowser
            webbrowser.open(ui_url)

        threading.Thread(target=_open_browser, daemon=True).start()

    def _kendr_ui_running(port: int, host: str) -> bool:
        import urllib.request as _req
        import json as _json

        _probe_hosts = ["127.0.0.1"]
        if host not in ("0.0.0.0", "", "127.0.0.1"):
            _probe_hosts.append(host)
        for _h in _probe_hosts:
            try:
                with _req.urlopen(f"http://{_h}:{port}/api/health", timeout=1) as r:
                    data = _json.loads(r.read())
                    if data.get("service") == "kendr-ui":
                        return True
            except Exception:
                pass
        return False

    if _kendr_ui_running(ui_port, os.getenv("KENDR_UI_HOST", "0.0.0.0")):
        print(f"Kendr UI already running at {ui_url}")
        return 0

    from .ui_server import main as ui_main

    try:
        ui_main()
    except OSError as _bind_err:
        print(f"[ui] Cannot bind port {ui_port}: {_bind_err}")
        print(f"[ui] If UI is already running, visit {ui_url}")
        return 1
    return 0


def _cmd_hello(args: argparse.Namespace) -> int:
    style = _style_from_args(args)
    version = _cli_version()

    quickstart = {
        "version": version,
        "capabilities": [
            {
                "name": "Deep Research",
                "command": 'kendr research "topic you want to investigate" --sources web,arxiv --pages 10',
                "description": "Multi-source research pipeline with document output (PDF/DOCX/Markdown).",
            },
            {
                "name": "Code Project Generation",
                "command": 'kendr generate "a FastAPI REST API with PostgreSQL and JWT auth" --auto-approve',
                "description": "Generate a complete production-ready software project end-to-end.",
            },
            {
                "name": "SuperRAG Knowledge Engine",
                "command": 'kendr run --superrag-mode build --superrag-new-session --superrag-session-title "my_kb" --superrag-path ./docs "Build my knowledge base."',
                "description": "Zero-config local-first RAG: ingest docs, URLs, DBs, and OneDrive. Chat over the indexed knowledge.",
            },
            {
                "name": "Local Command Execution",
                "command": 'kendr run --current-folder --privileged-approved --privileged-approval-note "manual review" "List the project files."',
                "description": "Controlled shell command execution with audit log and auto-install support.",
            },
            {
                "name": "Communication Suite",
                "command": 'kendr run --communication-authorized "Summarize my communications from the last 24 hours."',
                "description": "Unified digest across Gmail, Slack, Telegram, WhatsApp, and Microsoft 365.",
            },
        ],
        "setup_steps": [
            "1. Run `kendr setup set openai OPENAI_API_KEY sk-...` to configure your LLM provider.",
            "2. Run `kendr setup components` to see all integrations and required variables.",
            "3. Run `kendr status` to verify your configuration and routing eligibility.",
            "4. Run `kendr gateway start` to pre-launch the gateway (optional — auto-starts on first run).",
            "5. Run `kendr agents list` to see all available agents.",
        ],
        "docs": [
            "SampleTasks.md — full example library with expected outputs",
            "kendr --help — complete flag reference",
            "kendr help <command> — per-command help (e.g. `kendr help run`)",
        ],
    }

    if bool(getattr(args, "json", False)):
        print(json.dumps(quickstart, indent=2, ensure_ascii=False))
        return 0

    lines = [
        "",
        style.title("  ██╗  ██╗███████╗███╗   ██╗██████╗ ██████╗ "),
        style.title("  ██║ ██╔╝██╔════╝████╗  ██║██╔══██╗██╔══██╗"),
        style.title("  █████╔╝ █████╗  ██╔██╗ ██║██║  ██║██████╔╝"),
        style.title("  ██╔═██╗ ██╔══╝  ██║╚██╗██║██║  ██║██╔══██╗"),
        style.title("  ██║  ██╗███████╗██║ ╚████║██████╔╝██║  ██║"),
        style.title("  ╚═╝  ╚═╝╚══════╝╚═╝  ╚═══╝╚═════╝ ╚═╝  ╚═╝"),
        "",
        f"  {style.muted('v' + version + '  ·  Multi-agent intelligence runtime')}",
        "",
        style.heading("  Five core capabilities:"),
        "",
    ]
    for cap in quickstart["capabilities"]:
        lines.append(f"  {style.ok('▸')} {cap['name']}")
        lines.append(f"    {style.muted(cap['description'])}")
        lines.append(f"    {cap['command']}")
        lines.append("")

    lines.append(style.heading("  Getting started:"))
    lines.append("")
    for step in quickstart["setup_steps"]:
        lines.append(f"  {step}")
    lines.append("")

    lines.append(style.heading("  Learn more:"))
    lines.append("")
    for doc in quickstart["docs"]:
        lines.append(f"  · {doc}")
    lines.append("")

    print("\n".join(lines))
    return 0


def _cmd_workdir(args: argparse.Namespace) -> int:
    style = _style_from_args(args)
    action = args.workdir_action
    if action == "show":
        configured = _configured_working_dir()
        if bool(getattr(args, "json", False)):
            payload = {"configured": bool(configured), "path": _resolve_working_dir(configured) if configured else ""}
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0
        if configured:
            print(_resolve_working_dir(configured))
        else:
            print("(not set)")
        return 0

    if action == "set":
        resolved = _resolve_working_dir(args.path)
        save_component_values("core_runtime", {"KENDR_WORKING_DIR": resolved})
        os.environ["KENDR_WORKING_DIR"] = resolved
        print(style.ok(f"Working directory set to: {resolved}"))
        return 0

    if action == "here":
        resolved = _resolve_working_dir(str(Path.cwd()))
        save_component_values("core_runtime", {"KENDR_WORKING_DIR": resolved})
        os.environ["KENDR_WORKING_DIR"] = resolved
        print(style.ok(f"Working directory set to current folder: {resolved}"))
        return 0

    if action == "create":
        resolved = _resolve_working_dir(args.path)
        if bool(args.activate):
            save_component_values("core_runtime", {"KENDR_WORKING_DIR": resolved})
            os.environ["KENDR_WORKING_DIR"] = resolved
            print(style.ok(f"Created and activated working directory: {resolved}"))
        else:
            print(style.ok(f"Created working directory: {resolved}"))
        return 0

    if action == "clear":
        save_component_values("core_runtime", {"KENDR_WORKING_DIR": ""})
        os.environ.pop("KENDR_WORKING_DIR", None)
        print(style.ok("Cleared KENDR_WORKING_DIR."))
        return 0

    raise SystemExit(f"Unknown workdir action: {action}")


def _cmd_agents(args: argparse.Namespace) -> int:
    style = _style_from_args(args)
    registry = build_registry()
    if args.action == "list":
        payload = sorted(
            [
                {
                    "name": agent.name,
                    "description": agent.description,
                    "plugin": agent.plugin_name,
                    "skills": agent.skills,
                }
                for agent in registry.agents.values()
            ],
            key=lambda item: item["name"],
        )
        plugin_filter = str(getattr(args, "plugin", "") or "").strip().lower()
        contains_filter = str(getattr(args, "contains", "") or "").strip().lower()
        if plugin_filter:
            payload = [item for item in payload if str(item["plugin"]).lower() == plugin_filter]
        if contains_filter:
            payload = [
                item
                for item in payload
                if contains_filter in item["name"].lower() or contains_filter in str(item["description"]).lower()
            ]
        if int(getattr(args, "limit", 0) or 0) > 0:
            payload = payload[: int(args.limit)]
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            rows = [
                [
                    item["name"],
                    str(item["plugin"]),
                    ", ".join(item.get("skills", [])[:3]) or "-",
                    _truncate(str(item["description"]), 80),
                ]
                for item in payload
            ]
            if not rows:
                print(style.warn("No agents matched the current filters."))
                return 0
            print(style.heading(f"Discovered agents ({len(payload)}):"))
            print(_render_table(["NAME", "PLUGIN", "SKILLS", "DESCRIPTION"], rows))
        return 0

    if not args.name:
        raise SystemExit("agents show requires an agent name")
    agent = registry.agents.get(args.name)
    if not agent:
        raise SystemExit(f"Unknown agent: {args.name}")
    payload = {
        "name": agent.name,
        "description": agent.description,
        "plugin": agent.plugin_name,
        "skills": agent.skills,
        "input_keys": agent.input_keys,
        "output_keys": agent.output_keys,
        "requirements": agent.requirements,
        "metadata": agent.metadata,
    }
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(style.heading(f"{payload['name']}"))
        print(f"Description: {payload['description']}")
        print(f"Plugin:      {payload['plugin']}")
        print(f"Skills:      {', '.join(payload['skills']) if payload['skills'] else '-'}")
        print(f"Input keys:  {', '.join(payload['input_keys']) if payload['input_keys'] else '-'}")
        print(f"Output keys: {', '.join(payload['output_keys']) if payload['output_keys'] else '-'}")
        print(f"Requirements:{' ' if payload['requirements'] else ''}{payload['requirements'] or '-'}")
    return 0


def _cmd_plugins(args: argparse.Namespace) -> int:
    style = _style_from_args(args)
    registry = build_registry()
    payload = sorted(
        [
            {
                "name": plugin.name,
                "source": plugin.source,
                "description": plugin.description,
                "version": plugin.version,
                "sdk_version": plugin.sdk_version,
                "runtime_api": plugin.runtime_api,
                "kind": plugin.kind,
            }
            for plugin in registry.plugins.values()
        ],
        key=lambda item: item["name"],
    )
    kind_filter = str(getattr(args, "kind", "") or "").strip().lower()
    contains_filter = str(getattr(args, "contains", "") or "").strip().lower()
    if kind_filter:
        payload = [item for item in payload if str(item["kind"]).lower() == kind_filter]
    if contains_filter:
        payload = [
            item
            for item in payload
            if contains_filter in item["name"].lower() or contains_filter in str(item["description"]).lower()
        ]
    if int(getattr(args, "limit", 0) or 0) > 0:
        payload = payload[: int(args.limit)]
    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        rows = [
            [
                item["name"],
                str(item["kind"]),
                str(item.get("version", "") or "-"),
                str(item.get("sdk_version", "") or "-"),
                _truncate(str(item["description"]), 80),
            ]
            for item in payload
        ]
        if not rows:
            print(style.warn("No plugins matched the current filters."))
            return 0
        print(style.heading(f"Discovered plugins ({len(payload)}):"))
        print(_render_table(["NAME", "KIND", "VERSION", "SDK", "DESCRIPTION"], rows))
    return 0


def _cmd_model(args: argparse.Namespace) -> int:
    """Handle `kendr model` sub-commands."""
    from kendr.llm_router import (
        ALL_PROVIDERS,
        all_provider_statuses,
        get_active_provider,
        get_model_for_provider,
        get_model_setting_env,
        is_ollama_running,
        list_ollama_models,
        provider_status,
        selectable_models_for_provider,
    )
    from tasks.setup_config_store import save_component_values

    style = _style_from_args(args)
    action = args.model_action

    if action == "status":
        provider = get_active_provider()
        model = get_model_for_provider(provider)
        st = provider_status(provider)
        print(style.heading("\n  Active LLM Configuration"))
        print(f"  Provider : {provider}")
        print(f"  Model    : {model}")
        print(f"  Ready    : {'yes' if st['ready'] else 'no'}")
        if st.get("base_url"):
            print(f"  Base URL : {st['base_url']}")
        if st.get("note"):
            print(f"  Note     : {st['note']}")
        print()
        return 0

    if action == "list":
        statuses = all_provider_statuses()
        active = get_active_provider()
        rows = []
        for st in statuses:
            p = st["provider"]
            tick = style.ok("*") if p == active else " "
            ready = style.ok("yes") if st["ready"] else style.warn("no")
            note = st.get("note", "")
            selectable = ", ".join(selectable_models_for_provider(p)[:3])
            rows.append([tick, p, st["model"], ready, selectable or "-", note[:50]])
        print(style.heading("\n  LLM Providers\n"))
        print(_render_table(["", "PROVIDER", "DEFAULT MODEL", "READY", "SELECTABLE", "NOTE"], rows))
        print(f"\n  Active provider: {active}  (change with: kendr model set <provider>)\n")
        return 0

    if action == "set":
        provider = str(args.provider).strip().lower()
        model_name = str(getattr(args, "model", "") or "").strip()

        values: dict[str, str] = {"KENDR_LLM_PROVIDER": provider, "KENDR_MODEL": ""}
        model_env_key = get_model_setting_env(provider)
        if model_name and model_env_key:
            values[model_env_key] = model_name
        save_component_values("core_runtime", values)
        os.environ["KENDR_LLM_PROVIDER"] = provider
        os.environ.pop("KENDR_PROVIDER", None)
        os.environ.pop("KENDR_MODEL", None)
        if model_name and model_env_key:
            os.environ[model_env_key] = model_name
        effective_model = model_name or get_model_for_provider(provider)
        print(style.ok(f"Set provider to '{provider}'" + (f" with model '{effective_model}'" if effective_model else "") + "."))
        print("  Restart kendr for the change to take effect in running agents.")
        return 0

    if action == "test":
        provider = str(getattr(args, "provider", "") or "").strip().lower() or get_active_provider()
        model_name = str(getattr(args, "model", "") or "").strip() or get_model_for_provider(provider)
        print(f"  Testing {provider} / {model_name} ...")
        try:
            from kendr.llm_router import build_llm
            client = build_llm(provider=provider, model=model_name)
            resp = client.invoke("Say hello in one sentence.")
            content = getattr(resp, "content", str(resp))
            print(style.ok(f"  Response: {content[:200]}"))
            return 0
        except Exception as exc:
            print(style.fail(f"  Test failed: {exc}"))
            return 1

    if action == "ollama":
        ollama_action = getattr(args, "ollama_action", "status")

        if ollama_action == "status":
            running = is_ollama_running()
            base = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
            print(style.heading("\n  Ollama Status"))
            print(f"  Server  : {base}")
            print(f"  Running : {style.ok('yes') if running else style.warn('no')}")
            if running:
                models = list_ollama_models()
                if models:
                    print(f"  Models  : {', '.join(m.get('name', '') for m in models)}")
                else:
                    print("  Models  : (none — run: kendr model ollama pull llama3.2)")
            else:
                print("  Start   : ollama serve")
            print()
            return 0

        if ollama_action == "list":
            if not is_ollama_running():
                print(style.warn("Ollama is not running. Start it with: ollama serve"))
                return 1
            models = list_ollama_models()
            if not models:
                print(style.warn("No models installed. Pull one with: kendr model ollama pull <model>"))
                return 0
            rows = [[m.get("name", ""), m.get("size", ""), m.get("modified_at", "")[:19] if m.get("modified_at") else ""] for m in models]
            print(_render_table(["MODEL", "SIZE", "MODIFIED"], rows))
            return 0

        if ollama_action == "pull":
            model_name = args.model_name.strip()
            if not model_name:
                raise SystemExit("Please specify a model name, e.g. llama3.2")
            print(f"  Pulling {model_name} from Ollama registry ...")
            try:
                result = subprocess.run(["ollama", "pull", model_name], check=True)
                if result.returncode == 0:
                    print(style.ok(f"  Done! Model '{model_name}' is ready."))
                    print(f"  Use it: kendr model set ollama {model_name}")
                return result.returncode
            except FileNotFoundError:
                print(style.fail("  'ollama' command not found. Install from ollama.ai and ensure it's in your PATH."))
                return 1
            except subprocess.CalledProcessError as exc:
                print(style.fail(f"  Pull failed: {exc}"))
                return 1

        if ollama_action == "rm":
            model_name = args.model_name.strip()
            try:
                result = subprocess.run(["ollama", "rm", model_name], check=True)
                print(style.ok(f"  Removed '{model_name}'."))
                return result.returncode
            except (FileNotFoundError, subprocess.CalledProcessError) as exc:
                print(style.fail(f"  Failed: {exc}"))
                return 1

        if ollama_action == "run":
            model_name = (getattr(args, "model_name", "") or "").strip()
            from kendr.llm_router import get_model_for_provider as _gmp
            if not model_name:
                model_name = _gmp("ollama")
            try:
                subprocess.run(["ollama", "run", model_name], check=False)
                return 0
            except FileNotFoundError:
                print(style.fail("  'ollama' command not found. Install from ollama.ai."))
                return 1

        if ollama_action == "docker":
            docker_action = str(getattr(args, "docker_action", "status")).strip().lower()
            container = "kendr-ollama"
            image = "ollama/ollama"

            def _docker_available() -> bool:
                try:
                    r = subprocess.run(["docker", "info"], capture_output=True, timeout=5)
                    return r.returncode == 0
                except Exception:
                    return False

            if docker_action == "status":
                if not _docker_available():
                    print(style.warn("  Docker is not running or not installed."))
                    return 1
                try:
                    r = subprocess.run(
                        ["docker", "inspect", container],
                        capture_output=True, text=True, timeout=5,
                    )
                    if r.returncode != 0:
                        print(style.warn(f"  Container '{container}' does not exist."))
                        print(f"  Start it with: kendr model ollama docker start")
                        return 0
                    import json as _json
                    data = _json.loads(r.stdout)
                    c = data[0]
                    running = c.get("State", {}).get("Running", False)
                    host_cfg = c.get("HostConfig", {})
                    gpu = bool((host_cfg.get("DeviceRequests") or []))
                    print(style.heading("\n  Ollama Docker Container"))
                    print(f"  Container : {container}")
                    print(f"  Status    : " + (style.ok("running") if running else style.fail("stopped")))
                    print(f"  Mode      : " + ("GPU (NVIDIA)" if gpu else "CPU"))
                    print(f"  Port      : 11434")
                    print(f"  Image     : {c.get('Config', {}).get('Image', image)}")
                    return 0
                except Exception as exc:
                    print(style.fail(f"  Error: {exc}"))
                    return 1

            if docker_action == "start":
                gpu = bool(getattr(args, "gpu", False))
                if not _docker_available():
                    print(style.fail("  Docker is not running or not installed."))
                    return 1
                print(f"  Stopping any existing '{container}' container...")
                subprocess.run(["docker", "rm", "-f", container], capture_output=True, timeout=15)
                cmd = ["docker", "run", "-d"]
                if gpu:
                    cmd += ["--gpus=all"]
                cmd += ["--name", container, "-p", "11434:11434",
                        "-v", "ollama:/root/.ollama", image]
                mode = "GPU" if gpu else "CPU"
                print(f"  Starting Ollama Docker container ({mode}) ...")
                print(f"  Command: {' '.join(cmd)}")
                try:
                    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                    if r.returncode == 0:
                        print(style.ok(f"\n  Container started! Ollama is now running on port 11434."))
                        print(f"  Pull a model: kendr model ollama pull llama3.2")
                        return 0
                    else:
                        err = r.stderr.strip() or r.stdout.strip() or "Start failed"
                        if "image" in err.lower() and "pull" in err.lower():
                            print(style.warn("  Pulling ollama/ollama image from Docker Hub..."))
                        print(style.fail(f"  {err}"))
                        return 1
                except subprocess.TimeoutExpired:
                    print(style.warn("  Timed out — image may still be pulling in background."))
                    return 1
                except Exception as exc:
                    print(style.fail(f"  Error: {exc}"))
                    return 1

            if docker_action == "stop":
                if not _docker_available():
                    print(style.fail("  Docker is not running or not installed."))
                    return 1
                print(f"  Stopping container '{container}'...")
                subprocess.run(["docker", "stop", container], capture_output=True, timeout=30)
                subprocess.run(["docker", "rm", container], capture_output=True, timeout=15)
                print(style.ok(f"  Container '{container}' stopped and removed."))
                return 0

            raise SystemExit(f"Unknown docker action: {docker_action}")

        raise SystemExit(f"Unknown ollama action: {ollama_action}")

    raise SystemExit(f"Unknown model action: {action}")


def _run_setup_wizard(style: "_CliStyle") -> int:  # noqa: F821
    """Interactive CLI wizard that configures unconfigured integrations step-by-step."""
    from kendr.setup.catalog import INTEGRATION_DEFINITIONS

    if not sys.stdin.isatty():
        raise SystemExit("Setup wizard requires an interactive terminal.")

    print(style.heading("\n  kendr Setup Wizard"))
    print("  Walk through each integration conversationally.\n")

    # Build list of components that still need config
    todo: list[dict] = []
    for defn in INTEGRATION_DEFINITIONS:
        comp_id = defn.id
        snap = get_setup_component_snapshot(comp_id)
        total = snap.get("total_fields", 0)
        filled = snap.get("filled_fields", 0)
        if total > 0 and filled < total:
            todo.append({"id": comp_id, "title": defn.title, "defn": defn, "filled": filled, "total": total})

    if not todo:
        print(style.ok("All integrations are already configured. Nothing to set up!"))
        return 0

    print(f"  Found {len(todo)} integration(s) that need credentials:\n")
    for i, item in enumerate(todo, 1):
        pct = int(100 * item["filled"] / item["total"]) if item["total"] else 0
        pct_bar = ("#" * (pct // 10)).ljust(10, ".")
        print(f"  [{i}] {item['title']:35s}  [{pct_bar}] {pct}%")

    print()
    print("  Enter a number to configure it, 'all' to go through each, or 'q' to quit.\n")

    def _pick_integration() -> list[dict]:
        while True:
            choice = input("  Your choice: ").strip().lower()
            if choice in {"q", "quit", "exit"}:
                return []
            if choice == "all":
                return todo
            if choice.isdigit():
                idx = int(choice) - 1
                if 0 <= idx < len(todo):
                    return [todo[idx]]
            print("  Please enter a number from the list, 'all', or 'q'.")

    chosen = _pick_integration()
    if not chosen:
        print(style.warn("Wizard exited. No changes made."))
        return 0

    for item in chosen:
        comp_id = item["id"]
        title = item["title"]
        defn = item["defn"]
        fields = defn.fields
        snap = get_setup_component_snapshot(comp_id)
        current_vals = snap.get("values", {}) or {}

        print()
        print(style.heading(f"  Configuring: {title}"))
        desc = getattr(defn, "description", "")
        if desc:
            print(f"  {desc}\n")

        values_to_save: dict[str, str] = {}
        for field in fields:
            key = field.key
            label = field.label
            hint = field.description
            is_secret = bool(field.secret)
            existing = current_vals.get(key, "")

            prompt_parts = [f"  {label}"]
            if hint:
                print(f"    {hint}")
            if existing:
                masked = ("*" * min(len(existing), 8)) if is_secret else existing[:20]
                prompt_parts.append(f" [current: {masked}] (Enter to keep)")
            prompt_parts.append(": ")
            prompt_str = "".join(prompt_parts)

            try:
                if is_secret:
                    import getpass
                    value = getpass.getpass(prompt_str)
                else:
                    value = input(prompt_str)
                value = value.strip()
            except (EOFError, KeyboardInterrupt):
                print("\n  Skipped.")
                value = ""

            if value:
                values_to_save[key] = value
            elif existing:
                print(f"    Keeping existing value for {label}.")

        if values_to_save:
            result = save_component_values(comp_id, values_to_save)
            filled = result.get("filled_fields", 0)
            total = result.get("total_fields", 0)
            print(style.ok(f"  Saved {title}: {filled}/{total} fields configured."))
        else:
            print(style.warn(f"  No changes saved for {title}."))

    print()
    print(style.ok("  Wizard complete! Run 'kendr setup status' to verify your configuration."))
    return 0


def _cmd_setup(args: argparse.Namespace) -> int:
    style = _style_from_args(args)
    apply_setup_env_defaults()
    action = args.setup_action

    if not getattr(args, "json", False) and not getattr(args, "quiet", False):
        try:
            from kendr import cli_output as _setup_out
            _setup_out.startup_banner(
                version=_cli_version(),
                model=os.getenv("KENDR_MODEL", os.getenv("OPENAI_MODEL", "")),
                working_dir=os.getenv("KENDR_WORKING_DIR", ""),
                tagline=f"setup {action}",
            )
        except Exception:
            pass

    if action == "components":
        payload = setup_overview()
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            rows = [
                [
                    item["id"],
                    _truncate(str(item["title"]), 42),
                    "yes" if bool(item["enabled"]) else "no",
                    f"{item['filled_fields']}/{item['total_fields']}",
                ]
                for item in payload["components"]
            ]
            print(_render_table(["COMPONENT", "TITLE", "ENABLED", "CONFIGURED"], rows))
        return 0

    if action == "show":
        component = get_component(args.component)
        if not component:
            raise SystemExit(f"Unknown component: {args.component}")
        payload = get_setup_component_snapshot(args.component)
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"{component['title']} ({args.component})")
            print(f"enabled: {payload.get('enabled', True)}")
            print(f"configured fields: {payload.get('filled_fields', 0)}/{payload.get('total_fields', 0)}")
            for field in component.get("fields", []):
                key = field["key"]
                value = payload.get("values", {}).get(key, "")
                print(f"- {key}: {value or '(empty)'}")
        return 0

    if action == "set":
        component = get_component(args.component)
        if not component:
            raise SystemExit(f"Unknown component: {args.component}")
        known_keys = {field["key"] for field in component.get("fields", [])}
        if args.key not in known_keys:
            raise SystemExit(f"Unknown key '{args.key}' for component '{args.component}'")
        payload = save_component_values(args.component, {args.key: args.value})
        print(
            f"Updated {args.component}.{args.key} | "
            f"configured_fields={payload.get('filled_fields', 0)}/{payload.get('total_fields', 0)}"
        )
        return 0

    if action == "unset":
        component = get_component(args.component)
        if not component:
            raise SystemExit(f"Unknown component: {args.component}")
        known_keys = {field["key"] for field in component.get("fields", [])}
        if args.key not in known_keys:
            raise SystemExit(f"Unknown key '{args.key}' for component '{args.component}'")
        payload = save_component_values(args.component, {args.key: ""})
        print(
            f"Cleared {args.component}.{args.key} | "
            f"configured_fields={payload.get('filled_fields', 0)}/{payload.get('total_fields', 0)}"
        )
        return 0

    if action == "enable":
        component = get_component(args.component)
        if not component:
            raise SystemExit(f"Unknown component: {args.component}")
        set_component_enabled(args.component, True)
        print(style.ok(f"Enabled component: {args.component}"))
        return 0

    if action == "disable":
        component = get_component(args.component)
        if not component:
            raise SystemExit(f"Unknown component: {args.component}")
        set_component_enabled(args.component, False)
        print(style.ok(f"Disabled component: {args.component}"))
        return 0

    if action == "export-env":
        for line in export_env_lines(include_secrets=bool(args.include_secrets)):
            print(line)
        return 0

    if action == "install":
        requested = set(args.only or [])
        install_targets = [
            ("nmap", ["nmap"]),
            ("zap", ["zap-baseline.py", "owasp-zap", "zaproxy"]),
            ("dependency-check", ["dependency-check"]),
            ("playwright", ["playwright"]),
        ]
        if requested:
            install_targets = [item for item in install_targets if item[0] in requested]

        missing = [(name, checks) for name, checks in install_targets if not _tool_available(checks)]
        if not missing:
            print(style.ok("All selected components are already installed."))
            return 0

        print(style.heading("Installable missing components:"))
        for name, _ in missing:
            print(f"- {name}")

        if not bool(args.yes):
            if not sys.stdin.isatty():
                raise SystemExit("Use --yes for non-interactive install.")
            confirm = input("Proceed with best-effort install? (y/N): ").strip().lower()
            if confirm not in {"y", "yes"}:
                print(style.warn("Install canceled."))
                return 0

        for name, checks in missing:
            if name == "playwright":
                ok, detail = _run_install_command([sys.executable, "-m", "playwright", "install", "chromium"])
                if ok and _tool_available(checks):
                    print(style.ok("[installed] playwright"))
                else:
                    print(style.fail("[failed] playwright"))
                    if detail:
                        print(f"  {detail}")
                continue

            installed = False
            details: list[str] = []
            for command in _install_candidates_for_tool(name):
                ok, detail = _run_install_command(command)
                if ok and _tool_available(checks):
                    installed = True
                    break
                if detail:
                    details.append(f"{' '.join(command)} -> {detail}")
            if not installed and os.name == "nt" and name == "dependency-check":
                ok, detail = _install_dependency_check_from_release_zip()
                if ok and _tool_available(checks):
                    installed = True
                elif detail:
                    details.append(f"release-zip-fallback -> {detail}")
            if installed:
                print(style.ok(f"[installed] {name}"))
            else:
                print(style.fail(f"[failed] {name}"))
                if details:
                    for item in details[-3:]:
                        print(f"  - {item}")
        return 0

    if action == "oauth":
        provider = str(args.provider).strip().lower()
        providers = ["google", "microsoft", "slack"] if provider == "all" else [provider]
        base_url = _setup_ui_base_url()
        missing_by_provider: dict[str, list[str]] = {}
        for item in providers:
            missing = _oauth_missing_env(item)
            if missing:
                missing_by_provider[item] = missing
        if missing_by_provider:
            print(style.fail("OAuth is not configured for one or more providers."))
            for item in providers:
                missing = missing_by_provider.get(item, [])
                if not missing:
                    continue
                print(f"- {item}: missing {', '.join(missing)}")
            print("Set these values in the Kendr UI (Setup & Config) or in .env, then retry.")
            return 1
        if not _setup_ui_ready(timeout_seconds=0.8):
            print(style.warn(f"Kendr UI not detected at {base_url}; starting it..."))
            _start_setup_ui_process()

        for item in providers:
            url = f"{base_url}/api/oauth/{item}/start"
            if bool(args.no_browser):
                print(f"{item}: {url}")
                continue
            opened = False
            try:
                opened = bool(webbrowser.open(url, new=2))
            except Exception:
                opened = False
            if opened:
                print(style.ok(f"Opened {item} OAuth login in browser."))
            else:
                print(style.warn(f"Could not open browser automatically for {item}."))
                print(f"{item}: {url}")
        return 0

    if action == "status":
        try:
            registry = build_registry()
            snapshot = build_setup_snapshot(registry.agent_cards())
        except Exception:
            snapshot = build_setup_snapshot([])
        payload = {
            "setup": setup_overview(),
            "services": snapshot.get("services", {}),
            "available_agents": snapshot.get("available_agents", []),
            "disabled_agents": snapshot.get("disabled_agents", {}),
            "setup_actions": snapshot.get("setup_actions", []),
        }
        if args.json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(snapshot.get("summary_text", ""))
            actions = snapshot.get("setup_actions", [])
            if actions:
                print()
                print(style.heading("Setup actions:"))
                for item in actions:
                    if str(item.get("action", "")) == "oauth":
                        print(f"- {item.get('service')}: OAuth connect via {item.get('path')}")
                    else:
                        print(f"- {item.get('service')}: {item.get('hint', item.get('path', ''))}")
        return 0

    if action == "wizard":
        return _run_setup_wizard(style)

    if action == "ui":
        print(style.ok("Setup & Config is built into the main Kendr UI."))
        print("Starting the main UI...")
        return _cmd_ui(args)

    raise SystemExit(f"Unknown setup action: {action}")


def _cmd_sessions(args: argparse.Namespace) -> int:
    style = _style_from_args(args)
    action = str(getattr(args, "action", "list")).strip().lower()
    stored = _load_cli_session()

    if action == "current":
        if args.json:
            print(json.dumps(stored, indent=2, ensure_ascii=False))
            return 0
        if not stored:
            print(style.warn("No active CLI session selected."))
            return 0
        print(style.heading("Active session"))
        print(f"Session key: {stored.get('session_key', '')}")
        print(f"Channel:     {stored.get('channel', '')}")
        print(f"Workspace:   {stored.get('workspace_id', '')}")
        print(f"Chat:        {stored.get('chat_id', '')}")
        return 0

    if action == "clear":
        _clear_cli_session()
        if args.json:
            print(json.dumps({"cleared": True}, indent=2, ensure_ascii=False))
            return 0
        print(style.ok("Cleared active CLI session."))
        return 0

    if action == "use":
        session_key = str(getattr(args, "session_key", "") or "").strip()
        if not session_key:
            raise SystemExit("sessions use requires <session_key>")
        parts = _session_parts_from_key(session_key)
        if not parts:
            raise SystemExit("Invalid session key format. Expected channel:workspace:chat:scope")
        _save_cli_session(parts)
        if args.json:
            print(json.dumps(parts, indent=2, ensure_ascii=False))
            return 0
        print(style.ok(f"Active session set to: {session_key}"))
        return 0

    gateway_base = _gateway_base_url()
    if not _gateway_ready():
        raise SystemExit(
            f"Gateway is not running at {gateway_base}.\n"
            "Start it first with:  kendr gateway start"
        )
    sessions = _http_json_get(f"{gateway_base}/sessions", timeout_seconds=2.5)
    if not isinstance(sessions, list):
        raise SystemExit("Gateway returned invalid session payload.")
    limit = int(getattr(args, "limit", 20) or 20)
    sessions = sessions[:limit]
    if args.json:
        print(json.dumps(sessions, indent=2, ensure_ascii=False))
        return 0
    if not sessions:
        print(style.warn("No sessions found."))
        return 0
    rows = []
    for item in sessions:
        state = item.get("state", {}) if isinstance(item.get("state"), dict) else {}
        rows.append(
            [
                str(item.get("session_key", "")),
                str(item.get("channel", "")),
                str(item.get("workspace_id", "")),
                str(item.get("chat_id", "")),
                str(state.get("last_status", "")),
                str(item.get("updated_at", "")),
            ]
        )
    print(style.heading(f"Sessions ({len(rows)}):"))
    print(_render_table(["SESSION_KEY", "CHANNEL", "WORKSPACE", "CHAT", "STATUS", "UPDATED_AT"], rows))
    return 0


def _cmd_status(args: argparse.Namespace) -> int:
    style = _style_from_args(args)
    host, port = _gateway_host_port()
    base_url = _gateway_base_url()
    running = _gateway_ready(timeout_seconds=0.5)
    setup = setup_overview()
    components = list(setup.get("components", []))
    enabled_components = sum(1 for item in components if bool(item.get("enabled", True)))
    fully_configured_components = sum(
        1 for item in components if int(item.get("filled_fields", 0)) == int(item.get("total_fields", 0))
    )
    configured_workdir = _configured_working_dir()
    payload = {
        "gateway": {
            "running": running,
            "host": host,
            "port": port,
            "base_url": base_url,
            "listener_pids": _listener_pids_for_port(port) if running else [],
        },
        "working_directory": {
            "configured": bool(configured_workdir),
            "path": _resolve_working_dir(configured_workdir) if configured_workdir else "",
        },
        "setup": {
            "components_total": len(components),
            "components_enabled": enabled_components,
            "components_fully_configured": fully_configured_components,
        },
    }
    if bool(getattr(args, "json", False)):
        print(json.dumps(payload, indent=2, ensure_ascii=False))
        return 0
    print(style.heading("Runtime status"))
    print(f"Gateway:          {'running' if running else 'stopped'} ({base_url})")
    print(f"Working directory:{' ' if configured_workdir else ''}{payload['working_directory']['path'] or '(not set)'}")
    print(
        "Setup:            "
        f"{payload['setup']['components_fully_configured']}/{payload['setup']['components_total']} fully configured, "
        f"{payload['setup']['components_enabled']} enabled"
    )
    return 0


def _cmd_rollback(args: argparse.Namespace) -> int:
    style = _style_from_args(args)
    action = str(getattr(args, "action", "list")).strip().lower()
    if action == "list":
        snapshots = list_backup_snapshots(limit=100)
        if not snapshots:
            print(style.warn("No privileged snapshots found."))
            return 0
        print(style.heading(f"Privileged snapshots ({len(snapshots)}):"))
        for item in snapshots:
            print(f"- {item}")
        return 0

    snapshots = list_backup_snapshots(limit=200)
    snapshot = str(getattr(args, "snapshot", "")).strip() or (snapshots[0] if snapshots else "")
    if not snapshot:
        raise SystemExit("No snapshot available. Use rollback list first.")
    target_dir = str(getattr(args, "target_dir", "")).strip()
    if not target_dir:
        raise SystemExit("rollback apply requires --target-dir.")
    if not bool(getattr(args, "yes", False)):
        if not sys.stdin.isatty():
            raise SystemExit("Use --yes for non-interactive rollback apply.")
        confirm = input(f"Restore snapshot {snapshot} into {target_dir}? (y/N): ").strip().lower()
        if confirm not in {"y", "yes"}:
            print(style.warn("Rollback canceled."))
            return 0
    restored = restore_backup_snapshot(snapshot, target_dir, overwrite=bool(getattr(args, "overwrite", False)))
    print(style.ok(f"Rollback applied from {snapshot} to {restored}"))
    return 0


def main(argv: list[str] | None = None) -> int:
    style = _cli_style(argv)
    parser, command_parsers = _build_parser(style)
    args = parser.parse_args(argv)

    if getattr(args, "log_level", ""):
        os.environ["KENDR_LOG_LEVEL"] = str(args.log_level)

    if not getattr(args, "command", None):
        parser.print_help()
        return 0

    if args.command == "help":
        topic = str(getattr(args, "topic", "") or "").strip()
        if not topic:
            parser.print_help()
            return 0
        target_parser = command_parsers.get(topic)
        if not target_parser:
            raise SystemExit(f"Unknown help topic: {topic}")
        target_parser.print_help()
        return 0

    try:
        if args.command == "hello":
            return _cmd_hello(args)
        if args.command == "run":
            return _cmd_run(args)
        if args.command == "generate":
            return _cmd_generate(args)
        if args.command == "project":
            return _cmd_project(args)
        if args.command == "rag":
            return _cmd_rag(args)
        if args.command == "research":
            return _cmd_research(args)
        if args.command == "test":
            return _cmd_test(args)
        if args.command == "mcp":
            return _cmd_mcp(args)
        if args.command == "agents":
            return _cmd_agents(args)
        if args.command == "plugins":
            return _cmd_plugins(args)
        if args.command == "gateway":
            return _cmd_gateway(args)
        if args.command == "web":
            return _cmd_ui(args)
        if args.command == "setup-ui":
            return _cmd_ui(args)
        if args.command == "status":
            return _cmd_status(args)
        if args.command == "resume":
            return _cmd_resume(args)
        if args.command == "sessions":
            return _cmd_sessions(args)
        if args.command == "rollback":
            return _cmd_rollback(args)
        if args.command == "daemon":
            from .daemon import run_daemon

            return run_daemon(
                poll_interval_seconds=args.poll_interval,
                heartbeat_interval_seconds=args.heartbeat_interval,
                once=args.once,
            )
        if args.command == "model":
            return _cmd_model(args)
        if args.command == "setup":
            return _cmd_setup(args)
        if args.command == "workdir":
            return _cmd_workdir(args)
        if args.command == "ui":
            return _cmd_ui(args)
        if args.command == "new":
            return _cmd_new(args)
        if args.command == "checkpoint":
            return _cmd_checkpoint(args)
        if args.command == "doctor":
            return _cmd_doctor(args)
        if args.command == "clean":
            return _cmd_clean(args)
        if args.command == "upgrade":
            return _cmd_upgrade(args)
        raise SystemExit(f"Unknown command: {args.command}")
    except KeyboardInterrupt:
        print("\nQuit")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
