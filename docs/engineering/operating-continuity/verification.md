# Operating continuity verification

Specification revision 1 was independently accepted at SHA-256
`5249677864a945de6e1f2581afffc2f661b16adb3aca2351ffb92be6744d6a25`.
This record concerns a source candidate; installation and protected delivery are
separate evidence.

## Python behavior

An isolated source snapshot was tested with Python 3.14.2, MCP 2.3.0 and Codex
0.162.0, without model calls. Full discovery ran 814 tests. Twenty tests were
skipped: 18 require Linux process semantics and two require non-UTF8 filenames
unsupported by the validation filesystem.

The initial run exposed 11 failure records in seven existing test methods: exact
dictionary expectations lacked the new additive hint, terminal failures expected
the old polling reason, or an in-progress fixture retained a success conclusion.
Six test files were corrected to the reviewed contract. All 67 tests in those
affected files then passed. Production source did not change after the full run;
the final source and validation manifests matched for all 101 Python, test and
supporting files. This is a full run plus a focused correction run, not a second
full-suite run.

Coverage includes read-only repeated hints; exact decision resumption; legacy and
new native pending ownership; trusted latest push CI states; first and second
post-merge observation failures; preserved close intents during provider outages;
and unchanged admission-denial behavior. Identity checks cover source bounds and
races, unsafe filesystem entries, startup capture, configuration isolation, and
CLI/MCP/control agreement. Control tests bind links to their own Issue and PR.

## Mac application

The final application snapshot passed 23 frontend tests, TypeScript/Vite build,
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

The existing Draft PR's protected hygiene check has a separate binary-font
whitespace classification blocker. Its trusted secret-scan stage did not run on
that earlier head. This change does not weaken the workflow or claim CI, merge,
installation or unattended execution success from local checks.
