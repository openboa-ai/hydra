"""Shared control gates hold across live controllers and owned cleanup paths."""

import asyncio
import copy
import json
import os
import tempfile
import threading
import unittest
from contextlib import asynccontextmanager
from pathlib import Path
from unittest.mock import patch

from hydra_sdlc.coordinator import HostBusy, observe_coordinator, operation_guard, operation_scope
from hydra_sdlc.github import GitHub as Client
from hydra_sdlc.native import NativeController
from hydra_sdlc.operations import OperatingControl, OperationDenied
from hydra_sdlc.runner import Runner
from hydra_sdlc.workspace import WorkspaceWait
from test_runner import GitHub, Workspace, complete_capabilities
from test_project import BASE
import test_github as github_fixtures


REPO = "example/product"
OTHER = "example/other"
URL = f"https://github.com/{REPO}/issues/4"


class OwnedWorkspace(Workspace):
    def __init__(self, *args):
        super().__init__(*args)
        self.existing_calls = 0

    def existing(self, repo, number, branch):
        self.existing_calls += 1
        if (repo, number, branch) != (REPO, 4, "hydra/issue-4"):
            raise WorkspaceWait("foreign_workspace")
        return self.path


class CheckpointGitHub(GitHub):
    def __init__(self):
        super().__init__()
        self.cleanup_records = []

    def record_checkpoint(self, repo, number, record):
        self.cleanup_records.append((repo, number, copy.deepcopy(record)))
        self.record(repo, number, record)


class OperationIntegrationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.lock = self.root / "host.lock"
        self.control = OperatingControl(self.lock, [REPO, OTHER])
        self.control.set_mode("start")
        self.gh = CheckpointGitHub()
        self.ws = OwnedWorkspace(self.root, self.gh)
        self.calls = []
        for name in ("hydra_sdlc.runner.load_project", "hydra_sdlc.native.load_project"):
            patched = patch(name, side_effect=lambda gh, repo, **kw: copy.deepcopy(gh.cfg))
            patched.start()
            self.addCleanup(patched.stop)
        workers = patch("hydra_sdlc.native.residual_workers", return_value=[])
        workers.start()
        self.addCleanup(workers.stop)

    def controller(self):
        return NativeController(self.gh, self.ws, repos=[REPO, OTHER], host_alias="test",
                                lock_path=self.lock, operations=self.control)

    async def capabilities(self, cwd):
        self.calls.append("capabilities")
        return complete_capabilities()

    async def execute(self, assignment, **kwargs):
        self.calls.append(self.gh.note["pending_action"])
        if assignment["mode"] == "workspace_write":
            self.ws.dirty = True
        return {"status": "completed", "detail": {"result": {"outcome": "candidate_ready"}}}

    def runner(self, **kwargs):
        return Runner(self.gh, self.ws, host_alias="test", execute=self.execute,
                      capabilities=self.capabilities, operations=self.control, **kwargs)

    @asynccontextmanager
    async def completed_during_control_update(self, *, action="resume", outcome="candidate_ready"):
        """Return a real completed model while a separate writer owns LOCK_EX."""
        self.control.set_mode("resume")
        self.gh = CheckpointGitHub()
        self.ws = OwnedWorkspace(self.root, self.gh)
        self.calls = []
        runner = self.runner()
        execute, checkpoint = runner.execute, self.ws.checkpoint
        published, release = threading.Event(), threading.Event()
        cleanup_attempted = asyncio.Event()
        replace = os.replace
        writers = []
        checkpoints = []

        def pending_replace(*args, **kwargs):
            replace(*args, **kwargs)
            published.set()
            if not release.wait(10):
                raise RuntimeError("fixture writer was not released")

        async def completed(assignment, **kwargs):
            result = await execute(assignment, **kwargs)
            if assignment["mode"] == "workspace_write":
                result["detail"]["result"]["outcome"] = outcome
                writers.append(asyncio.create_task(asyncio.to_thread(self.control.set_mode, action)))
                self.assertTrue(await asyncio.to_thread(published.wait, 5))
            return result

        def count_checkpoint(*args):
            checkpoints.append(args)
            return checkpoint(*args)

        original_cleanup = runner._checkpoint_ended_once
        def cleanup(*args):
            cleanup_attempted.set()
            return original_cleanup(*args)

        runner.execute, runner._checkpoint_ended_once = completed, cleanup
        self.ws.checkpoint = count_checkpoint
        with patch("hydra_sdlc.operations.os.replace", side_effect=pending_replace):
            task = asyncio.create_task(runner.step(REPO, 4))
            try:
                await asyncio.wait_for(cleanup_attempted.wait(), 5)
                yield runner, task, release, writers, checkpoints
            finally:
                release.set()
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, *writers, return_exceptions=True)

    async def test_completed_model_waits_for_real_busy_lock_then_checkpoints_under_pause(self):
        for outcome in ("candidate_ready", "needs_decision"):
            with self.subTest(outcome=outcome):
                async with self.completed_during_control_update(action="pause", outcome=outcome) as (
                        runner, task, release, writers, checkpoints):
                    self.assertFalse(task.done())
                    self.assertEqual(len(runner._pending_ended), 1)
                    # A timer can run while the writer remains exclusive.
                    await asyncio.sleep(0.04)
                    self.assertEqual(checkpoints, [])
                    release.set()
                    result = await asyncio.wait_for(task, 3)
                    await asyncio.gather(*writers)
                    self.assertEqual(result["reason"], "host_paused")
                    self.assertEqual(len(checkpoints), 1)
                    self.assertEqual(len(self.gh.cleanup_records), 1)
                    self.assertEqual(self.calls.count("implementation"), 1)
                    self.assertEqual(self.gh.note["phase"], "checkpoint")
                    self.assertIsNone(self.gh.note["pending_action"])
                    self.assertFalse(self.ws.dirty)
                    self.assertEqual(runner._pending_ended, {})
                    self.assertEqual(runner._unconfirmed_checkpoints, {})
                    if outcome == "needs_decision":
                        self.assertEqual(self.gh.note["wait_reason"], "product_decision")
                    self.assertFalse(any(write[0] in {"push", "pr", "merge", "close"} for write in self.gh.writes))

    async def test_prolonged_busy_retains_exact_end_for_cleanup_only_reentry(self):
        async with self.completed_during_control_update() as (runner, task, release, writers, checkpoints):
            result = await asyncio.wait_for(task, 3)
            self.assertEqual(result["reason"], "operation_state_busy")
            self.assertEqual(result["checkpoint_status"], "pending")
            self.assertEqual(len(runner._pending_ended), 1)
            self.assertEqual(checkpoints, [])
            self.assertEqual(self.gh.note["phase"], "executing")
            self.assertTrue(self.ws.dirty)
            calls = list(self.calls)
            held = await asyncio.wait_for(runner.drain_completed(REPO, 4), 2)
            self.assertEqual((held[0]["action"], held[0]["checkpoint_status"]), ("waiting", "pending"))
            self.assertEqual(held[0]["reason"], "operation_state_busy")
            self.assertEqual(checkpoints, [])
            self.assertEqual(self.calls, calls)
            release.set()
            await asyncio.gather(*writers)
            # The proof is intentionally not restart authority.
            self.assertEqual((await self.runner().step(REPO, 4))["reason"], "confirm_previous_stopped")
            result = await runner.step(REPO, 4)
            self.assertEqual((result["action"], result["checkpoint_status"]), ("continue", "recorded"))
            self.assertEqual(self.calls, calls)
            self.assertEqual(len(checkpoints), 1)
            self.assertEqual(len(self.gh.cleanup_records), 1)
            self.assertEqual(runner._pending_ended, {})
            self.assertFalse(any(write[0] in {"push", "pr", "merge", "close"} for write in self.gh.writes))

    async def test_cancelled_cleanup_retains_proof_and_unrelated_steps_do_not_clear_it(self):
        async with self.completed_during_control_update() as (runner, task, release, writers, checkpoints):
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            self.assertEqual(len(runner._pending_ended), 1)
            self.assertEqual(runner._settling_ended, set())
            proof = dict(runner._pending_ended)
            release.set()
            await asyncio.gather(*writers)
            async def unrelated(repo, number):
                self.assertIsNone(runner._ended_execution.get())
                return {"repository": repo, "issue": number, "action": "continue"}
            with patch.object(runner, "_step", side_effect=unrelated):
                for target in ((OTHER, 4), (REPO, 5)):
                    self.assertEqual((await runner.step(*target))["action"], "continue")
                    self.assertEqual(runner._pending_ended, proof)
                self.assertEqual((await runner.step(REPO, 4))["checkpoint_status"], "recorded")
            self.assertEqual(self.calls.count("implementation"), 1)
            self.assertEqual(len(checkpoints), 1)
            self.assertEqual(runner._pending_ended, {})

    async def test_concurrent_same_target_cannot_consume_pending_proof_twice(self):
        async with self.completed_during_control_update() as (runner, task, release, writers, checkpoints):
            other = await asyncio.wait_for(runner.step(REPO, 4), 1)
            self.assertEqual((other["reason"], other["checkpoint_status"]), ("operation_state_busy", "pending"))
            self.assertEqual(len(runner._pending_ended), 1)
            release.set()
            await asyncio.wait_for(task, 3)
            await asyncio.gather(*writers)
            self.assertEqual(len(checkpoints), 1)
            self.assertEqual(self.calls.count("implementation"), 1)
            self.assertEqual(runner._pending_ended, {})

    async def test_deferred_end_never_overwrites_changed_identity_or_remote_intent(self):
        changes = (
            {"attempt_id": "22222222-2222-4222-8222-222222222222"},
            {"contract_revision": "d" * 40}, {"host_alias": "another-host"},
            {"branch": "hydra/issue-5"}, {"head": "d" * 40},
            {"expected_head": "d" * 40}, {"intake_digest": "d" * 64},
            {"spec_revision": "d" * 40}, {"phase": "publishing", "pending_action": "publish"},
        )
        for change in changes:
            with self.subTest(change=change):
                async with self.completed_during_control_update() as (runner, task, release, writers, checkpoints):
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    self.gh.note.update(change)
                    expected = copy.deepcopy(self.gh.note)
                    release.set()
                    await asyncio.gather(*writers)
                    result = await runner.step(REPO, 4)
                    self.assertEqual((result["reason"], result["checkpoint_status"]),
                                     ("checkpoint_state_changed", "superseded"))
                    self.assertEqual(self.gh.note, expected)
                    self.assertEqual(checkpoints, [])
                    self.assertEqual(self.gh.cleanup_records, [])
                    self.assertEqual(self.calls.count("implementation"), 1)
                    self.assertEqual(runner._pending_ended, {})

    async def test_unknown_checkpoint_result_is_observed_without_effect_replay(self):
        for applied in (False, True):
            with self.subTest(applied=applied):
                async with self.completed_during_control_update() as (runner, task, release, writers, checkpoints):
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    release.set()
                    await asyncio.gather(*writers)
                    write = self.gh.record_checkpoint
                    attempts = []
                    def uncertain(*args):
                        attempts.append(args)
                        if applied:
                            write(*args)
                        raise OperationDenied("operation_state_busy")
                    self.gh.record_checkpoint = uncertain
                    result = await runner.step(REPO, 4)
                    self.assertEqual(result["action"], "waiting")
                    self.assertEqual(result["reason"], "checkpoint_recording_unconfirmed")
                    again = await runner.step(REPO, 4)
                    self.assertEqual(len(attempts), 1)
                    self.assertEqual(len(checkpoints), 1)
                    self.assertEqual(self.calls.count("implementation"), 1)
                    if applied:
                        self.assertEqual(again["checkpoint_status"], "recorded")
                        self.assertEqual(runner._pending_ended, {})
                    else:
                        self.assertEqual(again["reason"], "checkpoint_recording_unconfirmed")
                        self.assertEqual(len(runner._pending_ended), 1)
                    self.assertFalse(any(row[0] in {"push", "pr", "merge", "close"} for row in self.gh.writes))

    async def test_local_checkpoint_failure_can_retry_before_any_remote_write(self):
        for committed in (False, True):
            with self.subTest(committed=committed):
                async with self.completed_during_control_update(action="pause") as (
                        runner, task, release, writers, checkpoints):
                    task.cancel()
                    with self.assertRaises(asyncio.CancelledError):
                        await task
                    release.set()
                    await asyncio.gather(*writers)
                    checkpoint = self.ws.checkpoint
                    attempts = []
                    before_head, before_writes = self.ws.head, len(self.gh.writes)
                    def fail_once(*args):
                        attempts.append(args)
                        if len(attempts) == 1:
                            if committed:
                                checkpoint(*args)
                            raise WorkspaceWait("git_operation_failed")
                        return checkpoint(*args)
                    self.ws.checkpoint = fail_once
                    first = (await runner.drain_completed())[0]
                    self.assertEqual((first["action"], first["reason"]),
                                     ("waiting", "checkpoint_recording_unconfirmed"))
                    failed_head = self.ws.head
                    self.assertEqual(failed_head == before_head, not committed)
                    self.assertEqual(len(runner._pending_ended), 1)
                    self.assertEqual(runner._unconfirmed_checkpoints, {})
                    self.assertEqual(len(self.gh.writes), before_writes)
                    self.assertEqual(self.gh.cleanup_records, [])
                    result = (await runner.drain_completed())[0]
                    self.assertEqual((result["action"], result["checkpoint_status"]), ("continue", "recorded"))
                    self.assertEqual(len(attempts), 2)
                    self.assertEqual(len(checkpoints), 2 if committed else 1)
                    if committed:
                        self.assertEqual(self.ws.head, failed_head)
                    self.assertEqual(self.gh.note["head"], self.ws.head)
                    self.assertEqual(len(self.gh.cleanup_records), 1)
                    self.assertEqual(runner._pending_ended, {})
                    self.assertEqual(runner._unconfirmed_checkpoints, {})
                    self.assertEqual(self.calls.count("implementation"), 1)
                    self.assertFalse(any(row[0] in {"push", "pr", "merge", "close"} for row in self.gh.writes))

    async def test_spec_read_failure_can_retry_after_local_checkpoint(self):
        async with self.completed_during_control_update(action="pause") as (runner, task, release, writers, checkpoints):
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            release.set()
            await asyncio.gather(*writers)
            spec_changed = runner._spec_changed
            reads = []
            def unavailable_once(*args):
                reads.append(args)
                if len(reads) == 1:
                    raise WorkspaceWait("git_operation_failed")
                return spec_changed(*args)
            with patch.object(runner, "_spec_changed", side_effect=unavailable_once):
                first = (await runner.drain_completed())[0]
                self.assertEqual(first["reason"], "checkpoint_recording_unconfirmed")
                checkpoint_head = self.ws.head
                self.assertFalse(self.ws.dirty)
                self.assertEqual(len(checkpoints), 1)
                self.assertEqual(self.gh.cleanup_records, [])
                self.assertEqual(runner._unconfirmed_checkpoints, {})
                self.assertEqual(len(runner._pending_ended), 1)
                result = (await runner.drain_completed())[0]
            self.assertEqual(result["checkpoint_status"], "recorded")
            self.assertEqual(len(reads), 2)
            self.assertEqual(len(checkpoints), 2)
            self.assertEqual(self.ws.head, checkpoint_head)
            self.assertEqual(self.gh.note["head"], checkpoint_head)
            self.assertEqual(len(self.gh.cleanup_records), 1)
            self.assertEqual(runner._pending_ended, {})
            self.assertEqual(runner._unconfirmed_checkpoints, {})
            self.assertEqual(self.calls.count("implementation"), 1)
            self.assertFalse(any(row[0] in {"push", "pr", "merge", "close"} for row in self.gh.writes))

    async def test_exact_readback_rejects_changed_checkpoint_after_lost_response(self):
        async with self.completed_during_control_update() as (runner, task, release, writers, checkpoints):
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            release.set()
            await asyncio.gather(*writers)
            original = self.gh.record_checkpoint
            attempts = []
            def uncertain(*args):
                attempts.append(args)
                original(*args)
                raise RuntimeError("synthetic response lost")
            self.gh.record_checkpoint = uncertain
            self.assertEqual((await runner.drain_completed())[0]["reason"], "checkpoint_recording_unconfirmed")
            self.gh.note["next_action"] = "operator_decision"
            observed = copy.deepcopy(self.gh.note)
            result = await runner.drain_completed()
            self.assertEqual(result[0]["checkpoint_status"], "superseded")
            self.assertEqual(self.gh.note, observed)
            self.assertEqual(len(attempts), 1)
            self.assertEqual(len(checkpoints), 1)
            self.assertEqual(self.calls.count("implementation"), 1)

    async def test_spec_checkpoint_intermediate_write_keeps_final_readback_proof(self):
        async with self.completed_during_control_update() as (runner, task, release, writers, checkpoints):
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            release.set()
            await asyncio.gather(*writers)
            original = self.gh.record_checkpoint
            attempts = []
            def final_response_lost(*args):
                attempts.append(copy.deepcopy(args[2]))
                original(*args)
                if len(attempts) == 2:
                    raise RuntimeError("synthetic final response lost")
            self.gh.record_checkpoint = final_response_lost
            with patch.object(runner, "_spec_changed", return_value=True):
                result = await runner.drain_completed()
            self.assertEqual(result[0]["reason"], "checkpoint_recording_unconfirmed")
            self.assertEqual(len(runner._pending_ended), 1)
            self.assertEqual([row["phase"] for row in attempts], ["design_done", "checkpoint"])
            self.assertEqual((await runner.drain_completed())[0]["checkpoint_status"], "recorded")
            self.assertEqual(len(attempts), 2)
            self.assertEqual(len(checkpoints), 1)
            self.assertEqual(self.calls.count("implementation"), 1)
            self.assertEqual(runner._pending_ended, {})
            self.assertEqual(runner._unconfirmed_checkpoints, {})

    async def test_cycle_drains_completed_proof_even_when_project_is_paused(self):
        async with self.completed_during_control_update(action="pause") as (runner, task, release, writers, checkpoints):
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task
            release.set()
            await asyncio.gather(*writers)
            calls = list(self.calls)
            result = await runner.cycle([REPO])
            self.assertEqual(result[0]["checkpoint_status"], "recorded")
            self.assertEqual(result[1]["reason"], "host_paused")
            self.assertEqual(self.calls, calls)
            self.assertEqual(len(checkpoints), 1)
            self.assertEqual(runner._pending_ended, {})
            self.assertFalse(any(row[0] in {"push", "pr", "merge", "close"} for row in self.gh.writes))

    async def test_normal_completion_does_not_schedule_cleanup_reentry(self):
        runner = self.runner()
        self.assertEqual((await runner.step(REPO, 4))["action"], "continue")
        self.assertEqual(self.gh.note["phase"], "implementation_done")
        self.assertEqual(runner._pending_ended, {})
        self.assertEqual(await runner.drain_completed(), [])
        self.assertEqual(self.gh.cleanup_records, [])

    async def checkpoint(self, controller, assignment, outcome="candidate_ready", **changes):
        values = dict(url=URL, attempt_id=assignment["attempt_id"], step_id=assignment["step_id"],
                      head=assignment["head"], contract_revision=assignment["contract_revision"], outcome=outcome)
        values.update(changes)
        return await controller.checkpoint(**values)

    async def test_live_controller_and_runner_observe_new_pause_without_reload(self):
        controller, runner = self.controller(), self.runner()
        self.control.set_mode("pause")
        self.assertEqual((await controller.begin(URL))["reason"], "host_paused")
        self.assertEqual((await runner.step(REPO, 4))["reason"], "host_paused")
        self.assertEqual(await runner.cycle([REPO, OTHER]), [
            {"repository": REPO, "action": "waiting", "reason": "host_paused",
             "progress_hint": {"kind": "human", "next_action": "await_control_change", "wake_source": "control_change"}},
            {"repository": OTHER, "action": "waiting", "reason": "host_paused",
             "progress_hint": {"kind": "human", "next_action": "await_control_change", "wake_source": "control_change"}}])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.gh.writes, [])
        self.assertFalse(self.lock.exists())

    async def test_paused_candidate_and_advance_preserve_ticket_until_exact_stopped(self):
        controller = self.controller()
        assignment = await controller.begin(URL)
        self.assertEqual(assignment["action"], "native_task")
        ticket = self.lock.read_bytes()
        prepared = len(self.ws.prepared_recovery)
        writes = len(self.gh.writes)
        self.ws.dirty = True
        self.control.set_mode("pause", REPO)
        self.assertEqual((await self.checkpoint(controller, assignment))["reason"], "project_paused")
        self.assertEqual((await controller.advance(URL, assignment["attempt_id"], assignment["head"],
                                                  assignment["contract_revision"]))["reason"], "project_paused")
        self.assertEqual(self.lock.read_bytes(), ticket)
        self.assertEqual(len(self.gh.writes), writes)
        with self.assertRaises(HostBusy):
            await self.checkpoint(controller, assignment, "stopped", head="e" * 40)
        self.assertEqual(self.lock.read_bytes(), ticket)
        result = await self.checkpoint(controller, assignment, "stopped")
        self.assertEqual(result["reason"], "stop_requested")
        self.assertFalse(self.ws.dirty)
        self.assertEqual(self.lock.read_bytes(), b"")
        self.assertEqual(self.ws.existing_calls, 1)
        self.assertEqual(len(self.ws.prepared_recovery), prepared)
        self.assertTrue(self.gh.cleanup_records)
        self.assertTrue(all(write[0] == "record" for write in self.gh.writes[writes:]))
        self.assertIsNone(self.gh.branch)
        self.assertIsNone(self.gh.pr)

    async def test_never_dispatched_exact_ticket_can_retire_without_creating_progress(self):
        controller = self.controller()
        original = self.gh.record
        def fail_assignment(repo, number, record):
            if record.get("native_step"):
                raise RuntimeError("Synthetic pre-write failure")
            return original(repo, number, record)
        self.gh.record = fail_assignment
        assignment = await controller.begin(URL)
        self.assertEqual(assignment["reason"], "assignment_record_unknown")
        self.assertIsNone(self.gh.note)
        prepared = len(self.ws.prepared_recovery)
        self.control.set_mode("stop")
        result = await self.checkpoint(controller, assignment, "stopped")
        self.assertEqual(result["reason"], "stop_requested")
        self.assertEqual(self.lock.read_bytes(), b"")
        self.assertIsNone(self.gh.note)
        self.assertEqual(self.gh.cleanup_records, [])
        self.assertEqual(self.ws.existing_calls, 0)
        self.assertEqual(len(self.ws.prepared_recovery), prepared)

    async def test_stopped_readback_failure_preserves_ticket_until_reconciliation(self):
        controller = self.controller()
        assignment = await controller.begin(URL)
        ticket = self.lock.read_bytes()
        self.control.set_mode("stop")
        original = self.gh.progress
        def unavailable(repo, number):
            record = original(repo, number)
            return None if record and record.get("native_outcome") == "stopped" else record
        with patch.object(self.gh, "progress", side_effect=unavailable):
            with self.assertRaisesRegex(RuntimeError, "read-back"):
                await self.checkpoint(controller, assignment, "stopped")
        self.assertEqual(self.lock.read_bytes(), ticket)
        self.assertEqual(self.gh.note["native_outcome"], "stopped")
        self.assertEqual((await self.checkpoint(controller, assignment, "stopped"))["reason"], "stop_requested")
        self.assertEqual(self.lock.read_bytes(), b"")
        self.assertFalse(any(write[0] in {"push", "pr", "merge", "close"} for write in self.gh.writes))

    async def test_pause_after_intent_restores_known_undispatched_work_for_resume(self):
        runner = self.runner()
        original = runner._latest
        paused = False
        def pause_after_record(repo, number, config, **kwargs):
            nonlocal paused
            if not paused and self.gh.note and self.gh.note.get("pending_action") == "implementation":
                paused = True
                self.control.set_mode("pause")
            return original(repo, number, config, **kwargs)
        runner._latest = pause_after_record
        result = await runner.step(REPO, 4)
        self.assertEqual(result["reason"], "host_paused")
        self.assertNotEqual(self.gh.note["phase"], "executing")
        self.assertIsNone(self.gh.note.get("pending_action"))
        self.assertNotIn("implementation", self.calls)
        self.assertTrue(self.gh.cleanup_records)
        self.control.set_mode("resume")
        self.assertEqual((await runner.step(REPO, 4))["action"], "continue")
        self.assertIn("implementation", self.calls)

    async def test_sdk_pause_preserves_checkpoint_without_old_stop_path_push(self):
        runner = self.runner()
        original = runner.execute
        async def interrupted(assignment, **kwargs):
            if assignment["mode"] == "read_only":
                return await original(assignment, **kwargs)
            self.ws.dirty = True
            self.control.set_mode("pause", REPO)
            self.assertTrue(kwargs["stop_requested"]())
            return {"status": "interrupted", "detail": {"cleanup": "confirmed"}}
        runner.execute = interrupted
        result = await runner.step(REPO, 4)
        self.assertEqual(result["reason"], "stop_requested")
        self.assertEqual(self.gh.note["checkpoint"], "interrupted_committed")
        self.assertFalse(self.ws.dirty)
        self.assertIsNone(self.gh.branch)
        self.assertFalse(any(write[0] in {"push", "pr", "merge", "close"} for write in self.gh.writes))
        self.assertTrue(self.gh.cleanup_records)

    async def test_completed_sdk_pause_preserves_restartable_checkpoint_at_each_boundary(self):
        for boundary in ("completed_return", "local_checkpoint", "progress_write", "invalid_result"):
            with self.subTest(boundary=boundary):
                self.control.set_mode("resume")
                self.gh = CheckpointGitHub()
                self.ws = OwnedWorkspace(self.root, self.gh)
                self.calls = []
                runner = self.runner()
                execute, effect, record = runner.execute, runner._workspace_effect, runner._record
                paused = False
                def pause_once():
                    nonlocal paused
                    if not paused:
                        paused = True
                        self.control.set_mode("pause")
                async def completed(assignment, **kwargs):
                    result = await execute(assignment, **kwargs)
                    if boundary in {"completed_return", "invalid_result"} and assignment["mode"] == "workspace_write":
                        pause_once()
                        if boundary == "invalid_result":
                            result["detail"]["result"] = {"outcome": "invalid"}
                    return result
                def checkpoint(repo, method, *args, **kwargs):
                    if boundary == "local_checkpoint" and method == "checkpoint" and args[-1].startswith("Implement"):
                        pause_once()
                    return effect(repo, method, *args, **kwargs)
                def progress(repo, number, previous, **values):
                    if boundary == "progress_write" and values.get("phase") == "implementation_done":
                        pause_once()
                    return record(repo, number, previous, **values)
                runner.execute, runner._workspace_effect, runner._record = completed, checkpoint, progress
                result = await runner.step(REPO, 4)
                self.assertEqual(result["reason"], "host_paused")
                self.assertEqual(self.gh.note["phase"], "checkpoint")
                self.assertIsNone(self.gh.note["pending_action"])
                self.assertEqual(self.gh.note["checkpoint"], "interrupted_committed")
                self.assertFalse(self.ws.dirty)
                self.assertFalse(any(write[0] in {"push", "pr", "merge", "close"} for write in self.gh.writes))
                self.assertIsNone(runner._ended_execution.get())
                self.control.set_mode("resume")
                self.assertNotEqual((await self.runner().step(REPO, 4)).get("reason"), "confirm_previous_stopped")

    async def test_pause_cannot_discard_a_completed_product_decision(self):
        for boundary in ("completed_return", "decision_record"):
            with self.subTest(boundary=boundary):
                self.control.set_mode("resume")
                self.gh = CheckpointGitHub()
                self.ws = OwnedWorkspace(self.root, self.gh)
                self.calls = []
                runner = self.runner()
                execute, record = runner.execute, runner._record
                pause_threads = []
                async def question(assignment, **kwargs):
                    result = await execute(assignment, **kwargs)
                    if assignment["mode"] == "workspace_write":
                        result["detail"]["result"]["outcome"] = "needs_decision"
                        if boundary == "completed_return":
                            self.control.set_mode("pause")
                    return result
                def recorded(repo, number, previous, **values):
                    result = record(repo, number, previous, **values)
                    if boundary == "decision_record" and values.get("wait_reason") == "product_decision":
                        thread = threading.Thread(target=self.control.set_mode, args=("pause",))
                        pause_threads.append(thread)
                        thread.start()
                    return result
                runner.execute, runner._record = question, recorded
                await runner.step(REPO, 4)
                for thread in pause_threads:
                    await asyncio.to_thread(thread.join, 3)
                    self.assertFalse(thread.is_alive())
                self.assertEqual(self.control.reason(), "host_paused")
                self.assertEqual(self.gh.note["wait_reason"], "product_decision")
                self.assertEqual(self.gh.note["next_action"], "operator_decision")
                self.assertIsNone(self.gh.note.get("pending_action"))
                self.assertFalse(self.ws.dirty)
                self.assertIsNone(self.gh.branch)
                before = list(self.calls)
                self.control.set_mode("resume")
                self.assertEqual((await self.runner().step(REPO, 4))["reason"], "product_decision")
                self.assertEqual(self.calls, before)

    async def test_spec_checkpoint_preserves_decision_across_competing_pause(self):
        runner = self.runner()
        execute = runner.execute
        threads = []
        edited = False
        spec = "docs/engineering/task/spec.md"
        original_paths = self.ws.changed_paths
        self.ws.changed_paths = lambda path, base: [spec, "src/main.py"] if edited else original_paths(path, base)
        async def question(assignment, **kwargs):
            nonlocal edited
            result = await execute(assignment, **kwargs)
            if assignment["mode"] == "workspace_write":
                edited = True
                result["detail"]["result"]["outcome"] = "needs_decision"
            return result
        def after_spec(record):
            if record.get("phase") == "design_done" and not threads:
                self.assertEqual(record.get("wait_reason"), "product_decision")
                self.assertEqual(record.get("next_action"), "operator_decision")
                thread = threading.Thread(target=self.control.set_mode, args=("pause",))
                threads.append(thread)
                thread.start()
        runner.execute, self.gh.on_record = question, after_spec
        await runner.step(REPO, 4)
        self.assertEqual(len(threads), 1)
        await asyncio.to_thread(threads[0].join, 3)
        self.assertFalse(threads[0].is_alive())
        self.assertEqual(self.control.reason(), "host_paused")
        self.assertEqual(self.gh.note["wait_reason"], "product_decision")
        self.assertEqual(self.gh.note["next_action"], "operator_decision")
        self.assertFalse(self.ws.dirty)
        before = list(self.calls)
        self.control.set_mode("resume")
        self.assertEqual((await self.runner().step(REPO, 4))["reason"], "product_decision")
        self.assertEqual(self.calls, before)

    async def test_native_stopped_cleanup_preserves_an_already_recorded_question(self):
        controller = self.controller()
        assignment = await controller.begin(URL)
        assignment = await self.checkpoint(controller, assignment)
        self.assertEqual(assignment["phase"], "implementation")
        self.ws.dirty = True
        record = controller.runner._record
        def paused_after_outcome(repo, number, previous, **values):
            result = record(repo, number, previous, **values)
            if values.get("native_outcome") == "needs_decision":
                self.control.set_mode("pause")
            return result
        controller.runner._record = paused_after_outcome
        result = await self.checkpoint(controller, assignment, "needs_decision")
        self.assertEqual(result["reason"], "host_paused")
        self.assertEqual(self.gh.note["native_outcome"], "needs_decision")
        self.assertTrue(self.lock.read_bytes())
        self.assertEqual((await self.checkpoint(controller, assignment, "stopped"))["reason"], "product_decision")
        self.assertEqual(self.lock.read_bytes(), b"")
        self.assertEqual(self.gh.note["wait_reason"], "product_decision")
        self.assertFalse(self.ws.dirty)
        self.assertIsNone(self.gh.branch)
        self.control.set_mode("resume")
        self.assertEqual((await self.controller().begin(URL))["reason"], "product_decision")
        self.assertEqual(self.lock.read_bytes(), b"")

    async def assert_native_retirement_barrier(self, kind):
        from hydra_sdlc.native import confirm_native_assignment

        controller = self.controller()
        assignment = await controller.begin(URL)
        if kind in {"write", "stale_review"}:
            assignment = await self.checkpoint(controller, assignment)
            self.ws.dirty = True
        if kind == "stale_review":
            await self.checkpoint(controller, assignment)
            current = self.gh.note
            assignment = await controller.advance(URL, current["attempt_id"], current["head"], current["contract_revision"])
            self.assertEqual(assignment["phase"], "change_review")
            controller = self.controller()  # No process-local verification review receipt.
        step = assignment["step_id"]
        progress = self.gh.progress
        observed, attempts, failures = [], [], []

        def pause_from_another_owner():
            async def pause():
                try:
                    control = OperatingControl(self.lock, [REPO, OTHER])
                    attempts.append(control.set_mode("pause", REPO))
                except OperationDenied as exc:
                    attempts.append(exc.reason)
            try:
                asyncio.run(pause())  # Real async control takes the nonblocking OS-lock path.
            except BaseException as exc:
                failures.append(exc)

        def readback(repo, number):
            value = progress(repo, number)
            if value and not value.get("native_step") and not observed and step.encode() in self.lock.read_bytes():
                observed.append(copy.deepcopy(value))
                writer = threading.Thread(target=pause_from_another_owner)
                writer.start()
                writer.join(5)
                self.assertFalse(writer.is_alive(), "Control lock probe did not finish")
            return value

        def confirm(retired):
            self.assertEqual(retired, step)
            self.assertTrue(observed, "Exact clean progress must be read back before ticket release")
            self.assertEqual(observed[0]["attempt_id"], assignment["attempt_id"])
            self.assertNotIn(step, controller.runner.consumed)
            return confirm_native_assignment(retired)

        with patch.object(self.gh, "progress", side_effect=readback), \
                patch("hydra_sdlc.native.confirm_native_assignment", side_effect=confirm) as retired:
            result = await self.checkpoint(controller, assignment,
                "candidate_ready" if kind == "stale_review" else "needs_decision")
        self.assertEqual(failures, [])
        self.assertEqual(attempts, ["operation_state_busy"])
        retired.assert_called_once_with(step)
        self.assertIn(step, controller.runner.consumed)
        self.assertNotIn(step.encode(), self.lock.read_bytes())
        self.assertFalse(self.ws.dirty)

        # The real mutation succeeds after the bounded retirement guard exits.
        self.assertEqual(self.control.set_mode("pause", REPO)["projects"][REPO], "paused")
        if kind == "stale_review":
            self.assertEqual(result["phase"], "change_review")
            self.assertNotEqual(result["step_id"], step)
            await self.checkpoint(controller, result, "stopped")
        else:
            self.assertEqual(result["reason"], "product_decision")
            self.assertEqual(self.gh.note["wait_reason"], "product_decision")
            self.assertEqual(self.gh.note["next_action"], "operator_decision")
            self.control.set_mode("resume", REPO)
            self.assertEqual((await self.controller().begin(URL))["reason"], "product_decision")
        self.assertEqual(self.lock.read_bytes(), b"")
        self.assertIsNone(self.gh.branch)

    async def test_native_write_retirement_excludes_a_real_concurrent_pause(self):
        await self.assert_native_retirement_barrier("write")

    async def test_native_review_retirement_excludes_a_real_concurrent_pause(self):
        await self.assert_native_retirement_barrier("review")

    async def test_stale_native_review_retirement_excludes_a_real_concurrent_pause(self):
        await self.assert_native_retirement_barrier("stale_review")

    async def assert_retirement_policy_read_outside_admission(self, kind):
        import hydra_sdlc.runner as runner_module

        protected_read = runner_module.load_project
        probes = []
        def read(*args, **kwargs):
            expected_phase = {"write": "implementation", "review": "spec_review",
                              "stale_review": "change_review"}[kind]
            expected_outcome = "candidate_ready" if kind == "stale_review" else "needs_decision"
            note = self.gh.note or {}
            if (note.get("native_phase"), note.get("native_outcome")) != (expected_phase, expected_outcome):
                return protected_read(*args, **kwargs)
            def probe():
                try:
                    # An independent owner takes the real exclusive lock. The
                    # already-running host mode makes this a no-write probe.
                    OperatingControl(self.lock, [REPO, OTHER]).set_mode_if_current(
                        "resume", expected_revision=1, blocking=False)
                    probes.append("acquired")
                except OperationDenied as exc:
                    probes.append(exc.reason)
            thread = threading.Thread(target=probe)
            thread.start()
            thread.join(5)
            self.assertFalse(thread.is_alive(), "Policy lock probe did not finish")
            self.assertNotEqual(probes[-1], "operation_state_busy",
                                "Protected policy was read inside the admission lock")
            return protected_read(*args, **kwargs)

        with patch.object(runner_module, "load_project", side_effect=read):
            await self.assert_native_retirement_barrier(kind)
        self.assertTrue(probes, "No current protected policy was observed")

    async def test_write_retirement_reads_policy_outside_admission(self):
        await self.assert_retirement_policy_read_outside_admission("write")

    async def test_review_retirement_reads_policy_outside_admission(self):
        await self.assert_retirement_policy_read_outside_admission("review")

    async def test_stale_review_retirement_reads_policy_outside_admission(self):
        await self.assert_retirement_policy_read_outside_admission("stale_review")

    async def test_pause_after_retirement_policy_preflight_keeps_exact_owner(self):
        controller = self.controller()
        assignment = await self.checkpoint(controller, await controller.begin(URL))
        self.ws.dirty = True
        require = controller.runner._require_policy
        pauses = []
        def pause_after_preflight(repo):
            require(repo)
            note = self.gh.note or {}
            if (not pauses and note.get("native_step") == assignment["step_id"]
                    and note.get("checkpoint") == "interrupted_committed"):
                pauses.append(self.control.set_mode("pause", REPO))
        with patch.object(controller.runner, "_require_policy", side_effect=pause_after_preflight):
            result = await self.checkpoint(controller, assignment, "needs_decision")
        self.assertEqual(result["reason"], "project_paused")
        self.assertEqual(len(pauses), 1)
        self.assertEqual(self.gh.note["native_step"], assignment["step_id"])
        self.assertIn(assignment["step_id"].encode(), self.lock.read_bytes())
        self.assertNotIn(assignment["step_id"], controller.runner.consumed)
        self.assertFalse(self.ws.dirty)
        self.assertEqual((await self.checkpoint(controller, assignment, "stopped"))["reason"], "product_decision")
        self.assertEqual(self.lock.read_bytes(), b"")

    async def test_policy_change_during_retirement_cannot_admit_later_work(self):
        controller = self.controller()
        assignment = await self.checkpoint(controller, await controller.begin(URL))
        self.ws.dirty = True
        write = self.gh.record
        changes = []
        def change_source(repo, number, record):
            value = write(repo, number, record)
            if (not changes and record.get("checkpoint") == "interrupted_committed"
                    and not record.get("native_step")):
                changes.append(True)
                self.gh.cfg["blob_sha"] = "f" * 40
            return value
        with patch.object(self.gh, "record", side_effect=change_source):
            result = await self.checkpoint(controller, assignment, "needs_decision")
        self.assertEqual(result["reason"], "policy_changed")
        self.assertEqual(changes, [True])
        self.assertIn(assignment["step_id"], controller.runner.consumed)
        self.assertEqual(self.lock.read_bytes(), b"")
        self.assertEqual(self.gh.note["wait_reason"], "product_decision")
        self.assertFalse(self.ws.dirty)
        self.assertFalse(any(item[0] in {"push", "pr", "merge", "close"} for item in self.gh.writes))

    async def test_retirement_release_failure_preserves_ticket_and_unconsumed_step(self):
        controller = self.controller()
        assignment = await self.checkpoint(controller, await controller.begin(URL))
        self.ws.dirty = True
        with patch("hydra_sdlc.native.confirm_native_assignment", side_effect=RuntimeError("release unavailable")):
            with self.assertRaisesRegex(RuntimeError, "release unavailable"):
                await self.checkpoint(controller, assignment, "needs_decision")
        self.assertIn(assignment["step_id"].encode(), self.lock.read_bytes())
        self.assertNotIn(assignment["step_id"], controller.runner.consumed)
        preserved = copy.deepcopy(self.gh.note)
        prepared = len(self.ws.prepared_recovery)
        await self.checkpoint(controller, assignment, "stopped")
        self.assertEqual(self.lock.read_bytes(), b"")
        self.assertEqual(self.gh.note, preserved)
        self.assertEqual(len(self.ws.prepared_recovery), prepared)

    async def test_retirement_completion_values_cannot_replace_assignment_identity(self):
        controller = self.controller()
        assignment = await controller.begin(URL)
        before, ticket = copy.deepcopy(self.gh.note), self.lock.read_bytes()
        writes = len(self.gh.writes)
        for field in ("head", "attempt_id", "contract_revision", "spec_revision", "native_step"):
            with self.subTest(field=field), self.assertRaises(OperationDenied):
                controller.runner._retire_assignment(REPO, 4, before, **{field: "foreign"})
        self.assertEqual(self.gh.note, before)
        self.assertEqual(self.lock.read_bytes(), ticket)
        self.assertEqual(len(self.gh.writes), writes)
        await self.checkpoint(controller, assignment, "stopped")

    async def test_pause_before_native_retirement_preserves_identity_and_ticket(self):
        controller = self.controller()
        assignment = await self.checkpoint(controller, await controller.begin(URL))
        self.ws.dirty = True
        record = controller.runner._record
        def pause_after_recovery(repo, number, previous, **values):
            value = record(repo, number, previous, **values)
            if values.get("checkpoint") == "interrupted_committed" and value.get("native_step"):
                self.control.set_mode("pause", REPO)
            return value
        with patch.object(controller.runner, "_record", side_effect=pause_after_recovery):
            result = await self.checkpoint(controller, assignment, "needs_decision")
        self.assertEqual(result["reason"], "project_paused")
        self.assertEqual(self.gh.note["native_step"], assignment["step_id"])
        self.assertIn(assignment["step_id"].encode(), self.lock.read_bytes())
        self.assertNotIn(assignment["step_id"], controller.runner.consumed)
        self.assertFalse(self.ws.dirty)
        self.assertEqual((await self.checkpoint(controller, assignment, "stopped"))["reason"], "product_decision")
        self.assertEqual(self.lock.read_bytes(), b"")

    async def assert_native_retirement_unknown(self, failure):
        controller = self.controller()
        assignment = await self.checkpoint(controller, await controller.begin(URL))
        self.ws.dirty = True
        original = self.gh.record if failure == "ack" else self.gh.progress
        def uncertain(*args):
            value = original(*args)
            current = self.gh.note
            if current.get("checkpoint") == "interrupted_committed" and not current.get("native_step"):
                if failure == "ack":
                    raise RuntimeError("Retirement acknowledgement lost")
                return {**value, "head": "f" * 40}
            return value
        with patch.object(self.gh, "record" if failure == "ack" else "progress", side_effect=uncertain), \
                patch("hydra_sdlc.native.confirm_native_assignment") as retired:
            with self.assertRaises(RuntimeError):
                await self.checkpoint(controller, assignment, "needs_decision")
            retired.assert_not_called()
        self.assertIn(assignment["step_id"].encode(), self.lock.read_bytes())
        self.assertNotIn(assignment["step_id"], controller.runner.consumed)
        self.assertFalse(self.ws.dirty)
        self.assertEqual(self.gh.note["head"], self.ws.head)
        preserved = copy.deepcopy(self.gh.note)
        prepared = len(self.ws.prepared_recovery)
        self.control.set_mode("pause", REPO)
        await self.checkpoint(controller, assignment, "stopped")
        self.assertEqual(self.lock.read_bytes(), b"")
        self.assertEqual(self.gh.note, preserved)
        self.assertEqual(len(self.ws.prepared_recovery), prepared)
        self.assertIsNone(self.gh.branch)

    async def test_native_retirement_lost_ack_retains_exact_stopped_recovery(self):
        await self.assert_native_retirement_unknown("ack")

    async def test_native_retirement_stale_readback_retains_exact_stopped_recovery(self):
        await self.assert_native_retirement_unknown("readback")

    async def test_completed_receipt_never_overwrites_pending_remote_effect(self):
        runner = self.runner()
        execute = runner.execute
        async def pending(assignment, **kwargs):
            result = await execute(assignment, **kwargs)
            if assignment["mode"] == "workspace_write":
                self.gh.note.update(phase="publishing", pending_action="publish")
                self.control.set_mode("pause")
            return result
        runner.execute = pending
        result = await runner.step(REPO, 4)
        self.assertEqual(result["reason"], "host_paused")
        self.assertEqual(self.gh.note["pending_action"], "publish")
        self.assertEqual(self.gh.note["phase"], "publishing")
        self.assertTrue(self.ws.dirty)
        self.assertEqual(self.gh.cleanup_records, [])
        self.assertIsNone(runner._ended_execution.get())

    async def test_unknown_sdk_cleanup_retains_uncertainty_without_checkpoint(self):
        runner = self.runner()
        original = runner.execute
        async def unknown(assignment, **kwargs):
            if assignment["mode"] == "read_only":
                return await original(assignment, **kwargs)
            self.ws.dirty = True
            self.control.set_mode("pause")
            return {"status": "transport_unknown", "detail": {"cleanup": "unknown"}}
        runner.execute = unknown
        result = await runner.step(REPO, 4)
        self.assertEqual(result["reason"], "host_paused")
        self.assertEqual(runner.host_hold_reason, "host_execution_unconfirmed")
        self.assertTrue(self.ws.dirty)
        self.assertEqual(self.gh.cleanup_records, [])
        self.assertEqual(self.gh.note["pending_action"], "implementation")

    async def test_verification_stop_callback_is_scoped_and_prevents_publication(self):
        runner = self.runner()
        self.assertEqual((await runner.step(REPO, 4))["action"], "continue")
        def stopped(path, commands, *, stop_requested, before_command=None):
            self.control.set_mode("pause", REPO)
            self.assertTrue(stop_requested())
            self.assertFalse(runner._stopping(OTHER))
            self.ws.dirty = True
            raise WorkspaceWait("verification_stopped")
        self.ws.verify = stopped
        result = await runner.step(REPO, 4)
        self.assertEqual(result["reason"], "stop_requested")
        self.assertFalse(self.ws.dirty)
        self.assertTrue(self.gh.cleanup_records)
        self.assertFalse(any(write[0] in {"push", "pr", "merge", "close"} for write in self.gh.writes))

    async def test_cleanup_exception_never_grants_publish_or_other_repository(self):
        runner = self.runner()
        record = {"attempt_id": "11111111-1111-4111-8111-111111111111"}
        self.control.set_mode("pause")
        with runner._confirmed_cleanup(REPO, 4, record):
            for repository, method in [(REPO, "publish"), (OTHER, "checkpoint")]:
                with self.subTest(repository=repository, method=method), self.assertRaises(OperationDenied):
                    runner._workspace_effect(repository, method, self.ws.path, "hydra/issue-4", None)
            with self.assertRaises(OperationDenied):
                runner._record(REPO, 5, record)
            with self.assertRaises(OperationDenied):
                runner._record(REPO, 4, {"attempt_id": "22222222-2222-4222-8222-222222222222"})

    async def test_scope_is_restored_and_other_project_can_enter(self):
        self.control.set_mode("pause", REPO)
        with operation_scope(self.control, OTHER):
            with operation_guard():
                pass
            with operation_scope(self.control, REPO):
                with self.assertRaises(OperationDenied):
                    with operation_guard():
                        self.fail("Paused repository was admitted")
            with operation_guard():
                pass
        with operation_guard():
            pass

    async def test_read_only_status_still_observes_paused_work(self):
        controller = self.controller()
        assignment = await controller.begin(URL)
        before = self.lock.read_bytes()
        self.control.set_mode("pause")
        status = controller.status()
        self.assertTrue(any(item.get("progress", {}).get("native_step") == assignment["step_id"]
                            for item in status if isinstance(item.get("progress"), dict)))
        self.assertEqual(self.lock.read_bytes(), before)


class CheckpointPublicationTests(unittest.TestCase):
    def test_cleanup_progress_write_does_not_change_active_labels(self):
        record = {"phase": "checkpoint", "checkpoint": "interrupted_committed", "head": BASE,
                  "wait_reason": "stop_requested"}
        fake = github_fixtures.GitHubTests().progress_fake([])
        fake.replies[("POST", f"/repos/{REPO}/issues/4/comments")] = {"id": 77}
        client = Client(transport=fake)
        with patch.object(client, "_active", side_effect=AssertionError("Cleanup changed labels")):
            client.record_checkpoint(REPO, 4, record)
        writes = [(method, path) for method, path, _ in fake.calls if method != "GET"]
        self.assertEqual(writes, [("POST", f"/repos/{REPO}/issues/4/comments")])
        payload = next(payload for method, _, payload in fake.calls if method == "POST")
        self.assertIn('"checkpoint":"interrupted_committed"', payload["body"])

    def test_coordinator_observation_never_creates_or_repairs_ownership(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary).resolve() / "missing" / "host.lock"
            self.assertEqual(observe_coordinator(path)["state"], "absent")
            self.assertFalse(path.parent.exists())
            path.parent.mkdir()
            path.write_text("unknown ownership")
            path.chmod(0o600)
            before = path.read_bytes()
            self.assertEqual(observe_coordinator(path)["state"], "unknown")
            self.assertEqual(path.read_bytes(), before)
