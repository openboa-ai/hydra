# Pull-request convergence

- Target: one repository and pull request, bound to its current head.
- Prefer: GitHub event-triggered scheduled task for commits, reviews, and comments; use a same-task interval only when active continuity is needed.
- Read: head revision, declared required checks and producers, Codex review on the exact head, unresolved threads, mergeability, and linked outcome.
- Act: fix routine findings inside the approved branch, rerun focused checks, and request another independent review.
- Notify: new blocker, failed recovery, changed authority, or exact-head merge gate.
- Stop: merged, closed, superseded, expired, or waiting only for a human gate.
- Never: merge, weaken checks, resolve a reviewer thread without fixing it, or create duplicate comments merely because a run was retried.
