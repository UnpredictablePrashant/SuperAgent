# Integration Checklist

Use this checklist when adding or changing any provider, channel, local tool, or service integration.

An integration is only complete when the same contract is wired through every stage below.

## Lifecycle Contract

1. Declaration
   Add the integration to [`kendr/setup/catalog.py`](../kendr/setup/catalog.py) with:
   - stable `id`
   - title/category/description
   - setup fields
   - auth mode
   - setup hint
   - docs path
   - detection inputs such as env vars, OAuth token store, local command, or health URL

2. Configuration
   Make sure the integration appears through `kendr setup components` via [`tasks/setup_config_store.py`](../tasks/setup_config_store.py).
   Required env keys must exist in [`.env.example`](../.env.example) when users are expected to set them directly.

3. Setup Detection
   Detection and health must be implemented in [`tasks/setup_registry.py`](../tasks/setup_registry.py) from the catalog contract, not as a one-off branch elsewhere.

4. Health Reporting
   `build_setup_snapshot()` must report:
   - `configured`
   - `enabled`
   - `status`
   - `health.detail`
   - `setup_hint`
   - `docs_path`

5. Routing Eligibility
   Agents must declare integration requirements in `AGENT_METADATA["<agent>"]["requirements"]`.
   If a legacy fallback is temporarily needed, add it deliberately and remove it later.
   Unconfigured integrations must not leave dependent agents in `available_agents`.

6. Discovery
   If the integration is a provider or channel, discovery must read it from the catalog instead of duplicating declarations elsewhere.

7. Docs
   Update:
   - [README](../README.md)
   - [Install](install.md)
   - [Integrations](integrations.md)
   - [SampleTasks](../SampleTasks.md) when user workflows depend on the new setup

8. Tests
   Add or update tests for:
   - setup snapshot detection
   - disabled/missing dependency handling
   - setup-aware routing eligibility
   - registry/discovery metadata when relevant

## Review Questions

- Does the integration have one canonical `id` across setup, detection, routing, and docs?
- Can a user tell exactly what to configure from docs and `.env.example`?
- Does `kendr setup status` explain why the integration is unavailable?
- Are dependent agents hidden from routing when the integration is missing or disabled?
- Is there at least one regression test covering that behavior?
