# Adding a New Agent to This A2A Infrastructure

This guide explains how to create a new agent and integrate it into the current ecosystem (runtime + UI detection).

## Fastest Way (Beginner-Friendly)

Use the scaffold script (recommended):

```bash
python3 ecosystem/create_agent.py gamma --port 8103
```

Super-easy interactive mode (prompts for values):

```bash
python3 ecosystem/create_agent.py
```

OpenAI-enabled template:

```bash
python3 ecosystem/create_agent.py gamma --port 8103 --with-openai
```

MCP-enabled template (adds MCP client/server scaffold):

```bash
python3 ecosystem/create_agent.py gamma --port 8103 --mcp
```

OpenAI + MCP:

```bash
python3 ecosystem/create_agent.py gamma --port 8103 --with-openai --mcp
```

No-DB template (optional):

```bash
python3 ecosystem/create_agent.py gamma --port 8103 --no-task-tracking
```

This auto-creates:
- `agent_gamma/app.py`
- `agent_gamma/agent_executor.py`
- `agent_gamma/AGENT_SETUP.md`

Then run:

```bash
python3 agent_gamma/app.py
```

## 1) Create Agent Folder (Manual)

Create a new directory in project root using `agent_<name>` convention.

Example:

```bash
mkdir -p agent_gamma
```

Required files:
- `agent_gamma/app.py`
- `agent_gamma/agent_executor.py`

The UI scanner auto-detects folders matching `agent_*`.

## 2) Implement Executor

Your executor should implement `AgentExecutor`:

- `execute(self, context, event_queue)`
- `cancel(self, context, event_queue)`

Minimal skeleton:

```python
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message

class GammaAgentExecutor(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = context.get_user_input() or ""
        await event_queue.enqueue_event(new_agent_text_message(f"Gamma handled: {text}"))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise RuntimeError("cancel not supported")
```

## 2.1 DB Creation + Connection (Important)

If you use task tracking, DB setup should happen in executor initialization:

```python
class GammaAgentExecutor(AgentExecutor):
    def __init__(self) -> None:
        self.db_path = os.environ.get("GAMMA_DB_PATH", os.path.join(os.path.dirname(__file__), "gamma_tasks.db"))
        self._init_db()
```

Inside `_init_db()`:
- `CREATE TABLE IF NOT EXISTS ...` for new environments
- optional migration for existing DB files (`PRAGMA table_info` + `ALTER TABLE`)

Runtime flow:
1. Server starts (`app.py`)
2. Executor is instantiated
3. DB/table are created/migrated
4. Each `execute(...)` call inserts task row
5. Processing updates status/result/timestamps
6. Final response is returned

This is why the DB process is part of agent startup, not a separate manual step.

## 3) Implement `app.py` with Agent Card + Port

Use A2A app bootstrap and expose a unique port.

Important: set explicit `port=<number>` in `uvicorn.run(...)`.
The UI detection endpoint parser reads this port from `app.py`.

Also load env in layered mode at startup:
- first: `agent_<name>/.env`
- fallback: project root `.env`
- existing exported env vars still take precedence

Example:

```python
import logging
import uvicorn

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from agent_executor import GammaAgentExecutor


def build_agent_card() -> AgentCard:
    skill = AgentSkill(
        id="gamma_skill",
        name="Gamma Skill",
        description="Example additional agent",
        tags=["gamma", "a2a"],
        examples=["run gamma task"],
    )

    return AgentCard(
        name="Gamma Agent",
        description="Additional agent in ecosystem",
        url="http://127.0.0.1:8103/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=[skill],
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    card = build_agent_card()

    request_handler = DefaultRequestHandler(
        agent_executor=GammaAgentExecutor(),
        task_store=InMemoryTaskStore(),
    )

    app = A2AStarletteApplication(agent_card=card, http_handler=request_handler)
    uvicorn.run(app.build(), host="0.0.0.0", port=8103, log_level="info")
```

## 4) Dependency and Env

If your new agent uses OpenAI or shared utilities, keep dependency set aligned with root `requirements.txt`.

For OpenAI-based agents, set:
- `OPENAI_API_KEY`
- `OPENAI_MODEL` (optional)

If needed, set agent-local overrides in `agent_<name>/.env` while keeping shared defaults in root `.env`.

## 4.1 Skill Definition Checklist (Detailed)

Avoid generic single-line skills. For each `AgentSkill`, define:
- `id`: stable and namespaced (`<agent>_task_execution`, `<agent>_integration_contract`, etc.)
- `name`: human-readable capability
- `description`: clear contract (input shape, processing responsibility, output/error format)
- `tags`: domain + behavior tags (`a2a`, `execute`, `tracking`, `integration`)
- `examples`: realistic payload/prompt examples matching actual calls in executor

Recommended minimum skills:
1. Task execution skill (core behavior).
2. Task tracking/observability skill (status + DB lifecycle).
3. Integration contract skill (actions, required fields, response schema).

## 4.2 MCP Scaffold (Optional)

If you used `--mcp`, the scaffold includes:
- `mcp_server.py` (FastMCP server with example tools)
- `mcp_layer.py` (client wrapper used by the executor)

Quick enable (edit `.env` or export):

```bash
GAMMA_MCP_ENABLED=true
GAMMA_MCP_TOOL_NAME=reverse_string
```

Override the server command/args to point at any MCP server (Python, Node, etc):

```bash
GAMMA_MCP_SERVER_COMMAND=npx
GAMMA_MCP_SERVER_ARGS='-y @modelcontextprotocol/server-everything'
```

### 4.2.1 Create an Agent Wired to an External MCP Server

1. Scaffold the agent with MCP support:

```bash
python3 ecosystem/create_agent.py gamma --port 8103 --mcp
```

2. Add MCP config in `agent_gamma/.env` (or root `.env`):

```env
GAMMA_MCP_ENABLED=true
GAMMA_MCP_SERVER_COMMAND=npx
GAMMA_MCP_SERVER_ARGS='-y @modelcontextprotocol/server-everything'
GAMMA_MCP_TOOL_NAME=reverse_string
GAMMA_MCP_TOOL_ARGS_JSON='{"text":"hello gamma"}'
GAMMA_MCP_PASS_USER_QUERY=true
GAMMA_MCP_CWD=
```

Notes:
- `*_MCP_SERVER_ARGS` is a shell-style string parsed by `shlex.split(...)`.
- Set `*_MCP_TOOL_NAME` to empty to list available MCP tools.
- `*_MCP_TOOL_ARGS_JSON` must be a JSON object string. If `*_MCP_PASS_USER_QUERY=true`, the user query is passed as `text` unless you override it.
- Use `*_MCP_CWD` if the MCP server expects a specific working directory.

3. Python server example:

```env
GAMMA_MCP_SERVER_COMMAND=python3
GAMMA_MCP_SERVER_ARGS='agent_gamma/mcp_server.py'
```

4. Global fallback keys (optional):

If you prefer shared settings, you can use `MCP_*` keys instead of per-agent keys:

```env
MCP_ENABLED=true
MCP_SERVER_COMMAND=npx
MCP_SERVER_ARGS='-y @modelcontextprotocol/server-everything'
MCP_TOOL_NAME=reverse_string
MCP_TOOL_ARGS_JSON='{"text":"hello gamma"}'
MCP_PASS_USER_QUERY=true
MCP_CWD=
```

## 5) Runtime Management + Discovery

Current UI server (`ecosystem/ui_server.py`) now discovers agents automatically by combining:
- `.env` URL/path keys (`AGENT_<NAME>_URL` or `<NAME>_AGENT_URL`)
- folders matching `agent_*` that contain `app.py`

Autostart behavior is also config-driven:
- default autostart: none (all agents are `false` unless explicitly enabled)
- override with `AGENT_<NAME>_AUTOSTART=true|false` (or `<NAME>_AGENT_AUTOSTART`)

For best detection, add each new agent URL in `.env`:
- `AGENT_GAMMA_URL=http://127.0.0.1:8103`

Polling can be tuned per caller-target route:
- in UI, after discovery, using `/polling` page
- default interval is `20` seconds
- values persist in `ecosystem/ecosystem.db` (`ECOSYSTEM_DB_PATH`)

## 6) Connect New Agent into Flow

If Gamma should participate in orchestration (not just standalone):

- Update Alpha executor routing logic to call Gamma (`A2AClient` call flow)
- Define payload contract (`action`, task IDs, etc.)
- Persist additional task metadata if needed in SQLite repositories

If your new agent uses task tracking DB tables, include lifecycle timestamps:
- `created_at` (when task is inserted)
- `updated_at` (last change)
- `completed_at` (when terminal status is reached)
- optional `ready_at` (if using queued/in_progress scheduling)

The scaffold generator now includes `created_at` / `updated_at` / `completed_at` by default.

## 7) Verify

### Basic card verification

```bash
python3 agent_gamma/app.py
curl -s http://127.0.0.1:8103/.well-known/agent-card.json
```

### UI verification

```bash
python3 ecosystem/ui_server.py
```

Open `http://127.0.0.1:8200` and check:
- `Agent Registry Detection` table shows `gamma`
- `detected=yes` when Gamma is running
- `detected=no` when Gamma is stopped

## 8) Common Integration Checklist

- Unique port in `uvicorn.run(...)`
- Card `url` matches actual host/port
- Folder naming is `agent_<name>`
- Agent process is running and reachable
- Payload schema documented if participating in orchestration
- DB init path is configured (`*_DB_PATH`) and table exists
- Terminal states set `completed_at`
- README/doc updates for team visibility

## Extra Easy Mode for Non-Coders

1. Run scaffold command (copy/paste):
   `python3 ecosystem/create_agent.py myagent --port 8103`
2. Start the new agent:
   `python3 agent_myagent/app.py`
3. Start UI:
   `python3 ecosystem/ui_server.py`
4. Open `http://127.0.0.1:8200`:
   - confirm your agent appears in **Agent Registry Detection**
   - click row to inspect details
