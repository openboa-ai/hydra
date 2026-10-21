# P04 verification evidence

## P04 Rev4 internal exact-question reader

Implements sections 3.1–3.3 and QREAD-D01–D12 as an inactive internal source reader.
The server supplies a fixed connection/task scope and an already mapped question
locator. The reader performs only DESC(Q), ASC(B), and an optional exact ASC(B)
repeat, at most three pages of twenty items. Missing mappings and scope mismatches
do not perform provider I/O. No task enumeration, title search, alternate anchor,
raw-history adapter, native or GitHub mutation, persistence or default transport
is introduced. The page-source interface is internal and is not a new Codex API.

Raw assembly is bounded to 1 MiB per page and 3 MiB total, with a shared 50-second
processing budget and at most 30 seconds per request. An actual adapter must also
enforce these bounds while reading, correlate protocol responses and honor owned
request cancellation/cleanup before it can be activated. Synthetic chunk streams
exercise exact limits, oversize rejection, processing deadlines and context cleanup;
these do not qualify a transport installation. Raw errors and unrelated page fields
are not returned. Private references and question text stay in internal observations
and are absent from ordinary result representations and public records.

The observed question keeps exact titles, options, ordering and absent/null fields.
Its canonical content digest detects change; it is not an immutable provider
revision, answer receipt or authority. A missing predecessor or target remains
bounded inconclusive. Changed content conflicts without adopting the new question.
Adjacent user messages, resolved/completed facts, client identifiers and instructions
inside a title do not create an answer, accepted selection, applied effect or Resume.

For this new module, three positive/byte/effect oracles failed on a minimal inactive
all-unavailable implementation before the reader was implemented. This is new-feature
RED, not a claim of a defect reproduced in a previously published module. The same
final tests pass. Local Python 3.12.7 with pinned MCP SDK 2.3.0 ran all 80 relevant
question/native/capability/wait/MCP methods in 27.512 seconds: zero failures,
errors or skips. The same twelve new reader methods also passed on Python 3.14.2;
that initial environment lacked the optional SDK and skipped eleven existing cases,
so those skipped cases were rerun in the declared SDK profile. Source/test bytes
were unchanged. No production service was installed or activated by these tests.

Full P04 source qualification remains NOT RUN: supported locator production,
actual reader transport/caller binding, human answer/source and correction linkage,
selected unsent intent, controller restart restoration and CP/P06 consumption remain.
The earlier bounded source feasibility observation is not transferred as actual
operation of this implementation. Remote Pause/answer/Pause retention/restart/
explicit Resume/same-work progress and two-project acceptance remain unqualified.
Final-head CI, independent code/security review, protected merge and main checks
are required before delivery of this internal-reader increment.
