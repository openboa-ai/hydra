# Hydra

Hydra is an SDLC software project for developing multiple projects with Codex. Its intended outcome is to keep authorized work moving from an agreed goal through implementation, verification, review, delivery, and follow-up, while involving people when their judgment is needed.

## Status

This repository starts from a new foundation. It contains the project purpose, collaboration rules, repository development workflow, and a draft design. An autonomous runtime has not been implemented or installed. No release, working runtime integration, or operational reliability claim is made.

## Intended workflow

1. Agree on a project's goal, delegated scope, and completion evidence.
2. Select a ready, independently verifiable unit of work.
3. Design, implement, and verify it in an isolated workspace.
4. Complete code and security review, address findings, and verify the resulting revision.
5. Deliver through the project's required checks and observe the result.
6. Continue eligible work or present the specific decision that needs a person.

Deterministic software should handle routine state checks and execution bookkeeping. Codex should handle work that requires reasoning. The first operator surfaces are Codex, GitHub, and a CLI; a separate management web application is not part of the initial scope.

## Design

Read [the draft SDLC design](docs/engineering/sdlc-v1/spec.md) and [the collaboration rules](AGENTS.md). Runtime language, persistence, MCP integration, and scheduling are intentionally undecided until the design is reviewed.

Each managed project owns its product requirements and quality criteria. Hydra must not lower those criteria to report a successful delivery. Public source and examples must remain separate from private project configuration and operating data.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the PR, verification, review, and delivery workflow. Repository hygiene checks are separate from runtime tests and product acceptance.
