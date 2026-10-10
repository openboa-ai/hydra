"""Late startup evidence uses the same live-owned control reader and cleanup budget."""

import asyncio
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
REPOSITORY = SOURCE.parent.parent


def _command(role, mode, directory):
    return [sys.executable, "-I", str(SOURCE), role, mode, str(directory)]


def _support():
    sys.path.insert(0, str(SOURCE.parent))
    import test_process_supervision as support
    return support


def _portable_helper(fd, command):
    """Real POSIX child/receipt test; this makes no Linux adoption claim."""
    import signal
    import socket
    sys.path.insert(0, str(REPOSITORY))
    from hydra_sdlc import execution_boundary as boundary

    control = socket.socket(fileno=fd)
    stream = control.makefile("rb")
    assert json.loads(stream.readline()) == {"version": 1, "kind": "launch"}
    child = subprocess.Popen(command, close_fds=True, start_new_session=True)
    os.close(0)
    os.close(1)
    control.sendall(boundary._supervision_frame("ready", pid=child.pid, pgid=child.pid))
    assert json.loads(stream.readline()) == {"version": 1, "kind": "terminate"}
    os.killpg(child.pid, signal.SIGTERM)
    code = child.wait(timeout=1)
    assert boundary._group_absent(child.pid)
    control.sendall(boundary._supervision_frame(
        "cleanup", pid=child.pid, pgid=child.pid,
        returncode=code, reaped=True, group_absent=True,
    ))
    stream.close()
    control.close()


def _worker(mode, directory):
    support = _support()
    support._mark(directory, "worker", pid=os.getpid(), pgid=os.getpgrp())
    if mode == "linux":
        support._spawn_descendant(directory)
    # No SDK is used. An assignment crossing this point would be a late dispatch.
    if sys.stdin.buffer.readline():
        support._mark(directory, "assignment")


def _coalesced(directory, *, actual_linux):
    """Put both controls in one write before the actual helper reads either."""
    sys.path.insert(0, str(REPOSITORY))
    from hydra_sdlc import execution_boundary as boundary
    support = _support()
    control, peer = socket.socketpair()
    control.settimeout(2)
    child_pid = None
    helper = None
    try:
        control.sendall(boundary._supervision_frame("launch") + boundary._supervision_frame("terminate"))
        helper = subprocess.Popen(
            [sys.executable, "-I", str(SOURCE), "--coalesced-helper", str(peer.fileno()), str(directory)],
            pass_fds=(peer.fileno(),), stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE, start_new_session=True,
        )
        peer.close()
        support._mark(directory, "helper", pid=helper.pid)
        stream = control.makefile("rb")
        receipt = boundary._decode_supervision(stream.readline())
        if receipt.get("kind") == "ready":
            # Retain a regression's actual identity solely for fixture cleanup.
            child_pid, pgid = boundary._validate_ready(receipt, helper.pid)
            support._mark(directory, "owned", pid=child_pid, pgid=pgid)
        assert receipt == {"version": 1, "kind": "launch_cancelled", "reaped": True}
        helper.communicate(timeout=2)
        assert helper.returncode == 0
        assert stream.read(1) == b""
        assert not any(row["name"] == "child_spawn_attempted" for row in support._observations(directory))
        stream.close()
        return {"receipt": receipt, "helper_returncode": helper.returncode}
    finally:
        # Success assertions precede fallback. Failed fixtures still release only
        # their observed helper/child; Linux's driver checks adopted descendants.
        if helper is not None and helper.poll() is None:
            if child_pid is not None:
                try:
                    os.killpg(child_pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            helper.kill()
            helper.communicate(timeout=2)
        control.close()
        peer.close()


async def _scenario(mode, directory, *, actual_linux):
    sys.path.insert(0, str(REPOSITORY))
    from hydra_sdlc import execution_boundary as boundary
    support = _support()
    before = support._subreaper() if actual_linux else None
    if mode == "coalesced":
        result = _coalesced(directory, actual_linux=actual_linux)
        return {"result": result, "subreaper_before": before,
                "subreaper_after": support._subreaper() if actual_linux else None}
    ready_seen = asyncio.Event()
    release_ready = asyncio.Event()
    handles = []
    audits = []
    real_owned = boundary.OwnedProcess

    class GatedProcess(real_owned):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.linux = True
            handles.append(self)

        async def _read_control(self):
            frame = await super()._read_control()
            if frame["kind"] == "ready":
                support._mark(directory, "helper", pid=self.process.pid)
                support._mark(directory, "owned", pid=frame["pid"], pgid=frame["pgid"])
                # A real ready frame has arrived from a real helper and child.
                # The gate is released only when caller cleanup starts.
                ready_seen.set()
                await release_ready.wait()
                if mode == "malformed":
                    return {**frame, "pid": self.process.pid}
            return frame

        async def cleanup(self):
            if mode != "missing":
                release_ready.set()
            return await super().cleanup()

    def portable_command(command, fd, deadline):
        return [sys.executable, "-I", str(SOURCE), "--portable-helper", str(fd), json.dumps(command)]

    async def wait_started():
        await asyncio.wait_for(ready_seen.wait(), 4)
        if actual_linux:
            await support._wait_for_descendant(directory)
        else:
            until = asyncio.get_running_loop().time() + 4
            while not any(row["name"] == "worker" for row in support._observations(directory)):
                if asyncio.get_running_loop().time() >= until:
                    raise TimeoutError("worker did not start")
                await asyncio.sleep(.01)

    worker_command = _command("--worker", "linux" if actual_linux else "portable", directory)
    from contextlib import ExitStack
    with ExitStack() as stack:
        stack.enter_context(patch.object(boundary, "OwnedProcess", GatedProcess))
        if not actual_linux:
            stack.enter_context(patch.object(boundary, "_helper_command", side_effect=portable_command))
        if mode.startswith("execution_"):
            stack.enter_context(patch.object(boundary, "_worker_command", return_value=worker_command))
            task = asyncio.create_task(boundary.execute_worker(
                {"cwd": str(directory), "task": "synthetic pre-dispatch startup"},
                lambda **values: None, lambda digest, event: audits.append(event), lambda: False, None,
                worker_source=boundary.__file__, timeout=1.5 if mode.endswith("deadline") else 5,
                grace=.05, poll=.01,
            ))
            await wait_started()
            if mode.endswith("cancel"):
                task.cancel()
            result = await task
        else:
            handle = GatedProcess(worker_command)
            task = asyncio.create_task(handle.start(
                asyncio.get_running_loop().time() + (1.5 if mode == "deadline" else 5),
            ))
            await wait_started()
            if mode != "deadline":
                task.cancel()
            try:
                await task
            except (asyncio.CancelledError, TimeoutError) as exc:
                start_error = type(exc).__name__
            else:
                raise AssertionError("gated startup unexpectedly succeeded")
            cleanup_started = time.monotonic()
            clean = await handle.cleanup()
            result = {"clean": clean, "start_error": start_error,
                      "cleanup_seconds": time.monotonic() - cleanup_started}
        handle = handles[0]
        result["receipt"] = handle.receipt
        result["helper_returncode"] = handle.process.returncode
        result["validated_pid"] = handle.pid
        result["audits"] = audits
    return {"result": result, "subreaper_before": before,
            "subreaper_after": support._subreaper() if actual_linux else None}


class StartupRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_coalesced_launch_and_terminate_are_processed_without_another_read(self):
        with tempfile.TemporaryDirectory() as directory:
            result = _coalesced(directory, actual_linux=False)
            observations = _support()._observations(directory)
        self.assertEqual(result["receipt"], {"version": 1, "kind": "launch_cancelled", "reaped": True})
        self.assertEqual([row["name"] for row in observations], ["helper"])
        for row in observations:
            with self.assertRaises(ProcessLookupError):
                os.kill(row["pid"], 0)

    async def check_startup(self, mode):
        with tempfile.TemporaryDirectory() as directory:
            report = await _scenario(mode, directory, actual_linux=False)
            observations = _support()._observations(directory)
        # Check actual absence before any test cleanup can hide a leftover.
        for row in observations:
            if "pid" in row:
                with self.assertRaises(ProcessLookupError, msg=str(row)):
                    os.kill(row["pid"], 0)
            if "pgid" in row:
                with self.assertRaises(ProcessLookupError, msg=str(row)):
                    os.killpg(row["pgid"], 0)
        self.assertNotIn("assignment", [row["name"] for row in observations])
        result = report["result"]
        self.assertEqual(result["helper_returncode"], 0)
        self.assertEqual(result["audits"], [])
        if mode.startswith("execution_"):
            self.assertEqual(result["status"], "interrupted" if mode.endswith("cancel") else "failed")
            self.assertNotIn("cleanup", result["detail"])
        elif mode in {"malformed", "missing"}:
            self.assertFalse(result["clean"])
            self.assertIsNone(result["receipt"])
            self.assertIsNone(result["validated_pid"])
            self.assertLess(result["cleanup_seconds"], 2.5)
        else:
            self.assertTrue(result["clean"])
            self.assertEqual(result["start_error"], "TimeoutError" if mode == "deadline" else "CancelledError")
            self.assertLess(result["cleanup_seconds"], 2.5)
        if mode not in {"malformed", "missing"}:
            self.assertTrue(result["receipt"]["reaped"])
            self.assertTrue(result["receipt"]["group_absent"])
            self.assertEqual(result["validated_pid"], result["receipt"]["pid"])

    async def test_cancelled_start_collects_late_identity_and_receipt(self):
        await self.check_startup("cancel")

    async def test_start_deadline_collects_late_identity_and_receipt(self):
        await self.check_startup("deadline")

    async def test_execution_cancel_cannot_dispatch_after_late_ready(self):
        await self.check_startup("execution_cancel")

    async def test_execution_deadline_cannot_dispatch_after_late_ready(self):
        await self.check_startup("execution_deadline")

    async def test_malformed_ready_remains_unknown(self):
        await self.check_startup("malformed")

    async def test_missing_ready_remains_unknown(self):
        await self.check_startup("missing")


@unittest.skipUnless(sys.platform == "linux", "requires actual Linux subreaper and /proc semantics")
class LinuxStartupRecoveryTests(unittest.TestCase):
    def test_late_ready_recovery_and_invalid_controls_under_nonreaping_ancestor(self):
        for mode in ("cancel", "deadline", "execution_cancel", "execution_deadline", "malformed", "missing", "coalesced"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                completed = subprocess.run(
                    _command("--driver", mode, directory), capture_output=True, text=True, timeout=22,
                )
                self.assertEqual(completed.returncode, 0, completed.stderr)
                report = json.loads(completed.stdout)
                self.assertEqual(report["returncode"], 0, report["stderr"])
                self.assertEqual(report["adopted"], {"state": "none"}, report)
                self.assertEqual(report["present_pids"], [], report)
                self.assertEqual(report["present_groups"], [], report)
                self.assertTrue(report["fallback_cleanup_complete"], report)
                supervisor = report["supervisor"]
                self.assertEqual(supervisor["subreaper_before"], 0)
                self.assertEqual(supervisor["subreaper_after"], 0)
                self.assertNotIn("assignment", [row["name"] for row in report["observations"]])
                result = supervisor["result"]
                self.assertEqual(result["helper_returncode"], 0, report)
                if mode == "coalesced":
                    self.assertEqual(result["receipt"],
                                     {"version": 1, "kind": "launch_cancelled", "reaped": True})
                    self.assertEqual([row["name"] for row in report["observations"]], ["helper"])
                    continue
                self.assertEqual(result["audits"], [])
                if mode.startswith("execution_"):
                    self.assertEqual(result["status"], "interrupted" if mode.endswith("cancel") else "failed")
                    self.assertNotIn("cleanup", result["detail"])
                else:
                    self.assertEqual(result["clean"], mode not in {"malformed", "missing"}, report)
                    self.assertLess(result["cleanup_seconds"], 2.5)
                if mode not in {"malformed", "missing"}:
                    self.assertTrue(result["receipt"]["reaped"])
                    self.assertTrue(result["receipt"]["group_absent"])
                    self.assertEqual(result["validated_pid"], result["receipt"]["pid"])


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--coalesced-helper":
        sys.path.insert(0, str(REPOSITORY))
        from hydra_sdlc import execution_boundary as boundary
        if sys.platform != "linux":
            # Native POSIX parser/reaping check; Linux uses the actual subreaper.
            boundary._enable_subreaper = lambda: None
        native_popen = boundary.subprocess.Popen

        def observed_spawn(*args, **kwargs):
            _support()._mark(sys.argv[3], "child_spawn_attempted")
            return native_popen(*args, **kwargs)

        boundary.subprocess.Popen = observed_spawn
        raise SystemExit(boundary._supervisor_main(
            int(sys.argv[2]), time.monotonic() + 5,
            [sys.executable, "-I", "-c", "import time; time.sleep(60)"],
        ))
    elif len(sys.argv) == 4 and sys.argv[1] == "--portable-helper":
        _portable_helper(int(sys.argv[2]), json.loads(sys.argv[3]))
    elif len(sys.argv) == 4 and sys.argv[1] == "--worker":
        _worker(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 4 and sys.argv[1] == "--leaf":
        _support()._leaf()
    elif len(sys.argv) == 4 and sys.argv[1] == "--supervisor":
        print(json.dumps(asyncio.run(_scenario(sys.argv[2], sys.argv[3], actual_linux=True))))
    elif len(sys.argv) == 4 and sys.argv[1] == "--driver":
        support = _support()
        support._command = _command
        print(json.dumps(support._driver(sys.argv[2], sys.argv[3])))
    else:
        unittest.main()
