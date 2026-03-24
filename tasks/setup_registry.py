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
from tasks.setup_config_store import apply_setup_env_defaults, get_setup_component_snapshot
from tasks.sqlite_store import get_setup_provider_tokens, set_setup_provider_tokens

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


def _service_record(name: str, configured: bool, details: str, *, oauth_ready: bool = False, setup_url: str = "", setup_hint: str = "") -> dict:
    return {
        "name": name,
        "configured": configured,
        "oauth_ready": oauth_ready,
        "details": details,
        "setup_url": setup_url,
        "setup_hint": setup_hint,
    }


def _require_all(services: dict, *service_names: str) -> tuple[bool, list[str]]:
    missing = [name for name in service_names if not services.get(name, {}).get("configured")]
    return not missing, missing


def _build_service_status() -> dict:
    google_oauth = build_google_oauth_config()
    microsoft_oauth = build_microsoft_oauth_config()
    slack_oauth = build_slack_oauth_config()
    services = {
        "openai": _service_record(
            "openai",
            bool(os.getenv("OPENAI_API_KEY", "").strip()),
            (
                "OpenAI API key for the core LLM stack. "
                f"general_model={os.getenv('OPENAI_MODEL_GENERAL', os.getenv('OPENAI_MODEL', 'gpt-4o-mini'))}, "
                f"coding_model={os.getenv('OPENAI_MODEL_CODING', os.getenv('OPENAI_CODEX_MODEL', os.getenv('OPENAI_MODEL_GENERAL', os.getenv('OPENAI_MODEL', 'gpt-4o-mini'))))}."
            ),
        ),
        "serpapi": _service_record(
            "serpapi",
            bool(os.getenv("SERP_API_KEY", "").strip()),
            "SerpAPI access for web search, scholarship, and patent search agents.",
        ),
        "elevenlabs": _service_record(
            "elevenlabs",
            bool(get_secret("ELEVENLABS_API_KEY", provider="elevenlabs", key="api_key")),
            "ElevenLabs API access for voice discovery, speech generation, and transcription.",
            setup_hint="Provide ELEVENLABS_API_KEY to enable ElevenLabs voice and audio agents.",
        ),
        "google_workspace": _service_record(
            "google_workspace",
            bool(get_google_access_token()),
            "Google Workspace access for Gmail and Drive.",
            oauth_ready=bool(google_oauth["client_id"] and google_oauth["client_secret"]),
            setup_url="/oauth/google/start",
            setup_hint="Configure GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET, then complete the Google OAuth flow.",
        ),
        "telegram": _service_record(
            "telegram",
            bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip())
            or bool(
                os.getenv("TELEGRAM_SESSION_STRING", "").strip()
                and os.getenv("TELEGRAM_API_ID", "").strip()
                and os.getenv("TELEGRAM_API_HASH", "").strip()
            ),
            "Telegram bot token or personal session string plus API credentials.",
        ),
        "slack": _service_record(
            "slack",
            bool(get_slack_bot_token()),
            "Slack bot token for workspace read access.",
            oauth_ready=bool(slack_oauth["client_id"] and slack_oauth["client_secret"]),
            setup_url="/oauth/slack/start",
            setup_hint="Configure SLACK_CLIENT_ID and SLACK_CLIENT_SECRET, then install the Slack app with OAuth.",
        ),
        "microsoft_graph": _service_record(
            "microsoft_graph",
            bool(get_microsoft_graph_access_token()),
            "Microsoft Graph delegated token for Outlook, Teams, and Drive access.",
            oauth_ready=bool(microsoft_oauth["client_id"] and microsoft_oauth["client_secret"]),
            setup_url="/oauth/microsoft/start",
            setup_hint="Configure MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET, then complete the Microsoft OAuth flow.",
        ),
        "qdrant": _service_record(
            "qdrant",
            _qdrant_reachable(),
            f"Qdrant vector store at {os.getenv('QDRANT_URL', 'http://localhost:6333')}.",
        ),
        "aws": _service_record(
            "aws",
            _aws_credentials_available(),
            "AWS credentials available through the default boto3 credential chain or environment variables.",
            setup_hint="Provide AWS credentials via environment variables, profile, or instance role.",
        ),
        "codex_cli": _service_record(
            "codex_cli",
            shutil.which("codex") is not None,
            "Local codex CLI available on PATH.",
        ),
        "owasp_dependency_check": _service_record(
            "owasp_dependency_check",
            shutil.which("dependency-check") is not None,
            "OWASP Dependency-Check available on PATH.",
        ),
        "zap": _service_record(
            "zap",
            shutil.which("zap-baseline.py") is not None or shutil.which("owasp-zap") is not None,
            "OWASP ZAP baseline tooling available on PATH.",
        ),
        "nmap": _service_record(
            "nmap",
            shutil.which("nmap") is not None,
            "Nmap available on PATH.",
        ),
        "cve_database": _service_record(
            "cve_database",
            bool(os.getenv("CVE_API_BASE_URL", "https://services.nvd.nist.gov/rest/json/cves/2.0").strip()),
            "Public CVE/NVD API endpoint configured. NVD_API_KEY is optional for higher rate limits.",
            setup_hint="Optionally provide NVD_API_KEY for higher-rate NVD access.",
        ),
        "playwright": _service_record(
            "playwright",
            importlib.util.find_spec("playwright") is not None or shutil.which("playwright") is not None,
            "Playwright available for interactive browser automation.",
            setup_hint="Install Playwright and browser binaries to enable interactive browser control.",
        ),
        "privileged_control": _service_record(
            "privileged_control",
            True,
            "Privileged control policy is available. Configure explicit approvals, scope, and kill-switch before high-privilege runs.",
            setup_hint="Review privileged_control component in setup UI/CLI before enabling root or destructive automation.",
        ),
        "whatsapp": _service_record(
            "whatsapp",
            bool(os.getenv("WHATSAPP_ACCESS_TOKEN", "").strip() and os.getenv("WHATSAPP_PHONE_NUMBER_ID", "").strip()),
            "WhatsApp Business Cloud API credentials. No inbox-reading agent is implemented yet.",
        ),
    }
    component_map = {
        "openai": "openai",
        "serpapi": "serpapi",
        "elevenlabs": "elevenlabs",
        "google_workspace": "google_workspace",
        "telegram": "telegram",
        "slack": "slack",
        "microsoft_graph": "microsoft_graph",
        "qdrant": "qdrant",
        "aws": "aws",
        "whatsapp": "whatsapp",
        "privileged_control": "privileged_control",
        "cve_database": "security_tools",
    }
    for service_name, component_id in component_map.items():
        snapshot = get_setup_component_snapshot(component_id)
        if snapshot and not snapshot.get("enabled", True):
            services[service_name]["configured"] = False
            services[service_name]["details"] = f"{services[service_name]['details']} Component disabled in setup DB."
            services[service_name]["setup_hint"] = (
                services[service_name].get("setup_hint", "") + " Re-enable this component from setup UI or CLI."
            ).strip()
    return services


def _build_agent_status(services: dict, agent_cards: list[dict]) -> tuple[dict, list[str], dict]:
    agent_names = [card["agent_name"] for card in agent_cards]
    agent_status: dict[str, dict] = {}

    def mark(agent_name: str, available: bool, missing: list[str] | None = None, note: str = ""):
        if agent_name not in agent_names:
            return
        agent_status[agent_name] = {
            "available": available,
            "missing_services": missing or [],
            "note": note,
        }

    llm_agents = [
        "planner_agent",
        "worker_agent",
        "reviewer_agent",
        "excel_agent",
        "report_agent",
        "prospect_identification_agent",
        "funding_stage_screening_agent",
        "sector_intelligence_agent",
        "company_meeting_brief_agent",
        "investor_positioning_agent",
        "financial_mis_analysis_agent",
        "deal_materials_agent",
        "investor_matching_agent",
        "investor_outreach_agent",
        "proposal_review_agent",
        "prior_art_analysis_agent",
        "claim_evidence_mapping_agent",
        "communication_scope_guard_agent",
        "communication_hub_agent",
        "security_scope_guard_agent",
        "web_recon_agent",
        "api_surface_mapper_agent",
        "unauthenticated_endpoint_audit_agent",
        "idor_bola_risk_agent",
        "security_headers_agent",
        "tls_assessment_agent",
        "dependency_audit_agent",
        "sast_review_agent",
        "prompt_security_agent",
        "ai_asset_exposure_agent",
        "security_findings_agent",
        "recon_agent",
        "evidence_agent",
        "exploit_agent",
        "security_report_agent",
        "access_control_agent",
        "web_crawl_agent",
        "document_ingestion_agent",
        "ocr_agent",
        "image_agent",
        "entity_resolution_agent",
        "knowledge_graph_agent",
        "timeline_agent",
        "source_verification_agent",
        "people_research_agent",
        "company_research_agent",
        "relationship_mapping_agent",
        "news_monitor_agent",
        "compliance_risk_agent",
        "structured_data_agent",
        "citation_agent",
        "reddit_agent",
        "deep_research_agent",
        "agent_factory_agent",
        "dynamic_agent_runner",
        "aws_scope_guard_agent",
        "aws_inventory_agent",
        "aws_cost_agent",
        "aws_automation_agent",
        "location_agent",
        "flight_tracking_agent",
        "transport_route_agent",
        "travel_hub_agent",
        "voice_catalog_agent",
        "speech_generation_agent",
        "speech_transcription_agent",
        "channel_gateway_agent",
        "session_router_agent",
        "browser_automation_agent",
        "scheduler_agent",
        "heartbeat_agent",
        "monitor_rule_agent",
        "stock_monitor_agent",
        "long_document_agent",
    ]

    for agent_name in llm_agents:
        ok, missing = _require_all(services, "openai")
        mark(agent_name, ok, missing, "Requires OpenAI for reasoning.")

    ok, missing = _require_all(services, "openai", "serpapi")
    mark("google_search_agent", ok, missing, "Requires OpenAI and SerpAPI.")
    mark("literature_search_agent", ok, missing, "Requires OpenAI and SerpAPI.")
    mark("patent_search_agent", ok, missing, "Requires OpenAI and SerpAPI.")
    mark("flight_tracking_agent", ok, missing, "Requires OpenAI and SerpAPI.")
    mark("transport_route_agent", ok, missing, "Requires OpenAI and SerpAPI.")
    mark("travel_hub_agent", ok, missing, "Requires OpenAI and SerpAPI.")

    eleven_ok, eleven_missing = _require_all(services, "openai", "elevenlabs")
    mark("voice_catalog_agent", eleven_ok, eleven_missing, "Requires OpenAI and ElevenLabs.")
    mark("speech_generation_agent", eleven_ok, eleven_missing, "Requires OpenAI and ElevenLabs.")
    mark("speech_transcription_agent", eleven_ok, eleven_missing, "Requires OpenAI and ElevenLabs.")

    whatsapp_ok, whatsapp_missing = _require_all(services, "openai", "whatsapp")
    mark("whatsapp_agent", whatsapp_ok, whatsapp_missing, "Requires OpenAI and WhatsApp Cloud API credentials.")

    any_notify = any(
        services[name]["configured"]
        for name in ("telegram", "slack", "whatsapp")
        if name in services
    )
    mark(
        "notification_dispatch_agent",
        services["openai"]["configured"] and any_notify,
        ([] if services["openai"]["configured"] else ["openai"]) + ([] if any_notify else ["outbound_channel"]),
        "Requires OpenAI and at least one configured outbound channel such as Telegram, Slack, or WhatsApp.",
    )

    interactive_browser_ok, interactive_browser_missing = _require_all(services, "openai", "playwright")
    mark(
        "interactive_browser_agent",
        interactive_browser_ok,
        interactive_browser_missing,
        "Requires OpenAI and Playwright. Headed mode may also require a desktop display or Xvfb.",
    )

    ok, missing = _require_all(services, "openai")
    qdrant_ok = services.get("qdrant", {}).get("configured", False)
    mark(
        "memory_index_agent",
        ok and qdrant_ok,
        missing + ([] if qdrant_ok else ["qdrant"]),
        "Requires OpenAI and a reachable Qdrant instance.",
    )

    google_ok, google_missing = _require_all(services, "openai", "google_workspace")
    mark("gmail_agent", google_ok, google_missing, "Requires OpenAI and configured Google Workspace access.")
    mark("drive_agent", google_ok, google_missing, "Requires OpenAI and configured Google Workspace access.")

    telegram_ok, telegram_missing = _require_all(services, "openai", "telegram")
    mark("telegram_agent", telegram_ok, telegram_missing, "Requires OpenAI and Telegram credentials.")

    slack_ok, slack_missing = _require_all(services, "openai", "slack")
    mark("slack_agent", slack_ok, slack_missing, "Requires OpenAI and Slack bot access.")

    ms_ok, ms_missing = _require_all(services, "openai", "microsoft_graph")
    mark("microsoft_graph_agent", ms_ok, ms_missing, "Requires OpenAI and Microsoft Graph access.")

    any_comm = any(
        services[name]["configured"]
        for name in ("google_workspace", "telegram", "slack", "microsoft_graph")
        if name in services
    )
    openai_ok = services["openai"]["configured"]
    mark(
        "communication_scope_guard_agent",
        openai_ok and any_comm,
        ([] if openai_ok else ["openai"]) + ([] if any_comm else ["communication_suite"]),
        "Requires OpenAI and at least one configured communication suite.",
    )
    mark(
        "communication_hub_agent",
        openai_ok and any_comm,
        ([] if openai_ok else ["openai"]) + ([] if any_comm else ["communication_suite"]),
        "Requires OpenAI and at least one configured communication suite.",
    )

    coding_ok = services["openai"]["configured"] or services["codex_cli"]["configured"]
    mark(
        "coding_agent",
        coding_ok,
        [] if coding_ok else ["openai_or_codex_cli"],
        "Requires OpenAI API access or a local codex CLI.",
    )
    mark(
        "master_coding_agent",
        coding_ok,
        [] if coding_ok else ["openai_or_codex_cli"],
        "Requires OpenAI API access or a local codex CLI.",
    )

    os_ok = services["openai"]["configured"]
    mark("os_agent", os_ok, [] if os_ok else ["openai"], "Uses the LLM to plan shell work.")

    aws_ok, aws_missing = _require_all(services, "openai", "aws")
    mark("aws_scope_guard_agent", aws_ok, aws_missing, "Requires OpenAI and AWS credentials.")
    mark("aws_inventory_agent", aws_ok, aws_missing, "Requires OpenAI and AWS credentials.")
    mark("aws_cost_agent", aws_ok, aws_missing, "Requires OpenAI and AWS credentials.")
    mark("aws_automation_agent", aws_ok, aws_missing, "Requires OpenAI and AWS credentials.")

    scan_tools_available = services.get("nmap", {}).get("configured", False) or services.get("zap", {}).get("configured", False)
    mark(
        "scanner_agent",
        services["openai"]["configured"] and scan_tools_available,
        ([] if services["openai"]["configured"] else ["openai"]) + ([] if scan_tools_available else ["nmap_or_zap"]),
        "Requires OpenAI and at least one safe scanner tool such as Nmap or ZAP baseline.",
    )

    for card in agent_cards:
        agent_status.setdefault(
            card["agent_name"],
            {
                "available": True,
                "missing_services": [],
                "note": "No extra setup requirements declared.",
            },
        )

    available_agents = sorted([name for name, item in agent_status.items() if item["available"]])
    disabled_agents = {
        name: item
        for name, item in sorted(agent_status.items())
        if not item["available"]
    }
    return agent_status, available_agents, disabled_agents


def build_setup_snapshot(agent_cards: list[dict]) -> dict:
    cached_snapshot = _read_json(SETUP_STATUS_JSON_PATH, {})
    if not agent_cards and isinstance(cached_snapshot.get("agent_card_cache"), list):
        agent_cards = cached_snapshot["agent_card_cache"]
    services = _build_service_status()
    agent_status, available_agents, disabled_agents = _build_agent_status(services, agent_cards)
    setup_actions = []
    for service_name, item in services.items():
        if item["configured"]:
            continue
        if item["oauth_ready"] and item["setup_url"]:
            setup_actions.append(
                {
                    "service": service_name,
                    "action": "oauth",
                    "path": item["setup_url"],
                    "hint": item["setup_hint"],
                }
            )
        else:
            setup_actions.append(
                {
                    "service": service_name,
                    "action": "manual",
                    "path": "",
                    "hint": item["setup_hint"] or item["details"],
                }
            )

    summary_lines = ["Configured services:"]
    for service_name, item in services.items():
        status = "configured" if item["configured"] else "not configured"
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

    snapshot = {
        "generated_at": _now_ts(),
        "services": services,
        "agents": agent_status,
        "agent_card_cache": agent_cards,
        "available_agents": available_agents,
        "disabled_agents": disabled_agents,
        "setup_actions": setup_actions,
        "summary_text": "\n".join(summary_lines),
    }
    _write_json(SETUP_STATUS_JSON_PATH, snapshot)
    _write_text(SETUP_STATUS_TEXT_PATH, snapshot["summary_text"])
    return snapshot


def issue_oauth_state_token() -> str:
    return secrets.token_urlsafe(24)
