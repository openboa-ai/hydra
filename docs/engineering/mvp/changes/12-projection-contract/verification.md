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


## Read generation, complete scope and bounded feedback corrections

Review of 7029761 identified five gaps. Fresh current reads now establish a new runtime
cache/display generation, discard older pending read identities and preserve unresolved
command effects. The existing connection's provider deadline is retained; no write is retried.
An older shared admission sample in an independent remote read cannot discard healthy GitHub
data. Same query-cache monotonic ordering and cross-source reducer ordering remain separate.
Unchanged source input is revalidated, while equal/null revisions with changed values still
invalidate dependent facts.

Complete refreshes remove absent work/source records only for the same repository/query set.
Partial/continuation frames retain uncovered records, and display removal never claims native
termination or resource retirement. Managed labels are excluded from the ordinary continuation
plan, so 100 managed-open plus 28 managed-closed records do not repeat or lose progress on the
ordinary page. Missing label metadata preserves meaningful Issues with partial coverage.
Continuation preserves the underlying query scope; repository-only reads identify their scope.
GitHub display casing is matched against registered names case-insensitively.

Command feedback has its own bounded queue (16 entries and 128-KiB retained receipt budget).
It does not consume the 1-MiB projection payload budget or silently evict the producer's visible
records/cursors. A near-limit valid wire frame plus a real P02 receipt verifies that separation.

Actual RED against published code includes the independent-cache regression, runtime recovery,
complete/partial scope, casing, feedback and managed continuation assertions. The complete-scope
input was corrected to explicitly declare complete coverage; its earlier inherited partial flag
is not treated as evidence for complete-scope pruning. The four corrected frontend assertions
were reproduced against unchanged published model bytes before GREEN.

The corrective candidate passes 53 projection/source/CLI methods, 117 control methods,
84 frontend methods and 32 Rust methods, with no failures/errors/skips/ignored cases. Typecheck
and Vite build pass. Bundles overlap; no full local kernel or unrelated bundle was repeated.
19 actual producer vectors still cross the real Python/Rust/TypeScript path. Small/record/byte
fixture reads use 4/5/5 injected GETs and encode 8,444/324,434/1,041,917 bytes respectively;
these are fixture measurements, not production performance claims.

Parent 7029761 passed all four jobs in run 39512490322 and security review without findings;
its five code findings require this correction. Those results do not qualify the later head.
Accepted P12 Rev4/CP8/NC8, the unchanged v2/default path and all live/native/P16 exclusions remain.
Final-head CI/reviews, protected merge and main checks are separate and pending.


## Bounded pages and source-local recovery -- 2026-10-21

The explicit v3 cache route now rejects legacy v2 before runtime/cache changes;
legacy decoding remains available on its separate compatibility path. Raw cache
frames no longer reject an entire healthy response because one observation's
monotonic revision regressed. The source-aware reducer retains/stales that source
only, including full decimal tokens, while independent current GitHub data flows.
A bounded original-request ledger retains late same-epoch provider waits across
runtime changes without restoring old data or renewing a replayed hint. A real
binding-epoch change still clears that connection's ledger and policy.

Before omitting a repository/work, the producer drops optional unreferenced query
provenance while retaining Fact/hint dependencies. Deep successful comment paging
therefore keeps the selected repository and 40 work records after 2,000+ GETs.
A selected repository never receives an overview-only recovery cursor. A later
exact-query recovery removes its old zero-wait hint instead of invalidating export.

The renderer first removes unreferenced provenance and evicts stale cached values
before known work identities. When individually valid continuation pages no longer
fit together, it rotates to the complete incoming page and its actual provider
cursor. It does not invent a cursor inside a received page or silently omit newly
read records. Actual producer pages traverse all 150 unique issues under the 1-MiB
view budget. Cache eviction/window rotation never terminates or retires work;
feedback, pending commands, source ordering and known provider waits stay separate.
A read failure at the byte boundary retains known work and navigation.

Published parent 0a98c26 reproduces seven actual assertions: two Python source
assembly failures, three Rust cache/limit failures and two renderer continuation/
failed-read failures. No import/compile/setup failure is counted as RED. The first
capacity-run result parser expected the wrong assertion wording; its retained
actual record-loss failure and the corrected unchanged-source rerun are separate.

The final unchanged source/test bytes pass Python55, frontend87 and Rust35 with
zero failures/errors/skips/ignored cases, plus typecheck/Vite build and the actual
19-vector Python/Rust/TS wire. No full local kernel was repeated. Latest local
fixture measurements: small 4 GET/8,444 bytes; 128-record prefix 5 GET/324,434 bytes;
UTF-8 byte prefix 5 GET/1,038,843 bytes/55 work records with a usable cursor. These
are fixture observations, not installed latency or native operation.

The previous head passed all four jobs in
[run 39517483650](https://github.com/openboa-ai/hydra/actions/runs/39517483650);
that run does not qualify this later correction. P12 Rev4/CP8/NC8 and the existing
authority/native exclusions are unchanged. Final-head CI and independent reviews,
protected merge and main checks remain required; P16 still owns screen/action and
actual running-screen integration. No runtime/authority was installed or activated.


## Repository resolution and bounded continuation navigation -- 2026-10-21

Local-only or failed initial reads can retain a requested repository alias. A later
numeric repository observation now replaces that alias and reconciles its display
selection. The inverse numeric-to-local-only path remains supported. Numeric
identity, execution and command authority are not inferred from an address alone.

Project navigation now tracks the same work retained by the merged read model.
Within the accepted 128-ref project bound, continuation refs accumulate alongside
their whole work records. At the bound it rotates only that project's incoming
whole page, removing the prior page's related cached sources/relations while
preserving other projects, actual cursors and command feedback. Byte-budget
rotation remains separate. No partial slice is promoted to whole-source coverage
and cache eviction does not terminate, complete or retire actual work.

Unread cursor scopes advance immediately despite the ordinary local/remote poll
floor. Replaying a cached cursor is a repeat poll, retaining the normal floor and
original cache age. Both continuation and manual recovery still honor connection
provider waits and automatic-retry exhaustion. The bridge uses the same bounded
process invocation; no new reader or authority was introduced.

Actual producer cases cover local-only/failed-read resolution, 100+20 fault/recovery
pages within the bound and 128+22 pages that require project rotation. They require
every retained work to be reachable, every newly read whole record present, the
128 bound, exact provider cursor, another project's retention and unknown cleanup.
Actual bridge calls verify local and remote continuation, cursor replay and
provider-limited recovery; child invocation counts distinguish cache reads from
additional subprocesses. These are source/fixture checks, not installed operation.

Unchanged published d201dc0 reproduces five actual assertions: three renderer
identity/navigation failures and two bridge continuation failures. No compiler or
setup error is counted. Earlier draft assertions incorrectly required retaining
150 project refs and allowed admission under the paused fixture host; the existing
128 contract and actual paused input corrected those oracles before the final
unchanged-parent RED. Final RED and GREEN use identical regression test bytes.

The final source/test bytes pass Python55, frontend90 and Rust38 with zero
failures/errors/skips/ignored cases, typecheck/Vite build and the existing actual
19-vector Python/Rust/TS wire. Read-cost fixtures remain small 4 GET/8,444 bytes,
128-record prefix 5 GET/324,434 bytes, and UTF-8 prefix 5 GET/1,038,843 bytes with
55 whole records and a usable cursor. No full local kernel was repeated.

P12 Rev4/CP8/NC8 remain pinned and unchanged. Final-head CI and completed
independent code/security reviews, protected merge and actual-main checks are
still required. P16 owns the later screen/action integration and running-screen
evidence. No runtime, source capability or authority was installed or activated.


## Current local admission and bounded raw input -- 2026-10-21

Local polls intentionally return no work rows. The reducer now propagates a
uniquely matching project's freshly validated admission Fact to its retained work
rows, preserving the current revision/evidence rather than leaving source_changed.
Missing, stale, regressed or ambiguous project facts cannot become current work
admission. Independent GitHub readiness/age, unknown execution/cleanup and command
feedback remain separate; this read model neither changes admission nor wakes work.

The projection-only HTTP parser rejects raw UTF-8 input above 1 MiB before JSON
decoding. The bound includes response headers and multibyte characters. Exactly
1 MiB remains accepted. Legacy JSON-only API behavior and the separate aggregate
collection budget are unchanged; oversize raw input is not normalized as success.

Published 7ddb603 reproduces three actual assertions: two ASCII/multibyte byte
boundary failures and one retained-work admission failure. Identical final test
bytes pass. Actual producer normal/local stopped/local allowed/regressed-revision
frames verify work/project agreement without GitHub GETs or refreshed independent
readiness. Oversize responses invoke the JSON decoder zero times.

Local Python projection56, GitHub71, frontend91 and Rust38 pass with zero failures,
errors/skips/ignored cases, plus typecheck/Vite build and the actual shared wire.
Some Python selections overlap; these are suite counts, not a combined unique
count. Cost fixtures retain 4 GET/8,444 bytes for small; 5 GET/324,434 bytes for
128 records; 5 GET/1,038,843 bytes for 55 UTF-8 records with a usable cursor.
These are source/fixture observations, not installed or native qualification.

P12 Rev4/CP8/NC8 remain pinned and unchanged. The previous 7ddb603 passed all four
jobs in [run 39526279339](https://github.com/openboa-ai/hydra/actions/runs/39526279339);
that evidence does not qualify this correction. Final-head CI and completed
independent code/security review, protected merge and main checks are required.
P16 still owns screen/action integration. No runtime or authority was activated
and no full local kernel was repeated.


## Exact output, required proof and partial-frame pressure -- 2026-10-21

The synchronous CLI and default async stdout emitter now write v3 bytes without
an extra newline. A valid maximum-size UTF-8 frame reaches exactly 1,048,576
stdout bytes; v2 and caller-supplied emit callbacks retain their own behavior.

Python, Rust and TypeScript require typed receipts when workflow_step or cleanup
reports applied. Existing receipt-kind/action validation remains in force;
waiting without a receipt is still valid. Four deliberate bad-wire cases extend
the shared actual-producer/consumer fixture to 23 vectors. A receiptless applied
command cannot become accepted applied feedback through these consumers.

The renderer replaces a retained view only with a complete query result or a
whole bounded prefix/continuation page backed by current repository identity.
Local-only and failed/incomplete source frames cannot replace healthy retained
work. Under their byte pressure it removes unreferenced provenance, then stale
and cached non-Hydra values as needed, exposing renderer_limit/unavailable while
retaining work identities, current local gates and independent feedback. Known
provider-hint anchors remain protected; cache eviction never ends or retires work.

Unchanged 0c00d12 reproduces thirteen actual assertions: six Python stdout/proof,
six TypeScript proof/partial-view and one Rust proof failure. The two actual
producer partial cases lose 55 retained work identities on the old model. Their
first draft was underfilled after decision normalization; the final fixture
normalizes prerequisites and asserts the retained view is eight bytes below the
bound before applying pressure. Only the actual final work-loss assertions count.
Final regression test bytes are identical in RED/GREEN; no compiler/setup error
or repeated run is counted as another failure.

Local Python projection58, GitHub71, frontend101 and Rust39 pass with zero
failures/errors/skips/ignored cases, plus typecheck/Vite build and the shared
23-vector Python/Rust/TS wire. Python selections overlap. Cost fixtures remain
small 4 GET/8,444 bytes; 128 records 5 GET/324,434 bytes; UTF-8 prefix 5 GET/
1,038,843 bytes with 55 whole records and a usable cursor.

The previous 0c00d12 passed all four jobs in
[run 39527627409](https://github.com/openboa-ai/hydra/actions/runs/39527627409);
that result does not qualify this later correction. P12 Rev4/CP8/NC8 remain
pinned. Final-head CI, completed independent code/security reviews, protected
merge and actual-main checks are required. P16 still owns screen/action and
actual running-screen integration. No runtime/authority was activated and no
full local kernel was repeated.


## Preserve uncertainty at classification and alias boundaries -- 2026-10-21

The ordinary issue pass now skips records whose label list or any label name is
unreadable, retaining partial source coverage. It never emits those identities as
ordinary candidates that could overwrite earlier managed progress. Valid string
and named-object labels, including a known empty list, retain their behavior.
The page remains bounded and traversal continues to independently valid records.

When a failed refresh uses a requested repository alias, the reducer retains its
incoming partial coverage and reason while reconciling the known numeric identity.
Only an intentional not_requested local poll reuses earlier remote coverage.
Retained work and the current local admission remain separate from failed source
coverage; no ended/accepted/applied state or native effect is inferred.

Seven finalized assertion failures were reproduced on unchanged published 22e6ec5:
six unreadable-label continuation variants and the failed-alias coverage case.
Both final test files are identical between that RED and GREEN. The positive
actual-CLI wire input now explicitly declares labels=[] for its ordinary issue;
previously omitted metadata was ambiguous under the corrected classification.
All original expected values and all 23 shared vectors are retained. The alias
regression compares its coverage reason with the actual incoming producer frame,
rather than assigning a different reason to the generic injected exception.

Final local checks: 59 projection Python methods, 102 frontend tests, 39 Rust tests,
TypeScript/build and unchanged bounded request/response probes all pass, with zero
failures/errors/skips. All shared Python-emitted vectors pass Rust and TypeScript.
Costs remain four GETs/8,444 bytes for a small source and five GETs for bounded
128-record and 1-MiB prefix reads. Earlier raw/wire/admission/retained-page cases
remain included. Unchanged HTTP parsing did not require another local suite run;
the required final-head hosted kernel/Mac/hygiene CI still applies.

P12 Rev4, CP8 and NC8 pins remain unchanged. No interface redesign, native command
activation, installation or operating qualification is claimed. Final-head CI,
independent code/security reviews, protected merge and actual-main checks remain.
