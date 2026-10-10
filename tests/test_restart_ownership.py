"""Durable host ownership survives wrappers; only confirmed cleanup retires it."""

import asyncio
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


SOURCE = Path(__file__).resolve()
REPOSITORY = SOURCE.parent.parent
sys.path.insert(0, str(REPOSITORY))

from hydra_sdlc import coordinator, execution_boundary as boundary
from hydra_sdlc.cli import operate, parser


BOOT = "11111111-1111-4111-8111-111111111111"
NEXT_BOOT = "22222222-2222-4222-8222-222222222222"


async def _assert_cli_held(lock, command="run"):
    target = (["--issue", "https://github.com/example/product/issues/1"]
              if command == "run" else ["--repos", "example/product"])
    args = parser().parse_args([
        command, *target, "--workspace-root", str(lock.parent / "workspaces"),
        "--host-alias", "test-host", "--lock-path", str(lock),
    ])
    capabilities, execute = AsyncMock(), AsyncMock()

    async def dispatch(*args, **kwargs):
        await capabilities()
        await execute()
        raise AssertionError("pending ownership reached runtime dispatch")

    runner = SimpleNamespace(stop_requested=lambda: False,
                             step=AsyncMock(side_effect=dispatch),
                             cycle=AsyncMock(side_effect=dispatch))
    # No wrapper enumeration or provider operation can be responsible for this
    # refusal: admission must fail on the actual persisted ownership marker.
    with patch("hydra_sdlc.runner.Runner", return_value=runner), \
            patch("hydra_sdlc.cli.residual_workers", return_value=[]) as residual:
        try:
            await operate(args, github=object(), workspace=object(),
                          capabilities=capabilities, execute=execute, emit=lambda _: None)
        except coordinator.HostBusy:
            pass
        else:
            raise AssertionError("pending owner admitted a fresh runtime")
    runner.step.assert_not_called()
    runner.cycle.assert_not_called()
    capabilities.assert_not_called()
    execute.assert_not_called()
    residual.assert_not_called()


class OwnershipRecordTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.lock = Path(directory.name) / "host.lock"
        self.boot = patch.object(coordinator, "_boot_identity", return_value=BOOT)
        self.boot.start()
        self.addCleanup(self.boot.stop)

    def pending(self):
        with coordinator.coordinator_lock(self.lock):
            ticket = coordinator.register_owned_process()
            self.assertIsNotNone(ticket)
        return ticket, self.lock.read_bytes()

    def assert_held(self):
        with self.assertRaises(coordinator.HostBusy):
            with coordinator.coordinator_lock(self.lock):
                self.fail("unresolved ownership admitted")

    def test_single_fsynced_marker_cannot_be_overwritten_or_cleared_by_another_ticket(self):
        real_sync = os.fsync
        with coordinator.coordinator_lock(self.lock):
            inode = self.lock.stat().st_ino
            with patch.object(coordinator.os, "fsync", wraps=real_sync) as sync:
                ticket = coordinator.register_owned_process()
                sync.assert_called_once()
            marker = self.lock.read_bytes()
            self.assertIn(BOOT.encode(), marker)
            with self.assertRaises(coordinator.HostBusy):
                coordinator.register_owned_process()
            with self.assertRaises(coordinator.HostBusy):
                coordinator.confirm_owned_cleanup((ticket[0], ticket[1]))
            self.assertEqual(self.lock.read_bytes(), marker)
            coordinator.confirm_owned_cleanup(ticket)
            self.assertEqual(self.lock.read_bytes(), b"")
            next_ticket = coordinator.register_owned_process()
            self.assertNotEqual(next_ticket[1], ticket[1])
            with self.assertRaises(coordinator.HostBusy):
                coordinator.confirm_owned_cleanup(ticket)
            self.assertNotEqual(self.lock.read_bytes(), marker)
            coordinator.confirm_owned_cleanup(next_ticket)
            self.assertEqual(self.lock.stat().st_ino, inode)
        with coordinator.coordinator_lock(self.lock):
            self.assertEqual(self.lock.stat().st_ino, inode)
        self.assertEqual(list(self.lock.parent.iterdir()), [self.lock])
        self.assertIsNone(coordinator.register_owned_process())
        coordinator.confirm_owned_cleanup(None)

    def test_context_exit_and_stale_live_handle_do_not_retire_pending_ownership(self):
        ticket, marker = self.pending()
        with self.assertRaises(coordinator.HostBusy):
            coordinator.confirm_owned_cleanup(ticket)
        for command in ("run", "serve"):
            asyncio.run(_assert_cli_held(self.lock, command))
        self.assertEqual(self.lock.read_bytes(), marker)

    def test_verified_new_boot_retires_pending_marker_without_replacing_inode(self):
        _, marker = self.pending()
        inode = self.lock.stat().st_ino
        self.assert_held()
        with patch.object(coordinator, "_boot_identity", return_value=NEXT_BOOT):
            with coordinator.coordinator_lock(self.lock):
                self.assertEqual(self.lock.read_bytes(), b"")
                ticket = coordinator.register_owned_process()
                self.assertIn(NEXT_BOOT.encode(), self.lock.read_bytes())
                self.assertNotEqual(self.lock.read_bytes(), marker)
                coordinator.confirm_owned_cleanup(ticket)
        self.assertEqual(self.lock.stat().st_ino, inode)

    def test_corrupt_truncated_and_unknown_version_records_hold_without_rewriting(self):
        _, valid = self.pending()
        for value in (b"x", valid[:-1], valid.replace(b"v1", b"v2", 1),
                      valid.replace(BOOT.encode(), b"z" * len(BOOT), 1), valid + b"x"):
            with self.subTest(value=value):
                self.lock.write_bytes(value)
                self.assert_held()
                self.assertEqual(self.lock.read_bytes(), value)

    def test_missing_boot_and_unreadable_record_never_admit_even_an_empty_lock(self):
        for pending in (False, True):
            with self.subTest(pending=pending):
                if pending:
                    self.pending()
                else:
                    self.lock.write_bytes(b"")
                before = self.lock.read_bytes()
                with patch.object(coordinator, "_boot_identity", side_effect=coordinator.HostBusy("unavailable")):
                    self.assert_held()
                with patch.object(coordinator.os, "pread", side_effect=OSError("synthetic read failure")):
                    with self.assertRaises((coordinator.HostBusy, OSError)):
                        with coordinator.coordinator_lock(self.lock):
                            self.fail("unreadable ownership admitted")
                self.assertEqual(self.lock.read_bytes(), before)

    def test_partial_registration_and_failed_fsync_leave_a_blocking_record(self):
        for failure in ("partial", "fsync"):
            with self.subTest(failure=failure):
                self.lock.write_bytes(b"")
                with coordinator.coordinator_lock(self.lock):
                    real_write = os.pwrite

                    def partial(fd, value, offset):
                        return real_write(fd, value[:9], offset)

                    target = "pwrite" if failure == "partial" else "fsync"
                    effect = partial if failure == "partial" else OSError("synthetic fsync failure")
                    with patch.object(coordinator.os, target, side_effect=effect):
                        with self.assertRaises((coordinator.HostBusy, OSError)):
                            coordinator.register_owned_process()
                    self.assertTrue(self.lock.read_bytes())
                    with self.assertRaises(coordinator.HostBusy):
                        coordinator.register_owned_process()
                self.assert_held()

    def test_failed_clear_preserves_exact_marker_and_holds_same_boot_restart(self):
        for failure in ("ftruncate", "fsync"):
            with self.subTest(failure=failure):
                self.lock.write_bytes(b"")
                with coordinator.coordinator_lock(self.lock):
                    ticket = coordinator.register_owned_process()
                    marker = self.lock.read_bytes()
                    with patch.object(coordinator.os, failure, side_effect=OSError("synthetic clear failure")):
                        with self.assertRaises((coordinator.HostBusy, OSError)):
                            coordinator.confirm_owned_cleanup(ticket)
                    self.assertEqual(self.lock.read_bytes(), marker)
                    with self.assertRaises(coordinator.HostBusy):
                        coordinator.register_owned_process()
                self.assert_held()


@unittest.skipUnless(os.name == "posix", "requires owned POSIX process supervision")
class OwnedRegistrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.lock = Path(directory.name) / "host.lock"
        boot = patch.object(coordinator, "_boot_identity", return_value=BOOT)
        boot.start()
        self.addCleanup(boot.stop)

    async def test_async_registration_is_durable_before_spawn_and_only_cleanup_clears(self):
        handle = boundary.OwnedProcess(["/bin/echo", "owned"])
        real_create, real_sync = asyncio.create_subprocess_exec, os.fsync
        synced = []

        def sync(fd):
            real_sync(fd)
            synced.append(self.lock.read_bytes())

        async def launch(*args, **kwargs):
            self.assertTrue(synced)
            self.assertEqual(self.lock.read_bytes(), synced[-1])
            self.assertTrue(synced[-1])
            return await real_create(*args, **kwargs)

        with coordinator.coordinator_lock(self.lock):
            try:
                with patch.object(coordinator.os, "fsync", side_effect=sync), \
                        patch.object(boundary.asyncio, "create_subprocess_exec", side_effect=launch) as spawned:
                    await handle.start(asyncio.get_running_loop().time() + 5)
                    self.assertEqual((await handle.communicate())[0], b"owned\n")
                    spawned.assert_called_once()
                self.assertTrue(self.lock.read_bytes())
                self.assertTrue(await handle.cleanup())
                self.assertEqual(self.lock.read_bytes(), b"")
            finally:
                await handle.cleanup()
        with coordinator.coordinator_lock(self.lock):
            pass

    async def test_sync_facade_registers_and_clears_inside_active_event_loop(self):
        real_popen, real_sync = boundary.subprocess.Popen, os.fsync
        synced = []

        def sync(fd):
            real_sync(fd)
            synced.append(self.lock.read_bytes())

        def launch(*args, **kwargs):
            self.assertTrue(synced and synced[-1])
            self.assertEqual(self.lock.read_bytes(), synced[-1])
            return real_popen(*args, **kwargs)

        with coordinator.coordinator_lock(self.lock):
            with patch.object(coordinator.os, "fsync", side_effect=sync), \
                    patch.object(boundary.subprocess, "Popen", side_effect=launch) as spawned:
                result = boundary.run_owned_sync(["/bin/echo", "sync-owned"], cwd=self.lock.parent,
                                                env=boundary.worker_environment(), timeout=5,
                                                max_output_bytes=1024)
                spawned.assert_called_once()
            self.assertEqual(result.stdout, b"sync-owned\n")
            self.assertEqual(result.returncode, 0)
            self.assertEqual(self.lock.read_bytes(), b"")
        with coordinator.coordinator_lock(self.lock):
            pass

    async def test_registration_write_failure_prevents_either_native_spawn(self):
        for mode in ("async", "sync"):
            with self.subTest(mode=mode), coordinator.coordinator_lock(self.lock):
                with patch.object(coordinator.os, "pwrite", side_effect=OSError("synthetic write failure")), \
                        patch.object(boundary.asyncio, "create_subprocess_exec", new_callable=AsyncMock) as create, \
                        patch.object(boundary.subprocess, "Popen") as popen:
                    if mode == "async":
                        handle = boundary.OwnedProcess(["/bin/echo", "must-not-spawn"])
                        try:
                            with self.assertRaises((OSError, coordinator.HostBusy)):
                                await handle.start(asyncio.get_running_loop().time() + 5)
                        finally:
                            await handle.cleanup()
                    else:
                        with self.assertRaises(boundary.OwnedCommandError):
                            boundary.run_owned_sync(["/bin/echo", "must-not-spawn"], cwd=self.lock.parent,
                                                    env=boundary.worker_environment(), timeout=5,
                                                    max_output_bytes=1024)
                    create.assert_not_called()
                    popen.assert_not_called()

    async def test_unknown_pre_ready_launch_retains_marker_before_test_reaping(self):
        handle = boundary.OwnedProcess(["/bin/sleep", "60"], stdout=asyncio.subprocess.DEVNULL)
        created = asyncio.Event()
        observed = []
        real_create = asyncio.create_subprocess_exec

        async def delayed_result(*args, **kwargs):
            process = await real_create(*args, **kwargs)
            observed.append(process)
            created.set()
            await asyncio.Event().wait()
            return process

        try:
            with coordinator.coordinator_lock(self.lock):
                with patch.object(boundary.asyncio, "create_subprocess_exec", side_effect=delayed_result):
                    start = asyncio.create_task(handle.start(asyncio.get_running_loop().time() + 5))
                    await asyncio.wait_for(created.wait(), 3)
                    start.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await start
                    with patch.object(boundary, "CLEANUP_SECONDS", .1):
                        self.assertFalse(await handle.cleanup())
                self.assertIsNone(handle.pid)
                marker = self.lock.read_bytes()
                self.assertTrue(marker)
            await _assert_cli_held(self.lock)
            self.assertEqual(self.lock.read_bytes(), marker)
        finally:
            # This is fixture-only cleanup after restart refusal is observed.
            # It cannot retroactively confirm the original live handle's ticket.
            for process in observed:
                if process.returncode is None:
                    process.kill()
                await asyncio.wait_for(process.communicate(), 2)

    async def test_sync_spawn_failure_after_registration_holds_fresh_runtime(self):
        with coordinator.coordinator_lock(self.lock):
            with patch.object(boundary.subprocess, "Popen", side_effect=OSError("synthetic launch failure")):
                with self.assertRaises(boundary.OwnedCommandError) as caught:
                    boundary.run_owned_sync(["/bin/echo", "unavailable"], cwd=self.lock.parent,
                                            env=boundary.worker_environment(), timeout=5,
                                            max_output_bytes=1024)
            self.assertEqual(caught.exception.reason, "cleanup_unknown")
            marker = self.lock.read_bytes()
            self.assertTrue(marker)
        await _assert_cli_held(self.lock)
        self.assertEqual(self.lock.read_bytes(), marker)

    async def test_failed_confirmation_is_unknown_for_both_facades_and_preserves_restart_hold(self):
        for mode in ("async", "sync"):
            with self.subTest(mode=mode):
                self.lock.write_bytes(b"")
                with coordinator.coordinator_lock(self.lock):
                    real_sync = os.fsync

                    def reject_clear(fd):
                        if not self.lock.read_bytes():
                            raise OSError("synthetic clear fsync failure")
                        return real_sync(fd)

                    with patch.object(coordinator.os, "fsync", side_effect=reject_clear):
                        if mode == "async":
                            handle = boundary.OwnedProcess(["/bin/echo", "done"])
                            await handle.start(asyncio.get_running_loop().time() + 5)
                            await handle.communicate()
                            self.assertFalse(await handle.cleanup())
                        else:
                            with self.assertRaises(boundary.OwnedCommandError) as caught:
                                boundary.run_owned_sync(["/bin/echo", "done"], cwd=self.lock.parent,
                                                        env=boundary.worker_environment(), timeout=5,
                                                        max_output_bytes=1024)
                            self.assertEqual(caught.exception.reason, "cleanup_unknown")
                    marker = self.lock.read_bytes()
                    self.assertTrue(marker)
                await _assert_cli_held(self.lock)
                self.assertEqual(self.lock.read_bytes(), marker)


def _command(role, mode, directory):
    return [sys.executable, "-I", str(SOURCE), role, mode, str(directory)]


def _support():
    sys.path.insert(0, str(SOURCE.parent))
    import test_process_supervision as support
    return support


def _worker(directory):
    support = _support()
    support._mark(directory, "worker", pid=os.getpid(), pgid=os.getpgrp())
    # The surviving executable is a platform binary, with inherited TERM
    # resistance. No SDK, authentication, shell environment dump or network.
    child = subprocess.Popen(["/bin/sh", "-c", "trap '' TERM; printf 'ready\\n'; exec /bin/sleep 60"],
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.DEVNULL)
    assert child.stdout.readline() == b"ready\n"
    child.stdout.close()
    support._mark(directory, "descendant", pid=child.pid)
    assert sys.stdin.buffer.readline() == b"exit\n"


async def _owner(directory):
    support = _support()
    lock = Path(directory) / "host.lock"
    linux = sys.platform.startswith("linux")
    command = (["/bin/sh", "-c", 'trap \'\' TERM; printf "%s\\n" "$$" > "$1"; exec /bin/sleep 60',
                "platform-fixture", str(Path(directory) / "platform.pid")]
               if linux else _command("--worker", "unused", directory))
    handle = boundary.OwnedProcess(command,
                                   stdout=asyncio.subprocess.DEVNULL)
    with coordinator.coordinator_lock(lock):
        await handle.start(asyncio.get_running_loop().time() + 5)
        support._mark(directory, "outer", pid=handle.process.pid)
        if linux:
            # A platform worker below the actual helper avoids a race with the
            # helper's ordinary direct-worker-exit cleanup. Its private launch
            # and ready handshake are unchanged; only the fixture helper dies.
            deadline = asyncio.get_running_loop().time() + 3
            marker = Path(directory) / "platform.pid"
            while not marker.exists():
                if asyncio.get_running_loop().time() >= deadline:
                    raise TimeoutError("platform worker did not start")
                await asyncio.sleep(.005)
            assert int(marker.read_text()) == handle.pid
            support._mark(directory, "descendant", pid=handle.pid, pgid=handle.pgid)
            handle.process.kill()
        else:
            await support._wait_for_descendant(directory)
            handle.stdin.write(b"exit\n")
            await handle.stdin.drain()
        await asyncio.wait_for(handle.process.wait(), 3)
        assert lock.read_bytes()
        # Deliberately omit cleanup: neither wrapper exit nor group state is a
        # cleanup receipt, so leaving this context must retain the ticket.


async def _scenario(directory):
    support = _support()
    owner = subprocess.Popen(_command("--owner", "unused", directory),
                             stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                             stderr=subprocess.PIPE)
    try:
        output, errors = await asyncio.to_thread(owner.communicate, timeout=8)
        assert owner.returncode == 0, (output, errors)
        support._mark(directory, "owner", pid=owner.pid)
        rows = support._observations(directory)
        descendant = next(row["pid"] for row in rows if row["name"] == "descendant")
        for row in rows:
            if row["name"] != "descendant":
                try:
                    os.kill(row["pid"], 0)
                except ProcessLookupError:
                    continue
                raise AssertionError("recognizable Python wrapper remains")
        os.kill(descendant, 0)
        # Verify the actual survivor's executable, not only its fixture label.
        # This bounded query inspects only the already observed child PID.
        deadline = asyncio.get_running_loop().time() + 2
        while True:
            observed = subprocess.run(["ps", "-p", str(descendant), "-o", "comm="],
                                      capture_output=True, text=True, check=True, timeout=2)
            if Path(observed.stdout.strip()).name == "sleep":
                break
            if asyncio.get_running_loop().time() >= deadline:
                raise AssertionError("survivor did not become the platform sleep executable")
            await asyncio.sleep(.005)
        lock = Path(directory) / "host.lock"
        marker = lock.read_bytes()
        assert marker
        await _assert_cli_held(lock, "run")
        await _assert_cli_held(lock, "serve")
        assert lock.read_bytes() == marker
        os.kill(descendant, 0)
        return {"held_before_capabilities_and_model": True, "descendant": descendant,
                "platform_executable": "sleep"}
    finally:
        if owner.poll() is None:
            owner.kill()
            owner.communicate(timeout=2)


def _portable_driver(directory):
    support = _support()
    supervisor = None
    report = {}
    try:
        supervisor = subprocess.Popen(_command("--supervisor", "unused", directory),
                                      stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                      stderr=subprocess.PIPE, text=True)
        output, errors = supervisor.communicate(timeout=12)
        report.update(returncode=supervisor.returncode, stderr=errors,
                      supervisor=json.loads(output) if supervisor.returncode == 0 else None)
        rows = support._observations(directory)
        report["observations"] = rows
        report["present_pids"] = support._present(rows, "pid", os.kill)
    finally:
        if supervisor is not None and supervisor.poll() is None:
            supervisor.kill()
            supervisor.communicate(timeout=2)
        rows = support._observations(directory)
        # This driver cannot reap adopted children on macOS. Kill only this
        # fixture's observed groups after its liveness/refusal oracle, then
        # confirm that the platform reaped them. This is not Linux evidence.
        for pgid in {row["pgid"] for row in rows if "pgid" in row}:
            try:
                os.killpg(pgid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        deadline = time.monotonic() + 4
        while support._present(rows, "pid", os.kill) and time.monotonic() < deadline:
            time.sleep(.01)
        report["fallback_cleanup_complete"] = not support._present(rows, "pid", os.kill)
    return report


class RestartTopologyTests(unittest.TestCase):
    def check_driver(self, linux):
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(_command("--driver", "unused", directory),
                                       capture_output=True, text=True, timeout=22)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["fallback_cleanup_complete"], report)
        self.assertEqual(report["returncode"], 0, report["stderr"])
        result = report["supervisor"]
        self.assertTrue(result["held_before_capabilities_and_model"])
        self.assertEqual(result["platform_executable"], "sleep")
        self.assertEqual(report["present_pids"], [result["descendant"]], report)
        if linux:
            self.assertEqual(report["adopted"]["state"], "live", report)
            self.assertTrue(report["present_groups"], report)

    @unittest.skipUnless(sys.platform == "darwin", "native macOS wrapper-loss evidence")
    def test_surviving_platform_descendant_holds_fresh_runtime_after_wrappers_exit(self):
        self.check_driver(False)

    @unittest.skipUnless(sys.platform.startswith("linux"), "requires Linux nonreaping ancestor")
    def test_linux_surviving_platform_descendant_holds_before_driver_reaping(self):
        self.check_driver(True)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--worker":
        _worker(sys.argv[3])
    elif len(sys.argv) == 4 and sys.argv[1] == "--owner":
        asyncio.run(_owner(sys.argv[3]))
    elif len(sys.argv) == 4 and sys.argv[1] == "--supervisor":
        print(json.dumps(asyncio.run(_scenario(sys.argv[3]))))
    elif len(sys.argv) == 4 and sys.argv[1] == "--driver":
        if sys.platform.startswith("linux"):
            support = _support()
            support._command = _command
            print(json.dumps(support._driver("unused", sys.argv[3])))
        else:
            print(json.dumps(_portable_driver(sys.argv[3])))
    else:
        unittest.main()
