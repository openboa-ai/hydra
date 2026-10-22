"""Exact-source P13 review regressions; real commands and independent source faults."""
from dataclasses import replace
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hydra_sdlc.control import load_host_config
from hydra_sdlc.runtime_identity import capture_runtime_identity
import test_native_verify_only_contract as fixture


class VerificationReviewFixTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_loaded_provider_identity_cannot_be_relabelled_with_current_config_digest(self):
        candidate = await self.candidate(0)
        original = self.settings.read_text()
        self.settings.write_text(original + 'storage_provider = "fixture_old:create"\n')
        self.controller.runtime_identity = capture_runtime_identity(load_host_config(self.settings), self.control)
        calls = []
        def wrap(path, argv, cwd):
            calls.append(argv)
            return argv
        self.ws.storage_provider = SimpleNamespace(wrap_command=wrap)
        self.settings.write_text(original + 'storage_provider = "fixture_new:create"\n')
        reply = await self.call(self.verification_command(candidate))
        self.assertEqual(reply['request']['reason'], 'verification_binding_mismatch', reply)
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(calls, [])
        self.assertFalse(self.counter.exists())
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_unchanged_loaded_provider_executes_actual_registered_command(self):
        candidate = await self.candidate(0)
        self.settings.write_text(self.settings.read_text() + 'storage_provider = "fixture_same:create"\n')
        self.controller.runtime_identity = capture_runtime_identity(load_host_config(self.settings), self.control)
        calls = []
        def wrap(path, argv, cwd):
            calls.append(argv)
            return argv
        self.ws.storage_provider = SimpleNamespace(wrap_command=wrap)
        reply = await self.call(self.verification_command(candidate))
        self.assertEqual(reply['request']['receipt']['verdict'], 'passed', reply)
        self.assertEqual(len(calls), 1)
        self.assertEqual(self.counter.read_text(), '1')

    async def test_unrecorded_unhanded_review_ticket_is_reconciled_without_resuming_pause(self):
        candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        intent = self.controller.runner._intent
        def pause_before_record(*args, **kwargs):
            if kwargs.get('native_phase') == 'change_review':
                self.control.set_mode('pause', 'example/product')
            return intent(*args, **kwargs)
        with patch.object(self.controller.runner, '_intent', side_effect=pause_before_record):
            reply = await self.call(command)
        self.assertIsNone(reply['handoff'])
        self.assertNotIn('native_step', self.gh.note)
        self.assertEqual(self.lock.read_bytes(), b'',
                         'A positively unhanded/unrecorded ticket must not strand the host')
        self.assertEqual(self.control.snapshot()['projects']['example/product'], 'paused')
        self.assertEqual(self.counter.read_text(), '1')

    async def test_completed_verifier_final_write_ack_loss_and_retry_do_not_run_D_twice(self):
        candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        write = self.gh.record_checkpoint
        def lost(repo, number, record):
            write(repo, number, record)
            if record.get('phase') == 'implementation_done' and record.get('next_action') == 'change_review':
                raise OSError('synthetic final verification write ACK loss')
        with patch.object(self.gh, 'record_checkpoint', side_effect=lost):
            first = await self.call(command)
        self.assertIn(first['request']['outcome'], ('waiting', 'unknown'))
        second = await self.call(command)
        self.assertEqual(self.counter.read_text(), '1',
                         'Reconcile the exact completed invocation instead of rerunning a stateful verifier')
        self.assertEqual(second['request']['receipt']['verdict'], 'passed', second)
        fresh = self.verification_command(candidate)
        fresh['request_id'] = '55555555-5555-4555-8555-555555555555'
        third = await self.call(fresh)
        self.assertEqual(third['request']['receipt']['verdict'], 'passed', third)
        self.assertEqual(self.counter.read_text(), '2', 'An explicit new command must actually run D')

    async def test_foreign_same_pin_progress_cannot_be_its_own_readback_proof(self):
        candidate = await self.candidate(0)
        write = self.gh.record_checkpoint
        def foreign(repo, number, record):
            write(repo, number, record)
            if record.get('phase') == 'implementation_done' and record.get('next_action') == 'change_review':
                self.gh.note.update(next_action='operator_decision', wait_reason='product_decision')
        with patch.object(self.gh, 'record_checkpoint', side_effect=foreign):
            reply = await self.call(self.verification_command(candidate))
        self.assertIsNone(reply['request']['receipt'],
                         'Same candidate pins cannot certify a foreign phase or decision record')
        self.assertIn(reply['request']['outcome'], ('unknown', 'waiting'))
        self.assertEqual(self.gh.note['next_action'], 'operator_decision')
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_retirement_write_ack_loss_reads_back_original_effect_before_release(self):
        candidate, assignment = await self.review()
        write = self.gh.record_checkpoint
        def lost(repo, number, record):
            write(repo, number, record)
            if 'native_step' not in record:
                raise OSError('synthetic retirement write ACK loss')
        command = self.finish_command(candidate, assignment)
        with patch.object(self.gh, 'record_checkpoint', side_effect=lost):
            reply = await self.call(command)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(reply['request']['receipt']['review'], 'accepted')
        self.assertEqual(self.lock.read_bytes(), b'')
        replay = await self.call(command)
        self.assertEqual(replay['request']['outcome'], 'unknown', replay)
        self.assertIsNone(replay['request']['receipt'])
        self.assertEqual(self.counter.read_text(), '1')

    async def test_retirement_failure_before_write_preserves_original_step_then_can_recover(self):
        candidate, assignment = await self.review()
        write = self.gh.record_checkpoint
        def failed(repo, number, record):
            if 'native_step' not in record:
                raise OSError('synthetic failure before retirement write')
            return write(repo, number, record)
        command = self.finish_command(candidate, assignment)
        ticket = self.lock.read_bytes()
        with patch.object(self.gh, 'record_checkpoint', side_effect=failed):
            first = await self.call(command)
        self.assertEqual(first['request']['outcome'], 'unknown', first)
        self.assertEqual(self.lock.read_bytes(), ticket)
        self.assertEqual(self.gh.note['native_step'], assignment['step_id'])
        second = await self.call(command)
        self.assertEqual(second['request']['receipt']['review'], 'accepted', second)
        self.assertEqual(self.lock.read_bytes(), b'')
        self.assertEqual(self.counter.read_text(), '1')
