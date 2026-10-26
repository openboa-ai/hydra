"""One work guard deadline includes current progress and actual v2 collection."""
import copy
from contextlib import contextmanager
import unittest
from unittest.mock import patch

from hydra_sdlc.github import GitHub
from hydra_sdlc.operations import OperationDenied
from hydra_sdlc.work_decisions import WorkDecisionGuard
from hydra_sdlc import delegated_decisions
from delegated_decision_fixture import ATTEMPT, REPO, InstallationFixture


class DelegatedDecisionDeadlineTests(InstallationFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.setup_installation()
        self.write_profile(True)
        self.make_server(new_profile=True)
        published = self.reply(await self.invoke())
        self.assertEqual(published['request']['outcome'], 'applied', published)
        self.before = copy.deepcopy(self.transport.effects)

    def progress_read_takes(self, seconds, clock):
        reads = []
        def advance(path):
            if '/issues/4/comments?' in path:
                reads.append(path)
                if len(reads) == 1:
                    clock[0] += seconds
        self.transport.before_read = advance
        return reads

    async def test_actual_v2_collection_uses_only_remaining_guard_budget(self):
        clock, budgets = [0.0], []
        reads = self.progress_read_takes(6.0, clock)
        original_budget = GitHub.read_budget
        @contextmanager
        def observed_budget(client, *, seconds, requests, **kwargs):
            budgets.append((seconds, requests))
            with original_budget(client, seconds=seconds, requests=requests, **kwargs) as value:
                yield value
        with patch('hydra_sdlc.work_decisions.monotonic', side_effect=lambda: clock[0]), \
                patch.object(GitHub, 'read_budget', new=observed_budget):
            observed, record = WorkDecisionGuard(self.controller.runner, REPO, 4)._work(timeout=15)
        self.assertGreaterEqual(len(reads), 3, 'The real current-progress and v2 source collection must run')
        self.assertEqual(observed[2].status, 'pair')
        self.assertEqual(record['attempt_id'], ATTEMPT)
        self.assertGreaterEqual(len(budgets), 2)
        self.assertEqual(budgets[0][0], 15)
        self.assertGreater(budgets[1][0], 0)
        self.assertLessEqual(budgets[1][0], 9,
            'The authenticated v2 reader cannot receive a fresh 15 seconds after six seconds of progress IO')
        self.assertEqual(self.transport.effects, self.before)

    async def test_completed_actual_v2_result_cannot_escape_expired_guard(self):
        clock, observed_pairs = [0.0], []
        self.progress_read_takes(6.0, clock)
        original_read = delegated_decisions.observe_work
        def completed_late(*args, **kwargs):
            result = original_read(*args, **kwargs)
            self.assertIsNotNone(result, 'This must expire after a real successful v2 observation')
            self.assertEqual(result[2].status, 'pair')
            observed_pairs.append(result[0].sha256)
            # Elapsed CPU/scheduling time after the final source IO is still
            # part of the enclosing work guard; no source fact is fabricated.
            clock[0] = 16.0
            return result
        with patch('hydra_sdlc.work_decisions.monotonic', side_effect=lambda: clock[0]), \
                patch.object(delegated_decisions, 'observe_work', side_effect=completed_late):
            with self.assertRaises(OperationDenied):
                WorkDecisionGuard(self.controller.runner, REPO, 4)._work(timeout=15)
        self.assertEqual(len(observed_pairs), 1)
        self.assertEqual(self.transport.effects, self.before)
        self.assertEqual(self.github.progress(REPO, 4)['attempt_id'], ATTEMPT)

    async def test_in_budget_actual_v2_result_remains_usable(self):
        clock = [0.0]
        self.progress_read_takes(6.0, clock)
        original_read = delegated_decisions.observe_work
        def completed_in_time(*args, **kwargs):
            result = original_read(*args, **kwargs)
            clock[0] = 14.0
            return result
        with patch('hydra_sdlc.work_decisions.monotonic', side_effect=lambda: clock[0]), \
                patch.object(delegated_decisions, 'observe_work', side_effect=completed_in_time):
            observed, record = WorkDecisionGuard(self.controller.runner, REPO, 4)._work(timeout=15)
        self.assertEqual(observed[2].status, 'pair')
        self.assertEqual(record['attempt_id'], ATTEMPT)
        self.assertEqual(self.transport.effects, self.before)
