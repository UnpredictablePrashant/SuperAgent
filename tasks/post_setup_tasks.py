"""Post-Setup Agent.

Runs safe post-setup commands (e.g., docker compose up) and reports output.
"""

import subprocess
from pathlib import Path

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.privileged_control import (
    append_privileged_audit_event,
    build_privileged_policy,
    ensure_command_allowed,
)
from tasks.utils import OUTPUT_DIR, log_task_update, write_text_file


AGENT_METADATA = {
    "post_setup_agent": {
        "description": "Runs safe post-setup commands and collects outputs.",
        "skills": ["command execution", "setup"],
        "input_keys": ["project_root"],
        "output_keys": ["post_setup_status", "post_setup_summary", "post_setup_results"],
        "requirements": [],
    },
}


def _run_command(command: list[str], cwd: str, timeout: int = 180) -> tuple[bool, str, str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
            check=False,
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return False, "", f"Command not found: {command[0]}"
    except subprocess.TimeoutExpired:
        return False, "", f"Command timed out after {timeout}s"
    except Exception as exc:
        return False, "", str(exc)


def post_setup_agent(state: dict) -> dict:
    active_task, task_content, _ = begin_agent_session(state, "post_setup_agent")
    state["post_setup_calls"] = state.get("post_setup_calls", 0) + 1
    call_number = state["post_setup_calls"]

    project_root = Path(state.get("project_root", "")).resolve()
    if not project_root or str(project_root) == ".":
        raise ValueError("post_setup_agent requires project_root in state.")

    privileged_policy = build_privileged_policy(state)
    log_task_update("Post-Setup", f"Post-setup pass #{call_number} started.")

    commands: list[list[str]] = []
    compose_path = project_root / "docker-compose.yml"
    if compose_path.exists():
        commands.append(["docker", "compose", "up", "-d"])
        commands.append(["docker-compose", "up", "-d"])

    # Allow user-provided commands
    extra_commands = state.get("post_setup_commands", [])
    if isinstance(extra_commands, list):
        for item in extra_commands:
            if isinstance(item, list) and item:
                commands.append([str(x) for x in item])

    results: list[str] = []
    all_ok = True

    for cmd in commands:
        command_str = " ".join(cmd)
        try:
            ensure_command_allowed(command_str, str(project_root), privileged_policy)
        except Exception as exc:
            results.append(f"[cmd] Blocked: {exc}")
            all_ok = False
            continue

        ok, stdout, stderr = _run_command(cmd, str(project_root), timeout=300)
        results.append(f"[cmd] {command_str}\n{stdout or stderr}")
        if ok:
            # If docker compose succeeded, skip fallback
            if cmd[:2] == ["docker", "compose"] and ["docker-compose", "up", "-d"] in commands:
                commands.remove(["docker-compose", "up", "-d"])
        else:
            all_ok = False

    status = "completed" if all_ok else "failed"
    summary = f"Post-setup commands {'succeeded' if all_ok else 'had failures'}."

    state["post_setup_status"] = status
    state["post_setup_summary"] = summary
    state["post_setup_results"] = results
    state["draft_response"] = summary + "\n" + "\n".join(results)

    append_privileged_audit_event(
        state,
        actor="post_setup_agent",
        action="post_setup",
        status=status,
        detail={"command_count": len(commands)},
    )
    write_text_file(f"post_setup_output_{call_number}.txt", summary + "\n" + "\n".join(results))
    log_task_update("Post-Setup", summary)

    state = publish_agent_output(
        state,
        "post_setup_agent",
        summary,
        f"post_setup_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent"],
    )
    return state
