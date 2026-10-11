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
initial review covered the exact decision-context protocol, the separation between a
read-only resume hint and ownership recovery, bounded selection of the current attempt's
context, rollback compatibility through an authenticated auxiliary marker outside the v1
progress payload, and a compatibility fixture independent of local Git history. Its full
suite ran 677 tests and returned `OK` with 27 skipped.

Pull-request review then identified recovery boundaries that required correction:

- both runner paths now stop with `decision_context_missing` if the exact preserved source
  context disappears after attempt rotation;
- status suppresses a resume hint when the pinned policy changed;
- whitespace-delimited inline, CRLF and tab decision summaries are accepted while
  ambiguous prefixes are rejected;
- the source context follows repeated recovery-attempt rotations and is removed when the
  resumed phase completes;
- progress without a policy revision fails closed before model work or an external write;
- native begin performs the same policy-pin check before retiring a stopped assignment.

Independent review reproduced and verified the edge cases, including direct completion
with the original context action still present, missing policy pins in both runner and
native entry paths, and valid healthy status fixtures. The final review found no remaining
actionable issue and returned `candidate_ready`. The focused Runner, Native and GitHub
suites covered 143 tests.

This result does not establish merge, installation, scheduled advancement, or a real
native question-answer-resumption cycle. Those remain delivery and operational evidence.
