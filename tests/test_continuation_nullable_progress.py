"""CP11 pre-workspace waits remain addressable without weakening execution heads."""
import copy
import json
from pathlib import Path
import unittest

from hydra_sdlc import projection as p
from hydra_sdlc.control_commands import InvalidAdmissionCommand, parse_command_v1
import test_continuation_review_recovery as recovery
import test_decision_commands as commands
import test_public_decisions as wire


class NullableProgressTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = recovery.ContinuationRecoveryTests.asyncSetUp
    command = recovery.ContinuationRecoveryTests.command
    invoke = recovery.ContinuationRecoveryTests.invoke
    close_pending = recovery.ContinuationRecoveryTests.close_pending
    pin_current = recovery.ContinuationRecoveryTests.pin_current

    def dependency(self):
        self.transport.rows, self.transport.direct = [], {}
        self.controller.decision_source = None
        self.transport.issue['body'] = self.transport.issue['body'].replace(
            '```hydra\n', '```hydra\ndependencies = ["https://github.com/example/other/issues/2"]\n')
        original, state = self.github.issue, ['open']
        def issue(repo, number):
            if repo == 'example/other' and number == 2:
                return {'number': 2, 'state': state[0]}
            return original(repo, number)
        self.github.issue = issue
        return state

    async def start_wait(self):
        command = self.command()
        command['parameters']['progress'] = None
        reply = await self.invoke(command)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        return reply

    async def test_dependency_wait_then_closure_returns_a_real_assignment(self):
        state = self.dependency()
        self.addAsyncCleanup(self.close_pending)
        first = await self.start_wait()
        record = self.github.progress(wire.REPO, 4)
        self.assertIsNone(record['head'])
        self.assertEqual(record['wait_reason'], 'dependency_open')
        self.assertEqual(self.workspace.prepared_recovery, [])
        try:
            p.command_result(first['request'], p.observations_index(first['observations']))
        except p.ProjectionError:
            self.fail('A real pre-workspace wait must return a valid continuation receipt.')
        pin = self.pin_current()
        try:
            repeated = await self.invoke(pin)
        except InvalidAdmissionCommand:
            self.fail('An existing null-head record must remain addressable by its exact pin.')
        self.assertEqual(repeated['request']['outcome'], 'waiting', repeated)
        self.assertEqual(self.workspace.prepared_recovery, [])
        self.assertIsNone(pin['parameters']['progress']['head'])
        state[0] = 'closed'
        continued = await self.invoke(pin)
        self.assertEqual(continued['request']['outcome'], 'applied', continued)
        assignment = continued['handoff']['assignment']
        self.assertEqual(assignment['head'], self.workspace.head)
        self.assertEqual(continued['request']['receipt']['head'], self.workspace.head)
        self.assertIsNone(pin['parameters']['progress']['head'], 'The submitted precondition stays unchanged.')
        p.command_result(continued['request'], p.observations_index(continued['observations']))

    async def test_stale_nullable_pins_do_not_adopt_a_changed_record(self):
        self.dependency()
        await self.start_wait()
        pin = self.pin_current()
        variants = [None]
        for key, value in [('head', 'a' * 40), ('phase', 'checkpoint'), ('attempt_id', wire.RESUME)]:
            changed = copy.deepcopy(pin['parameters']['progress'])
            changed[key] = value
            variants.append(changed)
        before = copy.deepcopy(self.transport.effects)
        for value in variants:
            with self.subTest(pin=value):
                command = copy.deepcopy(pin)
                command['parameters']['progress'] = value
                try:
                    received = await self.invoke(command)
                except InvalidAdmissionCommand:
                    self.fail('A well-typed stale nullable pin must be rejected against original progress.')
                self.assertEqual(received['request']['reason'], 'stale_progress', received)
        self.assertEqual(self.transport.effects, before)
        self.assertEqual(self.workspace.prepared_recovery, [])


class NullableProgressWireTests(unittest.TestCase):
    def test_nullable_head_is_required_and_candidate_heads_remain_strict(self):
        command = commands.continue_command()
        command['parameters']['progress']['head'] = None
        try:
            parsed = parse_command_v1(command)
        except InvalidAdmissionCommand:
            self.fail('The required nullable progress head must be accepted.')
        self.assertEqual(parsed, command)
        missing = copy.deepcopy(command)
        del missing['parameters']['progress']['head']
        with self.assertRaises(InvalidAdmissionCommand):
            parse_command_v1(missing)
        with self.assertRaises(p.ProjectionError):
            p.candidate({key: command['parameters']['progress'][key]
                         for key in ('attempt_id', 'head', 'contract_revision')})
        with self.assertRaises(p.ProjectionError):
            p.assignment({'attempt_id': wire.ATTEMPT, 'step_id': wire.RESUME, 'head': None,
                          'contract_revision': 'b' * 40, 'spec_revision': None})

    def test_shared_receipt_shapes_and_original_progress_correlation(self):
        cases = json.loads((Path(__file__).parent / 'fixtures/control-v3/continuation-heads.json').read_text())
        for case in cases:
            reply = case['reply']
            with self.subTest(case=case['name']):
                try:
                    p.command_result(reply['request'], p.observations_index(reply['observations']))
                    actual = True
                except p.ProjectionError:
                    actual = False
                self.assertEqual(actual, case['schema_accepted'])
                if actual:
                    with self.assertRaises(p.ProjectionError) as raised:
                        p.standard_reply(reply)
                    self.assertEqual(raised.exception.reason, 'unsupported_receipt_source')
