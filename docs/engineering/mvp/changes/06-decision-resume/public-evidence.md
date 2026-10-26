# P06 public decision evidence

## Revision 7: delegated publication and ordinary continuation

The delegated increment has two separate effect ceilings. Native-only
`workflow_step.decision_submit` can publish one exact context and one matching
receipt per invocation. A separately authorized `workflow_step.continue`
consumes the authenticated version-2 pair and resumes the original phase.
Native handoff has its own explicit grant. The original `decision_apply`
profile and its untagged receipts retain their previous source requirements.

`native_workflow_control` is absent/disabled by default. Its closed protected
configuration requires schema version 1, enabled, repository IDs, operations
and a canonical UTC expiry. The real MCP dispatcher selects the parsed target
and operation; it never unions admission/workflow grants. Runtime identity
changes with every authority field. Proposal text and claimed approvals cannot
grant Resume, policy changes or other effects.

An exact `hydra-decision-v1` owner uses the existing coordinator inode. Context
and receipt reservations each retain a lifetime ceiling of three. Before a
physical POST, the incremented counter must survive complete file writes,
file fsync and verified parent-directory fsync. Decision operations require an
existing real parent; they do not create an unsynchronized ancestor chain.
Failures retain conservative ownership and prevent dispatch. Partial positive
writes may finish on the same inode; failed persistence never yields a permit.

Mutable resume binds the entire intended record, exact public root and original
progress ResourceRef. Its live creator can dispatch one PATCH. Reboot/retry does
not reconstruct that permit. Exact late-result recovery rechecks the original
record and comment identity inside the final current-policy/admission guard
before retiring ownership. Identical content at a different comment ID remains
held. An unknown result cannot allocate another attempt or assignment.

All 64 delegated feature methods pass, including actual local SDK production,
five-phase continuation, expiry/scope separation, Pause, durable retry bounds,
lost acknowledgments, original-ID replacement, shared deadline, private-error
exclusion and v1 compatibility. File/directory synchronization and reboot
boundaries use deterministic fault injection; no physical power-loss trial or
installed-runtime qualification is claimed. The shared wire corpus also passes
the actual Python/Rust/TypeScript source boundaries; see
[P04 verification](../04-native-answer-source/verification.md).

The historical sections below describe the original public-decision component.
Source implementation does not complete P06/v1 operation. Actual remote native
questions/answers, explicit Resume, controlled business progress, installation,
final-head delivery and two-project acceptance remain separate gates.

## Original-profile component evidence

This implementation covers step 3 of [P06 revision 2](spec.md), using the exact
public intent and receipt contract in [EX revision 7, §7.3](../../contracts/execution.md#73-공개-결정과-유실재시작-복원).
It is a source component for later integration. Full P06, native answer
acceptance, `decision_apply`, continuation, and operating acceptance remain open.


## Current review corrections

Versioned claims for the selected decision are inspected even when a trusted
comment's first line is altered or prefixed. Marker payload parsing is bounded to 16 KiB and establishes
relevance only; full framing and exact bytes still decide validity. A long body
for a valid unrelated key cannot block the selected decision. A marker
whose key cannot be read is held. Known outsiders and valid unrelated keys remain
excluded, so they cannot block a healthy trusted pair.

Selected and previously pinned context/receipt references retain separate roles.
Any overlap returns unknown instead of allowing context membership to validate a
receipt pin. Direct GET read-back, source identity and the existing read budget
are retained. The first public registration is round 1; later public replacement
rounds require the same work's immediately preceding context pin. This structural
codec check does not establish that a predecessor was actually observed or accepted.

The same ten final methods reproduce 23 assertion failures on actual published
parent `d838ce329b3389901f8fb1c1258999b971eeb1e6`, with no errors or skips.
The correction passes all ten methods and all 110 selected public-reader,
GitHub/read-budget and checkpoint-continuation methods on Python 3.14.2, with
no failures, errors or skips. Healthy pairs, outsiders, unrelated keys, disjoint
recovery pins, initial rounds and explicitly pinned replacements are positive
controls. A 24-row matrix crosses full key, actor, framing and body size, and
reproduces three assertions on published parent ec4392c. Marker-bearing records
are classified by their full key before either actor uncertainty or selected-body
framing limits can block the decision. Legacy handling is unchanged.
Existing P06 Rev2 / EX7 / CP7 / NC8 pins remain unchanged.

Final-head CI, independent review, protected merge and actual-main checks remain
delivery gates. Native answer provenance, authority, application, Resume and full
P06/v1 operating acceptance remain separate requirements.

## Actor reconciliation correction

Two additional review regressions reproduce 14 assertion failures on actual
published parent 8651df0, with no errors or skips. Pinned context and receipt refs
must agree on numeric user ID and login in every listed copy and the direct GET;
unrelated user metadata does not change identity. Outsider exclusion counts use
the same full-key relevance predicate as classification, including damaged headers
and other keys sharing a source attempt. Both new methods and all twelve guard
methods pass. All 112 selected reader, GitHub, read-budget and continuation methods
pass on Python 3.14.2, with no failures, errors or skips. The previous 24-row
relevance matrix and accepted contract pins are retained.

## Responsibility and interface

`hydra_sdlc/public_decisions.py` keeps the protocol separate from the existing
legacy GitHub decision path. It does not change legacy resolution or enable a
new command, capability, default source, or installation profile.

- `prepare_context(public_text, basis)` snapshots a caller's public-safe proposal
  into canonical UTF-8 bytes. `parse_context` accepts exact canonical read-back
  bytes; it does not normalize a provider's response. Unknown or duplicate JSON
  fields, invalid numbers/UUIDs/pins, malformed frames, and context overflow are
  errors. The 16 KiB context limit never truncates content.
- `receipt_body(context)` derives the receipt from the verified context's public
  key and body digest. The model does not regenerate its payload or resume UUID.
- `observe_comments` folds service-owned, byte-identical physical duplicates into
  one semantic pair and picks the smallest numeric comment IDs for display.
  Different trusted payloads conflict; outsider copies do not block a valid pair.
- `read_public_decision` uses an injected `GitHub` client to verify the current
  service's numeric ID and login, repository numeric ID, Issue, complete comment
  collection, and direct selected refs. A transient read budget limits the
  observation to 30 seconds and 32 requests, including nested authentication
  requests. Every request is a GET. Previously observed refs must be supplied
  when recovering evidence about those refs.

The caller must obtain a public-safe proposal from the qualified private source
before using this component in a writer. Free text remains data; this codec does
not certify that arbitrary prose contains no private information. Metadata is a
closed public schema and includes no private question, answer, identity, or path.

## Results and failure meaning

| Observation | Meaning |
| --- | --- |
| `pair` | Exact authenticated context and derived receipt were observed. |
| `context` | Only the expected context was observed. |
| `receipt_without_context` | The receipt lacks the required observed context. |
| `not_observed` | This completed read found neither expected record. |
| `conflict` | The same public key has a different trusted payload. |
| `unknown` | Coverage, actor, source, edit metadata, identity, or pinned refs could not be established. |

None is evidence of human acceptance, permission, applied progress, dispatch, or
actual execution. An empty collection, timeout, or 404 never proves that an
earlier POST was not dispatched. This component has no write or retry operation.

Unexplained edits or changes to a known ref hold the observation. Comment edit
metadata does not establish immutable storage or reveal every historical edit.
Without previously observed refs, this reader cannot establish their deletion.
Public timestamps do not establish authority or the order of prior dispatches.

## Verification and integration boundary

`tests/test_public_decisions.py` uses a literal wire oracle, public-body digest,
UTF-8 byte boundaries, strict schema failures, semantic duplicates/conflicts,
outsider copies, provider edits, partial coverage, direct-ref changes, identity
rotation, pagination budgets, and a transport that rejects every non-GET call.
These cases cover the public evidence portion of EX-D12/17/18/24. Run with:

```sh
python3 -m unittest discover -s tests -p 'test_public_decisions.py' -v
python3 -m unittest discover -s tests -v
```

The normal pair must succeed, so always returning `unknown` is a failure. Trusting
an outsider must also fail. Deliberate fault controls establish those properties;
they are not claims that the published parent contained these injected defects.

No model judgment changes in this component. Deterministic fixtures do not
replace the native provenance, authority, coordinator, admission, effect ordering,
response-loss recovery, or real operating evidence required by the rest of P06.
Those gates must be connected and qualified before decision application is enabled.
