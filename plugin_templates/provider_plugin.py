from __future__ import annotations

import os

from kendr.types import AgentDefinition, PluginManifest, ProviderDefinition


PLUGIN = PluginManifest(
    name="example.provider",
    description="Example external plugin that registers one provider and one provider-backed agent.",
    version="0.1.0",
    sdk_version="1.0",
    runtime_api="registry-v1",
    capabilities=["provider", "agent"],
    metadata={
        "stable_surfaces": [
            "kendr.types.ProviderDefinition",
            "kendr.types.AgentDefinition",
            "register(registry)",
        ],
        "notes": (
            "External provider plugins are registry-stable, but setup UI/health/routing integration "
            "for custom providers is not yet SDK-stable. This example gates itself with an env var."
        ),
    },
)


def example_provider_agent(state: dict) -> dict:
    api_key = os.getenv("EXAMPLE_PROVIDER_API_KEY", "").strip()
    if not api_key:
        raise ValueError(
            "EXAMPLE_PROVIDER_API_KEY is required for example_provider_agent. "
            "External provider plugins should validate their own runtime prerequisites."
        )
    state["draft_response"] = "example provider plugin executed successfully"
    return state


def register(registry) -> None:
    registry.register_provider(
        ProviderDefinition(
            name="example_provider",
            description="Example provider registered from an external plugin.",
            auth_mode="api_key",
            plugin_name=PLUGIN.name,
            metadata={
                "env": ["EXAMPLE_PROVIDER_API_KEY"],
                "sdk_note": "Custom provider setup/health surfaces are plugin-defined today.",
            },
        )
    )
    registry.register_agent(
        AgentDefinition(
            name="example_provider_agent",
            handler=example_provider_agent,
            description="Example provider-backed agent registered from an external plugin.",
            skills=["example", "provider"],
            input_keys=["user_query"],
            output_keys=["draft_response"],
            plugin_name=PLUGIN.name,
            requirements=[],
            metadata={
                "provider": "example_provider",
                "gating": "Checks EXAMPLE_PROVIDER_API_KEY in the agent itself.",
            },
        )
    )
