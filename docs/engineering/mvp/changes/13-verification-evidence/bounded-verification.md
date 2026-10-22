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
