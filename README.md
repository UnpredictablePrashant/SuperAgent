<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/kendr-logo-dark.svg">
    <img src="docs/assets/kendr-logo-light.svg" alt="Kendr" width="720">
  </picture>
</p>

# Kendr

> Open-source multi-agent intelligence CLI for evidence-driven research, knowledge management, and software project generation.

Kendr is a terminal-first Python runtime that combines specialized agents, web and local evidence, durable memory, and structured run artifacts. It is built for intelligence work that needs traceability, synthesis, and reusable context — all from the command line.

[Quickstart](docs/quickstart.md) · [CLI Reference](docs/cli.md) · [Configuration](docs/configuration.md) · [Integrations](docs/integrations.md) · [Examples](SampleTasks.md)

---

## What You Can Do With Kendr

Kendr provides five distinct capability areas, each accessible as a CLI command:

| # | Capability | Command | Status |
|---|---|---|---|
| 1 | **Deep research with document generation** | `kendr run` / `kendr research` | Stable |
| 2 | **Multi-agent software project generation** | `kendr generate` | Beta |
| 3 | **Zero-config SuperRAG knowledge engine** | `kendr run --superrag-mode` | Stable |
| 4 | **Local command execution with auto-install** | `kendr run --os-command` / `--dev` | Beta |
| 5 | **Unified communication suite** | `kendr run --communication-authorized` | Beta |

Everything is CLI-based. There is no web dashboard.

---

## Quickstart

**1. Install:**

```bash
git clone https://github.com/your-org/kendr.git
cd kendr
pip install -e .
```

**2. Set the two required variables:**

```bash
kendr setup set openai OPENAI_API_KEY sk-...
kendr setup set core_runtime KENDR_WORKING_DIR /absolute/path/to/workdir
```

Or set them in `.env` (copy from `.env.example`).

**3. Start the gateway:**

```bash
kendr gateway start
```

The gateway is required before `kendr run`, `kendr research`, or `kendr generate`. Start it once — it stays running in the background.

**4. Check setup:**

```bash
kendr setup status
```

**5. Run your first query:**

```bash
kendr run --current-folder \
  "Create an intelligence brief on Stripe: business model, products, competitors, recent strategy moves, and top risks."
```

See [Quickstart](docs/quickstart.md) for a full walkthrough including what output to expect.

---

## Install and Verify

Linux or macOS:

```bash
./scripts/install.sh
python scripts/verify.py
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
python .\scripts\verify.py
```

Manual:

```bash
pip install -e ".[dev]"
python scripts/bootstrap_local_state.py
python scripts/verify.py smoke
```

---

## Capability Highlights

### 1. Deep Research and Document Generation

Multi-source research that synthesizes web, academic, patent, and local evidence into structured reports.

```bash
# Research brief
kendr run --current-folder "Analyze the AI chip market: key players, supply chain, and investment outlook."

# Select specific sources
kendr run --sources arxiv,web,reddit --pages 20 "AI safety research landscape 2024"

# Via the dedicated research command
kendr research --sources arxiv,web --pages 15 --title "Quantum ML Survey" \
  "Advances in quantum machine learning"

# Long-form staged document (50+ pages)
kendr run --long-document --long-document-pages 50 --long-document-sections 10 \
  --long-document-title "Global Gold Market Intelligence Dossier" \
  "Produce an exhaustive investment-grade global gold market report."
```

### 2. Multi-Agent Software Project Generation

Blueprint → scaffold → build → test → verify → zip export, fully automated.

```bash
# Generate a project with a specific stack
kendr generate --stack fastapi_postgres \
  "A task management REST API with user auth, tests, and Docker deployment."

# Full-stack web app
kendr generate --stack fastapi_react_postgres \
  "SaaS starter with billing, admin dashboard, and CI/CD."

# Via run with --dev flag
kendr run --dev --stack nextjs_prisma_postgres \
  "A blog platform with markdown, auth, and CDN image handling."
```

Available stacks: `fastapi_postgres`, `fastapi_react_postgres`, `nextjs_prisma_postgres`, `express_prisma_postgres`, `mern_microservices_mongodb`, `pern_postgres`, `nextjs_static_site`, `django_react_postgres`, `custom_freeform`.

### 3. Zero-Config SuperRAG Knowledge Engine

Index local files, URLs, databases, and OneDrive content into a persistent knowledge session. ChromaDB is the default vector backend — no setup required.

```bash
# Build a knowledge session
kendr run \
  --superrag-mode build \
  --superrag-new-session \
  --superrag-session-title "product_docs" \
  --superrag-path ./docs \
  --superrag-url https://example.com/help \
  "Index our product documentation."

# Chat with the session
kendr run \
  --superrag-mode chat \
  --superrag-session product_docs \
  --superrag-chat "What are the installation requirements?"

# Index a database
kendr run \
  --superrag-mode build \
  --superrag-session ops_db \
  --superrag-db-url "postgresql://user:pass@host/db" \
  "Scan and index this database."
```

For production use with shared persistence, opt in to Qdrant by setting `QDRANT_URL`.

### 4. Local Command Execution and Dev Pipeline

Controlled shell execution with audit trails, approval gates, and optional auto-install of missing tools.

```bash
# Execute a shell command with approval
kendr run --current-folder \
  --os-command "df -h" --os-shell bash \
  --privileged-approved --privileged-approval-note "OPS-42 approved" \
  "Check disk usage."

# Full dev pipeline mode
kendr run --dev --stack fastapi_postgres \
  "Build a production-ready FastAPI application."
```

### 5. Unified Communication Suite

Fetch and summarize messages from all configured channels in a single briefing.

```bash
# Morning digest across all channels
kendr run \
  --communication-authorized \
  "Summarize my communications across all channels from the last 24 hours."

# Custom lookback window
kendr run \
  --communication-authorized \
  --communication-lookback-hours 8 \
  "What did I miss on Slack and Gmail in the last 8 hours?"

# Send a WhatsApp message
kendr run \
  --communication-authorized \
  --whatsapp-to "+15551234567" \
  --whatsapp-message "Your briefing is ready." \
  "Send a WhatsApp notification."
```

---

## Feature Status Matrix

| Status | Areas | What It Means |
|---|---|---|
| **Stable** | Core CLI and runtime, setup-aware routing, local-drive intelligence, report synthesis, SuperRAG knowledge sessions | Best place for new users to start |
| **Beta** | OpenAI deep research, long-document generation, multi-agent project generation, gateway HTTP surface, unified communication suite, AWS workflows, authorized security workflows | Implemented and usable; more sensitive to environment and configuration |
| **Experimental** | Dynamic agent factory, generated agents, voice/audio workflows | Present or scaffolded; not part of the primary product promise |

---

## Gateway Lifecycle

The HTTP gateway (`kendr gateway start`) is **on-demand only**. It is never auto-started by `kendr run`, `kendr research`, or `kendr generate`. Start it explicitly when you need the REST API surface or session routing for communication channels.

```bash
kendr gateway start
kendr gateway status
kendr gateway stop
```

---

## Docs

- [Quickstart](docs/quickstart.md) — install, configure, first run
- [CLI Reference](docs/cli.md) — every subcommand and flag
- [Configuration](docs/configuration.md) — every env var with defaults and examples
- [Integrations](docs/integrations.md) — vector backends (ChromaDB / Qdrant), communication providers, security tools
- [Agents](docs/agents.md) — workflow families and the full agent inventory
- [Architecture](docs/architecture.md) — runtime flow, discovery, persistence
- [Security](docs/security.md) — safety boundaries and privileged controls
- [Examples](SampleTasks.md) — copy-paste CLI examples for every workflow
- [Troubleshooting](docs/troubleshooting.md) — common first-run issues

---

## Contribute

- [CONTRIBUTING.md](CONTRIBUTING.md)
- [CHANGELOG.md](CHANGELOG.md)
- [RELEASING.md](RELEASING.md)
- [SECURITY.md](SECURITY.md)

Contribution baseline:

- keep changes grounded in real code and verified workflows
- preserve setup-aware gating and runtime behavior unless fixing a bug
- update tests and docs with user-facing changes
- run `python scripts/verify.py` before opening a PR

---

## Under the Hood

- multi-agent orchestration runtime in [`kendr/runtime.py`](kendr/runtime.py)
- dynamic agent registry and discovery in [`kendr/discovery.py`](kendr/discovery.py)
- CLI entrypoint in [`kendr/cli.py`](kendr/cli.py)
- rich terminal output and spinners in [`kendr/cli_output.py`](kendr/cli_output.py)
- setup and integration catalog in [`kendr/setup/`](kendr/setup)
- durable SQLite persistence in [`kendr/persistence/`](kendr/persistence)
- multi-source research infrastructure in [`tasks/research_infra.py`](tasks/research_infra.py)
- optional HTTP gateway in [`kendr/gateway_server.py`](kendr/gateway_server.py)
- MCP server endpoints in [`mcp_servers/`](mcp_servers)
