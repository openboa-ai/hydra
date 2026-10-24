"""EX9 positive continuity, answer amendment and uncertain technical-write oracles."""
import copy
from dataclasses import replace
import json
import re
import unittest

from hydra_sdlc.decision_coordinator import DecisionSnapshot
from hydra_sdlc.decision_protocol import DecisionCallCoverage
from hydra_sdlc.github import GitHubError
from hydra_sdlc.native import NativeController
from hydra_sdlc.public_decisions import context_basis, prepare_context, receipt_body
import test_continuation_review_recovery as recovery
import test_decision_protocol as domain
import test_native_decision_resume as fixture
import test_public_decisions as wire


def progress_body(body):
    found = re.search(r'<!-- hydra-progress:v1 (.*?) -->', body)
    return json.loads(found[1]) if found else None


class ReplanSource(fixture.WorkSource):
    def __init__(self, *args):
        super().__init__(*args)
        self.technical_state, self.coverage_transform = 'unconfirmed', lambda value: value
        self.intents = {}
        self.confirmed_native = set()
        self.history_transform = lambda value: value
        self.history_requests = []

    def read_proposal(self, reference, *, timeout):
        snapshot = super().read_proposal(reference, timeout=timeout)
        basis = context_basis(self.chosen.context)
        writes = sum(progress_body(payload.get('body', '')).get('attempt_id') == basis['resume_attempt']
            and progress_body(payload['body']).get('next_action') == 'decision_context_' + wire.ATTEMPT
            and not progress_body(payload['body']).get('native_step')
            for _, payload in self.transport.effects if progress_body(payload.get('body', '')))
        return replace(snapshot, calls=replace(snapshot.calls, resume_writes=writes,
            resume_state='unconfirmed' if writes else 'not_dispatched'),
            predecessor_calls=DecisionCallCoverage(True, 0, 0, 1, 'applied')
                if self.chosen.predecessor is not None else None)

    def read_technical_replan_effects(self, repository_id, number, *, known_effects, timeout):
        from hydra_sdlc.native_replan import TechnicalReplanEffect, TechnicalReplanEffects
        self.history_requests.append(tuple(known_effects))
        effects = []
        for effect, intent in self.intents.items():
            after = json.loads(intent.after)
            writes = sum(progress_body(payload.get('body', '')) == after
                for _, payload in self.transport.effects)
            state = ('not_dispatched' if not writes else 'applied' if after['attempt_id'] in self.confirmed_native
                     else self.technical_state)
            effects.append(TechnicalReplanEffect(effect, intent.digest, intent.root, writes, state, True))
        return self.history_transform(TechnicalReplanEffects(repository_id, number, True, tuple(effects)))

    def read_work(self, repository, number, record, *, timeout):
        observed = super().read_work(repository, number, record, timeout=timeout)
        basis = context_basis(self.chosen.context)
        writes = sum(progress_body(payload.get('body', '')).get('attempt_id') == basis['resume_attempt']
            and progress_body(payload['body']).get('next_action') == 'decision_context_' + wire.ATTEMPT
            and not progress_body(payload['body']).get('native_step')
            for _, payload in self.transport.effects if progress_body(payload.get('body', '')))
        snapshot = replace(observed.snapshot, calls=replace(observed.snapshot.calls,
            resume_writes=writes, resume_state='unconfirmed' if writes else 'not_dispatched'))
        if self.chosen.predecessor is not None:
            snapshot = replace(snapshot, predecessor_calls=DecisionCallCoverage(True, 0, 0, 1, 'applied'))
        return replace(observed, snapshot=snapshot)

    def read_technical_replan(self, intent, *, timeout):
        from hydra_sdlc.native_replan import TechnicalReplanCoverage
        self.intents.setdefault(intent.effect, intent)
        original = self.intents[intent.effect]
        after = json.loads(original.after)
        writes = sum(progress_body(payload.get('body', '')) == after
            for _, payload in self.transport.effects)
        value = TechnicalReplanCoverage(intent.effect, original.digest, True, writes,
            self.technical_state if writes else 'not_dispatched', True)
        return self.coverage_transform(value)


class NativeTechnicalReplanTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.NativeDecisionResumeTests.asyncSetUp
    close_pending = recovery.ContinuationRecoveryTests.close_pending

    async def consume(self):
        self.source = ReplanSource(self.chosen, self.transport)
        self.controller.decision_source = self.source
        self.addAsyncCleanup(self.close_pending)
        first = await self.controller.begin(self.url)
        self.assertEqual(first['action'], 'native_task', first)
        await self.stop(first)
        return first

    async def stop(self, assignment):
        await self.controller.checkpoint(self.url, assignment['attempt_id'], assignment['step_id'],
            assignment['head'], assignment['contract_revision'], 'stopped')

    def record(self, **changes):
        record = self.github.progress(wire.REPO, 4)
        record = {key: value for key, value in record.items()
                  if key not in {'version', 'repository_id', 'issue_number'}}
        record.update(changes)
        self.github.record(wire.REPO, 4, record, preserve_decision_context=True)
        return self.github.progress(wire.REPO, 4)

    def ready(self):
        record = self.record(phase='uncertain', wait_reason='replan_required', pending_action=None,
                             resume_phase='implementation', next_action='diagnose')
        identifier = max(self.transport.direct) + 1
        self.transport.add(identifier, f"hydra: replan {record['attempt_id']} ready")
        self.transport.rows[-1]['user'] = {'login': self.config['authorized_actors'][0], 'id': 42}
        self.transport.direct[identifier] = copy.deepcopy(self.transport.rows[-1])
        return record

    async def begin(self):
        try:
            result = await self.controller.begin(self.url)
            if result.get('action') == 'native_task':
                original = self.github.decision_progress_source(wire.REPO, 4)
                if (original is not None and original['record']['attempt_id'] == result['attempt_id']
                        and original['record']['native_step'] == result['step_id'] and original['native_root'] is not None):
                    # Fixed original-provider fixture: retain the actual returned
                    # native call plus independently read-back public identity.
                    self.source.confirmed_native.add(result['attempt_id'])
            return result
        except GitHubError:
            self.fail('A valid native technical replan must reconcile rather than raise a writer error.')

    def decision_root_marker(self):
        found = re.search(r'<!-- hydra-native-decision-root:v1 (.*?) -->', self.transport.rows[0]['body'])
        return json.loads(found[1]) if found else None

    async def test_authorized_replan_and_restart_preserve_the_consumed_decision(self):
        first = await self.consume()
        self.ready()
        received = await self.begin()
        self.assertEqual(received['action'], 'native_task', received)
        self.assertNotEqual(received['attempt_id'], first['attempt_id'])
        self.assertEqual(self.decision_root_marker(), {'decision': {'key': context_basis(self.chosen.context)['key'],
            'context_sha256': self.chosen.context.sha256}, 'resume_attempt': wire.RESUME})
        self.assertEqual(self.github.decision_context_attempt(wire.REPO, 4, received['attempt_id']), wire.ATTEMPT)
        await self.stop(received)
        self.controller = NativeController(self.github, self.workspace, repos=[wire.REPO], host_alias='fixture',
            lock_path=self.controller.lock_path, operations=self.control)
        self.controller.decision_source = self.source
        after_restart = await self.begin()
        self.assertEqual(after_restart['action'], 'native_task', after_restart)
        self.assertEqual(after_restart['attempt_id'], received['attempt_id'])

    async def test_repeated_technical_replans_keep_one_unchanged_root(self):
        await self.consume()
        roots, attempts = [], {wire.RESUME}
        for _ in range(2):
            self.ready()
            received = await self.begin()
            self.assertEqual(received['action'], 'native_task', received)
            self.assertNotIn(received['attempt_id'], attempts)
            attempts.add(received['attempt_id'])
            roots.append(self.decision_root_marker())
            await self.stop(received)
        self.assertEqual(roots[0], roots[1])
        self.assertEqual(roots[0]['resume_attempt'], wire.RESUME)

    async def test_generic_marker_branch_cannot_rotate_a_consumed_native_decision(self):
        await self.consume()
        before = copy.deepcopy(self.transport.effects)
        with self.assertRaises(GitHubError):
            self.record(attempt_id='33333333-3333-4333-8333-333333333333',
                next_action='decision_context_' + wire.ATTEMPT, resume_phase='implementation')
        self.assertEqual(self.transport.effects, before)

    async def test_lost_ack_old_progress_holds_until_the_exact_successor_arrives(self):
        await self.consume()
        old = self.ready()
        attempted = []
        def lost(body):
            record = progress_body(body)
            if record['attempt_id'] != old['attempt_id'] and not record.get('native_step'):
                attempted.append(body)
                raise GitHubError('fixture lost technical-write acknowledgment', uncertain=True)
        self.transport.patch_behavior = lost
        first = await self.begin()
        self.assertNotEqual(first['action'], 'native_task', first)
        self.assertEqual(len(attempted), 1)
        self.transport.patch_behavior = lambda body: None
        self.controller = NativeController(self.github, self.workspace, repos=[wire.REPO], host_alias='fixture',
            lock_path=self.controller.lock_path, operations=self.control)
        self.controller.decision_source = self.source
        effects = len(self.transport.effects)
        repeated = await self.begin()
        self.assertNotEqual(repeated['action'], 'native_task', repeated)
        self.assertEqual(len(self.transport.effects), effects)
        self.transport.rows[0]['body'] = attempted[0]
        self.transport.direct[1] = copy.deepcopy(self.transport.rows[0])
        recovered = await self.begin()
        self.assertEqual(recovered['action'], 'native_task', recovered)
        self.assertEqual(recovered['attempt_id'], progress_body(attempted[0])['attempt_id'])

    async def test_incomplete_technical_coverage_has_no_write(self):
        await self.consume()
        self.ready()
        self.source.coverage_transform = lambda value: replace(value, complete=False)
        effects = copy.deepcopy(self.transport.effects)
        received = await self.begin()
        self.assertNotEqual(received['action'], 'native_task', received)
        self.assertEqual(self.transport.effects, effects)

    async def test_lagging_coverage_cannot_erase_a_known_attempt(self):
        await self.consume()
        old = self.ready()
        def lost(body):
            if progress_body(body)['attempt_id'] != old['attempt_id']:
                raise GitHubError('fixture unknown technical write', uncertain=True)
        self.transport.patch_behavior = lost
        await self.begin()
        effects = len(self.transport.effects)
        self.source.coverage_transform = lambda value: replace(value, writes=0, state='not_dispatched')
        received = await self.begin()
        self.assertNotEqual(received['action'], 'native_task', received)
        self.assertEqual(len(self.transport.effects), effects)

    async def test_unknown_original_effect_is_not_reset_by_technical_replan(self):
        await self.consume()
        self.ready()
        self.record(pending_action='publish', delivery_action='publish', delivery_attempt=3,
                    delivery_head=self.workspace.head)
        effects = copy.deepcopy(self.transport.effects)
        received = await self.begin()
        self.assertNotEqual(received['action'], 'native_task', received)
        self.assertEqual(self.transport.effects, effects)

    async def test_missing_descendant_root_cannot_fall_back_to_the_source_attempt(self):
        await self.consume()
        self.ready()
        received = await self.begin()
        self.assertEqual(received['action'], 'native_task', received)
        await self.stop(received)
        body = re.sub(r'\n<!-- hydra-native-decision-root:v1 .*? -->', '', self.transport.rows[0]['body'])
        self.transport.rows[0]['body'] = body
        self.transport.direct[1] = copy.deepcopy(self.transport.rows[0])
        effects = copy.deepcopy(self.transport.effects)
        held = await self.begin()
        self.assertNotEqual(held['action'], 'native_task', held)
        self.assertEqual(self.transport.effects, effects)

    async def test_unknown_successor_freshness_does_not_dispatch(self):
        await self.consume()
        self.ready()
        self.source.coverage_transform = lambda value: replace(value, successor_fresh=False)
        effects = copy.deepcopy(self.transport.effects)
        received = await self.begin()
        self.assertNotEqual(received['action'], 'native_task', received)
        self.assertEqual(self.transport.effects, effects)

    async def test_definitive_nonapplication_preserves_the_three_write_bound(self):
        await self.consume()
        old = self.ready()
        self.source.technical_state = 'not_applied'
        def fail(body):
            if progress_body(body)['attempt_id'] != old['attempt_id']:
                raise GitHubError('fixture definitively ended nonapplication', uncertain=True)
        self.transport.patch_behavior = fail
        for _ in range(3):
            self.assertNotEqual((await self.begin())['action'], 'native_task')
        effects = len(self.transport.effects)
        self.assertNotEqual((await self.begin())['action'], 'native_task')
        self.assertEqual(len(self.transport.effects), effects)
        writes = [progress_body(payload.get('body', '')) for _, payload in self.transport.effects]
        self.assertEqual(sum(record is not None and record['attempt_id'] != old['attempt_id']
            and record['attempt_id'] != wire.ATTEMPT for record in writes), 3)

    async def test_answer_amendment_after_technical_replan_consumes_a_new_root_and_checkpoints(self):
        await self.consume()
        self.ready()
        technical = await self.begin()
        self.assertEqual(technical['action'], 'native_task', technical)
        await self.stop(technical)
        old_context = self.chosen.context
        self.record(phase='checkpoint', wait_reason='product_decision', next_action='operator_decision',
                    resume_phase='implementation')
        basis = context_basis(old_context)
        basis.update(key={**basis['key'], 'round': 2}, resume_attempt='33333333-3333-4333-8333-333333333333',
            supersedes={'key': context_basis(old_context)['key'], 'context_sha256': old_context.sha256})
        context = prepare_context('Use the amended contract.', basis)
        self.source.chosen = replace(self.chosen, context=context, predecessor=old_context,
            replacement=domain.evidence('replacement'), replan=domain.evidence('replan'))
        self.transport.add(200, context.body)
        self.transport.add(201, receipt_body(context))
        amended = await self.begin()
        self.assertEqual(amended['action'], 'native_task', amended)
        self.assertEqual(amended['attempt_id'], basis['resume_attempt'])
        self.assertIn('Use the amended contract.', amended['prompt'])
        self.assertEqual(self.decision_root_marker()['decision']['context_sha256'], context.sha256)
        if amended['phase'] == 'spec_review':
            amended = await self.controller.checkpoint(self.url, amended['attempt_id'], amended['step_id'],
                amended['head'], amended['contract_revision'], 'candidate_ready')
        self.assertEqual(amended['phase'], 'implementation', amended)
        assignment = {key: amended[key] for key in
            ('attempt_id', 'step_id', 'head', 'contract_revision', 'spec_revision')}
        observed = []
        receipt = await self.controller._checkpoint_only(wire.REPO, 4, assignment, 'candidate_ready',
            repository_id=123, admission_revision=self.control.snapshot()['revision'], before_effect=lambda: None,
            source_observer=observed.append)
        self.assertEqual(receipt['kind'], 'checkpoint')
        self.assertTrue(receipt['step_retired'] and receipt['ticket_released'])
        self.assertEqual(observed[-1]['record']['phase'], 'implementation_done')
        self.assertIsNone(observed[-1]['record'].get('native_step'))
        self.assertEqual(observed[-1]['record'], self.github.progress(wire.REPO, 4))
