"""Operator hints expose wake boundaries without creating execution authority."""

import copy
from pathlib import Path
import unittest

from hydra_sdlc.coordinator import HostBusy
from hydra_sdlc.operations import OperatingControl
from hydra_sdlc.progress import progress_hint, with_progress_hint
from hydra_sdlc.workspace import WorkspaceWait
import test_host_resources as resource_fixture
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
                 ("host_stopped", "await_control_change", "control_change"),
                 ("project_paused", "await_control_change", "control_change"),
                 ("project_stopped", "await_control_change", "control_change")]
        for reason, action, source in cases:
            with self.subTest(reason=reason):
                self.assertEqual(progress_hint({"reason": reason}), {
                    "kind": "human", "next_action": action, "wake_source": source})
        self.assertEqual(progress_hint({"reason": "host_paused", "resume_hint": "decision_resolved"})["kind"], "human")

    def test_generic_stop_never_invents_an_operating_control_hold(self):
        for key in ["reason", "wait_reason"]:
            self.assertEqual(progress_hint({key: "stop_requested", "action": "completed"}), {
                "kind": "unknown", "next_action": "reconcile", "wake_source": "none"})

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
        self.assertEqual(progress_hint({"action": "completed", "resource_status": "retired"})["kind"], "complete")
        self.assertEqual(progress_hint({"progress": {"phase": "completed", "pending_action": None}})["kind"], "complete")
        self.assertEqual(progress_hint({"action": "native_task"}), {
            "kind": "actionable", "next_action": "perform_native_assignment", "wake_source": "none"})
        for reason in ["native_assignment_pending", "native_task_active"]:
            self.assertEqual(progress_hint({"wait_reason": reason}), {
                "kind": "unknown", "next_action": "reconcile_native_assignment", "wake_source": "native_checkpoint"})

    def test_resource_wait_overrides_completion_and_retirement_claims(self):
        for reason, kind in [("resource_completion_unconfirmed", "unknown"),
                             ("resource_cleanup_pending", "actionable")]:
            for completed in [{"action": "completed", "resource_status": "retired"},
                              {"progress": {"phase": "completed", "pending_action": None}}]:
                with self.subTest(reason=reason, completed=completed):
                    self.assertEqual(progress_hint({**completed, "resource_wait_reason": reason}), {
                        "kind": kind, "next_action": "reconcile_completion", "wake_source": "none"})
        self.assertEqual(progress_hint({"action": "completed", "reason": "host_paused",
                                       "resource_wait_reason": "resource_cleanup_pending"}), {
            "kind": "human", "next_action": "await_control_change", "wake_source": "control_change"})

    def test_unknown_resource_wait_never_falls_through_to_complete(self):
        for reason in [[], {}, False, 0, "", "new_resource_reason"]:
            with self.subTest(reason=reason):
                self.assertEqual(progress_hint({
                    "action": "completed", "resource_status": "retired", "resource_wait_reason": reason,
                    "progress": {"phase": "completed", "pending_action": None, "next_action": "resource_cleanup"}}), {
                    "kind": "unknown", "next_action": "reconcile", "wake_source": "none"})

    def test_durable_resource_cleanup_is_not_a_completed_responsibility(self):
        value = {"progress": {"phase": "completed", "pending_action": None, "next_action": "resource_cleanup"}}
        before = copy.deepcopy(value)
        self.assertEqual(with_progress_hint(value)["progress_hint"], {
            "kind": "actionable", "next_action": "reconcile_completion", "wake_source": "none"})
        self.assertEqual(value, before)
        value["progress"]["next_action"] = "completed"
        self.assertEqual(progress_hint(value)["kind"], "complete")


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
        expected = {"kind": "unknown", "next_action": "reconcile", "wake_source": "none"}
        self.assertEqual((await runner.step("example/product", 4))["progress_hint"], expected)
        runner.host_hold_reason = "host_cleanup_unconfirmed"
        self.assertEqual((await runner.cycle(["example/product"]))[0]["progress_hint"]["kind"], "unknown")
        self.assertEqual(runner.status(["example/product"])[0]["progress_hint"], expected)

    async def test_cancelled_verification_with_running_controls_requires_reconciliation(self):
        operations = OperatingControl(Path(self.directory.name).resolve() / "host.lock", ["example/product"])
        operations.set_mode("start")
        controls_before = operations.snapshot()
        runner = self.runner()
        runner.operations = operations
        # The workflow fixture uses the same durable in-memory record for exact
        # confirmed cleanup; production checkpoint authentication is unchanged.
        self.github.record_checkpoint = self.github.record
        self.assertEqual((await runner.step("example/product", 4))["action"], "continue")
        self.calls.clear()

        def verify(path, commands, *, stop_requested):
            self.stop = True
            self.assertTrue(stop_requested())
            raise WorkspaceWait("verification_stopped")

        self.workspace.verify = verify
        result = await runner.step("example/product", 4)
        self.assertEqual(result["reason"], "stop_requested")
        expected = {"kind": "unknown", "next_action": "reconcile", "wake_source": "none"}
        self.assertEqual(result["progress_hint"], expected)
        self.assertEqual(self.calls, [])
        self.assertFalse(any(write[0] in {"push", "pr", "merge", "close"} for write in self.github.writes))
        self.assertIsNone(operations.reason("example/product"))
        self.assertEqual(operations.snapshot(), controls_before)
        self.assertEqual(self.github.note["wait_reason"], "stop_requested")
        self.stop = False
        before = copy.deepcopy(self.github.note), copy.deepcopy(self.github.writes), list(self.calls)
        for _ in range(2):
            self.assertEqual(runner.status(["example/product"])[0]["progress_hint"], expected)
        self.assertEqual((self.github.note, self.github.writes, self.calls), before)


class ResourceProgressTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = resource_fixture.CompletionTests.asyncSetUp
    deliver = resource_fixture.CompletionTests.deliver

    async def test_cleanup_failure_and_read_only_status_do_not_retire_responsibility(self):
        self.ws.fail_retire = True
        result = await self.deliver()
        self.assertEqual(result["action"], "completed")
        self.assertEqual(result["resource_wait_reason"], "resource_cleanup_pending")
        expected = {"kind": "actionable", "next_action": "reconcile_completion", "wake_source": "none"}
        self.assertEqual(result["progress_hint"], expected)
        self.assertEqual(self.gh.note["phase"], "completed")
        self.assertEqual(self.gh.note["next_action"], "resource_cleanup")
        self.assertEqual(self.gh.work["state"], "closed")
        before = copy.deepcopy(self.gh.note), copy.deepcopy(self.gh.writes), list(self.ws.retired)
        for _ in range(2):
            self.assertEqual(self.runner.status(["example/product"])[0]["progress_hint"], expected)
        self.assertEqual((self.gh.note, self.gh.writes, self.ws.retired), before)
        effects = [write for write in self.gh.writes if write[0] in {"push", "pr", "merge", "close"}]
        self.ws.fail_retire = False
        result = await self.runner.step("example/product", 4)
        self.assertEqual(result["resource_status"], "retired")
        self.assertEqual(result["progress_hint"], {"kind": "complete", "next_action": "none", "wake_source": "none"})
        self.assertEqual(self.gh.note["next_action"], "completed")
        self.assertEqual([write for write in self.gh.writes if write[0] in {"push", "pr", "merge", "close"}], effects)

    async def test_unconfirmed_completion_readback_stays_unknown_until_reconciled(self):
        original_progress = self.gh.progress
        unavailable = False

        def progress(repo, number):
            nonlocal unavailable
            if (not unavailable and self.gh.note and self.gh.note.get("phase") == "completed"
                    and self.gh.note.get("next_action") == "resource_cleanup"):
                unavailable = True
                return None
            return original_progress(repo, number)

        self.gh.progress = progress
        result = await self.deliver()
        self.assertTrue(unavailable)
        self.assertEqual(result["action"], "completed")
        self.assertEqual(result["resource_wait_reason"], "resource_completion_unconfirmed")
        self.assertEqual(result["progress_hint"], {
            "kind": "unknown", "next_action": "reconcile_completion", "wake_source": "none"})
        self.assertEqual(self.ws.retired, [])
        self.assertEqual(self.gh.note["phase"], "completed")
        self.assertEqual(self.gh.note["next_action"], "resource_cleanup")
        self.assertEqual(self.gh.work["state"], "closed")
        effects = [write for write in self.gh.writes if write[0] in {"push", "pr", "merge", "close"}]
        result = await self.runner.step("example/product", 4)
        self.assertEqual(result["resource_status"], "retired")
        self.assertEqual(result["progress_hint"]["kind"], "complete")
        self.assertEqual(self.gh.note["next_action"], "completed")
        self.assertEqual([write for write in self.gh.writes if write[0] in {"push", "pr", "merge", "close"}], effects)


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
        self.assertEqual(stopped["progress_hint"], {
            "kind": "unknown", "next_action": "reconcile", "wake_source": "none"})
        self.assertEqual(self.lock.read_bytes(), b"")
