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
