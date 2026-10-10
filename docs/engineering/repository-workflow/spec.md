# Repository development workflow

> Historical record — this document records the earlier prototype. The current
> [GitHub-native contract](../github-workflow/spec.md) supersedes its operational
> store, private registration and CLI assumptions. Adapter evidence remains scoped
> to the behavior actually tested; it does not establish current autonomous delivery.

Revision: 1. Review status: proposed.

## Intent and scope

Establish a repeatable, observable development workflow for Hydra itself. The current project is documentation-only; this change adds repository hygiene and delivery controls, not a working SDLC runtime. Track delivery in the repository's foundation Issue.

The operator authorized a fresh public repository and its SDLC setup. The accepted defaults are Codex and GitHub as operator surfaces, normal changes proceeding without repeated approval, and human review of policy changes. Runtime architecture stays in the separate SDLC draft.

## Checks and execution boundary

A single `Repository hygiene` job runs on `pull_request` and `push` to `main`, with read-only contents permission and a 10-minute timeout. It checks the PR merge candidate (not only the branch head) and the main commit after delivery. Its checkout does not retain credentials. It never runs candidate scripts, installs project dependencies, receives deployment credentials, or publishes artifacts.

Actions are pinned by full commit. Existing public organization tooling may be read at an immutable revision to install checksum-verified actionlint and gitleaks. Workflow validation uses a trusted empty config and stdin, without shellcheck/pyflakes or candidate metadata discovery. Candidate workflows must be regular files, not symlinks. Whitespace checks disable external diff/textconv and force text attributes. Secret scans use trusted configuration, ignore no candidate allowlist, redact findings, and cover both available commit history and current files.

This is hygiene evidence, not product behavior coverage or an independent security attestation. New runtime behavior must bring requirement-linked tests in its own change. A PR can modify its own workflow; protected-path review is the approval boundary for such changes. A check name or Actions publisher alone is not sufficient provenance for a future autonomous merge controller.

## Repository settings

Use `main`, squash-only merge, automatic deletion of merged branches, read-only Actions defaults, and no Actions PR approval capability. Leave long-lived GitHub auto-merge requests disabled; the delivering agent performs a normal merge bound to the reviewed head.

An active main ruleset has no bypass actors. Require PRs, linear history, resolution of review threads, stale approval dismissal, no force push, no deletion, and an up-to-date required `Repository hygiene` check from GitHub Actions (app 15368). The check is made required only after its real PR run and producer are verified. Required blanket approval count is zero; code-owner review is required for protected paths.

Protect `.github/`, `AGENTS.md`, `SECURITY.md`, alternative CODEOWNERS locations, and secret-scan configuration with `@SonSangjoon`. Confirm this owner has write access and GitHub reports no CODEOWNERS errors. The operator has authorized this initial repository setup. Follow any native review requirement GitHub reports for its introduction; once the controls are installed, protected-path changes require the configured code-owner approval.

## Review and delivery

One meaningful PR carries the specification, workflow, instructions, and evidence. Request Code Review and Security Review when ready, wait for both, address findings, and reassess the final revision. Independent agent review can provide additional evidence but is not a human approval. Do not manufacture a review success if a service is unavailable.

Before merge, re-read head, base, required checks, review findings, threads, and applicable human decisions. Use the expected head SHA and normal squash merge. Verify the actual merge commit and main CI before marking delivered. If head or base changes, refresh the affected evidence.

## Recovery and public boundaries

No main push launches deployment or release. Missing checks, failed/cancelled jobs, unavailable reviews, invalid ownership, or unresolved policy approval prevent delivery. Preserve work and record the precise next action. Do not weaken checks to recover. Query current GitHub state before retrying an uncertain write.

Keep private operations, credentials, local paths, and internal research out of this repository and its public work records. New GitHub repository identity requires fresh integration/access verification; previous settings are not assumed inherited.

## Acceptance

- H1: actual pull_request run is green for the current PR merge candidate, with expected workflow path, job, and Actions publisher.
- H2: whitespace errors, invalid workflow YAML, and synthetic secret findings are rejected in isolated fixtures using the same tools; clean source passes.
- H3: candidate actionlint config, local action metadata, and gitleaks allowlists do not control the trusted checks; workflow symlinks are rejected.
- H4: live settings match the specified rules and CODEOWNERS is valid; ordinary paths do not acquire a blanket human-approval requirement.
- H5: current-head code/security review and any applicable native approvals are recorded before normal merge; actual main CI is green afterward.

A foundation PR waiting for a required external review or approval is prepared, not delivered. A delivered foundation still does not establish Hydra runtime or autonomous operation.
