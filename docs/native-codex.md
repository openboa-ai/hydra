# Native Codex setup and recovery

Codex owns native tasks and model execution. Hydra's stdio MCP server performs
registered GitHub/workspace operations and returns the next bounded assignment.
Product GitHub records are durable workflow truth. There is no second scheduler,
model service or local workflow database. The existing CLI remains supported.

## Install a reviewed revision

Create an isolated environment from the reviewed source revision:

```sh
python3 -m venv /absolute/approved/hydra/venv
/absolute/approved/hydra/venv/bin/python -m pip install '.[mcp]'
```

The portable plugin uses `hydra-mcp` on PATH. A desktop installation must resolve
that command to the approved environment; otherwise bind its MCP command to the
absolute approved Python with arguments `-m hydra_sdlc.mcp --config HOST_SETTINGS`.
Make this host binding in the installed plugin copy, retain the reviewed source
revision, and check initialization/list/call before using it. Do not run an editable
candidate checkout as the installed operating version.

The local marketplace is `.agents/plugins/marketplace.json`. Add this source through
the supported Codex plugin manager, install `hydra@hydra-local`, and confirm the
skill and the five MCP tools in a new native task. Plugin visibility, remote
notifications and questions/resumption require actual app qualification; a CLI
plugin installation receipt alone does not demonstrate them.

Installed host settings default to `~/.config/hydra/host.toml`:

```toml
repos = ["owner/product", "owner/another-product"]
host_alias = "development-mac"
workspace_root = "/absolute/owned/workspaces"
lock_path = "/absolute/owned/coordination/host.lock"
# Optional trusted, installed resource factories:
# lifecycle_provider = "host_resources:lifecycle"
# storage_provider = "host_resources:storage"
```

The native server and CLI must use the same lock and owned workspace root. The
allowlist and provider factories are installation settings, never Issue input.
Managed workspaces still require their existing lifecycle/storage providers. The
GitHub identity remains `openboa`; no new credential or approval identity is added.
An optional private knowledge repository can be set on the host. It is read-only
research context, never workflow truth or public prompt/transcript storage.

## Common task flow

1. Read current goals and `hydra_status`. Choose a delegated ready Issue, prioritizing
   recovery and pending delivery. Product planning may remain pending.
2. `hydra_begin` reconciles GitHub and prepares the owned worktree. A `native_task`
   response provides phase, prompt, mode, attempt, step, initial head and policy.
3. Codex executes that assignment. Independent spec/change reviews inspect actual
   artifacts and recorded verification without writing the checkout. Workers do
   not commit, push or merge through a competing path.
4. Submit `hydra_checkpoint` with its exact identity and candidate result. Hydra
   commits owned edits, checks actual scope/spec and chooses the next continuation.
   Committed write results include the read-back attempt, current head and policy
   for the next tool call; use these instead of the assignment's pre-edit head.
   `candidate_ready` is judgment, not acceptance of a PR or a check.
5. `hydra_verify`/`hydra_deliver` continue the same guarded workflow. These are
   continuation entry points, not separate authorization boundaries. They may
   return another assignment or reconcile publication, actual code/security
   reviews, CI, exact-head merge and post-merge observation. No override exists.

Native task creation/messaging and independent delegation must be explicitly
authorized. Use outcome-sized tasks, avoid duplicate writers and connect each
task to its Issue. One common skill coordinates the workflow; no hook automatically
creates an extra model loop.

## Decisions and interruptions

Submit `needs_decision` before asking an actual product/authority question in the
native task. Hydra checkpoints partial edits and records the originating phase.
Record the publishable answer and `hydra: decision ATTEMPT_UUID resolved` from an
authorized actor before resuming. The native question, Codex permission dialog and
GitHub CODEOWNER approval are different mechanisms.

An unresolved native assignment retains a bounded admission ticket in the existing
OS lock. It blocks another repository too, even if its Issue is paused or closed.
Service restart and reboot do not prove a native task stopped. Inspect and stop
the old task/processes, then submit `stopped` with its original identity. Owned
edits are preserved; late results cannot consume the new step.
If the remote branch changed or was deleted, explicit stop can still preserve and
commit the existing owned local edits and release its matching ticket. The original
expected ref stays pinned; the affected Issue waits for remote reconciliation.

If assignment publication was unconfirmed, the returned recovery identity can
release only its exact scoped ticket after explicit stop. It never manufactures
progress or adopts a checkout. GitHub unavailability preserves the hold. A write
completion records committed origin-phase recovery before retiring admission, so
callback failure or response loss can resume with fresh review and verification.
Read-only status does not take ownership or clean resources.

The trusted single-host lock is coordination, not credential isolation or a
distributed lease. Unpushed changes are not recoverable after host loss. Runtime
promotion, actual two-project delivery, remote question/resumption and a subsequent
scheduled continuation remain separate acceptance evidence.

The plugin layout follows [official plugin documentation](https://developers.openai.com/plugins/build/plugins).
