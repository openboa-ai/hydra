# Hydra

Hydra turns project work into isolated, autonomous implementation runs, allowing teams to manage
work instead of supervising coding agents.

Hydra is a modified fork of OpenAI Symphony under the `openboa-ai/hydra` repository.
Original project: <https://github.com/openai/symphony>

Hydra extends the upstream scheduler with a global CLI, local profile management, Docker Sandboxes
worker support, Nest-managed Codex artifacts, Linear polling, GitHub-ready project workflows, and
operator-visible runtime status.

Public CLI, local state, OTP application config, and docs use the Hydra name. Some internal
Elixir module names still retain `SymphonyElixir` while the fork stabilizes.

Hydra manages three local surfaces:
- `~/.hydra/projects/<project>/WORKFLOW.md` for project runtime policy
- `~/.hydra/workspaces/<project>/<issue>/` for isolated agent workspaces
- `~/.hydra/runtime/<project>/` for Nest-synced Codex home artifacts

> [!WARNING]
> Hydra is a low-key engineering preview for testing in trusted environments.

## Running Hydra

### Requirements

Hydra works best in codebases that have adopted
[harness engineering](https://openai.com/index/harness-engineering/). Hydra is the next step --
moving from managing coding agents to managing work that needs to get done.

### Run Global Profiles

Hydra is managed like `codex` or `claude`: the command is global, while user configuration lives
in a local home directory. By default that home is `~/.hydra`.

```text
~/.hydra/
  config.toml
  projects/<project>/WORKFLOW.md
  workspaces/<project>/<issue>/
  logs/<project>/
```

Project profiles do not live in target repositories, and they are no longer managed from this
development repository. Each `WORKFLOW.md` in `~/.hydra/projects/` is the single source of truth
for metadata, Linear selection, dashboard settings, workspace roots, hooks, and Codex runtime
policy.

Set up the local home:

```bash
hydra setup --wizard
```

The CLI follows the same broad shape as tools like OpenClaw: `setup` prepares local state,
`configure` revisits settings, and `doctor` checks or repairs the local installation.

Configure credentials through the CLI:

```bash
hydra auth login
hydra auth login --provider github --method browser
hydra auth login --provider linear --method token
hydra auth status
```

In a terminal, `hydra auth login` opens an arrow-key menu. Move with up/down and confirm with
Enter or Space. Use `--provider` and `--method` for scripts or copyable setup commands.

Both Linear and GitHub auth are mandatory for runtime profiles. `hydra check <project>` and
`hydra run <project>` fail before starting if either provider is missing.

On macOS, Hydra stores credentials in Keychain when available. In non-Keychain environments it
falls back to local files under `~/.hydra/auth/` with restrictive permissions. GitHub sync ignores
credentials and runtime state.

GitHub browser login is Hydra-specific. `hydra auth login --provider github --method browser`
delegates to `gh auth login --web` only to complete the browser flow, then stores the resulting
token in Hydra's auth backend. Hydra never falls back to your default local `gh` login or
shell `GH_TOKEN`. If you prefer a raw token, use
`hydra auth login --provider github --method token`.

Linear is different: the ChatGPT/Codex Linear connector token is not exposed to local processes, and
Linear browser OAuth requires a registered OAuth app plus callback handling. Until Hydra ships that
OAuth app flow, configure Hydra-specific Linear runtime access through
`hydra auth login --provider linear --method token`.

Run Hydra like `codex` or `claude`:

```bash
hydra list
```

The `hydra` command is the CLI. During local CLI development, keep the command on `PATH` as a
symlink to this repository's `hydra` launcher; repo edits are picked up immediately through the
symlink, so there is no separate install subcommand to rerun.

Run a profile:

```bash
hydra run openboa
```

`hydra run` renders one live terminal status panel, updates that panel in place, and starts the
browser dashboard at the profile's configured port. Disable the browser dashboard only when needed
with `hydra run openboa --no-web-dashboard`.

List available profiles:

```bash
hydra list
```

Inspect, validate, or check runtime status without starting the scheduler:

```bash
hydra show openboa
hydra check openboa
hydra status
hydra status openboa
hydra stop openboa
hydra configure
hydra doctor
hydra doctor --fix
```

The launcher sets `HYDRA_WORKSPACE_ROOT` for the selected project:

```text
~/.hydra/workspaces/<project>/<issue>/
```

Logs are under `~/.hydra/logs/<project>/`. Project profiles should default to Docker Sandboxes
(`sbx`) worker mode with Codex shell network disabled. If a profile explicitly sets `networkAccess: true`, `hydra run` still
requires `--allow-network` before starting.

The dashboard shows active sessions, retry pressure, rate-limit data, and an execution trace for
recent scheduler, workspace, retry, and Codex events. Hydra also writes a lightweight recovery
checkpoint to the configured `workspace_root` as `.hydra-recovery.json`; if the runtime restarts,
retrying issues are restored with their remaining backoff and in-flight issues are put back on the
retry queue so Codex can resume from the existing issue workspace.

### Docker Sandboxes Worker Mode

Hydra profiles should default to Docker Sandboxes (`sbx`) for autonomous Codex execution. In this
mode Codex runs inside a Docker-managed sandbox. Hydra keeps Linear orchestration on the host
through the narrow `linear_graphql` dynamic tool, while Git commits, pushes, and PR creation run
inside the sandbox using Docker Sandboxes GitHub credentials.

Set up Docker Sandboxes once through Hydra:

```bash
hydra setup sandbox
```

For stepwise setup, use Hydra subcommands only:

```bash
hydra sandbox install
hydra sandbox login
hydra sandbox openai
hydra sandbox status
```

Profile snippet:

```yaml
worker:
  sbx:
    enabled: true
    agent: codex
    lifecycle: fresh
    network_policy: balanced
    startup_timeout_ms: 120000
    # Optional Docker Sandboxes create options:
    # template: hydra-codex
    # kits: [kit-a]
    # cpus: 4
    # memory: 8g
    # extra_workspaces:
    #   - path: /path/to/docs
    #     readonly: true
```

Docker Sandboxes mounts the workspace at the same absolute path that exists on the host. Hydra uses
Docker Sandboxes branch mode by default for issue runs, so Codex works in an issue-specific
`.sbx/...worktrees/<branch>` checkout where normal Git commands can commit, push, and create PRs.
Leave `codex.turn_sandbox_policy` omitted unless a profile needs a custom policy; Hydra will
generate a `workspaceWrite` policy rooted at the active sandbox worktree. `lifecycle` supports
`fresh`, `reuse`, and `repair`; managed profiles default to `fresh` so stale sandboxes are rebuilt
before autonomous execution. Use `hydra sandbox doctor <project>`, `hydra sandbox inspect <project> <issue>`,
and `hydra sandbox exec <project> <issue> -- <cmd>` instead of raw `sbx` commands during normal
operation.

`hydra setup sandbox` configures both OpenAI and GitHub Docker Sandboxes secrets. GitHub is required
for managed profiles because PR publication runs inside the sandbox through `git` and `gh`. Linear
does not have a first-class Docker Sandboxes secret proxy today, so Hydra keeps Linear auth on the
host and exposes only the explicit Linear dynamic tool.



### Hydra Codex Plugin

Hydra ships its default Codex worker capabilities as a repo-owned plugin at `plugins/hydra`.
That plugin is the source of truth for Hydra-specific skills such as `hydra:commit`,
`hydra:debug`, `hydra:hydra-workpad`, `hydra:linear`, `hydra:pull`, `hydra:push`, and
`hydra:land`.

Nest repositories may include this plugin in their runtime bundles. Target repositories should
keep only repo-specific instructions and skills; they should not copy Hydra runtime skills into
application code PRs.

### Optional GitHub Sync

Local profiles can optionally be backed by a GitHub repository. Secrets and runtime state are ignored;
only profile source under `projects/` is pushed.

```bash
hydra setup git@github.com:<owner>/<repo>.git
hydra sync status
hydra sync pull git@github.com:<owner>/<repo>.git
hydra sync push git@github.com:<owner>/<repo>.git
```

### Option 1. Make your own

Tell your favorite coding agent to build Hydra in a programming language of your choice:

> Implement Hydra according to the following spec:
> https://github.com/openboa-ai/hydra/blob/main/SPEC.md

### Option 2. Use our experimental reference implementation

Check out [elixir/README.md](elixir/README.md) for instructions on how to set up your environment
and run the Elixir-based Hydra implementation. You can also ask your favorite coding agent to
help with the setup:

> Set up Hydra for my repository based on
> https://github.com/openboa-ai/hydra/blob/main/elixir/README.md

---

## License

This project includes code from OpenAI Symphony and is licensed under the
[Apache License 2.0](LICENSE). See [NOTICE](NOTICE) for upstream attribution and Hydra
modification notes.
