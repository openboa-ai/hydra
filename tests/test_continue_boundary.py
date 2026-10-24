"""P06 final handoff, unknown coverage and original progress race behavior."""
import copy
import json
from dataclasses import replace
import unittest
from unittest.mock import patch

from hydra_sdlc.github import GitHubError
from hydra_sdlc.work_decisions import WorkDecisionObservation
from hydra_sdlc.public_decisions import context_basis, prepare_context
import hydra_sdlc.native as native
import hydra_sdlc.work_decisions as work_decisions
import test_continue_command as command_fixture
import test_decision_apply_command as apply_fixture
import test_native_decision_resume as fixture
import test_public_decisions as wire


class ContinueBoundaryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.NativeDecisionResumeTests.asyncSetUp
    command = command_fixture.ContinueCommandTests.command
    invoke = command_fixture.ContinueCommandTests.invoke

    async def close_pending(self):
        self.transport.error = None
        self.transport.patch_behavior = lambda body: None
        record = self.github.progress(wire.REPO, 4)
        if record and record.get('native_step'):
            await self.controller.checkpoint(self.url, record['attempt_id'], record['native_step'],
                record['native_head'], record['contract_revision'], 'stopped')

    async def test_no_progress_start_returns_an_owned_native_assignment(self):
        self.transport.rows, self.transport.direct = [], {}
        self.controller.decision_source = None
        command = self.command()
        command['parameters']['progress'] = None
        self.addAsyncCleanup(self.close_pending)
        reply = await self.invoke(command)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(reply['request']['receipt']['boundary'], 'assignment_returned')
        self.assertEqual(reply['handoff']['assignment']['step_id'],
                         self.github.progress(wire.REPO, 4)['native_step'])

    async def test_continue_cannot_escape_an_existing_checkpoint_effect_scope(self):
        token = self.controller.runner._checkpoint_ceiling.set((wire.REPO,
            self.control.snapshot()['revision'], lambda: None, {}))
        try:
            reply = await self.invoke()
        finally:
            self.controller.runner._checkpoint_ceiling.reset(token)
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.transport.effects, [])

    async def test_decision_registration_cannot_escape_an_existing_checkpoint_effect_scope(self):
        self.transport.rows = self.transport.rows[:1]
        self.transport.direct = {1: copy.deepcopy(self.transport.rows[0])}
        command = apply_fixture.DecisionApplyCommandTests.command(self)
        token = self.controller.runner._checkpoint_ceiling.set((wire.REPO,
            self.control.snapshot()['revision'], lambda: None, {}))
        try:
            reply = await self.invoke(command)
        finally:
            self.controller.runner._checkpoint_ceiling.reset(token)
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.transport.effects, [])

    async def test_pending_assignment_is_waited_without_a_second_dispatch(self):
        self.addAsyncCleanup(self.close_pending)
        first = await self.invoke()
        self.assertEqual(first['request']['outcome'], 'applied', first)
        current = self.github.progress(wire.REPO, 4)
        command = self.command()
        command['parameters']['progress'] = {name: current[name] for name in
            ('attempt_id', 'head', 'contract_revision', 'phase')}
        before = copy.deepcopy(self.transport.effects)
        received = await self.invoke(command)
        self.assertIsNone(received['handoff'])
        self.assertEqual(received['request']['outcome'], 'waiting', received)
        self.assertEqual(self.transport.effects, before)

    async def test_source_read_uses_the_remaining_budget_after_progress_io(self):
        elapsed, budgets = [0.0], []
        original_current = work_decisions.WorkDecisionGuard._current
        original_work = self.source.read_work
        def elapsed_current(guard, *, timeout=15):
            result = original_current(guard, timeout=timeout)
            elapsed[0] += 6.0
            return result
        def read(*args, timeout, **kwargs):
            budgets.append(timeout)
            return original_work(*args, timeout=timeout, **kwargs)
        self.source.read_work = read
        self.addAsyncCleanup(self.close_pending)
        with patch.object(work_decisions, 'monotonic', side_effect=lambda: elapsed[0], create=True), \
                patch.object(work_decisions.WorkDecisionGuard, '_current', elapsed_current):
            reply = await self.invoke()
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertTrue(budgets)
        self.assertTrue(all(0 < budget <= 9 for budget in budgets), budgets)

    async def test_foreign_native_context_does_not_block_a_new_legacy_start(self):
        self.transport.rows, self.transport.direct = [], {}
        self.controller.decision_source = None
        basis = context_basis(self.chosen.context)
        basis['key']['repository_id'] = 124
        self.transport.add(100, prepare_context('An unrelated repository decision.', basis).body)
        command = self.command()
        command['parameters']['progress'] = None
        self.addAsyncCleanup(self.close_pending)
        reply = await self.invoke(command)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(reply['request']['receipt']['boundary'], 'assignment_returned')

    async def test_handoff_grant_revoked_during_final_policy_read_cannot_escape(self):
        original = native.load_project
        changed = []
        def revoke(*args, **kwargs):
            record = self.github.progress(wire.REPO, 4)
            if record and record.get('native_step'):
                self.grant = replace(self.grant, operations=frozenset({'workflow_step.continue'}))
                changed.append(True)
            return original(*args, **kwargs)
        self.addAsyncCleanup(self.close_pending)
        with patch.object(native, 'load_project', side_effect=revoke):
            reply = await self.invoke()
        self.assertIsNone(reply.get('handoff'), reply)
        self.assertTrue(changed, 'The final current policy must be observed before returning an assignment.')
        self.assertNotIn('"cwd"', json.dumps(reply))
        self.assertNotIn('"prompt"', json.dumps(reply))

    async def test_incomplete_source_is_not_absence_of_a_pending_decision(self):
        self.source.read_work = lambda *args, **kwargs: WorkDecisionObservation('none', complete=False)
        reply = await self.invoke()
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertIsNone(reply.get('handoff'))
        self.assertEqual(self.transport.effects, [])

    async def test_absent_selection_does_not_discard_an_authenticated_native_claim(self):
        self.source.read_work = lambda *args, **kwargs: WorkDecisionObservation('none', complete=True)
        reply = await self.invoke()
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.transport.effects, [])

    async def test_progress_race_during_policy_read_does_not_replace_the_original_pin(self):
        original = self.controller.runner._latest
        changed = []
        def change(*args, **kwargs):
            if not changed:
                record = self.github.progress(wire.REPO, 4)
                record['phase'] = 'ready'
                self.transport.rows[0]['body'] = '<!-- hydra-progress:v1 ' + json.dumps(record) + ' -->'
                self.transport.direct[1] = copy.deepcopy(self.transport.rows[0])
                changed.append(True)
            return original(*args, **kwargs)
        command = self.command()
        with patch.object(self.controller.runner, '_latest', side_effect=change):
            reply = await self.invoke(command)
        self.assertEqual(reply['request']['reason'], 'stale_progress', reply)
        self.assertEqual(command['parameters']['progress']['phase'], 'checkpoint')
        self.assertEqual(reply['observations'][0]['value']['phase'], 'ready')
        self.assertEqual(self.transport.effects, [])

    async def test_failed_current_read_does_not_relabel_an_older_observation_as_current(self):
        def fail(body):
            progress = json.loads(body.split('<!-- hydra-progress:v1 ', 1)[1].split(' -->', 1)[0])
            if progress.get('native_step'):
                self.transport.error = GitHubError('private-current-source-canary')
        self.transport.patch_behavior = fail
        self.addAsyncCleanup(self.close_pending)
        reply = await self.invoke()
        self.assertEqual(reply['request']['outcome'], 'unknown', reply)
        self.assertEqual(reply['observations'], [], 'Failed fresh coverage must not re-stamp the prior source.')
        self.assertNotIn('private-current-source-canary', json.dumps(reply))
