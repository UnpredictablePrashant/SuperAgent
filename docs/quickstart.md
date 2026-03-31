# Quickstart

This guide gets you from a fresh checkout to a successful first run in under 5 minutes. You need two things: an `OPENAI_API_KEY` and a directory where Kendr can write outputs.

---

## What you'll do

1. Install Kendr
2. Set your API key and working directory
3. Run a health check
4. Run your first research query

---

## Step 1 — Install

Clone the repo and install:

```bash
git clone https://github.com/your-org/kendr.git
cd kendr
pip install -e .
```

Or with the install script (Linux / macOS):

```bash
./scripts/install.sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

---

## Step 2 — Set the two required variables

Create a `.env` file in the repo root (copy `.env.example` as your starting point):

```bash
cp .env.example .env
```

Open `.env` and set:

```bash
OPENAI_API_KEY="sk-..."                  # your OpenAI API key
KENDR_WORKING_DIR="/home/user/kendr-out" # where outputs are written (absolute path)
```

Or use the CLI to set them in the local config database:

```bash
kendr setup set openai OPENAI_API_KEY sk-...
kendr setup set core_runtime KENDR_WORKING_DIR /home/user/kendr-out
```

That is the minimum. Everything else is optional.

---

## Step 3 — Start the gateway

Kendr routes all runs through the HTTP gateway server. You must start it before any `kendr run`, `kendr research`, or `kendr generate` command.

```bash
kendr gateway start
kendr gateway status     # confirm it's running
```

The gateway runs in the background and writes its PID to `~/.kendr/gateway.pid`. It stays running across multiple `kendr run` calls. You only need to start it once per session (or after a reboot).

---

## Step 4 — Health check

Confirm everything is wired up:

```bash
kendr setup status
```

You should see `openai` marked as **configured** and `core_runtime` showing the working directory you set. If `openai` shows as unconfigured, check that your `.env` file is being loaded (it must be in the current directory or on the `PYTHONPATH`).

Optional quick verification:

```bash
kendr --version
kendr agents list
```

---

## Step 5 — Your first run

Run a research brief:

```bash
kendr run --current-folder \
  "Create an intelligence brief on Stripe: business model, products, competitors, recent strategy moves, and top risks."
```

`--current-folder` tells Kendr to write outputs to your current terminal directory (no need to configure `KENDR_WORKING_DIR` separately for this run).

**What to expect:**

- The startup banner shows the model and working directory.
- Kendr routes the query and selects the appropriate agents.
- You see step-by-step progress: each agent start, its duration, and whether it succeeded.
- The run may pause at a blueprint approval gate. Type `y` to approve and continue.
- When done, the final output appears in a panel. Artifacts are written under `output/runs/<run_id>/`.
- A run summary table shows each agent, its duration, and output files.

---

## Step 6 — Try more workflows

### Deep research with source selection

```bash
kendr run --current-folder \
  --sources arxiv,web \
  "Survey of large language model safety research in 2024"
```

### Local file intelligence

```bash
kendr run --drive ./my-documents \
  "Summarize the key risks across these documents and produce an executive brief."
```

### superRAG: build a knowledge base

```bash
kendr run \
  --superrag-mode build \
  --superrag-new-session \
  --superrag-session-title "product_docs" \
  --superrag-path ./docs \
  "Build a searchable knowledge base from our product documentation."
```

### superRAG: chat with the knowledge base

```bash
kendr run \
  --superrag-mode chat \
  --superrag-session product_docs \
  --superrag-chat "What are the installation requirements?"
```

### Generate a software project

```bash
kendr generate --stack fastapi_postgres \
  "A task management REST API with user authentication, tests, and Docker deployment."
```

### Research pipeline with document output

```bash
kendr research --sources arxiv,web --pages 10 \
  "Battery recycling market: key players, investment trends, and technology outlook"
```

---

## Step 7 — Resume a paused or interrupted run

Every run writes resumable state to its output folder.

Inspect the most recent run:

```bash
kendr resume --working-directory . --latest --inspect
```

Resume a specific run:

```bash
kendr resume --output-folder ./output/runs/run_cli_abc123
```

Reply to a paused approval step:

```bash
kendr resume --output-folder ./output/runs/run_cli_abc123 --reply approve
```

---

## Next steps

- [Configuration Reference](configuration.md) — every env var with default values and examples
- [CLI Reference](cli.md) — every subcommand and flag
- [Integrations](integrations.md) — setting up search, communication providers, and vector backends
- [SampleTasks.md](../SampleTasks.md) — copy-paste examples for every workflow
- [Troubleshooting](troubleshooting.md) — common first-run issues and how to fix them
