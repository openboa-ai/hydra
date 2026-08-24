# Evidence to design trace

This document makes OpenBoa's reasoning inspectable. A source does not become a rule merely because a frontier lab or an AI-native company published it. Each row separates four steps:

`external evidence -> lesson -> OpenBoa decision -> validation`

The source IDs resolve to [source-register.csv](source-register.csv). “Adopted” means part of the v0.1 design. “Hypothesis” means it must earn promotion through canary evidence. “Deferred” means the idea is useful but outside the skills-only v0.1 boundary.

## Design premise

> Humans own purpose and final accountability. Agents lead work toward delegated outcomes. Systems enforce authority and safety boundaries.

This is OpenBoa's synthesis, not a quotation or a claim that agents have legal or moral personhood. It treats an agent as an operating collaborator: a visible role with an outcome, context, authority, resources, work history, current commitments, evaluation, and a recoverable handoff. The model, session, harness, and machine are replaceable implementations of that role.

## Decision trace

| ID | Evidence | Lesson | OpenBoa v0.1 decision | Validation |
|---|---|---|---|---|
| D-01 | OAI-01, OAI-04, LIN-01, SRC-01 | Agent value rises when the organization treats it as a visible participant with shared context and meaningful work, not as autocomplete hidden inside a human task. | **Adopted:** define the agent work lead as the default lead for a delegated outcome. Separate work responsibility from the human's final organizational accountability. Record the work lead and current state; do not repeat the sole accountable human on every artifact. | In a routine issue, the agent researches, plans, implements, verifies, and prepares review without asking the human to drive its inner loop. A reviewer can still identify the delegated outcome, active lead, evidence, and boundary. |
| D-02 | OAI-01, OAI-05, ANT-01, ANT-08 | Durable principles should outlive fast-changing harness assumptions; methods must be replaceable and should earn their complexity. | **Adopted:** package three lifetimes: slow doctrine, medium operating model, and fast playbooks. Keep v0.1 skills-only; no dispatcher, daemon, custom runtime, hook, or live database. | Swap a playbook or model-facing technique without changing doctrine. Static checks fail if a playbook silently weakens an authority rule. |
| D-03 | OAI-02, GIT-01, LIN-01 | Sessions and pull requests are attempts and integration artifacts; the durable unit is the outcome represented in a work tracker. | **Adopted:** a meaningful GitHub Issue is the default durable work item. A Codex task is an execution attempt, a PR is an integration proposal, and a deployment is an observed release. Do not create micro issues or PRs for every agent step. | Resume work in a new task from the Issue, repository, and evidence without relying on the old conversation. Confirm that one Issue can contain several attempts while preserving one outcome. |
| D-04 | OAI-02, ANT-02, ANT-07 | Long work survives model, session, and machine changes only when state is externalized and reconciled with the live environment. | **Adopted:** persist outcome, current plan, state, dependencies, decisions, evidence, and next action in durable artifacts. On resume, inspect live Issue, branch, PR, checks, and environment before acting. Reconcile ambiguous external effects before retrying. | Kill or replace a task after partial progress. The next agent resumes without duplicate external writes, invented completion, or loss of verified state. |
| D-05 | OAI-01, OAI-02, GOO-01, VER-01, VER-02 | Code generation is only one part of delivery; reliable value comes from a closed loop that reaches production evidence and feeds learning back into the system. | **Adopted:** lifecycle is `purpose and principles -> outcome -> explore and design -> plan and work graph -> execute, verify, recover -> independent review and integrate -> release and observe -> learn and improve`. Planning is the best current hypothesis, not a frozen phase gate. | A canary traces one outcome through every applicable stage and identifies a real post-release signal or a justified reason a stage is not applicable. |
| D-06 | ANT-01, ANT-04, GOO-02, COG-01 | More agents help when branches are genuinely independent; sequential dependencies, many tools, or uncoordinated peers can make them worse. | **Adopted:** choose topology from the work graph. Use one agent by default, lead-worker for parallel independent branches, and a single integration point. Never require a peer swarm. Bound fan-out, compute, retries, and duration. | Compare single-agent and multi-agent execution on representative tasks. Multi-agent use must show better accepted outcome, elapsed time, or coverage after coordination cost. |
| D-07 | ANT-04, GOO-02 | Scope hierarchy, execution dependencies, and evidence provenance answer different questions and should not be collapsed into one generic graph. | **Adopted:** maintain three views when needed: parent and sub-issue scope, dependency DAG, and evidence links from claim to source, change, check, and observation. Create only the view needed for the outcome. | A multi-part change can show what belongs together, what must happen first, and what proves each result without making status depend on an agent's narrative. |
| D-08 | ANT-06, NVI-02, GOO-03, GOO-04, MSR-01, OAI-06 | Final prose and binary test success are both incomplete. Actual environment outcome is primary; trajectory analysis explains reliability, waste, and unsafe shortcuts. | **Adopted:** evidence order is: observed environment outcome; deterministic tests and trusted CI; independent evaluator; rubric model review; human judgment where needed; post-release observation. Inspect trajectory for diagnosis and policy violations, not to force one stylistic path. Use repeated trials for nondeterministic behavior. | Repository-level validation should cover false success, lucky pass, correlated model review, missing verification, reward hacking, and a valid creative path. Unknown metrics remain unknown, never zero. |
| D-09 | OAI-05, ANT-05, NVI-01, NVI-03, STD-02 | Safe autonomy comes from narrow enforceable boundaries, not from interrupting the agent before every routine command. Untrusted text is data, never authority. | **Adopted:** effective authority is the intersection of delegated purpose and scope, repository, operation, Codex permissions, connector permissions, and GitHub rules. Scope capability by agent, environment, and action. Require an exact fresh gate only for a sensitive effect. | Malicious Issue, PR, file, tool output, or web text cannot expand permission. Routine work continues with no human prompt; a new credential, public commitment, irreversible data change, or high-impact production action waits at the exact boundary. |
| D-10 | OAI-02, GIT-01, GIT-02, GIT-03, STD-04 | Work tracking, integration, enforcement, and provenance belong in a durable control plane; authentication alone is not authorization. | **Adopted:** GitHub is the durable control plane and the Codex GitHub connector is the default GitHub interface. Bind each operation to workspace, repository, outcome, allowed action, and current authority. Use Issues, PRs, checks, and rulesets in their established meanings. Preserve required checks during migrations. | Attempt an operation with a valid connected account but outside the delegated repo or action; it must be refused. Verify exact PR head and required checks before presenting the merge gate. |
| D-11 | OAI-01, ANT-03, GIT-01, SRC-01 | Agents need a small map into authoritative local facts and just-in-time context, not one giant global instruction file. | **Adopted:** root AGENTS.md is a short execution contract and router. Repository facts stay near the code; reusable workflow guidance stays in the plugin; doctrine is not duplicated across navigation pages. | A new task can locate the relevant rule and build/test commands with bounded context. Link and drift checks catch duplicate or stale normative text. |
| D-12 | OAI-01, OAI-04, REP-01, VER-01, VER-02 | Reviewable diffs are not enough for UI and operational behavior. Agents need isolated runnable surfaces, logs, metrics, previews, and rollback paths. | **Adopted as guidance; infrastructure deferred:** require evidence from the closest real environment available. Prefer isolated worktrees, previews, browser checks, logs, canaries, and rollback. Hydra v0.1 describes these practices but does not build a runtime. | Ouroboros and Coffee Chat canaries must identify their runnable verification surface. A UI-relevant PR includes an observed running screen before final publication; a release-relevant canary states rollback and observation signals. |
| D-13 | OAI-01, ANT-06, MSR-02, GOO-01 | Learning compounds when a failure is converted into the right durable artifact rather than another warning in a long prompt. | **Adopted:** repository fact goes to AGENTS.md; recurring procedure to a skill or playbook; product behavior to a test; agent capability or failure to an eval; authority to system controls; organizational purpose to doctrine or operating model. | Observation review must name the repeated failure, chosen artifact, expected behavior change, and validation. A regression scenario proves the learning is executable. |
| D-14 | OAI-06, ANT-06, NVI-02, GOO-01, MSR-01 | Output volume is not value. Measurement must include accepted outcomes, variance, downstream load, safety, recovery, and resource use. | **Adopted:** track accepted outcome, first-pass acceptance, rework or reopen, defect and rollback, recovery, human attention, needed and unneeded escalation, review queue, resume success, out-of-scope action, cost, single-versus-multi comparison, and repeat failure. | Evaluation and observation records should expose these fields and distinguish zero from unknown. Quarterly review can retire a playbook that adds cost without improving accepted outcomes. |
| D-15 | STD-01, OAI-05, VER-02 | Risk management and rollout are continuous; a one-time design approval cannot prove a method works in a real repository. | **Adopted:** validate in Hydra, then use one bounded product canary, then another distinct canary before broader adoption. Ouroboros and Coffee Chat consume the SDLC; they do not redefine doctrine by accident. High-impact expansion remains a human gate. | Each canary records outcome, deviations, evidence quality, human attention, safety events, and playbook changes. Expansion occurs only after explicit review of those results. |
| D-16 | OAI-03, ANT-07, VER-01, STD-03 | Stable interfaces matter more than a permanent runtime implementation; telemetry standards are valuable only when a runtime exists. | **Deferred:** v0.1 provides portable skills, references, templates, and validation. A future execution plane may add sandbox, durable workflow, and OpenTelemetry-compatible traces without changing the doctrine. | Before runtime work, demonstrate a failure that skills and GitHub controls cannot solve, define the minimum interface, and test portability across at least two agent environments. |

## Situational leadership model

The evidence does not support either “human approval everywhere” or “unlimited agent authority.” OpenBoa therefore applies leadership by situation:

| Mode | Use when | Agent role | Human role |
|---|---|---|---|
| Agent-led | Outcome is clear; principles are approved; work is observable, reversible, and bounded. | Lead the full inner loop, delegate when helpful, verify, recover, and present evidence. | Set direction and remain available for genuine boundaries. |
| Joint | Several viable product, architecture, or risk choices change the outcome materially. | Research options, make a recommendation, show evidence and tradeoffs, and ask one decision at the decision point. | Choose the direction or redefine the goal. |
| Human-led | Purpose, priority, values, new permission, irreversible data, major production or financial impact, legal or privacy exposure, public commitment, release, or an exception is at stake. | Prepare evidence and reversible work; do not cross the boundary. | Make the consequential decision and accept final accountability. |

If the human is unavailable, the agent continues safe reversible preparation and routine execution. Only the exact unresolved boundary waits.

## Conflicts and how v0.1 resolves them

### Parallel fleets versus simple systems

Anthropic's production research system and AI-native product vendors report benefits from parallel agents (ANT-04, COG-01, CUR-01), while Anthropic and Google show that coordination can add cost or reduce performance on sequential work (ANT-01, GOO-02). OpenBoa does not choose a fixed fleet. It chooses topology from dependency shape and requires comparative evidence.

### Small tasks versus meaningful outcomes

Factory recommends keeping work small enough to contain wrong assumptions (FAC-01). OpenAI Symphony says sessions and PRs are means to a deliverable and highlights the cost of session-level management (OAI-02). OpenBoa makes the Issue a meaningful outcome and decomposes only into independently delegable and verifiable sub-issues. A run may be incremental without turning every increment into governance overhead.

### Outcome-first evaluation versus process quality

Anthropic and DeepMind prioritize observable end state and automated evaluators (ANT-06, GOO-03). Microsoft shows that test-passing trajectories can still contain blind retries and regression cycles (MSR-01). OpenBoa keeps real outcome first, then uses trajectory evidence to find fragility, unsafe shortcuts, and waste. It does not reject a correct novel path merely because it differs from a preferred sequence.

### Agent review versus production safety

OpenAI reports extensive agent-to-agent review in a controlled repository (OAI-01). Vercel warns that even green CI can miss operational hazards (VER-02). OpenBoa permits independent agent review but never treats correlated model agreement as stronger than deterministic checks, observed runtime behavior, canaries, or rollback evidence.

### Repository knowledge versus shared cross-repository context

OpenAI emphasizes repository-local, versioned knowledge (OAI-01), while Sourcegraph emphasizes cross-repository and historical context (SRC-01). OpenBoa stores local facts nearest the code and portable methods in Hydra. External context may assist discovery, but it must point back to an authoritative, reviewable source before it becomes a decision.

### Fewer approvals versus safe control

Anthropic reports that sandboxing can reduce approval fatigue (ANT-05), while NVIDIA and OWASP require stronger controls when untrusted data can reach sensitive tools (NVI-01, NVI-03, STD-02). OpenBoa removes routine prompts inside a bounded lane and adds fresh approval at the exact sensitive effect. Autonomy is earned through better boundaries, not fewer controls.

## Open questions

These are not silently resolved by v0.1:

1. **Persistent agent role:** Will a role reconstructed from Issue, repository, evidence, and history remain coherent across different models and harnesses? Measure resume success and handoff loss.
2. **Work size:** What is the largest meaningful outcome current agents can own without quality collapse in each repository? Measure rework, blocked runs, and time to accepted outcome.
3. **Independent evaluation:** How much independence is gained when work lead and evaluator use different contexts but the same model family? Compare with deterministic checks and, where useful, another model or human calibration.
4. **Human attention:** Which gates prevent harm, and which merely move routine work back to the human? Track needed and unneeded escalations and time waiting for a decision.
5. **Review queues:** Does agent throughput overwhelm integration and observation capacity? Track queue depth, age, reopen rate, and production defects.
6. **Cost:** When does parallelism or extra evaluation stop paying for itself? Compare cost per accepted outcome, not tokens or runs alone.
7. **Security boundary:** Can current Codex permissions, connector permissions, and GitHub rules enforce every stated authority rule, or is an external policy enforcement point eventually necessary?
8. **Canary transfer:** Which Hydra lessons transfer to Ouroboros and Coffee Chat, and which are repository-specific? Promote only repeated patterns.
9. **Long-term coherence:** Do agent-generated repositories accumulate architectural entropy faster than the learning loop removes it? Track invariant violations, stale knowledge, and recurring cleanup.
10. **Self-reported claims:** The corpus contains valuable vendor implementation detail but few independent replications of reported throughput or cost. Do not use those numbers as OpenBoa targets without local baselines.

## Rejected interpretations

The evidence does not justify these policies:

- a human approves every step;
- an agent receives unlimited authority or final organizational accountability;
- one global autonomy level applies to every repository and action;
- every lifecycle stage requires a permanently different agent;
- tiny Issues and PRs are inherently safer;
- a peer swarm is the default architecture;
- passing CI alone proves completion or safety;
- Hydra must become a live dispatcher before the operating model is useful;
- a vendor's self-reported throughput becomes an OpenBoa success target.
