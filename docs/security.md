# Security

Kendr should be treated as a governed intelligence workspace, not as unrestricted automation.

## Product Security Posture

Current security expectations in the repo are:

- setup-aware routing so unconfigured capabilities are not selected
- approval stages before execution
- privileged-mode guardrails for broad filesystem or root-level operations
- defensive-only framing for the security assessment workflow
- explicit scope and authorization requirements for security tasks

## Authorized Security Assessment Workflow

Status: Beta.

The repo includes a defensive security-assessment workflow for authorized targets.

Included:

- passive web reconnaissance
- passive API surface mapping from exposed documentation
- unauthenticated endpoint triage
- IDOR/BOLA risk review from design clues
- security-header review
- TLS and certificate review
- dependency and static code review
- prompt and AI configuration review
- AI/RAG/vector/storage exposure review
- evidence and report generation

Not included:

- operational exploitation
- credential attacks
- denial-of-service tooling
- malware deployment
- persistence or post-exploitation automation
- unauthorized access workflows

## Required Authorization

Before running security assessment workflows:

1. confirm ownership or explicit written permission
2. define scope boundaries and testing window
3. record an authorization reference
4. pass authorization explicitly on the CLI

Example:

```bash
kendr run \
  --security-authorized \
  --security-target-url https://example.com \
  --security-authorization-note "SEC-123 approved by security owner" \
  --security-scan-profile deep \
  "perform defensive security assessment and produce remediation report"
```

`exploit_agent` is analysis-only. The system does not automate payload generation, exploitation, credential attack, or service disruption.

## Security Workflow Requirements

Required:

- `OPENAI_API_KEY`

Optional local tooling for deeper authorized assessments:

- `OWASP Dependency-Check`
- `OWASP ZAP`
- `Nmap`
- `Playwright`
- `NVD_API_KEY` for higher-rate CVE lookup

## Privileged Execution Controls

The runtime includes privileged-mode guardrails for sensitive local automation.

Key controls:

- explicit approvals
- path allowlists
- allowed domain scope
- read-only mode
- root and destructive toggles, off by default
- pre-mutation backups
- kill-switch support

Relevant CLI flags include:

- `--privileged-mode`
- `--privileged-approved`
- `--privileged-approval-note`
- `--privileged-read-only`
- `--privileged-allow-root`
- `--privileged-allow-destructive`
- `--privileged-enable-backup`
- `--privileged-allowed-path`
- `--privileged-allowed-domain`
- `--kill-switch-file`

## Research And Compliance Boundaries

For people research or future social-intelligence work, you should define:

- allowed sources
- disallowed PII classes
- retention limits
- audit rules
- operator permissions
- escalation paths for sensitive requests

The current repo explicitly notes that social ecosystem analysis remains future-facing and should not be treated as operationally complete.

## Security-Related Docs

- [Integrations](integrations.md)
- [Troubleshooting](troubleshooting.md)
- [Project Upgrade Plan](project_upgrade_plan.md)
