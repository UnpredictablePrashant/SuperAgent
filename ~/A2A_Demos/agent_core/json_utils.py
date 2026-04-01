import json

from typing import Any


def parse_json_or_none(text: str) -> dict[str, Any] | None:
    try:
        value = json.loads(text)
    except Exception:
        return None
    return value if isinstance(value, dict) else None


def to_pretty_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2)


def to_json(payload: dict[str, Any]) -> str:
    return json.dumps(payload)
