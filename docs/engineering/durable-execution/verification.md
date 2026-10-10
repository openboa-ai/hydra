# S1 verification record

> Historical record — this document records the earlier prototype. The current
> [GitHub-native contract](../github-workflow/spec.md) supersedes its operational
> store, private registration and CLI assumptions. Adapter evidence remains scoped
> to the behavior actually tested; it does not establish current autonomous delivery.

Observed 2026-10-09. This record separates local tests, real execution, and delivery.

## Deterministic acceptance

`python3 -m unittest discover -s tests -v`: 94 tests passed without Codex installation or model
access. They cover assignment validation and idempotency, competing claims, repository/global
reservations, reopen persistence, cancellation priority, stale generations, unknown execution,
explicit recovery, malformed results, unchanged waits, adapter identity binding, silent streams,
interrupt limits, SDK/runtime pinning and non-sensitive capability output.

Independent review identified and the change fixed saved-thread propagation, malformed result
handling, incomplete database detection, invalid JSON/integer boundaries, and malformed adapter
outcomes. Provider completion remains a verification/decision wait, never delivered Work.

PR code review found two additional failure paths. Process inspection now has a five-second
timeout and occurs before claiming work, so inspection failure cannot strand an undispatched
run. Capability inspection runs in a separate POSIX process with a 20-second deadline and at
most two seconds for its own process-group cleanup. This avoids an unbounded SDK request holding
up the command's default-executor shutdown. A real subprocess regression blocks that request,
ignores TERM, and verifies bounded command exit and removal of the probe process. Unconfirmed
cleanup reports unavailable. Both corrections received independent implementation review.

A subsequent review identified duplicate registration after a workspace became unavailable.
Exact stored-input matches now return the existing Work before checking the live directory;
new or conflicting registrations remain rejected. The regression removes the workspace and
checks all three outcomes without dispatching or adding a second record.

Event ownership and nested terminal identity/status are validated before persistence, so a
foreign item, usage event or terminal cannot enter the current run's evidence. CLI database-open
failures return a structured nonzero response instead of a traceback. Regressions exercise
foreign-event persistence and real invalid database paths/formats.
Known work-evidence events require actual provider IDs, including nested started/completed turn
IDs. A malformed known notification wrapped by the pinned SDK cannot supply missing identity
through a current-run default. Independent review found this related path before publication;
fixtures cover it in the same correction batch.
The strict identity checks also accepted all 25 relevant events saved from the real qualification
runs. This was replay validation, without another model call.

Further PR findings are covered by the same bounded contract. Process identity and the run claim
now commit in one transaction; a rejected identity insert leaves no run or reservation. Existing
invalid state files retain both bytes and permissions, while new state files are private from
creation. A mismatched resume response retains requested/observed IDs as recovery detail without
binding the foreign thread or starting a turn. The stream handoff has one-event capacity and
cooperative scheduling; cancellation closes a backpressured stream within the shared cleanup
budget. Independent reviews accepted these corrections. This bounds Hydra's handoff queue, not
all buffering inside the SDK or provider process.

The final lifecycle corrections follow the independently accepted
[SDK process boundary appendix](sdk-process-boundary.md). The coordinator never owns the SDK's
blocking worker threads: one disposable process group contains startup, requests and shutdown.
Identity/event callbacks commit in the parent before an ACK permits dependent progress. Actual
subprocess fixtures cover late or blocked startup, response loss, parent cancellation/EOF,
oversized or malformed frames, blocked shutdown and SIGTERM-resistant descendants. Independent
review repeated 59 adapter/boundary tests and ten real subprocess-creation cancellation races;
the integrated 90-test suite passed locally. GitHub-hosted Ubuntu also passed all 90 tests in
[CI run 37916412136](https://github.com/openboa-ai/hydra/actions/runs/37916412136) at revision
`4319c59aa5beaa6d8b2d1017204e944775a6255c`.

A stop before the mutation coroutine begins no longer marks an attempted dispatch. A failed
provider terminal always waits for diagnosis even if its earlier result proposed a human decision.
Both failure classifications have requirement-linked regressions.

The silent-turn stop test now waits for persisted turn identity rather than assuming interpreter
startup completes within 150 ms. It covers normal and deliberately delayed startup. State-file
opening validates the original directory chain's owner/mode before following trusted aliases or
creating directories, then uses the canonical private parent. Regressions reject a shared
ancestor and untrusted alias, allow a private leaf below a trusted sticky directory, and preserve
the content/mode of a rejected file-symlink target. The integrated 94-test suite passed locally.
Both existing qualification databases reopened with their original verification/recovery waits
and run counts; this compatibility check made no provider calls or recovery transitions.

## Actual local Codex qualification

The pinned SDK/runtime pair 0.162.0 reported existing authenticated ChatGPT access, available
models and readable usage. A bounded read-only repository inspection completed with persisted
thread/turn IDs and a structured result. Reopening state preserved verification wait and did not
dispatch another turn.

The packaged CLI was also invoked from outside the source checkout. With the corrected capability
process boundary, a real `doctor` call returned known account/model/usage observations in 2.4
seconds with confirmed cleanup. This inspection did not generate a model turn.

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

An additional real resume attempt after the final review corrections was rejected because the
existing thread already had an active writer. No new thread/turn identity was acknowledged.
An official read showed the five earlier turns terminal; a separate resume-only diagnostic
confirmed the writer conflict without starting a turn. Hydra preserved this attempt as recovery
wait and reopening state dispatched nothing. The writer was not forcibly taken over. This
additional attempt is blocked qualification evidence, not a successful new resume or a reason
to erase the earlier successful observations.

With the supervised boundary integrated, a separate bounded read-only qualification used the
pinned real SDK/runtime and a fresh test state/thread. It completed with the worker launch and
both dispatch intents durably recorded, returned to verification wait, and reopened idle without
duplicate dispatch. The supervisor confirmed process-group cleanup before returning completion.
The earlier desktop-writer conflict and its unresolved test record were preserved; the new
qualification did not take over that thread or claim cross-host recovery.

## Limits and external checks

This qualifies local read-only execution and explicit recovery, not unattended code writing,
automatic GitHub delivery, a background installation, full host isolation, product acceptance or
multi-project operation. The operator explicitly reconciled unknown attempts using external
terminal evidence. Automatic recovery dispatch is still a later slice.

Authenticated runtime execution has been qualified on native macOS; deterministic process
fixtures have also passed on GitHub-hosted Ubuntu. Containers with a PID 1 that does not reap
orphans are unsupported. A killed orphan can retain a process-group entry there, so cleanup
remains unconfirmed and ownership stays held for recovery. This preserves the contract's
cleanup condition; no subreaper, container support, or ignored-zombie exception was added.

Current PR hygiene/Kernel tests, code and security review, native workflow ownership approval,
merge and post-merge CI are separate external delivery requirements. They are not established by
the local results above. The parent outcome remains open until actual delegated development
through delivery and continuation has been demonstrated.
