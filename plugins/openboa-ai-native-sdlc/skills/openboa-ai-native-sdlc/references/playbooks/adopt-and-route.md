# Adopt and route

**Change rate:** fast. This is a replaceable method, not doctrine.

Use this playbook to adopt the plugin, add or refresh an `AGENTS.md` contract, or decide where new knowledge belongs.

## Adopt safely

1. Confirm the workspace and repository, then check whether the exact repository root already contains `AGENTS.md` and whether an `AGENTS.override.md` would take precedence.
2. For a greenfield repository with no `AGENTS.md`, create the file manually from the packaged `assets/managed-AGENTS.md` template. Confirm the target is absent first, then replace the example repository-local bullets with actual local commands, architecture facts, and stricter controls. Review this bootstrap as a normal repository change.
3. Once `AGENTS.md` exists, run the packaged synchronization script without `--write` and review its proposed action. The script intentionally does not create a missing file.
4. Use `--write` only for the exact existing target after check mode succeeds. The script must preserve the local instructions section and refuse ambiguous layouts.
5. A successful changed write reports a retained `.AGENTS.md.sync-*` recovery file containing the pre-change inode. Record that path, keep it out of commits, and inspect it with the target before doing anything else. A later changed write refuses to run while an earlier recovery file remains.
6. Inspect the diff, run repository validation, and start a new Codex task to verify instruction discovery. Keep an external backup until this verification completes. After verification, move the recovery file to the protected backup location or remove it deliberately; never let a cleanup command target a broad directory.
7. Keep product-specific commands and architecture facts local. Link to the plugin for shared principles and methods.

```text
python3 <installed-skill>/scripts/sync_agents.py <repository-or-AGENTS.md>
python3 <installed-skill>/scripts/sync_agents.py --write <repository-or-AGENTS.md>
```

Do not pass a repository without `AGENTS.md` to the script and interpret refusal as failed adoption. Bootstrap the file manually, review it, then use check mode and write mode for future managed-block updates.

## Route knowledge by lifetime

- Enduring purpose and human-agent principles belong in doctrine.
- Organization roles and decision boundaries belong in the operating model.
- A repeatable way of working belongs in a playbook or skill.
- A repository fact, command, or constraint belongs in its nearest `AGENTS.md`.
- Product behavior belongs in code and tests.
- A capability claim belongs in an eval.
- A permission boundary belongs in the platform, repository rules, sandbox, or credential policy—not only in prose.

## Plugin identity migration

For an existing `openboa-operations@openboa-hydra` installation:

1. Preserve an exact external backup of the target `AGENTS.md` before changing it.
2. Upgrade the `openboa-hydra` marketplace.
3. Install `openboa-ai-native-sdlc@openboa-hydra` without removing the old plugin.
4. Start a new Codex task and confirm this skill is available.
5. Run the managed `AGENTS.md` migration in check mode, then write mode. Record and inspect the reported recovery file.
6. Verify the diff, repository checks, managed block, local instructions, and another new task.
7. Remove `openboa-operations@openboa-hydra` only after every prior step passes.
8. Restart Codex or begin another new task and verify the old skill is gone.

Rehearse this sequence in a temporary Codex home before changing an active installation. If any step fails, keep the old plugin and stop. To abort or roll back, use the external backup or retained recovery file as the source for a reviewed managed-block-only edit; preserve the target's current repository-local section byte for byte. Never restore the whole file over newer local instructions. Refuse mixed, missing, duplicate, or overlapping markers rather than guessing. Do not delete plugin cache directories by hand.

## Stop conditions

Do not auto-edit a symlink, an override-managed location, a file outside the requested target, duplicate or mixed marker blocks, malformed markers, a block overlapping local instructions, or a contract from an unsupported higher major version. Report the exact conflict and leave the file unchanged.
