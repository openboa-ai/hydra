"""P14: persist an authenticated squash receipt before testing completion."""
import copy
import unittest
from unittest.mock import patch

import test_delivery_observation_recovery as fixture


class SquashRecoveryReviewTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.ExternalClosureReviewTests.asyncSetUp
    new_controller = fixture.ExternalClosureReviewTests.new_controller
    result = fixture.ExternalClosureReviewTests.result
    command = fixture.ExternalClosureReviewTests.command
    checkpoint = fixture.ExternalClosureReviewTests.checkpoint
    real_git_assignment = fixture.ExternalClosureReviewTests.real_git_assignment
    candidate = fixture.ExternalClosureReviewTests.candidate
    verification_command = fixture.ExternalClosureReviewTests.verification_command
    verification_grant = fixture.ExternalClosureReviewTests.verification_grant
    call = fixture.ExternalClosureReviewTests.call
    finish_command = fixture.ExternalClosureReviewTests.finish_command
    reviewed = fixture.ExternalClosureReviewTests.reviewed
    publication_command = fixture.ExternalClosureReviewTests.publication_command
    publication_grant = fixture.ExternalClosureReviewTests.publication_grant
    publish = fixture.ExternalClosureReviewTests.publish
    published = fixture.ExternalClosureReviewTests.published
    delivery_command = fixture.ExternalClosureReviewTests.delivery_command
    delivery_grant = fixture.ExternalClosureReviewTests.delivery_grant
    deliver = fixture.ExternalClosureReviewTests.deliver
    effects = fixture.ExternalClosureReviewTests.effects
    unchanged_candidate = fixture.ExternalClosureReviewTests.unchanged_candidate

    async def late_merge(self, *, restart=False):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        original = self.gh.merge
        attempts = []
        def uncertain(*args, **kwargs):
            attempts.append((args, kwargs))
            if len(attempts) > 1:
                raise AssertionError('An uncertain merge must not be retransmitted')
            raise RuntimeError('Synthetic lost merge result')
        self.gh.merge = uncertain
        start = len(self.gh.writes)
        waiting = await self.deliver(command)
        self.assertIn(waiting['request']['outcome'], {'waiting', 'unknown'}, waiting)
        self.assertEqual(self.gh.note['pending_action'], 'merge')
        self.assertFalse(self.gh.pr['merged'])
        self.assertEqual(len(attempts), 1)
        self.gh.merge = original
        original(*attempts[0][0], **attempts[0][1])
        self.gh.work['state'] = 'closed'
        if restart:
            self.controller = self.new_controller()
            self.controller.runner.operations = self.control
        return candidate, command, attempts, start

    def failed_main(self):
        original = self.gh.observe_commit
        def failed(repo, sha):
            value = original(repo, sha)
            value['runs'][0].update(status='completed', conclusion='failure')
            value['runs'][0]['jobs'][0].update(status='completed', conclusion='failure')
            value['checks'][0].update(status='completed', conclusion='failure')
            return value
        self.gh.observe_commit = failed

    async def recovered(self, *, restart):
        candidate, command, attempts, start = await self.late_merge(restart=restart)
        completed = await self.deliver(command)
        self.assertEqual(completed['request']['outcome'], 'applied', completed)
        self.assertEqual(self.gh.note['checkpoint'], 'squash_' + self.gh.pr['merge_commit_sha'])
        self.assertEqual((self.gh.note['phase'], self.gh.note['pending_action']), ('completed', None))
        self.assertEqual(self.effects(start), [('merge', candidate['head'])])
        self.assertEqual(len(attempts), 1)
        replay = await self.deliver(command)
        self.assertEqual(replay['request']['outcome'], 'applied', replay)
        self.assertEqual(self.effects(start), [('merge', candidate['head'])])
        self.unchanged_candidate(candidate)

    async def test_late_merge_and_external_close_recover_in_the_same_owner(self):
        await self.recovered(restart=False)

    async def test_late_merge_and_external_close_recover_after_restart(self):
        await self.recovered(restart=True)

    async def test_squash_receipt_is_retained_while_main_checks_fail(self):
        candidate, command, attempts, start = await self.late_merge(restart=True)
        self.failed_main()
        waiting = await self.deliver(command)
        self.assertEqual(waiting['request']['outcome'], 'waiting', waiting)
        self.assertEqual(waiting['request']['reason'], 'post_merge_failed')
        self.assertEqual(self.gh.note['checkpoint'], 'squash_' + self.gh.pr['merge_commit_sha'])
        self.assertEqual((self.gh.note['phase'], self.gh.note['pending_action']), ('observing', None))
        self.assertEqual(waiting['request']['receipt']['post_merge'], 'failed')
        self.assertEqual(self.effects(start), [('merge', candidate['head'])])
        self.assertEqual(len(attempts), 1)
        self.unchanged_candidate(candidate)

    async def test_wrong_squash_correlation_cannot_create_a_checkpoint(self):
        candidate, command, attempts, start = await self.late_merge()
        pending = copy.deepcopy(self.gh.note)
        original = self.gh.transform_observation
        def invalid(value):
            value = original(value)
            value['merge_commit']['message'] = 'An unrelated merge result'
            return value
        writer = self.controller.runner._record
        for after_validation in (False, True):
            with self.subTest(after_validation=after_validation):
                self.gh.transform_observation = original if after_validation else invalid
                def changed(repo, number, record, **values):
                    if after_validation and str(values.get('checkpoint', '')).startswith('squash_'):
                        self.gh.transform_observation = invalid
                    return writer(repo, number, record, **values)
                with patch.object(self.controller.runner, '_record', side_effect=changed):
                    waiting = await self.deliver(command)
                self.assertIn(waiting['request']['outcome'], {'waiting', 'unknown'}, waiting)
                self.assertEqual(self.gh.note, pending)
                self.assertEqual(self.effects(start), [('merge', candidate['head'])])
        self.assertEqual(len(attempts), 1)
        self.unchanged_candidate(candidate)

    async def test_acknowledged_merge_and_external_close_record_the_same_receipt(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        original = self.gh.merge
        def closed(*args, **kwargs):
            value = original(*args, **kwargs)
            self.gh.work['state'] = 'closed'
            return value
        self.gh.merge = closed
        start = len(self.gh.writes)
        completed = await self.deliver(command)
        self.assertEqual(completed['request']['outcome'], 'applied', completed)
        self.assertEqual(self.gh.note['checkpoint'], 'squash_' + self.gh.pr['merge_commit_sha'])
        self.assertEqual((self.gh.note['phase'], self.gh.note['pending_action']), ('completed', None))
        self.assertEqual(self.effects(start), [('merge', candidate['head'])])
        self.unchanged_candidate(candidate)

    async def test_unrelated_record_changes_cannot_borrow_squash_evidence(self):
        candidate, command, attempts, start = await self.late_merge()
        self.failed_main()
        pending = copy.deepcopy(self.gh.note)
        original = self.controller.runner._record
        for field, replacement in [('phase', 'completed'),
                                   ('attempt_id', '33333333-3333-4333-8333-333333333333'),
                                   ('head', 'f' * 40)]:
            with self.subTest(field=field):
                def corrupt(repo, number, record, **values):
                    if str(values.get('checkpoint', '')).startswith('squash_'):
                        values[field] = replacement
                    return original(repo, number, record, **values)
                with patch.object(self.controller.runner, '_record', side_effect=corrupt):
                    waiting = await self.deliver(command)
                self.assertIn(waiting['request']['outcome'], {'waiting', 'unknown'}, waiting)
                self.assertEqual(self.gh.note, pending)
                self.assertEqual(self.effects(start), [('merge', candidate['head'])])
        self.assertEqual(len(attempts), 1)
        self.unchanged_candidate(candidate)
