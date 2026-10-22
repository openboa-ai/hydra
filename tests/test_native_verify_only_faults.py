"""P13 failure, SDK and effect-ceiling cases independent of the happy-path oracle."""
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from hydra_sdlc import native
from hydra_sdlc.control_commands import (InvalidAdmissionCommand, execute_command_v1,
    parse_command_v1)
from hydra_sdlc.mcp import create_server
from hydra_sdlc.operations import OperationDenied
import test_native_verify_only_contract as fixture


class VerificationFaultTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_registered_mutation_checkpoints_once_without_refreshing_candidate(self):
        original = self.real_git_assignment
        async def configure():
            argv = self.gh.cfg['verification'][0]['argv']
            argv[2] = argv[2].replace('print(', 'Path("src/main.py").write_text("verifier_edit = True\\n"); print(')
            return await original()
        with patch.object(self, 'real_git_assignment', side_effect=configure):
            candidate = await self.candidate(0)
        reply = await self.call(self.verification_command(candidate))
        self.assertEqual(reply['request']['reason'], 'candidate_changed', reply)
        self.assertIsNone(reply['request']['receipt'])
        self.assertNotEqual(self.gh.note['head'], candidate['head'])
        self.assertEqual((self.path / 'src/main.py').read_text(), 'verifier_edit = True\n')
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_current_authority_is_rechecked_before_second_registered_command(self):
        original = self.real_git_assignment
        async def configure():
            self.gh.cfg['verification'] *= 2
            return await original()
        with patch.object(self, 'real_git_assignment', side_effect=configure):
            candidate = await self.candidate(0)
        def current():
            return self.verification_grant('admission_set') if self.counter.exists() else self.verification_grant()
        reply = await self.call(self.verification_command(candidate), context_provider=current)
        self.assertIsNone(reply['request']['receipt'])
        self.assertIn(reply['request']['outcome'], ('waiting', 'unknown'))
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_effect_ceiling_blocks_delivery_intent_workspace_and_provider_writes(self):
        candidate = await self.candidate(0)
        runner, verify = self.controller.runner, self.ws.verify
        blocked = []
        def guarded(*args, **kwargs):
            effects = [lambda: runner._intent('example/product', 4, self.gh.cfg, self.gh.note, 'publish'),
                lambda: runner._workspace_effect('example/product', 'publish', self.path, 'hydra/issue-4', None),
                lambda: runner._effect('example/product', lambda: self.fail('foreign provider write'))]
            for effect in effects:
                with self.assertRaises(OperationDenied): effect()
                blocked.append(True)
            return verify(*args, **kwargs)
        with patch.object(self.ws, 'verify', side_effect=guarded):
            reply = await self.call(self.verification_command(candidate))
        self.assertEqual(reply['request']['receipt']['verdict'], 'passed', reply)
        self.assertEqual(len(blocked), 3)
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_same_content_replacement_run_does_not_match_original_review_invocation(self):
        candidate, assignment = await self.review()
        runner = self.controller.runner
        key = next(iter(runner.verification_runs))
        old = runner.verification_runs[key]
        runner.verification_runs[key] = replace(old)
        self.assertIsNot(runner.verification_runs[key], old)
        reply = await self.call(self.finish_command(candidate, assignment))
        self.assertEqual(reply['request']['receipt']['review'], 'pending', reply)
        self.assertEqual(self.gh.note['wait_reason'], 'verification_evidence_unknown')
        self.assertEqual(self.counter.read_text(), '1')

    async def test_output_corruption_invalidates_actual_run_digest(self):
        candidate, assignment = await self.review()
        self.ws._outputs.clear()
        reply = await self.call(self.finish_command(candidate, assignment))
        self.assertEqual(reply['request']['receipt']['review'], 'pending', reply)
        self.assertEqual(self.gh.note['wait_reason'], 'verification_evidence_unknown')

    async def test_proof_loss_during_final_readback_cannot_release_as_accepted(self):
        candidate, assignment = await self.review()
        source = self.gh.progress_source
        def lose(repo, number):
            if self.gh.note.get('phase') == 'change_review_done':
                self.controller.runner.verification_runs.clear()
            return source(repo, number)
        with patch.object(self.gh, 'progress_source', side_effect=lose):
            reply = await self.call(self.finish_command(candidate, assignment))
        self.assertEqual(reply['request']['receipt']['review'], 'pending', reply)
        self.assertNotEqual(self.gh.note.get('checkpoint'), 'locally_verified')
        self.assertEqual(self.gh.note['wait_reason'], 'verification_evidence_unknown')

    async def test_retirement_ack_loss_does_not_manufacture_replay_receipt(self):
        candidate, assignment = await self.review()
        command = self.finish_command(candidate, assignment)
        confirm = native.confirm_native_assignment
        def lost(step):
            confirm(step)
            raise OSError('synthetic private retirement ACK loss')
        with patch.object(native, 'confirm_native_assignment', side_effect=lost):
            first = await self.call(command)
        self.assertEqual(first['request']['outcome'], 'unknown', first)
        replay = await self.call(command)
        self.assertEqual(replay['request']['outcome'], 'unknown', replay)
        self.assertIsNone(replay['request']['receipt'])
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_oversized_private_review_is_rejected_before_ticket_registration(self):
        candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        with patch.object(self.controller.runner, '_operator_context', return_value='SYNTHETIC_PRIVATE' + 'x' * 1100000):
            reply = await self.call(command)
        self.assertIsNone(reply['handoff'])
        self.assertNotIn('SYNTHETIC_PRIVATE', json.dumps(reply))
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')
        self.assertNotIn('native_step', self.gh.note)

    async def test_actual_sdk_returns_private_review_then_bounded_completion(self):
        from mcp import Client
        candidate = await self.candidate(0)
        server = create_server(self.controller, command_config_path=self.settings,
            command_context_provider=lambda ctx: self.verification_grant())
        command = self.verification_command(candidate)
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        with patch.object(self.controller, 'advance', side_effect=AssertionError('broad continuation')):
            async with Client(server) as client:
                tools = await client.list_tools()
                self.assertEqual({tool.name for tool in tools.tools}, {'hydra_status', 'hydra_begin',
                    'hydra_checkpoint', 'hydra_verify', 'hydra_deliver', 'hydra_command_v1'})
                response = await client.call_tool('hydra_command_v1', {'command': command})
                self.assertFalse(response.is_error, response.content)
                reply = json.loads(response.content[0].text)
                assignment = reply['handoff']['assignment']
                self.assertIn('SYNTHETIC_PRIVATE_VERIFY_ONLY_OUTPUT', assignment['prompt'])
                response = await client.call_tool('hydra_command_v1',
                    {'command': self.finish_command(candidate, assignment)})
                self.assertFalse(response.is_error, response.content)
                reply = json.loads(response.content[0].text)
        self.assertEqual(reply['request']['receipt']['review'], 'accepted', reply)
        self.assertIsNone(reply['handoff'])
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')
        self.assertNotIn('SYNTHETIC_PRIVATE', json.dumps(self.gh.note))


class VerificationBoundaryTests(unittest.IsolatedAsyncioTestCase):
    command = fixture.VerificationSchemaTests.command

    async def test_native_profile_survives_missing_config_rejection(self):
        command = self.command()
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        reply = await execute_command_v1(None, command,
            context_provider=lambda: None, github=None, controller=None)
        self.assertEqual(reply.get('reply_profile'), 'native_handoff_v1', reply)
        self.assertIsNone(reply['handoff'])
        self.assertEqual(reply['request']['outcome'], 'rejected')

    def test_malformed_profile_fields_always_raise_closed_validation_error(self):
        for field in ('stage', 'reply_profile', 'candidate'):
            for value in (None, [], True, 7, {}, 'invalid'):
                command = self.command()
                command['parameters'][field] = value
                with self.subTest(field=field, value=value), self.assertRaises(InvalidAdmissionCommand):
                    parse_command_v1(command)
