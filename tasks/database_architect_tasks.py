"""Database Architect Agent.

Generates ORM models, migration files, Docker database services,
and seed data scripts based on the project blueprint.
"""

import json
import os
import subprocess
from pathlib import Path

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.privileged_control import (
    append_privileged_audit_event,
    build_privileged_policy,
    path_allowed,
)
from tasks.utils import OUTPUT_DIR, llm, log_file_action, log_task_update, normalize_llm_text, write_text_file


AGENT_METADATA = {
    "database_architect_agent": {
        "description": (
            "Generates ORM models, database migrations, Docker DB containers, "
            "and seed data scripts from the project blueprint."
        ),
        "skills": ["database design", "ORM generation", "migrations", "docker", "seed data"],
        "input_keys": [
            "blueprint_json", "blueprint_db_schema", "blueprint_tech_stack",
            "blueprint_docker_services", "project_root",
        ],
        "output_keys": [
            "db_architect_status", "db_architect_models", "db_architect_migrations",
            "db_architect_seed_script", "db_architect_docker_status", "db_architect_summary",
        ],
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


def _generate_code_file(description: str, tech_context: str, existing_code: str = "") -> str:
    """Use LLM to generate a single code file."""
    existing_section = ""
    if existing_code:
        existing_section = "Existing related code for reference:" + chr(10) + existing_code
    prompt = f"""
Generate production-ready code for the following:

{description}

Technical context:
{tech_context}

{existing_section}

Return ONLY the file content. No explanation, no markdown fences.
""".strip()
    response = llm.invoke(prompt)
    raw = normalize_llm_text(response.content if hasattr(response, "content") else response)
    return _strip_code_fences(raw).strip() + "\n"


def _write_project_file(root: Path, relative_path: str, content: str, policy: dict, *, overwrite: bool = True) -> tuple[str, bool]:
    """Write a file into the project directory with policy checks."""
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


def _generate_docker_compose(docker_services: list[dict], project_name: str) -> str:
    """Generate a docker-compose.yml for the project's database services."""
    services = {}
    volumes = {}
    for svc in docker_services:
        name = svc.get("name", "db")
        service_def: dict = {"image": svc.get("image", "postgres:16-alpine"), "restart": "unless-stopped"}
        if svc.get("ports"):
            service_def["ports"] = svc["ports"]
        if svc.get("env"):
            service_def["environment"] = svc["env"]
        if svc.get("volumes"):
            service_def["volumes"] = svc["volumes"]
            for vol in svc["volumes"]:
                vol_name = vol.split(":")[0]
                if "/" not in vol_name:
                    volumes[vol_name] = {"driver": "local"}
        services[name] = service_def

    compose = {"version": "3.8", "services": services}
    if volumes:
        compose["volumes"] = volumes

    # Use YAML-like JSON formatting since we don't want to add pyyaml dependency
    return _dict_to_yaml(compose)


def _dict_to_yaml(data: dict, indent: int = 0) -> str:
    """Simple dict-to-YAML serializer for docker-compose."""
    lines: list[str] = []
    prefix = "  " * indent
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"{prefix}{key}:")
            lines.append(_dict_to_yaml(value, indent + 1))
        elif isinstance(value, list):
            lines.append(f"{prefix}{key}:")
            for item in value:
                if isinstance(item, dict):
                    lines.append(f"{prefix}  -")
                    lines.append(_dict_to_yaml(item, indent + 2))
                else:
                    lines.append(f"{prefix}  - {item}")
        else:
            lines.append(f"{prefix}{key}: {value}")
    return "\n".join(lines)


def _start_db_containers(project_root: Path) -> tuple[bool, str]:
    """Attempt to start database containers via docker-compose."""
    compose_path = project_root / "docker-compose.yml"
    if not compose_path.exists():
        return False, "docker-compose.yml not found"

    try:
        result = subprocess.run(
            ["docker-compose", "up", "-d"],
            capture_output=True,
            text=True,
            cwd=str(project_root),
            timeout=120,
            check=False,
        )
        if result.returncode == 0:
            return True, result.stdout.strip() or "Containers started."
        # Try docker compose (v2) as fallback
        result2 = subprocess.run(
            ["docker", "compose", "up", "-d"],
            capture_output=True,
            text=True,
            cwd=str(project_root),
            timeout=120,
            check=False,
        )
        if result2.returncode == 0:
            return True, result2.stdout.strip() or "Containers started."
        return False, result.stderr.strip() or result2.stderr.strip() or "docker-compose failed"
    except FileNotFoundError:
        return False, "Docker/docker-compose not found on this system. Database containers will need to be started manually."
    except Exception as exc:
        return False, f"Failed to start containers: {exc}"


def database_architect_agent(state):
    """Generate database models, migrations, and Docker services."""
    active_task, task_content, _ = begin_agent_session(state, "database_architect_agent")
    state["database_architect_agent_calls"] = state.get("database_architect_agent_calls", 0) + 1
    call_number = state["database_architect_agent_calls"]

    blueprint = state.get("blueprint_json", {})
    db_schema = state.get("blueprint_db_schema") or blueprint.get("db_schema", {})
    tech_stack = state.get("blueprint_tech_stack") or blueprint.get("tech_stack", {})
    docker_services = state.get("blueprint_docker_services") or blueprint.get("docker_services", [])
    project_root = Path(state.get("project_root", "")).resolve()
    project_name = state.get("project_name", "app")

    if not project_root or str(project_root) == ".":
        raise ValueError("database_architect_agent requires project_root in state.")

    privileged_policy = build_privileged_policy(state)
    log_task_update("DB Architect", f"Database architecture pass #{call_number} started.")
    preserve_existing = bool(state.get("scaffold_template_used", False))

    created_files: list[str] = []
    tech_context = json.dumps({"tech_stack": tech_stack, "db_schema": db_schema}, indent=2, ensure_ascii=False)

    # 1. Generate docker-compose.yml for DB services
    if docker_services:
        compose_content = _generate_docker_compose(docker_services, project_name)
        compose_path, written = _write_project_file(
            project_root,
            "docker-compose.yml",
            compose_content,
            privileged_policy,
            overwrite=not preserve_existing,
        )
        if written:
            created_files.append(compose_path)
        log_task_update("DB Architect", "Generated docker-compose.yml for database services.")

    # 2. Generate ORM models
    orm = tech_stack.get("orm", "sqlalchemy")
    framework = tech_stack.get("framework", "fastapi")
    language = str(tech_stack.get("language", "python")).lower()

    if "prisma" in orm:
        # Generate Prisma schema
        schema_content = _generate_code_file(
            f"Generate a complete Prisma schema file (schema.prisma) with the following tables and relationships. "
            f"Include a generator client block and a datasource postgresql block.",
            tech_context,
        )
        schema_dir = "prisma" if "+" not in language else "backend/prisma"
        if (project_root / "frontend" / "prisma").parent.exists() and not (project_root / "backend").exists():
            schema_dir = "prisma"
        path, written = _write_project_file(
            project_root,
            f"{schema_dir}/schema.prisma",
            schema_content,
            privileged_policy,
            overwrite=not preserve_existing,
        )
        if written:
            created_files.append(path)
        state["db_architect_models"] = [path]
    else:
        # Generate SQLAlchemy / other ORM models
        models_dir = "app/models" if "+" not in language else "backend/app/models"
        if preserve_existing:
            existing_models = list((project_root / models_dir).glob("*.py"))
            if existing_models:
                log_task_update("DB Architect", "Template models detected; skipping ORM model generation.")
                state["db_architect_models"] = [str(p) for p in existing_models]
            else:
                models_content = _generate_code_file(
                    f"Generate {orm.upper()} ORM model classes for ALL tables in the schema. "
                    f"Include imports, base class, relationships, and column types. "
                    f"Framework: {framework}.",
                    tech_context,
                )
                path, written = _write_project_file(
                    project_root,
                    f"{models_dir}/models.py",
                    models_content,
                    privileged_policy,
                    overwrite=not preserve_existing,
                )
                if written:
                    created_files.append(path)
                state["db_architect_models"] = [path]
        else:
            models_content = _generate_code_file(
                f"Generate {orm.upper()} ORM model classes for ALL tables in the schema. "
                f"Include imports, base class, relationships, and column types. "
                f"Framework: {framework}.",
                tech_context,
            )
            path, written = _write_project_file(
                project_root,
                f"{models_dir}/models.py",
                models_content,
                privileged_policy,
                overwrite=not preserve_existing,
            )
            if written:
                created_files.append(path)
            state["db_architect_models"] = [path]

        # DB session/connection
        session_content = _generate_code_file(
            f"Generate the database session/connection setup module for {orm} with {framework}. "
            f"Include async session factory, engine creation from DATABASE_URL env var, and dependency injection.",
            tech_context,
        )
        session_dir = "app/db" if "+" not in language else "backend/app/db"
        path, written = _write_project_file(
            project_root,
            f"{session_dir}/session.py",
            session_content,
            privileged_policy,
            overwrite=not preserve_existing,
        )
        if written:
            created_files.append(path)

    # 3. Generate migration files
    migration_tool = tech_stack.get("migration_tool", "")
    if migration_tool == "alembic":
        alembic_dir = "alembic" if "+" not in language else "backend/alembic"
        env_content = _generate_code_file(
            "Generate the alembic/env.py file configured for async SQLAlchemy with the project's models. "
            "Import the Base metadata and configure the target_metadata.",
            tech_context,
        )
        path, written = _write_project_file(
            project_root,
            f"{alembic_dir}/env.py",
            env_content,
            privileged_policy,
            overwrite=not preserve_existing,
        )
        if written:
            created_files.append(path)

        ini_content = _generate_code_file(
            "Generate an alembic.ini configuration file. Use sqlalchemy.url from environment variable DATABASE_URL.",
            tech_context,
        )
        ini_dir = "" if "+" not in language else "backend/"
        path, written = _write_project_file(
            project_root,
            f"{ini_dir}alembic.ini",
            ini_content,
            privileged_policy,
            overwrite=not preserve_existing,
        )
        if written:
            created_files.append(path)
        state["db_architect_migrations"] = [path]
    elif migration_tool == "prisma":
        state["db_architect_migrations"] = ["prisma migrate dev (run after containers start)"]
    else:
        state["db_architect_migrations"] = []

    # 4. Generate seed data script
    if db_schema.get("tables"):
        seed_content = _generate_code_file(
            f"Generate a seed data script that inserts sample/test data into all tables. "
            f"Use {orm} and the project's models. Make it runnable as a standalone script.",
            tech_context,
        )
        seed_dir = "scripts" if "+" not in language else "backend/scripts"
        (project_root / seed_dir).mkdir(parents=True, exist_ok=True)
        path, written = _write_project_file(
            project_root,
            f"{seed_dir}/seed.py",
            seed_content,
            privileged_policy,
            overwrite=not preserve_existing,
        )
        if written:
            created_files.append(path)
        state["db_architect_seed_script"] = path

    # 5. Start database containers
    docker_ok, docker_msg = _start_db_containers(project_root)
    state["db_architect_docker_status"] = "up" if docker_ok else "manual_required"
    log_task_update("DB Architect", f"Docker status: {'up' if docker_ok else docker_msg}")

    # Summary
    summary_parts = [
        f"Database architecture for {project_name}:",
        f"  ORM: {orm}",
        f"  Tables: {len(db_schema.get('tables', []))}",
        f"  Files created: {len(created_files)}",
        f"  Docker DB: {'running' if docker_ok else docker_msg}",
    ]
    summary = "\n".join(summary_parts)
    state["db_architect_status"] = "completed"
    state["db_architect_summary"] = summary
    state["draft_response"] = summary

    append_privileged_audit_event(
        state,
        actor="database_architect_agent",
        action="db_architecture",
        status="completed",
        detail={"files": created_files, "docker_status": state["db_architect_docker_status"]},
    )
    write_text_file(f"db_architect_output_{call_number}.txt", summary + "\n\n" + "\n".join(created_files))
    log_task_update("DB Architect", f"Database architecture complete.", summary)

    state = publish_agent_output(
        state,
        "database_architect_agent",
        summary,
        f"db_architect_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent"],
    )
    return state
