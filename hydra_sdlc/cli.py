"""Private local operator interface. No publication or completion override."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sqlite3
import sys
from pathlib import Path

from .store import StateError, StateStore


def parser():
    p = argparse.ArgumentParser(prog="hydra", description="Bounded execution; autonomous delivery is not yet implemented")
    p.add_argument("--state", type=Path, default=Path.home() / ".local/state/hydra/state.sqlite3")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("status")
    work = sub.add_parser("work").add_subparsers(dest="work_command", required=True)
    work.add_parser("add").add_argument("file", type=Path)
    run = sub.add_parser("run")
    run.add_argument("--once", action="store_true", required=True)
    for command in ("pause", "resume", "cancel"):
        sub.add_parser(command).add_argument("work_id")
    doctor = sub.add_parser("doctor")
    doctor.add_argument("--cwd", type=Path, required=True)
    return p


def main(argv=None):
    args = parser().parse_args(argv)
    os.umask(0o077)
    try:
        if args.command == "doctor":
            from .codex import capabilities

            result = asyncio.run(capabilities(str(args.cwd.resolve(strict=True))))
        else:
            path = args.state.expanduser().absolute()
            store = StateStore(path)
            if args.command == "status":
                result = {"state": str(path), "work": store.list_work(), "runs": store.list_runs()}
            elif args.command == "work":
                result = store.add_work(json.loads(args.file.read_text()))
            elif args.command == "run":
                from .coordinator import run_once

                result = asyncio.run(run_once(store, path))
            else:
                method = "request_cancel" if args.command == "cancel" else args.command
                result = getattr(store, method)(args.work_id)
        print(json.dumps(result, indent=2, ensure_ascii=False))
        return 0
    except (StateError, ValueError, OSError, ImportError, sqlite3.Error) as exc:
        # Do not print provider exceptions, environments or auth payloads.
        print(json.dumps({"error": type(exc).__name__, "message": str(exc) if isinstance(exc, StateError) else "Operation failed; inspect local prerequisites and input"}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
