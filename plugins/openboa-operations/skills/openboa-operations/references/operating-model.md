# OpenBoa Operating Model

**Contract:** `0.1.0`
**Rule:** Repository policy may be stricter; it may not silently weaken this model.

## Ownership surfaces

| Surface | Owns |
| --- | --- |
| Hydra plugin | Portable doctrine, operating references, skill, templates, and contract version |
| `openboa-ai/.github` | Trusted reusable workflow, GitHub templates, and executable policy projection |
| Product repository | Product work, repository facts, local `AGENTS.md`, CI, and acceptance commands |
| GitHub | Goal and task graph, change evidence, review, approval, delivery, and observation state |
| Local workspace | Worktrees, diffs, commits, tests, and temporary execution state |

Hydra does not dispatch live agents or own product implementation. Product repositories do not redefine portable policy.

## Work and accountability

A goal has one human owner, an outcome, acceptance evidence, dependencies, and a risk lane. A plan describes how to advance it. Tasks are bounded units of execution or review. A session is one interaction with a harness; a worktree isolates repository changes. Neither replaces the goal.

Agents may prepare changes, evidence, and handoffs inside the declared scope. Repository checks and reviewers qualify the work. Routine automation may approve ordinary delivery; the named human gate approves sensitive or irreversible actions. Goal closure remains accountable to the human owner.

## Precedence

1. Law, platform safety, and enforced security boundaries.
2. Approved OpenBoa doctrine and governance.
3. This operating model and workflow.
4. GitHub profile and repository contract.
5. Goal-specific plan and task instructions.

A lower layer may add constraints but not remove a higher-layer constraint. Conflicts stop for a handoff unless a valid governance exception names the owner, rule, reason, scope, compensating control, expiry, and review condition.
