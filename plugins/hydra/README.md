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

## Runtime Boundary

Hydra supplies host-side orchestration and dynamic tools. This plugin describes how Codex should use those capabilities inside a worker session; it does not contain secrets.
