"""
Unified Connector Registry
==========================

A *connector* is anything the orchestrator can route work to:

  - ``task_agent``  — a native Python agent in ``tasks/`` discovered by reflection
  - ``skill``       — an installed user skill (catalog or custom) stored in ``user_skills``
  - ``mcp_tool``    — a tool from a connected MCP server stored in ``mcp_servers``
  - ``integration`` — an external service integration gated by env-var credentials

All connectors expose:
  - ``agent_name``      — the registry key (what to put in ``state["next_agent"]``)
  - ``input_schema``    — JSON Schema describing the inputs dict the agent expects
  - ``state_input_key`` — the state key to set before routing
  - ``state_output_key``— the state key where the result will land
  - ``status``          — "ready" | "needs_config" | "not_discovered" | "disabled"

Call ``build_connector_catalog(registry)`` to get a fresh snapshot.
Call ``connector_catalog_prompt_block(specs)`` to get the orchestrator-ready text.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Any

_log = logging.getLogger("kendr.connector_registry")

# System / internal agents that must never appear in connector catalogs
_SYSTEM_AGENTS: frozenset[str] = frozenset({
    "orchestrator_agent",
    "finalize_agent",
    "reviewer_agent",
    "planner_agent",
    "session_router_agent",
    "channel_gateway_agent",
})


# ---------------------------------------------------------------------------
# ConnectorSpec — one entry in the catalog
# ---------------------------------------------------------------------------

@dataclass
class ConnectorSpec:
    """Unified descriptor for every callable connector."""

    agent_name: str          # Exact registry name: "skill_web_search_agent"
    connector_type: str      # "task_agent" | "skill" | "mcp_tool" | "integration"
    display_name: str
    description: str
    icon: str                # Emoji / short string
    status: str              # "ready" | "needs_config" | "not_discovered" | "disabled"
    category: str

    # ── Input contract ──────────────────────────────────────────────────────
    state_input_key: str     # set state[state_input_key] = {…inputs…} before routing
    input_schema: dict       # JSON Schema for the input dict
    required_inputs: list[str] = field(default_factory=list)

    # ── Output contract ─────────────────────────────────────────────────────
    state_output_key: str = "draft_response"
    output_schema: dict = field(default_factory=dict)

    # ── Config / dependency info ─────────────────────────────────────────────
    missing_config: list[str] = field(default_factory=list)

    # ── Extra type-specific metadata ─────────────────────────────────────────
    metadata: dict = field(default_factory=dict)

    # ────────────────────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "agent_name": self.agent_name,
            "connector_type": self.connector_type,
            "display_name": self.display_name,
            "description": self.description,
            "icon": self.icon,
            "status": self.status,
            "category": self.category,
            "state_input_key": self.state_input_key,
            "input_schema": self.input_schema,
            "required_inputs": self.required_inputs,
            "state_output_key": self.state_output_key,
            "output_schema": self.output_schema,
            "missing_config": self.missing_config,
            "metadata": self.metadata,
        }

    def prompt_summary(self) -> str:
        """Compact multi-line string for the orchestrator prompt.

        Tells the LLM exactly how to invoke this connector — which state key to
        set, what fields are required, and where to find the output.
        """
        icon = self.icon or "•"
        status_note = "" if self.status == "ready" else f" [{self.status.upper()}]"
        lines = [f"{icon} `{self.agent_name}`{status_note}: {self.description}"]

        if self.required_inputs:
            req_str = ", ".join(f'"{k}"' for k in self.required_inputs)
            lines.append(
                f"   → set `state[\"{self.state_input_key}\"]` = {{dict with {req_str}}}"
            )
        elif self.state_input_key:
            lines.append(
                f"   → set `state[\"{self.state_input_key}\"]` = {{inputs dict}}"
            )

        lines.append(f"   → result in `state[\"{self.state_output_key}\"]`")
        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Catalog builder — reads registry + DB, returns list[ConnectorSpec]
# ---------------------------------------------------------------------------

def build_connector_catalog(
    registry: Any,
    agent_routing: Any | None = None,
) -> list[ConnectorSpec]:
    """Build a unified connector catalog from the live registry.

    The function classifies each agent by its metadata tags, then enriches
    skill and MCP entries with schema data from the DB.  Task agents get
    their schema from ``AGENT_METADATA.input_keys``.

    Safe to call at any time — all DB/import failures are swallowed so the
    orchestrator can still proceed even if a sub-store is unavailable.
    """
    specs: list[ConnectorSpec] = []
    for agent_name, agent_def in registry.agents.items():
        if agent_name in _SYSTEM_AGENTS:
            continue
        meta = getattr(agent_def, "metadata", {}) or {}
        ctype = meta.get("connector_type") or (
            "mcp_tool" if meta.get("mcp_tool") else
            "skill"    if meta.get("skill_agent") else
            "task_agent"
        )
        try:
            if ctype == "mcp_tool":
                specs.append(_mcp_spec(agent_name, agent_def, meta))
            elif ctype == "skill":
                specs.append(_skill_spec(agent_name, agent_def, meta))
            else:
                specs.append(_task_agent_spec(agent_name, agent_def, meta))
        except Exception as exc:
            _log.debug("ConnectorSpec build failed for %s: %s", agent_name, exc)
    return specs


# ---------------------------------------------------------------------------
# Per-type spec builders
# ---------------------------------------------------------------------------

def _safe_slug(text: str, max_len: int = 30) -> str:
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")[:max_len]


def _mcp_spec(agent_name: str, agent_def: Any, meta: dict) -> ConnectorSpec:
    server_name = meta.get("mcp_server_name", "")
    tool_name   = meta.get("mcp_tool_name", "")
    description = (getattr(agent_def, "description", "") or "").strip()
    if not description:
        description = f"MCP tool '{tool_name}' from server '{server_name}'"

    input_schema: dict = {}
    required_inputs: list[str] = []
    try:
        from kendr.mcp_manager import list_servers_safe as _ls
        server_id = meta.get("mcp_server_id", "")
        for s in _ls():
            if s.get("id") == server_id or s.get("name") == server_name:
                for t in (s.get("tools") or []):
                    if t.get("name") == tool_name:
                        raw_schema = t.get("schema") or {}
                        if isinstance(raw_schema, str):
                            try:
                                raw_schema = json.loads(raw_schema)
                            except Exception:
                                raw_schema = {}
                        input_schema = raw_schema
                        required_inputs = input_schema.get("required") or []
                        break
                break
    except Exception:
        pass

    tool_slug = _safe_slug(tool_name)
    return ConnectorSpec(
        agent_name=agent_name,
        connector_type="mcp_tool",
        display_name=f"{server_name} › {tool_name}",
        description=description,
        icon="🔌",
        status="ready",
        category="MCP Tool",
        state_input_key=f"mcp_input_{tool_slug}",
        input_schema=input_schema,
        required_inputs=required_inputs,
        state_output_key=f"mcp_result_{tool_slug}",
        output_schema={},
        missing_config=[],
        metadata={"server_name": server_name, "tool_name": tool_name},
    )


def _skill_spec(agent_name: str, agent_def: Any, meta: dict) -> ConnectorSpec:
    slug       = meta.get("skill_slug", "")
    skill_type = meta.get("skill_type", "")
    icon       = meta.get("skill_icon", "⚡")
    category   = meta.get("skill_category", "Custom")
    description = (getattr(agent_def, "description", "") or "").strip()

    input_schema: dict  = {}
    output_schema: dict = {}
    required_inputs: list[str] = []
    display_name = slug

    try:
        from kendr.skill_manager import resolve_runtime_skill as _get_skill
        row = _get_skill(slug=slug)
        if row:
            display_name = row.get("name") or slug
            raw_in = row.get("input_schema") or {}
            if isinstance(raw_in, str):
                try:
                    raw_in = json.loads(raw_in)
                except Exception:
                    raw_in = {}
            input_schema = raw_in
            required_inputs = input_schema.get("required") or []
            raw_out = row.get("output_schema") or {}
            if isinstance(raw_out, str):
                try:
                    raw_out = json.loads(raw_out)
                except Exception:
                    raw_out = {}
            output_schema = raw_out
    except Exception:
        pass

    safe = _safe_slug(slug)
    return ConnectorSpec(
        agent_name=agent_name,
        connector_type="skill",
        display_name=display_name,
        description=description,
        icon=icon,
        status="ready",
        category=category,
        state_input_key=f"skill_inputs_{safe}",
        input_schema=input_schema,
        required_inputs=required_inputs,
        state_output_key="skill_output",
        output_schema=output_schema,
        missing_config=[],
        metadata={"slug": slug, "skill_type": skill_type},
    )


def _task_agent_spec(agent_name: str, agent_def: Any, meta: dict) -> ConnectorSpec:
    description  = (getattr(agent_def, "description", "") or "").strip() or agent_name
    input_keys   = list(getattr(agent_def, "input_keys",  []) or [])
    output_keys  = list(getattr(agent_def, "output_keys", []) or [])
    skills       = list(getattr(agent_def, "skills",      []) or [])
    requirements = list(getattr(agent_def, "requirements", []) or [])

    missing_config: list[str] = []
    try:
        from kendr.integration_registry import check_agent_integration_config as _check
        _, _missing, _needs_cfg, _ = _check(agent_name)
        if _needs_cfg:
            missing_config = list(_missing or [])
    except Exception:
        pass

    status = "needs_config" if missing_config else "ready"

    # Build a loose schema from declared input_keys so the orchestrator
    # knows at least what keys this agent expects to find in state.
    input_schema: dict = {}
    if input_keys:
        input_schema = {
            "type": "object",
            "properties": {k: {"type": "string"} for k in input_keys},
        }

    state_input_key  = input_keys[0]  if input_keys  else agent_name.replace("_agent", "")
    state_output_key = output_keys[0] if output_keys else "draft_response"

    return ConnectorSpec(
        agent_name=agent_name,
        connector_type="task_agent",
        display_name=agent_name.replace("_agent", "").replace("_", " ").title(),
        description=description,
        icon="🤖",
        status=status,
        category="Agent",
        state_input_key=state_input_key,
        input_schema=input_schema,
        required_inputs=[],
        state_output_key=state_output_key,
        output_schema={},
        missing_config=missing_config,
        metadata={"skills": skills, "requirements": requirements},
    )


# ---------------------------------------------------------------------------
# Integration catalog (not in registry — separate call)
# ---------------------------------------------------------------------------

def build_integration_catalog() -> list[ConnectorSpec]:
    """Return ConnectorSpec entries for every known service integration."""
    specs: list[ConnectorSpec] = []
    try:
        from kendr.integration_registry import list_integrations as _list_integrations

        for card in _list_integrations():
            status = "ready" if card.is_configured else "needs_config"
            missing = card.missing_vars
            actions_summary = "; ".join(
                f"{a.name}({', '.join(a.required_inputs)})" for a in card.actions
            )
            specs.append(ConnectorSpec(
                agent_name=f"integration:{card.id}",   # not a registry agent — marker prefix
                connector_type="integration",
                display_name=card.name,
                description=card.description + (f" — Actions: {actions_summary}" if actions_summary else ""),
                icon=card.icon,
                status=status,
                category=card.category,
                state_input_key=f"integration_{card.id}_input",
                input_schema={},
                required_inputs=[],
                state_output_key=f"integration_{card.id}_output",
                output_schema={},
                missing_config=missing,
                metadata={
                    "required_env_vars": list(card.required_env_vars),
                    "docs_url": card.docs_url,
                    "legacy_connector_type": "plugin",
                },
            ))
    except Exception:
        pass
    return specs


def build_plugin_catalog() -> list[ConnectorSpec]:
    """Compatibility wrapper for the old service-plugin naming."""

    return build_integration_catalog()


# ---------------------------------------------------------------------------
# Prompt block generator
# ---------------------------------------------------------------------------

_TYPE_ORDER = ["skill", "mcp_tool", "task_agent"]
_TYPE_LABELS = {
    "skill":      "⚡ Custom Skills",
    "mcp_tool":   "🔌 MCP Tools",
    "task_agent": "🤖 Built-in Agents",
}


def connector_catalog_prompt_block(
    specs: list[ConnectorSpec],
    *,
    include_types: set[str] | None = None,
    only_ready: bool = False,
    max_per_type: int = 25,
) -> str:
    """Format connector specs as a structured section for the orchestrator prompt.

    Each entry includes the canonical agent name, a one-line description, the
    state key to set for inputs, and the required input fields — so the LLM
    knows precisely how to invoke it without guessing.
    """
    filtered = [
        s for s in specs
        if s.agent_name not in _SYSTEM_AGENTS
        and not s.agent_name.startswith("plugin:")
        and not s.agent_name.startswith("integration:")  # config-only entries
        and (include_types is None or s.connector_type in include_types)
        and (not only_ready or s.status == "ready")
    ]
    if not filtered:
        return ""

    by_type: dict[str, list[ConnectorSpec]] = {}
    for s in filtered:
        by_type.setdefault(s.connector_type, []).append(s)

    lines: list[str] = ["## Available Connectors\n",
                         "Route to these agents to extend your capabilities.\n"]

    for ctype in _TYPE_ORDER:
        group = by_type.get(ctype, [])[:max_per_type]
        if not group:
            continue
        lines.append(f"### {_TYPE_LABELS.get(ctype, ctype)}")
        for s in group:
            lines.append(s.prompt_summary())
        lines.append("")

    return "\n".join(lines).strip()
