# P17 implementation sequence

This change reuses [P17 revision 2](spec.md), [PC revision 1](../../contracts/project-connection.md)
and the existing control-plane command and projection contracts. It preserves the
complete connection outcome: preview, guarded configuration/admission CAS,
read-back, restart and accountable disconnection. Source increments do not complete
the required remote operating qualification.

## Fresh binding before configuration writes

The first increment supplies the prerequisite that makes the later two-store
writer safe. A profile-1 configuration can describe zero projects and exact
connection intentions. Admission version 2 names one trusted configuration path;
every effect reads that path and compares the current configuration with the
configuration actually loaded by its controller. Arg-only or differently bound
writers cannot use a version-2 store. An allowlist entry without a connected
declaration cannot gain permission by receiving a running override or Resume.

An unprepared version-2 project defaults to stopped. Explicit project Resume
still requires host permission and a connected current declaration. A pending
disconnect blocks new business effects while retaining separately authorized
Stop and exact cleanup behavior. Source loss, unsafe paths and stale loaded
configuration preserve the previous stores and prevent the callback. A cached
controller can preserve an ended execution or apply a limiting operation after a
pure connected-to-disconnect-requested transition. The declarations, native
locators, registry, providers and every other setting must otherwise be unchanged.
This narrow exception does not reload the controller or allow further business
effects, reconnection or unrelated configuration changes.

The existing loader retains its source provenance privately, outside serialized
configuration fields. Runtime configuration identity includes the profile and
connection declarations, while legacy configuration digests retain their meaning.
Neither an operation request nor a project file selects the trusted path.

Projection producers and strict Python/Rust/TypeScript consumers must agree on
the admission default. The implementation closes an optional
`default_project_mode` admission source field: absence retains the legacy running
default; the version-2 source declares stopped. It is derived from the actual
admission format, carries no configuration path, and does not authorize work.
Old schema-2 control operations reject this new profile before any mutation.
MCP status emits a closed public controls view, preserving the actual store
version and stopped default without exposing the trusted configuration locator.

During a disconnect's desired-first crash window, the actual store can still say
running. The producer retains that source fact and supplies a scoped unavailable
admission observation for the affected project's connection guard. Project and
work permission become unknown with the exact reason; another connected project
can retain allowed permission. Existing strict consumers reject an allowed claim
using that unavailable source. This uses the current observation/fact protocol.

Repository spelling remains case-insensitive when run/serve arguments are compared
with the installed allowlist. Host, path and provider comparisons remain exact.

Tests first pin independent normal, stale, source-loss, malformed, no-config and
missing-override outcomes. They use actual temporary settings and configuration
files and the actual command/CLI boundaries. Existing legacy checks and the real
producer/strict-consumer wire checks remain required.

## Subsequent configuration writer and actual qualification

The next increment uses this fresh guard and the same admission barrier for
PC's stopped-first connect, desired-first disconnect, exact expected values and
atomic read-back. It must close migration's old-writer/pending-effect checks and
the actual provider coverage needed for final disconnection. The first increment
does not expose a configuration writer or migrate an installed store.

The maintained PC request/reply remains the contract for the fixed connection CLI.
Remote Codex access, installation migration, native/resource qualification and
the separate app consumer are verified through their own required paths before
their capabilities are enabled. No new registry or native task is introduced.
