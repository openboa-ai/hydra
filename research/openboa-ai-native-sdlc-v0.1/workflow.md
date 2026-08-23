# Workflow Lessons

OpenBoa work can be explained with three loops. A goal may move through them once or repeat a loop when evidence exposes a gap.

## Development loop

`Goal → Plan → Task → Worktree → Verify → Review`

1. Name one human owner, the desired outcome, acceptance evidence, dependencies, and risk lane.
2. Write a proportionate plan and split it into tasks only where separate ownership or review is useful.
3. Work in an isolated worktree or clean clone. Keep each change bounded and reversible.
4. Verify with executable checks and relevant environment evidence.
5. Present the diff, evidence, limits, and unresolved questions for review.

A handoff records the goal, current state, completed and remaining work, changed files, checks, blockers, and next safe action. A new session should be able to resume from repository state and the handoff without hidden transcript context.

## Delivery loop

`Review → Approval → Deliver → Observe`

Routine checks may supply approval for routine work. Work requiring human approval waits for the named reviewer before a sensitive or irreversible action. Delivery may mean merge, release, deploy, publish, or a bounded handoff.

After delivery, inspect the realized target: required checks, deployment state, UI, telemetry, incident signals, or other acceptance evidence. A green local command or open pull request is not the delivered outcome.

## Learning loop

`Observe → Classify → Improve → Re-evaluate`

Classify a failure at the smallest useful layer: missing context, weak skill, unreliable tool, absent test, poor eval, misleading grader, unsafe boundary, or unsuitable workflow. Improve that layer, add a regression check when possible, and run the relevant eval again.

Learning should create a follow-up goal when the improvement is not part of the current authority or scope. It must not silently weaken a gate.

## Choosing the work unit

Use a GitHub Issue when work is delegated, asynchronous, long-running, cross-repository, multi-PR, high-risk, dependency-bound, or likely to need a handoff. A human-supervised, single-repository, single-PR, routine, reversible change with obvious acceptance may use the fast path.

Parallel tasks are useful only when they are independent and review capacity exists. Sequential work should remain sequential. The evidence does not support multi-agent execution as a default.

## Canary boundary

Hydra should qualify the portable guidance and validators first. Ouroboros and Coffee Chat may later test the guidance as canary products after the human owner selects bounded goals and acceptance evidence. Product behavior must not be copied back as doctrine without external evidence, review, and approval.
