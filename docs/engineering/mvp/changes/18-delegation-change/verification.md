# P18 private delegation-change normalization

This source increment implements only WR 7.1's closed private input types and
whole-object canonical SHA-256 digest. It retains amend/null-or-accepted-references,
withdraw/exact-actions and cancel/exact-target as distinct data. Opaque source
handles and revisions remain exact; parsing provides no human authority, source
qualification, accepted design, applied gate, interruption or cleanup evidence.

P18 Rev2 and WR 7.1 remain the requirements. The plan permits independent P18
parser/guard work while actual native source qualification is pending. No source
resolver, persistence, tool, remote command or activation is added by this change.
The full P18 source/resolver/effect/consumer and D/L/O responsibilities remain open.

The parser rejects duplicate or unknown fields, invalid union combinations,
unsupported actions, boolean/unsafe numeric identities, invalid requirement refs,
duplicate requirements/actions, control characters, malformed UTF-8/JSON and
nonfinite values. It preserves the inclusive 2,048/512-character source limits,
50 requirement references and current IssueRef/RequirementRef constraints. A
256-KiB raw input bound protects parsing; valid maximum-size UTF-8 data is covered.
Sorted compact UTF-8 object keys define the digest; arrays are not reordered.

Seven new methods exercise normal positive paths and forbidden input. A private
new-API scaffold that only decoded/canonicalized JSON produced 57 assertion
failures, with no setup errors or skips. This is a new-interface RED, not a claim
that the absent API was an existing production bug. Identical test bytes pass
with the strict validator. The affected work-record and work-input regressions
bring the local bundle to 40 passing methods, zero failures/errors/skips on Python
3.14.2. The existing pinned markdown-it-py 4.2.0/mdurl 0.1.2 test target was reused.
Earlier attempts without that existing dependency are retained as environment
failures; they are not counted as meaningful RED or successful regression.

Final-head hosted CI, independent code/security review, protected merge and main
checks remain required. Actual qualified human instruction/target/revision reads,
remote change application, running cancellation and recovery remain NOT RUN.
No runtime or authority profile was installed or activated.
