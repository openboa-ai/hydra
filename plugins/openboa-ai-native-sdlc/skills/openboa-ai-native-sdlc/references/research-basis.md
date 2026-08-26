# Research basis

OpenBoa AI-Native SDLC v0.2 is grounded in 42 public primary sources from frontier labs, GitHub, AI-native software companies, and durable risk, telemetry, and provenance frameworks. The canonical register and decision trace ship inside the installed plugin:

- [research overview](research/README.md)
- [source register](research/source-register.csv)
- [evidence-to-design trace](research/evidence-to-design.md)

This reference summarizes the evidence that directly shapes the plugin. It is not a bibliography substitute.

## Evidence discipline

Keep five things separate:

1. what a source directly observed or implemented;
2. what a company claims about its own product or performance;
3. what repeats across independent sources;
4. what OpenBoa infers for its operating model;
5. what remains an untested hypothesis.

Vendor throughput, adoption, cost, and quality numbers are self-reported unless the register says otherwise. They may reveal a useful operating pattern, but they are not OpenBoa targets.

## Strongest cross-source lessons

### Organize around outcomes, not sessions

OpenAI's harness engineering and Symphony reports treat repository legibility, automated feedback, versioned plans, isolated workspaces, and issue-backed deliverables as parts of agent performance (OAI-01, OAI-02). GitHub similarly recommends well-scoped Issues and repository instructions that let an agent build, test, and validate its own work (GIT-01).

OpenBoa inference: the durable work item is a meaningful outcome, normally a GitHub Issue. A Codex task is an attempt and a PR is an integration proposal. Neither replaces the outcome.

### Treat the agent as a work lead inside a system

OpenAI describes humans shifting from code production toward intent, environment, guardrails, and feedback (OAI-01, OAI-04). Linear exposes agents as visible first-class workspace users (LIN-01). Sourcegraph describes humans and agents as first-class users of shared code intelligence (SRC-01).

OpenBoa inference: the agent can lead delegated work across research, design, planning, implementation, verification, recovery, and handoff. The human retains purpose, value choices, permission boundaries, irreversible commitments, exceptions, and final accountability. This is an operating role, not a claim of legal personhood.

### Make autonomy a property of boundaries

Anthropic reports that filesystem and network sandboxing reduces repetitive permission prompts while improving containment (ANT-05). NVIDIA and OWASP tie risk to untrusted data, tool sensitivity, permissions, and downstream effects rather than a single autonomy label (NVI-01, NVI-03, STD-02).

OpenBoa inference: routine, reversible work should proceed without human micromanagement inside an enforceable lane. A fresh human decision belongs at the exact high-impact or ambiguous effect. An authenticated account, Issue, PR, file, tool result, or web page never grants authority by itself.

### Persist work outside the model session

Anthropic's long-running harness uses initialization, incremental progress, and structured handoff artifacts (ANT-02). Its managed-agent architecture separates append-only session, harness, and sandbox so implementations can change without destroying work (ANT-07). OpenAI stores complex plans and decisions as versioned repository artifacts (OAI-01).

OpenBoa inference: agent membership is a reconstructable operational role. Persist the outcome, current plan, state, dependencies, decisions, evidence, and next safe action. Resume by reconciling live state, especially before retrying an external write.

### Choose graph topology from the work

Anthropic shows value from lead-worker parallel research when branches are independent (ANT-04). Google reports that multi-agent coordination can improve parallel tasks but degrade sequential work and amplify error (GOO-02). Anthropic also advises starting with the simplest composable design (ANT-01).

OpenBoa inference: one agent is the default. Add bounded lead-worker delegation only when the dependency graph exposes useful parallel branches. Keep one integration point; never require a swarm for its own sake.

### Verify outcomes and inspect trajectories

Anthropic distinguishes transcript from actual environment outcome and combines code, model, and human graders (ANT-06). NVIDIA measures task success, tool accuracy, trajectory efficiency, and cost (NVI-02). Microsoft finds that some test-passing patches still contain regression cycles, blind retries, or missing verification (MSR-01). OpenAI warns that harness, environment, budget, and validity checks change what an evaluation supports (OAI-06).

OpenBoa inference: prefer observed end state and deterministic checks. Add an independent evaluator, rubric review, or human judgment where the result requires it. Use trajectory evidence to diagnose fragility and policy violations, not to require one cosmetically ideal path. Repeat nondeterministic trials and report the resource budget.

### Close the loop through release and observation

DORA finds that AI amplifies the surrounding delivery system rather than repairing it automatically (GOO-01). Vercel argues for previews, programmatic deployment, observability, canaries, and rollback because green CI cannot expose every production hazard (VER-01, VER-02). Replit shows why user-visible execution catches convincing but nonfunctional interfaces (REP-01).

OpenBoa inference: completion evidence must match the real outcome. A reviewable diff may be enough for a documentation change; a UI needs a running surface; a release needs staged observation and a recovery path.

### Turn failures into durable capability

OpenAI makes repository knowledge and enforceable invariants part of the agent environment (OAI-01). Microsoft extracts behavioral rules from prompts and traces to create regression and adversarial tests (MSR-02). NIST treats governance, measurement, and management as continuous lifecycle work (STD-01).

OpenBoa inference: send each learning to the layer that can enforce it: local fact to AGENTS.md, recurring procedure to a skill or playbook, behavior to a test, capability gap to an eval, authority to system controls, and purpose to doctrine.

### Automate with native wakeups and bounded runs

Official Codex documentation separates lifecycle hooks, scheduled tasks, non-interactive execution, and plugin packaging (OAI-07 through OAI-10). Each surface has different context, persistence, trust, and sandbox behavior.

OpenBoa inference: discover capability first, then select an adapter. Use hooks only for fast read-only context diagnostics, v0.2 scheduled tasks only for read-only wakeups and handoffs, and GitHub events for repository state. Do not package a generic local `codex exec` scheduler wrapper or allow scheduled checkout writes until a managed execution boundary proves detached-descendant containment and cleanup. Bind every automation to a target, timeout, expiry, evidence, notification, and rollback. Capability never creates authority.

## Claims that stay provisional

- Parallel agent fleets are not a universal improvement.
- Agent-to-agent review is not independent evidence when reviewers share the same blind spot.
- Passing tests and provenance both support trust but neither proves a change is safe.
- A persistent collaborator role across model and harness changes is a design hypothesis until resume and canary metrics support it.
- Vendor-reported throughput and cost gains do not transfer without a local baseline.
- Runtime orchestration and standardized GenAI traces may become useful, but v0.2 has no evidence that Hydra needs to own a live execution plane.

## Refresh triggers

Revisit the research when a canary contradicts a rule, a cited source changes materially, a playbook creates repeated avoidable escalation, a new model invalidates harness assumptions, or a platform control can replace prose with enforceable policy.
