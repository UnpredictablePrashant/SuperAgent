# Learn.md - Deep Beginner Guide to This A2A Demo

This file explains how the code works block by block so a new learner can read the project with confidence.

## 1) Big Picture: What Is Happening?

This project is an **Agent-to-Agent (A2A)** system with 3 agents:

- **Alpha**: Planner/orchestrator agent
- **Beta**: Worker/content generator agent
- **Gamma**: Another worker agent with similar async task lifecycle

Main runtime path:

1. User sends text to Alpha.
2. Alpha creates a planner brief (OpenAI or fallback).
3. Alpha submits a task to Beta or Gamma (`submit_task`).
4. Worker returns `task_id` + `queued` status.
5. Alpha polls worker (`get_task_status`) until terminal status.
6. Alpha sends final combined response to user.
7. SQLite stores lifecycle states for observability.

---

## 2) Core A2A Contract Used in This Repo

This repo uses JSON action messages in text payloads.

### Submit payload

```json
{
  "action": "submit_task",
  "source_agent": "alpha",
  "user_query": "...",
  "planner_brief": "..."
}
```

### Poll payload

```json
{
  "action": "get_task_status",
  "task_id": "<uuid>"
}
```

### Common statuses

- `queued`
- `in_progress`
- `completed`
- `failed`
- `not_found`
- `invalid_request`

---

## 3) `app.py` Files: Bootstrapping Each Agent Server

Files:

- `agent_alpha/app.py`
- `agent_beta/app.py`
- `agent_gamma/app.py`

Each `app.py` has the same core blocks.

### Block A: Imports + path setup

Purpose:

- Load A2A server components.
- Make sure project root is in `sys.path` so shared `agent_core` imports work.

### Block B: `load_env_chain(...)`

Purpose:

- Load environment values from:
  1. `agent_<name>/.env`
  2. root `.env`
  3. already-exported OS env vars win over both

This allows global defaults + per-agent overrides.

### Block C: Agent Card builder

Purpose:

- Build metadata exposed at `/.well-known/agent-card.json`.
- Defines `name`, `description`, `url`, `skills`, `capabilities`.

Why this matters:

- Other agents/UIs discover your agent and know how to call it.

### Block D: Request handler + executor wiring

Code pattern:

- `DefaultRequestHandler(agent_executor=..., task_store=InMemoryTaskStore())`
- `A2AStarletteApplication(...)`
- `uvicorn.run(... port=810x ...)`

Purpose:

- Connect transport layer (A2A HTTP server) to your business logic (`AgentExecutor`).

---

## 4) Alpha Executor (`agent_alpha/agent_executor.py`) - Orchestrator Logic

### Block A: Constructor (`__init__`)

Responsibilities:

- Read worker URLs (`BETA_AGENT_URL`, `GAMMA_AGENT_URL`).
- Read selected worker (`ALPHA_WORKER_AGENT`, default `beta`).
- Create OpenAI client (`agent_core.openai_utils`).
- Load polling defaults and DB path.
- Initialize `AlphaTaskRepository` for local orchestration history.

### Block B: `_resolve_worker_url(...)`

Purpose:

- Convert worker id (`beta`, `gamma`, or custom) into actual URL.

Design point:

- Supports dynamic agent expansion through env keys.

### Block C: `_create_plan(user_query)`

Purpose:

- Use OpenAI to format a strict planner brief.
- If model/client fails, fallback to deterministic text template.

This makes planner behavior resilient in offline/error mode.

### Block D: `execute(...)`

This is the main Alpha flow:

1. Read user input.
2. Build planner brief.
3. Resolve worker and polling config.
4. Resolve worker agent card using `A2ACardResolver`.
5. Send `submit_task` payload using `send_text_message(...)`.
6. Store first worker response in Alpha DB.
7. If task id exists, poll status in a loop.
8. Update Alpha DB on each poll result.
9. Build final human-readable summary and enqueue event response.

Important design idea:

- Alpha does not assume immediate completion. It follows async task lifecycle and can handle delayed workers.

### Block E: `cancel(...)`

- Not implemented (`RuntimeError`).

---

## 5) Beta Executor (`agent_beta/agent_executor.py`) - Worker with Repository

### Block A: Constructor

- Reads model + API key client.
- Reads task delay (`BETA_TASK_DELAY_SECONDS`).
- Initializes `BetaTaskRepository`.

### Block B: `_generate_story(...)` and `_generate_llm_response(...)`

- Generates final story from Alpha brief.
- Uses fallback story if no OpenAI key.
- Catches model errors and returns graceful failure text.

### Block C: `_refresh_and_get_task(task_id)`

State machine behavior:

1. If task terminal (`completed`/`failed`) -> return.
2. If still before `ready_at`:
   - move `queued` -> `in_progress`.
3. If ready:
   - run generation,
   - update task to `completed` or `failed`.

### Block D: `execute(...)`

Action router:

- `submit_task`: insert task row, return `task_id` and timestamps.
- `get_task_status`: refresh state and return lifecycle data.
- missing/unknown action: treat input as task submission.

Response is sent as pretty JSON text back through A2A event queue.

---

## 6) Gamma Executor (`agent_gamma/agent_executor.py`) - Worker with Inline SQLite

Gamma is conceptually similar to Beta, but DB logic is inside executor instead of shared repository class.

### Block A: Constructor + `_init_db()`

- Reads model/key/delay/db path.
- Creates `gamma_tasks` table.
- Performs safe migration via `_ensure_column(...)`.

### Block B: DB helpers

- `_insert_task(...)`
- `_get_task(...)`
- `_update_task_status(...)`

These implement task persistence lifecycle directly.

### Block C: `_generate_text(...)`

- Calls OpenAI responses API with simple system prompt.
- If key missing, returns guidance text.

### Block D: `_refresh_and_get_task(...)`

- Same lifecycle pattern as Beta:
  - queued/in_progress while waiting
  - generate when `ready_at` reached
  - store completed/failed

### Block E: `execute(...)`

- Same action contract (`submit_task`, `get_task_status`) as Beta.
- Returns JSON lifecycle payload to caller.

---

## 7) Shared Core Utilities (`agent_core/*`)

### `env_loader.py`

- Reads `.env` files safely.
- Merges root + agent values.
- Does not overwrite pre-set process env.

### `json_utils.py`

- `parse_json_or_none`: safe dict parser.
- `to_json` / `to_pretty_json`: consistent serialization.

### `openai_utils.py`

- `create_openai_client_from_env`: optional client.
- `extract_openai_text`: robust text extraction across response shapes.

### `a2a_utils.py`

- `send_text_message(...)`: wraps A2A `SendMessageRequest` with logs.
- `extract_last_a2a_text(...)`: pulls latest text part from complex response payload.
- `resolve_polling_config(...)`: chooses polling settings from DB/env with fallback priority.

### `task_repositories.py`

- `AlphaTaskRepository`: tracks orchestration-side view.
- `BetaTaskRepository`: tracks worker-side lifecycle.
- Both include table creation and small migration support.

---

## 8) UI Orchestration Layer (`ecosystem/ui_server.py`)

Main responsibilities:

- Load env and discover agents.
- Optionally autostart local agent processes.
- Expose APIs for tasks/sessions/config/db snapshots.
- Persist polling config per caller-target pair in `ecosystem.db`.
- Push live events through websocket.

Why this layer is useful:

- You can run multi-agent demos from browser without manually wiring each call.

---

## 9) Data Flow Walkthrough (End-to-End)

Example user query: `"write a short story about climate resilience"`

1. UI/API sends message to Alpha.
2. Alpha makes planner brief.
3. Alpha -> Beta: `submit_task` JSON.
4. Beta stores queued task and returns `task_id`.
5. Alpha polls Beta every configured interval.
6. Beta moves task to `in_progress`, then `completed` with generated result.
7. Alpha receives final result, stores to `alpha_tasks`, returns final summary.

---

## 10) Gamma MCP Layer (FastMCP) - Code Explanation

MCP is implemented in Gamma and can be scaffolded for new agents via `--mcp` in `ecosystem/create_agent.py`.

- **A2A**: Alpha <-> Gamma task exchange
- **MCP**: Gamma <-> tool server exchange

Current Gamma MCP files:

- `agent_gamma/mcp_layer.py` (FastMCP client wrapper)
- `agent_gamma/mcp_server.py` (minimal FastMCP server with reverse tool)

### 10.1 `agent_gamma/mcp_server.py` (minimal tool server)

Block-by-block:

1. `mcp = FastMCP(name=\"Gamma Minimal MCP\")`
   - Creates a FastMCP server instance.
2. `@mcp.tool` over `reverse_string(text: str) -> str`
   - Exposes one MCP tool named `reverse_string`.
   - Returns `text[::-1]` (reverse string).
3. `mcp.run()` in `__main__`
   - Starts MCP server on stdio transport.
   - This is what Gamma client launches as a subprocess.

### 10.2 `agent_gamma/mcp_layer.py` (Gamma-only client wrapper)

Main parts:

1. Safe imports of FastMCP client classes:
   - `Client`
   - `StdioTransport`
   - If package missing, code degrades gracefully with error message.
2. `GammaMCPConfig` dataclass:
   - Stores runtime MCP config (enabled, command, args, tool name, args JSON, cwd).
3. `GammaMCPClient.from_env()`:
   - Reads Gamma-specific env keys:
     - `GAMMA_MCP_ENABLED`
     - `GAMMA_MCP_SERVER_COMMAND`
     - `GAMMA_MCP_SERVER_ARGS`
     - `GAMMA_MCP_TOOL_NAME`
     - `GAMMA_MCP_TOOL_ARGS_JSON`
     - `GAMMA_MCP_PASS_USER_QUERY`
     - `GAMMA_MCP_CWD`
   - Defaults are beginner-friendly:
     - command: current Python interpreter
     - args: local `agent_gamma/mcp_server.py`
     - tool: `reverse_string`
4. `fetch_context(user_query)`:
   - Builds `StdioTransport(command, args, cwd)`.
   - Opens FastMCP `Client` session.
   - If tool name missing, returns available tool list.
   - Else calls tool with args.
   - If `GAMMA_MCP_PASS_USER_QUERY=true`, injects user text as `text` argument.
   - Returns tool output as context string for Gamma executor.

### 10.3 Where Gamma Executor Uses MCP

In `agent_gamma/agent_executor.py`:

1. `self.mcp = GammaMCPClient.from_env()` in `__init__`.
2. `_generate_text(user_query)` calls `await self.mcp.fetch_context(user_query)`.
3. If OpenAI is disabled but MCP returns data, Gamma still completes task with MCP output.
4. If OpenAI is enabled, MCP context is injected into model prompt.

This keeps Gamma resilient:
- MCP off -> normal Gamma behavior
- MCP on + no OpenAI -> tool-only response still works
- MCP on + OpenAI -> tool-augmented response

### 10.4 Reverse String Example

Minimal `.env`:

```env
GAMMA_MCP_ENABLED=true
GAMMA_MCP_SERVER_COMMAND=python3
GAMMA_MCP_SERVER_ARGS='agent_gamma/mcp_server.py'
GAMMA_MCP_TOOL_NAME=reverse_string
GAMMA_MCP_PASS_USER_QUERY=true
```

If `user_query` is `hello gamma`, MCP tool output is:

`ammag olleh`

---

## 11) Beginner Debug Checklist

If something breaks, check in this order:

1. Agent process is running on the expected port.
2. `/.well-known/agent-card.json` is reachable.
3. `.env` URLs and DB paths are correct.
4. `submit_task` payload has expected fields.
5. Polling interval/attempt settings are sane.
6. Worker DB rows move through `queued -> in_progress -> completed/failed`.
7. `OPENAI_API_KEY` exists when expecting model output.
8. MCP is optional and should degrade gracefully when unavailable.

---

## 12) Quick Mental Model for Newcomers

- `app.py` = network server + identity card
- `agent_executor.py` = agent brain
- `task_repositories.py` / sqlite blocks = memory + lifecycle tracking
- `a2a_utils.py` = communication helpers
- `ui_server.py` = ecosystem runtime dashboard/orchestrator
- MCP layer (new) = external tools/data extension for agents

If you understand those six pieces, you understand this project deeply.
