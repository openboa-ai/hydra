---
name: openboa-ship-change
description: Use when a reviewed pull request needs approval, merge, deployment, rollback planning, or post-delivery observation.
---

# Ship a Change

Move reviewed work through GitHub without confusing checks with authority.

1. Confirm the linked Issue, exact pull request revision, required checks, unresolved conversations, reviewers, risk, and rollback.
2. Routine, reversible work may use auto-merge after required checks and independent review pass.
3. Require human approval for workflows, `CODEOWNERS`, permissions, secrets, security, migrations, infrastructure, public policy, and irreversible actions. A new reviewable push invalidates the earlier decision when repository rules require fresh approval.
4. Use the Codex GitHub connector for supported review, Actions, and merge operations. Authentication is not authority.
5. Deploy through the configured GitHub environment. Respect protection rules, concurrency, secrets, and self-review prevention.
6. Observe the delivered behavior and record the result. If health or acceptance fails, stop rollout, use the rollback, and reopen or create follow-up work.

Read [GitHub](../../references/github.md), [governance](../../references/governance.md), and [evals and observation](../../references/evals.md). Use the [pull request](../../assets/pull-request.md) and [handoff](../../assets/handoff.md) templates.

Return the checks, review and approval state, merge or deployment evidence, observation, rollback readiness, and next action.
