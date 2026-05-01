# Hydra Codex Plugin

This plugin provides Hydra's default Codex worker capabilities.

It is the source of truth for Hydra-managed issue execution skills. Nest repositories may include this plugin in their runtime bundles to expose Hydra capabilities to Codex without copying them into target code repositories.

## Skills

- `hydra:commit`
- `hydra:debug`
- `hydra:hydra-workpad`
- `hydra:land`
- `hydra:linear`
- `hydra:pull`
- `hydra:push`

## Marketplace

Hydra exposes this plugin through the repo marketplace at `.agents/plugins/marketplace.json`.
For local Codex testing without Hydra runtime materialization, register the marketplace from the repo root:

```bash
codex plugin marketplace add ./
```

For Git-backed registration, include both the marketplace and plugin paths when using sparse checkout:

```bash
codex plugin marketplace add https://github.com/openboa-ai/hydra.git --ref main --sparse .agents/plugins --sparse plugins/hydra
```

The marketplace category is `Productivity`. Official public Plugin Directory publishing is not self-serve yet, so this repo marketplace is the supported distribution path today.

## Runtime Boundary

Hydra supplies host-side orchestration and dynamic tools. This plugin describes how Codex should use those capabilities inside a worker session; it does not contain secrets.
