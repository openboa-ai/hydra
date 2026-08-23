# OpenBoa Evals and Observation

**Contract:** `0.1.0`

## Eval contract

An eval tests whether a workflow produces the intended outcome under stated conditions. Start from the goal's acceptance evidence and use the smallest useful method:

- deterministic checks for code, documents, schemas, and policy;
- scenario evals for variable tool use or environments;
- review for judgment, maintainability, safety, and fit;
- observation for delivered behavior.

Outcome evidence is primary. Inspect a compact trajectory only when the path affects safety, scope, or diagnosis. Do not retain hidden reasoning as an audit requirement.

## Graders

Prefer executable graders with explicit pass/fail conditions. Use rubric or model graders only when deterministic checks cannot measure the quality. Calibrate them against human examples and record the grader version, scenario, environment, result, and limits.

Every eval should name the failure it catches. A score that rewards output volume or repeats the generated answer is not useful evidence.

## Observation and learning

After delivery, inspect the intended surface: merge or deployment state, UI behavior, telemetry, incidents, user or operator signals, and rollback readiness as applicable.

When evidence reveals a failure, improve the smallest responsible layer and add a regression case. A passing test, approved pull request, or successful session does not replace required observation.
