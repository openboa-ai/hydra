"""A completed partial result list cannot leave a replayable verification intent."""
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import test_native_verify_only_contract as fixture


class IncompleteVerificationTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_signalled_partial_result_settles_without_repeating_earlier_commands(self):
        original = self.real_git_assignment
        later = Path(self.tmp.name) / 'later-command'
        async def configure():
            argv = self.gh.cfg['verification'][0]['argv']
            argv[2] = 'import os, signal; ' + argv[2].replace(
                'sys.exit(int(sys.argv[2]))', 'os.kill(os.getpid(), signal.SIGTERM)')
            self.gh.cfg['verification'].append({'argv': [sys.executable, '-c',
                'from pathlib import Path; import sys; Path(sys.argv[1]).write_text("unexpected")', str(later)],
                'cwd': '.', 'timeout': 20})
            return await original()
        with patch.object(self, 'real_git_assignment', side_effect=configure):
            candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        reply = await self.call(command)
        self.assertEqual(reply['request']['reason'], 'verification_evidence_unknown', reply)
        self.assertIsNone(reply['request']['receipt'])
        self.assertIsNone(self.gh.note.get('pending_action'), 'Incomplete results must settle the original intent')
        self.assertEqual(self.gh.note['wait_reason'], 'replan_required')
        await self.call(command)
        ordinary = await self.controller.advance(self.url, candidate['attempt_id'],
            candidate['head'], candidate['contract_revision'])
        self.assertEqual(ordinary['reason'], 'replan_required')
        self.assertEqual(self.counter.read_text(), '1')
        self.assertFalse(later.exists())
        self.assertEqual(self.lock.read_bytes(), b'')
