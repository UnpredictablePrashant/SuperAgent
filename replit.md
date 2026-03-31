# Kendr Runtime

A plugin-driven multi-agent runtime and orchestration system built on LangGraph/LangChain.

## Architecture

- **`kendr/`** — Core package: runtime, registry, discovery, CLI, gateway server, UI server, setup UI
- **`tasks/`** — Built-in task agent modules (research, coding, security, file ops, etc.)
- **`mcp_servers/`** — MCP server implementations (research, vector, security)
- **`app.py`** — Entry point: builds registry and workflow
- **`kendr/ui_server.py`** — NEW: Kendr Web Chat & Config UI on port 2151 (`kendr ui`)
- **`kendr/setup_ui.py`** — OAuth/Setup Console on port 8787 (`kendr setup ui`)
- **`kendr/gateway_server.py`** — HTTP gateway/ingest server on port 8000 (`kendr gateway start`)

## Running on Replit

The main workflow runs the **Kendr Web Chat & Config UI**.

**Workflow command:**
```
KENDR_UI_HOST=0.0.0.0 KENDR_UI_PORT=5000 python3 -m kendr.cli ui
```

> **Port note**: The Replit webview requires port 5000 (`localPort=5000, externalPort=80`).
> The default port outside Replit is **2151**. The `KENDR_UI_PORT` env var overrides the port.
> `kendr gateway start` (without `kendr ui`) also auto-starts the UI on the default port (2151).

### Port Overview
| Port | Service | Command |
|---|---|---|
| `2151` | Kendr Web Chat + Config UI (default, self-hosted) | `kendr ui` |
| `5000` | Kendr Web Chat + Config UI (Replit webview) | Workflow env `KENDR_UI_PORT=5000` |
| `8000` | Gateway (agent ingest, Replit) | `kendr gateway start` |
| `8787` | Setup/OAuth Console | `kendr setup ui` |

## Key Environment Variables

Set via Replit secrets/env vars (see `.env.example` for the full list):

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Required for agent LLM calls |
| `KENDR_UI_HOST` | Bind host for Chat+Config UI (default: 0.0.0.0) |
| `KENDR_UI_PORT` | Port for Chat+Config UI (default: 2151) |
| `SETUP_UI_HOST` | Bind host for OAuth Setup UI (default: 127.0.0.1) |
| `SETUP_UI_PORT` | Port for OAuth Setup UI (default: 8787) |
| `GATEWAY_HOST` | Bind host for Gateway server (default: 0.0.0.0) |
| `GATEWAY_PORT` | Port for Gateway server (default: 8000) |
| `KENDR_WORKING_DIR` | Default output/workspace directory |

## Python 3.10 Compatibility Fixes

The codebase was migrated from Python 3.11+ to 3.10 (Replit's default). Fixes applied:

1. **`datetime.UTC`** → replaced with `timezone.utc` across all task/kendr modules
2. **`typing.NotRequired`** → wrapped with try/except fallback to `typing_extensions` in `kendr/orchestration/state.py`

## Dependencies

Managed via `pyproject.toml`. Install with:
```
pip install -e ".[dev]"
```

Key dependencies: `langgraph`, `langchain`, `langchain-openai`, `openai`, `fastmcp`, `qdrant-client`, `playwright`, `boto3`, `telethon`

## Task #2: Deep Research & Document Generation Pipeline

New capabilities added:

### New functions in `tasks/research_infra.py`
- **`arxiv_search(query, max_results, sort_by)`** — Fetches academic papers from the arXiv Atom API (no API key required)
- **`reddit_search(query, subreddit, sort, limit)`** — Fetches Reddit posts from the public JSON search API (no auth required)

### New file: `tasks/research_pipeline_tasks.py`
- **`research_pipeline_agent(state)`** — Orchestrates multi-source evidence collection from any combination of: `web`, `arxiv`, `reddit`, `scholar`, `patents`, `openalex`
- Builds a combined markdown evidence report with formatted results per source
- Populates `long_document_evidence_bank_*` state keys when `long_document_collect_sources_first` is set

### CLI additions to `kendr/cli.py`
- **`--sources web,arxiv,reddit`** — Comma-separated source list for the research pipeline; sets `research_sources` in state
- **`--pages 50`** — Shorthand for `--long-document --long-document-pages 50`; implies long-form document mode

### State additions in `kendr/orchestration/state.py`
- `research_sources: list[str]`
- `research_pipeline_enabled: bool`

### MCP server updates in `mcp_servers/research_server.py`
- New `arxiv_papers` tool — fetches arXiv papers via MCP
- New `reddit_posts` tool — fetches Reddit posts via MCP

## Task #3: Multi-Agent Dev Project Generation

New `kendr generate` and `kendr research` subcommands added to `kendr/cli.py`.

### `kendr generate` command
Generates a complete multi-agent software project from a natural language description.

```
kendr generate "a FastAPI todo API with PostgreSQL" --auto-approve
kendr generate "a Next.js SaaS dashboard" --stack nextjs_prisma_postgres --name my-saas --output ~/projects
kendr generate "an Express REST API with MongoDB" --skip-tests --skip-devops
```

Flags:
- `description` — Natural language description of the project (positional)
- `--name NAME` — Project name in kebab-case; auto-derived if omitted
- `--stack STACK` — Stack template (fastapi_postgres, fastapi_react_postgres, nextjs_prisma_postgres, express_prisma_postgres, mern_microservices_mongodb, pern_postgres, nextjs_static_site)
- `--output PATH` — Output directory root (defaults to working directory)
- `--auto-approve` — Skip interactive blueprint/plan approval prompts
- `--skip-tests` — Omit test_agent from the build plan
- `--skip-devops` — Omit devops_agent (Dockerfile/CI/CD) from the build plan
- `--skip-reviews` — Skip reviewer agent between steps
- `--max-steps N` — Max orchestration steps (default 40)

Sets `project_build_mode=True` in state so the orchestrator directly routes to `project_blueprint_agent` without NLP detection.

### `kendr research` command
Runs a multi-source research pipeline and optionally generates a long-form document.

```
kendr research "transformer architectures 2024" --sources arxiv,openalex --pages 20
kendr research "AI in healthcare" --sources web,scholar,reddit --title "AI Healthcare Report"
kendr research "my local notes" --drive ~/documents --sources local
```

Flags:
- `query` — Research query or topic (positional)
- `--sources SOURCES` — Comma-separated sources (web, arxiv, reddit, scholar, patents, openalex, local)
- `--pages N` — Target page count; implies long-form document mode
- `--title TITLE` — Optional document title
- `--drive PATH` — Local folder/file path (repeatable)
- `--research-model MODEL` — Override deep-research model
- `--auto-approve` — Auto-approve plan gates

### New file: `tasks/dev_pipeline_tasks.py`
- `dev_pipeline_agent(state)` — end-to-end synchronous pipeline orchestrator
- Stages: blueprint → blueprint approval gate → scaffold → db → auth → backend → frontend → deps → tests → security scan → devops → verify → auto-fix loop → post-setup → zip export
- **Blueprint approval gate**: Interactive y/n prompt (skipped when `auto_approve=True`)
- **Auto-fix retry loop**: Up to `dev_pipeline_max_fix_rounds` (default 3) rounds — invokes `coding_agent` to fix when `project_verifier_agent` fails
- **Zip export**: Packages generated project into `<project_name>.zip` in parent of `project_root`; writes path to `dev_pipeline_zip_path` state key
- `dev_pipeline_zip_path` persisted to `dev_pipeline_zip_path.txt` in the output directory

### `kendr run --dev` flag
- `--dev` — activates `dev_pipeline_mode`, routes to `dev_pipeline_agent` instead of planner
- `--dev-skip-tests` — omit test stage
- `--dev-skip-devops` — omit devops stage
- `--dev-max-fix-rounds N` — override auto-fix retry count (default 3)

### Runtime changes
- `_is_project_build_request()` in `kendr/runtime.py` — now returns `True` immediately when `project_build_mode` is already set in state (avoids requiring NLP marker detection for `generate` command)
- New routing block in `kendr/runtime.py` — routes to `dev_pipeline_agent` when `dev_pipeline_mode=True`; takes priority over individual `project_blueprint_agent` routing
- `skip_test_agent: bool` and `skip_devops_agent: bool` added to `RuntimeState` in `kendr/orchestration/state.py`
- New dev pipeline state keys: `dev_pipeline_mode`, `dev_pipeline_status`, `dev_pipeline_stages_completed`, `dev_pipeline_error`, `dev_pipeline_zip_path`, `dev_pipeline_max_fix_rounds`, `project_verifier_status`, `project_verifier_output`
- Planner prompt updated to honor `skip_test_agent` and `skip_devops_agent` flags from planning context

## Task #4: SuperRAG Zero-Config Knowledge Engine (Vector Backend Abstraction)

### New file: `tasks/vector_backends.py`
Pluggable vector store backend abstraction with zero-config local fallback:

- **`VectorBackend`** — Abstract base class with `ensure_collection()`, `upsert()`, `search()` methods
- **`ChromaBackend`** — Local persistent vector store using `chromadb.PersistentClient`; stores data in `$KENDR_WORKING_DIR/.chroma/` (fallback `./.chroma/`)
- **`QdrantBackend`** — Wraps Qdrant with lazy client creation; connects to `QDRANT_URL`
- **`get_vector_backend()`** — Auto-selects backend on first call; result is cached process-wide:
  1. If `QDRANT_URL` is set and Qdrant health check passes → `QdrantBackend`
  2. If default Qdrant URL (`localhost:6333`) is reachable → `QdrantBackend`
  3. Otherwise → `ChromaBackend` (zero-config, no server required)
  4. Prints `[vector] Using ChromaDB (local)` or `[vector] Using Qdrant at <url>` to stderr

### Updated: `tasks/research_infra.py`
- `ensure_vector_collection()` — now delegates to `get_vector_backend().ensure_collection()`
- `upsert_memory_records()` — now delegates to `get_vector_backend().upsert()`
- `search_memory()` — now delegates to `get_vector_backend().search()`
- `embed_texts()` — unchanged; still uses OpenAI embeddings for both backends
- `get_qdrant_client()` — kept for backwards compatibility but no longer used internally

### Callers unchanged (no API changes)
- `tasks/superrag_tasks.py` — imports `search_memory`, `upsert_memory_records` (unchanged)
- `mcp_servers/vector_server.py` — imports `search_memory`, `upsert_memory_records`, `DEFAULT_QDRANT_COLLECTION` (unchanged)
- `kendr/domain/local_drive.py` — calls via `intelligence_tasks` (unchanged)

### Dependencies
- Added `chromadb` to `pyproject.toml` dependencies

## Task #5: Unified Communication Suite

### Updated file: `tasks/communication_tasks.py`
Fully rewritten for robustness. All agents require `state["communication_authorized"] = True`.

#### New agents:
- **`whatsapp_list_messages_agent`** — Lists recent WhatsApp Business inbox messages via Meta Graph API v18+. Requires `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID`.
- **`whatsapp_send_message_agent`** — Sends a plain-text or template message via Meta Graph API v18+. Requires `WHATSAPP_ACCESS_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID`, and `state["whatsapp_to"]`.
- **`communication_summary_agent`** — Concurrent multi-provider digest agent. Fetches from all configured channels (Gmail, Slack, Microsoft Graph, Telegram, WhatsApp) using `ThreadPoolExecutor`. Filters by `communication_lookback_hours` (default 24h). Writes digest to output folder.

#### Telegram async fix (`telegram_agent`):
- `_run_telethon_sync(coro_factory)` — runs Telethon coroutines in a dedicated thread with `asyncio.new_event_loop()`. Prevents event loop conflicts with the LangGraph sync executor.

#### AGENT_METADATA:
Registered for `whatsapp_send_message_agent`, `whatsapp_list_messages_agent`, `communication_summary_agent` with description, skills, input/output keys, and requirements.

#### New CLI flags:
- `--communication-authorized` — sets `communication_authorized=True` in the ingest payload
- `--communication-lookback-hours N` — sets `communication_lookback_hours`
- `--whatsapp-to NUMBER` — sets `whatsapp_to` (E.164 format)
- `--whatsapp-message TEXT` — sets `whatsapp_message`
- `--whatsapp-template NAME` — sets `whatsapp_template_name`
- `--whatsapp-template-language CODE` — sets `whatsapp_template_language` (default: en_US)

#### SampleTasks.md additions:
- Case Study 11: Unified Communication Digest — concurrent multi-provider fetch + digest
- Case Study 12: WhatsApp Message Send — plain-text and template send

## Task #6: Futuristic CLI Personality + On-Demand Gateway

### CLI taglines expanded (`kendr/cli.py`):
`_cli_tagline()` now rotates through 12 options (was 4). New additions include:
- "Research, build, communicate, and know — all from one command."
- "Your agents are waiting. Give them a mission."
- "Multi-source intelligence in a single invocation."
- "From raw query to polished report, without leaving the terminal."
- "Deploy a fleet of agents with one line."
- "The intelligence layer your workflow was missing."
- "Ship faster. Think deeper. Automate further."
- "Knowledge at the speed of the command line."

### New command: `kendr hello`
- Shows ASCII art logo + version
- Lists all 5 core capabilities with copy-ready example commands
- Prints a 5-step setup guide
- Includes links to SampleTasks.md and help references
- `--json` flag emits all content as structured JSON (useful for tooling integration)

### On-demand gateway (pre-existing, documented):
`kendr gateway start/stop/status/restart` — fully functional on-demand gateway control.
Gateway auto-starts on first `kendr run` if not already running.
Explicit management: `kendr gateway start` (pre-launch) / `kendr gateway stop` (clean shutdown).
