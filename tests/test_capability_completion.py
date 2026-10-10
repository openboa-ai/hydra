"""Capability output deadlines are independent of confirmed process collection."""

import asyncio
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc import codex, coordinator, execution_boundary as boundary


BOOT = "55555555-5555-4555-8555-555555555555"
REPORT = {
    "available": True,
    "sdk_version": "fixture-sdk",
    "runtime_version": "fixture-runtime",
    "account": {"status": "known", "type": "chatgpt", "authenticated": True},
    "models": {"status": "known", "ids": ["fixture-model"]},
    "usage": {"status": "known", "data": {"rateLimits": {"primary": {"usedPercent": 20}}}},
    "private_fixture_field": "must not propagate",
}
WORKER = """
import os, pathlib, sys, time
root = pathlib.Path(sys.argv[1])
(root / 'worker.pid').write_text(str(os.getpid()))
os.write(1, sys.argv[2].encode())
(root / 'emitted').touch()
mode = sys.argv[3]
if mode == 'open':
    while True:
        time.sleep(.005)
if mode == 'late':
    while not (root / 'release').exists():
        time.sleep(.005)
os.close(1)
(root / 'closed').touch()
if mode in ('late', 'rejected'):
    while True:
        time.sleep(.005)
if mode == 'gated':
    while not (root / 'release').exists():
        time.sleep(.005)
(root / 'natural-exit').touch()
os._exit(int(sys.argv[4]))
"""


class _LateEOF:
    """Release an actual open pipe only when its original read deadline expires."""

    def __init__(self, reader, root, events):
        self.reader, self.root, self.events = reader, root, events

    async def read(self):
        reading = asyncio.create_task(self.reader.read())
        try:
            return await asyncio.shield(reading)
        except asyncio.CancelledError:
            # A read can finish while cancellation is being delivered. Complete
            # the real EOF after this deadline, exercising the explicit clock
            # check as well as wait_for's cancellation behavior.
            self.events.append(("read-deadline", asyncio.get_running_loop().time()))
            (self.root / "release").touch()
            output = await reading
            observed_by = asyncio.get_running_loop().time() + 1
            while not (self.root / "closed").exists():
                if asyncio.get_running_loop().time() >= observed_by:
                    raise AssertionError("late EOF worker did not reach its cleanup phase")
                await asyncio.sleep(.001)
            self.events.append(("late-eof", asyncio.get_running_loop().time()))
            return output


@unittest.skipUnless(os.name == "posix", "requires actual POSIX probe processes")
class CapabilityCompletionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sequence = 0
        boot = patch.object(coordinator, "_boot_identity", return_value=BOOT)
        boot.start()
        self.addCleanup(boot.stop)

    async def probe(self, *, scenario="normal", payload=None, exitcode=0):
        self.sequence += 1
        root = self.root / str(self.sequence)
        root.mkdir()
        lock = root / "host.lock"
        events, handles = [], []
        worker_mode = {"early_eof": "gated", "open_stdout": "open", "late_eof": "late"}.get(
            scenario, "normal",
        )
        if payload is not None:
            worker_mode = "rejected"
        command = [sys.executable, "-I", "-c", WORKER, str(root),
                   json.dumps(REPORT) + "\n" if payload is None else payload,
                   worker_mode, str(exitcode)]

        class ObservedProcess(boundary.OwnedProcess):
            async def start(self, deadline):
                self.probe_deadline = deadline
                handles.append(self)
                await super().start(deadline)
                events.append(("started", asyncio.get_running_loop().time()))

            @property
            def stdout(self):
                reader = super().stdout
                return _LateEOF(reader, root, events) if scenario == "late_eof" else reader

            async def completion_gate(self):
                events.append(("completion-gate", asyncio.get_running_loop().time()))
                try:
                    await asyncio.Future()
                except asyncio.CancelledError:
                    events.append(("completion-deadline", asyncio.get_running_loop().time()))
                    raise

            async def wait(self):
                events.append(("wait-entered", asyncio.get_running_loop().time()))
                if not self.process.stdout.at_eof():
                    raise AssertionError("completion wait began before complete stdout EOF")
                if scenario == "early_eof":
                    if (root / "natural-exit").exists():
                        raise AssertionError("worker exited before the wait gate released it")
                    (root / "release").touch()
                result = await super().wait()
                events.append(("worker-collected", asyncio.get_running_loop().time()))
                if scenario == "slow_completion":
                    await self.completion_gate()
                if scenario == "wait_error":
                    raise RuntimeError("synthetic completion observation failure")
                return result

            async def communicate(self):
                # The same delayed completion also applies to the former API.
                # Thus the positive test fails when capability collection still
                # couples timely output to communicate() completing in time.
                result = await super().communicate()
                if scenario == "slow_completion":
                    await self.completion_gate()
                return result

            async def cleanup(self):
                events.append(("cleanup-entered", asyncio.get_running_loop().time()))
                if scenario == "ticket_failure":
                    with patch.object(coordinator.os, "fsync", side_effect=OSError("synthetic clear failure")):
                        clean = await super().cleanup()
                else:
                    clean = await super().cleanup()
                events.append(("cleanup-confirmed" if clean else "cleanup-unknown",
                               asyncio.get_running_loop().time()))
                return False if scenario == "cleanup_unknown" else clean

        with coordinator.coordinator_lock(lock), patch.object(
            codex, "_capability_command", return_value=command,
        ), patch.object(boundary, "OwnedProcess", ObservedProcess), patch.object(
            codex, "CAPABILITIES_TIMEOUT_SECONDS", 1.0,
        ):
            result = await codex.capabilities(str(root))
            marker = lock.read_bytes()

        self.assertEqual(len(handles), 1)
        handle = handles[0]
        self.assertTrue((root / "emitted").exists(), events)
        self.assertIsNotNone(handle.process.returncode, events)
        pid = int((root / "worker.pid").read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertTrue(boundary._group_absent(pid))
        return result, root, lock, marker, handle, events

    def assert_report(self, result):
        self.assertEqual(result, {key: value for key, value in REPORT.items()
                                  if key != "private_fixture_field"})
        self.assertNotIn("must not propagate", json.dumps(result))

    def assert_fresh_lock(self, lock):
        with coordinator.coordinator_lock(lock):
            self.assertEqual(lock.read_bytes(), b"")

    async def test_timely_report_survives_completion_wait_deadline(self):
        result, root, lock, marker, handle, events = await self.probe(scenario="slow_completion")
        self.assert_report(result)
        phases = [name for name, _ in events]
        self.assertLess(phases.index("worker-collected"), phases.index("completion-deadline"))
        self.assertLess(phases.index("completion-deadline"), phases.index("cleanup-entered"))
        observed = dict(events)
        self.assertLess(observed["worker-collected"], handle.probe_deadline)
        self.assertGreaterEqual(observed["completion-deadline"], handle.probe_deadline)
        self.assertTrue((root / "natural-exit").exists())
        self.assertEqual(handle.returncode, 0)
        self.assertEqual(marker, b"")
        self.assert_fresh_lock(lock)

    async def test_early_eof_preserves_remaining_time_for_normal_worker_exit(self):
        result, root, lock, marker, handle, events = await self.probe(scenario="early_eof")
        self.assert_report(result)
        phases = [name for name, _ in events]
        self.assertLess(phases.index("wait-entered"), phases.index("worker-collected"))
        self.assertLess(phases.index("worker-collected"), phases.index("cleanup-entered"))
        self.assertLess(dict(events)["worker-collected"], handle.probe_deadline)
        self.assertTrue((root / "natural-exit").exists())
        self.assertEqual(handle.returncode, 0)
        self.assertEqual(marker, b"")
        self.assert_fresh_lock(lock)

    async def test_valid_newline_without_eof_is_not_a_report(self):
        result, root, _, marker, _, events = await self.probe(scenario="open_stdout")
        self.assertFalse(result["available"])
        self.assertEqual(result["error_type"], "TimeoutError")
        self.assertNotIn("cleanup", result)
        self.assertNotIn("wait-entered", dict(events))
        self.assertFalse((root / "closed").exists())
        self.assertEqual(marker, b"")

    async def test_eof_received_during_deadline_cancellation_is_too_late(self):
        result, root, _, marker, handle, events = await self.probe(scenario="late_eof")
        self.assertFalse(result["available"])
        self.assertEqual(result["error_type"], "TimeoutError")
        self.assertGreaterEqual(dict(events)["late-eof"], handle.probe_deadline)
        self.assertNotIn("wait-entered", dict(events))
        self.assertTrue((root / "closed").exists())
        self.assertFalse((root / "natural-exit").exists())
        self.assertLess(handle.returncode, 0)
        self.assertEqual(marker, b"")

    async def test_malformed_trailing_and_invalid_reports_are_unavailable(self):
        for payload in ('{"available":', '{"available":true}\n{"available":true}\n',
                        '[]\n', '{"available":1}\n'):
            with self.subTest(payload=payload):
                result, root, _, marker, handle, events = await self.probe(payload=payload)
                self.assertFalse(result["available"])
                self.assertIn(result["error_type"], {"JSONDecodeError", "ValueError"})
                self.assertNotIn("wait-entered", dict(events))
                self.assertFalse((root / "natural-exit").exists())
                self.assertLess(handle.returncode, 0)
                self.assertEqual(marker, b"")

    async def test_timely_report_requires_actual_worker_exit_zero(self):
        result, _, _, marker, handle, events = await self.probe(exitcode=7)
        self.assertFalse(result["available"])
        self.assertEqual(result["error_type"], "AdapterUnavailable")
        self.assertEqual(handle.returncode, 7)
        self.assertIn("cleanup-confirmed", dict(events))
        self.assertEqual(marker, b"")

    async def test_timely_report_with_unknown_cleanup_is_unavailable(self):
        result, _, _, marker, handle, events = await self.probe(scenario="cleanup_unknown")
        self.assertFalse(result["available"])
        self.assertEqual(result["cleanup"], "unknown")
        self.assertEqual(handle.returncode, 0)
        self.assertIn("cleanup-confirmed", dict(events))
        self.assertEqual(marker, b"")

    async def test_non_timeout_completion_error_discards_timely_report(self):
        result, _, _, marker, handle, events = await self.probe(scenario="wait_error")
        self.assertFalse(result["available"])
        self.assertEqual(result["error_type"], "RuntimeError")
        self.assertEqual(handle.returncode, 0)
        self.assertIn("cleanup-confirmed", dict(events))
        self.assertEqual(marker, b"")

    async def test_durable_ticket_clear_failure_keeps_report_unavailable_and_restart_held(self):
        result, _, lock, marker, handle, events = await self.probe(scenario="ticket_failure")
        self.assertFalse(result["available"])
        self.assertEqual(result["cleanup"], "unknown")
        self.assertEqual(handle.returncode, 0)
        self.assertIn("cleanup-unknown", dict(events))
        self.assertTrue(marker)
        with self.assertRaises(coordinator.HostBusy):
            with coordinator.coordinator_lock(lock):
                self.fail("failed ownership retirement admitted a fresh capability probe")
        self.assertEqual(lock.read_bytes(), marker)


if __name__ == "__main__":
    unittest.main()
