# S1 appendix: supervised SDK execution

> Historical record — this document records the earlier prototype. The current
> [GitHub-native contract](../github-workflow/spec.md) supersedes its operational
> store, private registration and CLI assumptions. Adapter evidence remains scoped
> to the behavior actually tested; it does not establish current autonomous delivery.

Status: Proposed; requires independent acceptance before implementation.
Parent contract: [durable bounded execution](spec.md).
Work record: https://github.com/openboa-ai/hydra/issues/3

## Problem and outcome

The pinned Python SDK offloads startup, requests and shutdown to synchronous worker threads.
Cancelling the awaiting coroutine does not stop those threads. Startup may publish its subprocess
after an earlier close found no process. The reported lifecycle failure in
[openai/codex issue 46903](https://github.com/openai/codex/issues/46903) is consistent with the
installed 0.162.0 source; the issue report alone does not establish a released upstream fix.

S1 must keep its coordinator responsive, retain durable observations, and stop the process group
it created even if SDK initialization or shutdown hangs. It must also distinguish cancellation
before mutation dispatch from uncertainty after dispatch. This appendix changes the execution
boundary, not the assignment's read-only qualification scope or existing GitHub authority.

## Small implementation boundary

- Keep the public async `codex.execute(assignment, on_identity, on_event, stop_requested,
  resume_thread_id=None)` signature and plain result shape.
- Put subprocess supervision and the private transport in one `execution_boundary.py` module.
  Keep provider policy, payload validation, structured results and stream interpretation in
  `codex.py`; its existing execution body becomes an internal worker routine.
- The coordinator process never initializes an SDK client or owns an SDK executor thread.
  It owns SQLite callbacks and one short-lived child per admitted assignment.
- Launch the same Python interpreter with `-I`, the parent-selected absolute adapter source
  path and a fixed private worker entry point, in a new POSIX session/process group. Candidate
  cwd is an SDK argument only; it cannot select the worker source, import path or command.
- Send the assignment over stdin, not argv, environment variables or a temporary file. Preserve
  the existing account/configuration; introduce no credentials, authentication mutation, daemon,
  scheduler, generic subprocess API, model API, desktop attachment or GitHub operation.

The worker initially waits for its input frame and cannot initialize the SDK before it arrives.
The parent records a `hydra/workerStarted` event through the existing durable event callback before
sending that frame. Its parent-observed PID, process-group ID and UTC creation observation provide
recovery evidence. Do not overwrite the coordinator's existing immutable process identity or add
a store schema merely for this boundary. PID observations alone never authorize killing a process
after restart; a live supervisor's owned subprocess handle/group is the cleanup authority.

## Private transport and persistence ordering

Use newline-delimited JSON on the dedicated pipes, with a fixed protocol version and monotonically
increasing sequence number. Permit only initial assignment, dispatch permission, identity, event,
stop poll and final result messages. Each message is at most 1 MiB of UTF-8 data including framing;
an oversized, malformed, unexpected or out-of-order frame fails closed. Do not truncate evidence
and call it complete. There is at most one outstanding worker request; no retry or message broker.

The worker's existing synchronous callbacks become synchronous pipe requests. For identity/event
requests, the parent invokes the original caller callback and sends the matching ACK only after it
returns successfully. The next turn cannot begin before the thread identity ACK, and stream
consumption cannot advance past an event before its persistence ACK. Capture observed IDs before
invoking callbacks so failure outcomes still carry reconciliation information; accepted IDs remain
distinct from mismatched/unbound observations. Existing identity and event validation remains in
force. A callback failure or lost ACK does not authorize retransmission or another SDK operation.

Stop polling uses the same request/reply channel. The parent also checks the real stop callback
while awaiting frames, at the existing polling interval. Thus a worker blocked inside SDK startup
cannot prevent the parent from seeing a local pause/cancel request. A stop response means stop,
not permission for another action. The worker's control reader watches the input pipe throughout
execution so parent EOF is detected even while an SDK call or callback is blocked.

Only the final result lacks a durability ACK: it is an observation returned to the coordinator,
which still owns `finish_run`. Receiving a result or EOF is not evidence that the run was committed.
The parent does not echo raw stdout/stderr, exception text, authentication material or account
identity into result diagnostics. Protocol failures use a bounded reason/error category. Provider
events and assignment/result content remain in the existing private run evidence surface.

## Dispatch and cancellation contract

Before each `thread/start`, `thread/resume` or `turn/start`, the actual mutation coroutine asks the
parent for dispatch permission. The parent checks current stop intent and the deadline, persists a
`hydra/dispatchIntent` event, then returns a sequence-bound grant or refusal. The worker sets its
attempted-dispatch marker only when that coroutine has entered and received a grant, immediately
before invoking the SDK operation. Merely creating a coroutine/task or completing account lookup
does not mark an attempt. The parent conservatively treats a grant it sent as possible dispatch.

If stop wins before the first grant, no mutation can have started: shut down the owned worker/group,
confirm cleanup and return `interrupted` with `stopped_before_dispatch`. If initialization fails or
times out before any grant, confirmed cleanup permits a pre-dispatch `failed` outcome. Failure to
confirm cleanup always returns `transport_unknown`, even without an observed thread ID.

After a grant, retain uncertainty if the response/identity is lost. Do not infer that a missing
thread or turn ID means the operation was not sent. Preserve the requested resume ID in recovery
detail and any observed identities already received. A validated worker report that it stopped
after thread identity but before turn dispatch can retain the existing `stopped_before_turn`
outcome only after group cleanup is confirmed. A parent kill alone cannot prove a provider turn
was interrupted or undo a request that reached the provider.

When a turn is known and stop is requested, the worker retains the existing exact-turn interrupt
and bounded transient-rejection behavior. It must observe the matching terminal event; an
interrupt response alone is not termination evidence. Parent cancellation follows the same stop
and bounded cleanup path rather than abandoning a live SDK worker. No automatic start/resume retry
is introduced, including for an active-writer conflict with another Codex process.

## Parent deadlines and cleanup

The parent starts the existing 300-second qualification deadline before launching the worker.
Stop or expiry allows at most the existing 10-second cooperative interruption/cleanup grace after
possible dispatch; pre-dispatch stop need not wait that grace. A blocked initialization, SDK close,
worker executor shutdown, pipe read or result wait cannot extend this deadline indefinitely.

At the hard boundary, terminate only the newly owned process group: SIGTERM, up to one second to
collect, then SIGKILL and up to one more second to collect. Confirm the direct child was reaped and
the owned group is gone. A subprocess exit, result frame or closed output pipe without group cleanup
is insufficient. Cleanup uncertainty is explicit and preserves ownership through
`transport_unknown`; it is never converted to a successful doctor or stopped run. Do not signal
desktop Codex, other workers, a process found by broad name matching, or a pre-existing writer.

A valid provider terminal outcome may be retained after forced local cleanup only if its matching
terminal event was durably ACKed, identities match, the final result was received and group cleanup
was confirmed. Otherwise forced shutdown returns `transport_unknown` after possible dispatch,
retaining all received IDs and the latest acknowledged evidence. Existing store cancellation
precedence still determines whether a completed candidate may be admitted.

Parent control-pipe loss forbids new dispatch. The worker's control reader terminates its own
new session/group on EOF or invalid control traffic, without attempting a fresh SDK request. The
parent's durable run remains unresolved for explicit reconciliation after restart. This is a
bounded process-lifecycle measure on the current POSIX host, not a sandbox, credential boundary,
or guarantee against OS failure or descendants that deliberately escape the owned process group.
Existing local SQLite callback/storage failure limits remain; no unbounded synchronous external
callback is added to the supervisor.

## Required acceptance evidence

Use the actual private transport and real disposable Python subprocesses with fake providers.
No authenticated model turn, external mutation or installed service is required for these tests.

1. Stop immediately after account lookup and before the mutation coroutine enters: no dispatch
   grant, no thread/turn invocation, confirmed cleanup, `interrupted` rather than held uncertainty.
2. Stop races with a dispatch grant or loses its response: no replay, preserve known/requested IDs,
   and return unknown unless an exact terminal/stopped-before-turn observation resolves it.
3. Identity and event callback commits precede ACK; a held callback prevents dependent turn/stream
   progress. A callback exception or lost ACK never permits the next operation.
4. A fake blocking startup creates its runtime late; a blocked initialization/request/close and an
   executor that ignores coroutine cancellation cannot hold the outer `asyncio.run` process open.
   Confirm only the test worker/group is terminated, including the SIGTERM-resistant path.
5. A silent stream and an immediate event burst remain cancellable; bounded framing/backpressure
   prevents unbounded transport buffering. Oversized or malformed frames fail without raw output.
6. Worker exit, parent pipe EOF, parent cancellation and terminal/result response loss preserve
   uncertainty and IDs as appropriate; no worker or owned descendant survives confirmed cleanup.
7. A clean exact-terminal run still saves IDs/events and returns the same candidate result; a
   provider-completed result never declares Work/Goal achieved. Existing adapter tests still pass.
8. Test the launcher from an unrelated cwd with a shadow module/PYTHONPATH candidate: only the
   parent-selected implementation runs and private assignment text never appears in argv.

Retain the current qualification limitations: SDK-internal buffering is not bounded by Hydra's
handoff queue, independent desktop ownership may block resume, and passing this appendix's tests
establishes execution lifecycle behavior rather than autonomous product delivery.
