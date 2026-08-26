# Capability map

OpenBoa chooses a method from capabilities that are actually available in the current environment. The map prevents a design from assuming that every Codex surface, GitHub permission, runner, or scheduler exists.

| Need | Preferred capability | Durable evidence | Safe fallback | Human boundary |
| --- | --- | --- | --- | --- |
| Understand local work | nearest `AGENTS.md`, repository files, local commands | commit, diff, test output | read-only inspection and a named unknown | changing shared doctrine or local policy |
| Keep an outcome durable | GitHub Issue | Issue state, decisions, links, acceptance evidence | checked-in plan when GitHub is unavailable | changing purpose or priority |
| Execute code changes | isolated Codex task plus local `git` worktree | branch, commit, focused and full tests | clean clone or a documented handoff | new credentials, scope, or material effect |
| Split independent work | Codex subagents or separate tasks | bounded outputs and integration evidence | sequential execution | overlapping authority or unclear product choice |
| Review a candidate | deterministic CI plus exact-head Codex review | check run, review commit, unresolved-thread state | local test and recorded `unknown` for missing review | merge when repository policy requires it |
| Revisit work in this task | read-only Codex scheduled task or task wakeup | schedule definition, observation, notification, and handoff | explicit interactive follow-up | any checkout or external write triggered by time |
| Run without an open task | GitHub Actions or a verified managed execution surface | workflow run, exact revision, logs, final status | native Codex scheduled task or manual run | adding a scheduler, containment adapter, or write authority |
| Observe delivered behavior | deployment, logs, metrics, support evidence | environment, window, revision, result | a scheduled read-only check | rollback, public notice, or material production action |
| Enforce repository policy | GitHub Actions and rulesets | workflow source, permissions, producer, rule readback | shadow evaluation | ruleset or required-check change |
| Recover | live-state reconciliation, idempotency, rollback path | observed before/after state | stop with exact unblock condition | irreversible compensation or weakened control |

## Capability discovery

Before choosing a mechanism:

1. inspect the tools exposed in the current Codex task;
2. inspect repository instructions, local binaries, authentication state, and the target platform read-only;
3. distinguish `available`, `unavailable`, and `unknown`;
4. choose the least-powerful capability that can produce the required evidence; and
5. bind the capability to the outcome, repository, action, resource bounds, and stop condition.

Do not infer authority from capability. A connector may authenticate an account with administrative access while the delegated action remains read-only. Do not infer capability from documentation either: verify the surface in the current environment.

## Wakeups and invalidation

An automation needs both a reason to wake and a reason to stop. Common wakeups are a new commit, check completion, review activity, deployment, incident, dependency alert, schedule, task resume, or compacted context. On every wakeup, reconcile live state before acting.

Evidence is invalidated by the state it describes changing. Commit-scoped CI and review are invalid after a new head. Deployment observation is invalid after a new artifact. A permission or workflow-source change invalidates a trust claim. A changed outcome invalidates an old plan. The automation should do no work when the wakeup does not change the relevant state.

## Adapter rule

Adapters describe how current products expose these capabilities. They are replaceable. If a product changes, update its adapter and tests; do not rewrite the doctrine to match a button, command, or vendor name.
