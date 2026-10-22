"""P13-R8: real registered verification stops at its bounded command boundary."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

from hydra_sdlc.control import load_host_config
from hydra_sdlc.control_commands import AdmissionCallContext, execute_command_v1, _runtime_key
from hydra_sdlc.runtime_identity import capture_runtime_identity
import test_checkpoint_only as checkpoint_fixture
from test_workspace import git


class VerificationRunTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = checkpoint_fixture.CheckpointOnlyTests.asyncSetUp
    new_controller = checkpoint_fixture.CheckpointOnlyTests.new_controller
    result = checkpoint_fixture.CheckpointOnlyTests.result
    command = checkpoint_fixture.CheckpointOnlyTests.command
    checkpoint = checkpoint_fixture.CheckpointOnlyTests.checkpoint
    real_git_assignment = checkpoint_fixture.CheckpointOnlyTests.real_git_assignment

    async def candidate(self, exit_code):
        self.counter = Path(self.tmp.name) / 'registered-verification-count'
        code = ('from pathlib import Path; import sys; p=Path(sys.argv[1]); '
                'p.write_text(str((int(p.read_text()) if p.exists() else 0)+1)); '
                'print("SYNTHETIC_PRIVATE_VERIFY_ONLY_OUTPUT"); sys.exit(int(sys.argv[2]))')
        self.gh.cfg['verification'] = [{'argv': [sys.executable, '-c', code,
            str(self.counter), str(exit_code)], 'cwd': '.', 'timeout': 20}]
        assignment, path, base = await self.real_git_assignment()
        (path / 'src/main.py').write_text('verified_candidate = True\n')
        completed = await self.checkpoint(assignment)
        self.assertEqual(completed['request']['outcome'], 'applied', completed)
        self.assertEqual(self.gh.note['phase'], 'implementation_done')
        self.assertEqual(self.lock.read_bytes(), b'')
        self.assertFalse(self.counter.exists())
        self.path, self.base = path, base
        return {key: self.gh.note[key] for key in ('attempt_id', 'head', 'contract_revision')}

    def verification_command(self, candidate):
        cfg = load_host_config(self.settings)
        return {'command_schema': 1, 'request_id': '22222222-2222-4222-8222-222222222222',
            'binding_epoch': None, 'action': 'workflow_step',
            'target': {'repository_id': self.gh.cfg['repository_id'], 'issue_number': 4},
            'expected': {'runtime_key': _runtime_key(capture_runtime_identity(cfg, self.control)),
                'admission_revision': self.control.snapshot()['revision'],
                'source_checks': [], 'assignment': None}, 'effect_key': None,
            'parameters': {'operation': 'verify_only', 'stage': 'run',
                'candidate': dict(candidate), 'reply_profile': 'standard_v1'}}

    async def invoke(self, candidate):
        grant = AdmissionCallContext('native', None, frozenset({self.gh.cfg['repository_id']}),
            frozenset({'workflow_step.verify_only.run'}))
        with patch.object(self.controller, 'advance', side_effect=AssertionError('broad continuation')):
            return await execute_command_v1(self.settings, self.verification_command(candidate),
                context_provider=lambda: grant, github=self.gh, controller=self.controller)

    async def test_standard_run_executes_registered_D_without_review_or_delivery_dispatch(self):
        candidate = await self.candidate(0)
        writes = len(self.gh.writes)
        reply = await self.invoke(candidate)
        receipt = reply['request']['receipt']
        self.assertIsNotNone(receipt, 'A valid verify_only run must return its actual verification receipt')
        self.assertEqual(receipt['kind'], 'verification')
        self.assertEqual(receipt['candidate'], candidate)
        self.assertEqual(receipt['verdict'], 'passed')
        self.assertIn(receipt['review'], ('pending', None))
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(git(self.path, 'rev-parse', 'HEAD'), candidate['head'])
        self.assertEqual(self.lock.read_bytes(), b'')
        self.assertNotIn('native_step', self.gh.note)
        self.assertTrue(all(row[0] == 'record' for row in self.gh.writes[writes:]))
        self.assertNotIn('SYNTHETIC_PRIVATE_VERIFY_ONLY_OUTPUT', json.dumps(reply))

    async def test_failed_registered_D_is_reported_without_correction_or_another_run(self):
        candidate = await self.candidate(7)
        writes = len(self.gh.writes)
        reply = await self.invoke(candidate)
        receipt = reply['request']['receipt']
        self.assertIsNotNone(receipt, 'A completed failing verifier must return a failed verdict')
        self.assertEqual(receipt['kind'], 'verification')
        self.assertEqual(receipt['candidate'], candidate)
        self.assertEqual(receipt['verdict'], 'failed')
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(git(self.path, 'rev-parse', 'HEAD'), candidate['head'])
        self.assertEqual(self.lock.read_bytes(), b'')
        self.assertNotIn('native_step', self.gh.note)
        self.assertTrue(all(row[0] == 'record' for row in self.gh.writes[writes:]))
        self.assertNotIn('SYNTHETIC_PRIVATE_VERIFY_ONLY_OUTPUT', json.dumps(reply))
