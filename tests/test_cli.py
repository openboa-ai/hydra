import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

from hydra_sdlc.cli import parser
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

    def test_residual_capability_and_execution_workers_both_hold_startup(self):
        with patch('hydra_sdlc.coordinator.subprocess.run') as run:
            run.return_value.stdout = ('12 python /installed/hydra_sdlc/codex.py --capability-worker /work\n'
                                      '13 python /installed/hydra_sdlc/execution_boundary.py --execution-worker\n'
                                      '14 python unrelated.py --capability-worker\n')
            self.assertEqual(residual_workers(), ['12', '13'])


if __name__ == '__main__':
    unittest.main()
