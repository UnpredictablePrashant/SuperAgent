import os
import platform
import re
import shutil
import subprocess

from kendr.execution_trace import append_execution_event, now_iso
from kendr.machine_index import machine_sync_status, run_file_index_sync, run_software_inventory_sync
from kendr.software_inventory import update_inventory_from_command_result
from kendr.workflow_contract import build_approval_request
from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.privileged_control import (
    append_privileged_audit_event,
    build_privileged_policy,
    classify_command,
    create_backup_snapshot,
    ensure_command_allowed,
    redact_sensitive_text,
)
from tasks.utils import OUTPUT_DIR, llm, log_task_update, normalize_llm_text, write_text_file


AGENT_METADATA = {
    "os_agent": {
        "description": (
            "Executes a single shell command on the host operating system. "
            "Handles OS-level operations: running programs, checking tool versions, "
            "querying system info, reading files, and one-shot installations."
        ),
        "skills": [
            "shell", "bash", "command", "terminal", "execute", "run command",
            "system", "os", "linux", "macos", "windows", "powershell",
            "subprocess", "process", "check version", "which", "whereis",
        ],
        "input_keys": ["os_command", "os_working_directory", "os_timeout", "target_os", "shell"],
        "output_keys": ["os_result", "os_success", "os_return_code", "os_shell", "os_host"],
        "category": "system",
        "intent_patterns": [
            "run command", "execute command", "run script", "shell command",
            "bash command", "terminal command", "check if installed",
            "what version", "which version", "is installed", "check version",
            "run the following", "execute the following",
        ],
    },
    "shell_plan_agent": {
        "description": (
            "Plans and executes multi-step shell automation workflows. "
            "Given a high-level goal (e.g. 'run nginx with docker', 'set up ollama with llama3', "
            "'install and configure redis'), it decomposes the goal into sequential shell steps, "
            "checks pre-conditions (is a tool installed?), installs missing dependencies, "
            "and executes each step in order with result validation. "
            "Use this agent for any task that requires more than one command or depends on "
            "the output of previous steps. Preferred over os_agent for complex setup tasks."
        ),
        "skills": [
            "install", "setup", "configure", "deploy", "start service", "run server",
            "docker", "nginx", "redis", "postgres", "mysql", "mongodb", "ollama",
            "llm local", "local llm", "pull model", "run model",
            "apt install", "brew install", "pip install", "npm install",
            "cargo install", "go install", "pipx install", "conda install",
            "docker pull", "docker run", "docker compose",
            "start nginx", "stop nginx", "restart nginx",
            "systemctl", "service", "daemon",
            "automation", "workflow", "pipeline",
            "check and install", "if not installed", "install if missing",
            "set up environment", "bootstrap", "provision",
            "run website", "run sample", "demo",
        ],
        "input_keys": ["user_query", "working_directory", "privileged_approved", "privileged_approval_note"],
        "output_keys": ["shell_plan_result", "shell_plan_steps", "shell_plan_success"],
        "category": "system",
        "intent_patterns": [
            "install docker", "setup docker", "run docker",
            "install nginx", "run nginx", "setup nginx", "start nginx",
            "install ollama", "setup ollama", "run ollama", "pull ollama",
            "install redis", "setup redis", "run redis",
            "install postgres", "setup postgres", "run postgres",
            "set up", "configure", "bootstrap",
            "run a sample", "run a demo", "run a website",
            "pull and run", "install and run", "install and configure",
            "make sure .* is installed", "install .* if not",
            "check and install", "automate", "run everything",
            "do the setup", "full setup", "end to end setup",
            "local llm", "local model", "local ai", "run llm",
            "run llama", "run mistral", "run gemma", "run phi",
        ],
    },
}


def _detect_host_os() -> str:
    system_name = platform.system().lower()
    if "windows" in system_name:
        return "windows"
    if "darwin" in system_name:
        return "macos"
    if "linux" in system_name:
        return "linux"
    return system_name or "unknown"


def _resolve_shell(target_os: str, requested_shell: str | None = None) -> tuple[str | None, list[str], str]:
    shell_candidates = []

    if requested_shell:
        shell_candidates.append(requested_shell)
    elif target_os == "windows":
        shell_candidates.extend(["powershell", "pwsh", "cmd"])
    else:
        shell_candidates.extend(["bash", "sh"])

    for candidate in shell_candidates:
        shell_path = shutil.which(candidate)
        if not shell_path and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
            shell_path = candidate
        if shell_path:
            shell_name = os.path.basename(shell_path).lower()
            if shell_name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
                return shell_path, ["-NoProfile", "-ExecutionPolicy", "Bypass", "-Command"], shell_name
            if shell_name in {"cmd", "cmd.exe"}:
                return shell_path, ["/C"], shell_name
            return shell_path, ["-lc"], shell_name

    return None, [], requested_shell or target_os


def _shell_plan_rules(host_os: str, shell_name: str) -> str:
    shell = str(shell_name or "").lower()
    if host_os == "windows" and shell in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        return (
            "- Use PowerShell command syntax only.\n"
            "- Do NOT use bash syntax like `which`, `command -v`, `||`, `&&`, subshells, `/dev/null`, or backtick-wrapped commands.\n"
            "- Prefer `Get-Command`, `Get-Process`, `Test-Path`, `Start-Process`, `Stop-Process`, `Out-Null`, and `$null` redirection.\n"
            "- Do NOT hardcode `C:\\Program Files\\...` paths unless there is no safer option.\n"
            "- If an app may need manual GUI startup or installation, emit a clear prerequisite step instead of an invalid shell trick."
        )
    if host_os == "windows" and shell in {"cmd", "cmd.exe"}:
        return (
            "- Use cmd.exe syntax only.\n"
            "- Do NOT use bash syntax, PowerShell cmdlets, or Unix paths.\n"
            "- Prefer `where`, `if exist`, `start`, `sc query`, and simple `&&` chaining only when valid for cmd.exe."
        )
    return (
        "- Use POSIX shell syntax only.\n"
        "- Prefer `command -v`, `test`, `mkdir -p`, and plain shell redirects.\n"
        "- Do NOT emit PowerShell cmdlets or Windows-only paths."
    )


def _parse_shell_plan_steps(raw: str) -> list[dict]:
    steps = []
    current: dict = {}
    for line in str(raw or "").splitlines():
        line = line.strip()
        if line.upper().startswith("STEP ") and line.upper().replace("STEP ", "").strip().isdigit():
            if current.get("command"):
                steps.append(current)
            current = {"description": "", "command": "", "optional": False, "check": ""}
        elif line.lower().startswith("description:"):
            current["description"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("command:"):
            current["command"] = line.split(":", 1)[1].strip()
        elif line.lower().startswith("optional:"):
            current["optional"] = line.split(":", 1)[1].strip().lower() in ("yes", "true", "1")
        elif line.lower().startswith("check:"):
            current["check"] = line.split(":", 1)[1].strip()
    if current.get("command"):
        steps.append(current)
    return steps


def _shell_step_issue(step: dict, host_os: str, shell_name: str) -> str:
    shell = str(shell_name or "").lower()
    command = str(step.get("command", "")).strip()
    check = str(step.get("check", "")).strip()
    joined = f"{command}\n{check}".lower()
    if host_os == "windows" and shell in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        if (command.startswith("`") and command.endswith("`")) or (check.startswith("`") and check.endswith("`")):
            return "PowerShell command wrapped in backticks."
        bad_markers = {
            "||": "PowerShell plan uses bash `||` operator.",
            "&&": "PowerShell plan uses `&&` chaining that is not safe here.",
            "/dev/null": "PowerShell plan uses Unix `/dev/null` path.",
            "command -v ": "PowerShell plan uses Unix `command -v`.",
            "which ": "PowerShell plan uses Unix `which`.",
        }
        for marker, reason in bad_markers.items():
            if marker in joined:
                return reason
    return ""


def _plan_shell_steps(goal: str, host_os: str, shell_name: str = "", known_tools: str = "") -> list[dict]:
    """Ask the LLM to decompose a goal into ordered shell steps."""
    prompt = f"""
You are a shell automation planner. The user wants to achieve this goal on a {host_os} system.
Selected shell: {shell_name or host_os}

GOAL: {goal}

Known environment hints:
{known_tools or "No extra tool inventory available."}

Break this down into the minimum ordered shell steps needed.
For each step, provide:
- A short description of what the step does
- The exact shell command to run
- Whether the step is optional (can be skipped on failure)
- A check command that can verify preconditions (use empty string if none needed)

IMPORTANT RULES:
- Use package managers appropriate for {host_os} (apt-get for Linux, brew for macOS, winget/choco/scoop for Windows only when appropriate).
- Prefer checking if tools exist before installing.
- Keep commands simple and idempotent where possible.
- For long-running processes (servers), use detached/background flags when valid.
- If an app may not exist or may need manual GUI startup, include a clear prerequisite step instead of guessing invalid commands.
- Maximum 8 steps. Combine related actions.

SHELL-SPECIFIC RULES:
{_shell_plan_rules(host_os, shell_name)}

Return EXACTLY this format, one step per block:
STEP 1
Description: <what this step does>
Command: <exact shell command>
Optional: yes|no
Check: <command to verify precondition, or empty>

STEP 2
...
"""
    response = llm.invoke(prompt)
    raw = normalize_llm_text(response.content if hasattr(response, "content") else response).strip()
    steps = _parse_shell_plan_steps(raw)

    issues = [f"Step {idx}: {issue}" for idx, step in enumerate(steps, 1) if (issue := _shell_step_issue(step, host_os, shell_name))]
    if not issues:
        return steps

    repair_prompt = f"""
Rewrite this shell plan for {host_os} using only valid syntax for shell `{shell_name or host_os}`.
Do not explain. Return only the exact step format.

GOAL: {goal}

Environment hints:
{known_tools or "No extra tool inventory available."}

Problems to fix:
{chr(10).join(issues)}

Shell rules:
{_shell_plan_rules(host_os, shell_name)}

Existing plan:
{raw}
"""
    repair = llm.invoke(repair_prompt)
    repaired_raw = normalize_llm_text(repair.content if hasattr(repair, "content") else repair).strip()
    repaired_steps = _parse_shell_plan_steps(repaired_raw)
    return repaired_steps or steps


def _build_command_from_request(user_query: str, target_os: str) -> tuple[str, str, str, int]:
    prompt = f"""
    You are the OS execution agent in a multi-agent system.

    Convert the user's request into exactly one command body for the target operating system.
    Keep the reasoning short and operational. Do not add markdown fences.
    IMPORTANT:
    - Do NOT include the shell executable prefix (no "powershell", "pwsh", "cmd", "bash", "sh").
    - Return only the command content that should run inside the selected shell.

    Target OS: {target_os}
    User request: {user_query}

    Return EXACTLY in this format:
    Thought: short execution summary
    Command: one command only
    WorkingDirectory: . or absolute path
    TimeoutSeconds: integer
    """
    response = llm.invoke(prompt)
    raw_output = normalize_llm_text(response.content if hasattr(response, "content") else response).strip()

    thought = "Generated a command from the user request."
    command = ""
    working_directory = "."
    timeout_seconds = 120

    for line in raw_output.splitlines():
        if line.lower().startswith("thought:"):
            thought = line.split(":", 1)[1].strip() or thought
        elif line.lower().startswith("command:"):
            command = line.split(":", 1)[1].strip()
        elif line.lower().startswith("workingdirectory:"):
            working_directory = line.split(":", 1)[1].strip() or "."
        elif line.lower().startswith("timeoutseconds:"):
            timeout_value = line.split(":", 1)[1].strip()
            if timeout_value.isdigit():
                timeout_seconds = int(timeout_value)

    if not command:
        raise ValueError("OS agent could not derive a command from the model output.")

    return thought, command, working_directory, timeout_seconds


def _unwrap_nested_shell_command(command: str, shell_name: str) -> str:
    cleaned = (command or "").strip()
    lower = cleaned.lower()

    if shell_name in {"powershell", "powershell.exe", "pwsh", "pwsh.exe"}:
        if lower.startswith("powershell ") or lower.startswith("powershell.exe ") or lower.startswith("pwsh ") or lower.startswith("pwsh.exe "):
            # Extract inner script after -Command "<script>" or -Command '<script>'
            match = re.search(r"-command\s+(?P<quote>['\"])(?P<script>.*)(?P=quote)\s*$", cleaned, flags=re.IGNORECASE)
            if match:
                return match.group("script")
            # Fallback: strip the leading executable and keep remaining command body
            parts = cleaned.split(maxsplit=1)
            if len(parts) == 2:
                return parts[1]

    if shell_name in {"cmd", "cmd.exe"}:
        if lower.startswith("cmd /c "):
            return cleaned[7:].strip()

    return cleaned


def _format_execution_report(
    host_os: str,
    target_os: str,
    shell_name: str,
    command: str,
    working_directory: str,
    timeout_seconds: int,
    thought: str = "",
    classification: dict | None = None,
    backup_path: str = "",
    completed: subprocess.CompletedProcess[str] | None = None,
    error_message: str | None = None,
) -> str:
    stdout = ""
    stderr = ""
    return_code = "not-run"

    if completed is not None:
        stdout = completed.stdout.strip()
        stderr = completed.stderr.strip()
        return_code = str(completed.returncode)

    lines = [
        f"Host OS: {host_os}",
        f"Target OS: {target_os}",
        f"Shell: {shell_name}",
        f"Working directory: {working_directory}",
        f"Timeout seconds: {timeout_seconds}",
        f"Thought: {thought or 'n/a'}",
        f"Command: {command}",
        f"Return code: {return_code}",
    ]
    if classification:
        lines.extend(
            [
                f"Mutating: {bool(classification.get('mutating', False))}",
                f"Destructive: {bool(classification.get('destructive', False))}",
                f"Requests root: {bool(classification.get('root_requested', False))}",
                f"Networking: {bool(classification.get('networking', False))}",
            ]
        )
    if backup_path:
        lines.append(f"Backup snapshot: {backup_path}")
    lines.extend(
        [
            "",
            "STDOUT:",
            stdout or "<empty>",
            "",
            "STDERR:",
            stderr or "<empty>",
        ]
    )

    if error_message:
        lines.extend(["", f"Error: {error_message}"])

    return "\n".join(lines)


def _publish_os_result(state: dict, report: str, call_number: int) -> dict:
    output_name = f"os_agent_output_{call_number}.txt"
    write_text_file(output_name, report)
    log_task_update("OS Agent", f"Execution report saved to {OUTPUT_DIR}/{output_name}", report)
    return publish_agent_output(
        state,
        "os_agent",
        report,
        f"os_agent_result_{call_number}",
        recipients=["orchestrator_agent", "worker_agent"],
    )


def _record_command_visibility(state: dict, command: str, working_directory: str) -> None:
    redacted = redact_sensitive_text(command)
    state["last_shell_command"] = redacted
    history = state.get("recent_shell_commands", [])
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "command": redacted,
            "working_directory": working_directory,
            "timestamp": now_iso(),
        }
    )
    state["recent_shell_commands"] = history[-40:]


def _run_machine_sync(state: dict, *, working_directory: str, scope: str) -> str:
    lines = ["Machine sync started."]
    software_result = {}
    file_result = {}

    if scope in {"machine", "software"}:
        software_result = run_software_inventory_sync(working_directory)
        state["software_inventory"] = dict(software_result.get("software", {}) or {})
        state["software_inventory_last_synced"] = str(software_result.get("software_inventory_last_synced", "") or "")
        state["software_inventory_stale"] = False
        lines.append(
            f"Software scan: installed {int(software_result.get('installed_count', 0) or 0)} tools."
        )

    if scope in {"machine", "files"}:
        roots = state.get("local_drive_paths", [])
        if not isinstance(roots, list):
            roots = []
        file_result = run_file_index_sync(
            working_directory=working_directory,
            roots=roots or [working_directory],
            max_files=int(state.get("machine_index_max_files", 250000) or 250000),
        )
        state["file_index_last_synced"] = str(file_result.get("file_index_last_synced", "") or "")
        state["indexed_files"] = int(file_result.get("scanned_files", 0) or 0)
        state["recent_file_changes_24h"] = int(
            machine_sync_status(working_directory).get("recent_changes_24h", 0) or 0
        )
        state["machine_sync_stale"] = False
        lines.append(
            "File scan: "
            f"scanned={int(file_result.get('scanned_files', 0) or 0)}, "
            f"created={int(file_result.get('created', 0) or 0)}, "
            f"modified={int(file_result.get('modified', 0) or 0)}, "
            f"deleted={int(file_result.get('deleted', 0) or 0)}, "
            f"errors={int(file_result.get('errors', 0) or 0)}."
        )

    status = machine_sync_status(working_directory)
    lines.append(f"Indexed files now: {int(status.get('indexed_files', 0) or 0)}")
    lines.append(f"Recent file changes (24h): {int(status.get('recent_changes_24h', 0) or 0)}")
    lines.append("Machine sync complete.")
    return "\n".join(lines)

def _set_shell_approval_request(
    state: dict,
    *,
    scope: str,
    command: str,
    working_directory: str,
    reason: str,
    classification: dict | None = None,
    step_label: str = "",
) -> None:
    redacted_command = redact_sensitive_text(command)
    summary = "Shell command execution requires your approval before continuing."
    if step_label:
        summary = f"{step_label} requires your approval before continuing."
    state["pending_user_question"] = (
        f"{summary}\n\nCommand:\n{redacted_command}\n\nWorking directory:\n{working_directory}"
    )
    state["pending_user_input_kind"] = "shell_approval"
    state["approval_pending_scope"] = scope
    state["approval_request"] = build_approval_request(
        scope=scope,
        title="Shell Command Approval",
        summary=summary,
        sections=[
            {"title": "Command", "items": [redacted_command]},
            {"title": "Working Directory", "items": [working_directory]},
            {"title": "Policy Block Reason", "items": [reason]},
            {
                "title": "Command Classification",
                "items": [
                    f"Mutating: {bool((classification or {}).get('mutating', False))}",
                    f"Destructive: {bool((classification or {}).get('destructive', False))}",
                    f"Root requested: {bool((classification or {}).get('root_requested', False))}",
                    f"Networking: {bool((classification or {}).get('networking', False))}",
                ],
            },
        ],
        accept_label="Approve",
        reject_label="Reject",
        suggest_label="Suggestion",
        help_text="Approve to run this command now. Reject cancels this shell action.",
        metadata={
            "command": redacted_command,
            "working_directory": working_directory,
            "approval_mode": str(state.get("privileged_approval_mode", "per_command") or "per_command"),
            "reason": reason,
        },
    )


def os_agent(state):
    active_task, task_content, _ = begin_agent_session(state, "os_agent")
    state["os_agent_calls"] = state.get("os_agent_calls", 0) + 1

    host_os = _detect_host_os()
    target_os = (state.get("target_os") or host_os).lower()
    requested_shell = state.get("shell")
    explicit_command = state.get("os_command")
    timeout_seconds = int(state.get("os_timeout", 120))
    working_directory = state.get("os_working_directory", ".")
    privileged_policy = build_privileged_policy(state)

    log_task_update(
        "OS Agent",
        f"Execution pass #{state['os_agent_calls']} started on host OS '{host_os}' targeting '{target_os}'.",
    )

    if explicit_command:
        thought = "Using the explicit command provided in state."
        command = explicit_command
    else:
        thought, command, working_directory, timeout_seconds = _build_command_from_request(
            task_content or state.get("current_objective") or state["user_query"],
            target_os,
        )

    resolved_working_directory = os.path.abspath(working_directory)
    if str(command).strip() == "__KENDR_SYNC_MACHINE__":
        sync_scope = str(state.get("machine_sync_scope", "machine") or "machine").strip().lower()
        sync_scope = sync_scope if sync_scope in {"machine", "software", "files"} else "machine"
        _record_command_visibility(state, command, resolved_working_directory)
        report = _run_machine_sync(state, working_directory=resolved_working_directory, scope=sync_scope)
        state["os_command"] = command
        state["os_shell"] = "internal"
        state["os_host"] = host_os
        state["os_target"] = target_os
        state["os_result"] = report
        state["os_success"] = True
        state["os_return_code"] = 0
        state["draft_response"] = report
        return _publish_os_result(state, report, state["os_agent_calls"])

    shell_path, shell_args, shell_name = _resolve_shell(target_os, requested_shell)
    if not shell_path:
        error_message = f"No supported shell was found for target OS '{target_os}'."
        report = _format_execution_report(
            host_os,
            target_os,
            requested_shell or "unavailable",
            command,
            working_directory,
            timeout_seconds,
            thought=thought,
            error_message=error_message,
        )
        state["os_result"] = report
        state["os_success"] = False
        state["os_return_code"] = None
        state["draft_response"] = report
        log_task_update("OS Agent", error_message, report)
        return _publish_os_result(state, report, state["os_agent_calls"])

    command = _unwrap_nested_shell_command(command, shell_name)

    classification = classify_command(command)
    _record_command_visibility(state, command, resolved_working_directory)
    try:
        ensure_command_allowed(command, resolved_working_directory, privileged_policy)
    except Exception as exc:
        reason = str(exc)
        reason_lc = reason.lower()
        # Safe fallback for read-only checks: retry once in a known allowed path.
        # This prevents deterministic loops when LLM picks a blocked cwd (e.g., drive root).
        if (
            "outside the allowed path scope" in reason_lc
            and not bool(classification.get("mutating"))
            and not bool(classification.get("destructive"))
            and not bool(classification.get("root_requested"))
        ):
            fallback_candidates: list[str] = []
            preferred = str(state.get("working_directory", "") or "").strip()
            if preferred:
                fallback_candidates.append(preferred)
            for path in privileged_policy.get("allowed_paths", []) or []:
                if str(path or "").strip():
                    fallback_candidates.append(str(path))
            for candidate in fallback_candidates:
                candidate_abs = os.path.abspath(candidate)
                if candidate_abs == resolved_working_directory:
                    continue
                try:
                    ensure_command_allowed(command, candidate_abs, privileged_policy)
                    log_task_update(
                        "OS Agent",
                        f"Working directory '{resolved_working_directory}' blocked by policy; retrying in allowed path '{candidate_abs}'.",
                    )
                    resolved_working_directory = candidate_abs
                    _record_command_visibility(state, command, resolved_working_directory)
                    reason = ""
                    break
                except Exception:
                    continue
        if not reason:
            pass
        else:
            report = _format_execution_report(
                host_os,
                target_os,
                shell_name,
                command,
                resolved_working_directory,
                timeout_seconds,
                thought=thought,
                classification=classification,
                error_message=f"policy_blocked: {reason}",
            )
            state["os_result"] = report
            state["os_success"] = False
            state["os_return_code"] = None
            state["draft_response"] = report
            state["last_error"] = f"policy_blocked: {reason}"
            append_privileged_audit_event(
                state,
                actor="os_agent",
                action="command",
                status="blocked",
                detail={
                    "command": redact_sensitive_text(command),
                    "working_directory": resolved_working_directory,
                    "reason": reason,
                },
            )
            if "approval_required" in reason:
                _set_shell_approval_request(
                    state,
                    scope="shell_command",
                    command=command,
                    working_directory=resolved_working_directory,
                    reason=reason,
                    classification=classification,
                )
            elif "outside the allowed path scope" in reason.lower():
                state["deterministic_failure"] = {
                    "agent": "os_agent",
                    "kind": "policy_blocked_outside_scope",
                    "reason": reason,
                    "working_directory": resolved_working_directory,
                }
            log_task_update("OS Agent", "Command blocked by privileged policy.", report)
            return _publish_os_result(state, report, state["os_agent_calls"])

    backup_path = ""
    if privileged_policy.get("enable_backup", True) and classification.get("mutating", False):
        try:
            backup_path = create_backup_snapshot(
                state,
                source_dir=resolved_working_directory,
                reason=f"os_command:{command}",
            )
        except Exception as exc:
            backup_path = ""
            log_task_update("OS Agent", f"Backup snapshot failed before mutating command: {exc}")

    append_privileged_audit_event(
        state,
        actor="os_agent",
        action="command",
        status="started",
        detail={
            "command": redact_sensitive_text(command),
            "working_directory": resolved_working_directory,
            "shell": shell_name,
            "classification": classification,
            "backup_path": backup_path,
        },
    )

    log_task_update("OS Agent", thought)
    log_task_update(
        "OS Agent",
        f"Running command with shell '{shell_name}' in '{resolved_working_directory}'.",
        command,
    )
    command_started_at = now_iso()
    append_execution_event(
        state,
        kind="command",
        actor="os_agent",
        status="running",
        title="Shell command started",
        detail=thought,
        command=command,
        cwd=resolved_working_directory,
        started_at=command_started_at,
        metadata={"shell": shell_name, "target_os": target_os},
        persist=True,
        active_agent="os_agent",
    )

    try:
        completed = subprocess.run(
            [shell_path, *shell_args, command],
            capture_output=True,
            text=True,
            cwd=resolved_working_directory,
            timeout=timeout_seconds,
            check=False,
        )
        report = _format_execution_report(
            host_os,
            target_os,
            shell_name,
            command,
            resolved_working_directory,
            timeout_seconds,
            thought=thought,
            classification=classification,
            backup_path=backup_path,
            completed=completed,
        )
        state["os_success"] = completed.returncode == 0
        state["os_return_code"] = completed.returncode
        append_privileged_audit_event(
            state,
            actor="os_agent",
            action="command",
            status="completed" if completed.returncode == 0 else "failed",
            detail={
                "command": redact_sensitive_text(command),
                "working_directory": resolved_working_directory,
                "return_code": completed.returncode,
                "stdout": redact_sensitive_text((completed.stdout or "")[:1200]),
                "stderr": redact_sensitive_text((completed.stderr or "")[:1200]),
                "backup_path": backup_path,
            },
        )
        append_execution_event(
            state,
            kind="command",
            actor="os_agent",
            status="completed" if completed.returncode == 0 else "failed",
            title="Shell command completed" if completed.returncode == 0 else "Shell command failed",
            detail=(completed.stderr or completed.stdout or "")[:240],
            command=command,
            cwd=resolved_working_directory,
            started_at=command_started_at,
            completed_at=now_iso(),
            exit_code=completed.returncode,
            metadata={"shell": shell_name, "target_os": target_os},
            persist=True,
            active_agent="os_agent",
        )
    except Exception as exc:
        completed = None
        report = _format_execution_report(
            host_os,
            target_os,
            shell_name,
            command,
            resolved_working_directory,
            timeout_seconds,
            thought=thought,
            classification=classification,
            backup_path=backup_path,
            error_message=str(exc),
        )
        state["os_success"] = False
        state["os_return_code"] = None
        append_privileged_audit_event(
            state,
            actor="os_agent",
            action="command",
            status="error",
            detail={
                "command": redact_sensitive_text(command),
                "working_directory": resolved_working_directory,
                "error": str(exc),
                "backup_path": backup_path,
            },
        )
        append_execution_event(
            state,
            kind="command",
            actor="os_agent",
            status="failed",
            title="Shell command errored",
            detail=str(exc),
            command=command,
            cwd=resolved_working_directory,
            started_at=command_started_at,
            completed_at=now_iso(),
            metadata={"shell": shell_name, "target_os": target_os},
            persist=True,
            active_agent="os_agent",
        )

    state["os_command"] = command
    state["os_shell"] = shell_name
    state["os_host"] = host_os
    state["os_target"] = target_os
    state["os_result"] = report
    state["draft_response"] = report
    if completed is not None:
        snapshot = update_inventory_from_command_result(
            working_directory=resolved_working_directory,
            command=command,
            stdout=completed.stdout,
            stderr=completed.stderr,
            return_code=completed.returncode,
        )
        state["software_inventory"] = dict(snapshot.get("software", {}) or {})
        state["software_inventory_last_synced"] = str(snapshot.get("last_synced_at", "") or "")
        state["software_inventory_stale"] = False

    return _publish_os_result(state, report, state["os_agent_calls"])


def _run_step(
    command: str,
    shell_path: str,
    shell_args: list,
    working_directory: str,
    timeout: int = 180,
) -> tuple[int, str, str]:
    """Run a single shell command. Returns (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            [shell_path, *shell_args, command],
            capture_output=True,
            text=True,
            cwd=working_directory,
            timeout=timeout,
            check=False,
        )
        return result.returncode, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return -1, "", f"Command timed out after {timeout}s"
    except Exception as exc:
        return -1, "", str(exc)


def _build_shell_plan_checklist(steps: list[dict]) -> list[dict]:
    checklist = []
    for idx, step in enumerate(steps, 1):
        description = str(step.get("description", f"Step {idx}")).strip() or f"Step {idx}"
        checklist.append(
            {
                "step": idx,
                "title": description,
                "description": description,
                "command": str(step.get("command", "")).strip(),
                "check_command": str(step.get("check", "")).strip(),
                "optional": bool(step.get("optional", False)),
                "status": "pending",
                "done": False,
                "detail": "",
                "stdout": "",
                "stderr": "",
                "reason": "",
                "return_code": None,
            }
        )
    return checklist


def _update_shell_plan_step(checklist: list[dict], step_number: int, **patch) -> None:
    idx = max(0, int(step_number) - 1)
    if idx >= len(checklist):
        return
    current = dict(checklist[idx])
    current.update(patch)
    status = str(current.get("status", "") or "").strip().lower()
    current["done"] = status in {"completed", "skipped"}
    checklist[idx] = current


def _shell_tool_hints(state: dict, goal: str, host_os: str) -> str:
    hints: list[str] = []
    inventory = state.get("software_inventory")
    if isinstance(inventory, dict) and inventory:
        installed = [name for name, value in inventory.items() if str(value or "").strip()]
        if installed:
            hints.append("Known installed tools from inventory: " + ", ".join(sorted(installed)[:25]))
    if host_os == "windows":
        for tool in ("docker", "git", "python", "node", "npm", "curl", "winget", "choco"):
            path = shutil.which(tool)
            if path:
                hints.append(f"{tool} available at {path}")
    query = str(goal or "").lower()
    if "docker" in query:
        hints.append("If Docker CLI exists but engine is not running, prefer a prerequisite/manual-start step over repeating pull/run failures.")
    return "\n".join(hints)


def _summarize_shell_plan_blockers(step_results: list[dict], host_os: str, shell_name: str) -> list[str]:
    notes: list[str] = []
    for item in step_results:
        reason = str(item.get("reason", "")).strip()
        stderr = str(item.get("stderr", "")).strip()
        text = f"{reason}\n{stderr}".lower()
        if not text.strip():
            continue
        if "not a valid statement separator" in text or "/dev/null" in text or "which " in text or "command -v" in text:
            note = f"Planner emitted syntax for the wrong shell ({shell_name} on {host_os})."
            if note not in notes:
                notes.append(note)
        if "cannot find the file specified" in text or "not recognized as the name of a cmdlet" in text or "get-command" in text and "not found" in text:
            note = "A required app/tool was missing or not discoverable from this machine."
            if note not in notes:
                notes.append(note)
        if "dockerdesktoplinuxengine" in text or "_ping" in text or "docker engine not responding" in text:
            note = "Docker CLI was present but Docker Engine/Desktop was not actually running."
            if note not in notes:
                notes.append(note)
        if "outside the allowed scope" in text:
            note = "A command referenced paths outside the allowed execution scope."
            if note not in notes:
                notes.append(note)
    return notes


def shell_plan_agent(state: dict) -> dict:
    """Multi-step shell automation agent. Plans a sequence of shell commands and executes them."""
    active_task, task_content, _ = begin_agent_session(state, "shell_plan_agent")

    goal = task_content or state.get("current_objective") or state.get("user_query", "")
    host_os = _detect_host_os()
    working_directory = os.path.abspath(state.get("working_directory") or state.get("os_working_directory") or ".")
    privileged_policy = build_privileged_policy(state)
    shell_path, shell_args, shell_name = _resolve_shell(host_os)

    log_task_update("Shell Plan Agent", f"Planning shell automation for: {goal}")

    if not shell_path:
        error_msg = f"No shell found on {host_os}. Cannot run shell automation."
        state["shell_plan_result"] = error_msg
        state["shell_plan_success"] = False
        state["draft_response"] = error_msg
        return publish_agent_output(
            state, "shell_plan_agent", error_msg, "shell_plan_error",
            recipients=["orchestrator_agent", "worker_agent"],
        )

    known_tools = _shell_tool_hints(state, goal, host_os)
    steps = _plan_shell_steps(goal, host_os, shell_name=shell_name, known_tools=known_tools)
    if not steps:
        error_msg = "Could not decompose the goal into shell steps. Please be more specific."
        state["shell_plan_result"] = error_msg
        state["shell_plan_success"] = False
        state["draft_response"] = error_msg
        return publish_agent_output(
            state, "shell_plan_agent", error_msg, "shell_plan_error",
            recipients=["orchestrator_agent", "worker_agent"],
        )

    log_task_update("Shell Plan Agent", f"Planned {len(steps)} step(s).")

    step_results = []
    checklist = _build_shell_plan_checklist(steps)
    state["shell_plan_steps"] = checklist
    overall_success = True

    for idx, step in enumerate(steps, 1):
        desc = step.get("description", "Step " + str(idx))
        command = step.get("command", "")
        optional = step.get("optional", False)
        check_cmd = step.get("check", "")
        _update_shell_plan_step(
            checklist,
            idx,
            status="running",
            detail=f"Working on step {idx} of {len(steps)}.",
            reason="",
            stdout="",
            stderr="",
            return_code=None,
        )
        state["shell_plan_steps"] = checklist

        log_task_update("Shell Plan Agent", f"Step {idx}/{len(steps)}: {desc}", command)

        if not command:
            step_results.append({
                "step": idx, "description": desc, "command": command,
                "skipped": True, "reason": "Empty command",
            })
            _update_shell_plan_step(
                checklist,
                idx,
                status="skipped",
                detail="Skipped because no command was generated.",
                reason="Empty command",
            )
            continue

        _record_command_visibility(state, command, working_directory)

        if check_cmd:
            chk_rc, chk_out, chk_err = _run_step(check_cmd, shell_path, shell_args, working_directory, timeout=30)
            if chk_rc == 0:
                step_results.append({
                    "step": idx, "description": desc, "command": command,
                    "check_command": check_cmd, "check_passed": True,
                    "skipped": True, "reason": "Precondition already met",
                    "check_output": chk_out,
                })
                _update_shell_plan_step(
                    checklist,
                    idx,
                    status="skipped",
                    detail=chk_out or "Already done. Skipped this step.",
                    reason="Precondition already met",
                    stdout=chk_out,
                    stderr=chk_err,
                    return_code=chk_rc,
                )
                log_task_update("Shell Plan Agent", f"Step {idx}: precondition already met, skipping.")
                continue

        try:
            ensure_command_allowed(command, working_directory, privileged_policy)
        except PermissionError as exc:
            reason = str(exc)
            if "approval_required" in reason:
                _set_shell_approval_request(
                    state,
                    scope="shell_plan_step",
                    command=command,
                    working_directory=working_directory,
                    reason=reason,
                    classification=classify_command(command),
                    step_label=f"Step {idx}/{len(steps)}: {desc}",
                )
                blocked_msg = (
                    f"Shell plan paused for approval at step {idx}/{len(steps)}.\n"
                    f"Step: {desc}\n"
                    f"Command: {redact_sensitive_text(command)}\n"
                    f"Reason: {reason}"
                )
                _update_shell_plan_step(
                    checklist,
                    idx,
                    status="awaiting_approval",
                    detail="Waiting for approval before running this command.",
                    reason=reason,
                )
                state["shell_plan_steps"] = checklist
                state["shell_plan_result"] = blocked_msg
                state["shell_plan_success"] = False
                state["draft_response"] = blocked_msg
                return publish_agent_output(
                    state,
                    "shell_plan_agent",
                    blocked_msg,
                    f"shell_plan_paused_{idx}",
                    recipients=["orchestrator_agent", "worker_agent"],
                )
            log_task_update("Shell Plan Agent", f"Step {idx} blocked by policy: {reason}")
            step_results.append({
                "step": idx, "description": desc, "command": command,
                "blocked": True, "reason": reason,
            })
            _update_shell_plan_step(
                checklist,
                idx,
                status="blocked",
                detail="Blocked by execution policy.",
                reason=reason,
            )
            if not optional:
                overall_success = False
            continue

        classification = classify_command(command)
        if privileged_policy.get("enable_backup", True) and classification.get("mutating"):
            try:
                create_backup_snapshot(state, source_dir=working_directory, reason=f"shell_plan:step{idx}")
            except Exception:
                pass

        append_privileged_audit_event(
            state, actor="shell_plan_agent", action="step",
            status="started",
            detail={"step": idx, "command": redact_sensitive_text(command), "description": desc},
        )

        rc, stdout, stderr = _run_step(command, shell_path, shell_args, working_directory)
        success = rc == 0
        snapshot = update_inventory_from_command_result(
            working_directory=working_directory,
            command=command,
            stdout=stdout,
            stderr=stderr,
            return_code=rc,
        )
        state["software_inventory"] = dict(snapshot.get("software", {}) or {})
        state["software_inventory_last_synced"] = str(snapshot.get("last_synced_at", "") or "")
        state["software_inventory_stale"] = False

        append_privileged_audit_event(
            state, actor="shell_plan_agent", action="step",
            status="completed" if success else "failed",
            detail={
                "step": idx, "command": redact_sensitive_text(command),
                "return_code": rc,
                "stdout": redact_sensitive_text(stdout[:800]),
                "stderr": redact_sensitive_text(stderr[:400]),
            },
        )

        step_results.append({
            "step": idx, "description": desc, "command": command,
            "return_code": rc, "success": success,
            "stdout": stdout, "stderr": stderr,
        })

        if success:
            _update_shell_plan_step(
                checklist,
                idx,
                status="completed",
                detail=stdout[:240] if stdout else "Command completed successfully.",
                stdout=stdout,
                stderr=stderr,
                return_code=rc,
            )
            log_task_update("Shell Plan Agent", f"Step {idx}: OK (rc=0)", stdout[:300] if stdout else "")
            if (
                privileged_policy.get("approval_mode") == "per_command"
                and privileged_policy.get("require_approvals", True)
                and not privileged_policy.get("auto_approve", False)
            ):
                privileged_policy["approved"] = False
                state["privileged_approved"] = False
        else:
            _update_shell_plan_step(
                checklist,
                idx,
                status="failed",
                detail=stderr[:240] if stderr else f"Command failed with exit code {rc}.",
                stdout=stdout,
                stderr=stderr,
                return_code=rc,
            )
            log_task_update("Shell Plan Agent", f"Step {idx}: FAILED (rc={rc})", stderr[:300] if stderr else "")
            if not optional:
                overall_success = False
        state["shell_plan_steps"] = checklist

    lines = [f"Shell Automation: {goal}", f"Host OS: {host_os}", f"Shell: {shell_name}", ""]
    lines.append(f"Executed {len(step_results)} step(s):")
    lines.append("")
    for r in step_results:
        step_num = r.get("step", "?")
        d = r.get("description", "")
        cmd = r.get("command", "")
        if r.get("skipped"):
            icon = "⏭"
            status_label = "SKIPPED — " + r.get("reason", "")
        elif r.get("blocked"):
            icon = "🚫"
            status_label = "BLOCKED — " + r.get("reason", "")
        elif r.get("success"):
            icon = "✅"
            status_label = "OK"
        else:
            icon = "❌"
            status_label = "FAILED (rc=" + str(r.get("return_code", "?")) + ")"

        lines.append(f"{icon} Step {step_num}: {d}  [{status_label}]")
        lines.append(f"   $ {cmd}")

        stdout = r.get("stdout", "")
        stderr = r.get("stderr", "")
        if stdout:
            preview = stdout[:200] + ("…" if len(stdout) > 200 else "")
            lines.append("   → " + preview.replace("\n", "\n   "))
        if stderr and not r.get("success") and not r.get("skipped"):
            preview = stderr[:200] + ("…" if len(stderr) > 200 else "")
            lines.append("   STDERR: " + preview.replace("\n", "\n   "))
        lines.append("")

    blockers = _summarize_shell_plan_blockers(step_results, host_os, shell_name)
    if blockers:
        lines.append("Observed blockers:")
        for item in blockers:
            lines.append(f"- {item}")
        lines.append("")

    overall_label = "✅ All steps completed successfully." if overall_success else "⚠ Some required steps failed."
    lines.append(overall_label)
    result_text = "\n".join(lines)

    state["shell_plan_result"] = result_text
    state["shell_plan_steps"] = checklist
    state["shell_plan_success"] = overall_success
    state["draft_response"] = result_text

    output_name = "shell_plan_result.txt"
    write_text_file(output_name, result_text)
    log_task_update("Shell Plan Agent", overall_label, result_text[:400])

    return publish_agent_output(
        state, "shell_plan_agent", result_text, "shell_plan_result",
        recipients=["orchestrator_agent", "worker_agent"],
    )
