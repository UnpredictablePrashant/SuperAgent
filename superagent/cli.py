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
from tasks.setup_registry import build_setup_snapshot
from tasks.setup_registry import (
    build_google_oauth_config,
    build_microsoft_oauth_config,
    build_slack_oauth_config,
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
        return importlib.metadata.version("superagent-runtime")
    except importlib.metadata.PackageNotFoundError:
        return "dev"


def _cli_tagline() -> str:
    options = [
        "Orchestrate agents, not terminal chaos.",
        "Structured automation for serious workflows.",
        "Reliable multi-agent execution from one command surface.",
        "If it scales, it belongs in your CLI.",
    ]
    day_index = dt.date.today().toordinal() % len(options)
    return options[day_index]


def _cli_banner(style: _CliStyle) -> str:
    version = _cli_version()
    return f"{style.title('SuperAgent')} {style.muted(version)} - {_cli_tagline()}"


class _SuperagentHelpFormatter(argparse.RawTextHelpFormatter):
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
    message = (
        f"[run] status={session.get('status', 'running')} "
        f"active_agent={session.get('active_agent', '') or '-'} "
        f"steps={session.get('step_count', 0)}"
    )
    if bool(summary.get("awaiting_user_input")):
        pending_kind = _truncate_status_text(summary.get("pending_user_input_kind") or "user_input", limit=40)
        scope = _truncate_status_text(summary.get("approval_pending_scope") or "", limit=40)
        message += f" awaiting={pending_kind}"
        if scope:
            message += f" scope={scope}"
    active_task = _truncate_status_text(summary.get("active_task") or summary.get("objective") or "")
    if active_task:
        message += f" task={active_task}"
    return message


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
    style = _style_from_args(args)
    level = _status_level(message, transient=transient)
    formatter = {
        "muted": style.muted,
        "fail": style.fail,
        "warn": style.warn,
        "ok": style.ok,
        "heading": style.heading,
    }[level]
    return formatter(str(message))


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
    print(styled_message, file=sys.stderr, flush=True)


def _gateway_ready(timeout_seconds: float = 1.0) -> bool:
    request = urllib.request.Request(f"{_gateway_base_url()}/health", method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            payload = json.loads(response.read().decode("utf-8"))
            return response.status == 200 and payload.get("status") == "ok"
    except Exception:
        return False


def _start_gateway_process() -> None:
    subprocess.Popen(
        [sys.executable, "-m", "superagent.cli", "gateway", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(20):
        if _gateway_ready(timeout_seconds=0.5):
            return
        time.sleep(0.25)
    raise SystemExit(f"Gateway did not become ready at {_gateway_base_url()}. Start it manually with: superagent gateway")


def _setup_ui_base_url() -> str:
    host = os.getenv("SETUP_UI_HOST", "127.0.0.1")
    port = int(os.getenv("SETUP_UI_PORT", "8787"))
    return f"http://{host}:{port}"


def _setup_ui_ready(timeout_seconds: float = 1.0) -> bool:
    try:
        _http_json_get(f"{_setup_ui_base_url()}/api/setup/overview", timeout_seconds=timeout_seconds)
        return True
    except Exception:
        return False


def _start_setup_ui_process() -> None:
    subprocess.Popen(
        [sys.executable, "-m", "superagent.cli", "setup", "ui"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(24):
        if _setup_ui_ready(timeout_seconds=0.5):
            return
        time.sleep(0.25)
    raise SystemExit(f"Setup UI did not become ready at {_setup_ui_base_url()}. Start it manually with: superagent setup ui")


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
    for pid in pids:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, check=False)
            else:
                os.kill(pid, 15)
        except Exception:
            continue
    return len(pids)


def _resolve_working_dir(path_value: str) -> str:
    resolved = Path(path_value).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    return str(resolved)


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


def _configured_working_dir() -> str:
    configured = str(os.getenv("SUPERAGENT_WORKING_DIR", "")).strip()
    if configured:
        return configured
    try:
        snapshot = get_setup_component_snapshot("core_runtime")
        return str(snapshot.get("values", {}).get("SUPERAGENT_WORKING_DIR", "")).strip()
    except Exception:
        return ""


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


def _superagent_home_dir() -> Path:
    raw = os.getenv("SUPERAGENT_HOME", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path.home() / ".superagent").resolve()


def _active_scripts_dir() -> Path:
    return Path(sys.executable).resolve().parent


def _install_dependency_check_from_release_zip() -> tuple[bool, str]:
    try:
        tools_root = _superagent_home_dir() / "tools" / "dependency-check"
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
        prog="superagent",
        description=(
            f"{_cli_banner(style)}\n\n"
            "Plugin-driven multi-agent runtime and orchestration surface."
        ),
        epilog=(
            f"{style.heading('Examples')}\n"
            "  superagent run \"Summarize this repository\" --max-steps 12\n"
            "  superagent agents list\n"
            "  superagent gateway start\n"
            "  superagent status\n"
            "  superagent help setup\n\n"
            f"{style.heading('Docs')}\n"
            "  README.md"
        ),
        formatter_class=_SuperagentHelpFormatter,
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
        "--long-document",
        action="store_true",
        help="Force long-form staged document workflow (chaptered research + merged output).",
    )
    run_parser.add_argument(
        "--long-document-pages",
        type=int,
        default=0,
        help="Target page count for long-form mode (for example 50).",
    )
    run_parser.add_argument(
        "--long-document-sections",
        type=int,
        default=0,
        help="Optional explicit section count for long-form mode.",
    )
    run_parser.add_argument(
        "--long-document-section-pages",
        type=int,
        default=0,
        help="Approximate pages per section in long-form mode.",
    )
    run_parser.add_argument(
        "--long-document-title",
        default="",
        help="Optional report title override for long-form mode.",
    )
    run_parser.add_argument(
        "--drive",
        action="append",
        default=[],
        help="Local folder or file path for local-drive ingestion. Repeat for multiple paths.",
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
    subparsers.add_parser("web", help="Alias for gateway server.")
    subparsers.add_parser("setup-ui", help="Run the OAuth/setup UI.")
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

    setup_sub.add_parser("ui", help="Run the web-based setup UI.")
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
        help="Also save this path as SUPERAGENT_WORKING_DIR.",
    )
    workdir_sub.add_parser("clear", help="Clear configured SUPERAGENT_WORKING_DIR.")
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
    return parser, command_parsers


def _cmd_run(args: argparse.Namespace) -> int:
    query = " ".join(args.query).strip() or input("Enter your query: ").strip()
    configured_working_dir = ""
    if bool(args.current_folder):
        configured_working_dir = str(Path.cwd())
    else:
        configured_working_dir = str(args.working_directory or _configured_working_dir()).strip()
    if not configured_working_dir:
        configured_working_dir = input("Set a working folder for task runs (required): ").strip()
        if not configured_working_dir:
            raise SystemExit("Working folder is required. Configure SUPERAGENT_WORKING_DIR in setup or pass --working-directory.")
        save_component_values("core_runtime", {"SUPERAGENT_WORKING_DIR": configured_working_dir})
        os.environ["SUPERAGENT_WORKING_DIR"] = configured_working_dir
    resolved_working_dir = _resolve_working_dir(configured_working_dir)
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
            print(authorization_process_text(security_target_url))
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

    if not _gateway_ready():
        _emit_status(args, f"[gateway] not running at {gateway_base}; starting gateway...")
        _start_gateway_process()
        _emit_status(args, f"[gateway] ready at {gateway_base}")

    client_run_id = f"run_cli_{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
    selected_session = {}
    if str(args.session_key or "").strip():
        selected_session = _session_parts_from_key(str(args.session_key))
        if not selected_session:
            raise SystemExit("Invalid --session-key format. Expected channel:workspace:chat:scope")
    else:
        selected_session = _load_cli_session()
    ingest_payload = {
        "run_id": client_run_id,
        "text": query,
        "max_steps": args.max_steps,
        "working_directory": resolved_working_dir,
    }
    if bool(args.long_document):
        ingest_payload["long_document_mode"] = True
    if int(args.long_document_pages or 0) > 0:
        ingest_payload["long_document_pages"] = int(args.long_document_pages)
    if int(args.long_document_sections or 0) > 0:
        ingest_payload["long_document_sections"] = int(args.long_document_sections)
    if int(args.long_document_section_pages or 0) > 0:
        ingest_payload["long_document_section_pages"] = int(args.long_document_section_pages)
    if str(args.long_document_title or "").strip():
        ingest_payload["long_document_title"] = str(args.long_document_title).strip()
    if int(args.research_max_wait_seconds or 0) > 0:
        ingest_payload["research_max_wait_seconds"] = int(args.research_max_wait_seconds)
    if int(args.research_poll_interval_seconds or 0) > 0:
        ingest_payload["research_poll_interval_seconds"] = int(args.research_poll_interval_seconds)
    if int(args.research_max_tool_calls or 0) > 0:
        ingest_payload["research_max_tool_calls"] = int(args.research_max_tool_calls)
    if int(args.research_max_output_tokens or 0) > 0:
        ingest_payload["research_max_output_tokens"] = int(args.research_max_output_tokens)

    drive_paths = _normalize_drive_paths(args.drive)
    if drive_paths:
        ingest_payload["local_drive_paths"] = drive_paths
        ingest_payload["local_drive_recursive"] = not bool(args.drive_no_recursive)
        if bool(args.drive_include_hidden):
            ingest_payload["local_drive_include_hidden"] = True
        if int(args.drive_max_files or 0) > 0:
            ingest_payload["local_drive_max_files"] = int(args.drive_max_files)
        if str(args.drive_extensions or "").strip():
            ingest_payload["local_drive_extensions"] = [item.strip() for item in str(args.drive_extensions).split(",") if item.strip()]
        if bool(args.drive_disable_image_ocr):
            ingest_payload["local_drive_enable_image_ocr"] = False
        if str(args.drive_ocr_instruction or "").strip():
            ingest_payload["local_drive_ocr_instruction"] = str(args.drive_ocr_instruction).strip()
        if bool(args.drive_no_memory_index):
            ingest_payload["local_drive_index_to_memory"] = False
        ingest_payload["local_drive_working_directory"] = resolved_working_dir

        inferred_pages = _extract_requested_page_count(query)
        inferred_long_document = _query_requests_long_document(query)
        explicit_long_document = bool(args.long_document) or int(args.long_document_pages or 0) > 0
        if inferred_long_document and not explicit_long_document:
            ingest_payload["long_document_mode"] = True
            if inferred_pages >= 20:
                ingest_payload["long_document_pages"] = inferred_pages
        if inferred_long_document or explicit_long_document:
            ingest_payload["local_drive_force_long_document"] = True

    superrag_paths = _normalize_drive_paths(args.superrag_path)
    superrag_urls = [str(item).strip() for item in list(args.superrag_url or []) if str(item).strip()]
    if str(args.superrag_mode or "").strip():
        ingest_payload["superrag_mode"] = str(args.superrag_mode).strip().lower()
    if str(args.superrag_session or "").strip():
        ingest_payload["superrag_session_id"] = str(args.superrag_session).strip()
    if bool(args.superrag_new_session):
        ingest_payload["superrag_new_session"] = True
    if str(args.superrag_session_title or "").strip():
        ingest_payload["superrag_session_title"] = str(args.superrag_session_title).strip()
    if superrag_paths:
        ingest_payload["superrag_local_paths"] = superrag_paths
    if superrag_urls:
        ingest_payload["superrag_urls"] = superrag_urls
    if str(args.superrag_db_url or "").strip():
        ingest_payload["superrag_db_url"] = str(args.superrag_db_url).strip()
    if str(args.superrag_db_schema or "").strip():
        ingest_payload["superrag_db_schema"] = str(args.superrag_db_schema).strip()
    if bool(args.superrag_onedrive):
        ingest_payload["superrag_onedrive_enabled"] = True
    if str(args.superrag_onedrive_path or "").strip():
        ingest_payload["superrag_onedrive_path"] = str(args.superrag_onedrive_path).strip()
        ingest_payload["superrag_onedrive_enabled"] = True
    if str(args.superrag_chat or "").strip():
        ingest_payload["superrag_chat_query"] = str(args.superrag_chat).strip()
    if int(args.superrag_top_k or 0) > 0:
        ingest_payload["superrag_top_k"] = int(args.superrag_top_k)

    has_superrag_sources = bool(superrag_paths or superrag_urls or ingest_payload.get("superrag_db_url") or ingest_payload.get("superrag_onedrive_enabled"))
    if has_superrag_sources and not ingest_payload.get("superrag_mode"):
        ingest_payload["superrag_mode"] = "build"
    if ingest_payload.get("superrag_chat_query") and not ingest_payload.get("superrag_mode"):
        ingest_payload["superrag_mode"] = "chat"

    if security_authorized:
        ingest_payload["security_authorized"] = True
    if security_target_url:
        ingest_payload["security_target_url"] = security_target_url
    if security_authorization_note:
        ingest_payload["security_authorization_note"] = security_authorization_note
    if security_scan_profile:
        ingest_payload["security_scan_profile"] = security_scan_profile
    if bool(args.privileged_mode):
        ingest_payload["privileged_mode"] = True
    if bool(args.privileged_approved):
        ingest_payload["privileged_approved"] = True
    if str(args.privileged_approval_note or "").strip():
        ingest_payload["privileged_approval_note"] = str(args.privileged_approval_note).strip()
    if bool(args.privileged_read_only):
        ingest_payload["privileged_read_only"] = True
    if bool(args.privileged_allow_root):
        ingest_payload["privileged_allow_root"] = True
    if bool(args.privileged_allow_destructive):
        ingest_payload["privileged_allow_destructive"] = True
    if bool(args.privileged_enable_backup):
        ingest_payload["privileged_enable_backup"] = True
    if args.privileged_allowed_path:
        ingest_payload["privileged_allowed_paths"] = list(args.privileged_allowed_path)
    if args.privileged_allowed_domain:
        ingest_payload["privileged_allowed_domains"] = list(args.privileged_allowed_domain)
    if str(args.kill_switch_file or "").strip():
        ingest_payload["kill_switch_file"] = str(args.kill_switch_file).strip()
    channel = str(args.channel or selected_session.get("channel", "webchat") or "webchat").strip()
    workspace_id = str(args.workspace_id or selected_session.get("workspace_id", "default") or "default").strip()
    stored_sender = str(selected_session.get("sender_id", "") or "").strip()
    sender_id = str(args.sender_id or stored_sender or "cli_user").strip()
    chat_id = str(args.chat_id or selected_session.get("chat_id", sender_id) or sender_id).strip()
    ingest_payload["channel"] = channel
    ingest_payload["workspace_id"] = workspace_id
    ingest_payload["sender_id"] = sender_id
    ingest_payload["chat_id"] = chat_id
    ingest_payload["is_group"] = bool(selected_session.get("scope", "main") == "group")
    if bool(args.new_session):
        ingest_payload["new_session"] = True
    else:
        _save_cli_session(
            {
                "session_key": f"{channel}:{workspace_id}:{chat_id}:{'group' if ingest_payload['is_group'] else 'main'}",
                "channel": channel,
                "workspace_id": workspace_id,
                "chat_id": chat_id,
                "sender_id": sender_id,
                "scope": "group" if ingest_payload["is_group"] else "main",
            }
        )

    def _ingest_once() -> dict:
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

    holder: dict[str, object] = {"result": None, "error": None}

    def _submit_ingest() -> None:
        try:
            holder["result"] = _ingest_once()
        except BaseException as exc:  # noqa: BLE001
            holder["error"] = exc

    worker = threading.Thread(target=_submit_ingest, daemon=True)
    worker.start()

    def _poll_task_session_progress(previous_message: str) -> str:
        try:
            sessions = _http_json_get(f"{gateway_base}/task-sessions", timeout_seconds=1.2)
            if isinstance(sessions, list):
                match = next((item for item in sessions if str(item.get("run_id", "")) == client_run_id), None)
                if isinstance(match, dict):
                    message = _build_run_progress_message(match)
                    if message != previous_message:
                        _emit_status(args, message)
                        return message
        except Exception:
            pass
        return previous_message

    try:
        _emit_status(
            args,
            f"[run] accepted request run_id={client_run_id} | working_directory={resolved_working_dir}",
        )
        started_wait = time.time()
        last_progress = ""
        last_wait_emit = 0.0
        while worker.is_alive():
            worker.join(timeout=1.0)
            last_progress = _poll_task_session_progress(last_progress)

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
                last_progress = _poll_task_session_progress(last_progress)
                try:
                    payload = _http_json_get(f"{gateway_base}/runs/{client_run_id}", timeout_seconds=1.5)
                    if isinstance(payload, dict):
                        run_record = payload
                except Exception:
                    run_record = None

                if run_record is not None:
                    status = str(run_record.get("status", "")).strip().lower()
                    if status == "completed":
                        result = {
                            "run_id": run_record.get("run_id", client_run_id),
                            "final_output": run_record.get("final_output", ""),
                            "last_agent": "",
                        }
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

        _emit_status(
            args,
            f"[run] completed run_id={result.get('run_id', client_run_id)} "
            f"last_agent={result.get('last_agent', '') or '-'}",
        )

        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False, default=str))
        else:
            print(result.get("final_output", ""))
        return 0
    finally:
        _clear_transient_status_line()


def _cmd_gateway(args: argparse.Namespace) -> int:
    style = _style_from_args(args)
    action = getattr(args, "action", "serve")
    base = _gateway_base_url()
    host, port = _gateway_host_port()

    if action == "serve":
        from .gateway_server import main as gateway_main

        gateway_main()
        return 0

    if action == "status":
        running = _gateway_ready(timeout_seconds=0.5)
        pids = _listener_pids_for_port(port)
        payload = {"running": running, "host": host, "port": port, "base_url": base, "pids": pids}
        if bool(getattr(args, "json", False)):
            print(json.dumps(payload, indent=2, ensure_ascii=False))
            return 0
        if running:
            print(style.ok(f"Gateway is running at {base} (port {port}, pids={pids or 'unknown'})."))
        else:
            print(style.warn(f"Gateway is stopped at {base} (port {port})."))
        return 0

    if action == "stop":
        stopped = _terminate_gateway_on_port()
        if bool(getattr(args, "json", False)):
            print(json.dumps({"action": "stop", "port": port, "stopped": stopped}, indent=2, ensure_ascii=False))
            return 0
        print(style.ok(f"Stopped gateway listeners on port {port}: {stopped}"))
        return 0

    if action == "restart":
        _terminate_gateway_on_port()
        _start_gateway_process()
        if bool(getattr(args, "json", False)):
            print(json.dumps({"action": "restart", "base_url": base, "port": port}, indent=2, ensure_ascii=False))
            return 0
        print(style.ok(f"Gateway restarted at {base}"))
        return 0

    if action == "start":
        if _gateway_ready(timeout_seconds=0.5):
            if bool(getattr(args, "json", False)):
                print(json.dumps({"action": "start", "base_url": base, "already_running": True}, indent=2, ensure_ascii=False))
                return 0
            print(style.warn(f"Gateway already running at {base}"))
            return 0
        _start_gateway_process()
        if bool(getattr(args, "json", False)):
            print(json.dumps({"action": "start", "base_url": base, "started": True}, indent=2, ensure_ascii=False))
            return 0
        print(style.ok(f"Gateway started at {base}"))
        return 0

    raise SystemExit(f"Unknown gateway action: {action}")


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
        save_component_values("core_runtime", {"SUPERAGENT_WORKING_DIR": resolved})
        os.environ["SUPERAGENT_WORKING_DIR"] = resolved
        print(style.ok(f"Working directory set to: {resolved}"))
        return 0

    if action == "here":
        resolved = _resolve_working_dir(str(Path.cwd()))
        save_component_values("core_runtime", {"SUPERAGENT_WORKING_DIR": resolved})
        os.environ["SUPERAGENT_WORKING_DIR"] = resolved
        print(style.ok(f"Working directory set to current folder: {resolved}"))
        return 0

    if action == "create":
        resolved = _resolve_working_dir(args.path)
        if bool(args.activate):
            save_component_values("core_runtime", {"SUPERAGENT_WORKING_DIR": resolved})
            os.environ["SUPERAGENT_WORKING_DIR"] = resolved
            print(style.ok(f"Created and activated working directory: {resolved}"))
        else:
            print(style.ok(f"Created working directory: {resolved}"))
        return 0

    if action == "clear":
        save_component_values("core_runtime", {"SUPERAGENT_WORKING_DIR": ""})
        os.environ.pop("SUPERAGENT_WORKING_DIR", None)
        print(style.ok("Cleared SUPERAGENT_WORKING_DIR."))
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
                _truncate(str(item["description"]), 80),
            ]
            for item in payload
        ]
        if not rows:
            print(style.warn("No plugins matched the current filters."))
            return 0
        print(style.heading(f"Discovered plugins ({len(payload)}):"))
        print(_render_table(["NAME", "KIND", "VERSION", "DESCRIPTION"], rows))
    return 0


def _cmd_setup(args: argparse.Namespace) -> int:
    style = _style_from_args(args)
    apply_setup_env_defaults()
    action = args.setup_action

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
            print("Set these values in setup UI component pages or in .env, then retry.")
            return 1
        if not _setup_ui_ready(timeout_seconds=0.8):
            print(style.warn(f"Setup UI not detected at {base_url}; starting setup UI..."))
            _start_setup_ui_process()

        for item in providers:
            url = f"{base_url}/oauth/{item}/start"
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

    if action == "ui":
        from .setup_ui import main as setup_main

        setup_main()
        return 0

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
        _start_gateway_process()
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
        rows.append(
            [
                str(item.get("session_key", "")),
                str(item.get("channel", "")),
                str(item.get("workspace_id", "")),
                str(item.get("chat_id", "")),
                str(item.get("updated_at", "")),
            ]
        )
    print(style.heading(f"Sessions ({len(rows)}):"))
    print(_render_table(["SESSION_KEY", "CHANNEL", "WORKSPACE", "CHAT", "UPDATED_AT"], rows))
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
        os.environ["SUPERAGENT_LOG_LEVEL"] = str(args.log_level)

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

    if args.command == "run":
        return _cmd_run(args)
    if args.command == "agents":
        return _cmd_agents(args)
    if args.command == "plugins":
        return _cmd_plugins(args)
    if args.command == "gateway":
        return _cmd_gateway(args)
    if args.command == "web":
        return _cmd_gateway(argparse.Namespace(action="serve"))
    if args.command == "setup-ui":
        from .setup_ui import main as setup_main

        setup_main()
        return 0
    if args.command == "status":
        return _cmd_status(args)
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
    if args.command == "setup":
        return _cmd_setup(args)
    if args.command == "workdir":
        return _cmd_workdir(args)
    raise SystemExit(f"Unknown command: {args.command}")


if __name__ == "__main__":
    raise SystemExit(main())
