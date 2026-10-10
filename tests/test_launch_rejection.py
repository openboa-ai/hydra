"""Only native pre-exec rejection can retire a failed launch's ownership."""

import asyncio
from contextlib import ExitStack
import errno
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch


SOURCE = Path(__file__).resolve()
sys.path.insert(0, str(SOURCE.parent.parent))

from hydra_sdlc import coordinator, execution_boundary as boundary


BOOT = "33333333-3333-4333-8333-333333333333"
LINUX = sys.platform.startswith("linux")


@unittest.skipUnless(os.name == "posix", "requires native POSIX spawn semantics")
class LaunchRejectionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        boot = patch.object(coordinator, "_boot_identity", return_value=BOOT)
        boot.start()
        self.addCleanup(boot.stop)
        denied = self.root / "not-executable"
        denied.write_bytes(b"fixture without execution permission\n")
        denied.chmod(0o600)
        invalid = self.root / "invalid-executable"
        invalid.write_bytes(b"not an executable image\n")
        invalid.chmod(0o700)
        self.missing = self.root / "absent-executable"
        self.cases = (
            ("missing_executable", [self.missing], self.root, errno.ENOENT),
            ("permission", [denied], self.root, errno.EACCES),
            ("exec_format", [invalid], self.root, errno.ENOEXEC),
            ("missing_cwd", ["/bin/echo", "must-not-run"], self.root / "absent-cwd", errno.ENOENT),
            ("nondirectory_cwd", ["/bin/echo", "must-not-run"], denied, errno.ENOTDIR),
        )

    def assert_held(self, lock, marker):
        self.assertTrue(marker)
        self.assertEqual(lock.read_bytes(), marker)
        with self.assertRaises(coordinator.HostBusy):
            with coordinator.coordinator_lock(lock):
                self.fail("uncertain ownership admitted a fresh execution")
        self.assertEqual(lock.read_bytes(), marker)

    async def start_rejected(self, command, cwd):
        # Public OwnedProcess accepts string argv. Path inputs are exercised at
        # the native predicate separately without changing helper serialization.
        handle = boundary.OwnedProcess([os.fspath(value) for value in command], cwd=cwd,
                                       env=boundary.worker_environment())
        # Keep the caller-visible native error for these assertions. A separate
        # regression explicitly clears its traceback before cleanup.
        try:
            await handle.start(asyncio.get_running_loop().time() + 5)
        except (OSError, boundary.OwnedCommandError) as error:
            failure = error
        else:
            await handle.cleanup()
            self.fail("native rejected command unexpectedly started")
        self.assertIsNone(handle.pid)
        self.assertIsNone(handle.pgid)
        return handle, failure

    def run_sync(self, command, cwd):
        return boundary.run_owned_sync([os.fspath(value) for value in command], cwd=cwd,
                                       env=boundary.worker_environment(), timeout=5,
                                       max_output_bytes=1024)

    async def test_real_async_native_rejections_clear_only_after_cleanup(self):
        for name, command, cwd, expected in self.cases:
            with self.subTest(case=name):
                lock = self.root / (name + ".lock")
                with coordinator.coordinator_lock(lock):
                    handle, error = await self.start_rejected(command, cwd)
                    try:
                        self.assertTrue(lock.read_bytes())
                        if LINUX and cwd == self.root:
                            self.assertIsInstance(error, boundary.OwnedCommandError)
                            self.assertEqual(error.reason, "unavailable")
                            self.assertEqual(handle._rejection,
                                             {"version": 1, "kind": "launch_rejected",
                                              "errno": expected, "reaped": True})
                        else:
                            self.assertIsInstance(error, OSError)
                            self.assertEqual(error.errno, expected)
                        self.assertTrue(await handle.cleanup())
                        if handle.process is not None:
                            self.assertEqual(handle.process.returncode, 0)
                            with self.assertRaises(ProcessLookupError):
                                os.kill(handle.process.pid, 0)
                        self.assertEqual(lock.read_bytes(), b"")
                    finally:
                        await handle.cleanup()
                with coordinator.coordinator_lock(lock):
                    pass

    async def test_async_rejection_evidence_survives_caller_traceback_clearing(self):
        # Invalid cwd rejects the outer native launch on both platforms. Missing
        # executable additionally exercises the actual Linux helper's receipt.
        attempts = ((["/bin/echo", "must-not-run"], self.root / "absent-cwd"),
                    ([self.missing], self.root))
        for index, (command, cwd) in enumerate(attempts):
            with self.subTest(attempt=index):
                lock = self.root / f"traceback-{index}.lock"
                with coordinator.coordinator_lock(lock):
                    handle, error = await self.start_rejected(command, cwd)
                    try:
                        self.assertTrue(lock.read_bytes())
                        # unittest.assertRaises and ordinary callers may discard
                        # this traceback after catching the launch exception.
                        error.__traceback__ = None
                        self.assertFalse(boundary._native_launch_rejected(error, command, cwd))
                        self.assertTrue(await handle.cleanup())
                        self.assertEqual(lock.read_bytes(), b"")
                    finally:
                        await handle.cleanup()
                with coordinator.coordinator_lock(lock):
                    pass

    async def test_linux_style_outer_cwd_rejection_retains_exact_launch_proof(self):
        # Exercise the concurrent ready reader on every POSIX host. Native cwd
        # rejection prevents the helper executable from running, including on
        # macOS; no Linux subprocess implementation or result is simulated.
        for name, command, cwd, expected in self.cases:
            if name not in {"missing_cwd", "nondirectory_cwd"}:
                continue
            with self.subTest(case=name):
                lock = self.root / ("linux-outer-" + name + ".lock")
                handle = boundary.OwnedProcess(command, cwd=cwd, env=boundary.worker_environment())
                handle.linux = True
                loop = asyncio.get_running_loop()
                with coordinator.coordinator_lock(lock), \
                        patch.object(loop, "sock_sendall", wraps=loop.sock_sendall) as send_control:
                    try:
                        # assertRaises clears the caller's exception traceback.
                        # Only the evidence captured by the exact launch task
                        # before another reader awaits it can permit cleanup.
                        with self.assertRaises(OSError) as caught:
                            await handle.start(loop.time() + 5)
                        self.assertEqual(caught.exception.errno, expected)
                        self.assertIsNone(caught.exception.__traceback__)
                        self.assertTrue(lock.read_bytes())
                        self.assertIsNone(handle.process)
                        self.assertIsNone(handle.pid)
                        self.assertIsNone(handle.pgid)
                        self.assertIsNone(handle._rejection)
                        self.assertIsNone(handle.receipt)
                        self.assertIsNone(handle._receipt_task)
                        self.assertIsNotNone(handle._ready_task)
                        self.assertTrue(handle._ready_task.done())
                        self.assertTrue(handle._launch.done())
                        self.assertFalse(handle._launch.cancelled())
                        self.assertIs(handle._rejected_launch, handle._launch)
                        self.assertFalse(handle._launch_sent)
                        send_control.assert_not_called()
                        self.assertTrue(await handle.cleanup())
                        send_control.assert_not_called()
                        self.assertEqual(lock.read_bytes(), b"")
                    finally:
                        await handle.cleanup()
                with coordinator.coordinator_lock(lock):
                    pass

    async def test_real_sync_native_rejections_are_unavailable_and_allow_fresh_lock(self):
        for name, command, cwd, _ in self.cases:
            with self.subTest(case=name):
                lock = self.root / (name + ".lock")
                with coordinator.coordinator_lock(lock):
                    with self.assertRaises(boundary.OwnedCommandError) as caught:
                        self.run_sync(command, cwd)
                    self.assertEqual(caught.exception.reason, "unavailable")
                    self.assertEqual(lock.read_bytes(), b"")
                with coordinator.coordinator_lock(lock):
                    pass

    async def test_native_provenance_accepts_real_errors_and_rejects_wrong_attempt_or_fabrication(self):
        for name, command, cwd, expected in self.cases:
            with self.subTest(case=name):
                try:
                    subprocess.Popen(command, cwd=cwd, start_new_session=True,
                                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                                     stderr=subprocess.DEVNULL)
                except OSError as observed:
                    error = observed
                else:
                    self.fail("native rejected command unexpectedly executed")
                self.assertEqual(error.errno, expected)
                self.assertTrue(boundary._native_launch_rejected(error, command, cwd))
                self.assertFalse(boundary._native_launch_rejected(error, ["/different/executable"], "/different/cwd"))
                try:
                    raise OSError(error.errno, "matching fabricated error", error.filename)
                except OSError as fabricated:
                    self.assertFalse(boundary._native_launch_rejected(fabricated, command, cwd))
                error.errno = errno.EIO
                self.assertFalse(boundary._native_launch_rejected(error, command, cwd))

    async def test_execution_rejection_is_failed_without_assignment_or_dispatch(self):
        identities, events = Mock(), Mock()
        lock = self.root / "execution.lock"
        with coordinator.coordinator_lock(lock), \
                patch.object(boundary, "_worker_command", return_value=[str(self.missing)]):
            result = await boundary.execute_worker(
                {"cwd": str(self.root), "task": "must not dispatch"}, identities, events,
                lambda: False, None, worker_source=boundary.__file__, timeout=5, grace=.05, poll=.005,
            )
            self.assertEqual(result["status"], "failed")
            self.assertIsNone(result["thread_id"])
            self.assertIsNone(result["turn_id"])
            identities.assert_not_called()
            events.assert_not_called()
            self.assertNotIn("cleanup", result["detail"])
            self.assertEqual(lock.read_bytes(), b"")
        with coordinator.coordinator_lock(lock):
            pass

    async def test_matching_post_spawn_and_generic_errors_cannot_retire_ownership(self):
        real_popen = subprocess.Popen
        for facade in ("async", "sync"):
            for matching in (False, True):
                with self.subTest(facade=facade, matching=matching):
                    lock = self.root / f"post-spawn-{facade}-{matching}.lock"
                    observed = []

                    def fail_after_spawn(command, *args, **kwargs):
                        self.assertTrue(lock.read_bytes())
                        # Reap the fixture child before raising, so the test
                        # leaks nothing. The caller still has no native rejection
                        # provenance and must retain its durable uncertainty.
                        child = real_popen([sys.executable, "-I", "-c", "pass"], *args, **kwargs)
                        observed.append(child)
                        child.communicate(timeout=2)
                        if matching:
                            raise FileNotFoundError(errno.ENOENT, "post-spawn transport failure", command[0])
                        raise OSError(errno.EIO, "generic transport failure")

                    with coordinator.coordinator_lock(lock), \
                            patch.object(boundary.subprocess, "Popen", side_effect=fail_after_spawn):
                        if facade == "async":
                            handle, _ = await self.start_rejected(["/bin/echo", "unused"], self.root)
                            self.assertFalse(await handle.cleanup())
                        else:
                            with self.assertRaises(boundary.OwnedCommandError) as caught:
                                self.run_sync(["/bin/echo", "unused"], self.root)
                            self.assertEqual(caught.exception.reason, "cleanup_unknown")
                        marker = lock.read_bytes()
                    self.assertEqual(len(observed), 1)
                    self.assertEqual(observed[0].returncode, 0)
                    self.assert_held(lock, marker)

    async def test_failed_clear_after_real_rejection_preserves_pending_marker(self):
        real_sync = os.fsync
        for facade in ("async", "sync"):
            with self.subTest(facade=facade):
                lock = self.root / ("clear-" + facade + ".lock")

                def refuse_empty(fd):
                    if not lock.read_bytes():
                        raise OSError("synthetic retirement fsync failure")
                    real_sync(fd)

                with coordinator.coordinator_lock(lock), \
                        patch.object(coordinator.os, "fsync", side_effect=refuse_empty):
                    if facade == "async":
                        handle, _ = await self.start_rejected([self.missing], self.root)
                        self.assertFalse(await handle.cleanup())
                    else:
                        with self.assertRaises(boundary.OwnedCommandError) as caught:
                            self.run_sync([self.missing], self.root)
                        self.assertEqual(caught.exception.reason, "cleanup_unknown")
                    marker = lock.read_bytes()
                self.assert_held(lock, marker)

    async def test_stale_live_ticket_after_real_rejection_cannot_clear_a_new_registration(self):
        original_confirm = coordinator.confirm_owned_cleanup
        for facade in ("async", "sync"):
            with self.subTest(facade=facade):
                lock = self.root / ("stale-" + facade + ".lock")
                replacement = []

                def retire_then_register(ticket):
                    original_confirm(ticket)
                    replacement.append(coordinator.register_owned_process())
                    original_confirm(ticket)

                with coordinator.coordinator_lock(lock), \
                        patch.object(coordinator, "confirm_owned_cleanup", side_effect=retire_then_register):
                    if facade == "async":
                        handle, _ = await self.start_rejected([self.missing], self.root)
                        self.assertFalse(await handle.cleanup())
                    else:
                        with self.assertRaises(boundary.OwnedCommandError) as caught:
                            self.run_sync([self.missing], self.root)
                        self.assertEqual(caught.exception.reason, "cleanup_unknown")
                    self.assertEqual(len(replacement), 1)
                    marker = lock.read_bytes()
                    self.assertIn(replacement[0][1].encode(), marker)
                self.assert_held(lock, marker)


def _portable_helper(fd, command, mode):
    """Real socket and native failed exec; no Linux adoption claim or SDK."""
    control = socket.socket(fileno=fd)
    stream = control.makefile("rb")
    assert json.loads(stream.readline()) == {"version": 1, "kind": "launch"}
    try:
        subprocess.Popen(command, close_fds=True, start_new_session=True,
                         stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL)
    except FileNotFoundError as error:
        assert error.errno == errno.ENOENT
    else:
        raise AssertionError("fixture unexpectedly executed its missing command")
    try:
        os.waitpid(-1, os.WNOHANG)
    except ChildProcessError:
        pass
    else:
        raise AssertionError("native rejection left an uncollected fixture child")
    if mode != "missing":
        frame = {"version": 1, "kind": "launch_rejected", "errno": errno.ENOENT, "reaped": True}
        if mode == "bad_reaped":
            frame["reaped"] = 1
        elif mode == "bad_errno":
            frame["errno"] = errno.EIO
        elif mode == "extra_field":
            frame["unexpected"] = True
        data = (json.dumps(frame) + "\n").encode()
        if mode == "extra_frame":
            data += b'{"version":1,"kind":"unexpected"}\n'
        control.sendall(data)
    stream.close()
    control.close()
    return 3 if mode == "nonzero" else 0


@unittest.skipUnless(os.name == "posix", "requires POSIX private control socket")
class LaunchRejectionProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def check_mode(self, mode):
        for facade in ("async", "sync"):
            with self.subTest(facade=facade, mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                lock = root / "host.lock"
                command = [str(root / "absent-executable")]

                def helper_command(command, fd, deadline):
                    return [sys.executable, "-I", str(SOURCE), "--portable-helper", str(fd),
                            json.dumps(command), mode]

                with patch.object(coordinator, "_boot_identity", return_value=BOOT):
                    with coordinator.coordinator_lock(lock), \
                            patch.object(boundary, "_helper_command", side_effect=helper_command), ExitStack() as stack:
                        if facade == "async":
                            handle = boundary.OwnedProcess(command, env=boundary.worker_environment())
                            handle.linux = True
                            try:
                                with self.assertRaises((boundary.OwnedCommandError, boundary.ProtocolError)):
                                    await handle.start(asyncio.get_running_loop().time() + 5)
                                self.assertTrue(lock.read_bytes())
                                self.assertEqual(await handle.cleanup(), mode == "valid")
                                self.assertIsNotNone(handle.process)
                                self.assertIsNotNone(handle.process.returncode)
                            finally:
                                await handle.cleanup()
                        else:
                            stack.enter_context(patch.object(boundary.sys, "platform", "linux"))
                            with self.assertRaises(boundary.OwnedCommandError) as caught:
                                boundary.run_owned_sync(command, cwd=root, env=boundary.worker_environment(),
                                                        timeout=5, max_output_bytes=1024)
                            self.assertEqual(caught.exception.reason,
                                             "unavailable" if mode == "valid" else "cleanup_unknown")
                        marker = lock.read_bytes()
                        self.assertEqual(bool(marker), mode != "valid")
                    if mode == "valid":
                        with coordinator.coordinator_lock(lock):
                            pass
                    else:
                        with self.assertRaises(coordinator.HostBusy):
                            with coordinator.coordinator_lock(lock):
                                self.fail("unconfirmed rejection admitted a fresh execution")
                        self.assertEqual(lock.read_bytes(), marker)

    async def test_valid_first_frame_requires_actual_native_reaping_exit_and_eof(self):
        await self.check_mode("valid")

    async def test_malformed_rejection_receipts_keep_pending_ownership(self):
        for mode in ("bad_reaped", "bad_errno", "extra_field"):
            await self.check_mode(mode)

    async def test_extra_control_frame_keeps_pending_ownership(self):
        await self.check_mode("extra_frame")

    async def test_nonzero_helper_exit_keeps_pending_ownership(self):
        await self.check_mode("nonzero")

    async def test_missing_rejection_receipt_keeps_pending_ownership(self):
        await self.check_mode("missing")


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--portable-helper":
        raise SystemExit(_portable_helper(int(sys.argv[2]), json.loads(sys.argv[3]), sys.argv[4]))
    else:
        unittest.main()
