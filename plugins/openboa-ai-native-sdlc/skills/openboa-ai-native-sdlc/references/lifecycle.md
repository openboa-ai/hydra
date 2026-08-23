# AI-Native Software Development Lifecycle

OpenBoa treats an agent as a collaborator that can lead delegated work, not as an autocomplete tool attached to a human-only process. The human sets purpose, priorities, principles, and final accountability. The agent drives the work inside its delegated authority. System controls enforce the boundary between the two.

This document describes the current lifecycle method. The doctrine explains why OpenBoa works this way, and the operating model explains who decides and acts. Those foundations should be stable. The lifecycle, tools, and playbooks are expected to improve as better evidence and capabilities become available.

## The lifecycle is a loop

Use this as a connected learning loop, not as a one-way sequence of stage gates:

`Purpose and principles → Outcome → Explore and design → Plan the work graph → Execute ↔ Verify ↔ Recover → Review and integrate → Release and observe → Learn and improve`

Later evidence can send the work back to any earlier point. A failed test can change the implementation, an implementation discovery can change the plan, and production observation can change the original understanding of the outcome. The plan is the best current hypothesis, not a promise that reality must follow.

### 1. Set purpose and principles

The human defines why the work matters, which outcomes have priority, and which values or constraints must not be traded away. The agent should surface ambiguity and recommend a direction, but it must not invent a product purpose, accept a new policy tradeoff, or expand its own authority.

This step changes only when the purpose or governing principles are genuinely unclear. It is not a request for human approval of routine implementation choices.

### 2. Define the outcome

Translate the purpose into an observable result. State what should be true in the relevant user or operating environment, the important boundaries, and the evidence that would demonstrate success.

A GitHub Issue is the default durable work item for a meaningful outcome. The Issue should survive individual Codex tasks, models, sessions, branches, and pull requests. Keep it large enough to represent useful progress and small enough to lead and verify. Do not create an Issue for every prompt, file, commit, or test.

Small routine work may use a fast path when it stays in one repository and one pull request, is reversible, has obvious acceptance evidence, and fits existing delegated authority. It does not need continuous human supervision. Create an Issue before continuing if the work grows, needs coordination or a handoff, or crosses a decision or authority boundary.

### 3. Explore and design

The agent gathers repository and environment facts, checks relevant external evidence, identifies constraints, compares options, and recommends a design. Exploration should reduce uncertainty that can change the outcome, authority, architecture, or verification approach.

The agent leads this work. Ask the human only when a decision changes purpose, priorities, principles, permission, or another defined human boundary. Record important decisions and rejected alternatives in a durable place; do not require a transcript of private reasoning.

### 4. Plan the work graph

Break the outcome into work that can be ordered, delegated, isolated, and verified. Keep scope hierarchy, dependencies, and evidence links distinct. Choose the execution topology that fits the work instead of starting with a fixed number of agents.

Use one agent when the work is tightly coupled or coordination would cost more than it saves. Use parallel agents only when their work is meaningfully independent, their write scopes can be isolated, and their results can be verified. See [Work graphs](work-graphs.md).

### 5. Execute, verify, and recover

The agent work lead makes progress inside the approved scope and authority, using repository instructions and the actual environment as constraints. Verification runs throughout execution rather than after all changes are complete. A failing check is new information: inspect it, update the hypothesis, and recover from a known state.

Prefer small internal checkpoints and meaningful integration units. Small internal steps do not require small Issues or pull requests. Preserve unrelated work, isolate concurrent writers, and reconcile external effects before retrying an uncertain action. See [Continuity and recovery](continuity-and-recovery.md).

### 6. Review and integrate

Review asks whether the proposed change achieves the outcome without unacceptable regressions or boundary violations. Match the review method to the failure risk. Independent evaluation is most useful when it brings different evidence, tools, or perspective; another agent repeating the same assumptions is not independent evidence.

A pull request is the normal integration surface for repository changes. It links the outcome, candidate change, exact head revision, checks, review, and merge decision. A pull request is not automatically the work unit, and opening one is not completion.

### 7. Release and observe

Deliver the accepted change through the repository's normal release or deployment path. Confirm the realized result in the environment that matters: installed plugin, preview, production system, published artifact, or another stated target.

Release authority follows [Authority and approvals](authority-and-approvals.md). Routine, bounded, reversible delivery should continue without unnecessary human intervention. Irreversible, externally binding, or otherwise defined high-impact actions wait at the exact boundary that requires a human decision; safe preparation continues.

### 8. Learn and improve

Use observation, defects, review findings, recovery time, and unnecessary escalation to improve the system. Put the learning where it can change future behavior:

- repository-specific facts belong in `AGENTS.md`;
- a recurring way of working belongs in a skill or playbook;
- product behavior belongs in a deterministic test;
- an agent capability or failure mode belongs in an eval;
- permission boundaries belong in system and GitHub controls;
- durable organizational principles belong in doctrine or the operating model.

Do not freeze a method merely because it worked once. Change the method when evidence shows a better way, while preserving the purpose and principles that the method serves.

## Work items and execution artifacts

Keep these concepts separate:

- **GitHub Issue:** the durable outcome and shared operating record.
- **Codex task:** a bounded execution context used to advance the outcome.
- **Run:** one attempt inside a task or automation.
- **Commit:** a versioned repository checkpoint.
- **Pull request:** the proposed integration change and its review surface.
- **Check or eval result:** evidence about a specific revision, behavior, or capability.
- **Release or deployment:** the act that places an accepted change in its target environment.
- **Observation:** evidence about what the delivered change actually did.
- **Handoff:** the continuity record that allows another task, model, agent, or human to resume safely.

One Issue may require several tasks, runs, commits, or pull requests. Conversely, a routine pull request may use the fast path without an Issue. Do not treat any single artifact as proof that the outcome is complete.

## Evidence and completion

Prefer evidence in this order, using the highest relevant level available:

1. the outcome observed in the actual target environment;
2. deterministic tests and trusted continuous-integration checks;
3. an independent evaluator with distinct evidence;
4. model review against an explicit rubric;
5. human judgment where the decision genuinely requires it;
6. post-release observation over the period needed to detect operational failure.

These sources accumulate rather than mechanically replace one another. A production observation can invalidate an earlier passing test, and a deterministic test should override a model's unsupported confidence. Unknown evidence is not a pass.

The work is complete only when the accepted outcome exists, required checks and review are satisfied, delivery reached the intended target, and the required observation evidence has been recorded. A generated answer, successful command, green unit test, open pull request, or merge is evidence of progress, not completion by itself.
