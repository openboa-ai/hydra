# Goal-driven native continuation specification review

Reviewed specification SHA-256:
`b5e2aab537d05fd9d64cd44cf7e736f0657fae00f70145c31fce2a06c90712d0`.

Independent review initially identified four blocking ambiguities: decision content
was not tied to resumption, preparation under `not_delegated` lacked a write boundary,
duplicate markers had no defined semantics, and resume-hint precedence was incomplete.

The accepted revision resolves them by:

- passing only public-safe authorized Issue comments as bounded untrusted decision
  context while keeping raw private answers in the native task;
- limiting undelegated preparation to read-only inspection, public-safe Issue updates,
  and an already designated private planning area;
- making duplicate current-attempt markers idempotent and stale markers ineffective;
- defining blocker precedence, including policy/intake changes, active assignments,
  completion reconciliation, and uncertain external effects.

Result: `candidate_ready` for implementation. This review accepts the specification
boundary.

The implementation was independently re-reviewed after each material correction. The
review covered the exact decision-context protocol, the separation between a read-only
resume hint and ownership recovery, bounded selection of the current attempt's context,
rollback compatibility through an authenticated auxiliary marker outside the v1 progress
payload, and a compatibility fixture that does not depend on local Git history. The final
review found no material issue and returned `candidate_ready` for commit and pull-request
review. Its independent full suite ran 677 tests and returned `OK` with 27 skipped.

Pull-request Code Review then found one P2 recovery gap: after attempt rotation, removal
of the preserved source decision context could allow an unrelated recent comment to reach
a resumed worker. The correction makes both the base runner and native runner wait with
`decision_context_missing` before model dispatch, native assignment registration, or a
native task response. Restoring the exact source-attempt context resumes the same work.
An independent correction review inspected both execution paths and their regressions,
found no further issue, and returned `candidate_ready`.

This result does not establish merge, installation, scheduled advancement, or a real
native question-answer-resumption cycle. Those remain delivery and operational evidence.
