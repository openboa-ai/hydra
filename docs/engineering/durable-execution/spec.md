# S1: durable bounded Codex execution

Status: Proposed implementation contract within the reviewed SDLC v1 architecture.
Work record: https://github.com/openboa-ai/hydra/issues/3

## Outcome and boundary

Run a bounded assignment through the official local Codex runtime, retain identity/events after
process exit, and prevent duplicate or stale execution. Provide real operator status, interruption
and an explicit recovery boundary. S1 cannot publish a branch, create a PR, merge, deploy, declare
Work/Goal achieved, accept a worker's authority claim, or run as an installed background service.
Those capabilities remain subsequent slices; no pretend success path is included.

Implement as a small Python package with standard-library SQLite/CLI and the pinned optional
Codex adapter dependency. Tests of state do not require model access. Live qualification uses an
operator-authorized read-only assignment over this repository, no product code change.

## Data and command contract

An assignment is JSON with required nonempty fields `work_id`, `repository_id` (positive integer),
`goal_ref`, `goal_revision`, `spec_ref`, `spec_revision`, `cwd` (absolute existing directory),
`task`, plus `role` (plan/implement/review/diagnose), `priority` (integer), and `dependencies`
(list of work IDs). Cwd and full input digest are immutable once registered. S1 registration is
an explicit operator command referencing already accepted records, not automatic Issue intake.
It does not claim to have remotely authenticated the referenced delegation. Only the read-only
profile is live-qualified in this slice. Local/private paths and outputs remain in private state.

`StateStore(path)` creates schema version 1, enables foreign keys and busy timeout, and makes a
private DB directory. Existing unknown versions fail closed. Tables hold assignments, runs,
events and a schema version. Use JSON for immutable assignment data plus indexed scheduling and
ownership fields. State contains no credentials. Views expose outcome and wait explicitly.

Before creating or opening state, validate directory ownership and POSIX mode from root to leaf.
Trust only root and the current effective UID. Reject group/other-writable ancestors unless they
are trusted-owner sticky directories whose next component is also trusted-owner. Check aliases
before following them; only root-owned directory aliases are supported. Validate their targets
by the same rules and use the resulting canonical path for database operations. Create missing
directories with mode 0700 only below validated ancestors. The final parent must belong to the
current effective UID and have no group/other write permission. Reject a database-file symlink;
new files start at 0600, and rejected existing files retain their content and mode. This guards
against path replacement permitted by POSIX ownership/mode; it does not claim isolation from
same-UID/root actors or ACL-granted access.

Public store operations return plain dictionaries and raise a descriptive `StateError`:

- `add_work(assignment)`: validate, insert ready; exact duplicate is idempotent, conflicting ID
  rejected; dependency IDs must exist and graph must be acyclic.
- `list_work()` / `get_work(work_id)` / `list_runs(work_id=None)` / `events(run_id)`.
- `claim_next()`: transactional selection of ready work by priority/age, dependencies eligible,
  no cancelled/paused work; max two active assignments and one reserved repository lane. S1 cannot
  produce completed Work, so work with dependencies remains unready in this slice. Returns
  run dict containing immutable assignment, UUID run ID, generation and status, or None.
- `set_identity(run_id, generation, thread_id=None, turn_id=None, process_identity=None)`:
  bind immediately, never overwrite a different existing identity in the same run.
- `record_event(run_id, generation, event_id, payload)`: dedupe exact ID/payload; conflicting
  duplicate rejected; stale payload may be audited but cannot transition current ownership.
- `finish_run(run_id, generation, outcome, detail)`: terminal provider outcome completed/failed/
  interrupted/transport_unknown; store proposed result and actual terminal. Completed becomes
  `waiting` for verification (or decision if explicitly proposed); never completed Work. Failed
  becomes waiting for diagnosis; transport_unknown holds ownership for recovery.
- `pause(work_id)` / `request_cancel(work_id)`: synchronous local stop intent independent of
  network. Ready/waiting work pauses/cancels without dispatch; a running work records stop request,
  rejects subsequent candidate admission and needs confirmed termination. Do not clear ownership
  or repository reservation while a run is active/unknown.
- `resume(work_id)`: only paused work with no unresolved run can return ready; cancelled work
  cannot be revived by this command. No routine wait is automatically converted to ready.
- `recover_run(run_id, confirmed_stopped, reason)`: require actual boolean True and nonempty
  operator observation. S1 CLI has no force-recover switch. Resolve the old attempt as interrupted
  and preserve checkpoint. Cancellation always wins: cancel-requested becomes cancelled, pause
  becomes paused, other stopped recovery becomes paused. Terminal handling uses the same priority.
  Never convert cancellation to a resumable pause. Only paused work may subsequently resume.
  Unknown/active process claims never expire by time.

Use BEGIN IMMEDIATE for claim/mutation and a POSIX file lock held by the coordinator for the whole
run. Stale generation, no identified run, or wrong current owner fails state transition. The lock
is not a substitute for SQLite claims. There are no external GitHub writes in S1; restart does not
assume that arbitrary candidate shell effects can be replayed.

## Codex adapter contract

Pin `openai-codex==0.162.0` and its runtime. Expose:

- `capabilities(cwd)`: installed versions, account type/auth known/unknown, model IDs and usage
  availability. Never expose tokens, account email or auth files. No model generation.
- `execute(assignment, on_identity, on_event, stop_requested, resume_thread_id=None)`: create
  or explicitly resume an identified thread using read-only sandbox and deny_all approval;
  record thread ID before turn, turn ID before stream consumption; invoke synchronous callbacks
  for durable persistence. Return terminal status/result or transport_unknown, with IDs.
- Consume each turn stream once. Save item-completed results keyed by item ID and terminal
  status/usage. Poll the stop callback while consuming, interrupt the exact turn, and wait for its
  terminal acknowledgement. A bounded interrupt timeout produces transport_unknown, not stopped.
- Start-response loss or disconnect is unknown, never automatic restart. Exceptions after an
  attempted start preserve uncertainty. A failure before dispatch can be identified as failed.
- Qualification wall-clock limit defaults to 300 seconds and interrupt grace to 10 seconds.
  Apply the deadline to start/stream as well as execution; after attempted dispatch, expiration
  without terminal observation means transport_unknown. Stop polling works independently of event
  arrival; a queued stream consumer avoids repeatedly cancelling the SDK subscription. Test a
  silent stream with cancellation.
- Construct an explicit rejecting native approval handler for any lower-level capability reader.
  Do not wait for a human in the SDK's transport reader or use default auto-approval.
- Structured result has `outcome` candidate_ready/needs_decision/failed, `summary`, `evidence`
  (array) and `next_action`. It cannot authorize a subsequent action itself.

Use fake SDK/client contracts in tests for terminal, disconnect, duplicate events and cancellation.
An actual local account call and bounded read-only turn establish connection qualification, not
code-writing sandbox compatibility or unattended software delivery.

Read-only sandbox constrains filesystem/shell behavior; it does not prove inherited MCP/connectors
or computer-use cannot cause external effects. The qualification assignment forbids external
tools/effects; this is a bounded behavioral qualification, not a host-isolation guarantee.

## CLI/coordinator integration

`hydra --state PATH status`, `work add FILE`, `run --once`, `pause ID`, `resume ID`, `cancel ID`,
and `doctor --cwd PATH` use the same store/adapter. State path is explicit or a private default
outside product source. `run --once` holds the coordinator lock, holds unresolved prior attempts and their work/repository lanes (not unrelated eligible work),
claims one eligible run, records process PID/start observation, executes, persists callbacks and
reports resulting wait. Use a monotonic clock for in-process timeouts and UTC timestamps for audit.
No perpetual scheduler, automatic install, daemon launch, model heartbeat or hidden retries yet.

On a clean completed turn, another `run --once` does not redispatch the same waiting work.
`status` distinguishes idle/ready/running/waiting/paused/cancel-requested/cancelled; outputs JSON
by default and records exact wait reason. Model text claiming success cannot mutate phase.

## Requirement-linked acceptance

- E1: exact input duplicate is idempotent; mismatched ID/repo/path/revision and invalid types fail.
- E2: concurrent store claims and coordinator locks admit only one mutable run per work/repo;
  global capacity is bounded, and independent eligible repositories can proceed.
- E3: reopening the database preserves run identity/events/wait; elapsed time never reclaims it.
- E4: cancellation blocks late outcome admission and does not release an unconfirmed process.
- E5: duplicate event is idempotent; stale generation/conflicting identity cannot advance work.
- E6: completed provider/candidate-ready/claimed goal achieved does not mark Work/Goal done;
  unchanged verification/decision wait does not dispatch a new run.
- E7: explicit confirmed-stop recovery preserves history; unknown stop does not allow resume.
- E8: fake adapter and actual bounded read-only Codex turn demonstrate IDs, terminal evidence,
  persisted state and no secret-bearing capability output. Live resume/interrupt are separately
  recorded; untested capabilities are not called qualified.
- E9: pause/cancel can be requested locally while remote systems are unavailable.

This slice is execution readiness evidence only. The work record remains open until actual
reviewed delivery, continued goal work and cross-project operation satisfy the parent outcome.

## CI execution

Run the deterministic unittest suite in a separate `Kernel tests` job on PR merge candidates and
main. Use the existing pinned checkout, read-only contents permission, no persisted Git credential,
no secrets, no Codex authentication/model calls, and a five-minute timeout. The runner's Python 3
must satisfy the package's Python 3.11 minimum. Tests use fake SDK contracts and the standard
library; no dependency installation or provider access is needed for this job. The existing
hygiene job remains separate and keeps its trust boundary. The first introduction follows native
CODEOWNER review; make Kernel tests required only after observing its real producer and success.
This job verifies S1 behavior, not external SDK qualification or autonomous delivery.
