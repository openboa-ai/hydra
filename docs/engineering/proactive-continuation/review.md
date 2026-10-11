# Goal-driven native continuation specification review

Reviewed specification SHA-256:
`191a6ef3a0ba6a37635ae8f19283fdd861b13ec1bdef2b4bd37810b8d3d6d596`.

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
boundary; it does not accept implementation, tests, installation, scheduled progress,
or native question/resumption behavior.
