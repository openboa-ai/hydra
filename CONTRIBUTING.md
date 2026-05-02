# Contributing

Hydra uses local hooks for fast feedback and GitHub Actions for merge gates.

## Local Setup

Install required hooks before committing:

```bash
scripts/setup-git-hooks.sh
```

The hooks require `gitleaks`. On macOS:

```bash
brew install gitleaks
```

## Commit Messages

Use Conventional Commits:

```text
<type>[optional scope][!]: <description>
```

Allowed types are:

- `feat` for user-facing features
- `fix` for bug fixes
- `docs` for documentation-only changes
- `style` for formatting-only changes
- `refactor` for code changes that do not add features or fix bugs
- `perf` for performance improvements
- `test` for test-only changes
- `build` for packaging, dependencies, or build system changes
- `ci` for GitHub Actions and automation changes
- `chore` for maintenance tasks
- `revert` for revert commits

Examples:

```text
feat(cli): add setup wizard
ci: add secret scanning gates
build(homebrew): add formula
fix!: remove deprecated profile field
```

## Pull Requests

PR titles use the same Conventional Commits format as commits. The PR body must follow
`.github/pull_request_template.md`, remove placeholder comments, and include a checked test plan
for the relevant validation.

## Required Checks

Before publishing work, run the focused checks that match the change. For general repo changes:

```bash
scripts/check-apache-compliance.sh --worktree
scripts/check-gitleaks.sh --staged
scripts/check-gitleaks.sh --pre-push
```
