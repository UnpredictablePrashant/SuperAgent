"""Dependency Manager Agent.

Installs all project packages, validates lockfiles, and resolves
version conflicts using the project blueprint.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.privileged_control import (
    append_privileged_audit_event,
    build_privileged_policy,
    ensure_command_allowed,
)
from tasks.utils import OUTPUT_DIR, llm, log_task_update, write_text_file


AGENT_METADATA = {
    "dependency_manager_agent": {
        "description": (
            "Installs project dependencies, validates lockfiles, "
            "and resolves package version conflicts."
        ),
        "skills": ["package management", "dependency resolution", "npm", "pip"],
        "input_keys": [
            "blueprint_json", "blueprint_dependencies", "blueprint_tech_stack", "project_root",
        ],
        "output_keys": ["dep_manager_status", "dep_manager_install_log", "dep_manager_summary"],
        "requirements": [],
    },
}


def _run_command(command: list[str], cwd: str, timeout: int = 180) -> tuple[bool, str, str]:
    """Run a shell command and return (success, stdout, stderr)."""
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


def _detect_package_manager(tech_stack: dict, project_root: Path) -> list[str]:
    """Determine which package managers to use."""
    managers: list[str] = []
    pm = str(tech_stack.get("package_manager", "")).lower()
    language = str(tech_stack.get("language", "")).lower()

    if "pip" in pm or "python" in language:
        managers.append("pip")
    if "npm" in pm or "typescript" in language or "javascript" in language:
        # Check for yarn/pnpm lockfiles
        if (project_root / "pnpm-lock.yaml").exists():
            managers.append("pnpm")
        elif (project_root / "yarn.lock").exists():
            managers.append("yarn")
        else:
            managers.append("npm")
    if not managers:
        managers.append("pip" if "python" in language else "npm")
    return managers


def _install_python_deps(project_root: Path, policy: dict) -> tuple[bool, str]:
    """Install Python dependencies."""
    req_file = project_root / "requirements.txt"
    if not req_file.exists():
        # Try pyproject.toml with pip install -e .
        if (project_root / "pyproject.toml").exists():
            cmd = ["pip", "install", "-e", "."]
        else:
            return True, "No Python dependency file found. Skipped."
    else:
        cmd = ["pip", "install", "-r", "requirements.txt"]

    command_str = " ".join(cmd)
    try:
        ensure_command_allowed(command_str, str(project_root), policy)
    except Exception as exc:
        return False, f"Blocked by policy: {exc}"

    ok, stdout, stderr = _run_command(cmd, str(project_root), timeout=300)
    output = stdout or stderr
    return ok, output


def _install_node_deps(project_root: Path, manager: str, policy: dict) -> tuple[bool, str]:
    """Install Node.js dependencies."""
    # Find the directory with package.json
    pkg_dirs = []
    if (project_root / "package.json").exists():
        pkg_dirs.append(project_root)
    if (project_root / "frontend" / "package.json").exists():
        pkg_dirs.append(project_root / "frontend")
    if (project_root / "backend" / "package.json").exists():
        pkg_dirs.append(project_root / "backend")

    if not pkg_dirs:
        return True, "No package.json found. Skipped."

    results: list[str] = []
    all_ok = True

    for pkg_dir in pkg_dirs:
        cmd = [manager, "install"]
        command_str = " ".join(cmd)
        try:
            ensure_command_allowed(command_str, str(pkg_dir), policy)
        except Exception as exc:
            results.append(f"[{pkg_dir.name}] Blocked: {exc}")
            all_ok = False
            continue

        ok, stdout, stderr = _run_command(cmd, str(pkg_dir), timeout=300)
        label = pkg_dir.name if pkg_dir != project_root else "root"
        if ok:
            results.append(f"[{label}] Installed successfully.")
        else:
            results.append(f"[{label}] Failed: {stderr or stdout}")
            all_ok = False

    return all_ok, "\n".join(results)


def _resolve_conflicts(error_output: str, tech_stack: dict) -> str:
    """Use LLM to diagnose and suggest fixes for install failures."""
    prompt = f"""
A package installation failed with this error output:

{error_output[:3000]}

Tech stack: {json.dumps(tech_stack, indent=2)}

Diagnose the root cause and provide:
1. What went wrong
2. Specific commands to fix it
3. Any version pins needed

Be concise and actionable.
""".strip()
    response = llm.invoke(prompt)
    return response.content if hasattr(response, "content") else str(response)


def dependency_manager_agent(state):
    """Install all project dependencies and validate."""
    active_task, task_content, _ = begin_agent_session(state, "dependency_manager_agent")
    state["dependency_manager_agent_calls"] = state.get("dependency_manager_agent_calls", 0) + 1
    call_number = state["dependency_manager_agent_calls"]

    blueprint = state.get("blueprint_json", {})
    tech_stack = state.get("blueprint_tech_stack") or blueprint.get("tech_stack", {})
    project_root = Path(state.get("project_root", "")).resolve()

    if not project_root or str(project_root) == ".":
        raise ValueError("dependency_manager_agent requires project_root in state.")

    privileged_policy = build_privileged_policy(state)
    log_task_update("Dep Manager", f"Dependency installation pass #{call_number} started.")

    managers = _detect_package_manager(tech_stack, project_root)
    install_logs: list[str] = []
    all_ok = True

    for manager in managers:
        if manager == "pip":
            ok, log = _install_python_deps(project_root, privileged_policy)
        else:
            ok, log = _install_node_deps(project_root, manager, privileged_policy)

        install_logs.append(f"=== {manager} ===\n{log}")
        if not ok:
            all_ok = False
            # Try to diagnose
            diagnosis = _resolve_conflicts(log, tech_stack)
            install_logs.append(f"=== Diagnosis ===\n{diagnosis}")
            log_task_update("Dep Manager", f"{manager} install failed. Diagnosis attached.")

    install_log = "\n\n".join(install_logs)
    summary = (
        f"Dependency installation {'succeeded' if all_ok else 'had failures'}.\n"
        f"  Package managers: {', '.join(managers)}\n"
        f"  Status: {'all installed' if all_ok else 'see logs for failures'}"
    )

    state["dep_manager_status"] = "completed" if all_ok else "failed"
    state["dep_manager_install_log"] = install_log
    state["dep_manager_summary"] = summary
    state["draft_response"] = summary + "\n\n" + install_log

    append_privileged_audit_event(
        state,
        actor="dependency_manager_agent",
        action="dependency_install",
        status="completed" if all_ok else "partial_failure",
        detail={"managers": managers, "success": all_ok},
    )
    write_text_file(f"dep_manager_output_{call_number}.txt", summary + "\n\n" + install_log)
    log_task_update("Dep Manager", "Dependency installation complete.", summary)

    state = publish_agent_output(
        state,
        "dependency_manager_agent",
        summary,
        f"dep_manager_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent"],
    )
    return state
