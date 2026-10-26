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

## Choose native planning and continuity

Inspect existing requirements and decisions before asking the user. Use supported
native Plan mode when product choices or dependencies need planning; do not require
it for every change or assume Hydra can switch modes. Repository specifications
remain acceptance criteria; an execution checklist is not a second specification.
Respect the active mode's tool and mutation constraints.

Use native Goal only when the user explicitly requests a Goal. Define its outcome,
evidence, constraints, delegated boundary and stopping condition. Set a budget only
when explicitly supplied. Reuse the current Goal and preserve accounting on
reconnection; reading status is not replacing an objective. A Goal's native idle
continuation does not establish delivery, always-on availability or new authority.

## Perform the returned assignment

Call hydra_begin for the chosen Issue. For action=native_task, retain attempt_id,
step_id, head and contract_revision. Follow its bounded prompt and mode. Write
only within the owned worktree and accepted scope. Let Hydra checkpoint commits;
do not commit, push, create a PR or merge through a competing path. Review phases
inspect actual spec/diff and verification output without changing the checkout.

For an ordinary assignment, submit hydra_checkpoint with candidate_ready, failed
or needs_decision. The response may contain the next assignment. Do not replay a
consumed step. Continue with hydra_verify/hydra_deliver against the current recorded
head and policy.

A read_only change_review returned by workflow_step.verify_only with the private
native_handoff_v1 profile has a different bounded completion route. Retain the
original command target and candidate plus the full returned assignment. Complete
through hydra_command_v1: action=workflow_step, operation=verify_only,
stage=review_checkpoint, the exact expected assignment, and
effect_key=checkpoint:<attempt_id>:<step_id>, with the review outcome and private
summary. Use the current qualified runtime and admission expectations. Do not
substitute hydra_checkpoint or broad continuation. Missing capability, invocation
proof or authority means preserve the assignment and wait; do not invent a grant.
Explicit stopped cleanup still uses the original ticket identity after confirming
the owned work has stopped. It is not review acceptance or permission to deliver.

Candidate readiness is a model judgment. Hydra and current GitHub facts decide
delivery. Wait for actual code/security review and CI; fix coherent findings as a
meaningful PR update. UI changes require a real screen shared before final PR.
Keep private research, paths, prompts, app IDs and transcripts out of public records.

## Ask, stop and resume

Ask about missing requirements, facts only the user knows, preferences, product
choices and meaningful conflicts. Inspect existing decisions first. Use the
supported native question tool in the owning task, with useful choices and their
tradeoffs when appropriate, and allow free text. Use an open question when options
would constrain the answer. Respect the active mode and remote surface. MCP
elicitation supplies missing tool input; it is not a duplicate product questionnaire.

Interpret a selected option together with its explanation. Preserve corrections,
uncertainty and partial answers. Apply a partial answer only to independent decisions
with sufficient information. Explain its effect on the specification or acceptance
checks without routine reapproval. Continue unrelated authorized work while waiting.
Preparatory and nonblocking questions do not create an attempt or checkpoint.

When an assignment must wait, first submit needs_decision through its exact
completion route and retain the confirmed checkpoint. A checkpoint is not a delivered
question. Silence, an automatic default, prompt resolution or interruption does not
establish a human answer. Answer interpretation, command authority, decision
publication and resumed execution remain distinct. A reply never lifts Pause.

For an actually exposed and qualified codex_delegated_v1 profile, Codex owns the
conversation and proposes a public-safe interpretation inside the existing scope.
Use hydra_command_v1 with action=workflow_step and operation=decision_submit, the
exact waiting source_attempt, round=1, current origin/head/contract/spec/intake basis,
current runtime/admission expectations and effect_key=decision:<source_attempt>:1.
Retain the complete command target and the returned exact public references. Do not
claim that Hydra independently authenticated the human or invent source evidence.
Approval text never grants scope, credentials, spending, protected approval or Resume.

Check current admission before every mutating command, including decision_submit.
While the project is paused or the host is stopped, keep new interpretations and
proposals in the owning Codex conversation. Do not attempt public context or receipt
publication, continuation or assignment. Questions and read-only reconciliation may
continue; an exact confirmed result may be reported without another write. An answer
never removes this barrier. New publication requires running admission, fresh accepted
work pins and its own current grant after an independently authorized explicit Resume.

The proposal's public_text is deliberately public data. Summarize the allowed
operational meaning and uncertainty; keep raw answers, private IDs, transcripts,
credentials and private research in their original native boundary. If a safe
summary is unavailable, preserve the unresolved decision in the owning conversation
rather than publish it. Unsupported capability or missing authority remains held.

A confirmed decision receipt means the exact public context/receipt pair was read
back. It does not start work. After a separately authorized explicit project Resume,
use typed workflow_step.continue with fresh progress/runtime/admission expectations.
Returning a native assignment additionally requires its own native_handoff_v1 grant.
Do not use legacy begin/advance to consume an unconsumed delegated pair.

After lost publication output, reconcile original references first. A fresh authorized
submission can finish only the identical original intent within its persisted budget.
Do not change the proposal or request identity to evade uncertainty or exhaustion.
Mutable resume uncertainty permits read-back only until the exact original result is
confirmed. Recorded-choice amendments and delegated technical successors in this
increment remain held for the appropriate accepted follow-up.

For a legacy operator-comment path only, preserve its existing qualified protocol:
a public-safe comment beginning hydra: decision <attempt> context and the later
hydra: decision <attempt> resolved marker refer to that exact attempt. Do not handcraft
these markers as a substitute for delegated decision_submit or a protected approval.
A status hint selects the next reconciliation; it does not authorize repeating effects.

An interrupted assignment retains its host admission ticket. Inspect/stop the
previous native task and its owned processes before submitting stopped with its
original identity. Never infer shutdown from a heartbeat, closed Issue or timeout.
Preserve edits; a new assignment has a new identity and rejects late results.
Reconcile remote effects before retrying. Unknown GitHub results remain waits.

## Operate through remote Codex and MCP

The required remote human surface is Codex. Read current status and use only an
actually exposed and qualified Hydra command for the requested effect. The app is
an auxiliary view/control surface. Never substitute broad legacy begin/checkpoint/
verify/deliver for a narrow pause, interrupt, checkpoint-only or verification-only
request. MCP reachability or caller-supplied task/approval fields do not establish
authority. Unsupported control remains unsupported until its source and guard exist.

Distinguish admission pause/stop, native turn interruption, Goal state and schedule
state. Read back the original effect after a lost response before retrying. A busy
worker, failed MCP connection, unavailable Codex remote connection and unreachable
host have different limits; do not report an unobserved stop as applied. Local app
success is not evidence of remote operation. Preserve GitHub's protected approvals.

## Observe and continue

Report goal, selected work/reason, stage, latest verification, PR/merge state,
next action and required decision. Verify actual merge and post-merge checks before
calling an Issue complete. Record unmeasured time/cost as unknown.

Before ending a turn, state the next action and its real wait condition. If the next
action is available now, continue it instead of asking for a generic proceed message.
Do not repeat completed research or create proposals merely to appear active.

Distinguish an unanswered decision, a progressing external check and unknown
execution from available work. Derived progress hints explain the next required
observation; they do not grant authority, prove execution ended or provide an event
subscription. A human or not-delegated hint does not prevent preparation already
allowed by the goal.

Once that independent preparation is exhausted and only the user's answer remains,
show the existing question and its owning task with the answer/re-entry route. Do
not create another question or task, repeatedly scan unrelated repositories or CI,
or announce the same wait as progress. A real answer received in the owning native
task re-enters the existing decision protocol and checks current authority and
ownership before work. Do not promise automatic cross-task wake or resumption.

Continue immediately available work in the current turn. For an explicitly active
native Goal, use its supported idle continuation within its existing budget and
mode constraints. Do not add a timer to mimic that continuation. For a future time
or external event wait, use only a delegated, qualified native schedule with the
required target, wait condition and end condition; do not impose a fixed 30-minute
heartbeat on every task. Quiet while unchanged; notify completion, meaningful
failure or needed decision. Native scheduling consumes usage and requires the host/app.
Pause a goal-specific heartbeat when it solely waits for the user and has no
remaining delegated action or external execution to monitor. A shared heartbeat
skips that goal while other responsibilities remain. Retire an unnecessary schedule
when its responsibility ends; do not retain it to repeat completed work.

Change only an existing schedule whose exact identity, scope and ownership are
known and delegated. Inspect its current settings and preserve its prompt, target,
recurrence and notification preferences when only pausing it. Apply changes through
the native scheduling tool and read back the result; reconcile an uncertain response
before retrying. Changing a schedule neither interrupts the current turn nor
releases an assignment ticket. Admission Start/Resume does not resume a schedule.
After an actual answer or authorized re-entry, re-evaluate the need and authority
for recurring operation; do not override an explicit operator pause or stop.
Source skill changes alone do not establish installed or scheduled behavior.

Use included usage or existing credits when Codex permits; never buy credits,
auto-recharge or switch to API billing. Goal creation requires explicit user request.
