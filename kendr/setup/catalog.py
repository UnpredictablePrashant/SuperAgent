from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class SetupField:
    key: str
    label: str
    description: str
    secret: bool = False
    required: bool = False
    default: str = ""


@dataclass(frozen=True, slots=True)
class IntegrationDefinition:
    id: str
    title: str
    category: str
    description: str
    provider_name: str = ""
    channel_name: str = ""
    auth_mode: str = "manual"
    docs_path: str = "docs/integrations.md"
    setup_hint: str = ""
    setup_url: str = ""
    oauth_provider: str = ""
    oauth_start_path: str = ""
    fields: tuple[SetupField, ...] = ()
    env_any: tuple[str, ...] = ()
    env_all: tuple[str, ...] = ()
    provider_token: str = ""
    python_modules_any: tuple[str, ...] = ()
    commands_any: tuple[str, ...] = ()
    healthcheck_url_env: str = ""
    healthcheck_url_default: str = ""
    health_description: str = ""

    def component(self) -> dict:
        payload = {
            "id": self.id,
            "title": self.title,
            "category": self.category,
            "description": self.description,
            "fields": [asdict(field) for field in self.fields],
            "docs_path": self.docs_path,
            "integration_id": self.id,
        }
        if self.oauth_provider:
            payload["oauth_provider"] = self.oauth_provider
        if self.oauth_start_path:
            payload["oauth_start_path"] = self.oauth_start_path
        return payload


@dataclass(frozen=True, slots=True)
class RequirementRule:
    name: str
    mode: str
    integrations: tuple[str, ...]
    description: str


def _field(key: str, label: str, description: str, *, secret: bool = False, required: bool = False, default: str = "") -> SetupField:
    return SetupField(key=key, label=label, description=description, secret=secret, required=required, default=default)


INTEGRATION_DEFINITIONS: tuple[IntegrationDefinition, ...] = (
    IntegrationDefinition(
        id="openai",
        title="OpenAI",
        category="Providers",
        description="Primary LLM provider for orchestration, reasoning, OCR, embeddings, and research agents.",
        provider_name="openai",
        auth_mode="api_key",
        docs_path="docs/integrations.md#openai",
        setup_hint="Set OPENAI_API_KEY and choose the general/coding models before using the main runtime.",
        fields=(
            _field("OPENAI_API_KEY", "API Key", "OpenAI API key.", secret=True, required=True),
            _field("OPENAI_MODEL_GENERAL", "General Model", "Model for planning, orchestration, research, and general agents."),
            _field("OPENAI_MODEL_CODING", "Coding Model", "Model for coding-focused agents."),
            _field("OPENAI_MODEL", "Legacy Default Model", "Backward-compatible fallback model."),
            _field("OPENAI_CODEX_MODEL", "Legacy Codex Model", "Backward-compatible fallback coding model."),
            _field("OPENAI_VISION_MODEL", "Vision Model", "Model used by image and OCR workflows."),
            _field("OPENAI_EMBEDDING_MODEL", "Embedding Model", "Model used for embedding/vector workflows."),
        ),
        env_all=("OPENAI_API_KEY",),
        health_description="OpenAI API key available for the core LLM stack.",
    ),
    IntegrationDefinition(
        id="anthropic",
        title="Anthropic (Claude)",
        category="LLM Providers",
        description="Anthropic Claude models — Opus 4.6, Sonnet 4.6, Haiku 4.5 — for reasoning and general tasks.",
        provider_name="anthropic",
        auth_mode="api_key",
        docs_path="docs/integrations.md#anthropic",
        setup_hint="Set ANTHROPIC_API_KEY and optionally ANTHROPIC_MODEL (default: claude-haiku-4-5).",
        fields=(
            _field("ANTHROPIC_API_KEY", "API Key", "Anthropic API key from console.anthropic.com.", secret=True, required=True),
            _field("ANTHROPIC_MODEL", "Default Model", "Model to use (e.g. claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5)."),
        ),
        env_all=("ANTHROPIC_API_KEY",),
        health_description="Anthropic API key available for Claude models.",
    ),
    IntegrationDefinition(
        id="google_gemini",
        title="Google Gemini",
        category="LLM Providers",
        description="Google Gemini 2.5 Pro, Flash — fast and multimodal via the Generative AI API.",
        provider_name="google_gemini",
        auth_mode="api_key",
        docs_path="docs/integrations.md#google-gemini",
        setup_hint="Set GOOGLE_API_KEY and optionally GOOGLE_MODEL (default: gemini-2.0-flash).",
        fields=(
            _field("GOOGLE_API_KEY", "API Key", "Google AI Studio API key from aistudio.google.com.", secret=True, required=True),
            _field("GOOGLE_MODEL", "Default Model", "Model to use (e.g. gemini-2.5-pro, gemini-2.0-flash)."),
        ),
        env_all=("GOOGLE_API_KEY",),
        health_description="Google API key available for Gemini models.",
    ),
    IntegrationDefinition(
        id="xai",
        title="xAI (Grok)",
        category="LLM Providers",
        description="xAI Grok-3 with x_search tool — OpenAI-compatible API.",
        provider_name="xai",
        auth_mode="api_key",
        docs_path="docs/integrations.md#xai",
        setup_hint="Set XAI_API_KEY and optionally XAI_MODEL (default: grok-4). Base URL: https://api.x.ai/v1.",
        fields=(
            _field("XAI_API_KEY", "API Key", "xAI API key from console.x.ai.", secret=True, required=True),
            _field("XAI_MODEL", "Default Model", "Model to use (e.g. grok-4, grok-4.20-beta-latest-non-reasoning)."),
        ),
        env_all=("XAI_API_KEY",),
        health_description="xAI API key available for Grok models.",
    ),
    IntegrationDefinition(
        id="minimax",
        title="MiniMax",
        category="LLM Providers",
        description="MiniMax M2 language and image generation (image-01) — OpenAI-compatible API.",
        provider_name="minimax",
        auth_mode="api_key",
        docs_path="docs/integrations.md#minimax",
        setup_hint="Set MINIMAX_API_KEY and optionally MINIMAX_MODEL (default: MiniMax-M2).",
        fields=(
            _field("MINIMAX_API_KEY", "API Key", "MiniMax API key from platform.minimaxi.com.", secret=True, required=True),
            _field("MINIMAX_MODEL", "Default Model", "Model to use (e.g. MiniMax-M2, image-01)."),
        ),
        env_all=("MINIMAX_API_KEY",),
        health_description="MiniMax API key available.",
    ),
    IntegrationDefinition(
        id="qwen",
        title="Qwen (Alibaba)",
        category="LLM Providers",
        description="Alibaba Qwen-Max, Qwen-Plus via DashScope — OpenAI-compatible API.",
        provider_name="qwen",
        auth_mode="api_key",
        docs_path="docs/integrations.md#qwen",
        setup_hint="Set QWEN_API_KEY from dashscope.aliyuncs.com. Optionally set QWEN_MODEL (default: qwen-plus).",
        fields=(
            _field("QWEN_API_KEY", "API Key", "Alibaba DashScope API key (also called DASHSCOPE_API_KEY).", secret=True, required=True),
            _field("QWEN_MODEL", "Default Model", "Model to use (e.g. qwen-max, qwen-plus, qwen-turbo)."),
        ),
        env_all=("QWEN_API_KEY",),
        health_description="Qwen / DashScope API key available.",
    ),
    IntegrationDefinition(
        id="glm",
        title="GLM (Zhipu AI)",
        category="LLM Providers",
        description="Zhipu AI GLM-5 — OpenAI-compatible API from bigmodel.cn.",
        provider_name="glm",
        auth_mode="api_key",
        docs_path="docs/integrations.md#glm",
        setup_hint="Set GLM_API_KEY from bigmodel.cn. Optionally set GLM_MODEL (default: glm-4).",
        fields=(
            _field("GLM_API_KEY", "API Key", "Zhipu AI API key from bigmodel.cn.", secret=True, required=True),
            _field("GLM_MODEL", "Default Model", "Model to use (e.g. glm-5, glm-4, glm-4-flash)."),
        ),
        env_all=("GLM_API_KEY",),
        health_description="GLM / Zhipu AI API key available.",
    ),
    IntegrationDefinition(
        id="ollama",
        title="Ollama (Local)",
        category="LLM Providers",
        description="Run any model locally — Llama, Mistral, DeepSeek, Qwen, Gemma — via Ollama. No API key required.",
        provider_name="ollama",
        auth_mode="local_dependency",
        docs_path="docs/integrations.md#ollama",
        setup_hint="Install Ollama (ollama.ai), run `ollama serve`, then pull a model: `ollama pull llama3.2`. Set OLLAMA_MODEL to override default.",
        fields=(
            _field("OLLAMA_BASE_URL", "Ollama URL", "Ollama server URL (default: http://localhost:11434)."),
            _field("OLLAMA_MODEL", "Default Model", "Model to use (e.g. llama3.2, mistral, deepseek-r1, qwen2.5)."),
        ),
        healthcheck_url_env="OLLAMA_BASE_URL",
        healthcheck_url_default="http://localhost:11434",
        health_description="Ollama server reachable at configured URL.",
    ),
    IntegrationDefinition(
        id="openrouter",
        title="OpenRouter",
        category="LLM Providers",
        description="Single API key for 200+ models — GPT-5, Claude, Gemini, Llama, Mistral and more — via openrouter.ai.",
        provider_name="openrouter",
        auth_mode="api_key",
        docs_path="docs/integrations.md#openrouter",
        setup_hint="Set OPENROUTER_API_KEY from openrouter.ai. Set OPENROUTER_MODEL to choose a model (e.g. openai/gpt-4o).",
        fields=(
            _field("OPENROUTER_API_KEY", "API Key", "OpenRouter API key from openrouter.ai/keys.", secret=True, required=True),
            _field("OPENROUTER_MODEL", "Default Model", "Model path (e.g. openai/gpt-4o, anthropic/claude-3-5-sonnet, meta-llama/llama-3.1-8b-instruct)."),
        ),
        env_all=("OPENROUTER_API_KEY",),
        health_description="OpenRouter API key available for multi-provider routing.",
    ),
    IntegrationDefinition(
        id="custom_llm",
        title="Custom / Self-Hosted LLM",
        category="LLM Providers",
        description="Any OpenAI-compatible endpoint — vLLM, LM Studio, LocalAI, Together.ai, etc.",
        provider_name="custom",
        auth_mode="custom",
        docs_path="docs/integrations.md#custom-llm",
        setup_hint="Set CUSTOM_LLM_BASE_URL to your server's base URL and CUSTOM_LLM_MODEL to the model name. CUSTOM_LLM_API_KEY is optional.",
        fields=(
            _field("CUSTOM_LLM_BASE_URL", "Base URL", "OpenAI-compatible base URL (e.g. http://localhost:1234/v1).", required=True),
            _field("CUSTOM_LLM_MODEL", "Model Name", "Model name as the server expects it."),
            _field("CUSTOM_LLM_API_KEY", "API Key (optional)", "Bearer token if required by the server.", secret=True),
        ),
        env_all=("CUSTOM_LLM_BASE_URL",),
        health_description="Custom LLM base URL configured.",
    ),
    IntegrationDefinition(
        id="serpapi",
        title="SerpAPI",
        category="Providers",
        description="Search provider for web, travel, scholarly, and patent workflows.",
        provider_name="serpapi",
        auth_mode="api_key",
        docs_path="docs/integrations.md#serpapi",
        setup_hint="Set SERP_API_KEY to enable structured search-backed agents.",
        fields=(
            _field("SERP_API_KEY", "API Key", "SerpAPI key.", secret=True),
        ),
        env_all=("SERP_API_KEY",),
        health_description="SerpAPI key available for search workflows.",
    ),
    IntegrationDefinition(
        id="elevenlabs",
        title="ElevenLabs",
        category="Providers",
        description="Speech generation and transcription provider.",
        provider_name="elevenlabs",
        auth_mode="api_key",
        docs_path="docs/integrations.md#elevenlabs",
        setup_hint="Set ELEVENLABS_API_KEY to enable voice and audio agents.",
        fields=(
            _field("ELEVENLABS_API_KEY", "API Key", "ElevenLabs API key.", secret=True),
        ),
        env_all=("ELEVENLABS_API_KEY",),
        health_description="ElevenLabs API key available for voice workflows.",
    ),
    IntegrationDefinition(
        id="google_workspace",
        title="Google Workspace",
        category="Providers",
        description="Gmail and Google Drive integration via OAuth or direct access token.",
        provider_name="google_workspace",
        auth_mode="oauth",
        docs_path="docs/integrations.md#google-workspace",
        setup_hint="Configure GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET and complete the Google OAuth flow, or provide GOOGLE_ACCESS_TOKEN.",
        setup_url="/oauth/google/start",
        oauth_provider="google",
        oauth_start_path="/oauth/google/start",
        fields=(
            _field("GOOGLE_ACCESS_TOKEN", "Access Token", "Backward-compatible direct Google access token.", secret=True),
            _field("GOOGLE_CLIENT_ID", "Client ID", "Google OAuth client ID."),
            _field("GOOGLE_CLIENT_SECRET", "Client Secret", "Google OAuth client secret.", secret=True),
            _field("GOOGLE_REDIRECT_URI", "Redirect URI", "OAuth callback URI."),
            _field("GOOGLE_OAUTH_SCOPES", "OAuth Scopes", "Space-separated OAuth scopes."),
        ),
        env_any=("GOOGLE_ACCESS_TOKEN",),
        env_all=("GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET"),
        provider_token="google",
        health_description="Google Workspace token or OAuth configuration available.",
    ),
    IntegrationDefinition(
        id="slack",
        title="Slack",
        category="Providers",
        description="Slack workspace bot integration via bot token or OAuth.",
        provider_name="slack",
        channel_name="slack",
        auth_mode="oauth",
        docs_path="docs/integrations.md#slack",
        setup_hint="Configure SLACK_CLIENT_ID/SLACK_CLIENT_SECRET and install the Slack app, or set SLACK_BOT_TOKEN.",
        setup_url="/oauth/slack/start",
        oauth_provider="slack",
        oauth_start_path="/oauth/slack/start",
        fields=(
            _field("SLACK_BOT_TOKEN", "Bot Token", "Slack bot token if set manually.", secret=True),
            _field("SLACK_CLIENT_ID", "Client ID", "Slack OAuth client ID."),
            _field("SLACK_CLIENT_SECRET", "Client Secret", "Slack OAuth client secret.", secret=True),
            _field("SLACK_REDIRECT_URI", "Redirect URI", "OAuth callback URI."),
            _field("SLACK_OAUTH_SCOPES", "OAuth Scopes", "Comma-separated OAuth scopes."),
        ),
        env_any=("SLACK_BOT_TOKEN",),
        env_all=("SLACK_CLIENT_ID", "SLACK_CLIENT_SECRET"),
        provider_token="slack",
        health_description="Slack bot token or OAuth configuration available.",
    ),
    IntegrationDefinition(
        id="microsoft_graph",
        title="Microsoft Graph",
        category="Providers",
        description="Outlook, Teams, and OneDrive integration via OAuth or direct access token.",
        provider_name="microsoft_graph",
        channel_name="teams",
        auth_mode="oauth",
        docs_path="docs/integrations.md#microsoft-graph",
        setup_hint="Configure MICROSOFT_CLIENT_ID/MICROSOFT_CLIENT_SECRET and complete the Microsoft OAuth flow, or provide MICROSOFT_GRAPH_ACCESS_TOKEN.",
        setup_url="/oauth/microsoft/start",
        oauth_provider="microsoft",
        oauth_start_path="/oauth/microsoft/start",
        fields=(
            _field("MICROSOFT_GRAPH_ACCESS_TOKEN", "Access Token", "Backward-compatible direct Microsoft Graph token.", secret=True),
            _field("MICROSOFT_TENANT_ID", "Tenant ID", "Tenant ID or common."),
            _field("MICROSOFT_CLIENT_ID", "Client ID", "Microsoft OAuth client ID."),
            _field("MICROSOFT_CLIENT_SECRET", "Client Secret", "Microsoft OAuth client secret.", secret=True),
            _field("MICROSOFT_REDIRECT_URI", "Redirect URI", "OAuth callback URI."),
            _field("MICROSOFT_OAUTH_SCOPES", "OAuth Scopes", "Space-separated OAuth scopes."),
        ),
        env_any=("MICROSOFT_GRAPH_ACCESS_TOKEN",),
        env_all=("MICROSOFT_CLIENT_ID", "MICROSOFT_CLIENT_SECRET"),
        provider_token="microsoft",
        health_description="Microsoft Graph token or OAuth configuration available.",
    ),
    IntegrationDefinition(
        id="telegram",
        title="Telegram",
        category="Channels",
        description="Telegram bot or user-session integration.",
        provider_name="telegram",
        channel_name="telegram",
        auth_mode="token_or_session",
        docs_path="docs/integrations.md#telegram",
        setup_hint="Set TELEGRAM_BOT_TOKEN for bot mode, or TELEGRAM_SESSION_STRING with TELEGRAM_API_ID and TELEGRAM_API_HASH for user-session mode.",
        fields=(
            _field("TELEGRAM_BOT_TOKEN", "Bot Token", "Telegram bot token.", secret=True),
            _field("TELEGRAM_SESSION_STRING", "Session String", "Telethon user session string.", secret=True),
            _field("TELEGRAM_API_ID", "API ID", "Telegram API ID."),
            _field("TELEGRAM_API_HASH", "API Hash", "Telegram API hash.", secret=True),
        ),
        env_any=("TELEGRAM_BOT_TOKEN",),
        health_description="Telegram bot token or user session configured.",
    ),
    IntegrationDefinition(
        id="whatsapp",
        title="WhatsApp",
        category="Channels",
        description="WhatsApp Cloud API integration.",
        provider_name="whatsapp",
        channel_name="whatsapp",
        auth_mode="api_key",
        docs_path="docs/integrations.md#whatsapp",
        setup_hint="Set WHATSAPP_ACCESS_TOKEN and WHATSAPP_PHONE_NUMBER_ID before enabling WhatsApp notifications.",
        fields=(
            _field("WHATSAPP_ACCESS_TOKEN", "Access Token", "WhatsApp Cloud API token.", secret=True),
            _field("WHATSAPP_PHONE_NUMBER_ID", "Phone Number ID", "WhatsApp phone number ID."),
        ),
        env_all=("WHATSAPP_ACCESS_TOKEN", "WHATSAPP_PHONE_NUMBER_ID"),
        health_description="WhatsApp Cloud API credentials available.",
    ),
    IntegrationDefinition(
        id="aws",
        title="AWS",
        category="Cloud",
        description="AWS credentials and default region.",
        provider_name="aws",
        auth_mode="credential_chain",
        docs_path="docs/integrations.md#aws",
        setup_hint="Provide AWS credentials via env vars, profile, or instance role and set AWS_DEFAULT_REGION when needed.",
        fields=(
            _field("AWS_ACCESS_KEY_ID", "Access Key ID", "Optional static access key.", secret=True),
            _field("AWS_SECRET_ACCESS_KEY", "Secret Access Key", "Optional static secret key.", secret=True),
            _field("AWS_SESSION_TOKEN", "Session Token", "Optional session token.", secret=True),
            _field("AWS_DEFAULT_REGION", "Default Region", "AWS region override."),
            _field("AWS_PROFILE", "Profile", "Named AWS profile if used."),
        ),
        health_description="AWS credentials available through the active boto3 credential chain.",
    ),
    IntegrationDefinition(
        id="qdrant",
        title="Qdrant",
        category="Infrastructure",
        description="Vector store endpoint used by memory and superRAG workflows.",
        provider_name="qdrant",
        auth_mode="service",
        docs_path="docs/integrations.md#qdrant",
        setup_hint="Run a reachable Qdrant instance and set QDRANT_URL. Add QDRANT_API_KEY if your deployment requires it.",
        fields=(
            _field("QDRANT_URL", "Qdrant URL", "Qdrant service URL."),
            _field("QDRANT_API_KEY", "API Key", "Optional Qdrant API key.", secret=True),
            _field("QDRANT_COLLECTION", "Collection", "Default Qdrant collection for memory workflows."),
        ),
        env_all=("QDRANT_URL",),
        healthcheck_url_env="QDRANT_URL",
        healthcheck_url_default="http://localhost:6333",
        health_description="Reachable Qdrant endpoint.",
    ),
    IntegrationDefinition(
        id="playwright",
        title="Playwright",
        category="Local Tools",
        description="Playwright package or CLI for browser automation.",
        provider_name="playwright",
        auth_mode="local_dependency",
        docs_path="docs/integrations.md#playwright",
        setup_hint="Install the Playwright Python package and browser binaries.",
        python_modules_any=("playwright",),
        commands_any=("playwright",),
        health_description="Playwright package or CLI available.",
    ),
    IntegrationDefinition(
        id="nmap",
        title="Nmap",
        category="Local Tools",
        description="Local Nmap binary for authorized defensive scanning.",
        provider_name="nmap",
        auth_mode="local_dependency",
        docs_path="docs/integrations.md#security-tools",
        setup_hint="Install the nmap binary and keep it on PATH for authorized defensive scans.",
        commands_any=("nmap",),
        health_description="Nmap binary available on PATH.",
    ),
    IntegrationDefinition(
        id="zap",
        title="OWASP ZAP",
        category="Local Tools",
        description="OWASP ZAP baseline tooling for authorized defensive scans.",
        provider_name="zap",
        auth_mode="local_dependency",
        docs_path="docs/integrations.md#security-tools",
        setup_hint="Install OWASP ZAP and keep zap-baseline.py or owasp-zap on PATH.",
        commands_any=("zap-baseline.py", "owasp-zap"),
        health_description="OWASP ZAP baseline tooling available on PATH.",
    ),
    IntegrationDefinition(
        id="cve_database",
        title="CVE Database",
        category="Security",
        description="CVE/NVD lookup endpoint and optional API key.",
        provider_name="cve_database",
        auth_mode="service",
        docs_path="docs/integrations.md#cve-database",
        setup_hint="CVE_API_BASE_URL defaults to the public NVD endpoint. Add NVD_API_KEY for higher rate limits.",
        fields=(
            _field("CVE_API_BASE_URL", "CVE API Base URL", "CVE/NVD API base URL."),
            _field("NVD_API_KEY", "NVD API Key", "Optional key for NVD rate limits.", secret=True),
        ),
        env_any=("CVE_API_BASE_URL",),
        health_description="CVE/NVD lookup endpoint configured.",
    ),
    IntegrationDefinition(
        id="codex_cli",
        title="Codex CLI",
        category="Local Tools",
        description="Local codex CLI used as a fallback integration for coding workflows.",
        auth_mode="local_dependency",
        docs_path="docs/integrations.md#coding-integrations",
        setup_hint="Install the codex CLI and make sure the `codex` command is on PATH if you want coding-agent fallback without OpenAI.",
        commands_any=("codex",),
        health_description="Codex CLI available on PATH.",
    ),
    IntegrationDefinition(
        id="owasp_dependency_check",
        title="OWASP Dependency-Check",
        category="Local Tools",
        description="Dependency-Check CLI for software composition scanning.",
        auth_mode="local_dependency",
        docs_path="docs/integrations.md#security-tools",
        setup_hint="Install dependency-check and keep it on PATH for dependency audit workflows.",
        commands_any=("dependency-check",),
        health_description="OWASP Dependency-Check available on PATH.",
    ),
    IntegrationDefinition(
        id="github",
        title="GitHub",
        category="Code & SCM",
        description=(
            "GitHub repository operations: clone, pull, push, branch management, commit, "
            "pull request create/merge, issue tracking, and code review automation."
        ),
        provider_name="github",
        auth_mode="api_key",
        docs_path="docs/integrations.md#github",
        setup_hint=(
            "Create a GitHub personal access token (classic) with 'repo' scope "
            "at https://github.com/settings/tokens and set GITHUB_TOKEN."
        ),
        setup_url="https://github.com/settings/tokens/new",
        fields=(
            _field(
                "GITHUB_TOKEN",
                "Personal Access Token",
                "GitHub token with repo scope for reading and writing repositories.",
                secret=True,
                required=True,
            ),
        ),
        env_all=("GITHUB_TOKEN",),
        health_description="GitHub token available for repository and issue management.",
    ),
    IntegrationDefinition(
        id="privileged_control",
        title="Privileged Control",
        category="Security",
        description="Privileged execution policy gates and kill-switch controls.",
        auth_mode="policy",
        docs_path="docs/integrations.md#privileged-control",
        setup_hint="Review privileged mode, approvals, allowed paths/domains, and kill-switch settings before enabling high-privilege automation.",
        fields=(
            _field("KENDR_PRIVILEGED_MODE", "Privileged Mode", "If true, privileged policy controls are enabled for runs."),
            _field("KENDR_REQUIRE_APPROVALS", "Require Approvals", "If true, privileged actions require explicit approval."),
            _field("KENDR_READ_ONLY_MODE", "Read-Only Mode", "If true, mutating command and file actions are blocked."),
            _field("KENDR_ALLOW_ROOT", "Allow Root Escalation", "If true, sudo/root escalation is allowed for privileged runs."),
            _field("KENDR_ALLOW_DESTRUCTIVE", "Allow Destructive Commands", "If true, destructive operations may run."),
            _field("KENDR_ENABLE_BACKUPS", "Enable Snapshots", "If true, snapshots are created before mutating OS commands."),
            _field("KENDR_ALLOWED_PATHS", "Allowed Paths", "Comma or pathsep-separated allowlist roots for privileged scope."),
            _field("KENDR_ALLOWED_DOMAINS", "Allowed Domains", "Comma-separated allowed network domains for privileged tasks."),
            _field("KENDR_KILL_SWITCH_FILE", "Kill Switch File", "If this file exists, runtime halts before more agent execution."),
        ),
        health_description="Privileged control policy is available for guarded high-privilege execution.",
    ),
)


BUILTIN_CHANNEL_DEFINITIONS: tuple[dict[str, str], ...] = (
    {"name": "webchat", "description": "Browser-based chat surface."},
    {"name": "telegram", "description": "Telegram chat channel."},
    {"name": "slack", "description": "Slack channel surface."},
    {"name": "whatsapp", "description": "WhatsApp chat surface."},
    {"name": "teams", "description": "Microsoft Teams channel."},
    {"name": "discord", "description": "Discord channel."},
    {"name": "matrix", "description": "Matrix channel."},
    {"name": "signal", "description": "Signal channel."},
)


REQUIREMENT_RULES: dict[str, RequirementRule] = {
    "configured_llm": RequirementRule(
        name="configured_llm",
        mode="any",
        integrations=("openai", "anthropic", "google_gemini", "xai", "ollama", "openrouter", "custom_llm", "minimax", "qwen", "glm"),
        description="Requires at least one configured LLM provider.",
    ),
    "openai_or_codex_cli": RequirementRule(
        name="openai_or_codex_cli",
        mode="any",
        integrations=("openai", "codex_cli"),
        description="Requires either OpenAI or the local codex CLI.",
    ),
    "nmap_or_zap": RequirementRule(
        name="nmap_or_zap",
        mode="any",
        integrations=("nmap", "zap"),
        description="Requires at least one authorized scan tool: Nmap or ZAP.",
    ),
    "outbound_channel": RequirementRule(
        name="outbound_channel",
        mode="any",
        integrations=("telegram", "slack", "whatsapp"),
        description="Requires at least one outbound channel integration.",
    ),
    "communication_suite": RequirementRule(
        name="communication_suite",
        mode="any",
        integrations=("google_workspace", "telegram", "slack", "microsoft_graph"),
        description="Requires at least one communication suite integration.",
    ),
}


def _legacy_requirements() -> dict[str, list[str]]:
    """Build the legacy agent-to-integrations requirement map.

    SOURCE-OF-TRUTH NOTE:
    ``AGENT_METADATA["<agent>"]["requirements"]`` (defined in each agent's task
    module) is the authoritative requirement list used at routing time.  It only
    lists *integration-specific* dependencies (e.g. ``["github"]``) because
    ``openai`` is a universal runtime dependency present for every agent.

    This legacy mapping is used as a *fallback* by ``setup_registry.py`` when an
    older agent card does not carry embedded requirements.  It intentionally lists
    ``openai`` explicitly alongside integration-specific dependencies so that the
    fallback path remains complete.  Do not derive routing logic from this mapping
    directly — always prefer ``AGENT_METADATA`` requirements.

    Dual-declaration example — github_agent:
        AGENT_METADATA: requirements = ["github"]          (authoritative)
        LEGACY:         requirements = ["openai", "github"] (fallback, exhaustive)
    """
    mapping: dict[str, list[str]] = {}

    def assign(requirements: list[str], *agent_names: str) -> None:
        for agent_name in agent_names:
            mapping[agent_name] = list(requirements)

    assign(
        ["openai"],
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
        "document_formatter_agent",
        "superrag_agent",
        "local_drive_agent",
        "memory_index_agent",
        "os_agent",
    )
    assign(["openai", "serpapi"], "google_search_agent", "literature_search_agent", "patent_search_agent")
    assign(["openai", "elevenlabs"], "voice_catalog_agent", "speech_generation_agent", "speech_transcription_agent")
    assign(["openai", "whatsapp"], "whatsapp_agent")
    assign(["openai", "outbound_channel"], "notification_dispatch_agent")
    assign(["openai", "playwright"], "interactive_browser_agent")
    assign(["openai"], "memory_index_agent", "superrag_agent")
    assign(["openai", "google_workspace"], "gmail_agent", "drive_agent")
    assign(["openai", "telegram"], "telegram_agent")
    assign(["openai", "slack"], "slack_agent")
    assign(["openai", "microsoft_graph"], "microsoft_graph_agent")
    assign(["openai", "communication_suite"], "communication_scope_guard_agent", "communication_hub_agent")
    assign(["openai_or_codex_cli"], "coding_agent", "master_coding_agent")
    assign(["openai", "aws"], "aws_scope_guard_agent", "aws_inventory_agent", "aws_cost_agent", "aws_automation_agent")
    assign(["openai", "nmap_or_zap"], "scanner_agent")
    assign(["openai", "github"], "github_agent")
    return mapping


LEGACY_AGENT_REQUIREMENTS = _legacy_requirements()


def integration_index() -> dict[str, IntegrationDefinition]:
    return {item.id: item for item in INTEGRATION_DEFINITIONS}


def integration_components() -> list[dict]:
    return [item.component() for item in INTEGRATION_DEFINITIONS]


def provider_catalog() -> list[dict]:
    providers = []
    for item in INTEGRATION_DEFINITIONS:
        if not item.provider_name:
            continue
        providers.append(
            {
                "name": item.provider_name,
                "description": item.description,
                "auth_mode": item.auth_mode,
                "metadata": {
                    "component_id": item.id,
                    "docs_path": item.docs_path,
                    "setup_url": item.setup_url or item.oauth_start_path,
                },
            }
        )
    return providers


def channel_catalog() -> list[dict]:
    channels = list(BUILTIN_CHANNEL_DEFINITIONS)
    for item in INTEGRATION_DEFINITIONS:
        if item.channel_name and all(channel["name"] != item.channel_name for channel in channels):
            channels.append({"name": item.channel_name, "description": item.description})
    return channels


def setup_component_catalog() -> list[dict]:
    runtime_components = [
        {
            "id": "core_runtime",
            "title": "Core Runtime",
            "category": "Core",
            "description": "Base runtime behavior, working directory, output paths, and plugin discovery.",
            "fields": [
                asdict(_field("KENDR_HOME", "Kendr Home", "Home directory for plugin and config files.", default="~/.kendr")),
                asdict(_field("KENDR_PLUGIN_PATHS", "Plugin Paths", "OS path-separated plugin paths.")),
                asdict(_field("OUTPUT_DIR", "Output Directory", "Output folder for runs and setup artifacts.", default="./output")),
                asdict(_field("KENDR_WORKING_DIR", "Working Folder", "Base folder for task runs, artifacts, and outputs.", required=True)),
                asdict(_field("KENDR_LLM_PROVIDER", "LLM Provider", "Active LLM provider: openai, anthropic, google, xai, minimax, qwen, glm, ollama, openrouter, custom.", default="openai")),
                asdict(_field("KENDR_MODEL", "Legacy Model Override", "Legacy global model override. Prefer the Models page or `kendr model set` so defaults stay provider-specific.")),
                asdict(_field("KENDR_COMMUNICATION_AUTHORIZED", "Communication Access Default", "Default communication authorization for inbox/messaging workflows. Set to false to disable by default.", default="true")),
                asdict(_field("RESEARCH_USER_AGENT", "Research User Agent", "User-Agent string for research HTTP fetches.", default="kendr-research/1.0")),
            ],
            "docs_path": "docs/install.md",
        },
        {
            "id": "gateway_server",
            "title": "Gateway Server",
            "category": "Runtime",
            "description": "HTTP ingest and dashboard server settings.",
            "fields": [
                asdict(_field("GATEWAY_HOST", "Host", "Gateway bind host.", default="127.0.0.1")),
                asdict(_field("GATEWAY_PORT", "Port", "Gateway bind port.", default="8790")),
            ],
            "docs_path": "docs/install.md",
        },
        {
            "id": "kendr_ui",
            "title": "Kendr Web UI",
            "category": "Runtime",
            "description": "Web UI bind settings (chat, setup, run history, MCP servers, projects).",
            "fields": [
                asdict(_field("KENDR_UI_HOST", "Host", "Web UI bind host.", default="0.0.0.0")),
                asdict(_field("KENDR_UI_PORT", "Port", "Web UI bind port.", default="5000")),
            ],
            "docs_path": "docs/install.md",
        },
        {
            "id": "daemon",
            "title": "Daemon",
            "category": "Runtime",
            "description": "Always-on monitor daemon intervals.",
            "fields": [
                asdict(_field("DAEMON_POLL_INTERVAL", "Poll Interval", "Main daemon poll interval in seconds.", default="30")),
                asdict(_field("DAEMON_HEARTBEAT_INTERVAL", "Heartbeat Interval", "Heartbeat interval in seconds.", default="300")),
            ],
            "docs_path": "docs/install.md",
        },
        {
            "id": "security_tools",
            "title": "Security Tools",
            "category": "Security",
            "description": "Scan profile and optional local security tooling settings.",
            "fields": [
                asdict(_field("SECURITY_SCAN_PROFILE", "Default Scan Profile", "Security scan depth: baseline, standard, deep, or extensive.", default="standard")),
                asdict(_field("SECURITY_AUTO_INSTALL_TOOLS", "Auto Install Security Tools", "If true, CLI attempts to install missing security tools.", default="true")),
            ],
            "docs_path": "docs/integrations.md#security-tools",
        },
        {
            "id": "mcp_research",
            "title": "MCP Research Server",
            "category": "MCP",
            "description": "Research MCP server bind settings.",
            "fields": [
                asdict(_field("MCP_RESEARCH_HOST", "Host", "Host for research MCP.", default="127.0.0.1")),
                asdict(_field("MCP_RESEARCH_PORT", "Port", "Port for research MCP.", default="9100")),
            ],
            "docs_path": "docs/integrations.md#mcp-servers",
        },
        {
            "id": "mcp_vector",
            "title": "MCP Vector Server",
            "category": "MCP",
            "description": "Vector MCP server bind settings.",
            "fields": [
                asdict(_field("MCP_VECTOR_HOST", "Host", "Host for vector MCP.", default="127.0.0.1")),
                asdict(_field("MCP_VECTOR_PORT", "Port", "Port for vector MCP.", default="9101")),
            ],
            "docs_path": "docs/integrations.md#mcp-servers",
        },
        {
            "id": "mcp_security",
            "title": "MCP Security Servers",
            "category": "MCP",
            "description": "Shared settings for security MCP servers.",
            "fields": [
                asdict(_field("MCP_SECURITY_HOST", "Host", "Host for security MCP services.", default="127.0.0.1")),
                asdict(_field("MCP_NMAP_PORT", "Nmap Port", "Nmap MCP port.", default="9110")),
                asdict(_field("MCP_ZAP_PORT", "ZAP Port", "ZAP MCP port.", default="9111")),
                asdict(_field("MCP_SCREENSHOT_PORT", "Screenshot Port", "Screenshot MCP port.", default="9112")),
                asdict(_field("MCP_HTTP_FUZZING_PORT", "HTTP Fuzzing Port", "HTTP fuzzing MCP port.", default="9113")),
                asdict(_field("MCP_CVE_PORT", "CVE Port", "CVE MCP port.", default="9114")),
            ],
            "docs_path": "docs/integrations.md#mcp-servers",
        },
    ]
    return [*runtime_components, *integration_components()]
