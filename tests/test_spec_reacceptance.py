"""Revised specification bytes require a new review and implementation turn."""

import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc.codex import _assignment_options
from hydra_sdlc.runner import Runner
from hydra_sdlc.workspace import WorkspaceWait
from test_project import BASE, HEAD
from test_runner import GitHub, Workspace, complete_capabilities
from test_workspace import LocalWorkspace, git


REPO = "example/product"
SPEC = "docs/engineering/task/spec.md"


class SnapshotWorkspace(Workspace):
    """Derive every diff from actual fixture bytes at the requested commit."""

    def __init__(self, directory, github, events):
        super().__init__(directory, github)
        self.events = events
        self.snapshots = {BASE: self.contents()}
        self.commits = 0
        self.on_verify = None

    def contents(self):
        return {str(path.relative_to(self.path)): path.read_bytes()
                for path in self.path.rglob("*") if path.is_file()}

    def inspect(self, path):
        state = super().inspect(path)
        state["dirty"] = self.dirty or self.contents() != self.snapshots[self.head]
        return state

    def changed_paths(self, path, base):
        if base not in self.snapshots:
            raise WorkspaceWait("git_operation_failed")
        before, after = self.snapshots[base], self.contents()
        return sorted(name for name in before.keys() | after.keys()
                      if before.get(name) != after.get(name))

    def checkpoint(self, path, message):
        if self.inspect(path)["dirty"]:
            self.commits += 1
            self.head = HEAD if self.commits == 1 else f"{self.commits:040x}"
            self.snapshots[self.head] = self.contents()
            self.dirty = False
            self.events.append(("checkpoint", self.head))
        return self.head

    def verify(self, path, commands, *, stop_requested=lambda: False):
        self.events.append(("verify", self.head))
        result = super().verify(path, commands, stop_requested=stop_requested)
        effect, self.on_verify = self.on_verify, None
        if effect:
            effect()
        return result


class SpecReacceptanceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.github = GitHub()
        self.events, self.records, self.calls = [], [], []
        self.workspace = SnapshotWorkspace(self.root, self.github, self.events)
        self.initial_spec = (self.root / SPEC).read_bytes()
        self.effects = {}
        self.stop = self.low_usage = False
        self.edits = 0
        self.github.on_record = lambda record: self.records.append(copy.deepcopy(record))
        loader = patch("hydra_sdlc.runner.load_project", side_effect=lambda gh, repo: copy.deepcopy(gh.cfg))
        loader.start()
        self.addCleanup(loader.stop)

    def edit_spec(self, content=None):
        target = self.root / SPEC
        target.write_bytes(content if content is not None else target.read_bytes() + b"\nRevised requirement.")
        self.workspace.dirty = True

    def edit_source(self):
        self.edits += 1
        source = self.root / "src/main.py"
        source.parent.mkdir(exist_ok=True)
        source.write_text(f"implementation_version = {self.edits}\n")
        self.workspace.dirty = True

    def queue(self, phase, effect=None, *, outcome="candidate_ready", status="completed"):
        self.effects.setdefault(phase, []).append((effect, outcome, status))

    async def execute(self, assignment, **kwargs):
        _assignment_options(assignment)
        phase = self.github.note["pending_action"]
        self.calls.append(phase)
        self.events.append(("model", phase))
        self.assertEqual(assignment["mode"], "read_only" if "review" in phase else "workspace_write")
        effect, outcome, status = (self.effects[phase].pop(0) if self.effects.get(phase)
                                   else (None, "candidate_ready", "completed"))
        if phase in {"implementation", "correction"}:
            self.edit_source()
        elif phase == "design" and effect is None:
            self.edit_spec()
        if effect:
            effect()
        if status != "completed":
            return {"status": status, "detail": {"cleanup": "confirmed"}}
        return {"status": "completed", "detail": {"result": {"outcome": outcome,
                "summary": "fixture finding", "evidence": [], "next_action": ""}}}

    async def capabilities(self, cwd):
        return complete_capabilities(used=95 if self.low_usage else 10, allowed=not self.low_usage)

    def runner(self):
        return Runner(self.github, self.workspace, host_alias="host-a", execute=self.execute,
                      capabilities=self.capabilities, stop_requested=lambda: self.stop)

    async def step(self, runner=None):
        return await (runner or self.runner()).step(REPO, 4)

    async def implemented(self):
        self.assertEqual((await self.step())["action"], "continue")
        self.assertEqual(self.calls, ["spec_review", "implementation"])
        self.assertEqual(self.github.note["spec_revision"], BASE)
        self.assertEqual(self.workspace.verification_calls, 0)
        self.calls.clear()

    async def published(self):
        await self.implemented()
        self.github.remote_pending = True
        await self.step()
        self.assertIsNotNone(self.github.pr)
        self.calls.clear()

    def assert_revised_checkpoint(self, anchor=BASE):
        record = self.github.note
        self.assertEqual(record["spec_revision"], anchor)
        self.assertEqual(record["resume_phase"], "implementation")
        self.assertEqual(record["head"], self.workspace.head)
        self.assertFalse(self.workspace.inspect(self.root)["dirty"])
        self.assertNotEqual(self.workspace.snapshots[record["head"]][SPEC],
                            self.workspace.snapshots[anchor][SPEC])
        self.assertEqual(record["correction_reason"], "accepted_spec_changed")
        self.assertGreater(record["correction_attempt"], 0)

    async def assert_review_then_implementation(self, runner=None):
        self.calls.clear()
        before, revision = self.workspace.verification_calls, self.workspace.head
        result = await self.step(runner)
        self.assertEqual(result["action"], "continue", result)
        self.assertEqual(self.calls, ["spec_review", "implementation"])
        self.assertEqual(self.workspace.verification_calls, before)
        self.assertEqual(self.github.note["spec_revision"], revision)
        self.assertIsNone(self.github.note.get("resume_phase"))
        self.assertNotEqual(self.workspace.head, revision)

    async def test_implementation_spec_mutation_is_checkpointed_then_reaccepted_before_verification(self):
        self.queue("implementation", self.edit_spec)
        await self.implemented()
        self.assert_revised_checkpoint()
        self.assertFalse(any(name in {"push", "pr", "merge"} for name, *_ in self.github.writes))
        await self.assert_review_then_implementation()
        self.calls.clear()
        await self.step()
        self.assertEqual(self.calls, ["spec_review", "change_review"])
        self.assertEqual(self.workspace.verification_calls, 1)

    async def test_existing_pr_correction_keeps_implementation_remaining_after_spec_changes(self):
        await self.published()
        old_remote, verified = self.github.branch, self.workspace.verification_calls
        self.queue("correction", self.edit_spec)
        record = self.github.progress(REPO, 4)
        config = {**self.github.cfg, "intake_digest": record["intake_digest"]}
        result = await self.runner()._correct(REPO, 4, config, record, self.root, "review_findings")
        self.assertEqual(result["action"], "continue")
        self.assert_revised_checkpoint()
        self.assertEqual(self.github.branch, old_remote)
        await self.assert_review_then_implementation()
        self.assertEqual(self.workspace.verification_calls, verified)
        self.assertEqual(self.github.pr["head"]["sha"], old_remote)
        self.assertFalse(any(write[0] == "merge" for write in self.github.writes))

    async def verifier_mutation(self, *, commit=False, stopped=False):
        await self.implemented()
        def mutate():
            self.edit_spec()
            if commit:
                self.workspace.checkpoint(self.root, "Verifier committed changed specification")
            if stopped:
                self.stop = True
                raise WorkspaceWait("verification_stopped")
        self.workspace.on_verify = mutate
        result = await self.step()
        self.assertEqual(result.get("reason") if stopped else result["action"],
                         "stop_requested" if stopped else "continue")
        self.assertEqual(self.calls, ["spec_review"])
        self.assert_revised_checkpoint()
        self.assertEqual(self.workspace.verification_calls, 1)
        self.stop = False
        await self.assert_review_then_implementation()
        self.calls.clear()
        await self.step()
        self.assertEqual(self.workspace.verification_calls, 2)
        self.assertEqual(self.calls, ["spec_review", "change_review"])

    async def test_dirty_verifier_spec_change_requires_review_and_implementation(self):
        await self.verifier_mutation()

    async def test_committed_verifier_spec_change_requires_review_and_implementation(self):
        await self.verifier_mutation(commit=True)

    async def test_stopped_verifier_spec_change_preserves_remaining_implementation(self):
        await self.verifier_mutation(stopped=True)

    async def test_confirmed_interruption_preserves_spec_anchor_and_new_work_across_restart(self):
        def interrupted():
            self.edit_spec()
            self.stop = True
        self.queue("implementation", interrupted, status="interrupted")
        self.assertEqual((await self.step())["reason"], "stop_requested")
        self.assert_revised_checkpoint()
        self.assertEqual(self.github.note["checkpoint"], "interrupted_committed")
        self.assertFalse(any(write[0] in {"push", "pr", "merge"} for write in self.github.writes))
        self.stop = False
        await self.assert_review_then_implementation()
        self.assertEqual(self.workspace.verification_calls, 0)

    async def test_decision_wait_preserves_revised_spec_work_without_consuming_attempts(self):
        self.queue("implementation", self.edit_spec, outcome="needs_decision")
        self.assertEqual((await self.step())["reason"], "product_decision")
        self.assert_revised_checkpoint()
        attempts, calls = self.github.note["correction_attempt"], list(self.calls)
        for _ in range(2):
            self.assertEqual((await self.step())["reason"], "product_decision")
            self.assertEqual(self.github.note["correction_attempt"], attempts)
            self.assertEqual(self.calls, calls)
        self.github.extra_comments.append({"user": {"login": "operator"},
            "body": f"hydra: decision {self.github.note['attempt_id']} resolved"})
        await self.assert_review_then_implementation()

    async def test_explicit_stopped_handover_checkpoints_spec_before_reacceptance(self):
        await self.implemented()
        self.github.note.update(phase="executing", pending_action="correction")
        self.edit_spec()
        self.edit_source()
        dirty = self.workspace.contents()
        self.assertEqual((await self.step())["reason"], "confirm_previous_stopped")
        self.assertEqual(self.workspace.contents(), dirty)
        self.assertEqual(self.calls, [])
        self.github.extra_comments.append({"user": {"login": "operator"},
            "body": f"hydra: handover {self.github.note['attempt_id']} stopped"})
        before_handover = len(self.records)
        result = await self.step()
        self.assertEqual(result["action"], "continue")
        self.assertEqual(self.calls, ["spec_review", "implementation"])
        self.assertEqual(self.workspace.verification_calls, 0)
        self.assertIn(True, self.workspace.prepared_recovery)
        revised = [record for record in self.records[before_handover:] if record.get("resume_phase") == "implementation"
                   and record.get("spec_revision") == BASE and record.get("head") != HEAD]
        self.assertTrue(revised, self.records)
        self.assertEqual(self.workspace.snapshots[revised[0]["head"]][SPEC], dirty[SPEC])

    async def test_unchanged_spec_source_commit_and_remote_wait_do_not_repeat_implementation(self):
        await self.implemented()
        self.github.remote_pending = True
        await self.step()
        self.assertEqual(self.calls, ["spec_review", "change_review"])
        self.assertEqual(self.github.note["spec_revision"], BASE)
        self.assertEqual(self.workspace.verification_calls, 1)
        self.calls.clear()
        for _ in range(2):
            self.assertEqual((await self.step())["reason"], "remote_delivery_gates")
        self.assertEqual(self.calls, [])

    async def test_pause_and_decision_labels_do_not_prevent_stopped_spec_checkpoint(self):
        def interrupted():
            self.edit_spec()
            self.github.work["labels"] += [
                {"name": self.github.cfg["labels"]["paused"]},
                {"name": self.github.cfg["labels"]["decision"]},
            ]
        self.queue("implementation", interrupted, status="interrupted")
        self.assertEqual((await self.step())["reason"], "stop_requested")
        self.assert_revised_checkpoint()
        self.calls.clear()
        self.assertEqual((await self.step())["reason"], "paused")
        self.github.work["labels"] = [item for item in self.github.work["labels"]
                                       if item["name"] != self.github.cfg["labels"]["paused"]]
        self.assertEqual((await self.step())["reason"], "human_decision")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.workspace.verification_calls, 0)
        self.github.work["labels"] = [{"name": self.github.cfg["labels"]["ready"]}]
        await self.assert_review_then_implementation()

    async def test_intake_edit_during_stop_cannot_redirect_original_spec_checkpoint(self):
        original_body = self.github.work["body"]
        replacement = "docs/engineering/other/spec.md"
        def interrupted():
            self.edit_spec()
            self.github.work["body"] = original_body.replace(SPEC, replacement)
        self.queue("implementation", interrupted, status="interrupted")
        self.assertEqual((await self.step())["reason"], "stop_requested")
        self.assert_revised_checkpoint()
        self.assertFalse((self.root / replacement).exists())
        checkpoint, records, writes = copy.deepcopy(self.github.note), len(self.records), len(self.github.writes)
        self.calls.clear()
        self.assertEqual((await self.step())["reason"], "intake_changed")
        self.assertEqual(self.github.note, checkpoint)
        self.assertEqual(len(self.records), records)
        self.assertEqual(len(self.github.writes), writes)
        self.assertEqual(self.calls, [])
        self.github.work["body"] = original_body
        await self.assert_review_then_implementation()

    async def test_pinned_intake_spec_mismatch_remains_blocked(self):
        self.github.work["body"] = self.github.work["body"].replace(
            "```hydra\n", f'```hydra\nspec_revision = "{BASE}"\n')
        original_file = self.github.file
        self.github.file = lambda repo, path, revision: (
            {"content": self.initial_spec.decode(), "sha": self.github.cfg["blob_sha"]}
            if path == SPEC else original_file(repo, path, revision))
        self.queue("implementation", self.edit_spec)
        await self.implemented()
        self.assert_revised_checkpoint()
        self.assertEqual((await self.step())["reason"], "accepted_spec_content_changed")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.workspace.verification_calls, 0)
        self.assertEqual(self.github.note["spec_revision"], BASE)

    async def test_read_only_reviewer_mutation_never_accepts_or_dispatches_implementation(self):
        self.queue("spec_review", self.edit_spec)
        result = await self.step()
        self.assertEqual(result["action"], "waiting")
        self.assertIsNone(self.github.note["spec_revision"])
        self.assertEqual(self.calls, ["spec_review"])
        self.assertEqual(self.workspace.verification_calls, 0)
        self.assertTrue(self.workspace.inspect(self.root)["dirty"])

    async def test_old_in_memory_acceptance_cannot_accept_bytes_under_a_changed_anchor(self):
        runner = self.runner()
        self.queue("implementation", self.edit_spec)
        await self.step(runner)
        self.assert_revised_checkpoint()
        self.queue("implementation", lambda: self.edit_spec(self.initial_spec))
        self.calls.clear()
        await self.step(runner)
        self.assertEqual(self.calls, ["spec_review", "implementation"])
        self.assertNotEqual(self.github.note["spec_revision"], BASE)
        self.assertEqual((self.root / SPEC).read_bytes(), self.initial_spec)
        await self.assert_review_then_implementation(runner)

    async def test_repeated_mutations_are_bounded_but_usage_observations_do_not_increment(self):
        self.queue("implementation", self.edit_spec)
        await self.implemented()
        self.assert_revised_checkpoint()
        attempts = self.github.note["correction_attempt"]
        self.low_usage = True
        for _ in range(3):
            self.assertEqual((await self.step())["reason"], "usage_unavailable_or_low")
            self.assertEqual(self.github.note["correction_attempt"], attempts)
            self.assertEqual(self.calls, [])
        self.low_usage = False
        for _ in range(2):
            self.queue("implementation", self.edit_spec)
            result = await self.step()
        self.assertEqual(result["reason"], "replan_required")
        self.assertEqual(self.github.note["correction_attempt"], 3)
        count = len(self.calls)
        for _ in range(2):
            self.assertEqual((await self.step())["reason"], "replan_required")
            self.assertEqual(self.github.note["correction_attempt"], 3)
        self.assertEqual(len(self.calls), count)
        self.assertEqual(self.workspace.verification_calls, 0)

    async def test_rejected_revised_spec_correction_is_scoped_to_its_pre_correction_head(self):
        self.queue("implementation", self.edit_spec)
        await self.implemented()
        source = (self.root / "src/main.py").read_bytes()
        self.queue("spec_review", outcome="failed")
        self.queue("design", self.edit_spec)
        result = await self.step()
        self.assertEqual(result["action"], "continue", result)
        self.assertEqual(self.calls, ["spec_review", "design"])
        self.assertEqual((self.root / "src/main.py").read_bytes(), source)
        self.assert_revised_checkpoint()
        await self.assert_review_then_implementation()

    async def test_pending_publication_is_reconciled_at_its_exact_head_before_reacceptance(self):
        self.queue("implementation", self.edit_spec)
        await self.implemented()
        pending_head = self.workspace.head
        self.github.note.update(phase="uncertain", pending_action="publish", expected_head=None,
                                expected_base=BASE, delivery_action="publish", delivery_head=pending_head,
                                delivery_attempt=1)
        result = await self.step()
        self.assertEqual(result["action"], "continue")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.workspace.verification_calls, 0)
        self.assertEqual([write for write in self.github.writes if write[0] == "push"], [("push", pending_head)])
        intents = [record for record in self.records if record.get("pending_action") == "publish"]
        self.assertTrue(intents)
        self.assertTrue(all(record["head"] == pending_head and record["delivery_head"] == pending_head
                            for record in intents))
        self.assertEqual(self.github.note["spec_revision"], BASE)
        self.assertEqual(self.github.note["resume_phase"], "implementation")

    async def test_different_correction_reasons_preserve_mutation_budget_through_unknown_recovery(self):
        self.queue("implementation", self.edit_spec)
        await self.implemented()
        self.queue("implementation", self.edit_spec)
        await self.step()
        self.assertEqual(self.github.note["correction_attempt"], 2)
        await self.assert_review_then_implementation()
        self.assertEqual(self.github.note["correction_attempt"], 2)
        anchor = self.github.note["spec_revision"]
        record = self.github.progress(REPO, 4)
        config = {**self.github.cfg, "intake_digest": record["intake_digest"]}
        unchanged_spec = (self.root / SPEC).read_bytes()
        first = await self.runner()._correct(REPO, 4, config, record, self.root, "ci_failure")
        self.assertEqual(first["action"], "continue")
        self.assertEqual((self.root / SPEC).read_bytes(), unchanged_spec)
        self.assertGreaterEqual(self.github.note["correction_attempt"], 2)
        self.assertEqual(self.github.note["correction_reason"], "ci_failure")
        record = self.github.progress(REPO, 4)
        self.queue("correction", self.edit_spec, status="transport_unknown")
        result = await self.runner()._correct(REPO, 4, config, record, self.root, "review_findings")
        self.assertEqual(result["reason"], "execution_unknown")
        intents = [value for value in self.records if value.get("phase") == "executing"
                   and value.get("pending_action") == "correction"
                   and value.get("correction_reason") == "review_findings"]
        self.assertTrue(intents)
        self.assertGreaterEqual(intents[-1]["correction_attempt"], 2)
        preserved = self.workspace.contents()
        self.calls.clear()
        self.assertEqual((await self.step())["reason"], "confirm_previous_stopped")
        self.assertEqual(self.workspace.contents(), preserved)
        self.github.extra_comments.append({"user": {"login": "operator"},
            "body": f"hydra: handover {self.github.note['attempt_id']} stopped"})
        self.assertEqual((await self.step())["reason"], "replan_required")
        self.assertEqual(self.github.note["correction_attempt"], 3)
        self.assertEqual(self.github.note["spec_revision"], anchor)
        self.assertEqual(self.github.note["resume_phase"], "implementation")
        self.assertEqual(self.workspace.snapshots[self.github.note["head"]], preserved)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.workspace.verification_calls, 0)

    async def test_existing_pr_spec_restoration_still_requires_remaining_implementation(self):
        await self.published()
        verified, remote = self.workspace.verification_calls, self.github.branch
        record = self.github.progress(REPO, 4)
        config = {**self.github.cfg, "intake_digest": record["intake_digest"]}
        self.queue("correction", self.edit_spec)
        await self.runner()._correct(REPO, 4, config, record, self.root, "review_findings")
        self.calls.clear()
        self.queue("spec_review", outcome="failed")
        self.queue("design", lambda: self.edit_spec(self.initial_spec))
        self.assertEqual((await self.step())["action"], "continue")
        self.assertEqual(self.calls, ["spec_review", "design"])
        self.assertEqual((self.root / SPEC).read_bytes(), self.initial_spec)
        self.assertEqual(self.github.note["spec_revision"], BASE)
        self.assertEqual(self.github.note["resume_phase"], "implementation")
        restored_head = self.workspace.head
        self.calls.clear()
        self.assertEqual((await self.step())["action"], "continue")
        self.assertEqual(self.calls, ["spec_review", "implementation"])
        self.assertNotEqual(self.workspace.head, restored_head)
        self.assertEqual(self.github.note["spec_revision"], BASE)
        self.assertIsNone(self.github.note.get("resume_phase"))
        self.assertEqual(self.workspace.verification_calls, verified)
        self.assertEqual(self.github.pr["head"]["sha"], remote)
        self.assertFalse(any(write[0] == "merge" for write in self.github.writes))

    async def test_interrupted_spec_only_correction_allows_prior_legitimate_implementation(self):
        self.queue("implementation", self.edit_spec)
        await self.implemented()
        before = self.workspace.head
        source = (self.root / "src/main.py").read_bytes()
        self.queue("spec_review", outcome="failed")
        self.queue("design", self.edit_spec, status="interrupted")
        result = await self.step()
        self.assertEqual(result["reason"], "stop_requested")
        self.assertEqual(self.calls, ["spec_review", "design"])
        self.assert_revised_checkpoint()
        self.assertEqual(self.github.note["checkpoint"], "interrupted_committed")
        self.assertEqual(self.workspace.changed_paths(self.root, before), [SPEC])
        self.assertIn("src/main.py", self.workspace.changed_paths(self.root, BASE))
        self.assertEqual((self.root / "src/main.py").read_bytes(), source)
        self.assertEqual(self.workspace.verification_calls, 0)
        await self.assert_review_then_implementation()

    async def test_initial_design_can_request_decision_without_edits_or_a_spec_file(self):
        (self.root / SPEC).unlink()
        self.workspace.snapshots[BASE].pop(SPEC)
        self.queue("design", lambda: None, outcome="needs_decision")
        result = await self.step()
        self.assertEqual(result["reason"], "product_decision")
        self.assertEqual(self.calls, ["design"])
        self.assertEqual(self.github.note["resume_phase"], "design")
        self.assertIsNone(self.github.note["spec_revision"])
        self.assertEqual(self.workspace.head, BASE)
        self.assertFalse((self.root / SPEC).exists())
        self.assertEqual(self.workspace.verification_calls, 0)
        self.assertFalse(any(write[0] in {"push", "pr", "merge"} for write in self.github.writes))
        self.github.extra_comments.append({"user": {"login": "operator"},
            "body": f"hydra: decision {self.github.note['attempt_id']} resolved"})
        self.queue("design", lambda: None)
        self.calls.clear()
        self.assertEqual((await self.step())["reason"], "replan_required")
        self.assertEqual(self.github.note["next_action"], "diagnose_spec_artifact")
        self.assertEqual(self.calls, ["design"])
        self.assertIsNone(self.github.note["spec_revision"])
        self.assertEqual(self.workspace.verification_calls, 0)

    async def test_spec_only_correction_can_request_decision_without_new_edits(self):
        self.queue("implementation", self.edit_spec)
        await self.implemented()
        self.assert_revised_checkpoint()
        previous = copy.deepcopy(self.github.note)
        contents = self.workspace.contents()
        self.queue("spec_review", outcome="failed")
        self.queue("design", lambda: None, outcome="needs_decision")
        result = await self.step()
        self.assertEqual(result["reason"], "product_decision")
        self.assertEqual(self.calls, ["spec_review", "design"])
        self.assertEqual(self.github.note["resume_phase"], "implementation")
        for field in ("spec_revision", "head", "correction_attempt"):
            self.assertEqual(self.github.note[field], previous[field])
        self.assertEqual(self.workspace.contents(), contents)
        self.assertEqual(self.workspace.verification_calls, 0)
        self.assertFalse(any(write[0] in {"push", "pr", "merge"} for write in self.github.writes))
        self.calls.clear()
        self.assertEqual((await self.step())["reason"], "product_decision")
        self.assertEqual(self.calls, [])
        self.assertEqual(self.github.note["correction_attempt"], previous["correction_attempt"])

    async def test_unchanged_accepted_spec_decision_resumes_scoped_revision_with_prior_implementation(self):
        await self.implemented()
        source = (self.root / "src/main.py").read_bytes()
        self.assertEqual((self.root / SPEC).read_bytes(), self.initial_spec)
        self.queue("spec_review", outcome="failed")
        self.queue("design", lambda: None, outcome="needs_decision")
        self.assertEqual((await self.step())["reason"], "product_decision")
        self.assertEqual(self.calls, ["spec_review", "design"])
        self.assertEqual(self.github.note["resume_phase"], "implementation")
        self.assertEqual(self.github.note["spec_revision"], BASE)
        self.assertEqual(self.workspace.head, HEAD)
        self.assertEqual(self.workspace.verification_calls, 0)
        self.github.extra_comments.append({"user": {"login": "operator"},
            "body": f"hydra: decision {self.github.note['attempt_id']} resolved"})
        self.calls.clear()
        self.queue("spec_review", outcome="failed")
        self.queue("design", self.edit_spec)
        result = await self.step()
        self.assertEqual(result["action"], "continue", result)
        self.assertEqual(self.calls, ["spec_review", "design"])
        self.assertEqual((self.root / "src/main.py").read_bytes(), source)
        self.assertEqual(self.workspace.changed_paths(self.root, HEAD), [SPEC])
        self.assert_revised_checkpoint()
        self.assertEqual(self.workspace.verification_calls, 0)
        self.assertFalse(any(write[0] in {"push", "pr", "merge"} for write in self.github.writes))
        await self.assert_review_then_implementation()


class ActualGitSpecAnchorTests(unittest.TestCase):
    def test_actual_git_diff_binds_spec_bytes_to_available_accepted_commit(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            remote, seed = root / "origin.git", root / "seed"
            remote.mkdir()
            seed.mkdir()
            git(remote, "init", "--bare", "--initial-branch=main")
            git(seed, "init", "--initial-branch=main")
            spec = seed / SPEC
            spec.parent.mkdir(parents=True)
            spec.write_text("Accepted requirement.\n")
            git(seed, "add", ".")
            git(seed, "commit", "-m", "accepted specification")
            anchor = git(seed, "rev-parse", "HEAD")
            git(seed, "remote", "add", "origin", str(remote))
            git(seed, "push", "origin", "main")
            workspace = LocalWorkspace(root / "owned", remote)
            path = workspace.prepare(REPO, 4, "hydra/issue-4", None)
            github = GitHub()
            runner = Runner(github, workspace, host_alias="fixture", execute=None, capabilities=None)
            record = {"spec_revision": anchor}
            changed = lambda: runner._spec_changed(REPO, 4, {**github.cfg, "_scoped_spec": SPEC}, record, path)
            self.assertFalse(changed())
            (path / "src").mkdir()
            (path / "src/main.py").write_text("implementation = True\n")
            workspace.checkpoint(path, "source-only implementation")
            self.assertFalse(changed())
            (path / SPEC).write_text("Revised requirement.\n")
            self.assertTrue(changed())
            workspace.checkpoint(path, "checkpoint revised specification")
            self.assertTrue(changed())
            record["spec_revision"] = "f" * 40
            with self.assertRaises(WorkspaceWait):
                changed()


if __name__ == "__main__":
    unittest.main()
