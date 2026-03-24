from .discovery import build_registry

try:
    from .runtime import AgentRuntime
except Exception:  # pragma: no cover - allows setup tooling to load without full runtime deps
    AgentRuntime = None

__all__ = ["AgentRuntime", "build_registry"]
