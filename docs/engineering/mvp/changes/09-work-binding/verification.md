# P09 binding read and restart identity verification

This record covers the read-only schema, explicit selection and exact-attempt
recovery stage of the maintained [P09 specification](spec.md), Revision 1, and
[work-records contract](../../contracts/work-records.md), Revision 5, at base
`d1ac65a98f93f8a2e2ade423aaf621287c96df42`. It does not complete all P09
requirements or activate github_native execution.

## Scoped behavior

The new pure module validates the closed WorkBinding v2, InputContract and attempt
anchor schemas, preserves canonical array order, and retains null/empty/Unicode
source bytes compatible with existing intake_digest. Fixed digest vectors do not
call the production serializer to calculate expected values. Returned binding
content is immutable and contains references rather than Issue prose copies.

Explicit selection requires the exact comment ID and digest, authenticated author
ID and login, unchanged creation/update timestamps, numeric repository/Issue
identity, and complete comment coverage. A copied foreign marker is not selected.
Duplicate same-revision own records conflict; historical revisions are preserved.
Restart follows authenticated progress to its exact attempt anchor and binding,
without a cache, newest-comment fallback, or new comments/attempts.

The GitHub resolver uses only GET requests under the existing nested read budget
(at most 15 seconds/32 requests, further restricted by any outer budget), existing
bounded pagination, and explicit duplicate-row checks. Recovery derives progress
and anchors from one collected comment view. This avoids mixing two separate
collection reads; it is not an atomic GitHub snapshot or authorization grant.

## Local evidence

The original implementation lacked this read boundary; its public-result test
failed one assertion before implementation. A subsequent behavioral regression
also reproduced one actual assertion failure: recovery fetched comment collections
twice and could mix active attempts. That correction now passes with the other
focused cases: **22 tests, zero failures/errors/skips**.

An initial 121-test run passed all 14 then-existing pure tests and all 100 adjacent
project/GitHub/work-source/identity tests. Seven new resolver tests had setup errors
because their fixture used a publishing login forbidden by the existing client.
Those are test fixture errors, not product regressions or a passing full run. The
fixture was corrected to the existing identity; the final focused 22-test run
passed. Adjacent unchanged behavior is retained from its passing run; final-head
hosted CI remains required. The product checkout, index and unrelated dirty work
were preserved.

## Requirement boundaries and remaining work

P09-R01/R02/R03 are covered here at the structural/schema/digest boundary. This
does not validate symlink-free referenced file resolution or indirect delegation
cycles. P09-R04/R05 have deterministic comment-source and attempt-recovery evidence;
real independent acceptance/delegation and a live adopted-binding round trip remain
required. P09-R06 supports adopted payloads and preserves exact references without
rewriting prose, but the accepted reference-section payload resolver is still
unimplemented. A reference is not treated as resolved empty clauses.

No model calls, Issues/comments/labels, native assignments, pending bind_work
writes, relationships, protected policy, MCP tools or existing legacy schemas were
changed. Future execution must separately verify accepted meaning, actual authority,
current admission and dependency evidence. Existing github_native dispatch remains
unsupported. Live GitHub binding adoption/recovery, reference resolution, P09 unit
completion, installation and full-v1 operation are NOT RUN here. Independent code
and security review, final-head CI, protected merge and exact-main checks are
separate required delivery evidence.


## Canonical repository casing follow-up

Self-review reproduced a valid-input regression at original head `5356ad1`: the
provider confirmed the same numeric repository with canonical lowercase display
name, but the read resolver compared its Issue URL with caller-supplied uppercase
casing. That positive control failed an assertion before correction. The resolver
now takes subsequent read paths from the authenticated repository full_name;
numeric identity and exact comment/source guards remain unchanged. The final
focused suite passes **23 tests with no skips/failures/errors**, including this
actual API-path control. No file/authority/dispatch scope was added. Original CI
and reviews are not treated as final-head evidence for this correction.


## Exact reference input conditions -- 2026-10-21

This follow-up to verified main `7e0b570` implements P09-R01/R05/R06 and
WR-D53/D55. Accepted P09 Rev1 / WR Rev5 remain unchanged. Adopted and reference
inputs normalize to one immutable canonical clauses payload/digest. Missing
meaning never becomes an empty dependency list.

Every normalization first reuses the complete WorkBinding-v2 validator with the
caller's explicit spec-directory scope. An unchecked Binding constructor is only
a value, not validation evidence. Unknown/invalid source digests, kind, outcome,
requirements, spec and other fields are rejected before any provider read.

Reference reading verifies numeric repository identity, exact commit and a single
complete recursive Git tree view. Each parent prefix must be a tree, and the leaf
must be a regular file. This covers valid deep paths without one request per
segment, preserves the 15-second / 32-request budget and never follows Contents
symlinks. Partial trees stay unknown; duplicate entries conflict. Blob identity,
size, base64 and UTF-8 must match. The contracted interpretation bound is
65,536 UTF-8 bytes, checked before blob fetch and by the parser. Oversized input
is an incomplete/limited observation, never valid empty conditions. Malformed
repository names remain inside the static source-error boundary.

Pinned CommonMark syntax tokens select one exact top-level heading's literal
title or leading requirement ID. Only standalone section-level JSON participates;
quoted/list examples cannot become conditions. Multiple candidate objects,
including a second object in an unsupported top-level code fence, are ambiguous.
The one payload must satisfy the same closed RequiredInput schema and canonical
ordering as adopted inputs. Missing/unsupported meaning stays unavailable;
provider-generated heading slugs and prose are not guessed. An explicitly chosen
adopted form still reuses a design in another format. Nothing is rendered or run,
and the output contains normalized conditions rather than raw source prose.

Initial candidate `752a337` passed all four
[CI jobs](https://github.com/openboa-ai/hydra/actions/runs/39470894561), each Python
suite collecting 1,180 tests (1,172 passed, eight explicit skips). Its initial
169-case impact run and final 28 new cases passed, and two actual fresh provider
fixture reads returned the same payload/digest with no writes. Those are
historical observations, not proof of the subsequent correction.

Code review identified five boundary defects: the initial oversized-input limit,
depth-dependent request exhaustion, unchecked Binding fields, malformed provider
names and nested Markdown examples. Seven behavioral regression methods reproduced
**15 actual assertion failures** on unchanged published `752a337`, with zero
setup errors/skips. After the coherent correction, **178 new/affected regressions
pass with zero failures/errors/skips**, including the exact 64-KiB boundary, a
complete 30-segment path, forged bindings before any GET, malformed metadata and
quoted/list controls. Legacy schema/digest/project/GitHub behavior is retained.

New final-head provider observation, CI, independent code/security reviews,
protected merge and actual-main checks remain separate. This stage grants no
design acceptance, delegation, registration, dependency satisfaction or native
assignment/dispatch. It changes no installed runtime or authority. P10/P11 and
actual v1 operation remain incomplete, and no durable source copy is created.
