# AI-Native SDLC Lifecycle Matrix

This matrix translates recurring evidence into a candidate lifecycle. It is a design artifact for review, not a final policy.

| Stage | Human responsibility | Agent responsibility | Required artifacts | Gate and evidence |
| --- | --- | --- | --- | --- |
| Frame | Name the problem, owner, desired outcome, non-goals, and business or product intent | Clarify ambiguity, discover affected surfaces, identify dependencies and unknowns | Goal record, owner, outcome, scope, dependencies, initial risk lane | Goal is admissible only when outcome and owner are explicit |
| Plan | Approve the approach and the authority corridor | Inspect repository and references, propose plan, decompose work, select workflow topology | Plan, acceptance criteria, context package, tool and boundary declaration | Plan review confirms bounded scope, task topology, and acceptance evidence |
| Context | Decide which domain knowledge and constraints are authoritative | Gather relevant files, history, instructions, APIs, and prior decisions; record provenance | Context manifest, source list, decision record, repository commands | Context is sufficient, current, and discoverable; missing context becomes a blocker |
| Execute | Intervene on ambiguity, sensitive decisions, or scope changes | Work in an isolated run, use declared tools, make incremental changes, keep state clean | Run record, worktree, commits or documents, progress log, tool events | Run remains inside repository, goal, risk, and operation scope |
| Verify | Judge whether evidence answers the real acceptance criteria | Run tests, static checks, evaluations, previews, security checks, and independent review | Test output, trajectory summary, evaluator result, preview or artifact links | Evidence proves behavior, not only process completion |
| Approve | Make human-gate decisions and public commitments | Prepare review packet, summarize uncertainty, request approval, never self-authorize | Approval record, unresolved questions, risk decision, exception if any | Routine automation or named human reviewer authorizes next action |
| Deliver | Own release, merge, publication, or rollback decision | Execute allowed delivery steps, preserve immutable references, report result | PR/release/deployment record, immutable artifact, delivery log | Delivery state matches acceptance and repository rules |
| Observe | Confirm realized behavior and decide whether to close the goal | Inspect runtime, incidents, user or operator signals, and post-delivery regressions | Observation record, telemetry, rollback signal, follow-up issue | Goal closes only after required observation evidence exists |
| Learn | Decide which system layer should improve | Classify failure as context, tool, test, evaluator, guardrail, or workflow issue | Learning record, follow-up goal, updated test or reference | Improvement is attached to evidence and does not silently weaken policy |

## Candidate lifecycle state

The Issue state remains a durable goal state:

status:backlog → status:ready → status:in-progress → status:in-review → closed

The lifecycle stages above are evidence-bearing stages inside that goal. They are not additional Issue labels.

## Source basis

- Goal and issue control plane: OA-02, GH-01, LI-01.
- Context and repository legibility: OA-01, AN-07, GO-03, GH-04, SG-01.
- Long-running execution and handoff: OA-07, AN-02, AN-05, VE-05.
- Evaluation and observation: OA-06, AN-03, AN-04, NV-02, RE-01, VE-01.
- Boundary and approval controls: OA-03, AN-06, NV-01, NV-05, GH-03, VE-03, VE-04.
