<p align="center">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="docs/assets/kendr-logo-dark.svg">
    <img src="docs/assets/kendr-logo-light.svg" alt="Kendr" width="720">
  </picture>
</p>

<p align="center">
  <a href="https://github.com/UnpredictablePrashant/Kendr/releases"><img src="https://img.shields.io/badge/version-0.2.0-teal" alt="Version"></a>
  <a href="https://www.python.org/downloads/"><img src="https://img.shields.io/badge/python-3.10%2B-blue" alt="Python 3.10+"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License"></a>
</p>

<p align="center">
  <a href="https://github.com/UnpredictablePrashant/Kendr/stargazers"><img src="https://img.shields.io/github/stars/UnpredictablePrashant/Kendr" alt="GitHub stars" /></a>
  <a href="https://github.com/UnpredictablePrashant/Kendr/network/members"><img src="https://img.shields.io/github/forks/UnpredictablePrashant/Kendr" alt="GitHub forks" /></a>
  <a href="https://github.com/UnpredictablePrashant/Kendr/watchers"><img src="https://img.shields.io/github/watchers/UnpredictablePrashant/Kendr" alt="GitHub watchers" /></a>
  <a href="https://github.com/UnpredictablePrashant/Kendr/issues"><img src="https://img.shields.io/github/issues/UnpredictablePrashant/Kendr" alt="GitHub issues" /></a>
  <a href="https://github.com/UnpredictablePrashant/Kendr/actions"><img src="https://img.shields.io/github/actions/workflow/status/UnpredictablePrashant/Kendr/ci.yml?branch=main" alt="GitHub workflow" /></a>
  <a href="https://discord.gg/GgU8UEdn"><img src="https://img.shields.io/badge/discord-join-blue?logo=discord" alt="Discord" /></a>
</p>

# Kendr

> Open-source multi-agent intelligence platform — Web UI + CLI for research, project management, and software automation.

Kendr is a Python runtime that combines specialized AI agents, a web-based chat and project UI, multi-source research, durable memory, and structured run artifacts. Use it from the browser or the terminal.

[Quickstart](docs/quickstart.md) · [CLI Reference](docs/cli.md) · [Configuration](docs/configuration.md) · [Integrations](docs/integrations.md) · [Examples](SampleTasks.md)

---

## Install

### Desktop installers

If you want a ready-to-install desktop app, use the platform artifacts published on the
[GitHub Releases](https://github.com/UnpredictablePrashant/Kendr/releases) page:

- **Windows**: `Kendr Setup <version>.exe`
- **macOS**: `Kendr-<version>-mac-*.dmg`
- **Linux**: `Kendr-<version>.AppImage` or `kendr-desktop_<version>_amd64.deb`

These desktop builds bundle the Kendr backend, so users do **not** need to preinstall Python just to launch the app.

---

### Requirements

- **Python 3.10 or newer** — [python.org/downloads](https://python.org/downloads)
- **Git** — [git-scm.com](https://git-scm.com)
- An **OpenAI API key** (or Anthropic / Google / local Ollama — see [LLM Providers](#llm-providers) below)

---

### macOS / Linux — one command

```bash
git clone https://github.com/UnpredictablePrashant/Kendr.git
cd Kendr
./scripts/install.sh
```

After it finishes, reload your shell and run `kendr --help` to confirm the install:

```bash
source ~/.zshrc     # zsh (macOS default)
# or
source ~/.bashrc    # bash (Linux default)

kendr --help
```

---

### Windows — PowerShell

Open **PowerShell** (not CMD) and run:

```powershell
git clone https://github.com/UnpredictablePrashant/Kendr.git
cd Kendr
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

Open a **new terminal** after the script finishes, then verify:

```powershell
kendr --help
```

---

### Manual install (any platform)

If you prefer to control the environment yourself:

```bash
git clone https://github.com/UnpredictablePrashant/Kendr.git
cd Kendr

# Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate       # macOS/Linux
# .venv\Scripts\activate        # Windows PowerShell

# Install kendr
pip install -e .

# Verify
kendr --help
```

---

### Install with pip (no git clone)

If you just want the package without cloning the repo:

```bash
pip install kendr-runtime
kendr --help
```

> **Note:** Running `kendr ui` from a pip install requires the repo to be present for the HTML assets. Clone + install is recommended for the full experience.

---

### Build desktop installers from source

Release builders need **Node.js 18+** and **Python 3.10+**. Then run:

```bash
./scripts/build-release.sh        # macOS / Linux
powershell -ExecutionPolicy Bypass -File .\scripts\build-release.ps1   # Windows
```

The build output lands in `electron-app/dist/`.

---

## LLM Providers

Kendr ships with **OpenAI** by default. Install optional packages to add more providers:

| Provider | Install command | Models |
|---|---|---|
| **OpenAI** *(default)* | included | GPT-4o, GPT-4o-mini, o1, o3 |
| **Anthropic Claude** | `pip install 'kendr-runtime[anthropic]'` | claude-3-5-sonnet, claude-opus |
| **Google Gemini** | `pip install 'kendr-runtime[google]'` | gemini-2.0-flash, gemini-1.5-pro |
| **Local Ollama** | `pip install 'kendr-runtime[ollama]'` | llama3, mistral, phi3, … |
| **All of the above** | `pip install 'kendr-runtime[full]'` | everything |

Or use the install script with `--full`:

```bash
./scripts/install.sh --full          # macOS/Linux
.\scripts\install.ps1 -Full         # Windows
```

---

## First-Time Setup

After installing, set two required values:

```bash
# Your LLM API key
kendr setup set openai OPENAI_API_KEY sk-...

# Where kendr writes output files
kendr setup set core_runtime KENDR_WORKING_DIR ~/kendr-work

# Check everything is configured
kendr setup status
```

Or copy `.env.example` to `.env` and fill in the values manually.

---

## Launch the Web UI

```bash
kendr ui
# or the shorter alias:
kendr web
```

Opens the web interface at **http://localhost:5000** with:

- **Chat** — multi-agent chat with streaming output and plan cards
- **Projects** — open any local code project, chat with an AI that understands your codebase, manage files, run terminal commands, view git status
- **Setup & Config** — configure API keys and LLM providers in the browser
- **Run History** — browse every past run and its output artifacts
- **LLM Models** — view and switch between available models

---

## CLI Quick Reference

```bash
# Research
kendr run "Analyse the AI chip market: key players, supply chain, investment outlook."
kendr research --sources arxiv,web --pages 15 "Advances in LLM reasoning 2024"

# Software project generation
kendr generate --stack fastapi_postgres "Task management API with auth and tests."
kendr generate --stack nextjs_prisma_postgres "Blog platform with markdown and auth."

# SuperRAG knowledge sessions
kendr run --superrag-mode build --superrag-new-session --superrag-session-title "docs" \
  --superrag-path ./docs "Index my documentation."
kendr run --superrag-mode chat --superrag-session docs "What are the install requirements?"

# Shell command execution (with approval gate)
kendr run --os-command "df -h" --os-shell bash --privileged-approved "Check disk usage."

# Gateway (required for communication integrations and REST API)
kendr gateway start
kendr gateway status
kendr gateway stop
```

---

## What You Can Do

| # | Capability | Entry point | Status |
|---|---|---|---|
| 1 | **Web UI** — chat, projects, config, history | `kendr ui` | Stable |
| 2 | **Deep research + document generation** | `kendr run` / `kendr research` | Stable |
| 3 | **Multi-agent project generation** | `kendr generate` | Beta |
| 4 | **SuperRAG knowledge engine** | `kendr run --superrag-mode` | Stable |
| 5 | **Local command execution** | `kendr run --os-command` | Beta |
| 6 | **Unified communication suite** | `kendr run` | Beta |

---

## Feature Status Matrix

| Status | Areas |
|---|---|
| **Stable** | Web UI, core CLI, setup-aware routing, SuperRAG sessions, research synthesis, local-drive intelligence |
| **Beta** | Project generation, long-document pipeline, gateway HTTP surface, communication suite, AWS workflows |
| **Experimental** | Dynamic agent factory, generated agents, voice/audio workflows |

---

## Capability Highlights

### Web UI and Project Workspace

```bash
kendr ui
# → http://localhost:5000
```

The web interface gives you a full project workspace:
- Open any local Git repository and chat with the AI about your code
- Auto-generates a `kendr.md` project context file if one doesn't exist
- Model selector and live context-window usage bar in the chat input
- File browser, integrated terminal, and git status panel
- Recent chat history per project

### Deep Research and Document Generation

Multi-source research that synthesises web, academic, patent, and local evidence into structured reports.

```bash
kendr run --current-folder \
  "Create an intelligence brief on Stripe: business model, competitors, strategy, risks."

kendr run --long-document --long-document-pages 50 \
  "Produce an exhaustive global gold market investment report."
```

### Multi-Agent Software Project Generation

Blueprint → scaffold → build → test → verify → zip export, fully automated.

```bash
kendr generate --stack fastapi_react_postgres \
  "SaaS starter with billing, admin dashboard, and CI/CD."
```

Available stacks: `fastapi_postgres`, `fastapi_react_postgres`, `nextjs_prisma_postgres`, `express_prisma_postgres`, `mern_microservices_mongodb`, `pern_postgres`, `nextjs_static_site`, `django_react_postgres`, `custom_freeform`.

### SuperRAG Knowledge Engine

Zero-config vector search over local files, URLs, databases, and OneDrive content.

```bash
kendr run --superrag-mode build --superrag-new-session \
  --superrag-session-title "product_docs" --superrag-path ./docs \
  "Index our documentation."

kendr run --superrag-mode chat --superrag-session product_docs \
  --superrag-chat "What are the installation requirements?"
```

---

## Docs

- [Quickstart](docs/quickstart.md) — install, configure, first run
- [CLI Reference](docs/cli.md) — every subcommand and flag
- [Configuration](docs/configuration.md) — every environment variable
- [Integrations](docs/integrations.md) — vector backends, communication providers, security tools
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
- preserve setup-aware gating and runtime behaviour unless fixing a bug
- update tests and docs with user-facing changes
- run `python scripts/verify.py` before opening a PR

---

## Community

- Join the **Kendr Discord** community for live chat, collaboration, Q&A, and announcements: [https://discord.gg/GgU8UEdn](https://discord.gg/GgU8UEdn)
- Track ongoing work, open issues/feedback, and CI results on the [GitHub project view](https://github.com/UnpredictablePrashant/Kendr)
- The badges above pull live GitHub metrics (stars, forks, watchers, issues, workflows + more) so you can see how the project is performing in real time.

## Contributors

<p align="center">
  <a href="https://github.com/UnpredictablePrashant/Kendr/graphs/contributors"><img src="https://contrib.rocks/image?repo=UnpredictablePrashant/Kendr" alt="Top contributors" /></a>
</p>

Names and avatars shown above are generated automatically from GitHub contributions, so the list reflects the latest community participation without manual updates.

---

## Under the Hood

- multi-agent orchestration runtime in [`kendr/runtime.py`](kendr/runtime.py)
- web UI server (chat + project workspace) in [`kendr/ui_server.py`](kendr/ui_server.py)
- CLI entrypoint in [`kendr/cli.py`](kendr/cli.py)
- dynamic agent registry and discovery in [`kendr/discovery.py`](kendr/discovery.py)
- multi-provider LLM routing in [`kendr/llm_router.py`](kendr/llm_router.py)
- project context management in [`kendr/project_context.py`](kendr/project_context.py)
- rich terminal output in [`kendr/cli_output.py`](kendr/cli_output.py)
- setup and integration catalog in [`kendr/setup/`](kendr/setup)
- durable SQLite persistence in [`kendr/persistence/`](kendr/persistence)
- multi-source research infrastructure in [`tasks/research_infra.py`](tasks/research_infra.py)
- optional HTTP gateway in [`kendr/gateway_server.py`](kendr/gateway_server.py)
- MCP server endpoints in [`mcp_servers/`](mcp_servers)
