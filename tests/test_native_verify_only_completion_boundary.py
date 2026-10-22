"""Owned result writes and every completion entry point preserve the same boundary."""
import copy
import unittest
from unittest.mock import AsyncMock, patch

from hydra_sdlc.github import GitHub, GitHubError
from test_native_verify_only_intent import IntentFixture


class VerificationCompletionBoundaryTests(IntentFixture, unittest.IsolatedAsyncioTestCase):
    async def legacy(self, pin, assignment, outcome='candidate_ready'):
        return await self.controller.checkpoint(self.url, pin['attempt_id'], assignment['step_id'],
            pin['head'], pin['contract_revision'], outcome, 'SYNTHETIC_LEGACY_REVIEW_RESULT')

    def foreign_correction(self):
        self.gh.note.update(phase='implementation_done', pending_action=None,
            resume_phase='correction', wait_reason='review_findings', next_action='diagnose_review')

    async def test_owned_result_writer_cannot_overwrite_a_later_lifecycle(self):
        pin = await self.candidate(0)
        runner, changed = self.controller.runner, False
        effect = runner._effect
        def foreign(repo, callback, *args, **kwargs):
            nonlocal changed
            planned = runner._checkpoint_ceiling.get()[3].get('record', {})
            if (not changed and kwargs.get('_checkpoint_effect') == 'progress'
                    and planned.get('next_action') == 'change_review' and self.counter.exists()
                    and self.gh.note.get('pending_action') == 'verification'):
                changed = True
                self.foreign_correction()
            return effect(repo, callback, *args, **kwargs)
        with patch.object(runner, '_effect', side_effect=foreign):
            reply = await self.call(self.verification_command(pin))
        self.assertTrue(changed)
        self.assertEqual(self.gh.note['next_action'], 'diagnose_review',
                         'A positively ended run cannot overwrite newer progress at its writer')
        self.assertEqual(self.gh.note['wait_reason'], 'review_findings')
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(self.counter.read_text(), '1')
        await self.call(self.fresh(pin))
        self.assertEqual(self.counter.read_text(), '1')

    async def test_owned_result_candidate_read_cannot_adopt_a_foreign_source(self):
        pin = await self.candidate(0)
        bound, verify = self.controller._bound, self.ws.verify
        finished, changed = False, False
        def completed(*args, **kwargs):
            nonlocal finished
            result = verify(*args, **kwargs)
            finished = True
            return result
        def foreign(*args, **kwargs):
            nonlocal changed
            if finished and not changed:
                changed = True
                self.foreign_correction()
            return bound(*args, **kwargs)
        with patch.object(self.ws, 'verify', side_effect=completed), \
             patch.object(self.controller, '_bound', side_effect=foreign):
            reply = await self.call(self.verification_command(pin))
        self.assertTrue(changed)
        self.assertEqual(self.gh.note['next_action'], 'diagnose_review')
        self.assertEqual(self.gh.note['wait_reason'], 'review_findings')
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(self.counter.read_text(), '1')

    async def test_legacy_completion_cannot_use_weaker_caches_after_proof_loss(self):
        pin, assignment = await self.review()
        runner = self.controller.runner
        runner.verification_runs.clear(); runner.review_runs.clear()
        self.assertTrue(runner.review_steps and runner.pending_verifications)
        source, ticket = copy.deepcopy(self.gh.note), self.lock.read_bytes()
        with patch.object(runner, '_publish', return_value={
                'action': 'waiting', 'reason': 'observed_forbidden_publication'}) as publish:
            await self.legacy(pin, assignment)
        self.assertEqual(publish.call_count, 0, 'The legacy path must not advance a bounded review')
        self.assertEqual(self.gh.note, source)
        self.assertEqual(self.lock.read_bytes(), ticket)
        self.assertEqual(self.counter.read_text(), '1')
        honest = await self.call(self.finish_command(pin, assignment))
        self.assertEqual(honest['request']['receipt']['review'], 'pending')
        self.assertNotEqual(self.gh.note.get('checkpoint'), 'locally_verified')
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_all_non_stopped_legacy_outcomes_leave_bounded_review_unchanged(self):
        pin, assignment = await self.review()
        runner = self.controller.runner
        source, ticket = copy.deepcopy(self.gh.note), self.lock.read_bytes()
        for outcome in ('candidate_ready', 'failed', 'needs_decision'):
            with self.subTest(outcome=outcome):
                self.gh.note = copy.deepcopy(source)
                writes = len(self.gh.writes)
                step = AsyncMock(return_value={'action': 'waiting', 'reason': 'forbidden_continuation'})
                with patch.object(runner, 'step', step):
                    await self.legacy(pin, assignment, outcome)
                self.assertEqual(step.await_count, 0)
                self.assertEqual(len(self.gh.writes), writes)
                self.assertEqual(self.gh.note, source)
                self.assertEqual(self.lock.read_bytes(), ticket)
        self.gh.note = copy.deepcopy(source)
        completed = await self.call(self.finish_command(pin, assignment))
        self.assertEqual(completed['request']['receipt']['review'], 'accepted')
        self.assertNotIn('native_completion', self.gh.note)

    async def test_restart_does_not_turn_bounded_review_into_legacy_completion(self):
        pin, assignment = await self.review()
        source, ticket = copy.deepcopy(self.gh.note), self.lock.read_bytes()
        self.controller = self.new_controller(); self.controller.runner.operations = self.control
        step = AsyncMock(return_value={'action': 'waiting', 'reason': 'forbidden_continuation'})
        with patch.object(self.controller.runner, 'step', step):
            await self.legacy(pin, assignment)
        self.assertEqual(step.await_count, 0, 'Completion ownership must survive private-cache loss')
        self.assertEqual(self.gh.note, source)
        self.assertEqual(self.lock.read_bytes(), ticket)
        self.assertEqual(self.counter.read_text(), '1')

    async def test_provisional_typed_outcome_keeps_legacy_path_closed(self):
        pin, assignment = await self.review()
        runner = self.controller.runner
        with patch.object(runner, '_retire_assignment', side_effect=OSError('synthetic pre-retirement failure')):
            first = await self.call(self.finish_command(pin, assignment))
        self.assertIsNone(first['request']['receipt'])
        self.assertEqual(self.gh.note['native_outcome'], 'candidate_ready')
        source, ticket = copy.deepcopy(self.gh.note), self.lock.read_bytes()
        runner.verification_runs.clear(); runner.review_runs.clear()
        step = AsyncMock(return_value={'action': 'waiting', 'reason': 'forbidden_continuation'})
        with patch.object(runner, 'step', step):
            await self.legacy(pin, assignment)
        self.assertEqual(step.await_count, 0)
        self.assertEqual(self.gh.note, source)
        self.assertEqual(self.lock.read_bytes(), ticket)
        honest = await self.call(self.finish_command(pin, assignment))
        self.assertEqual(honest['request']['receipt']['review'], 'pending')
        self.assertNotIn('native_completion', self.gh.note)
        self.assertEqual(self.counter.read_text(), '1')

    async def test_completion_source_has_a_closed_backwards_readable_attribution(self):
        _, _ = await self.review()
        source = {**self.gh.note, 'native_completion': 'verify_only'}
        try:
            GitHub._validate_record(source, metadata=True)
        except GitHubError:
            self.fail('The existing progress source must preserve bounded completion attribution')
        for changes in ({'native_completion': 'future'}, {'native_completion': True},
                        {'native_phase': 'implementation'}, {'native_step': None}):
            with self.subTest(changes=changes), self.assertRaises(GitHubError):
                GitHub._validate_record({**source, **changes}, metadata=True)
        legacy = {k: v for k, v in source.items() if k != 'native_completion'}
        GitHub._validate_record(legacy, metadata=True)
        GitHub._validate_record({**legacy, 'native_completion': None}, metadata=True)

    async def test_ordinary_legacy_review_keeps_its_existing_continuation(self):
        pin = await self.candidate(0)
        assignment = await self.advance(pin)
        self.assertEqual(assignment['phase'], 'change_review')
        self.assertIsNone(self.gh.note.get('native_completion'))
        self.assertEqual(self.counter.read_text(), '1')
        source, ticket = copy.deepcopy(self.gh.note), self.lock.read_bytes()
        rejected = await self.call(self.finish_command(pin, assignment))
        self.assertIsNone(rejected['request']['receipt'],
                         'Typed completion cannot retire an unrelated legacy review')
        self.assertEqual(self.gh.note, source)
        self.assertEqual(self.lock.read_bytes(), ticket)
        with patch.object(self.controller.runner, '_publish', return_value={
                'action': 'waiting', 'reason': 'observed_ordinary_publication'}) as publish:
            reply = await self.legacy(pin, assignment)
        self.assertEqual(publish.call_count, 1)
        self.assertEqual(reply['reason'], 'observed_ordinary_publication')
        self.assertEqual(self.counter.read_text(), '1')
