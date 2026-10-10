"""Real Linux cleanup beneath an ancestor that does not reap adopted children.

The disposable driver owns the subreaper setting; the unittest process never
changes process-wide child ownership. No provider runtime or authentication is
used by these tests.
"""

import asyncio
import ctypes
import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch


SOURCE = Path(__file__).resolve()
REPOSITORY = SOURCE.parent.parent


def _command(role, mode, directory):
    return [sys.executable, "-I", str(SOURCE), role, mode, str(directory)]


def _mark(directory, name, **values):
    with (Path(directory) / "observed.jsonl").open("a") as output:
        output.write(json.dumps({"name": name, **values}) + "\n")


def _observations(directory):
    marker = Path(directory) / "observed.jsonl"
    return [json.loads(line) for line in marker.read_text().splitlines()] if marker.exists() else []


def _subreaper(enabled=None):
    libc = ctypes.CDLL(None, use_errno=True)
    if enabled is not None and libc.prctl(36, int(enabled), 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_SET_CHILD_SUBREAPER failed")
    observed = ctypes.c_int()
    if libc.prctl(37, ctypes.byref(observed), 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), "PR_GET_CHILD_SUBREAPER failed")
    return observed.value


def _leaf():
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    print("ready", flush=True)
    time.sleep(60)


def _spawn_descendant(directory):
    child = subprocess.Popen(
        _command("--leaf", "unused", directory), stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
    )
    if child.stdout.readline() != "ready\n":
        raise RuntimeError("resistant descendant did not start")
    child.stdout.close()
    _mark(directory, "descendant", pid=child.pid, at=time.monotonic())
    return child


def _worker(mode, directory):
    # Inspect before opening the marker or spawning descendants. The temporary
    # directory fd used by iterdir is already closed when readlink is attempted.
    descriptors = {}
    for entry in list(Path("/proc/self/fd").iterdir()):
        try:
            descriptors[entry.name] = os.readlink(entry)
        except FileNotFoundError:
            pass
    _mark(directory, "worker", pid=os.getpid(), pgid=os.getpgrp(),
          descriptors=descriptors)
    if mode == "execution":
        sys.path.insert(0, str(REPOSITORY))
        from hydra_sdlc import execution_boundary as boundary

        async def blocked(assignment, identity, event, stopped,
                          resume_thread_id=None, on_dispatch=None):
            _spawn_descendant(directory)
            await asyncio.Event().wait()

        boundary.worker_main(blocked)
        return
    _spawn_descendant(directory)
    if mode == "capability_completed":
        # The supervisor releases a ready worker near the original deadline;
        # interpreter startup must not silently consume the intended phase.
        while not (Path(directory) / "capability-report-release").exists():
            time.sleep(.005)
        print(json.dumps({"available": True}), flush=True)
        return
    if mode == "verification_completed":
        print("verified", flush=True)
        return
    if mode == "verification_eof":
        os.close(1)
        os.close(2)
        _mark(directory, "stdout_closed")
    if mode == "verification_output_limit":
        os.write(1, b"x" * 4096)
    if mode == "owned":
        print("ready", flush=True)
    time.sleep(60)


async def _wait_for_descendant(directory):
    deadline = asyncio.get_running_loop().time() + 5
    while not any(item["name"] == "descendant" for item in _observations(directory)):
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("worker did not create its resistant descendant")
        await asyncio.sleep(.01)


async def _release_capability_report(directory, deadline):
    loop = asyncio.get_running_loop()
    release_at = deadline - .3
    while not any(item["name"] == "descendant" for item in _observations(directory)):
        if loop.time() >= release_at:
            raise TimeoutError("capability descendant missed the report-release phase")
        await asyncio.sleep(min(.01, max(0, release_at - loop.time())))
    await asyncio.sleep(max(0, release_at - loop.time()))
    _mark(directory, "capability_report_released", at=loop.time())
    (Path(directory) / "capability-report-release").touch()


async def _supervisor(mode, directory):
    sys.path.insert(0, str(REPOSITORY))
    from hydra_sdlc import codex, execution_boundary as boundary

    before = _subreaper()
    if mode == "negative_control":
        # Exit while this direct child is alive. The driver's single observation
        # must find the adopted child even if the machine's PID 1 is healthy.
        child = subprocess.Popen(
            _command("--leaf", "unused", directory), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
        )
        if child.stdout.readline() != "ready\n":
            raise RuntimeError("negative control did not start")
        child.stdout.close()
        _mark(directory, "negative_orphan", pid=child.pid)
        return {"negative_control": True}

    real_owned_process = boundary.OwnedProcess
    report_release = None

    class ObservedProcess(real_owned_process):
        @property
        def stdout(self):
            return getattr(self, "_observed_stdout", super().stdout)

        async def start(self, *args, **kwargs):
            nonlocal report_release
            if mode == "capability_completed":
                _mark(directory, "capability_deadline", deadline=args[0])
            result = await super().start(*args, **kwargs)
            _mark(directory, "helper", pid=self.process.pid)
            _mark(directory, "owned", pid=self.pid, pgid=self.pgid)
            if mode == "capability_completed":
                stdout = super().stdout
                report_bytes = bytearray()

                async def observe_output(*read_args, **read_kwargs):
                    output = await stdout.read(*read_args, **read_kwargs)
                    report_bytes.extend(output)
                    if stdout.at_eof():
                        _mark(directory, "capability_stdout_eof",
                              at=asyncio.get_running_loop().time(), stdout_hex=report_bytes.hex())
                    return output

                self._observed_stdout = SimpleNamespace(read=observe_output)
                report_release = asyncio.create_task(
                    _release_capability_report(directory, args[0]),
                )
            return result

        async def _read_control(self):
            frame = await super()._read_control()
            if mode == "capability_completed" and frame.get("kind") == "cleanup":
                _mark(directory, "capability_cleanup_receipt",
                      at=asyncio.get_running_loop().time(), receipt=frame)
            if mode == "invalid_receipt" and frame.get("kind") == "cleanup":
                # Preserve real setup, shutdown and reaping. Corrupt only the
                # identity in the actual helper's completed cleanup receipt.
                _mark(directory, "receipt_rewritten")
                return {**frame, "pid": frame["pid"] + 1}
            return frame

        async def cleanup(self):
            if mode == "capability_completed":
                _mark(directory, "capability_cleanup_started",
                      at=asyncio.get_running_loop().time())
            clean = await super().cleanup()
            if mode == "capability_completed":
                _mark(directory, "capability_cleanup_finished",
                      at=asyncio.get_running_loop().time(), clean=clean,
                      worker_returncode=self.returncode,
                      helper_returncode=self.process.returncode)
            return clean

    boundary.OwnedProcess = ObservedProcess
    if mode.startswith("execution_"):
        boundary._worker_command = lambda _: _command("--worker", "execution", directory)
        task = asyncio.create_task(boundary.execute_worker(
            {"cwd": str(directory), "task": "synthetic blocked execution"},
            lambda **values: None, lambda *values: None, lambda: False, None,
            worker_source=boundary.__file__, timeout=1.5, grace=.05, poll=.01,
        ))
        if mode == "execution_cancel":
            await _wait_for_descendant(directory)
            task.cancel()
        result = await task
    elif mode.startswith("capability_"):
        worker_mode = "capability_completed" if mode == "capability_completed" else "capability"
        codex._capability_command = lambda _: _command("--worker", worker_mode, directory)
        codex.CAPABILITIES_TIMEOUT_SECONDS = 1.5
        result = await codex.capabilities(str(directory))
        if report_release is not None:
            await report_release
    elif mode.startswith("verification_"):
        helpers = []
        helper_killed = False
        real_popen = boundary.subprocess.Popen
        real_ready = boundary._validate_ready

        def observe_spawn(command, *args, **kwargs):
            process = real_popen(command, *args, **kwargs)
            if "--owned-process-helper" in command:
                helpers.append(process)
                _mark(directory, "helper", pid=process.pid)
            return process

        def observe_ready(*args, **kwargs):
            pid, pgid = real_ready(*args, **kwargs)
            _mark(directory, "owned", pid=pid, pgid=pgid)
            return pid, pgid

        def stopped():
            nonlocal helper_killed
            names = {item["name"] for item in _observations(directory)}
            if (mode == "verification_helper_death" and {"owned", "descendant"} <= names
                    and not helper_killed):
                os.kill(helpers[0].pid, signal.SIGKILL)
                helper_killed = True
            return ((mode == "verification_stop" and "descendant" in names)
                    or (mode == "verification_eof" and "stdout_closed" in names))

        # Deliberately invoke the synchronous facade inside this active loop.
        # Only observe real helper creation and real validated identities.
        with patch.object(boundary.subprocess, "Popen", side_effect=observe_spawn), \
                patch.object(boundary, "_validate_ready", side_effect=observe_ready):
            try:
                completed = boundary.run_owned_sync(
                    _command("--worker", mode, directory), cwd=directory,
                    env=boundary.worker_environment(),
                    timeout=1.5 if mode == "verification_timeout" else 5,
                    stop_requested=stopped,
                    max_output_bytes=128 if mode == "verification_output_limit" else 1024,
                )
                result = {"returncode": completed.returncode, "stdout_hex": completed.stdout.hex()}
            except boundary.OwnedCommandError as exc:
                result = {"reason": exc.reason}
        result["helper_killed"] = helper_killed
    elif mode == "expired_start":
        handle = ObservedProcess(_command("--worker", "owned", directory))
        start_error = None
        try:
            await handle.start(asyncio.get_running_loop().time() - 1)
        except (TimeoutError, boundary.ProtocolError) as exc:
            start_error = type(exc).__name__
        finally:
            clean = await handle.cleanup()
        # A timed-out launch is retained by its owner until cleanup collects it.
        # Do not wait/reap here: the driver must detect any helper left behind.
        if handle.process is not None:
            _mark(directory, "helper", pid=handle.process.pid)
        result = {"clean": clean, "start_error": start_error,
                  "cancelled_launch": handle._cancelled_launch,
                  "helper_returncode": handle.process.returncode if handle.process else None}
    else:
        unrelated = None
        handle = ObservedProcess(_command("--worker", "owned", directory))
        try:
            if mode == "descriptors_and_unrelated":
                unrelated = subprocess.Popen(
                    _command("--leaf", "unused", directory), stdin=subprocess.DEVNULL,
                    stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True,
                )
                if unrelated.stdout.readline() != "ready\n":
                    raise RuntimeError("unrelated child did not start")
                unrelated.stdout.close()
                _mark(directory, "unrelated", pid=unrelated.pid)
            await handle.start(asyncio.get_running_loop().time() + 5)
            if await asyncio.wait_for(handle.stdout.readline(), 5) != b"ready\n":
                raise RuntimeError("owned worker did not start")
            if mode == "control_eof":
                # Lose the private channel, not the assignment pipe. Its receipt
                # is no longer available, but the helper must still stop/reap.
                handle.control.close()
                await asyncio.wait_for(handle.process.wait(), 5)
            elif mode == "helper_death":
                os.kill(handle.process.pid, signal.SIGKILL)
                # Process.wait can also await pipe EOF; the still-live worker
                # deliberately retains stdout until cleanup's fallback kills it.
                deadline = asyncio.get_running_loop().time() + 5
                while handle.process.returncode is None:
                    if asyncio.get_running_loop().time() >= deadline:
                        raise TimeoutError("helper child exit was not collected")
                    await asyncio.sleep(.01)
            clean = await handle.cleanup()
            result = {"clean": clean, "helper_returncode": handle.process.returncode}
            if unrelated is not None:
                result["unrelated_alive"] = unrelated.poll() is None
        finally:
            # Failure cleanup is still performed by the real owner first; the
            # driver later records any adoption before its own fallback cleanup.
            if handle.process is not None and handle.process.returncode is None:
                await handle.cleanup()
            if unrelated is not None:
                unrelated.kill()
                unrelated.wait(timeout=2)
    return {"result": result, "subreaper_before": before, "subreaper_after": _subreaper()}


def _probe_children_once():
    try:
        pid, _ = os.waitpid(-1, os.WNOHANG)
    except ChildProcessError:
        return {"state": "none"}
    # A positive result has reaped a zombie. This remains a failed observation;
    # a second call must never turn that first result into a passing ECHILD.
    return {"state": "zombie" if pid else "live", "pid": pid}


def _present(observations, field, signal_function):
    present = []
    for value in sorted({item[field] for item in observations if field in item}):
        try:
            signal_function(value, 0)
        except ProcessLookupError:
            continue
        present.append(value)
    return present


def _reap_leftovers():
    # This driver has no other waiters or unrelated children. A child that exits
    # between enumeration and kill remains our zombie until we reap it, keeping
    # its PID from being reused by an unrelated process.
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        while True:
            try:
                pid, _ = os.waitpid(-1, os.WNOHANG)
            except ChildProcessError:
                return True
            if pid == 0:
                break
        children = Path(f"/proc/self/task/{os.getpid()}/children").read_text().split()
        for child in children:
            try:
                os.kill(int(child), signal.SIGKILL)
            except ProcessLookupError:
                pass
        time.sleep(.01)
    return False


def _driver(mode, directory):
    signal.signal(signal.SIGCHLD, signal.SIG_DFL)
    if _subreaper(True) != 1:
        raise RuntimeError("driver subreaper setup was not confirmed")
    supervisor = None
    report = {}
    try:
        supervisor = subprocess.Popen(
            _command("--supervisor", mode, directory), stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        )
        stdout, stderr = supervisor.communicate(timeout=12)
        report["returncode"] = supervisor.returncode
        report["supervisor"] = json.loads(stdout) if supervisor.returncode == 0 else None
        report["stderr"] = stderr
        report["observations"] = _observations(directory)
        # Observe liveness before waitpid's potentially reaping diagnostic call.
        report["present_pids"] = _present(report["observations"], "pid", os.kill)
        report["present_groups"] = _present(report["observations"], "pgid", os.killpg)
        report["adopted"] = _probe_children_once()
    finally:
        if supervisor is not None and supervisor.poll() is None:
            supervisor.kill()
            supervisor.communicate(timeout=2)
        report["fallback_cleanup_complete"] = _reap_leftovers()
    return report


def _require_proc_children():
    try:
        Path(f"/proc/self/task/{os.getpid()}/children").read_text()
    except (FileNotFoundError, PermissionError):
        raise unittest.SkipTest("requires readable Linux proc task-children for owned fixture cleanup")


@unittest.skipUnless(sys.platform == "linux", "requires Linux subreaper and /proc semantics")
class LinuxProcessSupervisionTests(unittest.TestCase):
    def run_driver(self, mode):
        _require_proc_children()
        with tempfile.TemporaryDirectory() as directory:
            completed = subprocess.run(
                _command("--driver", mode, directory), capture_output=True,
                text=True, timeout=22,
            )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        report = json.loads(completed.stdout)
        self.assertTrue(report["fallback_cleanup_complete"], report)
        self.assertEqual(report["returncode"], 0, report["stderr"])
        return report

    def assert_no_remaining_processes(self, report):
        self.assertEqual(report["adopted"], {"state": "none"}, report)
        self.assertEqual(report["present_pids"], [], report)
        self.assertEqual(report["present_groups"], [], report)
        supervisor = report["supervisor"]
        self.assertEqual(supervisor["subreaper_before"], 0)
        self.assertEqual(supervisor["subreaper_after"], 0)

    def assert_clean(self, report):
        self.assert_no_remaining_processes(report)
        names = [item["name"] for item in report["observations"]]
        for required in ("helper", "worker", "owned", "descendant"):
            self.assertIn(required, names)
        helper = next(item["pid"] for item in report["observations"] if item["name"] == "helper")
        worker = next(item for item in report["observations"] if item["name"] == "worker")
        owned = next(item for item in report["observations"] if item["name"] == "owned")
        self.assertNotEqual(helper, worker["pid"])
        self.assertEqual(owned["pid"], worker["pid"])
        self.assertEqual(owned["pgid"], worker["pgid"])
        self.assertEqual(worker["pid"], worker["pgid"])

    def test_negative_control_detects_adoption_before_test_cleanup(self):
        report = self.run_driver("negative_control")
        self.assertNotEqual(report["adopted"]["state"], "none", report)
        self.assertTrue(report["present_pids"], report)

    def test_execution_timeout_reaps_resistant_descendant(self):
        report = self.run_driver("execution_timeout")
        self.assert_clean(report)
        self.assertEqual(report["supervisor"]["result"]["status"], "failed")
        self.assertNotIn("cleanup", report["supervisor"]["result"]["detail"])

    def test_execution_cancellation_reaps_resistant_descendant(self):
        report = self.run_driver("execution_cancel")
        self.assert_clean(report)
        self.assertEqual(report["supervisor"]["result"]["status"], "interrupted")
        self.assertNotIn("cleanup", report["supervisor"]["result"]["detail"])

    def test_capability_timeout_reaps_resistant_descendant(self):
        report = self.run_driver("capability_timeout")
        self.assert_clean(report)
        result = report["supervisor"]["result"]
        self.assertFalse(result["available"])
        self.assertEqual(result["error_type"], "TimeoutError")
        self.assertNotIn("cleanup", result)

    def test_timely_capability_survives_reaping_after_probe_deadline(self):
        report = self.run_driver("capability_completed")
        self.assert_clean(report)
        self.assertTrue(report["supervisor"]["result"]["available"])
        self.assertNotIn("cleanup", report["supervisor"]["result"])
        phases = {item["name"]: item for item in report["observations"]}
        deadline = phases["capability_deadline"]["deadline"]
        released = phases["capability_report_released"]["at"]
        eof = phases["capability_stdout_eof"]
        started = phases["capability_cleanup_started"]["at"]
        receipt = phases["capability_cleanup_receipt"]
        finished = phases["capability_cleanup_finished"]
        self.assertLess(phases["descendant"]["at"], released, report)
        self.assertGreaterEqual(released, deadline - .3, report)
        self.assertLess(released, eof["at"], report)
        self.assertLess(eof["at"], deadline, report)
        self.assertEqual(json.loads(bytes.fromhex(eof["stdout_hex"])), {"available": True})
        self.assertGreaterEqual(started, deadline, report)
        self.assertGreater(receipt["at"], deadline, report)
        self.assertGreaterEqual(finished["at"], receipt["at"], report)
        self.assertTrue(receipt["receipt"]["reaped"], report)
        self.assertTrue(receipt["receipt"]["group_absent"], report)
        self.assertEqual(receipt["receipt"]["returncode"], 0, report)
        self.assertTrue(finished["clean"], report)
        self.assertEqual(finished["worker_returncode"], 0, report)
        self.assertEqual(finished["helper_returncode"], 0, report)
        self.assertLess(finished["at"] - started, 2, report)

    def test_control_eof_stops_tree_and_reaps_helper_without_claiming_receipt(self):
        report = self.run_driver("control_eof")
        self.assert_clean(report)
        self.assertFalse(report["supervisor"]["result"]["clean"])
        self.assertIsNotNone(report["supervisor"]["result"]["helper_returncode"])

    def test_helper_death_keeps_cleanup_unknown(self):
        report = self.run_driver("helper_death")
        self.assertFalse(report["supervisor"]["result"]["clean"])
        self.assertEqual(report["supervisor"]["result"]["helper_returncode"], -signal.SIGKILL)
        self.assertNotEqual(report["adopted"]["state"], "none", report)

    def test_expired_start_never_creates_worker_and_reaps_helper(self):
        report = self.run_driver("expired_start")
        self.assert_no_remaining_processes(report)
        result = report["supervisor"]["result"]
        self.assertEqual(result["start_error"], "TimeoutError")
        self.assertTrue(result["clean"])
        self.assertEqual(result["cancelled_launch"], {
            "version": 1, "kind": "launch_cancelled", "reaped": True,
        })
        self.assertEqual(result["helper_returncode"], 0)
        self.assertEqual([item["name"] for item in report["observations"]], ["helper"])

    def test_invalid_receipt_cannot_confirm_cleanup_after_real_reaping(self):
        report = self.run_driver("invalid_receipt")
        self.assert_clean(report)
        result = report["supervisor"]["result"]
        self.assertFalse(result["clean"])
        self.assertEqual(result["helper_returncode"], 0)
        self.assertEqual(sum(item["name"] == "receipt_rewritten" for item in report["observations"]), 1)

    def test_private_descriptors_and_unrelated_child_stay_outside_worker(self):
        report = self.run_driver("descriptors_and_unrelated")
        self.assert_clean(report)
        self.assertTrue(report["supervisor"]["result"]["clean"])
        self.assertTrue(report["supervisor"]["result"]["unrelated_alive"])
        worker = next(item for item in report["observations"] if item["name"] == "worker")
        self.assertEqual(set(worker["descriptors"]), {"0", "1", "2"}, worker)

    def test_sync_verification_success_reaps_resistant_descendant(self):
        report = self.run_driver("verification_completed")
        self.assert_clean(report)
        self.assertEqual(report["supervisor"]["result"], {
            "returncode": 0, "stdout_hex": b"verified\n".hex(), "helper_killed": False,
        })

    def test_sync_verification_timeout_reaps_resistant_descendant(self):
        report = self.run_driver("verification_timeout")
        self.assert_clean(report)
        self.assertLess(report["supervisor"]["result"]["returncode"], 0)

    def test_sync_verification_stop_reaps_resistant_descendant(self):
        report = self.run_driver("verification_stop")
        self.assert_clean(report)
        self.assertEqual(report["supervisor"]["result"]["reason"], "stopped")

    def test_sync_verification_stop_after_stdout_eof_reaps_descendant(self):
        report = self.run_driver("verification_eof")
        self.assert_clean(report)
        self.assertEqual(report["supervisor"]["result"]["reason"], "stopped")
        self.assertIn("stdout_closed", [item["name"] for item in report["observations"]])

    def test_sync_verification_output_limit_reaps_resistant_descendant(self):
        report = self.run_driver("verification_output_limit")
        self.assert_clean(report)
        self.assertEqual(report["supervisor"]["result"]["reason"], "output_limit")

    def test_sync_verification_helper_death_keeps_cleanup_unknown(self):
        report = self.run_driver("verification_helper_death")
        self.assertEqual(report["supervisor"]["result"], {
            "reason": "cleanup_unknown", "helper_killed": True,
        })
        self.assertNotEqual(report["adopted"]["state"], "none", report)


class TopologyPrerequisiteTests(unittest.TestCase):
    def entrypoints(self):
        from test_restart_ownership import RestartTopologyTests
        from test_startup_recovery import LinuxStartupRecoveryTests
        startup = LinuxStartupRecoveryTests("test_late_ready_recovery_and_invalid_controls_under_nonreaping_ancestor")
        return {
            "supervision": lambda: LinuxProcessSupervisionTests().run_driver("negative_control"),
            "restart": lambda: RestartTopologyTests().check_driver(True),
            "startup": startup.test_late_ready_recovery_and_invalid_controls_under_nonreaping_ancestor,
        }

    def test_missing_or_denied_proc_interface_skips_before_child_creation(self):
        for error in (FileNotFoundError("missing task-children"), PermissionError("denied task-children")):
            for name, entrypoint in self.entrypoints().items():
                with self.subTest(entrypoint=name, error=type(error).__name__), \
                        patch.object(Path, "read_text", side_effect=error), \
                        patch.object(tempfile, "TemporaryDirectory") as directory, \
                        patch.object(subprocess, "run") as spawn:
                    with self.assertRaisesRegex(unittest.SkipTest, "requires readable Linux proc task-children"):
                        entrypoint()
                    directory.assert_not_called()
                    spawn.assert_not_called()

    def test_unexpected_proc_read_error_is_not_masked_as_unsupported(self):
        for name, entrypoint in self.entrypoints().items():
            with self.subTest(entrypoint=name):
                error = OSError("unexpected proc read failure")
                with patch.object(Path, "read_text", side_effect=error), \
                        patch.object(tempfile, "TemporaryDirectory") as directory, \
                        patch.object(subprocess, "run") as spawn:
                    with self.assertRaises(OSError) as raised:
                        entrypoint()
                    self.assertIs(raised.exception, error)
                    directory.assert_not_called()
                    spawn.assert_not_called()


@unittest.skipUnless(os.name == "posix", "owned command execution requires POSIX")
class SynchronousCommandTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        from hydra_sdlc import execution_boundary as boundary
        self.boundary = boundary
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name).resolve()

    def run_command(self, source, **options):
        return self.boundary.run_owned_sync(
            [sys.executable, "-I", "-c", source], cwd=self.root,
            env=options.pop("env", {}), timeout=options.pop("timeout", 3),
            max_output_bytes=options.pop("max_output_bytes", 1024), **options,
        )

    def assert_worker_gone(self):
        pid = int((self.root / "worker.pid").read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        with self.assertRaises(ProcessLookupError):
            os.killpg(pid, 0)

    async def test_active_loop_preserves_cwd_explicit_environment_and_combined_bytes(self):
        self.assertIsNotNone(asyncio.get_running_loop())
        source = (
            "import json,os,sys\n"
            "print(json.dumps({'cwd': os.getcwd(), 'value': os.environ.get('HYDRA_SYNC_TEST'), "
            "'stdin': sys.stdin.buffer.read().decode()}), flush=True)\n"
            "os.write(2, b'private stderr\\n')\n"
        )
        with patch.dict(os.environ, {"HYDRA_SYNC_TEST": "parent"}):
            result = self.run_command(source, env={"HYDRA_SYNC_TEST": "child"})
            self.assertEqual(os.environ["HYDRA_SYNC_TEST"], "parent")
        self.assertEqual(result.returncode, 0)
        self.assertIsInstance(result.stdout, bytes)
        lines = result.stdout.splitlines()
        self.assertEqual(json.loads(lines[0]), {"cwd": str(self.root), "value": "child", "stdin": ""})
        self.assertEqual(lines[1:], [b"private stderr"])

    async def test_stop_before_dispatch_never_spawns(self):
        with patch.object(self.boundary.subprocess, "Popen") as spawn:
            with self.assertRaises(self.boundary.OwnedCommandError) as raised:
                self.run_command("raise AssertionError('must not run')", stop_requested=lambda: True)
        self.assertEqual(raised.exception.reason, "stopped")
        spawn.assert_not_called()

    def run_collected_helper(self):
        # Exercise the actual private socket on any POSIX host. This helper
        # reaps one real child; it does not simulate Linux descendant reaping.
        helper = """
import json, os, socket, subprocess, sys
from pathlib import Path

control = socket.socket(fileno=int(sys.argv[1]))
buffered = b''
while b'\\n' not in buffered:
    buffered += control.recv(4096)
assert json.loads(buffered) == {'version': 1, 'kind': 'launch'}
Path('helper.pid').write_text(str(os.getpid()))
child = subprocess.Popen(json.loads(sys.argv[2]), start_new_session=True, close_fds=True)
code = child.wait(timeout=2)
try:
    os.killpg(child.pid, 0)
except ProcessLookupError:
    pass
else:
    raise AssertionError('child group remains after collection')
frames = [
    {'version': 1, 'kind': 'ready', 'pid': child.pid, 'pgid': child.pid},
    {'version': 1, 'kind': 'cleanup', 'pid': child.pid, 'pgid': child.pid,
     'returncode': code, 'reaped': True, 'group_absent': True},
]
# Once terminal cleanup is ready, the helper no longer accepts commands.
# An extra terminate write must fail, while the receipt can still be read.
control.shutdown(socket.SHUT_RD)
control.sendall(b''.join(json.dumps(frame).encode() + b'\\n' for frame in frames))
control.close()
"""

        def helper_command(command, control_fd, deadline):
            return [sys.executable, "-I", "-c", helper, str(control_fd), json.dumps(command)]

        source = (
            "import os\nfrom pathlib import Path\n"
            "Path('worker.pid').write_text(str(os.getpid()))\n"
            "print('collected', flush=True)\n"
        )
        with patch.object(self.boundary.sys, "platform", "linux"), \
                patch.object(self.boundary, "_helper_command", side_effect=helper_command):
            return self.run_command(source)

    async def test_completed_receipt_needs_no_further_control_write(self):
        result = self.run_collected_helper()
        self.assertEqual((result.returncode, result.stdout), (0, b"collected\n"))
        self.assert_worker_gone()
        with self.assertRaises(ProcessLookupError):
            os.kill(int((self.root / "helper.pid").read_text()), 0)

    async def test_sync_receipt_prevents_signaling_a_reused_group(self):
        # The real helper verifies disappearance before sending its receipt.
        # Only the parent's later observation is replaced by a reused group.
        with patch.object(self.boundary, "_group_absent", return_value=False), \
                patch.object(self.boundary, "CLEANUP_SECONDS", .2), \
                patch.object(self.boundary.os, "killpg") as signal_group:
            with self.assertRaises(self.boundary.OwnedCommandError) as raised:
                self.run_collected_helper()
        self.assertEqual(raised.exception.reason, "cleanup_unknown")
        signal_group.assert_not_called()
        self.assert_worker_gone()
        with self.assertRaises(ProcessLookupError):
            os.kill(int((self.root / "helper.pid").read_text()), 0)

    async def test_stop_after_stdout_closes_runs_callback_on_caller_thread(self):
        caller = threading.get_ident()
        callback_threads = []

        def stopped():
            callback_threads.append(threading.get_ident())
            return (self.root / "closed").exists()

        source = (
            "import os,time\nfrom pathlib import Path\n"
            "Path('worker.pid').write_text(str(os.getpid()))\n"
            "os.close(1); os.close(2)\nPath('closed').touch()\ntime.sleep(60)\n"
        )
        with self.assertRaises(self.boundary.OwnedCommandError) as raised:
            self.run_command(source, stop_requested=stopped)
        self.assertEqual(raised.exception.reason, "stopped")
        self.assertGreaterEqual(len(callback_threads), 2)
        self.assertEqual(set(callback_threads), {caller})
        self.assert_worker_gone()

    async def test_output_limit_collects_worker_before_error(self):
        source = (
            "import os,time\nfrom pathlib import Path\n"
            "Path('worker.pid').write_text(str(os.getpid()))\n"
            "os.write(1, b'x' * 4096)\ntime.sleep(60)\n"
        )
        with self.assertRaises(self.boundary.OwnedCommandError) as raised:
            self.run_command(source, max_output_bytes=128)
        self.assertEqual(raised.exception.reason, "output_limit")
        self.assert_worker_gone()

    async def test_timeout_after_stdout_closes_returns_negative_receipt(self):
        source = (
            "import os,time\nfrom pathlib import Path\n"
            "Path('worker.pid').write_text(str(os.getpid()))\n"
            "os.close(1); os.close(2)\ntime.sleep(60)\n"
        )
        result = self.run_command(source, timeout=.5, stop_requested=lambda: False)
        self.assertLess(result.returncode, 0)
        self.assertEqual(result.stdout, b"")
        self.assert_worker_gone()


class ReceiptGroupOwnershipTests(unittest.IsolatedAsyncioTestCase):
    async def test_async_receipt_prevents_signaling_a_reused_group(self):
        from hydra_sdlc import execution_boundary as boundary

        handle = boundary.OwnedProcess(["unused"])
        handle.linux = True
        handle.pid = handle.pgid = 41001
        handle.process = SimpleNamespace(
            returncode=0, kill=Mock(), communicate=AsyncMock(return_value=(b"", b"")),
        )
        handle.control, peer = socket.socketpair()
        self.addCleanup(handle.control.close)
        self.addCleanup(peer.close)
        handle.control.setblocking(False)
        peer.sendall(boundary._supervision_frame(
            "cleanup", pid=handle.pid, pgid=handle.pgid,
            returncode=0, reaped=True, group_absent=True,
        ))
        handle._receipt_task = asyncio.create_task(handle._read_receipt())
        await handle._receipt_task  # Accept the real channel frame before reuse.
        self.assertTrue(handle.receipt["group_absent"])

        with patch.object(boundary, "_group_absent", return_value=False), \
                patch.object(boundary, "CLEANUP_SECONDS", .05), \
                patch.object(boundary.os, "killpg") as signal_group:
            clean = await handle._collect()
        self.assertFalse(clean)
        signal_group.assert_not_called()
        handle.process.kill.assert_not_called()
        handle.process.communicate.assert_not_called()

    async def test_receipt_during_last_sleep_prevents_final_kill_of_reused_group(self):
        from hydra_sdlc import execution_boundary as boundary

        handle = boundary.OwnedProcess(["unused"])
        handle.linux = True
        handle.pid = handle.pgid = 41001
        handle.process = SimpleNamespace(
            returncode=None, kill=Mock(), communicate=AsyncMock(return_value=(b"", b"")),
        )
        handle.control, peer = socket.socketpair()
        self.addCleanup(handle.control.close)
        self.addCleanup(peer.close)
        handle.control.setblocking(False)
        handle._receipt_task = asyncio.get_running_loop().create_future()
        real_sleep = asyncio.sleep

        async def late_receipt(seconds):
            peer.sendall(boundary._supervision_frame(
                "cleanup", pid=handle.pid, pgid=handle.pgid,
                returncode=0, reaped=True, group_absent=True,
            ))
            receipt = await handle._read_receipt()
            handle._receipt_task.set_result(receipt)
            handle.process.returncode = 0
            # Resume only after the loop deadline, exercising its final guard.
            await real_sleep(.02)

        with patch.object(boundary, "_group_absent", return_value=False), \
                patch.object(boundary, "CLEANUP_SECONDS", .01), \
                patch.object(boundary.asyncio, "sleep", side_effect=late_receipt) as sleep, \
                patch.object(boundary.os, "killpg") as signal_group:
            clean = await handle._collect()
        self.assertFalse(clean)
        sleep.assert_awaited_once()
        self.assertTrue(handle.receipt["group_absent"])
        signal_group.assert_not_called()
        handle.process.kill.assert_not_called()
        handle.process.communicate.assert_not_called()


class CleanupCancellationTests(unittest.TestCase):
    def test_cancelled_inner_cleanup_returns_unknown_without_spinning(self):
        # A timeout inside the affected loop cannot interrupt its busy spin.
        # Bound the isolated interpreter externally; no owned worker is launched.
        script = """
import asyncio, json, sys
sys.path.insert(0, sys.argv[1])
from hydra_sdlc.execution_boundary import OwnedProcess

async def exercise():
    handle = OwnedProcess(['unused'])
    inner = asyncio.create_task(asyncio.sleep(60))
    inner.cancel()
    try:
        await inner
    except asyncio.CancelledError:
        pass
    handle._cleanup_task = inner
    clean = await handle.cleanup()
    return {'clean': clean, 'launched': handle.process is not None}

print(json.dumps(asyncio.run(exercise())))
"""
        completed = subprocess.run(
            [sys.executable, "-I", "-c", script, str(REPOSITORY)],
            capture_output=True, text=True, timeout=5,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.assertEqual(json.loads(completed.stdout), {"clean": False, "launched": False})


class HelperGroupOwnershipTests(unittest.TestCase):
    def simulate_reused_group(self, *, control_failure):
        from hydra_sdlc import execution_boundary as boundary

        child = SimpleNamespace(pid=41001, returncode=None)
        control = Mock()
        control.recv.side_effect = [boundary._supervision_frame("launch"), BlockingIOError]
        clock = [100.0]
        groups = []
        waits = []
        polls = []

        def waitpid(pid, options):
            self.assertEqual((pid, options), (-1, os.WNOHANG))
            # Reap the direct worker once. An adopted descendant that escaped
            # its group stays alive, so subsequent calls never report ECHILD.
            observed = (child.pid, 0) if not waits else (0, 0)
            waits.append(observed)
            return observed

        def group_absent(pgid):
            absent = not groups
            groups.append((pgid, absent))
            return absent  # A different process later reuses this numeric PGID.

        def poll(*args):
            polls.append(clock[0])
            if control_failure and len(polls) == 2:
                raise OSError("synthetic control failure after PGID reuse")
            clock[0] += .5
            return ([], [], [])

        def sleep(seconds):
            clock[0] += seconds

        with ExitStack() as stack:
            stack.enter_context(patch.object(boundary.socket, "socket", return_value=control))
            stack.enter_context(patch.object(boundary, "_enable_subreaper"))
            stack.enter_context(patch.object(boundary.signal, "signal"))
            stack.enter_context(patch.object(boundary.subprocess, "Popen", return_value=child))
            stack.enter_context(patch.object(boundary.os, "close"))
            stack.enter_context(patch.object(boundary.os, "waitpid", side_effect=waitpid))
            killpg = stack.enter_context(patch.object(boundary.os, "killpg"))
            stack.enter_context(patch.object(boundary, "_group_absent", side_effect=group_absent))
            stack.enter_context(patch.object(boundary.time, "monotonic", side_effect=lambda: clock[0]))
            stack.enter_context(patch.object(boundary.time, "sleep", side_effect=sleep))
            stack.enter_context(patch("select.select", side_effect=poll))
            result = boundary._supervisor_main(123, 110.0, ["synthetic-worker"])

        self.assertEqual(result, 2)
        self.assertEqual(child.returncode, 0)
        self.assertEqual(waits[0], (child.pid, 0))
        self.assertTrue(all(observed == (0, 0) for observed in waits[1:]))
        self.assertGreaterEqual(len(groups), 2)
        self.assertEqual(groups[0], (child.pid, True))
        self.assertTrue(all(observed == (child.pid, False) for observed in groups[1:]))
        killpg.assert_not_called()
        frames = [json.loads(call.args[0]) for call in control.sendall.call_args_list]
        self.assertEqual([frame["kind"] for frame in frames], ["ready"])
        control.close.assert_called_once()
        if control_failure:
            self.assertEqual(len(polls), 2)
        else:
            self.assertGreaterEqual(clock[0], 101.8)

    def test_reused_group_is_not_signaled_during_bounded_cleanup_timeout(self):
        self.simulate_reused_group(control_failure=False)

    def test_reused_group_is_not_signaled_after_control_failure(self):
        self.simulate_reused_group(control_failure=True)


if __name__ == "__main__":
    if len(sys.argv) == 4 and sys.argv[1] == "--driver":
        print(json.dumps(_driver(sys.argv[2], sys.argv[3])))
    elif len(sys.argv) == 4 and sys.argv[1] == "--supervisor":
        print(json.dumps(asyncio.run(_supervisor(sys.argv[2], sys.argv[3]))))
    elif len(sys.argv) == 4 and sys.argv[1] == "--worker":
        _worker(sys.argv[2], sys.argv[3])
    elif len(sys.argv) == 4 and sys.argv[1] == "--leaf":
        _leaf()
    else:
        unittest.main()
