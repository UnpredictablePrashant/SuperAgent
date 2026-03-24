from __future__ import annotations

import os
from datetime import datetime, timezone

from tasks.sqlite_store import (
    delete_setup_config_value,
    get_setup_component,
    get_setup_config_value,
    list_setup_components,
    list_setup_config_values,
    upsert_setup_component,
    upsert_setup_config_value,
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def component_catalog() -> list[dict]:
    return [
        {
            "id": "core_runtime",
            "title": "Core Runtime",
            "category": "Core",
            "description": "Base runtime behavior, output paths, and plugin discovery.",
            "fields": [
                {"key": "SUPERAGENT_HOME", "label": "Superagent Home", "secret": False, "description": "Home directory for plugin/config files."},
                {"key": "SUPERAGENT_PLUGIN_PATHS", "label": "Plugin Paths", "secret": False, "description": "OS path-separated plugin paths."},
                {"key": "OUTPUT_DIR", "label": "Output Directory", "secret": False, "description": "Output folder for runs and setup artifacts."},
                {
                    "key": "SUPERAGENT_WORKING_DIR",
                    "label": "Working Folder",
                    "secret": False,
                    "description": "Required. Base folder where task runs, intermediate files, and outputs are stored.",
                },
            ],
        },
        {
            "id": "openai",
            "title": "OpenAI",
            "category": "Providers",
            "description": "Primary LLM provider for orchestration and reasoning agents.",
            "fields": [
                {"key": "OPENAI_API_KEY", "label": "API Key", "secret": True, "required": True, "description": "OpenAI API key."},
                {
                    "key": "OPENAI_MODEL_GENERAL",
                    "label": "General Model",
                    "secret": False,
                    "description": "Model for planning, orchestration, research, and general agents.",
                },
                {
                    "key": "OPENAI_MODEL_CODING",
                    "label": "Coding Model",
                    "secret": False,
                    "description": "Model for coding-focused agents such as coding_agent and reddit_agent.",
                },
                {
                    "key": "OPENAI_MODEL",
                    "label": "Legacy Default Model",
                    "secret": False,
                    "description": "Backward-compatible fallback model if OPENAI_MODEL_GENERAL is not set.",
                },
                {
                    "key": "OPENAI_CODEX_MODEL",
                    "label": "Legacy Codex Model",
                    "secret": False,
                    "description": "Backward-compatible fallback for coding model if OPENAI_MODEL_CODING is not set.",
                },
            ],
        },
        {
            "id": "serpapi",
            "title": "SerpAPI",
            "category": "Providers",
            "description": "Search provider for web/travel/literature tasks.",
            "fields": [
                {"key": "SERP_API_KEY", "label": "API Key", "secret": True, "description": "SerpAPI key."},
            ],
        },
        {
            "id": "elevenlabs",
            "title": "ElevenLabs",
            "category": "Providers",
            "description": "Speech and voice APIs.",
            "fields": [
                {"key": "ELEVENLABS_API_KEY", "label": "API Key", "secret": True, "description": "ElevenLabs API key."},
            ],
        },
        {
            "id": "google_workspace",
            "title": "Google Workspace",
            "category": "Providers",
            "description": "Gmail and Drive integration via OAuth.",
            "fields": [
                {"key": "GOOGLE_CLIENT_ID", "label": "Client ID", "secret": False, "description": "Google OAuth client ID."},
                {"key": "GOOGLE_CLIENT_SECRET", "label": "Client Secret", "secret": True, "description": "Google OAuth client secret."},
                {"key": "GOOGLE_REDIRECT_URI", "label": "Redirect URI", "secret": False, "description": "OAuth callback URI."},
                {"key": "GOOGLE_OAUTH_SCOPES", "label": "OAuth Scopes", "secret": False, "description": "Space-separated OAuth scopes."},
            ],
            "oauth_provider": "google",
            "oauth_start_path": "/oauth/google/start",
        },
        {
            "id": "microsoft_graph",
            "title": "Microsoft Graph",
            "category": "Providers",
            "description": "Outlook/Teams/OneDrive integration via OAuth.",
            "fields": [
                {"key": "MICROSOFT_TENANT_ID", "label": "Tenant ID", "secret": False, "description": "Tenant ID or common."},
                {"key": "MICROSOFT_CLIENT_ID", "label": "Client ID", "secret": False, "description": "Microsoft OAuth client ID."},
                {"key": "MICROSOFT_CLIENT_SECRET", "label": "Client Secret", "secret": True, "description": "Microsoft OAuth client secret."},
                {"key": "MICROSOFT_REDIRECT_URI", "label": "Redirect URI", "secret": False, "description": "OAuth callback URI."},
                {"key": "MICROSOFT_OAUTH_SCOPES", "label": "OAuth Scopes", "secret": False, "description": "Space-separated OAuth scopes."},
            ],
            "oauth_provider": "microsoft",
            "oauth_start_path": "/oauth/microsoft/start",
        },
        {
            "id": "slack",
            "title": "Slack",
            "category": "Providers",
            "description": "Slack bot workspace integration.",
            "fields": [
                {"key": "SLACK_BOT_TOKEN", "label": "Bot Token", "secret": True, "description": "Slack bot token if set manually."},
                {"key": "SLACK_CLIENT_ID", "label": "Client ID", "secret": False, "description": "Slack OAuth client ID."},
                {"key": "SLACK_CLIENT_SECRET", "label": "Client Secret", "secret": True, "description": "Slack OAuth client secret."},
                {"key": "SLACK_REDIRECT_URI", "label": "Redirect URI", "secret": False, "description": "OAuth callback URI."},
                {"key": "SLACK_OAUTH_SCOPES", "label": "OAuth Scopes", "secret": False, "description": "Comma-separated scopes."},
            ],
            "oauth_provider": "slack",
            "oauth_start_path": "/oauth/slack/start",
        },
        {
            "id": "telegram",
            "title": "Telegram",
            "category": "Channels",
            "description": "Telegram bot or session integration.",
            "fields": [
                {"key": "TELEGRAM_BOT_TOKEN", "label": "Bot Token", "secret": True, "description": "Telegram bot token."},
                {"key": "TELEGRAM_SESSION_STRING", "label": "Session String", "secret": True, "description": "Telegram user session string."},
                {"key": "TELEGRAM_API_ID", "label": "API ID", "secret": False, "description": "Telegram API ID."},
                {"key": "TELEGRAM_API_HASH", "label": "API Hash", "secret": True, "description": "Telegram API hash."},
            ],
        },
        {
            "id": "whatsapp",
            "title": "WhatsApp",
            "category": "Channels",
            "description": "WhatsApp Cloud API credentials.",
            "fields": [
                {"key": "WHATSAPP_ACCESS_TOKEN", "label": "Access Token", "secret": True, "description": "WhatsApp Cloud API token."},
                {"key": "WHATSAPP_PHONE_NUMBER_ID", "label": "Phone Number ID", "secret": False, "description": "WhatsApp phone number ID."},
            ],
        },
        {
            "id": "aws",
            "title": "AWS",
            "category": "Cloud",
            "description": "AWS credentials and default region.",
            "fields": [
                {"key": "AWS_ACCESS_KEY_ID", "label": "Access Key ID", "secret": True, "description": "Optional static access key."},
                {"key": "AWS_SECRET_ACCESS_KEY", "label": "Secret Access Key", "secret": True, "description": "Optional static secret key."},
                {"key": "AWS_SESSION_TOKEN", "label": "Session Token", "secret": True, "description": "Optional session token."},
                {"key": "AWS_DEFAULT_REGION", "label": "Default Region", "secret": False, "description": "AWS region override."},
                {"key": "AWS_PROFILE", "label": "Profile", "secret": False, "description": "Named profile if used."},
            ],
        },
        {
            "id": "qdrant",
            "title": "Qdrant",
            "category": "Infrastructure",
            "description": "Vector store endpoint and API key.",
            "fields": [
                {"key": "QDRANT_URL", "label": "Qdrant URL", "secret": False, "description": "Qdrant service URL."},
                {"key": "QDRANT_API_KEY", "label": "API Key", "secret": True, "description": "Optional Qdrant API key."},
            ],
        },
        {
            "id": "gateway_server",
            "title": "Gateway Server",
            "category": "Runtime",
            "description": "HTTP ingest and dashboard server settings.",
            "fields": [
                {"key": "GATEWAY_HOST", "label": "Host", "secret": False, "description": "Gateway bind host."},
                {"key": "GATEWAY_PORT", "label": "Port", "secret": False, "description": "Gateway bind port."},
            ],
        },
        {
            "id": "setup_ui",
            "title": "Setup UI",
            "category": "Runtime",
            "description": "Configuration web UI bind settings.",
            "fields": [
                {"key": "SETUP_UI_HOST", "label": "Host", "secret": False, "description": "Setup UI bind host."},
                {"key": "SETUP_UI_PORT", "label": "Port", "secret": False, "description": "Setup UI bind port."},
            ],
        },
        {
            "id": "daemon",
            "title": "Daemon",
            "category": "Runtime",
            "description": "Always-on monitor daemon intervals.",
            "fields": [
                {"key": "DAEMON_POLL_INTERVAL", "label": "Poll Interval", "secret": False, "description": "Main daemon poll interval in seconds."},
                {"key": "DAEMON_HEARTBEAT_INTERVAL", "label": "Heartbeat Interval", "secret": False, "description": "Heartbeat interval in seconds."},
            ],
        },
        {
            "id": "privileged_control",
            "title": "Privileged Control",
            "category": "Security",
            "description": "Policy gates for high-privilege command and filesystem execution.",
            "fields": [
                {
                    "key": "SUPERAGENT_PRIVILEGED_MODE",
                    "label": "Privileged Mode",
                    "secret": False,
                    "description": "If true, privileged policy controls are enabled for runs.",
                },
                {
                    "key": "SUPERAGENT_REQUIRE_APPROVALS",
                    "label": "Require Approvals",
                    "secret": False,
                    "description": "If true, privileged actions require explicit approved flag and approval note.",
                },
                {
                    "key": "SUPERAGENT_READ_ONLY_MODE",
                    "label": "Read-Only Mode",
                    "secret": False,
                    "description": "If true, mutating command/file actions are blocked.",
                },
                {
                    "key": "SUPERAGENT_ALLOW_ROOT",
                    "label": "Allow Root Escalation",
                    "secret": False,
                    "description": "If true, sudo/root escalation is allowed for privileged runs.",
                },
                {
                    "key": "SUPERAGENT_ALLOW_DESTRUCTIVE",
                    "label": "Allow Destructive Commands",
                    "secret": False,
                    "description": "If true, destructive operations may run.",
                },
                {
                    "key": "SUPERAGENT_ENABLE_BACKUPS",
                    "label": "Enable Snapshots",
                    "secret": False,
                    "description": "If true, snapshots are created before mutating OS commands.",
                },
                {
                    "key": "SUPERAGENT_ALLOWED_PATHS",
                    "label": "Allowed Paths",
                    "secret": False,
                    "description": "Comma or pathsep-separated allowlist roots for command/file scope.",
                },
                {
                    "key": "SUPERAGENT_ALLOWED_DOMAINS",
                    "label": "Allowed Domains",
                    "secret": False,
                    "description": "Comma-separated allowed network domains for privileged tasks.",
                },
                {
                    "key": "SUPERAGENT_KILL_SWITCH_FILE",
                    "label": "Kill Switch File",
                    "secret": False,
                    "description": "If this file exists, runtime halts before additional agent execution.",
                },
            ],
        },
        {
            "id": "security_tools",
            "title": "Security Tools",
            "category": "Security",
            "description": "Native binaries for scanner and review workflows.",
            "fields": [
                {
                    "key": "SECURITY_SCAN_PROFILE",
                    "label": "Default Scan Profile",
                    "secret": False,
                    "description": "Security scan depth default: baseline, standard, deep, or extensive.",
                },
                {
                    "key": "SECURITY_AUTO_INSTALL_TOOLS",
                    "label": "Auto Install Security Tools",
                    "secret": False,
                    "description": "If true, CLI attempts to install missing security tools before authorized security runs.",
                },
                {"key": "NVD_API_KEY", "label": "NVD API Key", "secret": True, "description": "Optional key for NVD rate limits."},
                {"key": "CVE_API_BASE_URL", "label": "CVE API Base URL", "secret": False, "description": "CVE/NVD API base URL."},
            ],
        },
        {
            "id": "mcp_research",
            "title": "MCP Research Server",
            "category": "MCP",
            "description": "Research MCP server bind settings.",
            "fields": [
                {"key": "MCP_RESEARCH_HOST", "label": "Host", "secret": False, "description": "Host for research MCP."},
                {"key": "MCP_RESEARCH_PORT", "label": "Port", "secret": False, "description": "Port for research MCP."},
            ],
        },
        {
            "id": "mcp_vector",
            "title": "MCP Vector Server",
            "category": "MCP",
            "description": "Vector MCP server bind settings.",
            "fields": [
                {"key": "MCP_VECTOR_HOST", "label": "Host", "secret": False, "description": "Host for vector MCP."},
                {"key": "MCP_VECTOR_PORT", "label": "Port", "secret": False, "description": "Port for vector MCP."},
            ],
        },
        {
            "id": "mcp_security",
            "title": "MCP Security Servers",
            "category": "MCP",
            "description": "Shared settings for security MCP servers.",
            "fields": [
                {"key": "MCP_SECURITY_HOST", "label": "Host", "secret": False, "description": "Host for security MCP services."},
                {"key": "MCP_NMAP_PORT", "label": "Nmap Port", "secret": False, "description": "Nmap MCP port."},
                {"key": "MCP_ZAP_PORT", "label": "ZAP Port", "secret": False, "description": "ZAP MCP port."},
                {"key": "MCP_SCREENSHOT_PORT", "label": "Screenshot Port", "secret": False, "description": "Screenshot MCP port."},
                {"key": "MCP_HTTP_FUZZING_PORT", "label": "HTTP Fuzzing Port", "secret": False, "description": "HTTP fuzzing MCP port."},
                {"key": "MCP_CVE_PORT", "label": "CVE Port", "secret": False, "description": "CVE MCP port."},
            ],
        },
    ]


def component_index() -> dict[str, dict]:
    return {item["id"]: item for item in component_catalog()}


def get_component(component_id: str) -> dict:
    return component_index().get(component_id, {})


def _field_secret_map(component: dict) -> dict[str, bool]:
    fields = component.get("fields", []) if isinstance(component, dict) else []
    return {field["key"]: bool(field.get("secret", False)) for field in fields}


def apply_setup_env_defaults() -> None:
    for item in list_setup_config_values(include_secrets=True):
        key = str(item.get("config_key", "")).strip()
        value = str(item.get("config_value", ""))
        if key and value and not os.getenv(key, "").strip():
            os.environ[key] = value


def set_component_enabled(component_id: str, enabled: bool, notes: str = "") -> dict:
    upsert_setup_component(component_id, enabled=enabled, notes=notes, updated_at=_utc_now())
    return get_setup_component(component_id)


def get_component_values(component_id: str, *, include_secrets: bool = False) -> list[dict]:
    values = []
    for item in list_setup_config_values(include_secrets=include_secrets):
        if item.get("component_id") == component_id:
            values.append(item)
    return values


def save_component_values(component_id: str, values: dict[str, str]) -> dict:
    component = get_component(component_id)
    if not component:
        raise ValueError(f"Unknown component: {component_id}")
    secrets = _field_secret_map(component)
    updated = _utc_now()
    for key, value in values.items():
        raw = "" if value is None else str(value)
        if raw.strip() == "":
            delete_setup_config_value(component_id, key)
            continue
        upsert_setup_config_value(
            component_id,
            key,
            raw,
            is_secret=bool(secrets.get(key, False)),
            updated_at=updated,
        )
    return get_setup_component_snapshot(component_id)


def get_setup_component_snapshot(component_id: str) -> dict:
    component = get_component(component_id)
    if not component:
        return {}
    state = get_setup_component(component_id)
    values = get_component_values(component_id, include_secrets=True)
    current = {item["config_key"]: item["config_value"] for item in values}
    masked = {}
    secrets = _field_secret_map(component)
    filled = 0
    for field in component.get("fields", []):
        key = field["key"]
        raw_value = current.get(key, "")
        if raw_value:
            filled += 1
        if secrets.get(key, False):
            masked[key] = "********" if raw_value else ""
        else:
            masked[key] = raw_value
    enabled = True if not state else bool(state.get("enabled", 1))
    return {
        "component": component,
        "enabled": enabled,
        "notes": state.get("notes", "") if state else "",
        "updated_at": state.get("updated_at", "") if state else "",
        "values": masked,
        "raw_values": current,
        "filled_fields": filled,
        "total_fields": len(component.get("fields", [])),
    }


def setup_overview() -> dict:
    component_rows = []
    states = {item["component_id"]: item for item in list_setup_components()}
    for component in component_catalog():
        component_id = component["id"]
        row = get_setup_component_snapshot(component_id)
        env_status = []
        for field in component.get("fields", []):
            key = field["key"]
            env_present = bool(os.getenv(key, "").strip())
            db_present = bool(row.get("raw_values", {}).get(key, "").strip())
            env_status.append({"key": key, "env": env_present, "db": db_present})
        component_rows.append(
            {
                "id": component_id,
                "title": component.get("title", component_id),
                "category": component.get("category", "Other"),
                "description": component.get("description", ""),
                "enabled": row.get("enabled", True if component_id not in states else bool(states[component_id].get("enabled", 1))),
                "filled_fields": row.get("filled_fields", 0),
                "total_fields": row.get("total_fields", 0),
                "env_status": env_status,
            }
        )

    categories: dict[str, list[dict]] = {}
    for item in component_rows:
        categories.setdefault(item["category"], []).append(item)

    return {
        "generated_at": _utc_now(),
        "components": component_rows,
        "categories": categories,
    }


def export_env_lines(include_secrets: bool = False) -> list[str]:
    lines = []
    all_values = list_setup_config_values(include_secrets=True)
    for item in all_values:
        key = str(item.get("config_key", "")).strip()
        value = str(item.get("config_value", ""))
        is_secret = bool(int(item.get("is_secret", 0) or 0))
        if not key or not value:
            continue
        if is_secret and not include_secrets:
            lines.append(f"# {key}=********")
        else:
            escaped = value.replace("\n", "\\n")
            lines.append(f"{key}={escaped}")
    return sorted(set(lines))


def resolve_config_value(component_id: str, key: str, default: str = "") -> str:
    env_value = os.getenv(key, "").strip()
    if env_value:
        return env_value
    row = get_setup_config_value(component_id, key)
    value = str(row.get("config_value", "")).strip() if row else ""
    return value or default
