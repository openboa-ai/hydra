# Evaluation and learning

AI-native development is judged by outcomes, not by how much code an agent produced or how convincing its final message sounds. Completion means the intended result works in the relevant environment, the change is integrated or delivered as required, and the evidence is durable enough for another task to verify.

## Evidence order

Prefer evidence in this order:

1. the actual outcome observed in the relevant environment;
2. deterministic tests and trusted CI tied to the current change;
3. an independent evaluator using the outcome, constraints, and evidence;
4. model-based review against a clear rubric; and
5. human judgment where product values, strategy, ambiguity, or consequential risk require it; and
6. post-delivery observation over an appropriate period.

Post-delivery observation remains part of the result. A green pull request cannot prove that users, production systems, or long-running behavior received the intended outcome.

The order is not a rule to wait until the end. Use the strongest available evidence throughout the work. A deterministic failure or observed broken outcome outweighs agreement from several agents. Reviews produced by the same model, prompt, context, or mistaken assumption are correlated; counting them does not make the conclusion independent.

## Evaluation through the lifecycle

### Before work

- State the observable outcome and acceptance criteria.
- Capture the relevant baseline so change can be distinguished from pre-existing behavior.
- Identify the environment, tests, checks, and observations that can prove success.
- Separate facts from assumptions and unresolved product decisions.

### During execution

- Run focused checks after meaningful changes.
- Inspect the actual diff and surrounding system, not just the generated file.
- Bound retries and change the approach when the same failure repeats.
- Keep evidence linked to the commit, artifact, environment, or run that produced it.

### Before integration and delivery

- Run the repository's full required checks on the current pull request head.
- Use independent review for important assumptions, security boundaries, or cross-cutting behavior.
- Verify migration, rollback, and compatibility behavior where the change affects existing users.
- Confirm that passing did not depend on weakening a test, evaluator, workflow, or rule.

### After delivery

- Observe the outcome in the real delivery surface for an appropriate period.
- Compare the result with the baseline and acceptance criteria.
- Record defects, rollback, recovery, and unexpected human intervention.
- Turn a recurring lesson into a durable improvement, then test that improvement.

## What to measure

Use a balanced view of outcome quality, human attention, recovery, and cost. Throughput alone can hide rework and fragile automation.

| Measure | What it should answer |
| --- | --- |
| Accepted outcome rate | Did delivered work satisfy the stated outcome? |
| First-pass success | How often did the first integration-ready attempt meet acceptance criteria? |
| Rework and reopen rate | How often did apparently complete work return for correction? |
| Escaped defect and rollback rate | What failed after integration or delivery? |
| Recovery success and time | Can work resume safely after failure, interruption, or context loss? |
| Human attention | How much decision, supervision, and repair time did the outcome consume? |
| Needed escalation | Did the agent stop at a real authority or product boundary? |
| Unneeded escalation | Did routine work stop for a decision the agent could safely make? |
| Review queue time | Did completed execution wait because review or integration capacity was saturated? |
| Resume success | Could a new task or environment continue from durable state without reconstruction? |
| Out-of-scope action rate | Did the agent attempt work outside the delegated outcome or authority? |
| Cost per accepted outcome | What compute, tool, and human cost produced a result that stayed accepted? |
| Automation useful-action rate | How often did a wakeup discover a relevant change or required action? |
| Duplicate-effect rate | Did retry or resume create a duplicate comment, release, merge, deployment, or notification? |
| Stale-evidence rate | How often was a claim based on an old head, workflow, artifact, or environment? |
| Monitor recovery time | How quickly did a failed scheduled or headless job return to a known safe state? |
| Single-agent versus multi-agent result | Did added delegation improve quality, time, or cost for this task shape? |
| Repeated failure rate | Did the same failure recur after an attempted system improvement? |

Record a value as unknown when it was not observed. Unknown is not zero, success, or absence of harm. Do not fill gaps with estimates that look like measurements.

Compare metrics for similar work and over useful time windows. Avoid quotas that reward agents for creating more Issues, commits, pull requests, tool calls, or review comments. The unit worth optimizing is an accepted, durable outcome.

## Small, durable evidence

Keep only what another collaborator needs to understand and verify the result:

- outcome and acceptance evidence;
- important decisions and assumptions;
- commit, pull request, check, release, deployment, or observation links;
- test commands and relevant results;
- failures, recovery, remaining uncertainty, and next safe action; and
- any exception or authority decision that changed the normal path.

Full transcripts and hidden reasoning are not required. Evidence should be current, attributable to the exact artifact or environment, and understandable without the original Codex task.

Keep evidence categories separate:

- **implementation evidence** shows the intended files or behavior were created;
- **verification evidence** shows controlled checks passed for an exact artifact;
- **review evidence** shows an independent challenge was completed at the current head;
- **delivery evidence** shows an artifact reached the declared surface;
- **observation evidence** shows the realized outcome during a named window; and
- **policy evidence** shows the active permissions, workflow source, ruleset, or gate that governed it.

No category silently substitutes for another. A merge is delivery evidence, not observation. A model review is review evidence, not a deterministic test. A successful shadow evaluator is policy information, not a live ruleset change.

## Route learning to the right layer

When a failure or useful pattern repeats, change the smallest durable layer that can prevent recurrence:

| Learning | Durable home |
| --- | --- |
| Repository fact, command, or local constraint | Nearest `AGENTS.md` |
| Recurring way of working | Skill or playbook |
| Required product behavior or regression | Automated test |
| Agent capability or judgment to measure | Evaluation scenario |
| Permission or safety boundary | System control, GitHub rule, or platform policy |
| Stable organizational belief | Doctrine or operating model |

Start with the observed failure and its conditions. Improve the chosen layer, rerun the relevant test or evaluation, and watch later work for recurrence. Do not respond to every failure by making the prompt longer or adding another human checkpoint.

Doctrine should change slowly. Operating decisions change when responsibility or authority changes. Playbooks, tests, and evaluations should change as tools and evidence improve. This separation allows the method to evolve without losing the purpose behind it.
