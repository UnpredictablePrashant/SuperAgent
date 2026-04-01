"""DevOps Agent.

Generates production Dockerfile, full-stack docker-compose, CI/CD pipelines,
reverse proxy config, and environment management for the project.
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
    "devops_agent": {
        "description": (
            "Generates production Dockerfile, full-stack docker-compose, "
            "CI/CD pipelines, reverse proxy, and environment configs."
        ),
        "skills": ["devops", "docker", "ci/cd", "deployment", "infrastructure"],
        "input_keys": [
            "blueprint_json", "project_root", "project_name",
            "backend_builder_files", "frontend_builder_files",
        ],
        "output_keys": ["devops_status", "devops_files", "devops_summary"],
        "requirements": [],
        "display_name": "DevOps Agent",
        "category": "infra",
        "intent_patterns": [
            "generate dockerfile", "create docker-compose", "setup CI/CD",
            "create github actions", "write nginx config", "containerize app",
        ],
        "active_when": [],
        "config_hint": "",
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
Generate production-ready configuration for the following:

{description}

Project context:
{context}

Return ONLY the file content. No explanation, no markdown fences.
Follow best practices for production deployments.
""".strip()
    response = llm.invoke(prompt)
    raw = response.content if hasattr(response, "content") else str(response)
    return _strip_code_fences(raw).strip() + "\n"


def _write_file(root: Path, relative_path: str, content: str, policy: dict) -> str:
    target = root / relative_path
    if not path_allowed(str(target), policy.get("allowed_paths", [])):
        raise PermissionError(f"Write blocked: {target} outside allowed scope.")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    log_file_action("wrote", str(target))
    return str(target)


def devops_agent(state):
    """Generate deployment infrastructure files."""
    active_task, task_content, _ = begin_agent_session(state, "devops_agent")
    state["devops_agent_calls"] = state.get("devops_agent_calls", 0) + 1
    call_number = state["devops_agent_calls"]

    blueprint = state.get("blueprint_json", {})
    tech_stack = blueprint.get("tech_stack", {})
    docker_services = blueprint.get("docker_services", [])
    env_vars = blueprint.get("env_vars", [])
    project_root = Path(state.get("project_root", "")).resolve()
    project_name = state.get("project_name", "app")

    if not project_root or str(project_root) == ".":
        raise ValueError("devops_agent requires project_root in state.")

    privileged_policy = build_privileged_policy(state)
    log_task_update("DevOps", f"Infrastructure generation pass #{call_number} started.")

    created_files: list[str] = []
    language = str(tech_stack.get("language", "")).lower()
    framework = str(tech_stack.get("framework", "")).lower()

    context = json.dumps({
        "project_name": project_name,
        "tech_stack": tech_stack,
        "docker_services": docker_services,
        "env_vars": env_vars,
        "directory_structure": blueprint.get("directory_structure", []),
    }, indent=2, ensure_ascii=False)

    # 1. Production Dockerfile(s)
    if "python" in language or "fastapi" in framework or "django" in framework or "flask" in framework:
        dockerfile_content = _generate_file(
            f"Generate a production multi-stage Dockerfile for a {framework} Python application. "
            f"Use python:3.12-slim as base. Include: non-root user, health check, "
            f"pip install from requirements.txt, proper ENTRYPOINT with uvicorn/gunicorn.",
            context,
        )
        if "+" in language:
            path = _write_file(project_root, "docker/backend.Dockerfile", dockerfile_content, privileged_policy)
        else:
            path = _write_file(project_root, "Dockerfile", dockerfile_content, privileged_policy)
        created_files.append(path)

    if "typescript" in language or "nextjs" in framework or "react" in framework:
        frontend_dockerfile = _generate_file(
            f"Generate a production multi-stage Dockerfile for a {framework} application. "
            f"Use node:20-alpine. Include: npm ci, build step, serve with nginx or standalone. "
            f"Optimize for small image size.",
            context,
        )
        if "+" in language:
            path = _write_file(project_root, "docker/frontend.Dockerfile", frontend_dockerfile, privileged_policy)
        elif "python" not in language:
            path = _write_file(project_root, "Dockerfile", frontend_dockerfile, privileged_policy)
        else:
            path = _write_file(project_root, "docker/frontend.Dockerfile", frontend_dockerfile, privileged_policy)
        created_files.append(path)

    # 2. Full-stack docker-compose for production
    compose_content = _generate_file(
        f"Generate a production docker-compose.yml that includes: "
        f"1) All database services: {json.dumps([s.get('name') for s in docker_services])} "
        f"2) The application service(s) built from the Dockerfile(s) "
        f"3) An nginx reverse proxy "
        f"4) Proper networking, volumes, restart policies, and health checks. "
        f"Use environment variable substitution for secrets.",
        context,
    )
    path = _write_file(project_root, "docker/docker-compose.prod.yml", compose_content, privileged_policy)
    created_files.append(path)

    # 3. Nginx configuration
    nginx_content = _generate_file(
        f"Generate an nginx.conf for reverse proxying the {framework} application. "
        f"Include: SSL-ready server block, gzip compression, static file caching, "
        f"proxy headers, websocket support (if applicable), rate limiting.",
        context,
    )
    path = _write_file(project_root, "docker/nginx.conf", nginx_content, privileged_policy)
    created_files.append(path)

    # 4. GitHub Actions CI/CD
    ci_content = _generate_file(
        f"Generate a GitHub Actions CI/CD workflow (.github/workflows/ci.yml) for a {framework} project. "
        f"Include: "
        f"1) Lint and type check on pull requests "
        f"2) Run tests "
        f"3) Build Docker image "
        f"4) Push to container registry on main branch merge "
        f"Language: {language}. Use appropriate setup actions.",
        context,
    )
    path = _write_file(project_root, ".github/workflows/ci.yml", ci_content, privileged_policy)
    created_files.append(path)

    # 5. Environment management
    for env_name in ["development", "staging", "production"]:
        env_content_lines = [f"# {env_name.upper()} environment", ""]
        for ev in env_vars:
            name = ev.get("name", "")
            desc = ev.get("description", "")
            example = ev.get("example_value", "")
            if desc:
                env_content_lines.append(f"# {desc}")
            if env_name == "production":
                env_content_lines.append(f"{name}=")
            else:
                env_content_lines.append(f"{name}={example}")
            env_content_lines.append("")

        env_content = "\n".join(env_content_lines)
        path = _write_file(project_root, f"docker/.env.{env_name}", env_content, privileged_policy)
        created_files.append(path)

    # 6. Makefile for common operations
    makefile_content = _generate_file(
        f"Generate a Makefile with targets for: "
        f"dev (start development), build (build containers), up (start production), "
        f"down (stop), logs, migrate, seed, lint, test, clean. "
        f"Project: {framework} with {tech_stack.get('database', 'postgresql')}.",
        context,
    )
    path = _write_file(project_root, "Makefile", makefile_content, privileged_policy)
    created_files.append(path)

    # Summary
    summary = (
        f"DevOps infrastructure for {project_name}:\n"
        f"  Dockerfiles: {'backend + frontend' if '+' in language else '1'}\n"
        f"  Docker Compose (prod): generated\n"
        f"  Nginx: configured\n"
        f"  CI/CD: GitHub Actions\n"
        f"  Env configs: development, staging, production\n"
        f"  Makefile: generated\n"
        f"  Total files: {len(created_files)}"
    )
    state["devops_status"] = "completed"
    state["devops_files"] = created_files
    state["devops_summary"] = summary
    state["draft_response"] = summary

    append_privileged_audit_event(
        state,
        actor="devops_agent",
        action="devops_generation",
        status="completed",
        detail={"files": created_files},
    )
    write_text_file(f"devops_output_{call_number}.txt", summary + "\n\n" + "\n".join(created_files))
    log_task_update("DevOps", "DevOps infrastructure generation complete.", summary)

    state = publish_agent_output(
        state,
        "devops_agent",
        summary,
        f"devops_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent"],
    )
    return state
