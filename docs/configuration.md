# Configuration Reference

Complete reference for every environment variable supported by Kendr, grouped by component. Copy `.env.example` as your starting point and fill in the values you need.

---

## Core Runtime

The minimum required set for any Kendr run.

| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `KENDR_WORKING_DIR` | **yes** | _(none)_ | Absolute path where run artifacts, session files, and outputs are written. | `/home/user/kendr-work` |
| `KENDR_HOME` | no | `~/.kendr` | Root of Kendr's local state directory (PID files, DB, plugin cache). | `~/.kendr` |
| `KENDR_PLUGIN_PATHS` | no | _(empty)_ | Colon- or comma-separated extra directories to scan for plugins. | `/opt/kendr-plugins` |
| `OUTPUT_DIR` | no | `output` | Default top-level output directory relative to working directory. | `output` |
| `RESEARCH_USER_AGENT` | no | `multi-agent-research-bot/1.0 (+https://localhost)` | HTTP User-Agent sent by the web crawl / research infrastructure. | `mybot/2.0 (+https://mysite.com)` |
| `KENDR_MODEL` | no | _(falls back to `OPENAI_MODEL`)_ | Short-form model override applied to all agents that don't have an explicit model set. | `gpt-4o` |

---

## OpenAI

Kendr requires OpenAI for orchestration, reasoning, embeddings, OCR, and deep research. `OPENAI_API_KEY` is the only strictly required variable.

| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `OPENAI_API_KEY` | **yes** | _(none)_ | Your OpenAI API key. | `sk-...` |
| `OPENAI_MODEL_GENERAL` | no | `gpt-4o-mini` | Model for planning, orchestration, research, and general agents. | `gpt-4o` |
| `OPENAI_MODEL_CODING` | no | `gpt-4o-mini` | Model used by coding-focused agents. | `gpt-4o` |
| `OPENAI_MODEL` | no | `gpt-4o-mini` | Backward-compatible fallback general model. Used when `OPENAI_MODEL_GENERAL` is not set. | `gpt-4o-mini` |
| `OPENAI_CODEX_MODEL` | no | _(falls back to `OPENAI_MODEL_CODING`)_ | Legacy backward-compatible fallback for coding-model selection. Checked after `OPENAI_MODEL_CODING`. Still active in coding agent paths. | `gpt-4o` |
| `OPENAI_VISION_MODEL` | no | `gpt-4o-mini` | Model used by image analysis and OCR workflows. | `gpt-4o` |
| `OPENAI_EMBEDDING_MODEL` | no | `text-embedding-3-small` | Model used for text embeddings and vector indexing. | `text-embedding-3-large` |

---

## Vector Backend

Kendr ships with **ChromaDB as the zero-config default** vector backend. No setup or env vars are required. For production workloads or shared persistence, you can opt in to Qdrant.

### ChromaDB (default)

ChromaDB runs in-process with no external dependencies. It is selected automatically when `QDRANT_URL` is not set or Qdrant is unreachable.

No environment variables are required. ChromaDB stores its data under `KENDR_WORKING_DIR/chroma_db/` by default.

### Qdrant (opt-in)

To use Qdrant instead of ChromaDB, set `QDRANT_URL` to a reachable Qdrant endpoint. Kendr checks health before switching; if Qdrant is unreachable it falls back to ChromaDB.

| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `QDRANT_URL` | no | _(none — ChromaDB used)_ | Qdrant service URL. When set and reachable, Qdrant replaces ChromaDB. | `http://127.0.0.1:6333` |
| `QDRANT_API_KEY` | no | _(none)_ | Optional Qdrant API key for authenticated deployments. | `qdrant-secret` |
| `QDRANT_COLLECTION` | no | `research_memory` | Default collection name for memory and superRAG workflows. | `my_knowledge_base` |

---

## Search (SerpAPI)

Required for web search, travel, scholarly, and patent workflows.

| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `SERP_API_KEY` | no | _(none)_ | SerpAPI key. Without this, search-backed agents are disabled. | `abc123...` |

Get your key at [serpapi.com](https://serpapi.com).

---

## Communication Providers

### Google Workspace (Gmail + Google Drive)

Choose **either** a direct access token (simpler for personal use) **or** OAuth client credentials (required for multi-user or long-lived tokens).

| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `GOOGLE_ACCESS_TOKEN` | no | _(none)_ | Direct Google access token. Takes precedence when set. | `ya29.a0...` |
| `GOOGLE_CLIENT_ID` | no | _(none)_ | Google OAuth client ID. Required for the OAuth flow. | `123456-abc.apps.googleusercontent.com` |
| `GOOGLE_CLIENT_SECRET` | no | _(none)_ | Google OAuth client secret. | `GOCSPX-...` |
| `GOOGLE_REDIRECT_URI` | no | `http://127.0.0.1:8787/oauth/google/callback` | OAuth redirect URI registered in Google Cloud Console. | `http://127.0.0.1:8787/oauth/google/callback` |
| `GOOGLE_OAUTH_SCOPES` | no | Gmail + Drive read scopes | Space-separated OAuth scope list. | `https://www.googleapis.com/auth/gmail.readonly` |

### Microsoft Graph (Outlook + Teams + OneDrive)

| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `MICROSOFT_GRAPH_ACCESS_TOKEN` | no | _(none)_ | Direct Microsoft Graph access token. Takes precedence when set. | `eyJ0eXAi...` |
| `MICROSOFT_TENANT_ID` | no | `common` | Azure tenant ID, or `common` for multi-tenant. | `aaaabbbb-cccc-dddd-eeee-ffffgggghhhh` |
| `MICROSOFT_CLIENT_ID` | no | _(none)_ | Microsoft OAuth client ID. | `11112222-3333-4444-5555-666677778888` |
| `MICROSOFT_CLIENT_SECRET` | no | _(none)_ | Microsoft OAuth client secret. | `aBcDeFgHiJkL...` |
| `MICROSOFT_REDIRECT_URI` | no | `http://127.0.0.1:8787/oauth/microsoft/callback` | OAuth redirect URI registered in Azure. | `http://127.0.0.1:8787/oauth/microsoft/callback` |
| `MICROSOFT_OAUTH_SCOPES` | no | offline_access User.Read Mail.Read Files.Read | Space-separated OAuth scopes. | `offline_access User.Read Mail.Read` |

### Slack

| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `SLACK_BOT_TOKEN` | no | _(none)_ | Slack bot token for simple single-workspace setup. | `xoxb-...` |
| `SLACK_CLIENT_ID` | no | _(none)_ | Slack OAuth app client ID. | `123456789012.1234567890` |
| `SLACK_CLIENT_SECRET` | no | _(none)_ | Slack OAuth app client secret. | `abc123def456...` |
| `SLACK_REDIRECT_URI` | no | `http://127.0.0.1:8787/oauth/slack/callback` | OAuth redirect URI registered in your Slack app. | `http://127.0.0.1:8787/oauth/slack/callback` |
| `SLACK_OAUTH_SCOPES` | no | channels:read channels:history groups:read groups:history | Comma-separated OAuth permission scopes. | `channels:read,channels:history` |

### Telegram

Telegram supports two modes:

- **Bot mode**: easier setup; can only read messages from channels/groups the bot is a member of
- **User-session mode**: uses your personal account via Telethon; can read any channel you have access to

| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `TELEGRAM_BOT_TOKEN` | no | _(none)_ | Telegram bot token from [@BotFather](https://t.me/BotFather). Used in bot mode. | `1234567890:ABCDEFghijklmnop...` |
| `TELEGRAM_API_ID` | no | _(none)_ | Telegram application API ID from [my.telegram.org](https://my.telegram.org/apps). Required for user-session mode. | `12345678` |
| `TELEGRAM_API_HASH` | no | _(none)_ | Telegram application API hash from [my.telegram.org](https://my.telegram.org/apps). Required for user-session mode. | `abcdef1234567890abcdef1234567890` |
| `TELEGRAM_SESSION_STRING` | no | _(none)_ | Telethon session string for user-session mode. Generate once with `python -c "from telethon.sync import TelegramClient; c = TelegramClient('s', API_ID, API_HASH); c.start(); print(c.session.save())"`. | _(long base64 string)_ |

**Bot mode** only requires `TELEGRAM_BOT_TOKEN`.
**User-session mode** requires `TELEGRAM_API_ID`, `TELEGRAM_API_HASH`, and `TELEGRAM_SESSION_STRING`.

### WhatsApp

Kendr integrates with the **Meta WhatsApp Cloud API** (not the WhatsApp Business App). You need a verified Meta Business account and a registered WhatsApp Business phone number.

| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `WHATSAPP_ACCESS_TOKEN` | **yes** (for WhatsApp) | _(none)_ | Meta Graph API access token with `whatsapp_business_messaging` permission. | `EAAGm0PX4ZC...` |
| `WHATSAPP_PHONE_NUMBER_ID` | **yes** (for WhatsApp) | _(none)_ | Phone number ID from Meta Business Manager. NOT the phone number itself. | `109876543210` |

Get credentials at [developers.facebook.com](https://developers.facebook.com/docs/whatsapp/cloud-api/get-started).

---

## Gateway

The HTTP gateway server (`kendr gateway start`) exposes a REST API and is used for session routing and the optional setup UI. It must be started explicitly — it is never auto-started by `kendr run`, `kendr research`, or `kendr generate`.

| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `SETUP_UI_HOST` | no | `127.0.0.1` | Host the setup UI listens on. Use `0.0.0.0` to expose externally. | `127.0.0.1` |
| `SETUP_UI_PORT` | no | `8787` | Port the setup UI listens on. | `8787` |
| `GATEWAY_HOST` | no | `127.0.0.1` | Host the gateway server listens on. | `127.0.0.1` |
| `GATEWAY_PORT` | no | `8790` | Port the gateway server listens on. | `8790` |
| `DAEMON_POLL_INTERVAL` | no | `30` | Seconds between monitor passes when the daemon is running. | `60` |
| `DAEMON_HEARTBEAT_INTERVAL` | no | `300` | Seconds between daemon heartbeat log entries. | `600` |

---

## Security and Privileged Mode

These variables control the safety boundaries for privileged automation (local command execution, OS agent, security scans). All are disabled by default.

| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `KENDR_PRIVILEGED_MODE` | no | `false` | Enable privileged policy controls for runs that use `os_agent` or security agents. | `true` |
| `KENDR_REQUIRE_APPROVALS` | no | `true` | Require explicit `--privileged-approved` flag and note before privileged actions run. | `true` |
| `KENDR_READ_ONLY_MODE` | no | `false` | Block all mutating commands and file writes for privileged runs. | `true` |
| `KENDR_ALLOW_ROOT` | no | `false` | Allow sudo/root escalation in privileged runs. | `false` |
| `KENDR_ALLOW_DESTRUCTIVE` | no | `false` | Allow destructive operations (rm, drop table, etc.) in privileged runs. | `false` |
| `KENDR_ENABLE_BACKUPS` | no | `true` | Create filesystem snapshots before mutating OS commands. | `true` |
| `KENDR_ALLOWED_PATHS` | no | _(none)_ | Comma-separated path roots that privileged commands may touch. | `/home/user/project,/tmp/kendr` |
| `KENDR_ALLOWED_DOMAINS` | no | _(none)_ | Comma-separated allowed network domains for privileged tasks. | `example.com,api.internal` |
| `KENDR_KILL_SWITCH_FILE` | no | `output/KENDR_STOP` | If this file exists, the runtime halts before executing any further agent steps. | `output/KENDR_STOP` |
| `SECURITY_SCAN_PROFILE` | no | `standard` | Default security scan depth when not overridden with `--security-scan-profile`. | `deep` |
| `SECURITY_AUTO_INSTALL_TOOLS` | no | `true` | Automatically install missing security tools (nmap, zap, dependency-check) before security runs. | `false` |
| `CVE_API_BASE_URL` | no | `https://services.nvd.nist.gov/rest/json/cves/2.0` | CVE/NVD API base URL. | `https://services.nvd.nist.gov/rest/json/cves/2.0` |
| `NVD_API_KEY` | no | _(none)_ | Optional NVD API key for higher rate limits. | `nvd-abc123` |

---

## Cloud (AWS)

| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `AWS_ACCESS_KEY_ID` | no | _(none)_ | Static AWS access key (optional if using profile or instance role). | `AKIAIOSFODNN7EXAMPLE` |
| `AWS_SECRET_ACCESS_KEY` | no | _(none)_ | Static AWS secret key. | `wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY` |
| `AWS_SESSION_TOKEN` | no | _(none)_ | AWS session token for temporary credentials. | `AQoXnyc4...` |
| `AWS_DEFAULT_REGION` | no | `us-east-1` | Default AWS region. | `eu-west-1` |
| `AWS_PROFILE` | no | _(none)_ | Named AWS profile from `~/.aws/credentials` to use. | `myprofile` |

---

## Voice (ElevenLabs)

| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `ELEVENLABS_API_KEY` | no | _(none)_ | ElevenLabs API key for voice synthesis and transcription. | `el_sk_...` |

---

## MCP Servers

These variables configure the Model Context Protocol server endpoints used by optional advanced integrations.

| Variable | Required | Default | Description | Example |
|---|---|---|---|---|
| `MCP_RESEARCH_HOST` | no | `127.0.0.1` | Host for the Research MCP server. | `127.0.0.1` |
| `MCP_RESEARCH_PORT` | no | `8081` | Port for the Research MCP server. | `8081` |
| `MCP_VECTOR_HOST` | no | `127.0.0.1` | Host for the Vector MCP server. | `127.0.0.1` |
| `MCP_VECTOR_PORT` | no | `8082` | Port for the Vector MCP server. | `8082` |
| `MCP_SECURITY_HOST` | no | `127.0.0.1` | Host for the Security MCP cluster. | `127.0.0.1` |
| `MCP_NMAP_PORT` | no | `8083` | Port for the Nmap MCP server. | `8083` |
| `MCP_ZAP_PORT` | no | `8084` | Port for the ZAP MCP server. | `8084` |
| `MCP_SCREENSHOT_PORT` | no | `8085` | Port for the Screenshot MCP server. | `8085` |
| `MCP_HTTP_FUZZING_PORT` | no | `8086` | Port for the HTTP Fuzzing MCP server. | `8086` |
| `MCP_CVE_PORT` | no | `8087` | Port for the CVE MCP server. | `8087` |

---

## Checking Your Setup

Use the CLI to inspect the current configuration state:

```bash
kendr setup status
kendr setup components
kendr setup show openai --json
```

Export all configured values as a dotenv block:

```bash
kendr setup export-env
kendr setup export-env --include-secrets
```
