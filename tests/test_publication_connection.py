"""P14/PC: bounded publication retains current project-connection admission."""
import json
import unittest
from unittest.mock import patch

from hydra_sdlc.control import control_from_config, load_host_config
import test_native_publication as fixture
from test_workspace import git


class PublicationConnectionTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.NativePublicationTests.asyncSetUp
    new_controller = fixture.NativePublicationTests.new_controller
    result = fixture.NativePublicationTests.result
    command = fixture.NativePublicationTests.command
    checkpoint = fixture.NativePublicationTests.checkpoint
    real_git_assignment = fixture.NativePublicationTests.real_git_assignment
    candidate = fixture.NativePublicationTests.candidate
    verification_command = fixture.NativePublicationTests.verification_command
    verification_grant = fixture.NativePublicationTests.verification_grant
    call = fixture.NativePublicationTests.call
    finish_command = fixture.NativePublicationTests.finish_command
    reviewed = fixture.NativePublicationTests.reviewed
    publication_command = fixture.NativePublicationTests.publication_command
    publication_grant = fixture.NativePublicationTests.publication_grant
    publish = fixture.NativePublicationTests.publish
    no_publication = fixture.NativePublicationTests.no_publication

    def connection(self, *, explicit_running):
        value = self.control.snapshot()
        text = self.settings.read_text()
        self.settings.write_text(text + 'connection_schema=1\n'
            '[project_connections."example/product"]\ndesired="connected"\n')
        self.settings.chmod(0o600)
        cfg = load_host_config(self.settings)
        self.control = control_from_config(cfg)
        value.update(version=2, revision=value['revision'] + 1,
            projects={'example/product': 'running'} if explicit_running else {},
            connection_config={'profile': 1, 'path': str(self.settings)})
        self.control.settings_path.write_text(json.dumps(value) + '\n')
        self.control.settings_path.chmod(0o600)
        self.controller.runner.operations = self.control

    async def test_connected_project_without_explicit_running_cannot_publish(self):
        candidate = await self.reviewed()
        self.connection(explicit_running=False)
        writes = len(self.gh.writes)
        reply = await self.publish(self.publication_command(candidate))
        self.assertEqual(reply['request']['outcome'], 'rejected', reply)
        self.assertEqual(reply['request']['reason'], 'project_stopped', reply)
        self.assertIsNone(reply['request']['receipt'])
        self.assertNotIn('example/product', self.control.snapshot()['projects'])
        self.no_publication(writes)

    async def test_explicit_connected_running_scope_publishes_actual_git_and_owned_pr(self):
        candidate = await self.reviewed()
        self.connection(explicit_running=True)
        writes = len(self.gh.writes)
        reply = await self.publish(self.publication_command(candidate))
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(reply['request']['receipt']['stage'], 'publication_ready')
        self.assertEqual(reply['request']['receipt']['observed_remote_head'], candidate['head'])
        self.assertEqual(self.pushes, [('hydra/issue-4', None)])
        self.assertEqual(git(self.path, 'ls-remote', 'origin', 'refs/heads/hydra/issue-4').split()[0], candidate['head'])
        self.assertEqual([row[0] for row in self.gh.writes[writes:] if row[0] != 'record'], ['pr'])
        self.assertEqual(git(self.path, 'rev-parse', 'HEAD'), candidate['head'])
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_fresh_disconnect_intent_blocks_cached_controller_at_actual_push_boundary(self):
        candidate = await self.reviewed()
        self.connection(explicit_running=True)
        controller, control = self.controller, self.control
        command = self.publication_command(candidate)
        self.assertIsNone(control.reason('example/product'), 'Entry conditions must permit publication')
        writes = len(self.gh.writes)
        effect = controller.runner._workspace_effect
        injected = False
        def disconnect(repo, method, *args, **kwargs):
            nonlocal injected
            if method == 'publish':
                self.assertFalse(injected, 'Do not retry a held publication')
                injected = True
                text = self.settings.read_text()
                self.assertIn('desired="connected"', text)
                self.settings.write_text(text.replace('desired="connected"', 'desired="disconnect_requested"'))
                self.settings.chmod(0o600)
            return effect(repo, method, *args, **kwargs)
        with patch.object(controller.runner, '_workspace_effect', side_effect=disconnect):
            reply = await self.publish(command)
        self.assertTrue(injected, 'Change the actual fixed config immediately before the real Git writer')
        self.assertIs(self.controller, controller)
        self.assertIs(controller.runner.operations, control)
        self.assertIn(reply['request']['outcome'], {'waiting', 'rejected'}, reply)
        self.assertEqual(control.snapshot()['projects']['example/product'], 'running', 'Do not erase the stored setting')
        self.assertIsNotNone(control.reason('example/product'))
        self.assertEqual(git(self.path, 'ls-remote', 'origin', 'refs/heads/hydra/issue-4'), '')
        self.assertIsNone(self.gh.pr)
        self.no_publication(writes)
