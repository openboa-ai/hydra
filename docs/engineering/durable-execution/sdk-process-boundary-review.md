# S1 execution boundary review

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
