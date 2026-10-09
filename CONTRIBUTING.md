# Developing Hydra

Use an Issue for work that needs a durable outcome, dependencies, or asynchronous coordination. Define the scope and completion evidence in a reviewed specification before implementation. The initial [runtime design](docs/engineering/sdlc-v1/spec.md) remains a draft.

Work in an isolated branch or worktree. Group changes into a meaningful PR that can be understood, verified, and reverted independently. Run appropriate behavior checks and `git diff --check` before publishing. The [repository workflow specification](docs/engineering/repository-workflow/spec.md) defines the foundation controls.

The `Repository hygiene` job validates workflow syntax, whitespace, and secrets. It checks the PR merge candidate and then the merged main commit using pinned tooling. It does not establish runtime correctness, product acceptance, or a completed security review. Add behavior tests alongside the runtime they verify.

Request code and security review when a PR is ready. Wait for the results, resolve findings, and verify the resulting revision. Normal implementation work proceeds within accepted scope. Policy paths require the configured code-owner approval once the repository controls are installed.

Before delivery, re-read current head/base, checks, review findings, and required decisions. Merge with the expected head through the normal squash path, then verify main CI and any required behavior. Do not bypass checks or leave a pending auto-merge request that can carry over to unreviewed changes.

No workflow in the foundation deploys, releases, or publishes packages. Public releases and operational effects require their own reviewed scope and authority.
