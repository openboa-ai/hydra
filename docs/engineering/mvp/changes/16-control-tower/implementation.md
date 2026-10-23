# P16 implementation: lifecycle reads and compatibility

Reuse P16 revision 4 and the maintained control-plane contract. The first
increment connects the delivered P12 read bridge and reducer to an actual
overview, project and work detail. It does not complete the typed-command or
installed-operation responsibilities of the full P16 specification.

## Purpose and responsibility

The viewer needs one place to inspect delegated goals, work, evidence and next
actions. GitHub, Codex and resource providers retain their original records.
The view owns only transient selection and the existing projection reducer's
display cache. It creates no tracker, question store or persistent data copy.

The visually separated V2 surface is a read-only compatibility view. Its status
and guarded original navigation remain available, while observations do not
authorize an operation. New workflow, native, connection, delegation and cleanup
actions remain disabled until their exact producer and typed consumer are
qualified; no legacy operation substitutes for them.

## Read and display behavior

The existing fixed `projection_binding`, `projection_status` and
`projection_clock_resumed` bridge commands supply binding, bounded reads and
clock invalidation. The renderer cannot choose a runtime, file, provider or
shell command. Request IDs and sequence numbers belong to the current read.
The delivered reducer validates responses, merges pages, preserves independent
sources and removes permission from stale evidence. Selection changes do not
create another work item or mutate provider state.

Overview shows observed projects and delegated goal references. A project
shows its source-backed admission, execution, coverage and observed work.
Work detail separates the original request, interpretation, stage, question,
answer, acceptance, application, delivery, outcome and cleanup. Missing facts
remain unconfirmed with their reasons. An observed empty/partial page is not
zero active work, goal completion or permission to Quit. Metadata reporting an
active task is not verified running execution.

All original text is rendered as text. Allowed GitHub source navigation uses
the existing guarded `open_record` boundary and exact observed Issue/PR
identity. No source URL is fetched or executed automatically. Private assignment
prompts, paths and native transcripts are not added to the screen or a cache.

## Failure, recovery and compatibility

A failed refresh retains the prior display with stale/unknown evidence and its
source reason. It does not erase a separate project's valid observations or
manufacture empty success. Read failure feedback belongs to the source and query
that failed; local polling, another project or another query cannot acknowledge
it. Matching recovery clears its own feedback. This bounded transient feedback
contains no provider error text and is invalidated with its connection/runtime.
Read lanes belong to request generations. Clock, binding and runtime boundaries
release only their display ownership; outstanding IPC promises remain accounted
for until they settle, with at most two retained invocations per source lane.
An old completion cannot clear a newer lane or confirm a newer clock recovery.
The native bridge retains its existing serialization and provider budgets.

Validated `requested:<address>` project aliases support read-only recovery before
GitHub identity is available. They are not numeric mutation targets or original
record authority. Shared binding preflight failure invalidates retained evidence
and old read queries while preserving original records and unresolved effects.
The reducer preserves an existing source failure cause when applying display TTL.
Only an uncached, non-stale matching reply acknowledges a failed source refresh.

Late responses cannot change the selected target.
A binding replacement clears the old read context, selection and cached view
before fresh data can be accepted. Read retries use the existing source policy;
no mutation is retried by this read-side component.

The compatibility view is not a V3 command consumer. Unsupported V3 reads show
an explicit unavailable view; they do not synthesize V3 evidence from a V2
snapshot. Qualified typed app commands remain a separate P16 responsibility.

## Read-only V2 compatibility

CP section 9 and P16 section 6 require V2 observations to remain read-only in
the new client. The compatibility renderer disables every legacy host/project
action and Quit, explains that boundary and removes its write/shutdown dispatch
code and command-pending state. Manually forcing a disabled handler still sends
no operation. Status refresh, source navigation and appearance controls remain
available through their existing guarded paths.

The Rust legacy mutation entry rejects with `legacy_control_read_only` before
runtime or provider dispatch. The same boundary also stops the native Quit
flow from turning a shutdown attempt into an implicit global Stop. Unsupported
shutdown remains held; a V2 observation cannot qualify execution termination.
Renderer permissions for the retired control and shutdown commands are removed.
Native menu wording and attempt feedback do not claim that work is stopping.

The installed CLI and native MCP retain their existing meanings. This source
change does not modify an installed runtime, operating setting or authority
profile. Typed V3 commands and installed/remote operating acceptance are still
required for the complete P16 outcome.

## Independent verification and completion

Tests execute the actual entry point and renderer in a DOM using synthetic
bridge responses and the shared, publishable P12 source frame. Independent
outcomes cover successful navigation, distinct lifecycle facts, unknown native
activity, inert original text, selective source failure, late responses and
binding replacement. A valid existing-entry control verifies the harness before
the behavioral RED is counted. Existing frontend, wire, theme and native bridge
regressions remain required.

Share the actual frontend fixture screen before publishing the visual PR.
Label it as a fixture and preserve installed app, real scoped command/read-back,
remote Codex, two-project operation and resource closure as separate obligations.
Source tests and a rendered fixture cannot complete those operating requirements.
