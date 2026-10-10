import asyncio
from contextlib import ExitStack
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from hydra_sdlc.cli import operate, parser
from hydra_sdlc.coordinator import HostBusy, coordinator_lock, residual_workers


class CliTests(unittest.TestCase):
    def test_three_commands_without_database_flag(self):
        p = parser()
        args = p.parse_args(['run', '--issue', 'https://github.com/example/product/issues/1',
                             '--workspace-root', '/owned/workspaces', '--host-alias', 'host-a'])
        self.assertFalse(hasattr(args, 'state'))
        self.assertEqual(args.command, 'run')
        self.assertEqual(p.parse_args(['status', '--repos', 'example/product']).command, 'status')

    def test_same_host_duplicate_launch_is_refused_without_state_file(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = Path(directory) / 'host.lock'
            with coordinator_lock(lock):
                with self.assertRaises(HostBusy):
                    with coordinator_lock(lock):
                        self.fail('duplicate acquired lock')
            with coordinator_lock(lock):
                self.assertEqual([p.name for p in Path(directory).iterdir()], ['host.lock'])

    def test_nonpositive_and_nonfinite_timeouts_refuse_before_runtime_acquisition(self):
        for command in ('run', 'serve'):
            target = ['--issue', 'https://github.com/example/product/issues/1'] if command == 'run' else ['--repos', 'example/product']
            for value in ('nan', 'inf', '-inf', '1e309', '0', '-1'):
                with self.subTest(command=command, timeout=value), ExitStack() as stack:
                    args = parser().parse_args([command, *target, '--workspace-root', '/owned/workspaces',
                                                '--host-alias', 'host-a', '--timeout=' + value])
                    runtime = [stack.enter_context(patch(name)) for name in (
                        'hydra_sdlc.github.GitHub', 'hydra_sdlc.workspace.Workspace',
                        'hydra_sdlc.codex.execute', 'hydra_sdlc.codex.capabilities',
                        'hydra_sdlc.cli.coordinator_lock', 'hydra_sdlc.cli._provider')]
                    with self.assertRaisesRegex(ValueError, 'finite and positive'):
                        asyncio.run(operate(args))
                    for entry in runtime:
                        entry.assert_not_called()

    def test_positive_finite_timeout_and_untimed_serve_reach_runtime(self):
        for command, timeout in (('run', '1.5'), ('serve', '1.5'), ('serve', None)):
            with self.subTest(command=command, timeout=timeout):
                target = ['--issue', 'https://github.com/example/product/issues/1'] if command == 'run' else ['--repos', 'example/product']
                values = [command, *target, '--workspace-root', '/owned/workspaces', '--host-alias', 'host-a']
                if timeout is not None:
                    values.append('--timeout=' + timeout)
                args = parser().parse_args(values)
                with patch('hydra_sdlc.runner.Runner') as runner, patch('hydra_sdlc.cli.coordinator_lock') as lock, \
                        patch('hydra_sdlc.cli.residual_workers', return_value=[]):
                    runner.return_value.stop_requested.return_value = True
                    result = asyncio.run(operate(args, github=object(), workspace=object()))
                    self.assertEqual(result, {'action': 'stopped', 'reason': 'signal_or_deadline'})
                    runner.assert_called_once()
                    lock.assert_called_once_with(args.lock_path)

    def test_residual_capability_and_execution_workers_both_hold_startup(self):
        with patch('hydra_sdlc.coordinator.subprocess.run') as run:
            run.return_value.stdout = ('12 python /installed/hydra_sdlc/codex.py --capability-worker /work\n'
                                      '13 python /installed/hydra_sdlc/execution_boundary.py --execution-worker\n'
                                      '14 python unrelated.py --capability-worker\n')
            self.assertEqual(residual_workers(), ['12', '13'])


if __name__ == '__main__':
    unittest.main()
