# P10 verification: immutable GitHub work drafts

This increment implements P10 revision 4, R04's fixed-payload read boundary
and R07's GitHub draft-source qualification, using WR section 8.
The accepted P10 and WR revisions are unchanged.

## Behavior and boundary

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

## Deterministic evidence

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

## Actual GitHub source observation

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

## Remaining responsibilities

Final-source hosted CI, independent code and security reviews, protected
merge and actual-main verification remain required for this source change.
Full P10 still requires interpretation and adoption evidence, the typed
creation contract and handler, ambiguous-result recovery, binding and anchor
read-back, applicable app consumers, relationship preparation, and actual
creation and model-quality acceptance. This increment does not complete
P10 or Hydra v1.0.0.
