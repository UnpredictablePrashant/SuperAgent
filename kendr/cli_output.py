from __future__ import annotations

import os
import time
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeElapsedColumn
from rich.table import Table
from rich.text import Text

_TEAL = "#00C9A7"
_AMBER = "#FFB347"
_CRIMSON = "#FF4757"
_BLUE = "#5352ED"
_GREY = "grey62"

_console = Console(stderr=False)
_err_console = Console(stderr=True)

AGENT_QUIPS: dict[str, tuple[str, str]] = {
    "deep_research_agent": (
        "⚡ DISPATCHING INTELLIGENCE",
        "deep_research_agent is combing the internet so you don't have to",
    ),
    "long_document_agent": (
        "📄 MATERIALIZING DOCUMENT",
        "converting thought into paper, like magic but slower",
    ),
    "planner_agent": (
        "🧠 CONSTRUCTING THE PLAN",
        "because someone has to think before doing things",
    ),
    "reviewer_agent": (
        "🔍 QUALITY ENFORCEMENT",
        "reviewer_agent is judging your output with appropriate severity",
    ),
    "worker_agent": (
        "⚙️ DOING THE WORK",
        "worker_agent is handling the actual labour. respect.",
    ),
    "superrag_agent": (
        "🗄️ INDEXING REALITY",
        "superrag_agent is building your knowledge graph, one chunk at a time",
    ),
    "communication_summary_agent": (
        "📬 AGGREGATING MESSAGES",
        "fetching everything you missed — there's a lot",
    ),
    "whatsapp_send_message_agent": (
        "💬 DISPATCHING WHATSAPP",
        "sending your message into the digital ether",
    ),
    "whatsapp_list_messages_agent": (
        "📲 FETCHING WHATSAPP",
        "retrieving your WhatsApp thread with impressive API calls",
    ),
    "master_coding_agent": (
        "👨‍💻 INITIATING CODEGEN",
        "master_coding_agent is about to write more code than you expected",
    ),
    "project_builder_agent": (
        "🏗️ BUILDING PROJECT",
        "scaffolding your empire, one file at a time",
    ),
    "blueprint_agent": (
        "📐 DESIGNING BLUEPRINT",
        "architect mode engaged — decisions are being made on your behalf",
    ),
    "test_agent": (
        "🧪 RUNNING TESTS",
        "finding out if the code actually works (results may surprise you)",
    ),
    "devops_agent": (
        "🚀 CONFIGURING DEPLOYMENT",
        "devops_agent is setting up infrastructure with quiet determination",
    ),
    "security_agent": (
        "🛡️ SECURITY ASSESSMENT",
        "probing for vulnerabilities — ethically, presumably",
    ),
    "os_command_agent": (
        "💻 EXECUTING COMMAND",
        "running your shell command with appropriate paranoia",
    ),
    "local_drive_agent": (
        "📁 SCANNING FILES",
        "local_drive_agent is indexing your filesystem. all of it.",
    ),
    "channel_gateway_agent": (
        "🔀 NORMALIZING PAYLOAD",
        "translating your request into orchestration-speak",
    ),
    "session_router_agent": (
        "🔗 RESOLVING SESSION",
        "finding your session context in the database maze",
    ),
}

_GENERIC_QUIPS = [
    "agents are being mobilized",
    "the runtime is earning its keep",
    "progress is definitely happening",
    "machines are machining",
    "an agent has been dispatched, results pending",
]


def _quip_for(agent_name: str) -> tuple[str, str]:
    if agent_name in AGENT_QUIPS:
        return AGENT_QUIPS[agent_name]
    day_index = int(time.time()) % len(_GENERIC_QUIPS)
    label = agent_name.replace("_", " ").upper()
    return (f"⚡ {label}", _GENERIC_QUIPS[day_index])


def _is_color_enabled() -> bool:
    if os.getenv("NO_COLOR"):
        return False
    try:
        import sys
        return bool(getattr(sys.stdout, "isatty", lambda: False)())
    except Exception:
        return False


def startup_banner(version: str = "", model: str = "", working_dir: str = "", tagline: str = "") -> None:
    ver_str = version or "dev"
    logo_lines = [
        "  ██╗  ██╗███████╗███╗   ██╗██████╗ ██████╗ ",
        "  ██║ ██╔╝██╔════╝████╗  ██║██╔══██╗██╔══██╗",
        "  █████╔╝ █████╗  ██╔██╗ ██║██║  ██║██████╔╝",
        "  ██╔═██╗ ██╔══╝  ██║╚██╗██║██║  ██║██╔══██╗",
        "  ██║  ██╗███████╗██║ ╚████║██████╔╝██║  ██║",
        "  ╚═╝  ╚═╝╚══════╝╚═╝  ╚═══╝╚═════╝ ╚═╝  ╚═╝",
    ]
    content = Text()
    for line in logo_lines:
        content.append(line + "\n", style=_TEAL)
    content.append(f"\n  v{ver_str}  ·  Multi-agent intelligence runtime\n", style=_GREY)
    if tagline:
        content.append(f"\n  {tagline}\n", style=_GREY)
    meta_parts = []
    if model:
        meta_parts.append(f"model: {model}")
    if working_dir:
        meta_parts.append(f"workdir: {working_dir}")
    if meta_parts:
        content.append("\n  " + "  |  ".join(meta_parts) + "\n", style=_GREY)
    _console.print(Panel(content, border_style=_TEAL, expand=False, padding=(0, 1)))


def step_start(agent_name: str, message: str = "") -> None:
    header, quip = _quip_for(agent_name)
    body = message or quip
    text = Text()
    text.append(header, style=f"bold {_BLUE}")
    text.append(f" — {body}", style=_GREY)
    _console.print(text)


def step_done(agent_name: str, duration: float | None = None, artifacts: list[str] | None = None) -> None:
    parts = [f"✓ {agent_name}"]
    if duration is not None:
        parts.append(f"{duration:.1f}s")
    if artifacts:
        parts.append(f"→ {', '.join(str(a) for a in artifacts[:3])}")
    _console.print(Text("  " + "  ".join(parts), style=f"bold {_TEAL}"))


def step_error(agent_name: str, error: str) -> None:
    sarcasm = "Turns out something went wrong. Remarkable."
    body = f"[bold {_CRIMSON}]{agent_name} failed[/bold {_CRIMSON}]\n\n{error}\n\n[{_GREY}]{sarcasm}[/{_GREY}]"
    _console.print(Panel(body, title="[bold]ERROR[/bold]", border_style=_CRIMSON, expand=False))


def run_summary(steps: list[dict[str, Any]]) -> None:
    if not steps:
        return
    table = Table(
        title="Run Summary",
        title_style=f"bold {_TEAL}",
        border_style=_GREY,
        show_header=True,
        header_style=f"bold {_BLUE}",
        expand=False,
    )
    table.add_column("Agent", style=_BLUE, no_wrap=True)
    table.add_column("Status", justify="center")
    table.add_column("Duration", justify="right", style=_GREY)
    table.add_column("Artifacts", style=_GREY)

    for step in steps:
        agent = str(step.get("agent_name") or step.get("agent") or "")
        status = str(step.get("status") or "").lower()
        duration = step.get("duration")
        artifacts = step.get("artifacts") or []

        if status in ("ok", "success", "completed", "done"):
            status_cell = Text("✓", style=f"bold {_TEAL}")
        elif status in ("failed", "error"):
            status_cell = Text("✗", style=f"bold {_CRIMSON}")
        elif status in ("skipped",):
            status_cell = Text("—", style=_GREY)
        else:
            status_cell = Text(status or "?", style=_AMBER)

        dur_str = f"{float(duration):.1f}s" if duration is not None else ""
        art_str = ", ".join(str(a) for a in (artifacts or [])[:3]) if artifacts else ""

        table.add_row(agent, status_cell, dur_str, art_str)

    _console.print(table)


def gateway_started(base_url: str) -> None:
    text = Text()
    text.append("✓ Gateway started  ", style=f"bold {_TEAL}")
    text.append(base_url, style=f"underline {_BLUE}")
    _console.print(text)


def gateway_already_running(base_url: str) -> None:
    _console.print(
        Text(f"  Gateway already running at {base_url} — nothing to do.", style=_AMBER)
    )


def gateway_stopped(port: int, count: int) -> None:
    _console.print(
        Text(f"✓ Gateway stopped on port {port} ({count} listener(s) terminated).", style=f"bold {_TEAL}")
    )


def gateway_not_running(base_url: str) -> None:
    _console.print(
        Text(f"  Gateway is not running at {base_url}.", style=_AMBER)
    )


def gateway_status(running: bool, base_url: str, pid: int | None, uptime_seconds: float | None) -> None:
    if running:
        parts = [f"✓ running  {base_url}"]
        if pid:
            parts.append(f"  pid={pid}")
        if uptime_seconds is not None:
            m, s = divmod(int(uptime_seconds), 60)
            h, m = divmod(m, 60)
            if h:
                uptime_str = f"{h}h{m:02d}m{s:02d}s"
            elif m:
                uptime_str = f"{m}m{s:02d}s"
            else:
                uptime_str = f"{s}s"
            parts.append(f"  uptime={uptime_str}")
        _console.print(Text("  ".join(parts), style=f"bold {_TEAL}"))
    else:
        _console.print(Text(f"  stopped  {base_url}", style=_AMBER))


def error_panel(message: str, sarcasm: str = "") -> None:
    sarcasm = sarcasm or "Unfortunate."
    body = f"{message}\n\n[{_GREY}]{sarcasm}[/{_GREY}]"
    _console.print(Panel(body, title="[bold]ERROR[/bold]", border_style=_CRIMSON, expand=False))


def info(message: str) -> None:
    _console.print(Text(f"  {message}", style=_GREY))


def ok(message: str) -> None:
    _console.print(Text(f"✓ {message}", style=f"bold {_TEAL}"))


def warn(message: str) -> None:
    _console.print(Text(f"  {message}", style=_AMBER))


def rule(title: str = "", style: str = _AMBER) -> None:
    _console.rule(f"[bold {style}]{title}[/bold {style}]" if title else "")


def print_text(text: str, style: str = "default") -> None:
    _console.print(text, style=style)


def print_status(message: str, style: str = _GREY) -> None:
    _err_console.print(Text(f"  {message}", style=style))


def print_final_output(output: str) -> None:
    if not str(output or "").strip():
        return
    _console.print()
    _console.print(Panel(
        Text(output.strip(), style="white"),
        title="[bold #00C9A7]Run Output[/bold #00C9A7]",
        border_style=_TEAL,
        padding=(1, 2),
    ))


def make_spinner(description: str = "Working...") -> Progress:
    return Progress(
        SpinnerColumn(style=_TEAL),
        TextColumn("[progress.description]{task.description}", style=_GREY),
        TimeElapsedColumn(),
        console=_console,
        transient=True,
    )
