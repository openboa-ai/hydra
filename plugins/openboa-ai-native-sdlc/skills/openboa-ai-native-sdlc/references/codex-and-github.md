# Codex and GitHub

OpenBoa uses Codex and GitHub as complementary parts of the development environment. Neither one is the organization or the source of purpose.

| Surface | Primary role |
| --- | --- |
| Hydra | Portable doctrine, operating guidance, playbooks, templates, and evaluations |
| Codex | Goal-directed execution, delegation, tool use, verification, recovery, and handoff |
| GitHub | Durable work state, collaboration, integration, repository controls, and delivery evidence |
| Local `git` | Worktrees, branches, diffs, commits, and other local data-plane operations |

The interfaces may change. The durable outcome, authority boundary, repository state, and acceptance evidence must survive a new Codex task, model, machine, or tool.

## GitHub control plane

Use the Codex GitHub connector as the default control plane for live GitHub operations when it exposes the needed capability. This includes reading or changing Issues, pull requests, reviews, checks, labels, rulesets, releases, and delivery state, and reading the canonical repository and remote-ref state used to authorize a branch update.

Before an operation, bind it to the workspace, canonical `owner/repository`, active outcome, and allowed action. Re-read the live target before a state-changing request. The connected account supplies authentication and attribution; account access alone is not authority.

Use local `git` as the data plane for fetches, worktrees, diffs, commits, rebases, tests, and push transport from the isolated worktree. A push is not an alternative GitHub control plane: before it, use connector-visible state to confirm the canonical repository, remote ref, active outcome, and allowed update; after it, read back the remote ref, pull request head, and checks through the connector. Local repository access and a successful push do not authorize a GitHub setting, release, merge, or deployment.

Use `gh` or the direct GitHub API only when the connector is unavailable or lacks a required operation. Record the missing capability, exact target and operation, result, and follow-up as a time-bounded exception. Do not switch transport merely to avoid a connector safeguard.

## A meaningful unit of work

A GitHub Issue is the default durable home for a delegated outcome that may outlive a Codex task. It should describe the result to create, how success will be observed, important constraints, dependencies, and current state. It is not a transcript and should not repeat the same accountable human on every update.

Use a parent Issue for the outcome. Create a sub-issue only when the child has an independently delegable result, dependency boundary, and acceptance evidence. A Codex task is an execution attempt; a pull request is an integration change. Neither should replace the outcome or force the work into artificial fragments.

Avoid tiny Issues, commits, or pull requests created only to mark process stages. Prefer one reviewable change that delivers a meaningful result while still fitting a clear rollback boundary.

## Working flow

1. Reconcile the Issue, default branch, existing pull requests, checks, and local worktree before acting.
2. Create or reuse an isolated branch for the approved outcome. Preserve unrelated local work.
3. Keep the plan as the best current hypothesis. Update it when environment evidence changes the path.
4. Commit coherent changes and push the work branch. Use a draft pull request while integration evidence is still being assembled when that improves collaboration.
5. Link the pull request to the outcome, show the important decisions and evidence, and respond to review and CI from the current head.
6. When repository policy declares merge human-gated, ask for the exact-head decision only after the change is ready and the required evidence is current.
7. After delivery, observe the actual result and feed recurring lessons back into the smallest durable layer.

When resuming, derive current state from GitHub and the repository instead of trusting the previous conversation. Before retrying a write whose result is uncertain, check whether the intended effect already happened. Use idempotent operations where GitHub supports them and never create a duplicate Issue, comment, release, or merge just because a response was lost.

## Audit and provenance

Use repository history, pull-request events, Actions, deployment records, and the GitHub Audit Log when available to reconstruct consequential external effects. The Audit Log is especially useful for changes to repository settings, rulesets, permissions, environments, credentials, releases, and other administrative controls.

An audit event proves that an attributed operation was recorded; it does not prove the action was authorized, safe, or successful. Bind useful audit evidence to the canonical organization and repository, action, actor or integration, target, timestamp, and resulting state. Read back the affected control or artifact as well. If the required audit surface is unavailable, record the evidence as `unknown` and do not replace it with an assumption.

## Repository rules

Use GitHub rulesets and branch protection for stable, machine-enforced boundaries. The normal public-repository baseline is:

- changes reach the default branch through a pull request;
- required checks pass on the current pull request head;
- blocking review conversations are resolved;
- force pushes and deletion of the protected branch are blocked; and
- the repository's chosen merge method preserves a clear, reviewable history.

Keep the required check named `openboa-governance` during this migration. A future rename or replacement is a separate rollout: run both checks through canaries, update every ruleset that relies on the old name, and remove the old check only after live verification.

In Hydra v0.1, the current `openboa-governance` pull-request job is candidate conformance and bootstrap evidence. It is not yet a trusted policy workflow whose producer is bound by a verified ruleset. The live ruleset currently accepts that context from any source, so the merge decision must manually verify the check producer as well as the result. Preserve the check name in this migration. Binding its expected source, or adding a base-controlled trusted policy workflow, is a separate post-merge canary and an explicit human-gated ruleset change.

Do not add blanket required `CODEOWNERS` approval as a substitute for judgment. In a one-human organization it can create a self-review deadlock without improving the evidence. Use `CODEOWNERS` for review routing where useful; use checks and rulesets for routine enforcement, plus an exact-effect merge gate where repository policy declares one.

Do not create an artificial GitHub Environment solely to simulate approval. Environments are useful when they protect a real deployment or release target and can enforce the actual boundary. Where merge is declared human-gated, approve the exact pull request head only after its current diff and checks are ready for the decision.

## Trusted GitHub Actions

Treat candidate code and pull request metadata as untrusted input. A trusted workflow should:

- run from trusted workflow code rather than accepting control logic from the candidate change;
- grant the smallest practical `GITHUB_TOKEN` permissions;
- avoid secrets, OIDC credentials, and write access while inspecting candidate code;
- pin third-party actions or shared workflows to immutable revisions where practical;
- separate verification from deployment or publication; and
- show which current commit produced each result.

Do not call a check trusted until its workflow source, permissions, trigger, expected producer, and live ruleset binding have been verified. Do not use `pull_request_target` to execute candidate code with secrets or write credentials.

Do not weaken a workflow, required check, ruleset, test, or evaluator to make a change pass. Fix the change, provide stronger evidence, or request a bounded exception at the real policy boundary.

## Codex working context

Keep repository facts and commands in the nearest `AGENTS.md`. Keep recurring cross-repository methods in the skill and its playbooks. Codex should load only the references required for the active work and use repository state as the source for resumption.

Delegation to multiple agents is useful when work can be separated by artifacts or verification surfaces. It is not a default. Name ownership of each subtask, prevent overlapping edits, and integrate evidence at the outcome level. More agents do not compensate for a vague goal, a shared false assumption, or a missing deterministic check.
