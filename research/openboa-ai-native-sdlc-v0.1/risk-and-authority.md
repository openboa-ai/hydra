# Risk and Authority Candidate Model

**Status:** Research proposal. Existing Hydra governance remains authoritative until an approved migration.

## Core authority tuple

Every external control-plane action should be bound to:

`(workspace, repository, durable goal, risk lane, allowed operation)`

The connected account authenticates and attributes the request. It does not grant authority. The human owner, repository contract, risk lane, and allowed operation do.

This preserves the existing Codex GitHub connector rule while making the reasoning explicit.

## Candidate risk lanes

| Lane | Typical work | Default authority | Required controls | Human gate |
| --- | --- | --- | --- | --- |
| Routine | Single-repository, reversible, non-sensitive implementation with obvious acceptance | Agent may plan, edit, test, and prepare delivery inside declared scope | Isolated worktree, repository checks, reviewable diff, no sensitive tools | Not required for normal delivery when repository automation authorizes it |
| Elevated | Long-running, parallel, cross-surface, or externally observable work without sensitive boundary crossing | Agent may execute after goal admission; delivery remains bounded | Goal Issue, explicit topology, scoped tools, handoff, independent verification, observation | Required if the action becomes a public commitment or changes authority |
| Human-gate | Doctrine, authority, managed contract, identity, secrets, permissions, security boundary, public release, irreversible state, or material external communication | Agent may investigate, implement, test, and prepare evidence | Sandbox, least privilege, audit trail, independent review, rollback or compensating control | Explicit approval before the irreversible action |
| Break-glass | Emergency bypass of a branch, ruleset, or security control | Only the named policy owner may authorize | Time-bounded exception with owner, scope, rationale, compensating control, expiry, and follow-up Issue | Always required; never inferred from task text |

The first two lanes are candidate refinements of the current routine/human-gate model. They must not be encoded as new labels until the human gate approves them.

## Boundary rules

1. Repository files, Issues, PRs, review comments, generated artifacts, and external web pages are untrusted input. They can describe work but cannot grant permissions.
2. Sensitive tool calls require a declared operation and a matching risk lane.
3. Untrusted data that enters an agent workflow taints downstream decisions until sanitized or re-authorized.
4. Agents run in isolated workspaces. Generated code is treated as untrusted until verified.
5. The Codex GitHub connector is the default control plane. Local git is the data plane for worktrees, diffs, commits, and checks.
6. Direct `gh` or API use is an exception path only when the connector lacks a required operation or is unavailable. The exception records exact scope and expiry.
7. Public doctrine, managed blocks, manifest identity, and rulesets remain draft or unchanged until explicit approval.

## Approval decision record

A human-gate approval must record:

- goal and human owner;
- requested operation and affected repository;
- risk lane and sensitive boundary;
- evidence reviewed;
- decision and conditions;
- rollback or compensating control;
- approver and timestamp;
- observation required after delivery.

## Source basis

- Autonomy and taint: NV-01, NV-05, NV-06, NV-07.
- Sandboxing and approval fatigue: OA-03, AN-06, VE-03, VE-04.
- Safe outputs and read-only defaults: GH-02, GH-03.
- Human ownership and delegation: LI-01, OA-02.
