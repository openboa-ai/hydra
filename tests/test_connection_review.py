"""Independent outcomes for the five final-head PR34 review findings."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_project_connection as fixture
from hydra_sdlc import cli
from hydra_sdlc.control import control_from_config, load_host_config
from hydra_sdlc.control_commands import AdmissionCallContext, execute_admission_command, _runtime_key
from hydra_sdlc.mcp import create_server
from hydra_sdlc.operations import OperationDenied
from hydra_sdlc.projection_read import read_projection
from hydra_sdlc.runtime_identity import capture_runtime_identity
from test_control_projection import EPOCH, REQUEST
from test_projection_read import ReadFixture, issue


ALPHA, BETA = fixture.ALPHA, fixture.BETA


class ConnectionReviewTests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.ConnectionBindingTests.setUp
    text = fixture.ConnectionBindingTests.text
    write = fixture.ConnectionBindingTests.write
    load = fixture.ConnectionBindingTests.load
    state = fixture.ConnectionBindingTests.state
    effect = fixture.ConnectionBindingTests.effect

    def connected(self, *, desired='connected'):
        return self.load(self.text(desired=desired)
            + f'[project_connections."{BETA}"]\ndesired="connected"\n')

    def test_unprepared_entry_cannot_resume_or_dispatch_but_can_be_limited(self):
        cfg = self.load()
        control = self.state(cfg, projects={ALPHA: 'running', BETA: 'stopped'})
        before = control.settings_path.read_bytes()
        with self.assertRaises(OperationDenied, msg='An allowlist entry alone is not a connected declaration'):
            control.set_mode_if_current('resume', BETA, expected_revision=1)
        self.assertEqual(control.settings_path.read_bytes(), before)
        control = self.state(cfg, projects={ALPHA: 'running', BETA: 'running'})
        ledger = []
        self.assertIsNotNone(self.effect(control, BETA, ledger))
        self.assertIsNone(self.effect(control, ALPHA, ledger))
        self.assertEqual(ledger, [ALPHA])
        self.assertIsNone(self.effect(control, BETA, ledger, cleanup=True))
        result = control.set_mode_if_current('stop', BETA, expected_revision=1)
        self.assertEqual(result['projects'][BETA], 'stopped')
        self.assertEqual(result['global_mode'], 'running')

    def test_cached_controller_preserves_exact_cleanup_and_stop_after_disconnect(self):
        cfg = self.connected()
        old = self.state(cfg, projects={ALPHA: 'running', BETA: 'running'})
        self.connected(desired='disconnect_requested')
        ledger = []
        self.assertIsNone(self.effect(old, ALPHA, ledger, cleanup=True),
            'A restrictive desired-only transition cannot strand an ended execution')
        self.assertEqual(ledger, [ALPHA])
        self.assertIsNotNone(self.effect(old, ALPHA, ledger))
        limited = old.set_mode_if_current('stop', ALPHA, expected_revision=1)
        self.assertEqual(limited['projects'][ALPHA], 'stopped')
        self.assertEqual(limited['projects'][BETA], 'running')
        self.assertEqual(limited['global_mode'], 'running')
        self.assertIsNotNone(self.effect(old, ALPHA, ledger))

    def test_cleanup_does_not_accept_other_config_changes_or_reconnection(self):
        original = self.text() + f'[project_connections."{BETA}"]\ndesired="connected"\n'
        disconnected = original.replace('desired="connected"', 'desired="disconnect_requested"', 1)
        changes = [disconnected.replace(str(self.root / 'work'), str(self.root / 'other-work')),
            disconnected + 'native_project_id="other-project"\n',
            original.replace(f'[project_connections."{ALPHA}"]\ndesired="connected"\n', '')]
        for text in changes:
            with self.subTest(change=text):
                old = self.state(self.load(original), projects={ALPHA: 'running', BETA: 'running'})
                self.write(text)
                before = old.settings_path.read_bytes()
                ledger = []
                self.assertIsNotNone(self.effect(old, ALPHA, ledger, cleanup=True))
                with self.assertRaises(OperationDenied):
                    old.set_mode_if_current('stop', ALPHA, expected_revision=1)
                self.assertEqual(ledger, [])
                self.assertEqual(old.settings_path.read_bytes(), before)
        old = self.state(self.load(disconnected))
        self.write(original)
        self.assertIsNotNone(self.effect(old, ALPHA, [], cleanup=True))

    def frame(self, cfg):
        reader = ReadFixture({(ALPHA, 'open', False): [issue(7)],
                              (BETA, 'open', False): [issue(8)]})
        with patch('hydra_sdlc.projection_read.observe_coordinator', return_value={'state': 'free'}):
            result = read_projection(cfg, binding_epoch=EPOCH, request_id=REQUEST,
                                     refresh=True, github=reader.client)
        self.assertNotIn(str(self.path), json.dumps(result))
        return result

    def expect_blocked_alpha(self, cfg):
        self.state(cfg, projects={ALPHA: 'running', BETA: 'running'})
        frame = self.frame(cfg)
        projects = {row['repository_ref']['id']: row for row in frame['projects']}
        self.assertIsNone(projects['101']['admission']['value'],
            'A connection gate cannot publish current permission')
        self.assertIsNotNone(projects['101']['admission']['reason'])
        self.assertEqual(projects['102']['admission']['value'], 'allowed')
        for row in frame['work']:
            expected = None if row['issue_ref']['id'].startswith('101:') else 'allowed'
            self.assertEqual(row['admission']['value'], expected)
        return frame

    def test_actual_projection_preserves_disconnect_gate_and_independent_project(self):
        frame = self.expect_blocked_alpha(self.connected(desired='disconnect_requested'))
        self.assertIn('project_disconnect_requested', json.dumps(frame))

    def test_actual_projection_does_not_allow_an_unprepared_running_override(self):
        cfg = self.load(self.text().replace(f'[project_connections."{ALPHA}"]\ndesired="connected"\n', '')
            + f'[project_connections."{BETA}"]\ndesired="connected"\n')
        self.expect_blocked_alpha(cfg)

    async def test_actual_mcp_status_never_exports_the_trusted_binding_path(self):
        from mcp import Client
        control = self.state(self.connected())
        class Controller:
            runner = SimpleNamespace(operations=control)
            def status(self):
                return []
        async with Client(create_server(Controller())) as client:
            result = await client.call_tool('hydra_status', {})
        self.assertFalse(result.is_error)
        value = result.structured_content or json.loads(result.content[0].text)
        self.assertNotIn(str(self.path), json.dumps(value))
        self.assertNotIn('connection_config', value['controls'])
        self.assertEqual(value['controls']['version'], 2)
        self.assertEqual(value['controls']['default_project_mode'], 'stopped')
        self.assertEqual(value['controls']['projects'][ALPHA], 'running')

    def test_actual_admission_command_reports_an_unprepared_target_without_mutation(self):
        cfg = self.load()
        control = self.state(cfg, projects={ALPHA: 'running', BETA: 'running'})
        before = control.settings_path.read_bytes()
        command = {'command_schema': 1, 'request_id': REQUEST, 'binding_epoch': None,
            'action': 'admission_set', 'target': {'kind': 'repository', 'repository_id': 124},
            'expected': {'runtime_key': _runtime_key(capture_runtime_identity(cfg, control)),
                'admission_revision': 1, 'source_checks': [], 'assignment': None},
            'effect_key': None, 'parameters': {'mode': 'running'}}
        class Source:
            def repository(self, repo):
                return {'id': 123 if repo == ALPHA else 124, 'full_name': repo, 'default_branch': 'main'}
        result = execute_admission_command(self.path, command,
            context_provider=lambda: AdmissionCallContext('native', None,
                frozenset({123, 124}), frozenset({'admission_set'})), github=Source())
        self.assertEqual(result['request']['outcome'], 'rejected')
        self.assertEqual(result['request']['reason'], 'project_connection_unprepared')
        self.assertEqual(control.settings_path.read_bytes(), before)

    async def test_bound_cli_preserves_case_insensitive_repository_arguments(self):
        cfg = self.load(self.text() + 'native_project_id="fixture-project"\n')
        control = self.state(cfg)
        state = control.snapshot()
        state['global_mode'] = 'paused'
        control.settings_path.write_text(json.dumps(state) + '\n')
        for command, target in [('run', ['--issue', 'https://github.com/Example/Alpha/issues/1']),
                                ('serve', ['--repos', 'Example/Alpha', 'EXAMPLE/Beta'])]:
            with self.subTest(command=command):
                args = cli.parser().parse_args([command, *target, '--config', str(self.path),
                    '--host-alias', 'fixture', '--workspace-root', str(self.root / 'work'),
                    '--lock-path', str(self.lock)])
                with patch.object(cli, '_provider', side_effect=AssertionError('No provider in a paused host')):
                    try:
                        result = await cli.operate(args, github=object(), emit=lambda value: None)
                    except ValueError:
                        self.fail('A case-only repository spelling change rejected the installed target')
                self.assertEqual((result['action'], result['reason']), ('waiting', 'host_paused'))

    def test_connected_current_work_and_legacy_controls_keep_normal_paths(self):
        control = self.state(self.connected(), projects={ALPHA: 'running', BETA: 'running'})
        ledger = []
        self.assertIsNone(self.effect(control, ALPHA, ledger))
        self.assertIsNone(self.effect(control, BETA, ledger))
        self.assertEqual(ledger, [ALPHA, BETA])
        legacy = self.load(self.text(profile=False))
        fresh = control_from_config(legacy)
        self.assertIsNotNone(fresh.reason(ALPHA), 'An old-format caller cannot adopt the version-2 binding')
