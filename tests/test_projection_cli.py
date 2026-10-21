"""The explicit v3 read profile has no mutation or legacy fallback."""
import asyncio
import copy
import io
import json
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from hydra_sdlc.cli import main, operate, operate_control, parser
from hydra_sdlc import projection as p
from test_control_projection import minimal as frame, EPOCH, REQUEST


class ProjectionCliTests(unittest.TestCase):
    def test_maximum_utf8_frame_crosses_sync_and_default_async_stdout_without_extra_bytes(self):
        from test_projection_read import ReadFixture, issue
        value = ReadFixture({('example/alpha', 'open', False): [issue()]}).read(repository='example/alpha')
        source = next(o for o in value['observations'] if o['resource']['kind'] == 'issue')
        source['value'].update(title='🚀', description_excerpt='', description_truncated=False)
        size = lambda: len(json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode())
        n = 0
        while p.MAX_BYTES - size() > 4096:
            n += 1
            value['observations'].append({'key': 'github:check:max:' + str(n),
                'resource': {'source': 'github', 'kind': 'check', 'id': 'max:' + str(n)},
                'revision': None, 'observed_at': value['assembled_at'], 'last_attempt_at': value['assembled_at'],
                'availability': 'current', 'reason': None,
                'coverage': {'state': 'complete', 'scope': 'max:' + str(n), 'returned_count': 1,
                    'total_count': 1, 'next_cursor': None, 'reason': None},
                'value': {'producer': None, 'name': 'fixture', 'head': 'a' * 40, 'status': 'completed',
                    'conclusion': 'success', 'url': 'https://github.com/example/alpha/actions/runs/1?padding=' + 'x' * 1800}})
        padding = p.MAX_BYTES - size()
        self.assertTrue(0 <= padding <= 4096)
        source['value']['description_excerpt'] = 'x' * padding
        encoded = p.encode(value)
        self.assertEqual(len(encoded), p.MAX_BYTES)
        for asynchronous in (False, True):
            with self.subTest(asynchronous=asynchronous):
                output = io.StringIO()
                with patch('hydra_sdlc.control.load_host_config', return_value={'repos': ['example/alpha']}), \
                     patch('hydra_sdlc.projection_read.read_projection', return_value=value), redirect_stdout(output):
                    if asynchronous:
                        asyncio.run(operate(self.args()))
                    else:
                        self.assertEqual(main(['control','status','--config','/example/host.toml',
                            '--projection-schema','3','--binding-epoch',EPOCH,'--request-id',REQUEST]), 0)
                self.assertEqual(len(output.getvalue().encode()), p.MAX_BYTES)
                self.assertEqual(output.getvalue().encode(), encoded)

    def args(self, *extra):
        return parser().parse_args(['control', 'status', '--config', '/example/host.toml',
            '--projection-schema', '3', '--binding-epoch', EPOCH, '--request-id', REQUEST, *extra])

    def test_read_profile_uses_actual_strict_encoder_for_sync_and_async_entry(self):
        value = frame()
        with patch('hydra_sdlc.control.load_host_config', return_value={'repos': ['example/alpha']}) as config, \
             patch('hydra_sdlc.projection_read.read_projection', return_value=value) as read, \
             patch('hydra_sdlc.control.control_result') as legacy, patch('builtins.print') as output:
            self.assertEqual(main(['control', 'status', '--config', '/example/host.toml',
                '--projection-schema', '3', '--binding-epoch', EPOCH, '--request-id', REQUEST, '--refresh']), 0)
            self.assertEqual(output.call_args.args[0].encode(), p.encode(value))
            read.assert_called_once_with({'repos': ['example/alpha']}, binding_epoch=EPOCH,
                request_id=REQUEST, repository=None, refresh=True)
            sent = []
            self.assertEqual(asyncio.run(operate(self.args('--repository', 'example/alpha'), emit=sent.append)), value)
            self.assertEqual(sent, [p.encode(value).decode()])
            legacy.assert_not_called()

    def test_bad_profiles_and_mutations_stop_before_config_or_provider(self):
        cases = [self.args('--all'), self.args('--project', 'example/alpha'), self.args()]
        cases[2].action = 'pause'
        for name, value in [('binding_epoch', None), ('request_id', 'not-a-uuid'), ('projection_schema', 1)]:
            args = self.args(); setattr(args, name, value); cases.append(args)
        old = self.args(); old.projection_schema = 2; cases.append(old)
        with patch('hydra_sdlc.control.load_host_config') as config, \
             patch('hydra_sdlc.cli._provider') as provider:
            for args in cases:
                with self.subTest(action=args.action, epoch=args.binding_epoch, request=args.request_id):
                    with self.assertRaises(ValueError):
                        operate_control(args)
            config.assert_not_called(); provider.assert_not_called()

    def test_invalid_v3_never_prints_a_legacy_or_partial_success(self):
        value = copy.deepcopy(frame()); value['retry_hints'] = 'bad'
        with patch('hydra_sdlc.control.load_host_config', return_value={}), \
             patch('hydra_sdlc.projection_read.read_projection', return_value=value), \
             patch('builtins.print') as output:
            self.assertEqual(main(['control', 'status', '--config', '/example/host.toml',
                '--projection-schema', '3', '--binding-epoch', EPOCH, '--request-id', REQUEST]), 1)
            self.assertEqual(output.call_count, 1)
            self.assertIn('file', output.call_args.kwargs)
