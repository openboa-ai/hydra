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
