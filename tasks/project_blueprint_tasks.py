"""Project Blueprint Agent.

Designs the complete technical architecture for a new software project:
tech stack, database schema, API endpoints, frontend components, directory
structure, environment variables, Docker services, and dependencies.

The blueprint is presented to the user for approval before any code is
generated.  Once approved it feeds into the planner and builder agents.
"""

import json
import re
from datetime import datetime, timezone
from pathlib import Path

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.utils import OUTPUT_DIR, llm, log_task_update, normalize_llm_text, write_text_file

# Lazy-import to avoid hard dependency at module level
_stack_helpers = None


def _load_stack_helpers():
    global _stack_helpers
    if _stack_helpers is None:
        try:
            from plugin_templates.project_stacks import (
                all_stack_summaries,
                available_stacks,
                load_stack_template,
            )
            _stack_helpers = {
                "load": load_stack_template,
                "available": available_stacks,
                "summaries": all_stack_summaries,
            }
        except ModuleNotFoundError as exc:
            # Keep blueprint generation operational even if template modules are
            # not present in an older/broken install.
            if str(getattr(exc, "name", "") or "").startswith("plugin_templates"):
                _stack_helpers = {
                    "load": lambda _name: None,
                    "available": lambda: [],
                    "summaries": lambda: [],
                }
            else:
                raise
    return _stack_helpers


AGENT_METADATA = {
    "project_blueprint_agent": {
        "description": (
            "Designs complete technical architecture for a new software project: "
            "tech stack, database schema, API endpoints, frontend components, "
            "directory structure, and infrastructure."
        ),
        "skills": [
            "architecture",
            "project design",
            "tech stack selection",
            "database design",
            "api design",
        ],
        "input_keys": [
            "blueprint_request",
            "user_query",
            "current_objective",
            "coding_context_files",
            "blueprint_context_files",
            "project_context_files",
            "context_files",
        ],
        "output_keys": [
            "blueprint_json",
            "blueprint_summary",
            "blueprint_tech_stack",
            "blueprint_db_schema",
            "blueprint_api_design",
            "blueprint_frontend_components",
            "blueprint_directory_structure",
            "blueprint_dependencies",
            "blueprint_env_vars",
            "blueprint_docker_services",
            "blueprint_stack_overrides",
        ],
        "requirements": [],
    },
}


# ---------------------------------------------------------------------------
# Stack detection heuristic
# ---------------------------------------------------------------------------

_STACK_KEYWORDS: dict[str, list[str]] = {
    "mern_microservices_mongodb": [
        r"\bmern\b",
        "mongo.*express.*react.*node",
        "node.*express.*react.*mongo",
        "express.*react.*mongo",
        "microservice.*mern",
        "mern.*microservice",
    ],
    "pern_postgres": [
        r"\bpern\b",
        "postgres.*express.*react.*node",
        "node.*express.*react.*postgres",
        "express.*react.*postgres",
        "express.*react.*postgresql",
    ],
    "fastapi_postgres": ["fastapi", "fast api"],
    "nextjs_prisma_postgres": ["next.js", "nextjs", "next js"],
    "express_prisma_postgres": ["express", "expressjs", "express.js"],
    "fastapi_react_postgres": ["fastapi.*react", "react.*fastapi", "fast api.*react"],
    "nextjs_static_site": [
        "nextjs.*static",
        "next.js.*static",
        "static.*nextjs",
        "static.*next.js",
        "static website.*next",
        "next.*static website",
    ],
}


def _extract_stack_requirements(description: str) -> dict[str, str]:
    text = description.lower()
    requirements: dict[str, str] = {}
    if re.search(r"\btypescript\b", text):
        requirements["language"] = "typescript"
    elif re.search(r"\bjavascript\b", text) or "node.js" in text or "nodejs" in text or "node " in text:
        requirements["language"] = "javascript"
    elif re.search(r"\bpython\b", text):
        requirements["language"] = "python"

    if re.search(r"\bnext\.?js\b", text) or "nextjs" in text or "next js" in text:
        requirements["framework"] = "nextjs"
    elif re.search(r"\bnestjs\b", text) or "nest js" in text:
        requirements["framework"] = "nestjs"
    elif re.search(r"\bexpress\b", text):
        requirements["framework"] = "express"
    elif re.search(r"\bfastapi\b", text) or "fast api" in text:
        requirements["framework"] = "fastapi"
    elif re.search(r"\bdjango\b", text):
        requirements["framework"] = "django"
    elif re.search(r"\bflask\b", text):
        requirements["framework"] = "flask"
    elif re.search(r"\brails\b", text):
        requirements["framework"] = "rails"
    elif re.search(r"\blaravel\b", text):
        requirements["framework"] = "laravel"

    if re.search(r"\breact\b", text):
        requirements["frontend"] = "react"
    if re.search(r"\bvue\b", text) or "vue.js" in text or "vuejs" in text:
        requirements["frontend"] = "vue"
    if re.search(r"\bsvelte\b", text) or "sveltekit" in text:
        requirements["frontend"] = "svelte"
    if re.search(r"\bangular\b", text):
        requirements["frontend"] = "angular"

    if "express" in requirements.get("framework", "") and requirements.get("frontend") == "react":
        requirements["framework"] = "express+react"
    if "fastapi" in requirements.get("framework", "") and requirements.get("frontend") == "react":
        requirements["framework"] = "fastapi+react"

    if re.search(r"\bmongo(db)?\b", text):
        requirements["database"] = "mongodb"
        if "orm" not in requirements:
            requirements["orm"] = "mongoose"
    elif re.search(r"\bpostgres\b", text) or "postgresql" in text:
        requirements["database"] = "postgresql"
    elif re.search(r"\bmysql\b", text):
        requirements["database"] = "mysql"
    elif re.search(r"\bsqlite\b", text):
        requirements["database"] = "sqlite"

    if re.search(r"\bprisma\b", text):
        requirements["orm"] = "prisma"
    elif re.search(r"\btypeorm\b", text):
        requirements["orm"] = "typeorm"
    elif re.search(r"\bsequelize\b", text):
        requirements["orm"] = "sequelize"
    elif re.search(r"\bsqlalchemy\b", text):
        requirements["orm"] = "sqlalchemy"
    elif re.search(r"\bmongoose\b", text):
        requirements["orm"] = "mongoose"

    if "tailwind" in text:
        requirements["css"] = "tailwindcss"
    elif "styled-components" in text:
        requirements["css"] = "styled-components"
    elif "css modules" in text or "css-modules" in text:
        requirements["css"] = "css-modules"

    if "pnpm" in text:
        requirements["package_manager"] = "pnpm"
    elif "yarn" in text:
        requirements["package_manager"] = "yarn"
    elif "npm" in text:
        requirements["package_manager"] = "npm"
    elif "pip" in text:
        requirements["package_manager"] = "pip"

    if "vite" in text:
        requirements["runtime"] = "vite"
    elif "next" in text:
        requirements["runtime"] = "next"
    elif "uvicorn" in text:
        requirements["runtime"] = "uvicorn"
    elif "node" in text:
        requirements["runtime"] = "node"

    return requirements


def _infer_stack_template(requirements: dict[str, str]) -> str | None:
    framework = requirements.get("framework", "")
    database = requirements.get("database", "")
    orm = requirements.get("orm", "")
    if framework == "express+react" and database == "mongodb":
        return "mern_microservices_mongodb"
    if framework == "express+react" and database == "postgresql":
        return "pern_postgres"
    if framework == "fastapi+react" and database == "postgresql":
        return "fastapi_react_postgres"
    if framework == "fastapi" and database == "postgresql":
        return "fastapi_postgres"
    if framework == "nextjs" and database == "postgresql" and orm == "prisma":
        return "nextjs_prisma_postgres"
    if framework == "express" and database == "postgresql" and orm == "prisma":
        return "express_prisma_postgres"
    if framework == "nextjs":
        return "nextjs_static_site"
    return None


def _detect_stack(description: str) -> str | None:
    """Return the best-matching stack template name, or ``None``."""
    text = description.lower()
    requirements = _extract_stack_requirements(description)
    inferred = _infer_stack_template(requirements)
    if inferred:
        return inferred
    for stack_name, keywords in _STACK_KEYWORDS.items():
        for kw in keywords:
            if re.search(kw, text):
                return stack_name
    return None


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def _build_blueprint_prompt(
    description: str,
    stack_template: dict | None,
    available_stack_names: list[str],
) -> str:
    template_hint = ""
    if stack_template:
        template_hint = (
            f"\n\nA matching stack template was detected: {stack_template.get('display_name', stack_template.get('name'))}.\n"
            f"Use it as a strong default. Override only where the user's description demands something different.\n"
            f"Template defaults:\n{json.dumps(stack_template, indent=2, ensure_ascii=False)}\n"
        )

    return f"""
You are the project blueprint architect in a multi-agent development system.

Your job is to design the COMPLETE technical architecture for a software project
described by the user.  This blueprint will be reviewed by the user and then
handed to specialised builder agents that generate every file.

User project description:
{description}

Available stack templates (for reference): {json.dumps(available_stack_names)}
{template_hint}

Return ONLY valid JSON using this exact schema (no markdown fences):
{{
  "project_name": "kebab-case-name",
  "tech_stack": {{
    "language": "python | typescript | javascript | python+typescript",
    "framework": "fastapi | express | nextjs | fastapi+react | express+react | django | flask | nestjs | rails | laravel",
    "database": "postgresql | mongodb | mysql | sqlite",
    "orm": "sqlalchemy | prisma | typeorm | mongoose | sequelize | none",
    "migration_tool": "alembic | prisma | typeorm | none",
    "auth": "jwt | next-auth | session | oauth | none",
    "css": "tailwindcss | css-modules | styled-components | none",
    "package_manager": "pip | npm | yarn | pnpm | pip+npm",
    "runtime": "uvicorn | next | ts-node | vite | node | node+vite"
  }},
  "directory_structure": [
    "src/",
    "src/main.py"
  ],
  "db_schema": {{
    "tables": [
      {{
        "name": "users",
        "columns": [
          {{"name": "id", "type": "uuid", "primary_key": true}},
          {{"name": "email", "type": "varchar(255)", "unique": true, "nullable": false}},
          {{"name": "created_at", "type": "timestamp", "default": "now()"}}
        ],
        "indexes": ["idx_users_email"],
        "relationships": []
      }}
    ]
  }},
  "api_design": {{
    "base_path": "/api",
    "endpoints": [
      {{
        "path": "/api/users",
        "method": "GET",
        "description": "List all users",
        "request_schema": {{}},
        "response_schema": {{"items": "User[]"}},
        "auth_required": true
      }}
    ]
  }},
  "frontend_components": {{
    "pages": [
      {{"name": "HomePage", "route": "/", "description": "Landing page"}}
    ],
    "layouts": [
      {{"name": "MainLayout", "description": "Navbar + sidebar + content area"}}
    ],
    "components": [
      {{"name": "LoginForm", "description": "Email/password login form"}}
    ]
  }},
  "env_vars": [
    {{"name": "DATABASE_URL", "description": "DB connection string", "example_value": "postgresql://...", "required": true}}
  ],
  "docker_services": [
    {{"name": "postgres", "image": "postgres:16-alpine", "ports": ["5432:5432"], "volumes": ["pgdata:/var/lib/postgresql/data"], "env": {{"POSTGRES_DB": "appdb"}}}}
  ],
  "dependencies": {{
    "runtime": ["fastapi>=0.110", "uvicorn"],
    "dev": ["pytest", "ruff"]
  }}
}}

Design rules:
- If the user explicitly specifies a stack or technologies, follow that requirement and do not override it.
- Be comprehensive: include auth, CORS, error handling, validation, health-check endpoint.
- Database schema must include all tables, columns, types, PKs, FKs, indexes.
- API design must cover full CRUD for every entity plus auth endpoints.
- Frontend must have pages for every user-facing feature plus login/register.
- Directory structure must list every directory and stub file.
- Use modern, production-grade patterns and libraries.
- If the project is backend-only (no frontend mentioned), set frontend_components to empty lists.
- If the project is API-only, omit CSS/frontend framework from tech_stack.
""".strip()


# ---------------------------------------------------------------------------
# Parsing & validation
# ---------------------------------------------------------------------------

def _strip_code_fences(text: str) -> str:
    stripped = normalize_llm_text(text).strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _read_context_files(
    file_paths: list[str],
    working_directory: str,
    max_chars: int = 6000,
) -> tuple[str, list[str], list[str]]:
    if not file_paths:
        return "", [], []
    resolved_dir = Path(working_directory).expanduser().resolve()
    chunks: list[str] = []
    missing: list[str] = []
    loaded: list[str] = []
    for raw_path in file_paths:
        value = str(raw_path or "").strip()
        if not value:
            continue
        path = Path(value)
        if not path.is_absolute():
            path = (resolved_dir / path).resolve()
        if not path.exists():
            missing.append(str(path))
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except Exception:
            try:
                text = path.read_text(encoding="latin-1")
            except Exception:
                missing.append(str(path))
                continue
        trimmed = text.strip()
        if not trimmed:
            continue
        loaded.append(str(path))
        chunks.append(f"[{path.name}]\n{trimmed[:max_chars]}")
    return "\n\n".join(chunks), missing, loaded


def _parse_blueprint(raw_output: str) -> dict:
    cleaned = _strip_code_fences(raw_output)
    data = json.loads(cleaned)
    if not isinstance(data, dict):
        raise ValueError("Blueprint must be a JSON object.")
    return data


def _stack_matches(blueprint: dict, stack_template: dict) -> bool:
    bp_stack = blueprint.get("tech_stack", {}) if isinstance(blueprint.get("tech_stack"), dict) else {}
    tpl_stack = stack_template.get("tech_stack", {}) if isinstance(stack_template.get("tech_stack"), dict) else {}
    if not bp_stack or not tpl_stack:
        return False
    for key in ("language", "framework", "database", "orm"):
        bp_value = str(bp_stack.get(key, "") or "").strip().lower()
        tpl_value = str(tpl_stack.get(key, "") or "").strip().lower()
        if tpl_value and bp_value and bp_value != tpl_value:
            return False
    return True


def _apply_stack_requirements(blueprint: dict, requirements: dict[str, str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    if not requirements:
        return overrides
    tech_stack = blueprint.get("tech_stack", {})
    if not isinstance(tech_stack, dict):
        tech_stack = {}
    for key, value in requirements.items():
        if key == "frontend":
            continue
        if not value:
            continue
        current = str(tech_stack.get(key, "") or "").strip().lower()
        if current != value:
            tech_stack[key] = value
            overrides[key] = value
    blueprint["tech_stack"] = tech_stack
    return overrides


def _validate_blueprint(blueprint: dict) -> list[str]:
    """Return a list of validation warnings (empty = valid)."""
    warnings: list[str] = []
    required_top_keys = [
        "project_name", "tech_stack", "directory_structure",
        "db_schema", "api_design", "dependencies",
    ]
    for key in required_top_keys:
        if not blueprint.get(key):
            warnings.append(f"Missing or empty required key: {key}")

    tech = blueprint.get("tech_stack", {})
    if not tech.get("language"):
        warnings.append("tech_stack.language is required")
    if not tech.get("framework"):
        warnings.append("tech_stack.framework is required")

    tables = blueprint.get("db_schema", {}).get("tables", [])
    if not tables:
        warnings.append("db_schema.tables is empty -- no database tables defined")

    endpoints = blueprint.get("api_design", {}).get("endpoints", [])
    if not endpoints:
        warnings.append("api_design.endpoints is empty -- no API endpoints defined")

    return warnings


# ---------------------------------------------------------------------------
# Markdown rendering for approval
# ---------------------------------------------------------------------------

def _blueprint_as_markdown(bp: dict) -> str:
    lines: list[str] = []
    lines.append(f"# Project Blueprint: {bp.get('project_name', 'unnamed')}")
    lines.append("")

    # Tech stack
    tech = bp.get("tech_stack", {})
    lines.append("## Tech Stack")
    for k, v in tech.items():
        if v:
            lines.append(f"- **{k}**: {v}")
    lines.append("")

    # Directory structure
    dirs = bp.get("directory_structure", [])
    if dirs:
        lines.append("## Directory Structure")
        for d in dirs[:50]:
            lines.append(f"  {d}")
        if len(dirs) > 50:
            lines.append(f"  ... and {len(dirs) - 50} more entries")
        lines.append("")

    # Database schema
    tables = bp.get("db_schema", {}).get("tables", [])
    if tables:
        lines.append("## Database Schema")
        for t in tables:
            cols = ", ".join(
                c.get("name", "?") + ":" + c.get("type", "?")
                for c in t.get("columns", [])
            )
            lines.append(f"- **{t.get('name', '?')}** ({cols})")
        lines.append("")

    # API endpoints
    endpoints = bp.get("api_design", {}).get("endpoints", [])
    if endpoints:
        lines.append("## API Endpoints")
        for ep in endpoints:
            auth_tag = " [auth]" if ep.get("auth_required") else ""
            lines.append(f"- `{ep.get('method', '?')} {ep.get('path', '?')}`{auth_tag} -- {ep.get('description', '')}")
        lines.append("")

    # Frontend
    fe = bp.get("frontend_components", {})
    pages = fe.get("pages", [])
    components = fe.get("components", [])
    if pages or components:
        lines.append("## Frontend")
        for p in pages:
            lines.append(f"- Page: **{p.get('name', '?')}** ({p.get('route', '?')}) -- {p.get('description', '')}")
        for c in components:
            lines.append(f"- Component: **{c.get('name', '?')}** -- {c.get('description', '')}")
        lines.append("")

    # Docker services
    services = bp.get("docker_services", [])
    if services:
        lines.append("## Docker Services")
        for svc in services:
            lines.append(f"- **{svc.get('name', '?')}** ({svc.get('image', '?')}) ports={svc.get('ports', [])}")
        lines.append("")

    # Dependencies
    deps = bp.get("dependencies", {})
    if deps:
        lines.append("## Dependencies")
        rt = deps.get("runtime", [])
        if rt:
            lines.append(f"- Runtime: {', '.join(str(d) for d in rt[:20])}")
        dev = deps.get("dev", [])
        if dev:
            lines.append(f"- Dev: {', '.join(str(d) for d in dev[:20])}")
        lines.append("")

    # Env vars
    env_vars = bp.get("env_vars", [])
    if env_vars:
        lines.append("## Environment Variables")
        for ev in env_vars:
            req = " (required)" if ev.get("required") else ""
            lines.append(f"- `{ev.get('name', '?')}`{req} -- {ev.get('description', '')}")
        lines.append("")

    return "\n".join(lines).strip()


# ---------------------------------------------------------------------------
# Project name derivation
# ---------------------------------------------------------------------------

def _slugify_project_name(name: str) -> str:
    return re.sub(r"[^a-z0-9\-]", "-", str(name or "").lower()).strip("-") or "new-project"


def _derive_project_name(blueprint: dict, user_query: str) -> str:
    name = blueprint.get("project_name", "")
    if name:
        return _slugify_project_name(name)
    # Fallback: first few words of user query
    words = re.sub(r"[^a-zA-Z0-9 ]", "", user_query).split()[:4]
    return _slugify_project_name("-".join(w.lower() for w in words))


def _unique_project_name(base_name: str, state: dict, working_directory: str) -> str:
    run_id = str(state.get("run_id", "") or "").strip()
    suffix = re.sub(r"[^a-zA-Z0-9]+", "", run_id)[-6:]
    if not suffix:
        suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    candidate = f"{base_name}-{suffix}"
    root = Path(working_directory).expanduser().resolve()
    unique = candidate
    counter = 2
    while (root / unique).exists():
        unique = f"{candidate}-{counter}"
        counter += 1
    return unique


# ---------------------------------------------------------------------------
# Main agent function
# ---------------------------------------------------------------------------

def project_blueprint_agent(state):
    """Design a complete project blueprint from a natural-language description."""
    active_task, task_content, _ = begin_agent_session(state, "project_blueprint_agent")
    state["project_blueprint_agent_calls"] = state.get("project_blueprint_agent_calls", 0) + 1
    call_number = state["project_blueprint_agent_calls"]

    description = (
        state.get("blueprint_request")
        or task_content
        or state.get("current_objective")
        or state.get("user_query", "")
    ).strip()
    if not description:
        raise ValueError("project_blueprint_agent requires a project description.")

    working_directory = str(state.get("working_directory", "."))
    raw_context_files: list[str] = []
    for key in ("blueprint_context_files", "coding_context_files", "project_context_files", "context_files"):
        value = state.get(key)
        if isinstance(value, list):
            raw_context_files.extend([str(item) for item in value if str(item).strip()])
        elif isinstance(value, str) and value.strip():
            raw_context_files.append(value)
    context_blob, missing_files, loaded_files = _read_context_files(raw_context_files, working_directory)
    if raw_context_files:
        log_task_update(
            "Blueprint",
            "Context files requested for blueprint generation.",
            f"Requested: {', '.join(raw_context_files)}",
        )
        if loaded_files:
            log_task_update(
                "Blueprint",
                "Context files loaded for blueprint generation.",
                f"Loaded: {', '.join(loaded_files)}",
            )
        if missing_files:
            log_task_update(
                "Blueprint",
                "Missing context files for blueprint generation.",
                f"Missing: {', '.join(missing_files)}",
            )
    if missing_files:
        missing_note = "Missing context files:\n" + "\n".join(f"- {path}" for path in missing_files)
        clarification = (
            "I couldn't find the context files needed to build the blueprint.\n\n"
            f"{missing_note}\n\n"
            "Please fix the path(s) and re-run, or reply with the correct location(s)."
        )
        state["blueprint_missing_context_files"] = missing_files
        state["pending_user_question"] = clarification
        state["pending_user_input_kind"] = "context_missing"
        state["approval_pending_scope"] = "project_blueprint"
        state["blueprint_waiting_for_approval"] = False
        state["blueprint_status"] = "blocked"
        state["draft_response"] = clarification
        log_task_update("Blueprint", "Blueprint blocked due to missing context files.", clarification)
        return state
    if context_blob:
        description = f"{description}\n\nAdditional context from files:\n{context_blob}"

    log_task_update("Blueprint", f"Architecture pass #{call_number} started.")

    # Load stack templates
    stack_requirements = _extract_stack_requirements(description)
    helpers = _load_stack_helpers()
    detected_stack_name = _detect_stack(description)
    stack_template = helpers["load"](detected_stack_name) if detected_stack_name else None
    available_stack_names = helpers["available"]()

    if stack_template:
        log_task_update("Blueprint", f"Detected stack template: {detected_stack_name}")

    # Generate blueprint via LLM
    prompt = _build_blueprint_prompt(description, stack_template, available_stack_names)
    response = llm.invoke(prompt)
    raw_output = response.content if hasattr(response, "content") else str(response)

    # Parse
    try:
        blueprint = _parse_blueprint(raw_output)
    except Exception:
        # Fallback: use stack template as base if available
        if stack_template:
            blueprint = {
                "project_name": "new-project",
                "tech_stack": stack_template.get("tech_stack", {}),
                "directory_structure": stack_template.get("base_directory_structure", []),
                "db_schema": {"tables": []},
                "api_design": {"base_path": "/api", "endpoints": []},
                "frontend_components": {"pages": [], "layouts": [], "components": []},
                "env_vars": stack_template.get("base_env_vars", []),
                "docker_services": stack_template.get("base_docker_services", []),
                "dependencies": stack_template.get("base_dependencies", {}),
            }
        else:
            blueprint = {
                "project_name": "new-project",
                "tech_stack": {"language": "python", "framework": "fastapi", "database": "postgresql"},
                "directory_structure": ["app/", "app/main.py", "tests/"],
                "db_schema": {"tables": []},
                "api_design": {"base_path": "/api", "endpoints": []},
                "frontend_components": {"pages": [], "layouts": [], "components": []},
                "env_vars": [],
                "docker_services": [],
                "dependencies": {"runtime": [], "dev": []},
            }

    if stack_template and not _stack_matches(blueprint, stack_template):
        log_task_update(
            "Blueprint",
            "Detected stack template conflicts with generated blueprint. Applying template defaults.",
            f"template={detected_stack_name}",
        )
        blueprint["tech_stack"] = stack_template.get("tech_stack", {})
        if not blueprint.get("directory_structure"):
            blueprint["directory_structure"] = stack_template.get("base_directory_structure", [])
        if not blueprint.get("env_vars"):
            blueprint["env_vars"] = stack_template.get("base_env_vars", [])
        if not blueprint.get("docker_services"):
            blueprint["docker_services"] = stack_template.get("base_docker_services", [])
        if not blueprint.get("dependencies"):
            blueprint["dependencies"] = stack_template.get("base_dependencies", {})

    if stack_requirements:
        overrides = _apply_stack_requirements(blueprint, stack_requirements)
        if overrides:
            state["blueprint_stack_overrides"] = overrides
            log_task_update(
                "Blueprint",
                "Applied explicit stack requirements from project description/context.",
                json.dumps(overrides, indent=2),
            )

    # Validate
    warnings = _validate_blueprint(blueprint)
    if warnings:
        log_task_update("Blueprint", f"Validation warnings: {'; '.join(warnings)}")

    # Derive project metadata (preserve same root within a run, but always unique per new run)
    existing_root = str(state.get("project_root", "") or "").strip()
    existing_name = str(state.get("project_name", "") or "").strip()
    if existing_root:
        project_root = existing_root
        project_name = existing_name or Path(existing_root).name
        blueprint["project_name"] = project_name
    else:
        base_name = _derive_project_name(blueprint, description)
        project_name = _unique_project_name(base_name, state, working_directory)
        blueprint["project_name"] = project_name
        project_root = str(Path(working_directory) / project_name)

    blueprint_version = int(state.get("blueprint_version", 0) or 0) + 1
    blueprint_md = _blueprint_as_markdown(blueprint)

    # Populate state
    state["blueprint_json"] = blueprint
    state["blueprint_summary"] = blueprint_md
    state["blueprint_tech_stack"] = blueprint.get("tech_stack", {})
    state["blueprint_db_schema"] = blueprint.get("db_schema", {})
    state["blueprint_api_design"] = blueprint.get("api_design", {})
    state["blueprint_frontend_components"] = blueprint.get("frontend_components", {})
    state["blueprint_directory_structure"] = blueprint.get("directory_structure", [])
    state["blueprint_dependencies"] = blueprint.get("dependencies", {})
    state["blueprint_env_vars"] = blueprint.get("env_vars", [])
    state["blueprint_docker_services"] = blueprint.get("docker_services", [])
    if state.get("blueprint_stack_overrides") is None and stack_requirements:
        state["blueprint_stack_overrides"] = dict(stack_requirements)
    state["blueprint_version"] = blueprint_version
    state["blueprint_status"] = "draft"
    state["project_name"] = project_name
    state["project_root"] = project_root
    state["project_stack"] = detected_stack_name or ""
    state["project_build_mode"] = True

    # Set up approval flow (same pattern as planner_agent)
    context_note = ""
    if loaded_files or raw_context_files:
        context_note = f"\n\nContext files loaded: {', '.join(loaded_files) if loaded_files else 'none'}"
    auto_approve = bool(state.get("auto_approve")) or bool(state.get("auto_approve_blueprint"))
    if auto_approve:
        state["pending_user_question"] = ""
        state["pending_user_input_kind"] = ""
        state["approval_pending_scope"] = ""
        state["blueprint_waiting_for_approval"] = False
        state["blueprint_status"] = "approved"
        state["plan_ready"] = False
        state["_skip_review_once"] = True
        state["draft_response"] = blueprint_md
        log_task_update("Blueprint", "Blueprint auto-approved; continuing to planning.")
    else:
        approval_prompt = (
            f"The project blueprint v{blueprint_version} is ready for approval.\n\n"
            f"{blueprint_md}\n\n"
            f"Project will be created at: `{project_root}`"
            f"{context_note}\n\n"
            f"Reply `approve` to proceed with planning and building, "
            f"or describe changes you want and I will regenerate the blueprint."
        )
        state["pending_user_question"] = approval_prompt
        state["pending_user_input_kind"] = "blueprint_approval"
        state["approval_pending_scope"] = "project_blueprint"
        state["blueprint_waiting_for_approval"] = True
        state["plan_ready"] = False
        state["_skip_review_once"] = True
        state["draft_response"] = approval_prompt

    # Persist artifacts
    write_text_file(f"blueprint_output_{call_number}.md", blueprint_md)
    write_text_file(f"blueprint_output_{call_number}.json", json.dumps(blueprint, indent=2, ensure_ascii=False))
    write_text_file(f"blueprint_raw_{call_number}.txt", raw_output)

    log_task_update(
        "Blueprint",
        f"Blueprint v{blueprint_version} saved. Project: {project_name}. Awaiting approval.",
        blueprint_md,
    )

    state = publish_agent_output(
        state,
        "project_blueprint_agent",
        blueprint_md,
        f"blueprint_v{blueprint_version}",
        recipients=["orchestrator_agent", "planner_agent"],
    )
    return state
