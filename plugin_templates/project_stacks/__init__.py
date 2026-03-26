"""Project stack template registry.

Each sibling module exports a STACK_TEMPLATE dict describing a pre-configured
technology stack (directory layout, dependencies, Docker services, etc.).
Templates are auto-discovered on first import and can be retrieved by name.
"""

from __future__ import annotations

import importlib
import pkgutil
from pathlib import Path
from typing import Any

_REGISTRY: dict[str, dict[str, Any]] = {}
_LOADED = False


def _discover() -> None:
    global _LOADED
    if _LOADED:
        return
    package_dir = str(Path(__file__).resolve().parent)
    for finder, module_name, is_pkg in pkgutil.iter_modules([package_dir]):
        if module_name.startswith("_"):
            continue
        try:
            mod = importlib.import_module(f"{__name__}.{module_name}")
            template = getattr(mod, "STACK_TEMPLATE", None)
            if isinstance(template, dict) and template.get("name"):
                _REGISTRY[template["name"]] = template
        except Exception:
            pass
    _LOADED = True


def load_stack_template(stack_name: str) -> dict[str, Any] | None:
    """Return the template dict for *stack_name*, or ``None``."""
    _discover()
    return _REGISTRY.get(stack_name)


def available_stacks() -> list[str]:
    """Return sorted list of registered stack names."""
    _discover()
    return sorted(_REGISTRY)


def all_stack_summaries() -> list[dict[str, str]]:
    """Return ``[{name, display_name}]`` for every registered stack."""
    _discover()
    return [
        {"name": t["name"], "display_name": t.get("display_name", t["name"])}
        for t in _REGISTRY.values()
    ]
