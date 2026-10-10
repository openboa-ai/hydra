# Native Codex workflow

Status: accepted user design; implementation acceptance requires independent review
of this specification and the resulting revision. Extends the GitHub workflow at
`bdd54f58801b4ce27c9f53d7d676a9afe3e3a7fd`. Work record: Issue #3.

## Outcome and delegated boundary

R1. Native Codex tasks own model execution, independent review and interactive
questions. Hydra supplies deterministic GitHub, workspace, verification and delivery
operations through a local stdio MCP plugin. Reuse the existing workflow and gates;
do not start an SDK worker inside an MCP call. Existing CLI behavior remains supported.
The operator explicitly approved this implementation and routine task creation and
continuation within the registered projects and delegated goals. New direction,
policy, credentials, spending and production effects retain their existing boundaries.

R2. Provide five tools: hydra_status (read-only), hydra_begin (select/prepare one
Issue), hydra_checkpoint (candidate result, decision wait, stopped checkpoint),
hydra_verify (registered verification), hydra_deliver (publication, PR/review,
exact-head merge and observation). All mutations require the registered Issue,
attempt ID and current expected policy/head; completion of a native assignment
also requires its unique step ID. No generic shell/API operation or pass override.
Host configuration, repository allowlist, lifecycle/storage factories and lock path
are installation settings, never candidate input. Use the optional official MCP
Python SDK; the existing standard-library CLI remains usable without this extra.

## Native continuation and common delivery

R3. Separate Runner's model dispatch from candidate processing. Native dispatch
returns an assignment containing the exact spec, phase, owned workspace and bounded
private context. Assignment identity and originating phase are recorded in the
existing authenticated progress comment before returning. Bind it to the attempt,
initial head, accepted policy/spec and delegated intake. Codex performs the assignment
and submits candidate_ready, failed or needs_decision. This is model judgment only;
the common runner still checks actual scope, spec edits, registered verification,
unchanged review head, authenticated PR review/CI and native GitHub protection.

R4. Keep workflow truth in GitHub. Add only typed public-safe native assignment
fields to the existing progress schema; never publish prompts, app task IDs, host
paths, private verification output or raw result summaries. Summaries/context and
verification output stay process-local. A server restart can rediscover an outstanding
assignment, but does not prove its prior worker stopped or approve its result.
An unresolved assignment is not redispatched automatically. Explicit stopped
checkpoint invalidates its step ID and preserves owned edits; redo independent
review/verification after loss of process-local evidence. Late and repeated results
cannot consume another assignment. Candidate completion is reconciled before retry.

R5. Use the same OS lock as the CLI for each native mutation. Retain the existing
bounded boot/nonce ownership ticket in that lock between native calls, with the
nonce bound to the GitHub assignment step ID and a fixed scope digest of its
repository, Issue, attempt, initial head and policy. Only an exact matching continuation
can enter while that ticket exists. CLI and other native assignments cannot enter,
even in another repository or after the owning Issue is paused/closed. Clear it
only after the current assignment has finished or explicitly confirmed stopped;
an unknown result preserves it. Do not clear a native ticket automatically on reboot:
the public checkpoint must first be reconciled. One active developer initially.
Before retiring a write assignment, commit owned edits and confirm a restartable
origin-phase checkpoint. An unconfirmed dispatch can release only its matching
admission ticket after explicit stop; it cannot create or adopt a work record.
Read-only status is
available while another process owns the lock. Existing CLI refuses native-owned
work; native calls refuse unresolved SDK execution. Never infer shutdown from time.
This is trusted-host coordination, not credential isolation or distributed locking.

R6. A needs_decision result checkpoints write edits and records the originating
phase before Codex asks the user. An authorized exact-attempt Issue resolution
continues that phase with a new attempt/step; a chat answer is not CODEOWNER approval.
Paused, cancelled, changed intake/policy/head and foreign-host work reject old
results. No tool self-certifies that an unknown external native process is stopped;
the operator must inspect the native task and stop it before confirming checkpoint.

## Plugin and operating loop

R7. Package one common SDLC skill and the MCP connection with a portable plugin
manifest and local marketplace. The skill uses native create/read/wait/message task
tools only within explicit human delegation. It coordinates outcome-sized tasks,
independent reviews, native questions and GitHub evidence. It proposes evidence-backed
improvements within existing goals; new direction is presented as a decision. No
arbitrary desktop RPC, extra service, hooks, SQLite or replacement operating database.

R8. Connect the existing host resource lifecycle and optional completion extension.
Preserve unrelated work, use storage-wrapped checks and retain unknown/busy resources.
Register Ouroboros and Coffee Chat with their existing CI/ownership rules and a
bounded initial documentation/verification-foundation scope. Product planning is
pending. Resolve actual external merge effects before enabling automatic delivery.
Activate one 30-minute native heartbeat only after real delivery and restart evidence;
quiet on unchanged state. Native availability and existing credits may be used;
never purchase credits, auto-recharge or switch to API billing.

## Requirement-linked acceptance

- R1-R3: real stdio initialize/list/call; native assignments never spawn SDK workers;
  existing CLI tests and exact-head delivery tests retain their behavior.
- R3-R6: real git candidate edits, independent spec/change review, failure correction,
  decision/origin-phase continuation, stale/repeated result refusal, dirty/uncommitted
  checkpoints, restart without automatic takeover and head/policy/intake changes.
- R4-R5: duplicate native calls/CLI launches cannot allocate another active writer;
  native A blocks CLI B and native B, including paused/closed A, until stopped;
  authenticated GitHub records reconstruct state without a local workflow DB.
- R7-R8: install/read the plugin, access a native task and deliver a real question/
  answer/resumption; verify two differently configured projects through common code.
- R8: actual PR, final-head code/security review and CI, exact merge, main checks,
  stopped/restarted continuation and subsequent scheduled progress are distinct receipts.

Source/tests/package readiness does not establish installed app visibility, remote
notifications, automatic delivery, production deployment or unattended operation.
