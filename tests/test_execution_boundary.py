import asyncio
import errno
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from hydra_sdlc import coordinator, execution_boundary as boundary


WORKER = r'''
import asyncio, importlib.util, json, os, signal, subprocess, sys, threading, time
from pathlib import Path
spec = importlib.util.spec_from_file_location('boundary', sys.argv[1])
b = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b)
mode, marker = sys.argv[2], Path(sys.argv[3])
def mark(name, **values):
    with marker.open('a') as output:
        output.write(json.dumps({'name': name, **values}) + '\n')
async def execute(assignment, identity, event, stopped, resume_thread_id=None, on_dispatch=None):
    mark('started', pid=os.getpid(), argv=sys.argv)
    if mode == 'environment':
        mark('environment', token_names=[key for key in b.PUBLISHING_TOKEN_VARIABLES if key in os.environ],
             harmless=os.environ.get('HYDRA_TEST_HARMLESS'))
    if mode in ('startup_hang', 'resistant', 'eof'):
        if mode in ('resistant', 'eof'):
            child = subprocess.Popen([sys.executable, '-I', '-c',
                'import signal,time; signal.signal(signal.SIGTERM, signal.SIG_IGN); print("ready",flush=True); time.sleep(60)'],
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
            child.stdout.readline()
            mark('descendant', pid=child.pid)
        await asyncio.to_thread(threading.Event().wait)
    if mode == 'late_start':
        def delayed():
            time.sleep(1)
            mark('late_runtime')
            threading.Event().wait()
        await asyncio.to_thread(delayed)
    if mode == 'oversized':
        sys.stdout.buffer.write(b'x' * (b.MAX_FRAME_BYTES + 1) + b'\n')
        sys.stdout.buffer.flush()
        await asyncio.Event().wait()
    if mode == 'wrong_seq':
        sys.stdout.buffer.write(b._encode(b._frame('poll', 0, {})))
        sys.stdout.buffer.flush()
        await asyncio.Event().wait()
    if mode == 'false_completed':
        return {'status': 'completed', 'thread_id': None, 'turn_id': None, 'detail': {}}
    if not on_dispatch('thread/resume' if resume_thread_id else 'thread/start'):
        return {'status': 'interrupted', 'thread_id': None, 'turn_id': None,
                'detail': {'reason': 'stopped_before_dispatch'}}
    mark('thread_dispatch')
    if mode == 'grant_loss':
        os._exit(7)
    identity(thread_id='thread-1')
    mark('identity_acked')
    if not on_dispatch('turn/start'):
        return {'status': 'interrupted', 'thread_id': 'thread-1', 'turn_id': None,
                'detail': {'reason': 'stopped_before_turn'}}
    identity(turn_id='turn-1')
    if mode == 'result_loss':
        os._exit(8)
    items = {}
    if mode == 'accumulated_items':
        for index in range(3):
            item = {'id': 'item-' + str(index), 'type': 'commandExecution',
                    'aggregatedOutput': 'x' * (b.MAX_FRAME_BYTES // 2)}
            event(item['id'], {'method': 'item/completed', 'params': {
                'threadId': 'thread-1', 'turnId': 'turn-1', 'item': item}})
            items[item['id']] = item
    status = 'completed'
    if mode in ('silent', 'slow_silent'):
        while not stopped():
            await asyncio.sleep(.005)
        status = 'interrupted'
    terminal = {'id': 'turn-1', 'status': status}
    event('terminal-event', {'method': 'turn/completed', 'params': {'threadId': 'thread-1', 'turn': terminal}})
    mark('event_acked')
    if mode == 'shutdown_hang':
        asyncio.create_task(asyncio.to_thread(threading.Event().wait))
        await asyncio.sleep(.01)
    return {'status': status, 'thread_id': 'thread-1', 'turn_id': 'turn-1',
            'detail': {'reason': 'provider_terminal', 'terminal': terminal,
                       'items': items,
                       'result': {'outcome': 'candidate_ready', 'summary': 'Candidate checked',
                                  'next_action': 'review', 'evidence': ['local check']}}}
if mode == 'slow_silent':
    time.sleep(.25)
b.worker_main(execute)
'''


class BoundaryTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.worker = self.root / 'worker.py'
        self.worker.write_text(WORKER)
        self.marker = self.root / 'observed.jsonl'
        self.module = str(Path(boundary.__file__).resolve())
        self.mode = 'normal'
        self.identities = []
        self.events = []
        self.stop = False
        self.command_patch = patch.object(boundary, '_worker_command', side_effect=lambda _: self.command())
        self.command_patch.start()
        self.addCleanup(self.command_patch.stop)

    def command(self):
        return [sys.executable, '-I', str(self.worker), self.module, self.mode, str(self.marker)]

    def observations(self):
        return [json.loads(line) for line in self.marker.read_text().splitlines()] if self.marker.exists() else []

    def identity(self, **values):
        self.identities.append(values)

    def event(self, event_id, payload):
        self.events.append((event_id, payload))

    async def run_worker(self, **kwargs):
        return await boundary.execute_worker(
            {'cwd': str(self.root), 'task': 'private-assignment-marker'},
            kwargs.pop('identity', self.identity), kwargs.pop('event', self.event),
            lambda: self.stop, kwargs.pop('resume', None), worker_source=self.module,
            timeout=kwargs.pop('timeout', 2), grace=.08, poll=.005, **kwargs,
        )

    def assert_pids_gone(self):
        for observation in self.observations():
            if 'pid' in observation:
                with self.assertRaises(ProcessLookupError):
                    os.kill(observation['pid'], 0)

    async def test_normal_outcome_preserves_callbacks_and_private_input(self):
        result = await self.run_worker()
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(self.identities, [{'thread_id': 'thread-1'}, {'turn_id': 'turn-1'}])
        self.assertEqual(self.events[0][1]['method'], 'hydra/workerStarted')
        self.assertNotIn('private-assignment-marker', json.dumps(self.observations()[0]['argv']))
        self.assert_pids_gone()

    async def test_worker_does_not_inherit_publishing_tokens(self):
        self.mode = 'environment'
        environment = {name: 'synthetic-token' for name in boundary.PUBLISHING_TOKEN_VARIABLES}
        environment['HYDRA_TEST_HARMLESS'] = 'retained'
        with patch.dict(os.environ, environment):
            result = await self.run_worker()
            self.assertTrue(all(os.environ[name] == 'synthetic-token' for name in boundary.PUBLISHING_TOKEN_VARIABLES))
        self.assertEqual(result['status'], 'completed')
        observed = next(item for item in self.observations() if item['name'] == 'environment')
        self.assertEqual(observed['token_names'], [])
        self.assertEqual(observed['harmless'], 'retained')
        self.assert_pids_gone()

    async def test_legal_events_over_final_frame_limit_preserve_completed_outcome(self):
        self.mode = 'accumulated_items'
        result = await self.run_worker()
        items = [(event_id, payload) for event_id, payload in self.events if payload['method'] == 'item/completed']
        self.assertEqual(len(items), 3)
        self.assertTrue(all(payload['params']['item']['aggregatedOutput'] == 'x' * (boundary.MAX_FRAME_BYTES // 2)
                            for _, payload in items))
        sizes = [len(boundary._encode(boundary._frame('event', index, {
            'event_id': event_id, 'payload': payload,
        }))) for index, (event_id, payload) in enumerate(items, 1)]
        self.assertGreater(sum(sizes), boundary.MAX_FRAME_BYTES)
        self.assertEqual(result['status'], 'completed')
        self.assertEqual((result['thread_id'], result['turn_id']), ('thread-1', 'turn-1'))
        self.assertEqual(result['detail']['terminal'], {'id': 'turn-1', 'status': 'completed'})
        self.assertEqual(result['detail']['result'], {
            'outcome': 'candidate_ready', 'summary': 'Candidate checked',
            'next_action': 'review', 'evidence': ['local check'],
        })
        self.assertEqual(result['detail']['items'], {})
        self.assertEqual(result['detail']['items_omitted'], 3)
        self.assertNotIn('cleanup', result['detail'])
        self.assert_pids_gone()

    def test_result_compaction_preserves_cleanup_receipt_and_original_data(self):
        detail = {'items': {'large': {'text': 'x' * boundary.MAX_FRAME_BYTES}},
                  'result': {'outcome': 'needs_decision'}, 'cleanup': 'unknown',
                  'terminal': {'id': 'turn-1', 'status': 'completed'}, 'usage': {'totalTokens': 12}}
        result = {'status': 'completed', 'thread_id': 'thread-1', 'turn_id': 'turn-1', 'detail': detail}
        frame = boundary._decode(boundary._encode_result(7, result))
        self.assertEqual(frame['seq'], 7)
        self.assertEqual(frame['data'], {**result, 'detail': {**detail, 'items': {}, 'items_omitted': 1}})
        self.assertIn('large', detail['items'])
        self.assertNotIn('items_omitted', detail)

    def test_oversized_structured_result_still_fails_without_truncation(self):
        result = {'detail': {'items': {'item-1': {'text': 'duplicate'}},
                             'result': {'summary': 'x' * boundary.MAX_FRAME_BYTES}}}
        with self.assertRaises(boundary.ProtocolError):
            boundary._encode_result(1, result)

    async def test_identity_and_event_ack_follow_successful_callbacks(self):
        def identity(**values):
            if 'thread_id' in values:
                time.sleep(.03)
                self.assertNotIn('identity_acked', [x['name'] for x in self.observations()])
            self.identity(**values)
        def event(event_id, payload):
            if payload['method'] == 'turn/completed':
                time.sleep(.03)
                self.assertNotIn('event_acked', [x['name'] for x in self.observations()])
            self.event(event_id, payload)
        result = await self.run_worker(identity=identity, event=event)
        self.assertEqual(result['status'], 'completed')
        self.assertIn('event_acked', [x['name'] for x in self.observations()])

    async def test_failed_worker_audit_prevents_assignment_injection(self):
        def fail(*_):
            raise OSError('private storage error')
        result = await self.run_worker(event=fail)
        self.assertEqual(result['status'], 'failed')
        self.assertEqual(self.observations(), [])
        self.assertNotIn('private storage error', json.dumps(result))

    async def test_failed_identity_callback_never_acks_or_starts_turn(self):
        def fail(**_):
            raise OSError('storage failed')
        result = await self.run_worker(identity=fail)
        self.assertEqual(result['status'], 'transport_unknown')
        self.assertEqual(result['thread_id'], 'thread-1')
        self.assertNotIn('identity_acked', [x['name'] for x in self.observations()])
        self.assert_pids_gone()

    async def test_failed_terminal_callback_cannot_admit_result(self):
        def event(event_id, payload):
            if payload['method'] == 'turn/completed':
                raise OSError('storage failed')
            self.event(event_id, payload)
        result = await self.run_worker(event=event)
        self.assertEqual(result['status'], 'transport_unknown')
        self.assertIsNone(result['detail']['terminal'])
        self.assertNotIn('event_acked', [x['name'] for x in self.observations()])

    async def test_granted_request_response_loss_keeps_resume_id_and_unknown(self):
        self.mode = 'grant_loss'
        result = await self.run_worker(resume='requested-thread')
        self.assertEqual(result['status'], 'transport_unknown')
        self.assertEqual(result['detail']['requested_resume_thread_id'], 'requested-thread')
        self.assertEqual(len([x for x in self.observations() if x['name'] == 'thread_dispatch']), 1)

    async def test_result_loss_retains_observed_ids(self):
        self.mode = 'result_loss'
        result = await self.run_worker()
        self.assertEqual(result['status'], 'transport_unknown')
        self.assertEqual(result['thread_id'], 'thread-1')
        self.assertEqual(result['turn_id'], 'turn-1')

    async def test_stop_before_dispatch_creates_no_worker(self):
        self.stop = True
        result = await self.run_worker()
        self.assertEqual(result['status'], 'interrupted')
        self.assertEqual(result['detail']['reason'], 'stopped_before_dispatch')
        self.assertEqual(self.observations(), [])

    async def test_silent_turn_observes_parent_stop(self):
        def stop_after_turn_identity(**values):
            self.identity(**values)
            if 'turn_id' in values:
                self.stop = True

        for mode in ('silent', 'slow_silent'):
            with self.subTest(mode=mode):
                self.mode = mode
                self.stop = False
                self.identities.clear()
                self.marker.unlink(missing_ok=True)
                result = await self.run_worker(identity=stop_after_turn_identity)
                self.assertEqual(self.identities, [{'thread_id': 'thread-1'}, {'turn_id': 'turn-1'}])
                self.assertEqual(result['status'], 'interrupted')
                self.assertEqual(result['detail']['terminal']['status'], 'interrupted')
                self.assert_pids_gone()

    async def test_repeated_parent_cancellation_still_cleans_worker(self):
        self.mode = 'startup_hang'
        task = asyncio.create_task(self.run_worker())
        while not self.observations():
            await asyncio.sleep(.005)
        task.cancel()
        asyncio.get_running_loop().call_later(.01, task.cancel)
        result = await task
        self.assertEqual(result['status'], 'interrupted')
        self.assert_pids_gone()

    async def test_startup_deadline_is_bounded_even_before_helper_admission(self):
        for mode in ('startup_hang', 'late_start'):
            with self.subTest(mode=mode):
                self.mode = mode
                self.marker.unlink(missing_ok=True)
                result = await self.run_worker(timeout=.2)
                self.assertEqual(result['status'], 'failed')
                self.assertNotIn('cleanup', result['detail'])
                self.assertNotIn('late_runtime', [x['name'] for x in self.observations()])
                self.assert_pids_gone()

    async def test_observed_blocked_sdk_startup_is_cancelled_and_collected(self):
        for mode in ('startup_hang', 'late_start'):
            with self.subTest(mode=mode):
                self.mode = mode
                self.marker.unlink(missing_ok=True)
                task = asyncio.create_task(self.run_worker())
                async def wait_started():
                    while not any(row['name'] == 'started' for row in self.observations()):
                        if task.done():
                            self.fail('Worker ended before observed SDK startup')
                        await asyncio.sleep(.005)
                await asyncio.wait_for(wait_started(), 2)
                task.cancel()
                result = await task
                self.assertEqual(result['status'], 'interrupted')
                self.assertNotIn('cleanup', result['detail'])
                self.assertNotIn('late_runtime', [x['name'] for x in self.observations()])
                self.assert_pids_gone()

    async def test_observed_sdk_shutdown_hang_preserves_completed_result(self):
        self.mode = 'shutdown_hang'
        result_received = asyncio.Event()
        original = boundary.OwnedProcess

        class ObservedProcess(original):
            async def wait(self):
                # execute_worker calls wait only after decoding the real result.
                result_received.set()
                return await super().wait()

        with patch.object(boundary, 'OwnedProcess', ObservedProcess):
            task = asyncio.create_task(self.run_worker())
            await asyncio.wait_for(result_received.wait(), 2)
            task.cancel()
            result = await task
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(result['detail']['terminal']['status'], 'completed')
        self.assertIn('event_acked', [x['name'] for x in self.observations()])
        self.assertNotIn('cleanup', result['detail'])
        self.assert_pids_gone()

    async def test_cleanup_uncertainty_overrides_completed_provider(self):
        with patch.object(boundary, '_cleanup', new=AsyncMock(return_value=False)):
            result = await self.run_worker()
        self.assertEqual(result['status'], 'transport_unknown')
        self.assertEqual(result['detail']['cleanup'], 'unknown')

    @unittest.skipUnless(sys.platform == 'darwin', 'native macOS direct collection')
    async def test_transient_group_probe_error_waits_for_actual_collection(self):
        self.mode = 'startup_hang'
        real_killpg = os.killpg
        injected, observed_absence = [], []

        def probe(pgid, sig):
            if sig == 0 and not injected:
                injected.append(pgid)
                raise PermissionError(errno.EPERM, 'transient fixture group probe')
            try:
                return real_killpg(pgid, sig)
            except ProcessLookupError:
                observed_absence.append(pgid)
                raise

        with patch.object(boundary.os, 'killpg', side_effect=probe):
            result = await self.run_worker(timeout=.2)
        self.assertEqual(result['status'], 'failed')
        self.assertTrue(injected)
        self.assertIn(injected[0], observed_absence)
        self.assertNotIn('cleanup', result['detail'])
        self.assert_pids_gone()

    @unittest.skipUnless(sys.platform == 'darwin', 'native macOS direct collection')
    async def test_persistent_group_probe_error_keeps_unknown_without_escalation(self):
        self.mode = 'startup_hang'
        real_killpg = os.killpg
        signals, probes = [], []

        def probe(pgid, sig):
            if sig == 0:
                probes.append(pgid)
                raise PermissionError(errno.EPERM, 'persistent fixture group probe')
            signals.append(sig)
            return real_killpg(pgid, sig)

        with patch.object(boundary.os, 'killpg', side_effect=probe):
            result = await self.run_worker(timeout=.2)
        self.assertEqual(result['status'], 'transport_unknown')
        self.assertEqual(result['detail']['cleanup'], 'unknown')
        self.assertGreater(len(probes), 1)
        self.assertEqual(signals, [boundary.signal.SIGTERM])
        self.assert_pids_gone()

    async def test_observed_group_absence_never_signals_again_after_collection_timeout(self):
        process = SimpleNamespace(pid=12345, communicate=AsyncMock(side_effect=TimeoutError))
        with patch.object(boundary.os, 'killpg', side_effect=[None, ProcessLookupError]) as signal_group:
            clean = await boundary._collect_direct(process, asyncio.get_running_loop().time() + 2)
        self.assertFalse(clean)
        self.assertEqual([call.args[1] for call in signal_group.call_args_list],
                         [boundary.signal.SIGTERM, 0])

    async def test_bad_frames_and_unbacked_completion_fail_closed(self):
        for mode in ('oversized', 'wrong_seq', 'false_completed'):
            with self.subTest(mode=mode):
                self.mode = mode
                self.marker.unlink(missing_ok=True)
                result = await self.run_worker()
                self.assertEqual(result['status'], 'failed')
                self.assertLess(len(json.dumps(result)), 1000)
                self.assert_pids_gone()

    async def test_group_cleanup_kills_resistant_descendant(self):
        self.mode = 'resistant'
        result = await self.run_worker(timeout=.2)
        self.assertEqual(result['status'], 'failed')
        self.assertNotIn('cleanup', result['detail'])
        self.assert_pids_gone()

    async def test_parent_pipe_eof_terminates_owned_group(self):
        self.mode = 'eof'
        process = boundary.OwnedProcess(self.command())
        try:
            await process.start(asyncio.get_running_loop().time() + 3)
            process.stdin.write(boundary._encode(boundary._frame('assignment', 0, {'assignment': {}})))
            await process.stdin.drain()
            until = time.monotonic() + 3
            while not any(x['name'] == 'descendant' for x in self.observations()):
                if time.monotonic() > until:
                    self.fail('worker did not start')
                await asyncio.sleep(.005)
            process.stdin.close()
            await asyncio.wait_for(process.wait(), 3)
            self.assertTrue(await process.cleanup())
            self.assert_pids_gone()
        finally:
            await process.cleanup()

    def test_outer_asyncio_run_exits_after_blocked_startup(self):
        script = '''
import asyncio, importlib.util, json, sys
spec=importlib.util.spec_from_file_location('boundary',sys.argv[1]); b=importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
b._worker_command=lambda _: [sys.executable,'-I',sys.argv[2],sys.argv[1],'startup_hang',sys.argv[3]]
print(json.dumps(asyncio.run(b.execute_worker({},lambda **x:None,lambda *x:None,lambda:False,None,
    worker_source=sys.argv[1],timeout=.15,grace=.05,poll=.005))))
'''
        result = subprocess.run([sys.executable, '-I', '-c', script, self.module, str(self.worker), str(self.marker)],
                                capture_output=True, text=True, timeout=5, check=True)
        self.assertEqual(json.loads(result.stdout)['status'], 'failed')
        self.assert_pids_gone()

    def test_standalone_sync_facade_needs_no_package_import(self):
        script = '''
import importlib.util, json, os, sys
spec=importlib.util.spec_from_file_location('boundary',sys.argv[1]); b=importlib.util.module_from_spec(spec); spec.loader.exec_module(b)
assert 'hydra_sdlc.coordinator' not in sys.modules
result=b.run_owned_sync([sys.executable,'-I','-c','print("standalone")'],cwd=sys.argv[2],env=os.environ.copy(),timeout=2,max_output_bytes=1024)
assert 'hydra_sdlc.coordinator' not in sys.modules
print(json.dumps({'returncode':result.returncode,'stdout':result.stdout.decode()}))
'''
        result = subprocess.run([sys.executable, '-I', '-c', script, self.module, str(self.root)],
                                capture_output=True, text=True, timeout=5, check=True)
        self.assertEqual(json.loads(result.stdout), {'returncode': 0, 'stdout': 'standalone\n'})

    def alias_boundary(self):
        spec = importlib.util.spec_from_file_location('boundary_alias', self.module)
        alias = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(alias)
        self.assertFalse(alias.__package__)
        self.assertIs(alias._ownership_coordinator(), coordinator)
        return alias

    async def test_standalone_alias_uses_active_cli_owner_for_both_facades(self):
        alias = self.alias_boundary()
        lock = self.root / 'host.lock'
        command = [sys.executable, '-I', '-c', 'pass']
        real_spawn, real_popen = asyncio.create_subprocess_exec, subprocess.Popen

        async def async_spawn(*args, **kwargs):
            self.assertTrue(lock.read_bytes(), 'active CLI marker missing before spawn')
            return await real_spawn(*args, **kwargs)

        def sync_spawn(*args, **kwargs):
            self.assertTrue(lock.read_bytes(), 'active CLI marker missing before spawn')
            return real_popen(*args, **kwargs)

        with coordinator.coordinator_lock(lock):
            process = alias.OwnedProcess(command, stdout=asyncio.subprocess.DEVNULL)
            try:
                with patch.object(alias.asyncio, 'create_subprocess_exec', side_effect=async_spawn):
                    await process.start(asyncio.get_running_loop().time() + 3)
                await process.wait()
                self.assertTrue(lock.read_bytes())
                self.assertTrue(await process.cleanup())
                self.assertEqual(lock.read_bytes(), b'')
            finally:
                await process.cleanup()
            with patch.object(alias.subprocess, 'Popen', side_effect=sync_spawn):
                result = alias.run_owned_sync(command, cwd=self.root, env=os.environ.copy(),
                                              timeout=2, max_output_bytes=1024)
            self.assertEqual(result.returncode, 0)
            self.assertEqual(lock.read_bytes(), b'')
        self.assertIs(sys.modules['hydra_sdlc.coordinator'], coordinator)
        self.assertNotIn('coordinator', sys.modules)

    async def test_standalone_alias_cannot_bypass_active_registration_failure(self):
        alias = self.alias_boundary()
        lock = self.root / 'host.lock'
        command = [sys.executable, '-I', '-c', 'pass']
        with coordinator.coordinator_lock(lock):
            ticket = coordinator.register_owned_process()
            marker = lock.read_bytes()
            process = alias.OwnedProcess(command)
            try:
                with patch.object(alias.asyncio, 'create_subprocess_exec', new_callable=AsyncMock) as spawn:
                    with self.assertRaises(coordinator.HostBusy):
                        await process.start(asyncio.get_running_loop().time() + 3)
                    spawn.assert_not_called()
            finally:
                await process.cleanup()
            with patch.object(alias.subprocess, 'Popen') as spawn:
                with self.assertRaises(alias.OwnedCommandError) as raised:
                    alias.run_owned_sync(command, cwd=self.root, env=os.environ.copy(),
                                         timeout=2, max_output_bytes=1024)
                self.assertEqual(raised.exception.reason, 'unavailable')
                spawn.assert_not_called()
            self.assertEqual(lock.read_bytes(), marker)
            coordinator.confirm_owned_cleanup(ticket)

    def test_launcher_ignores_candidate_pythonpath_and_cwd(self):
        source = Path(boundary.__file__).with_name('codex.py')
        (self.root / 'openai_codex.py').write_text('raise RuntimeError("candidate shadow module")')
        command = [sys.executable, '-I', str(source), '--execution-worker']
        process = subprocess.Popen(command, cwd=self.root, env={**os.environ, 'PYTHONPATH': str(self.root)},
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                   start_new_session=True)
        initial = boundary._encode(boundary._frame('assignment', 0, {'assignment': {'cwd': str(self.root), 'task': ''}}))
        # Keep the control pipe open until the result: EOF intentionally kills a live worker.
        process.stdin.write(initial)
        process.stdin.flush()
        frame = boundary._decode(process.stdout.readline())
        self.assertEqual(frame['kind'], 'result')
        self.assertEqual(frame['data']['status'], 'failed')
        process.wait(timeout=3)
        process.stdin.close()
        self.assertNotIn(b'candidate shadow module', process.stderr.read())
        process.stdout.close()
        process.stderr.close()


if __name__ == '__main__':
    unittest.main()
