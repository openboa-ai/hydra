# Work Graphs

A useful outcome rarely follows a perfect checklist. Work reveals dependencies, parallel opportunities, and new uncertainty as it proceeds. OpenBoa plans that work as a graph while keeping the GitHub record understandable to people and agents.

The graph is a replaceable planning method. It should help the current outcome; it must not become a new control system or a reason to add coordination overhead.

## Keep three relationships distinct

### Scope hierarchy

Scope hierarchy answers: **Which smaller outcomes make up the larger outcome?**

Use a parent GitHub Issue for the meaningful outcome and sub-issues when a child outcome can be led and verified independently. Use a task list for simple internal steps that do not deserve their own durable work item. A parent is not complete merely because its children are closed; verify the integrated outcome.

### Dependency graph

The dependency graph answers: **What must be true before another piece of work can proceed?**

Represent a real dependency with GitHub's issue relationships where available, or with explicit linked Issue references when they are not. State the unblock condition. Do not infer ordering from Issue numbers, hierarchy, assignees, labels, or the position of a card in a project view.

Dependencies should form a directed acyclic graph for the planned outcome. If two nodes appear to block each other, the work has an unresolved design decision or needs to be reshaped.

### Provenance links

Provenance answers: **Which artifacts and evidence explain how this outcome changed?**

Link the Issue to the relevant plan, decisions, commits, pull requests, checks, releases, observations, and follow-up defects. These links form an evidence trail; they do not imply that one item is a child of another or that it blocks another.

Never collapse the three relationships into one generic link. A sub-issue can be independent, a peer Issue can block the parent, and a pull request can provide evidence for several nodes.

## Shape outcome-sized nodes

A node is worth representing as a separate Issue when it has:

- a useful result that can be explained without listing file edits;
- a clear boundary and repository or environment scope;
- an identifiable work lead;
- evidence that can verify the result independently;
- authority that can be delegated without silently expanding another node;
- a size that justifies coordination and handoff cost.

Do not split work merely to increase activity or parallelism. Prompts, research queries, files, commits, test cases, review comments, and routine implementation steps are usually artifacts or checklist items, not outcome nodes.

When one outcome spans repositories, use one coordinating Issue and link repository-specific Issues only when each repository has an independently deliverable or verifiable result. Name the repository, handoff, and verification surface for every cross-repository node. Do not treat a sibling checkout as shared scratch space.

## Choose the topology from the work

Choose among four current patterns. The topology is a method, not an autonomy level. Every pattern keeps one work lead accountable for the integrated outcome, uses explicit authority and resource limits, and ends with evidence from the combined result.

### 1. Single-agent or sequential work

Use one work lead, with sequential nodes when needed, when:

- the design and implementation are tightly coupled;
- the same files, interfaces, or external state will change repeatedly;
- one result changes the constraints or interface of the next;
- a permission, decision, or external dependency is not yet resolved;
- downstream work would be discarded if the upstream hypothesis fails; or
- coordination would cost more than parallel execution saves.

Serialize strongly coupled writes. Record a meaningful checkpoint before a downstream node starts, and verify the integrated outcome after the sequence rather than treating each local success as completion.

### 2. Bounded parallel work

Use parallel agents when:

- nodes are meaningfully independent;
- each writer has an isolated worktree or a clearly non-overlapping file or system scope;
- inputs, authority, expected results, and evidence are explicit enough to avoid hidden coupling;
- each result can be tested or reviewed on its own; and
- one work lead can integrate the results and verify the combined outcome.

Declare the maximum fan-out and bound time, retries, tool use, and cost before dispatch. Stop opening new branches of work when integration or review is the bottleneck. The work lead owns conflict resolution, synthesis, and the final combined verification; successful workers do not prove the parent outcome by themselves.

### 3. Orchestrator-workers

Use an orchestrator with bounded workers when the outcome is clear but the best decomposition is not. This is useful for independent exploration, research, repository inspection, or competing technical probes that can reveal the real work graph.

The orchestrator keeps the outcome, authority boundary, budget, and current hypothesis. Give each worker a distinct question, scope, evidence requirement, and stopping condition. Workers return findings or candidate results; they do not redefine the outcome, expand authority, or create durable Issues merely because a probe ran. Bound worker count and duration, compare the results, then let the orchestrator update the graph and integrate the supported path.

### 4. Evaluator-optimizer

Use an evaluator-optimizer loop when the outcome and evaluation criteria are clear, a candidate can be improved incrementally, and the evaluator can bring a deterministic test, distinct evidence, or a deliberately separate perspective.

The evaluator reports failures and evidence against the stated criteria. The optimizer changes the candidate or justified hypothesis, then submits a new exact revision. Bound rounds, time, and cost; stop when the acceptance criteria pass, another attempt lacks a changed hypothesis, or the limit is reached. Never weaken the evaluator, test, or required check to end the loop. The work lead integrates the accepted candidate and verifies the actual outcome.

Multi-agent execution is an option, not the definition of AI-native work. A swarm of correlated agents can produce more confidence without more evidence. Prefer the simplest topology that can produce the required outcome and independent evidence.

## Map the graph to GitHub and Codex

Use existing platform concepts rather than creating a parallel tracker:

- GitHub Issues and sub-issues hold durable outcomes and scope hierarchy.
- Issue dependencies or explicit linked references record ordering and unblock conditions.
- GitHub Projects may provide a cross-Issue view, but the view is not the source of authority.
- Codex tasks and runs advance a node; they do not replace it.
- Branches and worktrees isolate writers.
- Pull requests integrate meaningful repository changes and link back to the outcome.
- Required checks, reviews, release records, and observations provide provenance and evidence.

Keep the current plan close to the Issue or in a versioned repository document when it needs review. Record only enough structure to resume, coordinate, and verify the work. Hydra does not need a live graph database, dispatcher, or custom workflow runtime for this model.

## Maintain the graph as evidence changes

At planning time, record the known nodes, dependencies, verification surfaces, and integration point. During execution:

1. compare discoveries with the current outcome and graph;
2. update the plan when a dependency, boundary, or verification approach changes;
3. create a new Issue only when a newly found outcome merits a durable node;
4. stop at the exact boundary if the discovery changes purpose, authority, or an unresolved human decision;
5. keep completed evidence linked even when the plan changes.

Do not rewrite history to make the first plan look correct. A changed graph is evidence that the team learned.

## Common failure modes

- **Micro-work:** every action becomes an Issue or pull request, and coordination replaces delivery.
- **False parallelism:** multiple agents edit the same surface or wait on an unrecorded dependency.
- **Hierarchy as schedule:** child relationships are mistaken for execution order.
- **Links as proof:** a linked pull request is treated as evidence without checking its revision and results.
- **Static plan:** the graph remains unchanged after reality invalidates it.
- **Agent count as progress:** more runs are started without independent nodes or verification.
- **Orphaned integration:** every node passes alone, but no one owns or tests the combined outcome.
