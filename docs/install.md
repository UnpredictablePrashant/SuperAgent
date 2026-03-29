# Install

This guide covers local setup, environment configuration, Docker services, and verification commands.

## Runtime Requirements

- Python 3.10 or newer
- network access for configured APIs
- optional Docker for Qdrant and MCP services

## Environment Baseline

Start from `.env.example`.

Required for the core runtime:

- `OPENAI_API_KEY`
- `KENDR_WORKING_DIR`

Recommended:

- `OPENAI_MODEL_GENERAL`
- `OPENAI_MODEL_CODING`
- `OPENAI_VISION_MODEL`
- `OPENAI_EMBEDDING_MODEL`
- `QDRANT_URL`
- `QDRANT_COLLECTION`
- `RESEARCH_USER_AGENT`
- `KENDR_HOME`
- `KENDR_PLUGIN_PATHS`

Workflow-specific or optional:

- `SERP_API_KEY`
- `ELEVENLABS_API_KEY`
- `GOOGLE_*`
- `SLACK_*`
- `MICROSOFT_*`
- `TELEGRAM_*`
- `WHATSAPP_*`
- `AWS_*`
- `NVD_API_KEY`

See [Integrations](integrations.md) for provider-specific details.
Use [Integration Checklist](integration_checklist.md) when adding new integrations.

## Local Installation

### Linux Or macOS

```bash
./scripts/install.sh
```

This script:

- creates `.venv` if needed
- installs the package in editable mode
- bootstraps local runtime state
- adds `.venv/bin` to your shell path

### Windows PowerShell

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

Preferred Chocolatey-assisted flow:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_choco.ps1
```

### Manual Install

```bash
python3 -m pip install -e ".[dev]"
python3 scripts/bootstrap_local_state.py
```

## Setup Commands

Inspect setup:

```bash
kendr setup status
kendr setup components
```

Set values in the local setup store:

```bash
kendr setup set core_runtime KENDR_WORKING_DIR /absolute/path/to/workdir
kendr setup set openai OPENAI_API_KEY sk-...
kendr setup set openai OPENAI_MODEL_GENERAL gpt-4.1-mini
```

Open the setup UI:

```bash
kendr setup ui
```

Export stored values as dotenv lines:

```bash
kendr setup export-env
kendr setup export-env --include-secrets
```

## Running Locally

Basic run:

```bash
kendr run --current-folder "Create a short research brief on OpenAI."
```

Gateway:

```bash
kendr gateway
```

Daemon:

```bash
kendr daemon
kendr daemon --once
```

Setup UI:

```bash
kendr setup ui
```

## Docker Stack

Start the Compose stack:

```bash
docker compose up --build
```

Compose currently includes:

- `qdrant`
- `app`
- `daemon`
- `gateway`
- `setup-ui`
- `research-mcp`
- `vector-mcp`
- `nmap-mcp`
- `zap-mcp`
- `screenshot-mcp`
- `http-fuzzing-mcp`
- `cve-mcp`

Docker is optional for local CLI use, but useful when you want the fuller Qdrant and MCP service stack.

## Verification Commands

Basic command checks:

```bash
kendr --help
kendr agents list
kendr plugins list
kendr setup status
```

Repository verification entrypoints:

```bash
python3 scripts/verify.py
python3 scripts/verify.py smoke
python3 scripts/verify.py docker
```

If `make` is available on your machine, the repo also defines:

```bash
make compile
make unit
make smoke
make docs-check
make verify
make ci
```

See [Verification](verification.md) for the exact phase definitions and CI-local parity.

## Uninstall

Linux or macOS:

```bash
./scripts/uninstall.sh
```

Windows:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall.ps1
```
