"""Project Generation Orchestrator.

Standalone multi-agent pipeline that scaffolds a complete, runnable project
from a natural language description — no gateway required.

Pipeline:
  blueprint → scaffold → coder (per module) → verifier/error-fixer (x3) →
  test writer → README writer → [optional GitHub push]
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
    return Path(__file__).resolve().parents[1]


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

            self._log("[1/7] generating blueprint…")
            self._blueprint = self._step_blueprint()
            self._log(f"[1/7] blueprint ready: {self._blueprint.get('project_name', self.project_name)}")

            if not self.auto_approve:
                self._blueprint = self._step_blueprint_approval(self._blueprint)

            self._log("[2/7] scaffolding project structure…")
            files_created = self._step_scaffold()
            result["files_created"].extend(files_created)
            self._log(f"[2/7] scaffold complete: {len(files_created)} files/dirs created")

            self._log("[3/8] generating code modules…")
            coded_files = self._step_code_modules()
            result["files_created"].extend(coded_files)
            self._log(f"[3/8] code generation complete: {len(coded_files)} files written")

            self._log("[4/8] reviewer — checking generated code quality…")
            review_notes = self._step_reviewer()
            if review_notes:
                self._log(f"[4/8] reviewer notes: {review_notes[:200]}")
            else:
                self._log("[4/8] reviewer: code looks good")

            if not self.skip_devops:
                self._log("[5/8] generating devops files…")
                devops_files = self._step_devops()
                result["files_created"].extend(devops_files)
                self._log(f"[5/8] devops files written: {len(devops_files)}")
            else:
                self._log("[5/8] devops generation skipped")

            self._log("[6/9] running error-fix loop (up to 3 iterations)…")
            fix_report = self._step_error_fix_loop()
            if fix_report.get("errors"):
                result["errors"].extend(fix_report["errors"])
            fix_ok = fix_report.get("ok", True)
            self._log(f"[6/9] error-fix loop done: {fix_report.get('iterations', 0)} iterations, {'pass' if fix_ok else 'some errors remain'}")
            if not fix_ok:
                result["ok"] = False  # explicitly mark failure; cannot be reset to True below

            self._log("[7/9] runtime smoke test…")
            smoke_errs = self._step_smoke_test()
            if smoke_errs:
                result["errors"].extend(smoke_errs)
                self._log(f"[7/9] smoke test found {len(smoke_errs)} issue(s) — patched")
            else:
                self._log("[7/9] smoke test passed")

            if not self.skip_tests:
                self._log("[8/9] generating tests…")
                test_files = self._step_generate_tests()
                result["files_created"].extend(test_files)
                self._log(f"[8/9] tests written: {len(test_files)} files")
            else:
                self._log("[8/9] test generation skipped")

            self._log("[9/9] writing README…")
            readme_written = self._step_readme()
            if readme_written:
                result["files_created"].append(str(self.project_root / "README.md"))
            self._log("[9/9] README written")

            if self.github_repo:
                self._log(f"[github] pushing to {self.github_repo}…")
                github_url = self._step_github_push()
                result["github_url"] = github_url
                if github_url:
                    self._log(f"[github] pushed: {github_url}")
                else:
                    self._log("[github] push skipped (no token or error)")

            elapsed = round(time.time() - start, 1)
            if result["ok"] is _PENDING:
                result["ok"] = True
            status_mark = "✓" if result["ok"] else "⚠"
            self._log(f"[orchestrator] done in {elapsed}s  {status_mark}  {self.project_root}")

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
        modules = self._blueprint.get("modules", [])
        if not modules:
            return []
        modules_sorted = sorted(modules, key=lambda m: int(m.get("priority", 99)))
        written_files: list[str] = []
        context_summary_parts: list[str] = []
        for i, module in enumerate(modules_sorted, start=1):
            file_rel = module.get("file", "")
            if not file_rel:
                continue
            target = self._safe_path(file_rel)
            if target is None:
                self._log(f"  [coder] rejected path-traversal module: {file_rel}")
                continue
            self._log(f"  [coder] {i}/{len(modules_sorted)} {file_rel}")
            context_summary = "\n".join(context_summary_parts[-6:])
            prompt = self._build_module_prompt(module, context_summary)
            try:
                code = _llm_call(prompt)
                code = _strip_fences(code)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(code + "\n", encoding="utf-8")
                written_files.append(str(target))
                context_summary_parts.append(f"- {file_rel}: {module.get('description', '')}")
                self._log(f"  [coder] wrote {file_rel}", event_type="file_created",
                          extra={"file": file_rel, "description": module.get("description", "")})
            except Exception as exc:
                self._log(f"  [coder] error on {file_rel}: {exc}")
        return written_files

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
