"""Auth & Security Agent.

Generates authentication and security modules (JWT auth, middleware, routers)
for supported stacks when missing.
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
    "auth_security_agent": {
        "description": (
            "Implements authentication/security modules (JWT, middleware, routes) "
            "for supported stacks when missing."
        ),
        "skills": ["authentication", "security", "jwt", "middleware"],
        "input_keys": [
            "blueprint_json", "blueprint_tech_stack", "blueprint_api_design", "project_root",
        ],
        "output_keys": ["auth_security_status", "auth_security_files", "auth_security_summary"],
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


def _generate_file(description: str, context: str) -> str:
    prompt = f"""
Generate production-ready code for the following:

{description}

Project context:
{context}

Return ONLY the complete file content. No explanation, no markdown fences.
""".strip()
    response = llm.invoke(prompt)
    raw = normalize_llm_text(response.content if hasattr(response, "content") else response)
    return _strip_code_fences(raw).strip() + "\n"


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


def _auth_already_present(project_root: Path) -> bool:
    candidates = [
        project_root / "services" / "auth-service",
        project_root / "backend" / "services" / "auth-service",
        project_root / "app" / "routes" / "auth",
        project_root / "app" / "routes" / "auth.py",
        project_root / "app" / "routes" / "auth.ts",
        project_root / "src" / "routes" / "auth.ts",
        project_root / "src" / "routes" / "auth.js",
        project_root / "app" / "api" / "auth.py",
    ]
    return any(path.exists() for path in candidates)


def _resolve_backend_root(project_root: Path) -> Path:
    candidates = [
        project_root / "backend",
        project_root / "app",
        project_root,
    ]
    for candidate in candidates:
        if (candidate / "package.json").exists() and (candidate / "src").exists():
            return candidate
    for candidate in candidates:
        if (candidate / "src").exists():
            return candidate
    return project_root


def _find_entry_file(backend_root: Path) -> Path | None:
    for name in ("src/index.ts", "src/index.js", "src/server.ts", "src/server.js", "src/app.ts", "src/app.js"):
        path = backend_root / name
        if path.exists():
            return path
    return None


def _inject_express_auth(entry_path: Path) -> bool:
    try:
        content = entry_path.read_text(encoding="utf-8")
    except Exception:
        return False

    if "authRouter" in content or "/auth" in content:
        return False

    lines = content.splitlines()
    import_line = "import authRouter from \"./routes/auth\";"
    use_line = "app.use(\"/api/auth\", authRouter);"

    # Insert import after last import
    insert_at = 0
    for i, line in enumerate(lines):
        if line.startswith("import "):
            insert_at = i + 1
    lines.insert(insert_at, import_line)

    # Insert use line before app.listen if possible
    listen_idx = None
    for i, line in enumerate(lines):
        if "app.listen" in line:
            listen_idx = i
            break
    if listen_idx is not None:
        lines.insert(listen_idx, use_line)
    else:
        lines.append(use_line)

    entry_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log_file_action("wrote", str(entry_path))
    return True


def _inject_fastapi_auth(main_path: Path) -> bool:
    try:
        content = main_path.read_text(encoding="utf-8")
    except Exception:
        return False

    if "auth" in content and "include_router" in content:
        return False

    lines = content.splitlines()
    import_line = "from app.api.auth import router as auth_router"
    include_line = "app.include_router(auth_router, prefix=\"/auth\", tags=[\"auth\"])"

    insert_at = 0
    for i, line in enumerate(lines):
        if line.startswith("from ") or line.startswith("import "):
            insert_at = i + 1
    lines.insert(insert_at, import_line)

    # Insert before end
    lines.append("")
    lines.append(include_line)

    main_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log_file_action("wrote", str(main_path))
    return True


def auth_security_agent(state: dict) -> dict:
    active_task, task_content, _ = begin_agent_session(state, "auth_security_agent")
    state["auth_security_agent_calls"] = state.get("auth_security_agent_calls", 0) + 1
    call_number = state["auth_security_agent_calls"]

    blueprint = state.get("blueprint_json", {})
    tech_stack = state.get("blueprint_tech_stack") or blueprint.get("tech_stack", {})
    api_design = state.get("blueprint_api_design") or blueprint.get("api_design", {})
    project_root = Path(state.get("project_root", "")).resolve()

    if not project_root or str(project_root) == ".":
        raise ValueError("auth_security_agent requires project_root in state.")

    auth_strategy = str(tech_stack.get("auth", "jwt") or "jwt").lower()
    if auth_strategy in {"none", "", "false"}:
        state["auth_security_status"] = "skipped"
        state["auth_security_files"] = []
        state["auth_security_summary"] = "Auth strategy set to none. Skipped."
        state["draft_response"] = state["auth_security_summary"]
        state["_skip_review_once"] = True
        return publish_agent_output(
            state,
            "auth_security_agent",
            state["auth_security_summary"],
            f"auth_security_result_{call_number}",
            recipients=["orchestrator_agent"],
        )

    privileged_policy = build_privileged_policy(state)
    log_task_update("Auth", f"Auth/security pass #{call_number} started.")
    preserve_existing = bool(state.get("scaffold_template_used", False))

    if preserve_existing and _auth_already_present(project_root):
        summary = "Auth modules already present. Skipped to preserve template."
        state["auth_security_status"] = "skipped"
        state["auth_security_files"] = []
        state["auth_security_summary"] = summary
        state["draft_response"] = summary
        state["_skip_review_once"] = True
        return publish_agent_output(
            state,
            "auth_security_agent",
            summary,
            f"auth_security_result_{call_number}",
            recipients=["orchestrator_agent"],
        )

    created_files: list[str] = []
    language = str(tech_stack.get("language", "")).lower()
    framework = str(tech_stack.get("framework", "")).lower()

    context = json.dumps({
        "tech_stack": tech_stack,
        "api_design": api_design,
        "auth_strategy": auth_strategy,
    }, indent=2, ensure_ascii=False)

    if "python" in language or "fastapi" in framework:
        # FastAPI auth module
        auth_content = _generate_file(
            "Generate a FastAPI auth router with JWT login/register endpoints and password hashing.",
            context,
        )
        path, written = _write_project_file(
            project_root,
            "app/api/auth.py" if (project_root / "app").exists() else "app/api/auth.py",
            auth_content,
            privileged_policy,
            overwrite=not preserve_existing,
        )
        if written:
            created_files.append(path)

        security_content = _generate_file(
            "Generate a security helper module for JWT token creation/verification and password hashing.",
            context,
        )
        path, written = _write_project_file(
            project_root,
            "app/core/security.py",
            security_content,
            privileged_policy,
            overwrite=not preserve_existing,
        )
        if written:
            created_files.append(path)

        main_path = project_root / "app" / "main.py"
        if main_path.exists():
            _inject_fastapi_auth(main_path)

    else:
        # Node/Express auth module
        backend_root = _resolve_backend_root(project_root)
        routes_path = backend_root / "src" / "routes" / "auth.ts"
        middleware_path = backend_root / "src" / "middleware" / "auth.ts"
        service_path = backend_root / "src" / "services" / "auth.ts"

        routes_content = _generate_file(
            "Generate an Express router for /auth endpoints (register, login, refresh) using JWT.",
            context,
        )
        path, written = _write_project_file(
            project_root,
            str(routes_path.relative_to(project_root)),
            routes_content,
            privileged_policy,
            overwrite=not preserve_existing,
        )
        if written:
            created_files.append(path)

        middleware_content = _generate_file(
            "Generate Express middleware that validates JWT tokens and attaches the user to request.",
            context,
        )
        path, written = _write_project_file(
            project_root,
            str(middleware_path.relative_to(project_root)),
            middleware_content,
            privileged_policy,
            overwrite=not preserve_existing,
        )
        if written:
            created_files.append(path)

        service_content = _generate_file(
            "Generate auth service helpers for hashing passwords and issuing JWT tokens.",
            context,
        )
        path, written = _write_project_file(
            project_root,
            str(service_path.relative_to(project_root)),
            service_content,
            privileged_policy,
            overwrite=not preserve_existing,
        )
        if written:
            created_files.append(path)

        entry = _find_entry_file(backend_root)
        if entry:
            _inject_express_auth(entry)

    summary = (
        f"Auth/security generation {'completed' if created_files else 'skipped'} with {len(created_files)} file(s)."
    )

    state["auth_security_status"] = "completed" if created_files else "skipped"
    state["auth_security_files"] = created_files
    state["auth_security_summary"] = summary
    state["draft_response"] = summary

    append_privileged_audit_event(
        state,
        actor="auth_security_agent",
        action="auth_security",
        status=state["auth_security_status"],
        detail={"file_count": len(created_files)},
    )
    write_text_file(f"auth_security_output_{call_number}.txt", summary + "\n" + "\n".join(created_files))
    log_task_update("Auth", summary)

    state = publish_agent_output(
        state,
        "auth_security_agent",
        summary,
        f"auth_security_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent"],
    )
    return state
