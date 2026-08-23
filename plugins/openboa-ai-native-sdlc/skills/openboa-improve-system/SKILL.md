---
name: openboa-improve-system
description: Use when failures, review rework, incidents, weak evals, or excessive human intervention show that the human-agent working system needs improvement.
---

# Improve the Working System

Make the team more capable instead of responding to every failure with tighter supervision.

1. Reproduce or gather evidence for the failure. Describe its effect on the outcome, cost, recovery, and team.
2. Classify the responsible layer: direction, assignment, role, authority, resources, context, skill, tool, access, environment, test, eval, policy, implementation, delivery, or observation.
3. Check both sides of delegation. Look for agent overreach or weak judgment, and for human micromanagement, unclear purpose, missing resources, or responsibility without authority.
4. Improve the smallest durable layer: local facts in `AGENTS.md`, repeatable judgment in a skill, deterministic behavior in a script or test, variable behavior in an eval, or enforced access and effects in the platform.
5. Add a regression or scenario that catches the observed failure, then re-run the original case and nearby checks.
6. Record what the team learned and how it changes future lead selection, resources, authority, boundaries, or observation. Keep one unusual incident from becoming a universal rule.

Read [doctrine](../../references/doctrine.md), [operating model](../../references/operating-model.md), [Codex](../../references/codex.md), and [evals and observation](../../references/evals.md).

Return the failure evidence, responsible layer, system change, regression, validation, future delegation change, owner, and follow-up signal.
