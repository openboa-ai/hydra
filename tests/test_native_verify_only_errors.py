"""Partial verification and unrecorded review recovery cannot repeat completed D."""
from pathlib import Path
import unittest
from unittest.mock import patch

import test_native_verify_only_contract as fixture


class VerificationErrorTests(unittest.IsolatedAsyncioTestCase):
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

    async def unavailable_second_command(self):
        original = self.real_git_assignment
        async def configure():
            self.gh.cfg['verification'].append({'argv': [str(Path(self.tmp.name) / 'unavailable-verifier')],
                'cwd': '.', 'timeout': 20})
            return await original()
        with patch.object(self, 'real_git_assignment', side_effect=configure):
            return await self.candidate(0)

    async def advance(self, candidate):
        return await self.controller.advance(self.url, candidate['attempt_id'],
            candidate['head'], candidate['contract_revision'])

    async def test_released_unrecorded_draft_can_retry_review_without_another_D(self):
        candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        write = self.gh.record_checkpoint
        def failed(repo, number, record):
            if record.get('native_step') is not None:
                raise OSError('synthetic failure before review record')
            return write(repo, number, record)
        with patch.object(self.gh, 'record_checkpoint', side_effect=failed):
            first = await self.call(command)
        self.assertIsNone(first['handoff'])
        self.assertNotIn('native_step', self.gh.note)
        self.assertEqual(self.lock.read_bytes(), b'')
        again = await self.call(command)
        self.assertIsNotNone(again['handoff'], 'A released unrecorded draft cannot strand the validated invocation')
        self.assertEqual(again['handoff']['assignment']['phase'], 'change_review')
        self.assertEqual(self.counter.read_text(), '1')

    async def test_partial_execution_error_settles_intent_and_blocks_all_automatic_reentry(self):
        candidate = await self.unavailable_second_command()
        command = self.verification_command(candidate)
        reply = await self.call(command)
        self.assertEqual(reply['request']['reason'], 'command_unavailable', reply)
        self.assertIsNone(reply['request']['receipt'], 'A partial invocation is not a full verification verdict')
        self.assertIsNone(self.gh.note.get('pending_action'), 'A deterministic error must settle its running intent')
        self.assertEqual(self.gh.note['phase'], 'implementation_done')
        self.assertEqual((self.gh.note['wait_reason'], self.gh.note['next_action']),
                         ('replan_required', 'diagnose_verification'))
        await self.call(command)
        fresh = self.verification_command(candidate)
        fresh['request_id'] = '77777777-7777-4777-8777-777777777777'
        await self.call(fresh)
        ordinary = await self.advance(candidate)
        self.assertEqual(ordinary['reason'], 'replan_required')
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_error_record_ack_loss_recovers_exact_source_without_new_D(self):
        candidate = await self.unavailable_second_command()
        command = self.verification_command(candidate)
        write = self.gh.record_checkpoint
        def lost(repo, number, record):
            value = write(repo, number, record)
            if record.get('next_action') == 'diagnose_verification':
                raise OSError('synthetic error-hold record ACK loss')
            return value
        with patch.object(self.gh, 'record_checkpoint', side_effect=lost):
            first = await self.call(command)
        self.assertEqual(first['request']['reason'], 'command_unavailable', first)
        again = await self.call(command)
        self.assertEqual(again['request']['reason'], 'command_unavailable', again)
        self.assertIsNone(again['request']['receipt'])
        self.assertEqual(self.counter.read_text(), '1')

    async def test_unapplied_error_hold_preserves_unknown_without_repeating_partial_D(self):
        candidate = await self.unavailable_second_command()
        command = self.verification_command(candidate)
        write = self.gh.record_checkpoint
        def failed(repo, number, record):
            if record.get('next_action') == 'diagnose_verification':
                raise OSError('synthetic failure before error-hold record')
            return write(repo, number, record)
        with patch.object(self.gh, 'record_checkpoint', side_effect=failed):
            first = await self.call(command)
        self.assertEqual(first['request']['outcome'], 'unknown', first)
        await self.call(command)
        fresh = self.verification_command(candidate)
        fresh['request_id'] = '88888888-8888-4888-8888-888888888888'
        await self.call(fresh)
        ordinary = await self.advance(candidate)
        self.assertIn(ordinary['reason'], ('verification_unconfirmed', 'replan_required'))
        self.assertEqual(self.counter.read_text(), '1', 'Unknown settlement cannot authorize a new invocation')
        self.assertEqual(self.gh.note['pending_action'], 'verification')

    async def test_restart_preserves_source_diagnosis_hold_without_a_fabricated_verdict(self):
        candidate = await self.unavailable_second_command()
        await self.call(self.verification_command(candidate))
        self.controller = self.new_controller()
        self.controller.runner.operations = self.control
        reply = await self.call(self.verification_command(candidate))
        self.assertIsNone(reply['request']['receipt'])
        ordinary = await self.advance(candidate)
        self.assertEqual(ordinary['reason'], 'replan_required')
        self.assertEqual(self.counter.read_text(), '1')
