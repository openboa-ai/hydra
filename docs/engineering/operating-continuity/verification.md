# Operating continuity verification

Specification revision 1 was independently accepted at SHA-256
`5249677864a945de6e1f2581afffc2f661b16adb3aca2351ffb92be6744d6a25`.
This record concerns a source candidate; installation and protected delivery are
separate evidence.

## Python behavior

On 2026-10-14, an isolated source snapshot was tested with Python 3.14.2, MCP
2.3.0 and Codex 0.162.0, without model calls. Full discovery ran 814 tests.
Twenty tests were skipped: 18 require Linux process semantics and two require non-UTF8 filenames
unsupported by the validation filesystem.

The initial run exposed 11 failure records in seven existing test methods: exact
dictionary expectations lacked the new additive hint, terminal failures expected
the old polling reason, or an in-progress fixture retained a success conclusion.
Six test files were corrected to the reviewed contract. All 67 tests in those
affected files then passed. Production source did not change after the full run;
the final source and validation manifests matched for all 101 Python, test and
supporting files. That local evidence is a full run plus a focused correction
run, not a second local full-suite run.

On 2026-10-15, [Repository CI run 38690740192](https://github.com/openboa-ai/hydra/actions/runs/38690740192)
passed for source head `52f2319ef5a74721ca0049146803cf70113b90ea`.
The Linux Python 3.11 and 3.14.2 jobs each ran 827 tests with eight skipped.
Repository hygiene, workflow linting, and trusted history/source secret scans
passed; both secret-scan stages reported zero findings under unchanged rules.
All 13 local asset-hygiene regression tests also passed without skips, and the
actual whitespace check and workflow linter passed on the complete 143-file
publishable candidate. This resolves the earlier candidate's binary whitespace
blocker; it does not certify later revisions or replace protected approval.

Coverage includes read-only repeated hints; exact decision resumption; legacy and
new native pending ownership; trusted latest push CI states; first and second
post-merge observation failures; preserved close intents during provider outages;
and unchanged admission-denial behavior. Identity checks cover source bounds and
races, unsafe filesystem entries, startup capture, configuration isolation, and
CLI/MCP/control agreement. Control tests bind links to their own Issue and PR.
Explicit CLI `run`/`serve` Pause tests and a real SDK server using `NativeController`
cover admission denial after a control update. The latter retains the same server
across the update and checks exact stopped cleanup; its GitHub/workspace dependencies
are fixtures, not a production installation.

## Mac application

The 2026-10-14 application snapshot passed 23 frontend tests, TypeScript/Vite build,
the theme mapping checks, and 15 locked Rust tests. A debug macOS application
bundle was built from that snapshot.

The packaged app ran against a separately installed validation wheel and isolated
example repositories. Its v2 runtime identity matched the isolated CLI observation.
Actual button operations confirmed host Start, an individual Pause and Stop, host
Pause, and global Resume preserving both restrictions with zero allowed and two
blocked projects. The app continued to show execution as unknown. Stop and Quit
applied host Stop and visibly held termination because execution/coverage was
unconfirmed. Running-screen evidence was shared before publication; the owned
fixture app was then stopped by the validation harness. That teardown is not a
successful product Quit or native-turn interruption.

On 2026-10-15, packaged keyboard inspection found and corrected local Refresh
focus loss during automatic polling. A later user interaction cancels the saved
focus restoration. Independent static review accepted the scoped frontend fix.
All 29 app source files matched the rebuilt snapshot; its 23 frontend tests,
TypeScript/Vite build, theme check and debug app packaging passed. Rust source did
not change, so the earlier 15-test result remains the bridge evidence.

The rebuilt app, with a disposable synthetic runtime, passed traversal of all 22
available keyboard targets, reverse traversal, Space refresh and Return Pause.
Actual observations confirmed focus recovery after automatic polling and retention
of a later user focus during a two-second delayed response. Unsupported protocol
output cleared cached controls, and malformed output exposed only a generic error.
An applied Pause with malformed output produced one mutation followed by a status
readback, an uncertainty warning and a reconciled blocked gate; it was not replayed.
The [Mac control verification](../mac-control/verification.md) records the exact
packaged executable and evidence limits. Screens were shared before publication;
these synthetic observations do not establish production runtime operation.

## Provider review corrections (2026-10-15)

The next reviewed head, `e3358b6537c5fe3a9ae5a4312a007c3c8c84a0b5`, passed
[all three CI jobs](https://github.com/openboa-ai/hydra/actions/runs/38732616915).
Its completed Code Review identified four issues. The corrections synchronize
race tests with real helper readiness, defer transient lock contention only for
active-work interruption, recapture local facts after remote refresh, and apply
the shared progress classifier to all CLI-generated waits/stops/denials. New work
and side-effect guards remain fail-closed; native execution and coverage can still
be unknown.

The corrected Python source was exercised in an isolated full run of 840 tests
with 20 skips. Two run/serve subtests had stale exact-result expectations for the
new progress hint. That test-only expectation was corrected, and all ten tests in
the affected file passed. Production source remained unchanged between these runs;
the final 143-file source and validation manifests matched. This is full discovery
plus a focused correction, not a second successful local full run. The added
regressions passed, and independent static review accepted the nine code/test files.
The [Mac control verification](../mac-control/verification.md) records their scope.
Fresh-head CI and provider reviews are still required after publication.

## Decision-only schedule observation

On 2026-10-14, one known goal-specific heartbeat waiting only for a user answer
was actually changed to `PAUSED`. Read-back confirmed that state and preservation
of its existing configuration fields and question/task references. This is evidence
of that bounded schedule transition, not interruption of its current turn,
installation of the source skill's wake policy, automatic cross-task wake support,
or qualification of all schedules.

## Independent review

Scoped code/security reviews accepted the Python identity/integration, core state
classification and native ownership changes. Reviews also accepted the Rust and
frontend changes after correcting incomplete runtime identity, stale error
responses, unknown admission, and decision-context wording. Reviews are static
evidence and do not replace execution tests or protected provider review.

## Operational limits

Native desktop start/interrupt, schedule coverage and automatic session creation
or retirement remain unqualified. Source skill changes do not install a wake
policy. Unknown ownership or coverage still holds Quit. Admission Resume does not
activate a paused schedule. Runtime digests are observation metadata, not an
attestation of loaded code or execution ownership.

The successful CI run above applies only to its recorded source head. Any later
revision still requires current-head CI and code/security review. Protected merge
also requires the configured human code-owner approval; green CI and agent reviews
cannot substitute for it. Merge, production installation, signing/notarization and
unattended operation are not established by these checks.
