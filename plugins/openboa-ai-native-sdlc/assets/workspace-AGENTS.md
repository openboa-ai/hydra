# OpenBoa workspace

<!-- openboa-ai-native-sdlc:managed:start version=0.1.0 -->
## Development workflow

- Keep a durable goal and linked GitHub parent Issue for cross-repository, multi-PR, long-running, or delegated work. Create a Codex Goal when the user asks Codex to track it. Use sub-issues and issue dependencies for meaningful task boundaries and ordering.
- Name every repository, human owner, dependency, handoff, and verification surface before implementation.
- Read the nearest repository `AGENTS.md` and use the focused OpenBoa skill for the current stage.
- Preserve sibling checkouts and unrelated dirty work. Give parallel tasks separate worktrees and avoid overlapping write scopes.
- Use the Codex GitHub connector for supported GitHub operations. Authentication is not authority; confirm the workspace, repository, linked work, risk, and exact action.
- Verify outcomes with tests, evals, independent review, delivery evidence, and observation. Require human approval at sensitive or irreversible boundaries.
- Use `gh` or a direct API only for a missing connector capability, and record the bounded exception in the Issue or handoff.
<!-- openboa-ai-native-sdlc:managed:end -->

## Workspace-local instructions

- Keep workspace-wide policy and reusable operating guidance in the OpenBoa Hydra marketplace; keep repository-specific facts in each repository.
- Do not treat a sibling checkout as disposable or as an implicit source of truth.
