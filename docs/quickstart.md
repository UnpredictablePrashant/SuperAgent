# Quickstart

This guide gets you from a fresh checkout to your first successful Kendr run.

## Prerequisites

- Python 3.10 or newer
- an `OPENAI_API_KEY`
- a working directory where Kendr can write run artifacts

Recommended for the best first experience:

- `SERP_API_KEY` for search-backed research workflows
- Docker if you want the full Qdrant and MCP stack

## 1. Install Kendr

Linux or macOS:

```bash
./scripts/install.sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

Manual install on any OS:

```bash
python3 -m pip install -e ".[dev]"
python3 scripts/bootstrap_local_state.py
```

## 2. Configure Environment

The install/bootstrap scripts create a local `.env` for you. If you are configuring manually, use `.env.example` as the baseline.

Set at least:

- `OPENAI_API_KEY`
- `SERP_API_KEY` for search-heavy workflows

You can also inspect setup from the CLI:

```bash
kendr setup status
kendr setup components
```

If you prefer a local UI for OAuth-backed providers:

```bash
kendr setup ui
```

The setup UI runs on `http://127.0.0.1:8787` by default.

## 3. Choose A Working Directory

Kendr needs a working directory for artifacts and intermediate outputs.

Use the current folder:

```bash
kendr workdir here
```

Or pass it per run:

```bash
kendr run --current-folder "Create a short research brief on OpenAI."
```

## 4. Sanity Check

```bash
kendr --help
kendr agents list
kendr plugins list
kendr setup status
python scripts/verify.py smoke
```

## 5. First Run

Use the actual CLI entrypoint:

```bash
kendr run --current-folder \
  "Create an intelligence brief on Stripe: business model, products, competitors, recent strategy moves, and top risks."
```

What to expect:

- the runtime ensures the gateway path is available
- the run may stop first on an approval-ready plan
- after approval, Kendr executes the workflow and writes artifacts under `output/runs/<run_id>/`

## 6. Recommended Next Runs

Deep research:

```bash
kendr run --current-folder \
  --research-model o4-mini-deep-research \
  --research-instructions "Cite concrete sources and call out uncertainty." \
  "Do deep research on battery recycling market structure, current leaders, and investment risks."
```

Local-drive intelligence:

```bash
kendr run \
  --drive="D:/xyz/folder" \
  "Review this folder, summarize the important files, and produce an executive-ready intelligence brief."
```

`superRAG` build:

```bash
kendr run \
  --superrag-mode build \
  --superrag-new-session \
  --superrag-session-title "product_ops_kb" \
  --superrag-path ./docs \
  --superrag-url https://example.com/help-center \
  "Create a reusable product operations knowledge session."
```

`superRAG` chat:

```bash
kendr run \
  --superrag-mode chat \
  --superrag-session product_ops_kb \
  --superrag-chat "What are the main operating risks and where are they sourced from?"
```

Coding project builder:

```bash
kendr run --current-folder \
  --max-steps 30 \
  --coding-context-file README.md \
  --coding-instructions "Prefer FastAPI, pytest, docs, and CI verification commands." \
  "Use master_coding_agent to design and deliver a production-ready internal tools API with tests, docs, CI, and deployment files."
```

Local command execution:

```bash
kendr run --current-folder \
  --os-command "Get-ChildItem" \
  --os-shell powershell \
  --target-os windows \
  --privileged-approved \
  --privileged-approval-note "OPS-123 approved repo inspection" \
  "List the project root."
```

## 7. Resume An Interrupted Run

Every run now writes resumable state into its run folder under `output/runs/<run_id>/`.

Inspect the latest saved run in a working directory:

```bash
kendr resume --working-directory . --latest --inspect
```

Resume directly from a run folder:

```bash
kendr resume --output-folder ./output/runs/run_cli_123
```

Resume a paused approval step with an explicit reply:

```bash
kendr resume \
  --output-folder ./output/runs/run_cli_123 \
  --reply approve
```

Start a new child run from a completed session's saved context:

```bash
kendr resume \
  --output-folder ./output/runs/run_cli_123 \
  --branch \
  "Expand the report into an investor-facing memo."
```

## Where To Go Next

- [Install](install.md) for the full setup surface
- [Core Workflows](core_workflows.md) for the recommended product entry points
- [Examples](examples.md) for more workflows
- [Troubleshooting](troubleshooting.md) if the first run does not behave as expected
