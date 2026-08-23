# OpenBoa Workflow

**Contract:** `0.1.0`

## Choose the work unit

Use a GitHub Issue before mutation for delegated, asynchronous, cross-repository, multi-PR, long-running, high-risk, dependency-bound work or work likely to need a handoff. Record one human owner, outcome, acceptance evidence, dependencies, and risk lane.

Use the fast path only for a human-supervised, single-repository, single-PR, routine, reversible change with obvious acceptance criteria. If scope grows, create and link an Issue before continuing.

## Development loop

`Goal → Plan → Task → Worktree → Verify → Review`

- Read the nearest `AGENTS.md` and relevant skill references.
- Plan in proportion to risk and split only genuinely independent tasks.
- Preserve unrelated work and execute in an isolated worktree or clean clone.
- Verify against acceptance evidence with executable checks and environment evidence.
- Review the diff, evidence, uncertainty, and scope before delivery.

## Delivery loop

`Review → Approval → Deliver → Observe`

Routine automation may approve routine work. Human-gate work requires explicit approval before the sensitive or irreversible action. Deliver through the repository's merge, release, deployment, publication, or handoff path, then inspect the realized state.

## Learning loop

`Observe → Classify → Improve → Re-evaluate`

Improve the smallest useful layer behind a failure: context, skill, plugin, harness, sandbox, tool, test, eval, grader, guardrail, or workflow. Add a regression check when possible. Create a follow-up goal if the improvement is outside current scope or authority.

## GitHub state

Use `status:backlog`, `status:ready`, `status:in-progress`, and `status:in-review`; close only with evidence or a not-planned rationale. `blocked` is an overlay that names the dependency, owner, and unblock condition. Session or harness states do not belong in the public goal state.

## Handoff and completion

A handoff records the goal and owner, current state, completed and remaining work, changed files, checks and observed evidence, blocker or decision, and next safe action.

Close a goal only when acceptance evidence, required delivery state, and required observation are satisfied. A successful session, green command, open pull request, or approval is evidence, not completion by itself.
