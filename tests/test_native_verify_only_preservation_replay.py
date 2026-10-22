"""Recovery under fresh authority retains the recovery request's replay boundary."""
import unittest
from unittest.mock import patch

import test_native_verify_only_preservation as fixture


class VerificationPreservationReplayTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.VerificationPreservationTests.asyncSetUp
    new_controller = fixture.VerificationPreservationTests.new_controller
    result = fixture.VerificationPreservationTests.result
    command = fixture.VerificationPreservationTests.command
    checkpoint = fixture.VerificationPreservationTests.checkpoint
    real_git_assignment = fixture.VerificationPreservationTests.real_git_assignment
    candidate = fixture.VerificationPreservationTests.candidate
    verification_command = fixture.VerificationPreservationTests.verification_command
    verification_grant = fixture.VerificationPreservationTests.verification_grant
    call = fixture.VerificationPreservationTests.call
    fresh = fixture.VerificationPreservationTests.fresh
    advance = fixture.VerificationPreservationTests.advance

    async def test_completed_recovery_replay_and_original_request_do_not_repeat_D(self):
        candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        revoked = False
        verify = self.ws.verify
        def completed(*args, **kwargs):
            nonlocal revoked
            results = verify(*args, **kwargs)
            revoked = True
            return results
        def context():
            return self.verification_grant('admission_set') if revoked else self.verification_grant()
        with patch.object(self.ws, 'verify', side_effect=completed):
            first = await self.call(command, context_provider=context)
        self.assertIsNone(first['request']['receipt'])
        self.assertEqual(self.gh.note['pending_action'], 'verification')
        self.assertEqual(self.counter.read_text(), '1')
        revoked = False
        fresh = self.fresh(candidate)
        recovered = await self.call(fresh, context_provider=context)
        self.assertEqual(recovered['request']['receipt']['verdict'], 'passed')
        self.assertEqual(self.counter.read_text(), '1')
        replay = await self.call(fresh, context_provider=context)
        self.assertEqual(self.counter.read_text(), '1',
                         'Replaying a completed recovery request must reuse the same invocation')
        self.assertEqual(replay['request']['receipt']['verdict'], 'passed')
        original = await self.call(command, context_provider=context)
        self.assertIsNone(original['request']['receipt'])
        self.assertEqual(self.counter.read_text(), '1', 'The retired original request cannot become new D')
        assignment = await self.advance(candidate)
        self.assertEqual((assignment.get('phase'), assignment.get('mode')), ('change_review', 'read_only'))
        self.assertEqual(self.counter.read_text(), '1')
