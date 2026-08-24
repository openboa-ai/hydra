#!/usr/bin/env python3
"""Safely check or synchronize one OpenBoa managed AGENTS.md block.

The default mode is read-only. Pass ``--write`` to install the current block or
to migrate one recognized ``openboa-operations`` block. Repository/workspace
local instructions are preserved byte-for-byte. Writes use a bound directory,
cooperative file locks, and an atomic exchange that retains the pre-exchange
inode as a recovery file. Unsupported safety or metadata surfaces fail closed
instead of silently degrading.
"""

from __future__ import annotations

import argparse
import ctypes
import dataclasses
import errno
import os
from pathlib import Path
import re
import secrets
import stat
import sys
from typing import Sequence

try:
    import fcntl
except ImportError:  # pragma: no cover - exercised on unsupported hosts
    fcntl = None  # type: ignore[assignment]


CURRENT_NAMESPACE = "openboa-ai-native-sdlc"
LEGACY_NAMESPACE = "openboa-operations"
LEGACY_SUPPORTED_MAJOR = 0
MAX_VERSION_DIGITS = 9

EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_REFUSED = 2
EXIT_ERROR = 3

DEFAULT_TEMPLATE = (
    Path(__file__).resolve().parent.parent / "assets" / "managed-AGENTS.md"
)

LOCAL_HEADING_RE = re.compile(
    r"(?m)^## (?:Repository|Workspace)-local instructions[ \t]*$"
)
FENCE_RE = re.compile(r"^( {0,3})(`{3,}|~{3,})([^\n]*)$")


class SyncRefused(Exception):
    """The target cannot be changed without risking local instructions."""


class TemplateError(Exception):
    """The packaged managed-block template is invalid or unavailable."""


@dataclasses.dataclass(frozen=True)
class ManagedBlock:
    start: int
    end: int
    version: tuple[int, int, int]


@dataclasses.dataclass(frozen=True)
class ResolvedTarget:
    path: Path
    parent_device: int
    parent_inode: int


@dataclasses.dataclass(frozen=True)
class Snapshot:
    data: bytes
    device: int
    inode: int
    mode: int
    uid: int
    gid: int
    links: int
    size: int
    mtime_ns: int
    ctime_ns: int
    flags: int


@dataclasses.dataclass(frozen=True)
class SyncResult:
    target: Path
    changed: bool
    action: str
    wrote: bool
    recovery: Path | None


def _marker_patterns(namespace: str) -> tuple[re.Pattern[str], re.Pattern[str]]:
    escaped = re.escape(namespace)
    component = rf"([0-9]{{1,{MAX_VERSION_DIGITS}}})"
    start = re.compile(
        rf"(?m)^<!-- {escaped}:managed:start "
        rf"contract={component}\.{component}\.{component} -->[ \t]*$"
    )
    end = re.compile(rf"(?m)^<!-- {escaped}:managed:end -->[ \t]*$")
    return start, end


def _fenced_ranges(text: str) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    opened_at: int | None = None
    fence_char = ""
    fence_length = 0
    offset = 0
    for line in text.splitlines(keepends=True):
        content = line.rstrip("\n")
        match = FENCE_RE.match(content)
        if match:
            token = match.group(2)
            suffix = match.group(3)
            if opened_at is None:
                opened_at = offset
                fence_char = token[0]
                fence_length = len(token)
            elif (
                token[0] == fence_char
                and len(token) >= fence_length
                and not suffix.strip(" \t")
            ):
                ranges.append((opened_at, offset + len(line)))
                opened_at = None
                fence_char = ""
                fence_length = 0
        offset += len(line)
    if opened_at is not None:
        ranges.append((opened_at, len(text)))
    return ranges


def _inside_html_comment(text: str, position: int) -> bool:
    cursor = 0
    inside = False
    while cursor < position:
        if inside:
            closing = text.find("-->", cursor, position)
            if closing < 0:
                return True
            inside = False
            cursor = closing + 3
        else:
            opening = text.find("<!--", cursor, position)
            if opening < 0:
                return False
            inside = True
            cursor = opening + 4
    return inside


def _inactive_reason(
    text: str, position: int, fenced: list[tuple[int, int]]
) -> str | None:
    if any(start <= position < end for start, end in fenced):
        return "fenced code"
    if _inside_html_comment(text, position):
        return "an enclosing HTML comment"
    return None


def _scan_namespace(text: str, namespace: str) -> ManagedBlock | None:
    start_re, end_re = _marker_patterns(namespace)
    starts = list(start_re.finditer(text))
    ends = list(end_re.finditer(text))
    hint_count = text.count(f"{namespace}:managed:")

    if hint_count != len(starts) + len(ends):
        raise SyncRefused(f"malformed {namespace} managed marker")
    if len(starts) > 1 or len(ends) > 1:
        raise SyncRefused(f"duplicate {namespace} managed markers")
    if bool(starts) != bool(ends):
        raise SyncRefused(f"incomplete {namespace} managed block")
    if not starts:
        return None

    fenced = _fenced_ranges(text)
    for match in (*starts, *ends):
        reason = _inactive_reason(text, match.start(), fenced)
        if reason:
            raise SyncRefused(
                f"{namespace} managed marker appears inside {reason}"
            )

    start_match = starts[0]
    end_match = ends[0]
    if end_match.start() < start_match.end():
        raise SyncRefused(f"misordered {namespace} managed markers")

    try:
        version = tuple(int(part) for part in start_match.groups())
    except ValueError as exc:
        raise SyncRefused(f"malformed {namespace} contract version") from exc
    return ManagedBlock(start_match.start(), end_match.end(), version)


def _normalize(data: bytes, *, source: str) -> tuple[str, bytes]:
    if b"\x00" in data:
        raise SyncRefused(f"{source} contains a NUL byte")

    has_crlf = b"\r\n" in data
    without_crlf = data.replace(b"\r\n", b"")
    if has_crlf and b"\n" in without_crlf:
        raise SyncRefused(f"{source} mixes LF and CRLF line endings")
    if b"\r" in without_crlf:
        raise SyncRefused(f"{source} contains unsupported bare CR line endings")

    newline = b"\r\n" if has_crlf else b"\n"
    normalized = data.replace(b"\r\n", b"\n")
    try:
        return normalized.decode("utf-8"), newline
    except UnicodeDecodeError as exc:
        raise SyncRefused(f"{source} is not valid UTF-8") from exc


def _denormalize(text: str, newline: bytes) -> bytes:
    encoded = text.encode("utf-8")
    if newline == b"\r\n":
        return encoded.replace(b"\n", b"\r\n")
    return encoded


def _load_template(template_path: Path) -> tuple[str, tuple[int, int, int]]:
    try:
        data = template_path.read_bytes()
    except OSError as exc:
        raise TemplateError(f"cannot read managed block template: {exc}") from exc

    try:
        text, _ = _normalize(data, source="managed block template")
        if f"{LEGACY_NAMESPACE}:managed:" in text:
            raise SyncRefused("template contains a legacy managed marker")
        block = _scan_namespace(text, CURRENT_NAMESPACE)
        if block is None:
            raise SyncRefused("template has no current managed block")
        if LOCAL_HEADING_RE.search(text[block.start : block.end]):
            raise SyncRefused("template managed block contains a local heading")
    except SyncRefused as exc:
        raise TemplateError(str(exc)) from exc

    return text[block.start : block.end], block.version


def _override_exists(parent: Path) -> bool:
    return os.path.lexists(parent / "AGENTS.override.md")


def resolve_target(
    target_arg: str | os.PathLike[str],
) -> ResolvedTarget:
    """Resolve one regular AGENTS.md and bind its expected parent identity."""

    requested = Path(os.path.abspath(os.path.expanduser(os.fspath(target_arg))))
    try:
        requested_stat = os.lstat(requested)
    except OSError as exc:
        raise SyncRefused(f"target does not exist: {requested}") from exc

    if stat.S_ISLNK(requested_stat.st_mode):
        raise SyncRefused(f"symlink target is not allowed: {requested}")

    if stat.S_ISDIR(requested_stat.st_mode):
        target = requested / "AGENTS.md"
        parent = requested
        parent_stat = requested_stat
    else:
        target = requested
        parent = target.parent
        if target.name != "AGENTS.md":
            raise SyncRefused(f"target file must be named AGENTS.md: {target}")
        try:
            parent_stat = os.lstat(parent)
        except OSError as exc:
            raise SyncRefused(f"cannot inspect target directory: {parent}") from exc
        if not stat.S_ISDIR(parent_stat.st_mode) or stat.S_ISLNK(parent_stat.st_mode):
            raise SyncRefused(f"target directory must be a real directory: {parent}")

    canonical_parent = Path(os.path.realpath(parent))
    if canonical_parent != parent:
        raise SyncRefused(
            f"target path contains a symlinked ancestor; use the canonical path: "
            f"{canonical_parent / target.name}"
        )

    if _override_exists(parent):
        raise SyncRefused(
            f"AGENTS.override.md takes precedence in target directory: {parent}"
        )

    try:
        target_stat = os.lstat(target)
    except OSError as exc:
        raise SyncRefused(f"target AGENTS.md does not exist: {target}") from exc
    if stat.S_ISLNK(target_stat.st_mode):
        resolved = Path(os.path.realpath(target))
        try:
            resolved.relative_to(canonical_parent)
        except ValueError:
            raise SyncRefused(
                f"AGENTS.md resolves outside target directory: {target}"
            ) from None
        raise SyncRefused(f"symlink target is not allowed: {target}")
    if not stat.S_ISREG(target_stat.st_mode):
        raise SyncRefused(f"target is not a regular file: {target}")

    return ResolvedTarget(
        path=target,
        parent_device=parent_stat.st_dev,
        parent_inode=parent_stat.st_ino,
    )


def _require_safe_host() -> None:
    missing: list[str] = []
    for name in ("O_DIRECTORY", "O_NOFOLLOW"):
        if not hasattr(os, name):
            missing.append(name)
    if fcntl is None:
        missing.append("flock")
    if os.open not in os.supports_dir_fd or os.stat not in os.supports_dir_fd:
        missing.append("dir_fd")
    if os.stat not in os.supports_follow_symlinks:
        missing.append("nofollow stat")
    if missing:
        raise SyncRefused(
            "host cannot guarantee safe AGENTS.md synchronization: "
            + ", ".join(sorted(set(missing)))
        )


def _assert_parent_binding(resolved: ResolvedTarget, parent_fd: int) -> None:
    info = os.fstat(parent_fd)
    if (info.st_dev, info.st_ino) != (
        resolved.parent_device,
        resolved.parent_inode,
    ):
        raise SyncRefused(f"target directory changed before binding: {resolved.path.parent}")
    try:
        live = os.lstat(resolved.path.parent)
    except OSError as exc:
        raise SyncRefused(
            f"target directory path changed during synchronization: {resolved.path.parent}"
        ) from exc
    if stat.S_ISLNK(live.st_mode) or (live.st_dev, live.st_ino) != (
        resolved.parent_device,
        resolved.parent_inode,
    ):
        raise SyncRefused(
            f"target directory path changed during synchronization: {resolved.path.parent}"
        )


def _open_parent(resolved: ResolvedTarget) -> int:
    _require_safe_host()
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        parent_fd = os.open(resolved.path.parent, flags)
    except OSError as exc:
        raise SyncRefused(
            f"cannot safely bind target directory: {resolved.path.parent}: {exc}"
        ) from exc
    try:
        _assert_parent_binding(resolved, parent_fd)
    except Exception:
        os.close(parent_fd)
        raise
    return parent_fd


def _override_exists_at(parent_fd: int) -> bool:
    try:
        os.stat("AGENTS.override.md", dir_fd=parent_fd, follow_symlinks=False)
    except FileNotFoundError:
        return False
    except OSError as exc:
        raise SyncRefused(f"cannot inspect AGENTS.override.md: {exc}") from exc
    return True


def _lock(fd: int, *, exclusive: bool) -> None:
    assert fcntl is not None
    operation = fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH
    try:
        fcntl.flock(fd, operation | fcntl.LOCK_NB)
    except OSError as exc:
        if exc.errno in (errno.EACCES, errno.EAGAIN):
            raise SyncRefused("target is locked by another synchronization") from exc
        raise SyncRefused(f"cannot lock target safely: {exc}") from exc


def _open_target_at(parent_fd: int, *, write: bool) -> int:
    flags = (os.O_RDWR if write else os.O_RDONLY) | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    try:
        fd = os.open("AGENTS.md", flags, dir_fd=parent_fd)
    except OSError as exc:
        raise SyncRefused(f"cannot safely open target AGENTS.md: {exc}") from exc
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise SyncRefused("target AGENTS.md is not a regular file")
        named = os.stat("AGENTS.md", dir_fd=parent_fd, follow_symlinks=False)
        if not stat.S_ISREG(named.st_mode) or (named.st_dev, named.st_ino) != (
            info.st_dev,
            info.st_ino,
        ):
            raise SyncRefused("target AGENTS.md changed while it was opened")
        _lock(fd, exclusive=write)
    except Exception:
        os.close(fd)
        raise
    return fd


def _snapshot_info(info: os.stat_result, data: bytes) -> Snapshot:
    return Snapshot(
        data=data,
        device=info.st_dev,
        inode=info.st_ino,
        mode=stat.S_IMODE(info.st_mode),
        uid=info.st_uid,
        gid=info.st_gid,
        links=info.st_nlink,
        size=info.st_size,
        mtime_ns=info.st_mtime_ns,
        ctime_ns=info.st_ctime_ns,
        flags=getattr(info, "st_flags", 0),
    )


def _read_snapshot_fd(fd: int) -> Snapshot:
    before = os.fstat(fd)
    if not stat.S_ISREG(before.st_mode):
        raise SyncRefused("target is not a regular file")
    os.lseek(fd, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    while True:
        chunk = os.read(fd, 1024 * 1024)
        if not chunk:
            break
        chunks.append(chunk)
    data = b"".join(chunks)
    after = os.fstat(fd)
    before_snapshot = _snapshot_info(before, data)
    after_snapshot = _snapshot_info(after, data)
    if before_snapshot != after_snapshot or len(data) != after.st_size:
        raise SyncRefused("target changed while it was being read")
    return after_snapshot


def _same_snapshot(left: Snapshot, right: Snapshot) -> bool:
    return left == right


def _same_exchanged_snapshot(left: Snapshot, right: Snapshot) -> bool:
    """Compare an inode across rename/exchange, which legitimately changes ctime."""

    return dataclasses.replace(left, ctime_ns=right.ctime_ns) == right


def _name_matches(parent_fd: int, name: str, snapshot: Snapshot) -> bool:
    try:
        info = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
    except OSError:
        return False
    return stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == (
        snapshot.device,
        snapshot.inode,
    )


def _darwin_metadata_issue(fd: int) -> str | None:
    libc = ctypes.CDLL(None, use_errno=True)
    try:
        flistxattr = libc.flistxattr
        flistxattr.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_int]
        flistxattr.restype = ctypes.c_ssize_t
        ctypes.set_errno(0)
        size = flistxattr(fd, None, 0, 0)
        if size < 0:
            return f"cannot verify extended attributes (errno {ctypes.get_errno()})"
        if size:
            return "target has extended attributes"

        acl_get_fd = libc.acl_get_fd
        acl_get_fd.argtypes = [ctypes.c_int]
        acl_get_fd.restype = ctypes.c_void_p
        acl_free = libc.acl_free
        acl_free.argtypes = [ctypes.c_void_p]
        acl_free.restype = ctypes.c_int
        ctypes.set_errno(0)
        acl = acl_get_fd(fd)
        if acl:
            acl_free(acl)
            return "target has an extended ACL"
        acl_errno = ctypes.get_errno()
        if acl_errno not in (0, errno.ENOENT):
            return f"cannot verify target ACL (errno {acl_errno})"
    except AttributeError:
        return "host cannot verify extended attributes and ACLs"
    return None


def _metadata_issue(fd: int, snapshot: Snapshot) -> str | None:
    if snapshot.links != 1:
        return "target has multiple hard links"
    if snapshot.flags:
        return "target has non-default file flags"
    if sys.platform == "darwin":
        return _darwin_metadata_issue(fd)
    if sys.platform.startswith("linux"):
        listxattr = getattr(os, "listxattr", None)
        if listxattr is None:
            return "host cannot verify extended attributes and ACLs"
        try:
            attributes = listxattr(fd)
        except (OSError, TypeError) as exc:
            return f"cannot verify extended attributes and ACLs: {exc}"
        if attributes:
            return "target has extended attributes or an ACL"
        return None
    return "host cannot verify extended attributes and ACLs"


def _write_all(fd: int, data: bytes) -> None:
    os.lseek(fd, 0, os.SEEK_SET)
    view = memoryview(data)
    written = 0
    while written < len(view):
        count = os.write(fd, view[written:])
        if count <= 0:
            raise OSError("short write while preparing replacement")
        written += count
    os.ftruncate(fd, len(data))
    os.fsync(fd)


def _fsync_directory(parent_fd: int) -> None:
    try:
        os.fsync(parent_fd)
    except OSError as exc:
        raise SyncRefused(
            f"host cannot durably synchronize the target directory: {exc}"
        ) from exc


def _atomic_exchange(parent_fd: int, left: str, right: str) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    left_bytes = os.fsencode(left)
    right_bytes = os.fsencode(right)
    if sys.platform == "darwin":
        try:
            exchange = libc.renameatx_np
        except AttributeError as exc:
            raise SyncRefused("host does not support atomic file exchange") from exc
        exchange.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        exchange.restype = ctypes.c_int
        result = exchange(parent_fd, left_bytes, parent_fd, right_bytes, 0x00000002)
    elif sys.platform.startswith("linux"):
        try:
            exchange = libc.renameat2
        except AttributeError as exc:
            raise SyncRefused("host does not support atomic file exchange") from exc
        exchange.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        exchange.restype = ctypes.c_int
        result = exchange(parent_fd, left_bytes, parent_fd, right_bytes, 0x00000002)
    else:
        raise SyncRefused("host does not support atomic file exchange")
    if result != 0:
        code = ctypes.get_errno()
        if code in (errno.ENOSYS, errno.ENOTSUP, errno.EINVAL, errno.EXDEV):
            raise SyncRefused("host does not support atomic file exchange")
        raise OSError(code, os.strerror(code))


def _leftovers(parent_fd: int) -> list[str]:
    prefix = ".AGENTS.md.sync-"
    try:
        return sorted(name for name in os.listdir(parent_fd) if name.startswith(prefix))
    except OSError as exc:
        raise SyncRefused(f"cannot inspect synchronization recovery files: {exc}") from exc


def _new_temp(parent_fd: int, expected: Snapshot, data: bytes) -> tuple[int, str, Snapshot]:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    for _ in range(32):
        name = f".AGENTS.md.sync-{secrets.token_hex(12)}"
        try:
            fd = os.open(name, flags, 0o600, dir_fd=parent_fd)
            break
        except FileExistsError:
            continue
    else:
        raise SyncRefused("cannot allocate a unique synchronization recovery file")

    try:
        _lock(fd, exclusive=True)
        os.fchmod(fd, expected.mode)
        info = os.fstat(fd)
        if (info.st_uid, info.st_gid) != (expected.uid, expected.gid):
            raise SyncRefused(
                "atomic replacement cannot preserve target ownership and group"
            )
        _write_all(fd, data)
        prepared = _read_snapshot_fd(fd)
        issue = _metadata_issue(fd, prepared)
        if issue:
            raise SyncRefused(f"replacement metadata is not portable: {issue}")
        if (prepared.uid, prepared.gid) != (expected.uid, expected.gid):
            raise SyncRefused(
                "prepared replacement did not preserve target ownership and group"
            )
        if prepared.data != data or prepared.mode != expected.mode:
            raise SyncRefused("prepared replacement did not verify")
        return fd, name, prepared
    except Exception:
        os.close(fd)
        try:
            os.unlink(name, dir_fd=parent_fd)
        except OSError:
            pass
        raise


def _atomic_write(
    resolved: ResolvedTarget,
    parent_fd: int,
    target_fd: int,
    data: bytes,
    expected: Snapshot,
) -> str:
    leftovers = _leftovers(parent_fd)
    if leftovers:
        raise SyncRefused(
            "unresolved synchronization recovery file exists: " + ", ".join(leftovers)
        )

    issue = _metadata_issue(target_fd, expected)
    if issue:
        raise SyncRefused(f"cannot preserve target metadata: {issue}")

    temp_fd, temp_name, prepared = _new_temp(parent_fd, expected, data)
    retain_temp = False
    try:
        _fsync_directory(parent_fd)
        _assert_parent_binding(resolved, parent_fd)
        if _override_exists_at(parent_fd):
            raise SyncRefused(
                f"AGENTS.override.md appeared during synchronization: {resolved.path.parent}"
            )
        current = _read_snapshot_fd(target_fd)
        if not _same_snapshot(current, expected) or not _name_matches(
            parent_fd, "AGENTS.md", expected
        ):
            raise SyncRefused(f"target changed during synchronization: {resolved.path}")

        _atomic_exchange(parent_fd, temp_name, "AGENTS.md")

        try:
            _fsync_directory(parent_fd)
            captured = _read_snapshot_fd(target_fd)
            if not _same_exchanged_snapshot(captured, expected) or not _name_matches(
                parent_fd, temp_name, expected
            ):
                raise SyncRefused(
                    f"target changed at the atomic exchange boundary: {resolved.path}"
                )
            captured_issue = _metadata_issue(target_fd, captured)
            if captured_issue:
                raise SyncRefused(
                    f"target metadata changed at the atomic exchange boundary: "
                    f"{captured_issue}"
                )
            installed = _read_snapshot_fd(temp_fd)
            if not _same_exchanged_snapshot(installed, prepared) or not _name_matches(
                parent_fd, "AGENTS.md", prepared
            ):
                raise SyncRefused(
                    f"replacement changed during synchronization: {resolved.path}"
                )
            installed_issue = _metadata_issue(temp_fd, installed)
            if installed_issue:
                raise SyncRefused(
                    f"replacement metadata changed during synchronization: "
                    f"{installed_issue}"
                )
            _assert_parent_binding(resolved, parent_fd)
            if _override_exists_at(parent_fd):
                raise SyncRefused(
                    f"AGENTS.override.md appeared during synchronization: {resolved.path.parent}"
                )
            final = _read_snapshot_fd(temp_fd)
            if not _same_exchanged_snapshot(final, prepared) or not _name_matches(
                parent_fd, "AGENTS.md", prepared
            ):
                raise SyncRefused(
                    f"target changed immediately before synchronization committed: "
                    f"{resolved.path}"
                )
            _assert_parent_binding(resolved, parent_fd)
        except Exception as exc:
            # Once an exchange has occurred, always retain whichever inode ends
            # up at the recovery name. A writer can hold an fd and modify that
            # inode immediately after any snapshot, so deleting it on a failure
            # cannot be made into a defensible compare-and-delete operation.
            retain_temp = True
            if _name_matches(parent_fd, "AGENTS.md", prepared):
                try:
                    live_prepared = _read_snapshot_fd(temp_fd)
                except Exception as inspection_exc:
                    retain_temp = True
                    raise SyncRefused(
                        f"replacement could not be verified after atomic exchange; "
                        f"pre-exchange file retained as {temp_name}: {inspection_exc}"
                    ) from exc
                live_prepared_issue = _metadata_issue(temp_fd, live_prepared)
                if (
                    not _same_exchanged_snapshot(live_prepared, prepared)
                    or live_prepared_issue
                ):
                    retain_temp = True
                    raise SyncRefused(
                        f"replacement changed after atomic exchange; pre-exchange "
                        f"file retained as {temp_name}"
                    ) from exc
                try:
                    _atomic_exchange(parent_fd, temp_name, "AGENTS.md")
                except Exception as rollback_exc:
                    retain_temp = True
                    raise SyncRefused(
                        f"synchronization failed and rollback could not complete; "
                        f"pre-exchange file retained as {temp_name}: {rollback_exc}"
                    ) from exc
                try:
                    _fsync_directory(parent_fd)
                except Exception as rollback_sync_exc:
                    retain_temp = True
                    raise SyncRefused(
                        f"rollback restored the original but directory durability "
                        f"could not be confirmed; prepared replacement retained as "
                        f"{temp_name}: {rollback_sync_exc}"
                    ) from exc
                try:
                    rolled_back_prepared = _read_snapshot_fd(temp_fd)
                except Exception as inspection_exc:
                    retain_temp = True
                    raise SyncRefused(
                        f"rollback restored the original but the prepared replacement "
                        f"could not be verified; recovery retained as {temp_name}: "
                        f"{inspection_exc}"
                    ) from exc
                rolled_back_issue = _metadata_issue(temp_fd, rolled_back_prepared)
                if (
                    not _same_exchanged_snapshot(rolled_back_prepared, prepared)
                    or rolled_back_issue
                ):
                    retain_temp = True
                    raise SyncRefused(
                        f"rollback restored the original; concurrently changed "
                        f"replacement retained as {temp_name}"
                    ) from exc
                raise SyncRefused(
                    f"{exc}; rollback restored the original and recovery retained "
                    f"as {temp_name}"
                ) from exc

            retain_temp = True
            raise SyncRefused(
                f"target changed after atomic exchange; pre-exchange file retained as "
                f"{temp_name}: {exc}"
            ) from exc

        # Keep the pre-exchange inode even on success. An uncooperative writer
        # may hold an already-open fd and write after the final snapshot; there
        # is no portable atomic compare-and-unlink primitive that could prove
        # deletion safe. Retention makes such a late write recoverable and also
        # blocks a future changed write until a human reviews the backup.
        retain_temp = True
        return temp_name
    finally:
        os.close(temp_fd)
        if temp_name and not retain_temp:
            try:
                os.unlink(temp_name, dir_fd=parent_fd)
                _fsync_directory(parent_fd)
            except (OSError, SyncRefused):
                pass
        # A retained name is the pre-exchange inode on success or an exchange
        # failure, or the prepared replacement after a completed rollback.


def _local_heading(text: str) -> re.Match[str]:
    headings = list(LOCAL_HEADING_RE.finditer(text))
    fenced = _fenced_ranges(text)
    for heading in headings:
        reason = _inactive_reason(text, heading.start(), fenced)
        if reason:
            raise SyncRefused(
                f"local instructions heading appears inside {reason}"
            )
    if not headings:
        raise SyncRefused("missing repository/workspace local instructions heading")
    if len(headings) > 1:
        raise SyncRefused("multiple or overlapping local instructions headings")
    return headings[0]


def _desired_text(
    text: str, template_block: str, template_version: tuple[int, int, int]
) -> tuple[str, str]:
    has_current_hint = f"{CURRENT_NAMESPACE}:managed:" in text
    has_legacy_hint = f"{LEGACY_NAMESPACE}:managed:" in text
    if has_current_hint and has_legacy_hint:
        raise SyncRefused("mixed current and legacy managed markers")

    current = _scan_namespace(text, CURRENT_NAMESPACE)
    legacy = _scan_namespace(text, LEGACY_NAMESPACE)
    local = _local_heading(text)
    block = current or legacy

    if current and current.version > template_version:
        version = ".".join(str(part) for part in current.version)
        raise SyncRefused(f"newer current contract version is not supported: {version}")
    if legacy and (
        legacy.version[0] != LEGACY_SUPPORTED_MAJOR
        or legacy.version > template_version
    ):
        version = ".".join(str(part) for part in legacy.version)
        raise SyncRefused(f"unsupported legacy contract version: {version}")
    if block and block.end > local.start():
        raise SyncRefused("managed block overlaps or follows local instructions")

    local_section = text[local.start() :]
    if current:
        desired = text[: current.start] + template_block + text[current.end :]
        action = "update"
    elif legacy:
        desired = text[: legacy.start] + template_block + text[legacy.end :]
        action = "migrate"
    else:
        prefix = text[: local.start()]
        if prefix and not prefix.endswith("\n"):
            before = "\n\n"
        elif prefix and not prefix.endswith("\n\n"):
            before = "\n"
        else:
            before = ""
        desired = prefix + before + template_block + "\n\n" + local_section
        action = "install"

    if not desired.endswith(local_section):
        raise SyncRefused("synchronization would alter local instructions")
    return desired, action


def synchronize(
    target_arg: str | os.PathLike[str],
    *,
    write: bool = False,
    template_path: Path | None = None,
) -> SyncResult:
    """Check or synchronize one target and return an observable result."""

    resolved = resolve_target(target_arg)
    parent_fd = _open_parent(resolved)
    target_fd = -1
    try:
        target_fd = _open_target_at(parent_fd, write=write)
        _assert_parent_binding(resolved, parent_fd)
        if _override_exists_at(parent_fd):
            raise SyncRefused(
                f"AGENTS.override.md takes precedence in target directory: "
                f"{resolved.path.parent}"
            )
        snapshot = _read_snapshot_fd(target_fd)
        text, newline = _normalize(snapshot.data, source=str(resolved.path))
        template_block, template_version = _load_template(
            template_path if template_path is not None else DEFAULT_TEMPLATE
        )
        desired_text, action = _desired_text(text, template_block, template_version)
        desired_data = _denormalize(desired_text, newline)
        changed = desired_data != snapshot.data

        recovery: Path | None = None
        if write and changed:
            recovery_name = _atomic_write(
                resolved, parent_fd, target_fd, desired_data, snapshot
            )
            recovery = resolved.path.parent / recovery_name
        else:
            _assert_parent_binding(resolved, parent_fd)
            if not _name_matches(parent_fd, "AGENTS.md", snapshot):
                raise SyncRefused(
                    f"target changed during synchronization: {resolved.path}"
                )
        return SyncResult(
            target=resolved.path,
            changed=changed,
            action=action,
            wrote=write and changed,
            recovery=recovery,
        )
    finally:
        if target_fd >= 0:
            os.close(target_fd)
        os.close(parent_fd)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Check one AGENTS.md managed block. The default is read-only; "
            "pass --write to apply a safe install or migration."
        )
    )
    parser.add_argument(
        "target", help="an AGENTS.md file or a directory containing AGENTS.md"
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help=(
            "atomically exchange and verify the managed block while retaining "
            "the pre-exchange inode as a recovery file"
        ),
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = synchronize(args.target, write=args.write)
    except SyncRefused as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return EXIT_REFUSED
    except TemplateError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except OSError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return EXIT_ERROR

    if result.changed and not args.write:
        print(
            f"DRIFT: {result.action} required for {result.target}; "
            "rerun with --write"
        )
        return EXIT_DRIFT
    if result.wrote:
        print(
            f"UPDATED: {result.action} completed for {result.target}; "
            f"pre-exchange recovery retained at {result.recovery}"
        )
    else:
        print(f"OK: managed block is in sync for {result.target}")
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
