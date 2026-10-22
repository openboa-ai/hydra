"""Exact intent acknowledgement and lifecycle eligibility, with real child counts."""
import copy
import unittest
from unittest.mock import patch

from test_native_verify_only_launch import LaunchFixture
import test_native_verify_only_contract as contract_fixture
from test_workspace import git


class IntentFixture(LaunchFixture):
    review = contract_fixture.VerificationContractTests.review
    finish_command = contract_fixture.VerificationContractTests.finish_command

    def lose_intent(self, *, apply=True, after=None, attempts=None):
        write = self.gh.record_checkpoint
        def lost(repo, number, record):
            if record.get('phase') == 'executing' and record.get('pending_action') == 'verification':
                if attempts is not None:
                    attempts.append('intent')
                if apply:
                    write(repo, number, record)
                if after is not None:
                    after()
                raise OSError('synthetic intent acknowledgement loss')
            return write(repo, number, record)
        return patch.object(self.gh, 'record_checkpoint', side_effect=lost)


class VerificationIntentAcknowledgementTests(IntentFixture, unittest.IsolatedAsyncioTestCase):
    async def test_applied_intent_ack_loss_restores_before_same_request_runs_once(self):
        pin = await self.candidate(0)
        original = copy.deepcopy(self.gh.note)
        command, attempts = self.verification_command(pin), []
        with self.lose_intent(attempts=attempts):
            first = await self.call(command)
        self.assertIsNone(self.gh.note.get('pending_action'), 'No worker exists after an intent-write ACK loss')
        self.assertEqual(self.gh.note['phase'], original['phase'])
        self.assertIsNone(first['request']['receipt'])
        self.assertEqual(attempts, ['intent'])
        self.assertFalse(self.counter.exists())
        self.assertEqual(git(self.path, 'rev-parse', 'HEAD'), pin['head'])
        completed = await self.call(command)
        self.assertEqual(completed['request']['receipt']['verdict'], 'passed')
        await self.call(command)
        self.assertEqual(self.counter.read_text(), '1')

    async def test_unapplied_intent_reads_original_without_reposting_then_runs_once(self):
        pin = await self.candidate(0)
        original, attempts = copy.deepcopy(self.gh.note), []
        command = self.verification_command(pin)
        with self.lose_intent(apply=False, attempts=attempts):
            first = await self.call(command)
        self.assertEqual(self.gh.note, original)
        self.assertEqual(attempts, ['intent'])
        self.assertIsNone(first['request']['receipt'])
        self.assertFalse(self.counter.exists())
        completed = await self.call(command)
        self.assertEqual(completed['request']['receipt']['verdict'], 'passed')
        self.assertEqual(self.counter.read_text(), '1')

    async def test_applied_intent_ack_loss_preserves_pause_and_restart_can_resume_once(self):
        pin = await self.candidate(0)
        intent = self.controller.runner._intent
        def paused(*args, **kwargs):
            try:
                return intent(*args, **kwargs)
            except OSError:
                # The external control write occurs after the writer's
                # admission guard has exited, before no-launch settlement.
                self.control.set_mode('pause', 'example/product')
                raise
        with self.lose_intent(), patch.object(self.controller.runner, '_intent', side_effect=paused):
            first = await self.call(self.verification_command(pin))
        self.assertIsNone(self.gh.note.get('pending_action'), 'Current preservation must restore the undispatched intent')
        self.assertIsNone(first['request']['receipt'])
        self.assertFalse(self.counter.exists())
        self.assertEqual(self.control.snapshot()['projects']['example/product'], 'paused')
        self.controller = self.new_controller(); self.controller.runner.operations = self.control
        self.control.set_mode('resume', 'example/product')
        completed = await self.call(self.fresh(pin))
        self.assertEqual(completed['request']['receipt']['verdict'], 'passed')
        self.assertEqual(self.counter.read_text(), '1')

    async def test_ack_loss_grant_revocation_reconciles_before_a_later_run(self):
        pin = await self.candidate(0)
        self.revoked = False
        def context():
            return self.verification_grant('admission_set') if self.revoked else self.verification_grant()
        with self.lose_intent(after=lambda: setattr(self, 'revoked', True)):
            first = await self.call(self.verification_command(pin), context_provider=context)
        self.assertIsNone(first['request']['receipt'])
        self.assertEqual(self.gh.note['pending_action'], 'verification')
        self.assertFalse(self.counter.exists())
        self.revoked = False
        command = self.fresh(pin)
        recovered = await self.call(command, context_provider=context)
        self.assertIsNone(self.gh.note.get('pending_action'), 'The retained no-worker witness must survive the lost ACK')
        self.assertIsNone(recovered['request']['receipt'])
        self.assertFalse(self.counter.exists())
        completed = await self.call(command, context_provider=context)
        self.assertEqual(completed['request']['receipt']['verdict'], 'passed')
        self.assertEqual(self.counter.read_text(), '1')

    async def test_unknown_intent_readback_retains_witness_then_recovers_without_dispatch(self):
        pin = await self.candidate(0)
        written = False
        read = self.gh.progress_source
        def unavailable(*args, **kwargs):
            if written:
                raise OSError('synthetic read-back unavailable')
            return read(*args, **kwargs)
        def changed():
            nonlocal written
            written = True
        command = self.verification_command(pin)
        with self.lose_intent(after=changed), patch.object(self.gh, 'progress_source', side_effect=unavailable):
            first = await self.call(command)
        self.assertIsNone(first['request']['receipt'])
        self.assertFalse(self.counter.exists())
        recovered = await self.call(command)
        self.assertIsNone(self.gh.note.get('pending_action'), 'Recovered source must settle the same no-launch intent')
        self.assertIsNone(recovered['request']['receipt'])
        self.assertFalse(self.counter.exists())
        completed = await self.call(command)
        self.assertEqual(completed['request']['receipt']['verdict'], 'passed')
        self.assertEqual(self.counter.read_text(), '1')

    async def test_unapplied_intent_at_accepted_checkpoint_invalidates_without_another_D(self):
        pin, assignment = await self.review()
        accepted = await self.call(self.finish_command(pin, assignment))
        self.assertEqual(accepted['request']['receipt']['review'], 'accepted')
        self.assertEqual(self.gh.note['checkpoint'], 'locally_verified')
        command, attempts = self.fresh(pin), []
        with self.lose_intent(apply=False, attempts=attempts):
            first = await self.call(command)
        self.assertIsNone(self.gh.note.get('checkpoint'), 'An explicit new run must not retain stale acceptance')
        self.assertIsNone(self.gh.note.get('pending_action'))
        self.assertEqual(attempts, ['intent'])
        self.assertIsNone(first['request']['receipt'])
        self.assertEqual(self.counter.read_text(), '1')
        completed = await self.call(command)
        self.assertEqual(completed['request']['receipt']['verdict'], 'passed')
        self.assertEqual(self.counter.read_text(), '2')


class VerificationCandidateEligibilityTests(IntentFixture, unittest.IsolatedAsyncioTestCase):
    async def assert_closed_states(self, states):
        pin = await self.candidate(0)
        original = copy.deepcopy(self.gh.note)
        for phase, resume, pending in states:
            with self.subTest(phase=phase, resume=resume, pending=pending):
                self.gh.note = {**copy.deepcopy(original), 'phase': phase,
                    'resume_phase': resume, 'pending_action': pending, 'wait_reason': None}
                expected = copy.deepcopy(self.gh.note)
                self.controller = self.new_controller(); self.controller.runner.operations = self.control
                self.counter.unlink(missing_ok=True)
                writes = len(self.gh.writes)
                reply = await self.call(self.verification_command(pin))
                self.assertFalse(self.counter.exists(), 'Verification must not consume unfinished lifecycle work')
                self.assertIsNone(reply['request']['receipt'])
                self.assertEqual(self.gh.note, expected)
                self.assertEqual(len(self.gh.writes), writes)
                self.assertEqual(self.lock.read_bytes(), b'')

    async def test_earlier_and_unresolved_phases_cannot_start_verification(self):
        await self.assert_closed_states([(p, None, None) for p in
            ('ready', 'design_done', 'spec_accepted', 'spec_review_done', 'checkpoint', 'completed')]
            + [('implementation_done', None, 'verification')])

    async def test_resume_debt_cannot_be_erased_by_a_passing_verifier(self):
        await self.assert_closed_states([('implementation_done', p, None) for p in
            ('design', 'spec_review', 'implementation', 'correction', 'change_review')]
            + [('spec_review_done', 'implementation', None), ('change_review_done', 'correction', None)])

    async def test_fresh_run_after_accepted_review_still_executes_actual_D(self):
        pin, assignment = await self.review()
        accepted = await self.call(self.finish_command(pin, assignment))
        self.assertEqual(accepted['request']['receipt']['review'], 'accepted')
        completed = await self.call(self.fresh(pin))
        self.assertEqual(completed['request']['receipt']['verdict'], 'passed')
        self.assertEqual(self.counter.read_text(), '2')
        self.assertIsNone(self.gh.note.get('checkpoint'))
        self.assertNotIn('native_step', self.gh.note)

    async def test_post_publication_candidates_still_allow_bounded_verification(self):
        pin, assignment = await self.review()
        accepted = await self.call(self.finish_command(pin, assignment))
        self.assertEqual(accepted['request']['receipt']['review'], 'accepted')
        for index, phase in enumerate(('published', 'review_wait')):
            with self.subTest(phase=phase):
                self.gh.note.update(phase=phase, pending_action=None, resume_phase=None)
                command = self.fresh(pin)
                command['request_id'] = f'7777777{index}-7777-4777-8777-777777777777'
                writes = len(self.gh.writes)
                reply = await self.call(command)
                self.assertIsNotNone(reply['request']['receipt'],
                    'An implementation-complete delivery candidate retains bounded verification')
                self.assertEqual(reply['request']['receipt']['verdict'], 'passed')
                self.assertEqual(self.counter.read_text(), str(index + 2))
                self.assertTrue(all(row[0] == 'record' for row in self.gh.writes[writes:]))
                self.assertEqual(git(self.path, 'rev-parse', 'HEAD'), pin['head'])

    async def test_changed_stage_at_final_guard_is_not_launched_or_overwritten(self):
        pin = await self.candidate(0)
        def foreign():
            self.gh.note.update(phase='implementation_done', pending_action=None,
                resume_phase='correction', wait_reason='review_findings', next_action='diagnose_review')
        with self.after_intent(foreign):
            reply = await self.call(self.verification_command(pin))
        self.assertFalse(self.counter.exists(), 'The exact acknowledged intent must still be current at dispatch')
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(self.gh.note['resume_phase'], 'correction')
        self.assertEqual(self.gh.note['next_action'], 'diagnose_review')
        self.assertEqual(git(self.path, 'rev-parse', 'HEAD'), pin['head'])

    async def test_changed_stage_immediately_before_intent_is_not_overwritten(self):
        pin = await self.candidate(0)
        runner, changed = self.controller.runner, False
        effect = runner._effect
        def foreign(repo, callback, *args, **kwargs):
            nonlocal changed
            if not changed and kwargs.get('_checkpoint_effect') == 'progress':
                changed = True
                self.gh.note.update(phase='spec_review_done', resume_phase='implementation',
                    pending_action=None, next_action='implementation')
            return effect(repo, callback, *args, **kwargs)
        writes = len(self.gh.writes)
        with patch.object(runner, '_effect', side_effect=foreign):
            reply = await self.call(self.verification_command(pin))
        self.assertTrue(changed)
        self.assertFalse(self.counter.exists(), 'A foreign original source cannot authorize the intent writer')
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(len(self.gh.writes), writes)
        self.assertEqual((self.gh.note['phase'], self.gh.note['resume_phase']),
                         ('spec_review_done', 'implementation'))
