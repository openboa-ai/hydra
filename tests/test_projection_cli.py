"""The explicit v3 read profile has no mutation or legacy fallback."""
import asyncio
import copy
import unittest
from unittest.mock import patch

from hydra_sdlc.cli import main, operate, operate_control, parser
from hydra_sdlc import projection as p
from test_control_projection import minimal as frame, EPOCH, REQUEST


class ProjectionCliTests(unittest.TestCase):
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
