# Examples

These examples start with the current recommended workflow entry points.

For a walkthrough with artifacts and acceptance checks, see [Core Workflows](core_workflows.md).
For a longer command list, see [Extended CLI Examples](../SampleTasks.md).

## Recommended Entry Points

### Deep Research

```bash
kendr run --current-folder \
  --research-model o4-mini-deep-research \
  --research-instructions "Cite concrete sources and call out uncertainty." \
  "Do deep research on Stripe's enterprise strategy, current moat, and main risks."
```

### Local-Drive Intelligence

```bash
kendr run \
  --drive="D:/xyz/folder" \
  "Review this folder, summarize the important files, and produce an executive-ready intelligence brief."
```

### superRAG Build

```bash
kendr run \
  --superrag-mode build \
  --superrag-new-session \
  --superrag-session-title "product_ops_kb" \
  --superrag-path ./docs \
  --superrag-url https://example.com/help-center \
  "Create a reusable product operations knowledge session."
```

### superRAG Chat

```bash
kendr run \
  --superrag-mode chat \
  --superrag-session product_ops_kb \
  --superrag-chat "What are the main operating risks and where are they sourced from?"
```

### Coding Project Builder

```bash
kendr run --current-folder --max-steps 30 \
  --coding-context-file README.md \
  --coding-instructions "Prefer FastAPI, pytest, docs, and CI verification commands." \
  "Use master_coding_agent to design and deliver a production-ready internal tools API with tests, docs, CI, and deployment files."
```

### Local Command Execution

```bash
kendr run --current-folder \
  --os-command "Get-ChildItem" \
  --os-shell powershell \
  --target-os windows \
  --privileged-approved \
  --privileged-approval-note "OPS-123 approved repo inspection" \
  "List the project root."
```

## Additional Examples

### Research Brief

```bash
kendr run --current-folder \
  "Create an intelligence brief on Stripe: business model, products, competitors, recent strategy moves, and top risks."
```

### People And Organization Mapping

```bash
kendr run --current-folder \
  "Research Satya Nadella's recent public interviews and connect themes to Microsoft product priorities."
```

### Deal Advisory

```bash
kendr run \
  "Identify India-based B2B SaaS startups likely in Series A/B range, then provide a screened shortlist with rationale."
```

### Research Proposal And Prior Art

```bash
kendr run \
  "Review this proposal topic: low-cost edge AI for crop disease detection; summarize prior art, key papers, and novelty gaps."
```

### Authorized Defensive Security Review

```bash
kendr run \
  --security-authorized \
  --security-target-url https://example.com \
  --security-authorization-note "SEC-123 approved by owner" \
  --security-scan-profile deep \
  "Perform defensive recon and extensive security findings with remediation priorities."
```

### Travel Planning

```bash
kendr run \
  "Plan best travel options from Bangalore to Singapore next month with likely flight windows and routing advice."
```

### Long Document

```bash
kendr run \
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

## Experimental Workflows

### Master Coding Agent

```bash
kendr run --max-steps 30 \
  "Use master_coding_agent to design and deliver a complete production-ready SaaS starter: API, auth, database migrations, CI, tests, docs, and deployment instructions."
```

### Generated-Agent Factory Flow

Use the agent-factory surface only when you are intentionally testing scaffold-and-run behavior. It is not part of the main product entry path today.

### Voice And Audio

Voice catalog, speech generation, and speech transcription are present in the repo, but they are currently treated as experimental from a product-positioning perspective.
