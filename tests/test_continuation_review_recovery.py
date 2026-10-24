"""Regression oracles for observed P06 progress races and partial stopped recovery."""
import copy
import json
import unittest
from unittest.mock import patch

from hydra_sdlc.github import GitHubError
from hydra_sdlc.work_decisions import WorkDecisionObservation
import test_continue_boundary as boundary
import test_public_decisions as wire


class ContinuationRecoveryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = boundary.ContinueBoundaryTests.asyncSetUp
    command = boundary.ContinueBoundaryTests.command
    invoke = boundary.ContinueBoundaryTests.invoke

    async def close_pending(self):
        record = self.github.progress(wire.REPO, 4)
        if (record and record.get('native_outcome') == 'stopped'
                and self.controller.lock_path.read_bytes() == b''):
            return  # This fixture already has positive stop and released ownership.
        await boundary.ContinueBoundaryTests.close_pending(self)

    def set_progress(self, record):
        self.transport.rows[0]['body'] = '<!-- hydra-progress:v1 ' + json.dumps(record) + ' -->'
        self.transport.direct[1] = copy.deepcopy(self.transport.rows[0])

    def pin_current(self):
        command = self.command()
        record = self.github.progress(wire.REPO, 4)
        command['parameters']['progress'] = {key: record[key] for key in
            ('attempt_id', 'head', 'contract_revision', 'phase')}
        return command

    async def test_decision_wait_created_during_writer_guard_is_preserved(self):
        record = self.github.progress(wire.REPO, 4)
        record.update(phase='ready', wait_reason=None, next_action='implementation', resume_phase=None)
        self.set_progress(record)
        self.transport.rows = self.transport.rows[:1]
        self.transport.direct = {1: copy.deepcopy(self.transport.rows[0])}
        active, changed = [False], []
        runner, original = self.controller.runner, self.controller.runner._effect

        def effect(repo, callback, *args, **kwargs):
            previous = active[0]
            active[0] = kwargs.get('_checkpoint_effect') == 'progress'
            try:
                return original(repo, callback, *args, **kwargs)
            finally:
                active[0] = previous

        def read(*args, **kwargs):
            if active[0] and not changed:
                latest = self.github.progress(wire.REPO, 4)
                latest.update(phase='checkpoint', wait_reason='product_decision',
                              next_action='operator_decision', resume_phase='implementation')
                self.set_progress(latest)
                changed.append(copy.deepcopy(latest))
            return WorkDecisionObservation('none', complete=True)

        self.source.read_work = read
        self.addAsyncCleanup(self.close_pending)
        with patch.object(runner, '_effect', side_effect=effect):
            reply = await self.invoke(self.pin_current())
        self.assertEqual(len(changed), 1, 'The race must occur inside the progress-writer guard.')
        self.assertEqual(self.github.progress(wire.REPO, 4), changed[0], reply)
        self.assertIsNone(reply.get('handoff'))
        self.assertEqual(self.transport.effects, [], 'The newly observed decision wait must not be overwritten.')
        self.assertEqual(self.controller.lock_path.read_bytes(), b'',
                         'A positively undispatched local ticket must not strand the work.')

    async def test_unknown_assignment_write_retains_its_exact_ticket(self):
        def unavailable(body):
            record = json.loads(body.split('<!-- hydra-progress:v1 ', 1)[1].split(' -->', 1)[0])
            if record.get('native_step'):
                self.transport.rows[0]['body'] = body
                self.transport.direct[1] = copy.deepcopy(self.transport.rows[0])
                raise GitHubError('fixture lost assignment acknowledgment', uncertain=True)
        self.transport.patch_behavior = unavailable
        self.addAsyncCleanup(self.close_pending)
        reply = await self.invoke()
        self.assertIsNone(reply.get('handoff'))
        record = self.github.progress(wire.REPO, 4)
        self.assertTrue(record.get('native_step'), reply)
        self.assertIn(record['native_step'].encode(), self.controller.lock_path.read_bytes())

    async def test_stopped_after_ticket_release_recovers_through_typed_continue(self):
        self.addAsyncCleanup(self.close_pending)
        first = await self.invoke()
        assignment = first['handoff']['assignment']
        failed = []

        def fail_retirement(body):
            record = json.loads(body.split('<!-- hydra-progress:v1 ', 1)[1].split(' -->', 1)[0])
            if not record.get('native_step'):
                failed.append(True)
                raise GitHubError('fixture final stopped retirement failed', uncertain=True)

        self.transport.patch_behavior = fail_retirement
        with self.assertRaises(GitHubError):
            await self.controller.checkpoint(self.url, assignment['attempt_id'], assignment['step_id'],
                assignment['head'], assignment['contract_revision'], 'stopped')
        self.assertEqual(failed, [True])
        stopped = self.github.progress(wire.REPO, 4)
        self.assertEqual(stopped['native_outcome'], 'stopped')
        self.assertEqual(self.controller.lock_path.read_bytes(), b'')
        self.transport.patch_behavior = lambda body: None
        received = await self.invoke(self.pin_current())
        self.assertEqual(received['request']['outcome'], 'applied', received)
        successor = received['handoff']['assignment']
        self.assertNotEqual(successor['step_id'], assignment['step_id'])
        self.assertEqual(successor['attempt_id'], assignment['attempt_id'])
        self.assertEqual(self.github.progress(wire.REPO, 4)['native_step'], successor['step_id'])
