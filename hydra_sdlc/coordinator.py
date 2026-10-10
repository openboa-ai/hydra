"""One host, one supervisor. The lock is not workflow state or a distributed lease."""

from __future__ import annotations

import fcntl
import os
import re
import subprocess
from contextlib import contextmanager
from pathlib import Path


class HostBusy(RuntimeError):
    pass


@contextmanager
def coordinator_lock(path: Path):
    path = path.expanduser().absolute()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise HostBusy("Lock path must not be a symlink")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HostBusy("Another Hydra process owns this host lock") from exc
        yield
    finally:
        os.close(fd)


def residual_workers():
    """Do not adopt or terminate an unidentified earlier execution."""
    result = subprocess.run(["ps", "-axo", "pid=,args="], capture_output=True,
                            text=True, timeout=5, check=True)
    return [line.split(None, 1)[0] for line in result.stdout.splitlines()
            if re.search(r"hydra_sdlc/(?:(?:codex|execution_boundary)\.py\s+--(?:execution|capability)-worker"
                         r"|execution_boundary\.py\s+--owned-process-helper)(?:\s|$)", line)]
