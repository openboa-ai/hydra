# OpenBoa Hydra

Hydra publishes **OpenBoa AI-Native SDLC**, a skills-first Codex plugin for running software work through Codex and GitHub.

The plugin uses familiar development objects instead of a new workflow language:

```text
Codex Goal → GitHub parent Issue → sub-issues and dependencies
  → task worktree → tests and evals → pull request and review
  → approval → merge or deploy → observation and improvement
```

The current doctrine is a draft until `SonSangjoon` approves it. This repository does not apply GitHub administrator settings or dispatch live agents.

## Install

```text
codex plugin marketplace add openboa-ai/hydra
codex plugin add openboa-ai-native-sdlc@openboa-hydra
```

## Skills

- `$openboa-plan-work` — turn a goal into Issues, acceptance criteria, and dependencies.
- `$openboa-build-change` — implement a linked task in an isolated worktree and leave a handoff.
- `$openboa-review-change` — review the diff, tests, evals, and actual outcome.
- `$openboa-ship-change` — handle checks, approval, merge, deployment, rollback, and observation.
- `$openboa-improve-workflow` — turn repeated failures into tested workflow improvements.
- `$openboa-adopt-sdlc` — audit and update `AGENTS.md` and propose GitHub adoption changes.

## Guidance

- [Doctrine](plugins/openboa-ai-native-sdlc/references/doctrine.md) — purpose, human responsibility, and principles.
- [Operating model](plugins/openboa-ai-native-sdlc/references/operating-model.md) — ownership and decision rights.
- [Workflow](plugins/openboa-ai-native-sdlc/references/workflow.md) — development, delivery, and learning loops.
- [Governance](plugins/openboa-ai-native-sdlc/references/governance.md) — routine work and approval-required boundaries.
- [GitHub](plugins/openboa-ai-native-sdlc/references/github.md) — Issues, pull requests, Actions, rulesets, `CODEOWNERS`, and environments.
- [Evals and observation](plugins/openboa-ai-native-sdlc/references/evals.md) — outcome checks, graders, and production evidence.

These references are the portable source of truth. Product repositories keep product commands and architecture facts in their own `AGENTS.md`.

The [40-source research package](research/openboa-ai-native-sdlc-v0.1/README.md) records the external evidence, limits, and open questions behind this version.

## GitHub boundary

The Codex GitHub connector is the default for supported GitHub operations. Authentication is not authority: every write remains tied to the intended repository, linked Goal or Issue, risk, and exact action. Local `git` handles worktrees, diffs, commits, and tests. Use `gh` or a direct API only for a missing connector capability and record the exception.

Routine, reversible changes may auto-merge after required checks and independent review. Workflows, `CODEOWNERS`, permissions, secrets, security, migrations, infrastructure, public doctrine, and irreversible actions require human approval.

## Migrate from OpenBoa Operations

Version `0.1.0` replaces the preview `openboa-operations` plugin rather than keeping two policy sources. `$openboa-adopt-sdlc` uses [sync_agents.py](plugins/openboa-ai-native-sdlc/scripts/sync_agents.py) to replace one valid legacy managed block while preserving repository-local text. Duplicate, malformed, or unknown-version markers are refused.

The required check named `openboa-governance` remains as a temporary compatibility check. After a repository administrator changes the GitHub ruleset to require `openboa-ai-native-sdlc`, remove the compatibility job in a follow-up pull request.

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

`validate_codex.py` finds the official plugin and skill validators through `CODEX_HOME`, falling back to `~/.codex`, and validates the plugin plus all six skills.
