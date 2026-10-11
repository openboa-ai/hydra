---
name: sdlc
description: Operate a delegated project goal through native Codex tasks and Hydra's GitHub-backed verification, review, delivery and recovery tools.
---

# Hydra SDLC

Use this workflow for an explicitly delegated registered project goal. Humans
decide purpose, important product choices, policy/authority changes, spending and
production effects. Continue routine work inside the delegated boundary.

## Observe and choose

Call hydra_status and inspect current GitHub goals, Issues, specifications and
delivery evidence. Finish recovery and pending delivery before starting new work.
Choose a requirement-linked outcome with actual acceptance evidence. Discover
bugs and useful improvements from CI, reviews, feedback and observed behavior.
Within a delegated goal, propose or create a bounded Issue and continue. A new
direction requires evidence, options, recommended experiment and the exact decision.
Do not invent features for projects whose product planning is pending.

Issue completion is not goal completion. After a delivered outcome, reconcile the
goal and choose its next bounded result in the same turn when possible. If an open
Issue is `not_delegated`, do not allocate an attempt, workspace, branch or ready label.
Continue only preparation already allowed by the goal: read repositories and GitHub,
record public-safe findings on the existing Issue, or use an already designated private
planning area. Do not edit a product checkout before formal delegation. Avoid duplicate
Issues, documents and workers. A heartbeat re-enters an ended turn; it is not the normal
way to advance every immediately available step.

Use native create_thread/read_thread/wait_threads/send_message_to_thread for
outcome tasks only when the user explicitly delegated creation and messaging.
Connect the Issue and goal in each task; use the owned workspace returned by Hydra.
Do not duplicate an existing active task. Initial operation has one developer.
Use independent reviewers for spec/diff judgments when delegated; they inspect
actual artifacts. They are additional judgment, not separate security principals.

## Perform the returned assignment

Call hydra_begin for the chosen Issue. For action=native_task, retain attempt_id,
step_id, head and contract_revision. Follow its bounded prompt and mode. Write
only within the owned worktree and accepted scope. Let Hydra checkpoint commits;
do not commit, push, create a PR or merge through a competing path. Review phases
inspect actual spec/diff and verification output without changing the checkout.

Submit hydra_checkpoint with candidate_ready, failed or needs_decision. Candidate
readiness is a model judgment. Hydra and current GitHub facts decide delivery.
The response may contain the next assignment. Do not replay a consumed step.
Continue with hydra_verify/hydra_deliver against the current recorded head and
policy. Wait for actual code/security review and CI; fix coherent findings as a
meaningful PR update. UI changes require a real screen shared before final PR.
Keep private research, paths, prompts, app IDs and transcripts out of public records.

## Ask, stop and resume

Before a user question, submit needs_decision and retain the returned checkpoint.
Use the native question tool in the outcome task. State decision, why it matters,
options and recommendation. Record only a publishable actual user decision in
the Issue, including the exact-attempt resolution marker expected by Hydra.
Do not manufacture a human decision or substitute chat answers for GitHub approval.
The operating task may continue another eligible project while an answer is pending.
The checkpoint itself is not a delivered question. For attempt `<id>`, record a
non-empty public-safe comment beginning `hydra: decision <id> context`, then record
`hydra: decision <id> resolved` in a later comment. A generic earlier comment does
not count; raw private answer text stays in the native task.
If no safe operational summary can be published, do not publish the marker. Before
an attempt exists, ask a planning question without manufacturing Hydra progress.
Repeated current-attempt markers are idempotent; stale markers cannot resume a new
attempt. A `resume_hint` from status means call begin to reconcile current facts, not
that an external effect is safe to repeat.

An interrupted assignment retains its host admission ticket. Inspect/stop the
previous native task and its owned processes before submitting stopped with its
original identity. Never infer shutdown from a heartbeat, closed Issue or timeout.
Preserve edits; a new assignment has a new identity and rejects late results.
Reconcile remote effects before retrying. Unknown GitHub results remain waits.

## Observe and continue

Report goal, selected work/reason, stage, latest verification, PR/merge state,
next action and required decision. Verify actual merge and post-merge checks before
calling an Issue complete. Record unmeasured time/cost as unknown.

Before ending a turn, state the next action and its real wait condition. If the next
action is available now, continue it instead of asking for a generic proceed message.
Do not repeat completed research or create proposals merely to appear active.

After real task and recovery qualification, use one native 30-minute heartbeat in
the operating chat. Quiet while unchanged; notify completion, meaningful failure or
needed decision. Native scheduling consumes usage and requires the host/app.
Use included usage or existing credits when Codex permits; never buy credits,
auto-recharge or switch to API billing. Goal creation requires explicit user request.
