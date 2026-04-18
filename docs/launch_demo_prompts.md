# Launch Demo Prompts

These are the blessed demo prompts for `v0.2.0`.

Use the prompt text exactly during launch week. Do not improvise wording unless you are deliberately running a non-launch demo.

The goal is to keep launch validation inside the current product story:

- deep research
- private knowledge retrieval when prepared
- source-backed report generation

## Primary Golden Path

Source case study: `competitive-intelligence-diligence`

This is the main launch path to validate and show:

- query
- deep research brief
- long-report handoff
- exported artifact

Recommended command:

```bash
kendr run --current-folder \
  --auto-approve \
  --deep-research \
  --deep-research-pages 40 \
  --format html,md \
  --cite apa \
  --research-model o4-mini-deep-research \
  --research-instructions "Cite concrete sources, separate verified facts from inferred conclusions, and keep an unresolved questions section." \
  "Build a diligence-grade competitive intelligence brief on the cloud backup and recovery software market. Compare Veeam, Rubrik, Druva, and Cohesity. Verify positioning, pricing clues, deployment model, traction signals, and risk factors. Separate verified facts from inferred conclusions and flag contradictions or weak evidence."
```

Expected shape:

- `Deep Research Brief` appears first
- the brief includes `Objective`, `Coverage`, `Findings`, `Recommended Next Steps`, and `Sources`
- the run hands off into the long-document lane without an approval dead-end
- an exported HTML or Markdown report is produced
- the final output preserves citations and source summaries

Prepared-KB variant:

If the demo environment already has an active diligence KB, rerun the exact same prompt with:

```bash
--research-use-active-kb --research-kb-top-k 8
```

## Supporting Demo 1

Source case study: `market-mapping-product-signals`

Use this as the shorter research demo when you want a public-web path without requiring a prepared corpus.

Recommended command:

```bash
kendr run --current-folder \
  --auto-approve \
  --deep-research \
  --deep-research-pages 25 \
  --format html,md \
  --cite apa \
  --research-model o4-mini-deep-research \
  --research-instructions "Track changes across competitors, keep citations for every signal, and flag weak evidence separately." \
  "Map the product analytics platform landscape. Focus on Amplitude, Mixpanel, Pendo, and PostHog. Cover ICP, positioning, pricing and packaging patterns, launch velocity, and where the category appears crowded versus under-served. Keep citations for every signal and flag weak evidence separately."
```

Expected shape:

- category map
- competitor and pricing signals
- citations for each major claim
- a reusable report artifact instead of a chat-only answer

## Supporting Demo 2

Source case study: `policy-reviews-dense-documents`

Use this only when the demo machine has a prepared local policy pack. This is the strongest dense-document demo in the current launch story.

Recommended command:

```bash
kendr run --current-folder \
  --auto-approve \
  --deep-research \
  --no-web-search \
  --drive <prepared-policy-pack> \
  --drive-max-files 20 \
  --deep-research-pages 25 \
  --format html,md \
  --cite apa \
  "Review the attached policy and source documents for data retention and access control requirements. Identify major obligations, effective dates, ambiguous or operationally risky sections, and where a human reviewer should pay special attention. Separate clear extraction from interpretation and cite the source section for every major point."
```

Expected shape:

- cited summary
- material-change or obligation list
- explicit ambiguity or human-review section
- exported report artifact with source traceability

## Not Blessed For `v0.2.0`

These KendrWeb case studies are good product stories, but they are not the launch demos for this release:

- `architecture-review-action-plan`
- `research-to-repeatable-team-work`

They lean into the broader assistant-platform or agentic-work story, while `v0.2.0` is intentionally scoped to research, KB, and cited reports.

## Release Rule

For manual launch validation:

1. Run the primary golden path twice in a clean environment.
2. Run one supporting demo.
3. Capture screenshots or terminal output from the primary golden path, not from an experimental prompt.
