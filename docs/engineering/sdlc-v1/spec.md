# Hydra SDLC v1 — design draft

Status: Draft. Purpose and initial operator surfaces are established; runtime architecture and implementation are not accepted yet.

## Purpose

Help an operator develop multiple projects with Codex without manually restarting each stage. The operator establishes goals and important boundaries; Hydra keeps eligible work moving and makes progress, failures, evidence, and required decisions visible.

Success is demonstrated by completed work and recoverable operation across different projects, not by repository creation, process startup, or generated plans.

## Users and responsibilities

- The operator owns purpose, product choices, authority, and final accountability.
- Codex performs bounded planning, implementation, verification, review response, and analysis.
- Hydra coordinates execution and exposes its state without becoming a substitute for project requirements or GitHub's actual delivery results.
- Each project owns its product tests, agent evaluations, acceptance thresholds, and deployment policy.

## Intended lifecycle

| Stage | Input | Required outcome |
| --- | --- | --- |
| Goal | Operator intent and boundaries | Delegated scope and observable completion criteria |
| Selection | Current work, dependencies, priorities, resources | One eligible and independently verifiable work unit |
| Design | Existing accepted specification or proposed change | Reviewed specification for the implementation boundary |
| Implementation | Accepted scope and isolated workspace | Change with requirement-linked verification |
| Review | Actual diff and current execution evidence | Completed code and security review with findings resolved |
| Delivery | Current revision, required checks, applicable decisions | Verified merge of the intended revision |
| Observation | Merge and any authorized delivery target | Required follow-up results and an accurate completion record |
| Continuation | Goal progress and current external state | Next eligible action, explicit wait, or a specific human decision |

Selection should finish or recover existing work before expanding concurrency. A product goal that has not been defined is a reason to request planning input, not to invent features.

## Execution behavior to design

Routine change detection, concurrency accounting, retry scheduling, and duplicate checks should use deterministic software. Model execution should serve a ready task or a justified planning/diagnostic action, not repeatedly ask whether anything changed.

The design must explain how work starts, waits, resumes, stops, and recovers after interruption. A review or CI wait must preserve the work record and resume when useful new evidence exists. Completion must come from actual outcome evidence rather than a worker's exit status.

Codex, GitHub, and a CLI are the initial operator surfaces. The operator needs the goal, current work and selection reason, stage, latest evidence, delivery status, next action, and any required decision. A separate web application is outside this initial scope.

## Human decisions and data boundaries

Routine fixes within accepted scope should continue without repeated approvals. Unresolved product direction, policy or authority changes, evaluation criteria changes, new credentials or spending, and production/public-release effects require the applicable human decision.

Access credentials do not establish authority. The chosen implementation must state which restrictions are technically enforced and which are operating conventions. Public source and examples must not contain private project configuration, secrets, or operating evidence.

## Failure and compatibility requirements

The detailed design must cover duplicate triggers, changed head or base, missing/expired authentication, unavailable storage, delayed reviews, repeated CI failure, lost responses to external writes, cancellation, and process restart. Re-query external facts before repeating an action with uncertain outcome.

Projects must keep independent specifications and quality criteria. Onboarding another project should change project configuration rather than require a fork of Hydra's common execution logic. Existing project work must not be silently adopted or overwritten.

## Acceptance scenarios for the eventual runtime

- A bounded feature or bug fix completes through review response, delivery, and follow-up without repeated operator prompts.
- A review finding or failed check leads to correction and verification of the resulting revision.
- Duplicate triggers do not create duplicate active execution for the same work.
- Restart and uncertain external responses recover from recorded work and current external facts.
- A required human decision pauses the affected work while independent eligible work can continue.
- Changed revisions invalidate affected evidence; protected checks and project evaluation thresholds remain intact.
- At least two projects complete the same lifecycle without project-specific changes to Hydra's core.

## Decisions still required before implementation

The next design review must choose the execution interface to Codex, change-detection mechanism, work/state ownership and persistence, concurrency and retry bounds, resource controls, operator intervention flow, and deployment/update/recovery strategy. Select a runtime language and any database or MCP interface only to satisfy that reviewed design.

No prior implementation, plugin contract, or evaluation result is adopted by this draft.
