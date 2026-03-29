# Contributing to Kendr

Kendr is a Python-native, setup-aware multi-agent runtime focused on evidence-driven workflows.

The fastest way to contribute safely is to stay inside the product thesis that the repo already documents:

- deep research
- local-drive intelligence
- `superRAG`
- coding project delivery
- controlled local command execution

If a change broadens scope beyond those workflows, explain why before adding new surface area.

## Before You Start

Read these first:

- [README.md](README.md)
- [docs/index.md](docs/index.md)
- [docs/product_overview.md](docs/product_overview.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/integration_checklist.md](docs/integration_checklist.md)
- [docs/plugin_sdk.md](docs/plugin_sdk.md) if you are extending plugins

## Ground Rules

- Keep claims true and grounded in code that exists in this repo.
- Prefer smaller coherent refactors over broad rewrites.
- Preserve CLI and runtime behavior unless you are fixing a bug.
- Do not expose unconfigured providers or agents to routing.
- Keep tests local and reliable by default. Do not add network-dependent unit tests.
- Document what is stable versus internal whenever you add an extension point.

## Local Setup

Linux or macOS:

```bash
./scripts/install.sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

Manual bootstrap:

```bash
python -m pip install -e ".[dev]"
python scripts/bootstrap_local_state.py
```

## Verification Expectations

Run the default verifier before opening a PR:

```bash
python scripts/verify.py
```

Useful buckets:

- `python scripts/verify.py unit`
- `python scripts/verify.py smoke`
- `python scripts/verify.py docs`
- `python scripts/verify.py docker`

If your change touches one of the shipped workflow surfaces, add or update smoke coverage when practical.

## Change Guidelines

### Product and UX changes

- update the README when the recommended user path changes
- update `docs/core_workflows.md` or `docs/examples.md` when commands or artifacts change
- keep setup instructions concrete, not aspirational

### Integration changes

- update declaration, setup detection, routing eligibility, docs, and tests together
- use [docs/integration_checklist.md](docs/integration_checklist.md)

### Plugin or extension changes

- keep external contracts simple and Python-native
- avoid leaking internal task-module details into public SDK surfaces
- update [docs/plugin_sdk.md](docs/plugin_sdk.md) when the external contract changes

## Pull Requests

Good PRs usually include:

- one clear problem statement
- the smallest coherent implementation that fixes it
- tests or verification notes
- docs updates when the user path changes
- explicit notes on behavior changes and compatibility

If you intentionally leave a large file in place, justify why that boundary is still coherent.

## What Not To Do

- do not add fragile tests that require live third-party services
- do not broaden the public product promise beyond what is verified
- do not rewrite major runtime surfaces in one pass
- do not invent setup flows that are not implemented

## Need A Safer Starting Point?

Start with one of these:

- tighten docs around an existing workflow
- improve setup-aware routing tests
- add missing smoke coverage for a shipped surface
- extract one coherent responsibility from an oversized module
