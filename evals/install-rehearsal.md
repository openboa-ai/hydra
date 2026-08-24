# Plugin installation and migration rehearsal

- **Date:** 2026-08-24
- **Codex CLI:** `0.144.5`
- **Environment:** isolated temporary Codex homes, a local final-content marketplace, and a Git-source branch cutover
- **Candidate plugin tree:** `2318234b77fb08a2e57461e8b3ebf3635bb7345d`
- **Marketplace manifest blob:** `51f899c284d96d7bb7daac4d6e8f062002e57cda`

This is observed packaging evidence, not a behavioral claim about product work. The active user installation and config were not changed; the active config checksum matched before and after the rehearsals.

The retained content identities are branch-verifiable and cover the payload plus the marketplace routing used by the rehearsal:

```text
git rev-parse HEAD:plugins/openboa-ai-native-sdlc
git rev-parse HEAD:.agents/plugins/marketplace.json
```

The recorded values must match these commands on the final reviewed branch. No temporary path, user configuration, or unreachable rehearsal-only commit is needed to verify them.

## Fresh installation

The candidate repository was added as a local `openboa-hydra` marketplace in an isolated Codex home. The command record is normalized below: the temporary path is replaced, while selectors, order, and outcomes are preserved.

```text
codex plugin marketplace add <final-candidate-local-path>
codex plugin list --marketplace openboa-hydra --available --json
codex plugin add openboa-ai-native-sdlc@openboa-hydra
codex plugin remove openboa-ai-native-sdlc@openboa-hydra
codex plugin list --marketplace openboa-hydra --available --json
```

Observed results:

- `openboa-ai-native-sdlc@openboa-hydra` was discovered as version `0.1.0`.
- Installation placed the plugin in the isolated cache and reported it as installed and enabled.
- Removal succeeded and the isolated plugin list no longer reported an installed plugin.

## Existing installation migration

A Git-source marketplace branch started at the current public baseline, commit `dd712df6f61f7c5a37f24737c648032102dd3c5e`, where `openboa-operations@openboa-hydra` was available. The legacy plugin was installed in a second isolated Codex home. The same branch was then advanced by a normal fast-forward to the reviewed candidate with the plugin tree and marketplace blob recorded above.

The sanitized command sequence was:

```text
codex plugin add openboa-operations@openboa-hydra
codex plugin marketplace upgrade openboa-hydra
codex plugin list --marketplace openboa-hydra --available --json
codex plugin add openboa-ai-native-sdlc@openboa-hydra
codex plugin remove openboa-operations@openboa-hydra
codex plugin list --marketplace openboa-hydra --available --json
```

The documented sequence produced these observed results:

1. `codex plugin marketplace upgrade openboa-hydra` selected and upgraded exactly `openboa-hydra` with no reported error.
2. The marketplace exposed `openboa-ai-native-sdlc@openboa-hydra` version `0.1.0` and no longer advertised the legacy identity.
3. Installing the new plugin succeeded and reported it as enabled.
4. Removing `openboa-operations@openboa-hydra` succeeded even though it was no longer advertised by the upgraded marketplace.
5. The isolated legacy cache was removed and the current plugin cache remained.

The retained result record contains no credential, temporary path, or active-user path. It is reduced to the public repository, branch, identity, version, installed/enabled state, selected marketplace, and success/error result summarized above; no raw user configuration is committed.

## Rollback rehearsal boundary

The rehearsal observed the prerequisite for a safe pre-removal abort: the legacy plugin remained installed through marketplace upgrade, new-plugin installation, and inspection. It did not modify an active `AGENTS.md` or exercise backup restoration; the active installation was unchanged.

The post-removal public rollback requires the exact squash merge to exist on public `main`; it therefore cannot be truthfully claimed before merge. The executable revert, marketplace recovery, managed-block-only restoration, and new-task verification sequence is defined in the root [rollback runbook](../README.md#roll-back-after-removing-the-old-plugin) and must be exercised during the Hydra public canary before Issue closure.

## Still unmeasured

Explicit skill discovery in a fresh isolated Codex task is measured in the [behavior eval results](results/README.md). Implicit invocation, discovery from the merged public marketplace, and managed `AGENTS.md` discovery remain unmeasured. Product-repository adoption and Ouroboros or Coffee Chat canaries remain separate rollout decisions.
