# S1 execution boundary review

> Historical record — this document records the earlier prototype. The current
> [GitHub-native contract](../github-workflow/spec.md) supersedes its operational
> store, private registration and CLI assumptions. Adapter evidence remains scoped
> to the behavior actually tested; it does not establish current autonomous delivery.

Accepted contract: `sdk-process-boundary.md` SHA-256
`60344d42dd2ba417fa25a164954768ea87a9d97e41cf4e235aac2cea73adc4dc`.

The implementation lead accepted this contract after reading it. An independent architecture
review accepted the same revision with no material blockers before dependent implementation.
Review covered durable callback ACKs, dispatch timing, bounded private framing, process identity,
parent loss, cleanup uncertainty and retained recovery evidence.

Implementation must treat an uncertain grant write as possible dispatch. Parent EOF must terminate
the worker's own process group without leaving a SIGTERM-resistant descendant behind. Provider
completion and confirmed local process cleanup remain separate requirements. This review grants
no new credentials, product scope, external operation or policy exception.

## Implementation evidence

Independent implementation review found no material blocker. The reviewer reran all 59 adapter
and subprocess tests successfully. It additionally exercised cancellation after actual subprocess
creation but before the async launcher returned ten times: no dispatch audit was emitted, each
outcome was `interrupted/stopped_before_dispatch`, and each owned process group was gone.

Reviewed source SHA-256 values:

- `hydra_sdlc/codex.py`: `025745608cea019d9df8cb58e4b9c5e54ed36306655d00c517f5351824ed24d9`
- `hydra_sdlc/execution_boundary.py`: `83adfe7ad7a579a74581f9ed535a919b969a3297aa42529c04f9b6f892a316a6`

The tests used disposable Python workers and fake providers on macOS; independent verification
used Python 3.12.7. Linux behavior needs CI evidence. This change did not perform an authenticated
model turn, resume an existing conversation, acquire another process's writer ownership, or claim
autonomous product delivery.
