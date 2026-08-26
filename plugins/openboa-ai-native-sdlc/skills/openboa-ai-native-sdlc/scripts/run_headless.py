#!/usr/bin/env python3
"""Run one bounded Codex job with an attributable local evidence record."""

from __future__ import annotations

import argparse
from contextlib import ExitStack
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from typing import IO, Sequence


JOB_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}")
SHUTDOWN_GRACE_SECONDS = 2


def absolute_dir(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("must be an absolute path")
    if path.is_symlink():
        raise argparse.ArgumentTypeError("must not be a symlink")
    resolved = path.resolve()
    if not resolved.is_dir():
        raise argparse.ArgumentTypeError("must be an existing directory")
    return resolved


def absolute_file(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("must be an absolute path")
    if path.is_symlink():
        raise argparse.ArgumentTypeError("must not be a symlink")
    resolved = path.resolve()
    if not resolved.is_file():
        raise argparse.ArgumentTypeError("must be a regular file")
    return resolved


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True, type=absolute_dir)
    parser.add_argument("--prompt", required=True, type=absolute_file)
    parser.add_argument("--state-dir", required=True, type=Path)
    parser.add_argument("--job", required=True)
    parser.add_argument("--sandbox", choices=("read-only", "workspace-write"), default="read-only")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--codex-bin", default="codex")
    args = parser.parse_args(argv)
    if not JOB_RE.fullmatch(args.job):
        parser.error("--job must match [A-Za-z0-9][A-Za-z0-9._-]{0,63}")
    if not args.state_dir.is_absolute():
        parser.error("--state-dir must be an absolute path")
    if not 1 <= args.timeout <= 86400:
        parser.error("--timeout must be between 1 and 86400 seconds")
    return args


def git(project: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=project, text=True, capture_output=True, timeout=5, check=False
    )
    if result.returncode != 0:
        raise ValueError(f"git {' '.join(args)} failed")
    return result.stdout.strip()


def isolated_worktree_git_dir(project: Path) -> Path:
    top = Path(git(project, "rev-parse", "--show-toplevel")).resolve()
    if top != project:
        raise ValueError("workspace-write project must be the Git worktree root")
    git_dir = Path(git(project, "rev-parse", "--git-dir"))
    common_dir = Path(git(project, "rev-parse", "--git-common-dir"))
    git_dir = (project / git_dir).resolve() if not git_dir.is_absolute() else git_dir.resolve()
    common_dir = (project / common_dir).resolve() if not common_dir.is_absolute() else common_dir.resolve()
    if git_dir == common_dir:
        raise ValueError("workspace-write requires an isolated Git worktree")
    return git_dir


def acquire_lock(handle: IO[str], message: str) -> bool:
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(message, file=sys.stderr)
        return False
    return True


def terminate_process_group(process: subprocess.Popen[str]) -> tuple[str, int]:
    process_group = process.pid
    try:
        os.killpg(process_group, signal.SIGTERM)
    except ProcessLookupError:
        pass

    # Do not use leader exit or pipe closure as evidence that the process group
    # is gone: a descendant can ignore SIGTERM and redirect every pipe. Keep the
    # worktree lock for the full grace period, then always attempt the group kill.
    time.sleep(SHUTDOWN_GRACE_SECONDS)
    try:
        os.killpg(process_group, signal.SIGKILL)
    except (ProcessLookupError, PermissionError):
        pass

    _, stderr = process.communicate()
    return stderr or "", 124


def timestamp() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def write_record(handle: IO[str], payload: dict[str, object]) -> None:
    handle.write(json.dumps(payload, sort_keys=True) + "\n")
    handle.flush()


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    state_dir = args.state_dir.resolve()
    try:
        state_dir.relative_to(args.project)
    except ValueError:
        pass
    else:
        print("state directory must be outside the project", file=sys.stderr)
        return 2
    if args.prompt.stat().st_size > 262144:
        print("prompt file exceeds 256 KiB", file=sys.stderr)
        return 2
    project_git_dir: Path | None = None
    if args.sandbox == "workspace-write":
        try:
            project_git_dir = isolated_worktree_git_dir(args.project)
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            print(str(exc), file=sys.stderr)
            return 2

    state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    if state_dir.is_symlink() or state_dir.stat().st_mode & 0o077:
        print("state directory must be private and must not be a symlink", file=sys.stderr)
        return 2
    lock_path = state_dir / f"{args.job}.lock"
    with ExitStack() as stack:
        job_lock = stack.enter_context(lock_path.open("a+", encoding="utf-8"))
        if not acquire_lock(job_lock, f"job is already running: {args.job}"):
            return 3

        if project_git_dir is not None:
            project_lock_path = project_git_dir / "openboa-workspace-write.lock"
            project_lock = stack.enter_context(project_lock_path.open("a+", encoding="utf-8"))
            if not acquire_lock(
                project_lock,
                f"workspace-write project is already running: {args.project}",
            ):
                return 3
            try:
                if git(args.project, "status", "--porcelain"):
                    raise ValueError("workspace-write project must be clean")
            except (OSError, subprocess.SubprocessError, ValueError) as exc:
                print(str(exc), file=sys.stderr)
                return 2

        run_id = f"{args.job}-{timestamp()}-{os.getpid()}"
        job_lock.seek(0)
        job_lock.truncate()
        job_lock.write(json.dumps({"pid": os.getpid(), "run_id": run_id}) + "\n")
        job_lock.flush()
        event_path = state_dir / f"{run_id}.jsonl"
        final_path = state_dir / f"{run_id}.final.md"
        prompt_text = args.prompt.read_text(encoding="utf-8")
        command = [
            args.codex_bin, "exec", "--ephemeral", "--json",
            "--ignore-user-config", "--disable", "hooks",
            "--sandbox", args.sandbox, "-C", str(args.project),
            "-c", 'approval_policy="never"',
            "--output-last-message", str(final_path), "-",
        ]
        with event_path.open("x", encoding="utf-8") as events:
            write_record(events, {
                "openboa_event": "run.started", "run_id": run_id,
                "project": str(args.project), "sandbox": args.sandbox,
                "timeout_seconds": args.timeout,
            })
            try:
                process = subprocess.Popen(
                    command, stdin=subprocess.PIPE, stdout=events, stderr=subprocess.PIPE,
                    text=True, cwd=args.project, start_new_session=True,
                )
                _, stderr = process.communicate(prompt_text, timeout=args.timeout)
                returncode = process.returncode
            except subprocess.TimeoutExpired:
                stderr, returncode = terminate_process_group(process)
            except OSError as exc:
                stderr = str(exc)
                returncode = 127
            write_record(events, {
                "openboa_event": "run.completed", "run_id": run_id,
                "returncode": returncode,
                "stderr_bytes": len(stderr.encode("utf-8", errors="replace")),
                "stderr_sha256": hashlib.sha256(stderr.encode("utf-8", errors="replace")).hexdigest(),
                "final_message": str(final_path) if final_path.exists() else None,
            })
        print(json.dumps({"run_id": run_id, "events": str(event_path), "final": str(final_path)}))
        return returncode


if __name__ == "__main__":
    raise SystemExit(main())
