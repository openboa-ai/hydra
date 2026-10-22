"""Actual child counts distinguish no launch, drained work and unknown cleanup."""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hydra_sdlc.control import load_host_config
from hydra_sdlc.operations import OperationDenied
from hydra_sdlc.runtime_identity import capture_runtime_identity
from hydra_sdlc.workspace import WorkspaceWait
import test_native_verify_only_preservation as fixture
from test_workspace import git


class LaunchFixture:
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

    def after_intent(self, callback):
        original = self.controller.runner._intent
        def checked(repo, number, config, record, action, **changes):
            value = original(repo, number, config, record, action, **changes)
            if action == 'verification' and value is not None:
                callback()
            return value
        return patch.object(self.controller.runner, '_intent', side_effect=checked)

    async def revoked_before_launch(self):
        pin = await self.candidate(0)
        self.revoked = False
        def context():
            return self.verification_grant('admission_set') if self.revoked else self.verification_grant()
        with self.after_intent(lambda: setattr(self, 'revoked', True)):
            reply = await self.call(self.verification_command(pin), context_provider=context)
        return pin, reply, context


class VerificationNoDispatchTests(LaunchFixture, unittest.IsolatedAsyncioTestCase):
    async def test_final_pause_restores_ack_lost_intent_without_checkpoint_or_new_work(self):
        pin = await self.candidate(0)
        runner = self.controller.runner
        record, write = runner._record, self.gh.record_checkpoint
        checks, attempted = [], []
        def checked(repo, number, value, **changes):
            planned = runner._record_values(value, **changes)
            if planned.get('phase') == 'implementation_done' and not self.counter.exists():
                with self.assertRaises(OperationDenied):
                    runner._workspace_effect(repo, 'checkpoint', self.path, 'Forbidden unstarted checkpoint')
                with self.assertRaises(OperationDenied):
                    runner._workspace_effect(repo, 'publish', self.path)
                checks.append('closed')
            return record(repo, number, value, **changes)
        def lost(repo, number, value):
            result = write(repo, number, value)
            if value.get('phase') == 'implementation_done' and not self.counter.exists():
                attempted.append('restore')
                raise OSError('synthetic restoration ACK loss')
            return result
        with patch.object(runner, '_record', side_effect=checked), \
             patch.object(self.gh, 'record_checkpoint', side_effect=lost), \
             self.after_intent(lambda: self.control.set_mode('pause', 'example/product')):
            reply = await self.call(self.verification_command(pin))
        self.assertIsNone(self.gh.note.get('pending_action'), 'A positively undispatched intent must be restored')
        self.assertEqual(self.gh.note['phase'], 'implementation_done')
        self.assertEqual((checks, attempted), (['closed'], ['restore']))
        self.assertFalse(self.counter.exists())
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(self.control.snapshot()['projects']['example/product'], 'paused')
        self.assertEqual(git(self.path, 'rev-parse', 'HEAD'), pin['head'])
        self.control.set_mode('resume', 'example/product')
        self.controller = self.new_controller(); self.controller.runner.operations = self.control
        completed = await self.call(self.fresh(pin))
        self.assertEqual(completed['request']['receipt']['verdict'], 'passed')
        self.assertEqual(self.counter.read_text(), '1')
        review = await self.advance(pin)
        self.assertEqual((review.get('phase'), review.get('mode')), ('change_review', 'read_only'))
        self.assertEqual(self.counter.read_text(), '1')

    async def test_pause_in_intent_postcheck_restores_before_the_dispatch_window(self):
        pin = await self.candidate(0)
        runner, paused = self.controller.runner, False
        latest = runner._latest
        def checked(*args, **kwargs):
            nonlocal paused
            if (not paused and self.gh.note.get('phase') == 'executing'
                    and self.gh.note.get('pending_action') == 'verification'):
                self.control.set_mode('pause', 'example/product'); paused = True
            return latest(*args, **kwargs)
        with patch.object(runner, '_latest', side_effect=checked):
            await self.call(self.verification_command(pin))
        self.assertTrue(paused)
        self.assertIsNone(self.gh.note.get('pending_action'), 'The typed owner must settle postcheck denial too')
        self.assertFalse(self.counter.exists())
        self.control.set_mode('resume', 'example/product')
        completed = await self.call(self.fresh(pin))
        self.assertEqual(completed['request']['receipt']['verdict'], 'passed')
        self.assertEqual(self.counter.read_text(), '1')

    async def test_foreign_edits_are_preserved_without_checkpoint_and_same_request_can_retry(self):
        pin = await self.candidate(0)
        main = self.path/'src/main.py'; original = main.read_text()
        command = self.verification_command(pin)
        with self.after_intent(lambda: main.write_text('external actor edit\n')):
            reply = await self.call(command)
        self.assertIsNone(self.gh.note.get('pending_action'), 'No-launch recovery must not depend on clean user edits')
        self.assertIsNone(reply['request']['receipt'])
        self.assertFalse(self.counter.exists())
        self.assertEqual(main.read_text(), 'external actor edit\n')
        self.assertEqual(git(self.path, 'rev-parse', 'HEAD'), pin['head'])
        self.assertTrue(self.ws.inspect(self.path)['dirty'])
        main.write_text(original)
        completed = await self.call(command)
        self.assertEqual(completed['request']['receipt']['verdict'], 'passed')
        self.assertEqual(self.counter.read_text(), '1')
        await self.call(command)
        self.assertEqual(self.counter.read_text(), '1')

    async def test_revoked_grant_writes_no_restoration_and_regrant_recovers_before_one_run(self):
        pin, first, context = await self.revoked_before_launch()
        self.assertIsNone(first['request']['receipt'])
        self.assertEqual(self.gh.note['pending_action'], 'verification')
        self.assertFalse(self.counter.exists())
        self.revoked = False
        fresh = self.fresh(pin)
        recovered = await self.call(fresh, context_provider=context)
        self.assertIsNone(self.gh.note.get('pending_action'), 'Current regrant must reconcile the retained no-launch witness')
        self.assertIsNone(recovered['request']['receipt'])
        self.assertFalse(self.counter.exists())
        completed = await self.call(fresh, context_provider=context)
        self.assertEqual(completed['request']['receipt']['verdict'], 'passed')
        await self.call(fresh, context_provider=context)
        self.assertEqual(self.counter.read_text(), '1')

    async def test_lost_no_launch_witness_remains_unknown_without_inventing_a_dispatch(self):
        pin, _, _ = await self.revoked_before_launch()
        self.controller = self.new_controller(); self.controller.runner.operations = self.control
        reply = await self.call(self.fresh(pin))
        self.assertIsNone(reply['request']['receipt'])
        self.assertFalse(self.counter.exists())
        self.assertEqual((await self.advance(pin))['reason'], 'verification_unconfirmed')
        self.assertFalse(self.counter.exists())

    async def test_unapplied_restoration_is_read_back_without_reposting_or_launching(self):
        pin = await self.candidate(0)
        main = self.path/'src/main.py'; original = main.read_text()
        write, attempts = self.gh.record_checkpoint, []
        def unavailable(repo, number, value):
            if value.get('phase') == 'implementation_done' and not self.counter.exists():
                attempts.append('restore')
                raise OSError('synthetic unapplied restoration')
            return write(repo, number, value)
        command = self.verification_command(pin)
        with patch.object(self.gh, 'record_checkpoint', side_effect=unavailable), \
             self.after_intent(lambda: main.write_text('external actor edit\n')):
            first = await self.call(command)
        self.assertEqual(attempts, ['restore'], 'The original no-launch intent needs one bounded restoration attempt')
        self.assertIsNone(first['request']['receipt'])
        main.write_text(original)
        await self.call(command); await self.call(self.fresh(pin))
        self.assertEqual(attempts, ['restore'])
        self.assertFalse(self.counter.exists())
        self.assertEqual(self.gh.note['pending_action'], 'verification')
        self.assertEqual((await self.advance(pin))['reason'], 'verification_unconfirmed')


class VerificationProviderPreparationTests(LaunchFixture, unittest.IsolatedAsyncioTestCase):
    async def provider_candidate(self, exception):
        original = self.real_git_assignment
        async def configure():
            self.gh.cfg['verification'] *= 2
            return await original()
        with patch.object(self, 'real_git_assignment', side_effect=configure):
            pin = await self.candidate(0)
        self.settings.write_text(self.settings.read_text()+'storage_provider = "fixture_launch:create"\n')
        self.controller.runtime_identity = capture_runtime_identity(load_host_config(self.settings), self.control)
        calls = []
        def wrap(path, argv, cwd):
            calls.append(argv)
            if len(calls) == 2:
                raise exception
            return argv
        self.ws.storage_provider = SimpleNamespace(wrap_command=wrap)
        return pin, calls

    async def deterministic_provider_failure(self, exception):
        pin, calls = await self.provider_candidate(exception)
        command = self.verification_command(pin)
        reply = await self.call(command)
        self.assertIsNone(self.gh.note.get('pending_action'), 'A constructor failure after drained work must settle diagnosis')
        self.assertEqual(self.gh.note['wait_reason'], 'replan_required')
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual((len(calls), self.counter.read_text()), (2, '1'))
        await self.call(command); await self.call(self.fresh(pin))
        self.assertEqual((len(calls), self.counter.read_text()), (2, '1'))
        self.assertEqual((await self.advance(pin))['reason'], 'replan_required')
        self.ws.storage_provider = None
        self.settings.write_text(self.settings.read_text().replace('storage_provider = "fixture_launch:create"\n', ''))
        self.controller = self.new_controller(); self.controller.runner.operations = self.control
        self.assertEqual((await self.advance(pin))['reason'], 'replan_required')
        self.assertEqual(self.counter.read_text(), '1')

    async def test_provider_value_error_after_first_command_settles_without_repeating_it(self):
        await self.deterministic_provider_failure(ValueError('synthetic wrapper preparation error'))

    async def test_provider_runtime_error_after_first_command_settles_without_repeating_it(self):
        await self.deterministic_provider_failure(RuntimeError('synthetic wrapper preparation error'))

    async def test_explicit_provider_uncertainty_is_not_reclassified_as_confirmed_end(self):
        pin, calls = await self.provider_candidate(WorkspaceWait('fixture_provider_uncertain', uncertain=True))
        reply = await self.call(self.verification_command(pin))
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(self.controller.runner.host_hold_reason, 'host_verification_unconfirmed')
        self.assertEqual(self.gh.note['pending_action'], 'verification')
        self.assertEqual((len(calls), self.counter.read_text()), (2, '1'))

    async def test_untyped_worker_failure_outside_preparation_remains_unknown(self):
        pin = await self.candidate(0)
        verify = self.ws.verify
        def unknown(*args, **kwargs):
            verify(*args, **kwargs)
            raise RuntimeError('synthetic untyped worker failure')
        command = self.verification_command(pin)
        with patch.object(self.ws, 'verify', side_effect=unknown):
            reply = await self.call(command)
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(self.gh.note['pending_action'], 'verification')
        await self.call(command); await self.call(self.fresh(pin))
        self.assertEqual((await self.advance(pin))['reason'], 'verification_unconfirmed')
        self.assertEqual(self.counter.read_text(), '1')
