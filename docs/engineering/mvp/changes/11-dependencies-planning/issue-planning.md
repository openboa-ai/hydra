# Default Issue priority observations

Scope: unchanged P11 revision 2 R05 and WR section 9. This step provides the
normal Issue planning source and its deterministic ordering key. No Project,
additional credential, mandatory Issue template or persisted planning copy is needed.

## Read and source boundary

`GitHub.native_issue_planning_read(repository, source, planning,
expected_source_digest)` reads one allowed numeric IssueRef at an exact source
digest. The caller owns protected planning-policy provenance, pin provenance and
accepted binding/adoption. The value and its constructor grant no execution rights.
An explicitly selected Project policy returns `planning_not_selected` here, with
no API call; this reader is never a fallback for unavailable Project priority.

The existing GitHub GET transport authenticates its account, validates numeric
repository/Issue and node identity, and reads the complete Issue twice. Exact
title/body digests, original creation identity and current repository visibility
must agree. A changed title/body returns `source_changed`, preserving the supplied
pin; this reader never adopts a new binding or accepts semantic equivalence itself.
Updated timestamps, labels and open/closed state are not priority or acceptance.

Complete freeform text without a declared priority has the default value zero.
One top-level CommonMark `hydra` fence may contain the existing four fields:
`spec`, `spec_revision`, `dependencies`, `priority`. This reader interprets only
priority, as a TOML integer from -1000 through 1000. Other fields do not select
specification, relations, permissions or commands. Existing legacy intake and
execution parsing are unchanged. Quoted, nested and HTML-comment examples do not
declare priority. Backtick and tilde fences follow CommonMark syntax.

Duplicate or unclosed declarations, bad TOML, unknown fields, boolean/string/float
values, out-of-range values, partial/redacted source or invalid metadata remain
unknown. Importance prose can support a later proposal; it does not become a
machine priority. Unknown has no implicit zero value.

The reader shares outer budgets and adds 15 seconds and eight API reservations,
including authentication. Complete bodies have a 262,144-byte ceiling; each Issue
response has an 8,000,000-byte decoded canonical JSON ceiling. Deadline,
credential, identity and visibility drift prevent a complete result. Output keeps
only numeric source identity, exact digest, original creation time, known priority,
coverage, safe reason and observation time. Raw source/error text is not exported.
No body, priority, native relation or progress state is written or persisted.

## Deterministic order and completion boundary

`priority_key(priority, created_at, source)` orders already qualified eligible
candidates by descending priority, ascending original UTC creation time and numeric
repository/Issue IDs. It preserves fractional timestamp precision through nine
digits and treats equivalent UTC representations equally. Unknown, coerced or
invalid values have no default key.

Eligibility, whole-pool uncertainty, active-attempt responsibilities, effect-time
source/dependency guards and native dispatch remain their existing owners. A key
does not cancel, restart, create, close or delegate any work. This implementation
does not activate native selection or add a command/projection profile.

The original 22-method suite produced 54 assertion failures against an explicit
always-unavailable/constant-key new-feature control, with no errors or skips.
The same original test bytes pass here. Two additional deadline methods reproduced
three failures in the unpublished reader when normalization completed after its
own deadline or the shorter inherited deadline. A complete value is now checked
after normalization, so late default zero and explicit priorities remain unknown.

On the verified main baseline, all 24 reader methods and 358 selected Python
3.14.2 regression methods pass without failures/errors/skips. The selected suite
includes existing project, transport/budget, work record/input, runner, status,
public decision and delivered relation-reader tests. This increment carries none
of PR #19's projection implementation. Final-head CI, independent reviews,
protected merge and actual-main checks remain delivery requirements.

The exact final module performed bounded GET-only observations of the existing
[Hydra goal Issue](https://github.com/openboa-ai/hydra/issues/3). At its current
exact read-source pin, the complete freeform Issue returned priority zero. At an
older exact read-source pin, it returned partial/source_changed without a priority
or replacement pin. No source mutation, permission change, runtime activation or
raw-page retention occurred. These pins are not adopted WorkBindings or delegation.
Actual candidate eligibility, pool ordering, effect-time guards, selected Project
operation and full P11/v1 acceptance remain unqualified.
