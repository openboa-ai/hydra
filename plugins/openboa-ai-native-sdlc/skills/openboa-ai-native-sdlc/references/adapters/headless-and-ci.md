# Headless and CI adapter

Use headless Codex or CI for bounded work that does not require an open interactive task.

## One-shot contract

A run has one project, prompt file, state directory, job name, sandbox, timeout, and final status. The runner creates a job lock and, for workspace writes, a worktree-wide lock shared by every job. It writes an attributable JSONL record, preserves the final response, and exits. It does not loop, daemonize, elevate, or decide its own next schedule.

Read-only is the default. Workspace write is accepted only for a clean isolated Git worktree and still uses approval `never`. Full access and bypass flags are refused. Prompts, repository files, and prior logs remain untrusted input.

## CI contract

CI should use reviewed workflow code, immutable dependencies, least privilege, bounded time, and exact-revision evidence. A policy evaluator should be pure where possible: accept a normalized snapshot and return a decision without performing GitHub writes. Collection and enforcement remain separate.

## Failure behavior

- refuse concurrent runs with the same state/job lock and refuse every overlapping workspace-write run against the same worktree;
- on timeout, terminate the full Codex process group so descendant tools cannot keep modifying the worktree;
- treat a stale lock as a visible failure requiring reconciliation, not permission to overlap;
- distinguish timeout, command failure, invalid configuration, and unsupported capability;
- preserve logs without secrets or private task content; and
- never retry an uncertain external write before checking whether it already occurred.
