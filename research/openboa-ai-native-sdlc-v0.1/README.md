# OpenBoa AI-Native SDLC v0.1 Research

**Status:** Research and design basis for review; not approved policy.

**Goal:** [Hydra Issue #3](https://github.com/openboa-ai/hydra/issues/3)

**Accountable owner:** SonSangjoon

**Risk:** Approval required

This package asks a different question from the earlier workflow-first draft: what must an organization provide when an agent is treated as a team member who can lead work rather than as a tool that needs step-by-step supervision?

OpenBoa's answer is a position to test, not a vendor claim to copy:

> Human leaders set purpose, allocate resources, and hold organizational accountability. Agent leads take responsibility for outcomes inside delegated authority. The system should make the agent more capable and more independent over time without giving away purpose or unbounded authority.

## Reading path

1. [Lessons](lessons.md) — observed evidence, vendor claims, OpenBoa inference, and OpenBoa's position.
2. [Workflow](workflow.md) — the current candidate for direction, delegation, autonomous work, delivery, and learning.
3. [GitHub](github.md) — how GitHub and Codex can support the relationship without becoming the doctrine.
4. [Evals](evals.md) — outcome, capability, teamwork, system, and leadership evidence.
5. [Open questions](open-questions.md) — questions that require canary evidence or later platform capability.

[sources.csv](sources.csv) is the source ledger behind the synthesis. It records what each source claims, the evidence it presents, its preconditions and failure modes, and how it may apply. The number of sources is not a success metric.

## Evidence boundaries

- **Observed:** a source documents an implementation, experiment, platform behavior, or measured result.
- **Claimed:** a company describes its own product or performance. These claims remain source-specific.
- **Inferred:** OpenBoa derives a condition that appears across multiple sources.
- **OpenBoa position:** OpenBoa chooses a philosophy or responsibility model that evidence alone cannot decide.
- **Unresolved:** a question needs a canary, independent evidence, or a human decision.

The employee-like team-member stance is an OpenBoa position. External evidence supports the need for context, durable work, adjustable autonomy, evaluation, and enforced boundaries; it does not establish legal personhood, consciousness, or a universal employment model.

## Scope

The v0.1 target remains a portable Codex plugin made of skills, references, templates, and deterministic validation. It does not add an agent runtime, identity database, scheduler, GitHub App, MCP server, or custom lifecycle format.

Ouroboros and Coffee Chat are later canaries. They may expose gaps in the current method; they do not define the doctrine.

## Verify

```bash
python3 scripts/validate_research.py .
python3 -m unittest tests.test_research_artifacts -v
```
