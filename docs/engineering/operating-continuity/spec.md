# Operating continuity and truthful runtime observation

Revision: 1. Status: user-authorized improvement scope; independent specification
review is required before dependent implementation. Work record: Issue #3.

Extends the native/proactive workflow at
`b59616b3e6210661aa62b30496efc6bed97c6826` and the current mac-control candidate,
revision 5. This is a bounded first implementation of operating improvements.

## Outcome and boundaries

R1. An operator can distinguish useful work, an unanswered decision, a progressing
external check, and execution whose outcome is unknown. Repeated wakes must not
represent unchanged decision waits as progress. The installed package and supported
controls must be identifiable independently of the development checkout.

Retain five native MCP tools, GitHub workflow truth, one host writer, exact assignment
identity, protected delivery, existing lifecycle/storage providers and unknown-state
preservation. Do not add a workflow database, session journal, daemon, native desktop
RPC, automatic rollback, new credentials or a scheduler. This revision neither
certifies native start/interrupt nor implements automatic session creation/retirement.

## Derived progress and wake behavior

R2. Add a derived `progress_hint` to public runner/native results and status rows:

```json
{"kind":"human|external|unknown|actionable|complete",
 "next_action":"bounded_code",
 "wake_source":"operator_decision|issue_update|ci_update|native_checkpoint|control_change|none"}
```

This object is computed from current verified facts, never persisted to GitHub.
Existing result/action/reason and durable next_action meanings remain compatible.
Decision context references are provenance, not commands. Unknown/malformed reasons
default to unknown; the hint is neither authority nor permission to repeat an effect.

Unresolved decisions and not-delegated work require a decision/intake update. Useful
already-delegated preparation may still continue; a human hint does not imply all
research is blocked. Exact authorized resolution hints can request a fresh begin.
Only authenticated completed work is complete; a closed Issue alone is insufficient.
Paused/stopped admission remains blocked until an actual control change.

R3. The shared skill selects the next meaningful result and its real wake condition.
Continue available work in the same turn. Once independent preparation is exhausted
and only a user answer remains, do not repeatedly scan unrelated repository/CI state
or repeat the same progress announcement. Show the existing question and owning task,
preserve its answer/re-entry route and avoid creating another question or task.

A goal-specific heartbeat with no remaining delegated action or external execution
to monitor is paused while it solely waits for the user. A shared heartbeat skips
such goals while other responsibilities remain. Retire an unnecessary schedule when
its responsibility ends. Actual answers resume the owning native task, which checks
current authority/ownership before work and re-evaluates whether recurring operation
is needed. Do not invent event subscriptions or automatic cross-task wake support.
Only change a schedule whose exact scope and ownership are known and delegated.

## Native assignment and post-merge checks

R4. New unresolved native assignments use `native_assignment_pending` instead of
claiming execution active before dispatch is observed. Read the legacy
`native_task_active` reason compatibly. Pending means awaiting a checkpoint with
execution unconfirmed, not proof that a task never started. Preserve the same ticket,
step, scope, stopped reconciliation and duplicate/stale refusal. Status remains
read-only. No start receipt or safe automatic redispatch is invented.

R5. Distinguish required post-merge checks at the exact merge SHA and trusted producer:
pending, terminal failure, unavailable/unqualified evidence and success. Preserve
latest-run, event, workflow, app, ref and required-job binding, including reruns.
Only actual pending checks use the existing polling reason. Terminal failure returns
`post_merge_failed` with a diagnose action; unknown evidence returns
`post_merge_evidence_unknown`. Do not treat terminal failure as generic replan,
automatically rerun/rollback, create another Issue or repeat merge/close. Preserve
uncertain close/completion intents and reconcile them when valid success appears.

## Runtime identity and control response

R6. One helper captures a bounded, read-only runtime identity. Expose it through a
CLI identity command, native `hydra_status.runtime` and control responses. Retain the
ordinary CLI status list shape. Capture the package-source digest at process/server
startup and keep it for the lifetime of a long-lived server; do not rehash changed
disk files and claim the running process loaded them.

```text
identity_schema = 1
package = openboa-hydra-sdlc
version = string | null
code_digest = lowercase SHA-256 | null
code_digest_scope = package_sources_at_startup
config_digest = lowercase SHA-256 | null
control_binding_digest = lowercase SHA-256 | null
identity_reason = bounded_code | null
```

Hash only the actual package's bounded Python source files and relative names.
Validate regular files and paths; failures produce unavailable identity rather than
raw diagnostics. A version comes from package-corresponding metadata or a declared
single source, never an unrelated installed distribution. Align the existing package
version declaration. A version string alone does not identify the candidate bytes.

Configuration identity covers only explicitly selected validated semantic fields;
never return configuration text, credentials, host paths, environment or prompts.
Control binding identity covers the actual normalized settings/lock identities used
by OperatingControl. A context without configuration can report null configuration
identity explicitly. Digests are observation aids, not executable ownership,
signature/attestation, installed qualification or credential isolation.

R7. Control response schema becomes v2. Python, Rust, TypeScript and fixtures change
together. Reject incompatible v1 as unsupported runtime rather than successful empty
state. Preserve strict parsing, freshness, target validation and fail-closed Quit.
Unknown native control and schedule coverage stay unknown. Do not add a configuration
switch that declares them qualified.

Do not combine remote work cached under one runtime/config/binding with another.
Identity changes clear incompatible remote observations. An older in-flight response
cannot restore the previous identity. Null identities never prove two snapshots are
from the same runtime. Keep blocking controls available as far as the existing safe
protocol allows; do not manufacture enabling or termination evidence.

## User-facing controls and exact records

R8. Describe buttons as admission controls. Start/Resume permit eligible new work;
Pause/Stop block admission. Their success does not assert native task start/termination.
Global Resume preserves project overrides and reports the resulting allowed/blocked
project counts. Show requested/effective mode, execution observation and runtime
identity separately. Retain existing styling and public bundled assets.

Each work item owns its exact Issue/PR links. Opening a work record uses the allowlisted
repository, Issue number and record kind, never a caller-supplied URL. Re-observe that
exact work identity before opening; a missing/replaced record fails unavailable rather
than falling back to another Issue or PR. The configured project chat link is distinct.

## Acceptance

- A1: repeated identical status gives identical derived hints and no writes. Unknown
  reason, closed-only work, not-delegated preparation and exact decision resumption
  preserve authority and truth. All public result paths use the same classifier.
- A2: old and new native pending records retain ownership across restart. Returned
  assignment without a checkpoint is never proven stopped/running by its reason.
- A3: exact terminal push-check failure requests diagnosis without polling/model/
  merge/close effects. Pending rerun overrides old failure; missing/wrong identity
  is unknown. Closed close-intent reconciliation still converges on valid success.
- A4: CLI/MCP/control identity agrees for the same package/configuration. Metadata
  absence/mismatch, unsafe source entries, changed disk files after startup and
  unknown identities do not become trusted current identity. No raw sensitive paths
  or values are emitted.
- A5: strict v2 parsers reject malformed/incompatible data. Changed identity clears
  stale remote data and late old replies cannot restore it. Admission labels/counts
  respect project overrides; two Issues open only their own records.
- A6: an actual decision-only schedule transition preserves its owning question/task
  and does not claim the current turn was interrupted. Source skill edits alone do
  not establish installed wake behavior. Human decisions are never fabricated.
- A7: scoped Python, Rust and frontend tests; independent code/security review; a
  real running-screen checkpoint before publishing visual changes; final-head CI
  and protected delivery. Installation and scheduled operational advancement remain
  separate evidence. Preserve existing candidate work and private validation records.
