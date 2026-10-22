# P17 fresh-binding increment: verification

Scope: P17 revision 2 and PC revision 1, with the maintained CP revision 10
admission-default representation. The first increment implements the read and
effect-guard prerequisites for the subsequent configuration writer.

## Behavior

- Profile 1 accepts a bounded closed set of connection declarations and zero
  registered projects. The loader retains its actual source path privately.
- Version-2 admission names one fixed trusted configuration. Every effect checks
  current safe source, loaded configuration, target registration and desired state.
  An arg-only or differently bound writer cannot dispatch an effect.
- Missing project overrides default to stopped. Explicit current Resume can
  progress; a pending disconnect cannot Resume. Explicit Stop preserves the host
  mode and the original connection intent.
- Actual command observations expose the admission default without exposing the
  configuration path. A bad or missing binding makes effective admission
  unavailable in the actual read producer.
- Legacy configuration and mode inheritance remain unchanged. Legacy schema-2
  control operations reject a new connection profile before any mutation.

## Independent deterministic controls

The initial ten-case core/CLI oracle set runs on immutable main with nine purpose
failures, one preserved legacy success and zero errors/skips, then passes on the
first source candidate. The review follow-up retains its outcome assertions and
explicitly declares the independent connected project in two positive fixtures;
missing declarations now have separate negative cases. Two additional legacy-control cases
reproduce unsupported status/mutation behavior before correction and pass
afterward, with no mode change. Two actual-read cases reproduce false current
admission under a different/missing binding and pass after the producer fence.

The shared wire matrix contains nine independent cases. The actual Python read
producer supplies the same bytes to Python, Rust and TypeScript. It covers the
stopped default, explicit overrides, host Pause, unchanged legacy inheritance,
contradictory permission claims, malformed defaults and rejected private fields.
Both original consumers reject the three new valid source cases; the unchanged
matrix passes after the matching parser/causality changes.

The maintained CP source mapping makes six whole-document fixture references
stale. A single reference check rejects all six original references, including the
five declared revisions. Only the exact contract digest and a revision where
already present are refreshed; case IDs, inputs, expected outcomes, metadata shape
and validators remain unchanged. The same reference check then passes and guards
all declared CP references together.

Final local impact checks use Python 3.14.2 and Node 24.5.0:

| Scope | Result |
| --- | --- |
| Python control, operations, CLI, runtime, projection, MCP and connection impact | 324 methods pass; zero failures, errors or skips |
| Complete frontend suite, including both shared connection matrices | 369 methods pass; zero failures, errors or skips |
| TypeScript check and frontend production build | Pass |
| Complete Rust suite, including both source matrices | 69 methods pass; zero failures or ignored methods; build succeeds |

These checks preserve the frozen core and wire oracles and bind the tested source
and fixture digests. A missing frontend build in the first Rust negative-control
attempt was a preparation failure; it is not counted as behavioral RED. After the
existing pinned frontend prerequisites were built, the original Rust consumer
reproduced the intended three-case rejection and the matching correction passed.

The implementation-contract addition separately reproduces a stale selected-D
manifest failure. Refreshing only its two exact specification digests makes the
unchanged collector and the two related CI boundary checks pass. The selected-D
manifest retains its original five selectors and acceptance scope; it does not
claim full P17 or native acceptance.

## Independent review corrections

Nine regression methods reproduce eight failing assertions/subtests on the
published parent, with zero errors or skips; the unchanged nine methods pass on
the corrections. They cover an unprepared Resume and running override, the actual
admission-command reply, current project/work permission, exact cached cleanup
and Stop, rejected mixed/reconnecting configuration changes, case-insensitive
run/serve targets and the actual MCP SDK status response's public boundary.

Six additional wire cases feed the real temporary config/store/read producer to
Python, Rust and TypeScript. A disconnect or unprepared running override yields
unknown permission for that project while the independent connected project stays
allowed. Connected and host-Pause controls still progress normally. Forged allowed
claims cannot use the unavailable project source; the stored running mode remains
visible without a fabricated stopped override.

Parent CI collected 1,737 methods with one stale metadata assertion and eight
explicit skips. The old control-wire test hardcoded CP revision 9. It now compares
the fixture revision and digest with the actual maintained document. An injected
stale revision still reproduces one purpose failure; restoring the current bytes
passes all three original wire checks. The final Python impact selection includes
all control and MCP suites so this consumer is checked locally as well as in CI.

## Admission receipts and defaults

The next review identified a second consumer of the stopped default: receipt
correlation. Two independent reducer cases reproduce a rejected valid Pause and
an incorrectly accepted Resume proof before correction; both pass unchanged after
the source parser and reducer share the public project-mode calculation.

Four actual admission-command controls cover implicit stopped Pause, explicit
stopped Pause, explicit Resume from the stopped default and legacy running Resume.
They verify exact store read-back and whether a write actually occurred. The
implicit-stop case also reproduces the wrong reply reason before Python's source
and receipt paths share the same calculation. The unchanged four controls pass
after correction. No stored override or revision is manufactured for retained Stop.

The preceding source `ad7203c` passes [Repository CI](https://github.com/openboa-ai/hydra/actions/runs/39842908538):
1,747 Python methods collected, 1,739 pass and eight explicit skips; 367 frontend
and 69 Rust methods, builds and trusted hygiene pass. Its selected-D export passes
within its declared scope. Final-source CI and independent review remain required
for the receipt correction.

## Remaining responsibilities

This increment does not create or migrate an installed configuration. The next
P17 increment retains stopped-first connect, desired-first disconnect, atomic
CAS/read-back, old-writer/pending-effect migration checks and qualified resource
coverage before final disconnection. It reuses the same spec.

Final-source remote CI and independent code/security review, protected delivery
and actual-main checks remain required. Actual remote Codex connection, native
qualification, two-project acceptance and full resource closure remain separate
v1 obligations. No installed runtime, admission mode or native task was changed.
