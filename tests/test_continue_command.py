"""P06 typed continuation purpose oracles, with actual controller and GitHub codecs."""
from dataclasses import replace
import unittest

from hydra_sdlc.control import load_host_config
from hydra_sdlc.control_commands import _runtime_key, execute_command_v1
from hydra_sdlc.github import GitHubError
from hydra_sdlc.runtime_identity import capture_runtime_identity
import test_decision_commands as commands
import test_native_decision_resume as fixture
import test_public_decisions as wire


class ContinueCommandTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.NativeDecisionResumeTests.asyncSetUp
    stop_if_assigned = fixture.NativeDecisionResumeTests.stop_if_assigned

    def command(self):
        command = commands.continue_command()
        command['expected']['runtime_key'] = _runtime_key(capture_runtime_identity(load_host_config(self.settings), self.control))
        command['expected']['admission_revision'] = self.control.snapshot()['revision']
        self.grant = replace(self.grant, operations=frozenset({
            'workflow_step.continue', 'command_reply.native_handoff_v1'}))
        return command

    async def invoke(self, command=None):
        return await execute_command_v1(self.settings, self.command() if command is None else command,
            context_provider=lambda: self.grant, github=self.github, controller=self.controller)

    async def test_continue_returns_actual_private_assignment_from_pinned_public_decision(self):
        command = self.command()
        reply = await self.invoke(command)
        assignment = reply.get('handoff', {}).get('assignment') if reply.get('handoff') else None
        if assignment:
            self.addAsyncCleanup(self.stop_if_assigned, assignment)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(reply['request']['receipt']['boundary'], 'assignment_returned')
        self.assertEqual(reply['reply_profile'], 'native_handoff_v1')
        self.assertIsNotNone(assignment)
        self.assertEqual(assignment['attempt_id'], wire.RESUME)
        self.assertEqual(assignment['step_id'], self.github.progress(wire.REPO, 4)['native_step'])
        effects = len(self.transport.effects)
        repeated = await self.invoke(command)
        self.assertEqual(repeated['request']['reason'], 'stale_progress', repeated)
        self.assertEqual(len(self.transport.effects), effects)

    async def test_changed_phase_rejects_without_replacing_the_callers_pin(self):
        command = self.command()
        command['parameters']['progress']['phase'] = 'ready'
        reply = await self.invoke(command)
        self.assertEqual(reply['request']['reason'], 'stale_progress', reply)
        self.assertEqual(self.transport.effects, [])
        self.assertEqual(command['parameters']['progress']['phase'], 'ready')

    async def test_null_progress_does_not_adopt_an_existing_attempt(self):
        command = self.command()
        command['parameters']['progress'] = None
        reply = await self.invoke(command)
        self.assertEqual(reply['request']['reason'], 'stale_progress', reply)
        self.assertEqual(self.transport.effects, [])

    async def test_standard_profile_records_resume_without_allocating_unreturnable_assignment(self):
        command = self.command()
        command['parameters']['reply_profile'] = 'standard_v1'
        reply = await self.invoke(command)
        self.assertNotIn('handoff', reply)
        self.assertNotIn('reply_profile', reply)
        self.assertNotIn('native_step', self.github.progress(wire.REPO, 4))
        self.assertEqual(self.github.progress(wire.REPO, 4)['attempt_id'], wire.RESUME)
        self.assertEqual([row[0] for row in self.transport.effects], ['resume'])
        self.assertEqual(reply['request']['receipt']['boundary'], 'progress_recorded')

    async def test_profile_choice_does_not_grant_private_handoff(self):
        command = self.command()
        self.grant = replace(self.grant, operations=frozenset({'workflow_step.continue'}))
        reply = await self.invoke(command)
        self.assertEqual(reply['reply_profile'], 'native_handoff_v1')
        self.assertIsNone(reply['handoff'])
        self.assertNotIn('native_step', self.github.progress(wire.REPO, 4))

    async def test_pause_prevents_resume_and_assignment(self):
        self.control.set_mode('pause', wire.REPO)
        reply = await self.invoke()
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertIsNone(reply.get('handoff'))
        self.assertEqual(self.transport.effects, [])

    async def test_bridge_rejects_native_profile_before_any_effect(self):
        command = self.command()
        command['binding_epoch'] = '55555555-5555-4555-8555-555555555555'
        self.grant = replace(self.grant, surface='bridge', binding_epoch=command['binding_epoch'])
        reply = await self.invoke(command)
        self.assertEqual(reply['request']['reason'], 'unsupported_reply_profile', reply)
        self.assertIsNone(reply['handoff'])
        self.assertEqual(self.transport.effects, [])

    async def test_unavailable_progress_is_not_treated_as_no_existing_attempt(self):
        command = self.command()
        command['parameters']['progress'] = None
        self.transport.error = GitHubError('private-source-canary')
        reply = await self.invoke(command)
        self.assertEqual(reply['request']['outcome'], 'unknown', reply)
        self.assertNotIn('private-source-canary', str(reply))
        self.assertEqual(self.transport.effects, [])
