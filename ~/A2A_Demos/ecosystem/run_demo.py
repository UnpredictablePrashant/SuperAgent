import asyncio
import logging
import os
import signal
import subprocess
import sys
import threading

from dataclasses import dataclass, field
from pathlib import Path
from uuid import uuid4

import httpx

from a2a.client import A2ACardResolver, A2AClient
from a2a.types import Message, MessageSendParams, Part, Role, SendMessageRequest, TextPart
from a2a.utils.constants import AGENT_CARD_WELL_KNOWN_PATH


ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "ecosystem" / "output"
CARDS_DIR = OUT_DIR / "cards"
FULL_LOG_FILE = OUT_DIR / "full_run.log"

ALPHA_URL = "http://127.0.0.1:8101"
BETA_URL = "http://127.0.0.1:8102"

LOGGER = logging.getLogger("ecosystem")


def collect_texts(value: object, out: list[str]) -> None:
    if isinstance(value, dict):
        if value.get("kind") == "text" and isinstance(value.get("text"), str):
            out.append(value["text"])
        for item in value.values():
            collect_texts(item, out)
        return
    if isinstance(value, list):
        for item in value:
            collect_texts(item, out)


def extract_last_text(response: object) -> str:
    if not hasattr(response, "model_dump"):
        return ""
    payload = response.model_dump(mode="json", exclude_none=True)
    texts: list[str] = []
    collect_texts(payload, texts)
    return texts[-1] if texts else ""


@dataclass
class ManagedProcess:
    name: str
    cwd: Path
    command: list[str]
    env: dict[str, str]
    process: subprocess.Popen[str] | None = None
    lines: list[str] = field(default_factory=list)
    _thread: threading.Thread | None = None

    def start(self) -> None:
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
                line = line.rstrip("\n")
                tagged = f"[{self.name}] {line}"
                self.lines.append(tagged)
                LOGGER.info(tagged)

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
            await asyncio.sleep(0.4)


async def run() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    CARDS_DIR.mkdir(parents=True, exist_ok=True)

    log_file = FULL_LOG_FILE.open("w", encoding="utf-8")
    stream_handler = logging.StreamHandler(sys.stdout)
    file_handler = logging.StreamHandler(log_file)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[stream_handler, file_handler],
    )

    base_env = os.environ.copy()
    base_env["PYTHONUNBUFFERED"] = "1"

    beta_proc = ManagedProcess(
        name="beta",
        cwd=ROOT / "agent_beta",
        command=[sys.executable, "-u", "app.py"],
        env=base_env,
    )
    alpha_proc = ManagedProcess(
        name="alpha",
        cwd=ROOT / "agent_alpha",
        command=[sys.executable, "-u", "app.py"],
        env={**base_env, "BETA_AGENT_URL": BETA_URL},
    )

    try:
        LOGGER.info("Starting Beta agent process...")
        beta_proc.start()
        await wait_for_endpoint(BETA_URL)
        LOGGER.info("Beta is ready.")

        LOGGER.info("Starting Alpha agent process...")
        alpha_proc.start()
        await wait_for_endpoint(ALPHA_URL)
        LOGGER.info("Alpha is ready.")

        async with httpx.AsyncClient(timeout=30.0) as httpx_client:
            alpha_resolver = A2ACardResolver(httpx_client=httpx_client, base_url=ALPHA_URL)
            beta_resolver = A2ACardResolver(httpx_client=httpx_client, base_url=BETA_URL)

            alpha_card = await alpha_resolver.get_agent_card()
            beta_card = await beta_resolver.get_agent_card()

            alpha_card_json = alpha_card.model_dump_json(indent=2, exclude_none=True)
            beta_card_json = beta_card.model_dump_json(indent=2, exclude_none=True)

            (CARDS_DIR / "alpha_agent_card.json").write_text(alpha_card_json, encoding="utf-8")
            (CARDS_DIR / "beta_agent_card.json").write_text(beta_card_json, encoding="utf-8")

            LOGGER.info("ALPHA_AGENT_CARD=%s", alpha_card_json)
            LOGGER.info("BETA_AGENT_CARD=%s", beta_card_json)

            client = A2AClient(httpx_client=httpx_client, agent_card=alpha_card)

            user_message = "Please ask Beta what you received from me."
            send_params = MessageSendParams(
                message=Message(
                    role=Role.user,
                    parts=[Part(TextPart(text=user_message))],
                    message_id=uuid4().hex,
                )
            )
            request = SendMessageRequest(id=str(uuid4()), params=send_params)
            LOGGER.info(
                "USER_TO_ALPHA_SEND_MESSAGE_REQUEST=%s",
                request.model_dump_json(indent=2, exclude_none=True),
            )

            response = await client.send_message(request)
            response_json = response.model_dump_json(indent=2, exclude_none=True)
            LOGGER.info("ALPHA_TO_USER_SEND_MESSAGE_RESPONSE=%s", response_json)

            final_text = extract_last_text(response)
            LOGGER.info("FINAL_TEXT_RESPONSE=%s", final_text)

        LOGGER.info("Demo completed successfully. Logs written to %s", FULL_LOG_FILE)
        return 0
    except Exception:
        LOGGER.exception("Demo failed.")
        return 1
    finally:
        LOGGER.info("Stopping agent processes...")
        alpha_proc.stop()
        beta_proc.stop()
        log_file.close()


if __name__ == "__main__":
    if hasattr(signal, "SIGINT"):
        signal.signal(signal.SIGINT, signal.default_int_handler)
    raise SystemExit(asyncio.run(run()))
