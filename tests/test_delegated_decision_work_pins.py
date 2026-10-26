"""Real SDK commands must compare every proposal pin with authenticated work."""
import copy
import unittest

from hydra_sdlc.control_commands import parse_command_v1
from delegated_decision_fixture import (
    ATTEMPT, REPO, InstallationFixture, public_pair,
)


class DelegatedWorkPinTests(InstallationFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.setup_installation()
        self.write_profile(True)
        self.make_server(new_profile=True)

    async def assert_pin_holds(self, *, field, value):
        command = self.command()
        if field == 'source_attempt':
            command['parameters']['source_attempt'] = value
            command['effect_key'] = f'decision:{value}:1'
        else:
            command['parameters']['basis'][field] = value
        self.assertEqual(parse_command_v1(command), command,
                         'The mutation must be schema-valid and reach the authenticated work guard')
        progress = copy.deepcopy(self.github.progress(REPO, 4))
        controls = self.control.snapshot()
        result = self.reply(await self.invoke(command))
        self.assertIn(result['request']['outcome'], {'waiting', 'rejected'}, result)
        self.assertIsNone(result['request']['receipt'], result)
        self.assertIsNone(result.get('handoff'), result)
        self.assertEqual(self.transport.effects, [], f'Wrong {field} must cause zero physical writes')
        self.assertEqual(self.github.progress(REPO, 4), progress)
        self.assertEqual(self.control.snapshot(), controls)

    async def test_all_current_pins_publish_only_the_independent_exact_pair(self):
        command = self.command()
        self.assertEqual(parse_command_v1(command), command)
        progress = self.github.progress(REPO, 4)
        controls = self.control.snapshot()
        context, receipt, resume = public_pair(self.transport.basis)
        result = self.reply(await self.invoke(command))
        self.assertEqual(result['request']['outcome'], 'applied', result)
        self.assertEqual(self.transport.effects,
                         [('context', {'body': context}), ('receipt', {'body': receipt})])
        self.assertEqual(result['request']['receipt']['source_attempt'], ATTEMPT)
        self.assertEqual(result['request']['receipt']['resume_attempt'], resume)
        self.assertEqual(result['request']['receipt']['profile'], 'codex_delegated_v1')
        self.assertEqual(self.github.progress(REPO, 4), progress)
        self.assertEqual(self.control.snapshot(), controls)
        self.assertIsNone(result.get('handoff'))

    async def test_wrong_source_attempt_with_matching_effect_key_holds(self):
        await self.assert_pin_holds(field='source_attempt', value='22222222-2222-4222-8222-222222222222')

    async def test_wrong_head_holds(self):
        await self.assert_pin_holds(field='head', value='f' * 40)

    async def test_wrong_contract_revision_holds(self):
        await self.assert_pin_holds(field='contract_revision', value='f' * 40)

    async def test_wrong_spec_revision_holds(self):
        await self.assert_pin_holds(field='spec_revision', value='f' * 40)

    async def test_wrong_intake_digest_holds(self):
        await self.assert_pin_holds(field='intake_digest', value='f' * 64)

    async def test_wrong_origin_phase_holds(self):
        await self.assert_pin_holds(field='origin_phase', value='design')
