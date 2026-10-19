"""CP-D09/12/18 store boundary; not native control or MCP authority evidence."""
from pathlib import Path
import errno
import json
import os
import select
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc.operations import MAX_REVISION, OperatingControl, OperationDenied, OperationUncertain


class AdmissionCASTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.control = OperatingControl(self.root / 'host.lock', ('example/alpha', 'example/beta'))
        self.control.set_mode('start')

    def test_noop_preserves_bytes_revision_and_time(self):
        before = self.control.snapshot()
        payload = self.control.settings_path.read_bytes()
        after = self.control.set_mode_if_current('resume', expected_revision=before['revision'])
        self.assertEqual(after, before)
        self.assertEqual(self.control.settings_path.read_bytes(), payload)

    def test_stale_same_mode_is_not_success(self):
        old = self.control.snapshot()['revision']
        self.control.set_mode('pause', 'example/alpha')
        payload = self.control.settings_path.read_bytes()
        with self.assertRaises(OperationDenied) as error:
            self.control.set_mode_if_current('pause', 'example/alpha', expected_revision=old)
        self.assertEqual(error.exception.reason, 'stale_revision')
        self.assertEqual(self.control.settings_path.read_bytes(), payload)

    def apply(self, action, repo='example/alpha'):
        return self.control.set_mode_if_current(action, repo,
            expected_revision=self.control.snapshot()['revision'])

    def test_target_and_host_limits_are_preserved(self):
        self.control.set_mode('stop', 'example/beta')
        before = self.control.snapshot()['revision']
        paused = self.apply('pause')
        self.assertEqual(paused['revision'], before + 1)
        self.assertEqual(paused['projects'], {'example/alpha': 'paused', 'example/beta': 'stopped'})
        self.assertEqual(self.apply('resume')['projects']['example/alpha'], 'running')
        self.apply('pause', None)
        with self.assertRaises(OperationDenied) as error:
            self.apply('resume')
        self.assertEqual(error.exception.reason, 'host_paused')
        self.assertEqual(self.control.snapshot()['projects']['example/beta'], 'stopped')

    def test_stronger_stop_and_max_revision_noop(self):
        self.apply('stop')
        before = self.control.snapshot()
        self.assertEqual(self.apply('pause'), before)
        before['revision'] = MAX_REVISION
        self.control.settings_path.write_text(json.dumps(before))
        payload = self.control.settings_path.read_bytes()
        self.assertEqual(self.apply('pause'), before)
        self.assertEqual(self.control.settings_path.read_bytes(), payload)
        with self.assertRaises(OperationDenied) as error:
            self.apply('resume')
        self.assertEqual(error.exception.reason, 'operation_state_revision_exhausted')

    def test_pause_under_stopped_host_stores_project_override(self):
        self.control.set_mode('stop')
        after = self.apply('pause')
        self.assertEqual(after['global_mode'], 'stopped')
        self.assertEqual(after['projects']['example/alpha'], 'paused')
        self.apply('resume', None)
        self.assertEqual(self.control.reason('example/alpha'), 'project_paused')

    def test_invalid_expected_never_creates_files(self):
        control = OperatingControl(self.root / 'new' / 'host.lock', ('example/alpha',))
        for expected in (None, True, False, -1, MAX_REVISION + 1, '0', []):
            with self.subTest(expected=expected), self.assertRaises(OperationDenied):
                control.set_mode_if_current('pause', 'example/alpha', expected_revision=expected)
            self.assertFalse((self.root / 'new').exists())

    def test_before_replace_error_is_definite_and_after_replace_is_unknown(self):
        before = self.control.settings_path.read_bytes()
        with patch('hydra_sdlc.operations.os.fsync', side_effect=OSError(errno.EIO, 'injected')):
            with self.assertRaises(OperationDenied) as error:
                self.apply('pause')
        self.assertNotIsInstance(error.exception, OperationUncertain)
        self.assertEqual(self.control.settings_path.read_bytes(), before)
        original = os.fsync
        calls = []
        def fail_parent(fd):
            calls.append(fd)
            if len(calls) == 2:
                raise OSError(errno.EIO, 'injected')
            return original(fd)
        with patch('hydra_sdlc.operations.os.fsync', side_effect=fail_parent):
            with self.assertRaises(OperationUncertain) as error:
                self.apply('pause')
        self.assertEqual(error.exception.observation['projects']['example/alpha'], 'paused')
        self.assertEqual(self.control.snapshot()['revision'], 2)

    def test_failed_readback_and_restart_do_not_manufacture_receipt(self):
        original = self.control._read
        calls = []
        def fail_readback(held):
            calls.append(1)
            # _set_mode read, pre-replace fingerprint, post-replace read-back.
            if len(calls) == 3:
                raise OperationDenied('operation_state_unavailable')
            return original(held)
        with patch.object(self.control, '_read', side_effect=fail_readback):
            with self.assertRaises(OperationUncertain) as error:
                self.control.set_mode_if_current('pause', 'example/alpha', expected_revision=1)
        self.assertEqual(len(calls), 4)  # exactly one recovery observation
        self.assertEqual(error.exception.observation['revision'], 2)
        restarted = OperatingControl(self.root / 'host.lock', ('example/alpha', 'example/beta'))
        with self.assertRaises(OperationDenied) as stale:
            restarted.set_mode_if_current('pause', 'example/alpha', expected_revision=1)
        self.assertEqual(stale.exception.reason, 'stale_revision')

    def test_post_write_lock_exit_failure_is_unknown(self):
        original = self.control._check_lock
        calls = []
        def fail_exit(held):
            calls.append(1)
            if len(calls) == 3:
                raise OperationDenied('operation_state_unsafe')
            return original(held)
        with patch.object(self.control, '_check_lock', side_effect=fail_exit):
            with self.assertRaises(OperationUncertain) as error:
                self.control.set_mode_if_current('pause', 'example/alpha', expected_revision=1)
        self.assertEqual(error.exception.observation['revision'], 2)
        self.assertEqual(error.exception.observation['projects']['example/alpha'], 'paused')

    def test_descriptor_exit_failure_and_failed_observation_remain_unknown(self):
        close = os.close
        check = self.control._check_lock
        lock = []
        def remember(held):
            if not lock:
                lock.append(held.lock)
            return check(held)
        failed = []
        def fail_close(fd):
            close(fd)
            if lock and fd == lock[0] and not failed:
                failed.append(True)
                raise OSError(errno.EIO, 'injected close failure')
        with patch.object(self.control, '_check_lock', side_effect=remember), \
                patch('hydra_sdlc.operations.os.close', side_effect=fail_close), \
                patch.object(self.control, 'snapshot', side_effect=OperationDenied('operation_state_unsafe')) as read:
            with self.assertRaises(OperationUncertain) as error:
                self.control.set_mode_if_current('pause', 'example/alpha', expected_revision=1)
        self.assertIsNone(error.exception.observation)
        read.assert_called_once_with()
        self.assertEqual(self.control.snapshot()['revision'], 2)

    def process(self, program):
        child = subprocess.Popen([sys.executable, '-c', program, str(self.root / 'host.lock')],
                                 stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def cleanup():
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)
        self.addCleanup(cleanup)
        return child

    def line(self, child):
        self.assertTrue(select.select([child.stdout], [], [], 5)[0], 'child did not respond')
        return child.stdout.readline().strip()

    def test_two_process_same_revision_one_wins_even_for_same_mode(self):
        program = '''
import sys
from hydra_sdlc.operations import OperatingControl, OperationDenied
c=OperatingControl(sys.argv[1], ('example/alpha','example/beta'))
print('ready',flush=True)
sys.stdin.readline()
try:
 result=c.set_mode_if_current('pause','example/alpha',expected_revision=1)
 print('applied:'+str(result['revision']),flush=True)
except OperationDenied as e:
 print(e.reason,flush=True)
'''
        a, b = self.process(program), self.process(program)
        self.assertEqual(self.line(a), 'ready')
        self.assertEqual(self.line(b), 'ready')
        for child in (a, b):
            child.stdin.write('\n')
            child.stdin.flush()
        self.assertCountEqual([self.line(a), self.line(b)], ['applied:2', 'stale_revision'])
        self.assertEqual(self.control.snapshot()['revision'], 2)

    def test_effect_finishes_before_pause_and_new_effect_is_denied(self):
        child = self.process('''
import sys
from hydra_sdlc.operations import OperatingControl
c=OperatingControl(sys.argv[1], ('example/alpha','example/beta'))
with c.guard('example/alpha'):
 print('inside',flush=True)
 sys.stdin.readline()
 print('effect-done',flush=True)
''')
        self.assertEqual(self.line(child), 'inside')
        # The existing store blocks synchronous exclusive acquisition until the
        # cooperating bounded effect releases its shared lock.
        writer = self.process('''
import sys
from hydra_sdlc.operations import OperatingControl
c=OperatingControl(sys.argv[1], ('example/alpha','example/beta'))
print('requesting',flush=True)
c.set_mode_if_current('pause','example/alpha',expected_revision=1)
print('applied',flush=True)
''')
        self.assertEqual(self.line(writer), 'requesting')
        self.assertFalse(select.select([writer.stdout], [], [], 0.05)[0])
        child.stdin.write('\n')
        child.stdin.flush()
        self.assertEqual(self.line(child), 'effect-done')
        self.assertEqual(self.line(writer), 'applied')
        with self.assertRaises(OperationDenied):
            with self.control.guard('example/alpha'):
                self.fail('new effect admitted after pause')
