"""PC-D05/10: fixed-config CLI binds before it loads an execution provider."""
import unittest
from unittest.mock import patch

from hydra_sdlc import cli
import test_project_connection as fixture


class ConnectionCLITests(unittest.IsolatedAsyncioTestCase):
    setUp = fixture.ConnectionBindingTests.setUp
    text = fixture.ConnectionBindingTests.text
    write = fixture.ConnectionBindingTests.write
    load = fixture.ConnectionBindingTests.load
    state = fixture.ConnectionBindingTests.state

    async def test_current_config_reaches_the_engine_and_foreign_argv_cannot_load_a_provider(self):
        cfg = self.load()
        self.state(cfg)
        argv = ['run', '--issue', 'https://github.com/example/alpha/issues/1',
            '--host-alias', 'fixture', '--workspace-root', str(self.root / 'work'),
            '--lock-path', str(self.lock), '--config', str(self.path)]
        try:
            args = cli.parser().parse_args(argv)
        except SystemExit:
            args = None
        self.assertIsNotNone(args, 'The fixed configuration entry must be available')
        with patch.object(cli, '_provider', return_value=None), patch('hydra_sdlc.runner.Runner',
                side_effect=RuntimeError('BOUND_CLI_REACHED_ENGINE')):
            with self.assertRaisesRegex(RuntimeError, 'BOUND_CLI_REACHED_ENGINE'):
                await cli.operate(args, github=object(), workspace=object(), emit=lambda value: None)
        args.host_alias = 'foreign'
        with patch.object(cli, '_provider', side_effect=AssertionError('Foreign argument reached provider')):
            with self.assertRaises(ValueError):
                await cli.operate(args, github=object(), emit=lambda value: None)
