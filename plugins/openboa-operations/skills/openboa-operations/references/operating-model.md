# OpenBoa Operating Model

**Status:** Working contract for `0.1.0`
**Owner:** OpenBoa policy owner
**Baseline rule:** Local repositories may be stricter; they may not silently weaken this model.

## Repository roles

| Surface | Owns | Does not own |
| --- | --- | --- |
| Hydra marketplace | Doctrine, portable references, skill, templates, contract versions | Product implementation, live dispatch, private repository facts |
| `openboa-ai/.github` | Reusable trusted workflow, GitHub templates, executable ruleset projection | Doctrine meaning, product-specific commands |
| Product repository | Product code/design/docs, local `AGENTS.md` facts, local CI and acceptance commands | Organization-wide policy semantics |
| GitHub Issue/PR/Actions/Deployments | Durable goal state and observable evidence | Hidden agent reasoning or authority to bypass gates |
| Workspace root | Local bootstrap bridge for nearby repositories | A replacement for a checked-in repository contract |

## Work entities

`Initiative` is optional context for a broad direction. `Goal/Task Issue` is the durable unit with one human owner. `Run Attempt` is one agent or human execution attempt in an isolated workspace. `Change` is one or more PRs, commits, documents, or analysis artifacts. `Delivery` is merge, release, deployment, or publication. `Observation` is the post-delivery evidence that the outcome behaves as intended.

One goal may produce multiple PRs, cross repository changes, or no code at all. The PR is never the identity of the goal.

## Decision rights

| Decision | Default authority | Agent role |
| --- | --- | --- |
| Doctrine, authority, or exception | `SonSangjoon` as policy owner | Draft, analyze, and propose |
| Goal priority and acceptance | Named human Issue owner | Clarify and prepare |
| Routine implementation | Goal owner delegates inside the routine lane | Plan and execute autonomously |
| Verification | Repository checks plus independent review/evaluation | Run, interpret, and repair |
| Routine merge and delivery | Passing automation and repository rules | Shepherd to the next handoff |
| Human-gate action | Required environment reviewer | Prepare evidence; never self-authorize |
| Goal closure | Owner accountable; automation may close when criteria are satisfied | Record evidence and request closure |

Delegation changes who acts, not who answers for the outcome.

## Precedence and exceptions

1. Applicable law, security boundary, and platform safety constraints.
2. Approved Hydra doctrine and governance.
3. Operating model and workflow.
4. GitHub profile and repository-local contract.
5. Goal-specific acceptance criteria and task instructions.

A lower layer may add constraints but may not remove a higher-layer constraint. A conflict stops the agent unless a time-bounded governance exception names an owner, rationale, scope, compensating control, expiry, and review condition.
