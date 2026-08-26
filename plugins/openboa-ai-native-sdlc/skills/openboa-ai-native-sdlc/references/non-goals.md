# Non-goals and v0.2 boundaries

OpenBoa AI-Native SDLC v0.2 establishes a portable way for humans and agents to work toward outcomes. The boundaries below keep the foundation focused and replaceable.

## What this is not

- It is not a claim that an agent is a legal person, employee, or moral subject. "Collaborator" describes an operational role with work responsibility, continuity, and evaluation.
- It is not a transfer of final organizational accountability to a model, agent, vendor, or connected account.
- It is not a process in which a human approves every stage, tool call, commit, or routine choice.
- It is not unlimited autonomy. Authority remains bounded by purpose, repository, capability, environment, action, and system controls.
- It is not one fixed autonomy level or a fixed human/agent role for every lifecycle stage. Leadership changes with clarity, reversibility, evidence, and consequence.
- It is not a new Issue tracker, custom specification language, workflow schema, or replacement vocabulary for established software-development terms.
- It is not a requirement to split work into small Issues or pull requests merely to show activity.
- It is not a default peer swarm. Multiple agents are used when the work graph or evaluation needs real separation.
- It is not a guarantee that several model reviews are independent or more trustworthy than deterministic evidence.
- It is not a benchmark optimized for code volume, tool calls, raw throughput, or the appearance of autonomy.
- It is not a replacement for repository-specific tests, `AGENTS.md` facts, product decisions, or running-environment evidence.
- It is not tied to one model, Codex task, machine, or vendor. Codex and GitHub are the first adapters, not the doctrine.
- It does not use Ouroboros, Coffee Chat, or another product repository as the source of the SDLC. Those products can become canaries and consumers after the foundation is validated.

## v0.2 product boundary

The plugin remains a portable guidance and automation package. It adds read-only lifecycle hooks, diagnostics, and templates that adapt native Codex scheduled tasks, GitHub, and CI capabilities. Those adapters do not turn Hydra into a central runtime or grant authority.

v0.2 does not add:

- an MCP server, custom dispatcher, always-on service, or central scheduler;
- a custom agent runtime, agent registry, or long-running orchestration service;
- a live database, graph database, event store, or operations dashboard;
- automatic access provisioning, credential management, deployment, release, or merge authority;
- organization-wide ruleset changes bundled into the documentation migration; or
- an assumption that every environment supports the plugin or the same controls.

Unsupported environments should be reported plainly. They must not be treated as successful adoption.

The package does not supply or register a generic local headless runner, launchd job, or cron entry. A portable process group does not contain a descendant that creates a new session, so v0.2 refuses to claim unattended write safety without an environment-specific containment boundary. It may wake Codex through supported hooks or scheduled tasks, but every supported run remains least-privilege, observable, and recoverable. It does not emulate a missing platform capability with an unsafe shell loop.

## Future work must earn its complexity

A runtime service, new GitHub integration, richer graph tooling, or automated delivery control should be added only when repeated real work shows that a skill, repository state, and existing platform controls cannot provide the needed outcome. The proposal should identify the missing capability, evidence of repetition, security boundary, operating cost, failure and recovery behavior, and a smaller alternative that was considered.

The method is expected to change. The enduring foundation is the relationship between purpose, delegated work, evidence, authority, and accountability.
