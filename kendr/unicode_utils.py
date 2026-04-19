from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


_UNPAIRED_SURROGATE_RE = re.compile(r"[\ud800-\udfff]")


def sanitize_text(value: object) -> str:
    text = "" if value is None else str(value)
    if not text:
        return ""
    return _UNPAIRED_SURROGATE_RE.sub("\uFFFD", text)


def sanitize_data(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, Path):
        return sanitize_text(value)
    if isinstance(value, dict):
        return {
            sanitize_text(key) if isinstance(key, str) else sanitize_text(key): sanitize_data(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [sanitize_data(item) for item in value]
    if isinstance(value, tuple):
        return tuple(sanitize_data(item) for item in value)
    if isinstance(value, set):
        return [sanitize_data(item) for item in value]
    return value


def safe_json_dumps(value: Any, **kwargs: Any) -> str:
    return json.dumps(sanitize_data(value), **kwargs)
