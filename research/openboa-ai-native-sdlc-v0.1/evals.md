# Eval and Observation Lessons

An eval asks whether an agent-assisted workflow produced the intended outcome under known conditions. It complements ordinary tests and review; it does not replace them.

## What to evaluate

Start with the goal's acceptance evidence. Use the smallest useful layer:

- deterministic checks for code, documents, schemas, and policy contracts;
- scenario evals for workflows with tool use or environmental variation;
- review for judgment, maintainability, safety, and fit;
- observation for delivery state and realized product behavior.

The outcome is primary. Inspect the trajectory only when the path can create risk or explains a failure, such as using the wrong tool, crossing scope, ignoring a failed check, or repeatedly recovering from the same error.

## Graders

Prefer executable graders with clear pass/fail conditions. Use rubric or model graders only for qualities that deterministic checks cannot measure, and calibrate them against human examples. Record the grader version, scenario, environment, result, and known limits.

An eval should catch a named failure. Avoid a score that merely restates the generated answer or rewards activity. Independent review is valuable when self-evaluation could hide the error.

## Observation

Observation happens after the candidate change reaches its intended surface. Depending on the goal, inspect merged state, deployment health, UI behavior, telemetry, incidents, user or operator signals, and rollback readiness.

Close a goal only when acceptance evidence, required delivery state, and required observation are present. Passing tests, an approved pull request, or a successful agent session are evidence items, not completion by themselves.

## Learning from failures

Preserve enough evidence to classify the failure without keeping a full hidden transcript. Improve the smallest responsible layer: context, skill, plugin, harness, sandbox, tool, test, eval, grader, or policy. Add the resulting regression case to the development or delivery loop and measure whether the change improves future outcomes.
