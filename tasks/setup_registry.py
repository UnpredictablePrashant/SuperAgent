from __future__ import annotations

import importlib.util
import json
import os
import secrets
import shutil
import socket
import time
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from dotenv import load_dotenv
from kendr.persistence import get_setup_provider_tokens, set_setup_provider_tokens
from kendr.setup.catalog import (
    INTEGRATION_DEFINITIONS,
    LEGACY_AGENT_REQUIREMENTS,
    REQUIREMENT_RULES,
    IntegrationDefinition,
    integration_index,
)
from tasks.setup_config_store import apply_setup_env_defaults, get_setup_component_snapshot

load_dotenv()
apply_setup_env_defaults()

OUTPUT_DIR = "output"
TOKEN_STORE_PATH = Path(OUTPUT_DIR) / "integration_tokens.json"
SETUP_STATUS_JSON_PATH = Path(OUTPUT_DIR) / "setup_status.json"
SETUP_STATUS_TEXT_PATH = Path(OUTPUT_DIR) / "setup_status.txt"


def _now_ts() -> int:
    return int(time.time())


def _read_json(path: Path, fallback):
    if not path.exists():
        return fallback
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return fallback


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def load_token_store() -> dict:
    providers = {}
    for provider in ("google", "microsoft", "slack"):
        payload = get_setup_provider_tokens(provider)
        if payload:
            providers[provider] = payload
    if providers:
        return providers
    data = _read_json(TOKEN_STORE_PATH, {})
    return data if isinstance(data, dict) else {}


def save_token_store(data: dict) -> None:
    if isinstance(data, dict):
        for provider, payload in data.items():
            if isinstance(payload, dict):
                set_setup_provider_tokens(provider, payload, updated_at=str(_now_ts()))
    _write_json(TOKEN_STORE_PATH, data)


def get_provider_tokens(provider: str) -> dict:
    db_payload = get_setup_provider_tokens(provider)
    if db_payload:
        return db_payload if isinstance(db_payload, dict) else {}
    data = load_token_store()
    provider_payload = data.get(provider, {})
    return provider_payload if isinstance(provider_payload, dict) else {}


def set_provider_tokens(provider: str, tokens: dict) -> dict:
    data = load_token_store()
    merged = {**get_provider_tokens(provider), **tokens}
    data[provider] = merged
    set_setup_provider_tokens(provider, merged, updated_at=str(_now_ts()))
    save_token_store(data)
    return merged


def get_secret(name: str, *, provider: str | None = None, key: str | None = None, default: str = "") -> str:
    env_value = os.getenv(name, "").strip()
    if env_value:
        return env_value
    if provider:
        provider_tokens = get_provider_tokens(provider)
        if key and provider_tokens.get(key):
            return str(provider_tokens[key]).strip()
        if provider_tokens.get(name):
            return str(provider_tokens[name]).strip()
    return default


def _token_valid(token_payload: dict) -> bool:
    access_token = str(token_payload.get("access_token", "")).strip()
    expires_at = int(token_payload.get("expires_at", 0) or 0)
    if not access_token:
        return False
    if not expires_at:
        return True
    return expires_at > _now_ts() + 60


def _post_form(url: str, payload: dict) -> dict:
    body = urlencode(payload).encode("utf-8")
    request = Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def _refresh_google_tokens(refresh_token: str) -> dict:
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if not (client_id and client_secret and refresh_token):
        return {}
    payload = _post_form(
        "https://oauth2.googleapis.com/token",
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
        },
    )
    expires_in = int(payload.get("expires_in", 3600) or 3600)
    return {
        "access_token": payload.get("access_token", ""),
        "token_type": payload.get("token_type", "Bearer"),
        "scope": payload.get("scope", ""),
        "expires_at": _now_ts() + expires_in,
    }


def _refresh_microsoft_tokens(refresh_token: str) -> dict:
    tenant_id = os.getenv("MICROSOFT_TENANT_ID", "common").strip() or "common"
    client_id = os.getenv("MICROSOFT_CLIENT_ID", "").strip()
    client_secret = os.getenv("MICROSOFT_CLIENT_SECRET", "").strip()
    redirect_uri = os.getenv("MICROSOFT_REDIRECT_URI", "").strip()
    if not (tenant_id and client_id and client_secret and refresh_token):
        return {}
    payload = _post_form(
        f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token",
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
            "grant_type": "refresh_token",
            "redirect_uri": redirect_uri,
            "scope": os.getenv(
                "MICROSOFT_OAUTH_SCOPES",
                "offline_access User.Read Mail.Read Files.Read Team.ReadBasic.All",
            ),
        },
    )
    expires_in = int(payload.get("expires_in", 3600) or 3600)
    return {
        "access_token": payload.get("access_token", ""),
        "refresh_token": payload.get("refresh_token", refresh_token),
        "token_type": payload.get("token_type", "Bearer"),
        "scope": payload.get("scope", ""),
        "expires_at": _now_ts() + expires_in,
    }


def get_google_access_token() -> str:
    direct = os.getenv("GOOGLE_ACCESS_TOKEN", "").strip()
    if direct:
        return direct
    token_payload = get_provider_tokens("google")
    if _token_valid(token_payload):
        return str(token_payload.get("access_token", "")).strip()
    refresh_token = str(token_payload.get("refresh_token", "")).strip()
    if not refresh_token:
        return ""
    refreshed = _refresh_google_tokens(refresh_token)
    if refreshed.get("access_token"):
        token_payload.update(refreshed)
        set_provider_tokens("google", token_payload)
        return refreshed["access_token"]
    return ""


def get_microsoft_graph_access_token() -> str:
    direct = os.getenv("MICROSOFT_GRAPH_ACCESS_TOKEN", "").strip()
    if direct:
        return direct
    token_payload = get_provider_tokens("microsoft")
    if _token_valid(token_payload):
        return str(token_payload.get("access_token", "")).strip()
    refresh_token = str(token_payload.get("refresh_token", "")).strip()
    if not refresh_token:
        return ""
    refreshed = _refresh_microsoft_tokens(refresh_token)
    if refreshed.get("access_token"):
        token_payload.update(refreshed)
        set_provider_tokens("microsoft", token_payload)
        return refreshed["access_token"]
    return ""


def get_slack_bot_token() -> str:
    direct = os.getenv("SLACK_BOT_TOKEN", "").strip()
    if direct:
        return direct
    token_payload = get_provider_tokens("slack")
    return str(token_payload.get("access_token", "")).strip()


def _port_open(host: str, port: int, timeout: float = 0.7) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _qdrant_reachable() -> bool:
    qdrant_url = os.getenv("QDRANT_URL", "http://localhost:6333").rstrip("/")
    try:
        request = Request(f"{qdrant_url}/collections")
        with urlopen(request, timeout=1.5) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def _aws_credentials_available() -> bool:
    try:
        import boto3
    except Exception:
        return False
    try:
        session = boto3.Session()
        credentials = session.get_credentials()
        return credentials is not None
    except Exception:
        return False


def build_google_oauth_config() -> dict:
    return {
        "client_id": os.getenv("GOOGLE_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("GOOGLE_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.getenv("GOOGLE_REDIRECT_URI", "http://127.0.0.1:8787/oauth/google/callback").strip(),
        "scopes": os.getenv(
            "GOOGLE_OAUTH_SCOPES",
            "https://www.googleapis.com/auth/gmail.readonly https://www.googleapis.com/auth/drive.readonly",
        ).strip(),
    }


def build_microsoft_oauth_config() -> dict:
    return {
        "tenant_id": os.getenv("MICROSOFT_TENANT_ID", "common").strip() or "common",
        "client_id": os.getenv("MICROSOFT_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("MICROSOFT_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.getenv("MICROSOFT_REDIRECT_URI", "http://127.0.0.1:8787/oauth/microsoft/callback").strip(),
        "scopes": os.getenv(
            "MICROSOFT_OAUTH_SCOPES",
            "offline_access User.Read Mail.Read Files.Read Team.ReadBasic.All",
        ).strip(),
    }


def build_slack_oauth_config() -> dict:
    return {
        "client_id": os.getenv("SLACK_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("SLACK_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.getenv("SLACK_REDIRECT_URI", "http://127.0.0.1:8787/oauth/slack/callback").strip(),
        "scopes": os.getenv(
            "SLACK_OAUTH_SCOPES",
            "channels:read channels:history groups:read groups:history",
        ).strip(),
    }


def build_google_oauth_start_url(state_token: str) -> str:
    config = build_google_oauth_config()
    params = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": config["scopes"],
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state_token,
    }
    return "https://accounts.google.com/o/oauth2/v2/auth?" + urlencode(params)


def build_microsoft_oauth_start_url(state_token: str) -> str:
    config = build_microsoft_oauth_config()
    params = {
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "response_mode": "query",
        "scope": config["scopes"],
        "state": state_token,
    }
    return f"https://login.microsoftonline.com/{config['tenant_id']}/oauth2/v2.0/authorize?" + urlencode(params)


def build_slack_oauth_start_url(state_token: str) -> str:
    config = build_slack_oauth_config()
    params = {
        "client_id": config["client_id"],
        "scope": config["scopes"],
        "redirect_uri": config["redirect_uri"],
        "state": state_token,
    }
    return "https://slack.com/oauth/v2/authorize?" + urlencode(params)


def exchange_google_oauth_code(code: str) -> dict:
    config = build_google_oauth_config()
    payload = _post_form(
        "https://oauth2.googleapis.com/token",
        {
            "code": code,
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "redirect_uri": config["redirect_uri"],
            "grant_type": "authorization_code",
        },
    )
    expires_in = int(payload.get("expires_in", 3600) or 3600)
    tokens = {
        "access_token": payload.get("access_token", ""),
        "refresh_token": payload.get("refresh_token", ""),
        "token_type": payload.get("token_type", "Bearer"),
        "scope": payload.get("scope", config["scopes"]),
        "expires_at": _now_ts() + expires_in,
    }
    return set_provider_tokens("google", tokens)


def exchange_microsoft_oauth_code(code: str) -> dict:
    config = build_microsoft_oauth_config()
    payload = _post_form(
        f"https://login.microsoftonline.com/{config['tenant_id']}/oauth2/v2.0/token",
        {
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "code": code,
            "redirect_uri": config["redirect_uri"],
            "grant_type": "authorization_code",
            "scope": config["scopes"],
        },
    )
    expires_in = int(payload.get("expires_in", 3600) or 3600)
    tokens = {
        "access_token": payload.get("access_token", ""),
        "refresh_token": payload.get("refresh_token", ""),
        "token_type": payload.get("token_type", "Bearer"),
        "scope": payload.get("scope", config["scopes"]),
        "expires_at": _now_ts() + expires_in,
    }
    return set_provider_tokens("microsoft", tokens)


def exchange_slack_oauth_code(code: str) -> dict:
    config = build_slack_oauth_config()
    payload = _post_form(
        "https://slack.com/api/oauth.v2.access",
        {
            "client_id": config["client_id"],
            "client_secret": config["client_secret"],
            "code": code,
            "redirect_uri": config["redirect_uri"],
        },
    )
    if not payload.get("ok"):
        raise ValueError(payload.get("error", "Slack OAuth exchange failed."))
    tokens = {
        "access_token": payload.get("access_token", ""),
        "scope": payload.get("scope", ""),
        "team": payload.get("team", {}),
        "bot_user_id": payload.get("bot_user_id", ""),
        "app_id": payload.get("app_id", ""),
    }
    return set_provider_tokens("slack", tokens)


def _env_present(key: str) -> bool:
    return bool(os.getenv(key, "").strip())


def _env_any_present(keys: tuple[str, ...]) -> bool:
    return any(_env_present(key) for key in keys)


def _env_all_present(keys: tuple[str, ...]) -> bool:
    return all(_env_present(key) for key in keys)


def _commands_available(commands: tuple[str, ...]) -> bool:
    return any(shutil.which(command) is not None for command in commands)


def _python_modules_available(modules: tuple[str, ...]) -> bool:
    return any(importlib.util.find_spec(module) is not None for module in modules)


def _component_enabled(integration_id: str) -> bool:
    snapshot = get_setup_component_snapshot(integration_id)
    if integration_id in {"cve_database", "nmap", "zap", "owasp_dependency_check"}:
        security_tools = get_setup_component_snapshot("security_tools")
        if security_tools and not security_tools.get("enabled", True):
            return False
    return True if not snapshot else bool(snapshot.get("enabled", True))


def _qdrant_health(url: str) -> bool:
    base_url = (url or "http://localhost:6333").rstrip("/")
    try:
        request = Request(f"{base_url}/collections")
        with urlopen(request, timeout=1.5) as response:
            return 200 <= response.status < 300
    except Exception:
        return False


def _detected_by_definition(definition: IntegrationDefinition) -> tuple[bool, str]:
    if definition.id == "google_workspace":
        oauth_ready = _env_all_present(definition.env_all)
        if _env_any_present(definition.env_any) or bool(get_google_access_token()):
            return True, "direct token or refreshed OAuth token available"
        if oauth_ready:
            return False, "OAuth client configuration present but no access token acquired yet"
        return False, "missing Google token and OAuth client configuration"
    if definition.id == "microsoft_graph":
        oauth_ready = _env_all_present(definition.env_all)
        if _env_any_present(definition.env_any) or bool(get_microsoft_graph_access_token()):
            return True, "direct token or refreshed OAuth token available"
        if oauth_ready:
            return False, "OAuth client configuration present but no access token acquired yet"
        return False, "missing Microsoft token and OAuth client configuration"
    if definition.id == "slack":
        oauth_ready = _env_all_present(definition.env_all)
        if _env_any_present(definition.env_any) or bool(get_slack_bot_token()):
            return True, "bot token or OAuth installation available"
        if oauth_ready:
            return False, "OAuth client configuration present but no installed bot token available yet"
        return False, "missing Slack bot token and OAuth client configuration"
    if definition.id == "telegram":
        if _env_any_present(definition.env_any):
            return True, "bot token configured"
        session_ready = _env_all_present(("TELEGRAM_SESSION_STRING", "TELEGRAM_API_ID", "TELEGRAM_API_HASH"))
        return session_ready, "user session configured" if session_ready else "missing Telegram bot token or user session"
    if definition.id == "aws":
        available = _aws_credentials_available()
        return available, "AWS credentials found in active boto3 chain" if available else "no AWS credentials found in boto3 chain"
    if definition.id == "qdrant":
        configured = _env_all_present(definition.env_all)
        if not configured:
            return False, "missing QDRANT_URL"
        healthy = _qdrant_health(os.getenv(definition.healthcheck_url_env, definition.healthcheck_url_default))
        return healthy, "reachable Qdrant endpoint" if healthy else "Qdrant URL configured but endpoint is not reachable"
    if definition.id == "cve_database":
        url = os.getenv("CVE_API_BASE_URL", definition.healthcheck_url_default or "https://services.nvd.nist.gov/rest/json/cves/2.0").strip()
        return bool(url), "CVE/NVD endpoint configured" if url else "missing CVE/NVD endpoint"
    if definition.id == "playwright":
        healthy = _python_modules_available(definition.python_modules_any) or _commands_available(definition.commands_any)
        return healthy, "Playwright package or CLI available" if healthy else "missing Playwright package and CLI"
    if definition.commands_any:
        healthy = _commands_available(definition.commands_any)
        return healthy, definition.health_description if healthy else f"missing local dependency: {', '.join(definition.commands_any)}"
    if definition.env_all or definition.env_any:
        healthy = _env_all_present(definition.env_all) and (True if not definition.env_any else _env_any_present(definition.env_any) or _env_all_present(definition.env_all))
        if definition.env_all and not _env_all_present(definition.env_all):
            return False, f"missing required configuration: {', '.join(definition.env_all)}"
        if definition.env_any and not _env_any_present(definition.env_any):
            return False, f"missing configuration: one of {', '.join(definition.env_any)}"
        return healthy, definition.health_description or "configuration detected"
    return True, definition.health_description or "available"


def _service_record(name: str, configured: bool, details: str, *, oauth_ready: bool = False, setup_url: str = "", setup_hint: str = "", enabled: bool = True, docs_path: str = "", status: str = "", routing_eligible: bool | None = None, component_id: str = "") -> dict:
    return {
        "name": name,
        "component_id": component_id or name,
        "configured": configured,
        "enabled": enabled,
        "oauth_ready": oauth_ready,
        "details": details,
        "setup_url": setup_url,
        "setup_hint": setup_hint,
        "docs_path": docs_path,
        "status": status or ("ready" if configured else "missing"),
        "routing_eligible": configured if routing_eligible is None else routing_eligible,
    }


def _require_all(services: dict, *service_names: str) -> tuple[bool, list[str]]:
    missing = [name for name in service_names if not services.get(name, {}).get("configured")]
    return not missing, missing


def _build_service_status() -> dict:
    services: dict[str, dict] = {}
    google_oauth = build_google_oauth_config()
    microsoft_oauth = build_microsoft_oauth_config()
    slack_oauth = build_slack_oauth_config()

    for definition in INTEGRATION_DEFINITIONS:
        enabled = _component_enabled(definition.id)
        configured, health_detail = _detected_by_definition(definition)
        oauth_ready = False
        if definition.id == "google_workspace":
            oauth_ready = bool(google_oauth["client_id"] and google_oauth["client_secret"])
        elif definition.id == "microsoft_graph":
            oauth_ready = bool(microsoft_oauth["client_id"] and microsoft_oauth["client_secret"])
        elif definition.id == "slack":
            oauth_ready = bool(slack_oauth["client_id"] and slack_oauth["client_secret"])

        status = "ready" if configured else "missing"
        details = definition.health_description or definition.description
        if not enabled:
            configured = False
            status = "disabled"
            health_detail = "component disabled in setup DB"
            details = f"{details} Component disabled in setup DB."
        elif not configured:
            status = "oauth_ready" if oauth_ready else "missing"

        services[definition.id] = _service_record(
            definition.id,
            configured,
            details,
            oauth_ready=oauth_ready,
            setup_url=definition.setup_url or definition.oauth_start_path,
            setup_hint=definition.setup_hint,
            enabled=enabled,
            docs_path=definition.docs_path,
            status=status,
            routing_eligible=configured and enabled,
            component_id=definition.id,
        )
        services[definition.id]["health"] = {
            "status": status,
            "detail": health_detail,
            "checked_at": _now_ts(),
        }
        services[definition.id]["integration_contract"] = {
            "config_fields": [field.key for field in definition.fields],
            "oauth_provider": definition.oauth_provider,
            "provider_token": definition.provider_token,
        }
    return services


def _agent_requirements(card: dict) -> tuple[list[str], str]:
    explicit = card.get("requirements", [])
    if isinstance(explicit, list) and explicit:
        return [str(item).strip() for item in explicit if str(item).strip()], ""
    fallback = LEGACY_AGENT_REQUIREMENTS.get(str(card.get("agent_name", "")).strip())
    if fallback:
        return list(fallback), "legacy requirements fallback; declare AGENT_METADATA requirements"
    return [], ""


def _requirement_status(services: dict, requirement: str) -> tuple[bool, list[str], str]:
    rule = REQUIREMENT_RULES.get(requirement)
    if rule:
        configured = [name for name in rule.integrations if services.get(name, {}).get("routing_eligible", False)]
        if rule.mode == "any":
            return bool(configured), ([] if configured else [requirement]), rule.description
        missing = [name for name in rule.integrations if not services.get(name, {}).get("routing_eligible", False)]
        return not missing, missing, rule.description

    if requirement not in services:
        return False, [requirement], f"Unknown setup requirement: {requirement}"
    available = bool(services[requirement].get("routing_eligible", False))
    detail = str(services[requirement].get("details", "") or "")
    return available, ([] if available else [requirement]), detail


def _build_agent_status(services: dict, agent_cards: list[dict]) -> tuple[dict, list[str], dict, list[str]]:
    agent_status: dict[str, dict] = {}
    contract_warnings: list[str] = []

    for card in agent_cards:
        agent_name = str(card.get("agent_name", "")).strip()
        if not agent_name:
            continue
        requirements, warning = _agent_requirements(card)
        if warning:
            contract_warnings.append(f"{agent_name}: {warning}")

        missing: list[str] = []
        notes: list[str] = []
        available = True
        for requirement in requirements:
            okay, missing_items, description = _requirement_status(services, requirement)
            if description:
                notes.append(description)
            if not okay:
                available = False
                missing.extend(missing_items)

        unique_missing = sorted(dict.fromkeys(missing))
        note = " ".join(dict.fromkeys(note for note in notes if note)).strip()
        if not requirements:
            note = "No extra setup requirements declared."
        agent_status[agent_name] = {
            "available": available,
            "missing_services": unique_missing,
            "note": note,
            "requirements": requirements,
        }

    available_agents = sorted([name for name, item in agent_status.items() if item["available"]])
    disabled_agents = {name: item for name, item in sorted(agent_status.items()) if not item["available"]}
    return agent_status, available_agents, disabled_agents, contract_warnings


def build_setup_snapshot(agent_cards: list[dict]) -> dict:
    cached_snapshot = _read_json(SETUP_STATUS_JSON_PATH, {})
    if not agent_cards and isinstance(cached_snapshot.get("agent_card_cache"), list):
        agent_cards = cached_snapshot["agent_card_cache"]
    services = _build_service_status()
    agent_status, available_agents, disabled_agents, contract_warnings = _build_agent_status(services, agent_cards)
    integration_defs = integration_index()
    setup_actions = []
    for service_name, item in services.items():
        if item["configured"]:
            continue
        definition = integration_defs.get(service_name)
        if item["oauth_ready"] and item["setup_url"]:
            setup_actions.append(
                {
                    "service": service_name,
                    "action": "oauth",
                    "path": item["setup_url"],
                    "hint": item["setup_hint"],
                    "docs_path": item.get("docs_path", ""),
                }
            )
        else:
            setup_actions.append(
                {
                    "service": service_name,
                    "action": "enable" if item.get("status") == "disabled" else "manual",
                    "path": "",
                    "hint": item["setup_hint"] or item["details"],
                    "docs_path": item.get("docs_path", ""),
                    "component_id": definition.id if definition else item.get("component_id", service_name),
                }
            )

    summary_lines = ["Configured integrations:"]
    for service_name, item in services.items():
        status = str(item.get("status", "unknown"))
        suffix = " (OAuth ready)" if item["oauth_ready"] and not item["configured"] else ""
        summary_lines.append(f"- {service_name}: {status}{suffix}")

    summary_lines.append("")
    summary_lines.append(f"Available agents ({len(available_agents)}):")
    summary_lines.append("- " + ", ".join(available_agents) if available_agents else "- none")
    if disabled_agents:
        summary_lines.append("")
        summary_lines.append("Disabled agents:")
        for agent_name, item in disabled_agents.items():
            missing = ", ".join(item["missing_services"]) or "unknown"
            summary_lines.append(f"- {agent_name}: missing {missing}")
    if contract_warnings:
        summary_lines.append("")
        summary_lines.append("Integration contract warnings:")
        for warning in sorted(contract_warnings):
            summary_lines.append(f"- {warning}")

    snapshot = {
        "generated_at": _now_ts(),
        "services": services,
        "integrations": services,
        "agents": agent_status,
        "agent_card_cache": agent_cards,
        "available_agents": available_agents,
        "disabled_agents": disabled_agents,
        "setup_actions": setup_actions,
        "contract_warnings": sorted(contract_warnings),
        "summary_text": "\n".join(summary_lines),
    }
    _write_json(SETUP_STATUS_JSON_PATH, snapshot)
    _write_text(SETUP_STATUS_TEXT_PATH, snapshot["summary_text"])
    return snapshot


def issue_oauth_state_token() -> str:
    return secrets.token_urlsafe(24)
