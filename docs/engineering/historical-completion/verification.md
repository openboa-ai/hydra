# Historical completion verification

Date: 2026-10-11. Base: `679c3d0cd7d71beaa9cbfe33b35e8818e1d14c4e`.
Accepted specification SHA-256:
`bcce542c16e9996f813110b1b1f828f760c5b3cd746c8775a9a66e2588d2f02b`.

## Change and initial local evidence

Only the historical `pull_request` association case in `project._bound_runs`
changes. An explicitly empty array is eligible only for an observed closed,
merged PR with a valid merge SHA. Existing producer, check, review and squash
evidence requirements remain in place. No Runner, workflow or policy changes.

The following initial results apply to revision
`a4e44faa6cb060b67951040c2bf0386e9b6642b3`, before the head-repository review
correction below; they do not establish the corrected revision's full-suite result.

Tests ran on macOS with Python 3.14.2 through the task-owned storage wrapper.
Each invocation printed and asserted that `hydra_sdlc.project.__file__` resolved
to this checkout, rather than the interpreter's installed package.

| Verification | Result |
| --- | --- |
| New historical regression against unchanged base source | 1 expected failure: `check_identity_missing:Unit tests` |
| `test_project`, `test_squash_completion`, `test_runner` | 108 passed, 0 skipped; 0.445 s |
| Full `unittest` discovery under `tests` | 667 collected: 642 passed, 25 skipped; 245.305 s; exit 0 |
| `git diff --check` | Passed |

The first focused run exposed a new test's incorrect observation count: the
existing completed-Issue reconciliation checks push evidence twice again on a
subsequent call. The fixture now asserts two reads on initial completion and four
after repetition. No runtime behavior or gate was changed for that correction.
The full run emitted asyncio shielded-future diagnostics in existing startup
cancellation and invalid-identity negative tests; the suite reported no failures
or errors. This is not a warning-free test-output claim.

## Requirement coverage

- R1/R2: Historical empty association passes with later main advancement;
  identical live checks and delivery gates reject it, including on a merged PR.
  Missing, null, malformed and wrong nonempty associations remain ineligible.
  Exact merged state is required, and the target-event reusable pin remains
  required.
- R1/R3: Workflow, repository, event, head, branch, job and check mismatches,
  failed reruns, unresolved threads, absent review or squash receipt, and wrong
  result parent/tree remain blockers.
- R4: Fresh Runner instances reconstruct the merged task after branch deletion,
  observe checks on the merge SHA and close once without another model or merge.
  Pending/failed push checks hold the Issue open. A failed candidate rerun
  observed after close intent also prevents closure. Repetition rechecks evidence
  without issuing another close.

Independent read-only review of the frozen source and regression diff found no
blocking issue against the accepted specification. This is local source review,
not a GitHub provider review or CI result.

## Head-repository review correction

Subsequent Code Review identified a missing producer-repository binding in the
new historical exception. That exception now requires `head_repository` to be an
object whose `id` is an exact integer matching the registered repository ID.
Populated association checks, live gates and the target-event reusable producer
path are unchanged. The observed successful run `38097834649` exposes the expected
integer head-repository ID `1411114385` for `openboa-ai/ouroboros`.

Two new regressions failed against the initial source: a same-head/same-branch
fork run was accepted, and a newer fork success hid an owned failed run. Both now
reject that evidence. Missing, null, non-object, absent-ID, boolean, string,
floating-point and foreign head-repository values also remain ineligible, while
the owned-repository positive control passes.

Current focused verification (`test_project`, `test_squash_completion`,
`test_runner`): **111 passed, 0 skipped, 0.369 s**. The checkout module assertion
and task-owned storage wrapper were retained. Full-suite verification of this
correction and current-head CI/provider reviews are pending at this document's
freeze; the initial revision's full-suite result above is not substituted for
them.

## Remaining delivery evidence

R5 remains pending: current-change GitHub CI and coupled code/security reviews,
actual merge, installation into a separate verified runtime, and continuation of
the waiting Issue through a fresh installed controller. These local tests do not
prove that live completion or lifecycle cleanup has occurred. No completion
override, manual Issue closure or installed-runtime edit was used.
