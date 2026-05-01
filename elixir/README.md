# Hydra Elixir

This directory contains the current Elixir/OTP implementation of Hydra, based on
[`SPEC.md`](../SPEC.md) at the repository root.

> [!WARNING]
> Hydra Elixir is prototype software intended for evaluation only and is presented as-is.
> We recommend implementing your own hardened version based on `SPEC.md`.

## Screenshot

![Hydra Elixir screenshot](../.github/media/elixir-screenshot.png)

## How it works

1. Polls Linear for candidate work
2. Creates a workspace per issue
3. Launches Codex in [App Server mode](https://developers.openai.com/codex/app-server/) inside the
   workspace
4. Sends a workflow prompt to Codex
5. Keeps Codex working on the issue until the work is done

During app-server sessions, Hydra serves the host-side `linear_graphql` tool for Linear updates. GitHub work should happen inside Docker Sandboxes branch worktrees with `git` and `gh`, using the Docker Sandboxes `github` secret configured by `hydra setup sandbox`.

If a claimed issue moves to a terminal state (`Done`, `Closed`, `Cancelled`, or `Duplicate`),
Hydra stops the active agent for that issue and cleans up matching workspaces.

## How to use it

1. Make sure your codebase is set up to work well with agents: see
   [Harness engineering](https://openai.com/index/harness-engineering/).
2. Configure runtime access with `hydra auth login --provider linear --method token` and
   `hydra auth login --provider github --method browser` when using the global launcher.
   If you run `elixir/bin/hydra` directly, export `LINEAR_API_KEY` and `GH_TOKEN` yourself.
3. Copy this directory's `WORKFLOW.md` to your repo.
4. Optionally copy the `commit`, `push`, `pull`, `land`, and `linear` skills to your repo.
   - The `linear` skill expects Hydra's `linear_graphql` app-server tool for raw Linear GraphQL
     operations such as comment editing or upload flows.
5. Customize the copied `WORKFLOW.md` file for your project.
   - To get your project's slug, right-click the project and copy its URL. The slug is part of the
     URL.
   - When creating a workflow based on this repo, note that it depends on non-standard Linear
     issue statuses: "Rework", "Human Review", and "Merging". You can customize them in
     Team Settings → Workflow in Linear.
6. Follow the instructions below to install the required runtime dependencies and start the service.

## Prerequisites

We recommend using [mise](https://mise.jdx.dev/) to manage Elixir/Erlang versions.

```bash
mise install
mise exec -- elixir --version
```

## Run

```bash
git clone https://github.com/openboa-ai/hydra
cd hydra/elixir
mise trust
mise install
mise exec -- mix setup
mise exec -- mix build
```

Run project profiles through the global `hydra` CLI:

```bash
hydra run openboa
hydra run autokairos
```

The launcher reads credentials managed by `hydra auth`, including Hydra-specific GitHub
browser login, selects
`~/.hydra/projects/<project>/WORKFLOW.md`, stores workspaces under
`~/.hydra/workspaces/<project>/`, and stores logs under `~/.hydra/logs/<project>/`.

Repository-local launchers are not the default for OpenBOA AI profiles. Keep project profiles in
`~/.hydra/projects/` unless you are deliberately testing a separate packaging flow.

## Configuration

Project profiles should be started through the global `hydra` command. Keep custom workflow
profiles under `~/.hydra/projects/<project>/WORKFLOW.md`, then run:

```bash
hydra run <project>
```

The lower-level Elixir escript is an implementation detail behind the global launcher.

Optional flags:

- `--logs-root` tells Hydra to write logs under a different directory (default: `./log`)
- `--port` overrides the Phoenix observability service port
- `--no-terminal-dashboard` disables the terminal status renderer while keeping the web dashboard enabled
- `--terminal-dashboard` enables the terminal status renderer explicitly

The `WORKFLOW.md` file uses YAML front matter for configuration, plus a Markdown body used as the
Codex session prompt. If a `settings.yml` file exists next to `WORKFLOW.md`, Hydra reads it at
startup and merges supported project-local values over the generated front matter. The project
settings file is intended for per-repo identity and runtime knobs when several dashboards run at the
same time:

```yaml
scope: project
project:
  name: OpenBOA
ui:
  project_name: OpenBOA
  title: OpenBOA
  description: Hydra runtime for OpenBOA
  color: "#16A34A"
linear:
  project_slug: openboa-bf82bb513f7b
runtime:
  dashboard_port: 4101
  dashboard_host: 127.0.0.1
  workspace_root: $HYDRA_WORKSPACE_ROOT
agent:
  max_concurrent_agents: 3
  max_turns: 20
```

Minimal example:

```md
---
tracker:
  kind: linear
  project_slug: "..."
workspace:
  root: ~/code/workspaces
hooks:
  after_create: |
    git clone git@github.com:your-org/your-repo.git .
agent:
  max_concurrent_agents: 10
  max_turns: 20
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
codex:
  command: codex app-server
---

You are working on a Linear issue {{ issue.identifier }}.

Title: {{ issue.title }} Body: {{ issue.description }}
```

Notes:

- If a value is missing, defaults are used.
- Safer Codex defaults are used when policy fields are omitted:
  - `codex.approval_policy` defaults to `{"reject":{"sandbox_approval":true,"rules":true,"mcp_elicitations":true}}`
  - `codex.thread_sandbox` defaults to `workspace-write`
  - `codex.turn_sandbox_policy` defaults to a `workspaceWrite` policy rooted at the current issue workspace
- Supported `codex.approval_policy` values depend on the targeted Codex app-server version. In the current local Codex schema, string values include `untrusted`, `on-failure`, `on-request`, and `never`, and object-form `reject` is also supported.
- Supported `codex.thread_sandbox` values: `read-only`, `workspace-write`, `danger-full-access`.
- When `codex.turn_sandbox_policy` is set explicitly, Hydra passes the map through to Codex
  unchanged. Compatibility then depends on the targeted Codex app-server version rather than local
  Hydra validation.
- The global `hydra` launcher keeps `workspace.root` portable by exporting
  `$HYDRA_WORKSPACE_ROOT` at runtime, so workflow files do not need machine-specific absolute
  paths.
- Env-backed entries inside `codex.turn_sandbox_policy.writableRoots` are resolved before the policy
  is sent to Codex. For Docker Sandboxes (`worker.sbx`), leave the policy omitted unless you need a
  custom override; sbx exposes the workspace at the same absolute path as the host.
- `agent.max_turns` caps how many back-to-back Codex turns Hydra will run in a single agent
  invocation when a turn completes normally but the issue is still in an active state. Default: `20`.
- If the Markdown body is blank, Hydra uses a default prompt template that includes the issue
  identifier, title, and body.
- Use `hooks.after_create` to bootstrap a fresh workspace. For a Git-backed repo, you can run
  `git clone ... .` there, along with any other setup commands you need.
- If a hook needs `mise exec` inside a freshly cloned workspace, trust the repo config and fetch
  the project dependencies in `hooks.after_create` before invoking `mise` later from other hooks.
- `tracker.api_key` reads from `LINEAR_API_KEY` when unset or when value is `$LINEAR_API_KEY`.
- For path values, `~` is expanded to the home directory.
- For env-backed path values, use `$VAR`. `workspace.root` resolves `$VAR` before path handling,
  while `codex.command` stays a shell command string and any `$VAR` expansion there happens in the
  launched shell.

```yaml
tracker:
  api_key: $LINEAR_API_KEY
workspace:
  root: $HYDRA_WORKSPACE_ROOT
hooks:
  after_create: |
    git clone --depth 1 "$SOURCE_REPO_URL" .
codex:
  command: "$CODEX_BIN --config 'model=\"gpt-5.5\"' app-server"
```

- If `WORKFLOW.md` is missing or has invalid YAML at startup, Hydra does not boot.
- If a later reload fails, Hydra keeps running with the last known good workflow and logs the
  reload error until the file is fixed.
- `server.port` sets the Phoenix LiveView dashboard and JSON API port. The global `hydra run`
  launcher starts that browser dashboard by default; pass `--no-web-dashboard` only when you do not
  need `/`, `/api/v1/state`, `/api/v1/<issue_identifier>`, or `/api/v1/refresh`.
- The dashboard includes an execution trace showing recent scheduler, workspace, retry, and Codex
  events. The same trace appears in the JSON payloads under `recent_events`.
- Hydra writes `.hydra-recovery.json` under `workspace.root`. On restart, existing retry
  entries are restored with their remaining backoff and in-flight issues are requeued immediately
  so the next Codex run can continue in the same workspace.

Project-specific OpenBOA AI workflow profiles live in `~/.hydra/projects/` so `elixir/` can stay
focused on runtime code.

## Web dashboard

The observability UI now runs on a minimal Phoenix stack:

- LiveView for the dashboard at `/`
- JSON API for operational debugging under `/api/v1/*`
- Bandit as the HTTP server
- Phoenix dependency static assets for the LiveView client bootstrap

## Project Layout

- `lib/`: application code and Mix tasks
- `test/`: ExUnit coverage for runtime behavior
- `WORKFLOW.md`: in-repo workflow contract used by local runs
- `../.codex/`: repository-local Codex skills and setup helpers

## Testing

```bash
make all
```

Run the real external end-to-end test only when you want Hydra to create disposable Linear
resources and launch a real `codex app-server` session:

```bash
cd elixir
export LINEAR_API_KEY=...
make e2e
```

Optional environment variables:

- `HYDRA_LIVE_LINEAR_TEAM_KEY` defaults to `SYME2E`
- `HYDRA_LIVE_SSH_WORKER_HOSTS` uses those SSH hosts when set, as a comma-separated list

`make e2e` runs two live scenarios:
- one with a local worker
- one with SSH workers

The SSH scenario requires `HYDRA_LIVE_SSH_WORKER_HOSTS`. If it is unset, that scenario
fails fast.

The live test creates a temporary Linear project and issue, writes a temporary `WORKFLOW.md`, runs
a real agent turn, verifies the workspace side effect, requires Codex to comment on and close the
Linear issue, then marks the project completed so the run remains visible in Linear.

## FAQ

### Why Elixir?

Elixir is built on Erlang/BEAM/OTP, which is great for supervising long-running processes. It has an
active ecosystem of tools and libraries. It also supports hot code reloading without stopping
actively running subagents, which is very useful during development.

### What's the easiest way to set this up for my own codebase?

Launch `codex` in your repo, give it the URL to the Hydra repo, and ask it to set things up for
you.

## License

This project is licensed under the [Apache License 2.0](../LICENSE).
