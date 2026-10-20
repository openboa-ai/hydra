# P13 verification — first evidence-collector stage

Date: 2026-10-19. Design: P13 Revision 4 and VF Revision 11, accepted design
baseline `ad9d6382465023b9aa11e8f662c2d6d906216e10`.
Implementation parent: `55460e38e74d3bf00ba6002c111c7b481b166d46`.

This record covers the first stage's selected D collection, safe export and CI
consumer. It does not complete P13-R8, activate `workflow_step.verify_only`, expose
a native command, or qualify native review/completion. P13 as a whole remains
incomplete pending the separate execution stage and applicable live L/O evidence.

## Implemented boundary

The stdlib collector loads a closed manifest containing original requirement
references, exact unittest methods and versioned oracle fixtures. Each selected
method is required. Actual loader results and start/completion counts must agree;
zero collection, missing/import-failed selectors, skip, expected failure, unexpected
success, failed subtests, class-fixture failures and interruption cannot become PASS.
The process returns zero only after all selected methods passed and a valid safe
envelope was exported. There is no shell/argv from the manifest or model service.

The initial manifest selects five existing source methods, already present on main,
covering two limited cases: canonical repository policy identity and required CI
producer/candidate evidence. Each has a normal-progress and forbidden-effect oracle.
Its explicit exclusions retain the rest of v1, live L, native O, `verify_only`, and
trusted CI attestation. These are source replay tests, not live provider operation.

The envelope includes VF §2's per-case fields plus the selected/excluded scope.
Requirement document content, policy, fixture, manifest, source bytes, actual Git
HEAD, supplied base and distinct PR source head are bound to the run. Dirty tracked
source and untracked Python in execution directories are rejected before execution.
Actual tracked bytes and modes are compared with HEAD blobs independently of index
stat hints. The same bindings are checked after execution and on read-only artifact validation.
A changed or corrupt artifact cannot trigger test execution or reuse old PASS.
Null base is explicitly `not_supplied`; a timestamp never substitutes for a revision.

Each execution creates a fresh public verification alias, repeated in every row's
same-run reference. This prevents combining successful rows from separate failed
runs at the same revision. The alias is not a native ID or authentication token.

Only validated public references, revisions, counts and fixed reason codes leave
the collector. Test/import/subprocess/FD output, exception text, skip reasons,
subtest labels and shutdown-handler output are discarded. It is an output boundary
for reviewed repository tests, not a sandbox for arbitrary hostile Python. Supported
CLI/CI entry requires `python3 -I`; a built-in-sys guard rejects ordinary invocation
before other imports, preventing script-directory startup shadowing.

Artifacts use a fixed repository-relative directory, reject symlink parents/targets,
anchor publication through no-follow directory descriptors and publish without
replacing earlier files. Export failure returns nonzero, preserves prior evidence
and does not retry tests or their effects. Artifact contents are not authority:
actual CI producer/workflow/event/ref/head still require provider verification.

The existing full kernel suite remains mandatory. CI adds the collector's actual
exit gate and uploads only its one safe JSON file on success. Existing permissions,
concurrency, Python matrix, Mac job and trusted hygiene tool/config boundaries remain.
The artifact action is pinned to official v7.0.2 commit
`cf430e030ddbb5b0abf93d22962f4752f3646cd9`, verified from its
[official release](https://github.com/actions/upload-artifact/releases/tag/v7.0.2)
and [commit](https://github.com/actions/upload-artifact/commit/cf430e030ddbb5b0abf93d22962f4752f3646cd9).
The official action definition uses Node 24. Missing artifact is an error; hidden
files and overwrite are disabled. No credentials or permission grants were added.

## Requirement and oracle evidence

| Requirement / case | Evidence in this stage | Remaining limit |
| --- | --- | --- |
| R1 / T01 | Actual complete and missing-method cases in one report: complete case PASS, missing case NOT RUN; references pinned to original document | Semantic requirements outside the selected manifest are excluded |
| R2 / T06 | Isolated real gate source mutations remove identity validation, accept unknown evidence, accept stale CI, or deny every valid candidate; each fails the independent positive/negative oracle | This is a deliberate bounded mutation sample, not exhaustive fault coverage |
| R3 / T02 | Real subprocess methods cover zero/missing/import error/duplicate/callable, class setup, skip, expected failure, unexpected success, failed subtest and interruption | No provider or live agent execution implied |
| R4 / T03–04 | Candidate/source/base/spec/policy/fixture and corrupt envelope invalidation; same-run source change; dirty initial source and untracked Python rejected | Artifact producer authenticity remains external |
| R5 | Explicit selected D and excluded L/O scope; public development cases and independent live evaluation handoff in `evals/mvp/README.md` | No live L/O trial claimed |
| R6 / T05 | Private synthetic canary through import, oversized print, native FD, child, exception, subtest, skip and shutdown handler; no canary, traceback or local path in public subprocess output | Trusted CI secret scan remains separate |
| R7 / T08 | Actual CI collector shell accepts normal run and rejects required skip; mutation tripwire detects full-suite deletion, trusted-scanner redirection and permission widening | Final immutable candidate review, full suite and actual CI still required |

## Execution history

All tests used the required external workspace storage runner with Python 3.12.
Paths below are repository-relative inner commands; no host-private identifiers or
runtime details are part of this public record.

1. Meaningful initial RED: an actual required skipped unittest returned exit 0.
   The behavioral assertion that required skip must not satisfy evidence failed.
   The module was collected and executed; this was not a missing-import RED.
2. First collector run: 16 tests collected; 15 passed, one CI mutation fixture failed
   because its replacement token did not match the current trusted-config spelling.
   The defective fixture was corrected without changing the product expectation.
3. Collector GREEN: 16 tests passed in 5.966 seconds. Adding the real versioned
   manifest integration control produced 17 passing tests in 6.188 seconds.
4. Additional meaningful RED: a test shutdown handler emitted the private canary
   after ordinary FD restoration. Keeping standard output suppressed through
   process exit fixed the actual subprocess boundary.
5. Additional meaningful RED: pre-existing modified test source at unchanged HEAD
   executed and returned success. Clean-source/tracked-input enforcement fixed the
   false candidate attribution. Positive controls now commit their synthetic
   candidate inputs in isolated temporary Git repositories.
6. Intermediate focused GREEN: **20 tests, 20 passed, 0 skipped, 0 failed in 8.395 seconds**:
   `python3 -m unittest discover -s tests -p test_mvp_verification_contract.py -v`.
   This includes the actual five selected source methods through the collector,
   the real CI shell and the two review-fix regressions above.

7. Independent review produced three additional meaningful REDs: actual untracked
   startup `argparse.py` emitted a private canary before rejection; assume-unchanged
   and skip-worktree each hid dirty bytes from candidate attribution; passing rows
   from two complementary-failure runs at identical pins were accepted when spliced.
   Three methods produced four failing assertions. No import-missing RED was used.
8. After isolated startup, exact HEAD blob/mode comparison and public run-alias
   binding: **23 tests, 23 passed, 0 skipped, 0 failed in 9.515 seconds** with the
   same focused command. The original positive control and actual manifest still pass.
9. Adjacent regression: `test_project.py` **33 passed** (0.041 seconds),
   `test_repository_intake_identity.py` **7 passed** (0.048 seconds), and
   `test_ci_whitespace.py` **13 passed** (13.913 seconds), each via unittest discovery
   under the required storage runner; no skips or failures.
10. Existing verified actionlint 1.7.12 checked the actual workflow through stdin,
    using an empty private config, `-shellcheck=` and `-pyflakes=`: **exit 0**.

The focused checkpoint above did not establish final full-suite or hosted CI
success. No runtime activation or public MCP behavior outside the first-stage
collector/CI scope changed.

## Final isolated source verification

The integration candidate used the implementation parent's Git archive plus the
exact reviewed nine files and the maintained specification's required `python3 -I`
invocation clarification. Unrelated skill changes were excluded. Independent code
and security reviewers verified the final collector, tests and workflow hashes;
all three material findings were closed and no remaining material finding was
reported. This is separate from hosted PR reviews.

The exact isolated Python 3.12.7 suite collected **1,047 tests: 1,022 passed,
25 skipped, zero failures/errors; 284.417 seconds, exit 0**. Actual installed MCP
packages were 2.3.0. None of the platform/optional-dependency skips is counted as
PASS. All 207 candidate file bytes remained unchanged during the run.

The same tested bytes were frozen in a clean temporary Git fixture. The actual
`python3 -I scripts/run_mvp_verification.py` exporter executed the versioned
manifest: two selected cases and five required source methods passed, with a valid
safe artifact and process exit 0. A separate invocation of `--validate-report`
accepted that artifact and the same source bindings without repeating tests.
No source bytes changed during either invocation. The fixture has no supplied base;
the artifact correctly retains null with its reason rather than inventing a SHA.

Only the verification text was appended afterward. These are source/fixture D
results, not a hosted producer certificate, native capability or protected merge.
Actual final-head CI and protected publication remain pending.

## Publication and handoff

The current-main manifest is pinned to the exact accepted workflow specification
bytes at `9ade2282c7ebe031db2e5ee9808f194b765529dd`. The document delta appends the
already-delivered exact-main CI preservation correction; the selected identity/CI
requirements and independent oracles are unchanged. The current-base fixture
below executes and validates the repinned manifest.

Mechanical collector behavior has no model-mediated judgment, so live L for this
delta is N/A with that reason. Overall v1 L, native O02 and P13 second-stage tests
T07/T09 remain NOT RUN. O05 is pending actual final-candidate CI. The implementation
owner retains review fixes and focused verification; delivery owns final source/CI
reconciliation and protected publication. Later narrow verification execution owns
the actual candidate/review/native handoff. This stage does not remove those duties.


## Current-main integration — 2026-10-20

This stage reuses the prepared collector, tests, oracle fixtures and workflow on
verified protected main `9ade2282c7ebe031db2e5ee9808f194b765529dd`. P13 Revision 4
is unchanged. Only the two requirement-document references in the manifest are
repinned; production collector behavior and existing CI controls are unchanged.

The exact archive with these source files passed **76 impact tests, no skips,
failures or errors, in 24.204 seconds**: collector contract 23, project 33,
repository identity 7, and CI whitespace 13. This includes normal progression,
required-skip rejection, canary suppression, revision/source invalidation, isolated
faults, mixed-run rejection, no-replace export and the actual CI shell consumer.

The tested bytes were frozen in a clean temporary Git fixture. The actual isolated
exporter ran two selected cases/five required methods with the current specification
pin; a separate read-only invocation accepted the same report without rerunning
tests. Both returned exit 0. Candidate bytes and existing implementation work were
preserved. These fixture results do not authenticate a hosted producer.

This verification record was updated afterward. Full final-candidate checks belong
to hosted CI, followed by independent code/security review, normal protected merge
and exact-main checks. Existing scoped human review of workflow controls remains
required. P13-R8 and the native/live limits above remain incomplete.


## Requirement-reference and classification corrections — 2026-10-20

PR #16 review identified three first-stage evidence defects. A syntactically valid
section slug was accepted even when the referenced heading did not exist; subtest
execution exceptions were labelled assertion failures; the repository-identity
fixture named S01 instead of canonical scenario S25.

The manifest now resolves requirement sections before collecting or executing
selected tests. Supported ATX and single-line Setext headings include ordinary
inline code/emphasis and duplicate suffixes. Fenced/indented code and raw HTML do
not create headings; ambiguous inline markup does not manufacture an anchor.
The basic anchor rules follow [GitHub's section-link documentation](https://docs.github.com/en/get-started/writing-on-github/getting-started-with-writing-and-formatting-on-github/basic-writing-and-formatting-syntax#section-links).
The synthetic positive fixture now includes its actual acceptance heading.

`addSubTest` distinguishes the test's failureException from other exception types,
retaining the fixed test_failure/test_error codes without exporting exception text.
The versioned identity fixture now names S25; its regression derives the expected
scenario from the unchanged canonical verification matrix.

Three collected regression methods produced **eight failing assertions** against
original head `7856c7782a3a795e7387af635345f93088cae6e2`, with no import/collection
errors or skips. These reproduce renamed/mistyped/missing headings including code
examples, the wrong subtest reason and the incorrect scenario connection.

Initial GREEN: **79 passed, zero skips/failures/errors**: collector 26, project 33,
repository identity 7 and whitespace 13. A final focused collector run after adding
raw-HTML controls and tightening that exclusion passed all **26 collector tests**.
The adjacent 53 checks' source and workflow are unchanged; the full candidate runs
in hosted CI. Normal headings, formatting, duplicate anchors and Setext controls
still execute and export PASS; unresolved references execute no selected effects.

The original candidate's two actual hosted Python artifacts were also consumed
read-only against independently reconstructed candidate/source/base/spec/policy/
fixture bindings and the provider's exact checked merge tree. Both contain two
cases/five passing methods. This is historical evidence for the original head,
not final-head CI for these corrections. Tests were not rerun to inspect artifacts.

Accepted P13/VF specifications, existing CI controls and native authority are
unchanged. Final-head CI, independent reviews, scoped human workflow approval,
protected merge and exact-main checks remain required. P13-R8 and live L/O remain
outside this stage's completion.


## Frozen-input, cancellation and CI-budget correction -- 2026-10-20

Further PR #16 review identified insufficient kernel budget, a live-file post-scan
race, missing early SIGTERM handling and untracked compiled-module shadowing.
The collector now materializes pinned Git objects as a read-only import root.
Selected tests retain their registered effects working directory; imports do not
use live source or generated packaging outputs. Git replacement refs are disabled,
snapshot paths/links are contained, and owned snapshot directories are released.
This is a source-input boundary, not a sandbox for hostile Python or a certificate
of live worktree cleanliness. The original source checks also finish with a Git
consistency check; no claim of an atomic transaction across live writers is made.

Preflight covers CPython source, bytecode and extension suffixes in the execution
roots. A real sourceless module and extension-loader precedence cases reject
before effects. Bytecode writes are disabled before collection and in the kernel
CI environment. The CLI still uses isolated Python. The kernel job budget is ten
minutes, with other jobs, required checks, permissions and trusted hygiene intact.
The budget is based on the documented 284.417-second full-suite observation plus
setup/evidence overhead; no prior successful CI is relabelled as a timeout.

SIGTERM handling now starts immediately after output suppression for both execute
and read-only validation paths. Actual cancellation during blocked Git preflight
returns the fixed interrupted result and exit 2 with owned children released.

Behavioral evidence: six original assertions reproduced immutable-input, early
cancellation, binary-shadow and budget defects. The first background-writer test
had an untracked barrier file and was not counted. After tracking that fixture
input, one actual owned background-writer assertion reproduced PASS after a
previously scanned source was changed; its unchanged-writer control passed.
Independent literal-heading tests also reproduced two false anchors from plain
underscores; true underscore emphasis remains a normal-progress control.

The 31-test collector run passed all 29 behavior tests; its two CI tripwires still
expected the former timeout literal. Updating those assertions for the intentional
bounded budget/cache policy, and adding the normal packaging-output control,
passed the focused three-test CI/compatibility run. Production source was unchanged
between those runs. The earlier adjacent 53 project/identity/whitespace results are
separate impact evidence; full final-candidate checks belong to hosted CI.

This integrates the first-stage files onto verified protected main
`d1ac65a98f93f8a2e2ade423aaf621287c96df42`, whose four actual-main checks passed.
The P05 MCP source and P01 installed-read record are preserved. Accepted P13/VF
specification bytes are unchanged. Final-head independent reviews, CI, scoped
human workflow approval, protected merge and exact-main checks remain required.
P13-R8, live model/native operation and the full remote v1 sequence remain incomplete.


## Warm-cache CI recovery and portable snapshot oracle -- 2026-10-21

Run [39443825518](https://github.com/openboa-ai/hydra/actions/runs/39443825518)
failed the standalone collector at original head
`b09c93542be74e9be13275c6a4738bf05e06c288`. Both complete Python suites had
already succeeded: 1,160 collected, 1,152 passed, eight explicit skips, zero
failures/errors (3.11: 204.798 seconds; 3.14.2: 218.023 seconds). The collector then
returned invalid_input/exit 2. This is a failed CI run, not a passed artifact gate.

Preflight was rejecting existing PEP 3147 caches even though these are excluded
from the fresh Git-only import snapshot. Execution-root scanning now leaves those
unrelated caches intact; legacy sourceless modules and extension shadows remain
rejected. The snapshot still contains only tracked Git inputs and disables cache
writes. No cleanup or live-cache execution substitutes for source verification.

A new actual subprocess control creates an unchecked-hash cache containing
different code and a forbidden side effect beside the verified tracked source.
It reproduced one assertion failure on the original collector. After correction,
the verified source executes and exports PASS, the poisoned side effect is absent
and the original cache still exists. This guards both compatibility and import
isolation rather than merely allowing all cached code.

Review also identified a nonportable test assumption: UID 0 may write a file whose
mode is 0444. The oracle now checks the separate snapshot source identity, declared
read-only modes, unchanged original bytes and writable effects cwd on all runs.
The actual write-denial assertion is applied to unprivileged execution. A simulated
root-reporting branch verifies that no write-denial assumption is used there;
this is not a real root isolation or sandbox qualification.

The full focused collector suite now passes **32 tests, no skips/failures/errors**,
including snapshot/race/cancellation, legacy bytecode/extension rejection, safe
output, CI shell and versioned manifest controls. Production/source bytes and the
unrelated checkout were preserved. This record was appended afterward. Final-head
hosted CI, independent reviews, existing human workflow approval, protected merge
and exact-main checks remain required; native/full-v1 limits are unchanged.


## Pinned definitions and separated execution -- 2026-10-21

Parent `94b4084cea094295b01033089d9b0016c86e454b` integrated verified main
`7e0b570d85017f21c193248842873f55d55e6ff1` without rewriting the nine P13
paths or five independent P09 paths. All four jobs in
[run 39456774067](https://github.com/openboa-ai/hydra/actions/runs/39456774067)
passed, and both real hosted artifacts passed read-only binding validation against
the provider-verified checked merge tree, including their archive digests. Those
selected-source results do not cover the five further code-review defects below.
They are historical evidence rather than final evidence for this correction.

The correction has three boundaries:

- Definitions are parsed from the Git-only read-only snapshot before selection.
  Manifest, fixture and requirement interpretation cannot come from transient live
  replacements. The manifest/policy digests use those same pinned inputs, and the
  original source is checked again before publication.
- Only the supervisor owns public output and publication. A fresh isolated Python
  child imports and runs tests using private stdin/stdout, closed inherited
  descriptors, bounded JSON transport and cleanup of its owned process session.
  The supervisor validates schema, counters, refs and interpreter context. Normal
  test output stays discarded; corrupt or oversized private output is never
  forwarded. This is process/output separation within one user identity, with the
  existing filesystem/effects cwd. It is not OS sandbox or CI authority evidence.
- A failed post-link finalization removes only this export's report inode. Prior
  evidence and a foreign replacement remain untouched. Temporary-link cleanup and
  visible-path read-back are part of finalization before success is reported.

SIGTERM has a persistent latch in each collector process. Catching the injected
KeyboardInterrupt in a selected method cannot turn cancellation into PASS.
SystemExit during import is collection_invalid and allows an independent valid
case to run; a test-method exit remains a test error through unittest.

Five new behavioral cases ran against unchanged parent source and reproduced
**six actual assertion failures, zero setup errors/skips**: transient-manifest
selection, public descriptor writes (including oversized output), import exit
classification, caught SIGTERM, and reuse after failed export finalization. The
last case also confirms preservation of a foreign replacement and no effect
replay. The initial private harness qualification counted subtest suffixes as
distinct methods; its count was corrected against the same preserved log without
rerunning or changing the six assertions.

The initial corrected implementation passed **90 tests, zero skips/errors**:
37 collector cases and 53 adjacent project/identity/CI regressions. Self-review
then reproduced one additional assertion failure on that unpublished separated
baseline: a test could change sys.version_info and report a false interpreter.
The supervisor now requires the actual interpreter context it launched. The final
collector suite passes **38 tests, zero failures/errors/skips**; the unaffected
53 adjacent passing regressions are retained rather than rerun.

The existing late background-writer regression keeps its actual already-scanned
file mutation and unchanged-writer control. Its injection hook now belongs to the
external test driver; it no longer assumes selected code can monkeypatch the
supervisor after deliberate process separation. Both controls pass, with the
mutated source still preventing export.

P13 Revision 4 and the verification definition remain unchanged. There is no
workflow/protection/authority expansion, new model runtime or P13-R8 activation.
Private test logs and host paths remain outside public artifacts. Final corrected
head CI, independent code/security reviews, scoped CODEOWNER approval, protected
merge and exact-main checks remain required; native/full-v1 limits are unchanged.


## Completed publication and late cancellation -- 2026-10-21

Parent `793a800aca5e41dde03d7d6581359d2c13e76bad` passed all four
[CI jobs](https://github.com/openboa-ai/hydra/actions/runs/39463406466).
Each Python suite collected 1,190 tests: 1,182 passed, eight explicit skips.
Both real hosted artifacts passed independent source/checked/base binding and
archive-digest validation without reexecuting tests. One further code review
identified contradictory late cancellation: a valid report could remain after
the public outcome was relabeled interrupted during snapshot teardown.

Successful export now commits the completed D outcome. Only after data/directory
sync, temporary-link cleanup and visible inode read-back does one supervisor-owned
assignment publish that outcome to the signal handler, export rollback and final
public reply. Cancellation before this point still interrupts and removes this
export's new report. After this point, late signals or teardown exceptions cannot
relabel finalized evidence. No verification, publication or other effect is replayed.
Validation-only calls publish nothing and retain their cancellation behavior.
The per-call state stays in memory and cannot be supplied by manifest/model data.

An actual precommit directory-sync SIGTERM remains a nonzero interrupted result
without a new report. Three postcommit controls (real SIGTERM, KeyboardInterrupt
and teardown exception) reproduced three assertion failures on unchanged parent
source. After correction they retain the completed outcome and the same report
passes read-only validation, with its single effect unchanged. The final focused
collector suite passes **39 tests, zero failures/errors/skips**. The earlier 53
unaffected adjacent passing regressions are retained; full local suites were not
repeated. P13/VF pins, workflow policy, authority and native exclusions are unchanged.
New final-head CI/reviews, scoped human approval, protected merge and actual-main
checks remain required. This is source evidence recovery, not full v1 acceptance.


## Snapshot input drift and full report capacity -- 2026-10-21

Integrated parent `cf0899fea8081603dcd836e64a306d1336c913e5` passed all four
[CI jobs](https://github.com/openboa-ai/hydra/actions/runs/39475236613). Each Python
suite collected 1,226 tests: 1,218 passed, eight explicit skips. Both actual hosted
reports passed independent source/checked/base and provider archive-digest
validation without reexecuting tests. Code review then found two additional
defects in snapshot integrity and report capacity; the earlier green is retained
as historical evidence rather than final qualification.

Read-only modes do not make a same-owner snapshot immutable. The actual snapshot
now has its full file/symlink stream checked against the pinned source_revision
before each selected import, after selected execution, and independently by the
supervisor before publication. Executable modes, read-only inputs, extra files and
Git-derived directory structure are checked. A selected test cannot chmod/rewrite
a later snapshot module and silently export it as committed PASS. An external
post-worker snapshot change also prevents publication while retaining its one
original effect and the untouched original checkout. This remains source-drift
detection at the checked boundaries, not an OS sandbox or new execution owner.

The 256-KiB manifest/request budget and accepted 64 cases / 32 selectors / eight
references remain unchanged. Report capacity is separately bounded from at most
two copies of manifest-controlled data, fixed per-method/per-case envelope
overhead and the root header (3,149,824 bytes). Private capture, report decoding,
indented export and read-only consumption use this same report bound. No valid
manifest is narrowed to fit the former 256-KiB output limit.

Four new regression methods reproduced **five actual assertion failures** on
unchanged published parent source, with zero setup errors/skips. The two snapshot
substitutions formerly produced PASS artifacts that the ordinary read-only
consumer accepted. Passing 32x32 and 64x32 selector matrices, each with eight
requirement refs per case, previously executed all effects but failed report
transport/export. A valid 180,000-character class identifier exposed the same
duplicated-selector budget error. After correction these cases export and validate
the same report without repeating effects. Stress-fixture deadlines are explicit
and bounded; existing default deadlines and the product worker budget are retained.

The changed collector plus project, repository-identity and CI-policy impact
regressions pass **96 tests with zero failures/errors/skips** (43 collector and
53 adjacent cases). No full local suite was repeated. Accepted P13/VF pins,
workflow policy, authority and native exclusions are unchanged. New final-head
CI/reviews/artifacts, scoped human approval, protected merge and actual-main
checks remain required. P13-R8 and full-v1 operation remain incomplete.


## Selector isolation, independent fixture definitions and regular report inputs -- 2026-10-21

Parent `9a8995f7d452c182ddb36bb40f3040148acf6869` passed all four
[CI jobs](https://github.com/openboa-ai/hydra/actions/runs/39480409559).
Each Python suite collected 1,230 tests (1,222 passed/eight skips), and both actual
hosted reports passed read-only source/checked/base/digest validation. Independent
code review then found three additional defects. This historical green does not
qualify the corrected head.

The orchestration worker no longer imports selected tests. Every selector runs in
its own isolated interpreter with a private bounded pipe; prior class or dependency
patches cannot replace a later committed method. Termination, interpreter identity,
source checks, safe aggregate publication and the existing total worker budget are
preserved. Child selectors remain in the supervised process group. This is process
and output separation for reviewed tests, not a same-user sandbox.

Versioned oracle definitions now require the exact nine fields, D classification,
nonempty typed preconditions/events/positive/forbidden-effect oracles and scope,
and unique S01--S30 scenario links. These definitions do not replace the actual
assertions/effects. Report reads open without following the final link, reject
non-regular inodes through fstat before reading, and consume bounded UTF-8 bytes.
FIFO/directory/UTF-16/UTF-32 inputs return the safe failure protocol without replay.

Three behavioral methods reproduced 19 actual assertion failures on unchanged
parent source, with no setup errors/skips. The intermediate descriptor reader's
encoding regression was independently reproduced and fixed before publication.
The first 99-test correction run retained one 64x32 stress-fixture timeout; the
method/effect/count oracles remain unchanged and its explicit fixture wait is now
240 seconds, inside the unchanged 600-second product-worker and ten-minute CI
budgets. That failed trial is not reported as PASS.

The final correction passes 99 focused/impact tests: 46 collector methods plus
53 project/repository-identity/CI-policy regressions, zero failures/errors/skips.
Both 32x32 and 64x32 matrices execute every method once and validate the same
export without repeating effects. No full local kernel suite was repeated.
Accepted P13/VF pins, workflow policy, native exclusions and authority are unchanged.
New final-head CI/reviews/artifacts, scoped CODEOWNER approval, protected merge
and actual-main checks remain required. P13-R8/full-v1 operation are incomplete.


## Isolated worker cost, request framing and actual invocation -- 2026-10-21

Parent `80ff5ee6e4c479eafb6898637360bc42dc4b204b` exhausted the unchanged ten-minute
[required kernel budget](https://github.com/openboa-ai/hydra/actions/runs/39485469177)
on both Python runners. Mac/hygiene passed; the cancelled kernel jobs and absent
standalone evidence remain incomplete. New independent code findings identified
the expensive maximum matrices, a compact-manifest/private-envelope mismatch and
counter-only lifecycle overrides that could omit the selected method.

A fresh isolated interpreter still owns orchestration and never imports selected
modules. On single-threaded Linux/macOS it forks a pristine child per selector,
closes inherited private descriptors and uses the same bounded capture/reaping.
No earlier selected heap can reach the next selector. Unsupported fork profiles
retain fresh exec. Normal Python shutdown still runs atexit callbacks; a real
shutdown-effect/canary regression verifies both execution and private output.
Children remain in the supervised group. No new sandbox, provider or authority
is claimed. The full 64x32 accepted matrix remains required; the redundant 32x32
replay was removed after it also passed, reducing required-job cost without a
smaller accepted manifest or a changed maximum-shape/effect oracle.

Private worker input now has its own derived bound: one manifest-bounded selector
plus a separately checked root/pins/framing envelope, at most twice 256 KiB. Public
manifest input stays 256 KiB and report capacity is unchanged. An exact compact
262,144-byte manifest exercises fresh-exec framing, completes once and validates
without repeating effects. The selected callable is wrapped with a sync/async
invocation probe: fabricated result counters cannot replace its actual one call;
missing/repeated calls cannot pass. Ordinary async unittest remains supported.

Two behavior methods reproduced four actual assertion failures on unchanged
published parent source, with zero setup errors/skips. The corrected collector
plus adjacent project/repository-identity/CI-policy regressions passed 102 methods
(49 collector +53 impact), zero failures/errors/skips, on Python 3.14 (patch version not retained) in 218.720s.
That run exercised both 32x32 and full 64x32 shapes. The final test edit only removes
the smaller parameter: exact AST comparison confirms every remaining body/oracle
is the already-executed one. Product bytes are identical to the GREEN snapshot.
No full local kernel replay or CI-budget/required-check relaxation was performed.
Final-head CI, actual artifact consumption, independent reviews, existing scoped
CODEOWNER approval, protected merge and actual-main checks remain required.
Accepted P13/VF contracts and native/verify_only/full-v1 exclusions are unchanged.


## Verdict transport, completed execution and source-check cost -- 2026-10-21

Parent `54a1ecf9f846b9daa56be50046944adc6b82bb4e` failed both Python jobs in
[CI](https://github.com/openboa-ai/hydra/actions/runs/39490156193): each collected
1,236 methods and hit the 240-second 64x32 fixture timeout. Mac/hygiene passed.
The outer job budget did not cancel these runs; the collector artifact stage was
not reached. These failures remain distinct from earlier cancelled runs.

Independent review reproduced a failed selected method becoming PASS when its
tearDown patched process-global JSON encoding. Selected code now writes a fixed
44-byte primitive packet using operations captured before import. The pristine
orchestrator validates it and owns aggregate JSON serialization. Public artifact
fields and existing output bounds are unchanged. This is an output boundary for
reviewed repository tests, not a same-user or OS sandbox.

The execution probe requires exactly one invocation and one completed return.
It retains actual method exceptions even when a custom run override swallows
them; unfinished daemon calls and lazy generator/async-generator/coroutine returns
cannot certify an unexecuted body. Ordinary async, unittest fixtures and shutdown
semantics remain covered. Four new methods produced seven actual assertion
failures on unchanged published parent source, with no setup errors/skips.

Repeated boundary checks reuse pinned paths and per-file hashes while reading and
hashing actual bytes every time. Directory identity/names, file identity/mode,
length and content must still match. Initial/final canonical checks remain. A
same-size rewrite with restored mode/mtime cannot execute a later substituted
module. An unpublished metadata-cache prototype was rejected after its own fault
test reproduced that forbidden effect under coarsened metadata; it was never
committed or published. The final byte-check implementation passes that regression.

The final exact product/test bytes pass 108 focused and impact methods (55 collector
+53 project/repository-identity/CI-policy), zero failures/errors/skips, on Python
3.14 (patch version not retained) in 174.526 seconds. The full 64x32 effect/count/export/read-only-consumption
case remains required. No maximum, timeout, required check or CI budget was relaxed,
and no full local kernel suite was repeated. Accepted P13 Rev4/VF Rev11 pins are
unchanged. Final-head CI, actual hosted artifact consumption, independent reviews,
existing scoped CODEOWNER approval, protected merge and actual-main checks remain
required. This does not complete P13-R8 or qualify native/full-v1 operation.


## Exact collection, ordinary returns and compile-only reuse -- 2026-10-21

Parent cf84505 passed Python 3.11, Mac and hygiene in
[run 39496243222](https://github.com/openboa-ai/hydra/actions/runs/39496243222).
Python 3.14 still failed: 1,242 collected, eight skipped, a 240-second full-matrix
timeout and a second cleanup error when the surviving worker raced with temporary
directory removal. A single Python report is not whole-run or final-head success.
Security review completed without findings; two in-scope code findings required
the changes below. Deliberate same-user descriptor forgery was triaged outside the
already documented reviewed-test boundary. No hostile-code sandbox is claimed.

The callable must return None, so map/filter/custom iterators cannot certify
deferred work. Collection captures the pristine loader method before importing
selected code and requires the returned test to have the exact selected class,
in addition to the existing method id/count and actual invocation/completion checks.
Two behavioral methods reproduced five actual assertion failures against unchanged
published parent source, with zero setup errors/skips; their exact assertion ASTs
are retained in the GREEN candidate.

The maximum fixture places all 2,048 methods in one module. The clean orchestrator
now compiles bounded repeated module input once, without importing or executing it.
Each fresh fork receives immutable code objects and executes a fresh module heap.
The 8-MB source-cache budget changes no accepted input: uncached modules retain
ordinary compilation. No pyc cache, selected heap, weaker byte checks, reduced
matrix or longer product/fixture/CI timeout is introduced. A module-import effect
test verifies no extra selected import occurs in the orchestrator. Existing
cross-selector mutation/source-drift tests still cover independent execution.

On fixture timeout the test runner sends SIGTERM and waits for the collector's
existing supervisor cleanup before removing files; the timeout still fails.
The exact final source/test bytes pass 111 focused/impact methods (58 collector
+53 adjacent cases), zero failures/errors/skips, Python 3.14 (patch version not retained) in 93.050 seconds.
No full local kernel suite was repeated. Accepted P13 Rev4/VF Rev11 and all native,
verify_only and full-v1 exclusions are unchanged. Final-head CI, actual hosted
artifact consumption, independent reviews, existing scoped CODEOWNER approval,
protected merge and actual-main checks remain required.


## Environment label correction -- 2026-10-21

The three local records above previously named Python 3.14.4 without a captured
patch-version field. That precision is withdrawn; the commands selected Python
3.14 and retain their original source hashes, test counts, durations and logs.
No local test was replayed merely to reconstruct missing historical metadata.

The actual hosted reports for head 2b8fd4f in
[run 39499391626](https://github.com/openboa-ai/hydra/actions/runs/39499391626)
separately record Python 3.11.17 and 3.14.2. All four required jobs passed, each
Python job collected 1,245 tests with 1,237 passing and eight explicit skips, and
the two selected-source reports each contain two cases and five methods. Their
checked commit has the exact head tree and expected base/head parents. Those are
observations of that head, not evidence for a subsequent revision.

This correction changes only documentation. Product/test blobs and accepted
specification pins are unchanged. Final-head CI/reviews, the existing scoped
CODEOWNER approval, protected merge and main checks remain separate gates.


## Selector shutdown interruption -- 2026-10-21

Review found a valid late-interruption gap: after the private outcome packet was
written, a selected atexit callback could deliver SIGTERM, Python could ignore the
handler's KeyboardInterrupt during shutdown, and the selector could still exit zero.
The test body having passed did not establish successful process completion.

The child now marks its shutdown boundary before emitting the packet. Its pristine
signal handler terminates late SIGTERM/SIGINT with a nonzero child status instead
of raising an exception Python can ignore. The clean supervisor waits for and
checks that status before accepting the packet, classifies the interruption and
does not export PASS. Ordinary shutdown callbacks and output privacy are retained.
The parent publication commit point is unchanged; this creates no hostile-program
authentication claim and does not move selected code into a sandbox.

The unchanged published parent cc4b86a reproduced four assertion failures: SIGTERM
and SIGINT in both ordinary fork and forced fresh-exec profiles. The same regression
assertions pass in the correction. Six focused interruption/shutdown/publication
methods pass with zero failures/errors/skips on Python 3.14.2 in 5.573 seconds.
They preserve exactly one completed method effect, prevent the next selector effect
and reject a PASS export after shutdown interruption. An initial misspelled test
class was a selection setup error, separately retained; it was corrected before
the successful run. No full local kernel or unrelated test bundle was repeated.

Accepted P13 Rev4/VF Rev11, selected-source limits and native/full-v1 exclusions
are unchanged. Final-head CI, actual hosted reports, code/security review, the
existing scoped CODEOWNER approval, protected merge and main checks remain required.


## Normal shutdown shares the worker deadline -- 2026-10-21

Review found that the packet pipe closes before normal interpreter cleanup ends.
The supervisor then used a separate two-second wait even though its existing
worker deadline had time remaining. A legitimate three-second atexit cleanup was
terminated and incorrectly prevented an otherwise valid export.

After EOF the supervisor now requires positive remaining time and waits only
within that same original worker deadline. The 600-second limit, input bounds,
signal handling, cleanup-on-timeout and publication commit point are unchanged.
No timeout or accepted maximum was increased.

The unchanged published parent 936beb1 reproduced two actual assertion failures,
one for ordinary fork and one for forced fresh-exec. Both now finish their real
three-second cleanup, preserve exactly one method/cleanup/control effect and pass
read-only report validation. Seven focused shutdown/interruption/publication
methods pass with zero failures/errors/skips on Python 3.14.2 in 12.846 seconds.
No full local kernel or unrelated test bundle was repeated. The prior head passed
all four jobs in [run 39511106111](https://github.com/openboa-ai/hydra/actions/runs/39511106111);
that run does not qualify this later correction.

P13 Rev4/VF Rev11 and native/full-v1 exclusions are unchanged. Final-head CI and
actual artifacts, independent code/security review, the existing scoped CODEOWNER
approval, protected merge and main checks remain required.
