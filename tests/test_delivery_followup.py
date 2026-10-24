"""P14: reconcile acknowledged intent writes without inventing a dispatch."""
import copy
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hydra_sdlc.github import GitHub, GitHubError
from hydra_sdlc.native_delivery import Delivery
from hydra_sdlc.runner import Runner
import test_delivery_guards as guards


class DeliverySourceBudgetTests(unittest.TestCase):
    def test_progress_source_uses_its_own_bounded_read_client(self):
        calls, observations = [], []
        github = GitHub(transport=lambda method, path, payload: calls.append((method, path)) or {})
        value = Delivery.__new__(Delivery)
        value.repo, value.number, value.reader = 'example/product', 4, None
        value.runner = SimpleNamespace(github=github, _record_values=Runner._record_values)
        value.observer = observations.append
        expected = {'phase': 'published'}
        def source(client, repo, number):
            for _ in range(33):
                client.api('GET', '/repos/example/product')
            return {'record': copy.deepcopy(expected),
                    'resource': {'source': 'github', 'kind': 'issue_comment', 'id': 'example/product/comments/1'}}
        with patch.object(GitHub, 'progress_source', source):
            with self.assertRaises(GitHubError):
                value.source(expected)
        self.assertEqual(len(calls), 32)
        self.assertEqual(observations, [])
        self.assertEqual(github._read_budgets, [])
        self.assertIsNone(value.reader)


class DeliveryIntentAcknowledgmentTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = guards.DeliveryGuardTests.asyncSetUp
    new_controller = guards.DeliveryGuardTests.new_controller
    result = guards.DeliveryGuardTests.result
    command = guards.DeliveryGuardTests.command
    checkpoint = guards.DeliveryGuardTests.checkpoint
    real_git_assignment = guards.DeliveryGuardTests.real_git_assignment
    candidate = guards.DeliveryGuardTests.candidate
    verification_command = guards.DeliveryGuardTests.verification_command
    verification_grant = guards.DeliveryGuardTests.verification_grant
    call = guards.DeliveryGuardTests.call
    finish_command = guards.DeliveryGuardTests.finish_command
    reviewed = guards.DeliveryGuardTests.reviewed
    publication_command = guards.DeliveryGuardTests.publication_command
    publication_grant = guards.DeliveryGuardTests.publication_grant
    publish = guards.DeliveryGuardTests.publish
    published = guards.DeliveryGuardTests.published
    delivery_command = guards.DeliveryGuardTests.delivery_command
    delivery_grant = guards.DeliveryGuardTests.delivery_grant
    deliver = guards.DeliveryGuardTests.deliver
    effects = guards.DeliveryGuardTests.effects
    unchanged_candidate = guards.DeliveryGuardTests.unchanged_candidate

    async def lost_intent(self, action):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        record, merge, close = self.gh.record_checkpoint, self.gh.merge, self.gh.close_issue
        lost, attempts = False, []
        def lose_ack(repo, number, value):
            nonlocal lost
            result = record(repo, number, value)
            if value.get('pending_action') == action and not lost:
                lost = True
                raise RuntimeError('Synthetic acknowledged intent write with lost response')
            return result
        def merged(*args, **kwargs):
            attempts.append(('merge', self.gh.note.get('delivery_attempt')))
            return merge(*args, **kwargs)
        def closed(*args, **kwargs):
            attempts.append(('close', self.gh.note.get('delivery_attempt')))
            return close(*args, **kwargs)
        self.gh.record_checkpoint, self.gh.merge, self.gh.close_issue = lose_ack, merged, closed
        start = len(self.gh.writes)
        first = await self.deliver(command)
        self.assertTrue(lost)
        self.assertEqual(first['request']['outcome'], 'unknown', first)
        self.assertEqual(self.gh.note['pending_action'], action)
        self.assertEqual(self.gh.note['delivery_attempt'], 1)
        self.assertEqual(self.gh.work['state'], 'open')
        self.assertEqual(self.effects(start), [] if action == 'merge' else [('merge', candidate['head'])])
        recovered = await self.deliver(command)
        self.assertEqual(recovered['request']['outcome'], 'applied', recovered)
        self.assertEqual(self.effects(start), [('merge', candidate['head']), ('close', 4)])
        self.assertEqual(attempts, [('merge', 1), ('close', 1)])
        self.unchanged_candidate(candidate)

    async def test_lost_merge_intent_ack_recovers_the_confirmed_unsent_request(self):
        await self.lost_intent('merge')

    async def test_lost_close_intent_ack_recovers_without_remerge_or_new_attempt(self):
        await self.lost_intent('close_issue')
