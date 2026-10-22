"""Final private return must revalidate authority after the progress read."""
import json
import unittest
from unittest.mock import patch
import test_native_verify_only_contract as fixture


class VerificationReturnTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_grant_revoked_in_final_source_read_cannot_receive_private_assignment(self):
        candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        revoked = False
        source = self.gh.progress_source
        def read(repo, number):
            nonlocal revoked
            value = source(repo, number)
            if value['record'].get('native_step') is not None:
                revoked = True
            return value
        def current():
            return self.verification_grant('admission_set') if revoked else self.verification_grant()
        with patch.object(self.gh, 'progress_source', side_effect=read):
            reply = await self.call(command, context_provider=current)
        self.assertTrue(revoked)
        self.assertEqual(reply.get('reply_profile'), 'native_handoff_v1')
        self.assertIsNone(reply['handoff'], 'The final source read cannot carry an earlier handoff grant')
        self.assertNotIn('SYNTHETIC_PRIVATE_VERIFY_ONLY_OUTPUT', json.dumps(reply))
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.gh.note['native_phase'], 'change_review')

    async def test_current_grant_receives_actual_private_assignment(self):
        _, assignment = await self.review()
        self.assertIn('SYNTHETIC_PRIVATE_VERIFY_ONLY_OUTPUT', assignment['prompt'])
        self.assertEqual(self.counter.read_text(), '1')

    async def test_same_request_recovery_revalidates_grant_and_does_not_run_D_again(self):
        candidate, _ = await self.review()
        command = self.verification_command(candidate)
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        revoked = False
        source = self.gh.progress_source
        def read(repo, number):
            nonlocal revoked
            value = source(repo, number)
            revoked = True
            return value
        def current():
            return self.verification_grant('admission_set') if revoked else self.verification_grant()
        with patch.object(self.gh, 'progress_source', side_effect=read):
            reply = await self.call(command, context_provider=current)
        self.assertIsNone(reply['handoff'])
        self.assertNotIn('SYNTHETIC_PRIVATE_VERIFY_ONLY_OUTPUT', json.dumps(reply))
        self.assertEqual(self.counter.read_text(), '1')
