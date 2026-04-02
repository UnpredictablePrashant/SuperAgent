# Plugin SDK

Kendr supports external plugins as simple Python modules discovered from plugin search paths.

This page defines the versioned contract for external contributors.

## Status

Stable SDK surface in `1.0`:

- single-file Python plugins discovered from plugin search paths
- `register(registry)` as the default plugin entry point
- plugin manifest metadata via `PLUGIN`
- registration through:
  - `kendr.definitions.AgentDefinition`
  - `kendr.definitions.ProviderDefinition`
  - `kendr.definitions.ChannelDefinition`
  - `kendr.definitions.PluginManifest`
- runtime registry visibility through:
  - `kendr plugins list`
  - `kendr agents list`
  - `GET /registry/plugins`
  - `GET /registry/agents`

Internal and not yet SDK-stable:

- direct imports from `tasks.*`
- built-in task-module scanning rules
- runtime state internals beyond the plain `dict` handler input/output shape
- setup UI integration for custom providers
- setup-aware health/routing detection for custom providers

If you build against the stable SDK surface only, your plugin should keep working across normal refactors.

## Search Paths

Kendr discovers external plugins from:

- `./plugins`
- `~/.kendr/plugins`
- any path listed in `KENDR_PLUGIN_PATHS`

Current stable discovery model:

- load `*.py` files from those directories
- import the module
- read optional `PLUGIN`
- call the manifest entry point, defaulting to `register(registry)`

## Versioned Contract

Current contract:

- `sdk_version`: `1.0`
- `runtime_api`: `registry-v1`

Use these in your manifest so contributors and operators can see what your plugin targets.

## Manifest Contract

You can declare `PLUGIN` as either:

- a `kendr.definitions.PluginManifest`
- a plain `dict`

Recommended fields:

```python
from kendr.definitions import PluginManifest

PLUGIN = PluginManifest(
    name="acme.example",
    description="Example Kendr plugin.",
    version="0.1.0",
    sdk_version="1.0",
    runtime_api="registry-v1",
    entry_point="register",
    capabilities=["agent", "provider"],
    metadata={
        "compatible_core": ">=0.1.0",
        "homepage": "https://example.com",
    },
)
```

Manifest expectations:

- `name`: globally unique plugin id
- `version`: plugin version
- `sdk_version`: Kendr SDK contract version
- `runtime_api`: registry/runtime contract family
- `entry_point`: callable invoked with `registry`
- `capabilities`: high-level plugin shapes such as `agent`, `provider`, `channel`
- `metadata`: extra plugin-specific information

## Minimal Agent Plugin

See [plugin_templates/echo_plugin.py](../plugin_templates/echo_plugin.py).

Pattern:

1. define `PLUGIN`
2. implement one or more handlers of shape `def handler(state: dict) -> dict`
3. register `AgentDefinition` instances in `register(registry)`

## Provider Plugin Example

See [plugin_templates/provider_plugin.py](../plugin_templates/provider_plugin.py).

This example is intentionally conservative:

- it registers a provider and a provider-backed agent
- it validates its own env var inside the agent
- it does not assume setup UI or setup-aware routing support for custom providers

That last point matters: custom providers are registry-stable today, but setup detection for them is still plugin-defined rather than first-class in the core setup catalog.

## Stable Registration Patterns

### Agent Plugin

Use `AgentDefinition` when your plugin contributes executable workflow logic.

Recommended:

- set `plugin_name=PLUGIN.name`
- fill `skills`, `input_keys`, and `output_keys`
- keep handler state usage narrow and explicit
- validate your own prerequisites with clear errors

### Provider Plugin

Use `ProviderDefinition` when your plugin contributes a named provider surface.

Recommended:

- expose auth/env expectations in `metadata`
- keep provider-specific setup validation inside the plugin for now
- do not assume the core setup UI will render your provider automatically

### Channel Plugin

Use `ChannelDefinition` when your plugin contributes a custom ingress/egress channel.

This is registry-stable, but end-to-end channel runtime integration is still more advanced than the basic agent/provider plugin path.

## Compatibility Guidance

For contributors:

- pin to `sdk_version="1.0"` and `runtime_api="registry-v1"`
- avoid importing from `tasks.*` unless you are intentionally coupling to repo internals
- treat `kendr.discovery`, `kendr.runtime`, and setup internals as implementation detail
- expose your own compatibility note in `metadata["compatible_core"]`

For maintainers:

- keep `register(registry)` backward compatible for SDK `1.x`
- bump `sdk_version` only when the external plugin contract changes
- prefer additive manifest fields over breaking changes

## Testing Guidance

Recommended plugin test loop:

1. place the plugin under a temporary folder
2. point `KENDR_PLUGIN_PATHS` at that folder
3. call `kendr.discovery.build_registry()`
4. assert your plugin, agents, providers, or channels were registered

Minimal example:

```python
import os
from kendr.discovery import build_registry

os.environ["KENDR_PLUGIN_PATHS"] = "/path/to/my/plugins"
registry = build_registry()

assert "acme.example" in registry.plugins
assert "my_agent" in registry.agents
```

You can also validate the discovery surface from the CLI:

```bash
kendr plugins list --json
kendr agents list --plugin acme.example --json
```

## What A Safe Plugin Should Avoid

- mutating global runtime behavior outside `register(registry)`
- reaching into internal task modules for core control flow
- assuming custom providers will automatically appear in setup status or setup UI
- relying on undocumented runtime state keys without validating them defensively

## Templates

- [plugin_templates/echo_plugin.py](../plugin_templates/echo_plugin.py)
- [plugin_templates/provider_plugin.py](../plugin_templates/provider_plugin.py)
