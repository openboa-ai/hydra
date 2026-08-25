# OpenBoa AI-Native SDLC

Hydra is the public Git marketplace for `openboa-ai-native-sdlc`, a portable way for humans and AI agents to lead software work together.

The foundation is simple:

> Humans own purpose and final accountability. Agents lead delegated work. Systems enforce authority and safety boundaries.

This is not a traditional human process with code generation attached. The lifecycle gives agents meaningful responsibility for understanding goals, research, design, planning, delegation, implementation, verification, recovery, handoff, and learning. Human attention is reserved for purpose, values, new authority, irreversible or material consequences, public commitments, and genuine ambiguity.

The foundation changes slowly. The playbooks can change whenever better models, tools, and engineering practices become available.

## Read the system

- [Doctrine](DOCTRINE.md) — the durable human-agent philosophy
- [Operating model](OPERATING-MODEL.md) — roles, situational leadership, work, and decision boundaries
- [AI-Native SDLC](AI-NATIVE-SDLC.md) — the outcome-to-learning lifecycle and work graphs
- [Governance](GOVERNANCE.md) — authority, approvals, GitHub/Codex controls, and evaluation
- [Research](research/openboa-ai-native-sdlc-v0.1/README.md) — primary-source evidence, conflicts, and OpenBoa inferences

These root pages are navigation surfaces. The canonical, portable documents and playbooks live inside the plugin so an installed skill carries the complete working context.

## Install

Add the public marketplace and install the plugin:

```text
codex plugin marketplace add openboa-ai/hydra
codex plugin add openboa-ai-native-sdlc@openboa-hydra
```

Start a new Codex task after installation. Codex discovers plugin skills and `AGENTS.md` instructions when a task starts.

Invoke `$openboa-ai-native-sdlc` directly, or ask Codex to shape, plan, execute, review, ship, observe, or improve OpenBoa work.

## Migrate from OpenBoa Operations

The plugin rename is an identity migration, not an in-place update. Rehearse it with a temporary Codex home before changing an active installation. Keep the old plugin installed and preserve an exact content backup of the target `AGENTS.md` until the new plugin, managed block, and a new task have all been verified.

Choose one explicit target and create a backup that does not already exist:

```bash
AGENTS_TARGET=/absolute/path/to/AGENTS.md
AGENTS_BACKUP=/absolute/path/outside-the-repository/AGENTS.md.openboa-operations-backup
test -f "$AGENTS_TARGET"
test ! -L "$AGENTS_TARGET"
test ! -e "$AGENTS_BACKUP"
cp -p "$AGENTS_TARGET" "$AGENTS_BACKUP"
```

Upgrade the marketplace and install the new identity without removing the old one:

```text
codex plugin marketplace upgrade openboa-hydra
codex plugin add openboa-ai-native-sdlc@openboa-hydra
```

Start a new task and confirm the new skill is available. Then locate the installed skill's `scripts/sync_agents.py` and migrate only the backed-up target. The first and third commands are read-only checks:

```bash
SDLC_SYNC_SCRIPT=/absolute/path/to/installed/sync_agents.py
python3 "$SDLC_SYNC_SCRIPT" "$AGENTS_TARGET"
python3 "$SDLC_SYNC_SCRIPT" --write "$AGENTS_TARGET"
python3 "$SDLC_SYNC_SCRIPT" "$AGENTS_TARGET"
```

After the new task and managed block are verified:

```text
codex plugin remove openboa-operations@openboa-hydra
```

Restart Codex or start another new task and confirm the old skill is no longer available. Do not delete Codex cache directories manually.

### Abort before removing the old plugin

Do not remove `openboa-operations` if marketplace upgrade, installation, a validator, managed-block synchronization, or new-task discovery is missing, inconsistent, or unsafe. If `AGENTS.md` was already changed, first confirm that the target is still a regular non-symlink file. Restore only the managed block from the preserved backup through a reviewed edit. Keep the current repository-local section byte for byte; never copy the whole backup over a file that may have gained local instructions. Review the resulting diff and stop unless the managed block is the only change.

```bash
test -f "$AGENTS_BACKUP"
test -f "$AGENTS_TARGET"
test ! -L "$AGENTS_TARGET"
codex plugin remove openboa-ai-native-sdlc@openboa-hydra
```

Begin a new task and confirm the legacy skill and restored instructions are active. Retain the failed evidence and backup; do not retry until the failed assumption has changed.

### Roll back after removing the old plugin

Stop further installation and product-repository adoption when the public marketplace cannot install the declared version, a new task cannot discover the skill or managed instructions, a required validator or check fails, an authority or security boundary is weakened, or the canary shows unsafe core behavior.

Record both the reviewed pull-request head and the squash merge commit that reached `main`. Roll back the public cutover with one revert pull request; do not rewrite `main`, move a published tag, or make an unreviewed direct push:

```bash
PUBLIC_MERGE_SHA=replace_with_exact_40_character_squash_merge_sha
ROLLBACK_WORKTREE=/absolute/path/to/hydra-openboa-ai-native-sdlc-rollback
git fetch origin
test "$(git cat-file -t "$PUBLIC_MERGE_SHA")" = commit
git merge-base --is-ancestor "$PUBLIC_MERGE_SHA" origin/main
git worktree add -b revert/openboa-ai-native-sdlc-v0.1 "$ROLLBACK_WORKTREE" origin/main
git -C "$ROLLBACK_WORKTREE" revert --no-edit "$PUBLIC_MERGE_SHA"
git -C "$ROLLBACK_WORKTREE" push -u origin HEAD
```

Open one pull request from `revert/openboa-ai-native-sdlc-v0.1`, wait for `openboa-governance`, review the exact revert head, and wait for the human merge gate. After the revert is merged and the marketplace again advertises the legacy identity, recover an installation that migrated from `openboa-operations` in this order:

```bash
codex plugin marketplace upgrade openboa-hydra
codex plugin add openboa-operations@openboa-hydra
test -f "$AGENTS_BACKUP"
test -f "$AGENTS_TARGET"
test ! -L "$AGENTS_TARGET"
```

Use the backup as the source for a reviewed managed-block-only edit. Preserve the target's current repository-local section exactly, inspect the diff, and run the repository's instruction and governance checks. If the marker pair is missing, mixed, duplicated, or overlaps the local section, stop and keep both plugins installed until the file can be repaired safely. Only after that succeeds:

```bash
codex plugin remove openboa-ai-native-sdlc@openboa-hydra
```

Start a new task, confirm the legacy skill and restored managed block are active, then start another new task and confirm the new identity is absent. Keep the backup until the rollback observation is complete.

For a fresh-install canary that had no legacy plugin or managed block, upgrade the reverted marketplace, remove `openboa-ai-native-sdlc`, and start a new task to confirm it is absent. Do not invent a legacy installation or restore an `AGENTS.md` backup that did not exist.

Never silently replace a plugin payload that has already been published as `0.1.0`. A forward fix or later reintroduction must increment the plugin version, beginning with `0.1.1`, keep the marketplace entry pointed at the corrected package, and repeat install, migration, new-task, and rollback checks before another public merge.

## Package map

The plugin contains one core/router skill and five replaceable playbooks:

- adopt and route;
- shape and plan;
- execute and hand off;
- review and ship; and
- observe and improve.

It contains guidance, templates, deterministic validation, and a safe `AGENTS.md` synchronization script. v0.1 deliberately contains no MCP server, hook, daemon, dispatcher, custom runtime, credential broker, or live work database.

Hydra is the portable source. Codex is the execution surface. GitHub Issues, pull requests, Actions, rulesets, releases, and deployments are the durable control plane and evidence surfaces. Product repositories remain the source of truth for product behavior and local commands.

## Development

Keep public content free of secrets, private repository details, and undisclosed vulnerabilities. Preserve the externally required Actions check name `openboa-governance` during this migration.

The current `openboa-governance` job is candidate-conformance and bootstrap evidence. It runs candidate-controlled repository validation with a read-only token, pinned actions, and no secrets, publication, or deployment authority. At the v0.1 review gate the active ruleset accepted this context from `Any source`; re-read the live rule and verify the producer in the pull-request merge box rather than describing this job as a trusted base-controlled policy check. Binding an expected source or introducing a base- or ruleset-controlled trusted workflow requires a separate post-merge canary, live readback, and explicit human approval; it is not part of this repository migration.

This repository now also carries the staged trusted-check pieces: `.github/openboa-governance.yml` names control-plane paths, `scripts/validate_governance.py` inspects a candidate tree as data, and `.github/workflows/openboa-governance-v2.yml` checks out the trusted Hydra source, the recorded base revision, and the candidate separately. The candidate risk lane is calculated from the event's base and head checkouts, not from a moving `main` branch. The `openboa-governance-v2` workflow is bootstrap evidence only until a human-gated ruleset canary binds the source repository, branch, and workflow file. The existing `openboa-governance` context remains required during that transition; no live ruleset was changed by adding these files.

Run the repository checks:

```text
python3 scripts/validate_hydra.py .
python3 -m unittest discover -s tests -v
git diff --check
```

Run the official Codex validators from an installed Codex development environment:

```text
uv run --with PyYAML python3 scripts/run_codex_plugin_validator.py
```

The wrapper locates the official plugin and skill validators through `CODEX_HOME` or the default Codex directory. It fails clearly when they are unavailable; it never substitutes the repository's own validator for the official check.

## Release posture

`0.1.0` is a candidate foundation. Merge of the exact reviewed pull-request head is the public-change gate. Live GitHub ruleset changes and adoption in Ouroboros or Coffee Chat are separate decisions after the Hydra canary passes.

After a squash merge, record the reviewed pull-request head and the resulting `main` commit separately. Completion requires more than merged files: validate a fresh install, begin a new task, confirm skill and instruction discovery, exercise the behavioral scenarios, and observe the intended agent-led behavior. Keep the Issue open and record missing evidence as `unknown` or `unmeasured`. Use the rollback runbook above if the public canary crosses a stop condition.
