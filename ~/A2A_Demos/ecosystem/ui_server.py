import asyncio
import json
import logging
import os
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import re

from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

import httpx
import uvicorn

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from a2a.client import A2ACardResolver, A2AClient
from a2a.types import Message, MessageSendParams, Part, Role, SendMessageRequest, TextPart
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.staticfiles import StaticFiles
from starlette.websockets import WebSocket


ROOT = ROOT_DIR
STATIC_DIR = ROOT / "ecosystem" / "static"

LOGGER = logging.getLogger("ecosystem-ui")
ENV_FILE = ROOT / ".env"
ECOSYSTEM_DB_FILE = ROOT / "ecosystem" / "ecosystem.db"


def load_dotenv(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        out[key.strip()] = value.strip()
    return out


def mask_value(key: str, value: str) -> str:
    if "KEY" not in key and "TOKEN" not in key and "SECRET" not in key:
        return value
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}...{value[-4:]}"


@dataclass
class ManagedProcess:
    name: str
    cwd: Path
    command: list[str]
    env: dict[str, str]
    process: subprocess.Popen[str] | None = None
    _thread: threading.Thread | None = None

    def start(self, line_handler: Callable[[str, str], None]) -> None:
        self.process = subprocess.Popen(
            self.command,
            cwd=self.cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            env=self.env,
        )

        def _reader() -> None:
            assert self.process is not None and self.process.stdout is not None
            for line in self.process.stdout:
                line_handler(self.name, line.rstrip("\n"))

        self._thread = threading.Thread(target=_reader, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if not self.process:
            return

        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)


def parse_port_from_app(app_path: Path) -> int | None:
    if not app_path.exists():
        return None
    text = app_path.read_text(encoding="utf-8")
    match = re.search(r"port\s*=\s*(\d+)", text)
    return int(match.group(1)) if match else None


def extract_last_text(response: object) -> str:
    if not hasattr(response, "model_dump"):
        return ""
    payload = response.model_dump(mode="json", exclude_none=True)

    out: list[str] = []

    def collect(value: object) -> None:
        if isinstance(value, dict):
            if value.get("kind") == "text" and isinstance(value.get("text"), str):
                out.append(value["text"])
            for item in value.values():
                collect(item)
        elif isinstance(value, list):
            for item in value:
                collect(item)

    collect(payload)
    return out[-1] if out else ""


async def wait_for_endpoint(url: str, timeout_seconds: int = 30) -> None:
    deadline = asyncio.get_event_loop().time() + timeout_seconds
    path = f"{url}{AGENT_CARD_WELL_KNOWN_PATH}"
    async with httpx.AsyncClient(timeout=2.0) as client:
        while True:
            try:
                response = await client.get(path)
                if response.status_code == 200:
                    return
            except Exception:
                pass

            if asyncio.get_event_loop().time() > deadline:
                raise TimeoutError(f"Timed out waiting for {path}")
            await asyncio.sleep(0.3)


class Orchestrator:
    def __init__(self) -> None:
        self.loop: asyncio.AbstractEventLoop | None = None
        self.events: deque[dict[str, Any]] = deque(maxlen=800)
        self.subscribers: set[asyncio.Queue[dict[str, Any]]] = set()
        self.task_runs: dict[str, dict[str, Any]] = {}
        self.active_run_ids: set[str] = set()
        self.managed_procs: dict[str, ManagedProcess] = {}
        self.effective_config: list[dict[str, str]] = []
        self.agent_catalog: list[dict[str, Any]] = []
        self.last_detected_agents: set[str] = set()
        self.runtime_env: dict[str, str] = {}
        self.entry_agent_id: str = ""
        self.entry_agent_url: str = ""
        self.ecosystem_db_path: Path = ECOSYSTEM_DB_FILE

    def _bool_from_env(self, value: str | None, default: bool) -> bool:
        if value is None:
            return default
        return value.strip().lower() in {"1", "true", "yes", "y", "on"}

    def _init_ecosystem_db(self) -> None:
        self.ecosystem_db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.ecosystem_db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS poll_config (
                    caller_agent TEXT NOT NULL,
                    target_agent TEXT NOT NULL,
                    poll_interval_seconds REAL NOT NULL,
                    max_poll_attempts INTEGER NOT NULL,
                    updated_at REAL NOT NULL,
                    PRIMARY KEY (caller_agent, target_agent)
                )
                """
            )
            conn.commit()

    def upsert_poll_config(
        self,
        caller_agent: str,
        target_agent: str,
        poll_interval_seconds: float,
        max_poll_attempts: int,
    ) -> None:
        caller = caller_agent.strip().lower()
        target = target_agent.strip().lower()
        if not caller or not target:
            raise ValueError("caller_agent and target_agent are required")
        with sqlite3.connect(self.ecosystem_db_path) as conn:
            conn.execute(
                """
                INSERT INTO poll_config (
                    caller_agent, target_agent, poll_interval_seconds, max_poll_attempts, updated_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(caller_agent, target_agent) DO UPDATE SET
                    poll_interval_seconds = excluded.poll_interval_seconds,
                    max_poll_attempts = excluded.max_poll_attempts,
                    updated_at = excluded.updated_at
                """,
                (
                    caller,
                    target,
                    float(poll_interval_seconds),
                    int(max_poll_attempts),
                    time.time(),
                ),
            )
            conn.commit()

    def get_poll_config_snapshot(self) -> dict[str, Any]:
        default_interval = 20.0
        default_attempts = 5
        rows: list[dict[str, Any]] = []
        if self.ecosystem_db_path.exists():
            with sqlite3.connect(self.ecosystem_db_path) as conn:
                conn.row_factory = sqlite3.Row
                fetched = conn.execute(
                    """
                    SELECT caller_agent, target_agent, poll_interval_seconds, max_poll_attempts, updated_at
                    FROM poll_config
                    ORDER BY caller_agent ASC, target_agent ASC
                    """
                ).fetchall()
                rows = [dict(row) for row in fetched]

        by_pair = {
            (str(row.get("caller_agent", "")).lower(), str(row.get("target_agent", "")).lower()): row for row in rows
        }
        known_agents = sorted(
            {
                str(item.get("id", "")).lower()
                for item in self.agent_catalog
                if str(item.get("id", "")).strip()
            }
        )
        if not known_agents:
            known_agents = sorted(
                {
                    str(row.get("caller_agent", "")).lower()
                    for row in rows
                    if str(row.get("caller_agent", "")).strip()
                }
                | {
                    str(row.get("target_agent", "")).lower()
                    for row in rows
                    if str(row.get("target_agent", "")).strip()
                }
            )
        effective_rows: list[dict[str, Any]] = []
        for caller in known_agents:
            for target in known_agents:
                if caller == target:
                    continue
                existing = by_pair.get((caller, target))
                effective_rows.append(
                    {
                        "caller_agent": caller,
                        "target_agent": target,
                        "poll_interval_seconds": (
                            float(existing.get("poll_interval_seconds", default_interval)) if existing else default_interval
                        ),
                        "max_poll_attempts": int(existing.get("max_poll_attempts", default_attempts)) if existing else default_attempts,
                        "updated_at": existing.get("updated_at") if existing else None,
                        "is_custom": bool(existing),
                    }
                )

        for row in rows:
            pair = (str(row.get("caller_agent", "")).lower(), str(row.get("target_agent", "")).lower())
            if not any(
                str(item.get("caller_agent", "")).lower() == pair[0]
                and str(item.get("target_agent", "")).lower() == pair[1]
                for item in effective_rows
            ):
                effective_rows.append({**row, "is_custom": True})

        effective_rows.sort(
            key=lambda x: (
                str(x.get("caller_agent", "")),
                str(x.get("target_agent", "")),
            )
        )
        return {
            "entry_agent_id": self.entry_agent_id,
            "agents": known_agents,
            "default_poll_interval_seconds": default_interval,
            "default_max_poll_attempts": default_attempts,
            "db_path": str(self.ecosystem_db_path),
            "rows": effective_rows,
            "timestamp": time.time(),
        }

    def _discover_agents_from_env(self, env_map: dict[str, str]) -> list[dict[str, Any]]:
        by_id: dict[str, dict[str, Any]] = {}

        def resolve_db_path(raw_path: str, agent_path: str) -> str:
            path = Path(raw_path)
            if path.is_absolute():
                return str(path)
            # Single filename -> agent-local DB file.
            if len(path.parts) == 1:
                return str((Path(agent_path) / path).resolve())
            # Nested relative path -> treat as project-root-relative.
            return str((ROOT / path).resolve())

        def get_row(agent_id: str) -> dict[str, Any]:
            key = agent_id.lower()
            if key not in by_id:
                by_id[key] = {
                    "id": key,
                    "folder": f"agent_{key}",
                    "path": str((ROOT / f"agent_{key}").resolve()),
                    "url": "",
                    "db_path": "",
                    "db_table": f"{key}_tasks",
                    "managed": False,
                    # Keep startup behavior uniform across all agents.
                    # Any agent starts only when explicitly configured via *_AUTOSTART=true.
                    "autostart": False,
                    "has_app": False,
                    "port": None,
                }
            return by_id[key]

        for raw_key, raw_val in env_map.items():
            key = raw_key.strip().upper()
            value = raw_val.strip().strip('"').strip("'")

            match = re.fullmatch(r"AGENT_([A-Z0-9_]+)_URL", key)
            if match:
                row = get_row(match.group(1).lower())
                row["url"] = value
                continue

            match = re.fullmatch(r"([A-Z0-9_]+)_AGENT_URL", key)
            if match:
                row = get_row(match.group(1).lower())
                row["url"] = value
                continue

            match = re.fullmatch(r"AGENT_([A-Z0-9_]+)_PATH", key)
            if match:
                row = get_row(match.group(1).lower())
                path = Path(value)
                if not path.is_absolute():
                    path = (ROOT / path).resolve()
                row["path"] = str(path)
                row["folder"] = path.name
                continue

            match = re.fullmatch(r"([A-Z0-9_]+)_AGENT_PATH", key)
            if match:
                row = get_row(match.group(1).lower())
                path = Path(value)
                if not path.is_absolute():
                    path = (ROOT / path).resolve()
                row["path"] = str(path)
                row["folder"] = path.name
                continue

            match = re.fullmatch(r"AGENT_([A-Z0-9_]+)_AUTOSTART", key)
            if match:
                row = get_row(match.group(1).lower())
                row["autostart"] = self._bool_from_env(value, row["autostart"])
                continue

            match = re.fullmatch(r"([A-Z0-9_]+)_AGENT_AUTOSTART", key)
            if match:
                row = get_row(match.group(1).lower())
                row["autostart"] = self._bool_from_env(value, row["autostart"])
                continue

            match = re.fullmatch(r"AGENT_([A-Z0-9_]+)_DB_PATH", key)
            if match:
                row = get_row(match.group(1).lower())
                row["db_path"] = value
                continue

            match = re.fullmatch(r"([A-Z0-9_]+)_DB_PATH", key)
            if match:
                row = get_row(match.group(1).lower())
                row["db_path"] = value
                continue

        for path in sorted(ROOT.glob("agent_*")):
            if not path.is_dir():
                continue
            app_path = path / "app.py"
            if not app_path.exists():
                continue
            agent_id = path.name.replace("agent_", "").lower()
            row = get_row(agent_id)
            row["folder"] = path.name
            row["path"] = str(path.resolve())
            if not row.get("db_path"):
                row["db_path"] = str((path / f"{agent_id}_tasks.db").resolve())

        out: list[dict[str, Any]] = []
        for _, row in sorted(by_id.items(), key=lambda x: x[0]):
            app_path = Path(row["path"]) / "app.py"
            row["has_app"] = app_path.exists()
            row["managed"] = row["has_app"]
            if row.get("db_path"):
                row["db_path"] = resolve_db_path(str(row["db_path"]), str(row["path"]))
            else:
                row["db_path"] = str((Path(row["path"]) / f"{row['id']}_tasks.db").resolve())
            if row["has_app"]:
                row["port"] = parse_port_from_app(app_path)
            if not row["url"] and row["port"]:
                row["url"] = f"http://127.0.0.1:{row['port']}"
            out.append(row)
        return out

    def _event_kind(self, msg: str) -> str:
        if re.search(r"[A-Z]+_TO_[A-Z]+_SEND_MESSAGE_(REQUEST|RESPONSE)", msg):
            return "transfer"
        if re.search(r"[A-Z]+_SENDING_RESPONSE_TEXT", msg):
            return "task"
        if re.search(r"[A-Z]+_FINAL_RESPONSE_TEXT", msg):
            return "task"
        if "OPENAI" in msg:
            return "llm"
        if "ERROR" in msg or "Traceback" in msg:
            return "error"
        return "log"

    def _extract_links(self, message: str) -> list[dict[str, str]]:
        links: list[dict[str, str]] = []
        match = re.search(r"([A-Z]+)_TO_([A-Z]+)_SEND_MESSAGE_(REQUEST|RESPONSE)", message)
        if match:
            links.append(
                {
                    "from": match.group(1).lower(),
                    "to": match.group(2).lower(),
                    "type": match.group(3).lower(),
                }
            )
        sender_match = re.search(r"([A-Z]+)_SENDING_RESPONSE_TEXT", message)
        if sender_match:
            sender = sender_match.group(1).lower()
            links.append({"from": sender, "to": f"{sender}_db", "type": "db_write"})
            if self.entry_agent_id and sender != self.entry_agent_id:
                links.append({"from": f"{sender}_db", "to": self.entry_agent_id, "type": "db_status"})
        final_match = re.search(r"([A-Z]+)_FINAL_RESPONSE_TEXT", message)
        if final_match:
            sender = final_match.group(1).lower()
            links.append({"from": sender, "to": f"{sender}_db", "type": "db_write"})
            links.append({"from": sender, "to": "user", "type": "final"})
        if message.startswith("New task submitted:"):
            links.append({"from": "user", "to": self.entry_agent_id or "agent", "type": "submit"})
        return links

    def _resolve_entry_agent(self, env_map: dict[str, str]) -> tuple[str, str]:
        preferred = str(env_map.get("ORCH_ENTRY_AGENT", "") or env_map.get("ECOSYSTEM_ENTRY_AGENT", "")).strip().lower()
        by_id = {str(item.get("id", "")).lower(): item for item in self.agent_catalog}
        if preferred:
            preferred_row = by_id.get(preferred)
            if preferred_row and preferred_row.get("url"):
                return preferred, str(preferred_row.get("url", ""))

        candidates = sorted(
            [item for item in self.agent_catalog if str(item.get("url", "")).strip()],
            key=lambda x: str(x.get("id", "")),
        )
        if not candidates:
            return "", ""
        first = candidates[0]
        return str(first.get("id", "")).lower(), str(first.get("url", ""))

    def _add_event(
        self, source: str, message: str, kind: str | None = None, run_id: str | None = None
    ) -> None:
        links = self._extract_links(message)
        event = {
            "ts": time.time(),
            "source": source,
            "kind": kind or self._event_kind(message),
            "message": message,
            "run_id": run_id,
            "links": links,
        }
        self.events.append(event)
        if run_id and run_id in self.task_runs:
            run = self.task_runs[run_id]
            events = run.setdefault("events", [])
            events.append(event)
            if len(events) > 500:
                del events[: len(events) - 500]
            run["updated_at"] = time.time()

        if self.loop is None:
            return

        for queue in list(self.subscribers):
            self.loop.call_soon_threadsafe(queue.put_nowait, event)

    def _line_handler(self, source: str, line: str) -> None:
        tagged = f"[{source}] {line}"
        LOGGER.info(tagged)
        run_id: str | None = None
        if len(self.active_run_ids) == 1:
            run_id = next(iter(self.active_run_ids))
        self._add_event(source, line, run_id=run_id)

    async def startup(self) -> None:
        self.loop = asyncio.get_event_loop()

        dotenv_values = load_dotenv(ENV_FILE)
        base_env = os.environ.copy()
        for key, value in dotenv_values.items():
            base_env.setdefault(key, value)
        base_env["PYTHONUNBUFFERED"] = "1"

        defaults = {
            "OPENAI_MODEL": "gpt-4.1-mini",
            "ORCH_ENTRY_AGENT": "",
            "ECOSYSTEM_DB_PATH": str(ECOSYSTEM_DB_FILE.resolve()),
        }
        tracked_keys = [
            "OPENAI_API_KEY",
            "OPENAI_MODEL",
            "ORCH_ENTRY_AGENT",
            "ECOSYSTEM_ENTRY_AGENT",
            "ECOSYSTEM_DB_PATH",
        ]
        dynamic_agent_keys = sorted(
            {
                key
                for key in set(base_env.keys()) | set(dotenv_values.keys())
                if "_AGENT_" in key.upper()
                or key.upper().startswith("AGENT_")
                or key.upper().endswith("_DB_PATH")
                or "_POLL_" in key.upper()
                or key.upper().endswith("_MAX_POLL_ATTEMPTS")
                or key.upper().endswith("_TASK_DELAY_SECONDS")
            }
        )
        for key in dynamic_agent_keys:
            if key not in tracked_keys:
                tracked_keys.append(key)
        self.effective_config = []
        for key in tracked_keys:
            if key in os.environ:
                source = "env"
                value = os.environ[key]
            elif key in dotenv_values:
                source = ".env"
                value = dotenv_values[key]
            else:
                source = "default"
                value = defaults.get(key, "")
            if source == "default" and value:
                base_env.setdefault(key, value)
            self.effective_config.append(
                {
                    "key": key,
                    "source": source,
                    "value": mask_value(key, value),
                }
            )

        self.runtime_env = dict(base_env)
        self.ecosystem_db_path = Path(
            str(base_env.get("ECOSYSTEM_DB_PATH", str(ECOSYSTEM_DB_FILE.resolve())))
        ).resolve()
        self._init_ecosystem_db()
        self.agent_catalog = self._discover_agents_from_env(base_env)
        self.entry_agent_id, self.entry_agent_url = self._resolve_entry_agent(base_env)

        # Keep DB path keys visible in config even when implicit defaults are used.
        for item in self.agent_catalog:
            db_key = f"{str(item.get('id', '')).upper()}_DB_PATH"
            if db_key and db_key not in tracked_keys:
                tracked_keys.append(db_key)
                db_path = str(item.get("db_path", ""))
                self.effective_config.append(
                    {
                        "key": db_key,
                        "source": (
                            "env"
                            if db_key in os.environ
                            else ".env"
                            if db_key in dotenv_values
                            else "default"
                        ),
                        "value": db_path,
                    }
                )

        start_order = sorted(
            [x for x in self.agent_catalog if x.get("managed") and x.get("autostart")],
            key=lambda x: str(x.get("id", "")),
        )
        self.managed_procs = {}
        for item in start_order:
            cwd = Path(str(item.get("path", "")))
            if not (cwd / "app.py").exists():
                continue

            env_for_agent = dict(base_env)
            agent_dotenv = load_dotenv(cwd / ".env")
            for key, value in agent_dotenv.items():
                if key not in os.environ:
                    env_for_agent[key] = value

            proc = ManagedProcess(
                name=str(item["id"]),
                cwd=cwd,
                command=[sys.executable, "-u", "app.py"],
                env=env_for_agent,
            )
            self._add_event("system", f"Starting {item['id']} agent", "task")
            proc.start(self._line_handler)
            self.managed_procs[str(item["id"])] = proc

            agent_url = str(item.get("url", ""))
            if agent_url:
                await wait_for_endpoint(agent_url)
                self._add_event("system", f"{item['id']} is ready", "task")
        self.entry_agent_id, self.entry_agent_url = self._resolve_entry_agent(base_env)

    async def shutdown(self) -> None:
        self._add_event("system", "Stopping agents", "task")
        for proc in self.managed_procs.values():
            proc.stop()

    async def agents_snapshot(self) -> dict[str, Any]:
        if not self.agent_catalog:
            self.agent_catalog = self._discover_agents_from_env(os.environ)

        statuses: list[dict[str, Any]] = []
        detected_count = 0
        detected_ids: set[str] = set()
        async with httpx.AsyncClient(timeout=2.5) as client:
            for item in self.agent_catalog:
                detected = False
                card_name = ""
                card_path = f"{item['url']}{AGENT_CARD_WELL_KNOWN_PATH}" if item["url"] else ""
                if card_path:
                    try:
                        res = await client.get(card_path)
                        if res.status_code == 200:
                            detected = True
                            data = res.json()
                            if isinstance(data, dict):
                                card_name = str(data.get("name", ""))
                    except Exception:
                        detected = False

                process_status = "not_managed"
                proc = self.managed_procs.get(str(item["id"]).lower())
                if proc and proc.process:
                    process_status = "running" if proc.process.poll() is None else "stopped"
                elif item.get("managed"):
                    # Managed-capable agent not launched by this UI process.
                    # If endpoint is live, treat it as running (externally started).
                    process_status = "running" if detected else "stopped"

                if detected:
                    detected_count += 1
                    detected_ids.add(str(item["id"]).lower())

                statuses.append(
                    {
                        **item,
                        "detected": detected,
                        "card_name": card_name,
                        "process_status": process_status,
                    }
                )

        self.last_detected_agents = detected_ids
        return {
            "agents": statuses,
            "total_added": len(statuses),
            "detected": detected_count,
            "undetected": max(0, len(statuses) - detected_count),
            "timestamp": time.time(),
        }

    async def submit_user_task(self, text: str) -> str:
        run_id = uuid4().hex
        if not self.entry_agent_url:
            self.entry_agent_id, self.entry_agent_url = self._resolve_entry_agent(self.runtime_env or os.environ)
        self.task_runs[run_id] = {
            "id": run_id,
            "input": text,
            "status": "running",
            "result": "",
            "entry_agent": self.entry_agent_id,
            "created_at": time.time(),
            "updated_at": time.time(),
            "events": [],
        }
        self._add_event("user", f"New task submitted: {text}", "task", run_id=run_id)
        asyncio.create_task(self._run_task(run_id, text))
        return run_id

    async def _run_task(self, run_id: str, text: str) -> None:
        self.active_run_ids.add(run_id)
        try:
            if not self.entry_agent_url:
                raise RuntimeError("No entry agent URL found. Set ORCH_ENTRY_AGENT or configure at least one *_AGENT_URL.")

            async with httpx.AsyncClient(timeout=60.0) as httpx_client:
                entry_resolver = A2ACardResolver(httpx_client=httpx_client, base_url=self.entry_agent_url)
                entry_card = await entry_resolver.get_agent_card()
                client = A2AClient(httpx_client=httpx_client, agent_card=entry_card)

                send_params = MessageSendParams(
                    message=Message(
                        role=Role.user,
                        parts=[Part(TextPart(text=text))],
                        message_id=uuid4().hex,
                    )
                )
                request = SendMessageRequest(id=str(uuid4()), params=send_params)
                self._add_event(
                    "user",
                    (
                        f"USER_TO_{self.entry_agent_id.upper()}_SEND_MESSAGE_REQUEST="
                        f"{request.model_dump_json(indent=2, exclude_none=True)}"
                    ),
                    "transfer",
                    run_id=run_id,
                )

                response = await client.send_message(request)
                response_text = extract_last_text(response)
                self.task_runs[run_id].update(
                    {
                        "status": "completed",
                        "result": response_text,
                        "updated_at": time.time(),
                    }
                )
                self._add_event(
                    "user",
                    (
                        f"{self.entry_agent_id.upper()}_TO_USER_SEND_MESSAGE_RESPONSE="
                        f"{response.model_dump_json(indent=2, exclude_none=True)}"
                    ),
                    "transfer",
                    run_id=run_id,
                )
        except Exception as exc:
            self.task_runs[run_id].update(
                {
                    "status": "failed",
                    "result": str(exc),
                    "updated_at": time.time(),
                }
            )
            self._add_event("system", f"Task execution failed: {exc}", "error", run_id=run_id)
        finally:
            self.active_run_ids.discard(run_id)

    def get_task_run(self, run_id: str) -> dict[str, Any] | None:
        return self.task_runs.get(run_id)

    def list_sessions(self) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for run in self.task_runs.values():
            rows.append(
                {
                    "id": run["id"],
                    "input": run.get("input", ""),
                    "status": run.get("status", "unknown"),
                    "created_at": run.get("created_at"),
                    "updated_at": run.get("updated_at"),
                    "event_count": len(run.get("events", [])),
                }
            )
        rows.sort(key=lambda x: float(x.get("created_at") or 0), reverse=True)
        return rows

    def session_graph(self, run_id: str, detected_agents: set[str]) -> dict[str, Any]:
        run = self.task_runs.get(run_id)
        if not run:
            return {"nodes": [], "edges": [], "events": []}

        events = list(run.get("events", []))
        detected = {x.lower() for x in detected_agents}
        agent_db_nodes = {f"{agent}_db" for agent in detected}
        nodes: set[str] = {"user"} | detected | agent_db_nodes
        edge_counts: dict[tuple[str, str, str], int] = {}

        for event in events:
            for link in event.get("links", []):
                from_id = str(link.get("from", "")).lower()
                to_id = str(link.get("to", "")).lower()
                link_type = str(link.get("type", "link")).lower()
                if not from_id or not to_id:
                    continue
                if from_id not in {"user"} and from_id not in detected and from_id not in agent_db_nodes:
                    continue
                if to_id not in {"user"} and to_id not in detected and to_id not in agent_db_nodes:
                    continue
                nodes.add(from_id)
                nodes.add(to_id)
                key = (from_id, to_id, link_type)
                edge_counts[key] = edge_counts.get(key, 0) + 1

        node_rows = [
            {
                "id": node,
                "kind": "user" if node == "user" else "db" if node.endswith("_db") else "agent",
            }
            for node in sorted(nodes)
        ]
        edge_rows = [
            {"from": f, "to": t, "type": typ, "count": count}
            for (f, t, typ), count in sorted(edge_counts.items(), key=lambda x: (-x[1], x[0]))
        ]
        return {"nodes": node_rows, "edges": edge_rows, "events": events[-120:]}

    def db_snapshot(self) -> dict[str, Any]:
        def fetch_table(path: Path, table: str, limit: int = 20) -> dict[str, Any]:
            if not path.exists():
                return {"columns": [], "rows": [], "exists": False, "row_count": 0}

            with sqlite3.connect(path) as conn:
                conn.row_factory = sqlite3.Row
                cols = conn.execute(f"PRAGMA table_info({table})").fetchall()
                col_names = [str(col[1]) for col in cols]
                if not col_names:
                    return {"columns": [], "rows": [], "exists": True, "row_count": 0}

                count_row = conn.execute(f"SELECT COUNT(*) AS c FROM {table}").fetchone()
                row_count = int(count_row["c"]) if count_row and "c" in count_row.keys() else 0

                preferred_order = ["created_at", "updated_at", "completed_at", "local_id", "task_id", "id"]
                order_by = next((c for c in preferred_order if c in col_names), col_names[0])
                query = (
                    f"SELECT {', '.join(col_names)} "
                    f"FROM {table} "
                    f"ORDER BY {order_by} DESC "
                    f"LIMIT {limit}"
                )
                rows = conn.execute(query).fetchall()
            return {"columns": col_names, "rows": [dict(row) for row in rows], "exists": True, "row_count": row_count}

        if not self.agent_catalog:
            self.agent_catalog = self._discover_agents_from_env(self.runtime_env or os.environ)

        agents_db: dict[str, Any] = {}
        for item in self.agent_catalog:
            agent_id = str(item.get("id", "")).lower()
            if not agent_id:
                continue
            db_path = Path(str(item.get("db_path", "")))
            table = str(item.get("db_table", f"{agent_id}_tasks"))
            table_snapshot = fetch_table(db_path, table)
            agents_db[agent_id] = {
                "agent_id": agent_id,
                "db_path": str(db_path),
                "table": table,
                "columns": table_snapshot["columns"],
                "rows": table_snapshot["rows"],
                "db_exists": table_snapshot["exists"],
                "row_count": table_snapshot["row_count"],
            }

        summary_agents: list[dict[str, Any]] = []
        for agent_id in sorted(agents_db.keys()):
            rows = list(agents_db.get(agent_id, {}).get("rows", []))
            latest = rows[0] if rows else {}
            latest_keys = list(latest.keys())
            status_key = next((k for k in ["status", "state"] if k in latest), "")
            if not status_key:
                status_key = next((k for k in latest_keys if k.endswith("_status")), "")
            task_key = next((k for k in ["task_id", "local_id", "id"] if k in latest), "")
            if not task_key:
                task_key = next((k for k in latest_keys if k.endswith("_task_id")), "")
            result_key = next((k for k in ["result_text", "result"] if k in latest), "")
            if not result_key:
                result_key = next((k for k in latest_keys if k.endswith("_result")), "")
            error_key = next((k for k in ["error_text", "error"] if k in latest), "")
            if not error_key:
                error_key = next((k for k in latest_keys if k.endswith("_error")), "")
            summary_agents.append(
                {
                    "agent_id": agent_id,
                    "status": latest.get(status_key, "n/a") if status_key else "n/a",
                    "task_id": str(latest.get(task_key, "")) if task_key else "",
                    "result_text": latest.get(result_key, "") if result_key else "",
                    "error_text": latest.get(error_key, "") if error_key else "",
                    "created_at": latest.get("created_at"),
                    "completed_at": latest.get("completed_at"),
                    "updated_at": latest.get("updated_at"),
                }
            )

        primary = next(
            (x for x in summary_agents if x.get("agent_id") == self.entry_agent_id),
            summary_agents[0] if summary_agents else {},
        )
        summary = {
            "entry_agent": self.entry_agent_id or None,
            "entry_agent_url": self.entry_agent_url or None,
            "agents": summary_agents,
            "primary": primary,
        }
        return {
            "agents": agents_db,
            "summary": summary,
            "timestamp": time.time(),
        }


ORCH = Orchestrator()


async def homepage(_: Request) -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


async def session_page(_: Request) -> FileResponse:
    return FileResponse(STATIC_DIR / "session.html")


async def polling_page(_: Request) -> FileResponse:
    return FileResponse(STATIC_DIR / "polling.html")


async def submit_task(request: Request) -> JSONResponse:
    payload = await request.json()
    text = str(payload.get("text", "")).strip()
    if not text:
        return JSONResponse({"error": "text is required"}, status_code=400)
    run_id = await ORCH.submit_user_task(text)
    return JSONResponse({"run_id": run_id})


async def task_status(request: Request) -> JSONResponse:
    run_id = request.path_params["run_id"]
    run = ORCH.get_task_run(run_id)
    if run is None:
        return JSONResponse({"error": "not_found"}, status_code=404)
    return JSONResponse({**run, "db_summary": ORCH.db_snapshot().get("summary", {})})


async def db_state(_: Request) -> JSONResponse:
    return JSONResponse(ORCH.db_snapshot())


async def config_state(_: Request) -> JSONResponse:
    return JSONResponse({"config": ORCH.effective_config, "env_file": str(ENV_FILE)})


async def polling_config_state(_: Request) -> JSONResponse:
    return JSONResponse(ORCH.get_poll_config_snapshot())


async def update_polling_config(request: Request) -> JSONResponse:
    payload = await request.json()
    caller_agent = str(payload.get("caller_agent") or ORCH.entry_agent_id or "alpha").strip().lower()
    target_agent = str(payload.get("target_agent", "")).strip().lower()
    if not target_agent:
        return JSONResponse({"error": "target_agent is required"}, status_code=400)
    if caller_agent == target_agent:
        return JSONResponse({"error": "caller_agent and target_agent must differ"}, status_code=400)

    try:
        poll_interval_seconds = float(payload.get("poll_interval_seconds", 20.0))
        max_poll_attempts = int(payload.get("max_poll_attempts", 5))
    except Exception:
        return JSONResponse({"error": "poll_interval_seconds/max_poll_attempts must be numeric"}, status_code=400)

    if poll_interval_seconds <= 0:
        return JSONResponse({"error": "poll_interval_seconds must be > 0"}, status_code=400)
    if max_poll_attempts <= 0:
        return JSONResponse({"error": "max_poll_attempts must be > 0"}, status_code=400)

    ORCH.upsert_poll_config(
        caller_agent=caller_agent,
        target_agent=target_agent,
        poll_interval_seconds=poll_interval_seconds,
        max_poll_attempts=max_poll_attempts,
    )
    ORCH._add_event(
        "system",
        (
            "POLL_CONFIG_UPDATED "
            f"caller={caller_agent} target={target_agent} "
            f"interval={poll_interval_seconds} attempts={max_poll_attempts}"
        ),
        kind="task",
    )
    return JSONResponse(ORCH.get_poll_config_snapshot())


async def agents_state(_: Request) -> JSONResponse:
    return JSONResponse(await ORCH.agents_snapshot())


async def sessions_state(_: Request) -> JSONResponse:
    return JSONResponse({"sessions": ORCH.list_sessions(), "timestamp": time.time()})


async def session_state(request: Request) -> JSONResponse:
    run_id = str(request.path_params["run_id"])
    run = ORCH.get_task_run(run_id)
    if run is None:
        return JSONResponse({"error": "not_found"}, status_code=404)

    agents = await ORCH.agents_snapshot()
    detected = {str(a.get("id", "")).lower() for a in agents.get("agents", []) if a.get("detected")}
    graph = ORCH.session_graph(run_id, detected_agents=detected)
    return JSONResponse(
        {
            "run": {
                "id": run.get("id"),
                "input": run.get("input"),
                "status": run.get("status"),
                "result": run.get("result"),
                "entry_agent": run.get("entry_agent"),
                "created_at": run.get("created_at"),
                "updated_at": run.get("updated_at"),
            },
            "detected_agents": sorted(detected),
            "graph": graph,
            "db_summary": ORCH.db_snapshot().get("summary", {}),
            "timestamp": time.time(),
        }
    )


async def events_ws(ws: WebSocket) -> None:
    await ws.accept()
    queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
    ORCH.subscribers.add(queue)

    try:
        for event in list(ORCH.events)[-100:]:
            await ws.send_text(json.dumps(event))

        while True:
            event = await queue.get()
            await ws.send_text(json.dumps(event))
    finally:
        ORCH.subscribers.discard(queue)


routes = [
    Route("/", homepage),
    Route("/sessions/{run_id}", session_page),
    Route("/polling", polling_page),
    Route("/api/tasks", submit_task, methods=["POST"]),
    Route("/api/tasks/{run_id}", task_status, methods=["GET"]),
    Route("/api/db", db_state, methods=["GET"]),
    Route("/api/config", config_state, methods=["GET"]),
    Route("/api/polling-config", polling_config_state, methods=["GET"]),
    Route("/api/polling-config", update_polling_config, methods=["POST"]),
    Route("/api/agents", agents_state, methods=["GET"]),
    Route("/api/sessions", sessions_state, methods=["GET"]),
    Route("/api/sessions/{run_id}", session_state, methods=["GET"]),
    WebSocketRoute("/ws/events", events_ws),
]

app = Starlette(routes=routes, on_startup=[ORCH.startup], on_shutdown=[ORCH.shutdown])
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


if __name__ == "__main__":
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, signal.default_int_handler)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    uvicorn.run(app, host="0.0.0.0", port=8200, log_level="info")
