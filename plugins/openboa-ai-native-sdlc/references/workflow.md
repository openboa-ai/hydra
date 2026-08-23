# OpenBoa Workflow

**Contract:** `0.1.0`

## Choose the work unit

For work that may take many steps, state the outcome, constraints, and verification, then link one GitHub parent Issue as the shared record. Create a Codex Goal when the user explicitly asks Codex to track it. Use sub-issues and issue dependencies only when tasks have separate owners, review surfaces, or ordering.

Use a single Issue or supervised fast path for a routine, reversible change with obvious acceptance criteria. If scope grows, create or link the parent Issue before continuing.

## Development loop

`Goal → Plan → Task → Worktree → Verify → Review`

- Read the nearest `AGENTS.md` and relevant skill references.
- Plan in proportion to risk and split only genuinely independent tasks.
- Preserve unrelated work and execute in an isolated worktree or clean clone.
- Verify against acceptance evidence with executable checks and environment evidence.
- Review the diff, evidence, uncertainty, and scope before delivery.

## Delivery loop

`Review → Approval → Deliver → Observe`

Routine automation may approve routine work. Work requiring human approval waits for that approval before the sensitive or irreversible action. Deliver through the repository's merge, release, deployment, publication, or handoff path, then inspect the realized state.

## Learning loop

`Observe → Classify → Improve → Re-evaluate`

Improve the smallest useful layer behind a failure: context, skill, plugin, harness, sandbox, tool, test, eval, grader, guardrail, or workflow. Add a regression check when possible. Create a follow-up goal if the improvement is outside current scope or authority.

## GitHub state

Use `Backlog`, `Ready`, `In progress`, `In review`, and `Done`. A `blocked` item names the dependency, owner, and unblock condition. Session or harness states do not replace the public work state.

## Handoff and completion

A handoff records the goal and owner, current state, completed and remaining work, changed files, checks and observed evidence, blocker or decision, and next safe action.

Close a goal only when acceptance evidence, required delivery state, and required observation are satisfied. A successful session, green command, open pull request, or approval is evidence, not completion by itself.
