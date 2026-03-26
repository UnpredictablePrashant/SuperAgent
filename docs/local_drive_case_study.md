# Case Study: Local Drive Intelligence for Superagent

## Scenario

A strategy and finance team keeps critical information scattered across a shared local drive:

- board decks (`pptx`, `ppt`)
- audit packs (`pdf`)
- contracts (`doc`, `docx`)
- MIS exports (`xls`, `xlsx`, `csv`)
- operating notes (`txt`, `md`)
- photographed whiteboards and scanned documents (`png`, `jpg`, `tiff`)

When leadership asks for a "48-hour investment-readiness report," analysts usually spend days opening files manually, extracting key points, and reconciling contradictions.

## Problem

The team had three blockers:

1. Source sprawl: hundreds of files across many folders and formats.
2. Slow synthesis: no reusable per-document intelligence layer.
3. Weak traceability: report claims were hard to map back to source documents.

## Superagent Feature Pattern

The new `local_drive_agent` workflow addresses this by letting users point Superagent at local folders.

### How It Works

1. User provides one or more local paths.
2. `local_drive_agent` scans supported files and processes **one file at a time**.
3. For each file, it extracts text (or OCR for images) and writes a document-level summary artifact.
4. It builds a summary bank in state:
   - `local_drive_document_summaries`
   - `local_drive_summary_bank`
5. The main orchestrator and downstream agents (for example `report_agent`) pull from this summary bank to produce deliverables.

## Why One-File-at-a-Time Matters

- Prevents large mixed-context failures.
- Improves auditability because each summary is source-bounded.
- Enables selective reprocessing when one document changes.
- Produces deterministic artifacts for compliance and QA review.

## Example Execution

### Inputs

- `local_drive_paths`: `D:/Deals/Acme_Raise`
- `local_drive_recursive`: `true`
- `local_drive_max_files`: `300`
- `local_drive_enable_image_ocr`: `true`

### Processing

- 186 files discovered.
- 186 document summaries generated.
- Summary artifacts written per file in `output/`.
- Aggregate rollup created in `output/local_drive_agent_<n>.txt`.

### Downstream Task

`report_agent` consumes the summary bank and generates:

- executive summary
- financial and operating risk section
- open-questions list
- cited source appendix

## Business Outcome

In internal dry runs, this pattern changes work from manual document hunting to directed analysis:

- faster first draft report turnaround
- higher source coverage
- better reproducibility of findings
- easier handoff between analyst, reviewer, and decision maker

## Design Notes

- Supports mixed formats in one pass.
- Keeps extraction and summarization explicit at the document level.
- Allows optional vector indexing for semantic retrieval (`memory_index_agent`).
- Preserves compatibility with existing intelligence and reporting workflows.

## Recommended Rollout

1. Start with one high-value folder and `local_drive_max_files=50`.
2. Validate summary quality against analyst review.
3. Expand extension allowlist and file volume.
4. Enable memory indexing for cross-document question answering.
5. Operationalize in recurring report workflows.
