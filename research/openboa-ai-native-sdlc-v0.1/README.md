# OpenBoa AI-Native SDLC v0.1 Research

**Status:** Research package and design candidate; not an approved doctrine or managed contract.

**Durable goal:** [Hydra Issue #3](https://github.com/openboa-ai/hydra/issues/3)

**Human owner:** SonSangjoon

**Risk lane:** `risk:human-gate` — the eventual name, doctrine, authority model, and managed contract are public policy surfaces.

## Purpose

This package establishes an evidence base for redesigning OpenBoa Operations as **OpenBoa AI-Native SDLC v0.1**. It studies how frontier labs and AI-native companies change the software lifecycle when agents can plan, execute, verify, and operate across long-running tasks.

The working hypothesis is deliberately provisional:

> AI-Native SDLC is a software lifecycle in which goals, context, execution environments, evaluation, authority, and observability are designed as first-class artifacts for humans and agents together.

The hypothesis becomes a doctrine only after source review, an application exercise, and explicit human approval.

## Research corpus

`sources.csv` contains 40 first-party sources selected from:

- frontier labs and platforms: OpenAI, Anthropic, NVIDIA, Google/DeepMind, and Microsoft/GitHub;
- AI-native development companies and platforms: Cursor, Factory, Replit, Vercel, Linear, and Sourcegraph.

The first pass uses sources published from 2024 onward. Older material is included only when it explains a still-relevant operating pattern. Product claims and self-reported metrics are marked as such; they are not treated as standalone design evidence.

## Source grading

| Grade | Meaning | Use |
| --- | --- | --- |
| A | Reproducible implementation, evaluation, security, or operational detail | Can support a candidate rule when corroborated |
| B | Detailed first-party engineering case or technical documentation | Strong supporting evidence |
| C | Product announcement or company-reported result | Directional evidence; never sufficient alone |
| D | Secondary commentary or context only | Discovery and triangulation, not normative evidence |

Every record keeps the claim, observed pattern, precondition, failure mode, control, metric, confidence, and applicability separate. This prevents a product claim from silently becoming an OpenBoa rule.

## Reading order

1. [Evidence synthesis](evidence-synthesis.md) — recurring patterns, conflicts, and candidate principles.
2. [Lifecycle matrix](lifecycle-matrix.md) — stage-by-stage human/agent responsibilities and evidence.
3. [Artifact catalog](artifact-catalog.md) — durable goal, context, handoff, evidence, delivery, and observation records.
4. [Source verification](source-verification.md) — provenance, manual verification method, and claim treatment.
5. [Risk and authority](risk-and-authority.md) — autonomy lanes, control-plane boundaries, and approval rules.
6. [Decision traceability](decision-traceability.md) — source evidence mapped to proposed OpenBoa rules.
7. [Draft model](draft-model.md) — the unapproved OpenBoa AI-Native SDLC v0.1 candidate.
8. [Hydra application](application-hydra.md) — a bounded exercise on this research goal itself.
9. [Open questions](open-questions.md) — unresolved conflicts and human decisions.

## Scope boundary

This package does **not** rename `openboa-operations`, change the marketplace manifest, edit the managed `AGENTS.md` contract, or claim doctrine approval. The repository `hydra` and marketplace `openboa-hydra` remain stable until the human gate is completed.

## Verification

Run the research validator from the repository root:

```bash
python3 scripts/validate_research.py .
python3 -m unittest discover -s tests -v
```

The validator checks the source-count target, required evidence fields, duplicate citations, source-grade values, and required synthesis artifacts.
