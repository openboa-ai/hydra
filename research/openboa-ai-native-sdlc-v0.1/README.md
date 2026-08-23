# OpenBoa AI-Native SDLC v0.1 Research

**Status:** External-evidence synthesis for review; not approved policy.

**Goal:** [Hydra Issue #3](https://github.com/openboa-ai/hydra/issues/3)

**Human owner:** SonSangjoon

**Risk lane:** `risk:human-gate`

This package asks a practical question: what should an operating guide make explicit when humans set goals and agents can plan, implement, verify, and prepare delivery? It summarizes external evidence without inventing another lifecycle specification.

## Reading path

1. [Lessons](lessons.md) — evidence, source grades, vocabulary, and limits.
2. [Workflow](workflow.md) — the development, delivery, and learning loops.
3. [GitHub](github.md) — parent Issues, sub-issues, dependencies, worktrees, PRs, and handoffs.
4. [Evals](evals.md) — outcome checks, graders, trajectories, and observation.
5. [Open questions](open-questions.md) — decisions and evidence gaps that remain.

[sources.csv](sources.csv) is the verified 40-source ledger behind the synthesis. It preserves source grading and separates each claim from its evidence, conditions, failure modes, controls, metrics, confidence, and applicability.

## Scope

The plugin references are the portable source of truth for OpenBoa work. This research explains why those guides take their current shape; it does not replace them or authorize a release, rename, managed-contract change, or GitHub policy change.

Ouroboros and Coffee Chat are possible later canary products. They are not sources for the design.

## Verify

```bash
python3 scripts/validate_research.py .
python3 -m unittest tests.test_research_artifacts -v
```
