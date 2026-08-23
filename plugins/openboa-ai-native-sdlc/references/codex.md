# OpenBoa with Codex

**Current practice:** `0.1.0`

Codex is the current work environment for the OpenBoa team. Configure it as a capable teammate: give it durable context, repeatable skills, safe tools, an isolated workspace, useful feedback, and clear authority.

## Use the right Codex surface

| Surface | Use it for |
| --- | --- |
| Task conversation | The current assignment, judgment, collaboration, and progress updates |
| Plan | The work lead's current approach for multi-step work; update it as evidence changes |
| Goal | Durable Codex tracking only when the user explicitly asks for a Goal |
| `AGENTS.md` | Stable repository or workspace facts, commands, boundaries, and routing |
| Skill | A repeatable job that needs focused instructions and supporting references or scripts |
| Plugin | A portable bundle of shared skills, references, templates, scripts, and optional connections |
| Worktree | Isolation for concurrent or risky repository changes |
| Subagent | A bounded independent assignment with a clear deliverable and non-overlapping write scope |
| Connector or MCP tool | Authenticated access to an external system within the task's authority |
| Code review | Independent review of a diff against the assignment and evidence |
| Scheduled task or CI | A stable, repeatable workflow with clear inputs, checks, effects, and recovery |

Do not copy the same policy into every surface. Keep purpose and principles in doctrine, team roles in the operating model, local facts in `AGENTS.md`, repeatable work in skills, and active state in the task and GitHub.

## Leading work in Codex

Give Codex the complete assignment rather than a sequence of tiny commands. Let the agent work lead inspect the repository, challenge weak assumptions, choose a plan, use tools, run tests, and continue through ordinary decisions. Progress updates keep collaboration visible; they are not requests for permission unless a real boundary is reached.

Use parallel agents for genuinely independent research, implementation, or review that benefits from separate context. Give each one a concrete outcome and avoid overlapping writes. The primary work lead remains responsible for synthesis and verification.

## Continuity

At the start of resumed work, recover the nearest `AGENTS.md`, assignment, role, branch or worktree, decisions, changed artifacts, checks, and remaining work. At handoff, persist those same facts. Do not rely on conversation history alone and do not pretend that a new model instance has personal memory it does not have.

## Automation boundary

Codex scheduled tasks, GitHub Actions, or future agent workflows should automate only stable jobs with explicit authority, bounded effects, observable results, and recovery. This v0.1 plugin installs no daemon, custom runtime, scheduler, or live dispatcher.

Official references: [Codex best practices](https://developers.openai.com/codex/learn/best-practices), [`AGENTS.md`](https://developers.openai.com/codex/guides/agents-md), [skills](https://developers.openai.com/codex/skills), [plugins](https://developers.openai.com/codex/plugins), [worktrees](https://developers.openai.com/codex/app/worktrees), and [subagents](https://developers.openai.com/codex/subagents).
