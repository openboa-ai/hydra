# OpenBoa on GitHub

**Current practice:** `0.1.0`

GitHub is the current shared control plane for assignments, code changes, review evidence, delivery, and observation. It does not define the OpenBoa doctrine and may be replaced later.

## Issues and projects

Use GitHub's existing planning features:

- a parent Issue for a substantial shared outcome;
- sub-issues for work with a separate lead, review surface, or test cycle;
- issue dependencies for real ordering and blockers;
- a Project with familiar states such as `Backlog`, `Ready`, `In progress`, `In review`, and `Done` when the team needs a portfolio view.

Record the purpose, outcome, work lead, decision rights, resources, boundaries, dependencies, and acceptance evidence in the Issue. OpenBoa's accountable human is inherited from the operating model and is not repeated. Record another human only when that person has a specific delegated decision. The work lead may be a human or agent role even when GitHub requires a human account as the formal assignee.

Keep labels minimal. `blocked`, `codex`, and `risk:approval` are enough for the portable workflow. The `risk:approval` label routes attention; it does not grant authority or replace an enforced approval.

## Codex GitHub connector

Use the Codex GitHub connector for supported Issue, pull request, review, check, and merge operations. Before a write, confirm the workspace, repository, linked assignment, exact operation, and authority. Authentication is not authority.

Use local `git` for worktrees, diffs, commits, tests, and Git-object pushes. Use `gh` or a direct API only when the connector lacks the operation, and record the bounded exception in the Issue or handoff.

## Pull requests and review

A pull request connects the assignment to the change, checks, independent review, delivery plan, recovery, and observation. Review tests the outcome and material risk; it is not a ritual sign-off and does not transfer accountability.

Routine, reversible agent-led work may use auto-merge after required checks and independent review. Do not add a human approval solely because an agent led the work. When governance reserves an exact decision for a human, keep the pull request blocked only at that boundary and name the decision needed.

## Rulesets and ownership

Protect the default branch with a GitHub ruleset that:

- requires a pull request and current status checks;
- requires conversation resolution;
- blocks force-push and branch deletion;
- requires Code Owner review for matching sensitive paths;
- dismisses stale approval or requires approval of the latest reviewable push when a human decision is required.

Use `CODEOWNERS` for security, identity and permissions, data migrations, infrastructure, workflows, policy, and other sensitive paths. Own `/.github/CODEOWNERS` itself, or all of `/.github/`, so its protection cannot be silently removed. `CODEOWNERS` requests reviewers; the ruleset's **Require review from Code Owners** setting enforces their approval.

## Actions and delivery

Run product tests, lint, type checks, security checks, and relevant evals in GitHub Actions. Give required jobs stable, unique names. Treat pull-request content as untrusted: do not expose organization secrets, OIDC, or write credentials to candidate code. Use least-privilege workflow permissions and immutable references for shared workflow code.

Use GitHub environments for consequential deployment targets. Configure protection and self-review prevention where a human decision is required. Record delivery, rollback or recovery, and post-delivery observation in the pull request or linked Issue.

The v0.1 plugin supplies guidance, templates, and validation. Repository administrators apply rulesets, `CODEOWNERS`, Actions permissions, and environment protection. Future GitHub agent workflows may automate stable jobs only after their authority, inputs, effects, evidence, and recovery are proven.
