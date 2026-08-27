# Hydra contributor contract

- Read `DESIGN.md` before changing the package. The product is an Agent Plugin, not a marketplace or an evaluation runner.
- Keep the stable commitments intact: capable agents, bounded authority, human accountability, portability, and verifiable outcomes.
- Treat implementation choices as candidates. Do not add a skill, MCP server, hook, runner, or client-specific behavior without a task and evidence in Hydra Eval.
- Keep `plugin.json` and `.codex-plugin/plugin.json` aligned at `0.0.0` until a reviewed release decision changes them together.
- Keep this repository free of copied marketplace data, benchmark results, private traces, secrets, and unsupported claims.
- Use an isolated worktree, inspect the exact diff, run the repository checks, and use the GitHub connector for GitHub control-plane changes.
