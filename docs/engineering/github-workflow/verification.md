# Verification record

The GitHub-native runtime has no SQLite/store imports or replacement workflow DB.
Product GitHub records are the work record. Foreground and eventual login-service
execution use the same CLI.

## Local candidate

On 2026-10-10 the final local suite collected 350 tests on macOS with Python 3.14.2
and pinned SDK/CLI 0.162.0 installed: 332 passed, 16 Linux-only process tests and
2 filesystem-specific raw-filename cases were skipped. The native filesystem
rejects those filenames with EILSEQ; an actual raw Git tree case passed without
changing the checkout or index. `git diff --check` passed. Skipped tests are not
Linux execution evidence.

```sh
python3 -B -m unittest discover -s tests
```

Regression coverage includes immutable intake, pinned policy, exact branch/PR
ownership, first implementation after integration/design, interrupted checkpoint
verification, bounded correction and delivery retries, lost-response read-back,
explicit stopped-host handover, usage waits, private review output, authenticated
provider findings and current formal workflow/job/check identities. Candidate-head
reviews and CI remain required when a PR was merged externally. Current merge
permission is distinct from evidence of an already performed merge.

Focused regressions cover final-guard cancellation before model/verification
dispatch, exact checkpoint restoration and ordinary restart without a spurious
handover. Actual correction dispatch clears the pending mutation marker; cancelled
dispatch preserves it and its budget. Authenticated duplicate summaries or review
rows enter durable diagnosis. Repeated authorized replanning retains an uncertain
request's original head/kind; repaired evidence resumes delivery without new model
work. Interruption fixtures bind cancellation to actual start/turn identity rather
than a timer racing account setup, without changing runtime interruption rules.

Final effects recheck bound dependencies and Issue controls, including after the
last PR observation and during closed-Issue recovery. Exact merge-commit push checks
are re-read after the close intent; newer pending/failed reruns prevent completion.
Review-request retries retain the exact kind across lost responses and replanning;
an observed Code row cannot reset an unknown Security request. Verification records
execution intent, preserves its mutations before review and enters bounded
correction, including stop/restart, policy/ref changes and integration ordering.
Invalid UTF-8 filenames remain lossless private correction input outside publishable
scope. Terminal unsuccessful required
CI enters bounded correction or durable diagnosis. Interrupted design publication
requires exactly the delegated regular bounded specification; pending publication
keeps its original base. Malformed intake cannot hide other Issues from status.
Actual native workspace tests cover staged allocation, crashes around ownership
stamping/promotion, destination races, and exclusive rename without replacement.

The shared SDK/capability/verification process owner requires actual cleanup. A
synchronous verification facade reuses the isolated helper and receipt contract;
it preserves caller-thread stop checks and does not nest event loops or add a
service. Receipt-confirmed group disappearance forbids later fallback signals,
including a reused PGID observation. Linux-specific
cases run below a deliberately non-reaping ancestor and observe remaining children
before test cleanup, including a negative control; they must run on Linux CI. Native
process tests cover cancellation and no signaling after observed group disappearance.
One focused macOS capability run reported unknown cleanup; the cause remains
unexplained. Its exact test passed ten instrumented repetitions with actual reaping,
and the final full suite passed. Cleanup deadlines were not relaxed.

## Actual edit and remaining acceptance

On 2026-10-10 a fresh authenticated pinned-SDK workspace-write turn created exactly
its requested file, with two identity observations, 105 lifecycle events and
confirmed cleanup under deny-all approval. This qualifies a bounded actual edit,
not autonomous delivery of the current implementation.

Current-head remote kernel/hygiene CI, coupled Code/Security Review and native
protected-change approval must be read from PR #4. Previous-head completion does
not qualify the current candidate. Revision-linked source acceptance is recorded
in [the review record](review.md).

Actual product delivery, another-host resumption, host lifecycle integration and
login-service activation remain unobserved. Fixtures, local tests and successful
installation do not establish those outcomes.
