# Core Workflows

These are the five productized entry points for Kendr in the current codebase.

Use them in this order if you are validating the repo end to end:

1. local-drive intelligence
2. `superRAG`
3. deep research
4. coding project builder
5. local command execution

## 1. Deep Research

Status: Beta

### When To Use It

Use this when you want OpenAI's web-grounded deep research path instead of the lighter general research flow.

### Minimum Setup

- `OPENAI_API_KEY`
- `KENDR_WORKING_DIR`

### Demo

```bash
kendr run --current-folder \
  --research-model o4-mini-deep-research \
  --research-instructions "Cite concrete sources and call out uncertainty." \
  "Do deep research on battery recycling market structure, current leaders, and investment risks."
```

### Expected Artifacts

- `deep_research_output_<n>.txt`
- `deep_research_raw_<n>.json`

### Acceptance Check

- the final output is source-aware and substantive
- the raw response artifact exists in the run folder

## 2. Local-Drive Intelligence

Status: Stable

### When To Use It

Use this when the evidence is already on disk and you want file-by-file summarization, OCR where relevant, and a rollup summary.

### Minimum Setup

- `OPENAI_API_KEY`
- `KENDR_WORKING_DIR`

### Demo

```bash
kendr run --current-folder \
  --drive ./docs \
  --drive-max-files 25 \
  "Review this folder, summarize the key files, and produce an executive-ready intelligence brief."
```

### Expected Artifacts

- `local_drive_agent_<n>.txt`
- `local_drive_agent_<n>.json`
- `local_drive_doc_summary_<n>_*.txt`

### Acceptance Check

- the rollup includes `Catalog Summary`
- per-document summary files are written

## 3. superRAG

Status: Stable

### When To Use It

Use this when you want a persistent session-based knowledge system over local files, URLs, databases, or OneDrive.

### Minimum Setup

- `OPENAI_API_KEY`
- reachable `QDRANT_URL`
- `KENDR_WORKING_DIR`

### Demo

Build:

```bash
kendr run --current-folder \
  --superrag-mode build \
  --superrag-new-session \
  --superrag-session-title "product_ops_kb" \
  --superrag-path ./docs \
  --superrag-url https://example.com/help-center \
  "Create a reusable product operations knowledge session."
```

Chat:

```bash
kendr run --current-folder \
  --superrag-mode chat \
  --superrag-session product_ops_kb \
  --superrag-chat "What are the main operating risks and where are they sourced from?"
```

### Expected Artifacts

- `superrag_build_<n>.txt`
- `superrag_build_<n>.json`
- `superrag_chat_<n>.txt`
- `superrag_chat_<n>.json`

### Acceptance Check

- build returns a session id and indexed chunk count
- chat works against the saved session id

## 4. Coding Project Builder

Status: Beta

### When To Use It

Use this for end-to-end project delivery: architecture, approval-ready blueprint, delegated implementation, and coding artifacts.

### Minimum Setup

- `KENDR_WORKING_DIR`
- `OPENAI_API_KEY` or local `codex` CLI on `PATH`

### Demo

```bash
kendr run --current-folder \
  --max-steps 30 \
  --coding-context-file README.md \
  --coding-instructions "Prefer FastAPI, pytest, docs, and CI verification commands." \
  "Use master_coding_agent to design and deliver a production-ready internal tools API with tests, docs, CI, and deployment files."
```

### Expected Artifacts

- `blueprint_output_<n>.md`
- `blueprint_output_<n>.json`
- `master_coding_agent_plan_<n>.md`
- `master_coding_agent_output_<n>.txt`
- `coding_agent_output_<n>.txt`
- `coding_agent_output_<n>.json`

### Acceptance Check

- the run pauses on blueprint approval before build work starts
- the master plan artifact lists phases and delegation
- coding output artifacts include backend, model, and generated code

## 5. Local Command Execution

Status: Beta

### When To Use It

Use this for controlled local shell execution with explicit approval, privileged audit logging, and command reports.

### Minimum Setup

- `KENDR_WORKING_DIR`
- explicit operator approval per run

### Demo

Windows PowerShell example:

```bash
kendr run --current-folder \
  --os-command "Get-ChildItem" \
  --os-shell powershell \
  --target-os windows \
  --privileged-approved \
  --privileged-approval-note "OPS-123 approved repo inspection" \
  "List the project root."
```

POSIX example:

```bash
kendr run --current-folder \
  --os-command "ls -la" \
  --os-shell bash \
  --target-os linux \
  --privileged-approved \
  --privileged-approval-note "OPS-123 approved repo inspection" \
  "List the project root."
```

### Expected Artifacts

- `os_agent_output_<n>.txt`
- `privileged_audit.log`
- optional backup snapshot for mutating commands

### Acceptance Check

- the report includes shell, command, return code, stdout, stderr, and command classification
- blocked commands still produce an audit/report artifact
