# OpenBoa Workflow

**Current practice:** `0.1.0`

This workflow is a replaceable method for putting the doctrine into practice:

`Direction → Assignment → Lead → Review → Deliver → Learn`

## Direction

The OpenBoa leader explains why the work matters, the outcome to create, priorities, and organizational boundaries. Organizational accountability is inherited from the operating model. For substantial work, use one GitHub parent Issue as the shared record. Create a Codex Goal only when the user explicitly asks Codex to track one.

## Assignment

Name the work lead. Give the lead the decision rights, context, repositories, tools, environments, access, time, budget, dependencies, boundaries, and acceptance evidence needed for the outcome. Name another human decision owner only when specific authority is delegated to that person.

Use one Issue for one coherent body of work. Use sub-issues and dependencies when work has a separate lead, review surface, or real ordering constraint—not for every file edit.

## Lead

The work lead accepts or challenges the assignment, then chooses the plan and method. It may inspect, design, implement, test, coordinate contributors, and revise the approach within its authority. When local instructions permit delegation, it may give independent contributors bounded, non-overlapping assignments.

An agent lead continues through ordinary choices without asking the OpenBoa leader to approve each step. It escalates when:

- the purpose or desired outcome is materially unclear or conflicting;
- required resources or authority are missing;
- the work would cross a repository, project, financial, legal, privacy, security, or public boundary not covered by the assignment;
- an effect is consequential and hard to reverse;
- a judgment belongs to the accountable owner or named human approver;
- repeated failure means continuing would waste resources or increase risk.

Preserve unrelated work, isolate concurrent changes, and keep the Issue or draft pull request current when asynchronous collaboration benefits from it.

## Review

Review the outcome, not the agent's confidence or the volume of output. Use executable checks for deterministic behavior, evals for variable behavior, independent review for judgment and maintainability, and real environment evidence when acceptance depends on a running system.

Routine, reversible agent-led work may pass through required checks and independent review without an extra human approval merely because an agent led it.

## Deliver

Deliver through the repository's normal merge, release, deployment, publication, or handoff path. Ask for a human decision only at a boundary reserved by governance or the assignment. Then observe the realized outcome and keep rollback or recovery available for the stated observation window.

## Learn

Classify failures and rework by the responsible layer: direction, assignment, role, context, skill, tool, access, environment, test, eval, policy, or implementation. Improve the smallest durable layer, add a regression when possible, and use the evidence to calibrate future assignments and autonomy.

## State, handoff, and completion

Use familiar GitHub states such as `Backlog`, `Ready`, `In progress`, `In review`, and `Done`. A blocked item names the dependency, owner, and unblock condition.

A handoff records the assignment, current and next work lead, decision rights, resources, state, decisions, evidence, remaining work, and next safe action. Inherited OpenBoa accountability is not repeated.

Work is complete only when the acceptance evidence, required delivery state, and required observation are satisfied. A successful session, command, check, review, or open pull request is evidence—not completion by itself.
