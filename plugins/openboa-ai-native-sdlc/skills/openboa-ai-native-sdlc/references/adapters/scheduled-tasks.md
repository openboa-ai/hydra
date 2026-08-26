# Scheduled-task adapter

Scheduling is a wakeup mechanism, not a source of purpose or authority.

## Choose the scheduler

1. Use a Codex scheduled task for follow-up that belongs to the current task and benefits from its context.
2. Use GitHub Actions for repository events or repository-owned periodic checks.
3. Use launchd on macOS for a local one-shot headless command that must survive the UI closing.
4. Use cron only when launchd or a platform scheduler is unavailable.

The plugin provides templates; it does not register persistent jobs.

## Every scheduled job declares

- outcome and exact target;
- wakeup event or cadence, timezone, and expiry;
- capability and authority boundary;
- read-only default and any explicitly allowed write;
- lock, timeout, retry limit, and resource bound;
- live-state reconciliation and idempotency key;
- success, change, failure, and human-decision notification rules;
- durable log location and retention; and
- disable and rollback procedure.

Offset periodic repository checks from existing jobs to reduce contention. Avoid schedules faster than the evidence can change. Silence means only that no notification condition was met; it is not proof of health.

## Persistent-install gate

Generating a plist or crontab example is reversible repository work. Loading a launchd job, editing a user's crontab, granting filesystem or network access, or adding credentials changes the execution environment and requires an explicit decision for that exact job.
