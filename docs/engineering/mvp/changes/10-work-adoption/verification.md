# P10 verification

Evidence below belongs to its stated increment. Data validation, source delivery,
production source qualification, enabled commands and actual operation remain
separate outcomes.

## Original fixed-draft reader

This increment implements P10 revision 4, R04's fixed-payload read boundary
and R07's GitHub draft-source qualification, using WR section 8.
The accepted P10 and WR revisions are unchanged.

### Behavior and boundary

A work-create draft preserves its exact title, body, creation key, target,
source and optional parent goal. Closed schemas, duplicate JSON keys, UTF-8
budgets and matching final creation markers are checked before use.
The draft comment parser frames the JSON value before its HTML terminator,
so comment text inside a quoted body remains payload data.

The GitHub reader authenticates the selected account and repository mapping,
reads the exact comment and source Issues, and rechecks their identities and
revisions before returning a transient value. Publisher, source, goal,
credential or repository changes prevent an available result. Reads are
bounded by the caller's budget and a 45-second, 32-request local ceiling.

The result contains source data, not delegation, disclosure permission,
duplicate-absence evidence or execution authority. No creation handler,
MCP capability, native preparation reader or installed profile is enabled.
Private native references are not accepted inside public draft payloads.
An unavailable native source produces no fallback read or payload echo.

### Deterministic evidence

- The 21 fixed-draft methods reproduce 54 assertion failures against the
  unimplemented boundary, with no errors or skips. A corrected capacity
  fixture independently establishes that canonical payload bytes can exceed
  the total limit while body bytes remain within their own limit.
- The 13 GitHub-reader methods reproduce 19 assertion failures against an
  unavailable-only reader, with no errors or skips. Positive controls require
  a genuinely available fixed source and fresh repeated reads.
- The same test bytes pass after implementation. The final related run passes
  all 151 methods with zero failures, errors or skips under Python 3.14.2.

The final bundle includes `test_work_drafts.py`,
`test_github_work_drafts.py`, `test_work_records.py`,
`test_work_dependencies.py`, `test_work_inputs.py` and `test_github.py`.
It covers valid Unicode, exact body preservation, schema and byte limits,
copied/edited comments, source and parent changes, repository changes,
credential rotation, nested budgets, late responses and oversized data.
The injected transport rejects every write.

### Actual GitHub source observation

On 2026-10-24, one data-only draft comment was posted by the selected
`openboa` account on the existing public Hydra Issue, then recovered through
the actual GitHub reader:

[Fixed source observation](https://github.com/openboa-ai/hydra/issues/3#issuecomment-6382474829).

The bounded observation made ten GET requests and one fixture-comment POST.
Exact comment revision, draft digest, selected publisher and original Issue
content matched. No Issue creation, delegation, native task, installed
operation or business execution occurred. The synthetic outcome key is
fixture metadata, not a qualified semantic outcome identity.

The default secret scan reported two generic-key matches in that generated
fixture. Both were independently reconstructed as the exact generated UUID
and SHA256 of public fixture metadata. The findings are retained and
classified as noncredentials; the scan is not reported as clean and its rules
were not changed. Product-source scans remain a separate delivery gate.

### Original completion boundary

The original source increment required final-source hosted CI, independent
code/security review, protected merge and actual-main verification.
At that boundary, full P10 still required interpretation and adoption evidence, the typed
creation contract and handler, ambiguous-result recovery, binding and anchor
read-back, applicable app consumers, relationship preparation, and actual
creation and model-quality acceptance. This increment does not complete
P10 or Hydra v1.0.0.

### Integration with verified project connections

The source increment is integrated with protected main `46e8c03`, whose actual
merge revision passes kernel, Mac and trusted hygiene checks. The original
four draft-source implementation and test files remain byte-identical.
The combined draft, work-record, GitHub and connection regression run passes
198 methods with zero failures, errors or skips.

This records the source-integration boundary at that revision. Work creation,
adoption, native operation and full P10/v1 acceptance remained open there.
Subsequent registration delivery is recorded below.

## Guarded registration delivered in PR43

[PR43](https://github.com/openboa-ai/hydra/pull/43) implements the first
effect-capable registration increment under P10 revision 5, WR revision 6 and
CP revision 12. It resolves the fixed authenticated draft/proposal, current
delegation and immutable references, then permits one fenced Issue/binding
sequence under independently qualified original-outcome history and current
execution ownership. Exact read-backs establish registration. Uncertain results
preserve the original effects and cannot obtain a new first-use permit.

Cancellation prevents later effects and drains the owned worker before returning
the original cancellation. The seven cancellation regressions also require zero
unhandled provider diagnostics. The final local related run passes 384 Python
methods; 421 frontend methods, 72 Rust methods and eight platform unit fixtures
pass. Platform fixtures are not native operation evidence.

[Source CI40176070458](https://github.com/openboa-ai/hydra/actions/runs/40176070458)
and [actual-main CI40177497204](https://github.com/openboa-ai/hydra/actions/runs/40177497204)
pass all three jobs. Each Python run collects 2,191 methods: 2,183 pass and eight
platform methods are skipped on Linux and covered locally on the same source.
Actual code and security reviews completed clean on final head `93585c7`.
Protected merge `7ed94a6` has the same reviewed/tested tree, its expected sole
parent and successful main checks. The merged source branch is retired.

This proves source delivery. The production creation-history producer remains
unsupported; no installed profile, business work or native source was activated.

## App registration-receipt data boundary

The Rust and TypeScript readers consume CP12's exact work_create data grammar.
They validate the registered stage, safe positive repository/Issue IDs, canonical
UUIDv4 and RFC variant, three SHA256 digests, exact Issue reference, comment
locator syntax, action/target consistency and both observed effect references.
Comment locator syntax establishes no publisher authentication.

The shared `creation-receipts.json` oracle declares 60 normal and invalid variants.
`emit_creation.py` obtains normal, replayed, missing-history and partial-Issue
responses from the real Registration/common command path with isolated synthetic
dependencies. No network, native task or production authority is involved.
One actual Python output crosses the Rust reader and the actual TS parser.
The test-only channel sends every invalid or unsupported wire onward for its own
TS validation; runtime forwarding rules are unchanged.

Before implementation, the permanent tests reproduce four TypeScript assertion
failures and one Rust data-boundary failure, without collection/runtime errors.
The same 60 cases and expected statuses pass afterward: six Python methods
(including contract conformance), 61 frontend methods and one Rust round-trip
method. The test harness accepts early rejection by the real JSON reader as a
data failure; it does not unwrap deliberately invalid numeric wire as valid data.

A valid applied creation receipt still reaches `unsupported_command_source`.
Malformed data fails as `invalid_response`; actual unknown/partial responses
retain their observed references and null receipt. The existing bound source
gates and reducer remain unchanged, so the new grammar does not enable an app
command, applied feedback or replacement source facts. The original tests and
source qualification expectations remain in force.

The affected Python run passes 389 methods with zero failures, errors or skips.
All 482 frontend methods and 73 Rust methods pass; theme verification, typecheck
and the frontend build pass. Independent code/security reviews, final-head CI,
protected merge and actual-main verification remain required for this increment.
Production history, enabled app command/correlation, initial
progress/attempt anchoring, relationship preparation, adoption-quality evaluation
and applicable live acceptance remain open. Full P10 and Hydra v1 are incomplete.
