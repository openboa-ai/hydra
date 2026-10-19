# Mac control verification

Initial verification on 2026-10-12 against [specification revision 5](spec.md), based on
`b59616b3e6210661aa62b30496efc6bed97c6826`. Related work: [Issue #3](https://github.com/openboa-ai/hydra/issues/3).
Later candidate evidence is recorded separately below.

## Result and qualification boundary

The initial shared admission controls and packaged debug application passed the
checks below on macOS with Python 3.14.2. The source was copied into an isolated
validation checkout; all 18 changed Python/test files and 29 app files matched
that validation snapshot by SHA-256. Source, isolated-fixture operation, GitHub
candidate checks, protected review/merge, release signing and installed operation
remain separate evidence.

| Check | Observed result |
| --- | --- |
| Python regression suite | 759 tests collected; successful, with 27 skipped; 247.191 seconds |
| Corrected CLI fixture regressions | 97 tests collected; successful, with 1 skipped |
| Installed optional MCP 2.3.0 | 2 protocol tests passed |
| Installed optional Codex 0.162.0 | 55 adapter tests passed; no model calls |
| Rust bridge, locked dependencies | 11 tests passed |
| TypeScript and frontend | Type check, Vite build and 9 tests passed |
| Theme and fonts | Canonical token comparison passed; bundled font integrity and alias/CSS checks passed |
| macOS bundle | Debug `Hydra.app` built and launched; not notarized |

Optional dependency checks were rerun after installing their pinned packages in
the isolated environment. They supplement the full-suite result; they do not
change its recorded skip count. Linux-only subreaper and `/proc` behavior was not
qualified by this macOS run; later Linux CI is recorded separately below.

## Later candidate evidence

The 2026-10-14 [operating-continuity validation](../operating-continuity/verification.md)
passed 23 frontend tests, TypeScript/Vite build, theme checks and 15 locked Rust
tests. Its debug app used a separately installed validation wheel. Actual controls
confirmed v2 runtime identity, project restrictions surviving global Resume, and
held Quit while execution and coverage remained unknown.

On 2026-10-15, [Repository CI run 38690740192](https://github.com/openboa-ai/hydra/actions/runs/38690740192)
passed for source head `52f2319ef5a74721ca0049146803cf70113b90ea`.
The Linux Python 3.11 and 3.14.2 jobs each ran 827 tests with eight skipped.
Repository hygiene, workflow linting, and trusted history/source secret scans
passed; both secret-scan stages reported zero findings under their existing rules.
Separately, all 13 local asset-hygiene regression tests passed without skips, and
the actual whitespace check and workflow linter passed on the complete 143-file
publishable candidate. These results apply to that candidate; later revisions
still require their own final-head checks and reviews.

## Requirement-linked evidence

| Acceptance | Evidence and limits |
| --- | --- |
| A1: safe persistent settings | `test_operations.py` exercises default denial, damaged/duplicate settings, unsafe paths, atomic updates, concurrent readers/writers, process persistence and project overrides. |
| A2: shared admission and publication barrier | `test_operation_integration.py` checks changed modes, project isolation and publication barriers. `test_cli.py` now explicitly checks paused `run` and `serve` entry before providers or admission. `test_mcp.py` keeps one real SDK server and `NativeController` alive across an external Pause, blocks new work through all mutating routes and allows exact stopped cleanup. GitHub/workspace dependencies remain fixtures; this is not a production MCP qualification. These tests are included in the later CI run above. |
| A3: races and durable ownership | `test_operation_boundary.py` and `test_restart_ownership.py` use real isolated processes for admission races, cancellation, failed cleanup and restart holds. Process evidence remains platform-scoped: the initial macOS results and later Linux CI results are separate observations. |
| A4: exact bounded cleanup | Integration tests cover matching stopped cleanup, never-dispatched ownership tickets, stale identities, remote intents, and preservation of unknown execution. Native interruption and schedule inventory remain unqualified. |
| A5: app and subprocess boundary | Packaged-app observations are recorded below, including malformed output and an uncertain mutation followed by state readback. Rust tests reject malformed/duplicate protocol output, excessive output, unsafe targets, invalid links and stale Quit evidence; they bound owned-child timeouts and fence queued requests during Quit. An installed-runtime probe confirmed that hostile cwd/PYTHONPATH modules did not replace the installed package. |
| A6: canonical expression | Canonical alias chains, resolved CSS values and bundled font hashes were checked. Actual light/dark screens were inspected and shared before PR publication. The 2026-10-15 packaged-app observation traversed all 22 available keyboard targets and verified focus recovery after automatic polling and preservation of a later user focus. |
| A7: regression and independent review | The checks above passed. Independent specification, Python and app/security reviews accepted their final scoped revisions. GitHub reviews and checks for the eventual PR head remain required. |

## Initial packaged application observations (2026-10-12)

An isolated installation of the real Python core was exercised through actual UI
buttons. Global Start, Pause, Resume and Stop changed the shared store. Project
Pause/Stop remained in effect across global Resume; project Start/Resume were
disabled while the host was paused. Individual project Resume/Start also worked.

Stop and Quit persisted global Stop but displayed a held Quit while execution was
unknown and schedule coverage unverified. Closing the window retained the process
and settings. Reopening the application restored the existing window, process and
stopped revision. The final reopen behavior was tested after the macOS Reopen
handler was added; it does not create another window or runtime.

A **separate simulated-observation fixture** exercised both Quit branches:
unresolved native execution kept the app alive with an unknown stopping state;
positively empty ownership and confirmed empty inventory allowed normal exit with
code 0. These simulated observations are not production native-control evidence.

The app bridge source for this initial observation was
`apps/mac/src-tauri/src/main.rs`, SHA-256
`95ade1289dd1e910da06adaccf3351a6ffe421dd06854bded055dfb9a4e469f0`.
This historical hash does not identify the later v2 application snapshot.

## Packaged-UI acceptance (2026-10-15)

Keyboard inspection found that automatic status polling temporarily disabled the
focused local Refresh button without restoring it. The correction remembers only
the refresh button that the request disables. Later keyboard, pointer, focus or
window-blur activity cancels that restoration, so an old request cannot reclaim
focus after a newer interaction. Independent static review accepted the correction.

All 29 application source files matched a new isolated build snapshot. Its 23
frontend tests, TypeScript/Vite build, canonical theme check and debug app packaging
passed. Rust source did not change; the 15 locked Rust tests above are the retained
bridge evidence. The new packaged executable had SHA-256
`340c30607ab0123d7969cf336dbd7605808feb8a28e380380e36a3e3d442b111`.

That executable was exercised with a disposable synthetic runtime. Only the test
copy's bundle identity/name changed to isolate it from an already running app;
the executable and icon bytes were unchanged. The observations were:

- Tab reached all 22 available targets: theme, host controls, refresh, record links,
  project controls, project chat, runtime identity, local refresh and Quit.
  Shift-Tab reversed direction; Space refreshed status and Return invoked Pause.
  Visible focus was inspected. Example record links were focused but not opened.
- Focus on local Refresh survived automatic polling. With a two-second synthetic
  status delay, moving to another button during the request retained the new focus
  after completion.
- Unsupported protocol output after a valid observation cleared the cached host
  and projects and disabled controls. Malformed output without a validated snapshot
  displayed a bounded generic error and kept controls disabled; its synthetic raw
  sentinel was absent from the accessibility text and visible UI.
- A Pause applied by the fixture followed by malformed output showed an uncertain
  result, a reconciled blocked gate, and unknown execution. The invocation log
  recorded one Pause followed by a status readback, with no mutation replay.

Running-screen evidence was shared before publication. These observations close
the pending packaged-UI cases; they do not qualify production native execution,
schedule coverage or external record destinations. Harness teardown is not product
Quit evidence. Private fixture paths, raw logs and local host configuration are not
part of the public candidate.

## Provider review corrections (2026-10-15)

Both provider reviews completed for head
`e3358b6537c5fe3a9ae5a4312a007c3c8c84a0b5`; its
[three CI jobs passed](https://github.com/openboa-ai/hydra/actions/runs/38732616915).
Code Review identified four corrections, implemented within the existing contract:

- Race tests now synchronize with the helper's actual native-spawn boundary before
  starting the short admission deadline. They inject startup delay and observe
  the real termination request. The child-before-Pause-acknowledgement assertion
  remains, and failed tests wait for owned worker cleanup.
- An active-work interruption probe defers only transient control-lock contention.
  Admission and side-effect guards still reject busy state. Actual target or host
  Pause/Stop, invalid state, signals and deadlines still interrupt work.
- A remote refresh collects local workers, current coordinator ownership and
  settings after remote reads. Settings are read last; the local observation uses
  its start time, so a slow probe cannot make earlier evidence appear newer.
  Native records bind only to the current exact owner; private candidates are not
  returned in the public response.
- CLI-generated admission waits, final stopped results and operation denials use
  the shared progress classifier while preserving unknown execution metadata.

An isolated Python 3.14.2 full run collected 840 tests with 20 skips. Two subtests
failed because an existing CLI result expectation omitted the new additive hint.
Only that expectation was corrected; all ten tests in its file then passed.
Production source did not change after the full run, and all 143 source/validation
files matched after the focused correction. This is a full run plus a focused
expectation correction, not a second successful local full-suite run. The new
race, real thread/process lock-contention, refresh-ordering and CLI regression
tests passed in the full run. Independent static review accepted all nine code/test
files. The subsequent PR head still requires fresh CI and provider review.

Application source and the packaged-UI evidence above are unchanged. These Python
checks do not replace an installed runtime or qualify production operation.

## Observation feedback and app CI corrections (2026-10-15)

Head `be8c6b82c1867616865c61ce32e630d83b0940ed` passed all
[three CI jobs](https://github.com/openboa-ai/hydra/actions/runs/38736830352).
Python 3.11 and 3.14.2 each ran 840 tests with eight skips; trusted history and
source secret scans reported zero leaks. Both provider reviews completed. Code
Review then identified two observation-feedback defects and missing app CI coverage.

Observation failures now check both the runtime generation and accepted request
sequence. An older failed refresh cannot cover a newer successful control response.
Successful response revision, identity and remote-cache rules are unchanged.
An accepted automatic refresh clears a recovered observation error, while pending
operations, uncertain mutation results and held Quit feedback remain visible.
A deliberate refresh can reconcile those operation messages after the request ends.

The actual feedback model used by the renderer has seven new behavioral regressions.
All 30 frontend tests, TypeScript/Vite build, published theme verification and debug
app packaging passed against the same 29-file application snapshot. Independent
static review accepted the three changed application files. The packaged executable
has SHA-256 `d0eb2a17955ddad5107108d2ef0f725692a21a2b9f4a2666fb65a3439b96203d`.

The packaged app was exercised with an isolated synthetic runtime:

- A GitHub refresh began before Pause and was held outside the fixture lock.
  Pause applied revision 11. Releasing the older invalid response afterwards left
  the applied Pause notice and blocked gate intact, with only one mutation logged.
- Automatic invalid responses displayed a bounded error. Returning the fixture to
  valid responses cleared that error on the next successful automatic poll without
  clicking Refresh, while retaining the paused gate and applied notice.
- Keyboard focus on local Refresh survived repeated automatic polls. Moving focus
  to another button during a two-second refresh retained the newer focus after the
  response arrived.

Relevant running screens were shared before publication. Fixture errors and
recoveries do not qualify production native execution or schedule coverage.

The added macOS CI job installs locked frontend dependencies, runs frontend tests,
theme verification and the TypeScript/Vite build, then tests the locked Rust bridge
and builds it with embedded frontend assets. Node and Rust versions and action
revisions are pinned. Existing kernel and hygiene jobs, credentials handling and
scanner controls are unchanged. Independent workflow review and pinned actionlint
passed; the new hosted macOS job still needs actual current-head CI evidence.

## Completed-execution checkpoint recovery (2026-10-15)

Head `64526d71e03f315744cd96842ffc8671bec3631e` passed all
[four CI jobs](https://github.com/openboa-ai/hydra/actions/runs/38741154779).
Python 3.11 and 3.14.2 each ran 840 tests with eight skips. The macOS job passed
30 frontend tests, theme verification, TypeScript/Vite build, 15 locked Rust tests
and the embedded-frontend Rust build. Repository hygiene and trusted history/source
secret scans passed. Both provider reviews completed; Code Review identified a
remaining race when control-lock contention interrupted a completed model's
checkpoint.

The correction retains exact completion evidence inside its existing Runner.
Checkpoint admission retries asynchronously, at most six attempts with 0.775
seconds of total retry delay. Longer contention or cancellation retains the
matching repository, Issue, attempt and contract identity for cleanup re-entry.
Re-entry only settles that existing checkpoint; it does not repeat model work or
publication. Changed durable identity or remote intent is preserved.

Once a checkpoint effect starts, an uncertain response permits read-back only.
The exact attempted record is retained before writing and compared with observed
progress; no uncertain effect is retransmitted. Intermediate specification records
retain the completion proof until settlement or reconciliation. Confirmed durable
progress can then follow the normal guarded lifecycle.

CLI run and foreground shutdown drain retained completions while coordinator
ownership remains held. The drain shares a 0.8-second retry-delay budget; admitted
checkpoint and API calls retain their existing bounds. Server cycles drain before
filtering paused projects and exclude those targets from normal work in that cycle.
An exhausted or unconfirmed exit drain reports pending cleanup and unknown state.
The proof is process-local: it creates no database or recovery file and grants no
restart or handover authority.

Independent static review accepted the five changed Python/test files. An isolated
Python 3.14.2 full suite ran 852 tests successfully with 20 skips in 260.437 seconds.
The added cases cover real exclusive-lock contention, cancellation, prolonged
contention, unrelated and concurrent targets, changed identity or remote intent,
uncertain checkpoint writes, intermediate specification writes, paused cycles and
CLI run/serve exit paths. All 143 source, validation and saved-snapshot files matched
before and after the run. Application and workflow files are unchanged from the
head above. The correction still requires its own current-head CI and provider
reviews before protected delivery.

## Cold-start controls and admission-boundary corrections (2026-10-15)

Head `1225d26d768e291c6cef2a15097b22151c18f837` passed all
[four CI jobs](https://github.com/openboa-ai/hydra/actions/runs/38747184564).
Both Python jobs ran 852 tests with eight skips. The macOS job passed 30 frontend
tests, 15 locked Rust tests, theme/type checks and both builds. Trusted history
and source secret scans reported zero findings. Both provider reviews completed;
Code Review identified four further corrections:

- Global Pause/Stop remain available before the first validated snapshot. Pending
  requests still block every control; enabling and project actions still require
  valid observations. The empty Projects message now names project controls.
- CLI `run` checks its repository's gate before provider/workspace setup and again
  while acquiring coordinator admission. `serve` retains its global admission and
  per-project isolation. Existing cleanup drains are unchanged.
- Local checkpoint and specification-read failures before a remote write retain
  completion proof and can retry the idempotent local checkpoint. The first remote
  write still records its exact attempted values before dispatch, so uncertain
  remote effects remain read-back only.
- Installed configuration loading walks every ancestor with no-follow directory
  descriptors and checks the complete directory identity chain and final file
  binding before and after reading. Unsafe ownership/modes, symlinks and changed
  paths are rejected without exposing configuration contents or private paths.

Independent static reviews accepted all nine changed source/test files. The
isolated Python 3.14.2 suite passed 863 tests with 20 skips in 262.157 seconds.
All 143 source, validation and saved-snapshot files matched. New cases include
project preflight and admission races, local checkpoint failures before and after
commit, pre-write specification reads, and configuration ancestor/file replacement.

The same 29-file app snapshot passed 32 frontend tests, TypeScript/Vite build,
theme verification and debug packaging. The packaged executable SHA-256 is
`ccc495d8325550ace9e7b8f85aff645eb5f39447ee65e88549e3f7a0e1e31772`.
In two separate cold-launch synthetic fixtures, every initial response was invalid.
The actual app displayed enabled global Pause/Stop, disabled Start/Resume and no
project controls. One fixture received exactly one Pause and the other exactly one
Stop, both targeting all projects before any valid snapshot. Invalid mutation
responses displayed uncertainty. After restoring valid responses and explicitly
refreshing, each app displayed revision 11 and the matching paused/stopped blocked
gate; execution and coverage remained unknown/unverified. Relevant screens were
shared before publication. Both owned fixture processes were stopped by the
harness; this is not product Quit or production runtime evidence.

These local results do not replace the correction's own current-head CI, provider
reviews or protected delivery gates. No production settings or schedules changed.

## Native replan recovery and settings observation corrections (2026-10-16)

Head `45259b41c90a2b1056c47d4d40d90bd31f582411` passed all
[four CI jobs](https://github.com/openboa-ai/hydra/actions/runs/38753335940).
Both Python jobs ran 863 tests with eight skips. The macOS job passed 32 frontend
tests, 15 locked Rust tests, theme/type checks and both builds. Trusted history
and source secret scans reported zero findings. Both provider reviews completed;
Code Review identified two further corrections:

- Native specification recovery persists the terminal `replan_required` reason
  and `diagnose` action before read-back and ticket retirement. An unanswered
  product decision retains precedence. Fresh-controller tests cover durable
  status, refusal of unauthorized/stale resolution markers, and exact authorized
  resolution returning to specification review with a new attempt.
- A later observation request can reconcile a lower settings revision or recovery
  from an unreadable state. Entering unreadable settings, accepting a reset, or
  recovering starts a response boundary: already-issued successes cannot restore
  the previous gate. Runtime identity and operation-error handling are preserved,
  so pending action uncertainty remains visible. Same-runtime remote work retains
  its original observation time. Standalone comparisons do not infer recovery
  from a timestamp alone; ticketed recovery also retains the timestamp check.

Independent static review accepted the four changed code/test files. The isolated
Python 3.14.2 full suite passed 865 tests with 20 skips in 266.171 seconds. All 143
source, validation and saved-snapshot files matched before and after the run.

The same 29-file app snapshot passed 39 frontend tests, TypeScript/Vite build,
theme verification and debug packaging. The packaged executable SHA-256 is
`adb21709f8bade1fcf25245c74cffdde1087840c9f93c29b5d71fc0f5e818338`.
In the actual packaged app, an isolated synthetic runtime first reported revision
10/running. Changing only its synthetic response state to revision 0/stopped was
reflected by automatic local polling as zero allowed projects and two blocked
projects. After restoring the revision-10 baseline, a revision-3/paused response
was also reflected automatically. Neither transition required an app restart or
manual refresh. One fixture remote refresh preceded these transitions; all 33
runtime invocations were status reads, with no control mutations.

Relevant running screens, including the final revision and unknown execution /
unverified coverage, were shared before publication. Late-response rejection and
cache timestamp preservation are model-test evidence, not packaged UI race
observations. The fixture injected response-state changes; it did not delete or
restore installed settings. The owned process was stopped by its harness, which
does not qualify product Quit or production control.

These corrections still require their own current-head CI and provider reviews
before protected delivery. No production settings, schedules or runtime changed.

## Cumulative remote observation budgets (2026-10-19)

Specification revision 6 adds transient cumulative time/request limits and fair
repository shares within the existing read-only refresh boundary. Its SHA-256 is
`c167e8b3ab9e87b3e4b658a2a1843a4b0f225bcec4fd6af66e494675aafc1974`.
Before implementation, the new budget suite had nine errors for the absent budget
API and one passing compatibility case. The control suite reproduced an actual
failure: a two-request limit still allowed 40 reads before local probes.

After implementation, local Python 3.12 checks passed:

| Check | Result |
| --- | --- |
| `test_github_read_budget.py` | 10 passed, including a real sleeping child terminated by a 50 ms budget and auth/identity/API timeout values of 10/9/8 seconds under an advancing clock |
| `test_control.py` | 42 passed, including time/request exhaustion preserving authenticated prefixes, a reserved later repository, 150 ordinary Issues plus authenticated work, delayed successful multi-repository reads and latest admission after exhaustion |
| `test_github*.py` | 47 passed, including the 10 budget tests; existing auth and write uncertainty behavior preserved |
| Complete Python discovery | 941 tests collected, successful with 25 skipped, 251.527 seconds |

The complete suite ran in a development checkout containing other pending
changes. This is development regression evidence, not isolated final-PR evidence
or current-head CI. The budget tests used fixture transports/subprocesses without
GitHub network effects. No packaged-app, installed runtime or production-control
qualification is claimed by this correction. Final isolated candidate checks,
running-screen evidence, provider reviews and protected delivery remain required.

## Remaining delivery and operating evidence

- Require current-head GitHub CI and code/security review before protected
  delivery. A passing local suite or draft PR is not merge evidence.
- Keep Issue #3 open for its broader operating acceptance; this change does not
  complete native question/resumption or unattended-operation qualification.
- Production desktop turn control and installed schedule coverage are not
  qualified. The implementation therefore preserves unknown execution and holds
  Quit when positive termination evidence is unavailable.
- No product schedule was resumed, active MCP process replaced, production runtime
  installed, protected policy changed, or signing/notarization completed by these
  checks.


## Isolated PR8 correction candidate — 2026-10-19

The published parent was `0c82a34a23eedff4d6ea540af74218357ae3c1bc`. An isolated
candidate contained only the three outstanding progress/control corrections,
the cumulative remote-read budget, their tests and this contract/evidence update.
It excluded the separate v1 design and typed admission candidates.

- The exact isolated candidate passed 106 tests selected by `test_control.py`,
  `test_progress_hints.py` and `test_github*.py`, with no skips or failures.
- Its unchanged app sources passed all 39 frontend tests, theme verification,
  TypeScript/Vite build and debug macOS app packaging.
- A separate installed fixture used the actual control core and packaged app,
  with simulated GitHub transport and a deliberately reduced 14-request budget.
  After Refresh GitHub, the first repository exhausted its share, but its
  authenticated work prefix and the second repository's work both remained
  visible. Local polling retained both work entries and the first project's
  explicit Pause. The screen showed unavailable remote evidence, unknown active
  execution and unverified schedule coverage; `can_quit` remained false.
- The running screen was shared before publication. The exact fixture process
  was then terminated by the test harness. This is not successful product Quit,
  live GitHub observation, native-turn control or production installation evidence.
- Independent scoped code/security review found no remaining material defect in
  the read-budget repair. These observations do not close the separate typed
  admission work or replace final-head CI, human code-owner review, protected
  merge and post-merge checks.

The 941-test mixed-checkout run above remains separate evidence; it is not
reported as this isolated candidate's full-suite result.
