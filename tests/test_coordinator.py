import asyncio
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hydra_sdlc.coordinator import coordinator_lock, run_once
from hydra_sdlc.store import StateError, StateStore


class CoordinatorTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.sqlite3'
        self.store = StateStore(self.path)
        self.addCleanup(self.store.db.close)
        self.store.add_work(dict(work_id='a', repository_id=1, goal_ref='issue', goal_revision='g',
                                 spec_ref='spec', spec_revision='s', cwd=self.temp.name, task='Inspect'))

    def test_completed_turn_persists_identity_but_not_work_completion(self):
        calls = []

        async def runner(assignment, **callbacks):
            calls.append(assignment)
            callbacks['on_identity'](thread_id='thread')
            callbacks['on_identity'](turn_id='turn')
            callbacks['on_event']('e', {'method': 'turn/completed'})
            return {'status': 'completed', 'detail': {'result': {'outcome': 'candidate_ready'}}}

        result = asyncio.run(run_once(self.store, self.path, runner))
        self.assertEqual(result['work']['wait_reason'], 'verification')
        self.assertEqual(self.store.list_runs()[0]['turn_id'], 'turn')
        self.assertEqual(asyncio.run(run_once(self.store, self.path, runner))['action'], 'idle')
        self.assertEqual(len(calls), 1)

    def test_competing_coordinator_does_not_claim(self):
        with coordinator_lock(self.path), self.assertRaises(StateError):
            asyncio.run(run_once(self.store, self.path, execute=lambda: None))
        self.assertEqual(self.store.list_runs(), [])

    def test_process_inspection_failure_leaves_work_dispatchable(self):
        calls = []

        async def runner(*args, **kwargs):
            calls.append(True)
            return {'status': 'completed', 'detail': {}}

        for error in (FileNotFoundError('ps'), subprocess.CalledProcessError(1, 'ps'),
                      subprocess.TimeoutExpired('ps', 5)):
            with self.subTest(error=type(error).__name__):
                with patch('hydra_sdlc.coordinator.subprocess.check_output', side_effect=error):
                    with self.assertRaisesRegex(StateError, 'no work was started'):
                        asyncio.run(run_once(self.store, self.path, runner))
                self.assertEqual(self.store.list_runs(), [])
                self.assertEqual(self.store.get_work('a')['status'], 'ready')
                self.assertEqual(calls, [])
        result = asyncio.run(run_once(self.store, self.path, runner))
        self.assertEqual(result['action'], 'executed')
        self.assertEqual(len(calls), 1)

    def test_empty_process_inspection_does_not_claim(self):
        with patch('hydra_sdlc.coordinator.subprocess.check_output', return_value='\n'):
            with self.assertRaises(StateError):
                asyncio.run(run_once(self.store, self.path, execute=lambda: None))
        self.assertEqual(self.store.list_runs(), [])

    def test_exception_retains_unknown_attempt(self):
        async def broken(*args, **kwargs):
            kwargs['on_identity'](thread_id='observed')
            raise ConnectionError('Provider diagnostic must not escape')

        result = asyncio.run(run_once(self.store, self.path, broken))
        self.assertEqual(result['work']['wait_reason'], 'recovery')
        self.assertIsNotNone(result['work']['current_run_id'])
        self.assertEqual(self.store.list_runs()[0]['thread_id'], 'observed')

    def test_malformed_adapter_outcome_retains_unknown(self):
        async def broken(*args, **kwargs):
            return None

        result = asyncio.run(run_once(self.store, self.path, broken))
        self.assertEqual(result['work']['wait_reason'], 'recovery')
        self.assertEqual(self.store.list_runs()[0]['status'], 'transport_unknown')

    def test_stop_callback_and_terminal_cancel(self):
        async def runner(*args, **kwargs):
            other = StateStore(self.path)
            try:
                other.request_cancel('a')
            finally:
                other.db.close()
            self.assertTrue(kwargs['stop_requested']())
            return {'status': 'interrupted', 'detail': {}}

        result = asyncio.run(run_once(self.store, self.path, runner))
        self.assertEqual(result['work']['status'], 'cancelled')

    def test_resume_passes_identified_thread(self):
        run = self.store.claim_next()
        self.store.set_identity(run['id'], 1, thread_id='saved-thread')
        self.store.finish_run(run['id'], 1, 'interrupted', {})
        self.store.resume('a')

        async def resumed(*args, **kwargs):
            self.assertEqual(kwargs['resume_thread_id'], 'saved-thread')
            return {'status': 'completed', 'detail': {}}

        result = asyncio.run(run_once(self.store, self.path, resumed))
        self.assertEqual(result['work']['generation'], 2)


if __name__ == '__main__':
    unittest.main()
