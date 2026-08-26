# Pull-request convergence

- Target: one repository and pull request, bound to its current head.
- Prefer: GitHub event-triggered scheduled task for commits, reviews, and comments; use a same-task interval only when active continuity is needed.
- Read: head revision, declared required checks and producers, Codex review on the exact head, unresolved threads, mergeability, and linked outcome.
- Evaluate: classify failed checks and review findings, identify the smallest coherent fix and verification commands, and create a task-local handoff to an interactive Codex task.
- Notify: new blocker, failed recovery, changed authority, or exact-head merge gate.
- Stop: merged, closed, superseded, expired, or waiting only for a human gate.
- Never: edit the branch, comment, request review, resolve a thread, merge, or weaken checks from the scheduled run.
