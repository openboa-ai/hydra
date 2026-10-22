"""Existing host holds and legacy evidence lifetimes also fence typed verification."""
import unittest

import test_native_verify_only_contract as fixture


class VerificationRecoveryTests(unittest.IsolatedAsyncioTestCase):
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

    async def test_existing_host_cleanup_hold_prevents_new_registered_verification(self):
        candidate = await self.candidate(0)
        self.controller.runner.host_hold_reason = 'host_verification_unconfirmed'
        reply = await self.call(self.verification_command(candidate))
        self.assertEqual(reply['request']['reason'], 'host_verification_unconfirmed', reply)
        self.assertIsNone(reply['request']['receipt'])
        self.assertFalse(self.counter.exists())
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_failed_explicit_reverification_invalidates_earlier_acceptance(self):
        candidate = await self.candidate(7)
        key = ('example/product', 4, candidate['head'], self.gh.cfg['blob_sha'])
        # A controlled earlier-acceptance snapshot; it is not fresh D evidence.
        self.controller.runner.verified_heads.add(key)
        self.gh.note['checkpoint'] = 'locally_verified'
        reply = await self.call(self.verification_command(candidate))
        self.assertEqual(reply['request']['receipt']['verdict'], 'failed', reply)
        self.assertNotIn(key, self.controller.runner.verified_heads,
                         'A later continuation must not consume superseded local acceptance')
        self.assertNotEqual(self.gh.note.get('checkpoint'), 'locally_verified')
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_explicit_legacy_stop_retires_only_the_original_private_review_lifetime(self):
        _, assignment = await self.review()
        runner = self.controller.runner
        self.assertTrue(runner.review_runs and runner.verification_runs)
        reply = await self.controller.checkpoint(self.url, assignment['attempt_id'], assignment['step_id'],
            assignment['head'], assignment['contract_revision'], 'stopped')
        self.assertEqual(reply['reason'], 'stop_requested', reply)
        self.assertEqual(runner.review_runs, {})
        self.assertEqual(runner.verification_runs, {})
        self.assertEqual(runner.review_steps, {})
        self.assertEqual(runner.pending_verifications, {})
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')
