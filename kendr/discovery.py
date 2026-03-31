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


def build_registry() -> Registry:
    registry = Registry()
    _register_builtin_capabilities(registry)
    _discover_builtin_task_agents(registry)
    _discover_external_plugins(registry)
    return registry
