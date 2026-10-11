# Goal-driven native continuation

Status: accepted user plan; implementation acceptance requires independent review
of this specification and the resulting revision. Extends the native workflow at
`0e6bdb9287ca893fa1dd5809ea5c18bff28927b4`. Work record: Issue #3.

## Outcome and boundary

R1. A native operating task continues a delegated goal without requiring repeated
generic `continue` prompts. After recovery and delivery work, Codex selects the next
requirement-linked outcome, prepares allowed research or specification work, or asks
one concrete question when a human decision is the actual blocker. Completion of an
Issue is not completion of its parent goal.

R2. Keep the existing architecture: native Codex tasks perform judgment and questions;
Hydra exposes the same five deterministic MCP tools; product GitHub stores publishable
work and delivery evidence. Add no database, state branch, daemon, webhook, management
UI, generic GitHub tool, global hook, or additional model worker. One trusted host and
one active developer remain the initial operating limit.

R3. The shared SDLC skill distinguishes execution eligibility from useful preparation.
`not_delegated` means Hydra must not allocate an attempt, workspace, branch, or delivery
action for that Issue. It does not mean that Codex must ignore an already delegated
goal when bounded research, specification preparation, or a concrete recommendation
can proceed without code authority. In this state Codex may inspect repositories and
GitHub read-only, update the existing Issue with public-safe findings, and use an
already designated private planning area for private drafts. It must not edit a product
checkout or create implementation artifacts until the Issue is formally delegated.
Codex reuses an existing Issue where suitable, avoids duplicate tasks and artifacts,
and never adds a ready label merely to create work.

R4. The operating loop reconciles current GitHub facts and native assignments, finishes
recovery or delivery first, then advances one meaningful next result. It records or
reports the current goal, result, next action, and real waiting condition. If the next
action is immediately available, the same native turn continues. A heartbeat is a
re-entry mechanism after a turn ends, not the primary way to advance every step.
Product-specific transient instructions stay out of the common skill and long-lived
heartbeat prompt.

## Questions and resumption

R5. During a registered native assignment, `needs_decision` checkpoints the exact
attempt before Codex uses the native question interface. The checkpoint alone is not
a delivered question. After a real answer, only a publishable decision and the exact
authorized resolution marker are recorded; the original phase then resumes through a
fresh attempt. The authorized actor records a public-safe decision comment before the
marker. The resumed assignment receives the bounded authorized Issue comments as
untrusted decision context; the exact-attempt marker authorizes resumption but does not
make the comment text trusted instructions. Raw private answer text stays in the native
task. If no safe operational summary can be recorded, the marker is not published and
the Issue remains waiting. Before an execution attempt exists, planning questions use
the native question interface without manufacturing Hydra progress. A pending question
is never duplicated or inferred as approved from elapsed time. Repeated identical
authorized markers are idempotent: the first successful begin rotates the attempt, so
old markers cannot resume the new attempt. Unauthorized, stale, or malformed markers
are ignored. Chat answers never substitute for protected GitHub review.

R6. Read-only status identifies an already resolved wait without mutating workflow
state. Reuse one marker predicate for `product_decision` and `replan_required`. When
the current attempt has an exact marker from an authorized actor, the Issue remains
eligible under current labels and intake, and no stronger wait applies, status adds
an optional `resume_hint` of `decision_resolved` or `replan_ready`. Otherwise the field
is omitted. Status does not create an attempt, consume a marker, release ownership,
write GitHub, or certify that an external process stopped. `hydra_begin` still repeats
all current policy, intake, head, workspace, ownership and recovery checks before
changing state.

The hint precedence is fixed:

| Observed state | `resume_hint` |
| --- | --- |
| Current `product_decision` or `replan_required`, exact authorized marker, and `_latest` has no blocker | Corresponding hint |
| Paused or decision-labelled Issue, not delegated, dependency open, closed Issue, or changed policy/intake | Omitted |
| Missing progress/attempt, active native step, unconfirmed prior worker, or completion reconciliation | Omitted |
| Replan marker with a preserved uncertain external action | `replan_ready`; this requests reconciliation and does not authorize repeating the effect |
| Stale, unauthorized, malformed, or duplicate old-attempt marker | Omitted; duplicate current-attempt markers remain one idempotent hint |

## Delivery and installation

R7. Package the revised skill and code as version `0.2.1`. Keep the CLI and five MCP
tool names and inputs compatible. Install only the protected merged commit into a new
immutable runtime path; update the local plugin from that source and retain the prior
runtime for rollback. Update the existing same-chat 30-minute heartbeat rather than
creating another scheduler. Its durable prompt names the common skill and current goal
entry points, not a growing transcript of completed work.

R8. Do not claim autonomous operation from source, tests, installation, or one read-only
wake. Observe a scheduled run advance an actual allowed planning or delivery outcome.
Observe a real question, answer, exact-attempt resolution and original-phase continuation
when a genuine decision arises; do not fabricate a question to pass acceptance. Host or
app restart, authentication expiry, cross-host handover and long unattended operation
remain unproven until separately exercised.

## Requirement-linked acceptance

- R1-R4: with completed prior Issues and an open planning Issue that is not executable,
  the skill advances read-only or designated-private preparation without modifying a
  product checkout or creating a ready label, attempt, worktree or duplicate Issue.
  With an eligible registered Issue it continues through the existing implementation
  and delivery loop.
- R5: an actual registered decision produces a checkpoint before the native question;
  a public-safe decision comment and authorized exact-attempt marker resume the origin
  phase once and supply bounded untrusted context. Duplicate current markers are
  idempotent; stale, unauthorized and policy-blocked answers remain waits. Planning
  questions create no fake progress record.
- R6: status reports the two resume hints only for exact current authorized markers,
  remains write-free under repeated calls, and omits the hint for paused/decision-labelled,
  changed-intake, closed, stale, unauthorized or malformed cases. Begin continues to
  enforce all existing checks.
- R7: the full deterministic suite and real stdio tool listing/call pass; package and
  plugin versions agree; the merged commit is installed without overwriting the prior
  runtime.
- R8: GitHub records the distinction between source validation, merged delivery,
  installed runtime, scheduled advancement and question/resumption evidence.

No change in this specification authorizes product implementation, credentials,
spending, production deployment, policy weakening or publication of private context.
