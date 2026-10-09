import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from hydra_sdlc import execution_boundary as boundary


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
    status = 'completed'
    if mode == 'silent':
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
                       'result': {'outcome': 'candidate_ready'}}}
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
        self.mode = 'silent'
        asyncio.get_running_loop().call_later(.15, setattr, self, 'stop', True)
        result = await self.run_worker()
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

    async def test_blocked_sdk_startup_and_shutdown_are_bounded(self):
        for mode in ('startup_hang', 'late_start', 'shutdown_hang'):
            with self.subTest(mode=mode):
                self.mode = mode
                self.marker.unlink(missing_ok=True)
                result = await self.run_worker(timeout=.2)
                self.assertEqual(result['status'], 'completed' if mode == 'shutdown_hang' else 'failed')
                self.assertNotIn('late_runtime', [x['name'] for x in self.observations()])
                self.assert_pids_gone()

    async def test_cleanup_uncertainty_overrides_completed_provider(self):
        with patch.object(boundary, '_cleanup', new=AsyncMock(return_value=False)):
            result = await self.run_worker()
        self.assertEqual(result['status'], 'transport_unknown')
        self.assertEqual(result['detail']['cleanup'], 'unknown')

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

    def test_parent_pipe_eof_terminates_owned_group(self):
        self.mode = 'eof'
        process = subprocess.Popen(self.command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                   stderr=subprocess.DEVNULL, start_new_session=True)
        try:
            process.stdin.write(boundary._encode(boundary._frame('assignment', 0, {'assignment': {}})))
            process.stdin.flush()
            until = time.monotonic() + 3
            while not any(x['name'] == 'descendant' for x in self.observations()):
                if time.monotonic() > until:
                    self.fail('worker did not start')
                time.sleep(.005)
            process.stdin.close()
            process.wait(timeout=3)
            until = time.monotonic() + 2
            while time.monotonic() < until:
                try:
                    self.assert_pids_gone()
                    break
                except AssertionError:
                    time.sleep(.02)
            self.assert_pids_gone()
        finally:
            if process.poll() is None:
                os.killpg(process.pid, 9)
                process.wait(timeout=2)
            process.stdout.close()

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
