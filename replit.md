# Kendr Runtime

A plugin-driven multi-agent runtime and orchestration system built on LangGraph/LangChain.

## Architecture

- **`kendr/`** — Core package: runtime, registry, discovery, CLI, gateway server, setup UI
- **`tasks/`** — Built-in task agent modules (research, coding, security, file ops, etc.)
- **`mcp_servers/`** — MCP server implementations (research, vector, security)
- **`app.py`** — Entry point: builds registry and workflow
- **`setup_ui.py`** — Starts the web-based Setup Console
- **`gateway_server.py`** — Starts the HTTP gateway/dashboard server

## Running on Replit

The main workflow runs the **Kendr Setup Console** (web UI) on port 5000.

**Workflow command:**
```
SETUP_UI_HOST=0.0.0.0 SETUP_UI_PORT=5000 python3 setup_ui.py
```

## Key Environment Variables

Set via Replit secrets/env vars (see `.env.example` for the full list):

| Variable | Purpose |
|---|---|
| `OPENAI_API_KEY` | Required for agent LLM calls |
| `SETUP_UI_HOST` | Bind host for Setup UI (set to `0.0.0.0`) |
| `SETUP_UI_PORT` | Port for Setup UI (set to `5000`) |
| `GATEWAY_HOST` | Bind host for Gateway server (set to `0.0.0.0`) |
| `GATEWAY_PORT` | Port for Gateway server (set to `8000`) |

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
