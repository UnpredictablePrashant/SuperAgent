# Kendr Core Intelligence Stack

Kendr is best understood today as a multi-agent intelligence workspace.

This document covers the core stack behind that positioning: evidence gathering, document ingestion, memory indexing, and report-ready synthesis across people, companies, organizations, groups, and related entities.

## Current Product Focus

- stable: research briefs, local-drive intelligence, `superRAG`, and report synthesis
- beta: long-document generation plus setup-heavy domain workflows
- experimental: generated agents, voice/audio, and future-facing social ecosystem analysis

## Core Intelligence Agents

- `access_control_agent`
- `web_crawl_agent`
- `document_ingestion_agent`
- `local_drive_agent`
- `ocr_agent`
- `entity_resolution_agent`
- `knowledge_graph_agent`
- `timeline_agent`
- `source_verification_agent`
- `people_research_agent`
- `company_research_agent`
- `relationship_mapping_agent`
- `news_monitor_agent`
- `compliance_risk_agent`
- `structured_data_agent`
- `memory_index_agent`
- `citation_agent`

## Required Environment Variables

- `OPENAI_API_KEY`
  Used for orchestration, structured extraction, OCR via vision, and embeddings.
- `SERP_API_KEY`
  Used for Google search and news retrieval.

## Optional Environment Variables

- `OPENAI_MODEL`
- `OPENAI_VISION_MODEL`
- `OPENAI_EMBEDDING_MODEL`
- `QDRANT_URL`
- `QDRANT_COLLECTION`
- `RESEARCH_USER_AGENT`

## Docker Services

- `qdrant`
  Vector database for semantic memory.
- `app`
  Main orchestration runtime.
- `research-mcp`
  MCP server for search, crawl, document parsing, OCR, and entity brief tools.
- `vector-mcp`
  MCP server for vector indexing and semantic retrieval.

## Startup

```bash
docker compose up --build
```

## Current API Coverage

No extra paid APIs are required beyond OpenAI and SerpAPI for the current implementation.

## Local Drive Intelligence

`local_drive_agent` can scan user-selected local folders, process supported files one at a time, and create per-document summaries for downstream synthesis and reporting.

Supported classes include:

- text and web docs (`txt`, `md`, `json`, `html`)
- office docs (`doc`, `docx`, `xls`, `xlsx`, `ppt`, `pptx`)
- data files (`csv`)
- PDFs (`pdf`)
- images with OCR (`png`, `jpg`, `jpeg`, `bmp`, `gif`, `webp`, `tif`, `tiff`)

## Long Document Visual Synthesis

`long_document_agent` now pauses for an explicit section-plan approval before it starts the expensive section research/drafting pass. The stored subplan includes:

- section/chapter breakdown
- per-step model allocation (`deep_research` model for evidence gathering, resolved document model for drafting/merge work)
- approval-ready markdown persisted into the active run folder and session planning memory

After approval, it augments section drafts with visuals where needed:

- markdown tables for structured comparisons and KPI snapshots
- mermaid flowcharts for process and dependency narratives

Artifacts are persisted inline with each run:

- `section_##/visual_assets.json`
- `section_##/visual_assets.md`
- `section_##/flowchart_##.mmd`
- `long_document_visual_index.md`
- `long_document_visual_index.json`

## Recommended Future Integrations

If you want stronger corporate and people intelligence, these are the next APIs to consider:

- People Data Labs
- Crunchbase
- Clearbit or Apollo
- OpenCorporates
- SEC/EDGAR connectors
- sanction or watchlist feeds
- Firecrawl or Browserbase for richer site extraction
