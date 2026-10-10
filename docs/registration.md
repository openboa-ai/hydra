# Register a product

Keep one reviewed `.hydra.toml` in the product's protected default branch. Its
repository ID prevents a recreated repository with the same name being adopted.
Add `/.hydra.toml` to the effective CODEOWNERS policy. Policy, required gates and
holdout changes retain current-head native human review.

Copy the [example contract](../examples/.hydra.toml), then replace its repository
identity, workflow IDs, job names, reviewers, path boundaries and commands with
observed values. Do not enable automatic merge until strict protection, provider
reviews and production effects are verified. This file references existing product
specifications; it does not duplicate product requirements.

Create ready, paused and decision labels using the contract's exact names. Hydra
manages the common `hydra:active` label while work or completion reconciliation is
unfinished. Leave it attached until verified completion; it is a discovery and
display label, not verification evidence. A ready
Issue is written by an authorized repository writer and states a public goal, scope
and acceptance criteria:

````markdown
## Goal
Describe the project's supported development workflow.

## Scope
Update CONTRIBUTING and its scoped specification. Product features are excluded.

## Acceptance
Examples match the actual CLI; registered verification and current CI pass; code
and security review findings are addressed; merged main is checked.

```hydra
spec = "docs/engineering/development-workflow/spec.md"
dependencies = []
priority = 0
```
````

Hydra binds the exact delegated Issue title/body before execution. Editing its goal,
acceptance or intake holds the existing attempt while preserving its checkpoint and
other waits. Restore the delegated text to continue; use a new Issue for changed scope.
Labels/comments remain available for pause, decision and handover without rebinding it.

`spec_revision` may pin a previously accepted specification commit. A SHA alone is
not acceptance: Hydra independently examines the actual specification before
dependent implementation. Issue text cannot supply executable verification commands.

## Operator decisions and handover

Use the paused label to stop new work, remove it to resume, and close an Issue to
cancel further delivery. Important product choices hold that Issue while siblings
continue. Record the choice in an Issue comment without changing its bound title,
body or accepted scope, then an authorized actor records `hydra: decision ATTEMPT_UUID resolved`. A repeated failure requires diagnosis
and `hydra: replan ATTEMPT_UUID ready`, rather than an endless correction loop.

For a host change: stop the old `serve`, confirm its supervised worker and uncertain
external actions, commit/push the checkpoint, then record
`hydra: handover ATTEMPT_UUID stopped` from an authorized actor before starting the
new host. The old heartbeat is not shutdown evidence. Preserve unpublished local
changes if GitHub is unavailable.

UI paths are pinned in `ui_paths`. Share an actual screen with the operator and
record `hydra: screen FULL_HEAD_SHA https://github.com/.../evidence` in an authorized
Issue comment before final PR publication. The marker points to the screen; it is
not a new product approval or a substitute for actual visual evidence.

## Host prerequisites

Use the pinned SDK runtime, authenticated ChatGPT account, selected service GitHub
identity, owned storage, git, gh and working process-group supervision. Existing
dirty workspaces and unknown processes are preserved. The OS lock prevents duplicate
CLI launches using the same host lock path; it is not credential isolation or a
distributed lock.

The host can supply trusted installed `module:factory` providers through
`--lifecycle-provider` and `--storage-provider`. These allocate the exact owned
workspace and run registered argument-array checks through existing host resource
controls. They are local host configuration, not downloaded Issue commands or state.
Set `--knowledge-repo OWNER/PRIVATE_REPOSITORY` in the host configuration when
knowledge refresh is required. The runtime reads the configured remote revision at
work start and replanning without overwriting local knowledge or publishing contents.

Register a new project's contract and pass its repository to `serve`; do not fork
the execution loop. Qualification includes actual delivery and stopped-host recovery,
not just configuration installation.
