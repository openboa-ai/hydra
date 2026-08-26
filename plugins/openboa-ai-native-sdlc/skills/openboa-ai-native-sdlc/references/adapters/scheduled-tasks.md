# Scheduled-task adapter

Scheduling is a wakeup mechanism, not a source of purpose or authority.

## Choose the scheduler

1. Use a Codex scheduled task for follow-up that belongs to the current task and benefits from its context.
2. Use GitHub Actions for repository events or repository-owned periodic checks.
3. Treat launchd, cron, and other generic local wrappers as unsupported in v0.2. Process-group timeout alone cannot contain a detached descendant.

The plugin provides prompt templates for supported native surfaces; it does not register persistent local jobs.

## Every scheduled job declares

- outcome and exact target;
- wakeup event or cadence, timezone, and expiry;
- capability and authority boundary;
- read-only sandbox and an explicit prohibition on checkout and external writes;
- lock, timeout, retry limit, and resource bound;
- live-state reconciliation and idempotency key;
- success, change, failure, and human-decision notification rules;
- durable log location and retention; and
- disable and rollback procedure.

Offset periodic repository checks from existing jobs to reduce contention. Avoid schedules faster than the evidence can change. Silence means only that no notification condition was met; it is not proof of health.

In v0.2 a Codex scheduled task may inspect, evaluate, notify, and create a task-local handoff. If code, branch, Issue, pull-request, release, deployment, credential, or policy state must change, stop and route that action to an interactive task or a separately verified managed adapter. Declaring a write boundary in a prompt is not containment.

## Persistent-install gate

Creating or enabling a new scheduler integration, granting filesystem or network access, or adding credentials changes the execution environment and requires an explicit decision for that exact adapter and job. The adapter must prove containment, cleanup, and rollback before it can carry unattended write authority.
