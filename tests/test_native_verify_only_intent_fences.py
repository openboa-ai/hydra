"""The actual progress writer and registered-command boundary own their fences."""
import copy
import unittest
from unittest.mock import patch

from test_native_verify_only_intent import IntentFixture


class VerificationIntentFenceTests(IntentFixture, unittest.IsolatedAsyncioTestCase):
    async def test_foreign_stage_before_restoration_writer_is_never_overwritten(self):
        pin = await self.candidate(0)
        runner, changed = self.controller.runner, False
        effect = runner._effect
        def foreign(repo, callback, *args, **kwargs):
            nonlocal changed
            planned = runner._checkpoint_ceiling.get()[3].get('record', {})
            if (not changed and kwargs.get('_checkpoint_effect') == 'progress'
                    and planned.get('phase') == 'implementation_done'
                    and self.gh.note.get('pending_action') == 'verification'
                    and not self.counter.exists()):
                changed = True
                self.gh.note.update(phase='implementation_done', resume_phase='correction',
                    pending_action=None, next_action='diagnose_review', wait_reason='review_findings')
            return effect(repo, callback, *args, **kwargs)
        with self.lose_intent(), patch.object(runner, '_effect', side_effect=foreign):
            reply = await self.call(self.verification_command(pin))
        self.assertTrue(changed)
        self.assertEqual(self.gh.note['resume_phase'], 'correction',
                         'A no-launch restoration cannot overwrite a later source at its writer')
        self.assertEqual(self.gh.note['next_action'], 'diagnose_review')
        self.assertFalse(self.counter.exists())
        self.assertIsNone(reply['request']['receipt'])

    async def test_stage_change_at_actual_worker_entry_cannot_launch_a_command(self):
        pin = await self.candidate(0)
        verify = self.ws.verify
        def foreign(*args, **kwargs):
            self.gh.note.update(phase='implementation_done', resume_phase='correction',
                pending_action=None, next_action='diagnose_review', wait_reason='review_findings')
            return verify(*args, **kwargs)
        with patch.object(self.ws, 'verify', side_effect=foreign):
            reply = await self.call(self.verification_command(pin))
        self.assertFalse(self.counter.exists(),
                         'Creating a worker cannot authorize dispatch from a changed source')
        self.assertEqual(self.gh.note['resume_phase'], 'correction')
        self.assertEqual(self.gh.note['next_action'], 'diagnose_review')
        self.assertIsNone(reply['request']['receipt'])

    async def test_grant_revoked_during_pre_intent_read_cannot_write_progress(self):
        pin = await self.candidate(0)
        original = copy.deepcopy(self.gh.note)
        self.revoked = False
        read = self.gh.progress_source
        def revoked(*args, **kwargs):
            value = read(*args, **kwargs)
            self.revoked = True
            return value
        def context():
            return self.verification_grant('admission_set') if self.revoked else self.verification_grant()
        writes = len(self.gh.writes)
        with patch.object(self.gh, 'progress_source', side_effect=revoked):
            reply = await self.call(self.verification_command(pin), context_provider=context)
        self.assertTrue(self.revoked)
        self.assertEqual(len(self.gh.writes), writes,
                         'A source read cannot carry an earlier workflow grant into its writer')
        self.assertEqual(self.gh.note, original)
        self.assertFalse(self.counter.exists())
        self.assertIsNone(reply['request']['receipt'])
        self.revoked = False
        completed = await self.call(self.fresh(pin), context_provider=context)
        self.assertEqual(completed['request']['receipt']['verdict'], 'passed')
        self.assertEqual(self.counter.read_text(), '1')
