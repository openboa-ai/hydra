"""Host adapters prepare argv; the runtime owns actual wrapped verification."""

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from hydra_sdlc import coordinator, execution_boundary
from hydra_sdlc.workspace import Workspace, WorkspaceWait


TOKENS = ('GH_TOKEN', 'GITHUB_TOKEN', 'GH_ENTERPRISE_TOKEN', 'GITHUB_ENTERPRISE_TOKEN')
REDIRECTS = ('GIT_DIR', 'GIT_WORK_TREE', 'GIT_INDEX_FILE', 'GIT_CONFIG_COUNT')


class StorageWrapperTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.path = self.root / 'work' / 'example' / 'product' / 'issue-1'
        self.path.mkdir(parents=True)
        self.nested = self.path / 'nested'
        self.nested.mkdir()
        self.resources = self.root / 'resources'
        self.resources.mkdir()
        self.wrapper = self.root / 'storage-wrapper.py'
        self.wrapper.write_text(
            'import os,sys\nfrom pathlib import Path\n'
            f'assert not any(name in os.environ for name in {TOKENS + REDIRECTS!r})\n'
            'resources,root,cwd = map(Path, sys.argv[1:4])\n'
            'assert Path.cwd() == root\n'
            'assert cwd.resolve().is_relative_to(root.resolve())\n'
            "for name,relative in [('TMPDIR','tmp'),('PIP_CACHE_DIR','cache')]:\n"
            '    target = resources / relative\n'
            '    target.mkdir(exist_ok=True)\n'
            '    os.environ[name] = str(target)\n'
            'os.chdir(cwd)\n'
            'os.execv(sys.argv[4], sys.argv[4:])\n'
        )
        self.provider = SimpleNamespace(wrap_command=Mock(side_effect=lambda path, argv, cwd: [
            sys.executable, '-I', str(self.wrapper), str(self.resources), str(path), str(cwd), *argv,
        ]))
        self.workspace = Workspace(self.root / 'work', storage_provider=self.provider)
        identity = patch.object(self.workspace, '_identity', return_value=(self.path, 'example/product', 1))
        identity.start()
        self.addCleanup(identity.stop)

    def command(self, code='pass', **options):
        return {'argv': [sys.executable, '-I', '-c', code], 'timeout': 3, **options}

    def test_actual_wrapper_is_owned_and_both_processes_receive_sanitized_environment(self):
        lock = self.root / 'host.lock'
        real_popen = subprocess.Popen

        def spawn(*args, **kwargs):
            self.assertTrue(lock.read_bytes(), 'verification ownership must precede spawn')
            self.assertEqual(kwargs['cwd'], self.path)
            self.assertTrue(all(name not in kwargs['env'] for name in TOKENS + REDIRECTS))
            return real_popen(*args, **kwargs)

        code = (
            'import json,os\n'
            f'assert not any(name in os.environ for name in {TOKENS + REDIRECTS!r})\n'
            "print(json.dumps({'cwd':os.getcwd(),'tmp':os.environ['TMPDIR'],'cache':os.environ['PIP_CACHE_DIR']}))"
        )
        injected = {name: 'synthetic-publishing-secret' for name in TOKENS + REDIRECTS}
        with patch.dict(os.environ, injected), coordinator.coordinator_lock(lock), patch.object(
            execution_boundary.subprocess, 'Popen', side_effect=spawn,
        ) as launched:
            records = self.workspace.verify(self.path, [self.command(code, cwd='nested')])
            launched.assert_called_once()
            self.assertEqual(lock.read_bytes(), b'')
            self.assertTrue(all(os.environ[name] == value for name, value in injected.items()))
        self.assertTrue(records[0]['passed'])
        self.assertEqual(records[0]['cwd'], 'nested')
        self.provider.wrap_command.assert_called_once_with(self.path, self.command(code)['argv'], self.nested)
        output = self.workspace.verification_output(records[0]['output_digest'])
        self.assertEqual(json.loads(output), {
            'cwd': str(self.nested), 'tmp': str(self.resources / 'tmp'), 'cache': str(self.resources / 'cache'),
        })
        self.assertNotIn('synthetic-publishing-secret', output)
        self.assertEqual(records[0]['argv'], self.command(code)['argv'])

    def test_legacy_and_malformed_providers_cannot_fabricate_execution_evidence(self):
        legacy = SimpleNamespace(run=Mock(return_value=subprocess.CompletedProcess(['true'], 0, b'pass')))
        providers = [legacy, SimpleNamespace(wrap_command=None)] + [
            SimpleNamespace(wrap_command=Mock(return_value=value)) for value in (
                None, 'true', ('true',), {}, [], [''], [1], ['bad\0argument'],
                subprocess.CompletedProcess(['true'], 0, b'pass'),
            )
        ]
        for provider in providers:
            with self.subTest(provider=provider), patch('hydra_sdlc.workspace._run') as execute:
                self.workspace.storage_provider = provider
                with self.assertRaisesRegex(WorkspaceWait, 'invalid_storage_provider_contract'):
                    self.workspace.verify(self.path, [self.command()])
                execute.assert_not_called()
                self.assertEqual(self.workspace._outputs, {})
        legacy.run.assert_not_called()

    def test_stop_before_construction_cannot_call_provider_or_execute(self):
        with patch('hydra_sdlc.workspace._run') as execute:
            with self.assertRaisesRegex(WorkspaceWait, 'verification_stopped'):
                self.workspace.verify(self.path, [self.command()], stop_requested=lambda: True)
            execute.assert_not_called()
        self.provider.wrap_command.assert_not_called()

    def test_stop_at_successful_return_cannot_pass_or_construct_a_later_command(self):
        stopped = False
        real_run = execution_boundary.run_owned_sync

        def finish(*args, **kwargs):
            nonlocal stopped
            result = real_run(*args, **kwargs)
            stopped = True
            return result

        with patch.object(execution_boundary, 'run_owned_sync', side_effect=finish) as execute:
            with self.assertRaisesRegex(WorkspaceWait, 'verification_stopped'):
                self.workspace.verify(self.path, [self.command(), self.command()], stop_requested=lambda: stopped)
        self.assertEqual(execute.call_count, 1)
        self.assertEqual(self.provider.wrap_command.call_count, 1)
        self.assertEqual(self.workspace._outputs, {})

    def test_unconfirmed_cleanup_preserves_owner_and_blocks_restart(self):
        lock = self.root / 'host.lock'
        with coordinator.coordinator_lock(lock), patch.object(
            coordinator, 'confirm_owned_cleanup', side_effect=RuntimeError('cleanup confirmation unavailable'),
        ):
            with self.assertRaisesRegex(WorkspaceWait, 'verification_cleanup_unknown') as raised:
                self.workspace.verify(self.path, [self.command(), self.command()])
            self.assertTrue(raised.exception.uncertain)
            self.assertTrue(lock.read_bytes())
        self.assertEqual(self.provider.wrap_command.call_count, 1)
        self.assertEqual(self.workspace._outputs, {})
        with self.assertRaises(coordinator.HostBusy):
            with coordinator.coordinator_lock(lock):
                self.fail('Unconfirmed wrapped verification was admitted on restart')

    def test_live_wrapped_process_stop_reaps_group_and_does_not_start_later_command(self):
        marker = self.path / 'owned-pids'
        code = (
            'import os,subprocess,sys,time\nfrom pathlib import Path\n'
            "child = subprocess.Popen([sys.executable,'-I','-c','import time; time.sleep(60)'])\n"
            "Path('owned-pids').write_text(str(os.getpid())+' '+str(child.pid))\n"
            'time.sleep(60)\n'
        )
        lock = self.root / 'host.lock'
        with coordinator.coordinator_lock(lock):
            with self.assertRaisesRegex(WorkspaceWait, 'verification_stopped'):
                self.workspace.verify(self.path, [self.command(code), self.command()], stop_requested=marker.exists)
            self.assertEqual(lock.read_bytes(), b'')
        self.assertEqual(self.provider.wrap_command.call_count, 1)
        self.assertEqual(self.workspace._outputs, {})
        for pid in map(int, marker.read_text().split()):
            deadline = time.monotonic() + 2
            while True:
                try:
                    os.kill(pid, 0)
                except ProcessLookupError:
                    break
                if time.monotonic() >= deadline:
                    self.fail('Stopped wrapped verification retained an owned process')
                time.sleep(.01)

    def test_wrapped_verifier_uses_original_timeout_and_stops_sequence(self):
        records = self.workspace.verify(self.path, [
            self.command('import time; time.sleep(60)', timeout=.3), self.command(),
        ])
        self.assertEqual(len(records), 1)
        self.assertFalse(records[0]['passed'])
        self.assertLess(records[0]['exit_code'], 0)
        self.assertEqual(self.provider.wrap_command.call_count, 1)


if __name__ == '__main__':
    unittest.main()
