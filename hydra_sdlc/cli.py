"""The same foreground CLI is used by a host login service after qualification."""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import math
import os
import signal
import sys
from contextlib import ExitStack
from pathlib import Path

from .coordinator import coordinator_lock, residual_workers
from .progress import with_progress_hint
from .runtime_identity import capture_runtime_identity


def parser():
    p = argparse.ArgumentParser(prog="hydra", description="Develop delegated GitHub Issues with Codex")
    sub = p.add_subparsers(dest="command", required=True)
    for name in ("run", "serve", "status"):
        command = sub.add_parser(name)
        if name == "run":
            command.add_argument("--issue", required=True)
        else:
            command.add_argument("--repos", nargs="+", required=True)
        if name != "status":
            command.add_argument("--workspace-root", type=Path, required=True)
            command.add_argument("--host-alias", required=True)
            command.add_argument("--lock-path", type=Path, default=Path.home() / ".local/share/hydra/host.lock")
            command.add_argument("--lifecycle-provider", help="Trusted installed host module:factory")
            command.add_argument("--storage-provider", help="Trusted installed host module:factory")
            command.add_argument("--knowledge-repo", help="Private knowledge repository configured by the host operator")
            command.add_argument("--timeout", type=float, default=1800 if name == "run" else None)
    identity = sub.add_parser("identity", help="Report this runtime's source and configuration identity")
    identity.add_argument("--config", type=Path)
    control = sub.add_parser("control", help="Inspect or change installed admission controls")
    control.add_argument("action", choices=("status", "start", "pause", "resume", "stop"))
    control.add_argument("--config", type=Path, required=True)
    target = control.add_mutually_exclusive_group()
    target.add_argument("--all", action="store_true")
    target.add_argument("--project")
    control.add_argument("--refresh", action="store_true", help="Refresh read-only GitHub observations")
    return p


def _provider(value):
    if not value:
        return None
    module, factory = value.split(":", 1)
    return getattr(importlib.import_module(module), factory)()


def operate_control(args):
    if args.action == "status":
        if args.all or args.project is not None:
            raise ValueError("Status does not take a mutation target")
    elif (not args.all and args.project is None) or args.refresh:
        raise ValueError("Mutation requires one explicit target and no remote refresh")
    from .control import control_result, load_host_config
    return control_result(load_host_config(args.config), action=args.action,
                          repository=args.project, refresh=args.refresh)


async def operate(args, *, github=None, workspace=None, execute=None, capabilities=None,
                  operations=None, emit=print):
    if args.command == "identity":
        from .control import load_host_config, control_from_config
        cfg = load_host_config(args.config) if args.config else None
        result = capture_runtime_identity(cfg, control_from_config(cfg) if cfg else None)
        emit(json.dumps(result, ensure_ascii=False))
        return result
    if args.command == "control":
        result = operate_control(args)
        emit(json.dumps(result, ensure_ascii=False))
        return result
    if args.command != "status" and args.timeout is not None and (not math.isfinite(args.timeout) or args.timeout <= 0):
        raise ValueError("Timeout must be finite and positive")
    from .codex import capabilities as inspect_capabilities, execute as execute_codex
    from .github import GitHub
    from .runner import Runner, issue_url
    from .workspace import Workspace
    from .operations import OperatingControl, OperationDenied

    github = github or GitHub(user="openboa")
    if args.command == "status":
        runner = Runner(github, None, host_alias="status", execute=None, capabilities=None)
        result = runner.status(args.repos)
        emit(json.dumps(result, indent=2, ensure_ascii=False))
        return result
    if not __import__("re").fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", args.host_alias):
        raise ValueError("Host alias must be a public-safe slug")
    run_target = issue_url(args.issue) if args.command == "run" else None
    admission_repo = run_target[0] if run_target else None
    targets = [admission_repo] if run_target else args.repos
    operations = operations if operations is not None else OperatingControl(args.lock_path, targets)
    reason = operations.reason(admission_repo)
    if reason:
        result = with_progress_hint({"action": "waiting", "reason": reason})
        emit(json.dumps(result))
        return result
    workspace = workspace or Workspace(args.workspace_root, lifecycle_provider=_provider(args.lifecycle_provider),
                                        storage_provider=_provider(args.storage_provider), user="openboa")
    stopped = False
    loop = asyncio.get_running_loop()
    deadline = loop.time() + args.timeout if args.timeout else float("inf")

    def stop():
        nonlocal stopped
        stopped = True

    previous_handlers = {}
    for sig in (signal.SIGINT, signal.SIGTERM):
        previous_handlers[sig] = signal.getsignal(sig)
        signal.signal(sig, lambda _signal, _frame: stop())

    def knowledge_revision():
        if not args.knowledge_repo:
            return None
        repository = github.repository(args.knowledge_repo)
        return github.ref(args.knowledge_repo, repository["default_branch"])

    runner = Runner(github, workspace, host_alias=args.host_alias, execute=execute or execute_codex,
                    capabilities=capabilities or inspect_capabilities,
                    stop_requested=lambda: stopped or loop.time() >= deadline or bool(operations.interruption_reason()),
                    knowledge_revision=knowledge_revision, operations=operations)

    async def drain_completed(result, repository=None, number=None):
        # Keep coordinator ownership for one bounded, cleanup-only opportunity.
        # A deadline or blocking mode forbids new work, not an exact ended
        # execution's checkpoint. Unknown settlement must remain visible.
        cleanup = await runner.drain_completed(repository, number)
        if not cleanup:
            return result
        result = {**result, "cleanup_results": cleanup, "checkpoint_status": "recorded"}
        pending = [row for row in cleanup if row.get("checkpoint_status") != "recorded"]
        if pending:
            result.update(checkpoint_status="pending", execution_state="unknown",
                          execution_reason=pending[0].get("reason") or "checkpoint_recording_unconfirmed")
        return result

    last = None
    try:
        with ExitStack() as ownership:
            # Hold the mode barrier only while acquiring admission, never for
            # a worker turn, verification or the foreground polling loop.
            with operations.guard(admission_repo):
                ownership.enter_context(coordinator_lock(args.lock_path))
            if residual_workers():
                raise RuntimeError("An earlier worker remains; confirm shutdown before starting Hydra")
            while not runner.stop_requested():
                if args.command == "run":
                    repo, number = run_target
                    result = await runner.step(repo, number)
                else:
                    result = await runner.cycle(args.repos)
                external_wait = args.command == "run" and result.get("reason") in {
                    "remote_delivery_gates", "post_merge_checks", "delivery_facts_changed"}
                returning = args.command == "run" and result.get("action") != "continue" and not external_wait
                if returning:
                    result = await drain_completed(result, repo, number)
                encoded = json.dumps(result, sort_keys=True, ensure_ascii=False)
                if encoded != last:
                    emit(encoded)
                    last = encoded
                if returning:
                    return result
                if external_wait:
                    until = min(loop.time() + 60, deadline)
                    while loop.time() < until and not runner.stop_requested():
                        await asyncio.sleep(min(1, until - loop.time()))
                if args.command == "serve":
                    if any(r.get("action") == "continue" for r in result):
                        await asyncio.sleep(0)
                        continue
                    active = any(r.get("action") == "continue" or r.get("reason") in {
                        "remote_delivery_gates", "post_merge_checks", "delivery_facts_changed"} for r in result)
                    delay = 60 if active else 300
                    until = min(loop.time() + delay, deadline)
                    while loop.time() < until and not runner.stop_requested():
                        await asyncio.sleep(min(1, until - loop.time()))
            result = {"action": "stopped", "reason": operations.reason() or "signal_or_deadline"}
            if runner.host_hold_reason:
                # This foreground loop has ended; uncertain owned cleanup is
                # still a hold, not evidence that execution has terminated.
                result.update(execution_state="unknown", execution_reason=runner.host_hold_reason)
            result = await drain_completed(result)
            result = with_progress_hint(result)
            emit(json.dumps(result, ensure_ascii=False))
            return result
    except OperationDenied as exc:
        result = with_progress_hint({"action": "waiting", "reason": exc.reason})
        emit(json.dumps(result))
        return result
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


def main(argv=None):
    args = parser().parse_args(argv)
    os.umask(0o077)
    try:
        if args.command == "control":
            # Exclusive mode changes can wait for an admitted bounded call.
            # Keep this synchronous and outside the async worker event loop.
            print(json.dumps(operate_control(args), ensure_ascii=False))
        else:
            asyncio.run(operate(args))
        return 0
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        # No provider exception, credential, account payload or local path is printed.
        print(json.dumps({"error": type(exc).__name__, "message": "Hydra held the action; check the registered contract and host prerequisites"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
