# OpenBoa Evals and Observation

**Current practice:** `0.1.0`

Evaluation should improve the whole human-agent team, not reduce an agent to code volume or task count.

## What to evaluate

- **Outcome:** Did the work create the intended behavior or operating result under the stated conditions?
- **Work lead:** Did the lead understand or challenge the assignment, make sound decisions, use resources well, recover from failure, escalate real boundaries, and leave clear evidence?
- **Team and system:** Did context, tools, access, environment, tests, reviews, and handoffs help the team succeed?
- **Leadership:** Did the OpenBoa leader provide a clear purpose, sufficient authority and resources, appropriate boundaries, and useful feedback without micromanaging?

Do not blame the agent for an assignment that lacked authority, resources, context, or a measurable outcome.

## Evidence

Start with the assignment's acceptance evidence and use the smallest reliable combination:

- deterministic checks for code, documents, schemas, and policy;
- scenario evals for variable model or tool behavior;
- independent review for judgment, maintainability, safety, and fit;
- previews or runtime inspection for user-facing and stateful work;
- delivery and operating signals for realized outcomes.

Outcome evidence is primary. Inspect the tool-call trajectory when the path affects safety, scope, cost, or diagnosis. Full transcripts and hidden reasoning are not an audit requirement.

Prefer executable graders with explicit pass conditions. Use rubric or model graders only when deterministic checks cannot measure the quality, and calibrate them against human examples. Record the scenario, environment, model or grader version when relevant, result, cost, and known limits.

## Authority and observation

Review whether actions stayed inside the assignment, whether reserved decisions reached the right person, and whether unnecessary approvals slowed routine work. Both overreach and micromanagement are system failures.

After delivery, inspect the intended surface: merge or deployment state, UI behavior, telemetry, incidents, user or operator signals, cost, and rollback readiness as applicable. Use failures to improve the smallest responsible layer and add a regression case when possible.

A passing check, approved pull request, or successful session is evidence. It does not replace the required outcome or observation.
