import tempfile
import unittest
from pathlib import Path

from hydra_sdlc.cli import parser
from hydra_sdlc.coordinator import HostBusy, coordinator_lock


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


if __name__ == '__main__':
    unittest.main()
