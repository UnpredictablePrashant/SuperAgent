"""Project Generation Orchestrator.

Standalone multi-agent pipeline that scaffolds a complete, runnable project
from a natural language description — no gateway required.

Pipeline (spec-aligned 16-agent DAG):
  planner → scaffolder → architect → db_agent →
  backend_coder → frontend_coder → stylist →
  reviewer → devops → error_fixer → smoke_test →
  test_agent → doc_agent → git_agent → github_agent

All pipeline stages emit MessageBus events using the ``<agent>:<action>``
convention defined in the AgentSys specification.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from typing import Any, Callable

from kendr.path_utils import application_root
from kendr.orchestration import MessageBus

_STACK_ALIASES: dict[str, str] = {
    "nextjs": "nextjs_prisma_postgres",
    "next": "nextjs_prisma_postgres",
    "nextjs-prisma": "nextjs_prisma_postgres",
    "react": "react_vite",
    "react-vite": "react_vite",
    "vite": "react_vite",
    "fastapi": "fastapi_postgres",
    "fastapi-postgres": "fastapi_postgres",
    "fastapi-react": "fastapi_react_postgres",
    "express": "express_prisma_postgres",
    "express-prisma": "express_prisma_postgres",
    "django": "django_react_postgres",
    "django-react": "django_react_postgres",
    "flutter": "flutter",
    "mern": "mern_microservices_mongodb",
    "pern": "pern_postgres",
    "static": "nextjs_static_site",
    "nextjs-static": "nextjs_static_site",
    "custom": "custom_freeform",
    "freeform": "custom_freeform",
}


def resolve_stack_name(stack: str) -> str:
    """Resolve a short stack alias or display name to the canonical template name."""
    clean = stack.strip().lower().replace(" ", "-")
    return _STACK_ALIASES.get(clean, clean) or clean


def _llm_call(prompt: str, model: str | None = None) -> str:
    """Call the configured LLM and return the text response."""
    from tasks.utils import llm, normalize_llm_text
    response = llm.invoke(prompt)
    return normalize_llm_text(response.content if hasattr(response, "content") else response)


def _strip_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            first = lines[0].lstrip("`").strip()
            if first in ("json", "python", "typescript", "javascript", "dart", "yaml", ""):
                return "\n".join(lines[1:-1]).strip()
    return stripped


def _strip_json_fences(text: str) -> str:
    return _strip_fences(text)


def _run_subprocess(
    command: list[str],
    cwd: str,
    timeout: int = 120,
) -> tuple[bool, str, str]:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=timeout,
            check=False,
        )
        return result.returncode == 0, result.stdout[:8000], result.stderr[:8000]
    except FileNotFoundError:
        return False, "", f"Command not found: {command[0]}"
    except subprocess.TimeoutExpired:
        return False, "", f"Timed out after {timeout}s"
    except Exception as exc:
        return False, "", str(exc)


def _load_stack_template(stack_name: str) -> dict | None:
    try:
        from plugin_templates.project_stacks import load_stack_template
        return load_stack_template(stack_name)
    except Exception:
        return None


def _copy_template_dir(template_dir: Path, project_root: Path) -> list[str]:
    created: list[str] = []
    for src in template_dir.rglob("*"):
        rel = src.relative_to(template_dir)
        if rel.parts and rel.parts[0].startswith(".git"):
            continue
        dest = project_root / rel
        if src.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        created.append(str(dest))
    return created


def _repo_root() -> Path:
    return application_root()


class ProjectGenerationOrchestrator:
    """Generate a complete, runnable project without requiring the gateway.

    Usage::

        orch = ProjectGenerationOrchestrator(
            description="A job board where employers post jobs and candidates apply",
            stack="nextjs",
            project_root="/home/user/projects/job-board",
            auto_approve=True,
            github_repo="my-org/job-board",
        )
        result = orch.run(progress_cb=print)

    Args:
        description:   Natural language description of the project.
        stack:         Stack alias or template name (e.g. "nextjs", "fastapi").
        project_root:  Directory where the project will be created.
        project_name:  Kebab-case project name. Auto-derived if omitted.
        auto_approve:  Skip interactive blueprint approval gate.
        skip_tests:    Skip test generation and test-run steps.
        skip_devops:   Skip Dockerfile/docker-compose generation.
        max_fix_iters: Maximum error-fixing iterations (default 3).
        github_repo:   "owner/repo" — push to GitHub after generation.
        github_token:  GitHub PAT. Falls back to GITHUB_TOKEN env var.
        progress_cb:   Optional callable(str) for progress messages.
    """

    def __init__(
        self,
        description: str,
        stack: str = "",
        project_root: str = "",
        project_name: str = "",
        auto_approve: bool = False,
        skip_tests: bool = False,
        skip_devops: bool = False,
        max_fix_iters: int = 3,
        github_repo: str = "",
        github_token: str = "",
        progress_cb: Callable[[str], None] | None = None,
    ) -> None:
        self.description = description.strip()
        self.stack = resolve_stack_name(stack) if stack else ""
        self.project_root = Path(project_root).expanduser().resolve() if project_root else Path.cwd()
        self.project_name = self._derive_name(project_name)
        self.auto_approve = auto_approve
        self.skip_tests = skip_tests
        self.skip_devops = skip_devops
        self.max_fix_iters = max_fix_iters
        self.github_repo = github_repo.strip()
        self.github_token = github_token.strip() or os.getenv("GITHUB_TOKEN", "")
        self._cb = progress_cb or (lambda msg: print(msg, flush=True))
        self._blueprint: dict = {}
        self._stack_template: dict | None = None
        # In-process event bus — all agents communicate via bus events.
        # Subscribe before run() so callers can attach monitors via bus.subscribe("*", fn).
        self._bus: MessageBus = MessageBus()

    def _log(self, msg: str, event_type: str = "progress", extra: dict | None = None) -> None:
        """Emit a progress message via the callback.

        The callback receives structured JSON-serialisable dicts so that the
        web UI can distinguish between event types (progress, file_created,
        patch_applied, run_output, reviewer_note) and render them appropriately.
        Plain-text callers (CLI) only see the ``text`` field.
        """
        payload: dict = {"type": event_type, "text": msg}
        if extra:
            payload.update(extra)
        self._cb(json.dumps(payload))

    def _safe_path(self, rel: str) -> Path | None:
        """Resolve *rel* relative to project_root and reject path-traversal escapes.

        Returns the resolved ``Path`` if safe, or ``None`` if the path escapes
        the project root (e.g. ``../secret``).  Every LLM-provided path MUST
        pass through this guard before any filesystem write.
        """
        try:
            resolved = (self.project_root / rel).resolve()
            resolved.relative_to(self.project_root.resolve())
            return resolved
        except (ValueError, Exception):
            return None

    def _derive_name(self, given: str) -> str:
        if given.strip():
            return given.strip().lower().replace(" ", "-")
        words = re.findall(r"[a-z]+", self.description.lower())[:4]
        return "-".join(words) or "my-app"

    def run(self) -> dict[str, Any]:
        """Execute the full 16-agent spec-aligned pipeline.

        Pipeline stages (following the AgentSys DAG specification):
          1.  planner     — generate project blueprint
          2.  scaffolder  — create directory tree + base files
          3.  architect   — ARCHITECTURE.md + openapi.yaml
          4.  db_agent    — database schema / migrations / seed
          5.  backend_coder — generate all backend modules
          6.  frontend_coder — generate all frontend modules (conditional)
          7.  stylist     — CSS / theme config (conditional)
          8.  reviewer    — LLM code-quality review
          9.  devops      — Dockerfile + docker-compose
          10. error_fixer — compile / type-check + LLM patch loop
          11. smoke_test  — startup crash detection
          12. test_agent  — generate test suite
          13. doc_agent   — README + API.md + CONTRIBUTING.md + DEPLOYMENT.md
          14. git_agent   — local git init + commit
          15. github_agent — create/push to GitHub repo

        Every stage emits a ``<agent>:complete`` MessageBus event so monitor
        subscribers can observe the full pipeline in real time.
        """
        start = time.time()
        _PENDING = object()
        result: dict[str, Any] = {
            "ok": _PENDING,
            "project_root": str(self.project_root),
            "project_name": self.project_name,
            "stack": self.stack,
            "files_created": [],
            "errors": [],
            "github_url": "",
        }
        try:
            self._log(f"[orchestrator] starting: {self.project_name}")
            self._log(f"[orchestrator] description: {self.description[:120]}")
            self._log(f"[orchestrator] stack: {self.stack or '(auto-detect)'}")
            self._log(f"[orchestrator] project root: {self.project_root}")

            if self.stack:
                self._stack_template = _load_stack_template(self.stack)
                if self._stack_template:
                    self._log(f"[orchestrator] loaded stack template: {self._stack_template.get('display_name', self.stack)}")
                else:
                    self._log(f"[orchestrator] no template found for '{self.stack}', using LLM-driven stack selection")

            # ── 1/15  planner ────────────────────────────────────────────────
            self._log("[1/15] planner — generating blueprint…")
            self._blueprint = self._step_blueprint()
            self._log(f"[1/15] blueprint ready: {self._blueprint.get('project_name', self.project_name)}")
            self._bus.emit("planner:complete", {
                "project_name": self._blueprint.get("project_name", self.project_name),
                "stack": self._blueprint.get("tech_stack", {}),
                "modules": len(self._blueprint.get("modules", [])),
            })

            if not self.auto_approve:
                self._blueprint = self._step_blueprint_approval(self._blueprint)

            # ── 2/15  scaffolder ─────────────────────────────────────────────
            self._log("[2/15] scaffolder — creating directory structure…")
            files_created = self._step_scaffold()
            result["files_created"].extend(files_created)
            self._log(f"[2/15] scaffold complete: {len(files_created)} files/dirs created")
            self._bus.emit("scaffolder:complete", {"files": files_created})

            # ── 3/15  architect ──────────────────────────────────────────────
            self._log("[3/15] architect — generating ARCHITECTURE.md + openapi.yaml…")
            arch_files = self._step_architect()
            result["files_created"].extend(arch_files)
            self._log(f"[3/15] architect complete: {arch_files}")
            self._bus.emit("architect:complete", {"files": arch_files})

            # ── 4/15  db_agent ───────────────────────────────────────────────
            self._log("[4/15] db_agent — generating database schema / migrations…")
            db_files = self._step_db_agent()
            result["files_created"].extend(db_files)
            self._log(f"[4/15] db_agent complete: {len(db_files)} files")
            self._bus.emit("db_agent:complete", {"files": db_files})

            # ── 5/15  backend_coder ──────────────────────────────────────────
            self._log("[5/15] backend_coder — generating backend modules…")
            backend_files = self._step_backend_coder()
            result["files_created"].extend(backend_files)
            self._log(f"[5/15] backend_coder complete: {len(backend_files)} files written")
            self._bus.emit("backend_coder:complete", {"files": backend_files})

            # ── 6/15  frontend_coder (conditional) ──────────────────────────
            if self._has_frontend():
                self._log("[6/15] frontend_coder — generating frontend modules…")
                frontend_files = self._step_frontend_coder()
                result["files_created"].extend(frontend_files)
                self._log(f"[6/15] frontend_coder complete: {len(frontend_files)} files written")
                self._bus.emit("frontend_coder:complete", {"files": frontend_files})
            else:
                self._log("[6/15] frontend_coder skipped (no frontend in stack)")
                self._bus.emit("frontend_coder:skipped", {})

            # ── 7/15  stylist (conditional) ──────────────────────────────────
            if self._has_frontend():
                self._log("[7/15] stylist — generating CSS / theme config…")
                style_files = self._step_stylist()
                result["files_created"].extend(style_files)
                self._log(f"[7/15] stylist complete: {len(style_files)} files")
                self._bus.emit("stylist:complete", {"files": style_files})
            else:
                self._log("[7/15] stylist skipped (no frontend in stack)")
                self._bus.emit("stylist:skipped", {})

            # ── 8/15  reviewer ───────────────────────────────────────────────
            self._log("[8/15] reviewer — checking generated code quality…")
            review_notes = self._step_reviewer()
            if review_notes:
                self._log(f"[8/15] reviewer notes: {review_notes[:200]}")
            else:
                self._log("[8/15] reviewer: code looks good")
            self._bus.emit("reviewer:complete", {"notes": review_notes or ""})

            # ── 9/15  devops ─────────────────────────────────────────────────
            if not self.skip_devops:
                self._log("[9/15] devops — generating Dockerfile + docker-compose…")
                devops_files = self._step_devops()
                result["files_created"].extend(devops_files)
                self._log(f"[9/15] devops complete: {len(devops_files)} files written")
                self._bus.emit("devops:complete", {"files": devops_files})
            else:
                self._log("[9/15] devops skipped")
                self._bus.emit("devops:skipped", {})

            # ── 10/15  error_fixer ────────────────────────────────────────────
            self._log("[10/15] error_fixer — compile / type-check + LLM patch loop…")
            fix_report = self._step_error_fix_loop()
            if fix_report.get("errors"):
                result["errors"].extend(fix_report["errors"])
            fix_ok = fix_report.get("ok", True)
            self._log(f"[10/15] error_fixer done: {fix_report.get('iterations', 0)} iter(s), {'pass' if fix_ok else 'some errors remain'}")
            if not fix_ok:
                result["ok"] = False

            # ── 11/15  smoke_test ─────────────────────────────────────────────
            self._log("[11/15] smoke_test — startup crash detection…")
            smoke_errs = self._step_smoke_test()
            if smoke_errs:
                result["errors"].extend(smoke_errs)
                self._log(f"[11/15] smoke_test found {len(smoke_errs)} issue(s) — patched")
            else:
                self._log("[11/15] smoke_test passed")
            self._bus.emit("smoke_test:complete", {"errors": smoke_errs})

            # ── 12/15  test_agent ─────────────────────────────────────────────
            if not self.skip_tests:
                self._log("[12/15] test_agent — generating test suite…")
                test_files = self._step_generate_tests()
                result["files_created"].extend(test_files)
                self._log(f"[12/15] test_agent complete: {len(test_files)} files")
                self._bus.emit("test_agent:complete", {"files": test_files})
            else:
                self._log("[12/15] test_agent skipped")
                self._bus.emit("test_agent:skipped", {})

            # ── 13/15  doc_agent ──────────────────────────────────────────────
            self._log("[13/15] doc_agent — writing README + API.md + CONTRIBUTING.md + DEPLOYMENT.md…")
            doc_files = self._step_doc_agent()
            result["files_created"].extend(doc_files)
            self._log(f"[13/15] doc_agent complete: {doc_files}")
            self._bus.emit("doc_agent:complete", {"files": doc_files})

            # ── 14/15  git_agent ──────────────────────────────────────────────
            self._log("[14/15] git_agent — local git init + commit…")
            committed = self._step_git_commit(f"feat: initial scaffold — {self.project_name}")
            self._log(f"[14/15] git_agent: {'committed' if committed else 'nothing to commit'}")
            self._bus.emit("git_agent:complete", {"committed": committed})

            # ── 15/15  github_agent ───────────────────────────────────────────
            if self.github_repo:
                self._log(f"[15/15] github_agent — pushing to {self.github_repo}…")
                github_url = self._step_github_push()
                result["github_url"] = github_url
                if github_url:
                    self._log(f"[15/15] github_agent: pushed to {github_url}")
                    self._bus.emit("github_agent:complete", {"url": github_url})
                else:
                    self._log("[15/15] github_agent: push skipped (no token or error)")
                    self._bus.emit("github_agent:skipped", {})
            else:
                self._log("[15/15] github_agent skipped (no --github-repo)")
                self._bus.emit("github_agent:skipped", {})

            elapsed = round(time.time() - start, 1)
            if result["ok"] is _PENDING:
                result["ok"] = True
            status_mark = "✓" if result["ok"] else "⚠"
            self._log(f"[orchestrator] done in {elapsed}s  {status_mark}  {self.project_root}")
            self._bus.emit("orchestrator:complete", {
                "ok": result["ok"],
                "elapsed": elapsed,
                "files": len(result["files_created"]),
                "errors": len(result["errors"]),
            })

            install_hint = self._install_hint()
            if install_hint:
                self._log(f"\n  Next steps:\n{textwrap.indent(install_hint, '    ')}")

        except Exception as exc:
            result["errors"].append(str(exc))
            result["ok"] = False
            self._log(f"[orchestrator] error: {exc}")

        if result["ok"] is _PENDING:
            result["ok"] = False
        return result

    def _install_hint(self) -> str:
        tech = self._blueprint.get("tech_stack", {}) if self._blueprint else {}
        lang = str(tech.get("language", "")).lower()
        pm = str(tech.get("package_manager", "")).lower()
        fw = str(tech.get("framework", "")).lower()
        lines: list[str] = []
        if lang == "dart" or fw == "flutter":
            lines = [
                "flutter pub get",
                "flutter run",
            ]
        elif "python" in lang:
            lines = [
                "pip install -r requirements.txt",
                "uvicorn app.main:app --reload  # or python manage.py runserver",
            ]
        elif "typescript" in lang or "javascript" in lang:
            installer = pm if pm in ("npm", "yarn", "pnpm") else "npm"
            lines = [
                f"{installer} install",
                f"{installer} run dev",
            ]
        if self._blueprint.get("docker_services"):
            lines.insert(0, "docker-compose up -d  # start supporting services")
        if not lines:
            return ""
        return "\n".join(lines)

    def _build_blueprint_prompt(self) -> str:
        stack_hint = ""
        if self._stack_template:
            ts = self._stack_template.get("tech_stack", {})
            hints = self._stack_template.get("blueprint_hints", {})
            stack_hint = f"""
Pre-selected stack:
{json.dumps(ts, indent=2)}

Architecture hints:
{json.dumps(hints, indent=2)}
""".strip()
        elif self.stack:
            stack_hint = f"Target stack: {self.stack}"

        return f"""
You are a senior software architect. Design a complete project blueprint as valid JSON.

Project description:
{self.description}

Project name: {self.project_name}

{stack_hint}

Return ONLY a JSON object with this exact schema:
{{
  "project_name": "kebab-case-name",
  "description": "one-sentence description",
  "tech_stack": {{
    "language": "typescript|python|dart|javascript",
    "framework": "nextjs|react|fastapi|express|django|flutter|...",
    "database": "postgresql|mongodb|sqlite|none",
    "orm": "prisma|sqlalchemy|mongoose|none",
    "css": "tailwindcss|styled-components|none",
    "package_manager": "npm|pip|pub|yarn|pnpm",
    "runtime": "nodejs|python|dart-vm|browser",
    "auth": "jwt|session|oauth|none",
    "testing": "jest|vitest|pytest|flutter_test|none"
  }},
  "directory_structure": ["list", "of", "paths/", "file.ext"],
  "modules": [
    {{
      "name": "module display name",
      "file": "relative/path/to/file.ext",
      "description": "what this module does",
      "priority": 1
    }}
  ],
  "api_design": {{
    "endpoints": [
      {{"method": "GET", "path": "/api/items", "description": "list items"}}
    ]
  }},
  "database_schema": {{
    "tables": [
      {{"name": "users", "columns": [{{"name": "id", "type": "uuid", "primary": true}}]}}
    ]
  }},
  "dependencies": {{
    "runtime": ["pkg@version"],
    "dev": ["pkg@version"]
  }},
  "env_vars": [
    {{"name": "DATABASE_URL", "description": "PostgreSQL connection string", "example_value": "postgresql://...", "required": true}}
  ],
  "docker_services": [
    {{"name": "db", "image": "postgres:16-alpine", "ports": ["5432:5432"], "environment": {{"POSTGRES_DB": "app"}}}}
  ],
  "run_command": "npm run dev",
  "install_command": "npm install"
}}

Rules:
- modules must cover all major features from the description (min 5, max 20)
- file paths must be realistic for the chosen framework
- dependencies must be real, installable packages
- env_vars must include all required secrets
- docker_services only if a database/cache/queue is needed
""".strip()

    def _step_blueprint(self) -> dict:
        prompt = self._build_blueprint_prompt()
        raw = _llm_call(prompt)
        try:
            data = json.loads(_strip_json_fences(raw))
        except Exception:
            match = re.search(r"\{[\s\S]+\}", raw)
            if match:
                data = json.loads(match.group(0))
            else:
                raise ValueError(f"Blueprint LLM did not return valid JSON. Raw: {raw[:300]}")

        if not isinstance(data, dict):
            raise ValueError("Blueprint must be a JSON object.")

        if not data.get("project_name"):
            data["project_name"] = self.project_name
        if self._stack_template:
            data.setdefault("tech_stack", {})
            for k, v in self._stack_template.get("tech_stack", {}).items():
                data["tech_stack"].setdefault(k, v)

            for dep_key in ("runtime", "dev"):
                base_deps = self._stack_template.get("base_dependencies", {}).get(dep_key, [])
                existing = data.get("dependencies", {}).get(dep_key, [])
                merged = list({d: None for d in (base_deps + existing)})
                data.setdefault("dependencies", {})[dep_key] = merged

            base_dirs = self._stack_template.get("base_directory_structure", [])
            if base_dirs:
                existing_dirs = set(data.get("directory_structure", []))
                for d in base_dirs:
                    if d not in existing_dirs:
                        data.setdefault("directory_structure", []).append(d)

            base_env_vars = self._stack_template.get("base_env_vars", [])
            if base_env_vars:
                existing_names = {e.get("name") for e in data.get("env_vars", [])}
                for ev in base_env_vars:
                    if ev.get("name") not in existing_names:
                        data.setdefault("env_vars", []).append(ev)

            base_docker = self._stack_template.get("base_docker_services", [])
            if base_docker:
                existing_svc_names = {s.get("name") for s in data.get("docker_services", [])}
                for svc in base_docker:
                    if svc.get("name") not in existing_svc_names:
                        data.setdefault("docker_services", []).append(svc)

        return data

    def _step_blueprint_approval(self, blueprint: dict) -> dict:
        if not sys.stdin.isatty():
            return blueprint
        print()
        print("=" * 72)
        print("  BLUEPRINT READY FOR REVIEW")
        print("=" * 72)
        tech = blueprint.get("tech_stack", {})
        print(f"  Stack: {tech.get('framework', '?')} + {tech.get('database', 'none')}")
        print(f"  Modules: {len(blueprint.get('modules', []))}")
        deps = blueprint.get("dependencies", {})
        print(f"  Dependencies: {len(deps.get('runtime', []))} runtime, {len(deps.get('dev', []))} dev")
        print()
        mods = blueprint.get("modules", [])
        for m in mods[:10]:
            print(f"    - {m.get('file', '?')}  ({m.get('description', '')})")
        if len(mods) > 10:
            print(f"    ... and {len(mods) - 10} more")
        print()
        ans = input("Proceed with this blueprint? [y/n]: ").strip().lower()
        if ans not in ("y", "yes"):
            print("Generation cancelled at blueprint review.")
            raise SystemExit(0)
        return blueprint

    def _step_scaffold(self) -> list[str]:
        from tasks.project_scaffold_tasks import (
            _create_directory_tree,
            _generate_gitignore,
            _generate_env_example,
            _generate_docker_compose_stub,
            _populate_frontend_starter,
        )

        root = self.project_root
        root.mkdir(parents=True, exist_ok=True)
        tech_stack = self._blueprint.get("tech_stack", {})
        raw_structure = self._blueprint.get("directory_structure", [])
        directory_structure = [
            entry for entry in raw_structure
            if self._safe_path(entry.rstrip("/")) is not None
        ]
        env_vars = self._blueprint.get("env_vars", [])
        created: list[str] = []

        stack_name = self.stack
        stack_template = _load_stack_template(stack_name) if stack_name else None
        template_dir = None
        if stack_template:
            td = stack_template.get("template_dir")
            if td:
                template_dir = _repo_root() / str(td)

        used_template = False
        if template_dir and template_dir.exists() and template_dir.is_dir():
            created.extend(_copy_template_dir(template_dir, root))
            used_template = True

        created.extend(_create_directory_tree(root, directory_structure, create_files=not used_template))

        gitignore_path = root / ".gitignore"
        if not used_template or not gitignore_path.exists():
            gitignore_path.write_text(_generate_gitignore(tech_stack), encoding="utf-8")
            created.append(str(gitignore_path))

        env_path = root / ".env.example"
        if not used_template or not env_path.exists():
            env_path.write_text(_generate_env_example(env_vars), encoding="utf-8")
            created.append(str(env_path))

        docker_services = self._blueprint.get("docker_services", [])
        if docker_services and not self.skip_devops:
            compose_path = root / "docker-compose.yml"
            if not used_template or not compose_path.exists():
                compose_path.write_text(_generate_docker_compose_stub(self._blueprint), encoding="utf-8")
                created.append(str(compose_path))

        if not used_template:
            frontend_files = _populate_frontend_starter(self._blueprint, root)
            created.extend(frontend_files)

        if self._stack_template and self._stack_template.get("name") == "flutter":
            pubspec_path = root / "pubspec.yaml"
            if not pubspec_path.exists():
                tpl = self._stack_template.get("pubspec_template", "")
                if tpl:
                    pubspec_path.write_text(
                        tpl.format(
                            project_name=self.project_name.replace("-", "_"),
                            description=self._blueprint.get("description", self.description[:80]),
                        ),
                        encoding="utf-8",
                    )
                    created.append(str(pubspec_path))

        return created

    def _stack_coder_strategy(self) -> str:
        """Return stack-specific coding instructions for the coder prompt.

        Each supported stack has an explicit coder strategy that overrides the
        generic instructions.  This implements the per-stack coder-agent concept
        inside the orchestrator without requiring separate agent classes.
        """
        tech = self._blueprint.get("tech_stack", {})
        fw = str(tech.get("framework", "")).lower()
        lang = str(tech.get("language", "")).lower()
        orm = str(tech.get("orm", "")).lower()
        auth = str(tech.get("auth", "")).lower()
        db = str(tech.get("database", "")).lower()

        strategies: dict[str, str] = {
            "nextjs": (
                "Stack: Next.js 14+ App Router with TypeScript.\n"
                "- Use Server Components by default; Client Components only when needed (use 'use client').\n"
                "- Route handlers go in app/api/<path>/route.ts (export GET/POST/etc.).\n"
                "- Use Prisma ORM with PostgreSQL. Define schema in prisma/schema.prisma.\n"
                "- Use next-auth or jose for JWT/session auth. Protect routes via middleware.ts.\n"
                "- Use Tailwind CSS for styling. No inline styles."
            ),
            "react": (
                "Stack: React + Vite + TypeScript + Tailwind.\n"
                "- Use functional components and hooks. No class components.\n"
                "- State management: React Context or Zustand (no Redux unless explicitly required).\n"
                "- API calls via fetch or axios with async/await. Wrap in custom hooks.\n"
                "- Router: react-router-dom v6 with createBrowserRouter.\n"
                "- Tailwind for all styling. Use shadcn/ui patterns where applicable."
            ),
            "fastapi": (
                "Stack: FastAPI + SQLAlchemy + PostgreSQL.\n"
                "- Use async def endpoints with asyncpg/databases or sqlalchemy[asyncio].\n"
                "- Pydantic v2 schemas for request/response validation.\n"
                "- Alembic for migrations. Define models in models.py, schemas in schemas.py.\n"
                "- JWT auth via python-jose or authlib. Dependency injection for current_user.\n"
                "- Pytest + httpx for tests."
            ),
            "express": (
                "Stack: Express.js + Prisma + PostgreSQL + TypeScript.\n"
                "- Use express Router, typed with @types/express.\n"
                "- Prisma for database access. Define schema in prisma/schema.prisma.\n"
                "- Middleware: helmet, cors, express-validator for input validation.\n"
                "- JWT auth via jsonwebtoken. Middleware for protected routes.\n"
                "- Jest or supertest for API tests."
            ),
            "django": (
                "Stack: Django REST Framework + React frontend + PostgreSQL.\n"
                "- Use class-based views (APIView / ModelViewSet).\n"
                "- Django ORM models with __str__ and Meta class.\n"
                "- DRF serializers for request/response. Use JWT via djangorestframework-simplejwt.\n"
                "- CORS via django-cors-headers. Pytest-django for tests."
            ),
            "flutter": (
                "Stack: Flutter + Dart.\n"
                "- Use StatelessWidget + StatefulWidget appropriately. Prefer Provider/Riverpod.\n"
                "- HTTP via http or dio package. Define API service classes.\n"
                "- Navigator 2.0 or go_router for routing.\n"
                "- Separate UI/logic: widgets in lib/widgets, screens in lib/screens, services in lib/services.\n"
                "- Write flutter_test widget tests."
            ),
            "mern": (
                "Stack: MongoDB + Express + React + Node.js (MERN) with TypeScript.\n"
                "- Mongoose models with TypeScript interfaces.\n"
                "- Express REST API with JWT auth (jsonwebtoken).\n"
                "- React front-end with React Query for server state.\n"
                "- Separate monorepo: packages/api and packages/web."
            ),
            "pern": (
                "Stack: PostgreSQL + Express + React + Node.js (PERN) with TypeScript.\n"
                "- pg or Prisma for database. Prisma preferred for type safety.\n"
                "- Express API with TypeScript, helmet, cors, zod for validation.\n"
                "- React frontend with React Query and React Router v6.\n"
                "- Vitest for frontend tests, Jest + supertest for backend."
            ),
        }

        if "nextjs" in fw or "next.js" in fw:
            return strategies["nextjs"]
        if "react" in fw and "next" not in fw:
            return strategies["react"]
        if "fastapi" in fw:
            return strategies["fastapi"]
        if "express" in fw:
            return strategies["express"]
        if "django" in fw:
            return strategies["django"]
        if "flutter" in fw or lang == "dart":
            return strategies["flutter"]
        if "mern" in fw:
            return strategies["mern"]
        if "pern" in fw:
            return strategies["pern"]

        generic = []
        if "python" in lang:
            generic.append("Write idiomatic Python 3.10+. Use type hints throughout.")
        if "typescript" in lang:
            generic.append("Write idiomatic TypeScript. No 'any' types.")
        if orm == "prisma":
            generic.append("Use Prisma ORM. Import from @prisma/client.")
        if orm == "sqlalchemy":
            generic.append("Use SQLAlchemy 2.x with async sessions.")
        if auth == "jwt":
            generic.append("Implement JWT auth. Include token creation and verification.")
        if "postgres" in db or "postgresql" in db:
            generic.append("Use PostgreSQL. Connection via DATABASE_URL env var.")
        return "\n".join(generic) if generic else "Write production-quality, idiomatic code."

    def _build_module_prompt(self, module: dict, context_summary: str) -> str:
        tech = self._blueprint.get("tech_stack", {})
        deps = self._blueprint.get("dependencies", {})
        api = self._blueprint.get("api_design", {})
        schema = self._blueprint.get("database_schema", {})
        stack_strategy = self._stack_coder_strategy()
        return f"""
You are a senior engineer implementing a production-quality module.

Project: {self._blueprint.get("project_name", self.project_name)}
Description: {self._blueprint.get("description", self.description)}

Stack-specific coder instructions:
{stack_strategy}

Tech stack (reference):
{json.dumps(tech, indent=2)}

Dependencies (runtime):
{json.dumps(deps.get("runtime", []), indent=2)}

API endpoints (reference):
{json.dumps(api.get("endpoints", [])[:15], indent=2)}

Database schema (reference):
{json.dumps(schema.get("tables", [])[:8], indent=2)}

Module to implement:
  File: {module.get("file", "?")}
  Description: {module.get("description", "?")}

Already implemented (do not re-implement):
{context_summary or "None yet."}

Instructions:
- Write complete, working, production-quality code.
- No placeholder or stub logic — implement the real feature.
- Use the declared dependencies; do not import packages not in the dependency list.
- Return ONLY the file content. No explanation, no markdown fences.
""".strip()

    def _step_code_modules(self) -> list[str]:
        """Generate all modules (legacy helper, delegates to _generate_modules)."""
        modules = self._blueprint.get("modules", [])
        if not modules:
            return []
        modules_sorted = sorted(modules, key=lambda m: int(m.get("priority", 99)))
        return self._generate_modules(modules_sorted, "coder")

    # ──────────────────────────────────────────────────────────────────────────
    # New spec-aligned agent step methods
    # ──────────────────────────────────────────────────────────────────────────

    def _has_frontend(self) -> bool:
        """Return True if the project includes a frontend layer."""
        tech = self._blueprint.get("tech_stack", {})
        fw = str(tech.get("framework", "")).lower()
        lang = str(tech.get("language", "")).lower()
        # Pure-backend frameworks have no frontend
        if fw in ("fastapi", "django", "express") and "react" not in self.description.lower() and "frontend" not in self.description.lower():
            return False
        if lang == "dart" or fw == "flutter":
            return True
        frontend_keywords = ("react", "nextjs", "next", "vite", "vue", "svelte", "angular", "flutter", "mern", "pern")
        return any(kw in fw for kw in frontend_keywords)

    def _is_backend_module(self, module: dict) -> bool:
        """Return True if *module* is a backend/server-side file."""
        file_path = str(module.get("file", "")).lower()
        desc = str(module.get("description", "")).lower()
        frontend_signals = ("/components/", "/pages/", "/screens/", "/views/", "/ui/", "/styles/",
                            "/hooks/", "/context/", "widget", ".css", ".scss", "tailwind")
        if any(sig in file_path for sig in frontend_signals):
            return False
        backend_signals = ("/api/", "/routes/", "/models/", "/schema", "/migrations/", "/services/",
                           "/middleware/", "/auth/", "/db/", "/controllers/", "main.py",
                           "settings.py", "config.py", "prisma", "alembic")
        if any(sig in file_path for sig in backend_signals):
            return True
        backend_desc_signals = ("api", "route", "model", "schema", "database", "migration",
                                "auth", "service", "controller", "server", "endpoint")
        return any(sig in desc for sig in backend_desc_signals)

    def _is_frontend_module(self, module: dict) -> bool:
        """Return True if *module* is a frontend/client-side file."""
        return not self._is_backend_module(module)

    def _step_architect(self) -> list[str]:
        """Architect agent: generate ARCHITECTURE.md and openapi.yaml.

        Mirrors spec Section 4 — architect agent produces:
        - ARCHITECTURE.md : high-level design document
        - openapi.yaml    : OpenAPI 3.1 spec derived from blueprint api_design
        """
        written: list[str] = []
        tech = self._blueprint.get("tech_stack", {})
        api = self._blueprint.get("api_design", {})
        schema = self._blueprint.get("database_schema", {})
        modules = self._blueprint.get("modules", [])

        # ── ARCHITECTURE.md ───────────────────────────────────────────────────
        arch_path = self.project_root / "ARCHITECTURE.md"
        if not arch_path.exists():
            arch_prompt = f"""
You are a senior software architect. Write a concise ARCHITECTURE.md document for this project.

Project: {self._blueprint.get("project_name", self.project_name)}
Description: {self._blueprint.get("description", self.description)}
Tech stack: {json.dumps(tech, indent=2)}
Modules: {json.dumps([{{"file": m.get("file"), "description": m.get("description")}} for m in modules[:20]], indent=2)}
API design: {json.dumps(api.get("endpoints", [])[:15], indent=2)}
Database schema: {json.dumps(schema.get("tables", [])[:8], indent=2)}

Include sections:
1. Overview — what the system does
2. Architecture — diagram (ASCII), key components and how they interact
3. Data flow — request lifecycle
4. Directory structure — purpose of each major directory
5. Key design decisions — rationale for tech choices

Return ONLY the Markdown content. No code fences.
""".strip()
            try:
                content = _llm_call(arch_prompt)
                arch_path.write_text(content + "\n", encoding="utf-8")
                written.append(str(arch_path))
                self._log("  [architect] wrote ARCHITECTURE.md", event_type="file_created",
                          extra={"file": "ARCHITECTURE.md"})
            except Exception as exc:
                self._log(f"  [architect] ARCHITECTURE.md error: {exc}")

        # ── openapi.yaml ──────────────────────────────────────────────────────
        openapi_path = self.project_root / "openapi.yaml"
        endpoints = api.get("endpoints", [])
        if not openapi_path.exists() and endpoints:
            openapi_prompt = f"""
Write a valid OpenAPI 3.1 spec (YAML) for this API.

Project: {self._blueprint.get("project_name", self.project_name)}
Description: {self._blueprint.get("description", self.description)}
Base URL: http://localhost:8000

Endpoints:
{json.dumps(endpoints[:20], indent=2)}

Database tables (for schema components):
{json.dumps(schema.get("tables", [])[:8], indent=2)}

Include:
- openapi: "3.1.0" header
- info block with title, version, description
- paths for each endpoint with request/response schemas
- components/schemas for key data models
- security schemes if auth is involved

Return ONLY the YAML content. No code fences.
""".strip()
            try:
                content = _llm_call(openapi_prompt)
                content = _strip_fences(content)
                openapi_path.write_text(content + "\n", encoding="utf-8")
                written.append(str(openapi_path))
                self._log("  [architect] wrote openapi.yaml", event_type="file_created",
                          extra={"file": "openapi.yaml"})
            except Exception as exc:
                self._log(f"  [architect] openapi.yaml error: {exc}")

        return written

    def _step_db_agent(self) -> list[str]:
        """DB agent: generate schema definitions, migrations, and seed data.

        Mirrors spec Section 5 — db_agent produces stack-appropriate files:
        - Prisma schema  → prisma/schema.prisma
        - SQLAlchemy     → app/models.py  (if not already generated)
        - Django ORM     → app/models.py  (if not already generated)
        - Seed data file → prisma/seed.ts or seeds/seed.py
        """
        tech = self._blueprint.get("tech_stack", {})
        orm = str(tech.get("orm", "")).lower()
        fw = str(tech.get("framework", "")).lower()
        lang = str(tech.get("language", "")).lower()
        db = str(tech.get("database", "")).lower()
        schema = self._blueprint.get("database_schema", {})
        written: list[str] = []

        if not db or db == "none":
            return written

        # ── Prisma schema ─────────────────────────────────────────────────────
        if orm == "prisma":
            prisma_path = self.project_root / "prisma" / "schema.prisma"
            if not prisma_path.exists():
                prisma_prompt = f"""
Write a complete Prisma schema file for this project.

Database: {db}
Tables/models: {json.dumps(schema.get("tables", []), indent=2)}
Project description: {self._blueprint.get("description", self.description)}

Include:
- datasource db block with postgresql provider and DATABASE_URL env var
- generator client block
- All model definitions with proper field types, relations, and attributes
- @id, @unique, @default, @@index as appropriate
- Relation fields with @relation for all foreign keys

Return ONLY the Prisma schema content. No code fences.
""".strip()
                try:
                    content = _llm_call(prisma_prompt)
                    content = _strip_fences(content)
                    prisma_path.parent.mkdir(parents=True, exist_ok=True)
                    prisma_path.write_text(content + "\n", encoding="utf-8")
                    written.append(str(prisma_path))
                    self._log("  [db_agent] wrote prisma/schema.prisma", event_type="file_created",
                              extra={"file": "prisma/schema.prisma"})
                except Exception as exc:
                    self._log(f"  [db_agent] schema.prisma error: {exc}")

            # Seed file
            seed_path = self.project_root / "prisma" / "seed.ts"
            if not seed_path.exists():
                seed_prompt = f"""
Write a Prisma seed script in TypeScript for this project.

Models: {json.dumps(schema.get("tables", [])[:6], indent=2)}
Project: {self._blueprint.get("project_name", self.project_name)}

Use @prisma/client. Include realistic sample data for development/testing.
Export a main() function and call it with error handling.
Return ONLY the TypeScript file content. No code fences.
""".strip()
                try:
                    content = _llm_call(seed_prompt)
                    content = _strip_fences(content)
                    seed_path.write_text(content + "\n", encoding="utf-8")
                    written.append(str(seed_path))
                    self._log("  [db_agent] wrote prisma/seed.ts", event_type="file_created",
                              extra={"file": "prisma/seed.ts"})
                except Exception as exc:
                    self._log(f"  [db_agent] seed.ts error: {exc}")

        # ── SQLAlchemy / Alembic ──────────────────────────────────────────────
        elif orm == "sqlalchemy" or ("python" in lang and "postgres" in db):
            models_path_candidates = [
                self.project_root / "app" / "models.py",
                self.project_root / "models.py",
            ]
            models_path = next((p for p in models_path_candidates if p.exists()), models_path_candidates[0])
            if not models_path.exists():
                models_prompt = f"""
Write SQLAlchemy 2.x models for this project.

Database: {db}
Tables: {json.dumps(schema.get("tables", []), indent=2)}

Use:
- DeclarativeBase from sqlalchemy.orm
- Mapped[] and mapped_column() syntax (SQLAlchemy 2.x)
- Relationship() for foreign key associations
- __tablename__ attribute on each model
- Type annotations throughout

Return ONLY the Python file content. No code fences.
""".strip()
                try:
                    content = _llm_call(models_prompt)
                    content = _strip_fences(content)
                    models_path.parent.mkdir(parents=True, exist_ok=True)
                    models_path.write_text(content + "\n", encoding="utf-8")
                    written.append(str(models_path))
                    self._log(f"  [db_agent] wrote {models_path.relative_to(self.project_root)}",
                              event_type="file_created")
                except Exception as exc:
                    self._log(f"  [db_agent] models.py error: {exc}")

            # Alembic env.py stub
            alembic_env = self.project_root / "alembic" / "env.py"
            if not alembic_env.exists():
                alembic_prompt = f"""
Write a minimal alembic/env.py for this FastAPI/SQLAlchemy project.

Import Base from app.models or app.database.
Set target_metadata = Base.metadata.
Use DATABASE_URL from environment.
Support both online and offline migration modes.

Return ONLY the Python file content. No code fences.
""".strip()
                try:
                    content = _llm_call(alembic_prompt)
                    content = _strip_fences(content)
                    alembic_env.parent.mkdir(parents=True, exist_ok=True)
                    alembic_env.write_text(content + "\n", encoding="utf-8")
                    written.append(str(alembic_env))
                    self._log("  [db_agent] wrote alembic/env.py", event_type="file_created")
                except Exception as exc:
                    self._log(f"  [db_agent] alembic/env.py error: {exc}")

        # ── Django models ─────────────────────────────────────────────────────
        elif "django" in fw:
            django_models = self.project_root / "api" / "models.py"
            if not django_models.exists():
                django_models_prompt = f"""
Write Django ORM models for this project.

Tables: {json.dumps(schema.get("tables", []), indent=2)}
App name: api

Include:
- All models as Django Model subclasses
- ForeignKey, ManyToManyField as appropriate
- __str__ method on each model
- Meta class with ordering where relevant
- Use Django's built-in fields (CharField, IntegerField, DateTimeField, etc.)

Return ONLY the Python file content. No code fences.
""".strip()
                try:
                    content = _llm_call(django_models_prompt)
                    content = _strip_fences(content)
                    django_models.parent.mkdir(parents=True, exist_ok=True)
                    django_models.write_text(content + "\n", encoding="utf-8")
                    written.append(str(django_models))
                    self._log("  [db_agent] wrote api/models.py", event_type="file_created")
                except Exception as exc:
                    self._log(f"  [db_agent] django models.py error: {exc}")

        return written

    def _step_backend_coder(self) -> list[str]:
        """Backend coder agent: generate server-side / API modules only."""
        modules = self._blueprint.get("modules", [])
        if not modules:
            return []
        modules_sorted = sorted(modules, key=lambda m: int(m.get("priority", 99)))
        backend_modules = [m for m in modules_sorted if self._is_backend_module(m)]
        if not backend_modules:
            # If no backend/frontend split can be made, generate all modules here
            backend_modules = modules_sorted
        return self._generate_modules(backend_modules, "backend_coder")

    def _step_frontend_coder(self) -> list[str]:
        """Frontend coder agent: generate client-side / UI modules only."""
        modules = self._blueprint.get("modules", [])
        if not modules:
            return []
        modules_sorted = sorted(modules, key=lambda m: int(m.get("priority", 99)))
        frontend_modules = [m for m in modules_sorted if self._is_frontend_module(m)]
        return self._generate_modules(frontend_modules, "frontend_coder")

    def _generate_modules(self, modules: list[dict], agent_label: str) -> list[str]:
        """Shared code generation loop used by backend_coder and frontend_coder."""
        written_files: list[str] = []
        context_summary_parts: list[str] = []
        for i, module in enumerate(modules, start=1):
            file_rel = module.get("file", "")
            if not file_rel:
                continue
            target = self._safe_path(file_rel)
            if target is None:
                self._log(f"  [{agent_label}] rejected path-traversal module: {file_rel}")
                continue
            if target.exists() and target.stat().st_size > 50:
                # Don't overwrite files already written by db_agent or scaffold
                self._log(f"  [{agent_label}] {i}/{len(modules)} {file_rel} (already exists, skipping)")
                continue
            self._log(f"  [{agent_label}] {i}/{len(modules)} {file_rel}")
            context_summary = "\n".join(context_summary_parts[-6:])
            prompt = self._build_module_prompt(module, context_summary)
            try:
                code = _llm_call(prompt)
                code = _strip_fences(code)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(code + "\n", encoding="utf-8")
                written_files.append(str(target))
                context_summary_parts.append(f"- {file_rel}: {module.get('description', '')}")
                self._log(f"  [{agent_label}] wrote {file_rel}", event_type="file_created",
                          extra={"file": file_rel, "description": module.get("description", "")})
            except Exception as exc:
                self._log(f"  [{agent_label}] error on {file_rel}: {exc}")
        return written_files

    def _step_stylist(self) -> list[str]:
        """Stylist agent: generate CSS / Tailwind config / global styles.

        Mirrors spec Section 8 — stylist produces theme configuration and
        global stylesheets so frontend_coder can reference consistent design
        tokens rather than duplicating colours/spacing per component.
        """
        tech = self._blueprint.get("tech_stack", {})
        css = str(tech.get("css", "")).lower()
        fw = str(tech.get("framework", "")).lower()
        written: list[str] = []

        # ── Tailwind config ───────────────────────────────────────────────────
        if "tailwind" in css:
            tw_path = self.project_root / "tailwind.config.js"
            if not tw_path.exists():
                tw_prompt = f"""
Write a complete tailwind.config.js for this project.

Framework: {fw}
Project description: {self._blueprint.get("description", self.description)}

Include:
- content array covering all source files
- theme.extend with custom colours, fonts, spacing derived from the project type
- Any plugins (forms, typography, etc.) appropriate for the project

Return ONLY the JavaScript file content. No code fences.
""".strip()
                try:
                    content = _llm_call(tw_prompt)
                    content = _strip_fences(content)
                    tw_path.write_text(content + "\n", encoding="utf-8")
                    written.append(str(tw_path))
                    self._log("  [stylist] wrote tailwind.config.js", event_type="file_created",
                              extra={"file": "tailwind.config.js"})
                except Exception as exc:
                    self._log(f"  [stylist] tailwind.config.js error: {exc}")

        # ── Global CSS ────────────────────────────────────────────────────────
        global_css_candidates = [
            self.project_root / "src" / "app" / "globals.css",
            self.project_root / "src" / "styles" / "global.css",
            self.project_root / "src" / "index.css",
            self.project_root / "styles" / "globals.css",
        ]
        global_css_path = next((p for p in global_css_candidates if p.exists()), global_css_candidates[0])
        if not global_css_path.exists():
            css_prompt = f"""
Write a production-quality global CSS file for this project.

Framework: {fw}
CSS library: {css or 'none'}
Project: {self._blueprint.get("project_name", self.project_name)}

{"Include Tailwind @tailwind base/components/utilities directives." if "tailwind" in css else ""}
Include CSS custom properties (variables) for colors, typography, and spacing.
Include basic reset and sensible defaults.

Return ONLY the CSS file content. No code fences.
""".strip()
            try:
                content = _llm_call(css_prompt)
                content = _strip_fences(content)
                global_css_path.parent.mkdir(parents=True, exist_ok=True)
                global_css_path.write_text(content + "\n", encoding="utf-8")
                written.append(str(global_css_path))
                self._log(f"  [stylist] wrote {global_css_path.relative_to(self.project_root)}",
                          event_type="file_created")
            except Exception as exc:
                self._log(f"  [stylist] global CSS error: {exc}")

        return written

    def _step_git_commit(self, message: str) -> bool:
        """Git agent: initialise local repo and create a commit.

        Returns True if a commit was created, False otherwise.
        Mirrors spec Section 12 — git_agent performs local git operations
        (init, add, commit) before the github_agent pushes to remote.
        """
        if not shutil.which("git"):
            self._log("  [git_agent] git not found — skipping local commit")
            return False
        root = str(self.project_root)
        git_dir = self.project_root / ".git"
        try:
            if not git_dir.exists():
                ok, _, err = _run_subprocess(["git", "init", "-b", "main"], root, timeout=30)
                if not ok:
                    # Older git doesn't support -b; fall back
                    _run_subprocess(["git", "init"], root, timeout=30)
                    _run_subprocess(["git", "checkout", "-b", "main"], root, timeout=10)

            _run_subprocess(["git", "config", "user.email", "kendr-bot@kendr.ai"], root, timeout=10)
            _run_subprocess(["git", "config", "user.name", "Kendr Bot"], root, timeout=10)
            _run_subprocess(["git", "add", "-A"], root, timeout=30)

            ok, stdout, _ = _run_subprocess(
                ["git", "status", "--porcelain"], root, timeout=10
            )
            if not stdout.strip():
                return False

            ok, _, err = _run_subprocess(["git", "commit", "-m", message], root, timeout=30)
            if ok:
                self._log(f"  [git_agent] committed: {message[:80]}")
                return True
            else:
                if "nothing to commit" in err:
                    return False
                self._log(f"  [git_agent] commit error: {err[:200]}")
                return False
        except Exception as exc:
            self._log(f"  [git_agent] error: {exc}")
            return False

    def _step_doc_agent(self) -> list[str]:
        """Doc agent: generate full documentation suite.

        Mirrors spec Section 13 — doc_agent produces:
        - README.md      : project overview + quick start
        - API.md         : full API reference
        - CONTRIBUTING.md: contribution guidelines
        - DEPLOYMENT.md  : deployment instructions
        """
        written: list[str] = []

        # ── README.md ─────────────────────────────────────────────────────────
        readme_written = self._step_readme()
        if readme_written:
            written.append(str(self.project_root / "README.md"))

        # ── API.md ────────────────────────────────────────────────────────────
        api_doc_path = self.project_root / "API.md"
        if not api_doc_path.exists():
            api = self._blueprint.get("api_design", {})
            endpoints = api.get("endpoints", [])
            if endpoints:
                api_prompt = f"""
Write a comprehensive API.md reference document for this REST API.

Project: {self._blueprint.get("project_name", self.project_name)}
Base URL: http://localhost:8000

Endpoints:
{json.dumps(endpoints[:25], indent=2)}

For each endpoint include:
- Method + path as a heading
- Description
- Request parameters / body (JSON example)
- Response format (JSON example)
- Status codes
- Authentication requirements

Return ONLY the Markdown content. No code fences.
""".strip()
                try:
                    content = _llm_call(api_prompt)
                    api_doc_path.write_text(content + "\n", encoding="utf-8")
                    written.append(str(api_doc_path))
                    self._log("  [doc_agent] wrote API.md", event_type="file_created",
                              extra={"file": "API.md"})
                except Exception as exc:
                    self._log(f"  [doc_agent] API.md error: {exc}")

        # ── CONTRIBUTING.md ────────────────────────────────────────────────────
        contrib_path = self.project_root / "CONTRIBUTING.md"
        if not contrib_path.exists():
            tech = self._blueprint.get("tech_stack", {})
            contrib_prompt = f"""
Write a CONTRIBUTING.md for this open-source project.

Project: {self._blueprint.get("project_name", self.project_name)}
Stack: {tech.get("framework", "?")} + {tech.get("language", "?")}
Install command: {self._blueprint.get("install_command", "npm install")}
Test command: {tech.get("testing", "pytest/jest")}

Include sections:
1. Getting started (fork, clone, install)
2. Development workflow (branch naming, commit style)
3. Running tests
4. Submitting a pull request
5. Code style / linting

Return ONLY the Markdown content. No code fences.
""".strip()
            try:
                content = _llm_call(contrib_prompt)
                contrib_path.write_text(content + "\n", encoding="utf-8")
                written.append(str(contrib_path))
                self._log("  [doc_agent] wrote CONTRIBUTING.md", event_type="file_created",
                          extra={"file": "CONTRIBUTING.md"})
            except Exception as exc:
                self._log(f"  [doc_agent] CONTRIBUTING.md error: {exc}")

        # ── DEPLOYMENT.md ──────────────────────────────────────────────────────
        deploy_path = self.project_root / "DEPLOYMENT.md"
        if not deploy_path.exists():
            docker_services = self._blueprint.get("docker_services", [])
            deploy_prompt = f"""
Write a DEPLOYMENT.md for this project.

Project: {self._blueprint.get("project_name", self.project_name)}
Stack: {json.dumps(self._blueprint.get("tech_stack", {}), indent=2)}
Docker services: {json.dumps(docker_services, indent=2)}
Environment variables: {json.dumps([e.get("name") for e in self._blueprint.get("env_vars", [])], indent=2)}

Include sections:
1. Prerequisites
2. Environment configuration (required env vars)
3. Docker deployment (if docker services present)
4. Manual deployment (without Docker)
5. Production considerations (health checks, scaling, monitoring)
6. CI/CD setup hints

Return ONLY the Markdown content. No code fences.
""".strip()
            try:
                content = _llm_call(deploy_prompt)
                deploy_path.write_text(content + "\n", encoding="utf-8")
                written.append(str(deploy_path))
                self._log("  [doc_agent] wrote DEPLOYMENT.md", event_type="file_created",
                          extra={"file": "DEPLOYMENT.md"})
            except Exception as exc:
                self._log(f"  [doc_agent] DEPLOYMENT.md error: {exc}")

        return written

    def _step_reviewer(self) -> str:
        """Reviewer stage: LLM reviews generated code and returns notes.

        Reads up to 10 generated source files, sends them to the LLM for a
        review, and returns a summary of issues found.  The notes are logged
        and made available to the error-fix loop.  This is a lightweight LLM-
        powered code review; it does not modify any files.
        """
        py_files = list(self.project_root.rglob("*.py"))
        ts_files = list(self.project_root.rglob("*.ts")) + list(self.project_root.rglob("*.tsx"))
        dart_files = list(self.project_root.rglob("*.dart"))
        all_files = (py_files + ts_files + dart_files)[:10]
        if not all_files:
            return ""

        snippets: list[str] = []
        for fp in all_files:
            try:
                rel = fp.relative_to(self.project_root)
                content = fp.read_text(encoding="utf-8", errors="replace")[:1200]
                snippets.append(f"--- {rel} ---\n{content}")
            except Exception:
                pass
        if not snippets:
            return ""

        review_prompt = f"""
You are a senior code reviewer. Review the following generated source files and
identify any critical issues: missing imports, obvious logic errors, unsafe patterns,
or incomplete implementations. Be concise — bullet-point issues only.

Project: {self._blueprint.get("project_name", self.project_name)}
Stack: {json.dumps(self._blueprint.get("tech_stack", {}), indent=2)}

Generated files:
{chr(10).join(snippets[:4000 - 200])}

Return a bullet-point list of critical issues only. If the code looks correct, return "No critical issues found."
""".strip()
        try:
            notes = _llm_call(review_prompt).strip()
            if len(notes) > 800:
                notes = notes[:800] + "…"
            return notes
        except Exception as exc:
            return f"reviewer error: {exc}"

    def _step_devops(self) -> list[str]:
        tech = self._blueprint.get("tech_stack", {})
        lang = str(tech.get("language", "")).lower()
        fw = str(tech.get("framework", "")).lower()
        written: list[str] = []

        dockerfile_path = self.project_root / "Dockerfile"
        if not dockerfile_path.exists():
            prompt = f"""
Write a production-ready multi-stage Dockerfile for this project:

Tech stack: {json.dumps(tech, indent=2)}
Framework: {fw}
Language: {lang}

Requirements:
- Use official base images
- Multi-stage build (builder + runtime stage)
- Non-root user
- EXPOSE appropriate port
- Minimal final image size

Return ONLY the Dockerfile content, no explanation, no markdown fences.
""".strip()
            try:
                dockerfile_content = _llm_call(prompt)
                dockerfile_content = _strip_fences(dockerfile_content)
                dockerfile_path.write_text(dockerfile_content + "\n", encoding="utf-8")
                written.append(str(dockerfile_path))
            except Exception as exc:
                self._log(f"  [devops] Dockerfile generation error: {exc}")

        compose_path = self.project_root / "docker-compose.yml"
        if not compose_path.exists() and self._blueprint.get("docker_services"):
            from tasks.project_scaffold_tasks import _generate_docker_compose_stub
            compose_path.write_text(_generate_docker_compose_stub(self._blueprint), encoding="utf-8")
            written.append(str(compose_path))

        return written

    def _step_smoke_test(self) -> list[str]:
        """Per-stack runtime smoke test.

        Launches the start command for at most `_SMOKE_TIMEOUT` seconds.
        If the process exits immediately with a non-zero code, the stderr is
        treated as a real runtime error and the LLM is asked to patch it.

        Long-running servers that survive the timeout are considered healthy.
        Errors are returned as a list of strings (empty = all clear).
        """
        _SMOKE_TIMEOUT = 5

        tech = self._blueprint.get("tech_stack", {})
        lang = str(tech.get("language", "")).lower()
        fw = str(tech.get("framework", "")).lower()
        pm = str(tech.get("package_manager", "npm")).lower()
        root = str(self.project_root)

        if lang == "dart" or fw == "flutter":
            return []

        smoke_cmd: list[str] | None = None
        if "python" in lang:
            for candidate in ["app/main.py", "main.py"]:
                if (self.project_root / candidate).exists():
                    smoke_cmd = ["python", "-c", f"import importlib.util; spec=importlib.util.spec_from_file_location('main','{self.project_root / candidate}'); mod=importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)"]
                    break
        elif (self.project_root / "package.json").exists():
            try:
                pkg = json.loads((self.project_root / "package.json").read_text(encoding="utf-8"))
                scripts = pkg.get("scripts", {})
                if "start" in scripts:
                    smoke_cmd = [pm, "run", "start"]
                elif "dev" in scripts:
                    smoke_cmd = [pm, "run", "dev"]
            except Exception:
                pass

        if not smoke_cmd:
            return []

        try:
            proc = subprocess.Popen(
                smoke_cmd,
                cwd=root,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                stdout_data, stderr_data = proc.communicate(timeout=_SMOKE_TIMEOUT)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.communicate()
                return []

            if proc.returncode == 0:
                return []

            crash_output = (stderr_data + "\n" + stdout_data).strip()[:2000]
            if not crash_output:
                return []

            self._log(f"  [smoke] crash detected (rc={proc.returncode}): {crash_output[:300]}", event_type="run_output",
                      extra={"command": " ".join(smoke_cmd), "ok": False, "stderr": stderr_data[:400]})

            fix_prompt = f"""
The following project crashed immediately on startup. Fix it.

Project: {self._blueprint.get("project_name", self.project_name)}
Tech stack: {json.dumps(tech, indent=2)}
Start command: {' '.join(smoke_cmd)}

Crash output:
{crash_output}

Return a JSON array of file patches to fix the crash:
[{{"file": "relative/path/file.ext", "content": "full corrected content"}}]
Return ONLY valid JSON, no explanation, no markdown fences.
""".strip()
            try:
                raw = _llm_call(fix_prompt)
                patches = json.loads(_strip_json_fences(raw))
                if isinstance(patches, list):
                    for patch in patches:
                        file_rel = patch.get("file", "")
                        content = patch.get("content", "")
                        if not file_rel or not content:
                            continue
                        target = self._safe_path(file_rel)
                        if target is None:
                            self._log(f"  [smoke] rejected path-traversal patch: {file_rel}")
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(content + "\n", encoding="utf-8")
                        self._log(f"  [smoke] patched: {file_rel}", event_type="patch_applied",
                                  extra={"file": file_rel, "stage": "smoke_test"})
            except Exception as exc:
                self._log(f"  [smoke] patch error: {exc}")

            return [f"Startup crash (rc={proc.returncode}): {crash_output[:300]}"]
        except Exception as exc:
            self._log(f"  [smoke] error: {exc}")
            return []

    def _detect_run_command(self) -> tuple[list[str] | None, str]:
        """Return (command, cwd) or (None, error_message|"").

        Returns (None, "") when no verification is applicable (Flutter,
        no entry point found).  Returns (None, error_text) when install fails —
        the caller treats a non-empty error string as a failure to record.

        Verification strategy (in priority order):
        1. Django: ``python manage.py check``
        2. Python: syntax-compile all .py files (fast correctness gate) + try a
           brief uvicorn/gunicorn import dry-run when applicable
        3. TypeScript: ``tsc --noEmit`` (type-checking)
        4. JS + ESLint declared: ``eslint --max-warnings 9999 .``
        5. Otherwise: skip (no applicable verifier)
        """
        tech = self._blueprint.get("tech_stack", {})
        lang = str(tech.get("language", "")).lower()
        fw = str(tech.get("framework", "")).lower()
        pm = str(tech.get("package_manager", "npm")).lower()
        root = str(self.project_root)

        if lang == "dart" or fw == "flutter":
            return None, ""

        if "python" in lang:
            if (self.project_root / "requirements.txt").exists():
                ok, _, err = _run_subprocess(["pip", "install", "-r", "requirements.txt"], root, timeout=120)
                if not ok:
                    return None, f"pip install failed: {err[:400]}"

            if (self.project_root / "manage.py").exists():
                return ["python", "manage.py", "check"], root

            py_files = sorted(self.project_root.rglob("*.py"), key=lambda p: len(p.parts))
            if not py_files:
                return None, ""

            first_failing: Path | None = None
            for pyf in py_files[:25]:
                ok, _, _ = _run_subprocess(["python", "-m", "py_compile", str(pyf)], root, timeout=20)
                if not ok:
                    first_failing = pyf
                    break

            if first_failing is not None:
                return ["python", "-m", "py_compile", str(first_failing)], root

            main_candidates = ["app/main.py", "main.py"]
            for candidate in main_candidates:
                p = self.project_root / candidate
                if p.exists():
                    return ["python", "-m", "py_compile", str(p)], root

            return ["python", "-m", "py_compile", str(py_files[0])], root

        if (self.project_root / "package.json").exists():
            ok, _, err = _run_subprocess([pm, "install", "--prefer-offline"], root, timeout=180)
            if not ok:
                ok, _, err = _run_subprocess(["npm", "install", "--prefer-offline"], root, timeout=180)
            if not ok:
                return None, f"npm install failed: {err[:400]}"

            if (self.project_root / "tsconfig.json").exists():
                return ["npx", "tsc", "--noEmit"], root

            try:
                pkg = json.loads((self.project_root / "package.json").read_text(encoding="utf-8"))
                scripts = pkg.get("scripts", {})
                all_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
                if "build" in scripts:
                    return ["npm", "run", "build"], root
                if "eslint" in all_deps:
                    return ["npx", "eslint", "--max-warnings", "9999", "."], root
            except Exception:
                pass
            return None, ""

        return None, ""

    def _step_error_fix_loop(self) -> dict:
        report: dict = {"ok": True, "iterations": 0, "errors": []}
        for iteration in range(self.max_fix_iters):
            report["iterations"] = iteration + 1
            command, cwd_or_err = self._detect_run_command()
            if command is None:
                if cwd_or_err:
                    report["ok"] = False
                    report["errors"].append(cwd_or_err)
                break
            cwd = cwd_or_err
            if not command:
                break

            self._log(f"  [verifier] iter {iteration + 1}: {' '.join(command)}")
            ok, stdout, stderr = _run_subprocess(command, cwd or str(self.project_root), timeout=120)
            combined_output = (stdout + "\n" + stderr).strip()
            self._log(f"  [verifier] output:\n{combined_output[:800]}", event_type="run_output",
                      extra={"command": " ".join(command), "ok": ok, "stdout": stdout[:400], "stderr": stderr[:400]})
            if ok:
                self._log(f"  [verifier] iter {iteration + 1}: pass ✓")
                report["ok"] = True
                break

            error_text = (stderr + "\n" + stdout).strip()[:4000]
            self._log(f"  [fixer] iter {iteration + 1}: errors found, asking LLM to patch…")
            self._log(f"  [fixer] stderr: {error_text[:200]}")

            fix_prompt = f"""
A project was generated but has errors. Fix them.

Project: {self._blueprint.get("project_name", self.project_name)}
Tech stack: {json.dumps(self._blueprint.get("tech_stack", {}), indent=2)}

Error output:
{error_text}

Instructions:
- Identify the root cause(s) from the error output.
- Return a JSON array of file patches:
  [{{"file": "relative/path/to/file.ext", "content": "full corrected file content"}}]
- Only include files that need to be changed.
- Return ONLY valid JSON, no explanation, no markdown fences.
""".strip()

            try:
                raw_fix = _llm_call(fix_prompt)
                patches = json.loads(_strip_json_fences(raw_fix))
                if isinstance(patches, list):
                    for patch in patches:
                        file_rel = patch.get("file", "")
                        content = patch.get("content", "")
                        if not file_rel or not content:
                            continue
                        target = (self.project_root / file_rel).resolve()
                        try:
                            target.relative_to(self.project_root.resolve())
                        except ValueError:
                            self._log(f"  [fixer] rejected path-traversal patch: {file_rel}")
                            continue
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(content + "\n", encoding="utf-8")
                        self._log(f"  [fixer] patched: {file_rel}", event_type="patch_applied",
                                  extra={"file": file_rel, "iteration": iteration + 1})
            except Exception as exc:
                self._log(f"  [fixer] patch parse error: {exc}")
                report["errors"].append(f"iter {iteration + 1}: {error_text[:200]}")

            if iteration + 1 >= self.max_fix_iters:
                report["ok"] = False
                report["errors"].append(f"Remaining errors after {self.max_fix_iters} fix iterations: {error_text[:400]}")

        return report

    def _step_generate_tests(self) -> list[str]:
        tech = self._blueprint.get("tech_stack", {})
        lang = str(tech.get("language", "")).lower()
        fw = str(tech.get("framework", "")).lower()
        testing = str(tech.get("testing", "")).lower()
        api = self._blueprint.get("api_design", {})
        modules = self._blueprint.get("modules", [])[:8]

        if lang == "dart" or fw == "flutter":
            test_file = self.project_root / "test" / "widget_test.dart"
            prompt = f"""
Write Flutter widget tests for this app:

Project: {self._blueprint.get("project_name", self.project_name)}
Description: {self._blueprint.get("description", self.description)}

Write tests using flutter_test and mockito.
Return ONLY the Dart file content.
""".strip()
        elif "python" in lang:
            test_file = self.project_root / "tests" / "test_api.py"
            prompt = f"""
Write pytest unit/integration tests for this API:

Project: {self._blueprint.get("project_name", self.project_name)}
Framework: {fw}
API endpoints: {json.dumps(api.get("endpoints", [])[:10], indent=2)}
Modules: {json.dumps([m.get("file") for m in modules], indent=2)}

Use pytest and httpx/TestClient.
Return ONLY the Python file content.
""".strip()
        else:
            test_file = self.project_root / "tests" / "app.test.ts"
            test_framework = "vitest" if "vite" in fw or testing == "vitest" else "jest"
            prompt = f"""
Write {test_framework} tests for this application:

Project: {self._blueprint.get("project_name", self.project_name)}
Framework: {fw}
API endpoints: {json.dumps(api.get("endpoints", [])[:10], indent=2)}
Modules: {json.dumps([m.get("file") for m in modules], indent=2)}

Use {test_framework} with @testing-library/react where appropriate.
Return ONLY the TypeScript/JavaScript file content.
""".strip()

        try:
            content = _llm_call(prompt)
            content = _strip_fences(content)
            test_file.parent.mkdir(parents=True, exist_ok=True)
            if not test_file.exists():
                test_file.write_text(content + "\n", encoding="utf-8")
                return [str(test_file)]
        except Exception as exc:
            self._log(f"  [tests] generation error: {exc}")
        return []

    def _step_readme(self) -> bool:
        readme_path = self.project_root / "README.md"
        if readme_path.exists() and len(readme_path.read_text(encoding="utf-8").strip()) > 200:
            return False
        tech = self._blueprint.get("tech_stack", {})
        api = self._blueprint.get("api_design", {})
        install_cmd = self._blueprint.get("install_command", "npm install")
        run_cmd = self._blueprint.get("run_command", "npm run dev")
        endpoints = api.get("endpoints", [])[:12]

        lines = [
            f"# {self._blueprint.get('project_name', self.project_name)}",
            "",
            f"> {self._blueprint.get('description', self.description)}",
            "",
            f"**Stack**: {tech.get('framework', '?')} · {tech.get('database', 'no DB')} · {tech.get('language', '?')}",
            "",
            "## Quick Start",
            "",
            "```bash",
        ]
        docker_services = self._blueprint.get("docker_services", [])
        if docker_services:
            lines.append("# Start supporting services")
            lines.append("docker-compose up -d")
            lines.append("")
        lines.append("# Install dependencies")
        lines.append(install_cmd)
        lines.append("")
        lines.append("# Copy environment config")
        lines.append("cp .env.example .env")
        lines.append("")
        lines.append("# Start development server")
        lines.append(run_cmd)
        lines.append("```")
        lines.append("")
        if endpoints:
            lines.append("## API Endpoints")
            lines.append("")
            for ep in endpoints:
                lines.append(f"- `{ep.get('method', '?')} {ep.get('path', '?')}` — {ep.get('description', '')}")
            lines.append("")
        env_vars = self._blueprint.get("env_vars", [])
        if env_vars:
            lines.append("## Environment Variables")
            lines.append("")
            lines.append("See `.env.example` for all required variables.")
            lines.append("")
            for ev in env_vars:
                required_label = " *(required)*" if ev.get("required") else ""
                lines.append(f"- `{ev.get('name', '?')}`{required_label} — {ev.get('description', '')}")
            lines.append("")
        lines.append("---")
        lines.append("Generated by [Kendr](https://github.com/kendr-ai/kendr) Project Builder.")
        readme_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return True

    def _step_github_push(self) -> str:
        """Create/find a GitHub repo and push the generated project.

        Authentication is handled exclusively via ``GitHubClient._git_env()``,
        which injects the token as an HTTP Authorization header through git's
        GIT_CONFIG_COUNT environment-variable mechanism.  The token is never
        embedded in any remote URL, git config file, or command-line argument.
        """
        if not self.github_repo or not self.github_token:
            return ""
        try:
            from tasks.github_client import GitHubClient
            owner, repo_name = self.github_repo.split("/", 1)
            client = GitHubClient(token=self.github_token)

            clone_url = f"https://github.com/{owner}/{repo_name}.git"
            try:
                existing = client.get_repo(owner, repo_name)
                self._log(f"  [github] repo exists: {existing.get('html_url', '')}")
            except RuntimeError as exc:
                if "404" in str(exc) or "Not Found" in str(exc):
                    try:
                        user_info = client._request_sync("GET", "/user", None, 30)
                        authenticated_login = str(user_info.get("login", ""))
                    except Exception:
                        authenticated_login = owner

                    create_path = (
                        "/user/repos"
                        if authenticated_login.lower() == owner.lower()
                        else f"/orgs/{owner}/repos"
                    )
                    new_repo = client._request_sync("POST", create_path, {
                        "name": repo_name,
                        "description": self._blueprint.get("description", self.description[:80]),
                        "private": False,
                        "auto_init": False,
                    }, 30)
                    self._log(f"  [github] repo created: {new_repo.get('html_url', '')}")
                else:
                    raise

            if not shutil.which("git"):
                self._log("  [github] git not found, skipping push")
                return ""

            git_dir = self.project_root / ".git"
            if not git_dir.exists():
                client._run_git(["init", "-b", "main"], self.project_root)

            try:
                client.commit(self.project_root, f"feat: initial project scaffold — {self.project_name}", add_all=True)
            except RuntimeError as exc:
                if "nothing to commit" not in str(exc):
                    raise

            try:
                client._run_git(["remote", "remove", "origin"], self.project_root)
            except RuntimeError:
                pass
            client._run_git(["remote", "add", "origin", clone_url], self.project_root)

            try:
                client.push_set_upstream(self.project_root, "main")
                return f"https://github.com/{self.github_repo}"
            except RuntimeError as push_err:
                if "main" in str(push_err):
                    try:
                        client.push_set_upstream(self.project_root, "master")
                        return f"https://github.com/{self.github_repo}"
                    except RuntimeError:
                        pass
                self._log(f"  [github] push error: {push_err}")
                return ""
        except Exception as exc:
            self._log(f"  [github] error: {exc}")
            return ""
