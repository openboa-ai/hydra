# GitHub Lessons

GitHub already provides the graph needed for OpenBoa work. Do not introduce a separate graph file format.

## Goal graph

- A parent Issue holds the human-owned goal and shared outcome.
- Sub-issues hold independently assignable tasks with their own acceptance evidence.
- Issue dependencies express ordering and blockers.
- Pull requests, commits, checks, reviews, approvals, deployments, and handoffs attach evidence to that graph.

Use the smallest graph that explains the work. A single routine change needs no parent/sub-issue hierarchy. Cross-repository work should name each repository, owner, dependency, and handoff rather than hiding coordination inside one pull request.

## Execution and evidence

Each active task uses an isolated worktree or clean clone. The Issue remains the durable coordination surface while branches and sessions can be replaced. Pull requests should link the goal, state the risk lane, summarize changed surfaces, and record verification, review, delivery, observation, and handoff state.

Status belongs on the Issue. Internal harness states such as queued, running, retrying, or released should not become public workflow labels unless humans need to act on them.

## Control plane

The Codex GitHub connector is the default GitHub control plane. Bind every operation to the workspace, repository, goal, risk lane, and allowed operation. A connected account authenticates and attributes the request; it does not authorize broader work.

Local `git` remains the data plane for worktrees, diffs, commits, and tests. A direct CLI or API path is an exception when the connector lacks the needed capability or is unavailable, and the exception should record its exact scope and result.

## Review and approval

Review judges the change and its evidence. Approval authorizes the next action. Keep those meanings separate: a useful review is not approval for a human-gate action, and an approval does not prove the outcome.

Trusted workflows should inspect candidate changes without executing them with secrets or write credentials. Branch rules and required checks remain stronger than task text.
