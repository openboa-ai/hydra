# OpenBoa Workflow

**Contract:** `0.1.0`

## Choose the work unit

Use a GitHub Issue before mutation when work is delegated, asynchronous, cross-repository, multi-PR, long-running, high-risk, dependent on another goal, or likely to require a handoff. The Issue must name one human owner, outcome, acceptance evidence, dependencies, and risk lane.

The fast path is allowed only when a human is actively supervising a single-repository, single-PR, routine, reversible change with obvious acceptance criteria. Record the same goal, risk, and verification fields in the PR. If the scope grows, create and link an Issue before continuing.

## Goal states

GitHub Issues use these mutually exclusive status labels:

1. `status:backlog` — captured but not yet admitted.
2. `status:ready` — owner, outcome, criteria, dependencies, and risk are clear; eligible to start.
3. `status:in-progress` — a human or agent run is actively advancing the goal.
4. `status:in-review` — a candidate outcome and review packet exist; qualification, approval, delivery, or observation remains.
5. Closed — completed with evidence or closed as not planned with rationale.

`blocked` is an overlay, not a replacement status. It names the dependency, unblock condition, and owner. Internal run states such as claimed, running, retry queued, and released belong to the executor, not to the Issue label set.

## Delivery loop

Use the following evidence-bearing stages without turning every stage into an Issue status:

`Plan → Execute → Verify → Approve → Deliver → Observe`

- Plan: clarify the goal, owner, boundaries, acceptance evidence, and risk.
- Execute: work in an isolated workspace; open a draft PR or produce the requested artifact early when useful.
- Verify: run local checks, tests, evals, independent review, and relevant product or UI checks.
- Approve: let routine automation authorize normal work; route only defined human-gate actions to the human reviewer.
- Deliver: merge, release, deploy, publish, or hand off the artifact according to the repository profile.
- Observe: inspect the realized environment and record evidence before closing the goal.

## Handoff packet

Every handoff records:

- goal and human owner;
- current Issue/PR/run state;
- completed and uncompleted work;
- changed files or artifacts;
- commands, checks, and environment evidence;
- blocker or decision required;
- next safe action and the authority needed.

Do not include hidden chain-of-thought. Record concise decisions, uncertainty, and observable evidence.

## Completion

Close a goal only when its acceptance criteria, required delivery state, and required observation evidence are satisfied. A successful agent process, green unit test, open PR, or generated report is evidence, not completion by itself.
