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
