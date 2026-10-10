import copy
import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hydra_sdlc.coordinator import HostBusy, coordinator_lock
from hydra_sdlc.native import NativeController
from hydra_sdlc.runner import Runner
from test_runner import GitHub, Workspace
from test_project import BASE


class NativeTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.gh = GitHub()
        self.ws = Workspace(self.tmp.name, self.gh)
        self.lock = Path(self.tmp.name) / "host.lock"
        self.url = "https://github.com/example/product/issues/4"
        for name in ("hydra_sdlc.runner.load_project", "hydra_sdlc.native.load_project"):
            p = patch(name, side_effect=lambda gh, repo, **kw: copy.deepcopy(gh.cfg))
            p.start()
            self.addCleanup(p.stop)
        self.controller = self.new_controller()

    def new_controller(self):
        return NativeController(self.gh, self.ws, repos=["example/product", "example/other"],
            host_alias="test", lock_path=self.lock)

    async def result(self, assignment, outcome="candidate_ready", **changes):
        values = dict(url=self.url, attempt_id=assignment["attempt_id"], step_id=assignment["step_id"],
                      head=assignment["head"], contract_revision=assignment["contract_revision"], outcome=outcome)
        values.update(changes)
        return await self.controller.checkpoint(**values)

    async def change_review(self):
        implementation = await self.result(await self.controller.begin(self.url))
        self.ws.dirty = True
        await self.result(implementation)
        record = self.gh.progress("example/product", 4)
        return await self.controller.advance(self.url, record["attempt_id"], record["head"], record["contract_revision"])

    async def test_uncertain_fsync_returns_ticket_identity_without_dispatch(self):
        with patch("hydra_sdlc.coordinator.os.fsync", side_effect=OSError("uncertain sync")):
            recovery = await self.controller.begin(self.url)
        self.assertEqual(recovery["action"], "waiting")
        self.assertEqual(recovery["reason"], "assignment_ticket_unconfirmed")
        self.assertIn(recovery["step_id"].encode(), self.lock.read_bytes())
        with self.assertRaises(HostBusy):
            await self.new_controller().begin(self.url)
        stopped = await self.result(recovery, "stopped")
        self.assertEqual(stopped["reason"], "stop_requested")
        self.assertEqual(self.lock.read_bytes(), b"")

    async def test_positive_short_ticket_writes_complete_and_allow_scoped_stop(self):
        real_write = os.pwrite
        writes = []

        def short_write(fd, value, offset):
            writes.append(offset)
            return real_write(fd, value[:7], offset)

        with patch("hydra_sdlc.coordinator.os.pwrite", side_effect=short_write):
            assignment = await self.controller.begin(self.url)
        self.assertEqual(assignment["action"], "native_task")
        self.assertEqual(writes, list(range(0, len(self.lock.read_bytes()), 7)))
        with self.assertRaises(HostBusy):
            await self.new_controller().begin(self.url)
        await self.result(assignment, "stopped")
        self.assertEqual(self.lock.read_bytes(), b"")

    async def test_partial_ticket_write_failure_remains_closed_without_dispatch(self):
        real_write = os.pwrite
        for failure in ("zero", "io", "invalid"):
            with self.subTest(failure=failure):
                self.lock.write_bytes(b"")
                writes = []

                def failed_write(fd, value, offset):
                    writes.append(offset)
                    if not offset:
                        return real_write(fd, value[:7], offset)
                    if failure == "io":
                        raise OSError("synthetic disk failure")
                    return 0 if failure == "zero" else len(value) + 1

                with patch("hydra_sdlc.coordinator.os.pwrite", side_effect=failed_write):
                    result = await self.controller.begin(self.url)
                self.assertEqual(result["action"], "waiting")
                self.assertEqual(result["reason"], "assignment_ticket_unknown")
                self.assertEqual(self.lock.read_bytes(), b"hydra-n")
                self.assertIsNone(self.gh.progress("example/product", 4))
                with self.assertRaises(HostBusy):
                    await self.new_controller().begin(self.url)

    async def test_review_accepts_exactly_the_run_in_its_prompt(self):
        review = await self.change_review()
        self.assertEqual(self.ws.verification_calls, 1)
        await self.result(review)
        self.assertEqual(self.ws.verification_calls, 1)
        self.assertEqual(self.controller.runner.pending_verifications, {})

    async def test_restart_requires_a_new_review_of_fresh_verification(self):
        review = await self.change_review()
        self.assertEqual(self.ws.verification_calls, 1)
        self.controller = self.new_controller()
        fresh = await self.result(review)
        self.assertEqual(self.ws.verification_calls, 2)
        self.assertEqual(fresh["phase"], "change_review")
        self.assertNotEqual(fresh["step_id"], review["step_id"])
        await self.result(fresh)
        self.assertEqual(self.ws.verification_calls, 2)

    async def test_write_results_do_not_retain_private_summaries(self):
        implementation = await self.result(await self.controller.begin(self.url))
        self.ws.dirty = True
        await self.result(implementation, summary="private implementation summary")
        self.assertEqual(self.controller.runner.summaries, {})

    async def test_initial_design_returns_identity_for_direct_continuation(self):
        from test_spec_reacceptance import SnapshotWorkspace
        self.ws = SnapshotWorkspace(Path(self.tmp.name) / "owned", self.gh, [])
        spec = self.ws.path / "docs/engineering/task/spec.md"
        spec.unlink()
        self.ws.snapshots[BASE] = self.ws.contents()
        self.controller = self.new_controller()
        design = await self.controller.begin(self.url)
        self.assertEqual(design["phase"], "design")
        spec.write_text("Requirement-linked specification with lifecycle acceptance")
        progress = await self.result(design)
        self.assertEqual(progress["action"], "continue")
        self.assertNotEqual(progress["head"], design["head"])
        review = await self.controller.advance(self.url, progress["attempt_id"], progress["head"], progress["contract_revision"])
        self.assertEqual(review["phase"], "spec_review")

    async def test_implementation_correction_returns_current_continuation_identity(self):
        implementation = await self.result(await self.controller.begin(self.url))
        self.ws.dirty = True
        correction = await self.result(implementation, "failed")
        self.assertEqual(correction["phase"], "correction")
        self.ws.dirty = True
        progress = await self.result(correction)
        self.assertNotEqual(progress["head"], correction["head"])
        review = await self.controller.advance(self.url, progress["attempt_id"], progress["head"], progress["contract_revision"])
        self.assertEqual(review["phase"], "change_review")

    async def test_native_development_review_merge_and_observation(self):
        review = await self.controller.begin(self.url)
        self.assertEqual(review["phase"], "spec_review")
        implementation = await self.result(review)
        self.assertEqual(implementation["phase"], "implementation")
        self.ws.dirty = True
        progress = await self.result(implementation)
        self.assertEqual(progress["action"], "continue")
        self.assertNotEqual(progress["head"], implementation["head"])
        review = await self.controller.advance(self.url, progress["attempt_id"], progress["head"], progress["contract_revision"])
        self.assertEqual(review["phase"], "change_review")
        self.assertIn("verification", review["prompt"])
        await self.result(review)
        record = self.gh.progress("example/product", 4)
        result = await self.controller.advance(self.url, record["attempt_id"], record["head"], record["contract_revision"])
        self.assertEqual(result["action"], "completed")
        self.assertEqual(self.gh.work["state"], "closed")
        self.assertTrue(self.gh.pr["merged"])
        self.assertNotIn("native_step", self.gh.note)

    async def test_persistent_ticket_blocks_other_native_and_cli_even_closed_or_paused(self):
        assignment = await self.controller.begin(self.url)
        for mutate in (lambda: None, lambda: self.gh.work.update(state="closed"),
                       lambda: self.gh.work["labels"].append({"name": "hydra:paused"})):
            mutate()
            with self.assertRaises(HostBusy):
                await self.new_controller().begin("https://github.com/example/other/issues/4")
            with self.assertRaises(HostBusy):
                with coordinator_lock(self.lock):
                    self.fail("CLI entered during native assignment")
        stopped = await self.result(assignment, "stopped")
        self.assertEqual(stopped["reason"], "stop_requested")
        with coordinator_lock(self.lock):
            pass

    async def test_late_result_cannot_consume_next_assignment(self):
        first = await self.controller.begin(self.url)
        second = await self.result(first)
        self.assertNotEqual(first["step_id"], second["step_id"])
        with self.assertRaises(HostBusy):
            await self.result(first)
        self.assertEqual(self.gh.note["native_step"], second["step_id"])

    async def test_restart_does_not_redispatch_unknown_native_work(self):
        first = await self.controller.begin(self.url)
        self.controller = self.new_controller()
        with self.assertRaises(HostBusy):
            await self.controller.begin(self.url)
        self.ws.dirty = True
        stopped = await self.result(first, "stopped")
        self.assertFalse(self.ws.dirty)
        self.assertEqual(stopped["head"], self.ws.head)
        self.assertIsNone(self.gh.note.get("native_step"))

    async def test_policy_intake_and_review_mutation_refuse_candidate(self):
        assignment = await self.controller.begin(self.url)
        self.gh.work["body"] += "Changed acceptance"
        with self.assertRaises(ValueError):
            await self.result(assignment)
        self.gh.work["body"] = self.gh.work["body"].removesuffix("Changed acceptance")
        self.ws.dirty = True
        result = await self.result(assignment)
        self.assertEqual(result["reason"], "head_changed_during_native_task")
        with self.assertRaises(HostBusy):
            with coordinator_lock(self.lock):
                pass

    async def test_candidate_readiness_is_not_merge_evidence(self):
        assignment = await self.controller.begin(self.url)
        implementation = await self.result(assignment)
        self.assertIsNone(self.gh.pr)
        self.assertFalse(any(w[0] == "merge" for w in self.gh.writes))
        self.assertEqual(implementation["phase"], "implementation")

    async def test_sdk_runner_refuses_native_progress_without_spawning(self):
        await self.controller.begin(self.url)
        async def forbidden(*a, **kw):
            self.fail("SDK spawned")
        runner = Runner(self.gh, self.ws, host_alias="test", execute=forbidden, capabilities=forbidden)
        result = await runner.step("example/product", 4)
        self.assertEqual(result["reason"], "native_owned")

    async def test_wrong_head_and_unregistered_issue_refused(self):
        with self.assertRaises(ValueError):
            await self.controller.begin("https://github.com/foreign/product/issues/4")
        assignment = await self.controller.begin(self.url)
        with self.assertRaises(HostBusy):
            await self.result(assignment, head="f" * 40)

    async def test_missing_intent_retains_scoped_admission_without_inventing_work(self):
        def lose_intent(record):
            if record.get("native_step"):
                self.gh.note = None
                raise RuntimeError("intent was not saved")
        self.gh.on_record = lose_intent
        assignment = await self.controller.begin(self.url)
        self.assertEqual(assignment["reason"], "assignment_record_unknown")
        with self.assertRaises(HostBusy):
            await self.result(assignment, "stopped", url="https://github.com/example/other/issues/4")
        with self.assertRaises(HostBusy):
            with coordinator_lock(self.lock):
                pass
        before = len(self.ws.prepared_recovery)
        await self.result(assignment, "stopped")
        self.assertEqual(len(self.ws.prepared_recovery), before)
        self.assertIsNone(self.gh.note)
        with coordinator_lock(self.lock):
            pass

    async def test_unknown_assignment_response_recovers_only_matching_remote_intent(self):
        def lose_intent(record):
            if record.get("native_step"):
                self.gh.on_record = lambda record: None
                raise RuntimeError("intent response lost")
        self.gh.on_record = lose_intent
        assignment = await self.controller.begin(self.url)
        self.assertEqual(assignment["reason"], "assignment_record_unknown")
        self.controller = self.new_controller()
        await self.result(assignment, "stopped")
        self.assertNotIn("native_step", self.gh.note)

    async def test_repository_identity_is_case_insensitive_across_calls(self):
        assignment = await self.controller.begin("https://github.com/Example/Product/issues/4")
        result = await self.result(assignment)
        self.assertEqual(result["phase"], "implementation")

    async def test_checkpoint_failure_retains_dirty_edits_and_stop_identity(self):
        implementation = await self.result(await self.controller.begin(self.url))
        self.ws.dirty = True
        with patch.object(self.ws, "checkpoint", side_effect=OSError("disk unavailable")):
            with self.assertRaises(OSError):
                await self.result(implementation)
        self.assertTrue(self.ws.dirty)
        self.assertEqual(self.gh.note["native_step"], implementation["step_id"])
        with self.assertRaises(HostBusy):
            with coordinator_lock(self.lock):
                pass
        self.controller = self.new_controller()
        stopped = await self.result(implementation, "stopped")
        self.assertEqual(stopped["head"], self.ws.head)
        self.assertFalse(self.ws.dirty)

    async def test_callback_failure_leaves_committed_origin_for_restart(self):
        implementation = await self.result(await self.controller.begin(self.url))
        self.ws.dirty = True
        with patch.object(self.controller.runner, "_finish_implementation", side_effect=OSError("callback failed")):
            with self.assertRaises(OSError):
                await self.result(implementation)
        self.assertFalse(self.ws.dirty)
        self.assertEqual(self.gh.note["head"], self.ws.head)
        self.assertEqual(self.gh.note["resume_phase"], "implementation")
        self.assertEqual(self.gh.note["checkpoint"], "interrupted_committed")
        self.assertNotIn("native_step", self.gh.note)
        self.controller = self.new_controller()
        resumed = await self.controller.begin(self.url)
        self.assertEqual(resumed["phase"], "spec_review")
        resumed = await self.result(resumed)
        self.assertEqual(resumed["phase"], "implementation")

    async def test_lost_clean_progress_response_preserves_restartable_checkpoint(self):
        implementation = await self.result(await self.controller.begin(self.url))
        self.ws.dirty = True
        def lose_clean(record):
            if record.get("checkpoint") == "interrupted_committed" and not record.get("native_step"):
                self.gh.on_record = lambda record: None
                raise RuntimeError("retirement response lost")
        self.gh.on_record = lose_clean
        with self.assertRaises(RuntimeError):
            await self.result(implementation)
        self.assertFalse(self.ws.dirty)
        self.assertEqual(self.gh.note["head"], self.ws.head)
        self.controller = self.new_controller()
        await self.result(implementation, "stopped")
        resumed = await self.controller.begin(self.url)
        self.assertEqual(resumed["phase"], "spec_review")

    async def test_native_ticket_survives_reboot_until_explicit_checkpoint(self):
        assignment = await self.controller.begin(self.url)
        with patch("hydra_sdlc.coordinator._boot_identity", return_value="00000000-0000-0000-0000-000000000001"):
            with self.assertRaises(HostBusy):
                with coordinator_lock(self.lock):
                    pass
            await self.result(assignment, "stopped")

    async def test_lost_candidate_response_reconciles_matching_remote_result(self):
        assignment = await self.controller.begin(self.url)
        def lose_after_write(record):
            if record.get("native_outcome"):
                self.gh.on_record = lambda record: None
                raise RuntimeError("response lost")
        self.gh.on_record = lose_after_write
        with self.assertRaises(RuntimeError):
            await self.result(assignment)
        self.controller = self.new_controller()
        next_assignment = await self.result(assignment)
        self.assertEqual(next_assignment["phase"], "implementation")
        self.assertNotEqual(next_assignment["step_id"], assignment["step_id"])

    async def test_decision_checkpoints_partial_implementation_and_resumes_origin(self):
        first = await self.controller.begin(self.url)
        implementation = await self.result(first)
        self.ws.dirty = True
        result = await self.result(implementation, "needs_decision")
        self.assertEqual(result["reason"], "product_decision")
        self.assertFalse(self.ws.dirty)
        self.assertEqual(self.gh.note["resume_phase"], "implementation")
        old_attempt = self.gh.note["attempt_id"]
        self.gh.extra_comments.append({"user": {"login": "openboa"},
            "body": f"hydra: decision {old_attempt} resolved"})
        result = await self.controller.begin(self.url)
        self.assertEqual(result["phase"], "implementation")
        self.assertNotEqual(result["attempt_id"], old_attempt)

    async def test_stopped_checkpoint_retries_after_response_loss(self):
        assignment = await self.controller.begin(self.url)
        def lose_after_write(record):
            if record.get("native_outcome") == "stopped":
                self.gh.on_record = lambda record: None
                raise RuntimeError("response lost")
        self.gh.on_record = lose_after_write
        with self.assertRaises(RuntimeError):
            await self.result(assignment, "stopped")
        self.controller = self.new_controller()
        result = await self.result(assignment, "stopped")
        self.assertEqual(result["reason"], "stop_requested")
        with coordinator_lock(self.lock):
            pass

    async def test_changed_accepted_spec_consumes_old_write_before_new_review(self):
        first = await self.controller.begin(self.url)
        implementation = await self.result(first)
        spec = self.ws.path / "docs/engineering/task/spec.md"
        spec.write_text("Revised requirement-linked specification")
        self.ws.dirty = True
        self.ws.changed_paths = lambda path, base: ["docs/engineering/task/spec.md", "src/main.py"]
        result = await self.result(implementation)
        self.assertEqual(result["action"], "continue")
        self.assertNotIn("native_step", self.gh.note)
        self.assertEqual(self.gh.note["spec_revision"], BASE)
        self.assertEqual(self.gh.note["correction_attempt"], 1)
        result = await self.controller.begin(self.url)
        self.assertEqual(result["phase"], "spec_review")
        self.assertNotEqual(result["step_id"], implementation["step_id"])

    async def test_stopped_spec_mutation_counts_once_and_preserves_replan_budget(self):
        implementation = await self.result(await self.controller.begin(self.url))
        spec = self.ws.path / "docs/engineering/task/spec.md"
        spec.write_text(spec.read_text() + "\nChanged acceptance while stopping.")
        self.ws.dirty = True
        self.ws.changed_paths = lambda path, base: ["docs/engineering/task/spec.md", "src/main.py"]
        self.gh.note["correction_attempt"] = 2
        stopped = await self.result(implementation, "stopped")
        self.assertEqual(stopped["reason"], "replan_required")
        self.assertEqual(self.gh.note["correction_attempt"], 3)
        result = await self.new_controller().begin(self.url)
        self.assertEqual(result["reason"], "replan_required")
        self.assertEqual(self.gh.note["correction_attempt"], 3)

    async def test_changed_intake_rejects_result_but_explicit_stop_releases_host(self):
        implementation = await self.result(await self.controller.begin(self.url))
        accepted = self.gh.note["spec_revision"]
        original = self.gh.work["body"]
        self.gh.work["body"] += "\nDifferent objective."
        self.ws.dirty = True
        with self.assertRaises(ValueError):
            await self.result(implementation)
        stopped = await self.result(implementation, "stopped")
        self.assertEqual(stopped["reason"], "replan_required")
        self.assertFalse(self.ws.dirty)
        self.assertEqual(self.gh.note["spec_revision"], accepted)
        with coordinator_lock(self.lock):
            pass
        self.gh.work["body"] = original
        result = await self.new_controller().begin(self.url)
        self.assertEqual(result["reason"], "replan_required")
        self.assertEqual(self.gh.note["correction_attempt"], 3)

    async def test_failed_spec_review_corrects_only_spec_then_reaccepts_before_code(self):
        from test_spec_reacceptance import SnapshotWorkspace
        self.ws = SnapshotWorkspace(Path(self.tmp.name) / "owned", self.gh, [])
        self.controller = self.new_controller()
        review = await self.controller.begin(self.url)
        correction = await self.result(review, "failed")
        self.assertEqual(correction["phase"], "design")
        spec = self.ws.path / "docs/engineering/task/spec.md"
        spec.write_text(spec.read_text() + "\nAdd explicit failure acceptance.")
        result = await self.result(correction)
        self.assertEqual(result["action"], "continue")
        self.assertNotEqual(result["head"], correction["head"])
        review = await self.controller.advance(self.url, result["attempt_id"], result["head"], result["contract_revision"])
        self.assertEqual(review["phase"], "spec_review")
        implementation = await self.result(review)
        self.assertEqual(implementation["phase"], "implementation")


class NativeSchemaTests(unittest.TestCase):
    def test_native_identity_is_typed_and_public_output_excludes_raw_summary(self):
        from hydra_sdlc.github import GitHub as Client, GitHubError
        Client._validate_record({"execution_mode": "native", "native_phase": "spec_review",
            "native_step": "00000000-0000-0000-0000-000000000001", "native_head": BASE,
            "native_spec_digest": hashlib.sha256(b"spec").hexdigest(), "native_outcome": "failed"})
        for field, value in (("native_phase", "shell"), ("native_step", "old"),
                             ("native_outcome", "pass=true"), ("summary", "private")):
            with self.assertRaises(GitHubError):
                Client._validate_record({field: value})

    def test_plugin_packages_one_skill_and_exactly_five_tools(self):
        import json
        root = Path(__file__).resolve().parents[1]
        plugin = root / "plugins/hydra"
        self.assertEqual(json.loads((plugin / "plugin.json").read_text())["name"], "hydra")
        self.assertEqual(json.loads((plugin / "mcp.json").read_text())["mcpServers"]["hydra"]["type"], "stdio")
        self.assertEqual(len(list((plugin / "skills").glob("*/SKILL.md"))), 1)


class ActualGitNativeTests(unittest.IsolatedAsyncioTestCase):
    async def test_explicit_stop_preserves_local_edits_and_refuses_changed_or_deleted_remote(self):
        from hydra_sdlc.workspace import WorkspaceWait
        from test_workspace import LocalWorkspace, git
        for deleted in (False, True):
            with self.subTest(deleted=deleted), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                remote, seed = root / "origin.git", root / "seed"
                remote.mkdir(); seed.mkdir()
                git(remote, "init", "--bare", "--initial-branch=main")
                git(seed, "init", "--initial-branch=main")
                spec = seed / "docs/engineering/task/spec.md"
                spec.parent.mkdir(parents=True)
                spec.write_text("Requirement and acceptance for stopped Git fixture.\n")
                git(seed, "add", ".")
                git(seed, "commit", "-m", "accepted fixture base")
                base = git(seed, "rev-parse", "HEAD")
                git(seed, "remote", "add", "origin", str(remote))
                git(seed, "push", "origin", "main")
                gh = GitHub()
                gh.cfg["revision"] = base
                workspace = LocalWorkspace(root / "owned", remote)
                make = lambda: NativeController(gh, workspace, repos=["example/product"],
                    host_alias="test", lock_path=root / "host.lock")
                url = "https://github.com/example/product/issues/4"
                async def result(c, assignment, outcome="candidate_ready"):
                    return await c.checkpoint(url, assignment["attempt_id"], assignment["step_id"],
                        assignment["head"], assignment["contract_revision"], outcome)
                with patch("hydra_sdlc.runner.load_project", side_effect=lambda *a, **kw: copy.deepcopy(gh.cfg)), \
                        patch("hydra_sdlc.native.load_project", side_effect=lambda *a, **kw: copy.deepcopy(gh.cfg)):
                    c = make()
                    assignment = await result(c, await c.begin(url))
                    path = Path(assignment["cwd"])
                    git(path, "push", "origin", "hydra/issue-4")
                    gh.branch = gh.note["expected_head"] = base
                    if deleted:
                        git(seed, "push", "origin", "--delete", "hydra/issue-4")
                        gh.branch = None
                    else:
                        (seed / "external.txt").write_text("separate remote work\n")
                        git(seed, "add", ".")
                        git(seed, "commit", "-m", "external branch update")
                        gh.branch = git(seed, "rev-parse", "HEAD")
                        git(seed, "push", "origin", "HEAD:hydra/issue-4")
                    source = path / "src/main.py"
                    source.parent.mkdir()
                    source.write_text("preserved_implementation = True\n")
                    with self.assertRaisesRegex(WorkspaceWait, "remote_head_changed"):
                        await result(c, assignment)
                    stopped = await result(c, assignment, "stopped")
                    self.assertEqual(stopped["reason"], "remote_head_changed")
                    self.assertEqual(gh.note["expected_head"], base)
                    self.assertEqual((root / "host.lock").read_bytes(), b"")
                    self.assertFalse(workspace.inspect(path)["dirty"])
                    self.assertEqual(git(path, "show", "HEAD:src/main.py"), "preserved_implementation = True")
                    self.assertFalse((path / "external.txt").exists())
                    wait = await make().begin(url)
                    self.assertEqual(wait["reason"], "remote_head_changed")
                    self.assertNotIn("native_step", gh.note)
                    self.assertFalse(any(w[0] in {"push", "pr", "merge"} for w in gh.writes))

    async def test_committed_decision_checkpoint_resumes_from_real_git_after_restart(self):
        from test_workspace import LocalWorkspace, git
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            remote, seed = root / "origin.git", root / "seed"
            remote.mkdir()
            seed.mkdir()
            git(remote, "init", "--bare", "--initial-branch=main")
            git(seed, "init", "--initial-branch=main")
            spec = seed / "docs/engineering/task/spec.md"
            spec.parent.mkdir(parents=True)
            spec.write_text("Requirement and acceptance for an actual Git fixture.\n")
            git(seed, "add", ".")
            git(seed, "commit", "-m", "accepted fixture base")
            base = git(seed, "rev-parse", "HEAD")
            git(seed, "remote", "add", "origin", str(remote))
            git(seed, "push", "origin", "main")
            gh = GitHub()
            gh.cfg["revision"] = base
            workspace = LocalWorkspace(root / "owned", remote)
            controller = lambda: NativeController(gh, workspace, repos=["example/product"],
                host_alias="test", lock_path=root / "host.lock")
            url = "https://github.com/example/product/issues/4"
            async def result(c, assignment, outcome="candidate_ready"):
                return await c.checkpoint(url.replace("example/product", "Example/Product"),
                    assignment["attempt_id"], assignment["step_id"],
                    assignment["head"], assignment["contract_revision"], outcome)
            with patch("hydra_sdlc.runner.load_project", side_effect=lambda *a, **kw: copy.deepcopy(gh.cfg)), \
                    patch("hydra_sdlc.native.load_project", side_effect=lambda *a, **kw: copy.deepcopy(gh.cfg)):
                c = controller()
                assignment = await result(c, await c.begin(url))
                self.assertEqual(assignment["phase"], "implementation")
                path = Path(assignment["cwd"])
                source = path / "src/main.py"
                source.parent.mkdir()
                source.write_text("implementation = True\n")
                pending = await result(c, assignment, "needs_decision")
                self.assertEqual(pending["reason"], "product_decision")
                self.assertFalse(workspace.inspect(path)["dirty"])
                self.assertEqual(git(path, "show", "HEAD:src/main.py"), "implementation = True")
                gh.extra_comments.append({"user": {"login": "openboa"},
                    "body": f"hydra: decision {gh.note['attempt_id']} resolved"})
                c = controller()
                review = await c.begin(url)
                self.assertEqual(review["phase"], "spec_review")
                resumed = await result(c, review)
                self.assertEqual(resumed["phase"], "implementation")
                self.assertEqual(resumed["head"], workspace.inspect(path)["head"])
                await result(c, resumed, "stopped")
