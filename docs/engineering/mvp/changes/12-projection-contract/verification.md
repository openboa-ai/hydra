# P12 v3 projection verification

Date: 2026-10-21. Contract: P12 revision 4, CP revision 8, NC revision 8,
reviewed at `30e55e019596d7b83bc7d596ddc575cf1f76044b`. Related work: #3, PR #19.
This record describes local deterministic evidence. Final-head hosted CI and code/security
reviews, protected merge and main checks are separate. No installed/native/live qualification
or completed v1 outcome is claimed.

## Implemented boundary

The existing `control status` remains v2. The explicit v3 read profile requires binding epoch
and request UUIDs and accepts only registered repository selection and an optional opaque
continuation. It uses the real strict UTF-8 encoder and the same fixed, isolated Rust subprocess
boundary. Mutations cannot select this read profile. The bridge provides separate read-only
binding/status/clock-resume commands for P16; the current screen and its action wiring remain
P16 work.

GitHub GET metadata retains actual rate-limit waits without raw headers, credentials or error
bodies. Missing headers never become provider zero. Managed open and closed work are read
before ordinary candidates. A failed later query preserves the known prefix and independent
projects. Queries are bounded by host/repository budgets; canonical repository responses cannot
expand the registered read scope. Any normal Issue is visible with interpretation and authority
unknown. Issue text is data, never a native question or command.

Work and project continuation cursors bind the process connection, exact configured repository
set and selected query. They carry read position, provide no authority and accept no arbitrary
URL. Record and UTF-8 byte bounds retain whole records and partial coverage. Tests recover all
150 issue records across the 128-record bound, all 100 large issue records across the 1-MiB
bound, and all 1,024 registered project contexts without remote calls.

The memory-only Rust cache is limited to 4 MiB of serialized payloads, 16 detail entries and
16 pending scopes. Whole details are evicted; eviction never releases a responsibility. Runtime,
binding and source sequence checks reject old results. Monotonic revisions compare decimal
length/digits without conversion to JSON numbers; a regression cannot replace the retained cache. A late, originally issued rate-limit hint
can strengthen a wait without replacing newer data. Replaying a cached result cannot renew age
or restart a wait. The private bridge envelope carries the original sequence and monotonic age;
it does not alter ProjectionV3.

The reducer keeps current facts, command receipts and unresolved effects separate. It invalidates
facts on source changes even for equal/null revisions; a local-only read cannot refresh GitHub,
create duplicate project contexts or roll back a newer source through an older cached frame.
Source TTLs are 15/60 seconds; visible polling uses 5/60-second floors, stops when invisible and
respects source waits. Clock/runtime/binding changes invalidate stale display dependencies while
preserving unknown effects. Native metadata/history never proves a question or execution.

Provider waits take precedence over fallback. Fallback increases 60, 120, 240, 480 and 900
seconds; five failed automatic retries require explicit recovery. An unrelated same-scope success
cannot reset the failed query. Explicit recovery still honors the known provider deadline.

## Requirement-linked deterministic evidence

| Cases | Evidence |
| --- | --- |
| CP-D01/17 | One CP-pinned input/oracle set emits 19 actual producer vectors. It includes actual CLI/source assembly, P02 readback and the real v2 serializer. The real Python encoder output crosses Rust validation/serialization and the actual TypeScript consumer; invalid/native-only values are never forwarded. |
| CP-D02/07/18 | Late success/failure, cache sequence, binding/runtime replacement, equal/null and opaque revisions, independent failure and pending-command identity cases. |
| CP-D03/04 | Separate unsupported native axes, stale prior values, exact TTL boundaries, clock resume and cached age that predates a newly opened renderer. |
| CP-D05/06 | Whole-record 1-MiB output, work/registered-project cursors, actual aggregate cache traffic above 4 MiB, detail LRU and pending-metadata capacity. Unknown execution/cleanup remain unknown. |
| CP-D14/18 | A real P02 receipt is consumed independently of current admission/execution. Unresolved command feedback survives ordinary reads and binding/runtime changes; duplicate pending effects/request identities are held. |
| CP-D15/16 | Untrusted Issue/native canaries, unsupported native handoff, malformed bytes/keys/scalars, no effect transport, no extra source fetch from text or changed provider address. |
| CP-D20 | Actual header parsing and producer hints, shared/independent scope, known zero versus fallback, cached replay, long provider waits, bounded automatic retries and exact-query recovery. |

Observed local environment: Python 3.14.2, Node 24.5.0, locked Rust dependencies. Local source
checks do not establish hosted trusted scanning or installed/runtime operation. Meaningful earlier
RED includes the existing v2 consumer rejecting v3 behavior and three source assertions showing
lost successful-response waits and lost known-empty description semantics. Setup/compiler errors
are retained separately and are not behavioral RED.

Local results: 117 control methods, 52 projection/source/CLI methods (including 24 common scalar
methods), 21 existing CLI regressions and 10 runtime-identity methods; bundles overlap and are
not a unique-test total. Frontend: 79 passing methods, zero skips; typecheck/Vite build passes.
Rust: 30 passing methods, zero ignored. GitHub transport/read-budget regression: 70 passing
methods; its GitHub product bytes are unchanged after that run. No full local kernel was repeated.

## Bounded source fixture measurements

These use injected GET-only fixture sources, not network or production measurements. Counts
exclude credential subprocesses absent from the injected transport. Elapsed time is one local
observation, not a performance guarantee; read effects are zero.

| Fixture | GET calls | Encoded bytes | Returned work | Coverage / continuation | Elapsed seconds |
| --- | ---: | ---: | ---: | --- | ---: |
| Small request | 4 | 8,428 | 1 | complete / none | 0.001683 |
| Record bound | 5 | 324,418 | 128 | partial / present | 0.023705 |
| UTF-8 byte bound | 5 | 1,041,901 | 55 | partial / present | 0.094047 |

## Compatibility, exclusions and handoff

v2 remains strictly read-only with absent v3 axes unknown. P01 diagnostic `native_context` remains
outside the projection union; private native handoffs are rejected before renderer/cache assignment.
No new database, scheduler, LLM call, wake, admission mutation, progress write or resource retirement
is introduced by reading. Current native, resource inventory and work-binding mapping capabilities
remain explicitly unsupported until their owning work supplies actual qualification. P16 owns visible
screen/action integration and live source observation; P12 source fixtures are not evidence of that.
