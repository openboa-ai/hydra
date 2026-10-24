"""P14/CP: final source guards, unknown effects, cleanup ceiling and worker ownership."""
import asyncio
import copy
from contextlib import ExitStack
from dataclasses import replace
from threading import Event
import unittest
from unittest.mock import patch

from hydra_sdlc.control_commands import InvalidAdmissionCommand, execute_command_v1, parse_command_v1
import test_native_delivery as fixture


class DeliveryParameterTests(unittest.TestCase):
    def command(self):
        return {'command_schema': 1, 'request_id': '11111111-1111-4111-8111-111111111111',
            'binding_epoch': None, 'action': 'workflow_step',
            'target': {'repository_id': 123, 'issue_number': 4},
            'expected': {'runtime_key': 'current-runtime', 'admission_revision': 0,
                         'source_checks': [], 'assignment': None},
            'effect_key': None, 'parameters': {'operation': 'deliver',
                'candidate': {'attempt_id': '22222222-2222-4222-8222-222222222222',
                              'head': 'b' * 40, 'contract_revision': 'a' * 40},
                'pr_number': 7, 'integration_base': 'a' * 40}}

    def test_valid_delivery_is_copied_without_replacing_its_pins(self):
        value = self.command()
        parsed = parse_command_v1(value)
        self.assertEqual(parsed, value)
        value['parameters']['integration_base'] = 'e' * 40
        self.assertEqual(parsed['parameters']['integration_base'], 'a' * 40)

    def test_malformed_or_expanded_delivery_cannot_cross_the_parser(self):
        for field, value in [('pr_number', True), ('pr_number', 0), ('pr_number', '7'),
                             ('integration_base', None), ('integration_base', 'main'),
                             ('candidate', {'head': 'b' * 40}), ('shell', 'arbitrary')]:
            with self.subTest(field=field, value=value):
                command = self.command()
                command['parameters'][field] = value
                with self.assertRaises(InvalidAdmissionCommand):
                    parse_command_v1(command)


class DeliveryGuardTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.NativeDeliveryTests.asyncSetUp
    new_controller = fixture.NativeDeliveryTests.new_controller
    result = fixture.NativeDeliveryTests.result
    command = fixture.NativeDeliveryTests.command
    checkpoint = fixture.NativeDeliveryTests.checkpoint
    real_git_assignment = fixture.NativeDeliveryTests.real_git_assignment
    candidate = fixture.NativeDeliveryTests.candidate
    verification_command = fixture.NativeDeliveryTests.verification_command
    verification_grant = fixture.NativeDeliveryTests.verification_grant
    call = fixture.NativeDeliveryTests.call
    finish_command = fixture.NativeDeliveryTests.finish_command
    reviewed = fixture.NativeDeliveryTests.reviewed
    publication_command = fixture.NativeDeliveryTests.publication_command
    publication_grant = fixture.NativeDeliveryTests.publication_grant
    publish = fixture.NativeDeliveryTests.publish
    published = fixture.NativeDeliveryTests.published
    delivery_command = fixture.NativeDeliveryTests.delivery_command
    delivery_grant = fixture.NativeDeliveryTests.delivery_grant
    deliver = fixture.NativeDeliveryTests.deliver
    effects = fixture.NativeDeliveryTests.effects
    unchanged_candidate = fixture.NativeDeliveryTests.unchanged_candidate

    async def test_wrong_candidate_pr_base_and_authority_have_no_delivery_effect(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        start = len(self.gh.writes)
        invalid = []
        for field, value in [('pr_number', command['parameters']['pr_number'] + 1),
                             ('integration_base', 'e' * 40), ('candidate', {**candidate, 'head': 'e' * 40})]:
            bad = copy.deepcopy(command)
            bad['parameters'][field] = value
            invalid.append(bad)
        for bad in invalid:
            reply = await self.deliver(bad)
            self.assertEqual(reply['request']['outcome'], 'rejected', reply)
            self.assertIsNone(reply['request']['receipt'])
        grant = self.delivery_grant()
        for value in [None, replace(grant, repository_ids=frozenset({999})),
                      replace(grant, operations=frozenset({'workflow_step.publish_candidate'}))]:
            reply = await execute_command_v1(self.settings, command,
                context_provider=lambda: value, github=self.gh, controller=self.controller)
            self.assertEqual(reply['request']['outcome'], 'rejected', reply)
        self.assertEqual(self.effects(start), [])
        self.assertIsNone(self.gh.note.get('pending_action'))
        self.unchanged_candidate(candidate)

    async def test_required_queue_and_incomplete_protection_or_reviews_hold_before_merge(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        original = self.gh.transform_observation
        start = len(self.gh.writes)
        def queue(value):
            value['rules'].append({'type': 'merge_queue'})
        def no_sources(value):
            value['rule_sources'] = []
        def no_reviews(value):
            value['native_reviews'] = None
        def no_provider(value):
            value['provider_comments'] = []
        for change in (queue, no_sources, no_reviews, no_provider):
            with self.subTest(change=change.__name__):
                def observe(value):
                    value = original(value)
                    change(value)
                    return value
                self.gh.transform_observation = observe
                reply = await self.deliver(command)
                self.assertIn(reply['request']['outcome'], {'waiting', 'unknown'}, reply)
                self.assertIsNone(reply['request']['receipt'])
                self.assertEqual(self.effects(start), [])
        self.gh.transform_observation = original
        self.assertEqual((await self.deliver(command))['request']['outcome'], 'applied')
        self.unchanged_candidate(candidate)

    async def test_authority_revoked_after_provider_observation_prevents_merge(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        original = self.gh.observe
        reads, revoked = 0, False
        def observe(repo, pr):
            nonlocal reads, revoked
            value = original(repo, pr)
            reads += 1
            if reads >= 2:
                revoked = True
            return value
        self.gh.observe = observe
        start = len(self.gh.writes)
        reply = await execute_command_v1(self.settings, command,
            context_provider=lambda: None if revoked else self.delivery_grant(),
            github=self.gh, controller=self.controller)
        self.assertTrue(revoked)
        self.assertIn(reply['request']['outcome'], {'waiting', 'rejected'}, reply)
        self.assertEqual(self.effects(start), [])
        self.assertFalse(self.gh.pr['merged'])
        self.unchanged_candidate(candidate)

    async def test_new_main_failure_after_close_intent_prevents_issue_closure(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        original_intent, original_observe = self.controller.runner._intent, self.gh.observe_commit
        failed = False
        def intent(*args, **kwargs):
            nonlocal failed
            value = original_intent(*args, **kwargs)
            if args[4] == 'close_issue' and value is not None:
                failed = True
            return value
        def observe(repo, sha):
            value = original_observe(repo, sha)
            if failed:
                value['runs'][0].update(status='completed', conclusion='failure')
                value['runs'][0]['jobs'][0].update(status='completed', conclusion='failure')
                value['checks'][0].update(status='completed', conclusion='failure')
            return value
        self.gh.observe_commit = observe
        start = len(self.gh.writes)
        with patch.object(self.controller.runner, '_intent', side_effect=intent):
            reply = await self.deliver(command)
        self.assertTrue(failed)
        self.assertEqual(reply['request']['outcome'], 'waiting', reply)
        self.assertEqual(reply['request']['receipt']['post_merge'], 'failed')
        self.assertEqual(self.gh.work['state'], 'open')
        self.assertEqual(self.effects(start), [('merge', candidate['head'])])
        self.unchanged_candidate(candidate)

    async def test_unknown_close_stays_unknown_across_calls_and_restart_until_late_result(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        original = self.gh.close_issue
        attempts = []
        def uncertain(*args, **kwargs):
            attempts.append((args, kwargs))
            if len(attempts) > 1:
                raise AssertionError('Unknown close must not be retransmitted')
            raise RuntimeError('Synthetic unconfirmed close dispatch')
        self.gh.close_issue = uncertain
        start = len(self.gh.writes)
        first = await self.deliver(command)
        self.assertEqual(first['request']['outcome'], 'waiting', first)
        self.assertEqual(self.gh.note['pending_action'], 'close_issue')
        again = await self.deliver(command)
        self.assertEqual(again['request']['outcome'], 'waiting', again)
        self.controller = self.new_controller()
        self.controller.runner.operations = self.control
        restored = await self.deliver(command)
        self.assertEqual(restored['request']['outcome'], 'waiting', restored)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(self.gh.work['state'], 'open')
        original(*attempts[0][0], **attempts[0][1])
        recovered = await self.deliver(command)
        self.assertEqual(recovered['request']['outcome'], 'applied', recovered)
        self.assertEqual(len(attempts), 1)
        self.assertEqual(self.effects(start), [('merge', candidate['head']), ('close', 4)])
        self.unchanged_candidate(candidate)

    async def test_delivery_retains_cleanup_without_calling_resource_retirement(self):
        candidate = await self.published()
        with patch.object(self.ws, 'completed', create=True,
                side_effect=AssertionError('Resource retirement is a separate operation')) as retire:
            reply = await self.deliver(self.delivery_command(candidate))
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        retire.assert_not_called()
        self.unchanged_candidate(candidate)

    async def test_cancellation_drains_the_sent_merge_before_releasing_ownership(self):
        candidate = await self.published()
        command = self.delivery_command(candidate)
        dispatched, release, ended = Event(), Event(), Event()
        original = self.gh.merge
        def merge(*args, **kwargs):
            dispatched.set()
            try:
                if not release.wait(10):
                    raise AssertionError('Test must release its owned writer')
                return original(*args, **kwargs)
            finally:
                ended.set()
        self.gh.merge = merge
        start = len(self.gh.writes)
        task = asyncio.create_task(self.deliver(command))
        try:
            self.assertTrue(await asyncio.to_thread(dispatched.wait, 10))
            task.cancel()
            await asyncio.sleep(0)
            self.assertFalse(task.done(), 'A sent writer still owns its scope')
        finally:
            release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(ended.is_set())
        self.assertTrue(self.gh.pr['merged'])
        self.assertEqual(self.gh.work['state'], 'open')
        self.assertEqual(self.effects(start), [('merge', candidate['head'])])
        self.unchanged_candidate(candidate)
