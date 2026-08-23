---
name: openboa-review-work
description: Use when independently deciding whether assigned work achieved its outcome and whether the team, evidence, and change are ready for delivery.
---

# Review Work

Review the outcome and the working system, not the work lead's confidence.

1. Identify the assignment, work lead, authority, acceptance evidence, exact diff or artifact, and delivery boundary. Do not require a repeated accountable-owner field; OpenBoa accountability is inherited.
2. Check scope and unintended effects before implementation detail. Confirm the lead stayed inside its authority and escalated the decisions it did not own.
3. Run or confirm required tests. Use evals for variable behavior, `/review` or another independent code reviewer for the diff, and the actual environment when acceptance depends on runtime state.
4. For visual work, inspect a running screen, screenshot, or preview. For stateful work, inspect the expected service, data, deployment, or operating result.
5. Separate product defects from failures in direction, assignment, context, tools, access, environment, tests, or leadership. Do not blame an agent for resources it was never given.
6. Report prioritized, actionable findings and re-review meaningful fixes. Missing evidence means not ready; a different style preference does not.

Read [evals and observation](../../references/evals.md), [workflow](../../references/workflow.md), and [GitHub](../../references/github.md). Use the [pull request template](../../assets/pull-request.md) to keep the assignment and evidence visible.

Return findings first, then outcome evidence, authority review, team or system gaps, residual risk, and a clear ready or not-ready verdict.
