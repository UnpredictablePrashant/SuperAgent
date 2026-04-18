# Assistant Platform Release Roadmap

This document converts the current launch discussion into a versioned execution plan for Kendr.

It is written for the actual repo state on **April 17, 2026** and assumes:

- the near-term product story is **deep research + superRAG + cited report generation**
- the longer-term product direction is **assistant platform with research as one capability**
- most implementation work will be executed through Codex, so work must be broken into narrow, testable packets

## Current State On April 17, 2026

Kendr is currently closer to a **Perplexity-style research product** than to an **OpenClaw-style assistant platform**.

What is already true:

- deep research, superRAG, and report generation are real and demoable
- setup-aware routing, persistence, and retrieval already exist
- the launch path has meaningful polish work behind it

What is still true:

- the platform boundary is not yet OpenClaw-class
- the research UX is not yet Perplexity-class
- the current branch still has launch-critical regressions

Known blockers from the latest wider non-socket regression run:

- `73 passed, 4 failed`
- `tests/test_phase0_cli_smoke.py::Phase0CliSmokeTests::test_run_cli_executes_phase0_deep_research_flow_via_runtime`
- `tests/test_long_document_planning.py::LongDocumentPlanningTests::test_deep_research_analysis_request_reflects_requested_scope_and_caps`
- `tests/test_long_document_planning.py::LongDocumentPlanningTests::test_long_document_agent_recomputes_analysis_when_requested_scope_changes`
- `tests/test_long_document_planning.py::LongDocumentPlanningTests::test_long_document_agent_requires_subplan_approval_before_execution`

Those failures make the first release priority unambiguous: **fix the launch path first**.

Update on **April 18, 2026**:

- dedicated wider non-socket release gate completed clean via `python scripts/release_gate_non_socket.py`
- `566` tests passed
- `0` failed
- `1` skipped
- no deferred wider non-socket failures remain for `v0.2.0`

## Release Cadence

Use a one-week release train after the first launch.

| Day | Activity | Rule |
|---|---|---|
| Monday | Start scoped build work | Only take items assigned to the current release |
| Tuesday | Continue implementation | No speculative platform work unless it unblocks the release |
| Wednesday | Integration and demo validation | Exercise the exact user-facing path that will be released |
| Thursday | Bug-fix only | No new features after Thursday starts |
| Friday | Code freeze | Only release-blocking fixes allowed |
| Saturday | Final verification and packaging | Re-run regression and verify docs/demo assets |
| Sunday | Release | Ship only if exit criteria are met |

For `v0.2.0`, compress the cycle because the launch target is already **April 19, 2026**.

## Codex Execution Rules

Every release below should be executed with the same discipline.

- Keep each Codex task packet small enough to land in one reviewable PR.
- Each packet must have a concrete acceptance test or smoke path.
- Do not mix launch-polish work and architecture work in the same packet unless the architecture change is required to unblock the release.
- Prefer adding seams over doing large rewrites during a release week.
- Any packet that changes CLI, runtime orchestration, or persistence must include regression coverage.
- Any packet that touches a launch demo path must be validated manually in addition to automated tests.

## Roadmap Summary

| Phase | Dates | Release | Product Positioning | Core Goal |
|---|---|---|---|---|
| Phase 0 | April 17-19, 2026 | `v0.2.0` | Deep research + superRAG + cited reports | Launch a credible research product |
| Phase 1 | April 20-26, 2026 | `v0.2.1` | Reliable research product | Stabilize the launch build |
| Phase 2 | April 27-May 3, 2026 | `v0.3.0` | Answer-first research engine | Move closer to Perplexity-style research UX |
| Phase 3 | May 4-10, 2026 | `v0.4.0` | Research product with cleaner internals | Reduce architecture debt in critical paths |
| Phase 4 | May 11-17, 2026 | `v0.5.0` | Platform-ready research product | Introduce capability model v1 |
| Phase 5 | May 18-24, 2026 | `v0.6.0` | Research system evolving toward assistant runtime | Build session-first runtime foundations |
| Phase 6 | May 25-31, 2026 | `v0.7.0` | Single runtime boundary for CLI and UI | Add control-plane seam |
| Phase 7 | June 1-7, 2026 | `v0.8.0` | Extensible platform core | Add plugin and extension lifecycle v1 |
| Phase 8 | June 8-14, 2026 | `v0.9.0` | Assistant platform beta | Establish assistant-platform beta foundation |

## Version Plan

## `v0.2.0` - April 19, 2026

**Theme:** Launch the research product  
**Positioning:** Deep research + superRAG + cited reports  
**Goal:** Ship a launch path that is credible, repeatable, and demo-safe.

### Scope

What this release is:

- a launch for deep research
- a launch for private knowledge retrieval
- a launch for source-backed report generation

What this release is not:

- assistant-platform parity with OpenClaw
- consumer answer-engine parity with Perplexity
- automation platform rollout

### Implementation Checklist

#### A. Launch blockers

- [x] Fix the `kendr run --auto-approve` deep-research CLI regression.
- [x] Restore the long-document approval payload contract so the expected overview fields appear again.
- [x] Fix or safely bypass SQLite bootstrap fragility on launch-critical paths.
- [x] Re-run the current wider non-socket suite until the known `4` failures are cleared or explicitly triaged and deferred.

#### B. Golden path hardening

- [x] Lock one golden demo path: query -> deep research brief -> long report handoff -> exported artifact.
  See [Launch Demo Prompts](launch_demo_prompts.md) for the blessed `competitive-intelligence-diligence` path.
- [x] Ensure the final brief always shows `Objective`, `Coverage`, `Findings`, `Recommended Next Steps`, and `Sources`.
- [x] Ensure the final report/export preserves the research brief card and source sections.
- [x] Ensure the KB-grounded path and the web-backed path both produce citations and source summaries.

#### C. Output polish

- [x] Make source summaries more explicit for `web`, `KB`, and `provided URL` evidence.
- [x] Make the auto-approved long-document handoff read like a clean execution update, not an internal state dump.
- [x] Normalize artifact path rendering in final outputs so demo users can see what was produced.
- [x] Make launch-facing wording consistent across deep research, superRAG, and report export surfaces.

#### D. Demo readiness

- [x] Prepare `2-3` fixed demo prompts that are known to exercise the strongest path.
  See [Launch Demo Prompts](launch_demo_prompts.md) for the blessed launch-week prompt set.
- [ ] Verify one short demo and one deep demo on a clean environment.
- [ ] Prepare launch screenshots or terminal captures using the final output shape.
- [x] Freeze launch messaging around the research product story only.
  The blessed prompt set intentionally excludes assistant-platform and agentic-work demos for `v0.2.0`.

#### E. Test gate

- [ ] Run the launch-critical suite and keep it green.
- [x] Run the wider non-socket suite and document any remaining deferred failures.
- [ ] Manually validate the golden path twice consecutively.
- [ ] Do not add non-launch features after the final green run.

### Codex Work Packets

- [x] Packet 1: Fix the CLI deep-research regression and add a focused regression test if needed.
- [x] Packet 2: Repair long-document planning payload drift and align tests.
- [x] Packet 3: Make runtime bootstrap more resilient around SQLite/WAL initialization.
- [x] Packet 4: Polish final research/report output wording and artifact references.
- [ ] Packet 5: Re-run regression, record final launch test results, and prepare release notes.

### Exit Criteria

- [ ] Launch-critical CLI path is green.
- [ ] Golden demo path works twice in a row.
- [ ] No known crash remains in the research/report path.
- [ ] Product messaging stays inside the research + RAG scope boundary.

## `v0.2.1` - April 26, 2026

**Theme:** Stabilize the launch build  
**Positioning:** Reliable research product  
**Goal:** Turn the launch build into something that can absorb user traffic without constant firefighting.

### Implementation Checklist

#### A. Stability

- [ ] Close every launch bug that was deferred out of `v0.2.0`.
- [ ] Audit persistence edge cases in run bootstrap, report generation, and session saves.
- [ ] Normalize fallback behavior when the planner or report path cannot persist state cleanly.
- [ ] Remove any launch-only hacks that can now be replaced with cleaner guarded logic.

#### B. Regression expansion

- [ ] Expand tests around deep research build and chat/report handoff.
- [ ] Expand tests around superRAG build, chat, session switch, and source summary behavior.
- [ ] Add stronger CLI tests for `kendr run`, `kendr research`, and report export flows.
- [ ] Add non-socket gateway-adjacent tests where possible without relying on bind permissions.

#### C. Research reliability

- [ ] Tighten artifact path consistency across runs and exports.
- [ ] Ensure failed source fetches degrade gracefully and remain visible in output summaries.
- [ ] Improve error messages for research jobs that partially complete.
- [ ] Make retrieval/source mix summaries easier to inspect in JSON and human-readable output.

#### D. UX cleanup

- [ ] Add a simpler `research mode` UX path in CLI or docs.
- [ ] Improve quickstart examples to point users toward the strongest research flows.
- [ ] Make output terminology consistent between `deep research`, `brief`, `report`, and `superRAG`.
- [ ] Document the supported launch workflows clearly.

### Codex Work Packets

- [ ] Packet 1: Persistence and bootstrap hardening.
- [ ] Packet 2: Research/superRAG regression expansion.
- [ ] Packet 3: CLI/output terminology cleanup.
- [ ] Packet 4: Quickstart/demo docs alignment.

### Exit Criteria

- [ ] Launch bugs are closed or explicitly deferred with rationale.
- [ ] Research, superRAG, report, and CLI flows have broader regression coverage.
- [ ] Failure cases are clearer and less brittle.

## `v0.3.0` - May 3, 2026

**Theme:** Perplexity-style research UX pass  
**Positioning:** Answer-first research engine  
**Goal:** Improve the user experience of research enough that Kendr feels substantially closer to Perplexity in research quality and clarity.

### Implementation Checklist

#### A. Source modes

- [ ] Add explicit source modes for `web`, `local/KB`, and `hybrid`.
- [ ] Reflect the selected source mode in CLI/UI output and final artifacts.
- [ ] Ensure the runtime respects source mode boundaries instead of silently mixing sources.
- [ ] Add source-mode regression coverage.

#### B. Answer-first UX

- [ ] Improve the initial answer shape so users get a concise grounded answer before reading the longer brief.
- [ ] Add a visible explanation of what evidence classes were used.
- [ ] Improve the way follow-up questions reuse prior context within the same research thread.
- [ ] Add a clear distinction between a quick brief and a deep report path.

#### C. Citation and transparency

- [ ] Improve inline citation visibility.
- [ ] Add source-card style summaries or equivalent terminal-friendly source breakdown.
- [ ] Surface retrieval/source trust signals such as hit counts, evidence type, or freshness where available.
- [ ] Make it obvious when an answer is grounded only in local files versus web + local evidence.

#### D. Research trace

- [ ] Expose a concise "how the answer was built" section.
- [ ] Show major search/retrieval steps without overwhelming the user.
- [ ] Add source-ledger references into the report flow where useful.
- [ ] Keep the trace readable in both JSON and terminal output.

### Codex Work Packets

- [ ] Packet 1: Source mode plumbing and state contract.
- [ ] Packet 2: Answer-first output and brief/deep split.
- [ ] Packet 3: Citation/source-card UX improvements.
- [ ] Packet 4: Follow-up continuity and research trace.

### Exit Criteria

- [ ] Users can choose source mode intentionally.
- [ ] Research outputs feel faster, clearer, and more trustworthy.
- [ ] Kendr is materially closer to Perplexity on research UX.

## `v0.4.0` - May 10, 2026

**Theme:** Internal architecture seam cleanup  
**Positioning:** Research product with cleaner internals  
**Goal:** Reduce code fragility in the current launch-critical paths without attempting a platform rewrite.

### Implementation Checklist

#### A. File decomposition

- [ ] Split research/retrieval/synthesis/report concerns into clearer modules.
- [ ] Reduce pressure inside `kendr/runtime.py`.
- [ ] Reduce pressure inside `kendr/cli.py`.
- [ ] Reduce pressure inside `kendr/ui_server.py`.

#### B. Boundary cleanup

- [ ] Make research orchestration less dependent on shared mutable runtime state.
- [ ] Create clearer interfaces between ingestion, retrieval, synthesis, and export.
- [ ] Normalize output payload structures for research results.
- [ ] Reduce hidden coupling between CLI presentation and runtime internals.

#### C. Testability

- [ ] Add smaller module-level tests around separated logic.
- [ ] Replace broad integration-only assumptions with more direct unit coverage where possible.
- [ ] Make it easier to test report generation without booting the full runtime.
- [ ] Make persistence adapters easier to stub.

### Codex Work Packets

- [ ] Packet 1: Extract research output and report boundary modules.
- [ ] Packet 2: Extract runtime/session helpers from the runtime monolith.
- [ ] Packet 3: Extract CLI command helpers from the CLI monolith.
- [ ] Packet 4: Add targeted tests around the new seams.

### Exit Criteria

- [ ] Core research code is easier to change safely.
- [ ] Monolith pressure is lower in the most active files.
- [ ] New tests can target narrower modules.

## `v0.5.0` - May 17, 2026

**Theme:** Capability model v1  
**Positioning:** Platform-ready research product  
**Goal:** Stop modeling the product as a flat set of agents and start modeling it as a capability system.

### Implementation Checklist

#### A. Capability taxonomy

- [ ] Define first-class capability kinds: `workflow`, `tool`, `provider`, `memory`, `skill`, `plugin`.
- [ ] Document how research, superRAG, report export, and setup-aware routing map into those capability kinds.
- [ ] Replace user-facing language that treats every surface as an agent when that is no longer accurate.
- [ ] Preserve compatibility for existing routing where needed.

#### B. Registry improvements

- [ ] Extend the registry model to track capability kind and basic metadata.
- [ ] Separate runtime plugin information from external integrations in the internal model.
- [ ] Surface capability diagnostics and health information.
- [ ] Record disabled, incompatible, or degraded capability states more clearly.

#### C. Research as a capability family

- [ ] Group deep research, long-document reporting, superRAG, and local-drive intelligence into a capability family model.
- [ ] Make it clear which surfaces are retrieval-heavy, which are synthesis-heavy, and which are workflow surfaces.
- [ ] Expose capability-family metadata where it helps routing and setup.
- [ ] Keep backward compatibility with existing CLI paths.

### Codex Work Packets

- [ ] Packet 1: Capability type definitions and docs.
- [ ] Packet 2: Registry metadata upgrade.
- [ ] Packet 3: Capability health/diagnostics surface.
- [ ] Packet 4: Research capability-family mapping.

### Exit Criteria

- [ ] The internal model is no longer just "flat registry of agents".
- [ ] Capability kind and health are inspectable.
- [ ] Research is modeled as one capability family, not the whole product identity.

## `v0.6.0` - May 24, 2026

**Theme:** Session-first runtime foundation  
**Positioning:** Research system evolving toward assistant runtime  
**Goal:** Build the runtime shape needed for an assistant platform without yet building the full gateway.

### Implementation Checklist

#### A. Core runtime concepts

- [ ] Define and document `session`, `run`, and `workflow` separately.
- [ ] Improve follow-up continuity across a session.
- [ ] Add more explicit run lifecycle states.
- [ ] Make resume/wait semantics more consistent for long-running research flows.

#### B. Session consistency

- [ ] Move toward per-session serialization for sensitive long-running work.
- [ ] Reduce race-prone shared state updates where practical.
- [ ] Separate session memory from run artifacts more explicitly.
- [ ] Make it easier to inspect what belongs to the current session versus the current run.

#### C. Streaming and progress

- [ ] Improve progress/status updates for long-running research work.
- [ ] Define a clearer internal event model for progress, approval, completion, and failure.
- [ ] Keep compatibility with current CLI output while preparing for a later control plane.
- [ ] Add regression coverage for wait/resume/progress flows.

### Codex Work Packets

- [ ] Packet 1: Session/run/workflow contract.
- [ ] Packet 2: Session-consistency and serialization helpers.
- [ ] Packet 3: Progress/event model cleanup.
- [ ] Packet 4: Wait/resume regression coverage.

### Exit Criteria

- [ ] Session behavior is more consistent.
- [ ] Long-running work is easier to resume and inspect.
- [ ] The runtime has a believable path toward an assistant model.

## `v0.7.0` - May 31, 2026

**Theme:** Control-plane seam  
**Positioning:** Single runtime boundary for CLI and UI  
**Goal:** Stop letting CLI and UI act like separate execution worlds.

### Implementation Checklist

#### A. Boundary creation

- [ ] Create a stable internal API boundary for run/session submission.
- [ ] Move CLI and UI entrypoints to use the same submission/status primitives.
- [ ] Stop importing large runtime modules directly into UI routes where avoidable.
- [ ] Make it possible to inspect the control plane without starting the full execution path.

#### B. Shared status model

- [ ] Centralize status, progress, and completion semantics.
- [ ] Normalize how runs are listed, resumed, and inspected.
- [ ] Add a clear internal response model for status queries.
- [ ] Add tests for the shared control-plane surface.

#### C. Prep for a future gateway

- [ ] Keep the boundary transport-agnostic so a later WebSocket layer can sit on top.
- [ ] Avoid overfitting the boundary to the current HTTP shape.
- [ ] Document what remains missing before a true OpenClaw-style gateway can exist.
- [ ] Keep release scope limited to the seam, not the full gateway rewrite.

### Codex Work Packets

- [ ] Packet 1: Shared run/session submission API.
- [ ] Packet 2: UI entrypoint migration to shared primitives.
- [ ] Packet 3: CLI entrypoint migration cleanup.
- [ ] Packet 4: Shared status/resume tests and docs.

### Exit Criteria

- [ ] CLI and UI use the same runtime boundary for core flows.
- [ ] Status and resume behavior are more uniform.
- [ ] The repo is prepared for a later gateway layer.

## `v0.8.0` - June 7, 2026

**Theme:** Plugin and extension lifecycle v1  
**Positioning:** Extensible platform core  
**Goal:** Upgrade extension handling from loose Python-module loading toward a more inspectable and controlled lifecycle.

### Implementation Checklist

#### A. Manifest direction

- [ ] Introduce a manifest shape for runtime plugins.
- [ ] Track plugin version, compatibility, capability claims, and basic permissions metadata.
- [ ] Keep Python-module compatibility while introducing the manifest-backed path.
- [ ] Document the compatibility contract clearly.

#### B. Discovery and diagnostics

- [ ] Surface plugin discovery failures more clearly.
- [ ] Expose discovered, validated, loaded, activated, degraded, and failed states where practical.
- [ ] Add diagnostics around incompatible or misconfigured plugins.
- [ ] Separate integration naming from runtime plugin naming in UX and docs where possible.

#### C. Safety and isolation groundwork

- [ ] Add basic permission metadata for plugins and MCP-backed surfaces.
- [ ] Document which execution surfaces remain in-process and which should move out later.
- [ ] Add kill-switch or disable paths for broken extensions.
- [ ] Keep scope realistic by avoiding a full subprocess-host implementation in the same release.

### Codex Work Packets

- [ ] Packet 1: Manifest schema and loader compatibility path.
- [ ] Packet 2: Discovery state and diagnostics.
- [ ] Packet 3: Plugin permission metadata and docs.
- [ ] Packet 4: Disable/degrade controls and regression tests.

### Exit Criteria

- [ ] Extension state is inspectable.
- [ ] Compatibility and diagnostics are clearer.
- [ ] The extension model is moving toward a real platform contract.

## `v0.9.0` - June 14, 2026

**Theme:** Assistant-platform beta foundation  
**Positioning:** Assistant platform with research as one capability  
**Goal:** Reach the first version that can honestly be described as an assistant-platform beta.

### Implementation Checklist

#### A. Product identity shift

- [ ] Reframe docs and entrypoints around an assistant-first session model.
- [ ] Keep research as a major capability pack, not the entire product identity.
- [ ] Make core workflows discoverable as capabilities, not just task families.
- [ ] Clarify what remains beta and what is stable.

#### B. Capability-aware routing

- [ ] Use the capability model to improve routing decisions.
- [ ] Expose health and readiness checks for operator-facing setup.
- [ ] Improve approval/safety boundaries for higher-power workflows.
- [ ] Make degraded capability states visible in the operator experience.

#### C. Limited platform features

- [ ] Add a small, credible automation or assistant-session surface if still needed.
- [ ] Add better operator health or doctor checks.
- [ ] Improve memory behavior for longer-lived assistant sessions.
- [ ] Keep the feature set narrow enough that the beta claim remains defensible.

#### D. Explicit deferrals

- [ ] Do not claim multi-channel parity with OpenClaw yet.
- [ ] Do not claim node/device/pairing parity with OpenClaw yet.
- [ ] Do not claim full consumer answer-engine parity with Perplexity yet.
- [ ] Document the remaining platform gaps clearly.

### Codex Work Packets

- [ ] Packet 1: Assistant-first docs and workflow framing.
- [ ] Packet 2: Capability-aware routing improvements.
- [ ] Packet 3: Operator health/doctor and safety polish.
- [ ] Packet 4: Limited assistant-surface implementation and tests.

### Exit Criteria

- [ ] Kendr can credibly be described as an assistant-platform beta.
- [ ] Research remains a major capability, not the only product story.
- [ ] Remaining OpenClaw and Perplexity gaps are explicit and honest.

## Parity Guidance

This roadmap intentionally splits parity into two tracks.

### Closer To Perplexity

Releases that move Kendr toward Perplexity-style research behavior:

- `v0.2.0`: ship the launchable research path
- `v0.2.1`: stabilize it
- `v0.3.0`: improve answer-first UX, source modes, and citation clarity

### Closer To OpenClaw

Releases that move Kendr toward OpenClaw-style platform architecture:

- `v0.4.0`: reduce architecture debt
- `v0.5.0`: capability model
- `v0.6.0`: session-first runtime foundations
- `v0.7.0`: control-plane seam
- `v0.8.0`: extension lifecycle
- `v0.9.0`: assistant-platform beta framing

## Practical Priority Order

If there is not enough capacity in a given week, cut work in this order:

1. cut speculative architecture work
2. cut non-demo UX extras
3. cut broad documentation refreshes
4. do not cut launch-path fixes
5. do not cut regression work for changed paths

## Final Rule

Until `v0.3.0` is shipped, the product should be described publicly as:

- deep research
- private knowledge retrieval
- source-backed report generation

Not as:

- full assistant platform
- OpenClaw parity
- Perplexity parity

That broader positioning only becomes reasonable after the later runtime, control-plane, and capability-model releases have landed.
