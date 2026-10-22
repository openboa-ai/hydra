"""P13/CP: actual candidate, invocation and bounded review completion oracles."""
import copy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from hydra_sdlc import native
from hydra_sdlc.control_commands import (AdmissionCallContext, InvalidAdmissionCommand,
    execute_command_v1, parse_command_v1)
import test_native_verify_only as run_fixture


class VerificationContractTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = run_fixture.VerificationRunTests.asyncSetUp
    new_controller = run_fixture.VerificationRunTests.new_controller
    result = run_fixture.VerificationRunTests.result
    command = run_fixture.VerificationRunTests.command
    checkpoint = run_fixture.VerificationRunTests.checkpoint
    real_git_assignment = run_fixture.VerificationRunTests.real_git_assignment
    candidate = run_fixture.VerificationRunTests.candidate
    verification_command = run_fixture.VerificationRunTests.verification_command

    def verification_grant(self, *operations):
        return AdmissionCallContext('native', None, frozenset({self.gh.cfg['repository_id']}),
            frozenset(operations or ('workflow_step.verify_only.run',
                'workflow_step.verify_only.review_checkpoint', 'command_reply.native_handoff_v1')))

    async def call(self, command, grant=None, context_provider=None):
        with patch.object(self.controller, 'advance', side_effect=AssertionError('broad continuation')), \
             patch.object(self.controller, '_checkpoint', side_effect=AssertionError('legacy checkpoint')), \
             patch.object(self.controller.runner, 'step', side_effect=AssertionError('broad step')), \
             patch.object(self.controller.runner, '_correct', side_effect=AssertionError('correction')):
            return await execute_command_v1(self.settings, command,
                context_provider=context_provider or (lambda: grant or self.verification_grant()),
                github=self.gh, controller=self.controller)

    async def review(self):
        candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        before = len(self.gh.writes)
        reply = await self.call(command)
        self.assertEqual(reply.get('reply_profile'), 'native_handoff_v1', reply)
        self.assertIsNotNone(reply.get('handoff'), 'Qualified review must return its actual assignment')
        assignment = reply['handoff']['assignment']
        self.assertEqual((assignment['mode'], assignment['phase']), ('read_only', 'change_review'))
        self.assertTrue(all(assignment[k] == candidate[k] for k in candidate))
        self.assertEqual(self.counter.read_text(), '1')
        self.assertIn(assignment['step_id'].encode(), self.lock.read_bytes())
        self.assertTrue(all(row[0] == 'record' for row in self.gh.writes[before:]))
        self.assertEqual(reply['request']['receipt']['review'], 'pending')
        return candidate, assignment

    def finish_command(self, candidate, assignment, outcome='candidate_ready'):
        command = self.verification_command(candidate)
        command['expected']['assignment'] = {k: assignment[k] for k in (
            'attempt_id', 'step_id', 'head', 'contract_revision', 'spec_revision')}
        command['effect_key'] = f"checkpoint:{assignment['attempt_id']}:{assignment['step_id']}"
        command['parameters'].update(stage='review_checkpoint', outcome=outcome,
            summary='SYNTHETIC_PRIVATE_REVIEW_SUMMARY', reply_profile='native_handoff_v1')
        return command

    async def test_exact_run_review_finishes_before_exact_ticket_release(self):
        candidate, assignment = await self.review()
        confirm = native.confirm_native_assignment
        def release(step):
            self.assertEqual(step, assignment['step_id'])
            self.assertEqual(self.gh.note['phase'], 'change_review_done')
            self.assertEqual(self.gh.note['checkpoint'], 'locally_verified')
            self.assertNotIn('native_step', self.gh.note)
            return confirm(step)
        with patch.object(native, 'confirm_native_assignment', side_effect=release):
            reply = await self.call(self.finish_command(candidate, assignment))
        receipt = reply['request']['receipt']
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(receipt['kind'], 'verification_review')
        self.assertEqual(receipt['review'], 'accepted')
        self.assertTrue(receipt['step_retired'] and receipt['ticket_released'])
        self.assertEqual(self.lock.read_bytes(), b'')
        self.assertEqual(self.counter.read_text(), '1')
        self.assertIsNone(reply['handoff'])
        self.assertNotIn('SYNTHETIC_PRIVATE_REVIEW_SUMMARY', json.dumps(reply))
        self.assertNotIn('SYNTHETIC_PRIVATE_VERIFY_ONLY_OUTPUT', json.dumps(self.gh.note))

    async def test_restart_preserves_finished_judgment_without_acceptance_or_new_run(self):
        candidate, assignment = await self.review()
        self.controller = self.new_controller()
        self.controller.runner.operations = self.control
        reply = await self.call(self.finish_command(candidate, assignment))
        self.assertEqual(reply['request']['receipt']['review'], 'pending', reply)
        self.assertEqual(self.gh.note['wait_reason'], 'verification_evidence_unknown')
        self.assertEqual(self.gh.note['next_action'], 'verification')
        self.assertEqual(self.lock.read_bytes(), b'')
        self.assertEqual(self.counter.read_text(), '1')
        self.assertIsNone(reply['handoff'])

    async def test_failed_judgment_stops_at_review_diagnosis_even_without_proof(self):
        candidate, assignment = await self.review()
        self.controller.runner.pending_verifications.clear()
        reply = await self.call(self.finish_command(candidate, assignment, 'failed'))
        self.assertEqual(reply['request']['receipt']['review'], 'failed', reply)
        self.assertEqual(self.gh.note['phase'], 'change_review_done')
        self.assertEqual((self.gh.note['wait_reason'], self.gh.note['next_action']),
                         ('review_findings', 'diagnose_review'))
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_product_decision_is_not_hidden_by_lost_verification_proof(self):
        candidate, assignment = await self.review()
        self.controller.runner.pending_verifications.clear()
        reply = await self.call(self.finish_command(candidate, assignment, 'needs_decision'))
        self.assertEqual(reply['request']['receipt']['review'], 'pending', reply)
        self.assertEqual((self.gh.note['resume_phase'], self.gh.note['wait_reason'], self.gh.note['next_action']),
                         ('change_review', 'product_decision', 'operator_decision'))
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_same_key_and_content_without_actual_run_link_cannot_accept(self):
        candidate, assignment = await self.review()
        runner = self.controller.runner
        key = next(iter(runner.pending_verifications))
        runner.pending_verifications[key] = copy.deepcopy(runner.pending_verifications[key])
        reply = await self.call(self.finish_command(candidate, assignment))
        self.assertEqual(reply['request']['receipt']['review'], 'pending', reply)
        self.assertEqual(self.gh.note['wait_reason'], 'verification_evidence_unknown')
        self.assertEqual(self.counter.read_text(), '1')

    async def test_private_result_or_output_mutation_invalidates_review_proof(self):
        candidate, assignment = await self.review()
        runner = self.controller.runner
        key = next(iter(runner.pending_verifications))
        runner.pending_verifications[key][0]['exit_code'] = 17
        reply = await self.call(self.finish_command(candidate, assignment))
        self.assertEqual(reply['request']['receipt']['review'], 'pending', reply)
        self.assertEqual(self.gh.note['wait_reason'], 'verification_evidence_unknown')

    async def test_dirty_review_completion_keeps_original_ticket_and_edits(self):
        candidate, assignment = await self.review()
        (self.path / 'src/main.py').write_text('unreviewed = True\n')
        ticket = self.lock.read_bytes()
        reply = await self.call(self.finish_command(candidate, assignment))
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(self.lock.read_bytes(), ticket)
        self.assertEqual(self.gh.note['native_step'], assignment['step_id'])
        self.assertEqual((self.path / 'src/main.py').read_text(), 'unreviewed = True\n')
        self.assertEqual(self.counter.read_text(), '1')

    async def test_stale_candidate_rejects_before_registered_subprocess(self):
        candidate = await self.candidate(0)
        for key, wrong in [('attempt_id', '33333333-3333-4333-8333-333333333333'),
                           ('head', 'f' * 40), ('contract_revision', 'e' * 40)]:
            with self.subTest(key=key):
                reply = await self.call(self.verification_command({**candidate, key: wrong}))
                self.assertEqual(reply['request']['reason'], 'stale_candidate', reply)
                self.assertIsNone(reply['request']['receipt'])
                self.assertFalse(self.counter.exists())
                self.assertEqual(self.lock.read_bytes(), b'')

    async def test_native_profile_requires_completion_and_private_handoff_grants_before_ticket(self):
        candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        reply = await self.call(command, self.verification_grant('workflow_step.verify_only.run'))
        self.assertEqual(reply.get('reply_profile'), 'native_handoff_v1', reply)
        self.assertIsNone(reply['handoff'])
        self.assertEqual(reply['request']['receipt']['verdict'], 'passed')
        self.assertEqual(self.lock.read_bytes(), b'')
        self.assertNotIn('native_step', self.gh.note)

    async def test_admission_only_grant_and_bridge_profile_never_dispatch(self):
        candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        reply = await self.call(command, self.verification_grant('admission_set'))
        self.assertEqual(reply['request']['reason'], 'authority_denied', reply)
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        command['binding_epoch'] = '44444444-4444-4444-8444-444444444444'
        grant = replace(self.verification_grant(), surface='bridge', binding_epoch=command['binding_epoch'])
        reply = await self.call(command, grant)
        self.assertEqual(reply['request']['reason'], 'unsupported_reply_profile', reply)
        self.assertFalse(self.counter.exists())
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_pause_and_config_bound_grant_drift_hold_before_dispatch(self):
        candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        stale = replace(self.verification_grant(), config_digest='f' * 64)
        reply = await self.call(command, stale)
        self.assertEqual(reply['request']['reason'], 'stale_runtime', reply)
        self.control.set_mode('pause', 'example/product')
        command = self.verification_command(candidate)
        reply = await self.call(command)
        self.assertIn(reply['request']['reason'], ('project_paused', 'paused'))
        self.assertFalse(self.counter.exists())
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_final_record_ack_loss_reconciles_without_second_run(self):
        candidate, assignment = await self.review()
        command = self.finish_command(candidate, assignment)
        write = self.gh.record_checkpoint
        def lost(repo, number, record):
            write(repo, number, record)
            if record.get('phase') == 'change_review_done':
                raise OSError('synthetic private ACK loss')
        with patch.object(self.gh, 'record_checkpoint', side_effect=lost):
            first = await self.call(command)
        self.assertEqual(first['request']['outcome'], 'unknown', first)
        self.assertIn(assignment['step_id'].encode(), self.lock.read_bytes())
        second = await self.call(command)
        self.assertEqual(second['request']['receipt']['review'], 'accepted', second)
        replay = await self.call(command)
        self.assertEqual(replay['request']['outcome'], 'unknown', replay)
        self.assertIsNone(replay['request']['receipt'])
        self.assertEqual(self.lock.read_bytes(), b'')
        self.assertEqual(self.counter.read_text(), '1')


class VerificationSchemaTests(unittest.TestCase):
    def command(self):
        return {'command_schema': 1, 'request_id': '22222222-2222-4222-8222-222222222222',
            'binding_epoch': None, 'action': 'workflow_step',
            'target': {'repository_id': 42, 'issue_number': 4},
            'expected': {'runtime_key': 'pinned', 'admission_revision': 1,
                         'source_checks': [], 'assignment': None}, 'effect_key': None,
            'parameters': {'operation': 'verify_only', 'stage': 'run', 'reply_profile': 'standard_v1',
                'candidate': {'attempt_id': '33333333-3333-4333-8333-333333333333',
                              'head': 'a' * 40, 'contract_revision': 'b' * 40}}}

    def test_closed_verify_variants_reject_malformed_before_dependencies(self):
        edits = [('stage', 'future'), ('candidate', {}), ('candidate', {'head': 'a' * 40}),
                 ('reply_profile', 'future'), ('summary', 'unexpected'), ('outcome', 'stopped')]
        for field, value in edits:
            command = self.command()
            command['parameters'][field] = value
            with self.subTest(field=field), self.assertRaises(InvalidAdmissionCommand):
                parse_command_v1(command)
        self.assertEqual(parse_command_v1(self.command()), self.command())
