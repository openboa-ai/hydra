"""One host, one supervisor. The lock is not workflow state or a distributed lease."""

from __future__ import annotations

import fcntl
import os
import re
import stat
import subprocess
import sys
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path


class HostBusy(RuntimeError):
    pass


_OWNER_PREFIX = b"hydra-owner-v1\n"
_OWNER_LIMIT = len(_OWNER_PREFIX) + 74
_current_owner = ContextVar("hydra_host_owner", default=None)


def _boot_identity():
    try:
        if sys.platform.startswith("linux"):
            with open("/proc/sys/kernel/random/boot_id", "rb") as source:
                value = source.read(128)
        elif sys.platform == "darwin":
            value = subprocess.run(
                ["/usr/sbin/sysctl", "-n", "kern.bootsessionuuid"], capture_output=True,
                timeout=5, check=True,
            ).stdout
        else:
            raise HostBusy("Native boot identity unavailable")
        text = value.decode("ascii").strip().lower()
        if len(value) > 128 or str(uuid.UUID(text)) != text:
            raise ValueError("Invalid boot identity")
        return text
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise HostBusy("Native boot identity unavailable") from exc


def _read_owner(fd):
    value = os.pread(fd, _OWNER_LIMIT + 1, 0)
    if not value:
        return None
    if len(value) != _OWNER_LIMIT or not value.startswith(_OWNER_PREFIX):
        raise HostBusy("Unrecognized host ownership")
    try:
        boot, nonce, empty = value[len(_OWNER_PREFIX):].decode("ascii").split("\n")
        if empty or any(str(uuid.UUID(part)) != part for part in (boot, nonce)):
            raise ValueError("Invalid ownership identity")
    except (ValueError, UnicodeError) as exc:
        raise HostBusy("Unrecognized host ownership") from exc
    return boot, nonce


def _clear_owner(fd, previous):
    value = _OWNER_PREFIX + (previous[0] + "\n" + previous[1] + "\n").encode("ascii")
    try:
        os.ftruncate(fd, 0)
        os.fsync(fd)
    except OSError:
        # Keep uncertainty visible when retirement itself fails. No substitute
        # file or replacement inode may take over this descriptor's flock.
        try:
            if os.pwrite(fd, value, 0) == len(value):
                os.ftruncate(fd, len(value))
                os.fsync(fd)
        except OSError:
            pass
        raise


class _HostOwner:
    def __init__(self, fd, boot):
        self.fd, self.boot, self.ticket = fd, boot, None

    def register(self):
        if self.fd is None or self.ticket is not None or _read_owner(self.fd) is not None:
            raise HostBusy("An owned execution remains unresolved")
        ticket = (self, str(uuid.uuid4()))
        value = _OWNER_PREFIX + (self.boot + "\n" + ticket[1] + "\n").encode("ascii")
        # Preserve the flock-held inode. A failed/partial write never permits a
        # spawn, and malformed bytes cannot be mistaken for an idle owner.
        if os.pwrite(self.fd, value, 0) != len(value):
            raise HostBusy("Host ownership write was incomplete")
        os.ftruncate(self.fd, len(value))
        os.fsync(self.fd)
        self.ticket = ticket
        return ticket

    def confirm(self, ticket):
        if (self.fd is None or ticket is not self.ticket or
                _read_owner(self.fd) != (self.boot, ticket[1])):
            raise HostBusy("Host ownership no longer matches")
        _clear_owner(self.fd, (self.boot, ticket[1]))
        self.ticket = None


def register_owned_process():
    """Register in the active CLI lock; standalone adapter calls keep their API."""
    owner = _current_owner.get()
    return None if owner is None else owner.register()


def confirm_owned_cleanup(ticket):
    """Only a live handle with confirmed cleanup may retire its own nonce."""
    if ticket is not None:
        ticket[0].confirm(ticket)


@contextmanager
def coordinator_lock(path: Path):
    path = path.expanduser().absolute()
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise HostBusy("Lock path must not be a symlink")
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0) | os.O_NONBLOCK, 0o600)
    owner = token = None
    try:
        observed = os.fstat(fd)
        if not stat.S_ISREG(observed.st_mode) or observed.st_uid != os.geteuid() or observed.st_nlink != 1:
            raise HostBusy("Lock must be an owned regular file")
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise HostBusy("Another Hydra process owns this host lock") from exc
        boot = _boot_identity()
        previous = _read_owner(fd)
        if previous is not None:
            if previous[0] == boot:
                raise HostBusy("An earlier owned execution remains unresolved")
            # Only a verified new boot proves every prior host process is gone.
            _clear_owner(fd, previous)
        owner = _HostOwner(fd, boot)
        token = _current_owner.set(owner)
        yield
    finally:
        if token is not None:
            _current_owner.reset(token)
        if owner is not None:
            owner.fd = None
        os.close(fd)


def residual_workers():
    """Do not adopt or terminate an unidentified earlier execution."""
    result = subprocess.run(["ps", "-axo", "pid=,args="], capture_output=True,
                            text=True, timeout=5, check=True)
    return [line.split(None, 1)[0] for line in result.stdout.splitlines()
            if re.search(r"hydra_sdlc/(?:(?:codex|execution_boundary)\.py\s+--(?:execution|capability)-worker"
                         r"|execution_boundary\.py\s+--owned-process-helper)(?:\s|$)", line)]
