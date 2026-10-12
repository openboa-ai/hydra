# Mac control verification

Verified on 2026-10-12 against [specification revision 5](spec.md), based on
`b59616b3e6210661aa62b30496efc6bed97c6826`. Related work: [Issue #3](https://github.com/openboa-ai/hydra/issues/3).

## Result and qualification boundary

The shared admission controls and packaged debug application passed the checks
below on macOS with Python 3.14.2. The source was copied into an isolated validation
checkout; all 18 changed Python/test files and 29 app files matched the final
source by SHA-256. This is source and isolated-fixture evidence. GitHub candidate
checks, protected review/merge, release signing and installed operation remain
separate requirements.

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
qualified on macOS and must be checked by the repository's Linux CI.

## Requirement-linked evidence

| Acceptance | Evidence and limits |
| --- | --- |
| A1: safe persistent settings | `test_operations.py` exercises default denial, damaged/duplicate settings, unsafe paths, atomic updates, concurrent readers/writers, process persistence and project overrides. |
| A2: shared admission and publication barrier | `test_operation_integration.py` checks that existing controllers and runners observe changed modes, isolate projects, and prevent publication after Pause. Explicit Pause through CLI `run`/`serve` and a long-lived real MCP server are not separately established by these receipts; MCP protocol tests use a fixture controller. |
| A3: races and durable ownership | `test_operation_boundary.py` and `test_restart_ownership.py` use real isolated processes for admission races, cancellation, failed cleanup and restart holds. A protocol fixture on macOS does not establish Linux kernel process containment. |
| A4: exact bounded cleanup | Integration tests cover matching stopped cleanup, never-dispatched ownership tickets, stale identities, remote intents, and preservation of unknown execution. Native interruption and schedule inventory remain unqualified. |
| A5: app and subprocess boundary | Packaged-app observations are recorded below. Rust tests reject malformed/duplicate protocol output, excessive output, unsafe targets, invalid links and stale Quit evidence; they bound owned-child timeouts and fence queued requests during Quit. An installed-runtime probe confirmed that hostile cwd/PYTHONPATH modules did not replace the installed package. Packaged-UI malformed-output injection is not recorded. |
| A6: canonical expression | Canonical alias chains, resolved CSS values and bundled font hashes were checked. Actual light/dark screens were inspected and shared before PR publication. Complete keyboard traversal is not recorded. |
| A7: regression and independent review | The checks above passed. Independent specification, Python and app/security reviews accepted their final scoped revisions. GitHub reviews and checks for the eventual PR head remain required. |

## Packaged application observations

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

The final app bridge source was
`apps/mac/src-tauri/src/main.rs`, SHA-256
`95ade1289dd1e910da06adaccf3351a6ffe421dd06854bded055dfb9a4e469f0`.

## Remaining delivery and operating evidence

- Complete the separately identified ingress and packaged-UI acceptance gaps
  before claiming every A1–A7 scenario is qualified.
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
