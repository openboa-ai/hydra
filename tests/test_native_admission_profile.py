"""Shared-installation admission policy, with actual store and SDK consumers."""
import copy
from datetime import datetime, timezone
import importlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

if __name__ == '__main__' and sys.argv[1:2] == ['--profile-stdio']:
    sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]


from hydra_sdlc.control import load_host_config
from hydra_sdlc.control_commands import execute_admission_command
from hydra_sdlc.mcp import create_server
from hydra_sdlc.operations import MAX_PROJECTS, MAX_REVISION
from hydra_sdlc.runtime_identity import capture_runtime_identity
import test_control_commands


class ProfileFixture:
    command = test_control_commands.AdmissionCommandTests.command
    payload = test_control_commands.AdmissionCommandTests.payload

    def setUp(self):
        test_control_commands.AdmissionCommandTests.setUp(self)

    def write_profile(self, body):
        self.config_path.write_text(self.config_text + (
            '' if body is None else '\n[native_admission_control]\n' + body + '\n'))
        self.config_path.chmod(0o600)

    def install(self, body='schema_version=1\nenabled=true\nrepository_ids=[101]'):
        self.write_profile(body)
        try:
            cfg = load_host_config(self.config_path)
        except ValueError:
            self.fail('A valid installation admission profile must be accepted')
        self.cfg = cfg
        self.runtime = capture_runtime_identity(cfg, self.control)
        return cfg

    def provider(self, path=None):
        try:
            module = importlib.import_module('hydra_sdlc.native_admission')
        except ModuleNotFoundError as error:
            if error.name != 'hydra_sdlc.native_admission':
                raise
            self.fail('The installation admission adapter is unavailable')
        return module.installation_admission_provider(path or self.config_path)

    def request(self, mode='paused', repository_id=101):
        command = self.command(mode, repository_id)
        command['binding_epoch'] = None
        return command

    def server(self, provider=None):
        controller = SimpleNamespace(runner=SimpleNamespace(github=self.github),
            runtime_identity=self.runtime, status=lambda: [])
        return create_server(controller, command_config_path=self.config_path,
            command_context_provider=provider if provider is not None else self.provider())

    async def call(self, client, command):
        result = await client.call_tool('hydra_command_v1', {'command': command})
        self.assertFalse(result.is_error, result.content)
        return result.structured_content or json.loads(result.content[0].text)


class ProfileConfigTests(ProfileFixture, unittest.TestCase):
    def test_valid_profiles_are_canonical_without_granting_registered_names(self):
        cfg = self.install('schema_version=1\nenabled=true\nrepository_ids=[202,101]\n'
                           'expires_at="2030-01-01T00:00:00Z"')
        self.assertEqual(cfg['native_admission_control'], {'schema_version': 1,
            'enabled': True, 'repository_ids': [101, 202], 'expires_at': '2030-01-01T00:00:00Z'})
        empty = self.install('schema_version=1\nenabled=false\nrepository_ids=[]')
        self.assertEqual(empty['native_admission_control']['repository_ids'], [])
        self.write_profile(None)
        self.assertNotIn('native_admission_control', load_host_config(self.config_path))

    def test_profile_rejects_unknown_fields_coercions_duplicates_and_bounds(self):
        self.install()
        invalid = [
            'schema_version=true\nenabled=true\nrepository_ids=[101]',
            'schema_version=2\nenabled=true\nrepository_ids=[101]',
            'schema_version=1\nenabled=1\nrepository_ids=[101]',
            'schema_version=1\nenabled="true"\nrepository_ids=[101]',
            'schema_version=1\nenabled=true\nrepository_ids=[true]',
            'schema_version=1\nenabled=true\nrepository_ids=[0]',
            'schema_version=1\nenabled=true\nrepository_ids=[-1]',
            'schema_version=1\nenabled=true\nrepository_ids=[101,101]',
            'schema_version=1\nenabled=true\nrepository_ids=["101"]',
            'schema_version=1\nenabled=true\nrepository_ids="101"',
            'schema_version=1\nenabled=true',
            'schema_version=1\nrepository_ids=[101]',
            'enabled=true\nrepository_ids=[101]',
            'schema_version=1\nenabled=true\nrepository_ids=[101]\noperation="SYNTHETIC_PRIVATE_CANARY"',
            f'schema_version=1\nenabled=true\nrepository_ids=[{MAX_REVISION + 1}]',
            'schema_version=1\nenabled=true\nrepository_ids=[' + ','.join(map(str, range(1, MAX_PROJECTS + 2))) + ']',
        ]
        for body in invalid:
            with self.subTest(body=body):
                self.write_profile(body)
                with self.assertRaises(ValueError) as raised:
                    load_host_config(self.config_path)
                self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', str(raised.exception))

    def test_expiry_is_an_exact_utc_second_string(self):
        self.install()
        values = ['2030-01-01T00:00:00Z', '2032-02-29T23:59:59Z']
        for value in values:
            self.install(f'schema_version=1\nenabled=true\nrepository_ids=[101]\nexpires_at="{value}"')
        invalid = ['"2030-01-01T00:00:00+00:00"', '"2030-01-01T00:00:00.1Z"',
                   '"2030-02-30T00:00:00Z"', '"2030-01-01T24:00:00Z"',
                   '"2030-01-01T00:00:60Z"', '"2030-1-01T00:00:00Z"',
                   '"2030-01-01T00:00:00z"', '2030-01-01T00:00:00Z', 'true', '""']
        for value in invalid:
            with self.subTest(value=value):
                self.write_profile(f'schema_version=1\nenabled=true\nrepository_ids=[101]\nexpires_at={value}')
                with self.assertRaises(ValueError):
                    load_host_config(self.config_path)

    def test_semantic_digest_tracks_authority_and_normalizes_only_id_order(self):
        legacy = capture_runtime_identity(self.cfg, self.control)['config_digest']
        base = self.install('schema_version=1\nenabled=true\nrepository_ids=[202,101]')
        digest = capture_runtime_identity(base, self.control)['config_digest']
        ordered = self.install('schema_version=1\nenabled=true\nrepository_ids=[101,202]')
        self.assertEqual(capture_runtime_identity(ordered, self.control)['config_digest'], digest)
        self.assertNotEqual(digest, legacy)
        for field, value in [('enabled', False), ('repository_ids', [101]),
                             ('expires_at', '2030-01-01T00:00:00Z')]:
            changed = copy.deepcopy(ordered)
            changed['native_admission_control'][field] = value
            self.assertNotEqual(capture_runtime_identity(changed, self.control)['config_digest'], digest)
        changed = copy.deepcopy(ordered)
        changed['native_admission_control']['enabled'] = 'PRIVATE_CANARY'
        invalid = capture_runtime_identity(changed, self.control)
        self.assertIsNone(invalid['config_digest'])
        self.assertNotIn('PRIVATE_CANARY', json.dumps(invalid))
        self.write_profile(None)
        self.assertEqual(capture_runtime_identity(load_host_config(self.config_path), self.control)['config_digest'], legacy)

    def test_provider_refuses_non_sdk_context_and_never_imports_host_factories(self):
        self.install()
        provider = self.provider()
        with patch('hydra_sdlc.control.load_host_config', side_effect=AssertionError('unexpected settings read')):
            for context in (None, {}, {'authorized': True}, SimpleNamespace(task_id='operator')):
                self.assertIsNone(provider(context))


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional pinned MCP SDK not installed')
class ProfileProtocolTests(ProfileFixture, unittest.IsolatedAsyncioTestCase):
    async def test_real_sdk_pause_then_explicit_resume_preserves_other_state(self):
        from mcp import Client
        self.install()
        provider = self.provider()
        grants = []
        def observe(ctx):
            grant = provider(ctx)
            grants.append(grant)
            return grant
        before = self.control.snapshot()
        with patch('hydra_sdlc.codex.execute', side_effect=AssertionError('native effect')):
            async with Client(self.server(observe)) as client:
                paused = await self.call(client, self.request())
                self.assertEqual(paused['request']['outcome'], 'applied', paused)
                self.assertIsNotNone(paused['request']['receipt'])
                middle = self.control.snapshot()
                self.assertEqual(middle['projects']['example/alpha'], 'paused')
                self.assertEqual(middle['global_mode'], before['global_mode'])
                self.assertEqual(middle['projects'].get('example/beta'), before['projects'].get('example/beta'))
                # Observing/answering has no implicit admission transition.
                await client.call_tool('hydra_status', {})
                self.assertEqual(self.control.snapshot(), middle)
                resumed = await self.call(client, self.request('running'))
                self.assertEqual(resumed['request']['outcome'], 'applied', resumed)
        self.assertEqual(self.control.snapshot()['projects'].get('example/alpha', 'running'), 'running')
        self.assertTrue(grants)
        self.assertTrue(all(g.operations == frozenset({'admission_set'}) and g.surface == 'native'
                            and g.binding_epoch is None and g.repository_ids == frozenset({101}) for g in grants))

    async def test_absent_disabled_empty_expired_and_foreign_scope_have_zero_effects(self):
        from mcp import Client
        self.install()
        for profile in (None, 'schema_version=1\nenabled=false\nrepository_ids=[101]',
                        'schema_version=1\nenabled=true\nrepository_ids=[]',
                        'schema_version=1\nenabled=true\nrepository_ids=[202]',
                        'schema_version=1\nenabled=true\nrepository_ids=[999]',
                        'schema_version=1\nenabled=true\nrepository_ids=[101]\nexpires_at="2000-01-01T00:00:00Z"'):
            self.write_profile(profile)
            self.cfg = load_host_config(self.config_path)
            self.runtime = capture_runtime_identity(self.cfg, self.control)
            before = self.payload()
            async with Client(self.server()) as client:
                denied = await self.call(client, self.request())
            self.assertEqual(denied['request']['outcome'], 'rejected', denied)
            self.assertIsNone(denied['request']['receipt'])
            self.assertEqual(self.payload(), before)

    async def test_source_time_disable_remove_and_scope_revoke_do_not_write(self):
        from mcp import Client
        for replacement in (None, 'schema_version=1\nenabled=false\nrepository_ids=[101]',
                            'schema_version=1\nenabled=true\nrepository_ids=[202]'):
            self.install()
            before = self.payload()
            self.github.during_read = lambda: self.write_profile(replacement)
            async with Client(self.server()) as client:
                result = await self.call(client, self.request())
            self.assertEqual(result['request']['outcome'], 'rejected', result)
            self.assertIsNone(result['request']['receipt'])
            self.assertEqual(self.payload(), before)
            self.github.during_read = None

    async def test_expiry_at_second_authority_check_removes_the_grant(self):
        from mcp import Client
        self.install('schema_version=1\nenabled=true\nrepository_ids=[101]\nexpires_at="2030-01-01T00:00:00Z"')
        before = self.payload()
        moments = [datetime(2029, 12, 31, 23, 59, 59, tzinfo=timezone.utc),
                   datetime(2030, 1, 1, tzinfo=timezone.utc)]
        with patch('hydra_sdlc.native_admission._now', side_effect=moments):
            async with Client(self.server()) as client:
                result = await self.call(client, self.request())
        self.assertEqual(result['request']['outcome'], 'rejected', result)
        self.assertEqual(self.payload(), before)

    async def test_profile_change_rejects_old_runtime_and_fresh_request_can_progress(self):
        from mcp import Client
        self.install()
        old = self.request()
        self.install('schema_version=1\nenabled=true\nrepository_ids=[101]\nexpires_at="2099-01-01T00:00:00Z"')
        before = self.payload()
        async with Client(self.server()) as client:
            stale = await self.call(client, old)
            self.assertEqual(stale['request']['reason'], 'stale_runtime', stale)
            self.assertEqual(self.payload(), before)
            fresh = await self.call(client, self.request())
            self.assertEqual(fresh['request']['outcome'], 'applied', fresh)

    async def test_fixed_locator_survives_cwd_change_and_unsafe_replacement_denies(self):
        from mcp import Client
        self.install()
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            provider = self.provider(Path('host.toml'))
        finally:
            os.chdir(previous)
        before = self.payload()
        async with Client(self.server(provider)) as client:
            result = await self.call(client, self.request())
            self.assertEqual(result['request']['outcome'], 'applied', result)
            self.control.set_mode('resume', 'example/alpha')
            before = self.payload()
            self.github.during_read = lambda: self.config_path.chmod(0o666)
            denied = await self.call(client, self.request())
            self.assertEqual(denied['request']['outcome'], 'rejected', denied)
            self.assertEqual(self.payload(), before)

    async def test_real_stdio_main_uses_profile_without_changing_legacy_tools(self):
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
        self.install()
        parameters = StdioServerParameters(command=sys.executable,
            args=['-I', str(Path(__file__).resolve()), '--profile-stdio', str(self.config_path)],
            cwd=str(Path(__file__).resolve().parents[1]))
        with tempfile.TemporaryFile(mode='w+') as errors:
            async with stdio_client(parameters, errlog=errors) as streams:
                async with ClientSession(*streams) as client:
                    await client.initialize()
                    tools = {tool.name for tool in (await client.list_tools()).tools}
                    self.assertEqual(tools, {'hydra_command_v1', 'hydra_status', 'hydra_begin',
                                            'hydra_checkpoint', 'hydra_verify', 'hydra_deliver'})
                    paused = await self.call(client, self.request())
                    self.assertEqual(paused['request']['outcome'], 'applied', paused)
                    resumed = await self.call(client, self.request('running'))
                    self.assertEqual(resumed['request']['outcome'], 'applied', resumed)
            errors.seek(0)
            self.assertNotIn('PRIVATE_CANARY', errors.read())


if __name__ == '__main__':
    if len(sys.argv) == 3 and sys.argv[1] == '--profile-stdio':
        from hydra_sdlc import mcp as hydra_mcp
        config_path = Path(sys.argv[2])
        cfg = load_host_config(config_path)
        from hydra_sdlc.control import control_from_config
        control = control_from_config(cfg)
        controller = SimpleNamespace(runner=SimpleNamespace(github=test_control_commands.RepositoryReader()),
            runtime_identity=capture_runtime_identity(cfg, control), status=lambda: [])
        with patch.object(hydra_mcp, 'controller_from_file', return_value=controller), \
             patch.object(sys, 'argv', [sys.argv[0], '--config', str(config_path)]):
            hydra_mcp.main()
    else:
        unittest.main()
