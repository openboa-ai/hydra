# P12 v3 projection verification

Date: 2026-10-21. Contract: P12 revision 4, CP revision 8, NC revision 8,
reviewed at `30e55e019596d7b83bc7d596ddc575cf1f76044b`. Related work: #3, PR #19.
This record describes local deterministic evidence. Final-head hosted CI and code/security
reviews, protected merge and main checks are separate. No installed/native/live qualification
or completed v1 outcome is claimed.

## Current correction: bounded overview and cached-result ordering

This increment corrects two findings on published parent
c8a779ed3689d63dca3da98e570cd6177750309f. Accepted P12 Rev4 / CP8 / NC8 and
the [Mac control contract](../../../mac-control/spec.md) remain unchanged.

- The aggregate refresh cap remains 4096 API requests including transport
  authentication, with the existing 45-second deadline and nested caller caps.
  An overview collects a bounded repository slice so its first fair share fits
  identity authentication, repository identity and all three Issue lists. The
  remaining-budget / remaining-repositories allocation is unchanged. Unvisited
  repositories remain partial behind the existing overview cursor; byte pruning
  can move that cursor earlier. All 1024 configured repositories remain reachable.
- The reducer reuses its greatest accepted payload sequence to replace current
  embedded request results. An older cached scope cannot restore a cleared
  receipt, erase a newer result with null or replace a different newer result.
  Fresh null and different results still replace the current result; separate
  command feedback history is preserved. No extra persistent or reducer counter
  is introduced.
- Numeric repository pins still survive credential rotation/sign-out without
  reusing remote data or access. Binding/runtime changes and late prior-context
  response fences remain enforced; current-token GETs prove access and identity.

The preceding increment incorrectly treated 4097 synthetic requests as a passing
accounting oracle. That expectation violated the existing accepted aggregate cap
and has been replaced, rather than expanding the contract. The new independent
oracle traverses actual returned overview cursors through all 1024 repositories,
using a cold real HTTP/auth client with deterministic synthetic subprocess replies
on each page. Every page stays within 4096 requests and one identity GET, every
collected minimum membership completes, returned records never repeat, and the
whole configured set is eventually returned. Wire-size pruning remains partial
until the last returned slice. These are deterministic accounting/pagination
checks, not a live throughput or installed-operation qualification.

The immutable parent reproduces two Python assertion failures across five methods
and one failing frontend method across two, without setup errors/skips. The same
tests pass after correction. Actual Python reply/encoder frames exercise fresh
null/applied/different results and cached cross-scope replay with lower payload
sequences, while preserving intentional feedback history.

Final local impact checks pass: 262 selected Python 3.14.2 methods, 333 frontend
tests, all 55 Rust 1.94.1 tests and TypeScript/Vite build, with zero failures,
errors, skips or cancellations. Exact final-head CI, independent code/security
reviews, protected merge and actual-main verification remain required. No native
writer, installed authority, remote Q&A/Resume flow, session recovery or complete
two-project v1 operating acceptance is qualified by these checks.

## Earlier correction: qualified claims and membership preservation

This increment corrects seven findings on published parent
da082c6203ff246720b9a540d975e02e99d2ad65 under unchanged P12 Rev4 / CP8 / NC8.
Public wire fields, command authority and installed/native activation are unchanged.

- Projection and standard replies bind every admission receipt readback to the
  runtime's exact Hydra admission resource. Tracked feedback checks the same
  binding before accepting the requested mode. Foreign-store diagnostic data
  cannot establish an applied receipt for this control store.
- Known readiness references/revises an evidence observation of its enclosing
  Issue. The implemented mapping exposes the original visible Issue as a
  proposal with unknown authority and no claimed interpretation, binding or
  extracted requirements. Qualified intake/authority mappings remain later work.
- Project work refs are unique canonical GitHub Issue refs in that repository.
  An unresolved repository can retain an empty membership without inventing a
  numeric binding. Local gate propagation cannot cross repository membership.
- Current producers already leave project execution and work stage, execution,
  wait, delivery, result, cleanup and next_action unknown. The three consumers
  now reject supplied known claims for these unimplemented view mappings.
  All thirteen typed SourceValue variants remain readable: a source record alone
  cannot invent a work binding, acceptance, delivery or complete resource scope.
- Parent edges require the exact child and explicit parent ref in the citing
  Issue payload. The other relation kinds have no implemented mapping. Parent
  visibility does not change accepted delegation or grant an effect. The current
  reader does not activate native parent collection; P11 integration remains open.
- Local polls preserve retained remote page coverage and its original source age.
  Scoped repository coverage cannot replace the host overview; a host overview
  can replace a previously scoped view. Existing binding/runtime fences remain.
- Optional query-provenance eviction preserves complete membership, unresolved
  detail refs and retained relation evidence. Actual omitted work/project records
  still produce partial response-limit coverage. No truncation declares completion.

One literal 431-case matrix supplies 862 projection/standard profiles. It includes
all thirteen source variants, current/unknown view claims, readiness/source/work
correlation, exact parent payloads, repository membership and active-store receipts.
Every positive profile is serialized by the actual Python encoder. Actual reader,
pruner and reducer sequences verify local/remote membership and optional-byte
eviction, including membership refs without expanded work records.

The immutable published parent reproduces 385 Python assertion failures across
six methods, four failing frontend methods and one aggregate Rust matrix failure,
with zero setup errors/skips/cancellations. The final Python/frontend oracles were
rechecked on a pristine parent after correcting a prerequisite: local reads may
emit unavailable GitHub placeholders but do not emit current GitHub observations.
Membership preservation requirements and matrix acceptance flags are unchanged.
The normal locked frontend build completed before Rust RED.

Final local checks pass: 257 selected Python 3.14.2 methods, 331 frontend tests,
all 54 Rust 1.94.1 tests and TypeScript/Vite build under Node 24.5.0. Final runs
have zero failures/errors/skips/cancellations. Exact new-head hosted CI,
independent reviews, protected merge and actual-main checks remain required.
Unsupported-view rejection is not completion of its source integrations. Actual
remote control/Q&A, session recovery, acceptance, delivery, resource scope and
two-project v1 operating acceptance remain required under their owned changes.

## Earlier correction: derived facts and retained repository identity

This increment corrects four findings on published parent
e58ca8e036eebaf061d6be963664b20aee9ec605 under unchanged P12 Rev4 / CP8 / NC8.
It changes no public wire field, native source support or command authority.

- Known project/work admission facts are derived from all cited Hydra admission
  snapshots with host restriction precedence and the owning repository's
  registered aliases. Missing, foreign or conflicting store/name context cannot
  support a known gate. Both view types use the same derivation rule.
- Current/stale repository values require the exact canonical decimal numeric
  resource locator. Requested names, leading zeros, another ID and signs cannot
  carry a non-null numeric repository value. Successful query provenance notes
  use the same validated numeric resource; unavailable notes retain requested refs.
- No implemented SourceValue mapping currently qualifies any DecisionView axis.
  Known question, answer, acceptance and application facts are rejected until
  an actual qualified mapping is implemented. Ordinary Issue evidence, minimal
  native metadata and capability claims do not create that mapping. Unknown
  decisions remain readable. P04/P06 native decision integration remains open.
- The existing fixed reader accepts an observed rename only when its numeric ID
  matches the retained binding. It still queries configured addresses only and
  rejects reused addresses with another ID. The bridge holds at most 1,024
  volatile read hints within the existing binding/credential/runtime context,
  clears them across context replacement and never retargets an existing name.
  Internal bounded CLI hints do not select arbitrary API paths or grant effects.
  Rename pagination retains the registered address associated with its cursor.

One shared literal 136-case matrix supplies 272 projection/standard profiles to
Python, Rust and TypeScript; all positive vectors use the actual Python encoder.
The actual Python reader-to-reducer sequences cover rename/reused-address reads
and independent admission preservation. Fixed-child-process tests verify the
hint argv, failure retention and binding/credential/runtime reset fences.
Validated response pages additionally fill the 1,024-entry limit, reject growth
and retargeting, and keep renamed cursor scope tied to its registered address.

The immutable published parent reproduces five Python methods with 108 assertion
failures and zero setup errors/skips after normalizing the capability-ref fixture
to its required string type. The earlier parent runs also reproduce three failing
frontend methods and two failing aggregate Rust methods without setup errors or
skips. The normalized capability-ref rejection oracle is unchanged. A preexisting
incomplete-runtime positive fixture now marks admission unknown when the control
binding is absent; independent observations and the cache-preservation oracle
remain unchanged.

Final local checks pass: 251 selected Python 3.14.2 methods, 327 frontend tests,
all 53 Rust 1.94.1 tests and TypeScript/Vite build under Node 24.5.0. Final runs
have zero failures/errors/skips/cancellations. Exact new-head hosted CI,
independent reviews, protected merge and actual-main checks remain required.
Installed migration, authenticated native decisions, actual remote control and
the full v1 acceptance sequence remain unqualified.

## Earlier correction: source values and evidence causality

This increment corrects five findings on published parent
3348240b10f208fd0caa149f6bdc43aa84d94988 under unchanged P12 Rev4 / CP8 / NC8.
It changes no wire fields, source capability, command authority or installation.

- Every attempted managed-progress read emits its stable-key observation.
  Exceptions, invalid records and no readable record emit unavailable evidence;
  the reducer immediately retains the last good value as stale. Independent
  Issue membership and complete repository coverage remain intact.
- Known project/work admission facts require at least one Hydra admission
  observation. Mixed supporting metadata remains valid. Generic evidence checks
  still require every cited observation to be current, complete and revision-matched.
- Non-null current/stale admission values require an exactly matching monotonic
  observation revision. An unrelated or forged high outer counter is rejected.
- Admission observations and project references use the runtime control-binding
  digest. Missing binding identity produces an explicit unresolved requested ref,
  unavailable admission and unknown gates while preserving independent reads.
  Missing source-code identity with a known control binding remains readable.
- Current/stale Issue values require a canonical positive safe-integer
  repository:Issue locator whose Issue number equals the typed source value.
  Unavailable resources retain opaque locator support.

One shared 30-case matrix covers projection facts and standalone reply sources
in Python, Rust and TypeScript. Actual builder-to-reducer sequences verify failed,
missing and invalid progress after a current value, before the old value's TTL.
The builder also checks known/missing binding, source-code identity failure and
local snapshot failure. No raw error text becomes public output.

The actual published parent reproduces 39 Python assertion failures across three
methods, 21 failing frontend methods with 12 healthy controls passing, and one
aggregate Rust matrix failure. There are no setup errors/skips/cancellations;
the normal locked frontend build completed before Rust RED. The final frontend
oracle was separately rechecked on that unchanged parent after correcting its
expectation from erased/unavailable to retained/stale. The sourceFresh=false
requirement is unchanged. Matrix formatting was compacted without changing any
parsed test case, value or acceptance flag.

Final local checks pass: 246 selected Python 3.14.2 methods, 324 frontend tests,
all 50 Rust 1.94.1 tests and TypeScript/Vite build under Node 24.5.0. Final runs
have zero failures/errors/skips/cancellations. Existing revision-order fixtures
now pair admission counters with their typed value, and generic arbitrary-size
counter tests use ownership observations. Their ordering/preservation oracles
are unchanged; admission remains bounded by its declared numeric source type.

These are source/consumer results. Exact new-head hosted CI, independent reviews,
protected merge and actual-main checks remain required. Installed migration,
native Q/A attribution, actual remote control and full v1 operation remain open.

## Earlier correction: exact receipts and final local observations

This increment corrects six code-review findings on published parent
9296d4119229cc3f527b0c78dca0346b35a00b7b under unchanged P12 Rev4 / CP8 / NC8.
It adds no wire version, capability, command authority, installation or effect.

- Admission tracking snapshots its requested mode. Repository tracking resolves
  the numeric target from a unique existing current repository observation and
  retains that name for the receipt comparison; missing/ambiguous mapping stays
  unknown. The receipt must prove the stored requested mode, or retained Stop
  for Pause. A restrictive host gate cannot substitute for a project's stored
  override. Project Resume also requires the host gate to be running.
- Deliver tracking snapshots the PR number and compares the receipt's GitHub
  repository:PR identity alongside candidate and integration base. A different
  PR or a generic placeholder cannot satisfy that request.
- Every cleanup receipt needs a nonempty provider read-back reference list in
  Python, Rust and TypeScript. One literal 32-case corpus covers the four
  operations, four outcomes and empty/present evidence in both wire profiles.
- The read cache retains valid incomplete runtime identities and independent
  facts. Runtime changes still fence older generations, malformed frames still
  fail, and RuntimeIdentity.known plus enabling-command guards are unchanged.
- Failure-shaped coordinator results are unavailable observations with safe
  fixed reasons. Valid absent/free/busy/owned/native reads remain observable;
  no ownership observation proves native termination.
- Local admission and ownership are sampled after remote collection. Project
  and work gates reference the final local snapshot; concurrent Pause/Stop and
  a final local read failure cannot be replaced by an earlier allowed gate.
  Independent GitHub membership and work facts remain available.

On the actual published parent's production logic, the same new tests reproduce
43 Python assertion failures across four methods, 50 failing frontend methods
with 32 normal controls passing, and three Rust assertion failures. The normal
locked frontend build completed before Rust RED. These behavioral runs have no
setup errors, skips or cancellations. Final new test bytes and corpus oracles
are unchanged from that RED run.

Final local Python 3.14.2 impact checks pass all 243 methods, frontend all 291
methods, Rust 1.94.1 all 49 methods, plus locked TypeScript/Vite build under Node
24.5.0. All final selected runs have zero failures/errors/skips/cancellations.
Earlier regression setup failures came from old positive cleanup fixtures with
empty evidence and an admission capacity fixture missing its requested mode;
their valid prerequisites were corrected without changing acceptance oracles.
Healthy fixtures now identify PR 9 and its stored Pause/read-back context.

These are source and consumer tests. P16 action wiring, native Q/A attribution,
actual remote control, installed migration and the full v1 operating flow remain
unqualified. Exact new-head hosted CI, independent code/security reviews,
protected merge and actual-main checks remain separate delivery gates.

## Earlier CP8 receipt, request and coverage correction

This follow-up preserves P12 revision 4 / CP8 / NC8 and corrects four findings on
published parent a7f59fcd1bcfde3c5d4eea1cf795b44b986aeb47. It changes no wire
fields, command capability, server authority, installation or effect path.

- Publication is applied only at publication_ready with a PR reference. A
  pr_ready/publication_ready receipt cannot omit that reference. Delivery is
  applied only after successful post-merge and Issue-close read-back. Valid
  partial/failed receipts remain available under waiting/unknown outcomes.
- Pending commands retain null effect keys. Nulls never create an effect-key
  collision; duplicate request IDs and actual unresolved checkpoint/decision keys
  remain fenced. Healthy admission/workflow/cleanup examples use their CP8 keys.
- Continuation tracking retains a bounded snapshot of the typed ProgressPin,
  distinguishes null from missing, and compares represented attempt/head/contract
  fields before accepting feedback. No missing receipt phase field is invented.
- Complete Issue membership is independent of a failed managed-progress read.
  The affected stage remains unknown while removed ordinary Issues can be pruned.

One independent 54-case receipt-state corpus drives Python, Rust and TypeScript,
under both standard replies and embedded projection results. Nine healthy typed
tracking events cover nullable and real effect keys. The actual producer also
feeds the removed-Issue reducer regression. These are deterministic consumer
tests, not executions of those commands or native operating acceptance.

Unmodified-parent production logic reproduces 41 Python assertion failures
(two methods), 35 failures among 72 new frontend methods, and one Rust matrix
assertion. These behavioral runs have no errors or skips. Rust first required
the normal locked frontend build; the earlier missing-dist compilation failure
is recorded separately and is not behavioral RED. A controlled null-key-only
correction still fails 27 frontend methods, exposing correlation/receipt/coverage
failures behind the former input rejection; it is not unmodified-parent evidence.

The same final wire inputs and oracles pass: two focused Python methods, all
72 new frontend methods, all 239 selected Python methods, all 209 frontend methods,
all 46 Rust methods, and TypeScript/Vite build. Python is 3.14.2, Node is 24.5.0,
Rust is 1.94.1; all successful runs have no failures, errors, skips or cancellations.
Formatting the corpus for review leaves every wire value/oracle unchanged; all
three focused consumers were rerun on the final file. The earlier duplicate-effect
test now uses a real checkpoint key rather than a fabricated admission key.

Command feedback remains separate from current source Facts. P16 owns actual
screen/action construction and wiring; native-only handoffs remain outside this
standard renderer profile. New-head CI/reviews, protected merge and actual-main
checks remain delivery gates. Full v1/native/installed qualification remains open.

## Earlier workflow-correlation correction

The reducer now snapshots bounded workflow correlation pins and the exact
assignment at command submission. Private summaries are excluded. A reply with
the same request/action/target still needs the requested operation and stage;
checkpoint/review receipts also need the same assignment. Candidate pins,
checkpoint outcomes, decision source/round, publication branch and integration
base are compared where the receipt represents them. Missing or mismatched
correlation leaves unknown feedback without an accepted receipt. Backend
authorization and per-command effect guards retain their existing responsibility.

At that revision, the 24-case regression reproduced 16 assertion failures on actual
parent `050c7beb2c20c92f30636e9c8ea347fae8ca5f1c`, with eight normal controls
passing and no wire errors, cancellations or skips. With the correction all
24 cases pass, including immutable pins after caller mutation and exclusion of
the private-summary canary. All 137 frontend methods and the locked TypeScript /
Vite build pass under Node 24.5.0; fixture children use Python 3.14.2.

This implements the common CP section 8 receipt-correlation requirement under
P12 revision 4 / CP8 / NC8. It changes no schema, server effect path, grant or
installed/native capability. New-head hosted CI, independent reviews, protected
merge and actual-main verification remain separate delivery evidence. The
following sections retain historical implementation and correction evidence.

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


## Causal cached pages and runtime poll floors -- 2026-10-21

Project absence, source fields and whole-page replacement now respect the original
bridge sequence rather than a later renderer request number. Older cached project
pages retain newer work, its source bytes, current coverage and independent user
selection. Failed alias reconciliation preserves both existing and attempted source
references, allowing the same ordering rule to hold newer partial coverage. Current
local admission and independent projects remain separately usable. Conflicting
unversioned cached content retains the existing conservative dependent-fact hold.
A genuinely newer complete source still prunes absent work from the display; that
absence does not prove resource termination or replace the user's selection.

Runtime identity has a small connection-local sequence fence even when its source
page is empty. Late cached old generations cannot roll it back, while a genuinely
new generation remains recoverable. Generation replacement resets stale ordinary
local/remote poll starts and restores the current read's actual start from the
existing bounded request ledger. Provider quota/backoff is retained separately;
clock/cache/detail behavior and public wire types are unchanged. No persistent
project/source map or authority is added.

Six actual parent assertions failed before the fix: two real producer/reducer
cache/detail/failed-alias cases, two cached runtime cases including an empty page,
and two actual Rust cache generation/poll cases. Final test bytes are unchanged
between RED and GREEN, including the Rust test tail on the unchanged parent prefix.
All 106 frontend and 41 Rust tests pass, along with TypeScript/build and the shared
23 Python-emitted wire vectors. Existing null-revision holds, quotas, ordinary floors,
continuation, source capacity and normal fresh-complete pruning remain covered.
Unchanged Python source/HTTP paths retain their earlier local checks and must pass
required final-head hosted CI; no installed/native operation is claimed.

P12 Rev4, CP8 and NC8 pins remain unchanged. Final-head CI, completed independent
code/security reviews, protected merge and actual-main checks remain required.


## Credential context, source ownership and continuation closure

This increment retains P12 Rev4 / CP8 / NC8 and closes four observed implementation gaps.

- A local, model-free context probe uses only the existing selected credential and no HTTP. It returns a per-binding opaque policy scope, never a token, identity proof or control grant. The bridge serializes probes, checks at most once per five seconds and bounds each process to three seconds; the credential selection itself has a two-second budget. Unknown context holds remote reads while local admission remains available.
- Every actual projection API request checks the selected credential against its invocation context before HTTP. Mid-read rotation ends that observation. The bridge preserves each scope's provider waits/fallback counters, fences late prior-context remote results and retains independent local facts. Returning to a credential restores its remaining policy. Ordinary polling floors remain.
- Internal CachedRead metadata carries the current context order independently of the cached payload sequence. The renderer requires that metadata, stales only affected GitHub facts, fences old contexts and clears failure counters only on an actual matching-scope recovery. CP3 and StandardCommandReplyV1 are unchanged.
- Exact accepted continuation tokens are tied to the originating cached scope/sequence, consumed when issued and held in at most 64 bounded entries. Unknown, modified, wrong-scope, replayed or evicted lineage receives the ordinary floor. Provider waits apply to all continuations. Cache eviction grants no resource retirement.
- All 13 Observation kinds enforce their source owner in Python/Rust/TypeScript, including unavailable values. Cleanup receipt resources must match their targets in all three consumers; the renderer also retains and compares the requested cleanup operation. Correct receipts and receipt-free waits remain valid.

### Evidence

The published-parent regressions reproduced 33 assertion failures across source ownership, credential wait scope, cleanup feedback and unissued cursor privilege, with zero setup errors/skips in the corrected RED run. A separate shared cleanup-resource regression adds one actual parent failure while its normal control passes. The initial fixture setup diagnostics are retained separately and are not counted as product RED. The same requirement oracles remain in the final tests; fixture metadata now explicitly identifies issued cursors and internal read context.

Initial local checks: Python 3.12.7 source/HTTP/CLI/control/identity suites, frontend, Rust, TypeScript/build. The shared producer set includes the earlier 23 vectors plus exact/foreign cleanup-resource cases (25 total); one independent owner matrix covers all 13 known kinds and all four source labels in the three consumers.

- python: SUMMARY 286 0 0 0; Ran 286 tests in 9.916s. Log SHA-256 `a0373878b6d92b47fe9a8be0b1fb91923f13a7aff0163afa6356ba7115c3c93e`.

- frontend: ℹ tests 113; ℹ pass 113; ℹ fail 0; ℹ skipped 0. Log SHA-256 `0c6beaff9b453bfb1128650b2ce49e2e08110592d9ec572e3df24b04d9c3d84b`.

- rust: test result: ok. 44 passed; 0 failed; 0 ignored; 0 measured; 0 filtered out; finished in 4.22s. Log SHA-256 `ab5b17ee707dc0504b49954826e1311ede72f5161cc9506031a9852d6950dee8`.

- build: TypeScript and Vite build passed. Log SHA-256 `2b282b48b6be2a25ee2d77b25d56acf7c41c6a5b76c73fabf14b841f9026a2b6`.

Local source tests do not establish installed operation, native question/answer attribution, remote control authority or full P12/v1 completion. Final-head hosted CI and independent code/security review remain required. No service was installed or activated for this increment.


### Local interpreter evidence correction

The initial scoped Python run used the shell-selected Python 3.12.7. The preceding version label is corrected; its 286-method result and log digest remain historical evidence. The same published source/test bytes were subsequently checked in the declared isolated Python 3.14.2 runtime, with child `python3` pinned to that same runtime: 286 methods passed, zero failures/errors/skips, in 9.972 seconds. Log SHA-256 `e81992d7d309330fece5d3387c55e98608ef439cd2bb2b0f8e25390210ff9e04`.

No implementation, oracle, requirement pin or protected check changes for this correction. The exact f3e4cb0 hosted run 39544070488 also passed all four jobs, including Python 3.11 and 3.14.2; that hosted result is distinct from the local run and does not qualify a later head automatically.


### Identity-request rate-limit classification

A known HTTP429 during the built-in credential identity check is now preserved as
a known status, instead of being collapsed into an unknown transport error. The
existing read adapter then holds subsequent GETs and emits its credential-scoped
fallback policy. Header metadata unavailable in that phase remains unknown; it is
not invented as provider=0 or a known Retry-After. No request, credential, wire,
retry threshold or authority profile is added.

The actual published-parent fixture made two identity GET attempts after one
known429 and emitted no hint. The new regression fails on that parent and checks
one HTTP attempt, zero target reads and a 60-second fallback; a healthy
authenticated source read remains a successful control.

Final affected local Python 3.14.2 suites: 287 methods, zero failures/errors/skips. Log SHA-256 `63067387f16bb1f3af921e4b7753be4896fc60a4ed1a5492ae978d9061a0efd9`. The TypeScript/Rust implementation, wire fixtures and their prior113/44 checks are unchanged; new-head hosted CI and independent reviews remain required. Installed/native operation remains NOT RUN.


## Credential rotation and the ordinary remote poll floor

An actual credential-context change now invalidates the obsolete ordinary
remote-start timer together with that credential's remote cache and ordering.
An unchanged context retains its floor. The new credential can rebuild an empty
remote cache immediately and its successful read starts a new floor. Independent
local data/timing and credential-scoped provider waits are retained; rotating
back to a limited credential does not erase its provider wait.

Identical final Rust test bytes reproduce two actual assertion failures on
published 83204b600f96753738c8e392b6eaa2489336e198: the new credential is held
for the old ordinary interval, both with and without a late previous-credential
provider hint. With the one-line production correction, all 45 Rust tests pass
without failures, ignored cases or filters under Rust 1.94.1. Python fixture
children use 3.14.2. The actual locked frontend was built for the Rust test
context under supported local Node 24.5.0; hosted CI retains Node 24.21.0.
The initial missing-frontend build setup error is separate from this RED proof.

P12 Rev4/CP8/NC8, provider quota policy, wire and command authority remain
unchanged. Existing UI source bytes are unchanged; this result is a Rust cache
behavior qualification, not an installed-app or native-operation observation.
Final-head hosted CI and independent reviews, protected merge and exact-main
verification remain required.
