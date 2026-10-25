"""Independent review regressions for completeness, disclosure and SDK logs."""
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from hydra_sdlc.native import NativeController
import test_post_merge_context as sources


class Wire(sources.Wire):
    def __init__(self, count=1):
        super().__init__(count)
        self.mangle = lambda path, value: value

    def cli(self, argv, **kwargs):
        result = super().cli(argv, **kwargs)
        if self.enriching and '--include' not in argv:
            raw = next(arg for arg in argv if arg == 'user' or arg.startswith('repos/'))
            value = self.mangle(raw, json.loads(result.stdout))
            return subprocess.CompletedProcess(argv, result.returncode, json.dumps(value), result.stderr)
        return result


class SourceReviewTests(unittest.TestCase):
    read = sources.SourceContextTests.read
    context = sources.SourceContextTests.context

    def test_contradictory_current_run_count_cannot_select_an_older_run(self):
        wire = Wire()
        def missing(path, value):
            if type(value) is dict and 'workflow_runs' in value:
                value['total_count'] += 1
            return value
        wire.mangle = missing
        value = self.context(self.read(wire))
        self.assertEqual(value['state'], 'unknown')
        self.assertIsNone(value['source'])
        self.assertEqual(value['current']['checks'], [])

    def test_contradictory_historical_job_count_keeps_current_and_holds_history(self):
        wire = Wire()
        wire.rerun(state='failure')
        def missing(path, value):
            if '/attempts/' in path and type(value) is dict and 'total_count' in value:
                value['total_count'] += 1
            return value
        wire.mangle = missing
        value = self.context(self.read(wire))
        self.assertEqual(value['state'], 'failed')
        self.assertEqual(value['current']['checks'][0]['run_attempt'], 2)
        self.assertEqual(value['history']['failed_checks'], [])
        self.assertNotEqual(value['history']['coverage']['state'], 'complete')
        self.assertIsNone(value['history']['coverage']['total_count'])

    def test_missing_or_invalid_typed_collection_count_is_not_complete(self):
        for count in ('missing', None, True, -1, '1'):
            with self.subTest(count=count):
                wire = Wire()
                def invalid(path, value):
                    if type(value) is dict and 'workflow_runs' in value:
                        if count == 'missing':
                            value.pop('total_count')
                        else:
                            value['total_count'] = count
                    return value
                wire.mangle = invalid
                value = self.context(self.read(wire))
                self.assertEqual(value['state'], 'unknown')
                self.assertEqual(value['current']['checks'], [])

    def test_phase_b_observed_nested_repository_visibility_invalidates_siblings(self):
        wire = Wire(2)
        for repo in wire.rows:
            wire.rerun(repo, state='failure')
        wire.rows['example/project1']['history'][(50, 1)]['runs'][0]['repository'].update(
            full_name='example/project1', private=True, visibility='private')
        rows = self.read(wire)
        for index in range(2):
            value = self.context(rows, index)
            self.assertEqual(value['state'], 'changed')
            self.assertIsNone(value['source'])
            self.assertEqual(value['current']['checks'], [])
            self.assertEqual(value['history']['failed_checks'], [])

    def test_omitted_nested_disclosure_fields_are_not_transitions(self):
        wire = Wire(2)
        for repo in wire.rows:
            wire.rerun(repo, state='failure')
        before = copy.deepcopy(wire.rows)
        rows = self.read(wire)
        for index in range(2):
            value = self.context(rows, index)
            self.assertEqual(value['state'], 'failed')
            self.assertEqual(len(value['history']['failed_checks']), 1)
        self.assertEqual(wire.rows, before)

    def test_runtime_error_during_one_current_source_preserves_sibling_status(self):
        wire = Wire(2)
        def fail(repo, path):
            if wire.enriching and repo == 'example/project1' and '/contents/.hydra.toml' in path:
                raise RuntimeError(sources.CANARY)
        wire.before = fail
        try:
            rows = self.read(wire)
        except RuntimeError:
            self.fail('A provider RuntimeError must not destroy existing status')
        self.assertEqual(self.context(rows)['state'], 'failed')
        self.assertEqual(self.context(rows, 1)['state'], 'unknown')
        self.assertNotIn(sources.CANARY, json.dumps(rows))


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional pinned MCP SDK not installed')
class SourceReviewProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_error_history_keeps_real_mcp_status_and_private_sdk_logs_clean(self):
        from mcp import Client
        from hydra_sdlc.mcp import create_server
        wire = Wire(2)
        for repo in wire.rows:
            wire.rerun(repo, state='failure')
        def fail(repo, path):
            if wire.enriching and repo == 'example/project1' and '/attempts/' in path:
                raise RuntimeError(sources.CANARY)
        wire.before = fail
        with tempfile.TemporaryDirectory() as directory, wire.installed_boundary() as github:
            controller = NativeController(github, wire.workspace, repos=wire.rows,
                host_alias='local-host', lock_path=Path(directory) / 'host.lock')
            with self.assertNoLogs('mcp', level='ERROR'):
                async with Client(create_server(controller)) as client:
                    reply = await client.call_tool('hydra_status', {})
                self.assertFalse(reply.is_error, 'Provider failures must stay sanitized status data')
            value = reply.structured_content or json.loads(reply.content[0].text)
            self.assertEqual([row['post_merge_context']['state'] for row in value['projects']], ['failed', 'failed'])
            self.assertEqual(value['projects'][0]['post_merge_context']['history']['coverage']['state'], 'complete')
            self.assertNotEqual(value['projects'][1]['post_merge_context']['history']['coverage']['state'], 'complete')
            self.assertNotIn(sources.CANARY, json.dumps(value))
