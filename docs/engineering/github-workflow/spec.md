# GitHub-native Hydra workflow

Status: implementation contract replacing the SQLite coordination architecture.
Work record: https://github.com/openboa-ai/hydra/issues/3

## Outcome and authority

Implement the user-approved five-component SDLC: Hydra software, private knowledge,
product repositories, Codex and one execution host. Product Issues, versioned specs,
branches, PRs and CI are the work record. No operational repository, SQLite, state
branch, replacement JSON journal or web console. Preserve old state files; do not
adopt old runs or external work automatically. This contract supersedes S1's store
and S2's private registration assumptions, but reuses the supervised Codex adapter.

The operator delegates a goal once. Routine design, implementation, verification and
review corrections proceed. Policy/evaluation/authority changes and production/public
release retain existing human/native boundaries. Product planning is not invented.
The first runtime is one trusted active host, one model turn at a time. OS locking
only protects that host. Explicit stopped-host handover, not automatic failover.

## Product contract and work intake

Use Python 3.11+ standard library, the existing optional pinned Codex SDK, git and
existing authenticated gh as the runtime transport. Interactive work uses the GitHub
connector. Every runtime GitHub action selects openboa per process; never use the
human account or persist/expose its token. Worker execution receives no publishing
token from Hydra. This is role separation, not hostile-worker credential isolation.

`.hydra.toml` is read at the repository's protected default-branch SHA, never from a
candidate worktree. Version 1 names repository numeric identity, authorized actors,
ready/paused/decision labels, spec directory, allowed paths, protected paths,
verification commands (argument arrays, relative cwd, timeout), required check
workflow/path/job bindings, review provider identity and production merge effects.
Automatic merge defaults off until the repository contract explicitly permits it,
strict integration protection and trustworthy checks are observed, and merging has
no unapproved production effect. Policy file and protected-path changes require
native human review. No unknown or empty verification policy enables delivery.
Pin contract revision per work. If its contents change, wait for policy reconciliation.

A ready Issue contains public goal/scope/acceptance and a fenced `hydra` TOML block:
`spec = "docs/engineering/.../spec.md"`, optional `spec_revision = "<40-char SHA>"`,
`dependencies = ["https://github.com/owner/repo/issues/N"]`, `priority = 0`.
Only registered repositories and authorized operator/writer intake are eligible;
arbitrary Issue text cannot supply shell commands, authority or passing evidence.
Paused/decision labels and closed Issues never dispatch. Missing product intent or
incomplete dependencies are explicit waits. Reuse an existing accepted spec when
its exact revision is given. Otherwise design a scoped spec in the permitted docs
location and independently review the actual spec before dependent implementation.
An independent review is another Codex turn, not a native human approval.

Bind valid initial intake by SHA-256 of exact Issue title/body serialized as sorted,
compact UTF-8 JSON. Store this public digest before first dispatch and recheck it
before PR recovery/delivery, during execution and immediately before/after service
intent publication. Labels/comments are separately observed and do not change this
digest. Changed or unbound intake holds the existing attempt and pending effect;
do not silently replace its digest, adopt a new goal or close it with old evidence.
Restore the delegated intake to continue, or close/pause the old task and delegate a
new Issue for a changed scope. Failure replanning does not authorize goal expansion.

Use the branch `hydra/issue-N`. Existing remote branch/PR and current dirty workspace
must be reconciled before changes. Another actor's branch/PR is a conflict, not adopted.
A public-safe marker binds PR to repository numeric ID and Issue number. Multiple
matching PRs or closed unmerged PRs require a scoped decision.

## GitHub progress and interfaces

One Hydra-authored progress comment per Issue has a versioned marker and compact
public fields: attempt UUID, host alias, contract/spec revisions, phase, branch/head,
PR number, pending service action, checkpoint, wait reason and next action. It is a
human-readable progress record with parseable metadata, not a new database. Locate
it by actual API author identity; foreign lookalike comments are ignored. Duplicate
own comments are a conflict. Never include local paths, SDK identities, raw provider
transcripts, private knowledge, credentials or exploit details. Do not post raw model
output. Update only on meaningful change. Issue/label/comment claims are not evidence.

Internal interfaces are plain records and injectable in tests:
- GitHub client: repository/file/issue/comments/branch/PR/check/review observations;
  progress publication, owned PR creation/update, review request, exact-head merge,
  post-delivery issue closure. Bounded calls, pagination, structured failures.
- Project parser: validate pinned TOML and Issue intake; no executable Issue commands.
- Workspace: prepare/inspect owned issue workspace, verify argument-array commands,
  validate scope, commit/checkpoint and expected-ref branch publication.
- Runner: reconcile actual facts -> next eligible action -> record -> execute -> record.

CLI: `hydra run --issue URL`, `hydra serve --repos OWNER/REPO ...`,
`hydra status --repos OWNER/REPO ...`. Local options select workspace root, host alias,
lock path, workspace/storage lifecycle provider, and bounded run/watch timeout. They
are host settings, not workflow state. No --state, completion override or forced
recovery. `run` drives one Issue until completion, actionable wait or its timeout;
`serve` rotates eligible repositories, releasing model capacity during external waits.
Status is read-only. SIGINT/SIGTERM requests bounded stop and records a checkpoint.
The login service executes this same CLI and is enabled only after real qualification.

## Execution, delivery and recovery

Before model start, record attempt and action in GitHub; failure to record prevents
dispatch. State during execution is memory-only. Reuse existing process-group
supervision, bounded startup/shutdown and explicit uncertain outcome. Confirm no
residual owned worker before starting after restart. A previously running attempt
on another host waits for explicit confirmed-stop handover in an authorized Issue
comment. An old heartbeat never proves shutdown. No time-based takeover.

Workspace-write mode is explicit with deny-all approval. Restrict writes to the
owned workspace/resources; keep read-only reviewer mode. Product checks run through
registered resource/lifecycle provider. The reviewer examines actual spec/diff/output.
A provider-completed result proposes candidate readiness, never delivery completion.
Missing resources/auth/usage observation or any usage window below 20% prevents a
new model turn. Preserve failed/unknown outcomes as waits rather than automatic restart.

Pin evidence to current head/spec/contract. UI tasks need a public-safe actual screen
checkpoint shared with the operator before final PR publication; otherwise wait.
Batch coherent review corrections. Observe automatic coupled code/security review
triggers before requesting missing reviews. Require authenticated provider completion
for exact head, relevant native reviews, resolved threads and required genuine CI.
Unknown review formats, stale heads or forged name/text/result files cannot pass.

Service-owned branch publish/PR creation/merge records intention first. Publish only
the owned branch with expected remote head and no force. After lost response, query
exact branch/PR/merge state before any retry. Unknown results hold that Issue. Use at
most two bounded transient retries after read-back; repeated failure becomes diagnosis.
Checks include workflow/event/target commit/job/source identity, not just green names.
Exact-head squash merge uses native strict integration protection; no policy bypass.
Verify actual merged PR/merge commit and post-merge checks before closing Issue. PR
body references its Issue without auto-closing it before observation is complete.

Before handover/stop, checkpoint commits and publishes permitted work when possible.
If GitHub is unavailable, stop safely with unpublished changes preserved locally.
Unpushed changes are not recoverable after host loss. Reopening reads GitHub/workspace
facts and uses a fresh Codex turn, not a restored private transcript. Unknown old
SDK attempts and old DB files stay preserved and outside the new dispatch path.

Model-free polling: active waits 60 seconds, idle 300 seconds, rate-limit backoff.
Prioritize recovery/delivery, then dependency unblockers, priority and oldest ready
work. A decision or review wait in one repository does not block another. No change
means no model wake or repeated notification. Knowledge revision is checked at work
start/replanning without overwriting dirty local knowledge or publishing its contents.

## Acceptance

Tests use fake GitHub/SDK and real temporary Git repositories/processes where useful:
- GitHub-only restart reconstructs work, existing branch/PR; no duplicate publication.
- Lost responses, stale head/base, forged checks/provider comments and policy changes
  never authorize delivery; actual matching read-back recovers submitted effects.
- One-host duplicate launch is refused; unresolved/residual/foreign-host run is held.
- Pause, stop, timeout and unknown execution preserve checkpoint and uncertainty.
- Accepted design precedes implementation; verification/review failure becomes correction.
- Exact-head delivery and post-merge observation precede Issue completion.
- Decision/external wait leaves another repository's work eligible.
- Two different project configurations and a new project fixture use common code.
- Runtime imports no SQLite/store and creates no state/journal file.

Live evidence remains distinct: read-only inspection, real workspace edit, review,
merge, post-merge checks, host handover and login service. Do not enable unattended
service or call full setup complete until a real episode and recovery are observed.

## Review corrections: decision resumption and bounded recovery

A completed turn that needs a product decision records its originating phase. For
workspace-write turns, checkpoint owned partial edits locally before waiting; do
not publish or treat them as verified. An authorized resolution resumes that phase
against the same bound intake and accepted policy. A fresh attempt ID prevents a
previous resolution marker from resolving another later question. Design resumes
only the Issue's exact spec path; implementation and correction resume their own
work, with verification and independent review still required afterward. Read-only
review decisions resume the corresponding review path. Operator comment context
remains untrusted input and never changes scope or policy by itself.

Authorized failure replanning resets bounded failure counters and returns the task
to executable design/implementation work, rather than treating unchanged code as
ready for delivery. Published work remains subject to actual PR ownership and head
checks. A recorded local checkpoint must exist at its exact recorded head before
continuing. A different host with only an older published head holds the task;
confirmed shutdown does not recreate an unpushed commit. Explicit recovery of an
unknown stopped write may checkpoint its preserved edits under the existing rule.

Successful verification output is bounded private input to independent review,
including warnings and skipped checks, not public progress text. Exhausted review
request retries enter explicit diagnosis/replan wait instead of an endless remote
review wait. Closed Issues with authenticated pending close intent remain eligible
only for actual merge/post-merge reconciliation, never new implementation.

Acceptance adds real origin-phase dispatch after a decision, partial-edit retention,
actual new implementation after replan, exact spec-only edits, missing unpublished
checkpoint refusal, successful-output review without public disclosure, three failed
review requests followed by diagnosis, and closed-Issue recovery through serve/status.

## Review corrections: integration, verification stop and completion policy

Before scope verification of unpublished work, check that its owned head includes
current default-branch revision. Fetch alone is not integration. If it does not,
perform a bounded correction to integrate that exact base while retaining normal
non-force ancestry; checkpoint and verify the new head. Reconcile pending publish
intent first, using its original pinned base to distinguish real candidate scope
from unrelated upstream-only differences; do not overwrite an uncertain effect.

Registered verification honors the same stop predicate as the CLI deadline and
signals. The owned active process group is terminated within the bounded polling
interval, and no later verification command or correction is dispatched after stop.
The trusted storage provider receives this predicate and must enforce it together
with its timeout. A cancelled check is a wait, never a passing receipt.

Design readiness requires the requested spec to be an actual non-symlink regular
file tracked by the owned Git worktree. Missing, untracked/special/aliased or empty
artifacts enter bounded diagnosis instead of another unbounded design turn. Check
regular-file identity before reading or hashing the spec; candidate_ready is not
proof that the artifact exists. Only its exact path is allowed during design.

If an authorized owned PR has actually merged at the recorded head and changed the
project policy, completion-only reconciliation uses the original pinned contract
for its post-merge checks and Issue finalization. This applies even if the new policy
is missing or invalid. Actual ownership/merge/head facts establish this narrow path;
labels or progress prose cannot establish it. It never starts a model, publishes,
creates a PR, adopts a new policy or performs another merge. Current Issue stop,
pause, decision and bound-intake controls remain enforced. Unmerged work still holds
on changed policy; later work must use the newly accepted current contract.

Acceptance adds advanced-base unpublished integration, verification process-group
shutdown on deadline/signal without later commands, missing/FIFO/symlink/untracked
spec refusal, and merged policy-change completion through step/serve/status with
no model or repeat merge. Pending or unowned policy changes cannot use this path.

## Review corrections: pending work and actionable recovery

Integration is preparatory work, not proof of completed implementation. Preserve
the pre-integration phase and any pending implementation when integrating a newer
base. A usage or other wait before implementation must likewise retain that work;
base-only commits cannot substitute for the Issue's requirement-linked change.

At the final fresh merge observation, reapply the shared owned-PR predicate before
recording merge intent. Head, checks and mergeability cannot substitute for current
ownership. Unknown or removed ownership never permits the merge request.

After three failed or uncertain service requests at one head, enter a durable
diagnosis/replan wait instead of silently polling an exhausted action. Preserve any
uncertain effect intent until remote reconciliation. Authorized replan resets the
bounded service counter and resumes that effect's reconciliation, without starting
unrelated implementation or creating a duplicate effect. A terminal missing or
conflicting result still holds; replan is not permission to adopt another head.

Out-of-scope implementation or correction checkpoints enter bounded correction or
diagnosis within the original allowlist. Restore unintended candidate changes to
the observed base; never broaden policy or delete unrelated work. After exhaustion,
the existing explicit replan marker can resume correction. Uncertain publication
continues to reconcile its exact request before any new candidate edit.

Workspace-write phases remain active until the owned local checkpoint and its head
are durably recorded. Model completion alone cannot mark design, implementation or
correction done. If checkpoint creation or its progress write fails, preserve the
active write and existing uncertainty so the stopped-work recovery route remains
available. Never silently overwrite or adopt dirty files on restart.

Acceptance adds base integration and usage waits before first implementation,
ownership changes at the final merge observation, exhausted publication/PR/merge/
close/thread requests with authorized reconciliation, scoped recovery of an unwanted
path, and interruption/checkpoint failure after each workspace-write phase.

## Review corrections: acquisition and terminal observations

A progress comment created for a dependency or resource wait does not acquire an
existing remote branch. Reconcile the fixed branch and PR before durable waits and
again before workspace/model/effect dispatch. A remote branch is explained only by
an actual owned PR, a previously confirmed published head recorded by the service,
or the exact target of its authenticated pending publication. A local checkpoint
or progress ownership alone cannot explain a newly appeared remote branch. Preserve
unexplained refs/PRs and wait without checking them out or marking them owned. Record
the confirmed published head only after actual remote read-back; it is not a gate.

An uncertain merge remains the original exact-head effect until actual remote
reconciliation. New findings, behind state or changed delivery facts do not authorize
another model, integration, correction, publication or replacement PR. Re-read the
owned PR; finish an actual matching merge, or retry the exact effect only while its
current delivery gates hold. Otherwise retain the pending head/base and uncertainty.
Issue/policy controls still apply; no stale observation or human comment proves merge.

Artifact validation and descriptor reads share the same 1 MiB maximum spec size.
Oversized regular files enter diagnosis before recording design readiness. CLI
timeouts must be finite and positive before runtime/provider/lock acquisition; NaN,
infinity and overflow cannot disable the run deadline.

Current-head provider rows count as active only for recognized queued/running
states, and as successful only for completed states accepted by the delivery gate.
Failed, cancelled, error or unknown terminal status enters durable diagnosis rather
than an endless review wait. Operator/provider recovery may start another review;
diagnosis itself is neither completion nor permission to bypass the provider gate.

Acceptance adds foreign refs present before or appearing during dependency/resource
waits; pending merge with new findings/behind state and later actual merge read-back;
regular oversized specs; non-finite parsed CLI timeouts; and terminal code/security
review rows without findings. Preserve the original scope, credentials and native
protection. These are recovery clarifications, not a new operating component.

## Review corrections: delivery evidence and interrupted allocation

Interrupted design is subject to the same exact-spec boundary as successful design.
Preserve an owned local checkpoint, but publish it only when its diff contains exactly
the delegated spec and that artifact passes regular-file/size validation. A broader
global implementation allowlist cannot authorize design output. Retain design
continuation and diagnose an invalid checkpoint without exposing non-spec edits.
Interrupted implementation/correction keeps its existing scoped checkpoint behavior.

Required CI that has actually reached any terminal non-success state enters bounded
recovery or actionable CI diagnosis, including cancelled, startup_failure,
action_required, stale, neutral/skipped and unknown terminal conclusions. Select the
current formally bound workflow/event/head/job/Actions source, rather than an
unrelated check with a matching display name. Queued/in-progress work still waits.
Ordinary code remains responsible for observation; a terminal state cannot silently
become an endless model-free gate wait or a false success.

Every final delivery guard re-reads dependencies from the unchanged bound intake.
A reopened dependency stops the effect before its intent/request, including a
change while recording intent. Preserve existing uncertainty; do not rewrite goals
or infer a closed dependency from its old observation. Other ready work may continue.

An owned exact-head PR merged outside this service is an observed merge, not proof
of completed delivery. Before Issue completion, verify the preserved candidate
head/repository/path scope, formal PR CI, authenticated Code/Security evidence,
resolved threads and required head-specific human review for protected changes,
then the actual merge commit's bound main checks. Missing/stale/unknown evidence
keeps completion waiting; no model, PR, publication or repeat merge can repair an
already merged candidate in place.

Separate candidate evidence from permission to perform a new merge. Historical
completion does not require an open/mergeable PR, automatic merge enabled, or the
old PR base to equal current main. Preserve formal PR number, head, repository,
event, job and source identities. A historical server association must have a valid
base identity; it need not equal main after that merge. The pinned reusable producer
requirement for an empty target-event association remains unchanged. Never forge an
open PR or passing observation to reuse an effect gate. Changed-policy completion
uses the already specified pinned-contract route and never adopts new policy.

Builtin standalone workspace allocation clones into an unpredictable sibling
staging directory. Validate its actual standalone checkout, branch, origin/push
origin, cleanliness, expected remote and ownership tuple keyed to the final
canonical path, then atomically promote without replacing any existing destination.
Plain replace-capable rename is insufficient. Unsupported exclusive promotion or
a destination race holds safely. A pre-promotion interruption leaves final absent
and preserves abandoned staging; restart may allocate fresh staging without
adopting or deleting the abandoned/foreign path. After promotion, ordinary ownership
validation can resume. Never move lifecycle-provider linked worktrees behind their
resource registry; those retain the existing provider recovery contract.

Linux SDK/capability cleanup must actually reap adopted descendants before reporting
clean. Use one short-lived per-execution subreaper helper outside the SDK process
group; it is part of the existing process boundary, not a scheduler or service.
Verify subreaper setup before SDK dispatch. A separate bounded private channel
records the actual owned SDK PID/group and cleanup receipt; it is not inherited by
the SDK worker. Preserve existing SDK assignment/event/identity/ACK/policy framing.
The parent targets only the recorded live-owned group, the helper survives to reap,
and clean requires the receipt, helper reaping and group absence. No process-wide
coordinator adoption, unscoped child wait or zombie-ignore shortcut is permitted.
Execution and capability probes share this supervision; macOS keeps its direct path.
Setup/receipt/helper failure or any live residual remains unknown and blocks dispatch.
Coordinator death without a receipt remains unresolved; a broken PID 1 may retain
the helper itself as a zombie, so this does not promise its absence after parent loss.
No new credentials, environment provisioning or process outside owned execution is
authorized by this correction.

Acceptance adds exact-spec versus extra-path interrupted design, all formal terminal
CI outcomes with active/unrelated controls, reopened dependency at final intent,
externally merged missing/stale candidate evidence versus normal historical
completion, allocation interruption before/after promotion and foreign destination
races, plus real Linux timeout/cancellation/resistant-descendant/EOF and capability
cleanup. Local macOS evidence and actual Linux CI remain distinct; unavailable Linux
execution is not a passing result. Native protection and actual product delivery
requirements remain unchanged.

OS semantics: [Linux subreapers](https://man7.org/linux/man-pages/man2/PR_SET_CHILD_SUBREAPER.2const.html)
and [exclusive rename](https://man7.org/linux/man-pages/man2/rename.2.html).

## Review corrections: verification and final observation

Review-request recovery binds the bounded delivery attempt to the exact head and
review kind. An authentic current-head running/queued/completed provider row settles
only that pending kind, including a successful request whose response/progress was
lost. Clear that reconciled intent before requesting the other kind. An unrelated
Code row cannot reset an unknown Security request. Legacy aggregate records may be
reconciled only when the original kind is identifiable from their requested-head
markers and provider facts; otherwise diagnose rather than transfer exhausted
attempts. Preserve existing request authentication, bounded retries and native gates.

Re-read formally bound push checks for the exact merge commit after recording the
close intent and after the final PR-candidate observation. Pending, failed or newer
rerun checks stop both a new close and recovered completion, retaining the close
intent. Reapply current Issue, dependency and policy controls after that final
external observation and before the effect/completion record.

Registered verification is a potentially mutating owned execution. Record its
intent before dispatch. Once process cleanup is confirmed, inspect the checkout
before independent review. Preserve tracked/untracked edits and changed HEAD as an
owned local checkpoint, record the new revision and enter existing bounded
correction for verification mutation. Do not reset/delete the work or accept the
old verification receipts for the new revision. Stopping preserves that correction
continuation; failure or cancellation must not strand known completed mutations.
After correction, re-run verification and independent review for the resulting
head. A repeated mutating verifier reaches durable diagnosis rather than an endless
loop. Unconfirmed cleanup or interruption retains execution ownership and prevents
another host execution until explicit stopped recovery. On that recovery, detected
verification mutations receive the same correction treatment before delivery.

Verification on Linux reuses the existing per-execution subreaper/helper and cleanup
receipt, including actual descendant reaping and group absence. Keep the synchronous
workspace/provider API by a bounded per-call adapter to that same process handle;
do not run a nested event loop in the coordinator or alter host-wide child ownership.
Poll stop/deadline at most every 100ms, bound output, and confirm cleanup before
returning pass, failure or stopped. Unknown supervision holds the host. Service Git
commands retain their existing path; this is not another service or scheduler.

Decode Git path bytes losslessly using filesystem surrogate handling. Paths that
cannot be represented as valid public UTF-8 remain local and outside publishable
scope, even under a broad allowlist. Route them through existing bounded scope
correction or durable diagnosis with byte-preserving private details. Do not let a
decode exception wedge every reconciliation, publish escaped surrogate paths, or
remove foreign/unrelated files.

Acceptance adds lost third Code request with first Security request, exhausted
unknown Security despite an observed Code row, close-intent push-check reruns and
closed-Issue recovery, successful/failed/stopped verification edits and commits,
interrupted verification/checkpoint-record failures and bounded mutation correction,
real Linux verification stop/timeout/EOF/resistant descendants under a nonreaping
ancestor, and actual invalid-UTF-8 tracked/untracked filenames. Existing product
delivery, native protected approvals and final-head provider reviews remain required.

## Review corrections: undispatched work and ambiguous reviews

If the final guard rejects a newly recorded model or verification intent before
dispatch, restore its prior non-executing checkpoint and continuation. No worker
started, so clearing the stop, pause or dependency boundary must permit ordinary
reconciliation without a stopped-worker handover. Preserve the original attempt,
head, scope, correction budget and any continuation marker. If the compensating
progress write is unavailable, retain the durable intent as unresolved; never
claim that an actually dispatched or unknown execution did not start. Existing
uncertain external publication/merge/review requests keep their reconciliation.

Multiple authenticated provider summaries or repeated rows for a review kind enter
the existing durable diagnosis/replan path. Do not pick a favorable row, request
repeated reviews, or silently wait forever. Preserve an uncertain review request
and its original head/kind until authentic evidence settles it. An authorized
replan resumes review reconciliation for the unchanged candidate, not unnecessary
implementation; ambiguity still blocks delivery until the provider facts are
unambiguous. Existing evidence authentication and native protection remain intact.

Acceptance adds final-guard rejection before every model/verification phase and
ordinary restart after the boundary clears, preservation of pending correction
and genuine unknown execution, duplicate authenticated summaries/rows with and
without an uncertain request, and authorized replan after evidence repair.

## Review corrections: observation scope and service Git

Revalidate the latest PR's shared ownership predicate before any PR-side mutation,
including review requests and thread resolution. Earlier branch/list ownership
cannot authorize effects after its marker or author changes.

Use native Issue state and labels for work discovery: open delegated intake and
closed `hydra:active` recovery are separate bounded collections. Set the active
label before an owned progress write can authorize execution, and remove it only
after verified completion is durably recorded. An interrupted label cleanup is
reconciled from the completed progress and actual delivery facts on the next cycle.
Authenticate and parse progress before admitting a closed recovery candidate.
Labels select and display work; PR, CI, reviews and actual merge facts still prove
delivery. Do not scan historical closed Issues, add a search marker, new journal or
local persistence. Collection/label failures hold safely. Read-only status does not
mutate labels. Direct `run --issue` still reconciles older unlabeled pending intents.

Reject an intake specification outside the registered candidate allowlist before
design or implementation dispatch. Do not silently broaden policy to accommodate it.
Count dependency edges from otherwise valid delegated, unpaused intake before
excluding dependency-blocked work from execution. Preserve recovery-first sorting;
malformed, unauthorized or paused work cannot boost another task's priority.

Validate every reported usage bucket and every actual reported window. Each bucket
needs at least one valid numeric finite window, and every observed usedPercent must
remain within the existing 0..80 dispatch boundary. A missing/null optional window
is unreported, never zero; malformed buckets/windows must not be normalized to null
or hidden by a healthy bucket. Use legacy rateLimits only when the multi-bucket map
is absent/null, not when a supplied map is empty or malformed. Invalid normalization
keeps usage unknown. Credits do not override this existing policy.

Required CI is the explicitly bound job and matching check, not optional jobs in
the same workflow. After formal producer/run identity validation, inspect that job
and check before failure classification. A completed required job/check can pass
despite another job's aggregate failure. Actual required-job failure, cancelled or
missing startup work still reaches the existing bounded recovery or diagnosis;
unknown identities and active required work cannot pass.

All service Git operates with a per-call generated trusted configuration and actual
validated HEAD/index/data paths. Use a private common-directory view with the actual
per-worktree gitdir and explicit worktree, preserving supported standalone and
lifecycle-provider-approved linked layouts. Candidate local config, includes,
config.worktree, filters, fsmonitor and transport commands must never execute.
Read the existing ownership keys and origin from bounded raw snapshots with includes
disabled in a neutral context; preserve their storage and shared config bytes.
Pass the service-derived GitHub HTTPS URL directly to remote commands, with the
fixed credential helper and protocol restrictions. Preserve genuine checkpoint
visibility, guarded nonforce publication and actual remote read-back. Unsupported
or foreign metadata holds rather than weakening the boundary. This limits service
Git configuration execution; it does not claim hostile-worker host isolation.

Acceptance covers fresh PR ownership changes before intermediate effects, large
closed histories with small open intake and authenticated active-label recovery,
out-of-policy specs before any model turn, valid/invalid mixed usage buckets,
required versus optional CI failures, dependency-unblocker selection, and real Git
fsmonitor/include/worktree/filter/transport traps in both supported layouts using
only synthetic credentials. Final-head reviews, native approval and actual product
delivery remain unchanged.
