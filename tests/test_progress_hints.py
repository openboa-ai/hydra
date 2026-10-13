"""Operator hints expose wake boundaries without creating execution authority."""

import copy
import unittest

from hydra_sdlc.coordinator import HostBusy
from hydra_sdlc.progress import progress_hint, with_progress_hint
import test_native as native_fixture
import test_runner as workflow


class ProgressHintTests(unittest.TestCase):
    def test_unknown_and_malformed_facts_never_request_work(self):
        for value in [None, [], {}, {"reason": []}, {"reason": "new_reason"},
                      {"reason": ""}, {"state": "closed"},
                      {"reason": "new_reason", "action": "completed"}]:
            with self.subTest(value=value):
                self.assertEqual(progress_hint(value), {
                    "kind": "unknown", "next_action": "reconcile", "wake_source": "none"})

    def test_decisions_intake_and_controls_name_the_actual_wake_source(self):
        cases = [("product_decision", "await_operator_decision", "operator_decision"),
                 ("not_delegated", "await_delegation", "issue_update"),
                 ("host_paused", "await_control_change", "control_change"),
                 ("project_stopped", "await_control_change", "control_change")]
        for reason, action, source in cases:
            with self.subTest(reason=reason):
                self.assertEqual(progress_hint({"reason": reason}), {
                    "kind": "human", "next_action": action, "wake_source": source})
        self.assertEqual(progress_hint({"reason": "host_paused", "resume_hint": "decision_resolved"})["kind"], "human")

    def test_only_exact_observed_resolution_is_actionable(self):
        for reason, marker in [("product_decision", "decision_resolved"), ("replan_required", "replan_ready")]:
            self.assertEqual(progress_hint({"wait_reason": reason, "resume_hint": marker}), {
                "kind": "actionable", "next_action": "begin", "wake_source": "none"})
            self.assertEqual(progress_hint({"wait_reason": reason, "resume_hint": "wrong"})["kind"], "human")

    def test_provenance_is_not_a_command_and_hints_are_not_persisted(self):
        value = {"action": "continue", "next_action": "decision_context_private_provenance"}
        original = copy.deepcopy(value)
        first = with_progress_hint(value)
        self.assertEqual(first, with_progress_hint(value))
        self.assertEqual(value, original)
        self.assertEqual(first["progress_hint"]["next_action"], "advance")
        first["progress_hint"]["kind"] = "human"
        self.assertEqual(with_progress_hint(first)["progress_hint"]["kind"], "actionable")

    def test_only_known_pending_checks_are_external(self):
        for reason, kind, action in [
                ("post_merge_checks", "external", "observe_post_merge_checks"),
                ("post_merge_failed", "actionable", "diagnose_post_merge"),
                ("post_merge_evidence_unknown", "unknown", "reconcile_post_merge_evidence")]:
            self.assertEqual(progress_hint({"reason": reason}), {
                "kind": kind, "next_action": action,
                "wake_source": "none" if reason == "post_merge_failed" else "ci_update"})
        self.assertEqual(progress_hint({"reason": "remote_delivery_gates"})["kind"], "unknown")

    def test_completed_work_and_fresh_assignment_keep_distinct_meanings(self):
        self.assertEqual(progress_hint({"action": "completed"})["kind"], "complete")
        self.assertEqual(progress_hint({"progress": {"phase": "completed", "pending_action": None}})["kind"], "complete")
        self.assertEqual(progress_hint({"action": "native_task"}), {
            "kind": "actionable", "next_action": "perform_native_assignment", "wake_source": "none"})
        for reason in ["native_assignment_pending", "native_task_active"]:
            self.assertEqual(progress_hint({"wait_reason": reason}), {
                "kind": "unknown", "next_action": "reconcile_native_assignment", "wake_source": "native_checkpoint"})


class RunnerProgressTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = workflow.RunnerTests.asyncSetUp
    execute = workflow.RunnerTests.execute
    capabilities = workflow.RunnerTests.capabilities
    runner = workflow.RunnerTests.runner

    async def test_status_does_not_write_or_start_work_while_intake_is_missing(self):
        self.github.work["labels"] = []
        runner = self.runner()
        before = copy.deepcopy(self.github.writes)
        first = runner.status(["example/product"])
        self.assertEqual(first, runner.status(["example/product"]))
        self.assertEqual(first[0]["progress_hint"], {
            "kind": "human", "next_action": "await_delegation", "wake_source": "issue_update"})
        self.assertEqual(self.github.writes, before)
        self.assertEqual(self.calls, [])
        self.assertEqual((await runner.step("example/product", 4))["progress_hint"], first[0]["progress_hint"])

    async def test_status_resolution_uses_authenticated_marker_and_retains_question(self):
        runner = self.runner()
        await runner.step("example/product", 4)
        self.github.note.update(wait_reason="product_decision", resume_phase="implementation")
        before = copy.deepcopy(self.github.note), len(self.github.writes), len(self.calls)
        self.assertEqual(runner.status(["example/product"])[0]["progress_hint"]["kind"], "human")
        self.github.resolve_decision()
        resolved = runner.status(["example/product"])[0]
        self.assertEqual(resolved["progress_hint"], {"kind": "actionable", "next_action": "begin", "wake_source": "none"})
        self.assertEqual((self.github.note, len(self.github.writes), len(self.calls)), before)

    async def test_every_public_runner_return_has_a_hint(self):
        runner = self.runner()
        self.stop = True
        self.assertEqual((await runner.step("example/product", 4))["progress_hint"]["wake_source"], "control_change")
        runner.host_hold_reason = "host_cleanup_unconfirmed"
        self.assertEqual((await runner.cycle(["example/product"]))[0]["progress_hint"]["kind"], "unknown")
        self.assertEqual(runner.status(["example/product"])[0]["progress_hint"]["wake_source"], "control_change")


class NativeProgressTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = native_fixture.NativeTests.asyncSetUp
    new_controller = native_fixture.NativeTests.new_controller
    result = native_fixture.NativeTests.result

    async def test_pending_and_legacy_status_preserve_the_exact_ticket_without_writes(self):
        assignment = await self.controller.begin(self.url)
        self.assertEqual(assignment["action"], "native_task")
        self.assertEqual(assignment["progress_hint"]["next_action"], "perform_native_assignment")
        self.assertEqual(self.gh.note["wait_reason"], "native_assignment_pending")
        ticket = self.lock.read_bytes()
        for reason in ["native_assignment_pending", "native_task_active"]:
            with self.subTest(reason=reason):
                self.gh.note["wait_reason"] = reason
                restarted = self.new_controller()
                before = copy.deepcopy(self.gh.note), len(self.gh.writes)
                rows = restarted.status()
                self.assertEqual(rows, restarted.status())
                self.assertEqual(rows[0]["progress_hint"], {
                    "kind": "unknown", "next_action": "reconcile_native_assignment", "wake_source": "native_checkpoint"})
                self.assertEqual((self.gh.note, len(self.gh.writes)), before)
                with self.assertRaises(HostBusy):
                    await restarted.begin(self.url)
                self.assertEqual(self.lock.read_bytes(), ticket)
        stopped = await self.result(assignment, "stopped")
        self.assertIn("progress_hint", stopped)
        self.assertEqual(self.lock.read_bytes(), b"")

