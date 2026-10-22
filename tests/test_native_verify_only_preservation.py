"""A drained verifier preserves its result under current authority without new work."""
import asyncio
from pathlib import Path
import unittest
from unittest.mock import patch

from hydra_sdlc.operations import OperationDenied
import test_native_verify_only_contract as fixture
from test_workspace import git


class VerificationPreservationTests(unittest.IsolatedAsyncioTestCase):
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

    async def paused_run(self, *, revoke=False, mutate=False):
        ready = Path(self.tmp.name) / 'verification-ready'
        release = Path(self.tmp.name) / 'verification-release'
        original = self.real_git_assignment
        async def configure():
            argv = self.gh.cfg['verification'][0]['argv']
            mutation = "Path('src/main.py').write_text('stopped_verifier_edit = True' + chr(10)); " if mutate else ''
            gate = mutation + """Path(sys.argv[3]).write_text('ready')
while not Path(sys.argv[4]).exists():
    time.sleep(.02)
print("""
            argv[2] = 'import time; ' + argv[2].replace('print(', gate)
            argv.extend([str(ready), str(release)])
            return await original()
        with patch.object(self, 'real_git_assignment', side_effect=configure):
            candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        revoked = False
        def context():
            return self.verification_grant('admission_set') if revoked else self.verification_grant()
        running = asyncio.create_task(self.call(command, context_provider=context))
        async def started():
            while not ready.exists():
                await asyncio.sleep(.02)
        try:
            await asyncio.wait_for(started(), 15)
            revoked = revoke
            self.control.set_mode('pause', 'example/product')
            reply = await asyncio.wait_for(running, 20)
        finally:
            release.write_text('released')
            if not running.done():
                running.cancel()
                try:
                    await running
                except asyncio.CancelledError:
                    pass
        return candidate, reply

    def fresh(self, candidate):
        command = self.verification_command(candidate)
        command['request_id'] = '99999999-9999-4999-8999-999999999999'
        return command

    async def advance(self, candidate):
        return await self.controller.advance(self.url, candidate['attempt_id'],
            candidate['head'], candidate['contract_revision'])

    async def test_running_pause_records_the_drained_hold_and_preserves_modes(self):
        candidate, reply = await self.paused_run()
        self.assertIsNone(self.gh.note.get('pending_action'),
                          'A stale dispatch revision must not strand confirmed owned cleanup')
        self.assertEqual(self.gh.note['phase'], 'implementation_done')
        self.assertEqual(self.gh.note['wait_reason'], 'replan_required')
        self.assertIsNone(reply['request']['receipt'])
        state = self.control.snapshot()
        self.assertEqual(state['global_mode'], 'running')
        self.assertEqual(state['projects'], {'example/product': 'paused'})
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')
        self.control.set_mode('resume', 'example/product')
        await self.call(self.fresh(candidate))
        self.assertEqual(self.counter.read_text(), '1')
        self.controller = self.new_controller()
        self.controller.runner.operations = self.control
        self.assertEqual((await self.advance(candidate))['reason'], 'replan_required')
        self.assertEqual(self.counter.read_text(), '1')

    async def test_regrant_reconciles_retained_completion_under_the_new_revision(self):
        candidate, _ = await self.paused_run(revoke=True)
        self.assertEqual(self.gh.note['pending_action'], 'verification')
        self.control.set_mode('resume', 'example/product')
        reply = await self.call(self.fresh(candidate))
        self.assertIsNone(self.gh.note.get('pending_action'),
                          'Fresh authority must reconcile the retained end witness before new D')
        self.assertEqual(self.gh.note['wait_reason'], 'replan_required')
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(self.counter.read_text(), '1')

    async def test_restart_without_end_evidence_cannot_repeat_an_executing_intent(self):
        candidate, _ = await self.paused_run(revoke=True)
        self.control.set_mode('resume', 'example/product')
        self.controller = self.new_controller()
        self.controller.runner.operations = self.control
        reply = await self.call(self.fresh(candidate))
        self.assertEqual(self.counter.read_text(), '1',
                         'A lost private witness is unknown, not permission to repeat D')
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual((await self.advance(candidate))['reason'], 'verification_unconfirmed')
        self.assertEqual(self.counter.read_text(), '1')

    async def test_late_pause_preserves_passed_D_and_resume_reaches_review_without_D(self):
        candidate = await self.candidate(0)
        verify = self.ws.verify
        def completed(*args, **kwargs):
            value = verify(*args, **kwargs)
            self.control.set_mode('pause', 'example/product')
            return value
        with patch.object(self.ws, 'verify', side_effect=completed):
            reply = await self.call(self.verification_command(candidate))
        self.assertIsNotNone(reply['request']['receipt'],
                             'A completed invocation must not be discarded at the preservation boundary')
        self.assertEqual(reply['request']['receipt']['verdict'], 'passed')
        self.assertNotIn('native_step', self.gh.note)
        self.assertEqual(self.control.snapshot()['projects']['example/product'], 'paused')
        self.control.set_mode('resume', 'example/product')
        assignment = await self.advance(candidate)
        self.assertEqual((assignment.get('phase'), assignment.get('mode')), ('change_review', 'read_only'))
        self.assertEqual(self.counter.read_text(), '1')

    async def test_pause_preserves_actual_owned_verifier_edits_once(self):
        candidate, reply = await self.paused_run(mutate=True)
        head = git(self.path, 'rev-parse', 'HEAD')
        self.assertNotEqual(head, candidate['head'], 'Confirmed stopped edits need their owned checkpoint')
        self.assertEqual(self.gh.note['head'], head)
        self.assertEqual((self.path / 'src/main.py').read_text(), 'stopped_verifier_edit = True' + chr(10))
        self.assertEqual(git(self.path, 'rev-list', '--count', candidate['head'] + '..HEAD'), '1')
        self.assertFalse(self.ws.inspect(self.path)['dirty'])
        self.assertIsNone(reply['request']['receipt'])
        self.assertNotIn('native_step', self.gh.note)
        self.assertEqual(self.control.snapshot()['projects']['example/product'], 'paused')
        self.assertEqual(self.counter.read_text(), '1')

    async def test_preservation_scope_forbids_review_and_publish_even_when_running(self):
        candidate = await self.candidate(0)
        command = self.verification_command(candidate)
        command['parameters']['reply_profile'] = 'native_handoff_v1'
        runner, attempted = self.controller.runner, []
        record = runner._record
        def checked(repo, number, value, **changes):
            planned = runner._record_values(value, **changes)
            if (planned.get('phase') == 'implementation_done' and planned.get('next_action') == 'change_review'
                    and not planned.get('native_step')):
                with self.assertRaises(OperationDenied):
                    runner._effect(repo, lambda: attempted.append('review'), _checkpoint_effect='review_assignment')
                with self.assertRaises(OperationDenied):
                    runner._workspace_effect(repo, 'publish', self.path)
            return record(repo, number, value, **changes)
        with patch.object(runner, '_record', side_effect=checked):
            reply = await self.call(command)
        self.assertEqual(attempted, [])
        self.assertEqual(reply['request']['receipt']['verdict'], 'passed')
        self.assertIsNotNone(reply['handoff'], 'The later authorized review remains outside preservation')
        self.assertEqual(self.counter.read_text(), '1')
