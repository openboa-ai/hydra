"""Completed failure evidence remains valid when the existing retry budget ends."""
import copy
import unittest

from hydra_sdlc.github import GitHub
from test_native_verify_only_intent import IntentFixture
from test_workspace import git


class VerificationRetryBudgetTests(IntentFixture, unittest.IsolatedAsyncioTestCase):
    def request(self, candidate, index):
        command = self.verification_command(candidate)
        command['request_id'] = f'8888888{index}-8888-4888-8888-888888888888'
        return command

    async def test_exhausted_failed_candidate_cannot_launch_a_fourth_diagnostic_run(self):
        candidate = await self.candidate(7)
        for index in (1, 2, 3):
            command = self.request(candidate, index)
            reply = await self.call(command)
            self.assertIsNotNone(reply['request']['receipt'])
            self.assertEqual(reply['request']['receipt']['verdict'], 'failed')
            self.assertEqual(self.counter.read_text(), str(index))
            self.assertEqual(self.gh.note['correction_attempt'], index)
            GitHub._validate_record(self.gh.note, metadata=True)
            await self.call(command)
            self.assertEqual(self.counter.read_text(), str(index), 'Replay cannot consume another attempt')
        source, writes = copy.deepcopy(self.gh.note), len(self.gh.writes)
        denied = await self.call(self.request(candidate, 4))
        self.assertEqual(self.counter.read_text(), '3', 'Exhaustion must hold before dispatching D4')
        self.assertIsNone(denied['request']['receipt'])
        self.assertEqual(denied['request']['reason'], 'replan_required')
        self.assertEqual(self.gh.note, source)
        self.assertEqual(len(self.gh.writes), writes)
        self.assertEqual(self.lock.read_bytes(), b'')
        self.assertEqual(git(self.path, 'rev-parse', 'HEAD'), candidate['head'])

    async def test_failed_verification_after_final_completed_correction_preserves_actual_result(self):
        candidate = await self.candidate(7)
        self.gh.note.update(correction_reason='verification_failure', correction_attempt=3,
                            resume_phase=None, wait_reason=None)
        GitHub._validate_record(self.gh.note, metadata=True)
        command = self.request(candidate, 1)
        reply = await self.call(command)
        self.assertIsNotNone(reply['request']['receipt'], 'A completed final correction still needs actual verification')
        self.assertEqual(reply['request']['receipt']['verdict'], 'failed')
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.gh.note['correction_attempt'], 3, 'A known failed result must retain a valid exhausted budget')
        self.assertIsNone(self.gh.note.get('pending_action'))
        self.assertEqual(self.gh.note['next_action'], 'diagnose_verification')
        GitHub._validate_record(self.gh.note, metadata=True)
        await self.call(command)
        source, writes = copy.deepcopy(self.gh.note), len(self.gh.writes)
        denied = await self.call(self.request(candidate, 2))
        self.assertIsNone(denied['request']['receipt'])
        self.assertEqual(denied['request']['reason'], 'replan_required')
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.gh.note, source)
        self.assertEqual(len(self.gh.writes), writes)
        self.assertEqual(self.lock.read_bytes(), b'')
        self.assertEqual(git(self.path, 'rev-parse', 'HEAD'), candidate['head'])
