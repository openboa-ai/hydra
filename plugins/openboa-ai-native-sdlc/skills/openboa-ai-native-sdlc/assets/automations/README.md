# Automation templates

These are prompts and design checklists, not installed jobs. Adapt one template to an exact outcome, test it manually, and follow [Automate and monitor](../../references/playbooks/automate-and-monitor.md).

Prefer a Codex scheduled task for same-task continuity and GitHub events for repository state. v0.2 does not package a generic local runner, launchd job, or cron entry because portable process-group timeout does not contain detached descendants. A future local scheduler adapter must prove OS-level containment and cleanup before it can be adopted.

Every adaptation must replace generic targets with canonical repository, Issue, pull request, revision, environment, cadence, timezone, expiry, permissions, stop conditions, notification rules, and rollback.
