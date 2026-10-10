"""No-child startup cancellation requires real helper evidence and ownership."""

import asyncio
from contextlib import ExitStack
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


SOURCE = Path(__file__).resolve()
sys.path.insert(0, str(SOURCE.parent.parent))
from hydra_sdlc import coordinator, execution_boundary as boundary


CANCELLED = {"version": 1, "kind": "launch_cancelled", "reaped": True}
BOOT = "44444444-4444-4444-8444-444444444444"


def _mark(directory, name, **values):
    with (Path(directory) / "helper-events.jsonl").open("a") as output:
        output.write(json.dumps({"name": name, **values}) + "\n")


def _events(directory):
    path = Path(directory) / "helper-events.jsonl"
    return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []


def _helper_entry(fd, deadline, command, directory, mode):
    if sys.platform != "linux":
        # Actual POSIX helper control logic; only Linux's unavailable prctl is
        # skipped on macOS. Linux CI runs the real subreaper unchanged.
        boundary._enable_subreaper = lambda: None
    native_spawn = boundary.subprocess.Popen

    def observed_spawn(*args, **kwargs):
        _mark(directory, "child_spawn_attempted")
        child = native_spawn(*args, **kwargs)
        _mark(directory, "child", pid=child.pid, pgid=child.pid)
        return child

    boundary.subprocess.Popen = observed_spawn
    if mode == "waitpid_busy":
        boundary.os.waitpid = lambda *args: (0, 0)
    elif mode == "waitpid_error":
        def uncertain_wait(*args):
            raise OSError("synthetic uncertain child collection")
        boundary.os.waitpid = uncertain_wait
    original_frame = boundary._supervision_frame

    def frame(kind, **values):
        data = original_frame(kind, **values)
        if kind != "launch_cancelled":
            return data
        # Corrupt only a receipt the actual helper produced after ECHILD.
        _mark(directory, "cancelled_receipt")
        if mode == "missing":
            return b""
        decoded = json.loads(data)
        if mode == "bad_reaped":
            decoded["reaped"] = 1
        elif mode == "extra_field":
            decoded["unexpected"] = True
        data = (json.dumps(decoded) + "\n").encode()
        return data + b'{"version":1,"kind":"unexpected"}\n' if mode == "trailing" else data

    boundary._supervision_frame = frame
    _mark(directory, "helper_entered", pid=os.getpid())
    result = boundary._supervisor_main(fd, deadline, command)
    _mark(directory, "helper_returned", code=result)
    return 3 if mode == "nonzero" and result == 0 else result


@unittest.skipUnless(os.name == "posix", "requires actual POSIX helper processes")
class StartupCancellationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.lock = self.root / "host.lock"
        self.child_marker = self.root / "child-executed"
        self.command = [sys.executable, "-I", "-c",
                        "import pathlib,sys; pathlib.Path(sys.argv[1]).write_text('executed')",
                        str(self.child_marker)]
        boot = patch.object(coordinator, "_boot_identity", return_value=BOOT)
        boot.start()
        self.addCleanup(boot.stop)

    def helper_command(self, command, fd, deadline, *, mode="valid", expired=False):
        return [sys.executable, "-I", str(SOURCE), "--actual-helper", str(fd),
                str(time.monotonic() - 1 if expired else deadline), json.dumps(command),
                str(self.root), mode]

    def assert_no_child(self):
        self.assertFalse(self.child_marker.exists())
        self.assertFalse(any(event["name"] in {"child_spawn_attempted", "child"}
                             for event in _events(self.root)), _events(self.root))

    def assert_restart(self, marker):
        if marker:
            with self.assertRaises(coordinator.HostBusy):
                with coordinator.coordinator_lock(self.lock):
                    self.fail("unconfirmed cancellation admitted a fresh execution")
            self.assertEqual(self.lock.read_bytes(), marker)
        else:
            with coordinator.coordinator_lock(self.lock):
                self.assertEqual(self.lock.read_bytes(), b"")

    def fixture_cleanup(self, process):
        # Used only after observations/assertions. Failed implementations must
        # not leak the fixture's known child group or direct helper.
        for event in _events(self.root):
            if event["name"] == "child":
                try:
                    os.killpg(event["pgid"], signal.SIGKILL)
                except ProcessLookupError:
                    pass
        if process is not None and process.poll() is None:
            process.kill()
            process.communicate(timeout=2)

    def direct_helper(self, controls, *, expired=False, valid=True, close_input=False):
        control, peer = socket.socketpair()
        control.settimeout(3)
        helper = stream = None
        try:
            if controls:
                # Queue all bytes before the helper's first read. This proves
                # coalesced/partial admission behavior without a scheduler race.
                control.sendall(controls)
            if close_input:
                control.shutdown(socket.SHUT_WR)
            helper = subprocess.Popen(
                self.helper_command(self.command, peer.fileno(), time.monotonic() + 5, expired=expired),
                pass_fds=(peer.fileno(),), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, start_new_session=True,
            )
            peer.close()
            stream = control.makefile("rb")
            first = stream.readline()
            helper.communicate(timeout=3)
            self.assert_no_child()
            if valid:
                self.assertEqual(json.loads(first), CANCELLED)
                self.assertEqual(helper.returncode, 0)
            else:
                self.assertEqual(first, b"")
                self.assertNotEqual(helper.returncode, 0)
            self.assertEqual(stream.read(1), b"")
            with self.assertRaises(ProcessLookupError):
                os.kill(helper.pid, 0)
        finally:
            self.fixture_cleanup(helper)
            if stream is not None:
                stream.close()
            control.close()
            peer.close()

    async def test_actual_helper_expiry_before_initial_frame_confirms_no_child(self):
        self.direct_helper(b"", expired=True)

    async def test_actual_helper_initial_terminate_confirms_no_child(self):
        self.direct_helper(boundary._supervision_frame("terminate"))

    async def test_actual_helper_late_launch_confirms_no_child(self):
        self.direct_helper(boundary._supervision_frame("launch"), expired=True)

    async def test_actual_helper_malformed_partial_and_eof_controls_never_admit_child(self):
        controls = (
            boundary._supervision_frame("launch") + b'{"version":1',
            boundary._supervision_frame("launch") + boundary._supervision_frame("invalid"),
            b'{"version":1,"kind":"terminate","unexpected":true}\n',
            b"",
        )
        for index, value in enumerate(controls):
            with self.subTest(case=index):
                self.direct_helper(value, valid=False, close_input=index == 3)

    async def gated_start(self, cancellation):
        handle = boundary.OwnedProcess(self.command, env=boundary.worker_environment())
        handle.linux = True
        created, release = asyncio.Event(), asyncio.Event()
        observed = []
        sent = []
        loop = asyncio.get_running_loop()
        native_create, native_send = asyncio.create_subprocess_exec, loop.sock_sendall

        async def held_launch_result(*args, **kwargs):
            process = await native_create(*args, **kwargs)
            observed.append(process)
            created.set()
            await release.wait()
            return process

        async def observe_control(channel, data):
            sent.append(json.loads(data))
            return await native_send(channel, data)

        start = None
        try:
            with coordinator.coordinator_lock(self.lock), \
                    patch.object(boundary, "_helper_command", side_effect=self.helper_command), \
                    patch.object(boundary.asyncio, "create_subprocess_exec", side_effect=held_launch_result), \
                    patch.object(loop, "sock_sendall", side_effect=observe_control):
                deadline = loop.time() + (5 if cancellation else .2)
                start = asyncio.create_task(handle.start(deadline))
                await asyncio.wait_for(created.wait(), 3)
                self.assertEqual(len(observed), 1)
                self.assertTrue(self.lock.read_bytes())
                self.assertEqual(sent, [])
                if cancellation:
                    start.cancel()
                with self.assertRaises(asyncio.CancelledError if cancellation else TimeoutError):
                    await start
                release.set()
                if cancellation:
                    # Observe the retained reader before cleanup can itself
                    # close admission. The cancelled start must already have
                    # selected terminate as its sole initial control.
                    with self.assertRaises(TimeoutError):
                        await asyncio.wait_for(asyncio.shield(handle._ready_task), 3)
                    self.assertIsNone(handle._cleanup_task)
                    self.assertTrue(sent)
                    self.assertTrue(all(frame["kind"] == "terminate" for frame in sent), sent)
                self.assertTrue(await handle.cleanup())
                self.assertEqual(handle._cancelled_launch, CANCELLED)
                self.assertIsNone(handle.pid)
                self.assertIsNone(handle.pgid)
                self.assertIsNone(handle.receipt)
                self.assertEqual(handle.process.returncode, 0)
                self.assertFalse(any(frame["kind"] == "launch" for frame in sent), sent)
                if cancellation:
                    self.assertTrue(sent)
                    self.assertTrue(all(frame["kind"] == "terminate" for frame in sent), sent)
                self.assert_no_child()
                self.assertEqual(self.lock.read_bytes(), b"")
            self.assert_restart(b"")
        finally:
            release.set()
            if start is not None and not start.done():
                start.cancel()
                await asyncio.gather(start, return_exceptions=True)
            await handle.cleanup()
            for process in observed:
                if process.returncode is None:
                    process.kill()
                await asyncio.wait_for(process.communicate(), 2)

    async def test_caller_cancel_before_first_control_sends_only_terminate(self):
        await self.gated_start(True)

    async def test_deadline_before_first_control_collects_cancelled_without_late_launch(self):
        await self.gated_start(False)

    async def consume_receipt(self, facade, *, mode="valid", clear_failure=False, stale=False, stop=False):
        handle = None
        original_confirm, original_sync = coordinator.confirm_owned_cleanup, os.fsync
        new_ticket = []
        cancellation_seen = False
        original_validate = boundary._validate_launch_cancelled

        def observe_cancellation(frame):
            nonlocal cancellation_seen
            result = original_validate(frame)
            cancellation_seen = True
            return result

        def failed_clear(fd):
            if not self.lock.read_bytes():
                raise OSError("synthetic cancellation retirement failure")
            original_sync(fd)

        def stale_clear(ticket):
            original_confirm(ticket)
            new_ticket.append(coordinator.register_owned_process())
            original_confirm(ticket)

        confirmed = mode == "valid" and not clear_failure and not stale
        with coordinator.coordinator_lock(self.lock), ExitStack() as stack:
            stack.enter_context(patch.object(boundary, "_helper_command", side_effect=lambda command, fd, deadline:
                                            self.helper_command(command, fd, deadline, mode=mode, expired=True)))
            if clear_failure:
                stack.enter_context(patch.object(coordinator.os, "fsync", side_effect=failed_clear))
            if stale:
                stack.enter_context(patch.object(coordinator, "confirm_owned_cleanup", side_effect=stale_clear))
            if stop:
                stack.enter_context(patch.object(boundary, "_validate_launch_cancelled", side_effect=observe_cancellation))
            if facade == "async":
                handle = boundary.OwnedProcess(self.command, env=boundary.worker_environment())
                handle.linux = True
                try:
                    with self.assertRaises((TimeoutError, boundary.ProtocolError)):
                        await handle.start(asyncio.get_running_loop().time() + 5)
                    self.assertTrue(self.lock.read_bytes())
                    self.assertEqual(await handle.cleanup(), confirmed)
                    self.assertIsNone(handle.pid)
                    self.assertIsNone(handle.pgid)
                    self.assertIsNotNone(handle.process.returncode)
                    if confirmed:
                        self.assertEqual(handle._cancelled_launch, CANCELLED)
                        self.assertEqual(handle.process.returncode, 0)
                finally:
                    await handle.cleanup()
            else:
                stack.enter_context(patch.object(boundary.sys, "platform", "linux"))

                def stopped():
                    return stop and cancellation_seen

                if confirmed and not stop:
                    result = boundary.run_owned_sync(self.command, cwd=self.root, env=boundary.worker_environment(),
                                                     timeout=5, stop_requested=stopped, max_output_bytes=1024)
                    self.assertLess(result.returncode, 0)
                    self.assertEqual(result.stdout, b"")
                else:
                    with self.assertRaises(boundary.OwnedCommandError) as caught:
                        boundary.run_owned_sync(self.command, cwd=self.root, env=boundary.worker_environment(),
                                                timeout=5, stop_requested=stopped, max_output_bytes=1024)
                    self.assertEqual(caught.exception.reason, "stopped" if confirmed else "cleanup_unknown")
            if stale:
                self.assertEqual(len(new_ticket), 1)
                self.assertIn(new_ticket[0][1].encode(), self.lock.read_bytes())
            self.assert_no_child()
            marker = self.lock.read_bytes()
            self.assertEqual(bool(marker), not confirmed)
        self.assert_restart(marker)

    async def test_sync_cancelled_receipt_is_nonzero_not_verification_success(self):
        await self.consume_receipt("sync")

    async def test_sync_stop_remains_stopped_after_confirmed_no_child_receipt(self):
        await self.consume_receipt("sync", stop=True)

    async def test_malformed_cancelled_receipts_hold_for_both_facades(self):
        for mode in ("bad_reaped", "extra_field"):
            for facade in ("async", "sync"):
                with self.subTest(mode=mode, facade=facade):
                    self.lock.write_bytes(b"")
                    await self.consume_receipt(facade, mode=mode)

    async def test_missing_trailing_and_nonzero_cancelled_receipts_hold_for_both_facades(self):
        for mode in ("missing", "trailing", "nonzero"):
            for facade in ("async", "sync"):
                with self.subTest(mode=mode, facade=facade):
                    self.lock.write_bytes(b"")
                    await self.consume_receipt(facade, mode=mode)

    async def test_uncertain_child_collection_cannot_emit_no_child_receipt(self):
        for mode in ("waitpid_busy", "waitpid_error"):
            for facade in ("async", "sync"):
                with self.subTest(mode=mode, facade=facade):
                    self.lock.write_bytes(b"")
                    await self.consume_receipt(facade, mode=mode)
                    self.assertFalse(any(event["name"] == "cancelled_receipt"
                                         for event in _events(self.root)))

    async def test_failed_ticket_clear_after_cancelled_receipt_holds(self):
        for facade in ("async", "sync"):
            with self.subTest(facade=facade):
                self.lock.write_bytes(b"")
                await self.consume_receipt(facade, clear_failure=True)

    async def test_stale_ticket_after_cancelled_receipt_cannot_clear_current_registration(self):
        for facade in ("async", "sync"):
            with self.subTest(facade=facade):
                self.lock.write_bytes(b"")
                await self.consume_receipt(facade, stale=True)


if __name__ == "__main__":
    if len(sys.argv) == 7 and sys.argv[1] == "--actual-helper":
        raise SystemExit(_helper_entry(int(sys.argv[2]), float(sys.argv[3]),
                                      json.loads(sys.argv[4]), sys.argv[5], sys.argv[6]))
    else:
        unittest.main()
