# Evidence Synthesis

**Status:** Draft synthesis for review; not approved policy.

## Executive finding

Across the corpus, the strongest convergence is not that agents should receive more freedom. It is that software teams must make purpose, context, execution boundaries, verification, and accountability explicit enough for an agent to operate without guessing.

The proposed design implication for OpenBoa is:

> Treat the goal, its authority corridor, its context package, its execution attempt, its evidence, and its observation as one connected lifecycle record. Treat sessions, worktrees, commits, and pull requests as replaceable attempts inside that record.

This is supported by the goal/control-plane framing in OpenAI Symphony (OA-02), the repository-legibility and invariant work in OpenAI Harness Engineering (OA-01), Anthropic's long-running handoff harness (AN-02), Linear's separation of human ownership and agent delegation (LI-01), and GitHub's issue-to-PR coding-agent flow (GH-01, GH-02).

## Recurring patterns

| Pattern | Evidence | Candidate OpenBoa implication | Confidence |
| --- | --- | --- | --- |
| Durable goal over session | OA-02, AN-02, GH-01, LI-01 | Make a human-owned goal the primary work entity; attach attempts, changes, and evidence to it | High |
| Context is infrastructure | OA-01, AN-07, GO-03, GH-04, SG-01 | Version repository guidance, acceptance criteria, decision records, and context provenance | High |
| Harness and runtime matter as much as model | OA-03, OA-05, OA-07, AN-05, VE-02, VE-03 | Define stable harness interfaces, isolated execution, resumable state, and runtime adapters | High |
| Verification is an execution loop | OA-06, AN-03, AN-04, NV-02, RE-01, VE-04 | Require objective checks and independent evaluation before approval | High |
| Authority is not identity | NV-01, NV-05, GH-02, LI-01, VE-04 | Bind actions to workspace, repository, goal, risk lane, operation, and human owner; never infer authority from account identity | High |
| Runtime safety is layered | OA-03, AN-06, NV-04, NV-06, NV-07, GH-03 | Use sandbox, network, credential, safe-output, and monitoring controls together | High |
| Long-running work needs continuity | OA-02, OA-07, AN-02, AN-05, VE-05, GO-01 | Persist state and leave structured handoff artifacts at every context boundary | High |
| Parallelism is conditional | AN-03, GO-04, CU-01 | Select single-agent, sequential, or parallel execution from task topology and review capacity | Medium-high |
| Review becomes a scarce resource | OA-02, CU-01, FA-01, VE-01 | Bound task size and optimize for reviewable evidence, not raw agent throughput | Medium-high |
| Operations joins the SDLC | OA-04, OA-06, VE-01, VE-04 | Extend the lifecycle through deployment, observation, incident response, and learning | High |

## Candidate principles

These are proposals, not doctrine.

### 1. Goals over sessions and artifacts

A goal has one human owner, an outcome, acceptance evidence, dependencies, and a risk lane. A session, run, worktree, commit, or PR advances the goal but does not replace it.

**Evidence:** OA-02, AN-02, GH-01, LI-01.

### 2. Context is a versioned operating surface

Repository instructions, architecture boundaries, acceptance criteria, test commands, decisions, and handoffs are executable context. They must be discoverable, bounded, and kept near the work.

**Evidence:** OA-01, AN-07, GO-03, GH-04, SG-01.

### 3. Autonomy is bounded delegation

An agent may choose procedures inside an explicit authority corridor. Purpose, public commitments, irreversible decisions, secrets, identity, and sensitive tools remain governed by the named human owner and risk lane.

**Evidence:** NV-01, NV-05, OA-03, LI-01, VE-04.

### 4. Evidence outranks assertion

Completion requires acceptance evidence, delivery state, and required observation evidence. A green process exit, generated report, or agent statement is not sufficient.

**Evidence:** AN-04, NV-02, OA-06, GH-01, VE-01.

### 5. Continuity is a first-class artifact

Every long-running attempt must leave clean repository state, progress, decisions, changed surfaces, checks, blockers, and next action.

**Evidence:** AN-02, AN-05, OA-07, VE-05.

### 6. Complexity must earn its place

Use a deterministic workflow when it is sufficient. Add agentic routing, evaluators, subagents, or parallel execution only when task variability or topology justifies the added failure surface.

**Evidence:** AN-01, AN-03, GO-04.

### 7. Portable meaning, local adapters

Keep the semantics of goal, state, owner, evidence, and gate stable across Codex, Claude, GitHub, local worktrees, and future runtimes. Treat manifests, connectors, and workflow implementations as adapters.

**Evidence:** OA-05, AN-05, GO-01, VE-02, VE-03.

## Contradictions and limitations

### Autonomy versus approval

Product sources emphasize longer autonomous runs (CU-01, RE-01), while security sources emphasize explicit approvals and isolation (OA-03, AN-06, NV-01, VE-04). These are not necessarily inconsistent: autonomy can expand inside a sandbox while sensitive boundary crossings remain gated.

**OpenBoa decision:** Define autonomy by action and boundary, not by elapsed time or agent label.

### Single agent versus multi-agent

Anthropic reports benefits from planner/generator/evaluator structures (AN-03), while Google Research finds multi-agent coordination degrades sequential tasks (GO-04). The evidence supports a topology-dependent choice, not a universal swarm.

**OpenBoa decision:** Require a task-topology justification before parallel delegation.

### Product metrics versus operational evidence

Cursor, Replit, and Vercel publish adoption or speed claims (CU-01, RE-01, VE-01). These are useful directional signals but do not prove quality, safety, or transferability to OpenBoa.

**OpenBoa decision:** Keep self-reported claims in a separate evidence class and require local validation.

### Platform coupling versus portability

Google, Vercel, and GitHub expose powerful managed runtimes (GO-01, GO-02, VE-02, GH-03). Anthropic and OpenAI emphasize stable harness primitives (AN-05, OA-05). The common abstraction is not a shared API; it is durable state, scoped tools, observable execution, and explicit gates.

**OpenBoa decision:** Standardize semantics and evidence, not provider-specific implementation.

## Source gaps

- Cognition/Devin did not yield a sufficiently detailed public engineering source in the initial pass. Its product claims should not be used as normative evidence until a primary technical source is available.
- Enterprise adoption evidence outside vendors is still thin. Internal engineering reports from companies such as Stripe, Shopify, Uber, or similar should be added only when they expose operational detail and measurement methodology.
- Current sources overrepresent vendor perspectives. A later pass should add independent evaluations, incident reports, and open-source implementations.
