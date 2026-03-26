# Verification

This repo now uses one verification entrypoint:

```bash
python scripts/verify.py
```

By default that runs:

- `compile`
- `unit`
- `smoke`
- `docs`

Use this instead of ad hoc `unittest discover` commands.

## Bootstrap

Recommended developer bootstrap:

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

Bootstrap creates local runtime folders and a usable `.env` with:

- `SUPERAGENT_WORKING_DIR=output/workspace`
- `QDRANT_URL=http://127.0.0.1:6333`

Container services still override `QDRANT_URL` to `http://qdrant:6333` inside Docker Compose.

## Verification Buckets

### Unit

Fast logic and persistence checks that do not require external services.

Run:

```bash
python scripts/verify.py unit
```

### Smoke

High-signal surface checks for the shipped developer experience:

- CLI behavior and module entrypoint
- registry discovery
- setup-aware routing
- gateway HTTP surface
- basic `superRAG` flow with stubbed ingestion
- import safety

Run:

```bash
python scripts/verify.py smoke
```

### Docs

Validates local Markdown and HTML docs links, including in-file anchors.

Run:

```bash
python scripts/verify.py docs
```

### Docker

Validates Docker assets without starting the whole stack:

- `docker compose config -q`
- `docker build`

Run:

```bash
python scripts/verify.py docker
```

If Docker is optional on your machine, the phase skips unless you pass `--strict-docker`.

### Integration

Integration checks are intentionally not part of the default verifier yet because they would depend on live external services and credentials.

For CI-style full verification:

```bash
python scripts/verify.py ci --strict-docker
```

## Make Targets

If `make` is available:

```bash
make verify
make unit
make smoke
make docs-check
make docker-smoke
make ci
```

## Current Coverage Summary

Verified by default:

- package importability and module entrypoints
- compileability
- registry discovery and agent-card requirements
- setup-aware routing and dependency gating
- gateway health and registry surfaces
- basic `superRAG` build flow with stubbed vector indexing
- local docs-link integrity
- Docker Compose config validity and Docker image build

Not part of default verification:

- live external API calls
- real OAuth flows
- end-to-end MCP interoperability
- long-running vector indexing against large corpora
- full `docker compose up` runtime behavior
