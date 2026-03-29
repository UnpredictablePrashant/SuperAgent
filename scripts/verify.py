#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parent.parent
PYTHON = sys.executable
COMPILE_TARGETS = [
    "app.py",
    "gateway_server.py",
    "setup_ui.py",
    "kendr",
    "tasks",
    "mcp_servers",
    "tests",
]
UNIT_TEST_MODULES = [
    "tests.test_local_drive_agent",
    "tests.test_long_document_planning",
    "tests.test_monitoring_store",
    "tests.test_os_agent",
    "tests.test_planning_tasks",
    "tests.test_privileged_control",
    "tests.test_recovery",
    "tests.test_security_policy",
    "tests.test_setup_cli_config",
    "tests.test_setup_registry",
    "tests.test_superrag_store",
    "tests.test_plugin_sdk",
]
SMOKE_TEST_MODULES = [
    "tests.test_cli",
    "tests.test_cli_entrypoint",
    "tests.test_gateway_surface",
    "tests.test_imports",
    "tests.test_registry",
    "tests.test_runtime_routing",
    "tests.test_superrag_smoke",
]
INTEGRATION_TEST_MODULES: list[str] = []
DEFAULT_PHASES = ["compile", "unit", "smoke", "docs"]
CI_PHASES = ["compile", "unit", "smoke", "docs", "docker"]
MARKDOWN_LINK_RE = re.compile(r"(?<!!)\[[^\]]+\]\(([^)]+)\)")
HTML_ATTR_RE = re.compile(r"""\b(?:href|src|srcset)\s*=\s*["']([^"']+)["']""", re.IGNORECASE)
HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*$", re.MULTILINE)


def _env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("OPENAI_API_KEY", "test-openai-key")
    env["PYTHONPATH"] = str(ROOT) if not env.get("PYTHONPATH") else f"{ROOT}{os.pathsep}{env['PYTHONPATH']}"
    return env


def _run(command: list[str], *, label: str) -> None:
    print(f"[verify] {label}")
    subprocess.run(command, cwd=ROOT, env=_env(), check=True)


def _run_compile() -> None:
    _run([PYTHON, "-m", "compileall", *COMPILE_TARGETS], label="compile")


def _run_unittest(modules: list[str], *, label: str) -> None:
    if not modules:
        print(f"[verify] {label}: no tests configured")
        return
    _run([PYTHON, "-m", "unittest", "-v", *modules], label=label)


def _slugify_heading(text: str) -> str:
    value = text.strip().lower()
    value = re.sub(r"[^\w\s-]", "", value)
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-{2,}", "-", value)
    return value.strip("-")


def _heading_anchors(path: Path, cache: dict[Path, set[str]]) -> set[str]:
    if path not in cache:
        text = path.read_text(encoding="utf-8")
        cache[path] = {_slugify_heading(match.group(1)) for match in HEADING_RE.finditer(text)}
    return cache[path]


def _split_link_target(raw_target: str) -> tuple[str, str]:
    target = raw_target.strip().strip("<>").split(maxsplit=1)[0]
    if "#" in target:
        path_part, anchor = target.split("#", 1)
        return path_part, anchor
    return target, ""


def _iter_doc_targets(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    targets = [match.group(1).strip() for match in MARKDOWN_LINK_RE.finditer(text)]
    for match in HTML_ATTR_RE.finditer(text):
        value = match.group(1).strip()
        if "srcset" in match.group(0).lower():
            for item in value.split(","):
                candidate = item.strip().split()[0]
                if candidate:
                    targets.append(candidate)
            continue
        targets.append(value)
    return targets


def _is_external_target(target: str) -> bool:
    if not target:
        return True
    if target.startswith(("mailto:", "data:")):
        return True
    parts = urlsplit(target)
    return parts.scheme in {"http", "https"}


def _validate_docs() -> None:
    print("[verify] docs")
    markdown_files = [ROOT / "README.md", ROOT / "SampleTasks.md", *sorted((ROOT / "docs").glob("*.md"))]
    anchors_cache: dict[Path, set[str]] = {}
    errors: list[str] = []

    for doc_path in markdown_files:
        for target in _iter_doc_targets(doc_path):
            if _is_external_target(target):
                continue
            link_path, anchor = _split_link_target(target)
            resolved = doc_path if not link_path else (doc_path.parent / link_path).resolve()
            if not resolved.exists():
                errors.append(f"{doc_path.relative_to(ROOT)} -> missing target: {target}")
                continue
            if anchor and resolved.suffix.lower() == ".md":
                anchors = _heading_anchors(resolved, anchors_cache)
                if anchor not in anchors:
                    errors.append(f"{doc_path.relative_to(ROOT)} -> missing anchor: {target}")

    if errors:
        for item in errors:
            print(f"[verify] docs error: {item}")
        raise SystemExit(1)


def _ensure_bootstrap_for_docker() -> None:
    env_path = ROOT / ".env"
    if env_path.exists():
        return
    _run([PYTHON, "scripts/bootstrap_local_state.py"], label="bootstrap for docker")


def _docker_compose_command() -> list[str] | None:
    docker = shutil.which("docker")
    if docker:
        result = subprocess.run(
            [docker, "compose", "version"],
            cwd=ROOT,
            env=_env(),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return [docker, "compose"]
    docker_compose = shutil.which("docker-compose")
    if docker_compose:
        return [docker_compose]
    return None


def _docker_engine_available(docker: str) -> bool:
    result = subprocess.run(
        [docker, "info"],
        cwd=ROOT,
        env=_env(),
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def _run_docker(strict: bool) -> None:
    compose_command = _docker_compose_command()
    docker = shutil.which("docker")
    if not compose_command or not docker:
        message = "[verify] docker: skipped because Docker Compose is not available"
        if strict:
            raise SystemExit(message)
        print(message)
        return

    _ensure_bootstrap_for_docker()
    _run([*compose_command, "config", "-q"], label="docker compose config")
    if not _docker_engine_available(docker):
        message = "[verify] docker build: skipped because the Docker engine is not running"
        if strict:
            raise SystemExit(message)
        print(message)
        return
    _run([docker, "build", "-t", "kendr-verify", "."], label="docker build")


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Kendr repository verification entrypoint.")
    parser.add_argument(
        "phases",
        nargs="*",
        help="Phases to run: compile, unit, smoke, docs, docker, integration, all, ci",
    )
    parser.add_argument(
        "--strict-docker",
        action="store_true",
        help="Fail instead of skipping when Docker Compose is unavailable.",
    )
    return parser.parse_args(argv)


def _resolve_phases(phases: list[str]) -> list[str]:
    requested = phases or DEFAULT_PHASES
    resolved: list[str] = []
    for phase in requested:
        if phase == "all":
            resolved.extend(DEFAULT_PHASES)
        elif phase == "ci":
            resolved.extend(CI_PHASES)
        else:
            resolved.append(phase)

    allowed = {"compile", "unit", "smoke", "docs", "docker", "integration"}
    unknown = [phase for phase in resolved if phase not in allowed]
    if unknown:
        raise SystemExit(f"Unknown verification phase(s): {', '.join(unknown)}")

    deduped: list[str] = []
    for phase in resolved:
        if phase not in deduped:
            deduped.append(phase)
    return deduped


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    phases = _resolve_phases(args.phases)

    phase_handlers = {
        "compile": _run_compile,
        "unit": lambda: _run_unittest(UNIT_TEST_MODULES, label="unit tests"),
        "smoke": lambda: _run_unittest(SMOKE_TEST_MODULES, label="smoke tests"),
        "docs": _validate_docs,
        "docker": lambda: _run_docker(args.strict_docker),
        "integration": lambda: _run_unittest(INTEGRATION_TEST_MODULES, label="integration tests"),
    }

    for phase in phases:
        phase_handlers[phase]()

    print(f"[verify] ok: {', '.join(phases)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
