# OpenBoa Hydra

OpenBoa Hydra is the public Git marketplace for the OpenBoa Operations plugin. It distributes a portable operating contract for agentic work: doctrine, ownership, workflow, governance, GitHub policy, and repository bootstrap templates.

The repository is intentionally independent of the former Nest and Hydra contents. The current doctrine is a draft until `SonSangjoon` approves it; no release tag or organization-wide enforcement rollout is implied by the draft.

## Install

Add the public marketplace and install the plugin in Codex:

```text
codex plugin marketplace add openboa-ai/hydra
codex plugin add openboa-operations@openboa-hydra
```

Then invoke the `openboa-operations` skill to bootstrap a workspace, audit repository adoption, or synchronize the managed `AGENTS.md` block. GitHub control-plane actions use the Codex GitHub connector by default; a direct `gh` or API fallback requires a recorded governance exception.

## Package map

- [Doctrine](plugins/openboa-operations/skills/openboa-operations/references/doctrine.md) — vision, era thesis, and principles
- [Operating model](plugins/openboa-operations/skills/openboa-operations/references/operating-model.md) — ownership, repository roles, and decision rights
- [Workflow](plugins/openboa-operations/skills/openboa-operations/references/workflow.md) — goals, states, delivery, handoff, and completion
- [Governance](plugins/openboa-operations/skills/openboa-operations/references/governance.md) — risk lanes, human gates, audit, exceptions, and rollback
- [GitHub profile](plugins/openboa-operations/skills/openboa-operations/references/github.md) — GitHub projection and enforcement contract

## Development

The repository is English-only. Keep the skill self-contained: reference documents and templates belong inside the skill directory, while the root files route maintainers to them. Run the repository validator and the official Codex plugin validator before publishing a release.

```bash
python3 scripts/validate_hydra.py .
python3 /Users/sangjoon/.codex/skills/.system/plugin-creator/scripts/validate_plugin.py plugins/openboa-operations
python3 -m unittest discover -s tests -v
```

## Release posture

`0.1.0` is the first preview contract. The doctrine remains non-normative until explicit human-gate approval is recorded. Promote to `1.0.0` only after approval, all public OpenBoa repositories have adopted the managed contract, and the GitHub audit is clean. Do not rewrite release tags.
