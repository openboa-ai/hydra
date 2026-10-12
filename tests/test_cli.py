import asyncio
from contextlib import ExitStack
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from hydra_sdlc.cli import operate, parser
from hydra_sdlc.coordinator import HostBusy, coordinator_lock, residual_workers
from hydra_sdlc.operations import OperatingControl


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
            with self.subTest(command=command, timeout=timeout), tempfile.TemporaryDirectory() as directory:
                target = ['--issue', 'https://github.com/example/product/issues/1'] if command == 'run' else ['--repos', 'example/product']
                values = [command, *target, '--workspace-root', '/owned/workspaces', '--host-alias', 'host-a']
                if timeout is not None:
                    values.append('--timeout=' + timeout)
                args = parser().parse_args(values)
                operations = OperatingControl(Path(directory) / 'host.lock', ['example/product'])
                operations.set_mode('start')
                with patch('hydra_sdlc.runner.Runner') as runner, patch('hydra_sdlc.cli.coordinator_lock') as lock, \
                        patch('hydra_sdlc.cli.residual_workers', return_value=[]):
                    runner.return_value.stop_requested.return_value = True
                    runner.return_value.host_hold_reason = None
                    result = asyncio.run(operate(args, github=object(), workspace=object(), operations=operations))
                    self.assertEqual(result, {'action': 'stopped', 'reason': 'signal_or_deadline'})
                    runner.assert_called_once()
                    lock.assert_called_once_with(args.lock_path)

    def test_missing_controls_block_foreground_before_provider_or_admission(self):
        with tempfile.TemporaryDirectory() as directory:
            lock_path = Path(directory) / 'host.lock'
            args = parser().parse_args(['serve', '--repos', 'example/product',
                '--workspace-root', directory, '--host-alias', 'host-a', '--lock-path', str(lock_path)])
            with patch('hydra_sdlc.cli._provider') as provider, \
                    patch('hydra_sdlc.cli.coordinator_lock') as acquire:
                result = asyncio.run(operate(args, github=object(), emit=lambda _: None))
                self.assertEqual(result, {'action': 'waiting', 'reason': 'host_stopped'})
                provider.assert_not_called()
                acquire.assert_not_called()
            self.assertFalse(lock_path.exists())

    def test_control_requires_an_explicit_mutation_target_before_config_read(self):
        from hydra_sdlc.cli import operate_control
        args = parser().parse_args(['control', 'stop', '--config', '/not-read/host.toml'])
        with patch('hydra_sdlc.control.load_host_config') as read:
            with self.assertRaises(ValueError):
                operate_control(args)
            read.assert_not_called()

    def test_control_never_loads_runtime_or_provider_factories(self):
        from hydra_sdlc.cli import operate_control
        args = parser().parse_args(['control', 'pause', '--config', '/installed/host.toml', '--all'])
        with patch('hydra_sdlc.control.load_host_config', return_value={'fixture': True}), \
                patch('hydra_sdlc.control.control_result', return_value={'request': 'applied'}) as control, \
                patch('hydra_sdlc.cli._provider') as provider:
            self.assertEqual(operate_control(args), {'request': 'applied'})
            control.assert_called_once_with({'fixture': True}, action='pause', repository=None, refresh=False)
            provider.assert_not_called()

    def test_residual_capability_and_execution_workers_both_hold_startup(self):
        with patch('hydra_sdlc.coordinator.subprocess.run') as run:
            run.return_value.stdout = ('12 python /installed/hydra_sdlc/codex.py --capability-worker /work\n'
                                      '13 python /installed/hydra_sdlc/execution_boundary.py --execution-worker\n'
                                      '14 python unrelated.py --capability-worker\n')
            self.assertEqual(residual_workers(), ['12', '13'])

    def test_residual_reaper_helper_holds_startup_without_sdk_worker(self):
        with patch('hydra_sdlc.coordinator.subprocess.run') as run:
            run.return_value.stdout = (
                '15 python /installed/hydra_sdlc/execution_boundary.py --owned-process-helper 4 12 []\n'
                '16 python /installed/hydra_sdlc/codex.py --owned-process-helper 4 12 []\n'
                '17 python unrelated.py --owned-process-helper 4 12 []\n'
                '18 python /installed/hydra_sdlc/execution_boundary.py --owned-process-helper-extra\n'
            )
            self.assertEqual(residual_workers(), ['15'])


if __name__ == '__main__':
    unittest.main()
