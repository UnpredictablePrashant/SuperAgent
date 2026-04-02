from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


StateHandler = Callable[[dict], dict]
PLUGIN_SDK_VERSION = "1.0"
PLUGIN_RUNTIME_API = "registry-v1"


@dataclass(slots=True)
class AgentDefinition:
    name: str
    handler: StateHandler
    description: str
    skills: list[str] = field(default_factory=list)
    input_keys: list[str] = field(default_factory=list)
    output_keys: list[str] = field(default_factory=list)
    plugin_name: str = "builtin"
    requirements: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class ChannelDefinition:
    name: str
    description: str
    plugin_name: str = "builtin"
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class ProviderDefinition:
    name: str
    description: str
    auth_mode: str = "api_key"
    plugin_name: str = "builtin"
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class PluginDefinition:
    name: str
    source: str
    description: str = ""
    version: str = "0.1.0"
    sdk_version: str = PLUGIN_SDK_VERSION
    runtime_api: str = PLUGIN_RUNTIME_API
    entry_point: str = "register"
    kind: str = "builtin"
    metadata: dict = field(default_factory=dict)


@dataclass(slots=True)
class PluginManifest:
    name: str
    description: str = ""
    version: str = "0.1.0"
    sdk_version: str = PLUGIN_SDK_VERSION
    runtime_api: str = PLUGIN_RUNTIME_API
    entry_point: str = "register"
    compatible_core: str = ""
    capabilities: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)

    @classmethod
    def from_mapping(cls, payload: dict | None, *, default_name: str) -> "PluginManifest":
        raw = payload if isinstance(payload, dict) else {}
        metadata = raw.get("metadata", {})
        return cls(
            name=str(raw.get("name", default_name)).strip() or default_name,
            description=str(raw.get("description", "")).strip(),
            version=str(raw.get("version", "0.1.0")).strip() or "0.1.0",
            sdk_version=str(raw.get("sdk_version", PLUGIN_SDK_VERSION)).strip() or PLUGIN_SDK_VERSION,
            runtime_api=str(raw.get("runtime_api", PLUGIN_RUNTIME_API)).strip() or PLUGIN_RUNTIME_API,
            entry_point=str(raw.get("entry_point", "register")).strip() or "register",
            compatible_core=str(raw.get("compatible_core", "")).strip(),
            capabilities=[
                str(item).strip()
                for item in raw.get("capabilities", [])
                if str(item).strip()
            ],
            metadata=metadata if isinstance(metadata, dict) else {},
        )

    def to_plugin_definition(self, *, source: str, kind: str = "external") -> PluginDefinition:
        extra_metadata = dict(self.metadata)
        if self.compatible_core:
            extra_metadata.setdefault("compatible_core", self.compatible_core)
        if self.capabilities:
            extra_metadata.setdefault("capabilities", list(self.capabilities))
        return PluginDefinition(
            name=self.name,
            source=source,
            description=self.description,
            version=self.version,
            sdk_version=self.sdk_version,
            runtime_api=self.runtime_api,
            entry_point=self.entry_point,
            kind=kind,
            metadata=extra_metadata,
        )
