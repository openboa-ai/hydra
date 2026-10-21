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


## P04 Rev4 explicitly injected stdio reader transport

This follow-up implements the transport-level boundary required by section 3.1
without activating a native source. A server must independently qualify and
explicitly inject its executable, current scope callback and mapped locator.
Those arguments are not authentication, work ownership or an input permission.
There is no default executable, tool/config route, locator discovery, writer,
installation change or background service. The existing reader and accepted P04
Rev4 remain unchanged; live source qualification remains NOT RUN.

One owned invocation uses the fixed public CLI command `app-server --listen
stdio://`, fixed working directory and the already selected environment/account.
Only initialize, initialized and thread/items/list are sent. Unique invocation
request IDs correlate responses; duplicate JSON keys, unexpected IDs and incoming
server requests fail closed. Notifications are discarded under a 32-frame/64-KiB
auxiliary bound; diagnostics have a separate 64-KiB bound. Raw pages retain the
1-MiB/page and 3-MiB aggregate limits, enforced while reading nonblocking pipes,
including a response that never sends a line terminator. The 50-second reader
budget includes initialization, with at most 15 seconds for startup and 30 seconds
per page. No retry or alternate method/source/home is selected after failure.

Success, failure, deadline and cancellation release owned pipes and confirm the
owned CLI child ended. EOF, terminate and kill waits are bounded separately to
0.25, 0.5 and 1 second. Failure to confirm cleanup invalidates an otherwise valid
observation. Repeated cancellation preserves this cleanup; unrelated processes
remain alive. This is trusted request cleanup, not hostile-program containment
or a claim that native application turns, helpers or unrelated work terminated.

Eighteen new real-process synthetic tests plus the twelve unchanged reader tests
pass on Python 3.14.2: 30 methods, zero failures/errors/skips. Exact-byte, malformed
and truncated frame, wrong-ID, scope-change, diagnostic/notification overflow,
timeout, double-cancellation, private-output and cleanup-failure cases retain the
normal two-page and repeat/free-text controls. Two controls fail on a minimal
unimplemented function; this is new-feature RED, not a published-parent defect.
A controlled removal of the unterminated-frame bound produces one further
assertion failure. Identical final test bytes pass against the implementation.
The original checkpoint/native/MCP public routes and projection schema are
unchanged. Full final-head CI and independent code/security review, protected
merge and main checks remain required.

These subprocesses are synthetic fixtures. No actual Codex source, model, question
or production process was started by this verification. Actual executable/account
qualification, source binding and locator production must precede a separately
delegated native observation. Answer attribution/correction, selected unsent
intent, controller restart, CP/P06 consumption and the first remote flow remain
separate unqualified responsibilities. This follow-up does not advertise them.


## P04 Rev4 high-numbered pipes and launch failures

Owned pipe reads now use nonblocking reads and the event loop's reader
registration. A long-running POSIX caller whose new pipe descriptors exceed
select's descriptor range can still read a valid question. An isolated real
worker holds 1,100 descriptors, verifies the owned pipes are at least 1,024 and
observes the normal two-page result plus ended-child proof. Its resource-limit
setting is confined to that worker; the host process is unchanged.

OS failures launching the selected executable are classified as safe transport
source failures rather than malformed provider responses. Actual missing,
non-executable and directory paths return unavailable/source_failure without
exposing the OS exception. A relative path remains rejected before launch.

The two final regression methods reproduce four actual assertion failures on
published b4826656d28c5983129190123962cdf4c5737b90. Identical final test bytes pass
with the correction: nineteen transport and twelve retained reader methods,
31 total, Python 3.14.2, zero failures/errors/skips. The normal byte, protocol,
scope, deadline, cancellation and cleanup controls remain in that same run.
These are synthetic owned-process tests, not an actual Codex source observation.

P04 Rev4 and its limits, fixed methods, scope guard, cleanup and inactive
source boundary remain unchanged. No profile or installed runtime is activated.
The previous b482665 hosted CI and reviews do not qualify this correction;
final-head CI and independent code/security review, protected merge and main
checks are required. Full answer/intent/restart and remote acceptance remain
NOT RUN.
