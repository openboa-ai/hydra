# OpenBoa Hydra

Hydra publishes **OpenBoa AI-Native SDLC**, a portable Codex plugin for building effective human-agent software teams.

The premise is simple: an agent is an organization member that can understand an assignment, exercise judgment, lead work, collaborate, and improve—not merely a tool that waits for the next command. OpenBoa's human leader remains accountable for purpose, priorities, resources, consequences, and the quality of delegation. The agent work lead owns its assigned outcome inside clear authority.

Approving every ordinary step is failed delegation. Giving away purpose, unlimited authority, and accountability is failed leadership. The operating system between those extremes should give each agent the context, tools, access, time, budget, feedback, and safety needed to do its best work.

OpenBoa has one inherited accountable human, `SonSangjoon`; it is not repeated in every Issue or pull request. Work records contain the facts that change: purpose, work lead, authority, resources, boundaries, dependencies, evidence, and any specifically delegated human decision.

The public doctrine is a draft until `SonSangjoon` approves it. This v0.1 plugin installs no custom runtime, live dispatcher, or scheduler. Codex and GitHub are the current methods, not the timeless purpose.

## Current working method

```text
Direction → Assignment → Lead → Review → Deliver → Learn
```

A work lead may be human or agent. It chooses the plan and continues through ordinary decisions within its assignment. Human decisions appear only at consequential boundaries reserved by law, policy, organizational authority, or the assignment.

## Install

```text
codex plugin marketplace add openboa-ai/hydra
codex plugin add openboa-ai-native-sdlc@openboa-hydra
```

## Skills

- `$openboa-delegate-work` — give a work lead a complete outcome, authority, resources, boundaries, and evidence.
- `$openboa-lead-work` — let a human or agent lead own the assignment and coordinate its execution.
- `$openboa-review-work` — independently review the outcome, change, authority use, and working system.
- `$openboa-deliver-work` — deliver authorized work, request only exact human decisions, observe, and recover.
- `$openboa-improve-system` — turn failures and rework into a more capable human-agent team.
- `$openboa-adopt-sdlc` — adopt the model, managed `AGENTS.md`, templates, and GitHub controls without losing local knowledge.

## Guidance

- [Doctrine](plugins/openboa-ai-native-sdlc/references/doctrine.md) — stable purpose and principles.
- [Operating model](plugins/openboa-ai-native-sdlc/references/operating-model.md) — roles, responsibility, authority, resources, and continuity.
- [Workflow](plugins/openboa-ai-native-sdlc/references/workflow.md) — the current, replaceable way of working.
- [Governance](plugins/openboa-ai-native-sdlc/references/governance.md) — broad autonomy with enforced consequential boundaries.
- [Codex](plugins/openboa-ai-native-sdlc/references/codex.md) — how tasks, plans, `AGENTS.md`, skills, worktrees, subagents, review, and automation fit together.
- [GitHub](plugins/openboa-ai-native-sdlc/references/github.md) — Issues, projects, pull requests, Actions, rulesets, `CODEOWNERS`, and environments.
- [Evals and observation](plugins/openboa-ai-native-sdlc/references/evals.md) — outcome, work-lead, team-system, and leadership evidence.

Product repositories keep product commands and architecture facts in their own `AGENTS.md`. Hydra keeps portable doctrine and working guidance.

The [46-source research package](research/openboa-ai-native-sdlc-v0.1/README.md) records external evidence from 13 organizations, source grades, disagreements, lessons, and open questions behind this draft. Company claims remain separate from operating evidence.

## Codex and GitHub boundary

Use the Codex GitHub connector as the default for supported GitHub operations. Authentication is not authority: every write remains tied to the intended repository, assignment, exact operation, and decision rights. Local `git` handles worktrees, diffs, commits, tests, and Git-object pushes. Use `gh` or a direct API only for a missing connector capability and record the bounded exception.

Routine, reversible agent-led work may auto-merge after required checks and independent review. A human decision is required only at the exact boundary reserved by governance or the assignment. Enforce identity, access, rulesets, secrets, deployment protection, budgets, and recovery below agent-controlled instructions.

## Migrate from OpenBoa Operations

Version `0.1.0` replaces the preview `openboa-operations` plugin rather than keeping two policy sources. `$openboa-adopt-sdlc` uses [sync_agents.py](plugins/openboa-ai-native-sdlc/scripts/sync_agents.py) to replace one valid legacy managed block while preserving repository-local text. Duplicate, malformed, overlapping, or unknown-version markers are refused.

The required check named `openboa-governance` remains temporarily for compatibility. After a repository administrator changes the GitHub ruleset to require `openboa-ai-native-sdlc`, remove the compatibility job in a follow-up pull request.

If the preview plugin is installed, remove it before refreshing the marketplace and installing the replacement:

```bash
codex plugin remove openboa-operations@openboa-hydra
codex plugin marketplace upgrade openboa-hydra
codex plugin add openboa-ai-native-sdlc@openboa-hydra
codex plugin list --marketplace openboa-hydra
```

Start a new Codex task after installation so the six new skills are loaded. Do not keep both plugin identities enabled.

## Validate

```bash
python3 scripts/validate_hydra.py .
python3 scripts/validate_research.py .
python3 -m unittest discover -s tests -v
python3 scripts/validate_codex.py .
```

`validate_codex.py` locates the official plugin and skill validators through `CODEX_HOME`, falling back to `~/.codex`, and validates the plugin plus all six skills.
