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

This follow-up to verified main `7e0b570` implements P09-R01/R05/R06 and the
WR-D53/D55 read boundary. It keeps the accepted P09 Rev1 / WR Rev5 contracts.
Adopted and reference inputs normalize to one immutable canonical clauses payload
and digest. Missing input meaning does not become an empty dependency list.

Reference reading verifies the supplied source repository's numeric identity,
the exact commit and every non-recursive Git tree segment, allowing only regular
file modes at the leaf. It never uses a Contents response that may follow a
symlink. Blob identity, size, base64 and UTF-8 must match before parsing; the
existing nested read budget limits reads to 15 seconds / 32 requests. Documents
are bounded to 1 MiB for this reader; larger input stays explicitly limited.

Pinned CommonMark syntax tokens select one top-level heading's exact literal
title or leading requirement ID. Setext headings, fenced code, HTML comments and
nested section endings are structural rather than flat text searches. Exactly
one standalone JSON object must satisfy the same closed RequiredInput schema and
canonical ordering as adopted inputs. Ambiguous sections/objects are invalid;
missing or unsupported meaning is unavailable. Provider-generated heading slugs
and prose are not guessed. Explicit adopted conditions remain available for an
existing design in another format. No document rendering or executable extension
is involved, and the returned value contains conditions rather than raw prose.

Two acceptance-interface assertions failed on unchanged main because these read
interfaces were absent. The first implementation passed **169 new/affected
regressions**, without skips/errors/failures. Self-review then reproduced one
actual assertion failure for a non-string provider file mode escaping the typed
source-error boundary. A second assertion failure reproduced an additional JSON
object hidden in an unsupported code fence being ignored as ambiguity. The
corrections passed the final **28 new input/read
tests**, without skips/errors/failures; the unaffected 143 passing regressions
are retained. Fixed digest vectors, adopted/reference equivalence, fresh reads,
symlink/submodule rejection, edited provider shapes, duplicate/partial paths,
resource budgets and invalid JSON/schema/content are covered. Local dependency
installation left existing tooling and the installed service unchanged.

Actual provider-file observation, final-head CI, independent code/security
reviews, protected merge and actual-main verification remain separate evidence.
This parser/read adapter does not grant design acceptance, delegation, project
registration, dependency satisfaction, native assignment or dispatch. P10/P11
and actual v1 operation remain incomplete; the reader stores no durable copy.
