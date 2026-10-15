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
