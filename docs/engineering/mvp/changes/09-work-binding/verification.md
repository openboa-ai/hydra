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
