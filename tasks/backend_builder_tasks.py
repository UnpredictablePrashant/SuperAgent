"""Backend Builder Agent.

Implements API routes, service layer, middleware, authentication, and
database connection setup based on the project blueprint.
"""

import json
from pathlib import Path

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.privileged_control import (
    append_privileged_audit_event,
    build_privileged_policy,
    path_allowed,
)
from tasks.utils import OUTPUT_DIR, llm, log_file_action, log_task_update, normalize_llm_text, write_text_file


AGENT_METADATA = {
    "backend_builder_agent": {
        "description": (
            "Implements API routes, service layer, middleware, authentication, "
            "and database connection from the project blueprint."
        ),
        "skills": ["backend development", "api implementation", "authentication", "middleware"],
        "input_keys": [
            "blueprint_json", "blueprint_api_design", "blueprint_db_schema",
            "blueprint_tech_stack", "project_root", "db_architect_models",
        ],
        "output_keys": ["backend_builder_status", "backend_builder_files", "backend_builder_summary"],
        "requirements": [],
    },
}


def _strip_code_fences(text: str) -> str:
    stripped = normalize_llm_text(text).strip()
    if stripped.startswith("```") and stripped.endswith("```"):
        lines = stripped.splitlines()
        if len(lines) >= 2:
            return "\n".join(lines[1:-1]).strip()
    return stripped


def _generate_file(description: str, context: str, existing_code: str = "") -> str:
    """Generate a single code file via LLM."""
    existing_section = ""
    if existing_code:
        existing_section = "Related existing code for reference and imports:" + chr(10) + existing_code
    prompt = f"""
Generate production-ready code for the following:

{description}

Project context:
{context}

{existing_section}

Return ONLY the complete file content. No explanation, no markdown fences.
Ensure proper imports, error handling, and type annotations.
""".strip()
    response = llm.invoke(prompt)
    raw = normalize_llm_text(response.content if hasattr(response, "content") else response)
    return _strip_code_fences(raw).strip() + "\n"


def _write_file(root: Path, relative_path: str, content: str, policy: dict, *, overwrite: bool = True) -> tuple[str, bool]:
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


def _read_file_safe(path: str) -> str:
    try:
        return Path(path).read_text(encoding="utf-8")
    except Exception:
        return ""


def _resolve_backend_dir(tech_stack: dict) -> str:
    """Determine the backend source directory prefix."""
    language = str(tech_stack.get("language", "")).lower()
    if "+" in language:
        return "backend/app"
    return "app"


def backend_builder_agent(state):
    """Implement the backend API layer from the blueprint."""
    active_task, task_content, _ = begin_agent_session(state, "backend_builder_agent")
    state["backend_builder_agent_calls"] = state.get("backend_builder_agent_calls", 0) + 1
    call_number = state["backend_builder_agent_calls"]

    blueprint = state.get("blueprint_json", {})
    api_design = state.get("blueprint_api_design") or blueprint.get("api_design", {})
    db_schema = state.get("blueprint_db_schema") or blueprint.get("db_schema", {})
    tech_stack = state.get("blueprint_tech_stack") or blueprint.get("tech_stack", {})
    project_root = Path(state.get("project_root", "")).resolve()

    if not project_root or str(project_root) == ".":
        raise ValueError("backend_builder_agent requires project_root in state.")

    privileged_policy = build_privileged_policy(state)
    log_task_update("Backend Builder", f"Backend implementation pass #{call_number} started.")
    preserve_existing = bool(state.get("scaffold_template_used", False))

    created_files: list[str] = []
    backend_dir = _resolve_backend_dir(tech_stack)
    framework = tech_stack.get("framework", "fastapi").split("+")[0]
    orm = tech_stack.get("orm", "sqlalchemy")

    # Read existing model code for reference
    model_files = state.get("db_architect_models", [])
    model_code = "\n\n".join(_read_file_safe(f) for f in model_files if f)

    context = json.dumps({
        "tech_stack": tech_stack,
        "api_design": api_design,
        "db_schema": db_schema,
        "framework": framework,
        "orm": orm,
    }, indent=2, ensure_ascii=False)

    # 1. Main entry point / app factory
    main_content = _generate_file(
        f"Generate the main application entry point for {framework}. "
        f"Include CORS middleware, error handlers, router registration, and a /health endpoint. "
        f"Import and include all API route modules.",
        context, model_code,
    )
    path, written = _write_file(
        project_root,
        f"{backend_dir}/main.py",
        main_content,
        privileged_policy,
        overwrite=not preserve_existing,
    )
    if written:
        created_files.append(path)

    # 2. Config module
    config_content = _generate_file(
        f"Generate the application configuration module. "
        f"Load settings from environment variables using pydantic-settings (if Python) or dotenv. "
        f"Include DATABASE_URL, SECRET_KEY, and other vars from the blueprint.",
        context,
    )
    path, written = _write_file(
        project_root,
        f"{backend_dir}/core/config.py",
        config_content,
        privileged_policy,
        overwrite=not preserve_existing,
    )
    if written:
        created_files.append(path)

    # 3. Security / Auth module
    auth_strategy = tech_stack.get("auth", "jwt")
    if auth_strategy and auth_strategy != "none":
        auth_content = _generate_file(
            f"Generate the authentication module using {auth_strategy}. "
            f"Include token creation, verification, password hashing, and auth dependency/middleware. "
            f"Framework: {framework}.",
            context, model_code,
        )
        path, written = _write_file(
            project_root,
            f"{backend_dir}/core/security.py",
            auth_content,
            privileged_policy,
            overwrite=not preserve_existing,
        )
        if written:
            created_files.append(path)

    # 4. Schemas / DTOs
    schemas_content = _generate_file(
        f"Generate Pydantic schemas (or TypeScript types) for ALL entities in the database schema. "
        f"Include Create, Update, and Response schemas for each entity. "
        f"Framework: {framework}, ORM: {orm}.",
        context, model_code,
    )
    schemas_dir = f"{backend_dir}/schemas" if "python" in str(tech_stack.get("language", "")).lower() else f"src/types"
    path, written = _write_file(
        project_root,
        f"{schemas_dir}/schemas.py" if "python" in str(tech_stack.get("language", "")).lower() else f"{schemas_dir}/index.ts",
        schemas_content,
        privileged_policy,
        overwrite=not preserve_existing,
    )
    if written:
        created_files.append(path)

    # 5. Route handlers - group by entity
    endpoints = api_design.get("endpoints", [])
    entities = set()
    for ep in endpoints:
        parts = ep.get("path", "").strip("/").split("/")
        if len(parts) >= 2:
            entities.add(parts[1])  # e.g., /api/users -> users

    if not entities:
        entities = {"main"}

    for entity in sorted(entities):
        entity_endpoints = [ep for ep in endpoints if f"/{entity}" in ep.get("path", "")]
        routes_content = _generate_file(
            f"Generate the complete route handler module for the '{entity}' entity. "
            f"Implement ALL these endpoints: {json.dumps(entity_endpoints, ensure_ascii=False)}. "
            f"Include proper request validation, error handling, and auth checks. "
            f"Framework: {framework}, ORM: {orm}.",
            context, model_code,
        )
        routes_dir = f"{backend_dir}/api/routes" if "python" in str(tech_stack.get("language", "")).lower() else "src/routes"
        ext = ".py" if "python" in str(tech_stack.get("language", "")).lower() else ".ts"
        path, written = _write_file(
            project_root,
            f"{routes_dir}/{entity}{ext}",
            routes_content,
            privileged_policy,
            overwrite=not preserve_existing,
        )
        if written:
            created_files.append(path)

    # 6. Service layer
    for entity in sorted(entities):
        service_content = _generate_file(
            f"Generate the service/business-logic module for the '{entity}' entity. "
            f"Include CRUD operations and any business rules. "
            f"Use {orm} for database access. Framework: {framework}.",
            context, model_code,
        )
        services_dir = f"{backend_dir}/services" if "python" in str(tech_stack.get("language", "")).lower() else "src/services"
        ext = ".py" if "python" in str(tech_stack.get("language", "")).lower() else ".ts"
        path, written = _write_file(
            project_root,
            f"{services_dir}/{entity}_service{ext}",
            service_content,
            privileged_policy,
            overwrite=not preserve_existing,
        )
        if written:
            created_files.append(path)

    # 7. Dependencies / middleware
    deps_content = _generate_file(
        f"Generate the dependency injection / middleware module for {framework}. "
        f"Include database session dependency, current-user dependency, and common middleware. "
        f"ORM: {orm}.",
        context, model_code,
    )
    deps_file = f"{backend_dir}/api/deps.py" if "python" in str(tech_stack.get("language", "")).lower() else "src/middleware/index.ts"
    path, written = _write_file(
        project_root,
        deps_file,
        deps_content,
        privileged_policy,
        overwrite=not preserve_existing,
    )
    if written:
        created_files.append(path)

    # Summary
    summary = (
        f"Backend implementation for {state.get('project_name', 'project')}:\n"
        f"  Framework: {framework}\n"
        f"  Entities: {', '.join(sorted(entities))}\n"
        f"  Files generated: {len(created_files)}\n"
        f"  Auth: {auth_strategy}"
    )
    state["backend_builder_status"] = "completed"
    state["backend_builder_files"] = created_files
    state["backend_builder_summary"] = summary
    state["draft_response"] = summary

    append_privileged_audit_event(
        state,
        actor="backend_builder_agent",
        action="backend_build",
        status="completed",
        detail={"files": created_files, "entities": sorted(entities)},
    )
    write_text_file(f"backend_builder_output_{call_number}.txt", summary + "\n\n" + "\n".join(created_files))
    log_task_update("Backend Builder", "Backend implementation complete.", summary)

    state = publish_agent_output(
        state,
        "backend_builder_agent",
        summary,
        f"backend_builder_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent"],
    )
    return state
