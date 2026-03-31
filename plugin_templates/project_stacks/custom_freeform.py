"""Custom / free-form stack template — LLM-driven, no pre-defined structure.

This template acts as a pass-through: the blueprint agent is given full freedom
to define the tech stack, directory layout, and dependencies from the user's
description, without any opinionated boilerplate constraints.
"""

STACK_TEMPLATE = {
    "name": "custom_freeform",
    "display_name": "Custom / Free-form (LLM-driven)",
    "tech_stack": {
        "language": None,
        "framework": None,
        "database": None,
        "orm": None,
        "migration_tool": None,
        "auth": None,
        "css": None,
        "package_manager": None,
        "runtime": None,
    },
    "base_directory_structure": [],
    "base_dependencies": {},
    "base_docker_services": [],
    "base_env_vars": [],
    "feature_flags": {
        "has_auth": False,
        "has_frontend": False,
        "has_docker": False,
        "has_tests": False,
        "has_migrations": False,
    },
    "description": (
        "Fully LLM-driven stack. The blueprint agent selects all technologies, "
        "defines the directory structure, and generates all configuration files "
        "based solely on the project description. No template constraints applied."
    ),
}
