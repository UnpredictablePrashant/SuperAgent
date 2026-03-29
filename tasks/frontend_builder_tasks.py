"""Frontend Builder Agent.

Implements pages, layouts, UI components, API client, state management,
and styling configuration based on the project blueprint.
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
    "frontend_builder_agent": {
        "description": (
            "Implements frontend pages, layouts, UI components, API client, "
            "state management, and styling from the project blueprint."
        ),
        "skills": ["frontend development", "react", "ui components", "state management"],
        "input_keys": [
            "blueprint_json", "blueprint_frontend_components", "blueprint_api_design",
            "blueprint_tech_stack", "project_root",
        ],
        "output_keys": ["frontend_builder_status", "frontend_builder_files", "frontend_builder_summary"],
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
Use modern patterns, proper TypeScript types, and clean component structure.
""".strip()
    response = llm.invoke(prompt)
    raw = response.content if hasattr(response, "content") else str(response)
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


def _resolve_frontend_dir(tech_stack: dict) -> str:
    """Determine the frontend source directory prefix."""
    language = str(tech_stack.get("language", "")).lower()
    framework = str(tech_stack.get("framework", "")).lower()
    if "+" in language or "+" in framework:
        return "frontend/src"
    if "nextjs" in framework or "next" in framework:
        return "src"
    return "src"


def frontend_builder_agent(state):
    """Implement the frontend UI layer from the blueprint."""
    active_task, task_content, _ = begin_agent_session(state, "frontend_builder_agent")
    state["frontend_builder_agent_calls"] = state.get("frontend_builder_agent_calls", 0) + 1
    call_number = state["frontend_builder_agent_calls"]

    blueprint = state.get("blueprint_json", {})
    frontend_components = state.get("blueprint_frontend_components") or blueprint.get("frontend_components", {})
    api_design = state.get("blueprint_api_design") or blueprint.get("api_design", {})
    tech_stack = state.get("blueprint_tech_stack") or blueprint.get("tech_stack", {})
    project_root = Path(state.get("project_root", "")).resolve()

    # Skip if no frontend components defined
    pages = frontend_components.get("pages", [])
    layouts = frontend_components.get("layouts", [])
    components = frontend_components.get("components", [])
    if not pages and not layouts and not components:
        state["frontend_builder_status"] = "skipped"
        state["frontend_builder_files"] = []
        state["frontend_builder_summary"] = "No frontend components in blueprint. Skipped."
        state["draft_response"] = state["frontend_builder_summary"]
        state["_skip_review_once"] = True
        return publish_agent_output(
            state, "frontend_builder_agent",
            state["frontend_builder_summary"],
            f"frontend_builder_result_{call_number}",
            recipients=["orchestrator_agent"],
        )

    if not project_root or str(project_root) == ".":
        raise ValueError("frontend_builder_agent requires project_root in state.")

    privileged_policy = build_privileged_policy(state)
    log_task_update("Frontend Builder", f"Frontend implementation pass #{call_number} started.")
    preserve_existing = bool(state.get("scaffold_template_used", False))

    created_files: list[str] = []
    frontend_dir = _resolve_frontend_dir(tech_stack)
    framework = str(tech_stack.get("framework", "react")).lower()
    css_framework = tech_stack.get("css", "tailwindcss")

    context = json.dumps({
        "tech_stack": tech_stack,
        "api_design": api_design,
        "frontend_components": frontend_components,
        "css_framework": css_framework,
    }, indent=2, ensure_ascii=False)

    # 1. API client
    api_client_content = _generate_file(
        f"Generate an API client module that provides typed functions for ALL these endpoints: "
        f"{json.dumps(api_design.get('endpoints', []), ensure_ascii=False)}. "
        f"Use fetch or axios. Include auth token handling. Export typed functions like getUsers(), createUser(), etc.",
        context,
    )
    path, written = _write_file(
        project_root,
        f"{frontend_dir}/lib/api.ts",
        api_client_content,
        privileged_policy,
        overwrite=not preserve_existing,
    )
    if written:
        created_files.append(path)

    # 2. TypeScript types
    types_content = _generate_file(
        "Generate TypeScript type definitions for ALL entities used in the API. "
        "Include request/response types matching the API design.",
        context,
    )
    path, written = _write_file(
        project_root,
        f"{frontend_dir}/types/index.ts",
        types_content,
        privileged_policy,
        overwrite=not preserve_existing,
    )
    if written:
        created_files.append(path)

    # 3. Layouts
    for layout in layouts:
        layout_name = layout.get("name", "MainLayout")
        layout_content = _generate_file(
            f"Generate a React layout component called '{layout_name}'. "
            f"Description: {layout.get('description', 'Main application layout')}. "
            f"Use {css_framework or 'CSS modules'} for styling. Include responsive design.",
            context,
        )
        path, written = _write_file(
            project_root,
            f"{frontend_dir}/components/{layout_name}.tsx",
            layout_content,
            privileged_policy,
            overwrite=not preserve_existing,
        )
        if written:
            created_files.append(path)

    # 4. Pages
    for page in pages:
        page_name = page.get("name", "Page")
        page_content = _generate_file(
            f"Generate a React page component called '{page_name}'. "
            f"Route: {page.get('route', '/')}. "
            f"Description: {page.get('description', '')}. "
            f"Use the API client for data fetching. Use {css_framework or 'CSS'} for styling. "
            f"Include loading states and error handling.",
            context,
        )
        # Determine file path based on framework
        if "next" in framework:
            route = page.get("route", "/").strip("/")
            page_dir = f"{frontend_dir}/app/{route}" if route else f"{frontend_dir}/app"
            file_name = "page.tsx"
        else:
            page_dir = f"{frontend_dir}/pages"
            file_name = f"{page_name}.tsx"
        path, written = _write_file(
            project_root,
            f"{page_dir}/{file_name}",
            page_content,
            privileged_policy,
            overwrite=not preserve_existing,
        )
        if written:
            created_files.append(path)

    # 5. UI Components
    for comp in components:
        comp_name = comp.get("name", "Component")
        comp_content = _generate_file(
            f"Generate a React component called '{comp_name}'. "
            f"Description: {comp.get('description', '')}. "
            f"Use {css_framework or 'CSS'} for styling. Include TypeScript props interface.",
            context,
        )
        path, written = _write_file(
            project_root,
            f"{frontend_dir}/components/{comp_name}.tsx",
            comp_content,
            privileged_policy,
            overwrite=not preserve_existing,
        )
        if written:
            created_files.append(path)

    # 6. App root / routing
    app_content = _generate_file(
        f"Generate the main App component with routing setup. "
        f"Include routes for all pages: {json.dumps([p.get('route', '/') for p in pages])}. "
        f"Import and use the main layout. Framework: {framework}.",
        context,
    )
    if "next" in framework:
        path, written = _write_file(
            project_root,
            f"{frontend_dir}/app/layout.tsx",
            app_content,
            privileged_policy,
            overwrite=not preserve_existing,
        )
    else:
        path, written = _write_file(
            project_root,
            f"{frontend_dir}/App.tsx",
            app_content,
            privileged_policy,
            overwrite=not preserve_existing,
        )
    if written:
        created_files.append(path)

    # 7. Global styles
    styles_content = _generate_file(
        f"Generate the global CSS file for the application using {css_framework or 'plain CSS'}. "
        f"Include CSS reset, base typography, and utility classes.",
        context,
    )
    ext = ".css"
    path, written = _write_file(
        project_root,
        f"{frontend_dir}/index{ext}" if "next" not in framework else f"{frontend_dir}/app/globals.css",
        styles_content,
        privileged_policy,
        overwrite=not preserve_existing,
    )
    if written:
        created_files.append(path)

    # Summary
    summary = (
        f"Frontend implementation for {state.get('project_name', 'project')}:\n"
        f"  Framework: {framework}\n"
        f"  CSS: {css_framework or 'plain CSS'}\n"
        f"  Pages: {len(pages)}\n"
        f"  Components: {len(components)}\n"
        f"  Layouts: {len(layouts)}\n"
        f"  Files generated: {len(created_files)}"
    )
    state["frontend_builder_status"] = "completed"
    state["frontend_builder_files"] = created_files
    state["frontend_builder_summary"] = summary
    state["draft_response"] = summary

    append_privileged_audit_event(
        state,
        actor="frontend_builder_agent",
        action="frontend_build",
        status="completed",
        detail={"files": created_files, "pages": len(pages), "components": len(components)},
    )
    write_text_file(f"frontend_builder_output_{call_number}.txt", summary + "\n\n" + "\n".join(created_files))
    log_task_update("Frontend Builder", "Frontend implementation complete.", summary)

    state = publish_agent_output(
        state,
        "frontend_builder_agent",
        summary,
        f"frontend_builder_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent"],
    )
    return state
