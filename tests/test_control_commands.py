"""P02: real admission effects behind a typed internal call boundary, no native client."""
import asyncio
import copy
import errno
import fcntl
from datetime import datetime, timezone, timedelta
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from unittest.mock import patch

from hydra_sdlc.control import control_from_config, load_host_config
from hydra_sdlc.control_commands import (
    AdmissionCallContext, InvalidAdmissionCommand, execute_admission_command,
)
from hydra_sdlc.operations import MAX_REVISION, OperatingControl, OperationDenied, OperationUncertain
from hydra_sdlc.runtime_identity import capture_runtime_identity


EPOCH = '11111111-1111-4111-8111-111111111111'
REQUEST = '22222222-2222-4222-8222-222222222222'


COMMAND_PROCESS = '''
import errno, json, os, sys
from unittest.mock import patch
from hydra_sdlc.control_commands import AdmissionCallContext, execute_admission_command
from hydra_sdlc.operations import OperatingControl
command = json.loads(sys.stdin.readline())
context = AdmissionCallContext('bridge', '11111111-1111-4111-8111-111111111111', frozenset({101, 202}))
class RepositoryReader:
    def repository(self, name):
        return {'id': {'example/alpha': 101, 'example/beta': 202}[name], 'full_name': name}
def execute():
    return execute_admission_command(sys.argv[1], command,
        context_provider=lambda: context, github=RepositoryReader())
if sys.argv[2] == 'uncertain':
    fsync, snapshot, calls = os.fsync, OperatingControl.snapshot_observed, []
    def fail_parent(fd):
        calls.append(fd)
        if len(calls) == 2:
            raise OSError(errno.EIO, 'injected post-replace failure')
        return fsync(fd)
    def recovery(control, *args, **kwargs):
        print('recovery', flush=True)
        sys.stdin.readline()
        return snapshot(control, *args, **kwargs)
    with patch('hydra_sdlc.operations.os.fsync', side_effect=fail_parent), \\
            patch.object(OperatingControl, 'snapshot_observed', recovery):
        result = execute()
else:
    result = execute()
print(json.dumps(result), flush=True)
'''


class RepositoryReader:
    def __init__(self):
        self.rows = {'example/alpha': {'id': 101, 'full_name': 'example/alpha'},
                     'example/beta': {'id': 202, 'full_name': 'example/beta'}}
        self.calls = []
        self.during_read = None

    def repository(self, name):
        self.calls.append(name)
        if self.during_read:
            self.during_read()
        result = self.rows[name]
        if isinstance(result, Exception):
            raise result
        return copy.deepcopy(result)


class AdmissionCommandTests(unittest.TestCase):
    def test_checkpoint_scope_does_not_grant_admission_writes(self):
        self.context = AdmissionCallContext('bridge', EPOCH, frozenset({101, 202}),
                                           frozenset({'workflow_step.checkpoint_only'}))
        before = self.payload()
        reply = self.run_command(self.command())
        self.assertEqual(reply['request']['reason'], 'authority_denied')
        self.assertEqual(self.payload(), before)

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.config_path = self.root / 'host.toml'
        self.config_text = ('repos=["example/alpha","example/beta"]\nhost_alias="fixture"\n'
                            'workspace_root="work"\nlock_path="locks/host.lock"\n')
        self.config_path.write_text(self.config_text)
        self.config_path.chmod(0o600)
        self.cfg = load_host_config(self.config_path)
        self.control = control_from_config(self.cfg)
        self.control.set_mode('start')
        self.runtime = capture_runtime_identity(self.cfg, self.control)
        self.context = AdmissionCallContext('bridge', EPOCH, frozenset({101, 202}))
        self.github = RepositoryReader()

    def command(self, mode='paused', repository_id=101):
        return {
            'command_schema': 1, 'request_id': REQUEST, 'binding_epoch': EPOCH,
            'action': 'admission_set',
            'target': {'kind': 'repository', 'repository_id': repository_id},
            'expected': {
                'runtime_key': json.dumps([self.runtime[k] for k in
                    ('version', 'code_digest', 'config_digest', 'control_binding_digest')], separators=(',', ':')),
                'admission_revision': self.control.snapshot()['revision'],
                'source_checks': [], 'assignment': None,
            },
            'effect_key': None, 'parameters': {'mode': mode},
        }

    def run_command(self, command):
        return execute_admission_command(self.config_path, command,
            context_provider=lambda: self.context, github=self.github)

    def payload(self):
        return self.control.settings_path.read_bytes()

    @contextmanager
    def command_process(self, command, *, uncertain=False):
        child = subprocess.Popen([sys.executable, '-c', COMMAND_PROCESS, str(self.config_path),
                                  'uncertain' if uncertain else 'normal'], stdin=subprocess.PIPE,
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        try:
            child.stdin.write(json.dumps(command) + '\n')
            child.stdin.flush()
            yield child
        finally:
            # Retire a failed test's blocked writer before its caller releases
            # the lock, so the oracle cannot accidentally permit a late effect.
            if child.poll() is None:
                child.kill()
            child.communicate(timeout=5)

    def process_line(self, child):
        self.assertTrue(select.select([child.stdout], [], [], 5)[0], 'command did not return before unlock')
        return child.stdout.readline().strip()

    def process_reply(self, child):
        result = json.loads(self.process_line(child))
        _, error = child.communicate(timeout=5)
        self.assertEqual(child.returncode, 0, error)
        return result

    def assert_rejected_without_write(self, command, reason=None):
        before = self.payload()
        result = self.run_command(command)
        self.assertEqual(result['request']['outcome'], 'rejected')
        if reason:
            self.assertEqual(result['request']['reason'], reason)
        self.assertIsNone(result['request']['receipt'])
        self.assertEqual(self.payload(), before)
        return result

    def test_stale_runtime_never_changes_admission(self):
        command = self.command()
        command['expected']['runtime_key'] = '["old","old","old","old"]'
        self.assert_rejected_without_write(command, 'stale_runtime')
        self.assertEqual(self.github.calls, [])

    def test_missing_authority_never_changes_admission(self):
        self.context = None
        self.assert_rejected_without_write(self.command(), 'authority_unavailable')
        self.assertEqual(self.github.calls, [])

    def test_pause_resume_has_exact_receipt_and_preserves_other_overrides(self):
        self.control.set_mode('stop', 'example/beta')
        command = self.command()
        result = self.run_command(command)
        self.assertEqual(set(result), {'command_schema', 'runtime', 'binding_epoch', 'request', 'observations'})
        self.assertEqual(result['runtime'], self.runtime)
        self.assertEqual(result['binding_epoch'], EPOCH)
        self.assertEqual(result['request']['outcome'], 'applied')
        observation = result['observations'][0]
        key = f'command:{REQUEST}:admission-readback'
        revision = {'kind': 'monotonic', 'value': '3'}
        ref = {'observation_key': key, 'revision': revision}
        resource = {'source': 'hydra', 'kind': 'admission', 'id': self.runtime['control_binding_digest']}
        self.assertEqual(observation['key'], key)
        self.assertEqual(observation['resource'], resource)
        self.assertEqual(observation['revision'], revision)
        self.assertEqual(observation['coverage'], {'state': 'complete', 'scope': key,
            'returned_count': 1, 'total_count': 1, 'next_cursor': None, 'reason': None})
        self.assertEqual(observation['availability'], 'current')
        self.assertIsNotNone(observation['observed_at'])
        self.assertEqual(observation['value'], {'revision': 3, 'global_mode': 'running',
            'project_overrides': {'example/alpha': 'paused', 'example/beta': 'stopped'},
            'gate_reason': 'project_paused'})
        self.assertEqual(result['request']['receipt'], {'kind': 'admission', 'readback': ref})
        self.assertEqual(result['request']['observed_refs'], [ref])
        self.assertEqual(result['request']['effect_refs'], [resource])
        resumed = self.run_command(self.command('running'))
        self.assertEqual(resumed['request']['outcome'], 'applied')
        self.assertEqual(self.control.snapshot()['projects'], {'example/alpha': 'running', 'example/beta': 'stopped'})
        with self.control.guard('example/alpha'):
            pass

    def test_malformed_commands_never_reach_sources_or_write(self):
        mutations = [
            lambda c: c.update(command_schema=True), lambda c: c.update(command_schema=0),
            lambda c: c.update(request_id='not-a-uuid'),
            lambda c: c.update(request_id='AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA'),
            lambda c: c.update(request_id='\ud800'), lambda c: c.update(binding_epoch='x' * 1024),
            lambda c: c.update(authorized=True), lambda c: c.pop('target'),
            lambda c: c['target'].update(repository_id=True),
            lambda c: c['target'].update(repository_id=MAX_REVISION + 1),
            lambda c: c['target'].update(repository_id=0),
            lambda c: c['target'].update(name='example/alpha'),
            lambda c: c['expected'].update(admission_revision=True),
            lambda c: c['expected'].update(source_checks=[{}]),
            lambda c: c['expected'].update(assignment={}),
            lambda c: c['expected'].update(runtime_key='\ud800'),
            lambda c: c['expected'].update(runtime_key='x' * 1025),
            lambda c: c.update(effect_key='invented'),
            lambda c: c['parameters'].update(mode='arbitrary'),
            lambda c: c['parameters'].update(human_approved=True),
        ]
        for change in mutations:
            with self.subTest(change=mutations.index(change)):
                command, before = self.command(), self.payload()
                change(command)
                with self.assertRaises(InvalidAdmissionCommand) as error:
                    self.run_command(command)
                self.assertEqual(str(error.exception), 'invalid_command')
                self.assertEqual(self.payload(), before)
        self.assertEqual(self.github.calls, [])

    def test_valid_unsupported_admission_and_missing_preconditions(self):
        command = self.command('stopped')
        self.assert_rejected_without_write(command, 'unsupported_operation')
        command = self.command()
        command['target'] = {'kind': 'host'}
        self.assert_rejected_without_write(command, 'unsupported_operation')
        for field in ('runtime_key', 'admission_revision'):
            command = self.command()
            command['expected'][field] = None
            self.assert_rejected_without_write(command, 'precondition_required')
        self.assertEqual(self.github.calls, [])

    def test_well_formed_unsupported_version_and_action_keep_identity(self):
        commands = [self.command(), self.command()]
        commands[0]['command_schema'] = 2
        commands[1].update(action='workflow_step', target={'repository_id': 101, 'issue_number': 4},
                           parameters={'operation': 'continue', 'private': 'SYNTHETIC_PRIVATE_CANARY'})
        for command in commands:
            result = self.assert_rejected_without_write(command, 'unsupported_operation')
            self.assertEqual(result['request']['request_id'], REQUEST)
            self.assertEqual(result['request']['action'], command['action'])
            self.assertEqual(result['request']['target'], command['target'])
            self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', json.dumps(result))
        self.assertEqual(self.github.calls, [])

    def test_unsupported_reply_has_current_validated_surface_binding(self):
        commands = [self.command(), self.command(), self.command(), self.command('stopped')]
        commands[0]['command_schema'] = 2
        commands[1].update(action='workflow_step', target={'repository_id': 101, 'issue_number': 4})
        commands[2]['target'] = {'kind': 'host'}
        for surface, epoch in (('bridge', EPOCH), ('native', None)):
            self.context = AdmissionCallContext(surface, epoch, frozenset())
            for command in commands:
                with self.subTest(surface=surface, action=command['action'], target=command['target']):
                    command['binding_epoch'] = epoch
                    result = self.assert_rejected_without_write(command, 'unsupported_operation')
                    self.assertEqual(result['binding_epoch'], epoch)
                    self.assertEqual(result['runtime'], self.runtime)
        self.assertEqual(self.github.calls, [])

    def test_unsupported_reply_does_not_echo_unvalidated_binding(self):
        command = self.command('stopped')
        current = '33333333-3333-4333-8333-333333333333'
        self.context = AdmissionCallContext('bridge', current, frozenset({101}))
        result = self.assert_rejected_without_write(command, 'stale_binding')
        self.assertEqual(result['binding_epoch'], current)
        self.context = None
        result = self.assert_rejected_without_write(command, 'authority_unavailable')
        self.assertIsNone(result['binding_epoch'])
        self.context = AdmissionCallContext('bridge', EPOCH, frozenset({101}))
        with patch('hydra_sdlc.control_commands.load_host_config', side_effect=OSError()):
            result = self.assert_rejected_without_write(command, 'host_config_unavailable')
        self.assertEqual(result['binding_epoch'], EPOCH)
        self.assertEqual(self.github.calls, [])

    def test_native_scope_is_explicit_and_null_is_not_bridge_bypass(self):
        self.context = AdmissionCallContext('native', None, frozenset({101}))
        command = self.command()
        command['binding_epoch'] = None
        result = self.run_command(command)
        self.assertEqual(result['request']['outcome'], 'applied')
        self.assertIsNone(result['binding_epoch'])
        command = self.command('running')
        command['binding_epoch'] = None
        self.assertEqual(self.run_command(command)['request']['outcome'], 'applied')
        self.assert_rejected_without_write(self.command(), 'stale_binding')
        for context in (AdmissionCallContext('native', EPOCH, frozenset({101})),
                        AdmissionCallContext('bridge', None, frozenset({101})),
                        AdmissionCallContext('future', None, frozenset({101}))):
            self.context = context
            self.assert_rejected_without_write(command, 'authority_unavailable')

    def test_context_binding_scope_and_forged_context_are_rejected(self):
        for context, reason in (
                (AdmissionCallContext('bridge', '33333333-3333-4333-8333-333333333333', frozenset({101})), 'stale_binding'),
                (AdmissionCallContext('bridge', EPOCH, frozenset({202})), 'authority_denied'),
                ({'binding_epoch': EPOCH, 'repository_ids': [101]}, 'authority_unavailable'),
                (AdmissionCallContext('bridge', EPOCH, frozenset({True})), 'authority_unavailable')):
            self.context = context
            self.assert_rejected_without_write(self.command(), reason)
        self.context = AdmissionCallContext('bridge', EPOCH, frozenset({101}))
        command = self.command()
        command['binding_epoch'] = None
        self.assert_rejected_without_write(command, 'stale_binding')
        self.assertEqual(self.github.calls, [])

    def test_runtime_unknown_or_each_identity_change_is_not_refreshed(self):
        for key in ('version', 'code_digest', 'config_digest', 'control_binding_digest'):
            for value in (None, 'different'):
                with self.subTest(key=key, value=value):
                    altered = {**self.runtime, key: value}
                    with patch('hydra_sdlc.control_commands.capture_runtime_identity', return_value=altered):
                        self.assert_rejected_without_write(self.command())
        with patch('hydra_sdlc.control_commands.capture_runtime_identity', return_value={
                **self.runtime, 'identity_reason': 'runtime_source_unavailable'}):
            self.assert_rejected_without_write(self.command(), 'runtime_unavailable')

    def test_current_numeric_identity_required(self):
        for row in ({'id': True, 'full_name': 'example/alpha'},
                    {'id': 101, 'full_name': 'different/alpha'},
                    {'id': 101}, RuntimeError('SYNTHETIC_PRIVATE_CANARY')):
            self.github.rows['example/alpha'] = row
            before = self.payload()
            result = self.run_command(self.command())
            self.assertEqual(result['request']['outcome'], 'unknown')
            self.assertIsNone(result['request']['receipt'])
            self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', json.dumps(result))
            self.assertEqual(self.payload(), before)
        self.github.rows['example/alpha'] = {'id': 303, 'full_name': 'example/alpha'}
        self.assert_rejected_without_write(self.command(), 'target_unregistered')

    def test_unrelated_lookup_failure_does_not_hide_exact_target(self):
        self.github.rows['example/alpha'] = RuntimeError('unavailable')
        result = self.run_command(self.command(repository_id=202))
        self.assertEqual(result['request']['outcome'], 'applied')
        self.assertEqual(self.control.snapshot()['projects'], {'example/beta': 'paused'})

    def test_lookup_does_not_hold_lock_and_rechecks_context_config(self):
        def changed_context():
            # Independent file description: a nested guard on the same Python
            # owner would not prove that remote lookup is outside the lock.
            with self.control.control_lock_path.open('rb') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.context = AdmissionCallContext('bridge', EPOCH, frozenset({202}))
        self.github.during_read = changed_context
        self.assert_rejected_without_write(self.command(), 'authority_denied')
        self.context = AdmissionCallContext('bridge', EPOCH, frozenset({101, 202}))
        self.github.during_read = lambda: self.config_path.write_text(
            self.config_text.replace('host_alias="fixture"', 'host_alias="changed"'))
        self.assert_rejected_without_write(self.command(), 'stale_runtime')

    def test_lookup_binding_change_and_request_mutation_are_not_adopted(self):
        self.github.during_read = lambda: setattr(self, 'context', AdmissionCallContext(
            'bridge', '33333333-3333-4333-8333-333333333333', frozenset({101})))
        self.assert_rejected_without_write(self.command(), 'stale_binding')
        self.context = AdmissionCallContext('bridge', EPOCH, frozenset({101, 202}))
        command = self.command()
        self.github.during_read = lambda: command['target'].update(repository_id=202)
        result = self.run_command(command)
        self.assertEqual(result['request']['target']['repository_id'], 101)
        self.assertEqual(self.control.snapshot()['projects'], {'example/alpha': 'paused'})

    def test_duplicate_request_does_not_apply_again_or_reconstruct_receipt(self):
        command = self.command()
        self.assertEqual(self.run_command(command)['request']['outcome'], 'applied')
        self.assert_rejected_without_write(command, 'stale_revision')
        self.assertEqual(self.control.snapshot()['revision'], 2)

    def test_current_noop_stronger_stop_stale_and_host_limits(self):
        self.control.set_mode('pause', 'example/alpha')
        before = self.payload()
        result = self.run_command(self.command())
        self.assertEqual(result['request']['reason'], 'already_satisfied')
        self.assertEqual(self.payload(), before)
        self.control.set_mode('stop', 'example/alpha')
        before = self.payload()
        result = self.run_command(self.command())
        self.assertEqual(result['request']['reason'], 'stronger_mode_retained')
        self.assertEqual(self.payload(), before)
        old = self.command()
        self.control.set_mode('pause', 'example/beta')
        self.assert_rejected_without_write(old, 'stale_revision')
        self.control.set_mode('stop')
        self.assert_rejected_without_write(self.command('running'), 'host_stopped')

    def test_success_receipt_keeps_r_plus_one_after_another_writer(self):
        original = OperatingControl.set_mode_if_current_observed
        def followed_by_other_writer(control, *args, **kwargs):
            result = original(control, *args, **kwargs)
            control.set_mode('stop', 'example/alpha')
            return result
        with patch.object(OperatingControl, 'set_mode_if_current_observed', followed_by_other_writer):
            result = self.run_command(self.command())
        self.assertEqual(self.control.snapshot()['revision'], 3)
        observation = result['observations'][0]
        self.assertEqual(observation['value']['revision'], 2)
        self.assertEqual(observation['value']['project_overrides']['example/alpha'], 'paused')
        self.assertEqual(result['request']['receipt']['readback']['revision']['value'], '2')

    def test_real_post_replace_uncertainty_is_not_receipt_or_retry(self):
        original, calls = os.fsync, []
        def fail_parent(fd):
            calls.append(fd)
            if len(calls) == 2:
                raise OSError(errno.EIO, 'SYNTHETIC_PRIVATE_CANARY')
            return original(fd)
        with patch('hydra_sdlc.operations.os.fsync', side_effect=fail_parent):
            result = self.run_command(self.command())
        self.assertEqual(result['request']['outcome'], 'unknown')
        self.assertIsNone(result['request']['receipt'])
        self.assertEqual(result['request']['effect_refs'], [])
        self.assertEqual(result['request']['required_next'], 'reconcile')
        self.assertEqual(result['observations'][0]['key'], f'command:{REQUEST}:admission-current')
        self.assertEqual(self.control.snapshot()['revision'], 2)
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', json.dumps(result))

    def test_uncertain_recovery_read_and_close_failure_preserve_unknown(self):
        fsync, read, close = os.fsync, os.read, os.close
        snapshot, check_lock = OperatingControl.snapshot_observed, OperatingControl._check_lock
        state = {'fsync': 0, 'recovery': False, 'reads': 0, 'closes': 0, 'lock': None}

        def fail_parent(fd):
            state['fsync'] += 1
            if state['fsync'] == 2:
                raise OSError(errno.EIO, 'injected post-replace failure')
            return fsync(fd)

        def recover(control, *args, **kwargs):
            state['recovery'] = True
            try:
                return snapshot(control, *args, **kwargs)
            finally:
                state['recovery'] = False

        def remember_lock(control, held):
            result = check_lock(control, held)
            if state['recovery']:
                state['lock'] = held.lock
            return result

        def fail_read(fd, length):
            if state['recovery']:
                state['reads'] += 1
                raise OSError(errno.EIO, 'private recovery read canary')
            return read(fd, length)

        def fail_close(fd):
            close(fd)
            if state['recovery'] and fd == state['lock'] and state['reads']:
                state['closes'] += 1
                raise OSError(errno.EIO, 'private recovery close canary')

        command = self.command()
        with patch('hydra_sdlc.operations.os.fsync', side_effect=fail_parent), \
                patch('hydra_sdlc.operations.os.read', side_effect=fail_read), \
                patch('hydra_sdlc.operations.os.close', side_effect=fail_close), \
                patch.object(OperatingControl, '_check_lock', remember_lock), \
                patch.object(OperatingControl, 'snapshot_observed', autospec=True, side_effect=recover) as recovery:
            result = self.run_command(command)
        self.assertEqual(recovery.call_count, 1)
        self.assertEqual((state['reads'], state['closes']), (1, 1))
        self.assertEqual(result['request']['outcome'], 'unknown')
        self.assertEqual(result['request']['reason'], 'operation_state_unknown')
        self.assertIsNone(result['request']['receipt'])
        self.assertEqual(result['request']['effect_refs'], [])
        self.assertEqual(result['observations'], [])
        self.assertNotIn('canary', json.dumps(result))
        self.assertEqual(self.control.snapshot()['revision'], 2)
        self.assertEqual(self.control.snapshot()['projects']['example/alpha'], 'paused')

    def test_busy_and_pre_replace_failures_have_no_receipt(self):
        for reason, outcome in (('operation_state_busy', 'waiting'),
                                ('operation_state_unsafe', 'rejected')):
            before = self.payload()
            with patch.object(OperatingControl, 'set_mode_if_current_observed', side_effect=OperationDenied(reason)):
                result = self.run_command(self.command())
            self.assertEqual(result['request']['outcome'], outcome)
            self.assertIsNone(result['request']['receipt'])
            self.assertEqual(result['observations'], [])
            self.assertEqual(self.payload(), before)

    def test_sync_command_returns_busy_before_shared_holder_releases(self):
        command, before = self.command(), self.payload()
        with self.control.control_lock_path.open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_SH)
            with self.command_process(command) as child:
                result = self.process_reply(child)
                self.assertEqual(result['request']['outcome'], 'waiting')
                self.assertEqual(result['request']['reason'], 'operation_state_busy')
                self.assertIsNone(result['request']['receipt'])
                self.assertEqual(result['request']['effect_refs'], [])
                self.assertEqual(result['observations'], [])
                self.assertEqual(self.payload(), before)
                self.assertEqual(self.control.snapshot()['revision'], 1)
        # A completed child cannot queue a delayed mutation when the lock opens.
        self.assertEqual(self.payload(), before)
        self.assertEqual(self.control.snapshot()['revision'], 1)
        self.context = AdmissionCallContext('bridge', EPOCH, frozenset({202}))
        self.assert_rejected_without_write(self.command(), 'authority_denied')
        self.context = AdmissionCallContext('bridge', EPOCH, frozenset({101, 202}))
        changed_config_request = self.command()
        self.config_path.write_text(self.config_text.replace('host_alias="fixture"', 'host_alias="changed"'))
        self.assert_rejected_without_write(changed_config_request, 'stale_runtime')

    def test_uncertain_recovery_returns_unknown_before_exclusive_holder_releases(self):
        with self.command_process(self.command(), uncertain=True) as child:
            self.assertEqual(self.process_line(child), 'recovery')
            with self.control.control_lock_path.open('rb') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                try:
                    child.stdin.write('\n')
                    child.stdin.flush()
                    result = self.process_reply(child)
                    self.assertEqual(result['request']['outcome'], 'unknown')
                    self.assertEqual(result['request']['reason'], 'operation_state_unknown')
                    self.assertIsNone(result['request']['receipt'])
                    self.assertEqual(result['request']['effect_refs'], [])
                    self.assertEqual(result['request']['observed_refs'], [])
                    self.assertEqual(result['observations'], [])
                    before_unlock = self.payload()
                    self.assertEqual(json.loads(before_unlock)['revision'], 2)
                finally:
                    if child.poll() is None:
                        child.kill()
                    child.communicate(timeout=5)
        self.assertEqual(self.payload(), before_unlock)
        self.assertEqual(self.control.snapshot()['revision'], 2)

    def test_nonboolean_lock_policy_is_rejected_before_creating_store(self):
        control = OperatingControl(self.root / 'uncreated' / 'host.lock', ('example/alpha',))
        for value in (None, 0, 1, 'false'):
            with self.subTest(value=value):
                with self.assertRaises(OperationDenied) as error:
                    control.set_mode_if_current('pause', 'example/alpha', expected_revision=0, blocking=value)
                self.assertEqual(error.exception.reason, 'invalid_command')
                with self.assertRaises(OperationDenied) as error:
                    control.snapshot(blocking=value)
                self.assertEqual(error.exception.reason, 'invalid_command')
                self.assertFalse(control.settings_path.parent.exists())

    def test_unknown_without_observation_does_not_probe_or_create_receipt(self):
        command = self.command()
        with patch.object(OperatingControl, 'set_mode_if_current_observed', side_effect=OperationUncertain()), \
                patch.object(OperatingControl, 'snapshot_observed', side_effect=AssertionError('extra snapshot')):
            result = self.run_command(command)
        self.assertEqual(result['request']['outcome'], 'unknown')
        self.assertIsNone(result['request']['receipt'])
        self.assertEqual(result['observations'], [])
        self.assertEqual(result['request']['observed_refs'], [])

    def test_context_error_does_not_leak_or_query_sources(self):
        before = self.payload()
        def unavailable():
            raise RuntimeError('SYNTHETIC_PRIVATE_CANARY')
        result = execute_admission_command(self.config_path, self.command(),
            context_provider=unavailable, github=self.github)
        self.assertEqual(result['request']['reason'], 'authority_unavailable')
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', json.dumps(result))
        self.assertEqual(self.payload(), before)
        self.assertEqual(self.github.calls, [])

    def test_first_and_second_config_close_error_is_bounded(self):
        original = load_host_config
        for position in (1, 2):
            count = []
            def fail_close(path):
                count.append(1)
                cfg = original(path)
                if len(count) == position:
                    raise OSError(errno.EIO, 'SYNTHETIC_PRIVATE_CANARY')
                return cfg
            with patch('hydra_sdlc.control_commands.load_host_config', side_effect=fail_close):
                result = self.assert_rejected_without_write(self.command(), 'host_config_unavailable')
            self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', json.dumps(result))

    def test_cancellation_propagates_without_store_change(self):
        before = self.payload()
        with self.assertRaises(asyncio.CancelledError):
            execute_admission_command(self.config_path, self.command(),
                context_provider=lambda: (_ for _ in ()).throw(asyncio.CancelledError()), github=self.github)
        self.assertEqual(self.payload(), before)

    def test_reply_has_no_paths_context_or_unrelated_source_fields(self):
        self.github.rows['example/alpha']['private'] = 'SYNTHETIC_PRIVATE_CANARY'
        result = self.run_command(self.command())
        payload = json.dumps(result)
        self.assertNotIn(str(self.root), payload)
        self.assertNotIn('SYNTHETIC_PRIVATE_CANARY', payload)
        self.assertNotIn('repository_ids', payload)
        self.assertEqual(set(result['observations'][0]['value']),
                         {'revision', 'global_mode', 'project_overrides', 'gate_reason'})

    def test_future_expected_object_is_opaque_for_unsupported_identity(self):
        for action, schema in (('admission_set', 2), ('workflow_step', 1)):
            command = self.command()
            command.update(action=action, command_schema=schema,
                           expected={'future': 'SYNTHETIC_PRIVATE_FUTURE_CANARY'},
                           parameters={'future_operation': {'private': 'SYNTHETIC_PRIVATE_FUTURE_CANARY'}})
            result = self.assert_rejected_without_write(command, 'unsupported_operation')
            self.assertEqual(result['request']['request_id'], command['request_id'])
            self.assertEqual(result['request']['target'], command['target'])
            self.assertEqual(result['binding_epoch'], EPOCH)
            self.assertNotIn('SYNTHETIC_PRIVATE_FUTURE_CANARY', json.dumps(result))
        self.assertEqual(self.github.calls, [])
        command = self.command(); command['expected'] = {'future': 'private'}
        with self.assertRaises(InvalidAdmissionCommand):
            self.run_command(command)

    def test_permission_denied_at_replace_is_definite_without_retry(self):
        before = self.payload()
        for code in (errno.EACCES, errno.EPERM, errno.EROFS):
            with self.subTest(code=code), patch('hydra_sdlc.operations.os.replace',
                    side_effect=OSError(code, 'SYNTHETIC_PRIVATE_REPLACE_CANARY')) as replace:
                result = self.assert_rejected_without_write(self.command(), 'operation_state_unavailable')
            replace.assert_called_once()
            self.assertEqual(result['observations'], [])
            self.assertEqual(self.payload(), before)
            self.assertNotIn('SYNTHETIC_PRIVATE_REPLACE_CANARY', json.dumps(result))

    def test_ambiguous_replace_error_preserves_unknown_even_after_real_effect(self):
        replace = os.replace
        def uncertain(*args, **kwargs):
            replace(*args, **kwargs)
            raise OSError(errno.EIO, 'SYNTHETIC_PRIVATE_REPLACE_CANARY')
        with patch('hydra_sdlc.operations.os.replace', side_effect=uncertain) as called:
            result = self.run_command(self.command())
        called.assert_called_once()
        self.assertEqual(result['request']['outcome'], 'unknown')
        self.assertIsNone(result['request']['receipt'])
        self.assertEqual(result['request']['effect_refs'], [])
        self.assertEqual(self.control.snapshot()['revision'], 2)
        self.assertNotIn('SYNTHETIC_PRIVATE_REPLACE_CANARY', json.dumps(result))

    def test_ambiguous_replace_failure_without_readback_stays_unknown(self):
        before = self.payload()
        for code in (errno.EIO, errno.EINTR, errno.ENOENT):
            command = self.command()
            with self.subTest(code=code), \
                    patch('hydra_sdlc.operations.os.replace', side_effect=OSError(code, 'ambiguous failure')) as replace, \
                    patch.object(OperatingControl, 'snapshot_observed',
                                 side_effect=OperationDenied('operation_state_unavailable')) as read:
                result = self.run_command(command)
            replace.assert_called_once()
            read.assert_called_once_with(blocking=False)
            self.assertEqual(result['request']['outcome'], 'unknown')
            self.assertIsNone(result['request']['receipt'])
            self.assertEqual(result['observations'], [])
            self.assertEqual(self.payload(), before)

    def test_permission_error_after_real_replace_keeps_uncertainty(self):
        replace = os.replace
        def failed_ack(*args, **kwargs):
            replace(*args, **kwargs)
            raise PermissionError(errno.EACCES, 'post-effect failure')
        with patch('hydra_sdlc.operations.os.replace', side_effect=failed_ack) as called:
            result = self.run_command(self.command())
        called.assert_called_once()
        self.assertEqual(result['request']['outcome'], 'unknown')
        self.assertIsNone(result['request']['receipt'])
        self.assertEqual(result['observations'][0]['value']['revision'], 2)
        self.assertEqual(self.control.snapshot()['revision'], 2)

    def assert_locked_observation_time(self, *, noop=False, uncertain=False):
        first = datetime(2030, 1, 1, tzinfo=timezone.utc)
        clock, depth, events, drift = [first], [0], [], []
        command = self.command('running' if noop else 'paused')
        original_lock = OperatingControl._locked
        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                events.append(('clock', depth[0], clock[0]))
                return clock[0]
        @contextmanager
        def after_read(control, *args, **kwargs):
            with original_lock(control, *args, **kwargs) as held:
                depth[0] += 1
                try:
                    yield held
                finally:
                    depth[0] -= 1
            events.append(('unlock', kwargs.get('exclusive'), clock[0]))
            if not drift and kwargs.get('exclusive') == (not uncertain):
                drift.append(True)
                clock[0] = first + timedelta(seconds=1)
                control.set_mode('stop', 'example/beta')
                clock[0] = first + timedelta(seconds=2)
        fsync, fsync_calls = os.fsync, []
        def fail_parent(fd):
            fsync_calls.append(fd)
            if uncertain and len(fsync_calls) == 2:
                raise OSError(errno.EIO, 'post-replace fixture fault')
            return fsync(fd)
        with patch.object(OperatingControl, '_locked', after_read), \
                patch('hydra_sdlc.operations.datetime', Clock), \
                patch('hydra_sdlc.control_commands.datetime', Clock, create=True), \
                patch('hydra_sdlc.operations.os.fsync', side_effect=fail_parent):
            result = self.run_command(command)
        self.assertEqual(drift, [True], 'A real writer must run after the locked observation')
        observation = result['observations'][0]
        self.assertEqual(observation['observed_at'], first.strftime('%Y-%m-%dT%H:%M:%S.%fZ'))
        self.assertEqual(observation['last_attempt_at'], observation['observed_at'])
        self.assertEqual(observation['value']['revision'], 1 if noop else 2)
        self.assertEqual(self.control.snapshot()['revision'], 2 if noop else 3)
        self.assertTrue(all(row[1] > 0 for row in events if row[0] == 'clock'),
                        'Evidence time must be captured inside the observation lock')
        self.assertEqual(result['request']['outcome'], 'unknown' if uncertain else 'applied')
        if uncertain:
            self.assertIsNone(result['request']['receipt'])

    def test_cas_observation_time_precedes_intervening_writer(self):
        self.assert_locked_observation_time()

    def test_noop_observation_time_is_locked_read_not_old_update_time(self):
        self.assert_locked_observation_time(noop=True)

    def test_unknown_current_observation_time_is_paired_with_recovery_read(self):
        self.assert_locked_observation_time(uncertain=True)

    def test_config_failure_during_lookup_precedes_each_authority_error(self):
        contexts = (None, AdmissionCallContext('bridge', '33333333-3333-4333-8333-333333333333', frozenset({101})),
                    AdmissionCallContext('bridge', EPOCH, frozenset()))
        for context in contexts:
            self.config_path.write_text(self.config_text)
            self.context = AdmissionCallContext('bridge', EPOCH, frozenset({101, 202}))
            command = self.command()
            def change():
                self.config_path.write_text('invalid = [')
                self.context = context
            self.github.during_read = change
            result = self.assert_rejected_without_write(command, 'host_config_unavailable')
            self.assertIsNone(result['runtime']['config_digest'])
            self.assertIsNone(result['runtime']['control_binding_digest'])
            self.assertEqual(result['binding_epoch'], context.binding_epoch if context else None)

    def test_authority_revoked_during_current_config_read_cannot_reach_cas(self):
        load, calls = load_host_config, []
        def revoke(path):
            cfg = load(path); calls.append(True)
            if len(calls) == 2:
                self.context = None
            return cfg
        with patch('hydra_sdlc.control_commands.load_host_config', side_effect=revoke):
            self.assert_rejected_without_write(self.command(), 'authority_unavailable')

    def test_changed_authority_reply_uses_current_config_identity(self):
        command = self.command()
        def change():
            self.config_path.write_text(self.config_text.replace('host_alias="fixture"', 'host_alias="changed"'))
            self.context = None
        self.github.during_read = change
        result = self.assert_rejected_without_write(command, 'authority_unavailable')
        current_cfg = load_host_config(self.config_path)
        current = capture_runtime_identity(current_cfg, control_from_config(current_cfg))
        self.assertEqual(result['runtime'], current)
        self.assertNotEqual(result['runtime']['config_digest'], self.runtime['config_digest'])


if __name__ == '__main__':
    unittest.main()
