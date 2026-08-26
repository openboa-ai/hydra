# Codex adapter

Codex is OpenBoa's current execution environment. Use its native capabilities before inventing another runtime.

## Interactive tasks

- Use the active plan for execution order; use GitHub for state that must survive the task.
- Read the nearest `AGENTS.md` and load only the relevant playbook and references.
- Use local tools for repository inspection, edits, tests, and evidence.
- Use subagents only when work has independent boundaries and an integration point. More agents are not a default.
- Use task handoff or a durable Issue when another task, model, or machine must continue.

## Scheduled tasks and wakeups

Use a Codex scheduled task when the same conversation should wake later to inspect state or perform a bounded follow-up. The prompt must name the target, read-only or write boundary, stop condition, notification condition, and expiry. A scheduled task must reconcile live state and avoid duplicate comments, releases, merges, or deployments.

## Hooks

The plugin's `SessionStart` and `PostCompact` hooks run a read-only doctor. Their purpose is to make missing context and unsupported surfaces visible at startup or after compaction. Hook output is context, not authority. Hooks must not mutate repositories, call network services, or block ordinary work when a diagnostic is unavailable.

## Headless execution

Codex supports non-interactive execution, but v0.2 does not package a generic local scheduler wrapper. A portable process-group timeout cannot contain a tool that daemonizes into a new session. Use interactive Codex worktrees for writes, Codex scheduled tasks for task-owned bounded follow-up, and GitHub Actions for repository-owned unattended checks. Treat local persistent headless execution as unsupported until the host provides a verified containment boundary.

## Claims to verify

Before relying on a capability, verify that the current Codex build exposes it and that the task has the necessary tool, sandbox, network, and authentication state. Report missing surfaces as `unknown` or `unavailable`; do not silently replace them with broader access.
