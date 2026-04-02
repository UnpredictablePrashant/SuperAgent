"""Project Scaffold Agent.

Creates the project directory tree, configuration files, entry points,
.gitignore, .env.example, docker-compose.yml, and README.md based on the approved blueprint.
"""

import json
import shutil
from pathlib import Path

from tasks.a2a_agent_utils import begin_agent_session, publish_agent_output
from tasks.privileged_control import (
    append_privileged_audit_event,
    build_privileged_policy,
    path_allowed,
)
from tasks.utils import OUTPUT_DIR, llm, log_file_action, log_task_update, normalize_llm_text, write_text_file


AGENT_METADATA = {
    "project_scaffold_agent": {
        "description": (
            "Creates the project directory tree, configuration files, entry points, "
            ".gitignore, .env.example, docker-compose.yml, and README from an approved blueprint."
        ),
        "skills": ["scaffolding", "project setup", "config generation"],
        "input_keys": ["blueprint_json", "project_root", "project_name"],
        "output_keys": ["scaffold_created_files", "scaffold_status", "scaffold_summary"],
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


def _create_directory_tree(root: Path, structure: list[str], *, create_files: bool = True) -> list[str]:
    """Create directories and optionally empty stub files. Returns list of created paths."""
    created: list[str] = []
    for entry in structure:
        target = root / entry
        if entry.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
            created.append(str(target))
        else:
            if not create_files:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists():
                target.write_text("", encoding="utf-8")
                log_file_action("created", str(target))
                created.append(str(target))
    return created


def _generate_gitignore(tech_stack: dict) -> str:
    language = str(tech_stack.get("language", "")).lower()
    lines = [
        "# Dependencies",
        "node_modules/",
        "__pycache__/",
        "*.pyc",
        ".venv/",
        "venv/",
        "",
        "# Environment",
        ".env",
        ".env.local",
        ".env.*.local",
        "",
        "# Build",
        "dist/",
        "build/",
        ".next/",
        "*.egg-info/",
        "",
        "# IDE",
        ".idea/",
        ".vscode/",
        "*.swp",
        "*.swo",
        "",
        "# OS",
        ".DS_Store",
        "Thumbs.db",
        "",
        "# Docker",
        "docker-compose.override.yml",
    ]
    if "python" in language:
        lines.extend(["", "# Python", "*.egg", "*.whl", ".mypy_cache/", ".ruff_cache/", ".pytest_cache/"])
    if "typescript" in language or "javascript" in language:
        lines.extend(["", "# TypeScript/JS", "*.tsbuildinfo", "coverage/"])
    return "\n".join(lines) + "\n"


def _generate_env_example(env_vars: list[dict]) -> str:
    lines = ["# Environment Variables", "# Copy to .env and fill in values", ""]
    for ev in env_vars:
        name = ev.get("name", "UNKNOWN")
        desc = ev.get("description", "")
        example = ev.get("example_value", "")
        if desc:
            lines.append(f"# {desc}")
        lines.append(f"{name}={example}")
        lines.append("")
    if not env_vars:
        lines.append("# ADD_VAR_HERE=")
        lines.append("")
    return "\n".join(lines)


def _generate_docker_compose_stub(blueprint: dict) -> str:
    services = blueprint.get("docker_services", [])
    lines = ['version: "3.9"', "services:"]
    if not services:
        lines.append("  # add services here")
        return "\n".join(lines) + "\n"
    for svc in services:
        name = str(svc.get("name") or "service").strip() or "service"
        lines.append(f"  {name}:")
        image = str(svc.get("image") or "").strip()
        if image:
            lines.append(f"    image: {image}")
        ports = svc.get("ports", [])
        if isinstance(ports, list) and ports:
            lines.append("    ports:")
            for port in ports:
                lines.append(f'      - "{port}"')
        env = svc.get("environment", {})
        if not env and isinstance(svc.get("env"), dict):
            env = svc.get("env", {})
        if isinstance(env, dict) and env:
            lines.append("    environment:")
            for key, value in env.items():
                lines.append(f"      {key}: {value}")
        volumes = svc.get("volumes", [])
        if isinstance(volumes, list) and volumes:
            lines.append("    volumes:")
            for volume in volumes:
                lines.append(f"      - {volume}")
    return "\n".join(lines) + "\n"


def _generate_readme(blueprint: dict) -> str:
    name = blueprint.get("project_name", "project")
    tech = blueprint.get("tech_stack", {})
    endpoints = blueprint.get("api_design", {}).get("endpoints", [])

    lines = [
        f"# {name}",
        "",
        f"**Stack**: {tech.get('framework', 'unknown')} + {tech.get('database', 'unknown')}",
        "",
        "## Quick Start",
        "",
        "```bash",
        "# Start database",
        "docker-compose up -d",
        "",
        "# Install dependencies",
    ]
    pm = tech.get("package_manager", "npm")
    if "pip" in pm:
        lines.extend(["pip install -r requirements.txt", ""])
    if "npm" in pm:
        lines.extend(["npm install", ""])
    lines.extend([
        "# Run development server",
        "# See .env.example for required environment variables",
        "```",
        "",
    ])
    if endpoints:
        lines.append("## API Endpoints")
        lines.append("")
        for ep in endpoints[:20]:
            lines.append(f"- `{ep.get('method', '?')} {ep.get('path', '?')}` -- {ep.get('description', '')}")
        lines.append("")
    lines.append("---")
    lines.append("Generated by Kendr Project Builder.")
    return "\n".join(lines) + "\n"


def _generate_config_file(blueprint: dict, file_type: str) -> str:
    """Use LLM to generate a config file appropriate for the stack."""
    tech = blueprint.get("tech_stack", {})
    deps = blueprint.get("dependencies", {})
    prompt = f"""
Generate the content for a {file_type} configuration file for a project with this tech stack:
{json.dumps(tech, indent=2)}

Dependencies:
{json.dumps(deps, indent=2)}

Project name: {blueprint.get('project_name', 'app')}

Return ONLY the file content, no explanation, no markdown fences.
""".strip()
    response = llm.invoke(prompt)
    raw = normalize_llm_text(response.content if hasattr(response, "content") else response)
    return _strip_code_fences(raw).strip() + "\n"

def _write_if_empty(path: Path, content: str) -> bool:
    """Write content if the target file is missing or empty. Returns True if written."""
    try:
        if path.exists():
            existing = path.read_text(encoding="utf-8")
            if existing.strip():
                return False
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        # If we can't read it, do not overwrite.
        return False
    path.write_text(content, encoding="utf-8")
    log_file_action("wrote", str(path))
    return True


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _load_stack_template(stack_name: str) -> dict | None:
    try:
        from plugin_templates.project_stacks import load_stack_template

        return load_stack_template(stack_name)
    except Exception:
        return None


def _copy_template_dir(template_dir: Path, project_root: Path, policy: dict) -> list[str]:
    created: list[str] = []
    for src in template_dir.rglob("*"):
        rel = src.relative_to(template_dir)
        if rel.parts and rel.parts[0].startswith(".git"):
            continue
        dest = project_root / rel
        if src.is_dir():
            dest.mkdir(parents=True, exist_ok=True)
            continue
        if not path_allowed(str(dest), policy.get("allowed_paths", [])):
            raise PermissionError(f"Write blocked: {dest} outside allowed scope.")
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest)
        log_file_action("copied", str(dest))
        created.append(str(dest))
    return created


def _ensure_generated_file(path: Path, content_factory) -> bool:
    """Write content if missing/empty. Returns True if written."""
    try:
        if path.exists() and path.read_text(encoding="utf-8").strip():
            return False
    except Exception:
        return False
    content = content_factory()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    log_file_action("wrote", str(path))
    return True


def _populate_frontend_starter(blueprint: dict, project_root: Path) -> list[str]:
    """Populate essential frontend starter files if they are empty."""
    tech_stack = blueprint.get("tech_stack", {})
    framework = str(tech_stack.get("framework", "")).lower()
    if "react" not in framework and "next" not in framework:
        return []

    frontend_root = project_root / "frontend" if (project_root / "frontend").exists() else project_root
    src_dir = frontend_root / "src"
    if not src_dir.exists():
        return []

    created: list[str] = []
    css_framework = str(tech_stack.get("css", "")).lower()
    uses_tailwind = "tailwind" in css_framework

    # index.html (Vite-style default)
    index_html = """<!doctype html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>App</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
"""
    index_html_path = frontend_root / "index.html"
    if _write_if_empty(index_html_path, index_html):
        created.append(str(index_html_path))

    # main entry
    main_path = src_dir / "main.tsx"
    main_tsx = """import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
"""
    if _write_if_empty(main_path, main_tsx):
        created.append(str(main_path))

    # App component
    app_path = src_dir / "App.tsx"
    app_tsx = """export default function App() {
  return (
    <div className="min-h-screen bg-slate-950 text-slate-100">
      <main className="mx-auto flex min-h-screen max-w-3xl flex-col items-center justify-center gap-4 px-6 text-center">
        <h1 className="text-3xl font-semibold">Project Scaffold Ready</h1>
        <p className="text-slate-300">
          This is a starter UI. The feature screens will be generated in later steps.
        </p>
      </main>
    </div>
  );
}
"""
    if _write_if_empty(app_path, app_tsx):
        created.append(str(app_path))

    # Global styles
    css_path = src_dir / "index.css"
    if uses_tailwind:
        css_content = """@tailwind base;
@tailwind components;
@tailwind utilities;

:root {
  color-scheme: dark;
}

body {
  margin: 0;
  font-family: "Space Grotesk", sans-serif;
}
"""
    else:
        css_content = """:root {
  color-scheme: light dark;
}

body {
  margin: 0;
  font-family: "Space Grotesk", sans-serif;
}
"""
    if _write_if_empty(css_path, css_content):
        created.append(str(css_path))

    return created


def project_scaffold_agent(state):
    """Create the project skeleton from the approved blueprint."""
    active_task, task_content, _ = begin_agent_session(state, "project_scaffold_agent")
    state["project_scaffold_agent_calls"] = state.get("project_scaffold_agent_calls", 0) + 1
    call_number = state["project_scaffold_agent_calls"]

    blueprint = state.get("blueprint_json", {})
    if not blueprint:
        raise ValueError("project_scaffold_agent requires blueprint_json in state.")

    project_root = Path(state.get("project_root", "")).resolve()
    if not project_root or str(project_root) == ".":
        raise ValueError("project_scaffold_agent requires project_root in state.")

    privileged_policy = build_privileged_policy(state)
    if privileged_policy.get("read_only", False):
        raise PermissionError("project_scaffold_agent blocked: privileged read-only mode.")
    if not path_allowed(str(project_root), privileged_policy.get("allowed_paths", [])):
        raise PermissionError(f"project_scaffold_agent blocked: {project_root} outside allowed scope.")

    tech_stack = blueprint.get("tech_stack", {})
    directory_structure = blueprint.get("directory_structure", [])
    env_vars = blueprint.get("env_vars", [])
    log_task_update("Scaffold", f"Scaffolding pass #{call_number} started at {project_root}.")

    # 1. Optional: copy full project template
    stack_name = str(state.get("project_stack", "") or "").strip()
    stack_template = _load_stack_template(stack_name) if stack_name else None
    template_dir = None
    if stack_template:
        template_dir = stack_template.get("template_dir") or stack_template.get("template_path")
    used_template = False
    created_files = []
    if template_dir:
        template_root = _repo_root() / str(template_dir)
        if template_root.exists() and template_root.is_dir():
            created_files.extend(_copy_template_dir(template_root, project_root, privileged_policy))
            used_template = True

    # 2. Create directory tree (avoid empty files when template is used)
    project_root.mkdir(parents=True, exist_ok=True)
    created_files.extend(
        _create_directory_tree(project_root, directory_structure, create_files=not used_template)
    )

    # 3. Generate .gitignore
    gitignore_path = project_root / ".gitignore"
    if used_template:
        if _write_if_empty(gitignore_path, _generate_gitignore(tech_stack)):
            created_files.append(str(gitignore_path))
    else:
        gitignore_path.write_text(_generate_gitignore(tech_stack), encoding="utf-8")
        log_file_action("wrote", str(gitignore_path))
        created_files.append(str(gitignore_path))

    # 4. Generate .env.example
    env_path = project_root / ".env.example"
    if used_template:
        if _write_if_empty(env_path, _generate_env_example(env_vars)):
            created_files.append(str(env_path))
    else:
        env_path.write_text(_generate_env_example(env_vars), encoding="utf-8")
        log_file_action("wrote", str(env_path))
        created_files.append(str(env_path))

    # 5. Generate README.md
    readme_path = project_root / "README.md"
    if used_template:
        if _write_if_empty(readme_path, _generate_readme(blueprint)):
            created_files.append(str(readme_path))
    else:
        readme_path.write_text(_generate_readme(blueprint), encoding="utf-8")
        log_file_action("wrote", str(readme_path))
        created_files.append(str(readme_path))

    # 5b. Generate docker-compose.yml
    compose_path = project_root / "docker-compose.yml"
    if used_template:
        if _write_if_empty(compose_path, _generate_docker_compose_stub(blueprint)):
            created_files.append(str(compose_path))
    else:
        compose_path.write_text(_generate_docker_compose_stub(blueprint), encoding="utf-8")
        log_file_action("wrote", str(compose_path))
        created_files.append(str(compose_path))

    # 6. Generate main config file (package.json / pyproject.toml) if missing
    language = str(tech_stack.get("language", "")).lower()
    if "python" in language:
        config_path = project_root / "pyproject.toml"
        if _ensure_generated_file(config_path, lambda: _generate_config_file(blueprint, "pyproject.toml")):
            created_files.append(str(config_path))

        # Also write requirements.txt
        runtime_deps = blueprint.get("dependencies", {}).get("runtime", [])
        python_deps = [d for d in runtime_deps if not str(d).startswith("npm:")]
        if python_deps:
            req_path = project_root / "requirements.txt"
            if _ensure_generated_file(req_path, lambda: "\n".join(python_deps) + "\n"):
                created_files.append(str(req_path))

    if "typescript" in language or "javascript" in language or tech_stack.get("package_manager") in ("npm", "yarn", "pnpm"):
        pkg_root = project_root
        # For full-stack projects, check if there's a frontend/ subdirectory
        if (project_root / "frontend").exists():
            pkg_root = project_root / "frontend"
        config_path = pkg_root / "package.json"
        if _ensure_generated_file(config_path, lambda: _generate_config_file(blueprint, "package.json")):
            created_files.append(str(config_path))

        # tsconfig.json
        ts_path = pkg_root / "tsconfig.json"
        if _ensure_generated_file(ts_path, lambda: _generate_config_file(blueprint, "tsconfig.json")):
            created_files.append(str(ts_path))

    # 7. Populate essential frontend starter files (HTML/CSS/JS) if empty
    if not used_template:
        frontend_files = _populate_frontend_starter(blueprint, project_root)
        created_files.extend(frontend_files)

    # Persist results
    state["scaffold_created_files"] = created_files
    state["scaffold_status"] = "completed"
    state["scaffold_template_used"] = used_template
    state["scaffold_template_dir"] = str(template_dir or "")
    required_paths = {
        "README.md": readme_path,
        ".env.example": env_path,
        "docker-compose.yml": compose_path,
    }
    required_status = [
        f"- {name}: {'present' if path.exists() else 'missing'}" for name, path in required_paths.items()
    ]
    summary = (
        f"Scaffolded {len(created_files)} files/directories at {project_root}.\n"
        f"Template used: {'yes' if used_template else 'no'}\n"
        "Required files:\n"
        + "\n".join(required_status)
    )
    state["scaffold_summary"] = summary
    state["draft_response"] = summary

    append_privileged_audit_event(
        state,
        actor="project_scaffold_agent",
        action="scaffold",
        status="completed",
        detail={"project_root": str(project_root), "file_count": len(created_files)},
    )
    write_text_file(f"scaffold_output_{call_number}.txt", summary + "\n\n" + "\n".join(created_files))
    log_task_update("Scaffold", f"Scaffold complete: {len(created_files)} items created.", summary)

    state = publish_agent_output(
        state,
        "project_scaffold_agent",
        summary,
        f"scaffold_result_{call_number}",
        recipients=["orchestrator_agent", "reviewer_agent"],
    )
    return state
