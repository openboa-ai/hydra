"""Actual writer and lifecycle boundaries retain ownership, evidence and debt."""
import copy
from pathlib import Path
import unittest
from unittest.mock import AsyncMock, patch

from test_native_verify_only_intent import IntentFixture


class VerificationCompletionRecoveryTests(IntentFixture, unittest.IsolatedAsyncioTestCase):
    async def foreign_review_writer(self, stage):
        candidate, assignment = await self.review()
        runner, effect, write = self.controller.runner, self.controller.runner._effect, self.gh.record_checkpoint
        ticket, changed, foreign, writes = self.lock.read_bytes(), False, None, None
        retire, policy, retiring = runner._retire_assignment, runner._require_policy, False
        def replace_source():
            nonlocal changed, foreign, writes
            changed = True
            self.gh.note.update(phase='implementation_done', resume_phase='correction',
                wait_reason='review_findings', next_action='diagnose_review')
            foreign, writes = copy.deepcopy(self.gh.note), len(self.gh.writes)
        def retirement(*args, **kwargs):
            nonlocal retiring
            retiring = True
            try:
                return retire(*args, **kwargs)
            finally:
                retiring = False
        def observed_policy(*args, **kwargs):
            value = policy(*args, **kwargs)
            if stage == 'retirement' and retiring and not changed:
                replace_source()
            return value
        def recorded(repo, number, record):
            value = write(repo, number, record)
            if stage == 'downgrade' and record.get('checkpoint') == 'locally_verified':
                runner.review_runs.clear()
            return value
        def racing(repo, callback, *args, **kwargs):
            nonlocal changed, foreign, writes
            planned = runner._checkpoint_ceiling.get()[3].get('record', {})
            target = ((stage == 'retirement' and planned.get('native_step') is None
                       and planned.get('phase') == 'change_review_done'
                       and planned.get('checkpoint') == 'locally_verified')
                or (planned.get('native_outcome') == 'candidate_ready'
                and ((stage == 'result' and planned.get('native_step') == assignment['step_id']
                      and planned.get('checkpoint') == 'locally_verified')
                     or (stage == 'downgrade' and planned.get('native_step') == assignment['step_id']
                         and planned.get('checkpoint') is None))))
            if not changed and kwargs.get('_checkpoint_effect') == 'progress' and target:
                replace_source()
            return effect(repo, callback, *args, **kwargs)
        with patch.object(self.gh, 'record_checkpoint', side_effect=recorded), \
             patch.object(runner, '_effect', side_effect=racing), \
             patch.object(runner, '_retire_assignment', side_effect=retirement), \
             patch.object(runner, '_require_policy', side_effect=observed_policy):
            reply = await self.call(self.finish_command(candidate, assignment))
        self.assertTrue(changed, 'The actual requested writer must be reached')
        self.assertEqual(self.gh.note, foreign, 'A review writer cannot replace a newer lifecycle')
        self.assertEqual(len(self.gh.writes), writes)
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(self.lock.read_bytes(), ticket)
        self.assertEqual(self.counter.read_text(), '1')

    async def test_review_result_writer_preserves_foreign_lifecycle(self):
        await self.foreign_review_writer('result')

    async def test_review_retirement_writer_preserves_foreign_lifecycle(self):
        await self.foreign_review_writer('retirement')

    async def test_proof_loss_downgrade_writer_preserves_foreign_lifecycle(self):
        await self.foreign_review_writer('downgrade')

    async def test_review_registration_writer_preserves_foreign_lifecycle(self):
        candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        runner, effect = self.controller.runner, self.controller.runner._effect
        changed, foreign = False, None
        def racing(repo, callback, *args, **kwargs):
            nonlocal changed, foreign
            planned = runner._checkpoint_ceiling.get()[3].get('record', {})
            if (not changed and kwargs.get('_checkpoint_effect') == 'progress'
                    and planned.get('native_step') and planned.get('native_outcome') is None):
                changed = True
                self.gh.note.update(resume_phase='correction', wait_reason='review_findings',
                    next_action='diagnose_review')
                foreign = copy.deepcopy(self.gh.note)
            return effect(repo, callback, *args, **kwargs)
        with patch.object(runner, '_effect', side_effect=racing):
            reply = await self.call(command)
        self.assertTrue(changed)
        self.assertEqual(self.gh.note, foreign, 'Registering review cannot overwrite a newer lifecycle')
        self.assertIsNone(reply.get('handoff'))
        self.assertTrue(self.lock.read_bytes(), 'Foreign progress cannot authorize ticket cleanup')
        self.assertEqual(self.counter.read_text(), '1')

    async def test_unhanded_retirement_writer_preserves_foreign_lifecycle(self):
        candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        runner = self.controller.runner
        retire, policy, write = runner._retire_assignment, runner._require_policy, self.gh.record_checkpoint
        retiring, revoked, changed, foreign = False, False, False, None
        def recorded(repo, number, record):
            nonlocal revoked
            value = write(repo, number, record)
            if record.get('native_step'):
                revoked = True
            return value
        def retirement(*args, **kwargs):
            nonlocal retiring
            retiring = True
            try:
                return retire(*args, **kwargs)
            finally:
                retiring = False
        def observed_policy(*args, **kwargs):
            nonlocal changed, foreign
            value = policy(*args, **kwargs)
            if retiring and not changed:
                changed = True
                self.gh.note.update(resume_phase='correction', wait_reason='review_findings',
                    next_action='diagnose_review')
                foreign = copy.deepcopy(self.gh.note)
            return value
        def current():
            return self.verification_grant('workflow_step.verify_only.run') if revoked else self.verification_grant()
        with patch.object(self.gh, 'record_checkpoint', side_effect=recorded), \
             patch.object(runner, '_retire_assignment', side_effect=retirement), \
             patch.object(runner, '_require_policy', side_effect=observed_policy):
            reply = await self.call(command, context_provider=current)
        self.assertTrue(changed)
        self.assertEqual(self.gh.note, foreign, 'Unhanded retirement cannot overwrite a newer lifecycle')
        self.assertIsNone(reply.get('handoff'))
        self.assertTrue(self.lock.read_bytes())
        self.assertEqual(self.counter.read_text(), '1')

    async def denied_before_intent(self, cause):
        candidate, assignment = await self.review()
        accepted = await self.call(self.finish_command(candidate, assignment))
        self.assertEqual(accepted['request']['receipt']['review'], 'accepted')
        runner, source = self.controller.runner, copy.deepcopy(self.gh.note)
        effect, read = runner._effect, self.gh.progress_source
        entered, revoked = False, False
        def current():
            return self.verification_grant('admission_set') if revoked else self.verification_grant()
        def unavailable(repo, number):
            nonlocal revoked
            if cause == 'source':
                raise OSError('synthetic source unavailable before intent')
            value = read(repo, number)
            revoked = True
            return value
        def denied(repo, callback, *args, **kwargs):
            nonlocal entered
            planned = runner._checkpoint_ceiling.get()[3].get('record', {})
            if (not entered and kwargs.get('_checkpoint_effect') == 'progress'
                    and planned.get('phase') == 'executing' and planned.get('pending_action') == 'verification'):
                entered = True
                with patch.object(self.gh, 'progress_source', side_effect=unavailable):
                    return effect(repo, callback, *args, **kwargs)
            return effect(repo, callback, *args, **kwargs)
        writes = len(self.gh.writes)
        with patch.object(runner, '_effect', side_effect=denied):
            reply = await self.call(self.fresh(candidate), context_provider=current)
        self.assertTrue(entered)
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(self.gh.note, source)
        self.assertEqual(len(self.gh.writes), writes)
        self.assertEqual(self.counter.read_text(), '1')
        revoked = False
        with patch.object(runner, '_publish', return_value={
                'action': 'waiting', 'reason': 'observed_delivery_boundary'}) as publish:
            continued = await self.advance(candidate)
        self.assertEqual(self.counter.read_text(), '1', 'A denied zero-effect request cannot invalidate accepted D')
        self.assertEqual(publish.call_count, 1)
        self.assertEqual(continued['reason'], 'observed_delivery_boundary')

    async def test_unavailable_pre_intent_source_preserves_accepted_verification(self):
        await self.denied_before_intent('source')

    async def test_revoked_pre_intent_authority_preserves_accepted_verification(self):
        await self.denied_before_intent('authority')

    async def test_pause_after_registration_recovers_same_unhanded_review_under_fresh_admission(self):
        candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        model = self.controller.runner._model
        async def paused(*args, **kwargs):
            value = await model(*args, **kwargs)
            self.control.set_mode('pause', 'example/product')
            return value
        with patch.object(self.controller.runner, '_model', side_effect=paused):
            first = await self.call(command)
        self.assertIsNone(first.get('handoff'))
        step, ticket = self.gh.note.get('native_step'), self.lock.read_bytes()
        self.assertTrue(step and ticket)
        self.assertEqual(self.control.snapshot()['projects']['example/product'], 'paused')
        self.control.set_mode('resume', 'example/product')
        fresh = self.fresh(candidate)
        fresh['parameters']['reply_profile'] = 'native_handoff_v1'
        recovered = await self.call(fresh)
        self.assertIsNotNone(recovered.get('handoff'), 'A settled unhanded review must recover after explicit Resume')
        self.assertEqual(recovered['handoff']['assignment']['step_id'], step)
        self.assertEqual(self.lock.read_bytes(), ticket)
        replay = await self.call(fresh)
        self.assertEqual(replay['handoff']['assignment']['step_id'], step)
        await self.call(command)
        self.assertEqual(self.counter.read_text(), '1')

    async def test_passing_standard_retry_reaches_independent_review_without_correction(self):
        exit_file = Path(self.tmp.name) / 'synthetic-verifier-exit'
        exit_file.write_text('7')
        original = self.real_git_assignment
        async def configured():
            argv = self.gh.cfg['verification'][0]['argv']
            argv[2] = argv[2].replace('sys.exit(int(sys.argv[2]))',
                'sys.exit(int(Path(sys.argv[2]).read_text()))')
            argv[-1] = str(exit_file)
            return await original()
        with patch.object(self, 'real_git_assignment', side_effect=configured):
            candidate = await self.candidate(7)
        failed = await self.call(self.verification_command(candidate))
        self.assertEqual(failed['request']['receipt']['verdict'], 'failed')
        self.assertEqual(self.gh.note['correction_reason'], 'verification_failure')
        exit_file.write_text('0')
        command = self.fresh(candidate)
        command['parameters']['reply_profile'] = 'standard_v1'
        passed = await self.call(command)
        self.assertEqual(passed['request']['receipt']['verdict'], 'passed')
        correction = AsyncMock(return_value={'action': 'waiting', 'reason': 'unexpected_correction'})
        with patch.object(self.controller.runner, '_correct', correction):
            review = await self.advance(candidate)
        self.assertEqual(correction.await_count, 0, 'A confirmed pass resolves the verification failure debt')
        self.assertEqual((review['action'], review['phase']), ('native_task', 'change_review'))
        self.assertEqual(self.counter.read_text(), '2')
        self.assertIsNone(self.gh.note.get('correction_reason'))
        self.assertIsNone(self.gh.note.get('correction_attempt'))
