"""EX9 source races, typed entry and one-dispatch mutable-write boundaries."""
import copy
from dataclasses import replace
import json
import unittest
from unittest.mock import patch

from hydra_sdlc.github import GitHubError
from hydra_sdlc.native import NativeController
from hydra_sdlc.public_decisions import context_basis, prepare_context, receipt_body
import test_continuation_review_recovery as recovery
import test_decision_apply_command as apply_fixture
import test_decision_protocol as domain
import test_native_technical_replan as technical
import test_public_decisions as wire


class TechnicalReplanBoundaryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = technical.NativeTechnicalReplanTests.asyncSetUp
    close_pending = technical.NativeTechnicalReplanTests.close_pending
    consume = technical.NativeTechnicalReplanTests.consume
    stop = technical.NativeTechnicalReplanTests.stop
    record = technical.NativeTechnicalReplanTests.record
    ready = technical.NativeTechnicalReplanTests.ready
    begin = technical.NativeTechnicalReplanTests.begin

    async def test_typed_replan_returns_actual_successor_without_rewriting_the_input_pin(self):
        await self.consume()
        old = self.ready()
        command = recovery.ContinuationRecoveryTests.command(self)
        command['parameters']['progress'] = {key: old[key] for key in
            ('attempt_id', 'head', 'contract_revision', 'phase')}
        before = copy.deepcopy(command['parameters']['progress'])
        received = await recovery.ContinuationRecoveryTests.invoke(self, command)
        self.assertEqual(received['request']['outcome'], 'applied', received)
        assignment = received['handoff']['assignment']
        self.assertNotEqual(assignment['attempt_id'], old['attempt_id'])
        self.assertEqual(received['request']['receipt']['attempt_id'], assignment['attempt_id'])
        self.assertEqual(command['parameters']['progress'], before)

    async def test_authorization_edit_during_source_coverage_prevents_dispatch(self):
        await self.consume()
        self.ready()
        reads = []
        def changed(value):
            reads.append(True)
            if len(reads) == 2:
                row = self.transport.rows[-1]
                row['updated_at'] = '2026-01-02T00:00:00Z'
                self.transport.direct[row['id']] = copy.deepcopy(row)
            return value
        self.source.coverage_transform = changed
        effects = copy.deepcopy(self.transport.effects)
        received = await self.begin()
        self.assertNotEqual(received['action'], 'native_task', received)
        self.assertEqual(self.transport.effects, effects)

    async def test_first_observed_count_cannot_decrease_before_dispatch(self):
        await self.consume()
        self.ready()
        reads = []
        def history(value):
            reads.append(True)
            return replace(value, writes=2, state='not_applied') if len(reads) == 1 else value
        self.source.coverage_transform = history
        self.source.history_transform = lambda value: replace(value, effects=tuple(
            replace(fact, writes=2, state='not_applied') for fact in value.effects))
        effects = copy.deepcopy(self.transport.effects)
        received = await self.begin()
        self.assertGreaterEqual(len(reads), 2)
        self.assertNotEqual(received['action'], 'native_task', received)
        self.assertEqual(self.transport.effects, effects,
                         'A lower count cannot erase the first original-source observation.')
        repeated = await self.begin()
        self.assertNotEqual(repeated['action'], 'native_task', repeated)
        self.assertEqual(self.transport.effects, effects, 'A later call must retain the observed maximum too.')

    async def test_changed_progress_during_source_coverage_is_preserved(self):
        await self.consume()
        self.ready()
        reads, changed = [], []
        def alter(value):
            reads.append(True)
            if len(reads) == 2:
                record = self.github.progress(wire.REPO, 4)
                record.update(phase='checkpoint', wait_reason='product_decision', next_action='operator_decision')
                body = self.transport.rows[0]['body']
                start, rest = body.split('<!-- hydra-progress:v1 ', 1)
                _, suffix = rest.split(' -->', 1)
                self.transport.rows[0]['body'] = start + '<!-- hydra-progress:v1 ' + json.dumps(record) + ' -->' + suffix
                self.transport.direct[1] = copy.deepcopy(self.transport.rows[0])
                changed.append(record)
            return value
        self.source.coverage_transform = alter
        effects = copy.deepcopy(self.transport.effects)
        received = await self.begin()
        self.assertNotEqual(received['action'], 'native_task', received)
        self.assertEqual(self.github.progress(wire.REPO, 4), changed[0])
        self.assertEqual(self.transport.effects, effects)

    async def test_a_permit_cannot_be_reused_after_an_uncertain_dispatch(self):
        await self.consume()
        old = self.ready()
        captured = []
        original = self.github.record_checkpoint
        def retain(*args, **kwargs):
            if kwargs.get('decision_successor') is not None:
                captured.append((args, kwargs))
            return original(*args, **kwargs)
        def lost(body):
            if technical.progress_body(body)['attempt_id'] != old['attempt_id']:
                raise GitHubError('fixture uncertain dispatch', uncertain=True)
        self.transport.patch_behavior = lost
        with patch.object(self.github, 'record_checkpoint', side_effect=retain):
            received = await self.begin()
        self.assertNotEqual(received['action'], 'native_task', received)
        self.assertEqual(len(captured), 1)
        effects = copy.deepcopy(self.transport.effects)
        with self.assertRaises(GitHubError):
            original(*captured[0][0], **captured[0][1])
        self.assertEqual(self.transport.effects, effects)

    async def test_a_known_unknown_successor_blocks_conflicting_answer_consumption(self):
        await self.consume()
        old = self.ready()
        def lost(body):
            if technical.progress_body(body)['attempt_id'] != old['attempt_id']:
                raise GitHubError('fixture unknown mutable successor', uncertain=True)
        self.transport.patch_behavior = lost
        self.assertNotEqual((await self.begin())['action'], 'native_task')
        self.transport.patch_behavior = lambda body: None
        predecessor = self.chosen.context
        self.record(phase='checkpoint', wait_reason='product_decision', next_action='operator_decision')
        basis = context_basis(predecessor)
        basis.update(key={**basis['key'], 'round': 2}, resume_attempt='33333333-3333-4333-8333-333333333333',
            supersedes={'key': context_basis(predecessor)['key'], 'context_sha256': predecessor.sha256})
        selected = prepare_context('Use the amended contract.', basis)
        self.source.chosen = replace(self.chosen, context=selected, predecessor=predecessor,
            replacement=domain.evidence('replacement'), replan=domain.evidence('replan'))
        self.transport.add(500, selected.body)
        self.transport.add(501, receipt_body(selected))
        effects = copy.deepcopy(self.transport.effects)
        received = await self.begin()
        self.assertNotEqual(received['action'], 'native_task', received)
        self.assertEqual(self.transport.effects, effects)

    async def test_restart_does_not_turn_an_unknown_successor_into_no_history(self):
        await self.consume()
        old = self.ready()
        def lost(body):
            if technical.progress_body(body)['attempt_id'] != old['attempt_id']:
                raise GitHubError('fixture unknown mutable successor', uncertain=True)
        self.transport.patch_behavior = lost
        self.assertNotEqual((await self.begin())['action'], 'native_task')
        self.transport.patch_behavior = lambda body: None
        self.controller = NativeController(self.github, self.workspace, repos=[wire.REPO], host_alias='fixture',
            lock_path=self.controller.lock_path, operations=self.control)
        self.controller.decision_source = self.source
        self.assertEqual(self.controller.runner.technical_replan_attempts, {})
        predecessor = self.chosen.context
        self.record(phase='checkpoint', wait_reason='product_decision', next_action='operator_decision')
        basis = context_basis(predecessor)
        basis.update(key={**basis['key'], 'round': 2}, resume_attempt='33333333-3333-4333-8333-333333333333',
            supersedes={'key': context_basis(predecessor)['key'], 'context_sha256': predecessor.sha256})
        selected = prepare_context('Use the amended contract.', basis)
        self.source.chosen = replace(self.chosen, context=selected, predecessor=predecessor,
            replacement=domain.evidence('replacement'), replan=domain.evidence('replan'))
        self.transport.add(500, selected.body)
        self.transport.add(501, receipt_body(selected))
        effects = copy.deepcopy(self.transport.effects)
        received = await self.begin()
        self.assertNotEqual(received['action'], 'native_task', received)
        self.assertEqual(self.transport.effects, effects)

    async def test_incomplete_original_work_history_prevents_a_native_effect(self):
        await self.consume()
        self.ready()
        self.source.history_transform = lambda value: replace(value, complete=False)
        effects = copy.deepcopy(self.transport.effects)
        received = await self.begin()
        self.assertNotEqual(received['action'], 'native_task', received)
        self.assertEqual(self.transport.effects, effects)

    async def test_original_history_must_include_locally_known_attempted_keys(self):
        await self.consume()
        old = self.ready()
        def lost(body):
            if technical.progress_body(body)['attempt_id'] != old['attempt_id']:
                raise GitHubError('fixture unknown mutable successor', uncertain=True)
        self.transport.patch_behavior = lost
        self.assertNotEqual((await self.begin())['action'], 'native_task')
        self.source.history_transform = lambda value: replace(value, effects=())
        effects = copy.deepcopy(self.transport.effects)
        received = await self.begin()
        self.assertNotEqual(received['action'], 'native_task', received)
        self.assertIn((123, 4, old['attempt_id']), self.source.history_requests[-1])
        self.assertEqual(self.transport.effects, effects)

    async def test_definitive_original_nonapplication_allows_an_amendment_after_restart(self):
        await self.consume()
        old = self.ready()
        def lost(body):
            if technical.progress_body(body)['attempt_id'] != old['attempt_id']:
                raise GitHubError('fixture unknown mutable successor', uncertain=True)
        self.transport.patch_behavior = lost
        self.assertNotEqual((await self.begin())['action'], 'native_task')
        self.transport.patch_behavior = lambda body: None
        self.controller = NativeController(self.github, self.workspace, repos=[wire.REPO], host_alias='fixture',
            lock_path=self.controller.lock_path, operations=self.control)
        self.controller.decision_source = self.source
        self.source.technical_state = 'not_applied'
        predecessor = self.chosen.context
        self.record(phase='checkpoint', wait_reason='product_decision', next_action='operator_decision')
        basis = context_basis(predecessor)
        basis.update(key={**basis['key'], 'round': 2}, resume_attempt='33333333-3333-4333-8333-333333333333',
            supersedes={'key': context_basis(predecessor)['key'], 'context_sha256': predecessor.sha256})
        selected = prepare_context('Use the amended contract.', basis)
        self.source.chosen = replace(self.chosen, context=selected, predecessor=predecessor,
            replacement=domain.evidence('replacement'), replan=domain.evidence('replan'))
        self.transport.add(500, selected.body)
        self.transport.add(501, receipt_body(selected))
        received = await self.begin()
        self.assertEqual(received['action'], 'native_task', received)
        self.assertEqual(received['attempt_id'], basis['resume_attempt'])
        self.assertEqual(self.github.decision_progress_source(wire.REPO, 4)['native_root']['decision']['context_sha256'], selected.sha256)

    async def test_unknown_successor_blocks_amended_public_pair_registration(self):
        await self.consume()
        old = self.ready()
        def lost(body):
            if technical.progress_body(body)['attempt_id'] != old['attempt_id']:
                raise GitHubError('fixture unknown mutable successor', uncertain=True)
        self.transport.patch_behavior = lost
        self.assertNotEqual((await self.begin())['action'], 'native_task')
        self.transport.patch_behavior = lambda body: None
        self.controller = NativeController(self.github, self.workspace, repos=[wire.REPO], host_alias='fixture',
            lock_path=self.controller.lock_path, operations=self.control)
        self.controller.decision_source = self.source
        predecessor = self.chosen.context
        self.record(phase='checkpoint', wait_reason='product_decision', next_action='operator_decision')
        basis = context_basis(predecessor)
        basis.update(key={**basis['key'], 'round': 2}, resume_attempt='33333333-3333-4333-8333-333333333333',
            supersedes={'key': context_basis(predecessor)['key'], 'context_sha256': predecessor.sha256})
        self.source.chosen = replace(self.chosen, context=prepare_context('Use the amended contract.', basis),
            predecessor=predecessor, replacement=domain.evidence('replacement'), replan=domain.evidence('replan'))
        command = apply_fixture.DecisionApplyCommandTests.command(self)
        command['parameters']['round'] = 2
        command['effect_key'] = 'decision:' + wire.ATTEMPT + ':2'
        command['expected']['source_checks'] = [self.source.chosen.proposal.source_check()]
        effects = copy.deepcopy(self.transport.effects)
        received = await apply_fixture.DecisionApplyCommandTests.invoke(self, command)
        self.assertEqual(received['request']['reason'], 'technical_replan_unconfirmed', received)
        self.assertNotEqual(received['request']['outcome'], 'applied', received)
        self.assertEqual(self.transport.effects, effects)
