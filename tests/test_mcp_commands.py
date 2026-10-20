"""Real SDK command routing; trusted providers are synthetic server dependencies."""
import importlib.util
import copy
import errno
import fcntl
import io
import json
import logging
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hydra_sdlc.mcp import create_server
import test_mcp
import test_control_commands
import test_checkpoint_only
from hydra_sdlc.control_commands import AdmissionCallContext


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional pinned MCP SDK not installed')
class CommandRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_registered_command_rejects_invalid_payload_without_echo(self):
        from mcp import Client
        async with Client(create_server(test_mcp.ControllerFixture())) as client:
            result = await client.call_tool('hydra_command_v1', {'command': 'PRIVATE_CANARY'})
        self.assertTrue(result.is_error)
        self.assertEqual([item.text for item in result.content], ['invalid_command'])
        self.assertNotIn('PRIVATE_CANARY', json.dumps(result.model_dump()))

    async def test_stdio_rejects_raw_private_input_without_stderr_echo(self):
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client
        from mcp.types import Request, CallToolResult
        canary = 'SYNTHETIC_PRIVATE_STDIO_CANARY'
        params = StdioServerParameters(command=sys.executable,
            args=[str(Path(test_mcp.__file__).resolve()), '--fixture'],
            cwd=str(Path(__file__).resolve().parents[1]))
        with tempfile.TemporaryFile(mode='w+') as errors:
            async with stdio_client(params, errlog=errors) as streams:
                async with ClientSession(*streams) as client:
                    await client.initialize()
                    result = await client.send_request(Request[dict, str](method='tools/call',
                        params={'name': 'hydra_command_v1', 'arguments': {'command': {'summary': canary}}}), CallToolResult)
            errors.seek(0)
            self.assertNotIn(canary, errors.read())
        self.assertEqual([part.text for part in result.content], ['invalid_command'])

    async def test_input_schema_has_only_command_and_closed_profiles(self):
        from mcp import Client
        async with Client(create_server(test_mcp.ControllerFixture())) as client:
            tools = {tool.name: tool for tool in (await client.list_tools()).tools}
        schema = tools['hydra_command_v1'].input_schema
        self.assertEqual(set(schema['properties']), {'command'})
        self.assertEqual(schema['required'], ['command'])
        self.assertIs(schema['additionalProperties'], False)
        for branch in schema['properties']['command']['oneOf']:
            for closed in (branch, branch['properties']['target'], branch['properties']['expected'],
                           branch['properties']['parameters']):
                self.assertIs(closed['additionalProperties'], False)
        expected = {'hydra_status': [], 'hydra_begin': ['issue_url'],
            'hydra_checkpoint': ['issue_url', 'attempt_id', 'step_id', 'head', 'contract_revision', 'outcome', 'summary'],
            'hydra_verify': ['issue_url', 'attempt_id', 'head', 'contract_revision'],
            'hydra_deliver': ['issue_url', 'attempt_id', 'head', 'contract_revision']}
        for name, fields in expected.items():
            baseline = {'title': name + 'Arguments', 'type': 'object', 'properties': {
                field: {'title': field.replace('_', ' ').title(), 'type': 'string',
                        **({'default': ''} if field == 'summary' else {})} for field in fields}}
            if fields:
                baseline['required'] = [field for field in fields if field != 'summary']
            self.assertEqual(tools[name].input_schema, baseline)


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional pinned MCP SDK not installed')
class AdmissionProtocolTests(unittest.IsolatedAsyncioTestCase):
    command = test_control_commands.AdmissionCommandTests.command
    payload = test_control_commands.AdmissionCommandTests.payload

    async def asyncSetUp(self):
        test_control_commands.AdmissionCommandTests.setUp(self)
        self.context = AdmissionCallContext('native', None, frozenset({101, 202}))
        self.controller = SimpleNamespace(runner=SimpleNamespace(github=self.github), status=lambda: [])
        self.contexts = []

    def grant(self, ctx):
        from mcp.server.mcpserver import Context
        self.assertIsInstance(ctx, Context)
        self.contexts.append(ctx)
        return self.context

    def request(self, mode='paused'):
        command = self.command(mode)
        command['binding_epoch'] = None
        return command

    def server(self, provider=True):
        return create_server(self.controller, command_config_path=self.config_path,
                             command_context_provider=self.grant if provider else None)

    async def call(self, client, command):
        result = await client.call_tool('hydra_command_v1', {'command': command})
        self.assertFalse(result.is_error, result.content)
        return result.structured_content or json.loads(result.content[0].text)

    async def test_actual_sdk_pause_readback_resume_preserves_host_beta_and_no_native_turn(self):
        from mcp import Client
        before = self.control.snapshot()
        with patch('hydra_sdlc.codex.execute', side_effect=AssertionError('native turn')), \
             patch('hydra_sdlc.codex.capabilities', side_effect=AssertionError('native probe')):
            async with Client(self.server()) as client:
                paused = await self.call(client, self.request())
                self.assertEqual(paused['request']['outcome'], 'applied', paused)
                self.assertIsNotNone(paused['request']['receipt'])
                middle = self.control.snapshot()
                self.assertEqual(middle['projects']['example/alpha'], 'paused')
                self.assertEqual(middle['global_mode'], before['global_mode'])
                self.assertEqual(middle['projects'].get('example/beta'), before['projects'].get('example/beta'))
                resumed = await self.call(client, self.request('running'))
        self.assertEqual(resumed['request']['outcome'], 'applied', resumed)
        after = self.control.snapshot()
        self.assertGreater(after['revision'], middle['revision'])
        self.assertEqual(after['projects'].get('example/alpha', 'running'), 'running')
        self.assertTrue(self.contexts)

    async def test_default_provider_and_forged_metadata_cannot_grant(self):
        from mcp import Client
        before = self.payload()
        async with Client(self.server(provider=False)) as client:
            result = await client.call_tool('hydra_command_v1', {'command': self.request()},
                meta={'authority': 'granted', 'repository_ids': [101], 'operations': ['admission_set']})
        self.assertFalse(result.is_error)
        reply = result.structured_content or json.loads(result.content[0].text)
        self.assertEqual(reply['request']['reason'], 'authority_unavailable')
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(self.payload(), before)

    async def test_revoked_scope_mismatch_stale_and_unsupported_have_no_fallback(self):
        from mcp import Client
        before = self.payload()
        command = self.request()
        variants = []
        for key, value in [('runtime_key', 'wrong'), ('admission_revision', 0)]:
            item = copy.deepcopy(command); item['expected'][key] = value; variants.append(item)
        item = copy.deepcopy(command); item['binding_epoch'] = test_control_commands.EPOCH; variants.append(item)
        item = copy.deepcopy(command); item['action'] = 'work_create'; variants.append(item)
        async with Client(self.server()) as client:
            for item in variants:
                reply = await self.call(client, item)
                self.assertEqual(reply['request']['outcome'], 'rejected', reply)
                self.assertIsNone(reply['request']['receipt'])
            self.github.during_read = lambda: setattr(self, 'context', AdmissionCallContext(
                'native', None, frozenset({101, 202}), frozenset()))
            reply = await self.call(client, command)
            self.assertEqual(reply['request']['reason'], 'authority_denied')
        self.assertEqual(self.payload(), before)

    async def test_bridge_grant_cannot_cross_into_native_mcp_and_provider_errors_are_private(self):
        from mcp import Client
        before = self.payload()
        self.context = AdmissionCallContext('bridge', test_control_commands.EPOCH, frozenset({101, 202}))
        command = self.request(); command['binding_epoch'] = self.context.binding_epoch
        async with Client(self.server()) as client:
            reply = await self.call(client, command)
        self.assertEqual(reply['request']['reason'], 'authority_unavailable')
        with patch.object(self, 'grant', side_effect=RuntimeError('PRIVATE_PROVIDER_CANARY')):
            async with Client(self.server()) as client:
                reply = await self.call(client, self.request())
        self.assertEqual(reply['request']['reason'], 'authority_unavailable')
        self.assertNotIn('PRIVATE_PROVIDER_CANARY', json.dumps(reply))
        self.assertEqual(self.payload(), before)

    async def test_malformed_command_arguments_and_metadata_never_echo_private_values(self):
        from mcp import Client
        from mcp.types import Request, CallToolResult
        canary = 'SYNTHETIC_PRIVATE_COMMAND_CANARY'
        base = self.request()
        bad = [None, [canary], canary, json.dumps(base)]
        for key, value in [('secret', canary), ('request_id', canary), ('command_schema', True)]:
            item = copy.deepcopy(base); item[key] = value; bad.append(item)
        item = copy.deepcopy(base); item['parameters']['summary'] = canary + '\ud800'; bad.append(item)
        item = copy.deepcopy(base); item['parameters']['summary'] = canary * 5000; bad.append(item)
        nested = canary
        for _ in range(20): nested = [nested]
        item = copy.deepcopy(base); item['parameters']['summary'] = nested; bad.append(item)
        params = [{'name': 'hydra_command_v1', 'arguments': {'command': item}} for item in bad]
        params += [{'name': 'hydra_command_v1', 'arguments': [canary]},
                   {'name': 'hydra_command_v1', 'arguments': {'command': base, 'provider': canary}},
                   {'name': 'hydra_command_v1', 'arguments': {'command': base}, '_meta': {'progress_token': [canary]}}]
        params += [{'name': 'hydra_command_v1', 'arguments': {'command': base}, key: canary}
                   for key in ('requestState', 'inputResponses', 'task')]
        before, logs = self.payload(), io.StringIO()
        handler = logging.StreamHandler(logs)
        logging.getLogger().addHandler(handler)
        try:
            async with Client(self.server()) as client:
                for raw in params:
                    with self.subTest(case=params.index(raw)):
                        result = await client.session.send_request(Request[dict, str](method='tools/call', params=raw), CallToolResult)
                        self.assertTrue(result.is_error)
                        self.assertEqual([part.text for part in result.content], ['invalid_command'])
                        self.assertNotIn(canary, json.dumps(result.model_dump()))
        finally:
            logging.getLogger().removeHandler(handler)
        self.assertNotIn(canary, logs.getvalue())
        self.assertEqual(self.payload(), before)
        self.assertEqual(self.contexts, [])

    async def test_busy_returns_before_shared_lock_release_and_has_no_late_write(self):
        from mcp import Client
        before = self.payload()
        fd = os.open(self.control.control_lock_path, os.O_RDONLY)
        try:
            fcntl.flock(fd, fcntl.LOCK_SH)
            async with Client(self.server()) as client:
                reply = await self.call(client, self.request())
            self.assertEqual(reply['request']['reason'], 'operation_state_busy')
            self.assertEqual(reply['request']['outcome'], 'waiting')
            self.assertIsNone(reply['request']['receipt'])
            self.assertEqual(self.payload(), before)
        finally:
            os.close(fd)
        self.assertEqual(self.payload(), before)

    async def test_lost_store_ack_is_unknown_and_reconciles_actual_effect(self):
        from mcp import Client
        calls, fsync = [], os.fsync
        def fail_parent(fd):
            calls.append(fd)
            if len(calls) == 2: raise OSError(errno.EIO, 'PRIVATE_ACK_CANARY')
            return fsync(fd)
        async with Client(self.server()) as client:
            with patch('hydra_sdlc.operations.os.fsync', side_effect=fail_parent):
                first = await self.call(client, self.request())
            self.assertEqual(first['request']['outcome'], 'unknown')
            self.assertIsNone(first['request']['receipt'])
            self.assertNotIn('PRIVATE_ACK_CANARY', json.dumps(first))
            self.assertEqual(self.control.snapshot()['projects']['example/alpha'], 'paused')
            second = await self.call(client, self.request())
        self.assertEqual(second['request']['outcome'], 'applied')
        self.assertEqual(second['request']['reason'], 'already_satisfied')


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional pinned MCP SDK not installed')
class CheckpointProtocolTests(unittest.IsolatedAsyncioTestCase):
    new_controller = test_checkpoint_only.CheckpointOnlyTests.new_controller
    result = test_checkpoint_only.CheckpointOnlyTests.result
    command = test_checkpoint_only.CheckpointOnlyTests.command
    real_git_assignment = test_checkpoint_only.CheckpointOnlyTests.real_git_assignment
    ended = test_checkpoint_only.CheckpointOnlyTests.ended

    async def asyncSetUp(self):
        await test_checkpoint_only.CheckpointOnlyTests.asyncSetUp(self)

    def server(self):
        return create_server(self.controller, command_config_path=self.settings,
            command_context_provider=lambda ctx: self.grant)

    async def test_actual_sdk_dirty_git_completion_readback_retirement_without_continuation(self):
        from mcp import Client
        from test_workspace import git
        assignment, path, base = await self.real_git_assignment()
        (path / 'src/main.py').write_text('retained SDK checkpoint\n')
        observed = []
        progress = self.gh.progress
        def read(repo, number):
            row = progress(repo, number)
            if row and row.get('phase') == 'implementation_done': observed.append(copy.deepcopy(row))
            return row
        with patch.object(self.ws, 'verify', side_effect=AssertionError('verification forbidden')), \
             patch.object(self.ws, 'publish', side_effect=AssertionError('publication forbidden')), \
             patch.object(self.controller, 'advance', side_effect=AssertionError('continuation forbidden')), \
             patch.object(self.gh, 'progress', side_effect=read):
            async with Client(self.server()) as client:
                command = self.command(assignment)
                canary = 'SYNTHETIC_PRIVATE_CHECKPOINT_CANARY'
                command['parameters']['summary'] = canary + '😀' * (24000 - len(canary))
                response = await client.call_tool('hydra_command_v1', {'command': command})
        self.assertFalse(response.is_error, response.content)
        reply = response.structured_content or json.loads(response.content[0].text)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertNotIn('SYNTHETIC_PRIVATE_CHECKPOINT_CANARY', json.dumps(response.model_dump()))
        head = git(path, 'rev-parse', 'HEAD')
        self.assertEqual(git(path, 'rev-list', '--count', f'{base}..HEAD'), '1')
        self.assertEqual(reply['request']['receipt']['checkpoint_head'], head)
        self.assertTrue(observed)
        self.assertEqual(self.gh.note['phase'], 'implementation_done')
        self.assertNotIn('native_step', self.gh.note)
        self.assertEqual(self.lock.read_bytes(), b'')
        self.assertEqual((path / 'src/main.py').read_text(), 'retained SDK checkpoint\n')

    async def test_stopped_without_independent_evidence_preserves_owner_and_edits(self):
        from mcp import Client
        assignment = await self.result(await self.controller.begin(self.url))
        self.ws.dirty = True
        ticket, note = self.lock.read_bytes(), copy.deepcopy(self.gh.note)
        async with Client(self.server()) as client:
            response = await client.call_tool('hydra_command_v1', {'command': self.command(assignment, 'stopped')})
        self.assertFalse(response.is_error)
        reply = response.structured_content or json.loads(response.content[0].text)
        self.assertEqual(reply['request']['reason'], 'termination_unconfirmed')
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(self.lock.read_bytes(), ticket)
        self.assertEqual(self.gh.note, note)
        self.assertTrue(self.ws.dirty)

    async def test_lost_final_ack_keeps_exact_owner_then_reconciles_without_duplicate_checkpoint(self):
        from mcp import Client
        assignment = await self.result(await self.controller.begin(self.url))
        self.ws.dirty = True
        command, write = self.command(assignment), self.gh.record_checkpoint
        def lose_final(repo, number, record):
            write(repo, number, record)
            if record.get('phase') == 'implementation_done': raise OSError('PRIVATE_FINAL_ACK_CANARY')
        async with Client(self.server()) as client:
            with patch.object(self.gh, 'record_checkpoint', side_effect=lose_final):
                first = await client.call_tool('hydra_command_v1', {'command': command})
            reply = first.structured_content or json.loads(first.content[0].text)
            self.assertEqual(reply['request']['outcome'], 'unknown')
            self.assertIsNone(reply['request']['receipt'])
            self.assertNotIn('PRIVATE_FINAL_ACK_CANARY', json.dumps(first.model_dump()))
            self.assertIn(assignment['step_id'].encode(), self.lock.read_bytes())
            with patch.object(self.ws, 'checkpoint', side_effect=AssertionError('duplicate checkpoint')):
                second = await client.call_tool('hydra_command_v1', {'command': command})
        reply = second.structured_content or json.loads(second.content[0].text)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)

    async def test_independent_stopped_fixture_proof_and_controller_mismatch(self):
        from mcp import Client
        assignment = await self.result(await self.controller.begin(self.url))
        self.ws.dirty = True
        before = self.lock.read_bytes()
        host = self.controller.runner.host
        self.controller.runner.host = 'wrong-host'
        async with Client(self.server()) as client:
            response = await client.call_tool('hydra_command_v1', {'command': self.command(assignment)})
        reply = response.structured_content or json.loads(response.content[0].text)
        self.assertEqual(reply['request']['reason'], 'checkpoint_binding_mismatch')
        self.assertEqual(self.lock.read_bytes(), before)
        self.assertTrue(self.ws.dirty)
        self.controller.runner.host = host
        server = create_server(self.controller, command_config_path=self.settings,
            command_context_provider=lambda ctx: self.grant,
            command_ended_provider=lambda ctx: self.ended(assignment))
        async with Client(server) as client:
            response = await client.call_tool('hydra_command_v1', {'command': self.command(assignment, 'stopped')})
        reply = response.structured_content or json.loads(response.content[0].text)
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.lock.read_bytes(), b'')
        self.assertFalse(self.ws.dirty)
