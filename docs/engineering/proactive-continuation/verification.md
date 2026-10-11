# Goal-driven native continuation verification

## Candidate

- Base revision: `0e6bdb9287ca893fa1dd5809ea5c18bff28927b4`
- Accepted specification and initial review commit:
  `ef0de4e795d745d51a311551f221c335e6c742a5`
- Final specification SHA-256:
  `b5e2aab537d05fd9d64cd44cf7e736f0657fae00f70145c31fce2a06c90712d0`
- Candidate version: `0.2.1`

## Evidence

The implementation was verified through the repository storage wrapper on the pinned
development volume.

- Runner-focused suite after the pull-request corrections: 70 tests passed.
- Native-assignment suite after the pull-request corrections: 36 tests passed.
- GitHub-adapter suite: 37 tests passed.
- Independent full suite: 677 tests ran and returned `OK`, with 27 skipped in
  that review environment.
- Final candidate full suite: 683 tests ran and returned `OK`, with 25 skipped
  on the delivery host.
- Real stdio MCP initialization, tool listing, read, and status path: 2 tests passed.
- Python bytecode compilation completed successfully.
- `git diff --check` completed successfully.
- Storage health verification completed successfully.

The tests cover current-attempt decision context, stale and malformed markers, restart
after review and verification steps, resume-hint blocker precedence, ownership handover,
bounded escaped JSON, progress-marker lifecycle, rollback parsing by the 0.2.0 reader,
status propagation through the MCP boundary, repeated recovery-attempt rotation, marker
removal after resume completion, and fail-closed behavior when the preserved source
decision context or its pinned policy revision disappears. Native begin also proves that
an unpinned stopped assignment is not retired or rewritten.

## Evidence boundary

This document records a source candidate. It does not claim that the change is merged or
installed. Scheduled advancement and a genuine native question-answer-resumption cycle
remain unproven until observed after protected delivery.
