# OpenBoa on GitHub

**Contract:** `0.1.0`

## Issues and task dependencies

Use GitHub's existing planning features:

- a parent Issue for a shared goal;
- sub-issues for work that deserves its own owner, test cycle, or review;
- issue dependencies for ordering and blockers;
- pull requests, commits, checks, reviews, approvals, deployments, and handoffs as attached evidence.

Do not create a separate graph file format. A routine change can use one Issue, and closely related tasks can share one cohesive pull request.

Use the Issue type `Feature`, `Bug`, or `Task`. Use `Backlog`, `Ready`, `In progress`, `In review`, and `Done` in a GitHub Project when one exists; otherwise use matching status labels. Keep labels minimal: `blocked`, `codex`, and `risk:approval` cover the portable workflow.

## Codex GitHub connector

The Codex GitHub connector is the default for supported GitHub operations. Before any write, confirm the workspace, repository, linked Goal or Issue, risk, and exact action. Authentication is not authority: the connected account identifies the actor but does not expand the work or bypass approval.

Use local `git` for worktrees, diffs, commits, and tests. Use `gh` or a direct API only when the connector lacks the required operation, and record the reason, target, action, result, and expiry in the Issue or handoff.

## Pull requests and rulesets

Protect the default branch with a GitHub ruleset:

- require a pull request;
- require current status checks;
- require review from Code Owners for matching sensitive paths;
- require conversation resolution;
- block force-push and branch deletion;
- dismiss stale approval or require approval of the latest reviewable push for approval-required changes.

Use `CODEOWNERS` for security, permissions, data migrations, infrastructure, workflows, and other sensitive paths. Assign an owner to `/.github/CODEOWNERS` itself so the review requirement cannot be removed without Code Owner review. `CODEOWNERS` requests the appropriate reviewers; the ruleset's **Require review from Code Owners** setting enforces their approval. Routine changes can use auto-merge after checks and independent review.

The `risk:approval` label is for routing and visibility. It does not grant approval or replace the ruleset, Code Owner review, or environment protection.

## Actions and deployments

Run product tests, lint, type checks, security checks, and relevant evals in GitHub Actions. Give each required job a unique name. Trusted workflow code comes from the base branch or an immutable reference; candidate pull-request content is untrusted data and must not receive organization secrets, OIDC, or write credentials.

Use GitHub environments for deployment targets. Limit deployment concurrency, expose environment secrets only after protection rules pass, and require a human reviewer with self-review prevention for approval-required production changes. Record the rollback and post-deployment observation in the pull request or linked Issue.

The plugin prepares and checks this setup; repository administrators apply rulesets, `CODEOWNERS`, and environment protection in GitHub.
