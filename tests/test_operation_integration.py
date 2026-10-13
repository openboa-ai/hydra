"""Shared control gates hold across live controllers and owned cleanup paths."""

import asyncio
import copy
import json
import tempfile
import threading
import unittest
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

    async def test_spec_checkpoint_and_decision_hold_share_one_pause_barrier(self):
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

    async def test_native_question_survives_pause_during_and_after_ticket_retirement(self):
        for boundary in ("clean_record", "after_retirement"):
            with self.subTest(boundary=boundary):
                self.control.set_mode("resume")
                self.gh = CheckpointGitHub()
                self.ws = OwnedWorkspace(self.root, self.gh)
                controller = self.controller()
                assignment = await controller.begin(URL)
                assignment = await self.checkpoint(controller, assignment)
                self.ws.dirty = True
                record, effect = controller.runner._record, controller.runner._effect
                paused = False
                def pause_once():
                    nonlocal paused
                    if not paused:
                        paused = True
                        self.control.set_mode("pause")
                def written(repo, number, previous, **values):
                    result = record(repo, number, previous, **values)
                    if (boundary == "clean_record" and not previous.get("native_step")
                            and previous.get("wait_reason") == "product_decision"):
                        pause_once()
                    return result
                def retired(repo, callback, *args, **kwargs):
                    result = effect(repo, callback, *args, **kwargs)
                    if boundary == "after_retirement" and callback.__name__ == "confirm_native_assignment":
                        pause_once()
                    return result
                controller.runner._record, controller.runner._effect = written, retired
                result = await self.checkpoint(controller, assignment, "needs_decision")
                self.assertEqual(result["reason"], "host_paused")
                self.assertEqual(self.gh.note["wait_reason"], "product_decision")
                self.assertEqual(self.gh.note["next_action"], "operator_decision")
                if self.lock.read_bytes():
                    await self.checkpoint(controller, assignment, "stopped")
                self.assertFalse(self.ws.dirty)
                self.assertIsNone(self.gh.branch)
                self.control.set_mode("resume")
                self.assertEqual((await self.controller().begin(URL))["reason"], "product_decision")
                self.assertEqual(self.lock.read_bytes(), b"")

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
        def stopped(path, commands, *, stop_requested):
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
