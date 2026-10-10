# S1 contract review

> Historical record — this document records the earlier prototype. The current
> [GitHub-native contract](../github-workflow/spec.md) supersedes its operational
> store, private registration and CLI assumptions. Adapter evidence remains scoped
> to the behavior actually tested; it does not establish current autonomous delivery.

Independent recovery and adapter reviews accepted spec SHA256
`9183680c6c4afe82808f8f62fb3b1dcca9955eb43f65f0ee21341324b591b039`
on 2026-10-09 before implementation.

Resolved findings: preserve cancellation through recovery, limit ambiguous-run blocking to its
scope, keep incomplete dependencies unready, check cancellation even without stream events,
bound start/turn/interrupt duration, and distinguish a read-only filesystem profile from full
external-effect isolation. No implementation blocker remained.

This is acceptance of S1's bounded execution contract. It is not a completed runtime, autonomous
delivery, credential isolation, background installation or multi-project operation result.

The subsequent CI section, in spec SHA256
`8fd46a785576290e4782a2c051566b21bd6d714bd50753baccdee333e2ccf4f8`,
was independently accepted before adding the isolated, credential-free Kernel tests job.
This does not replace the native CODEOWNER review for the workflow change.

The private-state path clarification in spec SHA256
`181eaab21f26646a2e10fd084173148d2e3dbe45936be8b3f8d23208dc90ac82`
was independently accepted before implementation. It makes the existing private-directory
requirement explicit: validate trusted ownership and POSIX permissions before following aliases
or opening state, preserve rejected files, and distinguish this guard from same-UID/root or ACL
isolation. It adds no delivery authority or new credential boundary.

Independent implementation review accepted the path guard and four regression cases within
that stated scope. The integrated 94-test suite passed, and existing qualification state reopened
without changing its waits or run counts. The silent-turn test separately synchronizes on turn
identity and covers delayed worker startup rather than using a fixed startup timer.
