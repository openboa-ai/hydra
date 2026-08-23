# GitHub and Codex Lessons

GitHub and Codex provide different parts of the working environment. Neither one defines OpenBoa's doctrine.

| Need | Current surface | OpenBoa use | Limit |
| --- | --- | --- | --- |
| Purpose and responsibility | GitHub Issue | Record outcome, accountable owner, work lead, authority, resources, boundaries, and evidence | An assignee or account does not fully express an agent role |
| Meaningful decomposition | Sub-issues and dependencies | Split only work with separate responsibility, ordering, or review | Do not create a custom graph or an Issue for every edit |
| Portfolio view | GitHub Projects and issue fields | Show status, priority, and selected resource signals across repositories | Organization fields are optional and may have visibility limits |
| Working context | Codex task and repository | Let the work lead inspect, plan, execute, and maintain a coherent thread | A thread is not the organizational record or permanent identity |
| Durable local guidance | `AGENTS.md` | Provide repository facts, commands, boundaries, and verification | Keep it short; do not copy doctrine or full manuals into every repository |
| Repeatable work | Codex skills | Package decisions that recur and benefit from consistent judgment | Do not encode generic Codex behavior or every exception |
| Isolated execution | Local git and worktrees | Protect unrelated work and support parallel attempts | A branch or worktree is an attempt, not the goal |
| Change evidence | Pull requests and checks | Preserve diff, tests, review, delivery, and observation | Green CI does not prove product realization by itself |
| Enforced authority | Rulesets and environments | Enforce review and deployment protection for consequential paths | Labels and prompt text do not grant or revoke authority |
| Live GitHub work | Codex GitHub connector | Default read and write path for Issues, PRs, review, Actions, and merge | Authentication identifies the actor; assignment defines authority |

## Work record

A parent Issue is used when work is delegated, long-running, cross-repository, multi-PR, dependency-bound, or likely to need a handoff. Routine supervised work may use one Issue or the repository's ordinary PR path.

The Issue keeps the accountable human separate from the work lead. An agent role can lead even when GitHub cannot assign that role as a user account. The connected GitHub account remains the attributable actor and never substitutes for the assignment.

## Control plane and execution plane

The Codex GitHub connector is the default for supported GitHub operations. Local git handles worktrees, diffs, commits, and tests. Codex tasks and subagents do the reasoning and execution; GitHub preserves shared organizational state and enforced delivery controls.

Use `gh` or a direct API only for a missing connector capability and record the target, reason, operation, result, and end of the exception.

## Automation boundary

GitHub Agentic Workflows and the Codex GitHub Action are credible future execution surfaces. They are not required by v0.1. Add them only after a manual skill is reliable on representative work and the automation can declare triggers, permissions, safe outputs, secrets boundaries, cost limits, and recovery.

## Review and approval

Review evaluates the change and evidence. Approval authorizes an effect. Routine work should not wait for a human solely because an agent led it. Rulesets, Code Owner review, and protected environments should concentrate human decisions on sensitive paths and consequential deployment rather than every pull request.
