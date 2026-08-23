# OpenBoa GitHub Profile

**Profile:** `public-standard`
**Contract:** `0.1.0`

## Goal and task graph

Use GitHub's existing graph:

- a parent Issue for a shared goal;
- sub-issues for independently owned or reviewed tasks;
- issue dependencies for ordering and blockers;
- pull requests, commits, checks, reviews, approvals, deployments, and handoffs as attached evidence.

Do not create a separate graph file format. Use no hierarchy for a routine single-Issue change.

## Control plane

Codex GitHub connector is the default control-plane for GitHub operations. Bind every operation to the canonical workspace, repository, goal, risk lane, and allowed operation. The connector account transports and attributes the request; account identity is not authority.

Local `git` is the data plane for worktrees, diffs, commits, and tests. Use a `gh` CLI or direct API path only through a recorded governance exception when the connector is unavailable or lacks the required operation.

## Repository contract

An adopted repository may add `.github/openboa-governance.yml`. It may add sensitive paths but may not remove the central baseline. Pin trusted shared workflows to an exact commit and fail closed on a contract or pin mismatch.

Use the standard status, delegation, risk, blocked, and exception labels defined by the templates. Issues record goals and dependencies; pull requests record linked goal, risk, changed surface, verification, review, delivery, observation, and handoff state.

## Branch and workflow baseline

Public default branches require a pull request, current required checks, resolved conversations, and no force-push. Preserve stronger repository rules. Human-gate changes wait for the required reviewer before delivery.

Trusted workflows inspect candidate content as untrusted data. Do not execute candidate code with organization secrets, OIDC, or write credentials. Local CI remains the product repository's responsibility.

The skill audits and synchronizes repositories on demand. It does not create a live dispatcher, scheduler, or background daemon.
