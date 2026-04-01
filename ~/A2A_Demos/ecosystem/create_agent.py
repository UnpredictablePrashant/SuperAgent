import argparse
from pathlib import Path


APP_TEMPLATE = '''import logging
import sys

import uvicorn

from pathlib import Path

from a2a.server.apps import A2AStarletteApplication
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.tasks import InMemoryTaskStore
from a2a.types import AgentCapabilities, AgentCard, AgentSkill

from agent_executor import {class_name}

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from agent_core.env_loader import load_env_chain


def build_skills() -> list[AgentSkill]:
    return [
        AgentSkill(
            # id: stable machine-friendly unique identifier for this capability.
            id="{agent_id}_task_execution",
            # name: short human-readable label shown in cards/UIs.
            name="{agent_name} Task Execution",
            # description: what this skill does, expected input shape, and output behavior.
            description=(
                "Primary execution skill for {agent_name}. "
                "Accepts plain text or structured task text, validates input, runs business logic, "
                "and returns final status plus output."
            ),
            # tags: searchable keywords for discovery/routing in multi-agent ecosystems.
            tags=["{agent_id}", "execute", "task", "a2a"],
            # examples: realistic prompts/messages that demonstrate intended usage.
            examples=[
                "execute {agent_id} task: summarize this requirement",
                "run {agent_id} on: generate implementation notes",
            ],
        ),
        AgentSkill(
            id="{agent_id}_task_tracking",
            name="{agent_name} Task Tracking",
            description=(
                "Tracks task lifecycle in SQLite when task tracking template is enabled. "
                "Persists created/updated/completed timestamps, status transitions, and result/error payloads."
            ),
            tags=["{agent_id}", "sqlite", "tracking", "observability"],
            examples=[
                "show latest {agent_id} task status from DB",
                "inspect {agent_id} completed tasks and timestamps",
            ],
        ),
        AgentSkill(
            id="{agent_id}_integration_contract",
            name="{agent_name} Integration Contract",
            description=(
                "Defines how other agents should call this agent through A2A payload conventions "
                "(action names, required fields, and response contract)."
            ),
            tags=["{agent_id}", "integration", "contract", "a2a"],
            examples=[
                "what payload schema should alpha send to {agent_id}",
                "document response fields for {agent_id} task status",
            ],
        ),
{mcp_skill_block}
    ]


def build_agent_card() -> AgentCard:
    return AgentCard(
        name="{agent_name}",
        description="{agent_name} in A2A ecosystem.",
        url="http://127.0.0.1:{port}/",
        version="1.0.0",
        default_input_modes=["text"],
        default_output_modes=["text"],
        capabilities=AgentCapabilities(streaming=True),
        skills=build_skills(),
    )


if __name__ == "__main__":
    load_env_chain(agent_dir=Path(__file__).resolve().parent, root_dir=ROOT_DIR)
    logging.basicConfig(level=logging.INFO)
    card = build_agent_card()

    request_handler = DefaultRequestHandler(
        agent_executor={class_name}(),
        task_store=InMemoryTaskStore(),
    )

    app = A2AStarletteApplication(agent_card=card, http_handler=request_handler)
    uvicorn.run(app.build(), host="0.0.0.0", port={port}, log_level="info")
'''


EXEC_TEMPLATE_BASIC = '''import os
import sqlite3
import time

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message


class {class_name}(AgentExecutor):
    def __init__(self) -> None:
        self.db_path = os.environ.get("{agent_env_db_key}", os.path.join(os.path.dirname(__file__), "{agent_id}_tasks.db"))
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS {agent_id}_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    input_text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_text TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                )
                """
            )
            conn.commit()

    def _insert_task(self, input_text: str) -> tuple[int, float]:
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO {agent_id}_tasks (input_text, status, result_text, created_at, updated_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (input_text, "in_progress", None, now, now, None),
            )
            conn.commit()
            return int(cur.lastrowid), now

    def _complete_task(self, task_id: int, result_text: str) -> tuple[float, float]:
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE {agent_id}_tasks
                SET status = ?, result_text = ?, updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                ("completed", result_text, now, now, task_id),
            )
            conn.commit()
        return now, now

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_text = context.get_user_input() or ""
        task_id, created_at = self._insert_task(user_text)

        reply_text = (
            "{agent_name} response:\\n"
            f"- task_id: {{task_id}}\\n"
            "- status: completed\\n"
            f"- input: {{user_text}}\\n"
            "- note: You can customize this behavior in agent_executor.py"
        )

        updated_at, completed_at = self._complete_task(task_id, reply_text)
        final = (
            f"{{reply_text}}\\n"
            f"- created_at: {{created_at}}\\n"
            f"- updated_at: {{updated_at}}\\n"
            f"- completed_at: {{completed_at}}"
        )
        await event_queue.enqueue_event(new_agent_text_message(final))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise RuntimeError("cancel not supported")
'''


EXEC_TEMPLATE_OPENAI = '''import os
import sqlite3
import time

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message
from openai import AsyncOpenAI


class {class_name}(AgentExecutor):
    def __init__(self) -> None:
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        self.client = AsyncOpenAI(api_key=api_key) if api_key else None
        self.db_path = os.environ.get("{agent_env_db_key}", os.path.join(os.path.dirname(__file__), "{agent_id}_tasks.db"))
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS {agent_id}_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    input_text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_text TEXT,
                    error_text TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                )
                """
            )
            conn.commit()

    def _insert_task(self, input_text: str) -> tuple[int, float]:
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO {agent_id}_tasks (input_text, status, result_text, error_text, created_at, updated_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (input_text, "in_progress", None, None, now, now, None),
            )
            conn.commit()
            return int(cur.lastrowid), now

    def _finish_task(self, task_id: int, status: str, result_text: str | None, error_text: str | None) -> tuple[float, float]:
        now = time.time()
        completed_at = now if status in {{"completed", "failed"}} else None
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE {agent_id}_tasks
                SET status = ?, result_text = ?, error_text = ?, updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (status, result_text, error_text, now, completed_at, task_id),
            )
            conn.commit()
        return now, completed_at or now

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_text = context.get_user_input() or ""
        task_id, created_at = self._insert_task(user_text)

        status = "completed"
        error = None

        if not self.client:
            reply = "Set OPENAI_API_KEY to enable model responses."
            status = "failed"
            error = reply
        else:
            try:
                res = await self.client.responses.create(
                    model=self.model,
                    input=[
                        {{"role": "system", "content": "You are {agent_name}."}},
                        {{"role": "user", "content": user_text}},
                    ],
                )
                reply = res.output_text or "(empty model response)"
            except Exception as exc:
                status = "failed"
                error = str(exc)
                reply = f"OpenAI call failed: {{exc}}"

        updated_at, completed_at = self._finish_task(
            task_id=task_id,
            status=status,
            result_text=reply if status == "completed" else None,
            error_text=error,
        )

        final = (
            f"{agent_name} response:\\n"
            f"- task_id: {{task_id}}\\n"
            f"- status: {{status}}\\n"
            f"- created_at: {{created_at}}\\n"
            f"- updated_at: {{updated_at}}\\n"
            f"- completed_at: {{completed_at}}\\n"
            f"- output:\\n{{reply}}"
        )
        await event_queue.enqueue_event(new_agent_text_message(final))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise RuntimeError("cancel not supported")
'''


EXEC_TEMPLATE_BASIC_NO_TRACK = '''from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message


class {class_name}(AgentExecutor):
    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_text = context.get_user_input() or ""
        reply = (
            "{agent_name} response:\\n"
            f"- I received: {{user_text}}\\n"
            "- You can customize this in agent_executor.py"
        )
        await event_queue.enqueue_event(new_agent_text_message(reply))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise RuntimeError("cancel not supported")
'''


EXEC_TEMPLATE_OPENAI_NO_TRACK = '''import os

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message
from openai import AsyncOpenAI


class {class_name}(AgentExecutor):
    def __init__(self) -> None:
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        self.client = AsyncOpenAI(api_key=api_key) if api_key else None

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_text = context.get_user_input() or ""

        if not self.client:
            reply = "Set OPENAI_API_KEY to enable model responses."
        else:
            try:
                res = await self.client.responses.create(
                    model=self.model,
                    input=[
                        {{"role": "system", "content": "You are {agent_name}."}},
                        {{"role": "user", "content": user_text}},
                    ],
                )
                reply = res.output_text or "(empty model response)"
            except Exception as exc:
                reply = f"OpenAI call failed: {{exc}}"

        await event_queue.enqueue_event(new_agent_text_message(reply))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise RuntimeError("cancel not supported")
'''


EXEC_TEMPLATE_BASIC_MCP = '''import os
import sqlite3
import time

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message

from mcp_layer import MCPClient


class {class_name}(AgentExecutor):
    def __init__(self) -> None:
        self.mcp = MCPClient.from_env()
        self.db_path = os.environ.get("{agent_env_db_key}", os.path.join(os.path.dirname(__file__), "{agent_id}_tasks.db"))
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS {agent_id}_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    input_text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_text TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                )
                """
            )
            conn.commit()

    def _insert_task(self, input_text: str) -> tuple[int, float]:
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO {agent_id}_tasks (input_text, status, result_text, created_at, updated_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (input_text, "in_progress", None, now, now, None),
            )
            conn.commit()
            return int(cur.lastrowid), now

    def _complete_task(self, task_id: int, result_text: str) -> tuple[float, float]:
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE {agent_id}_tasks
                SET status = ?, result_text = ?, updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                ("completed", result_text, now, now, task_id),
            )
            conn.commit()
        return now, now

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_text = context.get_user_input() or ""
        task_id, created_at = self._insert_task(user_text)

        reply_text = (
            "{agent_name} response:\\n"
            f"- task_id: {{task_id}}\\n"
            "- status: completed\\n"
            f"- input: {{user_text}}\\n"
            "- note: You can customize this behavior in agent_executor.py"
        )

        mcp_context = await self.mcp.fetch_context(user_text)
        if mcp_context:
            reply_text = f"{{reply_text}}\\n- mcp_context:\\n{{mcp_context}}"

        updated_at, completed_at = self._complete_task(task_id, reply_text)
        final = (
            f"{{reply_text}}\\n"
            f"- created_at: {{created_at}}\\n"
            f"- updated_at: {{updated_at}}\\n"
            f"- completed_at: {{completed_at}}"
        )
        await event_queue.enqueue_event(new_agent_text_message(final))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise RuntimeError("cancel not supported")
'''


EXEC_TEMPLATE_OPENAI_MCP = '''import os
import sqlite3
import time

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message
from openai import AsyncOpenAI

from mcp_layer import MCPClient


class {class_name}(AgentExecutor):
    def __init__(self) -> None:
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        self.client = AsyncOpenAI(api_key=api_key) if api_key else None
        self.mcp = MCPClient.from_env()
        self.db_path = os.environ.get("{agent_env_db_key}", os.path.join(os.path.dirname(__file__), "{agent_id}_tasks.db"))
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS {agent_id}_tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    input_text TEXT NOT NULL,
                    status TEXT NOT NULL,
                    result_text TEXT,
                    error_text TEXT,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL,
                    completed_at REAL
                )
                """
            )
            conn.commit()

    def _insert_task(self, input_text: str) -> tuple[int, float]:
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO {agent_id}_tasks (input_text, status, result_text, error_text, created_at, updated_at, completed_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (input_text, "in_progress", None, None, now, now, None),
            )
            conn.commit()
            return int(cur.lastrowid), now

    def _finish_task(self, task_id: int, status: str, result_text: str | None, error_text: str | None) -> tuple[float, float]:
        now = time.time()
        completed_at = now if status in {{"completed", "failed"}} else None
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                UPDATE {agent_id}_tasks
                SET status = ?, result_text = ?, error_text = ?, updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (status, result_text, error_text, now, completed_at, task_id),
            )
            conn.commit()
        return now, completed_at or now

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_text = context.get_user_input() or ""
        task_id, created_at = self._insert_task(user_text)

        status = "completed"
        error = None

        mcp_context = await self.mcp.fetch_context(user_text)

        if not self.client:
            if mcp_context:
                reply = "MCP response (OpenAI disabled):\\n" + mcp_context
                status = "completed"
            else:
                reply = "Set OPENAI_API_KEY to enable model responses."
                status = "failed"
                error = reply
        else:
            try:
                user_input = user_text
                if mcp_context:
                    user_input = (
                        f"User query:\\n{{user_text}}\\n\\n"
                        f"MCP context:\\n{{mcp_context}}\\n\\n"
                        "Use MCP context when relevant and clearly answer the user query."
                    )
                res = await self.client.responses.create(
                    model=self.model,
                    input=[
                        {{"role": "system", "content": "You are {agent_name}."}},
                        {{"role": "user", "content": user_input}},
                    ],
                )
                reply = res.output_text or "(empty model response)"
            except Exception as exc:
                status = "failed"
                error = str(exc)
                reply = f"OpenAI call failed: {{exc}}"

        updated_at, completed_at = self._finish_task(
            task_id=task_id,
            status=status,
            result_text=reply if status == "completed" else None,
            error_text=error,
        )

        final = (
            f"{agent_name} response:\\n"
            f"- task_id: {{task_id}}\\n"
            f"- status: {{status}}\\n"
            f"- created_at: {{created_at}}\\n"
            f"- updated_at: {{updated_at}}\\n"
            f"- completed_at: {{completed_at}}\\n"
            f"- output:\\n{{reply}}"
        )
        await event_queue.enqueue_event(new_agent_text_message(final))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise RuntimeError("cancel not supported")
'''


EXEC_TEMPLATE_BASIC_NO_TRACK_MCP = '''from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message

from mcp_layer import MCPClient


class {class_name}(AgentExecutor):
    def __init__(self) -> None:
        self.mcp = MCPClient.from_env()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_text = context.get_user_input() or ""
        mcp_context = await self.mcp.fetch_context(user_text)

        if mcp_context:
            reply = (
                "{agent_name} MCP response:\\n"
                f"{{mcp_context}}"
            )
        else:
            reply = (
                "{agent_name} response:\\n"
                f"- I received: {{user_text}}\\n"
                "- You can customize this in agent_executor.py"
            )
        await event_queue.enqueue_event(new_agent_text_message(reply))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise RuntimeError("cancel not supported")
'''


EXEC_TEMPLATE_OPENAI_NO_TRACK_MCP = '''import os

from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.utils import new_agent_text_message
from openai import AsyncOpenAI

from mcp_layer import MCPClient


class {class_name}(AgentExecutor):
    def __init__(self) -> None:
        self.model = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")
        api_key = os.environ.get("OPENAI_API_KEY", "")
        self.client = AsyncOpenAI(api_key=api_key) if api_key else None
        self.mcp = MCPClient.from_env()

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        user_text = context.get_user_input() or ""
        mcp_context = await self.mcp.fetch_context(user_text)

        if not self.client:
            if mcp_context:
                reply = "MCP response (OpenAI disabled):\\n" + mcp_context
            else:
                reply = "Set OPENAI_API_KEY to enable model responses."
        else:
            try:
                user_input = user_text
                if mcp_context:
                    user_input = (
                        f"User query:\\n{{user_text}}\\n\\n"
                        f"MCP context:\\n{{mcp_context}}\\n\\n"
                        "Use MCP context when relevant and clearly answer the user query."
                    )
                res = await self.client.responses.create(
                    model=self.model,
                    input=[
                        {{"role": "system", "content": "You are {agent_name}."}},
                        {{"role": "user", "content": user_input}},
                    ],
                )
                reply = res.output_text or "(empty model response)"
            except Exception as exc:
                reply = f"OpenAI call failed: {{exc}}"

        await event_queue.enqueue_event(new_agent_text_message(reply))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise RuntimeError("cancel not supported")
'''


MCP_LAYER_TEMPLATE = '''import json
import os
import shlex
import sys

from dataclasses import dataclass
from pathlib import Path
from typing import Any


try:
    from fastmcp import Client
    from fastmcp.client.transports import StdioTransport
except Exception:
    Client = None  # type: ignore[assignment]
    StdioTransport = None  # type: ignore[assignment]


@dataclass
class MCPConfig:
    enabled: bool
    command: str
    args: list[str]
    tool_name: str
    tool_args: dict[str, Any]
    pass_user_query: bool
    cwd: str | None


class MCPClient:
    def __init__(self, config: MCPConfig) -> None:
        self.config = config

    @staticmethod
    def _parse_bool(raw: str | None, default: bool) -> bool:
        if raw is None:
            return default
        return raw.strip().lower() in {{"1", "true", "yes", "y", "on"}}

    @staticmethod
    def _get_env_value(env: dict[str, str], primary: str, fallback: str) -> str:
        return env.get(primary, env.get(fallback, "")).strip()

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "MCPClient":
        env_map = dict(env or os.environ)
        enabled = cls._parse_bool(env_map.get("{agent_env_prefix}_MCP_ENABLED", env_map.get("MCP_ENABLED", "false")), False)
        command = cls._get_env_value(env_map, "{agent_env_prefix}_MCP_SERVER_COMMAND", "MCP_SERVER_COMMAND") or sys.executable

        raw_args = cls._get_env_value(env_map, "{agent_env_prefix}_MCP_SERVER_ARGS", "MCP_SERVER_ARGS")
        if raw_args:
            args = shlex.split(raw_args)
        else:
            default_server = Path(__file__).resolve().with_name("mcp_server.py")
            args = [str(default_server)]

        tool_name = cls._get_env_value(env_map, "{agent_env_prefix}_MCP_TOOL_NAME", "MCP_TOOL_NAME") or "reverse_string"
        raw_tool_args = cls._get_env_value(env_map, "{agent_env_prefix}_MCP_TOOL_ARGS_JSON", "MCP_TOOL_ARGS_JSON")
        tool_args: dict[str, Any] = {{}}
        if raw_tool_args:
            try:
                parsed = json.loads(raw_tool_args)
                if isinstance(parsed, dict):
                    tool_args = parsed
            except Exception:
                tool_args = {{}}

        pass_user_query = cls._parse_bool(
            env_map.get("{agent_env_prefix}_MCP_PASS_USER_QUERY", env_map.get("MCP_PASS_USER_QUERY", "true")),
            True,
        )

        raw_cwd = cls._get_env_value(env_map, "{agent_env_prefix}_MCP_CWD", "MCP_CWD")
        cwd = raw_cwd or None

        return cls(
            MCPConfig(
                enabled=enabled,
                command=command,
                args=args,
                tool_name=tool_name,
                tool_args=tool_args,
                pass_user_query=pass_user_query,
                cwd=cwd,
            )
        )

    async def fetch_context(self, user_query: str) -> str:
        if not self.config.enabled:
            return ""

        if not self.config.command:
            return "MCP is enabled but {agent_env_prefix}_MCP_SERVER_COMMAND is not set."

        if Client is None or StdioTransport is None:
            return "FastMCP is not installed. Install dependency 'fastmcp' to enable MCP calls."

        transport = StdioTransport(command=self.config.command, args=self.config.args, cwd=self.config.cwd)
        client = Client(transport)

        try:
            async with client:
                tool_name = self.config.tool_name
                if not tool_name:
                    tools = await client.list_tools()
                    names = [str(getattr(tool, "name", "")) for tool in tools]
                    names = [name for name in names if name]
                    if not names:
                        return "FastMCP connected, but no tools were exposed by the server."
                    return "Available MCP tools: " + ", ".join(names)

                args = dict(self.config.tool_args)
                if self.config.pass_user_query:
                    args.setdefault("text", user_query)

                result = await client.call_tool(tool_name, args)
                text = getattr(result, "text", None)
                if isinstance(text, str) and text.strip():
                    return text.strip()
                return str(result)
        except Exception as exc:
            return f"MCP call failed: {{exc}}"
'''


MCP_SERVER_TEMPLATE = '''from fastmcp import FastMCP


mcp = FastMCP(name="{agent_name} MCP")


@mcp.tool
def reverse_string(text: str) -> str:
    'Return the input text reversed.'
    return text[::-1]


@mcp.tool
def word_count(text: str) -> dict[str, int]:
    'Return word and character counts for the input text.'
    words = [word for word in text.split() if word]
    return {{"words": len(words), "characters": len(text)}}


# Add more tools by copying the pattern above.
# Keep tool names stable because agents may call them directly.


if __name__ == "__main__":
    mcp.run()
'''


MCP_SKILL_TEMPLATE = '''        AgentSkill(
            id="{agent_id}_mcp_tools",
            name="{agent_name} MCP Tool Access",
            description=(
                "Optionally connects to an MCP server from {agent_name} executor to fetch tool context "
                "before generating or returning responses."
            ),
            tags=["{agent_id}", "mcp", "tools", "retrieval"],
            examples=[
                "run {agent_id} with MCP context",
                "list available MCP tools through {agent_id}",
            ],
        ),'''


MCP_SETUP_BLOCK = '''

## MCP (Optional)

This agent was scaffolded with MCP support. Files:
- `mcp_server.py` (FastMCP server with example tools)
- `mcp_layer.py` (client wrapper used by the executor)

Enable MCP by setting:
- `{agent_env_prefix}_MCP_ENABLED=true`
- `{agent_env_prefix}_MCP_TOOL_NAME=reverse_string`

Optional overrides:
- `{agent_env_prefix}_MCP_SERVER_COMMAND` (default: `python3`)
- `{agent_env_prefix}_MCP_SERVER_ARGS` (default: `mcp_server.py`)
- `{agent_env_prefix}_MCP_TOOL_ARGS_JSON` (JSON object passed to tool call)
- `{agent_env_prefix}_MCP_PASS_USER_QUERY` (default: true)
- `{agent_env_prefix}_MCP_CWD` (optional working directory)

Example:

```bash
{agent_env_prefix}_MCP_ENABLED=true
{agent_env_prefix}_MCP_TOOL_NAME=reverse_string
```

To connect to an external MCP server, set `{agent_env_prefix}_MCP_SERVER_COMMAND` and `{agent_env_prefix}_MCP_SERVER_ARGS`.
'''


SETUP_TEMPLATE = '''# {agent_name}

This agent was scaffolded with `ecosystem/create_agent.py`.

## Run

```bash
python3 app.py
```

## Endpoints

- Card: `http://127.0.0.1:{port}/.well-known/agent-card.json`

## Optional Environment Variables

- `OPENAI_API_KEY` (needed when created with `--with-openai`)
- `OPENAI_MODEL` (default: `gpt-4.1-mini`)
- `{agent_env_url_key}` (agent card base URL used by the ecosystem UI)
- `{agent_env_url_key_alt}` (alternate URL key format; either key works)
- `{agent_env_db_key}` (SQLite path for this agent's task DB)
{mcp_setup_block}

## Env Resolution Order

At startup, this agent loads env files in this order:
1. `agent_{agent_id}/.env` (highest file priority)
2. project root `.env` (fallback for missing keys)
3. already-exported process env vars (highest overall priority)

Use this to keep agent-specific overrides local while still inheriting shared root config.

## Skill Blueprint (What To Define Clearly)

When adding or editing skills in `app.py`, define each skill with:
- `id`: stable machine-friendly identifier (`{agent_id}_...`)
- `name`: clear operator-facing name
- `description`: task scope, expected input shape, and output contract
- `tags`: capability keywords (`a2a`, domain, execution type, storage)
- `examples`: realistic prompts/calls that match your integration flow

Recommended skill split:
1. Execution skill:
   - what the agent does end-to-end
   - required/optional input fields
   - terminal output format
2. Tracking/observability skill:
   - task states (`queued`, `in_progress`, `completed`, `failed`)
   - timestamps and DB fields exposed
3. Integration contract skill:
   - expected `action` values
   - response payload keys and error behavior

Do not keep skill descriptions generic; document exact contracts used by your executor.

## AgentSkill Parameter Reference

`AgentSkill(...)` fields used in this project:
- `id`:
  - unique stable identifier for the skill
  - should not change frequently, because clients may depend on it
  - recommended format: `{agent_id}_<capability>`
- `name`:
  - short human-readable title
  - shown in agent cards and UI lists
- `description`:
  - explain exact behavior, expected input, and output/result contract
  - write this as an operator-facing mini spec, not a generic sentence
- `tags`:
  - searchable labels for discovery/routing
  - include domain (`finance`, `story`), behavior (`execute`, `tracking`) and protocol (`a2a`) where relevant
- `examples`:
  - concrete sample requests matching real usage
  - make examples realistic so users know how to call the skill correctly

Practical rule:
- if a new engineer reads only `id/name/description/tags/examples`, they should know when and how to use the skill.

## Server -> DB Flow (How It Works)

When you run `python3 app.py`, the sequence is:

1. `app.py` builds the A2A server and creates `{class_name}()`.
2. In `agent_executor.py`, `__init__` sets `self.db_path` from `{agent_env_db_key}`.
3. `__init__` calls `_init_db()`.
4. `_init_db()` runs `CREATE TABLE IF NOT EXISTS {agent_id}_tasks (...)`.
5. On each incoming request, `execute(...)`:
   - writes a new DB row (`_insert_task`) with `created_at`/`updated_at`
   - performs processing (LLM or business logic)
   - updates row status + `completed_at` (`_complete_task` or `_finish_task`)
   - returns response to caller

This means DB file/table are auto-created the first time the executor starts.

## Current Table

Default table name: `{agent_id}_tasks`

Typical columns:
- `id` primary key
- `input_text`
- `status`
- `result_text` (and `error_text` for OpenAI template)
- `created_at`, `updated_at`, `completed_at`

## Verify DB Quickly

```bash
python3 app.py
python3 - <<'PY'
import sqlite3
conn = sqlite3.connect('{agent_id}_tasks.db')
print(conn.execute("PRAGMA table_info({agent_id}_tasks)").fetchall())
conn.close()
PY
```

If you set `{agent_env_db_key}` in `.env`, check that custom path instead.

## How To Modify Safely

1. Add new columns:
   - update `_init_db()` DDL for fresh DBs
   - for existing DBs, add a migration step (check `PRAGMA table_info`, then `ALTER TABLE`)
2. Add new statuses:
   - update status transitions in `execute(...)`
   - set `completed_at` only for terminal statuses (`completed`, `failed`)
3. Add domain payload fields:
   - store raw payload JSON in a new `payload_json` column for debugging
4. Keep writes atomic:
   - use `with sqlite3.connect(...) as conn:` around each insert/update block

## Example: Add `payload_json`

In `_init_db()`:

```sql
payload_json TEXT
```

In insert:

```python
conn.execute(
    "INSERT INTO {agent_id}_tasks (input_text, status, payload_json, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
    (input_text, "in_progress", raw_json, now, now),
)
```

## Recommended Next Upgrade

If you want production-grade structure, move DB logic into:
- `agent_{agent_id}/task_repository.py` (all SQL only)
- `agent_executor.py` (business logic only)

This keeps agent behavior easier to evolve and test.
'''


def _prompt_if_missing(value: str | None, label: str, default: str) -> str:
    if value:
        return value
    raw = input(f"{label} [{default}]: ").strip()
    return raw or default


def _prompt_bool_if_none(value: bool | None, label: str, default: bool) -> bool:
    if value is not None:
        return value
    hint = "Y/n" if default else "y/N"
    raw = input(f"{label} ({hint}): ").strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a new A2A agent scaffold.")
    parser.add_argument("name", nargs="?", help="Agent name, e.g. gamma")
    parser.add_argument("--port", type=int, help="Port for the agent app (default: 8103)")
    parser.add_argument(
        "--with-openai",
        action="store_true",
        help="Create executor template that calls OpenAI",
    )
    parser.add_argument(
        "--no-task-tracking",
        action="store_true",
        help="Disable SQLite task tracking template",
    )
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Include MCP client/server scaffold and MCP-aware executor template",
    )
    args = parser.parse_args()

    name = _prompt_if_missing(args.name, "Agent name", "gamma")
    port_text = _prompt_if_missing(str(args.port) if args.port is not None else None, "Port", "8103")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise SystemExit(f"Invalid port: {port_text}") from exc

    with_openai = args.with_openai
    if not args.with_openai and args.name is None:
        with_openai = _prompt_bool_if_none(None, "Use OpenAI template", False)

    with_mcp = args.mcp
    task_tracking = not args.no_task_tracking

    agent_id = name.strip().lower().replace(" ", "_")
    folder = Path(f"agent_{agent_id}")
    if folder.exists():
        raise SystemExit(f"Folder already exists: {folder}")

    class_name = "".join(part.capitalize() for part in agent_id.split("_")) + "AgentExecutor"
    agent_name = " ".join(part.capitalize() for part in agent_id.split("_")) + " Agent"
    agent_env_db_key = f"{agent_id.upper()}_DB_PATH"
    agent_env_url_key = f"AGENT_{agent_id.upper()}_URL"
    agent_env_url_key_alt = f"{agent_id.upper()}_AGENT_URL"
    agent_env_prefix = agent_id.upper()

    folder.mkdir(parents=True, exist_ok=False)

    mcp_skill_block = ""
    mcp_setup_block = ""
    if with_mcp:
        mcp_skill_block = MCP_SKILL_TEMPLATE.format(agent_id=agent_id, agent_name=agent_name)
        mcp_setup_block = MCP_SETUP_BLOCK.format(agent_env_prefix=agent_env_prefix, agent_id=agent_id)

    app_py = APP_TEMPLATE.format(
        class_name=class_name,
        agent_id=agent_id,
        agent_name=agent_name,
        port=port,
        mcp_skill_block=mcp_skill_block,
    )

    if with_mcp:
        if task_tracking and with_openai:
            exec_template = EXEC_TEMPLATE_OPENAI_MCP
        elif task_tracking and not with_openai:
            exec_template = EXEC_TEMPLATE_BASIC_MCP
        elif not task_tracking and with_openai:
            exec_template = EXEC_TEMPLATE_OPENAI_NO_TRACK_MCP
        else:
            exec_template = EXEC_TEMPLATE_BASIC_NO_TRACK_MCP
    else:
        if task_tracking and with_openai:
            exec_template = EXEC_TEMPLATE_OPENAI
        elif task_tracking and not with_openai:
            exec_template = EXEC_TEMPLATE_BASIC
        elif not task_tracking and with_openai:
            exec_template = EXEC_TEMPLATE_OPENAI_NO_TRACK
        else:
            exec_template = EXEC_TEMPLATE_BASIC_NO_TRACK

    exec_py = exec_template.format(
        class_name=class_name,
        agent_name=agent_name,
        agent_id=agent_id,
        agent_env_db_key=agent_env_db_key,
    )

    setup_md = SETUP_TEMPLATE.format(
        agent_name=agent_name,
        port=port,
        agent_env_db_key=agent_env_db_key,
        agent_env_url_key=agent_env_url_key,
        agent_env_url_key_alt=agent_env_url_key_alt,
        class_name=class_name,
        agent_id=agent_id,
        mcp_setup_block=mcp_setup_block,
    )

    (folder / "app.py").write_text(app_py, encoding="utf-8")
    (folder / "agent_executor.py").write_text(exec_py, encoding="utf-8")
    (folder / "AGENT_SETUP.md").write_text(setup_md, encoding="utf-8")

    print(f"Created {folder}/app.py")
    print(f"Created {folder}/agent_executor.py")
    print(f"Created {folder}/AGENT_SETUP.md")
    if with_mcp:
        mcp_layer_py = MCP_LAYER_TEMPLATE.format(agent_env_prefix=agent_env_prefix)
        mcp_server_py = MCP_SERVER_TEMPLATE.format(agent_name=agent_name)
        (folder / "mcp_layer.py").write_text(mcp_layer_py, encoding="utf-8")
        (folder / "mcp_server.py").write_text(mcp_server_py, encoding="utf-8")
        print(f"Created {folder}/mcp_layer.py")
        print(f"Created {folder}/mcp_server.py")

    print("\nNext steps:")
    print(f"1) Run: python3 {folder}/app.py")
    print(f"2) Check card: curl -s http://127.0.0.1:{port}/.well-known/agent-card.json")
    print("3) Run UI: python3 ecosystem/ui_server.py")
    print("4) Open http://127.0.0.1:8200 and verify Agent Registry Detection")
    print("5) Add agent URL in .env (either key works):")
    print(f"   - {agent_env_url_key}=http://127.0.0.1:{port}")
    print(f"   - {agent_env_url_key_alt}=http://127.0.0.1:{port}")
    next_step = 6
    if with_mcp:
        print(f"{next_step}) Optional: enable MCP (see {folder}/AGENT_SETUP.md)")
        next_step += 1
    if task_tracking:
        print(f"{next_step}) Optional: set {agent_env_db_key}=<path> in .env")


if __name__ == "__main__":
    main()
