# Automation templates

These are prompts and design checklists, not installed jobs. Adapt one template to an exact outcome, test it manually, and follow [Automate and monitor](../../references/playbooks/automate-and-monitor.md).

Prefer a Codex scheduled task for same-task continuity, GitHub events for repository state, and a one-shot headless runner for local execution without an open task. The launchd and cron examples are inert files. Loading either changes the user's environment and requires an exact persistent-install decision.

Every adaptation must replace generic targets with canonical repository, Issue, pull request, revision, environment, cadence, timezone, expiry, permissions, stop conditions, notification rules, and rollback.
