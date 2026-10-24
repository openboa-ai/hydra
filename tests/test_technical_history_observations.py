"""EX10 observed uncertainty survives later lagging or omitted original history."""
import copy
from dataclasses import replace
import unittest

from hydra_sdlc.github import GitHubError
from hydra_sdlc.native import NativeController
from hydra_sdlc.public_decisions import context_basis, prepare_context, receipt_body
import test_decision_protocol as domain
import test_native_technical_replan as technical
import test_public_decisions as wire


class TechnicalHistoryObservationTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = technical.NativeTechnicalReplanTests.asyncSetUp
    close_pending = technical.NativeTechnicalReplanTests.close_pending
    consume = technical.NativeTechnicalReplanTests.consume
    stop = technical.NativeTechnicalReplanTests.stop
    record = technical.NativeTechnicalReplanTests.record
    ready = technical.NativeTechnicalReplanTests.ready
    begin = technical.NativeTechnicalReplanTests.begin

    async def assert_retained(self, *, unknown_count, omitted, other_effect=False, partial_history=False,
                              phase_race=False):
        await self.consume()
        old = self.ready()
        attempted = []
        self.source.technical_state = 'not_applied'
        def lost(body):
            if technical.progress_body(body)['attempt_id'] != old['attempt_id']:
                attempted.append(body)
                if len(attempted) == 2:
                    self.source.technical_state = 'unconfirmed'
                raise GitHubError('fixture technical write failed or unknown', uncertain=True)
        self.transport.patch_behavior = lost
        self.assertNotEqual((await self.begin())['action'], 'native_task')
        self.assertNotEqual((await self.begin())['action'], 'native_task')
        self.assertEqual(len(attempted), 2, 'Two actual fixture requests precede the restart.')
        self.transport.patch_behavior = lambda body: None
        self.controller = NativeController(self.github, self.workspace, repos=[wire.REPO], host_alias='fixture',
            lock_path=self.controller.lock_path, operations=self.control)
        self.controller.decision_source = self.source
        if unknown_count:
            self.source.history_transform = lambda value: replace(value, effects=tuple(
                replace(fact, writes=None, complete=False) for fact in value.effects))
        if other_effect:
            self.source.history_transform = lambda value: replace(value, effects=value.effects + tuple(
                replace(fact, effect=(123, 4, '99999999-9999-4999-8999-999999999999'),
                    intent_digest='e' * 64, writes=None, complete=False) for fact in value.effects))
        if partial_history:
            self.source.history_transform = lambda value: replace(value, complete=False)
        if phase_race:
            transform = self.source.history_transform
            def changed_progress(value):
                self.record(phase='checkpoint', wait_reason='product_decision', next_action='operator_decision')
                return transform(value)
            self.source.history_transform = changed_progress
        observed = await self.begin()
        self.assertNotEqual(observed['action'], 'native_task', observed)
        predecessor = self.chosen.context
        if not phase_race:
            self.record(phase='checkpoint', wait_reason='product_decision', next_action='operator_decision')
        basis = context_basis(predecessor)
        basis.update(key={**basis['key'], 'round': 2}, resume_attempt='33333333-3333-4333-8333-333333333333',
            supersedes={'key': context_basis(predecessor)['key'], 'context_sha256': predecessor.sha256})
        self.source.chosen = replace(self.chosen, context=prepare_context('Use the amended contract.', basis),
            predecessor=predecessor, replacement=domain.evidence('replacement'), replan=domain.evidence('replan'))
        self.transport.add(500, self.source.chosen.context.body)
        self.transport.add(501, receipt_body(self.source.chosen.context))
        self.source.history_transform = (lambda value: replace(value, effects=())) if omitted else (
            lambda value: replace(value, effects=tuple(replace(fact, writes=0,
                state='not_dispatched', complete=True) for fact in value.effects)))
        if other_effect:
            # The original request has definitively ended, but a second
            # previously returned identity is missing from this lagging page.
            self.source.history_transform = lambda value: replace(value, effects=tuple(
                replace(fact, state='not_applied', complete=True) for fact in value.effects))
        effects = copy.deepcopy(self.transport.effects)
        received = await self.begin()
        self.assertNotEqual(received['action'], 'native_task', received)
        self.assertEqual(self.transport.effects, effects)
        self.assertIn((123, 4, old['attempt_id']), self.source.history_requests[-1],
                      'Previously observed uncertainty must be requested again after an empty cache restart.')
        if other_effect:
            self.assertIn((123, 4, '99999999-9999-4999-8999-999999999999'), self.source.history_requests[-1])

    async def test_two_observed_requests_cannot_be_reset_to_zero(self):
        await self.assert_retained(unknown_count=False, omitted=False)

    async def test_two_observed_requests_cannot_disappear_from_history(self):
        await self.assert_retained(unknown_count=False, omitted=True)

    async def test_an_unknown_count_cannot_be_reinterpreted_as_zero(self):
        await self.assert_retained(unknown_count=True, omitted=False)

    async def test_an_observed_unknown_identity_cannot_disappear(self):
        await self.assert_retained(unknown_count=True, omitted=True)

    async def test_all_received_uncertain_identities_are_retained_before_holding(self):
        await self.assert_retained(unknown_count=False, omitted=False, other_effect=True)

    async def test_valid_identities_in_partial_history_remain_known(self):
        await self.assert_retained(unknown_count=False, omitted=True, partial_history=True)

    async def test_progress_change_cannot_hide_unknown_history_before_answer_amendment(self):
        await self.assert_retained(unknown_count=False, omitted=True, phase_race=True)

    async def test_progress_change_cannot_reset_observed_history_to_zero(self):
        await self.assert_retained(unknown_count=False, omitted=False, phase_race=True)
