---
name: openboa-plan-work
description: Use when a development goal needs scope, acceptance criteria, GitHub work items, dependencies, or a plan before implementation.
---

# Plan Development Work

Turn intent into work that Codex and people can execute and review.

1. For work that may take many steps, draft a Codex Goal with the outcome, constraints, and verification. Create it in Codex only when the user explicitly asks Codex to track the Goal. Link one GitHub parent Issue as the shared record.
2. Use a single Issue for a routine change. Add sub-issues only when work deserves a separate owner, test cycle, or review.
3. Record issue dependencies for real ordering or blockers. Parallelize only independent work with separate write scopes.
4. Define acceptance criteria as observable behavior, tests, evals, preview, deployment, or operating signals.
5. Mark work `risk:approval` when it touches workflows, `CODEOWNERS`, permissions, secrets, security, migrations, infrastructure, public policy, or irreversible actions.
6. Keep pull requests cohesive. Do not create an Issue or pull request for every file edit.

Use the Codex GitHub connector for supported Issue operations. Authentication does not expand the approved goal or repository scope.

Read [workflow](../../references/workflow.md), [operating model](../../references/operating-model.md), and [GitHub](../../references/github.md) when those decisions are needed. Start from [the Goal Issue template](../../assets/goal-issue.md).

Return the Goal text, Issue structure, dependencies, acceptance criteria, risk, and first executable task.
