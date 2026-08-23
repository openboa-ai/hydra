# OpenBoa Operating Model

**Current practice:** `0.1.0`

This document turns the doctrine into a practical team model. Repository rules may add constraints, but they may not silently weaken shared safety boundaries.

## Roles

| Role | Who can hold it | Responsibility |
| --- | --- | --- |
| OpenBoa accountable owner | `SonSangjoon` | Sets purpose and priorities, provides resources, defines consequential boundaries, and remains accountable for OpenBoa's results. This role is inherited and is not repeated on every work item. |
| Work lead | Human or agent | Owns the assigned outcome, chooses the approach, coordinates contributors, keeps evidence current, and escalates real boundary decisions. |
| Contributor | Human or agent | Completes a bounded part of the assignment and hands back evidence and remaining risk. |
| Independent reviewer | Human or agent not responsible for the change | Tests whether the result meets the assignment and identifies material problems. |
| Human approver | Authorized human | Makes only the decisions reserved for human authority by law, policy, or the assignment. |

The work lead is a real leadership role. An agent lead is not merely the person who typed the code, and a human owner is not expected to direct every action.

## A complete assignment

Before substantial work begins, make these facts clear in the Issue, task, or conversation:

- the purpose and observable outcome;
- the work lead and any specifically delegated human decision owner;
- the lead's decision rights, including what it may change, delegate, deliver, or spend;
- available context, repositories, tools, environments, access, time, and budget;
- boundaries that require escalation;
- dependencies and people or systems that can unblock them;
- the evidence that will demonstrate the outcome.

If responsibility is larger than authority or resources, fix the assignment. Do not compensate with more prompting.

## Calibrating autonomy

Set autonomy from the work, not from a universal label. Consider:

- demonstrated capability in this kind of work;
- judgment, recovery, escalation, and handoff quality—not only code generation;
- quality and freshness of context, tools, access, time, and budget;
- impact radius and reversibility of mistakes;
- exposure to untrusted input or sensitive systems;
- cost of action, cost of delay, and strength of checks and recovery.

Routine, reversible work with strong checks should run with broad autonomy. Consequential, hard-to-reverse work needs narrower authority or a human decision at the exact boundary. Update future assignments from observed performance.

## Continuity

Role identity belongs to the continuing responsibility, not to one model or session. Preserve the assignment, role, decisions, commitments, state, and evidence in durable team surfaces so another capable agent can recover the work without pretending to be the same model instance.

Use each current surface for what it does well:

- `AGENTS.md` keeps stable local context and boundaries near the work;
- skills teach repeatable jobs and decisions;
- GitHub Issues hold assignments, owners, dependencies, and public work state;
- pull requests and checks hold change and review evidence;
- handoffs preserve continuity between people, agents, sessions, and environments;
- repository history preserves accepted artifacts and decisions.

Human organizational and legal accountability never becomes a model identity. Record a different accountable owner only if OpenBoa's organizational ownership actually changes; record narrower delegated decision authority where it is used.

## Ownership surfaces

| Surface | Owns |
| --- | --- |
| Hydra plugin | Portable doctrine, current operating guidance, skills, templates, and validators |
| Product repository | Product facts, local instructions, implementation, tests, CI, and acceptance commands |
| GitHub | Assignments, dependencies, change evidence, reviews, delivery state, and observation links |
| Codex and execution environment | Active work, plans, worktrees, tool use, tests, and bounded parallel collaboration |

Hydra does not dispatch agents or run product work. A product repository does not redefine the shared doctrine.

## Precedence

1. Law, platform safety, and enforced security boundaries.
2. Approved OpenBoa doctrine and governance.
3. Repository and workspace instructions.
4. The assignment and its explicit authority.
5. The work lead's chosen method.

A lower layer may add constraints but cannot remove a higher-layer constraint. A conflict is a boundary decision, not permission to guess.
