# Mac operations and shared execution controls

Status: implementation candidate, revision 6. Base: b59616b3e6210661aa62b30496efc6bed97c6826.
Work record: https://github.com/openboa-ai/hydra/issues/3.

## Outcome and authority

R1. Provide a TypeScript-based macOS menu-bar application and one compact operations window.
The operator can inspect each registered repository and request Start, Pause,
Resume or Stop for one repository or the host. The application uses Hydra's real
local control interface; buttons must not merely change display state. This scope
adds a small operations surface to the existing GitHub/native contracts. Product
work, policy, reviews, approvals, credentials and model selection do not change.
No web control server, workflow database, private desktop API, settings-database
editing, replacement scheduler or hidden SDK worker is introduced. Existing
product schedules are not changed by development or tests.

R2. Distinguish three facts: requested operating mode, applied admission gate, and
observed execution state. GitHub remains workflow truth; native Codex retains
questions and answers. The only new durable host data is versioned operating
settings: global mode and per-repository overrides, with monotonic revision and
last update time. It stores no work history, candidate evidence or transcripts.
Default missing settings deny new work. Malformed, untrusted or unreadable settings
also deny new work and cannot be silently replaced by an enabling action.

## Mode and concurrency contract

R3. Modes are running, paused and stopped. Global Start/Resume set only the global
mode to running; project overrides survive. A project Start/Resume under a blocked
global gate is rejected without changing the project override. Project Stop/Pause
change only that repository. Global Stop/Pause block every registered repository
without rewriting its override. New projects inherit the global mode. Reboot,
restart and elapsed time never undo an explicit mode.

All installed CLI, MCP and app routes derive the same control settings and a
separate control lock from the trusted host lock path. The filesystem is a trusted
single-user host boundary, not a defense against an operator changing installed
configuration or executing older code. No Issue, PR, model output or project file
selects this path. The control store rejects symlinks, unsafe ownership/modes,
unknown keys/versions, invalid repository identities and oversized input. Writes
are serialized, atomically replaced and fsynced. Reads do not repair corrupt data.

R4. A short shared control lock guards each side effect's last eligibility check
through the side effect; a mode update takes the exclusive control lock. Thus an
already admitted bounded call may finish before Pause applies, but no new effect
can pass after the acknowledged mode revision. Pending UI requests show pausing
or stopping. A control request may wait for a currently admitted call; the UI must
remain responsive and must not report its gate as applied before read-back.
Never hold the control lock throughout a model turn, verification process or
polling sleep. The existing coordinator lock still owns execution admission and
native tickets. Control updates do not acquire it or clear it.

R5. Gate both entry and effects: workspace preparation/fetch, model/native
assignment admission, local mutation for new work, publish, progress writes, PR,
review, merge, close and resource retirement. Read-only observation remains
available. A project-specific cancellation callback reaches the existing owned
SDK and verification supervision; pausing one project must not stop another
eligible repository's loop. Host Stop ends the managed foreground loop after
owned cleanup; host Pause exits or waits without dispatch. Native assignments
outside that loop cannot be declared stopped by the gate.

There is one narrow cleanup exception: after the exact existing execution is
confirmed ended, or positive evidence confirms it was never dispatched, preserve
owned local edits and record/read back its bounded
stopped/interrupted checkpoint and retire only its matching admission ticket.
This permits only that bounded GitHub progress write and its read-back, while
branch push and PR publication remain forbidden under a blocked gate.
The exception never permits push, a new PR, review, merge, close, new assignment,
resource deletion or another repository. For an unconfirmed assignment with no
work record, retire only its exact scoped admission ticket; never manufacture
progress or adopt a workspace. Uncertainty retains the hold. The existing SDK stop path's checkpoint
publication must not bypass the new operating gate. If a remote effect was already
in flight or its result is uncertain, preserve and reconcile its existing intent;
do not retry it while the gate is blocked. Preserve all branches, worktrees and PRs.

## Honest execution observations

R6. The control response includes schema version, settings revision, observed_at,
global requested mode, each repository's override/effective mode, gate result,
work observations, capability limitations and execution observation. Counts are
nullable; unavailable evidence must not become zero active executions. Display
running/ready separately from paused/pausing/stopped/stopping/unknown/blocked.
Pause/Stop completion requires a current clean ownership observation and all
managed targets accounted for. Native tickets, unavailable GitHub observations,
unknown processes, unsupported native interruption or unverified schedule coverage
remain visible as unresolved; aggregate results preserve partial completion.

Inspect the existing coordinator lock without changing it. Bind any native ticket
to authenticated progress using its existing scope digest. Unmapped ownership
cannot be attributed to an arbitrary repository or killed by PID/name. A free lock
is insufficient evidence when an unresolved ticket or residual worker remains.
Old installed runtimes and schedules not verified to use this gate are explicitly
outside confirmed control coverage. Source tests do not certify an installation.

R7. This revision has no qualified desktop turn-control adapter. It explicitly
reports native_turn_control=unsupported and never invokes generic thread/resume,
turn/start or turn/interrupt against persisted desktop chats. A configuration
boolean cannot qualify the connection. Start/Resume requests change admission
permission only, not the execution fact: the response and UI say that new eligible
Hydra ingress is allowed and automatic native continuation remains unavailable.
They never start a substitute worker or enable a paused external schedule. An
unresolved native assignment still blocks actual admission under the existing
exact-identity rules. A future connector requires independent evidence of common
execution ownership, atomic admission and real native question/answer routing.

## Interface and app

Use Tauri 2 with a TypeScript renderer and a thin Rust command bridge. Keep the
Python execution core. Rust alone owns child-process invocation and window/tray
lifecycle. Load only bundled local content with a restrictive CSP; deny external
navigation and new windows, and validate each command action and target against
the loaded host settings. Scope Tauri capabilities to the main window and expose
only status/control/open-record operations, never generic shell, arbitrary argv,
filesystem writes or arbitrary URL opening. UI text from GitHub is rendered as
text, never HTML. Pin dependency versions and lockfiles. No renderer remote code or
development server in the packaged app. Use documented Tauri close/exit lifecycle
events, with one serialized Stop-and-confirm flow before an explicit Quit.

R8. Add `hydra control status|start|pause|resume|stop --config HOST_SETTINGS` with
an explicit `--all` or `--project owner/repo` target for mutation. Reuse validated
installed settings and repository allowlist; do not load provider factories merely
to change modes or inspect local controls. Return bounded JSON, no credentials or
raw provider diagnostics. Five MCP tool names remain compatible. Their operational
results may add mode/reason metadata. All mutating MCP methods are gated, including
long-lived server instances; exact stopped checkpoints retain R5's exception.

The app invokes an explicitly selected absolute installed Python executable with fixed
`-I -m hydra_sdlc.cli control ...` argument arrays and an absolute host configuration
path. Use a trusted non-repository working directory and a controlled environment;
ignore inherited PYTHONPATH and user site-packages. Verify that the installed package
is used, including when the parent process starts from a hostile repository cwd. It does not concatenate a shell command, resolve a runtime from a repository,
or load a candidate plugin into an active desktop session. Read-only refresh may
query GitHub, but local controls remain available when remote observations fail.
Use a separate read-only refresh operation/flag when remote results would delay
an urgent Pause request. Rust-owned child output/time are bounded; loss of a mutation
response means reconcile by status, never optimistic success or blind retry.

Remote refresh has one transient monotonic 45-second / 4096-API-request budget.
Each repository receives at most the remaining budget divided by the remaining
repository count, so an early backlog cannot consume a later repository's share.
Nested budgets cover pagination, progress authentication and the transport's own
identity API calls. Every auth, identity and API subprocess timeout is capped by
the remaining deadline; injected transports consume the same logical API budget.
Expired responses are not fresh evidence. Exhaustion preserves authenticated
work already observed, marks that repository incomplete and continues with the
next repository's reserved share. The separate display limits remain 128
authenticated records per repository and 512 overall; ordinary Issues do not
consume them. Budgets end with the refresh and introduce no saved workflow state.
The 60-second Rust deadline remains the outer safety limit: remote reads leave
five seconds for the bounded residual-worker probe and ten seconds of margin for
startup, local observations and response serialization. Local observations still
follow remote reads, with admission read last. Budget exhaustion never proves zero
owned executions or permits Quit.

R9. Window: host mode and connection freshness; global controls; repository cards
with distinct mode/work phase, current Issue/PR, wait reason, next action and scoped
controls. Preserve explicit project pauses after global Resume. Detail links open
validated GitHub HTTPS or configured Codex chat deep links in their native surface;
untrusted arbitrary URL schemes are rejected. Questions and approvals open the
original surface rather than creating a second inbox. Unknown/stale observations
carry text and an icon and never show a green success state.

Menu bar uses a functional symbol with an accessible name, not a redrawn logo.
Closing the window hides it. Explicit Quit requests global Stop and waits for
confirmed owned execution termination. Quit is blocked when a required owned
execution is unresolved, or stopping it requires unsupported control. Unsupported
native capability alone does not block Quit when current positive observations
establish zero owned executions and all managed gates/targets are accounted for.
Unknown schedule coverage is not positive zero evidence. Explain any blocked Quit.
No forced termination of unrelated Codex processes.
The app owns no model worker itself and does not activate on login in this change.

R10. Map the canonical OpenBoa light/dark tokens explicitly for colors, spacing,
radii, typography, borders and focus. Resolve aliases to exact values; dimensions
use CSS px in the renderer, with no Retina multiplier. Preserve token
names and a source content digest in a small publishable theme mapping, without
private filesystem paths or research narrative. Include only used assets and
their required licenses. Bundle the original variable TTF/WOFF2 fonts and load
them locally with explicit CSS font-face and canonical weight/width/line-height/
tracking. No remote font requests. State is communicated by text
and icons as well as color. Static cards use surface and border without shadows.
Retain the Hydra product name; do not alter OpenBoa marks.

## Acceptance and delivery

A1/R2-R4: missing/corrupt/unsafe settings deny work; concurrent requests preserve
project overrides; mode survives new processes; symlink/replacement and duplicate
JSON keys are rejected; no workflow history stored.
A2/R3-R5: host Pause blocks CLI run/serve and all mutating MCP paths, including an
already constructed server; project Pause blocks A while B remains eligible;
global Resume preserves explicit project Pause/Stop; no new push/PR/merge occurs
after the gate barrier, including the existing interrupted-checkpoint path.
A3/R4-R6: use real isolated subprocesses to exercise an admitted operation racing
Pause, owned cancellation, lock release, failed cleanup and lost response. Preserve
unknown ownership after restart. Do not inject failures into product main.
A4/R5-R7: exact stopped cleanup remains possible without publishing, including
the positively confirmed never-dispatched ticket with no progress record; stale scope
cannot exploit cleanup; native unknown and unverified schedule coverage cannot be
reported as stopped. No fixture or settings flag enables desktop turn control.
A5/R8-R9: launch the compiled macOS app against an isolated host fixture, exercise
actual buttons and read back shared modes, including partial/unknown states and
global/project precedence. Verify zero-owned-execution successful Quit, unresolved
native execution refusing Quit, window close retaining gate/status operation, and
malformed command output. Verify that a hostile cwd/PYTHONPATH cannot substitute
the installed Python package.
Capture the running app before final PR publication. Fixture control is reported
separately from production-native control.
Verify cumulative request/deadline limits through the actual GitHub client,
including auth and internal identity subprocess timeout values, nested budget
restoration and a real subprocess timeout. Delayed or request-heavy early
repositories must preserve authenticated prefixes while later repositories remain
observable. Keep the positive case with 150 ordinary Issues and one authenticated
work record, and verify normal multi-repository refresh and final local probes.
A6/R10: verify each used token's CSS value against its canonical alias chain
and final resolved value, in addition to the source content digest;
verify bundled fonts/theme, inspect light/dark state readability and keyboard labels.
A7: existing Python regression suite and new control tests pass; TypeScript build,
type checking and focused bridge/state tests pass. Independent spec, code and security reviews
inspect the actual final revision. Preserve protected GitHub delivery checks.

Source, local fixture operation, PR checks/reviews, merge, installed version and
production pause/resume are separate receipts. This implementation does not resume
the host's existing schedules, install a service, replace active MCP processes or
claim two-minute native event continuation. Keep the earlier continuation candidate
and acceptance evidence; its unproved native behaviors remain pending.
