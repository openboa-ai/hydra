# P14 candidate publication: implementation and verification

Scope: [P14 revision 4](spec.md), the publication portions of R1/R3/R6/R7 and T03/T08/T10;
[CP revision 9](../../contracts/control-plane.md), [EX revision 8](../../contracts/execution.md),
and the maintained [implementation contract](../../../github-workflow/spec.md).
This record does not complete the separate delivery command or the whole P14 change.

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

## Remaining qualification

The earlier main-CI preservation increment was delivered separately in
[PR #9](https://github.com/openboa-ai/hydra/pull/9). It does not establish this
publication command, actual consecutive-push O05, or the rest of P14.

These local source/SDK fixtures establish deterministic behavior only. Selected
installation authority, authenticated native operation, the actual remote first
flow, two-project acceptance, complete D/L/O and resource closure remain open.
The separate `deliver` profile, queue-required routing, post-merge repair and
requirement acceptance retain their maintained contracts and later verification.
