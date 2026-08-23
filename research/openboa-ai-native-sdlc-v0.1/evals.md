# Eval and Observation Lessons

Evaluation answers four separate questions. Collapsing them into one agent score hides the decision that the evidence should support.

## Outcome

Did the intended state exist in the target environment? Use deterministic tests, scenario evals, review, preview, deployment evidence, and observation as appropriate. A completion message is not an outcome.

## Work lead

Did the lead make progress with appropriate independence? Inspect scope control, tool choice, resource use, escalation quality, recovery, review rework, and handoff. Inspect a compact trajectory only when the path affects safety or explains a failure.

## Team and system

Did the assignment provide enough context, authority, tools, environment, feedback, and independent review? A failure caused by a missing test or unusable sandbox should not be recorded only as weak agent performance.

## Leadership

Did human attention go to high-leverage decisions rather than routine supervision? Track intervention count and time, approval wait, resource conflicts, preventable rework, and whether the agent was given responsibility without matching authority or resources.

## Using evidence

Use multiple trials for behavior that varies. Prefer executable graders with clear pass/fail conditions; use rubric or model graders only for judgment that deterministic checks cannot measure and calibrate them against human examples.

Evidence can support a broader, narrower, or differently shaped future assignment. Authority changes remain a leadership decision and must consider the impact and reversibility of the next work, not only the agent's historical success rate.

## Observation and learning

After delivery, inspect the realized surface: merge or deployment state, UI, telemetry, incidents, user or operator signals, and rollback readiness. When evidence exposes failure, improve the smallest responsible layer and add a regression case. Preserve decisions and observable evidence; a full hidden transcript is not required.
