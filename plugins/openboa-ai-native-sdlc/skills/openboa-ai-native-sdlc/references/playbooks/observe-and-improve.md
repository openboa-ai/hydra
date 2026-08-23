# Observe and improve

**Change rate:** fast. This is a replaceable method, not doctrine.

Use this playbook after delivery, during an incident review, or when the collaboration system itself needs improvement.

## Observe the realized outcome

Choose signals before delivery when possible. Inspect the running surface, deployment, user-visible behavior, logs, traces, support evidence, or business metric that proves the intended outcome. Record the observation window and environment.

Separate these states:

- designed;
- implemented;
- verified in a controlled environment;
- delivered;
- observed in use;
- measured against a qualified metric.

Do not collapse `unknown`, `unavailable`, or `unmeasured` into zero, failure, or success.

## Review the collaboration system

Track both outcome quality and coordination cost:

- accepted outcomes and first-pass acceptance;
- rework, reopened work, defects, rollback, and recovery time;
- human attention and necessary versus unnecessary escalation;
- review queue age and throughput;
- resume success after a new task, model, or machine;
- out-of-scope actions and duplicate external effects;
- time, tokens, tool calls, and cost;
- single-agent versus multi-agent results;
- repeated failure patterns.

Compare like work and keep missing data explicit. Vendor benchmarks and self-reported productivity claims are hypotheses until observed in the OpenBoa environment.

## Put learning in the smallest durable layer

- Repository fact or command: update `AGENTS.md`.
- Repeated way of working: improve a playbook or skill.
- Product regression: add or improve a test.
- Capability claim: add or improve an eval.
- Permission failure: strengthen platform controls, rules, sandboxing, or credential boundaries.
- Enduring principle conflict: propose an operating-model or doctrine change through its declared gate.

Prefer the smallest change that prevents recurrence. Do not compensate for a missing test, tool, or control with a longer prompt alone.
