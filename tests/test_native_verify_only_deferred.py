"""Completed-run recovery and actual private diagnosis for deferred correction."""
import json
import unittest
from unittest.mock import patch

import test_native_verify_only_contract as fixture
from test_workspace import git


class DeferredVerificationTests(unittest.IsolatedAsyncioTestCase):
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

    async def mutated_candidate(self):
        original = self.real_git_assignment
        async def configure():
            argv = self.gh.cfg['verification'][0]['argv']
            argv[2] = argv[2].replace('print(', 'Path("src/main.py").write_text("verifier_edit = True\\n"); print(')
            return await original()
        with patch.object(self, 'real_git_assignment', side_effect=configure):
            return await self.candidate(0)

    async def advance(self, candidate):
        return await self.controller.advance(self.url, candidate['attempt_id'],
            candidate['head'], candidate['contract_revision'])

    async def test_mutation_record_ack_loss_and_replay_recover_original_changed_candidate(self):
        candidate = await self.mutated_candidate()
        command = self.verification_command(candidate)
        write = self.gh.record_checkpoint
        def lost(repo, number, record):
            value = write(repo, number, record)
            if record.get('wait_reason') == 'candidate_changed':
                raise OSError('synthetic changed-candidate record ACK loss')
            return value
        with patch.object(self.gh, 'record_checkpoint', side_effect=lost):
            reply = await self.call(command)
        self.assertEqual(reply['request']['reason'], 'candidate_changed', reply)
        self.assertIsNone(reply['request']['receipt'])
        self.assertTrue(any(value['resource']['kind'] == 'progress' for value in reply['observations']))
        head = git(self.path, 'rev-parse', 'HEAD')
        self.assertEqual(self.gh.note['head'], head)
        again = await self.call(command)
        self.assertEqual(again['request']['reason'], 'candidate_changed', again)
        self.assertIsNone(again['request']['receipt'])
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(git(self.path, 'rev-parse', 'HEAD'), head)
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_changed_candidate_unapplied_record_stays_unknown_without_reexecuting(self):
        candidate = await self.mutated_candidate()
        command = self.verification_command(candidate)
        write = self.gh.record_checkpoint
        def failed(repo, number, record):
            if record.get('wait_reason') == 'candidate_changed':
                raise OSError('synthetic failure before changed-candidate write')
            return write(repo, number, record)
        with patch.object(self.gh, 'record_checkpoint', side_effect=failed):
            first = await self.call(command)
        self.assertIsNone(first['request']['receipt'])
        self.assertEqual(first['request']['outcome'], 'unknown')
        head = git(self.path, 'rev-parse', 'HEAD')
        again = await self.call(command)
        self.assertIsNone(again['request']['receipt'])
        self.assertEqual(again['request']['outcome'], 'unknown')
        self.assertNotEqual(self.gh.note['head'], head)
        self.assertEqual(git(self.path, 'rev-parse', 'HEAD'), head)
        self.assertEqual(self.counter.read_text(), '1')

    async def test_failed_review_actual_findings_reach_only_private_correction_assignment(self):
        candidate, assignment = await self.review()
        command = self.finish_command(candidate, assignment, 'failed')
        marker = 'SYNTHETIC_PRIVATE_FIX_THE_BOUNDARY_FINDING'
        command['parameters']['summary'] = marker
        reply = await self.call(command)
        self.assertEqual(reply['request']['receipt']['review'], 'failed')
        correction = await self.advance(candidate)
        self.assertEqual(correction.get('phase'), 'correction', correction)
        self.assertIn(marker, correction['prompt'])
        self.assertNotIn(marker, json.dumps(self.gh.note))
        self.assertNotIn(marker, json.dumps(reply))
        self.assertEqual(self.counter.read_text(), '1')

    async def test_failed_D_resumes_diagnosis_with_original_private_output_without_new_D(self):
        candidate = await self.candidate(7)
        reply = await self.call(self.verification_command(candidate))
        self.assertEqual(reply['request']['receipt']['verdict'], 'failed')
        correction = await self.advance(candidate)
        self.assertEqual(correction.get('phase'), 'correction', correction)
        self.assertIn('SYNTHETIC_PRIVATE_VERIFY_ONLY_OUTPUT', correction['prompt'])
        self.assertNotIn('SYNTHETIC_PRIVATE_VERIFY_ONLY_OUTPUT', json.dumps(self.gh.note))
        self.assertEqual(self.counter.read_text(), '1')

    async def test_pre_registration_wait_recovers_same_D_after_condition_is_resolved(self):
        candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        with patch.object(self.controller.runner, '_operator_context', return_value=None):
            first = await self.call(command)
            second = await self.call(command)
        self.assertEqual(first['request']['reason'], 'decision_context_missing', first)
        self.assertEqual(second['request']['reason'], 'decision_context_missing', second)
        self.assertIsNone(first['handoff'])
        self.assertEqual(first['request']['receipt']['verdict'], 'passed')
        self.assertEqual(self.lock.read_bytes(), b'')
        ready = await self.call(command)
        self.assertIsNotNone(ready['handoff'], ready)
        self.assertEqual(ready['handoff']['assignment']['phase'], 'change_review')
        self.assertEqual(self.counter.read_text(), '1')

    async def test_pre_registration_wait_recovery_still_requires_current_grants(self):
        candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        with patch.object(self.controller.runner, '_operator_context', return_value=None):
            await self.call(command)
        rejected = await self.call(command, self.verification_grant('admission_set'))
        self.assertIsNone(rejected['handoff'])
        self.assertEqual(self.lock.read_bytes(), b'')
        self.assertEqual(self.counter.read_text(), '1')
        ready = await self.call(command)
        self.assertIsNotNone(ready['handoff'], ready)
        self.assertEqual(self.counter.read_text(), '1')

    async def test_failed_review_record_ack_loss_does_not_charge_same_failure_twice(self):
        candidate, assignment = await self.review()
        command = self.finish_command(candidate, assignment, 'failed')
        write = self.gh.record_checkpoint
        def lost(repo, number, record):
            value = write(repo, number, record)
            if record.get('native_outcome') == 'failed':
                raise OSError('synthetic failed-review ACK loss')
            return value
        with patch.object(self.gh, 'record_checkpoint', side_effect=lost):
            await self.call(command)
        again = await self.call(command)
        self.assertEqual(again['request']['receipt']['review'], 'failed', again)
        self.assertEqual(self.gh.note['correction_attempt'], 1)
        self.assertEqual(self.counter.read_text(), '1')

    async def test_failed_D_same_request_preserves_debt_and_fresh_failure_consumes_budget(self):
        candidate = await self.candidate(7)
        command = self.verification_command(candidate)
        await self.call(command)
        await self.call(command)
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.gh.note.get('correction_attempt'), 1)
        fresh = self.verification_command(candidate)
        fresh['request_id'] = '66666666-6666-4666-8666-666666666666'
        await self.call(fresh)
        self.assertEqual(self.counter.read_text(), '2')
        self.assertEqual(self.gh.note['correction_attempt'], 2)
