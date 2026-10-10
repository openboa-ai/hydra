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
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path


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
    _mark(directory, "descendant", pid=child.pid)
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
        print(json.dumps({"available": True}), flush=True)
        return
    if mode == "owned":
        print("ready", flush=True)
    time.sleep(60)


async def _wait_for_descendant(directory):
    deadline = asyncio.get_running_loop().time() + 5
    while not any(item["name"] == "descendant" for item in _observations(directory)):
        if asyncio.get_running_loop().time() >= deadline:
            raise TimeoutError("worker did not create its resistant descendant")
        await asyncio.sleep(.01)


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

    class ObservedProcess(real_owned_process):
        async def start(self, *args, **kwargs):
            result = await super().start(*args, **kwargs)
            _mark(directory, "helper", pid=self.process.pid)
            _mark(directory, "owned", pid=self.pid, pgid=self.pgid)
            return result

        async def _read_control(self):
            frame = await super()._read_control()
            if mode == "invalid_receipt" and frame.get("kind") == "cleanup":
                # Preserve real setup, shutdown and reaping. Corrupt only the
                # identity in the actual helper's completed cleanup receipt.
                _mark(directory, "receipt_rewritten")
                return {**frame, "pid": frame["pid"] + 1}
            return frame

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


@unittest.skipUnless(sys.platform == "linux", "requires Linux subreaper and /proc semantics")
class LinuxProcessSupervisionTests(unittest.TestCase):
    def run_driver(self, mode):
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

    def test_completed_capability_reaps_descendant_before_available(self):
        report = self.run_driver("capability_completed")
        self.assert_clean(report)
        self.assertTrue(report["supervisor"]["result"]["available"])
        self.assertNotIn("cleanup", report["supervisor"]["result"])

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
        self.assertIn(result["start_error"], ("TimeoutError", "ProtocolError"))
        self.assertFalse(result["clean"])
        self.assertIsNotNone(result["helper_returncode"])
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
