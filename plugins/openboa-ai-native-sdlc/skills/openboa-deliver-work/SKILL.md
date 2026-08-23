---
name: openboa-deliver-work
description: Use when reviewed work needs an authorized merge, release, deployment, handoff, recovery plan, or post-delivery observation.
---

# Deliver Work

Turn reviewed work into an observed outcome without adding approval rituals.

1. Confirm the assignment, exact pull request or artifact, required checks, independent review, unresolved conversations, delivery authority, recovery, and observation window.
2. For routine, reversible work already authorized by the assignment, use the repository's normal auto-merge or delivery path after checks and review pass. Do not request human approval solely because an agent led the work.
3. At a boundary reserved by governance or the assignment, ask the authorized human for one exact decision. State the target, effect, evidence, residual risk, recovery, and expiry; do not turn the whole workflow into a gate.
4. Use the Codex GitHub connector for supported review, check, and merge operations. Authentication is not authority. Respect GitHub rulesets, environments, concurrency, permissions, and self-review prevention.
5. Deliver through the configured merge, release, deployment, publication, or handoff path. Stop if the reviewed revision or authorized effect changes materially.
6. Observe the realized outcome. If acceptance or health fails, stop rollout where possible, recover or roll back, and reopen or create follow-up work with evidence.
7. Close the assignment only when acceptance, delivery, and required observation are recorded.

Read [GitHub](../../references/github.md), [governance](../../references/governance.md), and [evals and observation](../../references/evals.md). Use the [pull request](../../assets/pull-request.md) and [handoff](../../assets/handoff.md) templates.

Return the checks and review state, authority, exact human decision if any, delivery evidence, observation, recovery readiness, and next action.
