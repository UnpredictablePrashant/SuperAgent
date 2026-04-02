"""Testing Agent Suite.

Five distinct agents:
  - api_test_agent       : given OpenAPI spec URL or file, generates Pytest/Jest test suite
  - unit_test_agent      : given source file(s), generates unit tests with edge cases
  - test_runner_agent    : runs existing test suite, parses output, returns A2A artifact
  - test_fix_agent       : reads failures, patches sources, re-runs to confirm fix
  - regression_test_agent: writes a targeted regression test for a bug description

Each agent returns a structured result dict AND publishes an A2A artifact with:
  - JSON report  (<label>_report.json)
  - Markdown summary (<label>_summary.md)

All five agents are accessible via `kendr test` sub-commands and via natural-language
intent routing in `kendr run`.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.a2a_protocol import append_artifact, ensure_a2a_state, make_artifact
from tasks.utils import OUTPUT_DIR, llm, log_task_update, normalize_llm_text, write_text_file

AGENT_METADATA = {
    "api_test_agent": {
        "description": "Generates a Pytest or Jest/Supertest test suite from an OpenAPI spec (URL or file).",
        "skills": ["api testing", "openapi", "pytest", "supertest"],
        "input_keys": [
            "test_openapi_source",
            "test_output_dir",
            "test_language",
            "test_base_url",
        ],
        "output_keys": ["test_suite_path", "test_report", "test_summary"],
        "requirements": ["openai_api_key"],
        "display_name": "API Test Generator",
        "category": "testing",
        "intent_patterns": ["generate api tests", "test this api", "openapi test suite", "write api tests"],
        "active_when": [],
        "config_hint": "",
    },
    "unit_test_agent": {
        "description": "Generates unit tests with edge cases for one or more source files.",
        "skills": ["unit testing", "pytest", "jest", "vitest", "mocks"],
        "input_keys": [
            "test_source_files",
            "test_output_dir",
            "test_language",
            "test_instructions",
        ],
        "output_keys": ["test_suite_path", "test_report", "test_summary"],
        "requirements": ["openai_api_key"],
        "display_name": "Unit Test Generator",
        "category": "testing",
        "intent_patterns": ["write unit tests", "generate unit tests", "add tests for", "create test cases"],
        "active_when": [],
        "config_hint": "",
    },
    "test_runner_agent": {
        "description": "Runs an existing test suite (auto-detects pytest/jest/vitest) and returns a structured pass/fail report.",
        "skills": ["test execution", "pytest", "jest", "vitest", "junit"],
        "input_keys": [
            "test_working_directory",
            "test_runner_command",
            "test_timeout",
        ],
        "output_keys": ["test_passed", "test_report", "test_summary"],
        "requirements": [],
        "display_name": "Test Runner",
        "category": "testing",
        "intent_patterns": ["run tests", "execute test suite", "run pytest", "run jest"],
        "active_when": [],
        "config_hint": "",
    },
    "regression_test_agent": {
        "description": "Writes a targeted regression test for a bug description.",
        "skills": ["regression testing", "bug reproduction", "pytest", "jest"],
        "input_keys": [
            "test_bug_description",
            "test_working_directory",
            "test_language",
            "test_context_files",
        ],
        "output_keys": ["test_suite_path", "test_report", "test_summary"],
        "requirements": ["openai_api_key"],
    },
    "test_fix_agent": {
        "description": "Reads test failures, patches the source or test files, and re-runs to confirm the fix.",
        "skills": ["test repair", "error diagnosis", "patch generation"],
        "input_keys": [
            "test_working_directory",
            "test_runner_command",
            "test_fix_max_iterations",
            "test_context_files",
        ],
        "output_keys": ["test_passed", "test_report", "test_summary", "test_patches_applied"],
        "requirements": ["openai_api_key"],
    },
}

_IGNORE_DIRS = {"node_modules", ".git", ".venv", "venv", "__pycache__", ".pytest_cache", "dist", "build", ".next"}


def _strip_fences(text: str) -> str:
    s = normalize_llm_text(text).strip()
    if s.startswith("```") and s.endswith("```"):
        lines = s.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
    return s


def _llm_call(prompt: str) -> str:
    response = llm.invoke(prompt)
    raw = normalize_llm_text(response.content if hasattr(response, "content") else response)
    return normalize_llm_text(raw).strip()


def _run_cmd(
    cmd: list[str],
    cwd: str,
    timeout: int = 300,
    env: dict | None = None,
) -> tuple[bool, str, str]:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
            check=False,
            env=env,
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except FileNotFoundError:
        return False, "", f"Command not found: {cmd[0]}"
    except subprocess.TimeoutExpired:
        return False, "", f"Command timed out after {timeout}s"
    except Exception as exc:
        return False, "", str(exc)


def _fetch_openapi(source: str) -> dict:
    """Fetch OpenAPI spec from URL or file path. Returns parsed dict."""
    source = str(source or "").strip()
    if not source:
        raise ValueError("test_openapi_source is required.")

    if source.startswith("http://") or source.startswith("https://"):
        from urllib.request import urlopen
        with urlopen(source, timeout=30) as resp:
            raw = resp.read().decode("utf-8")
    else:
        raw = Path(source).read_text(encoding="utf-8")

    try:
        return json.loads(raw)
    except Exception:
        try:
            import yaml
            return yaml.safe_load(raw)
        except Exception:
            return {"raw_text": raw[:8000]}


def _detect_test_runner(cwd: str) -> tuple[list[str], str]:
    """Auto-detect the test runner and return (command, framework)."""
    root = Path(cwd)

    pkg_json = root / "package.json"
    if pkg_json.exists():
        try:
            pkg = json.loads(pkg_json.read_text(encoding="utf-8"))
            scripts = pkg.get("scripts", {})
            dev_deps = pkg.get("devDependencies", {}) or {}
            deps = pkg.get("dependencies", {}) or {}
            all_deps = {**dev_deps, **deps}

            manager = "npm"
            if (root / "pnpm-lock.yaml").exists():
                manager = "pnpm"
            elif (root / "yarn.lock").exists():
                manager = "yarn"

            if "vitest" in all_deps:
                return [manager, "run", "test", "--", "--run"], "vitest"
            if "jest" in all_deps:
                return [manager, "run", "test", "--", "--runInBand"], "jest"
            if "test" in scripts:
                return [manager, "run", "test"], "npm"
        except Exception:
            pass

    if (root / "pytest.ini").exists() or (root / "pyproject.toml").exists() or (root / "setup.cfg").exists():
        return ["python", "-m", "pytest", "-q", "--tb=short"], "pytest"

    for f in root.rglob("test_*.py"):
        if not any(p in _IGNORE_DIRS for p in f.parts):
            return ["python", "-m", "pytest", "-q", "--tb=short"], "pytest"

    for f in root.rglob("*.test.ts"):
        if not any(p in _IGNORE_DIRS for p in f.parts):
            pkg_json2 = root / "package.json"
            manager = "npm"
            if (root / "pnpm-lock.yaml").exists():
                manager = "pnpm"
            return [manager, "run", "test"], "npm"

    return ["python", "-m", "pytest", "-q", "--tb=short"], "pytest"


def _parse_pytest_output(stdout: str, stderr: str) -> dict:
    """Parse pytest -q or --tb=short output into structured report."""
    combined = stdout + "\n" + stderr
    passed = failed = error = skipped = 0

    summary_match = re.search(
        r"(\d+)\s+passed(?:,\s*(\d+)\s+(?:warnings?|error|failed|skipped))*", combined
    )
    if summary_match:
        passed = int(summary_match.group(1) or 0)

    for pat, key in [
        (r"(\d+) failed", "failed"),
        (r"(\d+) error", "error"),
        (r"(\d+) skipped", "skipped"),
    ]:
        m = re.search(pat, combined)
        if m:
            if key == "failed":
                failed = int(m.group(1))
            elif key == "error":
                error = int(m.group(1))
            elif key == "skipped":
                skipped = int(m.group(1))

    failures: list[dict] = []
    fail_blocks = re.findall(r"FAILED (.+?)(?:\n|$)", combined)
    for block in fail_blocks[:10]:
        failures.append({"test": block.strip(), "message": ""})

    short_errors = re.findall(r"E\s+(.+)", combined)
    for i, err in enumerate(short_errors[:10]):
        if i < len(failures):
            failures[i]["message"] = err.strip()
        else:
            failures.append({"test": "unknown", "message": err.strip()})

    return {
        "framework": "pytest",
        "passed": passed,
        "failed": failed,
        "error": error,
        "skipped": skipped,
        "total": passed + failed + error + skipped,
        "failures": failures,
        "raw_output": combined[:4000],
    }


def _parse_jest_vitest_output(stdout: str, stderr: str) -> dict:
    """Parse Jest/Vitest output into structured report."""
    combined = stdout + "\n" + stderr
    passed = failed = skipped = 0

    pm = re.search(r"Tests:\s+.*?(\d+)\s+passed", combined)
    if pm:
        passed = int(pm.group(1))
    fm = re.search(r"Tests:\s+.*?(\d+)\s+failed", combined)
    if fm:
        failed = int(fm.group(1))
    sm = re.search(r"Tests:\s+.*?(\d+)\s+skipped", combined)
    if sm:
        skipped = int(sm.group(1))

    failures: list[dict] = []
    fail_blocks = re.findall(r"✕\s+(.+)", combined)
    for block in fail_blocks[:10]:
        failures.append({"test": block.strip(), "message": ""})
    err_blocks = re.findall(r"●\s+(.+)", combined)
    for block in err_blocks[:10]:
        failures.append({"test": block.strip(), "message": ""})

    framework = "vitest" if "vitest" in combined.lower() else "jest"
    return {
        "framework": framework,
        "passed": passed,
        "failed": failed,
        "error": 0,
        "skipped": skipped,
        "total": passed + failed + skipped,
        "failures": failures,
        "raw_output": combined[:4000],
    }


def _parse_junit_xml(xml_path: Path) -> dict:
    """Parse JUnit XML report file if it exists."""
    try:
        tree = ET.parse(str(xml_path))
        root = tree.getroot()
        suites = root.findall("testsuite") or [root]
        passed = failed = error = skipped = 0
        failures: list[dict] = []
        for suite in suites:
            for tc in suite.findall("testcase"):
                f = tc.find("failure")
                e = tc.find("error")
                s = tc.find("skipped")
                if f is not None:
                    failed += 1
                    failures.append({"test": tc.get("name", "?"), "message": f.text or ""})
                elif e is not None:
                    error += 1
                    failures.append({"test": tc.get("name", "?"), "message": e.text or ""})
                elif s is not None:
                    skipped += 1
                else:
                    passed += 1
        return {
            "framework": "junit",
            "passed": passed,
            "failed": failed,
            "error": error,
            "skipped": skipped,
            "total": passed + failed + error + skipped,
            "failures": failures[:10],
            "raw_output": "",
        }
    except Exception as exc:
        return {}


def _build_test_report(
    ok: bool,
    report: dict,
    run_path: str,
    artifacts: list[str],
) -> tuple[dict, str]:
    """Build final JSON report dict and markdown summary string."""
    p = report.get("passed", 0)
    f = report.get("failed", 0) + report.get("error", 0)
    s = report.get("skipped", 0)
    t = report.get("total", p + f + s)
    fw = report.get("framework", "unknown")
    status = "PASS" if ok else "FAIL"

    json_report = {
        "status": status,
        "framework": fw,
        "passed": p,
        "failed": f,
        "skipped": s,
        "total": t,
        "working_directory": run_path,
        "artifacts": artifacts,
        "failures": report.get("failures", []),
    }

    rows = []
    failures = report.get("failures", [])
    if failures:
        for failure in failures[:10]:
            rows.append(f"| `{failure.get('test', '?')}` | {failure.get('message', '')[:80]} |")

    failure_table = ""
    if rows:
        failure_table = "\n| Test | Error |\n|------|-------|\n" + "\n".join(rows)

    md = f"""## Test Results — {status}

| Metric | Count |
|--------|-------|
| Passed | {p} |
| Failed | {f} |
| Skipped | {s} |
| Total | {t} |
| Framework | {fw} |

**Working directory:** `{run_path}`
{failure_table}
"""
    return json_report, md.strip()


def _write_reports(json_report: dict, md_summary: str, label: str) -> tuple[str, str]:
    """Write JSON + markdown reports to output dir. Returns (json_path, md_path)."""
    json_name = f"{label}_report.json"
    md_name = f"{label}_summary.md"
    write_text_file(json_name, json.dumps(json_report, indent=2, ensure_ascii=False))
    write_text_file(md_name, md_summary)
    return str(Path(OUTPUT_DIR) / json_name), str(Path(OUTPUT_DIR) / md_name)


def _safe_write(target: Path, content: str) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content + "\n", encoding="utf-8")


def api_test_agent(state: dict) -> dict:
    """Generate a Pytest or Jest/Supertest test suite from an OpenAPI spec URL or file."""
    active_task, task_content, _ = begin_agent_session(state, "api_test_agent")
    state["api_test_agent_calls"] = state.get("api_test_agent_calls", 0) + 1
    call_number = state["api_test_agent_calls"]

    source = (
        state.get("test_openapi_source")
        or task_content
        or state.get("user_query", "")
    ).strip()
    output_dir = Path(state.get("test_output_dir", ".")).resolve()
    language = str(state.get("test_language", "python")).lower()
    base_url = str(state.get("test_base_url", "http://localhost:8000")).rstrip("/")

    log_task_update("API Test Agent", f"Pass #{call_number}: fetching spec from {source[:100]}")

    try:
        spec = _fetch_openapi(source)
    except Exception as exc:
        raise RuntimeError(f"api_test_agent: could not load OpenAPI spec from '{source}': {exc}") from exc

    spec_json = json.dumps(spec, indent=2, ensure_ascii=False)[:12000]
    paths_summary = ""
    if isinstance(spec.get("paths"), dict):
        for path, methods in list(spec["paths"].items())[:40]:
            for method in (methods or {}).keys():
                paths_summary += f"  {method.upper()} {path}\n"

    if "python" in language:
        framework = "pytest + httpx"
        test_file_name = "test_api_generated.py"
        prompt = f"""
You are a senior QA engineer. Generate a comprehensive Pytest test suite for the following REST API.

OpenAPI spec (truncated to 12KB):
{spec_json}

Endpoint summary:
{paths_summary or "  (see spec above)"}

Base URL: {base_url}

Requirements:
- Use pytest and httpx (AsyncClient or regular Client).
- Include at MINIMUM: one happy-path test per endpoint, one negative test (wrong input/missing auth).
- Group tests by endpoint path using pytest classes.
- Use pytest.mark.parametrize where it reduces repetition.
- Add a conftest.py fixture for the client if needed (include it in the output as --- conftest.py --- section).
- Keep code self-contained; no mocks needed unless an endpoint modifies state.
- Add clear docstrings for each test class.

Return ONLY valid Python code. No explanation, no markdown fences.
If you need a separate conftest.py, delimit it with a line: # ==== conftest.py ====
""".strip()
        raw = _llm_call(prompt)
        if "# ==== conftest.py ====" in raw:
            parts = raw.split("# ==== conftest.py ====", 1)
            main_code = _strip_fences(parts[0]).strip()
            conftest_code = _strip_fences(parts[1]).strip()
        else:
            main_code = _strip_fences(raw)
            conftest_code = ""

        tests_dir = output_dir / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        test_path = tests_dir / test_file_name
        _safe_write(test_path, main_code)
        written = [str(test_path)]
        if conftest_code:
            conftest_path = tests_dir / "conftest.py"
            _safe_write(conftest_path, conftest_code)
            written.append(str(conftest_path))

    else:
        framework = "jest + supertest"
        test_file_name = "api.generated.test.ts"
        prompt = f"""
You are a senior QA engineer. Generate a Jest + Supertest TypeScript test suite for the following REST API.

OpenAPI spec (truncated to 12KB):
{spec_json}

Endpoint summary:
{paths_summary or "  (see spec above)"}

Base URL: {base_url}

Requirements:
- Use jest and supertest.
- Include at MINIMUM: one happy-path test per endpoint, one negative test.
- Use describe/it blocks grouped by endpoint.
- Add beforeAll/afterAll if server setup is needed.
- Include proper TypeScript types.

Return ONLY valid TypeScript code. No explanation, no markdown fences.
""".strip()
        raw = _llm_call(prompt)
        tests_dir = output_dir / "__tests__"
        tests_dir.mkdir(parents=True, exist_ok=True)
        test_path = tests_dir / test_file_name
        _safe_write(test_path, _strip_fences(raw))
        written = [str(test_path)]

    suite_generated_msg = f"API test suite generated ({framework}): {len(written)} file(s) → {tests_dir}"
    log_task_update("API Test Agent", suite_generated_msg)

    run_ok: bool | None = None
    run_report: dict = {}
    run_errs: list[dict] = []

    if bool(state.get("test_run_after_generate", True)):
        log_task_update("API Test Agent", "  running generated tests against live API...")
        env = dict(os.environ)
        env["NODE_ENV"] = "test"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        if "python" in language:
            test_cmd = ["python", "-m", "pytest", "-q", "--tb=short", str(tests_dir)]
            run_cwd = str(tests_dir)
        else:
            test_cmd = ["npm", "test", "--", "--testPathPattern=__tests__"]
            run_cwd = str(output_dir)
        run_ok, stdout, stderr = _run_cmd(test_cmd, run_cwd, timeout=int(state.get("test_timeout", 120) or 120), env=env)
        if "python" in language:
            run_report = _parse_pytest_output(stdout, stderr)
        else:
            run_report = _parse_jest_vitest_output(stdout, stderr)
        run_errs = run_report.get("failures", [])[:5]
        r_pass = run_report.get("passed", 0)
        r_fail = run_report.get("failed", 0) + run_report.get("error", 0)
        log_task_update("API Test Agent", f"  run result: {r_pass} passed, {r_fail} failed")

    status = "PASS" if run_ok is True else ("FAIL" if run_ok is False else "generated")
    summary = f"API test suite {status} ({framework}): {len(written)} file(s)"

    passed_count = run_report.get("passed", 0) if run_report else 0
    failed_count = (run_report.get("failed", 0) + run_report.get("error", 0)) if run_report else 0
    skipped_count = run_report.get("skipped", 0) if run_report else 0
    total_count = run_report.get("total", passed_count + failed_count + skipped_count) if run_report else 0
    json_report = {
        "status": status,
        "framework": framework,
        "source": source,
        "base_url": base_url,
        "generated_files": written,
        "files": written,
        "passed": passed_count,
        "failed": failed_count,
        "skipped": skipped_count,
        "total": total_count,
        "duration": run_report.get("duration") if run_report else None,
        "runner": run_report.get("framework", framework) if run_report else framework,
        "agent": "api_test_agent",
        "run_result": run_report if run_report else None,
        "failures": run_errs,
    }
    run_row = f"| Run passed | {passed_count} |" if run_ok is not None else ""
    run_fail_row = f"| Run failed | {failed_count} |" if run_ok is not None else ""
    md_summary = f"""## API Test Suite — {status}

| Field | Value |
|-------|-------|
| Framework | {framework} |
| OpenAPI source | `{source[:80]}` |
| Base URL | `{base_url}` |
| Files written | {len(written)} |
{run_row}
{run_fail_row}


**Files:**
""" + "\n".join(f"- `{f}`" for f in written)

    json_path, md_path = _write_reports(json_report, md_summary, f"api_test_{call_number}")
    state["test_suite_path"] = str(tests_dir)
    state["test_report"] = json_report
    state["test_summary"] = md_summary
    state["draft_response"] = summary

    ensure_a2a_state(state)
    append_artifact(state, make_artifact(
        f"api_test_suite_{call_number}",
        "test_suite",
        md_summary,
        {"json_report": json_path, "md_summary": md_path, "files": written},
    ))
    return publish_agent_output(state, "api_test_agent", summary,
                                f"api_test_result_{call_number}",
                                recipients=["orchestrator_agent", "test_runner_agent"])


def unit_test_agent(state: dict) -> dict:
    """Generate unit tests with edge cases for one or more source files."""
    active_task, task_content, _ = begin_agent_session(state, "unit_test_agent")
    state["unit_test_agent_calls"] = state.get("unit_test_agent_calls", 0) + 1
    call_number = state["unit_test_agent_calls"]

    source_files_raw = state.get("test_source_files") or []
    if isinstance(source_files_raw, str):
        source_files_raw = [f.strip() for f in source_files_raw.split(",") if f.strip()]
    if not source_files_raw and task_content:
        source_files_raw = [task_content.strip()]
    if not source_files_raw:
        raise ValueError("unit_test_agent requires test_source_files in state.")

    output_dir = Path(state.get("test_output_dir", ".")).resolve()
    language = str(state.get("test_language", "auto")).lower()
    extra_instructions = str(state.get("test_instructions", "")).strip()

    log_task_update("Unit Test Agent", f"Pass #{call_number}: generating tests for {len(source_files_raw)} file(s)")

    written: list[str] = []
    working_dir_raw = str(state.get("test_working_directory") or state.get("project_root") or "")
    working_dir = Path(working_dir_raw).resolve() if working_dir_raw else None

    for src_path_raw in source_files_raw:
        src_path = Path(src_path_raw.strip())
        if not src_path.is_absolute():
            candidates = []
            if working_dir:
                candidates.append(working_dir / src_path)
            candidates.append(Path.cwd() / src_path)
            candidates.append(output_dir / src_path)
            resolved = next((c for c in candidates if c.exists()), None)
            if resolved:
                src_path = resolved
        if not src_path.exists():
            log_task_update("Unit Test Agent", f"Source file not found: {src_path} — skipping")
            continue

        src_code = src_path.read_text(encoding="utf-8")[:10000]
        ext = src_path.suffix.lower()
        if "python" in language or ext == ".py":
            fw = "pytest"
            test_ext = "_test.py"
            lang_hint = "Python"
        elif ext in (".ts", ".tsx"):
            fw = "vitest"
            test_ext = ".test.ts"
            lang_hint = "TypeScript"
        else:
            fw = "jest"
            test_ext = ".test.js"
            lang_hint = "JavaScript"

        extra_section = ("Additional instructions:\n" + extra_instructions) if extra_instructions else ""
        prompt = f"""
You are a senior QA engineer. Write a complete {fw} unit test file for the following {lang_hint} source file.

Source file: {src_path.name}
```
{src_code}
```

Requirements:
- Test EVERY exported function/class/method.
- Include at minimum: one happy-path test, one edge case (empty input, None, zero, boundary value), one error case per function.
- Mock external I/O (file system, network, DB) where needed.
- Use descriptive test names that read like specifications.
- Keep tests independent (no shared state between tests).
{extra_section}

Return ONLY the complete test file content. No explanation, no markdown fences.
""".strip()
        raw = _llm_call(prompt)
        test_content = _strip_fences(raw)

        stem = src_path.stem
        tests_dir = output_dir / "tests"
        tests_dir.mkdir(parents=True, exist_ok=True)
        test_file = tests_dir / f"{stem}{test_ext}"
        _safe_write(test_file, test_content)
        written.append(str(test_file))

    if not written:
        raise RuntimeError("unit_test_agent: no source files could be read — nothing generated.")

    summary = f"Unit tests generated ({fw}): {len(written)} file(s)"
    log_task_update("Unit Test Agent", summary)

    json_report = {
        "status": "generated",
        "framework": fw,
        "source_files": source_files_raw,
        "test_files": written,
    }
    md_summary = f"""## Unit Tests Generated

| Field | Value |
|-------|-------|
| Framework | {fw} |
| Source files | {len(source_files_raw)} |
| Test files written | {len(written)} |

**Generated:**
""" + "\n".join(f"- `{f}`" for f in written)

    json_path, md_path = _write_reports(json_report, md_summary, f"unit_test_{call_number}")
    state["test_suite_path"] = str(output_dir / "tests")
    state["test_report"] = json_report
    state["test_summary"] = md_summary
    state["draft_response"] = summary

    ensure_a2a_state(state)
    append_artifact(state, make_artifact(
        f"unit_test_suite_{call_number}",
        "test_suite",
        md_summary,
        {"json_report": json_path, "md_summary": md_path, "files": written},
    ))
    return publish_agent_output(state, "unit_test_agent", summary,
                                f"unit_test_result_{call_number}",
                                recipients=["orchestrator_agent", "test_runner_agent"])


def test_runner_agent(state: dict) -> dict:
    """Run existing test suite, parse output, return structured A2A artifact."""
    active_task, task_content, _ = begin_agent_session(state, "test_runner_agent")
    state["test_runner_agent_calls"] = state.get("test_runner_agent_calls", 0) + 1
    call_number = state["test_runner_agent_calls"]

    cwd_raw = (
        state.get("test_working_directory")
        or state.get("project_root")
        or task_content
        or "."
    )
    cwd = str(Path(cwd_raw).resolve())
    timeout = int(state.get("test_timeout", 300) or 300)

    custom_cmd_raw = state.get("test_runner_command")
    if custom_cmd_raw:
        if isinstance(custom_cmd_raw, str):
            import shlex
            cmd = shlex.split(custom_cmd_raw)
        else:
            cmd = list(custom_cmd_raw)
        cmd_str = " ".join(cmd).lower()
        if "pytest" in cmd_str or "py.test" in cmd_str:
            framework = "pytest"
        elif "vitest" in cmd_str:
            framework = "vitest"
        elif "jest" in cmd_str:
            framework = "jest"
        elif "mocha" in cmd_str:
            framework = "jest"
        else:
            framework = "custom"
    else:
        cmd, framework = _detect_test_runner(cwd)

    log_task_update("Test Runner Agent", f"Pass #{call_number}: running {' '.join(cmd)} in {cwd}")

    env = dict(os.environ)
    env["NODE_ENV"] = "test"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    junit_xml_path = Path(cwd) / "test-results.xml"
    if framework == "pytest" and "--junit-xml" not in " ".join(cmd):
        cmd_with_xml = cmd + [f"--junit-xml={junit_xml_path}"]
    else:
        cmd_with_xml = cmd

    ok, stdout, stderr = _run_cmd(cmd_with_xml, cwd, timeout=timeout, env=env)

    report: dict = {}
    if junit_xml_path.exists():
        report = _parse_junit_xml(junit_xml_path)

    if not report:
        if framework in ("pytest",):
            report = _parse_pytest_output(stdout, stderr)
        elif framework in ("jest", "vitest"):
            report = _parse_jest_vitest_output(stdout, stderr)
        else:
            combined = stdout + "\n" + stderr
            if re.search(r"\d+ passed", combined) or "PASSED" in combined or "::test_" in combined:
                report = _parse_pytest_output(stdout, stderr)
            else:
                report = _parse_jest_vitest_output(stdout, stderr)

    if not report.get("total") and not report.get("passed") and not report.get("failed"):
        ok_cmd, stdout2, stderr2 = _run_cmd(cmd, cwd, timeout=timeout, env=env)
        combined2 = stdout2 + "\n" + stderr2
        if framework in ("pytest",) or re.search(r"\d+ passed", combined2) or "::test_" in combined2:
            report = _parse_pytest_output(stdout2, stderr2)
        else:
            report = _parse_jest_vitest_output(stdout2, stderr2)
        ok = ok_cmd

    json_report, md_summary = _build_test_report(ok, report, cwd, [])
    json_path, md_path = _write_reports(json_report, md_summary, f"test_run_{call_number}")

    status = "PASS" if ok else "FAIL"
    summary = (
        f"Test run {status}: {report.get('passed', 0)} passed, "
        f"{report.get('failed', 0) + report.get('error', 0)} failed, "
        f"{report.get('skipped', 0)} skipped"
    )
    log_task_update("Test Runner Agent", summary)

    state["test_passed"] = ok
    state["test_report"] = json_report
    state["test_summary"] = md_summary
    state["draft_response"] = summary

    ensure_a2a_state(state)
    append_artifact(state, make_artifact(
        f"test_run_result_{call_number}",
        "test_report",
        md_summary,
        {"json_report": json_path, "md_summary": md_path,
         "passed": ok, "passed_count": report.get("passed", 0),
         "failed_count": report.get("failed", 0) + report.get("error", 0)},
    ))
    return publish_agent_output(state, "test_runner_agent", summary,
                                f"test_runner_result_{call_number}",
                                recipients=["orchestrator_agent", "test_fix_agent"])


def test_fix_agent(state: dict) -> dict:
    """Read test failures, patch source/test files, re-run to confirm fix."""
    active_task, task_content, _ = begin_agent_session(state, "test_fix_agent")
    state["test_fix_agent_calls"] = state.get("test_fix_agent_calls", 0) + 1
    call_number = state["test_fix_agent_calls"]

    cwd_raw = (
        state.get("test_working_directory")
        or state.get("project_root")
        or task_content
        or "."
    )
    cwd = str(Path(cwd_raw).resolve())
    max_iters = int(state.get("test_fix_max_iterations", 3) or 3)
    timeout = int(state.get("test_timeout", 300) or 300)
    context_files = state.get("test_context_files", [])
    if isinstance(context_files, str):
        context_files = [f.strip() for f in context_files.split(",") if f.strip()]

    custom_cmd_raw = state.get("test_runner_command")
    if custom_cmd_raw:
        if isinstance(custom_cmd_raw, str):
            import shlex
            cmd = shlex.split(custom_cmd_raw)
        else:
            cmd = list(custom_cmd_raw)
    else:
        cmd, _ = _detect_test_runner(cwd)

    log_task_update("Test Fix Agent", f"Pass #{call_number}: fix loop (max {max_iters} iterations) in {cwd}")

    env = dict(os.environ)
    env["NODE_ENV"] = "test"
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    context_blob = ""
    if context_files:
        parts = []
        for cf in context_files[:10]:
            cf_path = Path(cf.strip())
            if not cf_path.is_absolute():
                cf_path = Path(cwd) / cf_path
            if cf_path.exists():
                code = cf_path.read_text(encoding="utf-8")[:3000]
                parts.append(f"File: {cf_path}\n---\n{code}\n---")
        context_blob = "\n\n".join(parts)

    patches_applied: list[dict] = []
    ok = False
    report: dict = {}
    final_stdout = ""
    final_stderr = ""

    for iteration in range(1, max_iters + 1):
        ok, stdout, stderr = _run_cmd(cmd, cwd, timeout=timeout, env=env)
        final_stdout = stdout
        final_stderr = stderr
        report = _parse_pytest_output(stdout, stderr) if "pytest" in " ".join(cmd) else _parse_jest_vitest_output(stdout, stderr)

        if ok:
            log_task_update("Test Fix Agent", f"  iter {iteration}: all tests pass")
            break

        combined_output = (stderr + "\n" + stdout).strip()[:5000]
        if not combined_output:
            break

        log_task_update("Test Fix Agent", f"  iter {iteration}: {report.get('failed', 0)} failure(s) — asking LLM to fix")

        cmd_str = " ".join(cmd)
        context_section = ("Additional context:\n" + context_blob) if context_blob else ""
        fix_prompt = f"""
You are a senior QA engineer. The test suite is failing. Fix the source code or test files to make tests pass.

Working directory: {cwd}

Test command: {cmd_str}

Test output:
{combined_output}

{context_section}

Rules:
- Prefer fixing the source code (not the tests) unless the test itself is clearly wrong.
- Do NOT add skips or comment out failing tests.
- Return a JSON array of patches:
[{{"file": "relative/path/to/file.py", "content": "full corrected file content"}}]
Return ONLY valid JSON. No markdown fences, no explanation.
""".strip()

        try:
            raw = _llm_call(fix_prompt)
            raw_clean = _strip_fences(raw)
            if not raw_clean.strip().startswith("["):
                m = re.search(r"\[.*\]", raw_clean, re.DOTALL)
                raw_clean = m.group(0) if m else "[]"
            patch_list = json.loads(raw_clean)
        except Exception as exc:
            log_task_update("Test Fix Agent", f"  iter {iteration}: patch parse error: {exc}")
            break

        if not isinstance(patch_list, list) or not patch_list:
            log_task_update("Test Fix Agent", f"  iter {iteration}: no patches returned")
            break

        patched_count = 0
        for patch in patch_list:
            file_rel = str(patch.get("file", "")).strip()
            content = str(patch.get("content", "")).strip()
            if not file_rel or not content:
                continue
            target = (Path(cwd) / file_rel).resolve()
            try:
                target.relative_to(Path(cwd).resolve())
            except ValueError:
                log_task_update("Test Fix Agent", f"  iter {iteration}: rejected path traversal: {file_rel}")
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content + "\n", encoding="utf-8")
            patches_applied.append({"iteration": iteration, "file": file_rel})
            log_task_update("Test Fix Agent", f"  iter {iteration}: patched {file_rel}")
            patched_count += 1

        if patched_count > 0 and iteration == max_iters:
            log_task_update("Test Fix Agent", f"  iter {iteration}: final patch applied — running verification run")
            ok, stdout, stderr = _run_cmd(cmd, cwd, timeout=timeout, env=env)
            report = _parse_pytest_output(stdout, stderr) if "pytest" in " ".join(cmd) else _parse_jest_vitest_output(stdout, stderr)
            log_task_update("Test Fix Agent", f"  verification: {'PASS' if ok else 'FAIL'} — {report.get('passed', 0)} passed, {report.get('failed', 0)} failed")

    json_report, md_summary = _build_test_report(ok, report, cwd, [])
    json_report["patches_applied"] = patches_applied
    json_path, md_path = _write_reports(json_report, md_summary, f"test_fix_{call_number}")

    status = "PASS" if ok else "FAIL"
    summary = (
        f"Test fix loop {status}: {len(patches_applied)} patch(es) applied, "
        f"{report.get('passed', 0)} passed, "
        f"{report.get('failed', 0) + report.get('error', 0)} failed"
    )
    log_task_update("Test Fix Agent", summary)

    state["test_passed"] = ok
    state["test_report"] = json_report
    state["test_summary"] = md_summary
    state["test_patches_applied"] = patches_applied
    state["draft_response"] = summary

    ensure_a2a_state(state)
    append_artifact(state, make_artifact(
        f"test_fix_result_{call_number}",
        "test_report",
        md_summary,
        {"json_report": json_path, "md_summary": md_path,
         "passed": ok, "patches_applied": len(patches_applied)},
    ))
    return publish_agent_output(state, "test_fix_agent", summary,
                                f"test_fix_result_{call_number}",
                                recipients=["orchestrator_agent"])


def regression_test_agent(state: dict) -> dict:
    """Write a targeted regression test given a bug description."""
    active_task, task_content, _ = begin_agent_session(state, "regression_test_agent")
    state["regression_test_agent_calls"] = state.get("regression_test_agent_calls", 0) + 1
    call_number = state["regression_test_agent_calls"]

    bug_description = (
        state.get("test_bug_description")
        or task_content
        or state.get("user_query", "")
    ).strip()
    if not bug_description:
        raise ValueError("regression_test_agent requires test_bug_description in state.")

    cwd_raw = state.get("test_working_directory") or state.get("project_root") or "."
    cwd = Path(cwd_raw).resolve()
    output_dir = cwd
    language = str(state.get("test_language", "python")).lower()
    context_files = state.get("test_context_files", [])
    if isinstance(context_files, str):
        context_files = [f.strip() for f in context_files.split(",") if f.strip()]

    context_blob = ""
    if context_files:
        parts = []
        for cf in context_files[:5]:
            cf_path = Path(cf.strip())
            if not cf_path.is_absolute():
                cf_path = cwd / cf_path
            if cf_path.exists():
                code = cf_path.read_text(encoding="utf-8")[:3000]
                parts.append(f"File: {cf_path.name}\n---\n{code}\n---")
        context_blob = "\n\n".join(parts)

    if "python" in language:
        fw = "pytest"
        test_file_name = f"test_regression_{call_number}.py"
    else:
        fw = "jest"
        test_file_name = f"regression_{call_number}.test.ts"

    context_section = ("Relevant context:\n" + context_blob) if context_blob else ""
    prompt = f"""
You are a senior QA engineer. Write a targeted regression test for the following bug.

Bug description:
{bug_description}

{context_section}

Requirements:
- The test must FAIL before the bug is fixed and PASS after.
- Give the test a name that clearly describes the bug (e.g. test_login_fails_with_empty_password).
- Add a comment citing the bug description.
- Use {fw}.
- Keep the test focused and minimal.

Return ONLY the complete test file. No explanation, no markdown fences.
""".strip()

    raw = _llm_call(prompt)
    test_content = _strip_fences(raw)

    tests_dir = output_dir / "tests"
    tests_dir.mkdir(parents=True, exist_ok=True)
    test_path = tests_dir / test_file_name
    _safe_write(test_path, test_content)

    summary = f"Regression test written: {test_path}"
    log_task_update("Regression Test Agent", summary)

    json_report = {
        "status": "generated",
        "framework": fw,
        "bug_description": bug_description[:200],
        "test_file": str(test_path),
    }
    md_summary = f"""## Regression Test Generated

| Field | Value |
|-------|-------|
| Framework | {fw} |
| Test file | `{test_path}` |

**Bug:** {bug_description[:200]}
"""
    json_path, md_path = _write_reports(json_report, md_summary, f"regression_test_{call_number}")
    state["test_suite_path"] = str(test_path)
    state["test_report"] = json_report
    state["test_summary"] = md_summary
    state["draft_response"] = summary

    ensure_a2a_state(state)
    append_artifact(state, make_artifact(
        f"regression_test_{call_number}",
        "test_suite",
        md_summary,
        {"json_report": json_path, "md_summary": md_path, "file": str(test_path)},
    ))
    return publish_agent_output(state, "regression_test_agent", summary,
                                f"regression_test_result_{call_number}",
                                recipients=["orchestrator_agent", "test_runner_agent"])
