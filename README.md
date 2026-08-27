# Hydra

Hydra is an Agent Plugin for an AI-native organization: capable agents receive meaningful responsibility inside clear authority boundaries, while people retain purpose and final accountability.

## Why

Most development processes either keep an agent as a narrow tool or give it authority without a reliable operating boundary. Hydra is a small, portable package for the middle path: agents can decide and act within delegated scope, and the organization can verify what happened.

## What

Hydra defines a product boundary, not a fixed company process.

- The portable interface is the official Agent Plugins package format.
- A runtime starts from a trigger, receives managed input and context, and produces observable output.
- A development loop compares a baseline agent with a Hydra candidate on realistic work.
- A client decides how to load and run the package. Codex is the first client we will test; the package is not Codex-only.

The stable commitment is the relationship between capable agents, delegated authority, human accountability, and verifiable outcomes. Prompts, models, staffing, tools, and internal workflow may change when evidence shows a better way.

## How the runtime is understood

```text
Trigger (request, situation, alert)
  -> managed input (goal, constraints, files, live context)
  -> external agent + Hydra
  -> output (text, files, actions, outcome evidence)
  -> observation and follow-up
```

Hydra does not replace the host agent, run a hidden dispatcher, or require a particular internal workflow. It gives the host a portable place to add those capabilities later, only when an evaluated need exists.

## How Hydra is developed

```text
realistic task
  -> baseline run without Hydra
  -> candidate run with Hydra
  -> verifier and review
  -> compare outcome, time, tokens, cost, and safety
  -> keep, reject, or change the next candidate
```

Hydra Eval owns the tasks, runs, verifiers, and reviewed evidence for this loop. The separate [OpenBoa Plugins marketplace](https://github.com/openboa-ai/plugin-marketplace) will own discovery and installation metadata only; it will not copy this package.

## Current status

`0.0.0` is a foundation release. It contains the two manifests and the product documents, but no skills, MCP server, hooks, runner, or custom runtime. It is not an installable or supported release, and no evaluation score is claimed.

## Repository map

```text
plugin.json                  # portable Agent Plugins manifest
.codex-plugin/plugin.json    # Codex compatibility manifest
DESIGN.md                    # product essence and runtime/development boundary
EVALUATION.md                # link to the independent evaluation boundary
RELEASING.md                 # future release and rollback flow
SUPPORT.md                   # client support status
AGENTS.md                    # contributor contract for this repository
```

See the [Agent Plugins specification](https://agent-plugins.org/specification), [Codex plugin packaging guide](https://developers.openai.com/plugins/build/plugins), and [Hydra Eval](https://github.com/openboa-ai/hydra-eval) for the standards and evaluation work that inform future implementation.
