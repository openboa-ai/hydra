# P06 public decision evidence

This implementation covers step 3 of [P06 revision 2](spec.md), using the exact
public intent and receipt contract in [EX revision 7, §7.3](../../contracts/execution.md#73-공개-결정과-유실재시작-복원).
It is a source component for later integration. Full P06, native answer
acceptance, `decision_apply`, continuation, and operating acceptance remain open.

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
