# Integrations

Kendr routes against configured integrations, not against the full theoretical ecosystem.

The integration lifecycle is standardized across:

- declaration in [`kendr/setup/catalog.py`](../kendr/setup/catalog.py)
- configuration via `kendr setup ...` and [`.env.example`](../.env.example)
- setup detection and health reporting in [`tasks/setup_registry.py`](../tasks/setup_registry.py)
- routing eligibility through agent `requirements`
- docs and tests

If an integration is missing or disabled, setup-aware routing removes dependent agents from `available_agents`.

Future integrations should follow [Integration Checklist](integration_checklist.md).

## Lifecycle

Each integration should provide one contract:

| Stage | Source Of Truth |
| --- | --- |
| declaration | `kendr/setup/catalog.py` |
| configuration fields | `tasks/setup_config_store.py` via the shared catalog |
| health/detection | `tasks/setup_registry.py` |
| routing eligibility | `AGENT_METADATA["requirements"]` |
| concrete setup examples | `.env.example`, `README.md`, `SampleTasks.md` |
| regression coverage | `tests/test_setup_registry.py` and related routing tests |

## Built-In Providers

These providers are registered from the shared integration catalog.

| Provider | Purpose | Typical Configuration |
| --- | --- | --- |
| `openai` | orchestration, reasoning, OCR, embeddings, deep research | `OPENAI_API_KEY`, `OPENAI_MODEL_GENERAL`, `OPENAI_MODEL_CODING` |
| `elevenlabs` | speech and voice workflows | `ELEVENLABS_API_KEY` |
| `serpapi` | web, travel, scholarly, and patent search | `SERP_API_KEY` |
| `google_workspace` | Gmail and Google Drive | `GOOGLE_ACCESS_TOKEN` or OAuth client fields |
| `telegram` | Telegram bot or session access | `TELEGRAM_BOT_TOKEN` or `TELEGRAM_SESSION_STRING` + API fields |
| `slack` | Slack workspace access | `SLACK_BOT_TOKEN` or OAuth client fields |
| `microsoft_graph` | Outlook, Teams, OneDrive | `MICROSOFT_GRAPH_ACCESS_TOKEN` or OAuth client fields |
| `aws` | AWS cloud workflows | `AWS_*` |
| `qdrant` | vector memory | `QDRANT_URL`, `QDRANT_COLLECTION` |
| `whatsapp` | WhatsApp Cloud API | `WHATSAPP_*` |
| `playwright` | browser automation and screenshots | Playwright package or CLI |
| `nmap` | local network scanning | local `nmap` binary |
| `zap` | OWASP ZAP baseline scanning | `zap-baseline.py` or `owasp-zap` on PATH |
| `cve_database` | CVE and NVD lookup | `CVE_API_BASE_URL`, optional `NVD_API_KEY` |

## Built-In Channels

The runtime currently registers these channels:

- `webchat`
- `telegram`
- `slack`
- `whatsapp`
- `teams`
- `discord`
- `matrix`
- `signal`

## Setup UI And OAuth

The CLI exposes a web-based setup UI:

```bash
kendr setup ui
```

OAuth-backed flows currently documented in the repo:

- Google Workspace
- Microsoft Graph
- Slack

Manual or direct-token integrations:

- Telegram bot token or Telethon session
- WhatsApp Cloud API
- AWS credentials

Useful setup commands:

```bash
kendr setup status
kendr setup components
kendr setup show core_runtime --json
kendr setup show openai --json
kendr setup export-env
kendr setup install --yes
```

Concrete first-run baseline:

```bash
kendr setup set core_runtime KENDR_WORKING_DIR /absolute/path/to/workdir
kendr setup set openai OPENAI_API_KEY sk-...
kendr setup status
```

## Health And Routing

`build_setup_snapshot()` reports each integration with:

- `configured`
- `enabled`
- `status`
- `health.detail`
- `setup_hint`
- `docs_path`

Routing uses those results to populate:

- `available_agents`
- `disabled_agents`
- `setup_actions`

An agent should depend on integrations only through declared `requirements`. Missing integrations should never leave those agents eligible for routing.

## Specific Integrations

### OpenAI

- Required for the core runtime.
- Minimum concrete setup:
  - `OPENAI_API_KEY`
  - `KENDR_WORKING_DIR`

### Google Workspace

- Configure either a direct `GOOGLE_ACCESS_TOKEN` or OAuth client credentials.
- If OAuth client credentials exist but no token has been acquired yet, setup status will show the integration as OAuth-ready but not configured.

### Microsoft Graph

- Configure either `MICROSOFT_GRAPH_ACCESS_TOKEN` or the OAuth client fields.
- OneDrive/Outlook/Teams dependent agents stay disabled until a usable token exists.

### Slack

- Configure either `SLACK_BOT_TOKEN` or OAuth client fields plus app installation.
- Communication and notification surfaces remain filtered out without a usable token.

### Security Tools

- `nmap`, `zap`, and `dependency-check` are local dependencies, not remote APIs.
- Security agents stay hidden when their required tools are missing.

### Qdrant

- A `QDRANT_URL` alone is not enough.
- `kendr setup status` checks reachability and keeps vector-dependent agents disabled until the service responds.

## Plugin Discovery

External plugins are loaded from:

- `./plugins`
- `~/.kendr/plugins`
- any path listed in `KENDR_PLUGIN_PATHS`

Plugin files are simple Python modules that expose `register(registry)`.

Example:

- [`plugin_templates/echo_plugin.py`](../plugin_templates/echo_plugin.py)
- [`plugin_templates/provider_plugin.py`](../plugin_templates/provider_plugin.py)

See [Plugin SDK](plugin_sdk.md) for manifest expectations, compatibility notes, and testing guidance.

## MCP Servers

The repo includes these MCP surfaces:

| Service | Purpose | Entry Script |
| --- | --- | --- |
| Research MCP | web search, crawl, document parsing, OCR, entity brief | [`mcp_servers/research_server.py`](../mcp_servers/research_server.py) |
| Vector MCP | text indexing and semantic search | [`mcp_servers/vector_server.py`](../mcp_servers/vector_server.py) |
| Nmap MCP | safe host discovery and service scans | [`mcp_servers/nmap_server.py`](../mcp_servers/nmap_server.py) |
| ZAP MCP | baseline web scan summaries | [`mcp_servers/zap_server.py`](../mcp_servers/zap_server.py) |
| Screenshot MCP | browser screenshots and scripted capture | [`mcp_servers/screenshot_server.py`](../mcp_servers/screenshot_server.py) |
| HTTP Surface MCP | safe HTTP surface probing | [`mcp_servers/http_fuzzing_server.py`](../mcp_servers/http_fuzzing_server.py) |
| CVE MCP | CVE and OSV lookup | [`mcp_servers/cve_server.py`](../mcp_servers/cve_server.py) |

## Dockerized Service Surface

The Compose stack currently includes:

- `qdrant`
- `app`
- `daemon`
- `gateway`
- `setup-ui`
- all current MCP services

See [Install](install.md) for the `docker compose up --build` path.
