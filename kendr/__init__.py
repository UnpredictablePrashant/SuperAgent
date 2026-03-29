from __future__ import annotations

from typing import Any


def build_registry(*args: Any, **kwargs: Any):
    from .discovery import build_registry as _build_registry

    return _build_registry(*args, **kwargs)


def __getattr__(name: str):
    if name == "AgentRuntime":
        from .runtime import AgentRuntime

        return AgentRuntime
    if name == "build_registry":
        return build_registry
    raise AttributeError(f"module 'kendr' has no attribute {name!r}")


__all__ = ["AgentRuntime", "build_registry"]
