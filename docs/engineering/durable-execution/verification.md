# S1 verification record

Observed 2026-10-09. This record separates local tests, real execution, and delivery.

## Deterministic acceptance

`python3 -m unittest discover -s tests -v`: 53 tests passed without Codex installation or model
access. They cover assignment validation and idempotency, competing claims, repository/global
reservations, reopen persistence, cancellation priority, stale generations, unknown execution,
explicit recovery, malformed results, unchanged waits, adapter identity binding, silent streams,
interrupt limits, SDK/runtime pinning and non-sensitive capability output.

Independent review identified and the change fixed saved-thread propagation, malformed result
handling, incomplete database detection, invalid JSON/integer boundaries, and malformed adapter
outcomes. Provider completion remains a verification/decision wait, never delivered Work.

## Actual local Codex qualification

The pinned SDK/runtime pair 0.162.0 reported existing authenticated ChatGPT access, available
models and readable usage. A bounded read-only repository inspection completed with persisted
thread/turn IDs and a structured result. Reopening state preserved verification wait and did not
dispatch another turn.

An immediate interrupt after resume exposed a real startup race: the provider explicitly rejected
the interrupt because the turn was not active yet. The adapter preserved an unknown result and
ownership. An official thread read subsequently confirmed the exact turn interrupted before
recovery. The adapter now records request/response attempts and retries only this explicit
rejection, at most twice within the original interruption deadline; unknown responses are not
retried. Tests exercise delayed activation, exhaustion and cancellation of pending retries.

With the correction, a real resumed turn reported interrupted. A subsequent execution reused the
same thread, completed, and returned to verification wait. Another state reopen was idle without
a duplicate run. Raw thread identities, local paths and transcripts remain private.

The observed corrected interrupt succeeded on its first request. The bounded retry branch has
deterministic coverage; it is not claimed to have fired in that successful live run. Earlier failed
qualification attempts remain in the audit history rather than being counted as successes.

## Limits and external checks

This qualifies local read-only execution and explicit recovery, not unattended code writing,
automatic GitHub delivery, a background installation, full host isolation, product acceptance or
multi-project operation. The operator explicitly reconciled unknown attempts using external
terminal evidence. Automatic recovery dispatch is still a later slice.

Current PR hygiene/Kernel tests, code and security review, native workflow ownership approval,
merge and post-merge CI are separate external delivery requirements. They are not established by
the local results above. The parent outcome remains open until actual delegated development
through delivery and continuation has been demonstrated.
