---
name: openboa-review-change
description: Use when deciding whether a diff, branch, commit, or pull request meets its intended outcome and is ready for approval or delivery.
---

# Review a Change

Review the outcome, not the builder's confidence.

1. Identify the linked Goal or Issue, acceptance criteria, risk, and exact diff.
2. Inspect scope and unintended changes before judging implementation details.
3. Run or confirm the required tests. Use evals for variable agent or AI behavior and inspect the actual environment when acceptance depends on runtime state.
4. Use Codex `/review` or another independent reviewer for prioritized findings. The builder's self-review is useful evidence but is not the independent review.
5. For UI work, inspect a running screen, screenshot, or preview. For stateful work, confirm the expected database, service, or deployment outcome.
6. Classify findings by impact, request focused fixes, and re-review changed code. Do not mark ready while required evidence is missing.

Read [evals and observation](../../references/evals.md), [workflow](../../references/workflow.md), and [GitHub](../../references/github.md). Use the [pull request template](../../assets/pull-request.md) to keep evidence visible.

Return findings first, then tests, evals, runtime evidence, residual risk, and a clear ready/not-ready verdict.
