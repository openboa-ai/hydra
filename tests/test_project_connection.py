"""P17/PC: a new connection cannot bypass current fixed configuration."""
import asyncio
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc import cli, projection
from hydra_sdlc.control import control_from_config, load_host_config
from hydra_sdlc.control_commands import AdmissionCallContext, execute_admission_command, _runtime_key
from hydra_sdlc.operations import OperatingControl, OperationDenied
from hydra_sdlc.runtime_identity import capture_runtime_identity


ALPHA, BETA = 'example/alpha', 'example/beta'


class ConnectionBindingTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path, self.lock = self.root / 'host.toml', self.root / 'host.lock'

    def text(self, *, repos=None, profile=True, desired='connected'):
        repos = [ALPHA, BETA] if repos is None else repos
        text = (f'repos={json.dumps(repos)}\nhost_alias="fixture"\n'
                f'workspace_root={json.dumps(str(self.root / "work"))}\n'
                f'lock_path={json.dumps(str(self.lock))}\n')
        if profile:
            text += 'connection_schema=1\n'
            if ALPHA in repos:
                text += f'[project_connections."{ALPHA}"]\ndesired="{desired}"\n'
        return text

    def write(self, text):
        self.path.write_text(text)
        self.path.chmod(0o600)

    def load(self, text=None):
        self.write(self.text() if text is None else text)
        try:
            cfg = load_host_config(self.path)
        except ValueError:
            cfg = None
        self.assertIsNotNone(cfg, 'The specified connection profile must have a normal read path')
        return cfg

    def state(self, cfg, *, projects=None, path=None):
        control = control_from_config(cfg)
        value = {'version': 2, 'revision': 1, 'global_mode': 'running',
            'projects': {ALPHA: 'running'} if projects is None else projects,
            'updated_at': '2026-10-23T00:00:00.000000Z',
            'connection_config': {'profile': 1, 'path': str(path or self.path)}}
        control.control_lock_path.touch(mode=0o600, exist_ok=True)
        control.control_lock_path.chmod(0o600)
        control.settings_path.write_text(json.dumps(value) + '\n')
        control.settings_path.chmod(0o600)
        return control

    def effect(self, control, repo, ledger, *, cleanup=False):
        try:
            with control.guard(repo, cleanup=cleanup):
                ledger.append(repo)
        except OperationDenied as exc:
            return exc.reason
        return None

    def test_profile1_zero_projects_is_readable_without_authorizing_work(self):
        cfg = self.load(self.text(repos=[]))
        self.assertEqual(cfg['repos'], [])
        self.assertIsNotNone(capture_runtime_identity(cfg, control_from_config(cfg))['config_digest'])
        ledger = []
        self.assertIsNotNone(self.effect(control_from_config(cfg), None, ledger))
        self.assertEqual(ledger, [])

    def test_profile1_valid_and_malformed_settings_are_distinguished(self):
        valid = self.text()
        self.load(valid)
        cases = [valid.replace('connection_schema=1', 'connection_schema=true'),
            valid.replace('connection_schema=1\n', ''),
            valid.replace('desired="connected"', 'desired="running"'),
            valid.replace(ALPHA + '"]', 'example/foreign"]'),
            valid + 'authorized=true\n',
            valid + 'native_project_id="' + ('x' * 257) + '"\n',
            valid + 'native_project_id="\\n"\n']
        for text in cases:
            with self.subTest(text=text):
                self.write(text)
                with self.assertRaises(ValueError):
                    load_host_config(self.path)

    def test_v2_only_explicit_current_project_override_can_run(self):
        cfg = self.load(self.text() + f'[project_connections."{BETA}"]\ndesired="connected"\n')
        control = self.state(cfg)
        ledger = []
        self.assertIsNone(self.effect(control, ALPHA, ledger))
        self.assertIsNotNone(self.effect(control, BETA, ledger))
        self.assertEqual(ledger, [ALPHA])
        self.assertEqual(control.reason(BETA), 'project_stopped')
        self.assertNotIn(BETA, control.snapshot()['projects'], 'Do not fabricate a stored override')

    def test_cached_writer_holds_after_desired_change_and_current_beta_can_continue(self):
        beta = f'[project_connections."{BETA}"]\ndesired="connected"\n'
        cfg = self.load(self.text() + beta)
        old = self.state(cfg, projects={ALPHA: 'running', BETA: 'running'})
        self.write(self.text(desired='disconnect_requested') + beta)
        ledger = []
        self.assertIsNotNone(self.effect(old, ALPHA, ledger))
        current = control_from_config(load_host_config(self.path))
        self.assertIsNotNone(self.effect(current, ALPHA, ledger))
        self.assertIsNone(self.effect(current, BETA, ledger))
        self.assertEqual(ledger, [BETA])
        self.assertEqual(old.snapshot()['projects'], {ALPHA: 'running', BETA: 'running'})

    def test_missing_other_and_unsafe_binding_never_reach_an_effect(self):
        cfg = self.load()
        current = self.state(cfg)
        ledger = []
        self.assertIsNone(self.effect(current, ALPHA, ledger))
        ledger.clear()
        self.assertIsNotNone(self.effect(OperatingControl(self.lock, [ALPHA, BETA]), ALPHA, ledger))
        other = self.root / 'other.toml'
        other.write_text(self.path.read_text())
        other.chmod(0o600)
        self.state(cfg, path=other)
        self.assertIsNotNone(self.effect(current, ALPHA, ledger))
        self.state(cfg)
        self.path.unlink()
        self.assertIsNotNone(self.effect(current, ALPHA, ledger, cleanup=True))
        self.path.symlink_to(other)
        self.assertIsNotNone(self.effect(current, ALPHA, ledger, cleanup=True))
        self.assertEqual(ledger, [])

    def test_mode_cas_keeps_binding_and_never_resumes_disconnect_intent(self):
        cfg = self.load()
        current = self.state(cfg, projects={ALPHA: 'stopped'})
        result = None
        try:
            result = current.set_mode_if_current('resume', ALPHA, expected_revision=1)
        except OperationDenied:
            pass
        self.assertIsNotNone(result, 'A valid bound explicit Resume must progress')
        self.assertEqual(result['version'], 2)
        self.assertEqual(result['connection_config'], {'profile': 1, 'path': str(self.path)})
        self.write(self.text(desired='disconnect_requested'))
        current = control_from_config(load_host_config(self.path))
        with self.assertRaises(OperationDenied):
            current.set_mode_if_current('resume', ALPHA, expected_revision=2)
        stopped = current.set_mode_if_current('stop', ALPHA, expected_revision=2)
        self.assertEqual(stopped['projects'][ALPHA], 'stopped')
        self.assertEqual(stopped['global_mode'], 'running')

    async def test_actual_admission_reply_keeps_trusted_binding_private(self):
        cfg = self.load()
        control = self.state(cfg, projects={ALPHA: 'stopped'})
        class Source:
            def repository(self, repo):
                return {'id': 123 if repo == ALPHA else 124, 'full_name': repo, 'default_branch': 'main'}
        command = {'command_schema': 1, 'request_id': '22222222-2222-4222-8222-222222222222',
            'binding_epoch': None, 'action': 'admission_set', 'target': {'kind': 'repository', 'repository_id': 123},
            'expected': {'runtime_key': _runtime_key(capture_runtime_identity(cfg, control)),
                'admission_revision': 1, 'source_checks': [], 'assignment': None},
            'effect_key': None, 'parameters': {'mode': 'running'}}
        result = execute_admission_command(self.path, command,
            context_provider=lambda: AdmissionCallContext('native', None,
                frozenset({123, 124}), frozenset({'admission_set'})), github=Source())
        self.assertEqual(result['request']['outcome'], 'applied', result)
        self.assertNotIn(str(self.path), json.dumps(result))
        admission = result['observations'][0]['value']
        self.assertEqual(admission['default_project_mode'], 'stopped')
        self.assertNotIn(BETA, admission['project_overrides'])
        projection.observation(result['observations'][0])
        projection.command_result(result['request'], {row['key']: row for row in result['observations']})

    async def test_arg_only_and_foreign_config_cli_hold_before_provider_import(self):
        cfg = self.load()
        self.state(cfg)
        args = cli.parser().parse_args(['run', '--issue', 'https://github.com/example/alpha/issues/1',
            '--host-alias', 'fixture', '--workspace-root', str(self.root / 'work'),
            '--lock-path', str(self.lock), '--storage-provider', 'synthetic.provider:create'])
        with patch.object(cli, '_provider', side_effect=AssertionError('Provider imported before binding')):
            result = await cli.operate(args, github=object(), emit=lambda value: None)
        self.assertEqual(result['action'], 'waiting')
        self.assertEqual(result['reason'], 'connection_binding_required')

    def test_legacy_configuration_retains_its_original_inheritance(self):
        cfg = self.load(self.text(profile=False))
        control = control_from_config(cfg)
        control.set_mode('start')
        ledger = []
        self.assertIsNone(self.effect(control, BETA, ledger))
        self.assertEqual(ledger, [BETA])
        self.assertEqual(control.snapshot()['version'], 1)
