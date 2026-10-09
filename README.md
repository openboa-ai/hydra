# Hydra

Hydra is an SDLC software project for developing multiple projects with Codex. Its intended outcome is to keep authorized work moving from an agreed goal through implementation, verification, review, delivery, and follow-up, while involving people when their judgment is needed.

## Status

Hydra has a reviewed control-plane design and an initial bounded execution kernel: a private SQLite work/run record, transactional ownership, a Codex adapter, and CLI status/pause/cancel/resume. The kernel qualifies read-only local Codex execution. Goal planning, development-capable workers, GitHub publishing/review continuation, automatic merge and a background service are not implemented yet. This is not an installed autonomous SDLC or a production release.

## Intended workflow

1. Agree on a project's goal, delegated scope, and completion evidence.
2. Select a ready, independently verifiable unit of work.
3. Design, implement, and verify it in an isolated workspace.
4. Complete code and security review, address findings, and verify the resulting revision.
5. Deliver through the project's required checks and observe the result.
6. Continue eligible work or present the specific decision that needs a person.

Deterministic software should handle routine state checks and execution bookkeeping. Codex should handle work that requires reasoning. The first operator surfaces are Codex, GitHub, and a CLI; a separate management web application is not part of the initial scope.

## Design

Read [the SDLC architecture](docs/engineering/sdlc-v1/spec.md), [bounded execution contract](docs/engineering/durable-execution/spec.md), and [collaboration rules](AGENTS.md). The implementation uses Python, SQLite and the official local Codex SDK. Predictable coordination runs in code; model calls serve a bounded assignment.

Each managed project owns its product requirements and quality criteria. Hydra must not lower those criteria to report a successful delivery. Public source and examples must remain separate from private project configuration and operating data.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the PR, verification, review, and delivery workflow. Repository hygiene checks are separate from runtime tests and product acceptance.

Run deterministic checks without an SDK, account or model call:

```sh
python3 -m unittest discover -s tests -v
```

For local qualification, use Python 3.11+ and install into an isolated environment:

```sh
python3 -m pip install '.[codex]'
hydra doctor --cwd /absolute/path/to/owned/worktree
hydra --state /private/path/hydra.sqlite3 status
```

`work add assignment.json` registers an explicit bounded assignment referencing accepted goal
and spec revisions. `run --once` executes at most one eligible assignment. A provider-completed
turn becomes a verification/decision wait, never delivered Work. The S1 profile is read-only;
do not use it as a production development scheduler. See the contract for fields and limits.
Interrupted/unknown runs remain reserved until their actual state is reconciled. There is no
force-complete, force-recover, publication or installation command.

Authenticated runtime qualification currently covers a native macOS host. Deterministic process
fixtures also pass on GitHub-hosted Ubuntu. Containers whose PID 1 does not reap orphaned children
are unsupported: unresolved process-group cleanup retains recovery wait instead of permitting
another run. A general container runtime or cross-host recovery is not qualified by this slice.
