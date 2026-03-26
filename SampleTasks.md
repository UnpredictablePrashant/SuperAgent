# SampleTasks

This file shows example ways to run the multi-agent system using the `superagent` command.

## Quick Sanity Check

```bash
superagent --help
superagent agents list
superagent plugins list
```

Run one query:

```bash
superagent run "analyze this company and build a report"
```

Run in current terminal folder:

```bash
superagent run --current-folder "analyze this company and build a report"
```

Run with stricter step limit:

```bash
superagent run --max-steps 12 "summarize key risks for a fintech startup"
```

Get machine-readable output:

```bash
superagent run --json "build a short research brief on OpenAI"
```

## Case Study 1: Company Intelligence Brief

Goal: Produce a quick, source-backed brief on a company.

```bash
superagent run "Create an intelligence brief on Stripe: business model, products, competitors, recent strategy moves, and top risks."
```

Expected behavior:
- Routes through search/research/report-style agents when configured.
- Produces final narrative output in terminal.
- Stores run artifacts under `output/runs/<run_id>/`.

## Case Study 2: People + Organization Mapping

Goal: Map relationships between people, companies, and events.

```bash
superagent run "Research Satya Nadella's recent public interviews and connect themes to Microsoft product priorities."
```

Expected behavior:
- Uses entity/timeline/research flow when available.
- Produces structured notes and a summarized output.
- Artifacts and logs are saved per run.

## Case Study 3: Deal Advisory (Series A/B Screening)

Goal: Find and screen prospects in a target sector.

```bash
superagent run "Identify India-based B2B SaaS startups likely in Series A/B range, then provide a screened shortlist with rationale."
```

Expected behavior:
- Invokes deal-advisory agents (prospecting, stage screening, sector intelligence) when setup supports it.
- Produces shortlist + reasoning in final output.
- Writes intermediate outputs for traceability in the run folder.

## Case Study 4: Research Proposal and Prior Art

Goal: Compare a research idea against literature and patents.

```bash
superagent run "Review this proposal topic: low-cost edge AI for crop disease detection; summarize prior art, key papers, and novelty gaps."
```

Expected behavior:
- Uses proposal/literature/patent workflow if available.
- Generates evidence-oriented summary and novelty assessment.
- Saves step-by-step artifacts in `output/runs/<run_id>/`.

## Case Study 5: Defensive Security Review (Authorized Scope)

Goal: Generate a defensive security findings summary.

```bash
superagent run \
  --security-authorized \
  --security-target-url https://example.com \
  --security-authorization-note "SEC-123 approved by owner" \
  --security-scan-profile deep \
  "Perform defensive recon and extensive security findings with remediation priorities."
```

Expected behavior:
- Uses defensive security agents only when security setup is available.
- Produces findings-focused output with recommendations.
- Evidence artifacts are written to the run folder.

## Case Study 6: Travel Planning Flow

Goal: Build practical travel routing suggestions.

```bash
superagent run "Plan best travel options from Bangalore to Singapore next month with likely flight windows and routing advice."
```

Expected behavior:
- Travel agents are used only if required setup (including `SERP_API_KEY`) is configured.
- If unavailable, runtime will fall back to other eligible agents.

## Case Study 7: Authorized Deep Security Assessment

Goal: Run an explicit, authorized, defensive security assessment with deeper scan coverage.

```bash
superagent run \
  --security-authorized \
  --security-target-url https://example.com \
  --security-authorization-note "SEC-123 approved by owner" \
  --security-scan-profile extensive \
  "Perform a defensive security assessment with deep coverage and provide prioritized remediation guidance."
```

Expected behavior:
- CLI requires explicit authorization details before security scanning starts.
- CLI auto-checks security tooling and attempts to install missing tools (`nmap`, `zap`, `dependency-check`) unless disabled.
- Security workflow remains defensive-only and blocks unauthorized/offensive operation.
- Extensive profile applies deeper default scan posture (broader Nmap coverage and longer ZAP baseline window).
- Outputs include evidence and findings artifacts under `output/runs/<run_id>/`.

Optional: disable auto-install for this run

```bash
superagent run --no-auto-install-security-tools --security-authorized --security-target-url https://example.com --security-authorization-note "SEC-123 approved by owner" --security-scan-profile deep "Perform authorized defensive assessment."
```

## Case Study 8: Master Coding Agent (Detailed Long-Running Build)

Goal: Deliver a complete project blueprint and route implementation/setup work to the right specialist agents.

```bash
superagent run --max-steps 30 "Use master_coding_agent to design and deliver a complete production-ready SaaS starter: API, auth, database migrations, CI, tests, docs, and deployment instructions."
```

Expected behavior:
- `master_coding_agent` creates a detailed architecture + phased implementation plan.
- If dependencies/components are required, it delegates setup/install work to supporting agents (for example `os_agent`).
- It then delegates concrete coding execution to `coding_agent` and keeps the workflow detailed and end-to-end.

## Case Study 9: Very Long Exhaustive Document (50+ Pages)

Goal: Build a deeply researched, coherent long-form report through staged chapter generation and final merge.

```bash
superagent run \
  --max-steps 180 \
  --long-document \
  --long-document-pages 50 \
  --long-document-sections 10 \
  --long-document-section-pages 5 \
  --long-document-title "Global Gold Market Intelligence Dossier" \
  --research-max-wait-seconds 7200 \
  --research-max-tool-calls 16 \
  "Produce an exhaustive investment-grade global gold market report with coherent chapter-by-chapter analysis and final merged output."
```

Expected behavior:
- Routes to `long_document_agent` for staged section planning, deep research, chapter drafting, and continuity alignment.
- Requires explicit approval of the top-level plan first, then a second approval of the long-document section/chapter subplan before expensive research starts.
- Writes per-section research artifacts plus merged output into `output/runs/<run_id>/long_document_runs/long_document_run_<n>/`.
- Captures per-section references and a consolidated reference register (`long_document_references.md` / `.json`).
- Adds section visuals where useful (markdown tables + mermaid flowcharts), writes per-section visual artifacts, and compiles a run-level visual index.
- Coherence is anchored through markdown memory files (`Agent.md`, `soul.md`, `memory.md`, `session.md`, `planning.md`) plus live bridge files (`long_document_coherence_*.md`).
- Supports very long-running execution windows with explicit research wait configuration.

## Case Study 10: superRAG Session Build + Chat

Goal: Build a persistent session-based RAG system from mixed sources, then chat over indexed knowledge.

Build from local files + URLs:

```bash
superagent run \
  --superrag-mode build \
  --superrag-new-session \
  --superrag-session-title "product_ops_kb" \
  --superrag-path ./docs \
  --superrag-path ./notes \
  --superrag-url https://example.com/help-center \
  --superrag-url https://example.com/changelog \
  "Create a superRAG knowledge base for product operations."
```

Build from database URL (schema + sampled row knowledge):

```bash
superagent run \
  --superrag-mode build \
  --superrag-session ops_db_kb \
  --superrag-db-url "postgresql://user:pass@host:5432/appdb" \
  --superrag-db-schema public \
  "Scan this database and build a superRAG session."
```

Build including OneDrive content (requires Microsoft Graph setup):

```bash
superagent run \
  --superrag-mode build \
  --superrag-session onedrive_ops_kb \
  --superrag-onedrive \
  --superrag-onedrive-path "Shared/Operations" \
  "Ingest OneDrive documents into superRAG."
```

Chat with an existing session:

```bash
superagent run \
  --superrag-mode chat \
  --superrag-session ops_db_kb \
  --superrag-chat "What are the top risk indicators and their source tables?" \
  --superrag-top-k 10
```

Switch to a different session:

```bash
superagent run --superrag-mode switch --superrag-session onedrive_ops_kb "Switch active superRAG session."
```

Check one session status:

```bash
superagent run --superrag-mode status --superrag-session ops_db_kb "Show superRAG status."
```

List available superRAG sessions:

```bash
superagent run --superrag-mode list "List my superRAG sessions."
```

Expected behavior:
- `superrag_agent` runs ingestion, chunking, embeddings, vector indexing, and session persistence.
- Console/task logs include preflight analysis, estimated duration, and long-running progress messages.
- Database builds include schema knowledge base artifacts (tables, columns, keys, sampled rows).
- Session data is persisted and can be reused across runs (`build`, `chat`, `switch`, `status`, `list`).

## Useful Companion Commands

Inspect one agent:

```bash
superagent agents show company_research_agent --json
```

Run daemon once (monitor pass):

```bash
superagent daemon --once
```

Set current terminal folder as default working directory:

```bash
superagent workdir here
```

Run gateway mode:

```bash
superagent gateway
```

## Full Setup Configuration (Web + CLI)

Start setup UI:

```bash
superagent setup ui
```

List every configurable component:

```bash
superagent setup components
```

Set a config value in local setup DB:

```bash
superagent setup set openai OPENAI_API_KEY sk-...
superagent setup set openai OPENAI_MODEL_GENERAL gpt-4.1-mini
superagent setup set openai OPENAI_MODEL_CODING gpt-5.3-codex
```

Inspect one component:

```bash
superagent setup show openai --json
```

Disable or enable a component:

```bash
superagent setup disable serpapi
superagent setup enable serpapi
```

Export DB settings as dotenv lines:

```bash
superagent setup export-env
superagent setup export-env --include-secrets
```

Install auto-installable local components/tools:

```bash
superagent setup install
superagent setup install --yes
superagent setup install --yes --only nmap zap dependency-check playwright
```

## Notes

- Agent routing is setup-aware: unconfigured integrations are filtered out automatically.
- Every run writes logs and artifacts into `output/runs/<run_id>/` (including `execution.log` and `final_output.txt`).
- Use `--json` when integrating `superagent` output into another app or pipeline.
