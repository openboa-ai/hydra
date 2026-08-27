# Hydra design

This document is the product boundary for Hydra `0.0.0`. It intentionally describes the problem and the contract before choosing a skill, hook, MCP server, prompt library, or internal workflow.

## Why

OpenBoa is being built around a different relationship with agents. An agent is a collaborator who can understand a goal, choose a method, and carry delegated work forward. Treating every step as a human approval task wastes that capability. Handing over every decision is also poor leadership: the organization still needs purpose, authority limits, risk controls, and one accountable human owner.

Hydra exists to make that relationship portable and reliable across agent clients. It should help a capable agent do more of the work without making the organization blind to authority, evidence, or consequences.

## What

Hydra is an Agent Plugin package. Its first responsibility is a stable, client-neutral package boundary:

- `plugin.json` is the canonical Agent Plugins v1 manifest.
- `.codex-plugin/plugin.json` is a Codex compatibility adapter with the same package identity and version.
- Optional skills, MCP servers, and other client components may be added later, but they are not part of `0.0.0`.
- The package can be loaded by different clients; client support is evaluated separately for each client.

Hydra is not a marketplace, an evaluation harness, a deployment service, a work database, or a custom agent runtime. Those concerns belong to separate surfaces.

## Stable product commitments

These are the things the product is trying to preserve even when the implementation changes:

1. **Agent capability is a resource.** The agent may reason, choose a method, recover, and hand off work inside its delegated scope.
2. **Authority is bounded.** Scope, permissions, environment, and risk define what the agent may change or publish.
3. **Human accountability remains real.** People set purpose and retain final responsibility for values, new authority, irreversible consequences, and public commitments.
4. **Outcomes are verifiable.** A response is not completion; files, actions, tests, review, and relevant operating evidence determine whether the work is done.
5. **The package is portable.** The contract must not depend on one model, one account, or one client implementation.

## What is intentionally variable

Hydra does not freeze a company chart, an agent prompt, a staffing model, a graph/loop implementation, or a particular set of tools. Those are hypotheses. Hydra Eval should decide which implementation belongs in the package by comparing realistic work, not by preserving a method because it has a name.

## Runtime boundary

The runtime is understood as a simple input/output relationship:

```text
Trigger -> Input -> Agent + Hydra -> Output -> Observation
```

- **Trigger** can be a request, a situation, an event, or an alert. It does not have to be a text prompt.
- **Input** is the managed environment: goal, constraints, repository state, files, context, permissions, and available tools.
- **Agent + Hydra** is where the external client agent decides and acts. Hydra may provide guidance or components, but it does not secretly decide the organization's purpose.
- **Output** can be text, files, tool actions, a deployment, a handoff, or a blocked decision. The output should include enough evidence to tell what actually happened.
- **Observation** is the next check, user-visible state, operating signal, or follow-up trigger. It is not implied by a successful process exit.

The exact internal steps may be different for different work. The runtime contract is intentionally smaller than a fixed workflow.

## Development boundary

Hydra itself is improved through a separate loop owned by Hydra Eval:

```text
task set
  -> baseline agent run
  -> Hydra candidate run
  -> verifier, trajectory, artifact, and review
  -> outcome/time/token/cost/safety comparison
  -> implementation decision
  -> next candidate
```

The baseline is the same external agent and environment without the candidate Hydra package. A candidate is not accepted because it sounds good or because a model gave a plausible answer. It must produce reviewed evidence on realistic tasks. Time, token use, cost, quality, and safety stay visible as separate dimensions until evidence justifies a different decision.

## Repository boundaries

| Surface | Owns | Does not own |
| --- | --- | --- |
| Hydra | package identity, product boundary, future components, support and release claims | evaluation results, marketplace catalog, live work data |
| Hydra Eval | task definitions, baseline/candidate runs, verifiers, trajectories, reviewed results, invalidation history | Hydra implementation or package installation state |
| OpenBoa Plugins marketplace | discovery, exact source revisions, and install availability | copied plugin code, support claims, or evaluation scores |
| Host client (first test: Codex) | loading, permissions, tool execution, and client UI | changing Hydra's product meaning |

Console-style views are projections of these sources, not a source of truth. Existing host task views and Harbor job views are sufficient for the foundation; a custom console is deferred until an evaluated need is demonstrated.

## `0.0.0` boundary

This version proves only the package shape and the product boundary. It intentionally has no skill, MCP server, hook, runner, score, support declaration, tag, release, or installable marketplace entry. Any future implementation must be introduced as a candidate and evaluated in Hydra Eval before it becomes a product claim.
