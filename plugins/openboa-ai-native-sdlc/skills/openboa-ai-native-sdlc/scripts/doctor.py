#!/usr/bin/env python3
"""Report local OpenBoa context without changing files or calling the network."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
from typing import Any, Sequence


CONTRACT = "0.2.0"
MARKER = f"<!-- openboa-ai-native-sdlc:managed:start contract={CONTRACT} -->"
MAX_AGENTS_BYTES = 131072


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", nargs="?", type=Path)
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--json", action="store_true", dest="as_json")
    output.add_argument("--hook", action="store_true")
    return parser.parse_args(argv)


def run_git(cwd: Path, *args: str) -> tuple[int, str]:
    environment = os.environ.copy()
    for name in tuple(environment):
        if name.startswith("GIT_CONFIG_"):
            environment.pop(name)
    environment["GIT_OPTIONAL_LOCKS"] = "0"
    try:
        result = subprocess.run(
            [
                "git", "--no-optional-locks",
                "-c", "core.fsmonitor=false",
                "-c", "core.hooksPath=/dev/null",
                *args,
            ],
            cwd=cwd,
            env=environment,
            text=True,
            capture_output=True,
            timeout=2,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 127, ""
    return result.returncode, result.stdout.strip()


def nearest_agents(start: Path) -> Path | None:
    for directory in (start, *start.parents):
        override = directory / "AGENTS.override.md"
        if override.is_file() and not override.is_symlink():
            return override
        candidate = directory / "AGENTS.md"
        if candidate.is_file() and not candidate.is_symlink():
            return candidate
    return None


def read_agents_bounded(path: Path) -> str | None:
    """Read one regular instruction file without following links or allocating without bound."""
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
    except OSError:
        return None
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_AGENTS_BYTES:
            return None
        chunks = bytearray()
        while len(chunks) <= MAX_AGENTS_BYTES:
            chunk = os.read(descriptor, min(65536, MAX_AGENTS_BYTES + 1 - len(chunks)))
            if not chunk:
                break
            chunks.extend(chunk)
        payload = bytes(chunks)
        if len(payload) > MAX_AGENTS_BYTES:
            return None
        return payload.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    finally:
        os.close(descriptor)


def inspect(path: Path) -> dict[str, Any]:
    resolved = path.expanduser().resolve()
    result: dict[str, Any] = {
        "contract": CONTRACT,
        "path_status": "directory" if resolved.is_dir() else "unavailable",
        "git": "unknown",
        "worktree": "unknown",
        "dirty": "unknown",
        "agents": "missing",
        "managed_contract": "unknown",
        "github_connector": "unknown",
        "scheduled_tasks": "unknown",
    }
    if not resolved.is_dir():
        return result

    rc, top = run_git(resolved, "rev-parse", "--show-toplevel")
    if rc == 0 and top:
        result["git"] = "available"
        top_path = Path(top).resolve()
        result["worktree"] = "repository-root" if top_path == resolved else "repository-subdirectory"
        status_rc, status = run_git(resolved, "status", "--porcelain")
        result["dirty"] = "yes" if status_rc == 0 and status else "no" if status_rc == 0 else "unknown"
    elif rc == 128:
        result["git"] = "not-a-repository"
        result["worktree"] = "not-applicable"
        result["dirty"] = "not-applicable"

    agents = nearest_agents(resolved)
    if agents is not None:
        result["agents"] = "available"
        text = read_agents_bounded(agents)
        if text is None:
            result["managed_contract"] = "unreadable"
        else:
            result["managed_contract"] = "current" if MARKER in text else "absent-or-drifted"
    return result


def summary(result: dict[str, Any]) -> str:
    return (
        "OpenBoa context: "
        f"git={result['git']}, worktree={result['worktree']}, dirty={result['dirty']}, "
        f"AGENTS.md={result['agents']}, contract={result['managed_contract']}. "
        "Live GitHub connector and scheduled-task availability are unknown until inspected in this task. "
        "Reconcile the durable Issue and live target before external writes."
    )


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    event: dict[str, Any] = {}
    if args.hook:
        try:
            event = json.load(sys.stdin)
        except (json.JSONDecodeError, OSError):
            event = {}
    raw_path = args.path or Path(str(event.get("cwd") or os.getcwd()))
    result = inspect(raw_path)
    message = summary(result)

    if args.hook:
        event_name = event.get("hook_event_name")
        if event_name == "SessionStart":
            payload = {
                "continue": True,
                "hookSpecificOutput": {
                    "hookEventName": "SessionStart",
                    "additionalContext": message,
                },
            }
            print(json.dumps(payload, sort_keys=True))
        elif event_name == "PostCompact" and result["managed_contract"] != "current":
            print(json.dumps({"continue": True, "systemMessage": message}, sort_keys=True))
        return 0

    if args.as_json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
