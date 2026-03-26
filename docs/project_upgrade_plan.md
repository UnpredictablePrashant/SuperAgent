# SuperAgent Upgrade Plan

This document is the execution plan for turning SuperAgent from a capable framework into a polished product.

The plan is intentionally phased. Do not start the next phase until the acceptance criteria for the current phase are met.

## Core Principles

- Product clarity beats raw surface area.
- Docs must describe what is real today, not what might exist later.
- Every user-visible feature needs docs, tests, setup guidance, and artifacts.
- New code should reduce future complexity, not add to it.
- Prefer extracting modules over continuing to grow already large files.

## Target Outcome

By the end of this plan, SuperAgent should feel like:

- a clearly positioned multi-agent research and intelligence runtime
- easy to install and understand
- documented like a product, not a lab notebook
- structured so new agents and integrations can be added safely
- verified enough that users trust the default path

## Phase 0: Product Thesis And Scope

### Goal

Define exactly what SuperAgent is, who it is for, and which workflows are first-class.

### Deliverables

- one clear product sentence for the README hero
- one primary audience definition
- a feature status matrix: `stable`, `beta`, `experimental`
- 3 primary workflows to highlight everywhere
- a list of features to de-emphasize or move to "experimental"

### Acceptance Criteria

- the first 20 lines of the README explain the product without listing dozens of agents
- every major feature area has a status label
- the project can be described in one sentence without "and also" repetition

### GPT Prompt

```text
You are working inside the SuperAgent repository.

Your job is to rewrite the project positioning before any further feature work happens.

Tasks:
1. Inspect README.md, SampleTasks.md, docs/, superagent/, and tasks/.
2. Determine the strongest product thesis for the repo based on what is actually implemented today.
3. Produce a concise positioning update centered on one primary identity:
   - multi-agent research runtime
   - intelligence workspace
   - or another better fit grounded in the codebase
4. Create a feature status matrix with stable, beta, and experimental sections.
5. Rewrite the README hero, opening summary, and top-level navigation so the repo reads like a product.
6. Do not remove valuable features, but move secondary features out of the hero path.
7. Update docs to reflect the chosen positioning.

Constraints:
- Do not invent features.
- Use only what is implemented or explicitly marked as experimental.
- Keep the README opening focused and readable.
- Add acceptance notes summarizing the new scope.

Deliverables:
- patched docs
- a short summary of the new thesis
- a list of features moved to experimental status
```

## Phase 1: Documentation And Public Surface

### Goal

Replace the monolithic documentation style with a product docs structure.

### Deliverables

- a shorter README that acts as a landing page
- dedicated docs for quickstart, install, architecture, agents, integrations, security, and troubleshooting
- removal of all absolute local filesystem links from public docs
- a docs index page in `docs/`
- one "first success in 10 minutes" path

### Acceptance Criteria

- no public README links use absolute local filesystem paths
- README acts as overview, not full manual
- a new user can find install, setup, first run, and troubleshooting in under 3 clicks
- docs explain setup-aware routing, plugins, gateway, and output artifacts clearly

### GPT Prompt

```text
You are improving the documentation architecture of SuperAgent.

Tasks:
1. Audit README.md and docs/.
2. Convert the current documentation into a cleaner structure:
   - README as landing page
   - docs/quickstart.md
   - docs/install.md
   - docs/architecture.md
   - docs/agents.md
   - docs/integrations.md
   - docs/security.md
   - docs/troubleshooting.md
   - docs/examples.md
3. Remove absolute local filesystem links and replace them with repo-relative references.
4. Create a docs index that points to all major guides.
5. Keep all claims grounded in the codebase.
6. Add a short "first run" walkthrough using the actual `superagent` CLI.

Constraints:
- Do not delete important information; relocate and simplify it.
- Do not leave agent inventory or configuration docs stale.
- Keep docs readable for new users.

Verification:
- confirm there are no absolute local filesystem links left in public docs
- summarize the new docs structure
```

## Phase 2: Architecture Refactor

### Goal

Break the runtime into maintainable product boundaries.

### Deliverables

- extraction plan for oversized files
- package boundaries for runtime, gateway, agents, providers, memory, setup, and persistence
- typed runtime state models or equivalent structured contracts
- generated or centralized agent catalog
- reduced coupling between task logic and provider/setup logic

### Acceptance Criteria

- new code no longer defaults to giant task modules
- the largest files are materially reduced or have clear extraction seams
- setup logic, persistence logic, and orchestration logic are easier to reason about
- the feature registration path is documented and predictable

### GPT Prompt

```text
You are refactoring SuperAgent for long-term maintainability.

Tasks:
1. Inspect the largest files in the repository, especially:
   - superagent/cli.py
   - superagent/runtime.py
   - tasks/sqlite_store.py
   - tasks/intelligence_tasks.py
   - tasks/superrag_tasks.py
   - tasks/long_document_tasks.py
2. Propose and implement an incremental refactor that splits code by responsibility, not by arbitrary helpers.
3. Create cleaner package boundaries for:
   - orchestration/runtime
   - gateway/http surfaces
   - setup/integration detection
   - providers
   - persistence
   - domain agents
4. Introduce stronger typing around shared runtime state where practical.
5. Keep behavior unchanged unless a bug is being fixed.
6. Update tests and docs for any moved modules.

Constraints:
- Do not rewrite the whole project in one pass.
- Favor small coherent refactors with tests.
- Preserve CLI and runtime behavior.
- If a file exceeds about 600-800 lines after the refactor, justify why.

Deliverables:
- code patches
- updated imports/tests/docs
- short rationale for each extraction boundary
```

## Phase 3: Setup, Integration, And Contract Discipline

### Goal

Make every provider, channel, and optional tool follow one predictable lifecycle.

### Deliverables

- a documented integration contract
- consistent environment variable definitions
- setup detection rules for every optional integration
- setup UI coverage for every supported provider/tool
- health and misconfiguration reporting

### Acceptance Criteria

- adding a new integration follows one documented pattern
- `.env.example`, setup registry, discovery, docs, and tests stay in sync
- runtime only routes to integrations that are configured and healthy

### GPT Prompt

```text
You are standardizing integration architecture in SuperAgent.

Tasks:
1. Audit superagent/discovery.py, tasks/setup_registry.py, tasks/setup_config_store.py, .env.example, README.md, and SampleTasks.md.
2. Define and implement one integration lifecycle covering:
   - declaration
   - configuration
   - setup detection
   - health reporting
   - routing eligibility
   - docs
   - tests
3. Make inconsistencies visible and fix them.
4. Add or improve tests for setup-aware routing and missing dependency handling.
5. Update docs so future integrations follow the same contract.

Constraints:
- Preserve backward compatibility where reasonable.
- Do not expose unconfigured agents to routing.
- Keep user-facing setup instructions concrete.

Deliverables:
- code patches
- docs patches
- integration checklist added to repo docs
```

## Phase 4: Verification And CI Hardening

### Goal

Make the default development and validation path reliable.

### Deliverables

- one documented bootstrap path
- deterministic test entrypoints
- dependency validation
- docs link checks
- Docker Compose smoke checks
- e2e smoke tests for core flows

### Acceptance Criteria

- a new developer can bootstrap and run tests without guesswork
- CI reflects the documented local workflow
- the project has smoke coverage for `run`, `gateway`, `setup`, and `superrag`
- docs and examples are tested, not just written

### GPT Prompt

```text
You are hardening SuperAgent verification and CI.

Tasks:
1. Audit requirements.txt, pyproject.toml, Makefile, scripts/, docker-compose.yml, and tests/.
2. Find all gaps between documented setup and actual test/runtime expectations.
3. Implement a reliable bootstrap and verification path for developers.
4. Add or improve smoke tests for:
   - CLI entrypoint
   - registry discovery
   - setup-aware routing
   - gateway surface
   - superRAG basic flow
5. Add docs-link validation and Docker Compose smoke validation where practical.
6. Update documentation to match the real verification flow.

Constraints:
- Prefer the simplest reliable workflow.
- Do not add fragile network-dependent tests as default unit tests.
- Clearly separate unit, smoke, and integration checks.

Deliverables:
- code and CI patches
- updated developer docs
- explicit verification summary
```

## Phase 5: Product Wedge Excellence

### Goal

Make a small number of workflows excellent instead of many workflows merely present.

### Recommended First-Class Workflows

- deep research
- local drive intelligence
- superRAG build and chat

### Deliverables

- polished sample tasks
- stable docs and demos
- clearer artifacts and output quality expectations
- screenshots or example outputs
- tighter guardrails and failure messages

### Acceptance Criteria

- the 3 primary workflows are easy to run and easy to demo
- outputs are predictable and well documented
- setup requirements and failure states are explicit

### GPT Prompt

```text
You are productizing the core SuperAgent workflows.

Primary workflows:
- deep research
- local drive intelligence
- superRAG
- coding project master
- local command execution

Tasks:
1. Audit the implementation and docs for those workflows.
2. Improve them end to end:
   - CLI usability
   - docs clarity
   - examples
   - output artifacts
   - error handling
   - setup validation
3. Add or refine sample tasks and acceptance examples.
4. Tighten the README and docs so these workflows are the recommended entry points.

Constraints:
- Keep changes grounded in actual code.
- Do not broaden scope during this phase.
- Prefer polish and reliability over new surface area.

Deliverables:
- code/docs/test updates
- a short demo script or walkthrough for each workflow
```

## Phase 6: Plugin And Agent SDK

### Goal

Turn the current plugin mechanism into a documented extension system.

### Deliverables

- versioned plugin contract
- plugin manifest/schema
- compatibility rules
- example plugins
- plugin test harness
- docs for adding agents, providers, and channels

### Acceptance Criteria

- external contributors can build plugins without reading internal runtime code first
- plugin compatibility is documented
- example plugins cover common patterns

### GPT Prompt

```text
You are turning SuperAgent's plugin mechanism into a real extension SDK.

Tasks:
1. Audit plugin_templates/, superagent/types.py, superagent/discovery.py, and registry/runtime integration points.
2. Define a versioned plugin contract for external contributors.
3. Add missing structure such as:
   - plugin manifest expectations
   - compatibility/version notes
   - examples for agent plugins and provider plugins
   - plugin test guidance
4. Improve docs so an external contributor can add a plugin safely.

Constraints:
- Preserve current plugin support where possible.
- Keep the SDK simple and Python-native.
- Document what is stable vs internal.

Deliverables:
- SDK docs
- example plugin improvements
- compatibility guidance
```

## Phase 7: Visibility, Releases, And Public Trust

### Goal

Make the project discoverable and credible from the outside.

### Deliverables

- GitHub repo description
- GitHub homepage/docs URL
- release cadence and changelog
- screenshots or demo GIFs
- docs site deployment
- showcase section
- contribution guide

### Acceptance Criteria

- the GitHub repo explains the product without opening the code
- releases communicate what changed
- users can see what the project looks like and what it is good at

### GPT Prompt

```text
You are improving the public trust and visibility layer of SuperAgent.

Tasks:
1. Audit the repository for missing public-facing assets:
   - GitHub metadata
   - release notes
   - changelog
   - screenshots/demo assets
   - docs landing page
   - contribution guidance
2. Add or improve the repo assets that make the project credible to new users.
3. Create a release/readme/docs structure that communicates:
   - what SuperAgent is
   - what it does well
   - how to install it
   - how to verify it
   - how to contribute safely

Constraints:
- Keep all claims true.
- Prefer fewer strong examples over many weak examples.
- Align messaging with the product thesis from Phase 0.

Deliverables:
- docs and repo metadata recommendations
- any repo file changes possible from within the repo
- a public release checklist
```

## Execution Notes

- Run Phase 0 first.
- Run Phases 1 and 4 immediately after Phase 0.
- Run Phase 2 before adding large new feature areas.
- Run Phase 3 before adding new providers, channels, or OAuth surfaces.
- Run Phase 5 only after the base product story is stable.
- Run Phases 6 and 7 when the core workflows are trustworthy.

## Definition Of Done

SuperAgent is in a strong product state when:

- the README is clear and short
- the docs are structured and truthful
- the main workflows are reliable and demoable
- the architecture is modular enough for safe feature growth
- new integrations follow one contract
- tests and smoke checks match the documented workflow
- the public repo looks like a maintained product
