"""Private, single-worker stdio boundary; no SDK imports or durable state here."""

from __future__ import annotations

import asyncio
import errno
import hashlib
import json
import os
import queue
import selectors
import signal
import socket
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

MAX_FRAME_BYTES = 1024 * 1024
PROTOCOL_VERSION = 1
SUPERVISION_LIMIT = 4096
CLEANUP_SECONDS = 2.0
_REJECTED_LAUNCH_ERRNOS = frozenset({errno.ENOENT, errno.ENOTDIR, errno.EACCES, errno.ENOEXEC})
_NATIVE_EXECUTE_CHILD = getattr(subprocess.Popen._execute_child, "__code__", None)
PUBLISHING_TOKEN_VARIABLES = frozenset({
    "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN",
})


class ProtocolError(RuntimeError):
    pass


def _ownership_coordinator():
    if __package__:
        from . import coordinator
        return coordinator
    # A standalone file import has no CLI lock of its own. Reuse the canonical
    # module if the CLI loaded it; never create another ContextVar owner copy.
    return sys.modules.get("hydra_sdlc.coordinator")


def worker_environment():
    """Preserve host Codex configuration without service publishing tokens."""
    return {key: value for key, value in os.environ.items() if key not in PUBLISHING_TOKEN_VARIABLES}


def _encode(frame):
    data = json.dumps(frame, separators=(",", ":"), allow_nan=False).encode() + b"\n"
    if len(data) > MAX_FRAME_BYTES:
        raise ProtocolError("Frame too large")
    return data


def _decode(data):
    if not data or len(data) > MAX_FRAME_BYTES or not data.endswith(b"\n"):
        raise ProtocolError("Incomplete or oversized frame")
    frame = json.loads(data)
    if (not isinstance(frame, dict) or set(frame) != {"version", "kind", "seq", "data"}
            or type(frame.get("version")) is not int or frame["version"] != PROTOCOL_VERSION
            or type(frame.get("seq")) is not int or frame["seq"] < 0
            or not isinstance(frame.get("kind"), str) or not isinstance(frame.get("data"), dict)):
        raise ProtocolError("Invalid protocol frame")
    return frame


def _frame(kind, seq, data):
    return {"version": PROTOCOL_VERSION, "kind": kind, "seq": seq, "data": data}


def _encode_result(seq, data):
    try:
        return _encode(_frame("result", seq, data))
    except ProtocolError:
        detail = data.get("detail")
        if not isinstance(detail, dict) or not isinstance(detail.get("items"), dict) or not detail["items"]:
            raise
        # Every item already crossed the acknowledged event channel intact.
        # Omit only this duplicate snapshot; never trim the structured outcome,
        # terminal identity or cleanup receipt to fit a result frame.
        compact = {**data, "detail": {**detail, "items": {}, "items_omitted": len(detail["items"])}}
        return _encode(_frame("result", seq, compact))


def _worker_command(source):
    return [sys.executable, "-I", str(Path(source).resolve()), "--execution-worker"]


def _group_absent(pgid):
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return True
    except OSError:
        return False
    return False


def _supervision_frame(kind, **values):
    data = json.dumps({"version": 1, "kind": kind, **values}, allow_nan=False).encode() + b"\n"
    if len(data) > SUPERVISION_LIMIT:
        raise ProtocolError("Supervision frame too large")
    return data


class OwnedCommandError(ProtocolError):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def _helper_command(command, control_fd, deadline):
    return [sys.executable, "-I", str(Path(__file__).resolve()), "--owned-process-helper",
            str(control_fd), str(deadline), json.dumps(command)]


def _decode_supervision(data):
    frame = json.loads(data)
    if not isinstance(frame, dict) or type(frame.get("version")) is not int or frame["version"] != 1:
        raise ProtocolError("Invalid supervision frame")
    return frame


def _validate_ready(ready, helper_pid):
    if (set(ready) != {"version", "kind", "pid", "pgid"} or ready["kind"] != "ready"
            or type(ready["pid"]) is not int or ready["pid"] <= 1
            or type(ready["pgid"]) is not int
            or ready["pgid"] != ready["pid"] or ready["pid"] == helper_pid):
        raise ProtocolError("Invalid supervision identity")
    return ready["pid"], ready["pgid"]


def _validate_receipt(receipt, pid, pgid):
    if (set(receipt) != {"version", "kind", "pid", "pgid", "returncode", "reaped", "group_absent"}
            or receipt["kind"] != "cleanup" or receipt["pid"] != pid or receipt["pgid"] != pgid
            or type(receipt["pid"]) is not int or type(receipt["pgid"]) is not int
            or type(receipt["returncode"]) is not int
            or type(receipt["reaped"]) is not bool or type(receipt["group_absent"]) is not bool):
        raise ProtocolError("Invalid cleanup receipt")
    return receipt


def _native_launch_rejected(exc, command, cwd):
    """Recognize only CPython's collected pre-exec/cwd error, not transport loss."""
    if not isinstance(exc, OSError) or exc.errno not in _REJECTED_LAUNCH_ERRNOS:
        return False
    traceback = exc.__traceback__
    while traceback is not None and traceback.tb_next is not None:
        traceback = traceback.tb_next
    if (_NATIVE_EXECUTE_CHILD is None or traceback is None
            or traceback.tb_frame.f_code is not _NATIVE_EXECUTE_CHILD):
        return False
    try:
        attempted = [os.fsencode(command[0])]
        if cwd is not None:
            attempted.append(os.fsencode(cwd))
        return exc.filename is not None and os.fsencode(exc.filename) in attempted
    except (IndexError, TypeError, ValueError):
        return False


def _validate_launch_rejected(frame):
    if (set(frame) != {"version", "kind", "errno", "reaped"}
            or frame["kind"] != "launch_rejected" or type(frame["errno"]) is not int
            or frame["errno"] not in _REJECTED_LAUNCH_ERRNOS or frame["reaped"] is not True):
        raise ProtocolError("Invalid launch rejection receipt")
    return frame


def _validate_launch_cancelled(frame):
    if (set(frame) != {"version", "kind", "reaped"}
            or frame["kind"] != "launch_cancelled" or frame["reaped"] is not True):
        raise ProtocolError("Invalid launch cancellation receipt")
    return frame


class OwnedProcess:
    """One live-owned SDK group; Linux reaping never changes host-wide child ownership."""

    def __init__(self, command, *, stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
                 stderr=asyncio.subprocess.DEVNULL, env=None, cwd=None, limit=MAX_FRAME_BYTES):
        self.command = list(command)
        self.options = dict(stdin=stdin, stdout=stdout, stderr=stderr, env=env, cwd=cwd, limit=limit,
                            start_new_session=True)
        self.linux = sys.platform.startswith("linux")
        self.process = self.control = self._peer = self._launch = self._receipt_task = None
        self._ready_task = None
        self._launch_sent = False
        self._admission_closed = False
        self._launch_command = None
        self._rejected_launch = None
        self._rejection = None
        self._cancelled_launch = None
        self._ownership_ticket = None
        self._cleanup_task = None
        self._buffer = b""
        self.pid = self.pgid = self._returncode = None
        self.receipt = None

    @property
    def stdin(self):
        return self.process.stdin

    @property
    def stdout(self):
        return self.process.stdout

    @property
    def returncode(self):
        return self._returncode if self.linux else self.process.returncode

    def _registered(self, task):
        try:
            self.process = task.result()
            if not self.linux:
                self.pid = self.pgid = self.process.pid
        except BaseException:
            pass
        finally:
            if self._peer is not None:
                self._peer.close()
                self._peer = None

    async def _spawn(self, command, options):
        try:
            return await asyncio.create_subprocess_exec(*command, **options)
        except OSError as exc:
            # A readiness waiter can consume failure before done callbacks run.
            # Capture native provenance inside the launch task before exposing it.
            if _native_launch_rejected(exc, self._launch_command, options["cwd"]):
                self._rejected_launch = asyncio.current_task()
            raise

    async def start(self, deadline):
        if os.name != "posix" or self._launch is not None:
            raise ProtocolError("Invalid owned process launch")
        command, options = self.command, dict(self.options)
        if self.linux:
            self.control, self._peer = socket.socketpair()
            self.control.setblocking(False)
            command = _helper_command(command, self._peer.fileno(), deadline)
            options["pass_fds"] = (self._peer.fileno(),)
        # These hooks run only in the parent-side supervisor. The
        # isolated helper entry point needs no package import or lock descriptor.
        coordinator = _ownership_coordinator()
        self._ownership_ticket = None if coordinator is None else coordinator.register_owned_process()
        self._launch_command = tuple(command)
        self._launch = asyncio.create_task(self._spawn(command, options))
        self._launch.add_done_callback(self._registered)
        if self.linux:
            # Retain the single control reader through startup cancellation. It
            # can still validate late identity and cleanup within the same grace.
            self._ready_task = asyncio.create_task(self._read_ready(deadline))
            try:
                await asyncio.wait_for(asyncio.shield(self._ready_task),
                                      max(0.001, deadline - asyncio.get_running_loop().time()))
            except (asyncio.CancelledError, TimeoutError):
                self._admission_closed = True
                raise
            if asyncio.get_running_loop().time() >= deadline:
                raise TimeoutError("Owned process startup deadline expired")
            return self
        # Retain an in-flight launch so cancellation cannot discard its ownership.
        self.process = await asyncio.wait_for(asyncio.shield(self._launch),
                                             max(0.001, deadline - asyncio.get_running_loop().time()))
        self.pid = self.pgid = self.process.pid
        return self

    async def _read_ready(self, deadline):
        self.process = await asyncio.shield(self._launch)
        loop = asyncio.get_running_loop()
        # This is the only initial writer. Expiry closes admission but leaves
        # the reader alive for the helper's no-child receipt during cleanup.
        if loop.time() < deadline:
            initial = "terminate" if self._admission_closed else "launch"
            try:
                await loop.sock_sendall(self.control, _supervision_frame(initial))
            except OSError:
                # The helper may already have closed after confirming no child.
                # Only its validated receipt, zero exit and EOF can prove clean.
                pass
            else:
                self._launch_sent = initial == "launch"
        ready = await self._read_control()
        if ready.get("kind") == "launch_cancelled":
            self._cancelled_launch = _validate_launch_cancelled(ready)
            raise TimeoutError("Owned process launch cancelled")
        if ready.get("kind") == "launch_rejected":
            self._rejection = _validate_launch_rejected(ready)
            raise OwnedCommandError("unavailable")
        self.pid, self.pgid = _validate_ready(ready, self.process.pid)
        self._receipt_task = asyncio.create_task(self._read_receipt())

    async def _read_control(self):
        while b"\n" not in self._buffer:
            data = await asyncio.get_running_loop().sock_recv(self.control, SUPERVISION_LIMIT + 1)
            if not data:
                raise ProtocolError("Supervision channel disconnected")
            self._buffer += data
            if len(self._buffer.split(b"\n", 1)[0]) >= SUPERVISION_LIMIT:
                raise ProtocolError("Supervision frame too large")
        data, self._buffer = self._buffer.split(b"\n", 1)
        return _decode_supervision(data)

    async def _read_receipt(self):
        receipt = _validate_receipt(await self._read_control(), self.pid, self.pgid)
        self.receipt = receipt
        self._returncode = receipt["returncode"]
        return receipt

    async def wait(self):
        await self.process.wait()
        if self.linux and self._receipt_task is not None:
            await asyncio.shield(self._receipt_task)
        return self.returncode

    async def communicate(self):
        output = await self.process.communicate()
        if self.linux and self._receipt_task is not None:
            await asyncio.shield(self._receipt_task)
        return output

    async def cleanup(self):
        self._admission_closed = True
        if self._cleanup_task is None:
            self._cleanup_task = asyncio.create_task(self._collect_owned())
        while True:
            try:
                return await asyncio.shield(self._cleanup_task)
            except asyncio.CancelledError:
                if self._cleanup_task.cancelled():
                    return False
                # Repeated caller cancellation cannot abandon the owned cleanup.
                continue

    async def _collect_owned(self):
        if not await self._collect():
            return False
        try:
            if self._ownership_ticket is not None:
                _ownership_coordinator().confirm_owned_cleanup(self._ownership_ticket)
        except Exception:
            return False
        self._ownership_ticket = None
        return True

    async def _collect(self):
        loop = asyncio.get_running_loop()
        deadline = loop.time() + CLEANUP_SECONDS
        try:
            if self._launch is not None and self.process is None:
                try:
                    self.process = await asyncio.wait_for(asyncio.shield(self._launch),
                                                         max(0.001, deadline - loop.time()))
                except (Exception, asyncio.CancelledError):
                    if (self._launch is self._rejected_launch and self._launch.done()
                            and not self._launch.cancelled()):
                        return True
                    self._launch.cancel()
                    return False
            if self.process is None:
                return self._launch is None
            if not self.linux:
                return await _collect_direct(self.process, deadline)
            # A failed startup still retains its helper. It never authorizes clean
            # from the helper's disappearance without the child's private receipt.
            control_sent = False
            term_sent = False
            group_gone = False
            kill_at = min(deadline, loop.time() + 1.0)
            while loop.time() < deadline:
                if (self._launch_sent and not control_sent
                        and self._rejection is None and self._cancelled_launch is None):
                    try:
                        await loop.sock_sendall(self.control, _supervision_frame("terminate"))
                    except (OSError, RuntimeError):
                        pass
                    control_sent = True
                if self._ready_task is not None and self._ready_task.done():
                    try:
                        self._ready_task.result()
                    except Exception:
                        pass
                if ((self._rejection is not None or self._cancelled_launch is not None)
                        and self.process.returncode == 0):
                    await asyncio.wait_for(self.process.communicate(), max(.001, deadline - loop.time()))
                    if self._buffer:
                        return False
                    tail = await asyncio.wait_for(loop.sock_recv(self.control, 1),
                                                  max(.001, deadline - loop.time()))
                    return tail == b""
                if self.pgid is not None and _group_absent(self.pgid):
                    group_gone = True
                receipt_done = self._receipt_task is not None and self._receipt_task.done()
                if receipt_done:
                    try:
                        self._receipt_task.result()
                    except Exception:
                        pass
                if self.receipt is not None and self.receipt["group_absent"]:
                    group_gone = True
                if (self.receipt and self.receipt["reaped"] and self.receipt["group_absent"]
                        and self.process.returncode == 0 and _group_absent(self.pgid)):
                    await asyncio.wait_for(self.process.communicate(), max(0.001, deadline - loop.time()))
                    return True
                # Independent fallback if the helper/channel fails: signal only
                # the group whose identity this live handle actually received.
                failed = ((receipt_done and self.receipt is None) or self.process.returncode is not None)
                if failed and self.pgid is not None and not group_gone:
                    sig = signal.SIGTERM if loop.time() < kill_at else signal.SIGKILL
                    if not term_sent or sig == signal.SIGKILL:
                        try:
                            os.killpg(self.pgid, sig)
                        except ProcessLookupError:
                            group_gone = True
                        except OSError:
                            break
                        term_sent = True
                await asyncio.sleep(min(.01, max(0, deadline - loop.time())))
            if self.receipt is not None and self.receipt["group_absent"]:
                group_gone = True
            if self.pgid is not None and not group_gone and not _group_absent(self.pgid):
                try:
                    os.killpg(self.pgid, signal.SIGKILL)
                except OSError:
                    pass
            if self.process.returncode is None:
                self.process.kill()
            return False
        except (OSError, TimeoutError, ProtocolError):
            return False
        finally:
            if self._ready_task is not None:
                if not self._ready_task.done():
                    self._ready_task.cancel()
                elif not self._ready_task.cancelled():
                    self._ready_task.exception()
            if self._receipt_task is not None:
                if not self._receipt_task.done():
                    self._receipt_task.cancel()
                elif not self._receipt_task.cancelled():
                    self._receipt_task.exception()
            if self.control is not None:
                self.control.close()
            if self._peer is not None:
                self._peer.close()


async def _collect_direct(process, deadline):
    loop = asyncio.get_running_loop()
    signal_allowed, group_gone = True, False
    for sig in (signal.SIGTERM, signal.SIGKILL):
        if signal_allowed and not group_gone:
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                signal_allowed, group_gone = False, True
            except OSError:
                return False
        until = min(deadline, loop.time() + 1.0)
        while loop.time() < until:
            if not group_gone:
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    signal_allowed, group_gone = False, True
                except OSError:
                    # A dying native group may transiently reject the probe.
                    # Observe again, but never infer absence or permit escalation.
                    signal_allowed = False
                else:
                    signal_allowed = True
            if group_gone:
                try:
                    await asyncio.wait_for(process.communicate(), max(0.001, until - loop.time()))
                    return True
                except TimeoutError:
                    return False
            await asyncio.sleep(0.02)
    return False


async def _cleanup(process):
    return True if process is None else await process.cleanup()


def run_owned_sync(argv, *, cwd, env, timeout, stop_requested=None, max_output_bytes):
    """Run a synchronous check using the same owned helper and receipt contract.

    No nested event loop or background thread is needed. The caller retains its
    storage lease and evaluates its stop callback on the original thread.
    """
    if os.name != "posix":
        raise OwnedCommandError("unavailable")
    if stop_requested is not None and stop_requested():
        raise OwnedCommandError("stopped")
    deadline = time.monotonic() + timeout
    linux = sys.platform.startswith("linux")
    process = control = peer = None
    ownership_ticket = None
    pid = pgid = receipt = rejection = cancellation = None
    launch_sent = False
    native_rejected = False
    buffered = b""
    data = bytearray()
    reason = None
    group_gone = stdout_closed = control_closed = control_failed = False

    def fail(value):
        nonlocal reason
        if (reason is None or value == "cleanup_unknown" or (value == "stopped" and reason != "cleanup_unknown")
                or (value == "output_limit" and reason == "timeout")):
            reason = value

    def stopped():
        if stop_requested is not None and stop_requested():
            fail("stopped")
            return True
        return False

    def signal_group(sig):
        nonlocal group_gone
        if pgid is not None and not group_gone:
            try:
                os.killpg(pgid, sig)
            except ProcessLookupError:
                group_gone = True
            except OSError:
                fail("cleanup_unknown")

    with selectors.DefaultSelector() as selector:
        def close_control():
            nonlocal control_closed
            if control is not None and not control_closed:
                selector.unregister(control)
                control.close()
                control_closed = True

        def receive(wait):
            nonlocal pid, pgid, receipt, rejection, cancellation, buffered, stdout_closed, control_failed, group_gone
            for key, _ in selector.select(max(0, min(.1, wait))):
                if key.data == "output":
                    try:
                        chunk = os.read(process.stdout.fileno(), 65536)
                    except BlockingIOError:
                        continue
                    if not chunk:
                        selector.unregister(process.stdout)
                        stdout_closed = True
                    elif len(data) <= max_output_bytes:
                        data.extend(chunk[:max_output_bytes + 1 - len(data)])
                        if len(data) > max_output_bytes:
                            fail("output_limit")
                else:
                    try:
                        chunk = control.recv(SUPERVISION_LIMIT + 1)
                        if not chunk:
                            if (receipt is None and rejection is None and cancellation is None) or buffered:
                                raise ProtocolError("Missing cleanup receipt")
                            close_control()
                            continue
                        buffered += chunk
                        while b"\n" in buffered:
                            line, buffered = buffered.split(b"\n", 1)
                            if len(line) >= SUPERVISION_LIMIT:
                                raise ProtocolError("Supervision frame too large")
                            frame = _decode_supervision(line)
                            if pid is None and rejection is None and cancellation is None:
                                if frame.get("kind") == "launch_rejected":
                                    rejection = _validate_launch_rejected(frame)
                                    fail("unavailable")
                                elif frame.get("kind") == "launch_cancelled":
                                    cancellation = _validate_launch_cancelled(frame)
                                    fail("timeout")
                                else:
                                    pid, pgid = _validate_ready(frame, process.pid)
                            elif rejection is not None or cancellation is not None:
                                raise ProtocolError("Unexpected frame after no-child receipt")
                            elif receipt is None:
                                receipt = _validate_receipt(frame, pid, pgid)
                                if receipt["group_absent"]:
                                    group_gone = True
                            else:
                                raise ProtocolError("Unexpected supervision frame")
                        if len(buffered) >= SUPERVISION_LIMIT:
                            raise ProtocolError("Supervision frame too large")
                    except BlockingIOError:
                        continue
                    except (OSError, ValueError, ProtocolError):
                        control_failed = True
                        fail("cleanup_unknown")
                        close_control()

        try:
            command = list(argv)
            options = dict(cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                           stderr=subprocess.STDOUT, start_new_session=True)
            if linux:
                control, peer = socket.socketpair()
                control.setblocking(False)
                command = _helper_command(command, peer.fileno(), deadline)
                options["pass_fds"] = (peer.fileno(),)
            coordinator = _ownership_coordinator()
            ownership_ticket = None if coordinator is None else coordinator.register_owned_process()
            try:
                process = subprocess.Popen(command, **options)
            except OSError as exc:
                native_rejected = _native_launch_rejected(exc, command, cwd)
                raise
            if peer is not None:
                peer.close()
                peer = None
            os.set_blocking(process.stdout.fileno(), False)
            selector.register(process.stdout, selectors.EVENT_READ, "output")
            if linux:
                selector.register(control, selectors.EVENT_READ, "control")
                if time.monotonic() < deadline:
                    initial = "terminate" if stopped() else "launch"
                    try:
                        control.sendall(_supervision_frame(initial))
                    except OSError:
                        pass  # Still require the exact receipt, zero exit and EOF.
                    else:
                        launch_sent = initial == "launch"
                else:
                    fail("timeout")
            else:
                pid = pgid = process.pid
            while reason is None:
                if stopped():
                    break
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    fail("timeout")
                    break
                receive(remaining)
                if (linux and receipt is not None) or (not linux and process.poll() is not None):
                    break
        except BaseException as exc:
            fail("stopped" if isinstance(exc, KeyboardInterrupt) else
                 "cleanup_unknown" if process is not None else "unavailable")
        finally:
            if peer is not None:
                peer.close()

        clean = process is None and (ownership_ticket is None or native_rejected)
        if process is not None:
            cleanup_deadline = time.monotonic() + CLEANUP_SECONDS
            kill_at = cleanup_deadline - 1.0
            term_sent = False
            if (linux and launch_sent and receipt is None and rejection is None
                    and cancellation is None and not control_closed):
                try:
                    control.sendall(_supervision_frame("terminate"))
                except OSError:
                    pass  # A no-child receipt may already be queued before EOF.
            try:
                while time.monotonic() < cleanup_deadline:
                    try:
                        stopped()
                        receive(cleanup_deadline - time.monotonic())
                    except BaseException:
                        fail("cleanup_unknown")
                    outer_code = process.poll()  # Collect only this direct child.
                    if ((rejection is not None or cancellation is not None) and stdout_closed and control_closed
                            and outer_code == 0 and not control_failed):
                        clean = True
                        break
                    absent = pgid is not None and _group_absent(pgid)
                    if absent:
                        group_gone = True
                    receipt_clean = (receipt is not None and receipt["reaped"] and receipt["group_absent"])
                    if (stdout_closed and absent and outer_code is not None
                            and (not linux or (outer_code == 0 and receipt_clean and not control_failed))):
                        clean = True
                        break
                    # The Linux helper handles ordinary termination and reaping.
                    # Fall back only to the actual group reported by this handle.
                    if not linux or control_failed or outer_code is not None:
                        if not term_sent:
                            signal_group(signal.SIGTERM)
                            term_sent = True
                        if time.monotonic() >= kill_at:
                            signal_group(signal.SIGKILL)
                if not clean:
                    signal_group(signal.SIGKILL)
                    if process.poll() is None:
                        process.kill()
                    process.poll()
            except (OSError, ValueError):
                clean = False
            finally:
                if control is not None:
                    control.close()
                process.stdout.close()
        elif control is not None:
            control.close()

    if clean and reason != "cleanup_unknown":
        try:
            if ownership_ticket is not None:
                _ownership_coordinator().confirm_owned_cleanup(ownership_ticket)
        except Exception:
            clean = False
    if not clean or reason == "cleanup_unknown":
        raise OwnedCommandError("cleanup_unknown")
    if reason in {"stopped", "output_limit", "unavailable"}:
        raise OwnedCommandError(reason)
    code = -signal.SIGKILL if reason == "timeout" else receipt["returncode"] if linux else process.returncode
    return subprocess.CompletedProcess(list(argv), code, bytes(data))


def _enable_subreaper():
    import ctypes
    if not sys.platform.startswith("linux"):
        raise ProtocolError("Linux supervisor required")
    libc = ctypes.CDLL(None, use_errno=True)
    libc.prctl.argtypes = [ctypes.c_int, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_ulong]
    libc.prctl.restype = ctypes.c_int
    observed = ctypes.c_int()
    if (libc.prctl(36, 1, 0, 0, 0) != 0
            or libc.prctl(37, ctypes.addressof(observed), 0, 0, 0) != 0 or observed.value != 1):
        raise ProtocolError("Subreaper unavailable")


def _supervisor_main(fd, deadline, command):
    """Isolated helper: it owns every child it can reap, and runs no SDK code."""
    import select
    control = socket.socket(fileno=fd)
    control.settimeout(max(.001, deadline - time.monotonic()))
    child = None
    stopping = False
    stop_at = None
    returncode = None
    buffered = b""
    connected = True
    group_gone = False

    def stop(*_):
        nonlocal stopping
        stopping = True

    def no_child_receipt(kind, **fields):
        try:
            os.waitpid(-1, os.WNOHANG)
        except ChildProcessError:
            for descriptor in (0, 1):
                os.close(descriptor)
            control.settimeout(.05)
            control.sendall(_supervision_frame(kind, reaped=True, **fields))
            return 0
        raise ProtocolError("No-child receipt requires ECHILD")

    try:
        _enable_subreaper()
        signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        signal.signal(signal.SIGTERM, stop)
        signal.signal(signal.SIGINT, stop)
        while b"\n" not in buffered:
            control.settimeout(max(.001, deadline - time.monotonic()))
            try:
                part = control.recv(SUPERVISION_LIMIT + 1)
            except TimeoutError:
                if buffered:
                    raise ProtocolError("Incomplete launch control")
                return no_child_receipt("launch_cancelled")
            if not part or len(buffered) + len(part) > SUPERVISION_LIMIT:
                raise ProtocolError("Invalid launch control")
            buffered += part
        initial, buffered = buffered.split(b"\n", 1)
        initial = _decode_supervision(initial)
        if initial not in ({"version": 1, "kind": "launch"}, {"version": 1, "kind": "terminate"}):
            raise ProtocolError("Invalid launch control")
        stopping = stopping or initial["kind"] == "terminate"
        # Drain controls already available with launch before admitting a child.
        # A partial or invalid tail never authorizes admission or a clean receipt.
        control.setblocking(False)
        while True:
            try:
                part = control.recv(SUPERVISION_LIMIT + 1)
            except BlockingIOError:
                break
            if not part or len(buffered) + len(part) > SUPERVISION_LIMIT:
                raise ProtocolError("Invalid initial control tail")
            buffered += part
        while b"\n" in buffered:
            line, buffered = buffered.split(b"\n", 1)
            if _decode_supervision(line) != {"version": 1, "kind": "terminate"}:
                raise ProtocolError("Invalid initial control tail")
            stopping = True
        if buffered:
            raise ProtocolError("Incomplete initial control tail")
        control.settimeout(max(.001, deadline - time.monotonic()))
        if stopping or time.monotonic() >= deadline:
            return no_child_receipt("launch_cancelled")
        try:
            child = subprocess.Popen(command, close_fds=True, start_new_session=True)
        except OSError as exc:
            if not _native_launch_rejected(exc, command, None):
                raise
            return no_child_receipt("launch_rejected", errno=exc.errno)
        # Inherited SDK stdio is untouched; the private socket is CLOEXEC and is
        # deliberately absent from the child's pass_fds. Release helper copies.
        for descriptor in (0, 1):
            os.close(descriptor)
        control.sendall(_supervision_frame("ready", pid=child.pid, pgid=child.pid))
        control.setblocking(False)
        killed = False
        while True:
            # The launch read can also contain terminate. Consume complete
            # buffered controls even when no further socket data will arrive.
            while b"\n" in buffered:
                line, buffered = buffered.split(b"\n", 1)
                if json.loads(line) != {"version": 1, "kind": "terminate"}:
                    raise ProtocolError("Invalid supervision control")
                stopping = True
            all_reaped = False
            while True:
                try:
                    pid, status = os.waitpid(-1, os.WNOHANG)
                except ChildProcessError:
                    all_reaped = True
                    break
                if pid == 0:
                    break
                if pid == child.pid:
                    returncode = child.returncode = os.waitstatus_to_exitcode(status)
                    stopping = True
            absent = _group_absent(child.pid)
            group_gone = group_gone or absent
            if all_reaped and absent and returncode is not None:
                control.settimeout(.05)
                control.sendall(_supervision_frame("cleanup", pid=child.pid, pgid=child.pid,
                    returncode=returncode, reaped=True, group_absent=True))
                return 0
            now = time.monotonic()
            if stopping and stop_at is None:
                stop_at = now
                if not group_gone:
                    try:
                        os.killpg(child.pid, signal.SIGTERM)
                    except ProcessLookupError:
                        group_gone = True
            if stop_at is not None:
                if now >= stop_at + .8 and not killed:
                    if not group_gone:
                        try:
                            os.killpg(child.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            group_gone = True
                    killed = True
                # Reserve time for the receipt and direct helper collection within
                # the parent's existing total two-second cleanup allowance.
                if now >= stop_at + 1.8:
                    return 2
            if not connected:
                time.sleep(.01)
            elif select.select([control], [], [], .01)[0]:
                data = control.recv(SUPERVISION_LIMIT + 1)
                if not data:
                    stopping = True
                    connected = False
                else:
                    buffered += data
                    if len(buffered) > SUPERVISION_LIMIT:
                        stopping = True
    except (Exception, KeyboardInterrupt):
        # Any error must still attempt actual group termination and reaping; an
        # absent/invalid receipt cannot be promoted to clean by the coordinator.
        if child is not None:
            if not group_gone:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except OSError:
                    pass
            until = time.monotonic() + .8
            while time.monotonic() < until:
                try:
                    pid, status = os.waitpid(-1, os.WNOHANG)
                    if pid == child.pid:
                        child.returncode = os.waitstatus_to_exitcode(status)
                    if pid == 0:
                        time.sleep(.01)
                except ChildProcessError:
                    break
        return 2
    finally:
        control.close()


async def execute_worker(assignment, on_identity, on_event, stop_requested, resume_thread_id,
                         *, worker_source, timeout, grace, poll):
    """Admit one worker and keep all SDK threads inside its owned process group."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    process = None
    accepted = {"thread_id": None, "turn_id": None}
    observed = dict(accepted)
    grants = []
    terminal = None
    outcome = None
    outcome_at = None
    stopped = False
    stop_at = None
    failure = None

    def audit(method, params):
        payload = {"method": method, "params": params}
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
        on_event(hashlib.sha256(raw.encode()).hexdigest(), payload)

    async def session():
        nonlocal process, terminal, outcome, outcome_at
        initial = _encode(_frame("assignment", 0, {
            "assignment": assignment, "resume_thread_id": resume_thread_id,
        }))
        process = OwnedProcess(
            _worker_command(worker_source), stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            limit=MAX_FRAME_BYTES,
            env=worker_environment(),
        )
        await process.start(deadline)
        audit("hydra/workerStarted", {
            "pid": process.pid, "pgid": process.pgid,
            "observed_at": datetime.now(timezone.utc).isoformat(),
        })
        process.stdin.write(initial)
        await process.stdin.drain()
        expected = 1
        while True:
            frame = _decode(await process.stdout.readline())
            if type(frame.get("seq")) is not int or frame["seq"] != expected:
                raise ProtocolError("Unexpected sequence")
            kind, data = frame.get("kind"), frame.get("data")
            if not isinstance(data, dict):
                raise ProtocolError("Invalid frame data")
            answer = {}
            if kind == "identity":
                if len(data) != 1 or next(iter(data)) not in accepted:
                    raise ProtocolError("Invalid identity fields")
                key, value = next(iter(data.items()))
                if not isinstance(value, str) or not value:
                    raise ProtocolError("Invalid identity")
                observed[key] = value
                if accepted[key] not in (None, value):
                    raise ProtocolError("Conflicting identity")
                on_identity(**data)
                accepted[key] = value
            elif kind == "event":
                if set(data) != {"event_id", "payload"} or not isinstance(data["event_id"], str) or not isinstance(data["payload"], dict):
                    raise ProtocolError("Invalid event")
                on_event(data["event_id"], data["payload"])
                payload = data["payload"]
                params = payload.get("params", {})
                if payload.get("method") == "turn/completed" and isinstance(params, dict):
                    candidate = params.get("turn", {})
                    if (isinstance(candidate, dict) and params.get("threadId") == accepted["thread_id"]
                            and candidate.get("id") == accepted["turn_id"]
                            and accepted["thread_id"] is not None and accepted["turn_id"] is not None
                            and candidate.get("status") in {"completed", "failed", "interrupted"}):
                        terminal = candidate
            elif kind == "poll":
                if data:
                    raise ProtocolError("Invalid stop poll")
                answer = {"stop": stopped or stop_requested() or loop.time() >= deadline}
            elif kind == "dispatch":
                operation = data.get("operation")
                if set(data) != {"operation"} or operation not in {"thread/start", "thread/resume", "turn/start"}:
                    raise ProtocolError("Invalid dispatch operation")
                allow = not (stopped or stop_requested() or loop.time() >= deadline)
                if allow:
                    if operation == "turn/start" and accepted["thread_id"] is None:
                        raise ProtocolError("Turn before durable thread identity")
                    audit("hydra/dispatchIntent", {"operation": operation, "sequence": expected})
                    # Even a failed/uncertain pipe write may have delivered this grant.
                    grants.append(operation)
                answer = {"allow": allow}
            elif kind == "result":
                outcome = data
                outcome_at = loop.time()
                await process.wait()
                return
            else:
                raise ProtocolError("Unexpected frame kind")
            process.stdin.write(_encode(_frame("ack", expected, answer)))
            await process.stdin.drain()
            expected += 1

    task = None
    clean = False
    try:
        if os.name != "posix":
            raise ProtocolError("POSIX host required")
        if stop_requested():
            stopped, stop_at = True, loop.time()
        else:
            task = asyncio.create_task(session())
        while task is not None:
            now = loop.time()
            if not stopped and stop_requested():
                stopped, stop_at = True, now
            cutoff = deadline + (grace if grants else 0)
            if stopped:
                cutoff = min(cutoff, stop_at + (grace if grants else 0))
            if outcome_at is not None:
                cutoff = min(cutoff, outcome_at + grace)
            if task.done():
                task.result()
                break
            if now >= cutoff:
                failure = "stop_requested" if stopped else "execution_timeout"
                break
            try:
                await asyncio.wait({task}, timeout=min(poll, cutoff - now))
            except asyncio.CancelledError:
                stopped, stop_at = True, loop.time() if stop_at is None else stop_at
    except asyncio.CancelledError:
        stopped, failure = True, "parent_cancelled"
    except Exception as exc:
        failure = type(exc).__name__
    async def finalize():
        nonlocal failure
        if task is not None and not task.done():
            task.cancel()
            # No SDK execution runs before assignment. OwnedProcess retains an
            # in-flight launch so cleanup can still collect its actual owner.
            done, _ = await asyncio.wait({task}, timeout=1.0)
            if not done:
                failure = "supervisor_cleanup_unknown"
        if task is not None and task.done() and not task.cancelled():
            task.exception()
        try:
            return await _cleanup(process)
        except Exception:
            return False

    cleanup_task = asyncio.create_task(finalize())
    while True:
        try:
            clean = await asyncio.shield(cleanup_task)
            break
        except asyncio.CancelledError:
            stopped = True

    detail = {"reason": failure or "worker_exit_without_result", "result": None,
              "items": {}, "usage": None, "terminal": terminal,
              "requested_resume_thread_id": resume_thread_id}
    result = {"status": "transport_unknown", "thread_id": observed["thread_id"],
              "turn_id": observed["turn_id"], "detail": detail}
    if not clean or failure == "supervisor_cleanup_unknown":
        detail["cleanup"] = "unknown"
        return result
    if (isinstance(outcome, dict) and isinstance(outcome.get("status"), str)
            and outcome["status"] in {"completed", "failed", "interrupted", "transport_unknown"}):
        worker_detail = outcome.get("detail")
        same_ids = all(outcome.get(key) == accepted[key] for key in accepted)
        provider_terminal = (terminal is not None and terminal.get("status") == outcome["status"])
        before_turn = (outcome["status"] == "interrupted" and "turn/start" not in grants
                       and accepted["thread_id"] is not None and accepted["turn_id"] is None
                       and isinstance(worker_detail, dict) and worker_detail.get("reason") == "stopped_before_turn")
        if isinstance(worker_detail, dict) and worker_detail.get("cleanup") != "unknown" and same_ids:
            if (provider_terminal or before_turn or (not grants and outcome["status"] in {"failed", "interrupted"})
                    or outcome["status"] == "transport_unknown"):
                worker_detail.setdefault("requested_resume_thread_id", resume_thread_id)
                return outcome
    if outcome is not None:
        detail["reason"] = "invalid_worker_result"
    if not grants:
        result["status"] = "interrupted" if stopped else "failed"
        detail["reason"] = "stopped_before_dispatch" if stopped else (failure or "before_dispatch_failure")
    return result


class _WorkerChannel:
    def __init__(self):
        self.seq = 0
        self.pending = None
        self.responses = queue.Queue(maxsize=1)

    def _control_reader(self):
        try:
            buffered = b""
            while True:
                # A daemon blocked in BufferedReader.readline can prevent clean
                # Python shutdown; raw descriptor reads own no interpreter I/O lock.
                chunk = os.read(sys.stdin.fileno(), 4096)
                if not chunk:
                    raise ProtocolError("Parent disconnected")
                buffered += chunk
                if len(buffered) > MAX_FRAME_BYTES:
                    raise ProtocolError("Control frame too large")
                while b"\n" in buffered:
                    data, buffered = buffered.split(b"\n", 1)
                    frame = _decode(data + b"\n")
                    if frame["kind"] != "ack" or frame["seq"] != self.pending:
                        raise ProtocolError("Unexpected control frame")
                    self.responses.put_nowait(frame)
        except BaseException:
            # This entry point only runs in its own newly created POSIX session.
            # KILL the group together; TERM could kill us before a resistant child.
            os.killpg(os.getpid(), signal.SIGKILL)

    def start(self):
        threading.Thread(target=self._control_reader, daemon=True).start()

    def request(self, kind, data):
        self.seq += 1
        self.pending = self.seq
        sys.stdout.buffer.write(_encode(_frame(kind, self.seq, data)))
        sys.stdout.buffer.flush()
        response = self.responses.get()
        if type(response.get("seq")) is not int or response["seq"] != self.seq or not isinstance(response.get("data"), dict):
            os.killpg(os.getpid(), signal.SIGKILL)
        self.pending = None
        expected = {"poll": "stop", "dispatch": "allow"}.get(kind)
        if ((expected is None and response["data"])
                or (expected is not None and (set(response["data"]) != {expected}
                                             or type(response["data"][expected]) is not bool))):
            os.killpg(os.getpid(), signal.SIGKILL)
        return response["data"]

    def result(self, data):
        self.seq += 1
        sys.stdout.buffer.write(_encode_result(self.seq, data))
        sys.stdout.buffer.flush()


def worker_main(execute):
    if os.name != "posix" or os.getpid() != os.getpgrp() or os.getpid() != os.getsid(0):
        raise SystemExit(2)
    initial = _decode(sys.stdin.buffer.readline(MAX_FRAME_BYTES + 1))
    if initial.get("kind") != "assignment" or initial.get("seq") != 0 or not isinstance(initial.get("data"), dict):
        raise SystemExit(2)
    channel = _WorkerChannel()
    channel.start()

    async def run():
        result = await execute(
            initial["data"]["assignment"],
            lambda **values: channel.request("identity", values),
            lambda event_id, payload: channel.request("event", {"event_id": event_id, "payload": payload}),
            lambda: channel.request("poll", {}).get("stop") is not False,
            resume_thread_id=initial["data"].get("resume_thread_id"),
            on_dispatch=lambda operation: channel.request("dispatch", {"operation": operation}).get("allow") is True,
        )
        channel.result(result)

    asyncio.run(run())


if __name__ == "__main__":
    if len(sys.argv) != 5 or sys.argv[1] != "--owned-process-helper":
        raise SystemExit(2)
    # A fixed, parent-selected entry point. SDK assignment content never enters
    # this argument vector or the separate supervision channel.
    raise SystemExit(_supervisor_main(int(sys.argv[2]), float(sys.argv[3]), json.loads(sys.argv[4])))
