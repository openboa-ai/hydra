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
from pathlib import Path

from .coordinator import coordinator_lock, residual_workers


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
    return p


def _provider(value):
    if not value:
        return None
    module, factory = value.split(":", 1)
    return getattr(importlib.import_module(module), factory)()


async def operate(args, *, github=None, workspace=None, execute=None, capabilities=None, emit=print):
    if args.command != "status" and args.timeout is not None and (not math.isfinite(args.timeout) or args.timeout <= 0):
        raise ValueError("Timeout must be finite and positive")
    from .codex import capabilities as inspect_capabilities, execute as execute_codex
    from .github import GitHub
    from .runner import Runner, issue_url
    from .workspace import Workspace

    github = github or GitHub(user="openboa")
    if args.command == "status":
        runner = Runner(github, None, host_alias="status", execute=None, capabilities=None)
        result = runner.status(args.repos)
        emit(json.dumps(result, indent=2, ensure_ascii=False))
        return result
    if not __import__("re").fullmatch(r"[a-z0-9][a-z0-9_-]{0,63}", args.host_alias):
        raise ValueError("Host alias must be a public-safe slug")
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
                    stop_requested=lambda: stopped or loop.time() >= deadline,
                    knowledge_revision=knowledge_revision)
    last = None
    try:
        with coordinator_lock(args.lock_path):
            if residual_workers():
                raise RuntimeError("An earlier worker remains; confirm shutdown before starting Hydra")
            while not runner.stop_requested():
                if args.command == "run":
                    repo, number = issue_url(args.issue)
                    result = await runner.step(repo, number)
                else:
                    result = await runner.cycle(args.repos)
                encoded = json.dumps(result, sort_keys=True, ensure_ascii=False)
                if encoded != last:
                    emit(encoded)
                    last = encoded
                external_wait = args.command == "run" and result.get("reason") in {
                    "remote_delivery_gates", "post_merge_checks", "delivery_facts_changed"}
                if args.command == "run" and result.get("action") != "continue" and not external_wait:
                    return result
                if external_wait:
                    until = min(loop.time() + 60, deadline)
                    while loop.time() < until and not stopped:
                        await asyncio.sleep(min(1, until - loop.time()))
                if args.command == "serve":
                    if any(r.get("action") == "continue" for r in result):
                        await asyncio.sleep(0)
                        continue
                    active = any(r.get("action") == "continue" or r.get("reason") in {
                        "remote_delivery_gates", "post_merge_checks", "delivery_facts_changed"} for r in result)
                    delay = 60 if active else 300
                    until = min(loop.time() + delay, deadline)
                    while loop.time() < until and not stopped:
                        await asyncio.sleep(min(1, until - loop.time()))
            return {"action": "stopped", "reason": "signal_or_deadline"}
    finally:
        for sig, handler in previous_handlers.items():
            signal.signal(sig, handler)


def main(argv=None):
    args = parser().parse_args(argv)
    os.umask(0o077)
    try:
        asyncio.run(operate(args))
        return 0
    except (ValueError, RuntimeError, OSError, ImportError) as exc:
        # No provider exception, credential, account payload or local path is printed.
        print(json.dumps({"error": type(exc).__name__, "message": "Hydra held the action; check the registered contract and host prerequisites"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
