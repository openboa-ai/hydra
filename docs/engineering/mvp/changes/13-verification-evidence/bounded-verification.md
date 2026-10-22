# Bounded verification and review completion

Implementation scope: [P13 revision 4](spec.md), particularly R2–R4, R6 and R8;
[CP revision 9, section 8](../../contracts/control-plane.md#8-command-envelope와-공통-guard);
and [EX revision 8](../../contracts/execution.md).
The existing command, candidate, assignment and receipt contracts remain authoritative.

## Command behavior

`hydra_command_v1` accepts the closed `workflow_step.verify_only` variants through
the existing guarded command handler. A request selects a candidate and reply
profile; it cannot select commands, credentials, permissions or an effect ceiling.
The optional installation admission profile still grants only `admission_set`.
No installed verification authority or native-client capability is enabled here.

`run` checks the exact attempt, head, contract, repository, owner, accepted spec,
intake, base, clean workspace and current admission. It invokes the protected
project's registered verifier rather than reusing an earlier invocation's cache.
Actual results, argv and output digests remain in the existing private memory
lifetime. Public receipts contain the verdict, candidate, pending review and actual
GitHub progress reference. Private output has no fabricated public evidence URL.

A standard reply never allocates a review assignment. A private native handoff
requires current run, review-completion and handoff grants before ticket creation.
It returns the controller's actual matching `read_only` `change_review` assignment.
Missing support leaves review pending. The serializer checks the full assignment
and bounds its encoded size before registering a ticket. A bridge cannot obtain
a native handoff. Caller metadata and a selected reply profile confer no authority.

`review_checkpoint` checks the exact live review and candidate, unchanged spec and
workspace, and the actual invocation examined by that review. Matching candidate
keys or identical copied result JSON do not prove invocation identity. It records
and reads back the bounded final result before retiring the exact review step and
releasing its ticket. It does not invoke legacy checkpoint or continuation.

| Review outcome and proof | Bounded result |
| --- | --- |
| `candidate_ready`, same valid actual invocation | `change_review_done`, `locally_verified`, review accepted |
| `candidate_ready`, missing or changed invocation proof | Review pending; `verification_evidence_unknown` / `verification`; no automatic new run or review |
| `failed`, including lost proof | Review failed; `review_findings` / `diagnose_review`; no correction |
| `needs_decision`, including lost proof | Review pending; `product_decision` / `operator_decision`; no automatic question or decision |
| Candidate, workspace, intake, policy or admission drift | Hold the affected operation and preserve recoverable ownership and edits |
| Unattributable replay after retirement | Unknown, without a replacement receipt or assignment |

## Execution and recovery

A denial before the worker is created is positively undispatched. The owner
retains the original progress and exact acknowledged intent, then restores only
that intent under current authority, policy, intake and a fixed current control
revision. This scope permits progress only: it owns no workspace edits and cannot
checkpoint, create a review, publish or launch work. Pause/Stop remains in force.
Lost grants prevent the write; a retained private witness can reconcile after
regrant without launching verification in that recovery. A later eligible retry
can run once. Lost private evidence leaves an unresolved intent unknown.
An invoked uncertain restoration receives exact read-back without retransmission.
The same boundary handles the intent's own post-write check and the final grant.

The storage provider's pure command-construction boundary normalizes its
ValueError/RuntimeError into the existing bounded verification diagnosis. Earlier
commands have already drained and the next command has not launched. Explicit
provider uncertainty and unrelated untyped worker exceptions stay unknown.
A source-confirmed valid unchanged verification also projects the existing
accepted-spec source into the ordinary specification cache, as native checkpoint
does. Restart recovery accepts neither a new specification nor a code review.

The final private assignment return rechecks current configuration, admission and
handoff grants after the last source read. Revocation during that read leaves the
review recoverable and returns no private assignment or verifier output.
Reply construction remains inside the original coordinator ownership. A handoff
is marked returned only after the final reply guard. A previously returned
assignment keeps that status when a later retry lacks handoff grants.

If only handoff authority is lost, a never-returned review assignment can be
retired through the fixed original-source operation under remaining workflow
authority, policy and admission. Loss of workflow authority or an unknown source
preserves its ticket for authorized recovery. This is logical assignment cleanup;
it does not infer task termination or retire a previously returned assignment.

Workflow dispatch compares the controller's loaded configuration identity with
the current host configuration. A new digest cannot relabel already-loaded
storage or lifecycle providers; changed bindings require controller restart.
Embedded controllers without a startup identity cannot use configured providers.

Registered verification uses the existing supervised `Workspace.verify` in an
awaited worker with the original ownership and admission context. The MCP event
loop stays available for Pause. Exact admission revisions guard each launch and
bounded effect. Cancellation requests the existing supervisor's stop path and
waits for its result before releasing coordinator ownership. Unconfirmed cleanup
retains the host hold; cancellation is not termination evidence.
Existing host cleanup holds also block this route. An explicit new verification
invalidates earlier local acceptance for the candidate before dispatch. The new
private invocation links are cleared with the original review lifetime, including
an explicit legacy stop; they cannot outlive that step as accepted evidence.

Verifier edits may be safely checkpointed once. If this changes the candidate,
the command returns `candidate_changed` with no receipt for the old pin. It never
refreshes the pin or verifies the new head automatically. Completion ACK loss is
reconciled from the original progress source; it does not repeat verification.
That includes the changed-candidate record: its actual checkpoint head and exact
planned record survive an uncertain write in the existing private invocation
lifetime. A matching request replay can return only the confirmed
`candidate_changed` observation, without certifying or verifying the new head.
An unapplied or changed source remains unknown without a second checkpoint.

The completed invocation and its exact planned record are retained before the
final mutable write. An uncertain write receives a bounded original-source
read-back. A same-request retry reconciles that private invocation and cannot run
D or allocate a second review. After unresolved completed work is reconciled,
an explicit new request can start an actual new invocation. This memo is bounded
and process-local, not a durable request ledger
or a way to reconstruct a verdict after restart.

A wait before review registration retains its actual reason. A same-request
retry may recheck the resolved condition and dispatch that review with the same
validated invocation, current scope and handoff grants. It does not rerun D or
allocate a second existing assignment.
Confirmed release of a never-recorded ticket also clears its retired private
draft. Recovery can then create the actual review from that original invocation.

A deterministic verifier exception after an earlier command completed is not a
full verification verdict. Its original private request memo is retained before
settlement, and a guarded, exact source read-back clears the running intent into
the existing replan/diagnose-verification hold. Same-request replay returns that
wait without D; a new request cannot bypass unresolved diagnosis. An uncertain
settlement remains unknown and blocks ordinary reentry. A confirmed source hold
survives restart without reconstructing a missing private verdict.
An incomplete or invalid result list enters the same hold. In particular, a
signalled command cannot leave a replayable intent merely because it returned
partial results instead of throwing an exception.

Dispatch, preservation and later review have separate admission boundaries.
After the supervisor positively drains the owned invocation, its actual result
and local edits are retained before any final write. Preservation revalidates
current workflow authority, runtime, loaded providers, project policy and the
exact original source, then pins a fresh control revision. The existing confirmed
cleanup scope permits only that result record and an owned local checkpoint;
it never changes Pause/Stop or permits a new command, review assignment,
publication, delivery or resource retirement. Unknown supervisor cleanup grants
no preservation exception.
An owned edit to the specification is preserved as a changed candidate too;
preserving those bytes does not accept the edited specification or certify the
old pin. Full clean-candidate and accepted-spec checks remain necessary for any
verification verdict.

A Pause racing with a completed valid run preserves its actual receipt while
withholding review. After explicit Resume, the ordinary lifecycle can consume
that same invocation. Grant revocation prevents preservation writes; a later
authorized request first reconciles the retained positive completion before
considering new verification. Successful recovery binds that same private
invocation to the recovery request and remembers the original request in the
existing bounded retired-request cache. Replaying either request cannot turn
that completed recovery into another invocation. Only a writer actually invoked
inside the guarded effect counts as an attempted write. An uncertain attempted write is read back,
without retransmission. After private evidence loss, an unresolved executing
verification intent remains unknown through both entry points instead of
automatically repeating potentially stateful commands. The runner's positively
ended cleanup queue retains its existing recovery path.

Final read-back compares the exact attempted record, including phase, waits and
next action. Same candidate pins cannot certify unrelated progress. An unrecorded
review ticket may be released only with positive local birth/ownership, no
handoff and the exact original progress observation; cleanup preserves Pause.
An uncertain retirement write is read back once before confirming its matching
ticket. Missing, changed or incomplete source remains unknown without reposting.

A confirmed accepted review adds the existing verified-candidate marker only
after exact source retirement. A later ordinary invocation can continue toward
delivery without rerunning D or requesting the same review. A failed judgment
records correction debt and the existing retry budget for that later invocation;
the bounded command itself does not start correction. An ACK-loss retry does not
charge another correction attempt. Missing invocation proof grants no marker.
Failed verification records the same bounded diagnosis debt. The existing private
summary cache carries actual verifier output or review findings to the matching
candidate's later correction assignment as untrusted data. It is never progress
text or a public receipt. Successful correction/acceptance clears that candidate's
diagnosis; different candidate pins prune obsolete context. Restart does not
reconstruct a lost private summary from a reason code.

The fixed scope permits registered verification, its local checkpoint, progress
recording and the qualified independent review assignment. Publication intents,
workspace publication and other provider writes are rejected below dispatch.
There is no implementation assignment, PR creation, remote review request, merge,
Issue close, resource retirement, new evidence database or model service.

## Verification and qualification limits

The test modules use actual temporary Git repositories, registered subprocesses,
independent effect spies and the pinned MCP SDK:

- `test_native_verify_only.py`: unchanged normal and failing-run oracles.
- `test_native_verify_only_contract.py`: candidate and scope guards, exact review
  completion, all outcomes, restart, run/result mutation and final-record ACK loss.
- `test_native_verify_only_faults.py`: verifier edits, grant revocation between
  commands, effect-ceiling enforcement, output/run-link corruption, proof loss
  during read-back, retirement ACK loss, oversized private handoff and SDK routing.
- `test_native_verify_only_admission.py`: concurrent SDK Pause and cancellation
  with observed owned-child cleanup while actual verification is running.
- `test_native_verify_only_recovery.py`: existing host holds, earlier local
  acceptance invalidation and cleanup through the explicit legacy stop path.
- `test_native_verify_only_review.py`: loaded providers, unhanded ticket recovery,
  final-record ACK loss/retry, foreign same-pin progress and retirement ACK loss,
  with unchanged-provider and pre-write-failure controls.
- `test_native_verify_only_return.py`: final-source-read grant revocation, normal
  private handoff and same-request recovery without a second D invocation.
- `test_native_verify_only_lifecycle.py`: accepted-review continuation, failed-review
  correction debt and cap, missing proof, never-returned assignment cleanup and
  preservation of previously returned or foreign-source assignments.
- `test_native_verify_only_deferred.py`: changed-candidate ACK loss/read-back,
  unapplied records, actual private correction prompts, failed-verifier debt and
  pre-registration wait recovery under current grants.
- `test_native_verify_only_errors.py`: released draft recovery, partial invocation
  exceptions, diagnosis-record ACK loss, unknown settlement and restart holds,
  with an actual stateful first command and unavailable second executable.
- `test_native_verify_only_incomplete.py`: an actual signalled first command,
  incomplete results, untouched later command and a held ordinary continuation.

The first source CI ran all 1,637 methods successfully in 583.313 seconds with
eight explicit skips, but exhausted the ten-minute job budget before evidence
export. The kernel job now has a fifteen-minute execution budget, including
setup and export. Required checks, test cases, their own deadlines, permissions
and pinned trusted tooling are unchanged. The cancelled run is not a green CI
result; final-source CI and its evidence export must complete independently.
The next 1,645-method run took 590.679 seconds and exposed the stale ten-minute
capacity assertion. The bounded capacity test now uses that measured baseline,
two minutes of setup/export reserve and the fifteen-minute outer limit. Individual
test deadlines and product acceptance assertions retain their existing meaning.
The subsequent 1,655-method run completed in 675.675 seconds but failed two
subcases of a worker privacy assertion: an opaque SHA-256 value happened to
contain the synthetic PID digits. A fixed valid collision digest now reproduces
that case deterministically. The assertion qualifies only the defined opaque
runtime digests before checking all remaining public output for PID disclosure;
unknown execution/count and held-Quit assertions remain intact. This failed run
is not reported as green CI.

Run these with the repository's supported Python 3.14+ interpreter and pinned MCP
dependency; then run the affected legacy command, native, ownership and admission
suites and the full kernel checks. Final-head CI and independent code/security
review remain required before protected delivery.

These are deterministic source and SDK-fixture checks. Synthetic grants and
review judgments do not qualify an installed native caller, independent L review,
remote operating flow, two-project acceptance or the complete v1 product. Actual
RequirementRef acceptance and artifact-source mapping remain separate from this
command's private invocation proof. Renderer activation and other command
capabilities retain their existing qualification boundaries.
