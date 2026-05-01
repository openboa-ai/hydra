# Repository Instructions

This is the Hydra development repository. Make Hydra CLI, runtime, dashboard, workflow
orchestration, and documentation updates against this repository unless the user explicitly asks to
edit a cloned target repository.

This repository is not the canonical home for user project profiles. Hydra should behave like a
global CLI such as `codex` or `claude`: local user configuration lives under `~/.hydra` by
default. Treat `~/.hydra/projects/<project>/WORKFLOW.md` as the canonical profile source and
credentials managed through `hydra auth` as the local secret source. Runtime state belongs under
`~/.hydra/workspaces/` and `~/.hydra/logs/`.

Do not assume ChatGPT/Codex app connector credentials are available to the local `hydra` process.
Do not fall back to the user's default local `gh` login either. GitHub browser auth must use
an isolated temporary GitHub CLI config only for login, then store the resulting token through
Hydra's own auth backend; Linear still needs Hydra-managed runtime auth unless a first-class
Linear OAuth app flow is added.

Treat Linear and GitHub as mandatory runtime credentials. `hydra check <project>` and
`hydra run <project>` should fail when either provider is missing; do not make GitHub auth
conditional on `networkAccess`.

Use Docker Sandboxes (`worker.sbx`) for autonomous Codex runs. User-facing setup must go through
`hydra setup sandbox` or `hydra sandbox ...`; do not document raw `sbx` setup commands. Profiles
should require Docker Sandboxes plus an OpenAI sandbox secret and use the same absolute workspace
path visible on the host. Keep Linear host-controlled through Hydra dynamic tools. GitHub operations must use
`hydra sandbox github` plus in-sandbox `git` and `gh`; do not add host-side GitHub
publishing fallbacks.

GitHub sync, when used, should push and pull the local `~/.hydra` profile source. Do not move
canonical workflow profiles back into this development repository unless the user explicitly changes
that decision.

Nest is the preferred source for shared Hydra runtime artifacts such as `AGENTS.md`, Codex skills,
subagents, hooks, plugins, MCP templates, and project-owned `WORKFLOW.md` definitions. Treat Nest as
an artifact source, not an infrastructure/environment repo. `hydra nest sync <project>` should
materialize source artifacts into local `~/.hydra/projects/<project>` and
`~/.hydra/runtime/<project>`, while target code repositories stay code-only. Do not copy Nest
artifacts into target repo PRs. If artifact changes need review, publish a PR against the Nest
source via `hydra nest publish`, not against the target repo.

Use `hydra` as the CLI command in docs, examples, and verification. Do not add or document a
`hydra install-cli` subcommand; the `hydra` launcher is the CLI. For local development, the
PATH command should be a symlink to this repository's `hydra` file so edits are picked up from
the repo directly.

Prefer `hydra setup` as the user-facing command for preparing the global local home. Keep
`hydra init` as a low-level compatibility command, but do not make it the primary setup path in
docs or examples.

Mirror OpenClaw-style CLI boundaries where practical: `setup` prepares local state, `configure`
revisits settings, and `doctor` reports or repairs local installation problems. Keep full TUI work
separate from small prompt menus.

## Apache 2.0 Fork Compliance

Hydra is a modified fork of OpenAI Symphony. Treat Apache License 2.0 compliance as a repository
invariant, not as optional documentation cleanup.

Required rules for every agent working in this repository:

- Keep the root `LICENSE` file present and unchanged unless legal counsel explicitly instructs
  otherwise.
- Keep the root `NOTICE` file present. Do not remove the OpenAI attribution, copyright notice, or
  Apache 2.0 notice. Add Hydra/OpenBOA modification notes only as additive entries.
- Keep README attribution clear: Hydra is a modified fork of OpenAI Symphony, with the upstream
  project linked as `https://github.com/openai/symphony`.
- Preserve upstream copyright headers when editing copied or derived files. If a file receives
  meaningful Hydra-specific changes and already has copyright headers, add new contributor
  attribution without deleting existing attribution.
- Do not describe Hydra as a product from OpenAI, upstream distribution, or endorsed project. Use
  phrasing like "Hydra, based on OpenAI Symphony" or "modified fork" when upstream lineage matters.
- Do not use `OpenAI Symphony` as the product name. Public branding, CLI names, local state,
  dashboard titles, and docs should use `Hydra`; `Symphony` references should be limited to
  upstream attribution, internal legacy module names, or historical compatibility notes.
- When adding dependencies, check their licenses before landing the change. Do not add a dependency
  whose license conflicts with Apache 2.0 or intended commercial/SaaS use without documenting the
  risk and getting explicit user approval.
- When copying code from upstream Symphony or another third-party source, record the source and
  modification intent in the relevant docs or NOTICE when required by that source license.
- Before finalizing rename, branding, or distribution-related changes, run a focused search for
  stale public names and legal-surface regressions, including `LICENSE`, `NOTICE`, `README.md`,
  CLI help text, dashboard titles, workflow templates, and package metadata.
- Keep `.pre-commit-config.yaml` and `scripts/check-apache-compliance.sh` active. The pre-commit
  hook is the commit-time gate for this section, so do not bypass it with `--no-verify` unless the
  user explicitly approves that risk.
- Keep `scripts/check-gitleaks.sh` active in pre-commit. Gitleaks must run on staged changes before
  every commit, and commits should fail when `gitleaks` is missing or finds a secret.
- New clones should run `pre-commit install` before committing. If `pre-commit` is unavailable,
  run `scripts/check-apache-compliance.sh --worktree` and `scripts/check-gitleaks.sh --staged`
  manually before committing.

Useful compliance check:

```bash
scripts/check-apache-compliance.sh --worktree
scripts/check-gitleaks.sh --staged
```
