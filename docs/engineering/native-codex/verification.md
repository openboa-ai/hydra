# Native continuation verification

This source extends merged revision `bdd54f58801b4ce27c9f53d7d676a9afe3e3a7fd`.
The scoped design and its R5 clarification received independent review before
implementation. This record separates source qualification from installed operation.

On 2026-10-10, the macOS/Python 3.14.2 regression checkpoint ran 639 tests successfully;
25 environment-specific tests were skipped. Subsequent native-only regressions cover
canonical workspace lookup and stopped spec/intake changes. Required Linux CI still
validates the final PR revision, including optional MCP tests on Python 3.11 and 3.14.2.
The final native-focused run passed all 25 tests, including those later corrections.

The first published PR revision passed 641 tests on both Linux/Python 3.11 and
3.14.2, including repository hygiene. The subsequent PR review correction batch
passed all 29 native-focused tests and the full macOS/Python 3.14.2 suite:
647 tests in 215.622 seconds, with 25 environment-specific skips. New regressions
cover uncertain ticket persistence, one verification run per native review,
fresh review after restart, write-summary disposal, and durable cleanup discovery
even when a provider no longer lists the retired resource. Remote checks must
still run against the correction commit before delivery.

The second PR correction batch passed 32 native tests and 10 host-resource tests.
Its full macOS/Python 3.14.2 regression ran 653 tests in 230.450 seconds,
with 25 environment-specific skips. Actual Git fixtures advance and delete the
remote Issue ref during implementation: ordinary candidate results are refused;
explicit stop commits the owned edits and releases admission; fresh begin still
waits without dispatch, push or PR creation. Design, implementation and correction
results feed the returned current identity directly into the next native tool.
Provider timeout/failure fixtures preserve delivered progress, reconcile other
repositories and retry cleanup without redelivery. Final-head CI and coupled
external reviews remain required after publication of this batch.

The native fixtures exercise spec review, implementation, verification, independent
change review, existing exact-head merge/post-merge gates, interrupted result and
callback recovery, stale results, policy/intake/head changes and shared host admission.
An actual local Git repository demonstrates committed partial edits before a decision
and restart into independent review followed by the original implementation phase.
This Git fixture does not establish an actual product PR delivery.

Official pinned MCP SDK 2.3.0 tests initialize/list/call in process and through a
real subprocess stdio connection. They verify all five schemas and a refused foreign
Issue. Fixture transport/controller behavior is distinguished from installed app
tool visibility or authenticated remote writes.

Resource-completion tests require actual fixture merge/main checks, closed Issue and
confirmed progress before invoking cleanup. Failed delivery gates never invoke it;
cleanup failure leaves completed progress intact and retries without another push,
PR, merge or close. A discovery hint cannot establish completion or adopt closed work.
The lifecycle provider must return an explicit retirement receipt; unknown/dirty/busy
host resources remain a separate host-provider qualification.

The common CLI suite remains supported. Neither an MCP call nor a candidate result
starts an SDK model worker or certifies CI/reviews. Public progress accepts bounded
typed identities, not prompts, local paths, raw summaries or private verification output.

Not yet demonstrated by these source tests: desktop plugin installation/visibility,
remote notification and answer/resumption, actual two-project delivery/restart, host
handover, runtime promotion, production deployment or scheduled unattended progress.
Those require their own receipts; no background operation is claimed here.
