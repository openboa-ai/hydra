# Automate and monitor

**Change rate:** fast. This is a replaceable method, not doctrine.

Use this playbook when work should wake on events or time, run without continuous human attention, converge a pull request, or observe a delivered outcome.

## Start from the outcome

Automate a repeated decision or observation, not activity for its own sake. Name the state being watched, the evidence that can change, and what useful action follows. If the action still needs product judgment on every run, improve the decision boundary before adding a schedule.

## Design the run

1. Discover available capabilities and choose the least-powerful adapter.
2. Bind one target, authority boundary, sandbox, credentials, network scope, timeout, retry limit, cost bound, and expiry.
3. Declare wakeups, invalidation rules, idempotency, lock behavior, durable logs, and notification conditions.
4. Separate state collection, pure evaluation, and external mutation.
5. Keep the default path read-only. Gate persistent installation and consequential writes at their actual boundary.

## Run and reconcile

On every wakeup, read the current target first. Compare it with the last attributable state and do nothing when no relevant change occurred. If a prior write has an uncertain result, read it back before retrying. Stop when the outcome is done, expired, unsafe, repeatedly failing, or waiting for a named decision.

## Notify by exception

Notify when state meaningfully changes, a bound is crossed, recovery fails, evidence becomes stale, or a human decision is required. Do not send routine “still running” messages. A useful notification includes the target, observed state, exact evidence, action already taken, remaining uncertainty, and next safe decision.

## Validate before persistence

Exercise a one-shot dry run, success case, no-change case, hostile input, lock contention, timeout, and rollback. Inspect logs for secrets and private content. Only then ask for the exact persistent schedule or workflow-policy change. After enabling it, observe at least one real wakeup and read back the registered state.
