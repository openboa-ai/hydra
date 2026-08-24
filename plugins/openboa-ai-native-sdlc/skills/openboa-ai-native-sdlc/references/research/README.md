# OpenBoa AI-Native SDLC v0.1 research

This installed research package records the external evidence used to design OpenBoa AI-Native SDLC v0.1. It is deliberately independent of Ouroboros, Coffee Chat, earlier Hydra material, and any retired repository. Those products may later test the design; they do not define it.

## Research question

How should a software organization change when agents can lead meaningful work across the development lifecycle, while a human retains purpose and final accountability and the surrounding system enforces authority and safety?

The research examines the full loop:

`purpose -> outcome -> explore and design -> plan -> execute and verify -> review and integrate -> release and observe -> learn`

It pays particular attention to work continuity, task and dependency graphs, objective verification, GitHub controls, agent permissions, recovery, observability, and the cost of human attention.

## Corpus

The source register contains 38 public primary sources from:

- frontier labs: OpenAI, Anthropic, NVIDIA, Google/DeepMind, and Microsoft;
- the GitHub control plane;
- AI-native software companies: Cursor, Factory, Vercel, Replit, Cognition, Linear, and Sourcegraph;
- durable foundations: NIST AI RMF, OWASP, OpenTelemetry, and SLSA.

Most sources are from 2024 onward. Living documentation and standards were read on 2026-08-23. Older or undated material is included only where it supplies a durable control or evaluation concept.

## Evidence policy

Every source is classified so a product announcement cannot silently become doctrine:

- `controlled_research`: a disclosed experiment, benchmark, or empirical study;
- `engineering_evidence`: implementation detail, failure analysis, or operational lesson with enough detail to inspect;
- `official_guidance`: vendor or platform guidance grounded in stated practice but not an independent experiment;
- `self_reported_claim`: a company reports its own adoption, throughput, cost, or quality result;
- `standard`: a public framework or technical convention;
- `product_claim`: a description of a product capability or intended workflow.

Some rows contain more than one label. A self-reported number remains self-reported even when the surrounding article provides useful engineering evidence. OpenBoa decisions are not stored as source claims; they are explicit in [evidence-to-design.md](evidence-to-design.md).

Confidence means confidence that the cited source supports the recorded pattern, not confidence that the pattern transfers unchanged to OpenBoa. Applicability records that transfer judgment separately.

## Reading order

1. [source-register.csv](source-register.csv) — normalized claims, controls, failure modes, and metrics.
2. [evidence-to-design.md](evidence-to-design.md) — evidence to lesson to OpenBoa decision to validation trace.
3. [plugin research basis](../research-basis.md) — concise design-facing synthesis shipped with the plugin.

## What this research does not prove

- It does not prove that agents are legal or moral persons. “Collaborator” and “work lead” are operating roles.
- It does not prove that more agents always improve outcomes. The evidence says topology must follow the work.
- It does not establish that a passing test or green CI is sufficient evidence of safety.
- It does not independently verify vendor throughput, cost, adoption, or quality claims.
- It does not prescribe a permanent harness. Model capability, tools, and execution environments change faster than doctrine.
- It does not authorize production access, credentials, releases, purchases, public commitments, or GitHub settings changes.

## Refresh rule

Refresh this package when a design decision changes, a cited source is retracted or materially revised, a new canary exposes an unsupported assumption, or a model or platform change invalidates a playbook. Preserve source IDs where the source is unchanged; add a new row when the claim or evidence changes materially.
