"""Test Agent.

Generates tests for the project and runs them with retries.
"""

import json
import os
import subprocess
from pathlib import Path

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.privileged_control import (
    append_privileged_audit_event,
    build_privileged_policy,
    ensure_command_allowed,
    path_allowed,
)
from tasks.utils import OUTPUT_DIR, llm, log_file_action, log_task_update, normalize_llm_text, write_text_file


AGENT_METADATA = {
    "test_agent": {
        "description": "Generates and runs unit/integration tests for the project.",
        "skills": ["testing", "jest", "vitest", "pytest"],
        "input_keys": [
            "blueprint_json", "blueprint_tech_stack", "blueprint_api_design", "project_root",
        ],
        "output_keys": ["test_agent_status", "test_agent_summary", "test_agent_results"],
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


def _strip_code_fences(text: str) -> str:
    stripped = normalize_llm_text(text).strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _generate_file(description: str, context: str, error_note: str = "") -> str:
    prompt = f"""
Generate production-ready test code for the following:

{description}

Project context:
{context}

Prior test failures or errors (if any):
{error_note or 'none'}

Return ONLY the complete file content. No explanation, no markdown fences.
""".strip()
    response = llm.invoke(prompt)
    raw = normalize_llm_text(response.content if hasattr(response, "content") else response)
    return _strip_code_fences(raw).strip() + "\n"


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
    if len(found) < max_dirs:
        for pyproject in project_root.rglob("pyproject.toml"):
            if _should_skip_path(pyproject):
                continue
            found.add(pyproject.parent.resolve())
            if len(found) >= max_dirs:
                break
    return sorted(found, key=lambda p: str(p))


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    log_file_action("wrote", str(path))


def _pick_node_package_dir(pkg_dirs: list[Path]) -> Path | None:
    for pkg_dir in pkg_dirs:
        pkg = _read_json(pkg_dir / "package.json")
        deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        for marker in ("express", "fastify", "koa"):
            if marker in deps:
                return pkg_dir
    return pkg_dirs[0] if pkg_dirs else None


def _select_node_manager(pkg_dir: Path) -> str:
    if (pkg_dir / "pnpm-lock.yaml").exists():
        return "pnpm"
    if (pkg_dir / "yarn.lock").exists():
        return "yarn"
    if (pkg_dir / "bun.lockb").exists():
        return "bun"
    pkg = _read_json(pkg_dir / "package.json")
    package_manager = str(pkg.get("packageManager", "")).lower()
    if package_manager.startswith("pnpm"):
        return "pnpm"
    if package_manager.startswith("yarn"):
        return "yarn"
    if package_manager.startswith("bun"):
        return "bun"
    return "npm"


def _ensure_express_testability(entry_path: Path) -> None:
    if not entry_path.exists():
        return
    try:
        content = entry_path.read_text(encoding="utf-8")
    except Exception:
        return

    updated = False
    if "export { app }" not in content and "export default app" not in content and "module.exports" not in content:
        content += "\nexport { app };\n"
        updated = True

    if "app.listen" in content and "NODE_ENV" not in content:
        content = content.replace(
            "app.listen(",
            "if (process.env.NODE_ENV !== \"test\") {\n  app.listen(",
        )
        if "});" in content:
            content = content.replace("});", "});\n}\n", 1)
        else:
            content += "\n}\n"
        updated = True

    if updated:
        entry_path.write_text(content, encoding="utf-8")
        log_file_action("wrote", str(entry_path))


def _run_command(command: list[str], cwd: str, timeout: int = 180, env: dict | None = None) -> tuple[bool, str, str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
            check=False,
            env=env,
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return False, "", f"Command not found: {command[0]}"
    except subprocess.TimeoutExpired:
        return False, "", f"Command timed out after {timeout}s"
    except Exception as exc:
        return False, "", str(exc)


def _write_project_file(root: Path, relative_path: str, content: str, policy: dict, *, overwrite: bool = True) -> tuple[str, bool]:
    target = root / relative_path
    if not path_allowed(str(target), policy.get("allowed_paths", [])):
        raise PermissionError(f"Write blocked: {target} outside allowed scope.")
    target.parent.mkdir(parents=True, exist_ok=True)
    if not overwrite and target.exists():
        try:
            if target.read_text(encoding="utf-8").strip():
                return str(target), False
        except Exception:
            return str(target), False
    target.write_text(content, encoding="utf-8")
    log_file_action("wrote", str(target))
    return str(target), True


def test_agent(state: dict) -> dict:
    active_task, task_content, _ = begin_agent_session(state, "test_agent")
    state["test_agent_calls"] = state.get("test_agent_calls", 0) + 1
    call_number = state["test_agent_calls"]

    blueprint = state.get("blueprint_json", {})
    tech_stack = state.get("blueprint_tech_stack") or blueprint.get("tech_stack", {})
    api_design = state.get("blueprint_api_design") or blueprint.get("api_design", {})
    project_root = Path(state.get("project_root", "")).resolve()

    if not project_root or str(project_root) == ".":
        raise ValueError("test_agent requires project_root in state.")

    privileged_policy = build_privileged_policy(state)
    log_task_update("Test", f"Test generation pass #{call_number} started.")

    language = str(tech_stack.get("language", "")).lower()
    framework = str(tech_stack.get("framework", "")).lower()
    preserve_existing = bool(state.get("scaffold_template_used", False))
    max_attempts = int(state.get("test_agent_max_attempts", 2) or 2)

    created_files: list[str] = []
    results: list[str] = []

    context = json.dumps({
        "tech_stack": tech_stack,
        "api_design": api_design,
    }, indent=2, ensure_ascii=False)

    install_deps = bool(state.get("test_agent_install_deps", True))
    force_install = bool(state.get("test_agent_force_install", False))

    # Node/TypeScript tests
    if "typescript" in language or "javascript" in language or "express" in framework:
        pkg_dirs = _discover_node_package_dirs(project_root)
        pkg_dir = _pick_node_package_dir(pkg_dirs)
        if pkg_dir:
            pkg_json_path = pkg_dir / "package.json"
            pkg = _read_json(pkg_json_path)
            scripts = pkg.get("scripts", {}) if isinstance(pkg.get("scripts"), dict) else {}
            dev_deps = pkg.get("devDependencies", {}) if isinstance(pkg.get("devDependencies"), dict) else {}
            deps = pkg.get("dependencies", {}) if isinstance(pkg.get("dependencies"), dict) else {}
            changed = False

            test_framework = "vitest" if "vitest" in dev_deps else "jest" if "jest" in dev_deps else "vitest"
            if test_framework == "vitest" and "vitest" not in dev_deps:
                dev_deps["vitest"] = "^1.6.0"
                changed = True
            if "supertest" not in dev_deps and "supertest" not in deps:
                dev_deps["supertest"] = "^7.0.0"
                changed = True
            if "@types/supertest" not in dev_deps and "typescript" in language:
                dev_deps["@types/supertest"] = "^2.0.16"
                changed = True

            if "test" not in scripts:
                scripts["test"] = "vitest" if test_framework == "vitest" else "jest"
                changed = True

            pkg["scripts"] = scripts
            pkg["devDependencies"] = dev_deps
            _write_json(pkg_json_path, pkg)

            if install_deps and (force_install or changed or not (pkg_dir / "node_modules").exists()):
                manager = _select_node_manager(pkg_dir)
                install_cmd = [manager, "install"] if manager != "npm" else ["npm", "install"]
                command_str = " ".join(install_cmd)
                try:
                    ensure_command_allowed(command_str, str(pkg_dir), privileged_policy)
                    ok, stdout, stderr = _run_command(install_cmd, str(pkg_dir), timeout=600)
                    results.append(f"[node install] {stdout or stderr}")
                    if not ok:
                        results.append("[node install] failed")
                except Exception as exc:
                    results.append(f"[node install] Blocked: {exc}")

            # Ensure app export for supertest
            entry = None
            for name in ("src/index.ts", "src/index.js", "src/server.ts", "src/server.js", "src/app.ts", "src/app.js"):
                candidate = pkg_dir / name
                if candidate.exists():
                    entry = candidate
                    break
            if entry:
                _ensure_express_testability(entry)

            tests_dir = pkg_dir / "tests"
            tests_dir.mkdir(parents=True, exist_ok=True)
            test_path = tests_dir / "health.test.ts"

            error_note = ""
            for attempt in range(1, max_attempts + 1):
                test_content = _generate_file(
                    f"Write {test_framework} tests using supertest for the API health endpoint. "
                    f"Import the Express app from '{entry.name if entry else 'src/index.ts'}' and verify GET /api/health returns 200.",
                    context,
                    error_note,
                )
                path, written = _write_project_file(
                    project_root,
                    str(test_path.relative_to(project_root)),
                    test_content,
                    privileged_policy,
                    overwrite=True,
                )
                if written:
                    created_files.append(path)

                cmd = ["npm", "test"]
                if test_framework == "vitest":
                    cmd += ["--", "--run"]
                elif test_framework == "jest":
                    cmd += ["--", "--runInBand"]

                command_str = " ".join(cmd)
                try:
                    ensure_command_allowed(command_str, str(pkg_dir), privileged_policy)
                except Exception as exc:
                    results.append(f"[node] Blocked: {exc}")
                    break

                env = dict(os.environ)
                env["NODE_ENV"] = "test"
                ok, stdout, stderr = _run_command(cmd, str(pkg_dir), timeout=240, env=env)
                results.append(f"[node attempt {attempt}] {stdout or stderr}")
                if ok:
                    break
                error_note = stderr or stdout or "test run failed"
        else:
            results.append("[node] No package.json found; skipped Node tests.")

    # Python tests
    if "python" in language or "fastapi" in framework:
        py_dirs = _discover_python_dirs(project_root)
        py_dir = py_dirs[0] if py_dirs else project_root
        requirements = py_dir / "requirements.txt"
        requirements_changed = False
        if requirements.exists():
            deps = requirements.read_text(encoding="utf-8").splitlines()
            if not any(line.strip().startswith("pytest") for line in deps):
                deps.append("pytest>=7.4")
                requirements.write_text("\n".join(line for line in deps if line.strip()) + "\n", encoding="utf-8")
                log_file_action("wrote", str(requirements))
                requirements_changed = True

        if install_deps and requirements.exists() and (requirements_changed or force_install):
            install_cmd = ["python", "-m", "pip", "install", "-r", str(requirements)]
            command_str = " ".join(install_cmd)
            try:
                ensure_command_allowed(command_str, str(py_dir), privileged_policy)
                ok, stdout, stderr = _run_command(install_cmd, str(py_dir), timeout=600)
                results.append(f"[python install] {stdout or stderr}")
                if not ok:
                    results.append("[python install] failed")
            except Exception as exc:
                results.append(f"[python install] Blocked: {exc}")

        tests_dir = py_dir / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        test_path = tests_dir / "test_health.py"

        error_note = ""
        for attempt in range(1, max_attempts + 1):
            test_content = _generate_file(
                "Write pytest tests for FastAPI /health endpoint using TestClient. Verify status 200.",
                context,
                error_note,
            )
            path, written = _write_project_file(
                project_root,
                str(test_path.relative_to(project_root)),
                test_content,
                privileged_policy,
                overwrite=True,
            )
            if written:
                created_files.append(path)

            cmd = ["pytest", "-q"]
            command_str = " ".join(cmd)
            try:
                ensure_command_allowed(command_str, str(py_dir), privileged_policy)
            except Exception as exc:
                results.append(f"[python] Blocked: {exc}")
                break

            ok, stdout, stderr = _run_command(cmd, str(py_dir), timeout=240)
            results.append(f"[python attempt {attempt}] {stdout or stderr}")
            if ok:
                break
            error_note = stderr or stdout or "test run failed"

    passed = all("Blocked" not in line and "failed" not in line.lower() for line in results) if results else False
    status = "passed" if passed else "failed"

    summary = f"Test generation completed. Status: {status}."
    state["test_agent_status"] = status
    state["test_agent_summary"] = summary
    state["test_agent_results"] = results
    state["draft_response"] = summary + "\n" + "\n".join(results)

    append_privileged_audit_event(
        state,
        actor="test_agent",
        action="tests",
        status=status,
        detail={"file_count": len(created_files)},
    )
    write_text_file(f"test_agent_output_{call_number}.txt", summary + "\n" + "\n".join(results))
    log_task_update("Test", summary)

    state = publish_agent_output(
        state,
        "test_agent",
        summary,
        f"test_agent_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent"],
    )
    return state
