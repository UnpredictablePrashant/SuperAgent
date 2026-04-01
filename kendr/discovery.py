from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import pkgutil
from pathlib import Path

import tasks

from .setup.catalog import channel_catalog, provider_catalog
from .registry import Registry
from .types import AgentDefinition, ChannelDefinition, PluginDefinition, PluginManifest, ProviderDefinition


IGNORE_TASK_MODULES = {
    "__pycache__",
    "a2a_agent_utils",
    "a2a_protocol",
    "github_client",
    "research_infra",
    "setup_registry",
    "sqlite_store",
    "utils",
}


def _titleize(name: str) -> str:
    return name.replace("_", " ").strip().capitalize()


def _default_description(agent_name: str) -> str:
    if agent_name.endswith("_agent"):
        agent_name = agent_name[:-6]
    return f"{_titleize(agent_name)} agent."


def _default_skills(agent_name: str) -> list[str]:
    base = agent_name[:-6] if agent_name.endswith("_agent") else agent_name
    return [token for token in base.split("_") if token]


def _register_builtin_capabilities(registry: Registry) -> None:
    registry.register_plugin(
        PluginDefinition(
            name="builtin.core",
            source="builtin",
            description="Built-in channels and providers for the kendr runtime.",
        )
    )
    for provider in provider_catalog():
        registry.register_provider(
            ProviderDefinition(
                name=provider["name"],
                description=provider["description"],
                auth_mode=provider.get("auth_mode", "api_key"),
                plugin_name="builtin.core",
                metadata=provider.get("metadata", {}),
            )
        )
    for channel in channel_catalog():
        registry.register_channel(
            ChannelDefinition(
                name=channel["name"],
                description=channel["description"],
                plugin_name="builtin.core",
                metadata=channel.get("metadata", {}),
            )
        )


def _register_task_module_agents(registry: Registry, module_name: str) -> None:
    module = importlib.import_module(module_name)
    plugin_name = f"builtin.{module_name}"
    registry.register_plugin(
        PluginDefinition(
            name=plugin_name,
            source=module_name,
            description=f"Built-in agents discovered from {module_name}.",
        )
    )
    module_metadata = getattr(module, "AGENT_METADATA", {})
    for name, fn in inspect.getmembers(module, inspect.isfunction):
        if fn.__module__ != module.__name__:
            continue
        if not name.endswith("_agent") or name.startswith("_"):
            continue
        metadata = module_metadata.get(name, {}) if isinstance(module_metadata, dict) else {}
        description = metadata.get("description") or inspect.getdoc(fn) or _default_description(name)
        registry.register_agent(
            AgentDefinition(
                name=name,
                handler=fn,
                description=description,
                skills=metadata.get("skills") or _default_skills(name),
                input_keys=metadata.get("input_keys", []),
                output_keys=metadata.get("output_keys", []),
                plugin_name=plugin_name,
                requirements=metadata.get("requirements", []),
                metadata=metadata,
            )
        )


def _discover_builtin_task_agents(registry: Registry) -> None:
    for module_info in pkgutil.iter_modules(tasks.__path__):
        name = module_info.name
        if name in IGNORE_TASK_MODULES or name.startswith("__"):
            continue
        _register_task_module_agents(registry, f"tasks.{name}")


def _plugin_manifest_from_module(module, plugin_path: Path) -> PluginManifest:
    plugin_meta = getattr(module, "PLUGIN", None)
    if isinstance(plugin_meta, PluginManifest):
        return plugin_meta
    if isinstance(plugin_meta, dict):
        return PluginManifest.from_mapping(plugin_meta, default_name=plugin_path.stem)
    return PluginManifest.from_mapping({}, default_name=plugin_path.stem)


def _load_external_plugin(registry: Registry, plugin_path: Path) -> None:
    module_name = f"external_plugin_{plugin_path.stem}_{abs(hash(str(plugin_path)))}"
    spec = importlib.util.spec_from_file_location(module_name, plugin_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load plugin from {plugin_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    manifest = _plugin_manifest_from_module(module, plugin_path)
    register = getattr(module, manifest.entry_point, None)
    if not callable(register):
        raise RuntimeError(
            f"Plugin {plugin_path} must define a callable {manifest.entry_point}(registry) function."
        )
    registry.register_plugin(manifest.to_plugin_definition(source=str(plugin_path), kind="external"))
    register(registry)


def _plugin_search_paths() -> list[Path]:
    home = Path(os.getenv("KENDR_HOME", Path.home() / ".kendr")).expanduser()
    configured = os.getenv("KENDR_PLUGIN_PATHS", "")
    paths = [
        Path.cwd() / "plugins",
        home / "plugins",
    ]
    for raw in configured.split(os.pathsep):
        raw = raw.strip()
        if raw:
            paths.append(Path(raw).expanduser())
    unique = []
    seen = set()
    for path in paths:
        if str(path) in seen:
            continue
        seen.add(str(path))
        unique.append(path)
    return unique


def _discover_external_plugins(registry: Registry) -> None:
    for base in _plugin_search_paths():
        if not base.exists():
            continue
        for plugin_path in sorted(base.glob("*.py")):
            _load_external_plugin(registry, plugin_path)


def _register_mcp_tools(registry: Registry) -> None:
    """Register tools from enabled MCP servers as synthetic agents.

    Each MCP tool becomes an ``AgentDefinition`` with a generated handler that
    calls the tool via the fastmcp client.  This lets the planner route to MCP
    tools the same way it routes to native agents.

    The function is silent on any import/connectivity errors — MCP tools are
    best-effort at build_registry() time.
    """
    try:
        from kendr.mcp_manager import list_servers as _mcp_list_servers
    except Exception:
        return

    try:
        servers = _mcp_list_servers()
    except Exception:
        return

    plugin_name = "builtin.mcp"
    registry.register_plugin(
        PluginDefinition(
            name=plugin_name,
            source="mcp",
            description="Synthetic agents injected from registered MCP servers.",
        )
    )

    for server in servers:
        if not server.get("enabled", True):
            continue
        tools = server.get("tools", [])
        if not tools:
            continue

        server_name = server.get("name", "mcp")
        server_id = server.get("id", "")
        connection = server.get("connection", "")
        server_type = server.get("type", "http")

        for tool in tools:
            tool_name = str(tool.get("name", "")).strip()
            if not tool_name:
                continue

            # Build a safe agent name: mcp_<server_slug>_<tool_name>_agent
            server_slug = "".join(c if c.isalnum() else "_" for c in server_name.lower()).strip("_")[:20]
            tool_slug = "".join(c if c.isalnum() else "_" for c in tool_name.lower()).strip("_")
            agent_name = f"mcp_{server_slug}_{tool_slug}_agent"

            tool_desc = str(tool.get("description", "") or "").strip()
            full_desc = tool_desc or f"MCP tool '{tool_name}' from server '{server_name}'."

            _tool_name_captured = tool_name
            _connection_captured = connection
            _server_type_captured = server_type
            _server_name_captured = server_name

            def _make_handler(
                tname: str,
                conn: str,
                stype: str,
                sname: str,
            ):
                def _mcp_tool_handler(state: dict) -> dict:
                    import asyncio as _asyncio
                    import json as _json

                    try:
                        from fastmcp import Client as _MCPClient
                    except ImportError:
                        state["error"] = "fastmcp is not installed"
                        return state

                    tool_input: dict = state.get(f"mcp_input_{tname}", state.get("mcp_tool_input", {}))
                    if not isinstance(tool_input, dict):
                        tool_input = {}

                    async def _call():
                        async with _MCPClient(conn, timeout=30) as client:
                            return await client.call_tool(tname, tool_input)

                    try:
                        result = _asyncio.run(_call())
                        if hasattr(result, "content"):
                            parts = result.content
                            text_parts = [
                                p.text if hasattr(p, "text") else str(p)
                                for p in (parts if isinstance(parts, list) else [parts])
                            ]
                            state[f"mcp_result_{tname}"] = "\n".join(text_parts)
                        else:
                            state[f"mcp_result_{tname}"] = str(result)
                        state["mcp_tool_name"] = tname
                        state["mcp_server_name"] = sname
                        state["mcp_tool_ok"] = True
                    except Exception as exc:
                        state["mcp_tool_ok"] = False
                        state["mcp_tool_error"] = str(exc)
                    return state

                _mcp_tool_handler.__name__ = f"mcp_{sname}_{tname}_handler"
                return _mcp_tool_handler

            handler = _make_handler(
                _tool_name_captured,
                _connection_captured,
                _server_type_captured,
                _server_name_captured,
            )

            skills = [tool_slug, server_slug, "mcp"]
            registry.register_agent(
                AgentDefinition(
                    name=agent_name,
                    handler=handler,
                    description=full_desc,
                    skills=skills,
                    input_keys=[f"mcp_input_{tool_name}", "mcp_tool_input"],
                    output_keys=[f"mcp_result_{tool_name}", "mcp_tool_name", "mcp_tool_ok"],
                    plugin_name=plugin_name,
                    requirements=[],
                    metadata={
                        "mcp_tool": True,
                        "mcp_server_id": server_id,
                        "mcp_server_name": server_name,
                        "mcp_tool_name": tool_name,
                        "mcp_connection": connection,
                    },
                )
            )


def build_registry() -> Registry:
    registry = Registry()
    _register_builtin_capabilities(registry)
    _discover_builtin_task_agents(registry)
    _discover_external_plugins(registry)
    _register_mcp_tools(registry)
    return registry
