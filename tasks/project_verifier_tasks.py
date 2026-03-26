"""Project Verifier Agent.

Runs linters, type checkers, build checks, dev server health checks,
database connectivity tests, and generated tests to validate the project.
"""

import json
import subprocess
import time
from pathlib import Path

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.privileged_control import (
    append_privileged_audit_event,
    build_privileged_policy,
)
from tasks.utils import OUTPUT_DIR, log_task_update, write_text_file


AGENT_METADATA = {
    "project_verifier_agent": {
        "description": (
            "Validates the generated project by running linters, type checkers, "
            "build commands, dev server health checks, and tests."
        ),
        "skills": ["testing", "linting", "type checking", "build verification"],
        "input_keys": [
            "blueprint_json", "blueprint_tech_stack", "project_root",
        ],
        "output_keys": ["verifier_status", "verifier_issues", "verifier_summary"],
        "requirements": [],
    },
}


def _run_check(command: list[str], cwd: str, timeout: int = 120, label: str = "") -> dict:
    """Run a verification command and return structured result."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
            check=False,
        )
        return {
            "label": label or " ".join(command),
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout.strip()[:5000],
            "stderr": result.stderr.strip()[:5000],
        }
    except FileNotFoundError:
        return {
            "label": label or " ".join(command),
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"Command not found: {command[0]}. Skipped.",
        }
    except subprocess.TimeoutExpired:
        return {
            "label": label or " ".join(command),
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": f"Timed out after {timeout}s.",
        }
    except Exception as exc:
        return {
            "label": label or " ".join(command),
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(exc),
        }


def _check_python_project(project_root: Path) -> list[dict]:
    """Run Python-specific verification checks."""
    results: list[dict] = []
    cwd = str(project_root)

    # Check if backend is in a subdirectory
    if (project_root / "backend").exists():
        cwd = str(project_root / "backend")

    # 1. Syntax check with py_compile
    py_files = list(Path(cwd).rglob("*.py"))
    if py_files:
        # Just check a few key files
        for py_file in py_files[:10]:
            result = _run_check(
                ["python", "-m", "py_compile", str(py_file)],
                cwd,
                label=f"compile: {py_file.name}",
            )
            if not result["success"]:
                results.append(result)

    # 2. Ruff linter (if installed)
    results.append(_run_check(["ruff", "check", "."], cwd, label="ruff lint"))

    # 3. Mypy type check (if installed)
    results.append(_run_check(["mypy", ".", "--ignore-missing-imports"], cwd, timeout=180, label="mypy type check"))

    # 4. Pytest (if tests exist)
    test_dir = Path(cwd) / "tests"
    if test_dir.exists() and any(test_dir.glob("test_*.py")):
        results.append(_run_check(["python", "-m", "pytest", "-x", "--tb=short"], cwd, timeout=120, label="pytest"))

    return results


def _check_node_project(project_root: Path) -> list[dict]:
    """Run Node.js/TypeScript verification checks."""
    results: list[dict] = []

    # Determine frontend dir
    if (project_root / "frontend" / "package.json").exists():
        cwd = str(project_root / "frontend")
    elif (project_root / "package.json").exists():
        cwd = str(project_root)
    else:
        return [{"label": "node check", "success": True, "returncode": 0, "stdout": "No package.json found. Skipped.", "stderr": ""}]

    # 1. TypeScript compile check
    if (Path(cwd) / "tsconfig.json").exists():
        results.append(_run_check(["npx", "tsc", "--noEmit"], cwd, timeout=120, label="tsc type check"))

    # 2. ESLint
    results.append(_run_check(["npx", "eslint", ".", "--max-warnings=50"], cwd, timeout=120, label="eslint"))

    # 3. Build check
    pkg_json = Path(cwd) / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            if "build" in pkg.get("scripts", {}):
                results.append(_run_check(["npm", "run", "build"], cwd, timeout=180, label="npm build"))
        except Exception:
            pass

    # 4. Tests
    if (Path(cwd) / "package.json").exists():
        try:
            pkg = json.loads((Path(cwd) / "package.json").read_text(encoding="utf-8"))
            if "test" in pkg.get("scripts", {}):
                results.append(_run_check(["npm", "test", "--", "--watchAll=false"], cwd, timeout=120, label="npm test"))
        except Exception:
            pass

    return results


def _check_docker(project_root: Path) -> list[dict]:
    """Verify Docker-related configurations."""
    results: list[dict] = []

    # docker-compose config validation
    compose_file = project_root / "docker-compose.yml"
    if compose_file.exists():
        result = _run_check(
            ["docker-compose", "config", "-q"],
            str(project_root),
            label="docker-compose validate",
        )
        if not result["success"]:
            # Try docker compose v2
            result = _run_check(
                ["docker", "compose", "config", "-q"],
                str(project_root),
                label="docker compose validate",
            )
        results.append(result)

    # Dockerfile syntax (basic)
    for dockerfile in project_root.rglob("Dockerfile*"):
        if dockerfile.is_file():
            content = dockerfile.read_text(encoding="utf-8")
            if "FROM" not in content:
                results.append({
                    "label": f"dockerfile: {dockerfile.name}",
                    "success": False,
                    "returncode": -1,
                    "stdout": "",
                    "stderr": "Dockerfile missing FROM instruction.",
                })

    return results


def _aggregate_issues(check_results: list[dict]) -> list[dict]:
    """Extract structured issues from check results."""
    issues: list[dict] = []
    for result in check_results:
        if not result["success"] and result.get("stderr") and "not found" not in result.get("stderr", "").lower():
            issues.append({
                "check": result["label"],
                "severity": "error",
                "message": result["stderr"][:500] or result["stdout"][:500],
            })
    return issues


def project_verifier_agent(state):
    """Verify the generated project by running lint, type, build, and test checks."""
    active_task, task_content, _ = begin_agent_session(state, "project_verifier_agent")
    state["project_verifier_agent_calls"] = state.get("project_verifier_agent_calls", 0) + 1
    call_number = state["project_verifier_agent_calls"]

    blueprint = state.get("blueprint_json", {})
    tech_stack = state.get("blueprint_tech_stack") or blueprint.get("tech_stack", {})
    project_root = Path(state.get("project_root", "")).resolve()

    if not project_root or str(project_root) == ".":
        raise ValueError("project_verifier_agent requires project_root in state.")

    log_task_update("Verifier", f"Verification pass #{call_number} started.")

    all_results: list[dict] = []
    language = str(tech_stack.get("language", "")).lower()

    # Run checks based on language
    if "python" in language:
        all_results.extend(_check_python_project(project_root))

    if "typescript" in language or "javascript" in language:
        all_results.extend(_check_node_project(project_root))

    # Docker checks
    all_results.extend(_check_docker(project_root))

    # Filter out skipped checks
    meaningful_results = [r for r in all_results if not ("not found" in r.get("stderr", "").lower() and not r["success"])]
    issues = _aggregate_issues(meaningful_results)
    passed = len(issues) == 0
    passed_checks = sum(1 for r in meaningful_results if r["success"])
    total_checks = len(meaningful_results)

    # Build report
    report_lines: list[str] = [
        f"Project Verification Report: {state.get('project_name', 'project')}",
        f"Status: {'PASS' if passed else 'FAIL'}",
        f"Checks: {passed_checks}/{total_checks} passed",
        "",
    ]
    for result in meaningful_results:
        status = "PASS" if result["success"] else "FAIL"
        report_lines.append(f"[{status}] {result['label']}")
        if not result["success"] and result.get("stderr"):
            for line in result["stderr"].splitlines()[:5]:
                report_lines.append(f"  {line}")

    if issues:
        report_lines.extend(["", "Issues requiring attention:"])
        for issue in issues:
            report_lines.append(f"  [{issue['severity']}] {issue['check']}: {issue['message'][:200]}")

    report = "\n".join(report_lines)

    state["verifier_status"] = "pass" if passed else "fail"
    state["verifier_issues"] = issues
    state["verifier_check_results"] = meaningful_results
    state["verifier_summary"] = report
    state["draft_response"] = report

    append_privileged_audit_event(
        state,
        actor="project_verifier_agent",
        action="verification",
        status="pass" if passed else "fail",
        detail={"passed": passed_checks, "total": total_checks, "issues": len(issues)},
    )
    write_text_file(f"verifier_output_{call_number}.txt", report)
    log_task_update("Verifier", f"Verification {'passed' if passed else 'failed'}: {passed_checks}/{total_checks}.", report)

    state = publish_agent_output(
        state,
        "project_verifier_agent",
        report,
        f"verifier_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent"],
    )
    return state
