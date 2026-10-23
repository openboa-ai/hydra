"""PC-D07: an empty registered scope remains readable and denies all work."""
import json
import unittest
from unittest.mock import AsyncMock, patch

import test_connection_review as fixture
from hydra_sdlc import cli, projection
from hydra_sdlc.control import load_host_config
from hydra_sdlc.mcp import controller_from_file, create_server
from test_control_projection import EPOCH, REQUEST


ALPHA, BETA = fixture.ALPHA, fixture.BETA
URL = 'https://github.com/example/alpha/issues/1'


class EmptyConnectionServiceTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.ConnectionReviewTests.setUp
    text = fixture.ConnectionReviewTests.text
    write = fixture.ConnectionReviewTests.write
    load = fixture.ConnectionReviewTests.load
    state = fixture.ConnectionReviewTests.state

    def controller(self):
        try:
            return controller_from_file(self.path)
        except ValueError:
            self.fail('An empty connection profile must start its read-only MCP service')

    async def status(self, controller):
        from mcp import Client
        async with Client(create_server(controller, command_config_path=self.path)) as client:
            tools = (await client.list_tools()).tools
            self.assertEqual({tool.name for tool in tools}, {'hydra_status', 'hydra_command_v1',
                'hydra_begin', 'hydra_checkpoint', 'hydra_verify', 'hydra_deliver'})
            result = await client.call_tool('hydra_status', {})
        self.assertFalse(result.is_error)
        return result.structured_content or json.loads(result.content[0].text)

    async def test_empty_profile_factory_serves_sdk_status_and_tools(self):
        cfg = self.load(self.text(repos=[]))
        control = self.state(cfg, projects={})
        before = control.settings_path.read_bytes()
        with patch('hydra_sdlc.github.GitHub._gh', side_effect=AssertionError('No remote work')) as remote:
            controller = self.controller()
            value = await self.status(controller)
        self.assertEqual(controller.repos, ())
        self.assertEqual(value['projects'], [])
        self.assertEqual(value['controls']['version'], 2)
        self.assertEqual(value['controls']['default_project_mode'], 'stopped')
        self.assertEqual(value['controls']['projects'], {})
        self.assertNotIn(str(self.path), json.dumps(value))
        self.assertNotIn('connection_config', value['controls'])
        self.assertEqual(control.settings_path.read_bytes(), before)
        remote.assert_not_called()

    async def test_empty_controller_denies_all_legacy_work_entries(self):
        cfg = self.load(self.text(repos=[]))
        control = self.state(cfg, projects={})
        before = control.settings_path.read_bytes()
        with patch('hydra_sdlc.github.GitHub._gh', side_effect=AssertionError('No remote work')) as remote:
            controller = self.controller()
            with patch.object(controller, '_begin', new_callable=AsyncMock) as begin, \
                    patch.object(controller, '_checkpoint', new_callable=AsyncMock) as checkpoint, \
                    patch.object(controller, '_advance', new_callable=AsyncMock) as advance:
                for call in (lambda: controller.begin(URL),
                    lambda: controller.checkpoint(URL, REQUEST, EPOCH, 'a' * 40, 'b' * 40, 'stopped'),
                    lambda: controller.advance(URL, REQUEST, 'a' * 40, 'b' * 40)):
                    with self.subTest(call=call):
                        with self.assertRaisesRegex(ValueError, 'outside the installed repository allowlist'):
                            await call()
                begin.assert_not_awaited()
                checkpoint.assert_not_awaited()
                advance.assert_not_awaited()
        self.assertEqual(control.settings_path.read_bytes(), before)
        self.assertFalse(self.lock.exists())
        remote.assert_not_called()

    async def test_empty_status_preserves_removed_stopped_override(self):
        cfg = self.load(self.text(repos=[]))
        control = self.state(cfg, projects={ALPHA: 'stopped'})
        before = control.settings_path.read_bytes()
        with patch('hydra_sdlc.github.GitHub._gh', side_effect=AssertionError('No remote work')) as remote:
            controller = self.controller()
            value = await self.status(controller)
            with self.assertRaisesRegex(ValueError, 'outside the installed repository allowlist'):
                await controller.begin(URL)
        self.assertEqual(value['projects'], [])
        self.assertEqual(value['controls']['projects'], {ALPHA: 'stopped'})
        self.assertEqual(control.settings_path.read_bytes(), before)
        remote.assert_not_called()

    def test_legacy_empty_registry_is_rejected(self):
        self.write(self.text(repos=[], profile=False))
        with self.assertRaises(ValueError):
            load_host_config(self.path)

    def test_nonempty_controller_keeps_scope(self):
        cfg = self.load(self.text(repos=[ALPHA]))
        self.state(cfg)
        with patch('hydra_sdlc.github.GitHub._gh', side_effect=AssertionError('No remote work')) as remote:
            controller = self.controller()
            self.assertEqual(controller._issue(URL), (ALPHA, 1))
            with self.assertRaisesRegex(ValueError, 'outside the installed repository allowlist'):
                controller._issue('https://github.com/example/beta/issues/1')
        remote.assert_not_called()

    def test_empty_profile_cli_projection_is_readable(self):
        cfg = self.load(self.text(repos=[]))
        control = self.state(cfg, projects={})
        before = control.settings_path.read_bytes()
        args = cli.parser().parse_args(['control', 'status', '--config', str(self.path),
            '--projection-schema', '3', '--binding-epoch', EPOCH, '--request-id', REQUEST])
        with patch('hydra_sdlc.github.GitHub._gh', side_effect=AssertionError('No remote work')) as remote:
            value = cli.operate_control(args)
        encoded = projection.encode(value)
        self.assertEqual(value['projects'], [])
        self.assertEqual(value['work'], [])
        self.assertNotIn(str(self.path).encode(), encoded)
        self.assertEqual(control.settings_path.read_bytes(), before)
        remote.assert_not_called()

    async def test_empty_profile_run_rejects_unregistered_target_before_providers(self):
        cfg = self.load(self.text(repos=[]))
        control = self.state(cfg, projects={})
        before = control.settings_path.read_bytes()
        args = cli.parser().parse_args(['run', '--issue', URL, '--config', str(self.path),
            '--host-alias', 'fixture', '--workspace-root', str(self.root / 'work'),
            '--lock-path', str(self.lock)])
        with patch.object(cli, '_provider', side_effect=AssertionError('No provider')) as provider:
            with self.assertRaisesRegex(ValueError, 'differ from installed configuration'):
                await cli.operate(args, github=object(), emit=lambda value: None)
        self.assertEqual(control.settings_path.read_bytes(), before)
        provider.assert_not_called()
