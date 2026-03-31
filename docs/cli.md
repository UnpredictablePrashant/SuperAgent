# CLI Reference

Complete reference for every `kendr` subcommand and flag. Every command produces colored, structured terminal output via rich. Use `--json` for machine-readable output and `--quiet` to suppress progress messages.

---

## Global Flags

These flags apply to the `kendr` root command and must appear before the subcommand.

| Flag | Description |
|---|---|
| `--no-color` | Disable ANSI colors in all CLI output. |
| `--log-level LEVEL` | Global log verbosity hint for runtime services. Choices: `silent`, `fatal`, `error`, `warn`, `info`, `debug`, `trace`. Sets `KENDR_LOG_LEVEL` environment variable for the run. |
| `-V` / `--version` | Print the current version and exit. |

---

## `kendr run`

Run the multi-agent orchestrator for a single query. This is the primary entry point for all intelligence workflows.

**The gateway is NOT auto-started.** If your query requires the gateway, start it first with `kendr gateway start`.

```bash
kendr run [FLAGS] "your query"
```

### Core Flags

| Flag | Default | Description |
|---|---|---|
| `query` | _(positional)_ | The query or task to execute. |
| `--max-steps N` | `20` | Maximum orchestration steps before the run ends. |
| `--working-directory PATH` | _(from env)_ | Directory for output artifacts. |
| `--current-folder` | _(off)_ | Use the current terminal working directory as output. |
| `--auto-approve` | _(off)_ | Auto-approve all blueprint and plan gates without interactive prompts. |
| `--skip-reviews` | _(off)_ | Skip reviewer-agent checks between orchestration steps. |
| `--max-step-revisions N` | `0` | Override maximum reviewer revisions per step (0 = agent default). |
| `--json` | _(off)_ | Emit the final run state as JSON instead of rich output. |
| `--quiet` | _(off)_ | Suppress live step progress messages. |

### Research and Sources

| Flag | Default | Description |
|---|---|---|
| `--sources LIST` | _(auto)_ | Comma-separated list of research sources for the multi-source pipeline. Options: `web`, `arxiv` (alias `papers`, `academic`), `reddit` (alias `social`), `scholar`, `patents` (alias `patent`), `openalex`, `local` (requires `--drive`). Example: `--sources arxiv,reddit,web` |
| `--pages N` | `0` | Target page count for long-form document output. Implies `--long-document` mode. |
| `--research-model MODEL` | _(env)_ | Override the deep-research model for this run. Example: `o4-mini-deep-research`. |
| `--research-instructions TEXT` | _(none)_ | Extra instructions appended to every deep-research call. |
| `--research-max-wait-seconds N` | `0` | Max seconds to wait per deep-research API call before timeout handling. |
| `--research-poll-interval-seconds N` | `0` | Polling interval for background deep-research status checks. |
| `--research-max-tool-calls N` | `0` | Maximum web tool calls per deep-research pass. |
| `--research-max-output-tokens N` | `0` | Optional output token cap per deep-research pass. |

### Long-Form Document Mode

| Flag | Default | Description |
|---|---|---|
| `--long-document` | _(off)_ | Force staged long-form document workflow (chaptered research + merged output). |
| `--long-document-pages N` | `0` | Target page count for long-form output. |
| `--long-document-sections N` | `0` | Explicit chapter/section count. |
| `--long-document-section-pages N` | `0` | Approximate pages per section. |
| `--long-document-title TITLE` | _(auto)_ | Override the report title. |
| `--long-document-no-collect-sources` | _(off)_ | Skip the pre-collection evidence bank step. |
| `--long-document-no-section-search` | _(off)_ | Skip per-section web search. |
| `--long-document-section-search-results N` | `0` | Web search results to gather per section. |
| `--long-document-no-visuals` | _(off)_ | Skip generating tables and flowcharts. |

### Local Drive Intelligence

| Flag | Default | Description |
|---|---|---|
| `--drive PATH` | _(none)_ | Local folder or file to ingest. Repeat for multiple paths. |
| `--drive-min-files N` | `0` | Minimum file count for long-form report mode. |
| `--drive-max-files N` | `0` | Maximum files to process. |
| `--drive-extensions LIST` | _(all)_ | Comma-separated extension allowlist (example: `pdf,docx,xlsx`). |
| `--drive-no-recursive` | _(off)_ | Disable recursive folder traversal. |
| `--drive-include-hidden` | _(off)_ | Include hidden files and folders. |
| `--drive-disable-image-ocr` | _(off)_ | Disable OCR for images in drive paths. |
| `--drive-ocr-instruction TEXT` | _(auto)_ | Custom OCR instruction override. |
| `--drive-no-memory-index` | _(off)_ | Skip vector-memory indexing of extracted summaries. |
| `--drive-auto-generate-extension-handlers` | _(off)_ | Enable dynamic agent generation for unsupported file types. |

### Dev Pipeline Mode (`--dev`)

Activates the end-to-end dev pipeline: blueprint → scaffold → build → test → verify (with auto-fix) → zip export. Equivalent to `kendr generate` with full pipeline orchestration.

| Flag | Default | Description |
|---|---|---|
| `--dev` | _(off)_ | Activate the dev pipeline mode. |
| `--stack TEMPLATE` | _(LLM selects)_ | Tech stack template. Options: `fastapi_postgres`, `fastapi_react_postgres`, `nextjs_prisma_postgres`, `express_prisma_postgres`, `mern_microservices_mongodb`, `pern_postgres`, `nextjs_static_site`, `django_react_postgres`, `custom_freeform`. |
| `--dev-skip-tests` | _(off)_ | Skip test generation and execution. |
| `--dev-skip-devops` | _(off)_ | Skip Dockerfile, docker-compose, and CI/CD generation. |
| `--dev-max-fix-rounds N` | `3` | Maximum auto-fix rounds when the verifier fails. |

### Codebase Analysis

| Flag | Default | Description |
|---|---|---|
| `--codebase` | _(off)_ | Analyze an existing codebase before planning. |
| `--codebase-path PATH` | _(working dir)_ | Path to the existing project. |
| `--codebase-max-files N` | `0` | Maximum files to scan (0 = 1000). |

### superRAG Knowledge Engine

| Flag | Default | Description |
|---|---|---|
| `--superrag-mode MODE` | _(none)_ | superRAG operating mode: `build`, `chat`, `switch`, `list`, `status`. |
| `--superrag-session ID` | _(none)_ | Session ID to reuse or switch to. |
| `--superrag-new-session` | _(off)_ | Force creation of a new session for build mode. |
| `--superrag-session-title TITLE` | _(auto)_ | Human-readable title for the session. |
| `--superrag-path PATH` | _(none)_ | Local path to ingest. Repeat for multiple. |
| `--superrag-url URL` | _(none)_ | Seed URL to crawl and ingest. Repeat for multiple. |
| `--superrag-db-url URL` | _(none)_ | Database URL for schema and row-sample ingestion. |
| `--superrag-db-schema SCHEMA` | _(auto)_ | Optional database schema to target. |
| `--superrag-onedrive` | _(off)_ | Enable OneDrive ingestion (requires Microsoft Graph). |
| `--superrag-onedrive-path PATH` | _(root)_ | OneDrive folder path to ingest. |
| `--superrag-chat QUESTION` | _(none)_ | Question to ask in chat mode. |
| `--superrag-top-k N` | `0` | Top-K vector matches for chat (0 = agent default). |

### Coding Workflows

| Flag | Default | Description |
|---|---|---|
| `--coding-context-file FILE` | _(none)_ | Project file to load as coding context. Repeat for multiple. |
| `--coding-write-path PATH` | _(none)_ | Target file for coding output. |
| `--coding-instructions TEXT` | _(none)_ | Extra instructions for coding agents. |
| `--coding-language LANG` | _(auto)_ | Coding language hint. |
| `--coding-backend BACKEND` | `auto` | Preferred code-generation backend: `auto`, `codex-cli`, `openai-sdk`, `responses-http`. |

### Local Command Execution

| Flag | Default | Description |
|---|---|---|
| `--os-command CMD` | _(none)_ | Execute one explicit command through `os_agent`. |
| `--os-shell SHELL` | _(auto)_ | Preferred shell: `bash`, `powershell`, `cmd`. |
| `--os-timeout N` | `0` | Command timeout in seconds. |
| `--os-working-directory PATH` | _(working dir)_ | Working directory for command execution. |
| `--target-os OS` | _(auto)_ | Target OS hint: `linux`, `macos`, `windows`. |

### Privileged Mode

| Flag | Default | Description |
|---|---|---|
| `--privileged-mode` | _(off)_ | Enable privileged policy controls for this run. |
| `--privileged-approved` | _(off)_ | Confirm explicit operator approval for privileged actions. Required together with `--privileged-approval-note`. |
| `--privileged-approval-note NOTE` | _(none)_ | Ticket or approval reference for auditing. |
| `--privileged-read-only` | _(off)_ | Force read-only execution; no writes or mutations. |
| `--privileged-allow-root` | _(off)_ | Allow sudo/root escalation. |
| `--privileged-allow-destructive` | _(off)_ | Allow destructive operations. |
| `--privileged-enable-backup` | _(off)_ | Create filesystem snapshot before mutating actions. |
| `--privileged-allowed-path PATH` | _(none)_ | Allowed path root. Repeat for multiple. |
| `--privileged-allowed-domain DOMAIN` | _(none)_ | Allowed network domain. Repeat for multiple. |
| `--kill-switch-file FILE` | _(env)_ | Halt if this file exists before next agent step. |

### Security Workflows

| Flag | Default | Description |
|---|---|---|
| `--security-authorized` | _(off)_ | Confirm you are explicitly authorized to run defensive security tasks on the target. |
| `--security-target-url URL` | _(none)_ | Target URL for security assessment. |
| `--security-authorization-note NOTE` | _(none)_ | Ticket/approval reference proving assessment authorization. |
| `--security-scan-profile PROFILE` | `standard` | Scan depth: `baseline`, `standard`, `deep`, `extensive`. |
| `--no-auto-install-security-tools` | _(off)_ | Disable automatic installation of missing security tools (nmap, zap). |

### Communication

| Flag | Default | Description |
|---|---|---|
| `--communication-authorized` | _(off)_ | Confirm authorization to access communication channels for this run. |
| `--communication-lookback-hours N` | `24` | Lookback window in hours for the communication digest. |
| `--whatsapp-to PHONE` | _(none)_ | Recipient phone in E.164 format for `whatsapp_send_message_agent`. |
| `--whatsapp-message TEXT` | _(none)_ | Plain text message body. |
| `--whatsapp-template NAME` | _(none)_ | WhatsApp template name. |
| `--whatsapp-template-language CODE` | `en_US` | Language code for the template. |

### Session Continuity

| Flag | Default | Description |
|---|---|---|
| `--channel ID` | _(none)_ | Channel ID for conversational session continuity (e.g. `webchat`, `slack`). |
| `--workspace-id ID` | _(none)_ | Workspace ID for session routing. |
| `--sender-id ID` | _(none)_ | Sender/user ID for session routing. |
| `--chat-id ID` | _(none)_ | Chat/thread ID for session routing. |
| `--session-key KEY` | _(none)_ | Explicit session key in format `channel:workspace:chat:scope`. |
| `--new-session` | _(off)_ | Force creation of a fresh session for this run. |

### Examples

```bash
# Research brief
kendr run --current-folder "Analyze Stripe: business model, competitors, and key risks."

# Multi-source research into a 20-page document
kendr run --sources arxiv,web,reddit --pages 20 "AI safety landscape 2024"

# superRAG: build a knowledge base
kendr run --superrag-mode build --superrag-new-session --superrag-session-title "docs_kb" \
  --superrag-path ./docs --superrag-url https://example.com/help "Index our knowledge base."

# superRAG: chat with a session
kendr run --superrag-mode chat --superrag-session docs_kb \
  --superrag-chat "What are the installation requirements?"

# Dev pipeline with stack template
kendr run --dev --stack fastapi_postgres "Build a task management API"

# Privileged OS command
kendr run --current-folder --os-command "ls -la" --os-shell bash \
  --privileged-approved --privileged-approval-note "OPS-42 approved" "List project root."

# Communication digest (last 8 hours)
kendr run --communication-authorized \
  "Summarize my Slack and Gmail messages from the last 8 hours."
```

---

## `kendr research`

Run the multi-source research pipeline and generate a document directly. A focused shortcut for research-specific workflows.

```bash
kendr research [FLAGS] "research topic"
```

| Flag | Default | Description |
|---|---|---|
| `query` | _(positional)_ | Research query or topic. |
| `--sources LIST` | _(auto)_ | Comma-separated research sources: `web`, `arxiv`, `reddit`, `scholar`, `patents`, `openalex`, `local`. |
| `--pages N` | `0` | Target page count. Enables long-document mode automatically. |
| `--title TEXT` | _(auto)_ | Optional report title. |
| `--drive PATH` | _(none)_ | Local path to include as a research source. Repeat for multiple. |
| `--research-model MODEL` | _(env)_ | Override the deep-research model. |
| `--auto-approve` | _(off)_ | Auto-approve plan gates. |
| `--max-steps N` | `20` | Maximum orchestration steps. |
| `--working-directory PATH` | _(env)_ | Output directory. |
| `--current-folder` | _(off)_ | Use current terminal folder as output. |
| `--json` | _(off)_ | Emit final state as JSON. |
| `--quiet` | _(off)_ | Suppress progress messages. |

### Examples

```bash
# Quick research brief
kendr research "Battery recycling market: key players and investment risks"

# Multi-source with document output
kendr research --sources arxiv,web --pages 15 --title "Quantum ML Survey 2024" \
  "Survey of quantum machine learning advances"

# Include local files as a source
kendr research --sources local,web --drive ./internal-reports \
  "Summarize our internal research and compare with market trends"
```

---

## `kendr generate`

Generate a complete multi-agent software project from a description: blueprint → scaffold → build → test → verify → zip export.

```bash
kendr generate [FLAGS] "project description"
```

| Flag | Default | Description |
|---|---|---|
| `description` | _(positional)_ | Natural language project description. |
| `--name NAME` | _(auto)_ | Project name in kebab-case. Derived from description if omitted. |
| `--stack TEMPLATE` | _(LLM selects)_ | Tech stack template: `fastapi_postgres`, `fastapi_react_postgres`, `nextjs_prisma_postgres`, `express_prisma_postgres`, `mern_microservices_mongodb`, `pern_postgres`, `nextjs_static_site`, `django_react_postgres`, `custom_freeform`. |
| `--output PATH` | _(working dir)_ | Output directory root. |
| `--auto-approve` | _(off)_ | Auto-approve blueprint and plan gates. |
| `--skip-tests` | _(off)_ | Skip test generation and execution. |
| `--skip-devops` | _(off)_ | Skip Dockerfile, docker-compose, and CI/CD generation. |
| `--skip-reviews` | _(off)_ | Skip reviewer agent checks between build steps. |
| `--max-steps N` | `40` | Maximum orchestration steps. |
| `--working-directory PATH` | _(env)_ | Working directory for artifacts. |
| `--current-folder` | _(off)_ | Use current terminal folder. |
| `--json` | _(off)_ | Emit final state as JSON. |
| `--quiet` | _(off)_ | Suppress progress messages. |

### Examples

```bash
# Generate a FastAPI + PostgreSQL API
kendr generate --stack fastapi_postgres "A task management REST API with auth and tests"

# Full-stack with auto-approve
kendr generate --stack fastapi_react_postgres --auto-approve \
  "SaaS starter with user auth, billing, and an admin dashboard"

# Simple script project (LLM chooses stack)
kendr generate "A Python CLI tool for batch image resizing"
```

---

## `kendr gateway`

Start, stop, restart, or inspect the HTTP gateway server. The gateway must be started explicitly before any workflow that requires it. It is never auto-started by `kendr run`, `kendr research`, or `kendr generate`.

```bash
kendr gateway start
kendr gateway stop
kendr gateway restart
kendr gateway status [--json]
kendr gateway serve       # run in foreground (default when no action given)
```

| Action | Description |
|---|---|
| `start` | Start the gateway server in the background. Writes PID to `~/.kendr/gateway.pid`. |
| `stop` | Stop the gateway-owned process on the configured port. Does not kill unrelated processes. |
| `restart` | Stop the current gateway and start a fresh one. |
| `status` | Show gateway health, PID state, and port listener status. |
| `serve` | Run the gateway in the foreground (default when no action is specified). |

| Flag | Default | Description |
|---|---|---|
| `--json` | _(off)_ | Emit machine-readable status as JSON (includes `health_ok`, `pid_alive`, `pid_owned`, `port_listening`). |

### Examples

```bash
kendr gateway start
kendr gateway status
kendr gateway stop
kendr gateway restart
kendr gateway status --json
kendr gateway serve        # foreground — useful for debugging
```

---

## `kendr web`

Alias for `kendr gateway serve`. Runs the gateway server in the foreground.

```bash
kendr web
```

---

## `kendr setup-ui`

Run the OAuth and setup UI directly in the foreground (shortcut for `kendr setup ui`).

```bash
kendr setup-ui
```

---

## `kendr setup`

Manage component configuration via the CLI. Use `kendr setup status` after any configuration change.

```bash
kendr setup <action> [args]
```

| Action | Description |
|---|---|
| `status` | Show setup status: which components are configured, available agents, and setup actions. |
| `components` | List all configurable components (integrations). |
| `show COMPONENT` | Show one component's current configuration. |
| `set COMPONENT KEY VALUE` | Set one configuration field for a component (stored in local DB). |
| `unset COMPONENT KEY` | Remove one configuration field. |
| `enable COMPONENT` | Enable a component. |
| `disable COMPONENT` | Disable a component. |
| `export-env` | Export current DB configuration as dotenv lines. Use `--include-secrets` to include secrets. |
| `install` | Install auto-installable local components (nmap, zap, dependency-check, playwright). Use `--yes` to skip confirmation, `--only` to install specific tools. |
| `ui` | Run the web-based OAuth setup UI on `http://127.0.0.1:8787`. |
| `oauth PROVIDER` | Run the OAuth login flow for a supported provider (`google`, `microsoft`, `slack`, `all`). Use `--no-browser` to print URLs without opening a browser. Use `--ensure-ui` for compatibility with environments that auto-start the setup UI. |

### Examples

```bash
# Minimum viable setup
kendr setup set core_runtime KENDR_WORKING_DIR /home/user/kendr-work
kendr setup set openai OPENAI_API_KEY sk-...
kendr setup status

# Check one component
kendr setup show openai --json

# Install security tools
kendr setup install --yes

# Install only specific tools
kendr setup install --yes --only nmap zap

# Run OAuth flow without opening a browser (print URL to copy manually)
kendr setup oauth google --no-browser

# Export config for a .env file
kendr setup export-env > .env
```

---

## `kendr resume`

Resume or inspect a previously run or paused orchestration session.

```bash
kendr resume [FLAGS] [run-folder]
```

| Flag | Default | Description |
|---|---|---|
| `target` | _(positional)_ | Run folder, manifest/checkpoint file, or working directory path. |
| `query` | _(positional)_ | Optional reply or new query when resuming or branching. |
| `--output-folder PATH` | _(none)_ | Explicit path to the run output folder or manifest. |
| `--working-directory PATH` | _(none)_ | Working directory to search for persisted run folders. |
| `--latest` | _(off)_ | Automatically use the newest discovered run candidate. |
| `--inspect` | _(off)_ | Inspect the session without executing it. |
| `--branch` | _(off)_ | Start a new child run from the saved context instead of resuming in place. |
| `--reply TEXT` | _(none)_ | Explicit reply for a run paused at a user-input gate. |
| `--force` | _(off)_ | Take over a run marked as running or stale. |
| `--json` | _(off)_ | Emit resume candidate or result as JSON. |

### Examples

```bash
# Inspect the most recent run in the current folder
kendr resume --working-directory . --latest --inspect

# Resume a specific run
kendr resume --output-folder ./output/runs/run_cli_abc123

# Reply to a paused approval gate
kendr resume --output-folder ./output/runs/run_cli_abc123 --reply approve

# Branch: start a new run from a completed session
kendr resume --output-folder ./output/runs/run_cli_abc123 --branch \
  "Expand the brief into an investor-facing memo."
```

---

## `kendr agents`

List or inspect discovered agents.

```bash
kendr agents list [FLAGS]
kendr agents show AGENT_NAME [--json]
```

| Flag | Description |
|---|---|
| `--plugin NAME` | Filter by plugin name. |
| `--contains TEXT` | Filter agent name/description by substring. |
| `--limit N` | Limit number of results. |
| `--json` | Emit as JSON. |

### Examples

```bash
kendr agents list
kendr agents show deep_research_agent --json
kendr agents list --contains research
```

---

## `kendr plugins`

List discovered plugins (built-in and external).

```bash
kendr plugins list [FLAGS]
```

| Flag | Description |
|---|---|
| `--kind KIND` | Filter by plugin kind. |
| `--contains TEXT` | Filter by name/description substring. |
| `--limit N` | Limit results. |
| `--json` | Emit as JSON. |

---

## `kendr sessions`

List and manage conversational sessions.

```bash
kendr sessions list [FLAGS]
kendr sessions current
kendr sessions use SESSION_KEY
kendr sessions clear
```

| Flag | Description |
|---|---|
| `--limit N` | Number of sessions to list (default 20). |
| `--json` | Emit as JSON. |

---

## `kendr workdir`

Manage the configured working directory.

```bash
kendr workdir show [--json]
kendr workdir set PATH
kendr workdir here
kendr workdir create PATH [--activate]
```

| Subcommand | Description |
|---|---|
| `show` | Show the currently configured working directory. |
| `set PATH` | Set the working directory to an existing absolute path. |
| `here` | Set the current terminal folder as the working directory. |
| `create PATH` | Create a new working directory. Use `--activate` to set it active immediately. |
| `clear` | Clear the configured working directory (unset `KENDR_WORKING_DIR`). |

### Examples

```bash
kendr workdir here
kendr workdir show
kendr workdir set /home/user/my-project
```

---

## `kendr status`

Show a runtime status snapshot (agents available, setup health, session state).

```bash
kendr status [--json]
```

---

## `kendr daemon`

Run the always-on monitor and heartbeat loop for scheduled tasks and stock/news monitoring.

```bash
kendr daemon [--poll-interval N] [--heartbeat-interval N] [--once]
```

| Flag | Default | Description |
|---|---|---|
| `--poll-interval N` | _(env)_ | Seconds between monitor passes. |
| `--heartbeat-interval N` | _(env)_ | Seconds between heartbeat log entries. |
| `--once` | _(off)_ | Run one monitor pass and exit. |

---

## `kendr rollback`

List or apply filesystem snapshots created by privileged runs.

```bash
kendr rollback list
kendr rollback apply --snapshot PATH [--target-dir PATH] [--overwrite] [--yes]
```

---

## `kendr hello`

Display a quick-start welcome screen with setup guidance and example commands. Useful for first-time orientation.

```bash
kendr hello [--json]
```

| Flag | Default | Description |
|---|---|---|
| `--json` | _(off)_ | Emit quick-start info as JSON. |

---

## `kendr help`

Show help for a specific command.

```bash
kendr help [TOPIC]
```

| Argument | Description |
|---|---|
| `topic` | Optional command name to show help for. Omit to show general help. |

### Examples

```bash
kendr help
kendr help run
kendr help gateway
```
