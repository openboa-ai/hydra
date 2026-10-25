# P14 publication and protected delivery: implementation and verification

Scope: [P14 revision 4](spec.md), the publication portions of R1/R3/R6/R7 and T03/T08/T10;
[CP revision 9](../../contracts/control-plane.md), [EX revision 8](../../contracts/execution.md),
and the maintained [implementation contract](../../../github-workflow/spec.md).
The publication history is retained below. The bounded direct-delivery increment has its own source evidence below; full P14 and v1 operational acceptance remain open.

## Result boundary

`workflow_step.publish_candidate` uses the existing guarded command dispatcher,
owned coordinator and Runner effect engine. An exact candidate already verified
and independently reviewed can be pushed to its owned branch, obtain its owned
PR and confirm the required remote-review requests. A standard reply includes only
the actual `branch_published`, `pr_ready` or `publication_ready` receipt.
Review approval, merge, main acceptance and resource retirement are later outcomes.

Verification and publication share current caller, installation and loaded-provider
binding validation. Publication requires its own exact grant. The default and
optional installation admission profiles do not gain workflow authority.

New effects require the same clean candidate, current accepted spec/intake/policy,
current base, actual private candidate acceptance, current admission and original
progress. Each writer rechecks its source immediately before mutation. The fixed
publication ceiling rejects a checkpoint, another provider callback, new model or
verification work, merge and Issue close.

Unresolved effects retain their original intent. Matching branch/PR/request
read-back is reused; missing or contradictory observations remain unknown.
A private bounded witness permits an exact positively undispatched intent to
continue after authority returns, without charging another request or changing
its pins. Restart does not reconstruct a missing witness. An already confirmed
publication can be rediscovered from its actual external results. A matching
partial PR or review request is acknowledged before checking private acceptance
for remaining new effects. This does not recreate the lost acceptance marker.

Commit messages, existing PR text and the actual proposed title/body are checked
for early Issue-closing intent. The current producer's identity and revision
bindings are checked independently from request receipt and approval semantics.
The MCP event loop can answer Pause during provider reads; the publication worker
drains before releasing ownership, and Pause remains effective for later effects.
Publication reads only the PR, complete commits and complete Issue comments,
then rechecks the relevant PR anchor and counts. It uses a fresh client with a
15-second/32-request budget, without borrowing another caller's budget. CI,
protection rules and review threads remain separate delivery observations;
their absence is never fabricated as empty successful evidence.

## Deterministic evidence

The tests use Python 3.14.2, pinned MCP 2.3.0, actual temporary Git repositories and
registered subprocess verification. They make no external publication or native
installation changes.

| Requirement boundary | Independent oracle |
| --- | --- |
| Actual exact publication | A reviewed candidate reaches the real temporary remote and one owned PR; the verifier count stays one, HEAD is unchanged and no delivery/model/commit effect occurs. |
| Current authority and source | Grant revocation at push and foreign source at the actual progress writer hold; restored authority can continue only the original positively undispatched intent. |
| Candidate completion | Dirty/stale pins, wrong branch/expected head, missing actual review acceptance and unfinished correction cannot publish. |
| Pause and recovery | Pause actually applies after the admitted push callback returns. A partial receipt survives; explicit Resume completes the same PR without another push. |
| Lost responses and restart | PR ACK loss with temporarily unavailable read-back and completed-publication restart reuse actual owned results without duplicate push/PR. After restart, a confirmed partial PR clears its original intent even when private acceptance is gone; no new request runs without that acceptance. A lost code-review request is settled before requesting security, and hidden read-back never causes retransmission. |
| Request evidence | Required code/security requests have actual comment refs; request readiness does not wait for or claim approval. |
| Public payload | Candidate commit messages and both proposed PR fields cannot introduce premature closing intent. |
| Producer uncertainty | Conflicting legacy revisions and malformed author observations return typed unknown; source recovery avoids duplicate publication. |
| HTTP read boundary | The actual GitHub client and command reader progress without CI/protection/thread APIs. Changed source anchors, incomplete counts, pagination overflow and deadline expiry cannot return partial success or consume another caller's read budget. |
| Real SDK and fixed effects | The same six-tool MCP server routes publication and can apply project Pause during a blocked provider read. Unrelated workspace/provider effects are rejected. |

Negative controls reproduce the missing publication profile on the unchanged
main runtime. The actual post-effect Pause control independently fails there and
passes on the implementation. Six additional payload, producer, lifecycle and SDK
controls reproduce five purpose failures before correction and all pass afterward.
Two partial-effect recovery controls each fail before the reconciliation change;
the same unchanged controls both pass after it, without errors or skips.

The earlier implementation passes 686 affected methods, including all 115 prior
native verification cases: no failures or errors, with three explicit local
environment skips (non-UTF-8 filenames and the Linux subreaper). The publication
reconciliation change passes its 24 feature cases without errors or skips. The
subsequent HTTP read change has five unchanged negative controls (eight
assertion/subtest failures) and the same five passing controls. The final source
passes all 179 combined publication/GitHub impact methods, including all 29
publication cases, without failures, errors or skips. The earlier broad result
is not represented as a final-revision full-suite result.

Appending the maintained workflow contract makes its two whole-document manifest
references stale. The unchanged collector fails that negative control. Refreshing
only those exact digest references preserves the cases, sections, selectors and
fixtures; the same collector and two CI boundary cases pass. Validators, required
checks and test criteria are unchanged.

A bounded GET-only observation with the current source client also read actual
[PR #32](https://github.com/openboa-ai/hydra/pull/32): exact head `f5d5182`, ten
commits and two Issue comments, with matching counts and anchor, in 2.723 seconds.
This confirms that narrow read's API compatibility. It does not execute the
publication command or qualify an installed/native control connection.

Final-source CI, independent code/security reviews, protected delivery and actual
main checks remain pending for this candidate.

## Integration with current connection guards

The existing publication branch incorporates verified main `7a9db88fa66f5a16f1e3129b65bf2d2a0ef87dc0`
through a normal feature-branch integration. P14 revision 4 remains unchanged.
The current project-connection guard, public MCP controls and bounded
publication route are preserved together. No installation grant is activated.

All original publication, guard, reconciliation and bounded-read assertions
are byte-identical. Three additional integration cases use actual temporary
configuration, admission stores, registered verification and Git remotes.
Missing explicit running admission rejects publication; a connected/running
scope publishes its exact candidate and one owned PR; changing the fixed
configuration to disconnect immediately before the real push prevents that
writer from dispatching, even with the original cached controller.

The three cases pass with no failures, errors or skips. The initial
251-method impact run passes 249 methods, including all original 29
publication methods and the three integration cases. Two admission cases
fail because the custom local runner launches their children outside the
candidate checkout and loads a preserved older checkout. Bounded import
probes independently confirm the different source locations and digests.
After selecting the candidate working directory, all 45 unchanged admission
cases pass with no failures, errors or skips. The original failures remain
recorded; the 251 unique methods are covered across those runs, without
claiming a single 251-method passing execution. No product source or test
assertion changes for this runner correction. The three new cases are
integration controls, not a new-feature RED claim. The prior behavioral RED
evidence remains in the original publication record. Python source and root
test bytes match that impact run; the additional upstream app changes retain
their own exact-main CI. Only the two maintained-contract manifest digests
change; selected cases, five selectors, sections, exclusions and fixtures
retain their original meaning.

New exact-head CI and independent code/security reviews are required after
integration. The earlier source CI and review history are retained as
historical evidence. No source test qualifies installed or remote operation.

## Independent review corrections

Review of `b173961` identified three publication-boundary defects. This source
correction reuses P14 revision 4 and the existing effect/authority contract.
The original reviewed source and all earlier test assertions remain preserved.

The final pre-change matrix adds ten independent methods and reuses the original
exact-null-expectation restart control. Three normal controls pass; the remaining
cases produce twelve purpose assertion failures, without errors or skips.
The same eleven methods pass after correction. The initial nine-method probe is
retained separately from the refined, ownership-validated external-PR case and
the additional receipt-source budget case.

- A command's remote expectation must equal authenticated progress. A matching
  current remote ref cannot substitute for that source. Existing known-intent
  recovery still accepts the original null expectation after an observed push.
- Incomplete unrelated comments cannot erase valid owned review-request evidence.
  Comments claiming review evidence and configured producer comments retain
  strict identity/format checks. Request readiness remains distinct from approval.
- A complete publication observation uses one fresh 15-second/32-request client
  for branch, PR list, ownership, receipt source, commits, comments and identity.
  Payload preflight owns the same bounded read profile. Neither scope consumes
  another caller's budget, resets the deadline midway or replaces runner.github.
  Separate effect writes and workflow guards retain their existing contracts.

All 80 publication/GitHub impact methods pass without failures, errors or skips,
including all 42 publication methods and the original actual-Git/SDK recovery
paths. The ten new methods and the prior assertions are unchanged from their
final pre-change definitions. Source tests do not establish installed operation.
New exact-head CI and independent reviews are required after this correction;
earlier CI/review observations do not qualify the corrected revision.

## Integration with optional Project priority reads

The publication candidate incorporates verified main `399cd7a9e86ac92981c87bed39d36628475e5159`.
All original publication assertions and GitHub adapter methods are preserved.
The integration includes the optional Project reader without changing
publication authority or activating any installed operation.

All 111 selected Python 3.14.2 publication, GitHub and Project-planning
methods pass with zero failures, errors or skips. This is integration
regression evidence; it does not replace final-head CI, independent
code/security reviews, protected delivery or actual operational acceptance.

## Candidate-update and preflight review corrections

A newly reviewed correction can update its existing owned PR from the exact
prior head authenticated in progress. This allowance applies only before the
current candidate is confirmed published. Later PR observations and review
requests still require the exact candidate head; earlier reviews cannot approve
the correction. A lagging PR read is held and reconciled after restart without
another push. An externally rewound confirmed candidate is held.

Initial repository resolution runs in an awaited worker. Current caller/runtime
binding and admission are validated again after that read and before effects.
The MCP event loop can serve another callback during the provider lookup.

Three new regression methods produce three assertion failures before correction,
with zero errors or skips; the existing valid publication control passes. All
four focused methods pass after correction. A fourth new method retains the
external-rewind guard. All 115 selected publication, GitHub and planning impact
methods pass with zero failures, errors or skips. Earlier test assertions and
the original three new regression oracles are preserved. New final-head CI and
independent code/security reviews remain required. No live operation is claimed.

## Bounded direct-delivery increment

This increment implements the direct delivery portions of P14 revision 4,
R1–R4/R6/R7 and T01–T04/T08/T09/T11, using the maintained CP profile.
An independently granted exact published candidate/PR/base proceeds through
the existing merge engine, immutable squash reconciliation, exact-main check
observation and conditional Issue close. The shared completion engine preserves
the earlier broad path while the closed command retains cleanup responsibility.

The delivery command has no publication, verification, model, assignment,
repair-registration or resource-retirement effect. Queue-required and incomplete
protection observations hold. Unknown merge and close effects stay unknown
across repeated calls and restart; a matching late result can resume completion.
A newly confirmed undispatched intent can continue after explicit Resume,
without repinning or charging another request. Historical recovery uses the
original integration base even when main advances.

The original ten delivery test methods are preserved. An independent input
probe found that the inherited fake provider used a different current main
and integration base from the actual temporary Git fixture. The local fixture
now models actual main, current/pinned policy revision, PR CI association base,
changed paths and immutable squash parent separately. Its independent valid
candidate control passes the real delivery gate before implementation.

The fourteen final behavior oracles produce eleven intended assertion failures
before implementation, with three passing controls, zero errors and zero skips.
Those same fourteen methods pass after implementation. Additional source guards
cover malformed pins and authority, required queue and incomplete observations,
authority revocation, a newer failed main run at close, unknown close after
restart, the cleanup ceiling and cancellation of an already sent writer.

Final provider payload tests reproduce seven assertion failures across two
methods before correction, while the valid squash control passes. The adapter
then rejects current closing-intent PR text and sends a fixed safe squash title.
Existing API payload assertions are strengthened to include that title.

A separate admission-order oracle reproduces two assertion failures when
publication/delivery hold admission during final reads. It uses event ordering,
not a latency threshold. After moving preflight and progress read-back outside
the lock and retaining the final guarded writer, all six admission/payload
methods pass, with no errors or skips.

The initial 501-method Python 3.14.2 impact run completes 500 methods without
failure. One exact-payload assertion fails in eleven subtests because its
expected request omits the new fixed squash title. Adding that specified field
preserves every other assertion; all 27 squash regression methods then pass,
with zero failures, errors or skips and no product-code changes. These runs
cover 501 unique methods, without claiming a single passing 501-method run.
Three additional methods
then reproduce three assertion failures with zero errors or skips: bounded
progress-source reads and lost merge/close-intent acknowledgments. Only the
delivery profile changes afterward; all earlier Python source and assertions
are preserved. The same three oracles pass in a final 32-method delivery-profile
run, including all fourteen original contract methods and the admission/payload,
unknown-effect, cleanup and cancellation guards. The runs cover 504 unique
methods without claiming one 504-method passing execution. Exact-head CI,
independent reviews, protected delivery and actual main checks remain required. Source fixtures do not qualify
an installed authority grant or native remote operation.

## Review correction: delivery waits and completed replay

Independent code reviews identify recovery defects under P14-R3/R4/R7.
Main checks can change after a close intent is saved. This owner's wait-only
updates preserve an already-known undispatched intent, without creating that
proof for an unknown request.

Completed replay reports changed candidate, review, squash or main-check
evidence without rewriting confirmed completion or silently closing a
human-reopened Issue. The common delivery-wait boundary handles those fresh
observations. Explicit owned cleanup retains its separate responsibility.

Six new methods reproduce six assertion failures before the first correction.
Three additional methods reproduce three failures for changed candidate-review
evidence in both the narrow and shared broad paths. The earlier seven review
methods are preserved unchanged. All ten review regression/control methods
pass in the final 93-method completion/recovery run, with zero failures, errors
or skips. That run also includes post-merge checks, squash evidence, active
labels, policy completion and review recovery.

The shared broad path preserves terminal progress instead of fabricating a new
closing intent during label-cleanup recovery. Two existing active-label
expectations require completed history and no pending close; their ownership,
discovery, no-model, no-close and cleanup assertions remain. A cleanup positive
control passes before this shared-path refinement. The original fourteen
delivery contract methods remain unchanged.

An earlier 288-method impact run on the preceding published candidate has
287 passes, zero failures or errors and one unchanged Linux-only ownership
case skipped on macOS. The final-head Linux CI must execute that case
successfully. The original skipped result is retained; the later 93-method
run is not presented as a single combined passing 288-method execution.

These source checks require fresh exact-head CI and independent reviews before
protected delivery, followed by the actual merge revision's checks. They do not
qualify installed commands, remote native operation or full P14/v1 acceptance.

## Remaining qualification

The earlier main-CI preservation increment was delivered separately in
[PR #9](https://github.com/openboa-ai/hydra/pull/9). It does not establish this
publication command, actual consecutive-push O05, or the rest of P14.

These local source/SDK fixtures establish deterministic behavior only. Selected
installation authority, authenticated native operation, the actual remote first
flow, two-project acceptance, complete D/L/O and resource closure remain open.
Required-queue adapter support, post-merge repair and requirement acceptance retain their maintained contracts and later verification. The direct delivery source increment does not complete those obligations.

## Integration with verified connections and draft sources

Protected main `f431912` passes its actual merge-revision CI. Its tree equals
the draft/connection baseline used by this integration run. All original
delivery runtime files, delivery regression assertions and fourteen native
delivery oracles remain byte-identical to the preceding reviewed candidate.

The focused combined connection, draft, GitHub and verification-contract run
passes 202 methods with zero failures, errors or skips under Python 3.14.2.
An earlier run retains one CI-shell failure caused by the private runner
selecting Python 3.12. Correcting only the runner PATH makes the unchanged
202-method suite pass; product code and test expectations are unchanged.

A broader local run was stopped after 73 observed passes when byte comparison
showed its previously qualified delivery code and tests were unchanged. It
is retained as partial evidence and is not a complete passing run. Fresh
final-head CI still runs the complete suite and independent code/security
reviews still apply before protected delivery. Actual merge verification,
repair integration, installed operation and full P14/v1 acceptance remain
separate obligations. The two refreshed requirement hashes preserve all
existing selectors, cases and evaluation criteria.

## Integration with input-evidence comparison

The protected main from PR #41, `b2f27b9f361127c987f3e3e088cc79fc95805417`, passes its actual-merge CI. This delivery candidate preserves the P11 implementation and tests, all original delivery runtime files and all original delivery test oracles. The combined compatibility run passes 208 methods under Python 3.14.2 with zero failures, errors or skips.

Fresh final-head CI and independent code/security reviews are required before protected delivery, followed by the actual merge revision checks. Repair integration, effective requirement fulfillment, installed operation and full P14/v1 acceptance remain open.

## Full observations and external-close recovery

Two review regressions fail on the unchanged published candidate with two assertion failures and zero errors/skips. The same methods pass after correction. Full PR observations use a separate bounded allowance while progress reads retain their smaller budget; request/time exhaustion and foreign ownership remain holds. Verified external closure is reconciled without another close, preserving unknown-open requests and completed history.

The related 183-method regression bundle and seven focused methods pass under Python 3.14.2 with zero failures, errors or skips. The final focused control also covers external closure during the close-intent recheck. Existing test bytes and accepted requirement/spec revisions are unchanged. Fresh final-head CI and independent reviews, protected delivery and actual-main qualification remain required. Full P14/v1 and installed native acceptance remain open.

## Authenticated squash receipt before completion

Three unchanged purpose regressions fail on the published parent with three assertion failures and zero errors/skips. Late merge success plus external Issue closure now records the authenticated squash receipt in the same owner and after controller restart. Failed main checks retain that receipt while completion remains held. The prior progress stays the write fence until the exact transition is written and read back.

Recovery and its final write guard share one immutable-result/correlation validator. Six focused cases and 109 related methods pass on Python 3.14.2 with zero failures, errors or skips. Controls reject correlation changes during the recovery write and unrelated transition fields; an acknowledged merge followed by external closure also completes without another close. The three original purpose methods and all earlier delivery test bytes are preserved. A separate capacity assertion reproduces the insufficient outer CI allowance; three CI contract methods pass after the documented bounded capacity adjustment. All behavior cases and their deadlines remain.

The previous source CI cancellation is not a pass. Final-head CI and independent code/security reviews, protected merge, actual-main verification and retirement remain required. Full P14/v1 and installed native acceptance remain open.

## Authenticated post-merge investigation context

Scope: [P14 revision 5](spec.md), the source-context handoff for R4/R5 and
T14–T22; EX revision 10, GI revision 2, CP revision 12 and WR revision 6.
The baseline is protected main `a4fca55` from [PR #44](https://github.com/openboa-ai/hydra/pull/44),
whose [actual-main CI](https://github.com/openboa-ai/hydra/actions/runs/40181630170)
passes. That baseline result is not verification of this new increment.

The actual GitHub reader feeds existing Runner status, NativeController status
and `hydra_status`. An eligible authenticated row gains bounded origin, required
current-check references and separately observed historical failure references.
Current snapshots settle before optional history. No new MCP tool, projection
fact, durable state, model, assignment or provider mutation is added. Existing
delivery acceptance and protected write gates retain their prior behavior.

The pass owns a fresh read client. Typed collection pagination verifies actual
declared totals, stable counts, unique safe IDs and complete bounded pages.
These checks apply only to enrichment; legacy readers are unchanged. Required
failure evidence survives uncertainty in another required source. Optional
history failure cannot erase current CI, and bounded output leaves room for
both axes' coverage and times.

Credential/account or observed same-repository disclosure changes invalidate
all affected siblings, including previously finalized snapshots. Authenticated
nested Actions metadata participates in this guard; omitted nested fields and
ordinary foreign metadata do not manufacture a disclosure transition. Runtime
provider errors become fixed source states before reaching SDK exception logs.

Permanent cases use real GitHub parsing/authentication, Runner/NativeController
and the pinned in-memory MCP SDK with a synthetic CLI/provider boundary. They
reject non-GET and workspace/model effects. They exercise current and historical
source qualification, nullable spec/cross-host origins, pending merge correlation,
latest reruns, incomplete collections, historical caps, bounded output, shared
and local transitions, Pause, retained closed discovery and restart. The real
MCP error case verifies both the structured reply and SDK logger.

The original 24-method oracle reproduces 39 assertion/subtest failures before
implementation, with zero errors/skips, then passes. Six boundary methods
reproduce six failures and pass unchanged after correction. Seven independent
review methods reproduce ten failures and pass unchanged after the collection,
disclosure and error-boundary corrections. The provider fixture now supplies
actual `total_count` envelopes; all original behavioral/protocol method ASTs and
the six boundary methods remain unchanged.

Before review corrections, 296 related delivery/recovery/status methods pass
under Python 3.14.2 with zero failures, errors or skips. Before the exact-ID follow-up,
212 focused/compatibility methods complete with 211 passes and one CI-shell
failure: the private runner's child PATH selects Python 3.12. Fixing only that
runner PATH makes the same unchanged shell method pass, including its required
skip rejection. Product code, workflow, collector and test criteria do not
change for that correction. These runs cover 212 unique methods; they are not
represented as one passing 212-method execution or a full-suite/remote-CI pass.

Four follow-up identity methods reproduce six failures for malformed nested
repository, PR author/endpoint and fallback repository IDs. Enrichment-only
exact-safe-integer checks prevent false shared invalidation, unqualified origin
and fabricated complete-zero history. The same four methods pass afterward;
all preceding 37 methods remain unchanged. The final source passes 113 related
methods, including all 41 context methods, post-merge source gates, producer
delivery readers and projection/fixture compatibility, with zero failures,
errors or skips on Python 3.14.2. Legacy ownership/read predicates are unchanged.

Exact final-source code/security review, final-head CI, protected delivery,
actual-main checks and branch retirement remain required. Actual-source/native
operation, diagnosis, one repair outcome, repaired fulfillment, initial dispatch
anchoring and full P14/v1 acceptance remain open. No installation or business
operation is activated by this increment.
