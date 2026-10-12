"""Operating-mode barriers cover real launch and dispatch cancellation races."""

import asyncio
import json
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from hydra_sdlc import coordinator, execution_boundary as boundary
from hydra_sdlc.operations import OperatingControl, OperationDenied


REPO = "example/alpha"
DELAYED_DISPATCH = r'''
import asyncio, importlib.util, json, os, signal, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("boundary", sys.argv[1])
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
marker = Path(sys.argv[2])
def mark(name):
    with marker.open("a") as output:
        output.write(json.dumps({"name": name, "at": time.monotonic()}) + "\n")
async def execute(assignment, identity, event, stopped, resume_thread_id=None, on_dispatch=None):
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
    if not on_dispatch("thread/start"):
        return {"status": "interrupted", "thread_id": None, "turn_id": None, "detail": {}}
    mark("granted")
    time.sleep(.25)
    mark("provider_dispatch")
    identity(thread_id="thread-1")
    await asyncio.Event().wait()
b.worker_main(execute)
'''

DELAYED_HELPER = r'''
import importlib.util, json, os, subprocess, sys, time
from pathlib import Path
spec = importlib.util.spec_from_file_location("boundary", sys.argv[1])
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
marker, release = Path(sys.argv[5]), Path(sys.argv[6])
def mark(name, **values):
    with marker.open("a") as output:
        output.write(json.dumps({"name": name, "at": time.monotonic(), **values}) + "\n")
native_spawn = subprocess.Popen
def delayed_spawn(*args, **kwargs):
    # _supervisor_main has passed its final stop/deadline check here.
    mark("past_stop_check", helper=os.getpid())
    until = time.monotonic() + 5
    while not release.exists() and time.monotonic() < until:
        time.sleep(.005)
    child = native_spawn(*args, **kwargs)
    mark("child_created", pid=child.pid)
    return child
b.subprocess.Popen = delayed_spawn
if sys.platform != "linux":
    b._enable_subreaper = lambda: None
raise SystemExit(b._supervisor_main(int(sys.argv[2]), float(sys.argv[3]), json.loads(sys.argv[4])))
'''


@unittest.skipUnless(os.name == "posix", "owned POSIX process supervision")
class OperatingBoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.control = OperatingControl(self.root / "host.lock", (REPO,))
        self.control.set_mode("start")

    async def test_cancelling_launch_waiter_keeps_barrier_until_actual_creation(self):
        native_create = asyncio.create_subprocess_exec
        entered, release = asyncio.Event(), asyncio.Event()
        created = []

        async def delayed_create(*args, **kwargs):
            entered.set()
            await release.wait()
            process = await native_create(*args, **kwargs)
            created.append(time.monotonic())
            return process

        process = boundary.OwnedProcess([sys.executable, "-I", "-c", "import time; time.sleep(60)"])
        pause_entered = threading.Event()

        def pause():
            pause_entered.set()
            self.control.set_mode("pause")
            return time.monotonic()

        with coordinator.operation_scope(self.control, REPO), patch.object(
                asyncio, "create_subprocess_exec", delayed_create):
            task = asyncio.create_task(process.start(asyncio.get_running_loop().time() + 5))
            await asyncio.wait_for(entered.wait(), 2)
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            paused = asyncio.create_task(asyncio.to_thread(pause))
            await asyncio.to_thread(pause_entered.wait, 2)
            await asyncio.sleep(.03)
            premature_ack = paused.done()
            release.set()
            try:
                await asyncio.wait_for(asyncio.shield(process._launch), 3)
                acknowledged = await asyncio.wait_for(paused, 3)
                self.assertLessEqual(created[0], acknowledged)
            finally:
                self.assertTrue(await process.cleanup())
            self.assertFalse(premature_ack, "Pause acknowledged a still-pending native launch")

    async def test_denied_launch_is_confirmed_never_dispatched(self):
        self.control.set_mode("pause")
        process = boundary.OwnedProcess([sys.executable, "-I", "-c", "raise SystemExit(99)"])
        with coordinator.operation_scope(self.control, REPO):
            with self.assertRaises(OperationDenied):
                await process.start(asyncio.get_running_loop().time() + 2)
            self.assertTrue(await process.cleanup())
        self.assertIsNone(process.process)

    async def test_cancelled_grant_is_collected_before_pause_acknowledgement(self):
        marker = self.root / "dispatch.jsonl"
        command = [sys.executable, "-I", "-c", DELAYED_DISPATCH,
                   str(Path(boundary.__file__).resolve()), str(marker)]

        def observations():
            return [json.loads(line) for line in marker.read_text().splitlines()] if marker.exists() else []

        async def wait_grant(task):
            while not any(row["name"] == "granted" for row in observations()):
                if task.done():
                    self.fail("Worker exited before the dispatch grant")
                await asyncio.sleep(.005)

        def pause():
            self.control.set_mode("pause")
            return time.monotonic()

        with coordinator.operation_scope(self.control, REPO), patch.object(
                boundary, "_worker_command", return_value=command):
            task = asyncio.create_task(boundary.execute_worker(
                {}, lambda **values: None, lambda *values: None,
                lambda: bool(self.control.reason(REPO)), None,
                worker_source=Path(boundary.__file__), timeout=5, grace=0, poll=.005,
            ))
            await asyncio.wait_for(wait_grant(task), 3)
            paused = asyncio.create_task(asyncio.to_thread(pause))
            task.cancel()
            result = await asyncio.wait_for(task, 5)
            acknowledged = await asyncio.wait_for(paused, 3)
        self.assertNotEqual(result["detail"].get("cleanup"), "unknown")
        for row in observations():
            if row["name"] == "provider_dispatch":
                self.assertLessEqual(row["at"], acknowledged,
                                     "Granted dispatch continued after Pause acknowledgement")

    async def delayed_helper_race(self, synchronous):
        marker, release = self.root / "helper.jsonl", self.root / "release-helper"
        command = [sys.executable, "-I", "-c", "import time; time.sleep(60)"]

        def helper_command(argv, fd, deadline):
            return [sys.executable, "-I", "-c", DELAYED_HELPER,
                    str(Path(boundary.__file__).resolve()), str(fd), str(deadline),
                    json.dumps(argv), str(marker), str(release)]

        def observations():
            return [json.loads(line) for line in marker.read_text().splitlines()] if marker.exists() else []

        async def wait_helper(task):
            while not any(row["name"] == "past_stop_check" for row in observations()):
                if task.done():
                    self.fail("Helper ended before the delayed native Popen")
                await asyncio.sleep(.005)

        def pause():
            self.control.set_mode("pause")
            return time.monotonic()

        process = boundary.OwnedProcess(command)
        process.linux = True

        async def invoke():
            if synchronous:
                def run():
                    # Exercise the real Linux helper protocol on each POSIX
                    # host; the child skips only unavailable prctl on macOS.
                    with patch.object(boundary.sys, "platform", "linux"):
                        return boundary.run_owned_sync(command, cwd=self.root, env=None,
                            timeout=4, max_output_bytes=1024)
                return await asyncio.to_thread(run)
            try:
                await process.start(asyncio.get_running_loop().time() + 4)
            finally:
                self.assertTrue(await process.cleanup())

        with coordinator.operation_scope(self.control, REPO), \
                patch.object(boundary, "DISPATCH_SECONDS", .1), \
                patch.object(boundary, "_helper_command", side_effect=helper_command):
            task = asyncio.create_task(invoke())
            paused = None
            try:
                await asyncio.wait_for(wait_helper(task), 3)
                paused = asyncio.create_task(asyncio.to_thread(pause))
                # Pass the parent's admission deadline while the actual helper
                # is still between its final stop check and native Popen.
                await asyncio.sleep(.2)
                premature_ack = paused.done()
                release.touch()
                result = (await asyncio.wait_for(asyncio.gather(task, return_exceptions=True), 4))[0]
                acknowledged = await asyncio.wait_for(paused, 3)
                self.assertFalse(premature_ack, "Pause released a timed-out helper grant before collection")
                if synchronous:
                    self.assertNotIsInstance(result, BaseException)
                else:
                    self.assertIsInstance(result, TimeoutError)
                created = [row for row in observations() if row["name"] == "child_created"]
                self.assertEqual(len(created), 1)
                self.assertLessEqual(created[0]["at"], acknowledged)
            finally:
                release.touch()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                if paused is not None:
                    await asyncio.wait_for(paused, 3)

    async def test_async_timed_out_helper_grant_is_collected_before_pause_ack(self):
        await self.delayed_helper_race(False)

    async def test_sync_timed_out_helper_grant_is_collected_before_pause_ack(self):
        await self.delayed_helper_race(True)


if __name__ == "__main__":
    unittest.main()
