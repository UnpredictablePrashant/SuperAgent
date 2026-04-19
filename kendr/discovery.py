from __future__ import annotations

import importlib
import importlib.util
import inspect
import os
import pkgutil
from dataclasses import dataclass
from pathlib import Path

import tasks

from .setup.catalog import channel_catalog, provider_catalog
from .registry import Registry
from .definitions import (
    AgentDefinition,
    ChannelDefinition,
    PluginDefinition,
    PluginManifest,
    ProviderDefinition,
)


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


@dataclass(slots=True)
class DiscoveryOptions:
    discover_builtin_task_agents: bool = True
    discover_external_plugins: bool = True
    discover_mcp_tools: bool = True
    discover_skill_agents: bool = True
    strict: bool = False


class RegistryDiscoveryError(RuntimeError):
    def __init__(self, *, source: str, target: str, exc: Exception) -> None:
        message = f"Registry discovery failed for {source}:{target}: {type(exc).__name__}: {exc}"
        super().__init__(message)
        self.source = source
        self.target = target
        self.original_exception = exc


def _handle_discovery_error(
    registry: Registry,
    *,
    source: str,
    target: str,
    exc: Exception,
    strict: bool,
) -> None:
    if strict:
        raise RegistryDiscoveryError(source=source, target=target, exc=exc) from exc
    registry.record_discovery_issue(
        source=source,
        target=target,
        error=f"{type(exc).__name__}: {exc}",
    )


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
        metadata = dict(module_metadata.get(name, {}) if isinstance(module_metadata, dict) else {})
        if metadata.get("discoverable", True) is False:
            continue
        metadata.setdefault("connector_type", "task_agent")
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


def _discover_builtin_task_agents(registry: Registry, *, strict: bool = False) -> None:
    for module_info in pkgutil.iter_modules(tasks.__path__):
        name = module_info.name
        if name in IGNORE_TASK_MODULES or name.startswith("__"):
            continue
        module_name = f"tasks.{name}"
        try:
            _register_task_module_agents(registry, module_name)
        except Exception as exc:
            _handle_discovery_error(
                registry,
                source="builtin_task_module",
                target=module_name,
                exc=exc,
                strict=strict,
            )


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


def _discover_external_plugins(registry: Registry, *, strict: bool = False) -> None:
    for base in _plugin_search_paths():
        if not base.exists():
            continue
        for plugin_path in sorted(base.glob("*.py")):
            try:
                _load_external_plugin(registry, plugin_path)
            except Exception as exc:
                _handle_discovery_error(
                    registry,
                    source="external_plugin",
                    target=str(plugin_path),
                    exc=exc,
                    strict=strict,
                )


def _register_mcp_tools(registry: Registry, *, strict: bool = False) -> None:
    """Register tools from enabled MCP servers as synthetic agents.

    Each MCP tool becomes an ``AgentDefinition`` with a generated handler that
    calls the tool via the fastmcp client.  This lets the planner route to MCP
    tools the same way it routes to native agents.

    The function is silent on any import/connectivity errors — MCP tools are
    best-effort at build_registry() time.
    """
    try:
        from kendr.capability_sync import sync_mcp_capabilities
        sync_mcp_capabilities(workspace_id="default", actor_user_id="system:discovery")
    except Exception as exc:
        _handle_discovery_error(
            registry,
            source="mcp_capability_sync",
            target="kendr.capability_sync.sync_mcp_capabilities",
            exc=exc,
            strict=strict,
        )

    try:
        from kendr.mcp_manager import list_servers as _mcp_list_servers
    except Exception as exc:
        _handle_discovery_error(
            registry,
            source="mcp_registry",
            target="kendr.mcp_manager.list_servers",
            exc=exc,
            strict=strict,
        )
        return

    try:
        servers = _mcp_list_servers()
    except Exception as exc:
        _handle_discovery_error(
            registry,
            source="mcp_registry",
            target="kendr.mcp_manager.list_servers()",
            exc=exc,
            strict=strict,
        )
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
        auth_token = server.get("auth_token", "")

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
            _auth_token_captured = auth_token
            _tool_schema_captured = tool.get("schema", {})

            def _make_handler(
                tname: str,
                conn: str,
                stype: str,
                sname: str,
                tok: str,
                schema: dict,
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
                        try:
                            tool_input = _json.loads(tool_input) if tool_input else {}
                        except Exception:
                            tool_input = {}

                    if not tool_input and isinstance(schema, dict):
                        props = schema.get("properties") or {}
                        candidate: dict = {}
                        for prop_name in props:
                            for key in (
                                prop_name,
                                f"mcp_{prop_name}",
                                f"{tname}_{prop_name}",
                                f"{sname}_{prop_name}",
                            ):
                                val = state.get(key)
                                if val is not None:
                                    candidate[prop_name] = val
                                    break
                        if candidate:
                            tool_input = candidate

                    async def _call():
                        import shlex as _shlex
                        client_kwargs: dict = {}
                        if stype == "stdio":
                            from fastmcp.client.transports.stdio import StdioTransport as _StdioTransport
                            try:
                                parts = _shlex.split(conn)
                            except Exception:
                                parts = conn.split()
                            if not parts:
                                parts = [conn]
                            transport = _StdioTransport(command=parts[0], args=parts[1:])
                        else:
                            transport = conn
                            if tok:
                                client_kwargs = {"headers": {"Authorization": f"Bearer {tok}"}}
                        async with _MCPClient(transport, timeout=30, **client_kwargs) as client:
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
                        surfaces = state.setdefault("used_execution_surfaces", [])
                        if isinstance(surfaces, list):
                            surfaces.append({
                                "kind": "mcp",
                                "server": sname,
                                "tool": tname,
                                "label": f"{sname}/{tname}",
                            })
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
                _auth_token_captured,
                _tool_schema_captured,
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
                        "connector_type": "mcp_tool",
                        "mcp_tool": True,
                        "mcp_server_id": server_id,
                        "mcp_server_name": server_name,
                        "mcp_tool_name": tool_name,
                        "mcp_connection": connection,
                    },
                )
            )


def _register_skill_agents(registry: Registry, *, strict: bool = False) -> None:
    """Register installed user skills as synthetic ``skill_*_agent`` nodes.

    Each installed skill becomes an ``AgentDefinition`` whose handler calls
    ``execute_skill_by_slug(slug, inputs)``.  This mirrors the MCP tool pattern
    so the orchestrator can route to skills the same way it routes to any agent.

    The function is silent on errors — skills are best-effort at registry time.
    """
    try:
        from kendr.skill_manager import list_runtime_skills as _list_skills
    except Exception as exc:
        _handle_discovery_error(
            registry,
            source="skill_registry",
            target="kendr.skill_manager.list_runtime_skills",
            exc=exc,
            strict=strict,
        )
        return

    try:
        skills = _list_skills()
    except Exception as exc:
        _handle_discovery_error(
            registry,
            source="skill_registry",
            target="kendr.skill_manager.list_runtime_skills()",
            exc=exc,
            strict=strict,
        )
        return

    if not skills:
        return

    plugin_name = "builtin.skills"
    registry.register_plugin(
        PluginDefinition(
            name=plugin_name,
            source="skills",
            description="Synthetic agents for each installed user skill.",
        )
    )

    for skill in skills:
        slug = str(skill.get("slug", "")).strip()
        if not slug:
            continue

        safe_slug = "".join(c if c.isalnum() else "_" for c in slug.lower()).strip("_")
        agent_name = f"skill_{safe_slug}_agent"
        display_name = str(skill.get("name", slug))
        description = (str(skill.get("description", "") or "")).strip() or f"Skill: {display_name}"
        category = str(skill.get("category", "Custom"))
        skill_type = str(skill.get("skill_type", ""))
        icon = str(skill.get("icon", "⚡"))

        _slug_captured = slug

        def _make_skill_handler(slug_: str, name_: str):
            def _skill_agent_handler(state: dict) -> dict:
                import json as _json
                try:
                    from kendr.skill_manager import execute_skill_by_slug as _exec
                except ImportError:
                    state["skill_error"] = "kendr.skill_manager not available"
                    return state

                # Accept inputs from specific key, generic key, or task_content
                raw = (
                    state.get(f"skill_inputs_{slug_}")
                    or state.get("skill_inputs")
                    or {}
                )
                if isinstance(raw, str):
                    try:
                        raw = _json.loads(raw)
                    except Exception:
                        raw = {"input": raw}
                if not isinstance(raw, dict):
                    raw = {}

                result = _exec(slug_, raw, session_id=str(state.get("session_id", "") or ""))
                state["skill_result"] = result
                state["skill_slug"] = slug_
                state[f"skill_result_{slug_}"] = result
                surfaces = state.setdefault("used_execution_surfaces", [])
                if isinstance(surfaces, list):
                    surfaces.append({
                        "kind": "skill",
                        "skill": slug_,
                        "label": str(result.get("source_surface") or f"skill:{slug_}"),
                    })

                if result.get("error_type") == "approval_required":
                    state["awaiting_user_input"] = True
                    state["pending_user_input_kind"] = str(result.get("pending_user_input_kind", "") or "skill_approval").strip()
                    state["approval_pending_scope"] = str(result.get("approval_pending_scope", "") or f"skill_permission:{slug_}").strip()
                    state["approval_request"] = result.get("approval_request", {}) if isinstance(result.get("approval_request"), dict) else {}
                    state["pending_user_question"] = str(result.get("pending_user_question", "") or "").strip()
                    state["skill_output"] = state["pending_user_question"] or f"Approval required to run skill '{slug_}'."
                elif result.get("success"):
                    output = result.get("output") or result.get("stdout", "")
                    if not isinstance(output, str):
                        output = _json.dumps(output, ensure_ascii=False, indent=2)
                    state["skill_output"] = output
                else:
                    state["skill_output"] = f"Skill '{slug_}' error: {result.get('error', 'Unknown error')}"

                return state

            _skill_agent_handler.__name__ = f"skill_{slug_}_handler"
            return _skill_agent_handler

        handler = _make_skill_handler(_slug_captured, display_name)

        registry.register_agent(
            AgentDefinition(
                name=agent_name,
                handler=handler,
                description=f"{icon} {description} (type={skill_type}, category={category})",
                skills=[safe_slug, "skill", skill_type, category.lower()],
                input_keys=[f"skill_inputs_{slug}", "skill_inputs"],
                output_keys=["skill_result", "skill_output", f"skill_result_{slug}"],
                plugin_name=plugin_name,
                requirements=[],
                metadata={
                    "connector_type": "skill",
                    "skill_agent": True,
                    "skill_slug": slug,
                    "skill_type": skill_type,
                    "skill_category": category,
                    "skill_icon": icon,
                },
            )
        )


def build_registry(options: DiscoveryOptions | None = None, *, strict: bool | None = None) -> Registry:
    options = options or DiscoveryOptions()
    strict_mode = options.strict if strict is None else strict
    registry = Registry()
    _register_builtin_capabilities(registry)
    if options.discover_builtin_task_agents:
        _discover_builtin_task_agents(registry, strict=strict_mode)
    if options.discover_external_plugins:
        _discover_external_plugins(registry, strict=strict_mode)
    if options.discover_mcp_tools:
        _register_mcp_tools(registry, strict=strict_mode)
    if options.discover_skill_agents:
        _register_skill_agents(registry, strict=strict_mode)
    return registry
