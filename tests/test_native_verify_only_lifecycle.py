"""A bounded review must hand its actual result to the existing lifecycle."""
import copy
import unittest
from unittest.mock import AsyncMock, patch

import test_native_verify_only_contract as fixture


class VerificationLifecycleTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.VerificationContractTests.asyncSetUp
    new_controller = fixture.VerificationContractTests.new_controller
    result = fixture.VerificationContractTests.result
    command = fixture.VerificationContractTests.command
    checkpoint = fixture.VerificationContractTests.checkpoint
    real_git_assignment = fixture.VerificationContractTests.real_git_assignment
    candidate = fixture.VerificationContractTests.candidate
    verification_command = fixture.VerificationContractTests.verification_command
    verification_grant = fixture.VerificationContractTests.verification_grant
    call = fixture.VerificationContractTests.call
    review = fixture.VerificationContractTests.review
    finish_command = fixture.VerificationContractTests.finish_command

    async def advance(self, candidate):
        return await self.controller.advance(self.url, candidate['attempt_id'],
            candidate['head'], candidate['contract_revision'])

    async def test_accepted_review_reaches_next_delivery_boundary_without_new_D_or_review(self):
        candidate, assignment = await self.review()
        completed = await self.call(self.finish_command(candidate, assignment))
        self.assertEqual(completed['request']['receipt']['review'], 'accepted')
        runner = self.controller.runner
        review = AsyncMock(return_value=(None, {'action': 'waiting', 'reason': 'unexpected_review'}))
        with patch.object(runner, '_model', review), patch.object(runner, '_publish',
                return_value={'action': 'waiting', 'reason': 'observed_delivery_boundary'}) as publish:
            reply = await self.advance(candidate)
        self.assertEqual(self.counter.read_text(), '1', 'Accepted D must reach ordinary delivery without rerunning')
        self.assertEqual(review.await_count, 0)
        self.assertEqual(publish.call_count, 1)
        self.assertEqual(reply['reason'], 'observed_delivery_boundary')

    async def test_failed_review_next_invocation_resumes_correction_without_new_D(self):
        candidate, assignment = await self.review()
        completed = await self.call(self.finish_command(candidate, assignment, 'failed'))
        self.assertEqual(completed['request']['receipt']['review'], 'failed')
        runner = self.controller.runner
        correction = AsyncMock(return_value={'action': 'waiting', 'reason': 'observed_correction_boundary'})
        review = AsyncMock(return_value=(None, {'action': 'waiting', 'reason': 'unexpected_review'}))
        with patch.object(runner, '_correct', correction), patch.object(runner, '_model', review):
            reply = await self.advance(candidate)
        self.assertEqual(correction.await_count, 1, 'The next invocation must consume review correction debt')
        self.assertEqual(correction.await_args.args[5], 'review_findings')
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(review.await_count, 0)
        self.assertEqual(reply['reason'], 'observed_correction_boundary')

    async def test_another_failed_review_consumes_existing_correction_budget(self):
        candidate, assignment = await self.review()
        self.gh.note.update(correction_reason='review_findings', correction_attempt=2)
        await self.call(self.finish_command(candidate, assignment, 'failed'))
        self.assertEqual(self.gh.note['resume_phase'], 'correction')
        self.assertEqual(self.gh.note['correction_reason'], 'review_findings')
        self.assertEqual(self.gh.note['correction_attempt'], 3, 'A new failed review cannot reset retry debt')
        reply = await self.advance(candidate)
        self.assertEqual(reply['reason'], 'replan_required')
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_lost_actual_invocation_never_adds_accepted_candidate_marker(self):
        candidate, assignment = await self.review()
        runner = self.controller.runner
        runner.pending_verifications.clear()
        reply = await self.call(self.finish_command(candidate, assignment))
        self.assertEqual(reply['request']['receipt']['review'], 'pending')
        self.assertNotIn(('example/product', 4, candidate['head'], self.gh.cfg['blob_sha']), runner.verified_heads)
        self.assertEqual(self.counter.read_text(), '1')

    async def test_recorded_never_delivered_review_retires_under_remaining_workflow_grant(self):
        candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        revoked = False
        write = self.gh.record_checkpoint
        def recording(repo, number, record):
            nonlocal revoked
            value = write(repo, number, record)
            if record.get('native_step') is not None:
                revoked = True
            return value
        def current():
            return self.verification_grant('workflow_step.verify_only.run') if revoked else self.verification_grant()
        with patch.object(self.gh, 'record_checkpoint', side_effect=recording):
            reply = await self.call(command, context_provider=current)
        self.assertTrue(revoked)
        self.assertIsNone(reply['handoff'])
        self.assertEqual(self.lock.read_bytes(), b'', 'A qualified never-delivered ticket must not strand the host')
        self.assertNotIn('native_step', self.gh.note)
        again = await self.call(command, context_provider=current)
        self.assertIsNone(again['handoff'])
        self.assertEqual(self.counter.read_text(), '1')

    async def test_lost_handoff_grant_on_retry_cannot_retire_previously_delivered_assignment(self):
        candidate, assignment = await self.review()
        command = self.verification_command(candidate)
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        ticket, record = self.lock.read_bytes(), copy.deepcopy(self.gh.note)
        reply = await self.call(command, self.verification_grant('workflow_step.verify_only.run'))
        self.assertIsNone(reply['handoff'])
        self.assertEqual(self.lock.read_bytes(), ticket)
        self.assertEqual(self.gh.note, record)
        self.assertEqual(self.gh.note['native_step'], assignment['step_id'])
        self.assertEqual(self.counter.read_text(), '1')

    async def test_foreign_record_after_registration_never_authorizes_ticket_cleanup(self):
        candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        revoked = False
        write = self.gh.record_checkpoint
        def recording(repo, number, record):
            nonlocal revoked
            value = write(repo, number, record)
            if record.get('native_step') is not None:
                revoked = True
                self.gh.note.update(wait_reason='product_decision', next_action='operator_decision')
            return value
        def current():
            return self.verification_grant('workflow_step.verify_only.run') if revoked else self.verification_grant()
        with patch.object(self.gh, 'record_checkpoint', side_effect=recording):
            reply = await self.call(command, context_provider=current)
        self.assertIsNone(reply['handoff'])
        self.assertTrue(self.lock.read_bytes())
        self.assertIn('native_step', self.gh.note)
        self.assertEqual(self.gh.note['next_action'], 'operator_decision')
        self.assertEqual(self.counter.read_text(), '1')
