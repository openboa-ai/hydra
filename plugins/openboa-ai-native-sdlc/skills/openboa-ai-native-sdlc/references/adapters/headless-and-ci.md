# Headless and CI adapter

Use CI for repository-owned unattended checks. Use a native Codex scheduled task for follow-up that belongs to a Codex task. Treat generic local headless execution as unavailable in v0.2.

## Local headless boundary

A portable process-group timeout is not complete containment. A descendant can create a new session, detach from the original group, and continue after the parent returns. For a workspace-writing job, that can release the worktree lock while a process can still mutate the checkout.

For that reason, v0.2 packages no generic local runner, launchd job, or cron entry. Do not emulate it with an unsafe shell timeout. A future adapter must name an OS or managed execution boundary that detached descendants cannot escape, prove cleanup before releasing locks, preserve evidence, and pass hostile daemonization tests. Until then, use interactive Codex worktrees for writes and native read-only scheduled tasks or CI for unattended observation.

## CI contract

CI should use reviewed workflow code, immutable dependencies, least privilege, bounded time, and exact-revision evidence. A policy evaluator should be pure where possible: accept a normalized snapshot and return a decision without performing GitHub writes. Collection and enforcement remain separate.

## Failure behavior

- report generic local headless execution as unsupported rather than claiming partial containment;
- do not grant unattended workspace-write authority through an unverified scheduler wrapper;
- treat a stale managed job or lock as a visible failure requiring reconciliation, not permission to overlap;
- distinguish timeout, command failure, invalid configuration, and unsupported capability;
- preserve logs without secrets or private task content; and
- never retry an uncertain external write before checking whether it already occurred.
