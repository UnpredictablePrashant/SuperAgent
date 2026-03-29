# LLM Feature Delivery Guide

This guide defines the architecture and delivery rules that GPT or any other LLM must follow when adding a new feature to Kendr.

The purpose of this guide is to stop feature drift, prevent undocumented changes, and ensure new work is embedded properly into the product.

## Non-Negotiable Rules

- Start from a user-facing problem, not from a code-first idea.
- Keep the diff as small as possible while still delivering a complete feature.
- Every user-visible feature requires docs, examples, tests, and setup guidance.
- Do not grow giant files unless there is a clear reason.
- Do not invent integrations or dependencies that are not wired into setup and routing.
- Do not expose unconfigured capabilities to the runtime.
- Mark new features as `stable`, `beta`, or `experimental`.

## Mandatory Feature Intake Template

Before coding, the LLM must write down:

- feature name
- user problem
- target user
- command or entrypoint
- runtime state inputs
- outputs and artifacts
- dependencies and environment variables
- security and approval requirements
- failure modes
- docs that must change
- tests that must be added

If the feature cannot fill in those fields, it is not ready to implement.

## Feature Architecture Contract

Every feature must move through these layers.

### 1. User Surface

Decide where the feature is entered:

- CLI
- gateway payload
- setup UI
- plugin
- background daemon
- internal agent dispatch

If the entrypoint is user-facing, the docs and examples must show it.

### 2. State Contract

Define the runtime keys clearly.

For every new state key:

- name it consistently
- document its type and meaning
- document default behavior
- document whether it is required or optional

Do not scatter undocumented state keys through multiple modules.

### 3. Registration Path

If the feature is an agent:

- add or update `AGENT_METADATA` in the task module
- ensure discovery can see the agent
- define `skills`, `input_keys`, `output_keys`, and `requirements`

If the feature is a provider or channel:

- register it in `kendr/discovery.py`
- document how the runtime knows it is available

### 4. Setup Awareness

If the feature depends on external setup:

- update `.env.example`
- update `tasks/setup_registry.py`
- update any setup UI or config store paths
- ensure unconfigured features are filtered out from routing

No new external dependency is complete until setup detection exists.

### 5. Implementation Layer

Put feature logic in the right place:

- domain agent behavior belongs in task modules
- provider-specific helpers belong near provider/setup code
- gateway/http behavior belongs in gateway modules
- persistence belongs in storage modules

Do not bury cross-cutting logic in unrelated task files.

### 6. Persistence And Artifacts

If the feature creates durable outputs:

- decide whether it belongs in run artifacts, SQLite, or both
- use predictable filenames
- keep artifact format easy to inspect
- document where users will find the output

### 7. Documentation Embedding

Every completed feature must update the relevant docs:

- README if the feature is important enough for the landing page
- `SampleTasks.md` with a real example
- `docs/` for setup, usage, and troubleshooting
- feature status if the feature is beta or experimental

If the feature is not documented, it is not done.

### 8. Verification

Every feature must add verification at the right level:

- unit tests for pure logic
- routing/setup tests for registry or availability changes
- smoke tests for CLI or gateway behavior
- docs/examples updated to match the real interface

## Repository-Specific Rules

### If You Add A New Agent

You must:

- place it in the correct domain task module or extract a new domain module if needed
- add or update `AGENT_METADATA`
- define required inputs and outputs
- ensure discovery picks it up
- ensure runtime setup gating is correct
- add sample usage
- add tests for discovery and execution path

### If You Add A New Provider

You must:

- register it in discovery
- add setup detection and health checks
- add environment/config documentation
- add routing availability logic
- document failure modes and missing setup behavior

### If You Add A New Channel Or Gateway Surface

You must:

- define payload contract
- normalize channel naming consistently
- document session behavior
- document auth or allowlist rules
- add gateway or CLI smoke coverage

### If You Add New Environment Variables

You must update:

- `.env.example`
- setup registry/config handling
- docs explaining what the variables do
- verification or error messaging for missing values

### If You Add Persistence

You must:

- document storage location
- keep schema/file naming consistent
- add tests for round-trip behavior
- explain migration implications if schema changes

## Complexity Limits

When implementing a new feature:

- avoid adding more logic to files that are already oversized unless you are also extracting code
- prefer creating focused modules over increasing monolith size
- if the change touches 4 or more major subsystems, write a short design note first

## Required Design Note For Medium Or Large Features

Before implementing, the LLM should write a short design note with:

- problem statement
- chosen entrypoint
- state keys
- affected modules
- setup changes
- docs changes
- test plan
- risks and rollback plan

This can live in the task response or in a temporary repo doc during implementation.

## Definition Of Done For Any New Feature

A feature is complete only if:

- the feature works from the intended entrypoint
- setup gating is correct
- docs are updated
- sample usage exists
- tests exist
- outputs are discoverable
- status is labeled stable, beta, or experimental
- the code did not make the architecture worse without justification

## Copy-Paste Prompt For Any New Feature

```text
You are implementing a new feature in the Kendr repository.

Follow the repository's LLM Feature Delivery Guide exactly.

Before changing code:
1. Inspect the existing architecture and identify the correct entrypoint.
2. Write a short design note covering:
   - user problem
   - entrypoint
   - state keys
   - affected files
   - setup/env changes
   - persistence/artifacts
   - docs changes
   - tests
3. Reuse existing patterns where they are good, and improve them only when necessary.

Implementation requirements:
- Keep the diff minimal but complete.
- Do not invent undocumented state keys.
- If the feature depends on external setup, update `.env.example`, setup detection, and docs.
- If the feature adds an agent, update `AGENT_METADATA`, discovery compatibility, docs, and tests.
- If the feature is user-facing, update `SampleTasks.md` and the relevant docs.
- If the feature is experimental, label it clearly in docs.
- Prefer extracting modules over making large files even larger.

Verification requirements:
- add or update tests
- run the most relevant verification commands available
- summarize what was verified and what was not

Deliverables:
- code patches
- docs patches
- tests
- concise explanation of the architecture path followed
```

## Copy-Paste Prompt For Reviewing A Proposed Feature Before Coding

```text
Review this proposed Kendr feature before implementation.

Your job:
1. Validate whether the feature fits the current product thesis.
2. Map the correct architecture path:
   - entrypoint
   - state contract
   - agent/provider/channel registration
   - setup gating
   - persistence/artifacts
   - docs/tests
3. Identify risks, missing setup requirements, security issues, and likely file boundaries.
4. Recommend the smallest correct implementation plan.

Do not write code yet.
Return:
- architecture plan
- affected files
- required docs updates
- required tests
- stable/beta/experimental recommendation
```
