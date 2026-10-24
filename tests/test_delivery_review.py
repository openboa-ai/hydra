"""P14 review regressions: pending close continuity and immutable completion history."""
import copy
import unittest
from unittest.mock import patch

import test_delivery_guards as fixture
import test_squash_completion as legacy
import test_active_labels as active_labels
from hydra_sdlc.github import GitHub, GitHubError


class DeliveryReviewTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.DeliveryGuardTests.asyncSetUp
    new_controller = fixture.DeliveryGuardTests.new_controller
    result = fixture.DeliveryGuardTests.result
    command = fixture.DeliveryGuardTests.command
    checkpoint = fixture.DeliveryGuardTests.checkpoint
    real_git_assignment = fixture.DeliveryGuardTests.real_git_assignment
    candidate = fixture.DeliveryGuardTests.candidate
    verification_command = fixture.DeliveryGuardTests.verification_command
    verification_grant = fixture.DeliveryGuardTests.verification_grant
    call = fixture.DeliveryGuardTests.call
    finish_command = fixture.DeliveryGuardTests.finish_command
    reviewed = fixture.DeliveryGuardTests.reviewed
    publication_command = fixture.DeliveryGuardTests.publication_command
    publication_grant = fixture.DeliveryGuardTests.publication_grant
    publish = fixture.DeliveryGuardTests.publish
    published = fixture.DeliveryGuardTests.published
    delivery_command = fixture.DeliveryGuardTests.delivery_command
    delivery_grant = fixture.DeliveryGuardTests.delivery_grant
    deliver = fixture.DeliveryGuardTests.deliver
    effects = fixture.DeliveryGuardTests.effects
    unchanged_candidate = fixture.DeliveryGuardTests.unchanged_candidate

    async def wait_then_recover(self, state, *, lose_wait_ack=False):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        intent, observe, writer = self.controller.runner._intent, self.gh.observe_commit, self.gh.record_checkpoint
        current, lost = 'success', False
        def plan(*args, **kwargs):
            nonlocal current
            value = intent(*args, **kwargs)
            if args[4] == 'close_issue' and value is not None:
                current = state
            return value
        def checks(repo, sha):
            value = observe(repo, sha)
            if current != 'success':
                status, conclusion = ('in_progress', None) if current == 'pending' else ('completed', 'failure')
                value['runs'][0].update(status=status, conclusion=conclusion)
                value['runs'][0]['jobs'][0].update(status=status, conclusion=conclusion)
                value['checks'][0].update(status=status, conclusion=conclusion)
            return value
        def record(repo, number, value):
            nonlocal lost
            result = writer(repo, number, value)
            if (lose_wait_ack and not lost and value.get('pending_action') == 'close_issue'
                    and value.get('phase') == 'observing'):
                lost = True
                raise RuntimeError('Synthetic wait checkpoint acknowledgment loss')
            return result
        self.gh.observe_commit, self.gh.record_checkpoint = checks, record
        start = len(self.gh.writes)
        with patch.object(self.controller.runner, '_intent', side_effect=plan):
            waiting = await self.deliver(command)
        self.assertIn(waiting['request']['outcome'], {'waiting', 'unknown'}, waiting)
        self.assertEqual(self.gh.work['state'], 'open')
        self.assertEqual(self.gh.note['pending_action'], 'close_issue')
        self.assertEqual(self.gh.note['delivery_attempt'], 1)
        self.assertEqual(self.effects(start), [('merge', candidate['head'])])
        if lose_wait_ack:
            self.assertTrue(lost)
        current = 'success'
        recovered = await self.deliver(command)
        self.assertEqual(recovered['request']['outcome'], 'applied', recovered)
        self.assertEqual(self.effects(start), [('merge', candidate['head']), ('close', 4)])
        self.assertEqual(self.gh.note['delivery_attempt'], 1)
        self.unchanged_candidate(candidate)

    async def test_pending_main_checks_resume_the_known_undispatched_close(self):
        await self.wait_then_recover('pending')

    async def test_failed_main_checks_resume_after_later_success_without_a_new_attempt(self):
        await self.wait_then_recover('failed')

    async def test_lost_wait_checkpoint_ack_preserves_the_known_undispatched_close(self):
        await self.wait_then_recover('pending', lose_wait_ack=True)

    async def test_completed_replay_reports_reruns_without_rewriting_completion(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        self.assertEqual((await self.deliver(command))['request']['outcome'], 'applied')
        completed, start = copy.deepcopy(self.gh.note), len(self.gh.writes)
        observe = self.gh.observe_commit
        current = 'success'
        def checks(repo, sha):
            if current == 'unknown':
                raise RuntimeError('Synthetic unavailable current check source')
            value = observe(repo, sha)
            if current != 'success':
                status, conclusion = ('in_progress', None) if current == 'pending' else ('completed', 'failure')
                value['runs'][0].update(status=status, conclusion=conclusion)
                value['runs'][0]['jobs'][0].update(status=status, conclusion=conclusion)
                value['checks'][0].update(status=status, conclusion=conclusion)
            return value
        self.gh.observe_commit = checks
        for current in ('pending', 'failed', 'unknown'):
            waiting = await self.deliver(command)
            self.assertEqual(waiting['request']['outcome'], 'waiting', waiting)
            self.assertEqual(waiting['request']['receipt']['post_merge'], current)
            self.assertEqual(self.gh.note, completed)
            self.assertEqual(self.gh.writes[start:], [])
            current = 'success'
            restored = await self.deliver(command)
            self.assertEqual(restored['request']['outcome'], 'applied', restored)
            self.assertEqual(self.gh.note, completed)
            self.assertEqual(self.gh.writes[start:], [])
        self.unchanged_candidate(candidate)

    async def test_human_reopened_completed_issue_stays_open_after_a_check_rerun(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        self.assertEqual((await self.deliver(command))['request']['outcome'], 'applied')
        completed, start = copy.deepcopy(self.gh.note), len(self.gh.writes)
        observe = self.gh.observe_commit
        pending = True
        def checks(repo, sha):
            value = observe(repo, sha)
            if pending:
                value['runs'][0].update(status='in_progress', conclusion=None)
                value['runs'][0]['jobs'][0].update(status='in_progress', conclusion=None)
                value['checks'][0].update(status='in_progress', conclusion=None)
            return value
        self.gh.observe_commit = checks
        self.assertEqual((await self.deliver(command))['request']['outcome'], 'waiting')
        self.gh.work['state'] = 'open'
        pending = False
        restored = await self.deliver(command)
        self.assertEqual(restored['request']['outcome'], 'waiting', restored)
        self.assertEqual(restored['request']['reason'], 'completion_reopened')
        self.assertEqual(self.gh.work['state'], 'open')
        self.assertEqual(self.gh.note, completed)
        self.assertEqual(self.gh.writes[start:], [])
        self.unchanged_candidate(candidate)


    async def test_reopened_completion_preserves_history_across_review_thread_wait(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        self.assertEqual((await self.deliver(command))['request']['outcome'], 'applied')
        completed, start = copy.deepcopy(self.gh.note), len(self.gh.writes)
        original = self.gh.transform_observation
        self.gh.work['state'] = 'open'
        self.gh.transform_observation = lambda value: {**original(value), 'threads': [{'isResolved': False}]}
        waiting = await self.deliver(command)
        self.assertEqual(waiting['request']['outcome'], 'waiting', waiting)
        self.assertEqual(waiting['request']['reason'], 'completion_evidence_missing')
        self.assertEqual(self.gh.note, completed)
        self.assertEqual(self.gh.writes[start:], [])
        self.gh.transform_observation = original
        replay = await self.deliver(command)
        self.assertEqual(replay['request']['outcome'], 'waiting', replay)
        self.assertEqual(replay['request']['reason'], 'completion_reopened')
        self.assertEqual(self.gh.work['state'], 'open')
        self.assertEqual(self.gh.note, completed)
        self.assertEqual(self.gh.writes[start:], [])
        self.unchanged_candidate(candidate)

    async def test_closed_completion_replays_after_candidate_review_evidence_returns(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        self.assertEqual((await self.deliver(command))['request']['outcome'], 'applied')
        completed, start = copy.deepcopy(self.gh.note), len(self.gh.writes)
        original = self.gh.transform_observation
        self.gh.transform_observation = lambda value: {**original(value), 'provider_comments': []}
        waiting = await self.deliver(command)
        self.assertEqual(waiting['request']['outcome'], 'waiting', waiting)
        self.assertEqual(waiting['request']['reason'], 'completion_evidence_missing')
        self.assertEqual(self.gh.note, completed)
        self.assertEqual(self.gh.writes[start:], [])
        self.gh.transform_observation = original
        replay = await self.deliver(command)
        self.assertEqual(replay['request']['outcome'], 'applied', replay)
        self.assertEqual(self.gh.work['state'], 'closed')
        self.assertEqual(self.gh.note, completed)
        self.assertEqual(self.gh.writes[start:], [])
        self.unchanged_candidate(candidate)


class LegacyCompletionReviewTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = legacy.SquashRunnerTests.asyncSetUp
    execute = legacy.SquashRunnerTests.execute
    capabilities = legacy.SquashRunnerTests.capabilities
    step = legacy.SquashRunnerTests.step
    opened_pr = legacy.SquashRunnerTests.opened_pr
    merged_with_empty_association = legacy.SquashRunnerTests.merged_with_empty_association

    async def test_completed_label_cleanup_preserves_its_terminal_progress(self):
        await self.merged_with_empty_association()
        self.github.work['state'] = 'closed'
        transport = active_labels.NativeIssueTransport()
        transport.issue = {**copy.deepcopy(self.github.work), 'comments': 0,
            'labels': copy.deepcopy(self.github.work['labels']) + [{'name': 'hydra:active'}]}
        client = GitHub(transport=transport)
        completed = legacy.Runner._record_values(self.github.note,
            phase='completed', pending_action=None, wait_reason=None, next_action='completed')
        transport.fail = 'label_remove_before'
        with self.assertRaises(GitHubError) as lost:
            client.record(legacy.REPO, 4, completed)
        self.assertEqual(str(lost.exception), 'cleanup unavailable')
        self.assertIsNotNone(transport.comment)
        completed = client.progress(legacy.REPO, 4)
        self.assertEqual(completed['phase'], 'completed')
        transport.fail = None
        self.github.record, self.github.progress = client.record, client.progress
        self.github.issue, self.github.issues = client.issue, client.issues
        start, calls = len(transport.calls), len(self.calls)
        self.assertEqual((await self.step())['action'], 'completed')
        self.assertEqual(client.progress(legacy.REPO, 4), completed)
        self.assertEqual(client.issues(legacy.REPO), [])
        self.assertEqual(len(self.calls), calls)
        writes = [(method, path) for method, path, _ in transport.calls[start:] if method != 'GET']
        self.assertEqual(writes, [('DELETE', '/repos/example/product/issues/4/labels/hydra%3Aactive')])

    async def test_shared_completion_preserves_history_and_reopened_issue_after_rerun(self):
        await self.merged_with_empty_association()
        self.assertEqual((await self.step())['action'], 'completed')
        completed, start, calls = copy.deepcopy(self.github.note), len(self.github.writes), len(self.calls)
        observe = self.github.observe_commit
        pending = True
        def checks(repo, sha):
            value = observe(repo, sha)
            if pending:
                value['runs'][0].update(status='in_progress', conclusion=None)
                value['runs'][0]['jobs'][0].update(status='in_progress', conclusion=None)
                value['checks'][0].update(status='in_progress', conclusion=None)
            return value
        self.github.observe_commit = checks
        self.assertEqual((await self.step())['action'], 'waiting')
        self.github.work['state'] = 'open'
        pending = False
        restored = await self.step()
        self.assertEqual(restored['action'], 'waiting', restored)
        self.assertEqual(restored['reason'], 'completion_reopened')
        self.assertEqual(self.github.work['state'], 'open')
        self.assertEqual(self.github.note, completed)
        self.assertEqual(self.github.writes[start:], [])
        self.assertEqual(len(self.calls), calls)

    async def test_shared_completed_history_survives_candidate_evidence_wait(self):
        await self.merged_with_empty_association()
        self.assertEqual((await self.step())['action'], 'completed')
        completed, start, calls = copy.deepcopy(self.github.note), len(self.github.writes), len(self.calls)
        original = self.github.transform_observation
        self.github.work['state'] = 'open'
        self.github.transform_observation = lambda value: {**original(value), 'threads': [{'isResolved': False}]}
        self.assertEqual((await self.step())['reason'], 'completion_evidence_missing')
        self.assertEqual(self.github.note, completed)
        self.assertEqual(self.github.writes[start:], [])
        self.github.transform_observation = original
        replay = await self.step()
        self.assertEqual(replay['action'], 'waiting', replay)
        self.assertEqual(replay['reason'], 'completion_reopened')
        self.assertEqual(self.github.work['state'], 'open')
        self.assertEqual(self.github.note, completed)
        self.assertEqual(self.github.writes[start:], [])
        self.assertEqual(len(self.calls), calls)
