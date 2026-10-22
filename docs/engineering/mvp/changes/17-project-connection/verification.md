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

The ten-case core/CLI oracle set runs on the immutable main runtime:
nine purpose failures, one preserved legacy success, zero errors/skips. The same
unchanged set passes on the implementation. Two additional legacy-control cases
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
| Python control, operations, CLI, runtime, projection, MCP and connection impact | 272 methods pass; zero failures, errors or skips |
| Complete frontend suite, including nine shared connection cases | 361 methods pass; zero failures, errors or skips |
| TypeScript check and frontend production build | Pass |
| Complete Rust suite, including the same nine source cases | 68 methods pass; zero failures or ignored methods; build succeeds |

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

## Remaining responsibilities

This increment does not create or migrate an installed configuration. The next
P17 increment retains stopped-first connect, desired-first disconnect, atomic
CAS/read-back, old-writer/pending-effect migration checks and qualified resource
coverage before final disconnection. It reuses the same spec.

Final-source remote CI and independent code/security review, protected delivery
and actual-main checks remain required. Actual remote Codex connection, native
qualification, two-project acceptance and full resource closure remain separate
v1 obligations. No installed runtime, admission mode or native task was changed.
