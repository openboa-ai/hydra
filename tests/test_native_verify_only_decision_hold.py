"""A fresh verification request cannot dismiss an unresolved product decision."""
import unittest
import test_native_verify_only_contract as fixture


class VerificationDecisionHoldTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_explicit_run_preserves_product_decision_without_D_or_new_review(self):
        candidate = await self.candidate(0)
        self.gh.note.update(wait_reason='product_decision', next_action='operator_decision',
                            resume_phase='change_review')
        reply = await self.call(self.verification_command(candidate))
        self.assertEqual(reply['request']['reason'], 'product_decision', reply)
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual((self.gh.note['wait_reason'],self.gh.note['next_action'],self.gh.note['resume_phase']),
                         ('product_decision','operator_decision','change_review'))
        self.assertFalse(self.counter.exists())
        self.assertEqual(self.lock.read_bytes(), b'')
        self.assertNotIn('native_step', self.gh.note)
