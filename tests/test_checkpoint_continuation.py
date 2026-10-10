"""Durable acceptance and actual write completion survive stopped attempts."""

import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc import execution_boundary as boundary
from hydra_sdlc.runner import Runner
from test_execution_boundary import WORKER
from test_project import BASE
from test_runner import GitHub, complete_capabilities
from test_spec_reacceptance import SnapshotWorkspace


REPO = "example/product"
SPEC = "docs/engineering/task/spec.md"


class CheckpointContinuationTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.control = Path(temporary.name)
        self.path = self.control / "candidate"
        self.path.mkdir()
        self.github = GitHub()
        self.calls, self.events, self.records = [], [], []
        self.workspace = SnapshotWorkspace(self.path, self.github, self.events)
        self.github.on_record = lambda record: self.records.append(copy.deepcopy(record))
        self.stop = False
        self.edits = 0
        self.effects = {}
        loader = patch("hydra_sdlc.runner.load_project", side_effect=lambda gh, repo: copy.deepcopy(gh.cfg))
        loader.start()
        self.addCleanup(loader.stop)

    async def capabilities(self, cwd):
        return complete_capabilities()

    async def execute(self, assignment, **kwargs):
        phase = self.github.note["pending_action"]
        self.calls.append(phase)
        if assignment["mode"] == "workspace_write":
            # The continuation must be durable before the worker observes it.
            self.assertIn(self.github.note["resume_phase"], {"implementation", "correction"})
            self.edits += 1
            source = self.path / "src/main.py"
            source.parent.mkdir(exist_ok=True)
            source.write_text(f"revision = {self.edits}\n")
        effect = self.effects.pop(phase, None)
        if effect:
            return effect()
        return {"status": "completed", "detail": {"result": {"outcome": "candidate_ready"}}}

    def runner(self):
        return Runner(self.github, self.workspace, host_alias="host-a", execute=self.execute,
                      capabilities=self.capabilities, stop_requested=lambda: self.stop)

    async def step(self, runner=None):
        return await (runner or self.runner()).step(REPO, 4)

    def stopped(self):
        return {"status": "interrupted", "detail": {"cleanup": "confirmed"}}

    async def implemented(self, *, publish=False):
        self.assertEqual((await self.step())["action"], "continue")
        self.assertEqual(self.calls, ["spec_review", "implementation"])
        if publish:
            self.github.remote_pending = True
            self.assertEqual((await self.step())["reason"], "remote_delivery_gates")
            self.assertIsNotNone(self.github.pr)
        self.calls.clear()

    def config(self):
        return {**self.github.cfg, "intake_digest": self.github.note["intake_digest"]}

    def no_delivery(self):
        self.assertFalse(any(write[0] in {"pr", "merge", "close"} for write in self.github.writes))

    async def failed_acceptance(self, *, persisted):
        original = self.github.record
        failed = False
        def record(repo, number, value):
            nonlocal failed
            if value.get("spec_revision") and not failed:
                failed = True
                if persisted:
                    original(repo, number, value)
                raise RuntimeError("Acceptance response unavailable")
            original(repo, number, value)
        self.github.record = record
        runner = self.runner()
        with self.assertRaisesRegex(RuntimeError, "Acceptance response"):
            await self.step(runner)
        self.assertEqual(runner.accepted_specs, {})
        self.assertEqual(self.calls, ["spec_review"])
        self.assertEqual(self.github.note.get("spec_revision"), BASE if persisted else None)
        self.assertEqual(self.workspace.verification_calls, 0)
        self.no_delivery()
        self.assertEqual((await self.step(runner))["action"], "continue")
        self.assertEqual(self.calls, ["spec_review", "spec_review", "implementation"])
        self.assertEqual(self.github.note["spec_revision"], BASE)

    async def test_acceptance_write_failure_cannot_seed_the_cache(self):
        await self.failed_acceptance(persisted=False)

    async def test_acceptance_lost_response_retains_anchor_but_not_unconfirmed_cache(self):
        await self.failed_acceptance(persisted=True)

    async def test_stale_cache_without_durable_anchor_cannot_skip_review(self):
        runner = self.runner()
        key = REPO, 4, hashlib.sha256((self.path / SPEC).read_bytes()).hexdigest()
        runner.accepted_specs[key] = True
        self.assertEqual((await self.step(runner))["action"], "continue")
        self.assertEqual(self.calls, ["spec_review", "implementation"])
        self.assertEqual(self.github.note["spec_revision"], BASE)

    async def test_interrupted_implementation_finishes_before_verification_after_restart(self):
        self.effects["implementation"] = self.stopped
        self.assertEqual((await self.step())["reason"], "stop_requested")
        stopped_head = self.workspace.head
        self.assertEqual(self.github.note["resume_phase"], "implementation")
        self.assertEqual(self.github.note["checkpoint"], "interrupted_committed")
        self.assertEqual(self.github.branch, stopped_head)
        self.assertEqual(self.workspace.verification_calls, 0)
        self.no_delivery()
        self.calls.clear()
        self.assertEqual((await self.step())["action"], "continue")
        self.assertEqual(self.calls, ["spec_review", "implementation"])
        self.assertNotEqual(self.workspace.head, stopped_head)
        self.assertEqual(self.workspace.verification_calls, 0)
        self.assertIsNone(self.github.note["resume_phase"])
        self.no_delivery()

    async def test_uncertain_checkpoint_publish_reconciles_before_completion(self):
        self.effects["implementation"] = self.stopped
        self.workspace.publish_failures = 1
        self.assertEqual((await self.step())["reason"], "stop_requested")
        head = self.workspace.head
        self.assertEqual(self.github.note["pending_action"], "publish")
        self.calls.clear()
        self.assertEqual((await self.step())["action"], "continue")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.workspace.head, head)
        self.assertEqual(self.github.branch, head)
        self.assertEqual(self.github.note["resume_phase"], "implementation")
        self.assertEqual(self.workspace.verification_calls, 0)
        self.assertEqual((await self.step())["action"], "continue")
        self.assertEqual(self.calls, ["spec_review", "implementation"])
        self.assertEqual(self.workspace.verification_calls, 0)
        self.no_delivery()

    async def test_interrupted_correction_resumes_same_reason_and_budget(self):
        await self.implemented()
        self.effects["correction"] = self.stopped
        result = await self.runner()._correct(REPO, 4, self.config(), self.github.note,
                                               self.path, "review_findings")
        self.assertEqual(result["reason"], "stop_requested")
        self.assertEqual(self.github.note["resume_phase"], "correction")
        self.assertEqual(self.github.note["correction_reason"], "review_findings")
        self.assertEqual(self.github.note["correction_attempt"], 1)
        stopped_head = self.workspace.head
        self.calls.clear()
        self.assertEqual((await self.step())["action"], "continue")
        self.assertEqual(self.calls, ["spec_review", "correction"])
        self.assertEqual(self.github.note["correction_attempt"], 1)
        self.assertIsNone(self.github.note["resume_phase"])
        self.assertNotEqual(self.workspace.head, stopped_head)
        self.assertEqual(self.workspace.verification_calls, 0)
        self.no_delivery()

    async def test_interrupted_integration_before_implementation_keeps_implementation_debt(self):
        integrated = False
        self.workspace.contains_base = lambda *args: integrated
        def interrupted():
            nonlocal integrated
            integrated = True
            return self.stopped()
        self.effects["correction"] = interrupted
        self.assertEqual((await self.step())["reason"], "stop_requested")
        self.assertEqual(self.github.note["resume_phase"], "implementation")
        self.calls.clear()
        self.assertEqual((await self.step())["action"], "continue")
        self.assertEqual(self.calls, ["spec_review", "implementation"])
        self.assertEqual(self.workspace.verification_calls, 0)
        self.assertIsNone(self.github.note["resume_phase"])
        self.no_delivery()

    async def test_interrupted_integration_after_existing_pr_does_not_loop(self):
        await self.implemented(publish=True)
        verified = self.workspace.verification_calls
        self.effects["correction"] = self.stopped
        self.assertEqual((await self.runner()._correct(REPO, 4, self.config(), self.github.note,
                         self.path, "integration_changed"))["reason"], "stop_requested")
        self.assertEqual(self.github.note["resume_phase"], "correction")
        self.calls.clear()
        self.assertEqual((await self.step())["action"], "continue")
        self.assertEqual(self.calls, ["spec_review", "correction"])
        self.assertIsNone(self.github.note["resume_phase"])
        self.assertEqual(self.github.note["correction_attempt"], 1)
        self.assertEqual(self.workspace.verification_calls, verified)
        self.calls.clear()
        self.assertEqual((await self.step())["reason"], "remote_delivery_gates")
        self.assertEqual(self.calls, ["spec_review", "change_review"])
        self.assertEqual(self.workspace.verification_calls, verified + 1)
        self.assertFalse(any(write[0] in {"merge", "close"} for write in self.github.writes))

    async def test_owed_correction_finishes_before_later_base_integration(self):
        await self.implemented(publish=True)
        self.effects["correction"] = self.stopped
        self.assertEqual((await self.runner()._correct(REPO, 4, self.config(), self.github.note,
                         self.path, "review_findings"))["reason"], "stop_requested")
        verified = self.workspace.verification_calls
        integrated = False
        self.workspace.contains_base = lambda *args: integrated
        dispatched = []
        def correction():
            dispatched.append((self.github.note["correction_reason"],
                               self.github.note["correction_attempt"]))
            return {"status": "completed", "detail": {"result": {"outcome": "candidate_ready"}}}
        self.effects["correction"] = correction
        self.calls.clear()
        self.assertEqual((await self.step())["action"], "continue")
        self.assertEqual(dispatched, [("review_findings", 1)])
        self.assertEqual(self.calls, ["spec_review", "correction"])
        self.assertFalse(integrated)
        self.assertEqual(self.workspace.verification_calls, verified)
        self.assertIsNone(self.github.note["resume_phase"])
        def integration():
            nonlocal integrated
            integrated = True
            return correction()
        self.effects["correction"] = integration
        self.calls.clear()
        self.assertEqual((await self.step())["action"], "continue")
        self.assertEqual(dispatched, [("review_findings", 1), ("integration_changed", 1)])
        self.assertEqual(self.calls, ["correction"])
        self.assertEqual(self.workspace.verification_calls, verified)
        self.assertEqual(self.github.note["spec_revision"], BASE)
        self.calls.clear()
        self.assertEqual((await self.step())["reason"], "remote_delivery_gates")
        self.assertEqual(self.calls, ["spec_review", "change_review"])
        self.assertEqual(self.workspace.verification_calls, verified + 1)
        self.assertFalse(any(write[0] in {"merge", "close"} for write in self.github.writes))

    async def test_real_worker_stop_preserves_partial_bytes_until_fresh_completion(self):
        worker = self.control / "worker.py"
        marker = self.control / "worker.jsonl"
        worker.write_text(WORKER.replace("    identity(turn_id='turn-1')", """    identity(turn_id='turn-1')
    partial = Path(assignment['cwd']) / 'src/partial.py'
    partial.parent.mkdir(exist_ok=True)
    partial.write_text('partial = True\\n')
    event('partial-ready', {'method': 'item/completed', 'params': {
        'threadId': 'thread-1', 'turnId': 'turn-1',
        'item': {'id': 'partial-ready', 'type': 'commandExecution'}}})"""))
        observed = asyncio.Event()
        normal = self.execute
        async def execute(assignment, **kwargs):
            if self.github.note["pending_action"] != "implementation":
                return await normal(assignment, **kwargs)
            self.assertEqual(self.github.note["resume_phase"], "implementation")
            self.calls.append("implementation")
            def event(identifier, payload):
                if identifier == "partial-ready":
                    observed.set()
            return await boundary.execute_worker(assignment, kwargs["on_identity"], event,
                kwargs["stop_requested"], None, worker_source=str(Path(boundary.__file__).resolve()),
                timeout=5, grace=.2, poll=.01)
        runner = self.runner()
        runner.execute = execute
        command = [sys.executable, "-I", str(worker), str(Path(boundary.__file__).resolve()),
                   "silent", str(marker)]
        with patch.object(boundary, "_worker_command", return_value=command):
            task = asyncio.create_task(self.step(runner))
            try:
                await asyncio.wait_for(observed.wait(), 5)
                self.stop = True
                result = await task
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(result["reason"], "stop_requested")
        self.assertIsNone(runner.host_hold_reason)
        self.assertEqual(self.github.note["checkpoint"], "interrupted_committed")
        self.assertEqual(self.github.note["resume_phase"], "implementation")
        head = self.workspace.head
        self.assertEqual(self.workspace.snapshots[head]["src/partial.py"], b"partial = True\n")
        for value in map(json.loads, marker.read_text().splitlines()):
            if "pid" in value:
                with self.assertRaises(ProcessLookupError):
                    os.kill(value["pid"], 0)
        self.assertEqual(self.workspace.verification_calls, 0)
        self.no_delivery()
        self.stop = False
        self.calls.clear()
        self.assertEqual((await self.step())["action"], "continue")
        self.assertEqual(self.calls, ["spec_review", "implementation"])
        self.assertNotEqual(self.workspace.head, head)
        self.assertEqual((self.path / "src/partial.py").read_bytes(), b"partial = True\n")
        self.assertEqual(self.workspace.verification_calls, 0)

    async def cross_repository(self, failure):
        first, second = self.github, GitHub()
        first.work["body"] = first.work["body"].replace("```hydra\n", "```hydra\npriority = 1\n")
        second.cfg.update(repository="example/another", repository_id=456)
        other_path = self.control / "another"
        other_path.mkdir()
        other = SnapshotWorkspace(other_path, second, [])
        projects = {REPO: (first, self.workspace), "example/another": (second, other)}
        paths = {str(workspace.path): (repo, github, workspace)
                 for repo, (github, workspace) in projects.items()}
        class Router:
            def __getattr__(self, name):
                return lambda repo, *args, **kwargs: getattr(projects[repo][0], name)(repo, *args, **kwargs)
        class Workspaces:
            def prepare(self, repo, *args, **kwargs):
                return projects[repo][1].prepare(repo, *args, **kwargs)
            def __getattr__(self, name):
                return lambda path, *args, **kwargs: getattr(paths[str(path)][2], name)(path, *args, **kwargs)
        turns = []
        async def execute(assignment, **kwargs):
            repo, github, workspace = paths[assignment["cwd"]]
            phase = github.note["pending_action"]
            turns.append((repo, phase))
            if repo == REPO and phase == "implementation":
                if isinstance(failure, BaseException):
                    raise failure
                return {"status": "transport_unknown", "detail": failure}
            if assignment["mode"] == "workspace_write":
                target = workspace.path / "src/main.py"
                target.parent.mkdir(exist_ok=True)
                target.write_text("completed = True\n")
            return {"status": "completed", "detail": {"result": {"outcome": "candidate_ready"}}}
        with patch("hydra_sdlc.runner.load_project", side_effect=lambda gh, repo: copy.deepcopy(projects[repo][0].cfg)):
            runner = Runner(Router(), Workspaces(), host_alias="host-a", execute=execute,
                            capabilities=self.capabilities)
            result = await runner.cycle(list(projects))
            self.assertEqual(result[0]["reason"], "execution_unknown")
            self.assertEqual(first.note["pending_action"], "implementation")
            self.assertEqual(first.note["resume_phase"], "implementation")
            held = isinstance(failure, BaseException) or failure.get("cleanup") == "unknown"
            if held:
                self.assertEqual(runner.host_hold_reason, "host_execution_unconfirmed")
                self.assertEqual(len(result), 1)
                self.assertIsNone(second.note)
                self.assertFalse(any(repo == "example/another" for repo, _ in turns))
            else:
                self.assertIsNone(runner.host_hold_reason)
                self.assertEqual(len(result), 2)
                self.assertEqual(result[1]["action"], "continue")
                self.assertIn(("example/another", "implementation"), turns)
                before = list(turns)
                self.assertEqual((await runner.step(REPO, 4))["reason"], "confirm_previous_stopped")
                self.assertEqual(turns, before)
            self.assertEqual(self.workspace.verification_calls, 0)

    async def test_confirmed_clean_unknown_result_releases_only_the_host(self):
        await self.cross_repository({"cleanup": "confirmed"})

    async def test_production_clean_unknown_omitted_cleanup_releases_only_the_host(self):
        await self.cross_repository({"reason": "worker_exit_without_result"})

    async def test_unknown_cleanup_retains_host_hold(self):
        await self.cross_repository({"cleanup": "unknown"})

    async def test_unexpected_executor_exception_retains_host_hold(self):
        await self.cross_repository(RuntimeError("Unexpected executor failure"))

    async def test_unexpected_executor_cancellation_retains_host_hold(self):
        await self.cross_repository(asyncio.CancelledError())
