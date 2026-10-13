"""Terminal main checks require diagnosis, not another model or delivery effect."""

import copy
import unittest

from hydra_sdlc.github import GitHubError
from hydra_sdlc.operations import OperationDenied
import test_runner as workflow


class PostMergeContinuityTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = workflow.RunnerTests.asyncSetUp
    execute = workflow.RunnerTests.execute
    capabilities = workflow.RunnerTests.capabilities
    runner = workflow.RunnerTests.runner
    publish = workflow.RunnerTests.publish

    async def merged(self):
        runner = await self.publish()
        await runner.step("example/product", 4)
        self.assertTrue(self.github.pr["merged"])
        return runner

    def effects(self):
        return [value for value in self.github.writes if value[0] != "record"]

    async def test_terminal_failure_stays_diagnosable_across_restart_without_effects(self):
        await self.merged()
        actual = self.github.observe_commit

        def failed(repo, sha):
            value = actual(repo, sha)
            value["runs"][0]["jobs"][0]["conclusion"] = "failure"
            value["checks"][0]["conclusion"] = "failure"
            return value

        self.github.observe_commit = failed
        before = len(self.calls), self.effects(), self.github.note["attempt_id"]
        for _ in range(3):
            result = await self.runner().step("example/product", 4)
            self.assertEqual(result["reason"], "post_merge_failed")
            self.assertEqual(result["progress_hint"], {
                "kind": "actionable", "next_action": "diagnose_post_merge", "wake_source": "none"})
            self.assertEqual(self.github.note["next_action"], "diagnose_post_merge")
        self.assertEqual((len(self.calls), self.effects(), self.github.note["attempt_id"]), before)
        self.assertEqual(self.github.work["state"], "open")

    async def test_unknown_identity_holds_instead_of_polling_or_closing(self):
        await self.merged()
        actual = self.github.observe_commit

        def unknown(repo, sha):
            value = actual(repo, sha)
            value["checks"][0]["app"]["id"] = 999
            return value

        self.github.observe_commit = unknown
        before = len(self.calls), self.effects()
        result = await self.runner().step("example/product", 4)
        self.assertEqual(result["reason"], "post_merge_evidence_unknown")
        self.assertEqual(result["progress_hint"]["kind"], "unknown")
        self.assertEqual((len(self.calls), self.effects()), before)

    async def test_failure_after_close_intent_retains_intent_until_valid_success(self):
        runner = await self.merged()
        actual = self.github.observe_commit
        observations = 0

        def late_failure(repo, sha):
            nonlocal observations
            observations += 1
            value = actual(repo, sha)
            if observations > 1:
                value["runs"][0]["jobs"][0]["conclusion"] = "failure"
                value["checks"][0]["conclusion"] = "failure"
            return value

        self.github.observe_commit = late_failure
        before = len(self.calls), self.effects()
        result = await runner.step("example/product", 4)
        self.assertEqual(result["reason"], "post_merge_failed")
        self.assertEqual(self.github.note["pending_action"], "close_issue")
        self.assertEqual((len(self.calls), self.effects()), before)
        # Simulate the existing closed-intent recovery boundary, not new closure.
        self.github.work["state"] = "closed"
        result = await self.runner().step("example/product", 4)
        self.assertEqual(result["reason"], "post_merge_failed")
        self.assertEqual(self.github.note["pending_action"], "close_issue")
        self.github.observe_commit = actual
        result = await self.runner().step("example/product", 4)
        self.assertEqual(result["action"], "completed")
        self.assertEqual(result["progress_hint"]["kind"], "complete")
        self.assertEqual((len(self.calls), self.effects()), before)

    async def test_first_check_read_errors_return_unknown_without_effects(self):
        await self.merged()
        before = len(self.calls), self.effects(), self.github.note["attempt_id"]
        for error in [GitHubError, RuntimeError, OSError, ValueError]:
            with self.subTest(error=error.__name__):
                def unavailable(repo, sha):
                    raise error("private read diagnostic")
                self.github.observe_commit = unavailable
                result = await self.runner().step("example/product", 4)
                self.assertEqual(result["reason"], "post_merge_evidence_unknown")
                self.assertEqual(result["progress_hint"]["kind"], "unknown")
                self.assertIsNone(self.github.note["pending_action"])
                self.assertNotIn("private read diagnostic", repr(result) + repr(self.github.note))
        self.assertEqual((len(self.calls), self.effects(), self.github.note["attempt_id"]), before)

    async def test_check_read_errors_after_close_intent_preserve_recovery(self):
        await self.merged()
        actual = self.github.observe_commit
        initial = copy.deepcopy(self.github.note)
        before = len(self.calls), self.effects()
        for error in [GitHubError, RuntimeError, OSError, ValueError]:
            with self.subTest(error=error.__name__):
                self.github.note = copy.deepcopy(initial)
                calls = 0
                def unavailable(repo, sha):
                    nonlocal calls
                    calls += 1
                    if calls == 2:
                        raise error("private read diagnostic")
                    return actual(repo, sha)
                self.github.observe_commit = unavailable
                result = await self.runner().step("example/product", 4)
                self.assertEqual(result["reason"], "post_merge_evidence_unknown")
                self.assertEqual(self.github.note["pending_action"], "close_issue")
                self.assertEqual((len(self.calls), self.effects()), before)
        self.github.observe_commit = actual
        self.github.work["state"] = "closed"
        result = await self.runner().step("example/product", 4)
        self.assertEqual(result["action"], "completed")
        self.assertEqual((len(self.calls), self.effects()), before)

    async def test_admission_denial_is_not_reclassified_as_unknown_ci(self):
        await self.merged()
        before = copy.deepcopy(self.github.note), len(self.calls), self.effects()
        def denied(repo, sha):
            raise OperationDenied("host_paused")
        self.github.observe_commit = denied
        result = await self.runner().step("example/product", 4)
        self.assertEqual(result["reason"], "host_paused")
        self.assertEqual(result["progress_hint"]["wake_source"], "control_change")
        self.assertEqual((self.github.note, len(self.calls), self.effects()), before)

    async def test_read_and_progress_outage_still_returns_bounded_unknown(self):
        await self.merged()
        actual_read, actual_record = self.github.observe_commit, self.github.record
        initial = copy.deepcopy(self.github.note)
        before = len(self.calls), self.effects()
        for fail_at in [1, 2]:
            with self.subTest(fail_at=fail_at):
                self.github.note = copy.deepcopy(initial)
                calls = 0
                unknown_writes = []
                def unavailable(repo, sha):
                    nonlocal calls
                    calls += 1
                    if calls == fail_at:
                        raise GitHubError("private outage diagnostic")
                    return actual_read(repo, sha)
                def record_unavailable(repo, number, record):
                    if record.get("wait_reason") == "post_merge_evidence_unknown":
                        unknown_writes.append(record)
                        raise GitHubError("private outage diagnostic")
                    return actual_record(repo, number, record)
                self.github.observe_commit = unavailable
                self.github.record = record_unavailable
                result = await self.runner().step("example/product", 4)
                self.assertEqual(result["reason"], "post_merge_evidence_unknown")
                self.assertNotIn("private outage diagnostic", repr(result))
                self.assertEqual(self.github.note["pending_action"], "close_issue" if fail_at == 2 else None)
                self.assertEqual(unknown_writes, [])
                self.assertEqual((len(self.calls), self.effects()), before)

    async def test_pending_rerun_replaces_old_failure_then_converges_without_model(self):
        await self.merged()
        actual = self.github.observe_commit

        def rerun(repo, sha):
            value = actual(repo, sha)
            old = copy.deepcopy(value["runs"][0])
            old["jobs"][0]["conclusion"] = "failure"
            value["runs"][0].update(id=51, run_attempt=2, check_suite_id=81,
                                     status="in_progress", conclusion=None)
            value["runs"][0]["jobs"][0].update(id=91, status="in_progress", conclusion=None,
                check_run_url="https://api.github.com/repos/example/product/check-runs/91")
            value["checks"][0].update(id=91, check_suite={"id": 81}, status="in_progress", conclusion=None)
            value["runs"].append(old)
            return value

        self.github.observe_commit = rerun
        before = len(self.calls), self.effects()
        result = await self.runner().step("example/product", 4)
        self.assertEqual(result["reason"], "post_merge_checks")
        self.assertEqual(result["progress_hint"]["kind"], "external")
        self.assertEqual((len(self.calls), self.effects()), before)
        self.github.observe_commit = actual
        result = await self.runner().step("example/product", 4)
        self.assertEqual(result["action"], "completed")
        self.assertEqual(len(self.calls), before[0])
        self.assertEqual([x[0] for x in self.effects()[len(before[1]):]], ["close"])

