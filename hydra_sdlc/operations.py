"""Local admission settings, independent of workflow and execution ownership.

The host configuration chooses the lock path. Project content must never do so.
Callers hold ``guard`` only around bounded effects, never a model turn or sleep.
Cleanup callers remain responsible for proving their exact execution ended.
"""

from __future__ import annotations

import asyncio
import errno
import fcntl
import json
import os
import re
import stat
import threading
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


MAX_SETTINGS_BYTES = 65536
MAX_PROJECTS = 1024
MAX_REVISION = 2**53 - 1
_MODES = frozenset({"running", "paused", "stopped"})
_ACTIONS = {"start": "running", "resume": "running", "pause": "paused", "stop": "stopped"}
_KEYS = {"version", "revision", "global_mode", "projects", "updated_at"}
_REPOSITORY = re.compile(r"[a-z0-9][a-z0-9-]{0,38}/[a-z0-9_.-]{1,100}\Z")
_TIMESTAMP = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{6}Z\Z")
_held_locks = ContextVar("hydra_operation_locks", default={})


class OperationDenied(RuntimeError):
    """A bounded public reason; underlying paths and diagnostics stay private."""

    def __init__(self, reason):
        self.reason = reason
        super().__init__(reason)


class OperationUncertain(OperationDenied):
    """Replacement may have happened; current state is not a request receipt."""

    def __init__(self, reason="operation_state_unknown", observation=None):
        self.observation = observation
        super().__init__(reason)


def _default():
    return {"version": 1, "revision": 0, "global_mode": "stopped", "projects": {}, "updated_at": None}


def _execution_owner():
    # ContextVars are inherited by newly created tasks. They must not grant that
    # other task use of an outer task's descriptor (possibly already closed).
    try:
        task = asyncio.current_task()
    except RuntimeError:
        task = None
    return os.getpid(), threading.get_ident(), task


def _repository(value):
    if not isinstance(value, str):
        raise OperationDenied("operation_state_repository_invalid")
    canonical = value.lower()
    if not _REPOSITORY.fullmatch(canonical) or canonical.split("/")[-1] in {".", ".."}:
        raise OperationDenied("operation_state_repository_invalid")
    return canonical


def _pairs(values):
    result = {}
    for key, value in values:
        if key in result:
            raise ValueError("Duplicate key")
        result[key] = value
    return result


def _invalid_constant(value):
    raise ValueError("Non-finite number")


def _validate(value):
    if not isinstance(value, dict) or set(value) != _KEYS:
        raise ValueError("Invalid keys")
    if type(value["version"]) is not int or value["version"] != 1:
        raise ValueError("Invalid version")
    revision = value["revision"]
    if type(revision) is not int or not 0 <= revision <= MAX_REVISION:
        raise ValueError("Invalid revision")
    if not isinstance(value["global_mode"], str) or value["global_mode"] not in _MODES:
        raise ValueError("Invalid mode")
    projects = value["projects"]
    if not isinstance(projects, dict) or len(projects) > MAX_PROJECTS:
        raise ValueError("Invalid projects")
    for repository, mode in projects.items():
        if _repository(repository) != repository or not isinstance(mode, str) or mode not in _MODES:
            raise ValueError("Invalid project")
    timestamp = value["updated_at"]
    if revision == 0:
        if value != _default():
            raise ValueError("Invalid initial timestamp")
    elif not isinstance(timestamp, str) or not _TIMESTAMP.fullmatch(timestamp):
        raise ValueError("Invalid timestamp")
    else:
        datetime.strptime(timestamp, "%Y-%m-%dT%H:%M:%S.%fZ")
    return value


def _fingerprint(info):
    return (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _safe_file(info):
    if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid()
            or info.st_nlink != 1 or stat.S_IMODE(info.st_mode) != 0o600):
        raise OperationDenied("operation_state_unsafe")


def _io_reason(exc):
    return "operation_state_unsafe" if exc.errno in {errno.ELOOP, errno.ENOTDIR} else "operation_state_unavailable"


@dataclass
class _WriteAttempt:
    replacement_started: bool = False


@dataclass(frozen=True)
class _Held:
    parent: int
    lock: int
    owner: tuple


class OperatingControl:
    """One trusted host lock path produces one settings file and control lock.

    Construction performs no I/O. An empty allowlist permits host controls only.
    Removed repositories' valid overrides remain stored but cannot be targeted.
    ``snapshot`` and ``reason`` never create directories, files, or repair data.
    """

    def __init__(self, lock_path, repos=()):
        try:
            path = Path(lock_path).expanduser().absolute()
        except (TypeError, ValueError, RuntimeError) as exc:
            raise OperationDenied("operation_state_path_invalid") from exc
        if not path.name or ".." in path.parts or "\x00" in str(path):
            raise OperationDenied("operation_state_path_invalid")
        if isinstance(repos, (str, bytes)):
            raise OperationDenied("operation_state_repository_invalid")
        try:
            self.repos = frozenset(_repository(repo) for repo in repos)
        except TypeError as exc:
            raise OperationDenied("operation_state_repository_invalid") from exc
        if len(self.repos) > MAX_PROJECTS:
            raise OperationDenied("operation_state_repository_invalid")
        self.settings_path = path.with_name(path.name + ".operations.json")
        self.control_lock_path = path.with_name(path.name + ".operations.lock")
        self._key = str(self.control_lock_path)

    def _target(self, repository):
        if repository is None:
            return None
        repository = _repository(repository)
        if repository not in self.repos:
            raise OperationDenied("operation_state_repository_unregistered")
        return repository

    @contextmanager
    def _parent(self, *, create):
        """Walk no-follow directory descriptors, including every ancestor."""
        fd = os.open("/", os.O_RDONLY | os.O_DIRECTORY | os.O_CLOEXEC)
        try:
            parts = self.settings_path.parent.parts[1:]
            if not parts:
                raise OperationDenied("operation_state_unsafe")
            for index, part in enumerate(parts):
                try:
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                except FileNotFoundError:
                    if not create:
                        yield None
                        return
                    try:
                        os.mkdir(part, 0o700, dir_fd=fd)
                        os.fsync(fd)
                    except FileExistsError:
                        pass
                    child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fd)
                os.close(fd)
                fd = child
                info = os.fstat(fd)
                mode = stat.S_IMODE(info.st_mode)
                final = index == len(parts) - 1
                sticky_root = info.st_uid == 0 and bool(mode & stat.S_ISVTX) and not final
                if (info.st_uid not in {0, os.geteuid()} or (final and info.st_uid != os.geteuid())
                        or ((mode & 0o022) and not sticky_root)):
                    raise OperationDenied("operation_state_unsafe")
            yield fd
        finally:
            os.close(fd)

    def _check_lock(self, held):
        info = os.fstat(held.lock)
        _safe_file(info)
        if info.st_size:
            raise OperationDenied("operation_state_unsafe")
        visible = os.stat(self.control_lock_path.name, dir_fd=held.parent, follow_symlinks=False)
        if _fingerprint(info) != _fingerprint(visible):
            raise OperationDenied("operation_state_unsafe")
        with self._parent(create=False) as current:
            if current is None or ((os.fstat(current).st_dev, os.fstat(current).st_ino)
                    != (os.fstat(held.parent).st_dev, os.fstat(held.parent).st_ino)):
                raise OperationDenied("operation_state_unsafe")

    @contextmanager
    def _locked(self, *, exclusive, create, blocking=True):
        owner = _execution_owner()
        existing = _held_locks.get().get(self._key)
        caller_failed = False
        try:
            if existing is not None and existing.owner == owner:
                if exclusive:
                    raise OperationDenied("operation_state_busy")
                self._check_lock(existing)
                try:
                    yield existing
                except BaseException:
                    caller_failed = True
                    raise
                self._check_lock(existing)
                return
            with self._parent(create=create) as parent:
                if parent is None:
                    try:
                        yield None
                    except BaseException:
                        caller_failed = True
                        raise
                    return
                flags = os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC
                lock_created = False
                try:
                    fd = os.open(self.control_lock_path.name, flags, 0o600, dir_fd=parent)
                except FileNotFoundError:
                    try:
                        os.stat(self.settings_path.name, dir_fd=parent, follow_symlinks=False)
                    except FileNotFoundError:
                        if not create:
                            try:
                                yield None
                            except BaseException:
                                caller_failed = True
                                raise
                            return
                    else:
                        # A settings file without its original lock is not a
                        # fresh installation. Recreating it could admit work
                        # alongside an older holder of the removed inode.
                        raise OperationDenied("operation_state_unsafe")
                    try:
                        fd = os.open(self.control_lock_path.name, flags | os.O_CREAT | os.O_EXCL,
                                     0o600, dir_fd=parent)
                        lock_created = True
                    except FileExistsError:
                        # Another initializer won the race. Join its lock;
                        # never replace it or write an independent default.
                        fd = os.open(self.control_lock_path.name, flags, 0o600, dir_fd=parent)
                try:
                    if lock_created:
                        os.fsync(parent)
                    _safe_file(os.fstat(fd))
                    lock_mode = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
                    # An async caller must never block its event loop waiting
                    # for an effect that needs that same loop to finish. CLI
                    # controls can wait for the bounded admitted effect; async
                    # callers and explicitly nonblocking typed commands get
                    # a hold instead of retaining a checked grant while queued.
                    if not blocking or owner[2] is not None:
                        lock_mode |= fcntl.LOCK_NB
                    try:
                        fcntl.flock(fd, lock_mode)
                    except BlockingIOError as exc:
                        raise OperationDenied("operation_state_busy") from exc
                    held = _Held(parent, fd, owner)
                    self._check_lock(held)
                    token = _held_locks.set({**_held_locks.get(), self._key: held})
                    try:
                        try:
                            yield held
                        except BaseException:
                            caller_failed = True
                            raise
                        self._check_lock(held)
                    finally:
                        _held_locks.reset(token)
                finally:
                    os.close(fd)
        except OSError as exc:
            if caller_failed:
                raise
            raise OperationDenied(_io_reason(exc)) from exc

    def _read(self, held):
        try:
            return self._read_locked(held)
        except OSError as exc:
            raise OperationDenied(_io_reason(exc)) from exc

    def _read_locked(self, held):
        if held is None:
            return _default(), None
        try:
            fd = os.open(self.settings_path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                         dir_fd=held.parent)
        except FileNotFoundError:
            return _default(), None
        try:
            info = os.fstat(fd)
            _safe_file(info)
            if info.st_size > MAX_SETTINGS_BYTES:
                raise OperationDenied("operation_state_invalid")
            chunks, size = [], 0
            while size <= MAX_SETTINGS_BYTES:
                chunk = os.read(fd, min(8192, MAX_SETTINGS_BYTES + 1 - size))
                if not chunk:
                    break
                chunks.append(chunk)
                size += len(chunk)
            if size > MAX_SETTINGS_BYTES:
                raise OperationDenied("operation_state_invalid")
            observed = os.stat(self.settings_path.name, dir_fd=held.parent, follow_symlinks=False)
            if _fingerprint(info) != _fingerprint(os.fstat(fd)) or _fingerprint(info) != _fingerprint(observed):
                raise OperationDenied("operation_state_unsafe")
            try:
                value = json.loads(b"".join(chunks).decode("utf-8"), object_pairs_hook=_pairs,
                                   parse_constant=_invalid_constant)
                return _validate(value), _fingerprint(info)
            except (ValueError, UnicodeError, RecursionError, OperationDenied) as exc:
                raise OperationDenied("operation_state_invalid") from exc
        finally:
            os.close(fd)

    def snapshot(self, *, blocking=True):
        if type(blocking) is not bool:
            raise OperationDenied("invalid_command")
        with self._locked(exclusive=False, create=False, blocking=blocking) as held:
            return self._read(held)[0]

    @staticmethod
    def _reason(snapshot, repository):
        mode = snapshot["global_mode"]
        if mode != "running":
            return "host_" + mode
        mode = snapshot["projects"].get(repository, "running") if repository is not None else "running"
        return None if mode == "running" else "project_" + mode

    def reason(self, repo=None):
        try:
            return self._reason(self.snapshot(), self._target(repo))
        except OperationDenied as exc:
            return exc.reason

    def interruption_reason(self, repo=None):
        """Observe whether admitted work must stop, without treating a writer
        holding the control lock as a completed mode change.

        Contention is retried by the existing supervision poll. All other
        invalid or unavailable states still interrupt. New admission and every
        effect must continue to use ``reason`` and ``guard``, which deny busy.
        """
        reason = self.reason(repo)
        return None if reason == "operation_state_busy" else reason

    @contextmanager
    def guard(self, repo=None, *, cleanup=False):
        """Gate one bounded effect; async lock contention denies without waiting.

        A bounded async admission may use this context manager, but callers must
        never extend it through execution, verification, or polling. Cleanup is
        a mode exception only: the caller must prove its exact cleanup authority.
        """
        repository = self._target(repo)
        if type(cleanup) is not bool:
            raise OperationDenied("operation_state_cleanup_invalid")
        with self._locked(exclusive=False, create=True) as held:
            snapshot = self._read(held)[0]
            reason = self._reason(snapshot, repository)
            if reason is not None and not cleanup:
                raise OperationDenied(reason)
            yield snapshot

    def set_mode(self, action, repository=None):
        try:
            return self._set_mode(action, repository)
        except OSError as exc:
            raise OperationDenied(_io_reason(exc)) from exc

    def set_mode_if_current(self, action, repository=None, *, expected_revision, blocking=True):
        """Separate optimistic-concurrency entry; callers retain authority checks."""
        if expected_revision is None:
            raise OperationDenied("precondition_required")
        if type(expected_revision) is not int or not 0 <= expected_revision <= MAX_REVISION:
            raise OperationDenied("invalid_command")
        if type(blocking) is not bool:
            raise OperationDenied("invalid_command")
        try:
            return self._set_mode(action, repository, expected_revision=expected_revision, blocking=blocking)
        except OperationUncertain as exc:
            # One bounded read, not a mutation retry or reconstructed receipt.
            try:
                observation = self.snapshot() if blocking else self.snapshot(blocking=False)
            except (OperationDenied, OSError):
                observation = None
            raise OperationUncertain(observation=observation) from exc
        except OSError as exc:
            raise OperationDenied(_io_reason(exc)) from exc

    def _set_mode(self, action, repository, *, expected_revision=None, blocking=True):
        repository = self._target(repository)
        if not isinstance(action, str) or action not in _ACTIONS:
            raise OperationDenied("operation_state_action_invalid")
        attempt = _WriteAttempt()
        try:
            with self._locked(exclusive=True, create=True, blocking=blocking) as held:
                snapshot, before = self._read(held)
                mode = _ACTIONS[action]
                if expected_revision is not None and snapshot["revision"] != expected_revision:
                    raise OperationDenied("stale_revision")
                if repository is not None and mode == "running" and snapshot["global_mode"] != "running":
                    raise OperationDenied("host_" + snapshot["global_mode"])
                if expected_revision is not None:
                    stored = snapshot["global_mode"] if repository is None else snapshot["projects"].get(repository, "running")
                    if stored == mode or (stored == "stopped" and mode == "paused"):
                        return snapshot
                if snapshot["revision"] == MAX_REVISION:
                    raise OperationDenied("operation_state_revision_exhausted")
                if repository is None:
                    snapshot["global_mode"] = mode
                else:
                    snapshot["projects"][repository] = mode
                snapshot["revision"] += 1
                snapshot["updated_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
                return self._write_snapshot(snapshot, before, held, attempt)
        except (OSError, OperationDenied) as exc:
            # The transaction also includes lock/parent verification and descriptor
            # cleanup on context exit, after _write_snapshot has returned.
            if expected_revision is not None and attempt.replacement_started:
                raise OperationUncertain() from exc
            raise

    def _write_snapshot(self, snapshot, before, held, attempt):
        try:
            _validate(snapshot)
            payload = (json.dumps(snapshot, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
            if len(payload) > MAX_SETTINGS_BYTES:
                raise ValueError("Settings too large")
        except (ValueError, OperationDenied) as exc:
            raise OperationDenied("operation_state_invalid") from exc
        temporary = "." + self.settings_path.name + "." + uuid.uuid4().hex + ".tmp"
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC,
                     0o600, dir_fd=held.parent)
        try:
            offset = 0
            while offset < len(payload):
                count = os.write(fd, payload[offset:])
                if count <= 0:
                    raise OperationDenied("operation_state_unavailable")
                offset += count
            os.fsync(fd)
            _safe_file(os.fstat(fd))
            if self._read(held)[1] != before:
                raise OperationDenied("operation_state_changed")
            self._check_lock(held)
            attempt.replacement_started = True
            os.replace(temporary, self.settings_path.name, src_dir_fd=held.parent, dst_dir_fd=held.parent)
            os.fsync(held.parent)
            observed = self._read(held)[0]
            if observed != snapshot:
                raise OperationDenied("operation_state_changed")
            return observed
        finally:
            os.close(fd)
            try:
                os.unlink(temporary, dir_fd=held.parent)
            except FileNotFoundError:
                pass
