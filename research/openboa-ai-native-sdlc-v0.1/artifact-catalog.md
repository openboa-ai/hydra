# Artifact, Handoff, and Evidence Catalog

This catalog defines the minimum durable artifacts proposed by the research model. It is intentionally provider-neutral.

| Artifact | Created at | Owned by | Minimum fields | Used by | Evidence or retention rule |
| --- | --- | --- | --- | --- | --- |
| Goal record | Frame | Human owner | goal, owner, outcome, scope, dependencies, risk lane, acceptance evidence | All later stages | Must remain discoverable until closure |
| Context manifest | Context | Agent prepares; owner validates | source paths, decisions, commands, provenance, freshness, exclusions | Plan and Execute | Record what context was used for consequential decisions |
| Plan | Plan | Agent prepares; human accepts when required | approach, topology, boundaries, steps, stop conditions, expected evidence | Execute and Review | A scope change requires plan update or handoff |
| Run record | Execute | Delegated actor | run ID, workspace, branch/worktree, start/end, tools, allowed operations | Handoff and audit | One run cannot silently replace the goal |
| Progress record | Execute | Delegated actor | completed work, remaining work, tests, decisions, blockers, next action | Next session | Update at each context boundary |
| Change record | Execute/Deliver | Run actor | changed files, commits, PR or document links, rationale | Verify and Approve | Must be reviewable independently of the transcript |
| Verification packet | Verify | Agent prepares; reviewer interprets | commands, results, evaluator, trajectory summary, limitations, environment | Approve and Observe | A green command is one evidence item, not completion |
| Approval record | Approve | Human gate owner or automation | decision, conditions, evidence reviewed, authority, timestamp | Deliver | Required before human-gate actions |
| Delivery record | Deliver | Delivery owner | merge/release/deploy/publication, immutable reference, result | Observe | Preserve rollback reference |
| Observation record | Observe | Human owner | realized state, runtime signals, incidents, user/operator feedback, follow-up | Learn and Close | Required before goal closure when the risk lane demands it |
| Handoff packet | Any boundary | Current actor | goal, state, changed artifacts, evidence, blocker, decision needed, next safe action | Successor actor | No hidden transcript is required |
| Learning record | Learn | Human owner | failure class, evidence, smallest useful layer to improve, follow-up goal | Future work | Do not weaken a policy as a failure workaround |

## Handoff invariant

A successor should be able to resume from the repository state and the handoff packet without relying on the previous agent's hidden conversation.

## Evidence invariant

Evidence must answer the acceptance criterion it is attached to. A source, test, review, preview, or metric that does not answer a criterion remains context, not completion evidence.

## Source basis

- Long-running state and handoff: AN-02, AN-05, OA-07, VE-05.
- Goal and delivery entities: OA-02, LI-01, GH-01.
- Trajectory and outcome evidence: AN-04, NV-02, OA-06.
- Observation and runtime surfaces: VE-01, VE-02, RE-01.
