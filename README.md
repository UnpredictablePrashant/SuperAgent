# Multi-Agent Super Research System

This repository contains a multi-agent research and orchestration system built around:

- OpenAI for reasoning, generation, OCR, deep research, and embeddings
- LangGraph for orchestration
- A2A-inspired in-process task/message passing between agents
- SQLite for durable workflow tracking
- Qdrant for vector memory
- Docker and MCP servers for deployable research and memory services

The system is designed to evolve into a general-purpose research and intelligence platform for:

- people
- companies
- organizations
- groups
- documents
- websites
- spreadsheets
- code and technical artifacts
- eventually, social media ecosystems

## What Exists Today

The current codebase already includes:

- dynamic registry/discovery architecture in [superagent/discovery.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/superagent/discovery.py)
- dynamic orchestration runtime in [superagent/runtime.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/superagent/runtime.py)
- CLI entrypoint in [superagent/cli.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/superagent/cli.py)
- compatibility app entrypoint in [app.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/app.py)
- optional HTTP gateway and dashboard in [gateway_server.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/gateway_server.py)
- A2A task/message/artifact protocol in [tasks/a2a_protocol.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/tasks/a2a_protocol.py)
- agent session helpers in [tasks/a2a_agent_utils.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/tasks/a2a_agent_utils.py)
- SQLite persistence in [tasks/sqlite_store.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/tasks/sqlite_store.py)
- text work ledger in [tasks/utils.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/tasks/utils.py)
- Docker deployment assets in [docker-compose.yml](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/docker-compose.yml) and [Dockerfile](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/Dockerfile)
- MCP research server in [mcp_servers/research_server.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/mcp_servers/research_server.py)
- MCP vector server in [mcp_servers/vector_server.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/mcp_servers/vector_server.py)
- MCP Nmap server in [mcp_servers/nmap_server.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/mcp_servers/nmap_server.py)
- MCP ZAP server in [mcp_servers/zap_server.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/mcp_servers/zap_server.py)
- MCP screenshot server in [mcp_servers/screenshot_server.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/mcp_servers/screenshot_server.py)
- MCP HTTP surface server in [mcp_servers/http_fuzzing_server.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/mcp_servers/http_fuzzing_server.py)
- MCP CVE server in [mcp_servers/cve_server.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/mcp_servers/cve_server.py)

## Current Agent Inventory

Agents are now discovered dynamically from built-in task modules and external plugins, then registered into one runtime registry. The list below reflects the built-in inventory currently present in this repo.

### Core Workflow

- `planner_agent`
- `worker_agent`
- `reviewer_agent`
- `report_agent`
- `agent_factory_agent`
- `dynamic_agent_runner`

### Utility / Execution

- `os_agent`
- `coding_agent`
- `master_coding_agent`
- `excel_agent`
- `google_search_agent`
- `deep_research_agent`
- `long_document_agent`
- `reddit_agent`
- `location_agent`

### Travel / Transport

- `flight_tracking_agent`
- `transport_route_agent`
- `travel_hub_agent`

### Voice / Audio

- `voice_catalog_agent`
- `speech_generation_agent`
- `speech_transcription_agent`

### Gateway / Runtime

- `channel_gateway_agent`
- `session_router_agent`
- `browser_automation_agent`
- `interactive_browser_agent`
- `scheduler_agent`
- `notification_dispatch_agent`
- `whatsapp_agent`

### Monitoring / 24x7

- `heartbeat_agent`
- `monitor_rule_agent`
- `stock_monitor_agent`

### Cloud / AWS

- `aws_scope_guard_agent`
- `aws_inventory_agent`
- `aws_cost_agent`
- `aws_automation_agent`

### Deal Advisory / Fundraising

- `prospect_identification_agent`
- `funding_stage_screening_agent`
- `sector_intelligence_agent`
- `company_meeting_brief_agent`
- `investor_positioning_agent`
- `financial_mis_analysis_agent`
- `deal_materials_agent`
- `investor_matching_agent`
- `investor_outreach_agent`

### Research Documents / Patents

- `literature_search_agent`
- `patent_search_agent`
- `proposal_review_agent`
- `prior_art_analysis_agent`
- `claim_evidence_mapping_agent`

### Security Assessment

- `security_scope_guard_agent`
- `recon_agent`
- `web_recon_agent`
- `api_surface_mapper_agent`
- `scanner_agent`
- `exploit_agent`
- `evidence_agent`
- `unauthenticated_endpoint_audit_agent`
- `idor_bola_risk_agent`
- `security_headers_agent`
- `tls_assessment_agent`
- `dependency_audit_agent`
- `sast_review_agent`
- `prompt_security_agent`
- `ai_asset_exposure_agent`
- `security_findings_agent`
- `security_report_agent`

### Communication / Collaboration

- `communication_scope_guard_agent`
- `gmail_agent`
- `drive_agent`
- `telegram_agent`
- `whatsapp_agent`
- `slack_agent`
- `microsoft_graph_agent`
- `communication_hub_agent`

### Intelligence / Research

- `access_control_agent`
- `web_crawl_agent`
- `document_ingestion_agent`
- `ocr_agent`
- `image_agent`
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

## System Architecture

### 1. Orchestration

The main workflow is now assembled dynamically by [superagent/runtime.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/superagent/runtime.py) from the discovered registry produced by [superagent/discovery.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/superagent/discovery.py).

The orchestrator:

- reads the current workflow state
- loads a dynamic registry of discovered agents, channels, providers, and plugins
- detects which integrations and tools are actually configured on the machine
- filters agent cards so only configured agents are eligible for routing
- checks recent A2A messages and agent history
- chooses the next agent via LLM routing
- creates an A2A task for that agent
- routes the result back into the orchestration loop
- forces reviewer passes after successful non-reviewer steps
- can route into `agent_factory_agent` when the existing ecosystem lacks a capability
- can execute a newly scaffolded runtime agent through `dynamic_agent_runner`
- can stop when the answer is good enough or when `max_steps` is reached

This removes the old requirement to manually hardcode every agent node and edge in one giant file. If a new agent is discovered by the registry, it becomes part of the workflow graph automatically.

### 1.1 Registry and Discovery

The new registry/discovery layer is built around:

- [superagent/registry.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/superagent/registry.py)
- [superagent/types.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/superagent/types.py)
- [superagent/discovery.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/superagent/discovery.py)

It does four things:

- discovers built-in agents by scanning task modules for `*_agent` functions
- discovers external plugins from plugin search paths
- registers channels, providers, plugins, and agents in one runtime registry
- exposes that registry to the CLI and HTTP gateway for easy network-wide discovery

Default plugin discovery paths:

- `./plugins`
- `~/.superagent/plugins`
- any extra paths in `SUPERAGENT_PLUGIN_PATHS`

External plugin files are simple Python modules that define `register(registry)`. See [plugin_templates/echo_plugin.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/plugin_templates/echo_plugin.py) for the minimal pattern.

### 1.2 Runtime Setup Awareness

The runtime setup registry lives in [tasks/setup_registry.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/tasks/setup_registry.py).

It does four things:

- detects configured integrations, local tools, and OAuth-backed services
- writes a machine-readable setup snapshot to [output/setup_status.json](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/output/setup_status.json)
- writes a human-readable summary to [output/setup_status.txt](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/output/setup_status.txt)
- filters the orchestrator's available agent list so unconfigured agents are not selected

This means the app now routes based on real setup, not the full theoretical ecosystem.

This also applies to travel tooling. The orchestrator will only use the transport agents when `SERP_API_KEY` and the base OpenAI setup are available. If travel search is not configured, those agents remain filtered out of the runtime card list.

### 1.3 Dynamic Agent Creation

The dynamic agent path is implemented in [tasks/agent_factory_tasks.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/tasks/agent_factory_tasks.py).

It adds:

- `agent_factory_agent`
  Designs and scaffolds a new agent module under [tasks/generated_agents](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/tasks/generated_agents).
- `dynamic_agent_runner`
  Loads and executes the generated module in the current workflow.

Artifacts produced by the factory flow:

- [tasks/generated_agents/manifest.json](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/tasks/generated_agents/manifest.json)
- `output/agent_factory_output_<n>.txt`
- `output/agent_factory_manifest_<n>.json`
- `output/dynamic_agent_runner_output_<n>.txt`

This is intended as a scaffold-and-run path, not a guarantee of perfect autonomous framework surgery. The factory creates a working generated agent module and runs it through the generic runner, but it does not rewrite the entire static orchestrator graph for every new custom agent name.

### 2. A2A Communication

Agents communicate through an internal A2A-inspired protocol:

- tasks
- messages
- artifacts
- agent cards

This is implemented in:

- [tasks/a2a_protocol.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/tasks/a2a_protocol.py)
- [tasks/a2a_agent_utils.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/tasks/a2a_agent_utils.py)

Each agent:

- accepts work through `active_task`
- records acceptance
- performs work
- publishes outputs as A2A messages and artifacts
- updates the shared workflow state

### 3. Persistence

The system stores durable traces in SQLite:

- runs
- agent cards
- tasks
- messages
- artifacts
- agent executions

Database file:

- [output/agent_workflow.sqlite3](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/output/agent_workflow.sqlite3)

Human-readable planning/work notes are now stored inside each run folder as `agent_work_notes.txt`.

### 3.1 Per-Run Artifact Folders

Each workflow run now creates its own temporary artifact folder under [output/runs](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/output/runs).

Every agent artifact for that run is written inside the active run folder, including travel outputs such as:

- `flight_tracking_agent_<n>.txt`
- `flight_tracking_agent_<n>.json`
- `transport_route_agent_<n>.txt`
- `transport_route_agent_<n>.json`
- `travel_hub_agent_<n>.txt`
- `travel_hub_agent_<n>.json`

That run folder becomes the active output location for the entire run and receives:

- `execution.log`
- `graph.png`
- `final_output.txt`
- all agent `.txt`, `.json`, `.pdf`, `.html`, and `.xlsx` artifacts

### 4. Vector Memory

Vector memory is implemented with Qdrant and OpenAI embeddings in [tasks/research_infra.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/tasks/research_infra.py).

It supports:

- chunking web/document/OCR text
- embedding with OpenAI
- upserting into Qdrant
- semantic retrieval for downstream agents

### 5. Deployment and Services

Docker Compose services:

- `qdrant`
- `app`
- `research-mcp`
- `vector-mcp`

See [docker-compose.yml](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/docker-compose.yml).

## Shared Research Infrastructure

The shared intelligence layer lives in [tasks/research_infra.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/tasks/research_infra.py).

It currently provides:

- LLM text and JSON helpers
- OpenAI client access
- HTML-to-text extraction
- simple site crawling and link following
- SerpAPI search wrapper
- document parsing for `txt`, `md`, `json`, `html`, `csv`, `pdf`, `docx`
- OpenAI vision-based OCR
- chunking utilities
- Qdrant collection creation
- vector upsert and search
- evidence bundle construction for higher-level agents

## Intelligence Workflow Pattern

A typical deep-research flow should look like this:

1. `access_control_agent`
2. `google_search_agent` or `news_monitor_agent`
3. `web_crawl_agent`
4. `document_ingestion_agent` and/or `ocr_agent`
5. `entity_resolution_agent`
6. `memory_index_agent`
7. `people_research_agent` or `company_research_agent`
8. `knowledge_graph_agent`
9. `timeline_agent`
10. `source_verification_agent`
11. `compliance_risk_agent`
12. `citation_agent`
13. `report_agent`

The reviewer can interrupt or reroute this flow whenever it decides a step is insufficient.

## Deal Advisory Workflow Pattern

The system now supports a dedicated deal-advisory and fundraising workflow for mandates like:

- identify prospects in a sector
- filter companies that raised Series A or Series B
- build sector homework
- meet the company with a strong preparation brief
- analyze company financials and MIS
- prepare deliverables
- identify the right investor set
- plan outreach to investors

A recommended execution path is:

1. `prospect_identification_agent`
2. `funding_stage_screening_agent`
3. `sector_intelligence_agent`
4. `company_research_agent`
5. `company_meeting_brief_agent`
6. `investor_positioning_agent`
7. `financial_mis_analysis_agent`
8. `deal_materials_agent`
9. `investor_matching_agent`
10. `investor_outreach_agent`
11. `report_agent`

### What These Deal Agents Do

- `prospect_identification_agent`
  Identifies companies in the target sector and geography that appear to have raised Series A or Series B.
- `funding_stage_screening_agent`
  Screens and ranks sourced prospects against the advisory mandate.
- `sector_intelligence_agent`
  Builds sector homework including revenue models, benchmarks, past trends, and micro trends.
- `company_meeting_brief_agent`
  Creates a client-facing meeting brief and helps frame the Unitus point of view.
- `investor_positioning_agent`
  Determines the right type of investor and the core fundraising narrative.
- `financial_mis_analysis_agent`
  Reviews financial and MIS inputs, identifies key metrics, red flags, and follow-up asks.
- `deal_materials_agent`
  Prepares the structure for Excel analysis, PPT story, and an opportunity memo.
- `investor_matching_agent`
  Creates a shortlist of investors most likely to fit the company, stage, and geography.
- `investor_outreach_agent`
  Plans sequencing, intro strategy, angles, and artifacts for investor outreach.

### Inputs Commonly Needed For Deal Work

- `deal_sectors`
- `fundraising_stages`
- `deal_geography`
- `company_name`
- `research_target`
- `financial_document_paths`
- `document_paths`
- Excel/MIS files through the existing `excel_agent`

### Deliverables These Agents Support

- sector homework
- company briefing note
- financial and MIS diligence summary
- investor positioning note
- investor shortlist
- outreach plan
- Excel/PPT/opportunity-memo structure
- final downloadable report through `report_agent`

## Research Documents and Patents Workflow

The system now also supports a dedicated workflow for:

- searching academic literature
- searching patents
- reviewing research proposals
- comparing proposals against prior art
- building a claim-to-evidence matrix

A recommended execution path is:

1. `proposal_review_agent`
2. `literature_search_agent`
3. `patent_search_agent`
4. `prior_art_analysis_agent`
5. `claim_evidence_mapping_agent`
6. `source_verification_agent`
7. `report_agent`

### What These Agents Do

- `proposal_review_agent`
  Reads proposal documents and extracts objectives, novelty claims, methods, risks, and questions.
- `literature_search_agent`
  Searches scholarly literature and summarizes relevant papers, themes, and research gaps.
- `patent_search_agent`
  Searches patents and summarizes relevant filings, assignees, and technical clusters.
- `prior_art_analysis_agent`
  Compares the proposal against literature and patent evidence to identify overlap and white space.
- `claim_evidence_mapping_agent`
  Builds an evidence matrix linking claims to supporting and contradicting evidence.

### Inputs Commonly Needed For Research Proposal Work

- `proposal_document_paths`
- `literature_query`
- `patent_query`
- `claims_to_verify`
- optional extra technical context in `document_paths`

### Search Sources Used

- OpenAlex for literature metadata
- SerpAPI Google Scholar search
- SerpAPI Google Patents search

## Security Assessment Workflow

This repository now includes a defensive security-assessment workflow for authorized targets.

What is included:

- passive web reconnaissance
- passive API documentation and endpoint-surface mapping
- unauthenticated endpoint triage from exposed docs
- IDOR/BOLA risk review from API patterns and code clues
- HTTP security-header review
- TLS/certificate review
- dependency manifest review
- optional dependency-audit tool integration
- static code security review
- prompt and AI configuration integrity review
- AI/RAG/vector/storage exposure review
- aggregated findings and remediation guidance

What is intentionally not included:

- operational exploitation agents
- credential attacks
- denial-of-service tooling
- malware deployment
- persistence or post-exploitation automation
- unauthorized access workflows

The recommended defensive flow is:

1. `security_scope_guard_agent`
2. `recon_agent`
3. `web_recon_agent`
4. `api_surface_mapper_agent`
5. `scanner_agent`
6. `unauthenticated_endpoint_audit_agent`
7. `idor_bola_risk_agent`
8. `security_headers_agent`
9. `tls_assessment_agent`
10. `dependency_audit_agent`
11. `sast_review_agent`
12. `prompt_security_agent`
13. `ai_asset_exposure_agent`
14. `exploit_agent`
15. `evidence_agent`
16. `security_findings_agent`
17. `security_report_agent`

### What These Security Agents Do

- `security_scope_guard_agent`
  Confirms the assessment is explicitly authorized and blocks offensive scope.
- `recon_agent`
  Orchestrates passive recon and API-surface discovery into a single recon brief for the rest of the workflow.
- `web_recon_agent`
  Performs passive HTTP retrieval, captures headers, page text clues, and checks `robots.txt` and `sitemap.xml`.
- `api_surface_mapper_agent`
  Passively checks common Swagger/OpenAPI/ReDoc-style documentation locations and builds an endpoint inventory from exposed docs.
- `scanner_agent`
  Runs safe baseline scans with local `nmap` and `zap-baseline.py` when available, then summarizes exposed services and web findings for defenders.
- `exploit_agent`
  Performs analysis-only exploitability review. It does not generate payloads, attack chains, or operational exploit steps.
- `evidence_agent`
  Collects screenshots and run artifacts into an evidence bundle suitable for reporting.
- `unauthenticated_endpoint_audit_agent`
  Reviews discovered endpoints for likely missing authentication, especially public write paths and sensitive business objects.
- `idor_bola_risk_agent`
  Assesses object-level authorization risk from endpoint design and available code-review evidence.
- `security_headers_agent`
  Reviews key browser-facing security headers such as CSP, HSTS, X-Frame-Options, XCTO, Referrer-Policy, and Permissions-Policy.
- `tls_assessment_agent`
  Inspects TLS version, negotiated cipher, and certificate metadata for the target host.
- `dependency_audit_agent`
  Reviews dependency manifests and can optionally use local dependency-audit tooling if available.
- `sast_review_agent`
  Performs LLM-assisted static review of provided code files for common application-security issues.
- `prompt_security_agent`
  Treats prompts and AI configuration as crown-jewel assets and reviews integrity, governance, and silent-behavior-change risk.
- `ai_asset_exposure_agent`
  Reviews evidence for exposed RAG data, vector stores, storage paths, download URLs, model configs, and related AI asset leakage signals.
- `security_findings_agent`
  Aggregates results into prioritized findings and remediation guidance.
- `security_report_agent`
  Prepares a long-form security report package and delegates file generation to `report_agent` for PDF, HTML, and XLSX output.

### Inputs Commonly Needed For Security Work

- `security_authorized=True`
- `security_target_url`
- `security_authorization_note` (ticket/contract/approval reference)
- optional `security_scan_profile` (`baseline|standard|deep|extensive`, default `deep`)
- optional `scanner_ports`
- optional `scanner_top_ports`
- `sast_paths`
- `dependency_audit_workdir`
- optional `prompt_asset_paths`
- optional `ai_asset_paths`
- optional codebase or manifest files

### Security Requirements

No new API key is required for the currently implemented defensive security agents.

Required for current implementation:

- `OPENAI_API_KEY`
  Used for LLM-assisted analysis, summarization, SAST reasoning, and findings aggregation.

Optional local tools for deeper authorized assessments:

- `OWASP Dependency-Check`
  Used by `dependency_audit_agent` if installed locally.
- `pip-audit`
  Not currently wired directly, but useful for Python-focused dependency review.
- `OWASP ZAP`
  Used by `scanner_agent` and `mcp_servers/zap_server.py` when `zap-baseline.py` is installed locally.
- `Nuclei`
  Not currently integrated. Could be added later for authorized template-based detection.
- `Nmap`
  Used by `scanner_agent` and `mcp_servers/nmap_server.py` when installed locally.
- `Playwright`
  Used by `evidence_agent`, `interactive_browser_agent`, and `mcp_servers/screenshot_server.py` for browser screenshots and visible-page evidence.
- `python -m playwright install chromium`
  Required once after installing the Playwright Python package if you want screenshot/browser capture support.
- `NVD_API_KEY`
  Optional. Enables higher-rate access for the CVE/NVD MCP server. The implementation can still use public unauthenticated access with lower quotas.
- `SECURITY_AUTO_INSTALL_TOOLS`
  Optional. If `true` (default), `superagent run` attempts best-effort auto-install of missing security tools (`nmap`, `zap`, `dependency-check`) before authorized security runs.
  Use `--no-auto-install-security-tools` to disable for a specific run.

### Important Safety Constraint

These agents are for defensive assessment of assets you own or are explicitly permitted to assess.

Security authorization process before scanning:

1. Confirm ownership or explicit written permission from the system owner.
2. Define scope boundaries and testing window.
3. Record an authorization reference (ticket ID, contract ID, or signed approval).
4. Pass authorization explicitly in CLI before scan execution.

CLI example:

```bash
superagent run \
  --security-authorized \
  --security-target-url https://example.com \
  --security-authorization-note "SEC-123 approved by security owner" \
  --security-scan-profile deep \
  "perform defensive security assessment and produce remediation report"
```

The system should only run security workflows when:

- the target is in scope
- the operator is authorized
- the work is defensive
- the objective is assessment, remediation, or reporting

`exploit_agent` is intentionally analysis-only. The system does not automate payload generation, exploitation, credential attack, or service disruption.

### Coverage Added For Modern AI Platform Risk

The security layer now explicitly covers the classes of risk that show up in modern AI-platform incidents:

- exposed API documentation and oversized public API surface
- likely unauthenticated endpoints in documented APIs
- broken object level authorization and IDOR-style patterns
- prompt-layer integrity and governance failures
- exposed AI assets such as RAG data paths, vector infrastructure references, and model/prompt configs

This is still a defensive assessment stack. It is designed to help an authorized operator discover and remediate these weaknesses, not exploit them.

## Communication and Collaboration Workflow

The system now supports authenticated access to common communication and collaboration suites, subject to explicit authorization.

What is included:

- Gmail message search and summarization
- Google Drive file discovery and document summarization
- Telegram message review
- Slack channel/workspace review
- Microsoft Graph access for Outlook, Teams, and Drive/OneDrive style review
- cross-suite communication summarization

The recommended communication flow is:

1. `communication_scope_guard_agent`
2. `gmail_agent`
3. `drive_agent`
4. `telegram_agent`
5. `slack_agent`
6. `microsoft_graph_agent`
7. `communication_hub_agent`
8. `report_agent`

### What These Communication Agents Do

- `communication_scope_guard_agent`
  Confirms explicit authorization before any suite is accessed.
- `gmail_agent`
  Searches Gmail and summarizes messages, threads, and action items.
- `drive_agent`
  Searches Google Drive and summarizes files and document excerpts.
- `telegram_agent`
  Reads Telegram messages using either a bot token or a personal account session via Telethon.
- `slack_agent`
  Reads Slack channel lists or channel history using a Slack bot token.
- `microsoft_graph_agent`
  Reads Outlook mail, Teams memberships, or Drive items using Microsoft Graph.
- `communication_hub_agent`
  Combines all communication-suite outputs into one actionable summary.

### Inputs Commonly Needed For Communication Work

- `communication_authorized=True`
- `communication_suites`
- `gmail_query`
- `drive_query`
- `telegram_target`
- `slack_channel`
- `microsoft_graph_mode`

### Communication Requirements

Required for communication workflows:

- `OPENAI_API_KEY`
  Used to summarize and synthesize communication data.

Per-suite credentials:

- `GOOGLE_ACCESS_TOKEN`
  Required for `gmail_agent` and `drive_agent`.
  This must be a valid Google OAuth access token with the relevant Gmail/Drive scopes for the current user.

- `TELEGRAM_BOT_TOKEN`
  Optional for bot-based Telegram access.

- `TELEGRAM_API_ID`
- `TELEGRAM_API_HASH`
- `TELEGRAM_SESSION_STRING`
  Required together for personal-account Telegram access through Telethon.

- `SLACK_BOT_TOKEN`
  Required for `slack_agent`.

- `MICROSOFT_GRAPH_ACCESS_TOKEN`
  Required for `microsoft_graph_agent`.
  This should have the Microsoft Graph scopes needed for the selected mode, such as mail, Teams, or drive access.

### Important Communication Constraint

These communication agents are intended only for accounts, chats, mailboxes, workspaces, and storage systems you are explicitly permitted to access.

They should not be used for:

- unauthorized inbox access
- unauthorized workspace access
- bypassing account permissions
- impersonation
- sending messages without explicit instruction and authorization

## Gateway and Runtime Workflow

The system now includes a lightweight OpenClaw-style front-door/runtime layer for inbound channels, session routing, browser work, scheduling, and outbound notifications.

What is included:

- inbound channel message normalization
- session routing for direct and group chats
- browser/page inspection with Playwright when available and HTTP fallback otherwise
- scheduled job persistence for reminders and deferred tasks
- proactive outbound notification dispatch
- WhatsApp outbound delivery through the WhatsApp Cloud API

The recommended gateway/runtime flow is:

1. `channel_gateway_agent`
2. `session_router_agent`
3. `planner_agent` or `worker_agent`
4. `browser_automation_agent` when web interaction is needed
5. `interactive_browser_agent` when headless or HTTP fallback is not enough
6. `scheduler_agent` for reminders or deferred work
7. `notification_dispatch_agent` or `whatsapp_agent` for outbound messaging

### What These Gateway Agents Do

- `channel_gateway_agent`
  Normalizes inbound channel payloads into a common message shape and decides whether a group message should activate the workflow.
- `session_router_agent`
  Persists a routing/session key for the current channel interaction and isolates group traffic from direct-chat traffic.
- `browser_automation_agent`
  Uses Playwright when installed, or falls back to HTTP/HTML extraction, to inspect a web page and summarize visible content.
- `interactive_browser_agent`
  Controls a real Playwright browser session in headed or headless mode for sites that require visible browser behavior, scripted clicks, or form interaction.
- `scheduler_agent`
  Persists reminders and scheduled jobs in SQLite so deferred work is tracked explicitly.
- `notification_dispatch_agent`
  Sends explicitly authorized outbound notifications through configured Telegram, Slack, or WhatsApp channels.
- `whatsapp_agent`
  Sends explicitly authorized WhatsApp outbound messages through the WhatsApp Cloud API.

### Inputs Commonly Needed For Gateway Work

- `incoming_channel`
- `incoming_sender_id`
- `incoming_chat_id`
- `incoming_text`
- optional `incoming_is_group`
- `browser_url`
- optional `interactive_browser_actions`
- optional `browser_headless`
- `schedule_task`
- `schedule_time` or `schedule_cron`
- `notification_authorized=True`
- `notification_channel`
- `notification_recipient`
- `notification_message`

### Gateway Requirements

- `OPENAI_API_KEY`
  Required for orchestration and summaries.
- `WHATSAPP_ACCESS_TOKEN` and `WHATSAPP_PHONE_NUMBER_ID`
  Required for `whatsapp_agent` and WhatsApp notifications.
- `TELEGRAM_BOT_TOKEN`
  Required for Telegram outbound notifications.
- `SLACK_BOT_TOKEN`
  Required for Slack outbound notifications.
- optional local `playwright`
  Enables fuller browser automation, and is required for `interactive_browser_agent`.
- optional `GATEWAY_HOST` and `GATEWAY_PORT`
  Used by the lightweight HTTP gateway server in [gateway_server.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/gateway_server.py).

## 24/7 Monitoring and Heartbeat

The project now supports an always-on operating mode instead of acting only as a one-shot assistant.

What is included:

- persistent monitor rules stored in SQLite
- heartbeat records for continuous health visibility
- a daemon loop for recurring checks
- proactive outbound notifications when a watch rule triggers
- stock price monitoring as the first concrete watch type

The recommended always-on flow is:

1. `monitor_rule_agent` to create a persistent watch
2. `heartbeat_agent` to emit regular health/state records
3. `stock_monitor_agent` to evaluate price thresholds and change thresholds
4. `notification_dispatch_agent` or `whatsapp_agent` to push alerts to the user
5. gateway/dashboard views to inspect `/monitors`, `/monitor-events`, and `/heartbeats`

Run the daemon with:

```bash
python -m superagent.cli daemon
```

Useful flags:

```bash
python -m superagent.cli daemon --poll-interval 30 --heartbeat-interval 300
python -m superagent.cli daemon --once
```

Environment knobs:

- `DAEMON_POLL_INTERVAL`
- `DAEMON_HEARTBEAT_INTERVAL`

Current monitor types:

- `stock_price`

Current stock source:

- public Stooq CSV quotes, so no extra market-data API key is required for the initial implementation

Current database-backed views:

- `/monitors`
- `/monitor-events`
- `/heartbeats`

### Important Interactive Browser Constraint

`interactive_browser_agent` can run with `browser_headless=False`, but headed mode requires a real desktop display session or a virtual display such as Xvfb on Linux.

### Additional Setup Notes

- Gmail and Drive can now use either a direct `GOOGLE_ACCESS_TOKEN` or a stored OAuth token obtained through the local setup UI.
- Telegram personal-account access currently relies on Telethon session credentials.
- Slack can use either `SLACK_BOT_TOKEN` or a stored OAuth token from the local setup UI.
- Microsoft can use either `MICROSOFT_GRAPH_ACCESS_TOKEN` or a stored OAuth token from the local setup UI.

### Setup UI and OAuth Flow

The repository now includes a local setup UI in [setup_ui.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/setup_ui.py).

Run it with:

```bash
python3 setup_ui.py
```

Then open:

```text
http://127.0.0.1:8787
```

The setup UI:

- shows which integrations are configured
- shows which integrations are OAuth-ready but not connected yet
- starts the Google OAuth flow for Gmail and Drive
- starts the Microsoft OAuth flow for Outlook, Teams, and OneDrive/Drive
- starts the Slack OAuth install flow
- stores returned tokens in [output/integration_tokens.json](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/output/integration_tokens.json)

Current OAuth-backed flows:

- Google Workspace: `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI`
- Microsoft Graph: `MICROSOFT_CLIENT_ID`, `MICROSOFT_CLIENT_SECRET`, `MICROSOFT_TENANT_ID`, `MICROSOFT_REDIRECT_URI`
- Slack: `SLACK_CLIENT_ID`, `SLACK_CLIENT_SECRET`, `SLACK_REDIRECT_URI`

Manual-only integrations:

- Telegram bot token or Telethon session
- WhatsApp Cloud API credentials for `whatsapp_agent` and outbound notifications

If you want, the next step would be adding:

- refresh-token support for Google and Microsoft
- Gmail send/draft support with explicit user confirmation
- Drive file download/export workflows
- Slack thread-level summarization

### Privileged Execution Controls

The runtime now includes explicit privileged-mode guardrails for root-level or broad filesystem automation.

Key controls:

- explicit approvals before privileged actions
- path scope allowlists for command/file operations
- read-only enforcement mode
- root and destructive command toggles (off by default)
- pre-mutation snapshots for rollback support
- kill-switch file check before each agent step
- append-only hash-chained privileged audit log and SQLite event records

Run-time flags:

```bash
superagent run "..." \
  --privileged-mode \
  --privileged-approved \
  --privileged-approval-note "CHG-123 approved by ops" \
  --privileged-allowed-path "/srv/project" \
  --privileged-allowed-path "/var/data" \
  --privileged-read-only
```

Optional escalation flags:

- `--privileged-allow-root`
- `--privileged-allow-destructive`
- `--privileged-enable-backup`
- `--kill-switch-file /path/to/SUPERAGENT_STOP`

Audit endpoints and artifacts:

- HTTP: `/audit/privileged`
- Files: `privileged_audit.log` (inside each run output dir), snapshots in `output/privileged_snapshots/`

Rollback helpers:

- `superagent rollback list`
- `superagent rollback apply --snapshot <path> --target-dir <dir> --yes`

Setup component:

- `privileged_control` in Setup UI/CLI (`superagent setup show privileged_control`)
- Teams chat/channel message review

## AWS Workflow

The system now supports AWS-aware cloud workflows, subject to explicit authorization.

What is included:

- AWS access guard and credential validation
- AWS resource inventory across selected services
- AWS cost analysis through Cost Explorer
- explicit AWS automation through an allowlisted boto3 operation runner

The recommended AWS flow is:

1. `aws_scope_guard_agent`
2. `aws_inventory_agent`
3. `aws_cost_agent`
4. `aws_automation_agent`
5. `report_agent`

### What These AWS Agents Do

- `aws_scope_guard_agent`
  Confirms explicit AWS authorization and verifies that boto3 can resolve usable credentials.
- `aws_inventory_agent`
  Inventories selected AWS services such as EC2, S3, Lambda, RDS, and IAM.
- `aws_cost_agent`
  Pulls Cost Explorer data and summarizes spend drivers and optimization opportunities.
- `aws_automation_agent`
  Executes explicit allowlisted AWS operations and blocks mutating actions unless `aws_allow_mutation=True`.

### Inputs Commonly Needed For AWS Work

- `aws_authorized=True`
- `aws_region`
- `aws_profile`
- `aws_services`
- `aws_service`
- `aws_operation`
- `aws_parameters`
- `aws_operations`
- `aws_allow_mutation`

### AWS Requirements

- `OPENAI_API_KEY`
  Used for summarization and orchestration.
- `boto3`
  Required for AWS access.
- AWS credentials through one of these:
  `AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`
  optional `AWS_SESSION_TOKEN`
  `AWS_PROFILE`
  any other valid boto3 credential source such as an instance role

### Important AWS Constraint

These agents are for AWS accounts, roles, and operations you are explicitly permitted to access.

Mutating operations are blocked by default. To allow them, you must set both:

- `aws_authorized=True`
- `aws_allow_mutation=True`

## Travel and Transport Workflow

The system now includes travel-planning agents for flights and route comparisons across multiple modes of transport.

What is included:

- flight option lookup and summarization
- price, timing, airline, and stopover comparison
- route planning across transit, train-like transit results, bus-like transit results, driving, walking, cycling, and flight-style directions
- final travel recommendation synthesis

The recommended travel flow is:

1. `flight_tracking_agent`
2. `transport_route_agent`
3. `travel_hub_agent`
4. `report_agent`

### What These Travel Agents Do

- `flight_tracking_agent`
  Uses SerpAPI Google Flights results to summarize practical flight choices, price tradeoffs, airlines, stops, and schedule cues.
- `transport_route_agent`
  Uses SerpAPI Google Maps Directions results to compare route options between places for transit and other supported travel modes.
- `travel_hub_agent`
  Combines flight and route outputs into one concise recommendation with tradeoffs and likely travel risks.

### Inputs Commonly Needed For Travel Work

- `flight_departure_id`
- `flight_arrival_id`
- `flight_outbound_date`
- optional `flight_return_date`
- `travel_origin` or `route_start_addr`
- `travel_destination` or `route_end_addr`
- optional `transport_mode`
- optional `travel_hl`
- optional `travel_gl`
- optional `travel_currency`

### Travel Requirements

- `OPENAI_API_KEY`
  Used for summarization and orchestration.
- `SERP_API_KEY`
  Required for flight and route lookups.

### Important Travel Constraint

These agents rely on the currently configured SerpAPI-backed travel sources. They do not book tickets or access private operator systems directly.

## Voice and Audio Workflow

The system now includes an ElevenLabs-backed voice layer for speech generation and transcription.

What is included:

- available voice discovery
- voice recommendation for narration use cases
- text-to-speech audio generation
- speech-to-text transcription for uploaded audio files

The recommended voice workflow is:

1. `voice_catalog_agent`
2. `speech_generation_agent` or `speech_transcription_agent`
3. `report_agent`

### What These Voice Agents Do

- `voice_catalog_agent`
  Lists available ElevenLabs voices and summarizes which voices best fit the requested use case.
- `speech_generation_agent`
  Generates downloadable audio from text, report content, or the current workflow draft.
- `speech_transcription_agent`
  Transcribes an audio file into text and provides a readable summary of the transcript.

### Inputs Commonly Needed For Voice Work

- `voice_search_query`
- `speech_text` or `text_to_speak`
- optional `elevenlabs_voice_id`
- optional `elevenlabs_voice_name`
- `speech_audio_path` or `audio_file_path`
- optional `elevenlabs_model_id`
- optional `elevenlabs_output_format`

### Voice Requirements

- `OPENAI_API_KEY`
  Used for summarization and orchestration.
- `ELEVENLABS_API_KEY`
  Required for voice discovery, text-to-speech, and speech-to-text.

### Important Voice Constraint

These agents create or transcribe audio using the currently configured ElevenLabs account. They do not bypass account limits, manage billing, or perform voice cloning workflows.

## Location Workflow

The system now includes a location intelligence path for user-provided places and coordinates.

What is included:

- place geocoding from a text query
- reverse lookup from latitude and longitude
- nearby place and amenity discovery
- locality summary and map links

The recommended location flow is:

1. `location_agent`
2. `report_agent`

### What This Agent Does

- `location_agent`
  Resolves a place or coordinates, gathers nearby facilities using OpenStreetMap services, and summarizes the locality in practical terms.

### Inputs Commonly Needed For Location Work

- `location_query` or `place_query`
- or `location_lat` and `location_lon`
- optional `location_radius_meters`
- optional `location_countrycodes`
- optional `location_amenities`

### Location Requirements

- `OPENAI_API_KEY`
  Used for the final interpretation and summary.
- no additional API key is required for the current implementation

### Important Location Constraint

This agent is meant for understanding a user-provided place or coordinates. It does not perform private location tracking or covert user-location discovery.

## Environment Variables

Use [.env.example](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/.env.example) as the template.

### Required

- `OPENAI_API_KEY`
- `SERP_API_KEY`

### Recommended

- `OPENAI_MODEL`
- `OPENAI_VISION_MODEL`
- `OPENAI_EMBEDDING_MODEL`
- `ELEVENLABS_API_KEY`
- `SUPERAGENT_HOME`
- `SUPERAGENT_PLUGIN_PATHS`
- `QDRANT_URL`
- `QDRANT_COLLECTION`
- `RESEARCH_USER_AGENT`

## Local Run

### Easy Install (Linux / macOS)

```bash
./scripts/install.sh
```

This script:

- creates `.venv` (if missing)
- installs the package in editable mode
- bootstraps local runtime state (`.env` from `.env.example` when missing, plus local output/memory folders)
- adds `.venv/bin` to your shell PATH (`~/.bashrc` or `~/.zshrc`)

Then reload shell config:

```bash
source ~/.bashrc
```

or:

```bash
source ~/.zshrc
```

### Easy Uninstall (Linux / macOS)

```bash
./scripts/uninstall.sh
```

This script:

- uninstalls `superagent-runtime` from the local `.venv` (if present)
- removes `.venv/bin` PATH entry from `~/.bashrc` or `~/.zshrc`
- removes the local `.venv`

### Easy Install (Windows with Chocolatey)

Preferred Windows flow via `choco`:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install_choco.ps1
```

This flow:

- uses Chocolatey to install Python when missing
- runs the SuperAgent installer
- adds `.venv\Scripts` to your user PATH

Important:

- `choco` does not install directly from a GitHub repository URL by default
- for a proper `choco install superagent` experience, publish a Chocolatey package (`.nupkg`) that points to versioned GitHub Release assets
- this repo now builds Python distribution artifacts into `dist/` in GitHub Actions and publishes them as Release assets on tag pushes (`v*`)

Uninstall SuperAgent from this repo install:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall.ps1
```

Optional: if Python was installed only for this setup and is not needed elsewhere:

```powershell
choco uninstall python -y
```

### Easy Install (Windows PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install.ps1
```

This script:

- creates `.venv` (if missing)
- installs the package in editable mode
- bootstraps local runtime state (`.env` from `.env.example` when missing, plus local output/memory folders)
- adds `.venv\Scripts` to your user PATH
- recreates `.venv` automatically if it detects a non-Windows venv layout

Open a new terminal after install.

### Easy Uninstall (Windows PowerShell)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\uninstall.ps1
```

This script:

- uninstalls `superagent-runtime` from the local `.venv` (if present)
- removes `.venv\Scripts` from your user PATH
- removes the local `.venv`

Open a new terminal after uninstall.

### Manual Install (any OS)

```bash
python -m pip install -e .
```

### Manual Uninstall (any OS)

If installed in your active Python environment:

```bash
python -m pip uninstall -y superagent-runtime
```

If installed in this repo's local virtualenv:

```bash
.venv/bin/python -m pip uninstall -y superagent-runtime
```

Optional cleanup:

```bash
rm -rf .venv
```

Verify command is available:

```bash
superagent --help
```

Run a single CLI query:

```bash
superagent run "analyze this company and build a report"
```

`superagent run` now uses the gateway flow by default:

- ensures the gateway is running at `http://127.0.0.1:8790` (or `GATEWAY_HOST` / `GATEWAY_PORT`)
- submits the query through `POST /ingest`

List discovered agents:

```bash
superagent agents list
```

Inspect discovered plugins:

```bash
superagent plugins list
```

Run the lightweight gateway server:

```bash
superagent gateway
```

Run the always-on daemon:

```bash
superagent daemon
```

Run the setup UI:

```bash
superagent setup-ui
```

Legacy form still works:

```bash
python -m superagent.cli <subcommand>
```

## Docker Run

Build and start the stack:

```bash
docker compose up --build
```

This brings up:

- the main app container
- the always-on daemon container
- Qdrant
- research MCP server
- vector MCP server
- Nmap MCP server
- ZAP MCP server
- screenshot MCP server
- HTTP surface probing MCP server
- CVE MCP server

## Build and CI

The repository now has a basic CI gate for new agents, plugins, and skills.

Files involved:

- [Makefile](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/Makefile)
- [scripts/ci_check.sh](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/scripts/ci_check.sh)
- [.github/workflows/ci.yml](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/.github/workflows/ci.yml)
- [.github/workflows/release.yml](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/.github/workflows/release.yml)
- [tests/test_registry.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/tests/test_registry.py)
- [tests/test_setup_registry.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/tests/test_setup_registry.py)
- [tests/test_cli.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/tests/test_cli.py)
- [tests/test_imports.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/tests/test_imports.py)

What CI currently enforces:

- Python compile checks for `app.py`, `gateway_server.py`, `setup_ui.py`, `superagent/`, `tasks/`, `mcp_servers/`, and `tests/`
- dynamic registry/discovery smoke tests
- setup-awareness smoke tests
- CLI smoke tests
- runtime entrypoint import smoke tests
- Docker image build
- `dist/` package build artifact upload in CI
- GitHub Release publishing of `dist/*` assets when tags matching `v*` are pushed

Local commands:

```bash
make compile
make test
make ci
```

If you prefer the direct script:

```bash
./scripts/ci_check.sh
```

Important note:

- the CI workflow installs dependencies before testing
- the local test suite skips MCP import smoke tests when `fastmcp` is not installed in the active interpreter
- GitHub Actions still attempts the full dependency install and Docker build path

## MCP Servers

### Research MCP

File:

- [mcp_servers/research_server.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/mcp_servers/research_server.py)

Tools exposed:

- `web_search`
- `news_search`
- `crawl_site`
- `ingest_document`
- `ocr_image`
- `entity_brief`

### Vector MCP

File:

- [mcp_servers/vector_server.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/mcp_servers/vector_server.py)

Tools exposed:

- `index_texts`
- `semantic_search`

### Nmap MCP

File:

- [mcp_servers/nmap_server.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/mcp_servers/nmap_server.py)

Tools exposed:

- `service_scan`
- `host_discovery`

Requirements:

- local `nmap` binary on `PATH`

### ZAP MCP

File:

- [mcp_servers/zap_server.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/mcp_servers/zap_server.py)

Tools exposed:

- `baseline_scan`
- `version_info`

Requirements:

- local `zap-baseline.py` on `PATH`

### Screenshot MCP

File:

- [mcp_servers/screenshot_server.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/mcp_servers/screenshot_server.py)

Tools exposed:

- `capture`
- `capture_with_actions`

Requirements:

- Python `playwright` package
- installed Playwright browser binaries, for example `python -m playwright install chromium`

### HTTP Surface MCP

File:

- [mcp_servers/http_fuzzing_server.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/mcp_servers/http_fuzzing_server.py)

Tools exposed:

- `probe_common_paths`
- `method_matrix`

Important boundary:

- this is safe HTTP surface probing for defensive assessment, not offensive fuzzing or payload delivery

### CVE MCP

File:

- [mcp_servers/cve_server.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/mcp_servers/cve_server.py)

Tools exposed:

- `lookup_cve`
- `search_cves`
- `osv_package_query`

Requirements:

- no mandatory API key for basic public use
- optional `NVD_API_KEY` for higher-rate NVD access

## Outputs

The system writes artifacts into [output/](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/output).

Examples:

- execution logs
- planner/worker/reviewer outputs
- search results
- research results
- Excel analysis
- report files
- SQLite database
- work notes

## Social Media Analysis: What Information Is Needed

If the system is extended to analyze social media seriously, the required input is:

- target entities
- aliases and known handles
- domains and websites
- platforms in scope
- time window
- language and geography
- public intelligence vs owned-account analytics
- desired outputs
- compliance/privacy boundaries
- refresh cadence

More specifically:

### Target Definition

- person names
- company names
- organization names
- product names
- campaign names
- hashtags
- keywords
- domains
- known profile URLs or handles

### Analysis Goal

- brand monitoring
- due diligence
- reputation analysis
- narrative tracking
- influencer mapping
- threat detection
- competitor tracking
- engagement benchmarking
- misinformation analysis

### Scope Constraints

- historical depth
- number of entities
- languages
- countries
- budget
- platform-specific access limitations

## Social Media Analysis: Agents Needed

These agents are not yet implemented, but this is the planned design.

### Social Discovery and Identity

- `social_discovery_agent`
  Finds likely profiles/handles across platforms from names, aliases, and domains.
- `social_account_resolution_agent`
  Resolves whether multiple handles belong to the same entity.
- `social_identity_confidence_agent`
  Scores confidence for claimed cross-platform identity matches.

### Content Acquisition

- `social_content_fetch_agent`
  Pulls posts, videos, descriptions, and thread metadata.
- `social_comment_fetch_agent`
  Pulls replies, comments, discussion trees, and conversation context.
- `social_media_normalizer_agent`
  Converts platform-specific content into a common schema.
- `social_media_ocr_transcript_agent`
  Extracts text from memes, images, screenshots, and video/audio transcripts.

### Analysis

- `social_topic_sentiment_agent`
  Topics, sentiment, stance, emotion, toxicity, and audience reaction.
- `social_narrative_shift_agent`
  Tracks framing changes and emergent claims over time.
- `social_engagement_analytics_agent`
  Reach proxies, engagement rates, growth, and anomaly detection.
- `social_network_graph_agent`
  Reply, mention, repost, co-link, and amplification graphing.
- `social_influencer_agent`
  Finds central, amplifying, and bridge accounts.
- `social_timeline_agent`
  Builds a dated event timeline across platforms.
- `social_risk_signal_agent`
  Flags brigading, fraud signals, coordinated behavior, harassment, and reputational threats.
- `social_verification_agent`
  Cross-verifies claims across multiple platforms and external sources.
- `social_citation_agent`
  Packages exact post URLs, timestamps, and evidence references.
- `social_report_agent`
  Produces final user-facing reports from social findings.

### Orchestration Helpers

- `social_scheduler_agent`
  Runs recurring collection/monitoring jobs.
- `social_memory_agent`
  Stores normalized social content in vector memory.
- `social_policy_agent`
  Enforces collection/privacy/platform constraints before collection starts.

## Social Media Analysis: APIs Needed

The actual API set depends on whether you want:

- public social intelligence
- or owned/admin-account analytics

### Strongest First-Wave APIs

- `X API`
- `Reddit API`
- `YouTube Data API`
- `SerpAPI`
- `OpenAI API`
- `Qdrant`

### Platform-Specific APIs

- `X API`
  Public post and profile analysis.
- `Reddit API`
  Posts, comments, subreddit activity.
- `YouTube Data API`
  Videos, channels, comments, metadata.
- `TikTok Research API`
  Only if your access is approved.
- `Instagram Graph API`
  Best for assets you own/administer.
- `Facebook Graph API / Pages`
  Best for pages and assets you manage.
- `LinkedIn APIs`
  Highly constrained and not suitable as a broad public-intelligence backbone.

### Analysis Infrastructure APIs

- `OpenAI API`
  Summarization, extraction, OCR, classification, embeddings.
- `Qdrant`
  Vector memory and retrieval.

## Social Media Analysis: Practical Platform Constraints

This matters because the design must follow what each platform realistically permits.

### Good Public-Intelligence Fit

- X
- Reddit
- YouTube

### Restricted / Conditional

- TikTok research access
- Instagram public analysis beyond owned assets
- Facebook public analysis beyond managed assets
- LinkedIn

The practical recommendation is to build social analysis first around:

1. `X`
2. `Reddit`
3. `YouTube`

Then add:

- TikTok if approved
- Meta assets if you own/administer them
- LinkedIn only for narrow approved use cases

## Social Media Analysis: Recommended Build Order

1. `social_discovery_agent`
2. `social_account_resolution_agent`
3. `x_connector_agent`
4. `reddit_connector_agent`
5. `youtube_connector_agent`
6. `social_media_normalizer_agent`
7. `social_media_ocr_transcript_agent`
8. `social_topic_sentiment_agent`
9. `social_network_graph_agent`
10. `social_timeline_agent`
11. `social_verification_agent`
12. `social_report_agent`

Second wave:

- `tiktok_connector_agent`
- `instagram_connector_agent`
- `facebook_pages_connector_agent`
- `social_risk_signal_agent`
- `social_scheduler_agent`

Last:

- `linkedin_connector_agent`

## Additional APIs That May Be Useful Later

For stronger entity/company intelligence, these are likely next integrations:

- People Data Labs
- Crunchbase
- OpenCorporates
- Clearbit
- Apollo
- SEC/EDGAR connectors
- sanctions/watchlist data providers
- Firecrawl or Browserbase

These are not required for the current implementation, but they become valuable when you want:

- richer corporate enrichment
- registry validation
- ownership tracing
- higher-quality people/entity matching
- stronger adverse screening
- more reliable site extraction

## Compliance and Safety

This system should not be treated as unrestricted “know everything about everyone” infrastructure.

For people research and social analysis, you should define:

- allowed sources
- disallowed PII classes
- retention limits
- audit rules
- operator permissions
- escalation paths for sensitive requests

The role of `access_control_agent` should be expanded before any large-scale people-monitoring workflow is used operationally.

## Known Gaps

What exists now is a strong base, not a finished intelligence platform.

Current gaps:

- no dedicated social connector agents yet
- no external graph database yet
- no sanctions or corporate registry APIs yet
- no end-to-end Docker Compose validation has been performed in this repo

## Verification Status

The current stack has been verified for:

- Python import safety
- compileability
- orchestrator registration
- agent module structure
- Docker asset presence

Not fully verified:

- live end-to-end external API workflows
- Docker runtime execution
- MCP client interoperability
- heavy-load vector indexing behavior

## Files to Read First

If you are new to this repository, read these first:

- [app.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/app.py)
- [tasks/research_infra.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/tasks/research_infra.py)
- [tasks/intelligence_tasks.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/tasks/intelligence_tasks.py)
- [tasks/review_tasks.py](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/tasks/review_tasks.py)
- [docker-compose.yml](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/docker-compose.yml)
- [docs/super_agent_stack.md](/mnt/d/Personal%20Data/projects/multi-agents/sample-agents/docs/super_agent_stack.md)
- `SETUP_UI_HOST`
- `SETUP_UI_PORT`

### OAuth-Optional Communication Variables

- `GOOGLE_CLIENT_ID`
- `GOOGLE_CLIENT_SECRET`
- `GOOGLE_REDIRECT_URI`
- `GOOGLE_OAUTH_SCOPES`
- `MICROSOFT_CLIENT_ID`
- `MICROSOFT_CLIENT_SECRET`
- `MICROSOFT_TENANT_ID`
- `MICROSOFT_REDIRECT_URI`
- `MICROSOFT_OAUTH_SCOPES`
- `SLACK_CLIENT_ID`
- `SLACK_CLIENT_SECRET`
- `SLACK_REDIRECT_URI`
- `SLACK_OAUTH_SCOPES`
