"""Next.js static website template."""

STACK_TEMPLATE = {
    "name": "nextjs_static_site",
    "display_name": "Next.js Static Website",
    "template_dir": "project_templates/nextjs_static_site",
    "tech_stack": {
        "language": "typescript",
        "framework": "nextjs",
        "database": "none",
        "orm": "none",
        "migration_tool": "none",
        "auth": "none",
        "css": "tailwindcss",
        "package_manager": "npm",
        "runtime": "next",
    },
    "base_directory_structure": [
        "app/",
        "app/layout.tsx",
        "app/page.tsx",
        "app/globals.css",
        "components/",
        "public/",
    ],
    "base_dependencies": {
        "runtime": ["next", "react", "react-dom"],
        "dev": [
            "typescript",
            "@types/node",
            "@types/react",
            "@types/react-dom",
            "tailwindcss",
            "postcss",
            "autoprefixer",
        ],
    },
    "base_env_vars": [],
    "base_docker_services": [],
}
