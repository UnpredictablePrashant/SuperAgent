import logging
import sqlite3

from typing import Mapping
from uuid import uuid4

from a2a.client import A2AClient
from a2a.types import Message, MessageSendParams, Part, Role, SendMessageRequest, TextPart


def _collect_a2a_texts(value: object, out: list[str]) -> None:
    if isinstance(value, dict):
        if value.get("kind") == "text" and isinstance(value.get("text"), str):
            out.append(value["text"])
        for item in value.values():
            _collect_a2a_texts(item, out)
        return

    if isinstance(value, list):
        for item in value:
            _collect_a2a_texts(item, out)


def extract_last_a2a_text(response: object) -> str:
    if not hasattr(response, "model_dump"):
        return ""

    payload = response.model_dump(mode="json", exclude_none=True)
    texts: list[str] = []
    _collect_a2a_texts(payload, texts)
    return texts[-1] if texts else ""


async def send_text_message(client: A2AClient, text: str, logger: logging.Logger, request_log: str, response_log: str) -> str:
    send_params = MessageSendParams(
        message=Message(
            role=Role.user,
            parts=[Part(TextPart(text=text))],
            message_id=uuid4().hex,
        )
    )
    request = SendMessageRequest(id=str(uuid4()), params=send_params)

    logger.info(request_log, request.model_dump_json(indent=2, exclude_none=True))
    response = await client.send_message(request)
    logger.info(response_log, response.model_dump_json(indent=2, exclude_none=True))

    return extract_last_a2a_text(response)


def resolve_polling_config(
    env_map: Mapping[str, str],
    caller_agent: str,
    target_agent: str,
    default_interval_seconds: float,
    default_max_attempts: int,
    ecosystem_db_path: str | None = None,
) -> tuple[float, int]:
    caller = caller_agent.strip().upper()
    target = target_agent.strip().upper()

    interval_keys = [
        f"{caller}_TO_{target}_POLL_INTERVAL_SECONDS",
        f"{caller}_{target}_POLL_INTERVAL_SECONDS",
        f"{caller}_POLL_INTERVAL_SECONDS",
    ]
    attempts_keys = [
        f"{caller}_TO_{target}_MAX_POLL_ATTEMPTS",
        f"{caller}_{target}_MAX_POLL_ATTEMPTS",
        f"{caller}_MAX_POLL_ATTEMPTS",
    ]

    interval = default_interval_seconds
    max_attempts = default_max_attempts

    if ecosystem_db_path:
        try:
            with sqlite3.connect(ecosystem_db_path) as conn:
                conn.row_factory = sqlite3.Row
                row = conn.execute(
                    """
                    SELECT poll_interval_seconds, max_poll_attempts
                    FROM poll_config
                    WHERE caller_agent = ? AND target_agent = ?
                    """,
                    (caller.lower(), target.lower()),
                ).fetchone()
                if row is not None:
                    if row["poll_interval_seconds"] is not None:
                        interval = float(row["poll_interval_seconds"])
                    if row["max_poll_attempts"] is not None:
                        max_attempts = int(row["max_poll_attempts"])
                    return max(0.1, interval), max(1, max_attempts)
        except Exception:
            pass

    for key in interval_keys:
        raw = env_map.get(key)
        if raw is not None and str(raw).strip() != "":
            try:
                interval = float(str(raw).strip())
            except Exception:
                interval = default_interval_seconds
            break

    for key in attempts_keys:
        raw = env_map.get(key)
        if raw is not None and str(raw).strip() != "":
            try:
                max_attempts = int(str(raw).strip())
            except Exception:
                max_attempts = default_max_attempts
            break

    return max(0.1, interval), max(1, max_attempts)
