# Review and ship

**Change rate:** fast. This is a replaceable method, not doctrine.

Use this playbook to review a candidate change, prepare a pull request, deliver it, or recover from a bad delivery.

## Review the outcome, not only the diff

Check, in order:

1. Does the result satisfy the stated outcome in the actual environment?
2. Do deterministic tests and trusted CI pass?
3. Did an independent reviewer or evaluator inspect the risky assumptions and failure paths?
4. Are permissions, side effects, migrations, rollback, and observability appropriate?
5. Is the pull request a coherent review unit rather than a premature fragment?

Model self-review can find defects, but it does not overrule a failing deterministic check. Avoid correlated consensus: several agents repeating the same assumption are not independent evidence.

## Apply review backpressure

Review and integration capacity limit useful throughput. Before starting more implementation, inspect the ready-for-review queue, including its depth, oldest wait, blocked checks, and the declared work-in-progress limit. Record an unavailable measure as `unknown`, not zero.

When the queue exceeds its bound or completed work is waiting longer than the agreed limit:

- stop or reduce new parallel starts and worker fan-out;
- prioritize finishing evidence, resolving review, rebasing stale candidates, and integrating accepted work;
- direct available agents toward independent verification or removing a named review blocker instead of generating more candidates; and
- resume normal dispatch only after the queue is within its declared bound or the work lead records a justified change to that bound.

Backpressure is not a human approval ceremony. It is a flow-control decision made by the work lead so accepted outcomes, not generated changes, remain the unit of progress.

## Prepare the pull request

Link the durable Issue without automatically closing it when post-merge observation remains. State the outcome, important design decisions, changed surfaces, migration, verification, known uncertainty, and rollback. Keep generated detail behind links when it would obscure the decision.

Use GitHub Actions from trusted base-controlled workflow code. Give the workflow token the least privilege it needs, pin third-party actions to full commit SHAs, and do not execute untrusted candidate code with secrets or write credentials.

## Ship at the declared boundary

Routine, bounded delivery may proceed through passing checks and repository rules. Public release, official communication, and a public commitment always wait for the human decision. A merge waits only when repository policy declares it human-gated; in that case present the exact head revision and current evidence once. A changed head invalidates that approval. Material production, financial, legal, privacy, security, or irreversible effects follow the human gates in the authority policy.

After delivery, read back the actual merge, release, or deployment state. Observe the outcome before closing the work item.

## Roll back or repair

Prefer a forward fix when the system remains safe and the correction is bounded. Stop rollout and use a revert or documented recovery when authority, data integrity, security, installability, required checks, or core behavior is compromised. Do not rewrite published history or tags to hide a failed release.
