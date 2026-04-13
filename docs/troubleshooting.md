# Troubleshooting

This guide covers the most common first-run and setup issues implied by the current runtime and docs.

## Start With Setup Status

When something does not appear to route correctly, check setup first:

```bash
kendr setup status
kendr agents list
kendr plugins list
```

The runtime filters unconfigured capabilities out of the available agent set.

## Working Directory Required

Kendr needs a working directory for artifacts and intermediate state.

If a run fails before execution, set one of:

```bash
kendr workdir here
```

or:

```bash
kendr run --current-folder "Create a short research brief on OpenAI."
```

## The Run Stops On A Plan

This is expected behavior.

Planning is a first-class stage, and the runtime can pause for approval before execution. Long-document workflows add a second approval stage for section planning.

## A Feature Does Not Trigger

Likely causes:

- the required provider is not configured
- the required local tool is not installed
- the feature belongs to a beta or experimental workflow and needs more setup than the core path

Check:

- `.env`
- `kendr setup status`
- [Integrations](integrations.md)

## Gateway Or Setup UI Is Not Reachable

Default ports:

- gateway: `8790`
- setup UI: `8787`

Start them explicitly if needed:

```bash
kendr gateway
kendr setup ui
```

## Browser Features Do Not Work Fully

Some browser features require Playwright plus installed browser binaries:

```bash
python3 -m pip install playwright
python3 -m playwright install chromium
```

Headed browser mode also requires a real display session or virtual display support on Linux.

## Docker Stack Is Not Available

Docker is optional for normal local CLI use.

Use it when you want:

- containerized Qdrant
- MCP services
- the fuller service stack

If Docker is not installed, you can still use the CLI and local setup path for many workflows.

## Security Workflow Won't Start

Security workflows require explicit authorization flags and notes. Some deeper scans also depend on local tools like `nmap` or `zap-baseline.py`.

If a security feature is missing, confirm both:

- scope and authorization flags are present
- local tooling is installed or auto-install is enabled

For local one-command setup and preflight checks, use:

```bash
./scripts/setup-security-tools.sh --auto-install
./scripts/preflight-security-tools.sh
```

Then set authorization in `config/security-tools.env` and run:

```bash
./scripts/scan-website.sh https://example.com
```

## Communication Agent Dispatch Loop / Authorization Error

If a run ends with:

- `Agent 'communication_summary_agent' appears stuck in a dispatch loop`
- `Communication agents require explicit authorization`

the runtime safety policy blocked communication access and the circuit breaker stopped retries.

Use one of these fixes:

1. You actually want inbox/messaging access and disabled it explicitly:

```bash
kendr run --communication-authorized "Check my latest Gmail and Slack messages."
```

2. You only wanted capability/skill listing (not message access):

```bash
kendr agents list
curl http://127.0.0.1:8790/registry/skills
```

3. You are using gateway/state payloads directly:

- `communication_authorized` now defaults to `true`
- set `communication_authorized=false` for runs/workspaces that should not touch inbox or messaging data
- set `KENDR_COMMUNICATION_AUTHORIZED=false` to change the global default in CLI, web, and Electron-backed runtimes

## Verification Caveats

The current repo documents these limits:

- live end-to-end external API workflows are not fully verified
- Docker runtime execution is not fully verified
- MCP client interoperability is not fully verified
- heavy-load vector indexing behavior is not fully verified

Treat the stable workflows as the best-supported path today.

## Useful Recovery Commands

```bash
kendr --help
kendr help run
kendr help resume
kendr setup status
kendr daemon --once
```

## A Run Was Interrupted Or Looks Stuck

Start by inspecting the latest persisted run state:

```bash
kendr resume --working-directory . --latest --inspect
```

Common cases:

- `awaiting_user_input`: the run is paused on clarification or approval and needs `--reply`.
- `failed`: the run captured a resumable checkpoint and can continue from the saved step.
- `running_stale`: the last heartbeat is old; resume with `--force` to take it over.
- `completed`: use `--branch` if you want to continue from the prior context without overwriting the original run.

Examples:

```bash
kendr resume --output-folder ./output/runs/run_cli_123 --reply approve
kendr resume --output-folder ./output/runs/run_cli_123 --force
kendr resume --output-folder ./output/runs/run_cli_123 --branch "Continue with implementation."
```

For repository-level checks:

```bash
python3 scripts/verify.py
python3 scripts/verify.py smoke
python3 scripts/verify.py docs
```

Use [Verification](verification.md) when you need the full phase breakdown.
