"""Security Scanner Agent.

Runs dependency/security scans (npm audit, pip check/pip-audit) and reports findings.
"""

import shutil
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
    "security_scanner_agent": {
        "description": "Runs dependency and security scans and reports findings.",
        "skills": ["security", "dependency audit", "npm audit", "pip check"],
        "input_keys": ["project_root", "blueprint_tech_stack", "blueprint_json"],
        "output_keys": ["security_scan_status", "security_scan_summary", "security_scan_results"],
        "requirements": [],
    },
}


_IGNORE_DIRS = {
    "node_modules",
    ".git",
    ".venv",
    "venv",
    ".pytest_cache",
    "__pycache__",
    "dist",
    "build",
    ".next",
}


def _should_skip_path(path: Path) -> bool:
    return any(part in _IGNORE_DIRS for part in path.parts)


def _discover_node_package_dirs(project_root: Path, max_dirs: int = 25) -> list[Path]:
    found: list[Path] = []
    for pkg_path in project_root.rglob("package.json"):
        if _should_skip_path(pkg_path):
            continue
        found.append(pkg_path.parent)
        if len(found) >= max_dirs:
            break
    return sorted({p.resolve() for p in found}, key=lambda p: str(p))


def _discover_python_dirs(project_root: Path, max_dirs: int = 10) -> list[Path]:
    found: set[Path] = set()
    for req in project_root.rglob("requirements.txt"):
        if _should_skip_path(req):
            continue
        found.add(req.parent.resolve())
        if len(found) >= max_dirs:
            break
    return sorted(found, key=lambda p: str(p))


def _select_node_manager(pkg_dir: Path) -> str:
    if (pkg_dir / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (pkg_dir / "yarn.lock").exists():
        return "yarn"
    return "npm"


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


def security_scanner_agent(state: dict) -> dict:
    active_task, task_content, _ = begin_agent_session(state, "security_scanner_agent")
    state["security_scanner_calls"] = state.get("security_scanner_calls", 0) + 1
    call_number = state["security_scanner_calls"]

    project_root = Path(state.get("project_root", "")).resolve()
    if not project_root or str(project_root) == ".":
        raise ValueError("security_scanner_agent requires project_root in state.")

    privileged_policy = build_privileged_policy(state)
    log_task_update("Security", f"Security scan pass #{call_number} started.")

    results: list[str] = []
    all_ok = True

    # Node audits
    pkg_dirs = _discover_node_package_dirs(project_root)
    for pkg_dir in pkg_dirs:
        manager = _select_node_manager(pkg_dir)
        if manager == "npm":
            cmd = ["npm", "audit", "--audit-level=high"]
        elif manager == "pnpm":
            cmd = ["pnpm", "audit"]
        else:
            cmd = ["yarn", "audit", "--level", "high"]

        command_str = " ".join(cmd)
        try:
            ensure_command_allowed(command_str, str(pkg_dir), privileged_policy)
        except Exception as exc:
            results.append(f"[node:{pkg_dir.name}] Blocked: {exc}")
            all_ok = False
            continue

        ok, stdout, stderr = _run_command(cmd, str(pkg_dir), timeout=240)
        results.append(f"[node:{pkg_dir.name}] {stdout or stderr}")
        if not ok:
            all_ok = False

    # Python checks
    py_dirs = _discover_python_dirs(project_root)
    pip_audit = shutil.which("pip-audit")
    for py_dir in py_dirs:
        cmd = ["python", "-m", "pip", "check"]
        command_str = " ".join(cmd)
        try:
            ensure_command_allowed(command_str, str(py_dir), privileged_policy)
        except Exception as exc:
            results.append(f"[python:{py_dir.name}] Blocked: {exc}")
            all_ok = False
            continue

        ok, stdout, stderr = _run_command(cmd, str(py_dir), timeout=240)
        results.append(f"[python:{py_dir.name}] {stdout or stderr}")
        if not ok:
            all_ok = False

        if pip_audit:
            audit_cmd = ["pip-audit"]
            command_str = " ".join(audit_cmd)
            try:
                ensure_command_allowed(command_str, str(py_dir), privileged_policy)
            except Exception as exc:
                results.append(f"[python:{py_dir.name}] pip-audit blocked: {exc}")
                all_ok = False
            else:
                ok, stdout, stderr = _run_command(audit_cmd, str(py_dir), timeout=240)
                results.append(f"[python:{py_dir.name}] {stdout or stderr}")
                if not ok:
                    all_ok = False
        else:
            results.append("[python] pip-audit not installed; skipped vulnerability scan.")

    status = "passed" if all_ok else "failed"
    summary = f"Security scan completed. Status: {status}."

    state["security_scan_status"] = status
    state["security_scan_summary"] = summary
    state["security_scan_results"] = results
    state["draft_response"] = summary + "\n" + "\n".join(results)

    append_privileged_audit_event(
        state,
        actor="security_scanner_agent",
        action="security_scan",
        status=status,
        detail={"node_dirs": len(pkg_dirs), "python_dirs": len(py_dirs)},
    )
    write_text_file(f"security_scan_output_{call_number}.txt", summary + "\n" + "\n".join(results))
    log_task_update("Security", summary)

    state = publish_agent_output(
        state,
        "security_scanner_agent",
        summary,
        f"security_scan_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent"],
    )
    return state
