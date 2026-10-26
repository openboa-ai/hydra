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
_NATIVE_PREFIX = b"hydra-native-v2\n"
_DECISION_PREFIX = b"hydra-decision-v1\n"
_DECISION_LIMIT = 256
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
    value = os.pread(fd, len(_NATIVE_PREFIX) + 140, 0)
    if not value:
        return None
    prefix = _NATIVE_PREFIX if value.startswith(_NATIVE_PREFIX) else _OWNER_PREFIX
    native = prefix == _NATIVE_PREFIX
    if len(value) != len(prefix) + (139 if native else 74) or not value.startswith(prefix):
        raise HostBusy("Unrecognized host ownership")
    try:
        parts = value[len(prefix):].decode("ascii").split("\n")
        boot, nonce, empty = parts[0], parts[1], parts[-1]
        if empty or any(str(uuid.UUID(part)) != part for part in (boot, nonce)):
            raise ValueError("Invalid ownership identity")
        if native and not re.fullmatch(r"[0-9a-f]{64}", parts[2]):
            raise ValueError("Invalid native scope")
    except (ValueError, UnicodeError) as exc:
        raise HostBusy("Unrecognized host ownership") from exc
    return boot, nonce


def _clear_owner(fd, previous):
    if _read_owner(fd) != previous:
        raise HostBusy("Host ownership no longer matches")
    value = os.pread(fd, len(_NATIVE_PREFIX) + 140, 0)
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
        self.path, self.inode = None, None
        self.decision_scopes, self.decision_handle = frozenset(), None

    def register(self, *, native_step=None, native_scope=None):
        if self.fd is None or self.ticket is not None or _read_owner(self.fd) is not None:
            raise HostBusy("An owned execution remains unresolved")
        nonce = str(uuid.UUID(native_step)) if native_step else str(uuid.uuid4())
        if native_step and nonce != native_step:
            raise HostBusy("Invalid native assignment identity")
        if native_step and not re.fullmatch(r"[0-9a-f]{64}", native_scope or ""):
            raise HostBusy("Invalid native scope")
        ticket = (self, nonce)
        prefix = _NATIVE_PREFIX if native_step else _OWNER_PREFIX
        value = prefix + (self.boot + "\n" + ticket[1] + "\n").encode("ascii")
        if native_step:
            value += (native_scope + "\n").encode("ascii")
        # Finish positive short writes on the same flock-held inode. A real
        # write failure retains fail-closed bytes and never permits dispatch.
        offset = 0
        while offset < len(value):
            written = os.pwrite(self.fd, value[offset:], offset)
            if not isinstance(written, int) or not 0 < written <= len(value) - offset:
                raise HostBusy("Host ownership write was incomplete")
            offset += written
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


def register_native_assignment(step_id, scope):
    """Retain admission ownership after the MCP call returns."""
    owner = _current_owner.get()
    if owner is None:
        raise HostBusy("Native dispatch requires the host lock")
    return owner.register(native_step=step_id, native_scope=scope)


def native_assignment_matches(step_id, scope):
    """Read back registration uncertainty without dispatching or clearing ownership."""
    owner = _current_owner.get()
    if owner is None or owner.fd is None:
        raise HostBusy("Native registration read-back requires the host lock")
    value = os.pread(owner.fd, len(_NATIVE_PREFIX) + 140, 0)
    return (_read_owner(owner.fd) == (owner.boot, step_id)
            and value == _NATIVE_PREFIX + (owner.boot + "\n" + step_id + "\n" + scope + "\n").encode("ascii"))


def confirm_native_assignment(step_id):
    owner = _current_owner.get()
    if owner is None or owner.ticket is None or owner.ticket[1] != step_id:
        raise HostBusy("Native continuation identity no longer matches")
    owner.confirm(owner.ticket)


def _decision_scope(phase, scope):
    if (type(phase) is not str or phase not in {'publication', 'resume'}
            or type(scope) is not str or re.fullmatch('[0-9a-f]{64}', scope) is None):
        raise HostBusy('Invalid decision ownership scope')
    return phase, scope


def _decision_uuid(value):
    try:
        if type(value) is not str or str(uuid.UUID(value)) != value:
            raise ValueError()
    except (ValueError, AttributeError, TypeError):
        raise HostBusy('Invalid decision ownership identity') from None
    return value


def _decision_record(raw):
    """Decode one bounded owner; unknown and torn bytes never mean absence."""
    if not raw or len(raw) > _DECISION_LIMIT or not raw.startswith(_DECISION_PREFIX):
        raise HostBusy('Unrecognized decision ownership')
    try:
        boot, request, phase, scope, contexts, receipts, end = raw[len(_DECISION_PREFIX):].decode('ascii').split('\n')
        if end or contexts not in {'0', '1', '2', '3'} or receipts not in {'0', '1', '2', '3'}:
            raise ValueError()
        _decision_uuid(boot)
        _decision_uuid(request)
        _decision_scope(phase, scope)
        if phase == 'resume' and (contexts != '0' or receipts != '0'):
            raise ValueError()
    except (ValueError, UnicodeError):
        raise HostBusy('Unrecognized decision ownership') from None
    return boot, request, phase, scope, int(contexts), int(receipts)


def _decision_bytes(record):
    raw = _DECISION_PREFIX + ('\n'.join(map(str, record)) + '\n').encode('ascii')
    _decision_record(raw)
    return raw


def _decision_inode(owner):
    if owner is None or owner is not _current_owner.get() or owner.fd is None or owner.path is None:
        raise HostBusy('Decision ownership requires the active host lock')
    opened, named = os.fstat(owner.fd), owner.path.lstat()
    if (owner.path != owner.path.resolve() or not stat.S_ISREG(named.st_mode)
            or not stat.S_ISREG(opened.st_mode) or opened.st_uid != os.geteuid()
            or opened.st_nlink != 1 or opened.st_mode & 0o077
            or (opened.st_dev, opened.st_ino) != owner.inode
            or (named.st_dev, named.st_ino) != owner.inode):
        raise HostBusy('Decision ownership inode changed')


def _decision_read(owner):
    _decision_inode(owner)
    return os.pread(owner.fd, _DECISION_LIMIT + 1, 0)


def _decision_sync_parent(owner):
    """Persist the existing directory entry before a decision permit escapes."""
    _decision_inode(owner)
    parent = owner.path.parent
    before = parent.lstat()
    if not stat.S_ISDIR(before.st_mode):
        raise HostBusy('Decision ownership directory changed')
    fd = os.open(parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC)
    try:
        opened = os.fstat(fd)
        identity = opened.st_dev, opened.st_ino
        if identity != (before.st_dev, before.st_ino):
            raise HostBusy('Decision ownership directory changed')

        def check():
            named = parent.lstat()
            child = os.stat(owner.path.name, dir_fd=fd, follow_symlinks=False)
            if (not stat.S_ISDIR(named.st_mode) or (named.st_dev, named.st_ino) != identity
                    or not stat.S_ISREG(child.st_mode)
                    or (child.st_dev, child.st_ino) != owner.inode):
                raise HostBusy('Decision ownership directory changed')
            _decision_inode(owner)

        check()
        os.fsync(fd)
        check()
    finally:
        os.close(fd)


def _decision_write(owner, expected, replacement):
    if _decision_read(owner) != expected:
        raise HostBusy('Decision ownership no longer matches')
    offset = 0
    while offset < len(replacement):
        written = os.pwrite(owner.fd, replacement[offset:], offset)
        if type(written) is not int or not 0 < written <= len(replacement) - offset:
            raise HostBusy('Decision ownership write was incomplete')
        offset += written
    os.ftruncate(owner.fd, len(replacement))
    os.fsync(owner.fd)
    _decision_sync_parent(owner)
    if _decision_read(owner) != replacement:
        raise HostBusy('Decision ownership read-back changed')


class DecisionHandle:
    """Live scoped ownership, never a grant or an external-result witness."""
    __slots__ = ('_owner', '_raw', '_created_here', '_spent', '_invalid')

    def __init__(self, owner, raw, created_here):
        self._owner, self._raw, self._created_here = owner, raw, created_here
        self._spent, self._invalid = set(), False

    @property
    def phase(self):
        return _decision_record(self._raw)[2]

    @property
    def scope(self):
        return _decision_record(self._raw)[3]

    @property
    def created_here(self):
        return self._created_here

    @property
    def context_posts(self):
        return _decision_record(self._raw)[4]

    @property
    def receipt_posts(self):
        return _decision_record(self._raw)[5]

    def _check(self):
        if (self._invalid or self._owner.decision_handle is not self
                or _decision_read(self._owner) != self._raw):
            raise HostBusy('Decision ownership handle no longer matches')


def current_decision_owner():
    """Return only phase/scope from the current locked inode; None is not free."""
    owner = _current_owner.get()
    raw = _decision_read(owner)
    if raw.startswith(_DECISION_PREFIX):
        record = _decision_record(raw)
        return record[2], record[3]
    if raw:
        _read_owner(owner.fd)  # Reject malformed ordinary ownership as well.
    return None


def claim_decision_owner(phase, scope_digest, request_id):
    """Create or recover one exact owner; recovery never restores a PATCH permit."""
    scope = _decision_scope(phase, scope_digest)
    _decision_uuid(request_id)
    owner = _current_owner.get()
    raw = _decision_read(owner)
    if scope not in owner.decision_scopes or owner.ticket is not None:
        raise HostBusy('Decision ownership scope was not selected')
    if owner.decision_handle is not None:
        handle = owner.decision_handle
        handle._check()
        if (handle.phase, handle.scope) != scope:
            raise HostBusy('Another decision remains unresolved')
        return handle
    created = not raw
    if raw:
        record = _decision_record(raw)
        if (record[2], record[3]) != scope:
            raise HostBusy('Another decision remains unresolved')
    else:
        raw = _decision_bytes((owner.boot, request_id, phase, scope_digest, 0, 0))
        _decision_write(owner, b'', raw)
    handle = DecisionHandle(owner, raw, created)
    owner.decision_handle = handle
    return handle


def spend_publication(handle, kind):
    """Durably reserve one POST before transport; return its lifetime count."""
    if (type(handle) is not DecisionHandle or type(kind) is not str
            or kind not in {'context', 'receipt'}):
        raise HostBusy('Invalid decision publication permit')
    handle._check()
    if handle.phase != 'publication' or kind in handle._spent:
        raise HostBusy('Decision publication permit already spent')
    index = 4 if kind == 'context' else 5
    record = list(_decision_record(handle._raw))
    if record[index] >= 3:
        raise HostBusy('Decision publication retry bound exhausted')
    record[index] += 1
    replacement = _decision_bytes(record)
    handle._spent.add(kind)
    try:
        _decision_write(handle._owner, handle._raw, replacement)
    except BaseException:
        handle._invalid = True
        raise
    handle._raw = replacement
    return record[index]


def resume_new(handle):
    """Consume the sole PATCH permit of the live invocation that created it."""
    if type(handle) is not DecisionHandle:
        raise HostBusy('Invalid decision resume permit')
    handle._check()
    if handle.phase != 'resume' or not handle.created_here or handle._spent:
        raise HostBusy('Decision resume permits read reconciliation only')
    handle._spent.add('resume')
    return True


def retire_decision_owner(handle):
    """Retire after the caller verifies exact terminal external evidence."""
    if type(handle) is not DecisionHandle:
        raise HostBusy('Invalid decision retirement')
    handle._check()
    try:
        _decision_write(handle._owner, handle._raw, b'')
    except BaseException:
        # Restore only this exact serialized record on the same locked inode.
        # A failed restoration remains uncertain and never permits dispatch.
        try:
            current = _decision_read(handle._owner)
            if not current:
                _decision_write(handle._owner, b'', handle._raw)
        except (OSError, HostBusy):
            pass
        handle._invalid = True
        raise
    handle._invalid = True
    handle._owner.decision_handle = None


def retire_undispatched_decision(handle):
    """Only the creating live publication can prove no transport was reserved."""
    if (type(handle) is not DecisionHandle or not handle.created_here
            or handle.phase != 'publication' or handle.context_posts or handle.receipt_posts
            or handle._spent):
        raise HostBusy('Decision non-dispatch is not established')
    retire_decision_owner(handle)


@contextmanager
def coordinator_lock(path: Path, *, native_step=None, native_scope=None, decision_scopes=frozenset()):
    if type(decision_scopes) is not frozenset or len(decision_scopes) > 3:
        raise HostBusy('Invalid decision ownership scopes')
    for scope in decision_scopes:
        if type(scope) is not tuple or len(scope) != 2:
            raise HostBusy('Invalid decision ownership scopes')
        _decision_scope(*scope)
    if decision_scopes and (native_step is not None or native_scope is not None):
        raise HostBusy('Conflicting host ownership scopes')
    path = path.expanduser().absolute()
    if decision_scopes:
        # Installed admission prepares this same directory durably. A scoped
        # decision cannot silently create an unsynced chain of new ancestors.
        try:
            parent = path.parent.lstat()
            if not stat.S_ISDIR(parent.st_mode) or path != path.resolve():
                raise HostBusy('Decision ownership directory unavailable')
        except OSError as exc:
            raise HostBusy('Decision ownership directory unavailable') from exc
    else:
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
        decision_raw = os.pread(fd, _DECISION_LIMIT + 1, 0)
        decision = _decision_record(decision_raw) if decision_raw.startswith(_DECISION_PREFIX) else None
        if decision is not None and (decision[2], decision[3]) not in decision_scopes:
            raise HostBusy('An earlier decision effect remains unresolved')
        previous = None if decision is not None else _read_owner(fd)
        native = os.pread(fd, len(_NATIVE_PREFIX), 0) == _NATIVE_PREFIX
        if previous is not None:
            if native:
                observed_scope = os.pread(fd, len(_NATIVE_PREFIX) + 140, 0).decode("ascii").split("\n")[3]
                if native_step != previous[1] or native_scope != observed_scope:
                    raise HostBusy("An earlier native assignment remains unresolved")
            elif previous[0] == boot:
                raise HostBusy("An earlier owned execution remains unresolved")
            # Only a verified new boot proves every prior host process is gone.
            if not native:
                _clear_owner(fd, previous)
        elif native_step is not None:
            raise HostBusy("Native assignment ownership is missing")
        owner = _HostOwner(fd, boot)
        owner.path, owner.inode = path, (observed.st_dev, observed.st_ino)
        owner.decision_scopes = decision_scopes
        if native:
            # Preserve the old boot until explicit completion/reconciliation.
            owner.boot = previous[0]
            owner.ticket = (owner, previous[1])
        token = _current_owner.set(owner)
        if decision_scopes:
            _decision_inode(owner)
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


_operating_scope = ContextVar("hydra_operating_scope", default=None)


@contextmanager
def operation_scope(control, repository, *, expected_revision=None):
    """Bind host admission settings to one parent-side repository operation."""
    token = _operating_scope.set((control, repository, expected_revision) if control is not None else None)
    try:
        yield
    finally:
        _operating_scope.reset(token)


def operation_scope_active():
    """Whether this execution is bound to installed operating controls."""
    return _operating_scope.get() is not None


@contextmanager
def operation_guard():
    """Barrier for one launch/grant, never an entire model or verification run."""
    current = _operating_scope.get()
    if current is None:
        yield
    else:
        control, repository, revision = current
        with control.guard(repository) if revision is None else control.guard(repository, expected_revision=revision):
            yield


def observe_coordinator(path):
    """Inspect admission without creating, truncating or retiring its inode.

    A free admission lock is not proof that every managed execution has ended.
    Callers must separately account for scoped progress and residual execution.
    """
    path = Path(path).expanduser().absolute()
    fd = None
    try:
        if path != path.resolve():
            return {"state": "unknown", "reason": "ownership_file_unsafe"}
        before = path.lstat()
        if (not stat.S_ISREG(before.st_mode) or before.st_uid != os.geteuid()
                or before.st_nlink != 1 or before.st_mode & 0o077):
            return {"state": "unknown", "reason": "ownership_file_unsafe"}
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | os.O_NONBLOCK)
        opened = os.fstat(fd)
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            return {"state": "unknown", "reason": "ownership_file_changed"}
        held = False
        try:
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
            held = True
        except BlockingIOError:
            pass
        value = os.pread(fd, _DECISION_LIMIT + 1, 0)
        decision = _decision_record(value) if value.startswith(_DECISION_PREFIX) else None
        owner = None if decision is not None else _read_owner(fd)
        after = path.lstat()
        if ((after.st_dev, after.st_ino) != (opened.st_dev, opened.st_ino)
                or os.pread(fd, _DECISION_LIMIT + 1, 0) != value):
            return {"state": "unknown", "reason": "ownership_changed_during_observation"}
        if decision is not None:
            return {"state": "unknown", "reason": "decision_effect_pending"}
        if owner is None:
            return {"state": "free" if held else "busy", "ticket": None}
        result = {"state": "native" if value.startswith(_NATIVE_PREFIX) else "owned",
                  "busy": not held, "boot_id": owner[0], "nonce": owner[1]}
        if value.startswith(_NATIVE_PREFIX):
            result["scope_digest"] = value.decode("ascii").split("\n")[3]
        return result
    except FileNotFoundError:
        return {"state": "absent", "ticket": None}
    except (OSError, ValueError, HostBusy):
        return {"state": "unknown", "reason": "ownership_observation_unavailable"}
    finally:
        if fd is not None:
            os.close(fd)
