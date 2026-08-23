# OpenBoa AI-Native SDLC v0.1 — Draft Model

**Status:** Unapproved design candidate. This document does not change the current OpenBoa doctrine, managed contract, plugin manifest, or GitHub rules.

## Working definition

OpenBoa AI-Native SDLC is a portable operating model for software work in which humans own purpose and accountability while agents execute bounded investigation, planning, implementation, verification, delivery preparation, and observation.

The model is AI-native when the lifecycle treats the following as first-class, versioned artifacts:

- goal and acceptance evidence;
- repository and domain context;
- execution environment and authority corridor;
- agent and human responsibility;
- verification and evaluation trajectory;
- delivery and observation evidence;
- handoff and learning records.

## Operating entities

| Entity | Meaning | Authority |
| --- | --- | --- |
| Initiative | Optional context for a broad direction | Human policy or product owner |
| Goal | Durable unit with owner, outcome, evidence, dependencies, and risk | Named human owner |
| Context package | Relevant instructions, sources, decisions, commands, and provenance | Goal owner and repository contract |
| Run attempt | One isolated agent or human execution attempt | Delegated actor inside goal corridor |
| Change | Commit, document, PR, or analysis artifact produced by an attempt | Run actor prepares; repository rules govern |
| Delivery | Merge, release, deployment, publication, or handoff | Automation or human gate according to risk |
| Observation | Post-delivery evidence about realized behavior | Goal owner accountable |
| Learning | Follow-up change to context, tool, test, evaluator, guardrail, or workflow | Goal owner admits next goal |

## Human and agent relationship

- The human owns purpose, prioritization, acceptance, public commitments, and accountable outcome.
- The agent may inspect, plan, create, test, and operate within explicit authority.
- Delegation changes who acts; it does not transfer accountability.
- A connected account authenticates and attributes an operation; it does not grant authority.
- Agents must surface ambiguity, uncertainty, blockers, and evidence gaps rather than silently widening scope.

## Lifecycle contract

The candidate lifecycle is:

Frame -> Plan -> Context -> Execute -> Verify -> Approve -> Deliver -> Observe -> Learn

The Issue state remains:

status:backlog -> status:ready -> status:in-progress -> status:in-review -> closed

The lifecycle stages describe evidence and handoffs. They do not replace the durable goal state.

## Workflow selection

Use the simplest workflow that can satisfy the goal:

- deterministic workflow for bounded, repeatable work;
- single-agent adaptive workflow for variable but sequential work;
- parallel or multi-agent workflow only when task topology permits independent work and review capacity exists;
- human-gate workflow when the action affects authority, identity, secrets, security boundaries, irreversible state, or public commitments.

Every workflow declares:

- goal and owner;
- repository and workspace;
- risk lane;
- allowed tools and operations;
- acceptance evidence;
- stop conditions;
- handoff artifact;
- observation requirement.

## Evidence contract

A candidate completion packet contains:

- goal and current state;
- changed artifacts;
- commands and checks;
- test/evaluation results;
- tool or trajectory summary where relevant;
- review and approval state;
- delivery or handoff link;
- observation evidence;
- unresolved uncertainty and next action.

A generated answer, green process exit, open PR, or passing unit test is evidence but not completion by itself.

## Control-plane contract

- Codex GitHub connector is the default GitHub control plane.
- Each operation is scoped by workspace, repository, durable goal, risk lane, and allowed operation.
- Local git remains the data plane for worktrees, diffs, commits, and tests.
- Direct CLI or API use is exception-only and must record reason, scope, actor, operation, result, and expiry.
- Issue, PR, file, external page, and generated artifact content is untrusted input.

## Metrics

Measure outcomes at the goal and lifecycle level:

- goal success rate by risk lane;
- acceptance evidence completeness;
- first-pass verification rate;
- review rework and time to approval;
- handoff recovery rate;
- run duration, retries, tokens, and cost per successful goal;
- tool-call accuracy and trajectory efficiency;
- rollback and incident rate;
- observation completeness;
- context defects and repeated failure classes.

Do not use prompt count, raw lines changed, or agent adoption alone as success metrics.

## Proposed migration boundary

After explicit human approval:

1. rename the public plugin and skill identity to openboa-ai-native-sdlc;
2. update manifest, marketplace entry, README, skill references, templates, and managed-block identifiers in one migration;
3. preserve hydra and openboa-hydra;
4. keep a migration note from openboa-operations;
5. retain the existing required checks until the replacement contract passes canary validation;
6. use a semantic major version for changes to doctrine, authority, or managed contract.

No migration is authorized by this draft.
