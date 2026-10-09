import concurrent.futures
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path

from hydra_sdlc.store import StateError, StateStore


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'state.sqlite3'
        self.store = StateStore(self.path)
        self.addCleanup(self.store.db.close)

    def assignment(self, name='a', repo=1, **changes):
        return dict(work_id=name, repository_id=repo, goal_ref='https://example.invalid/issue/1',
                    goal_revision='accepted-goal', spec_ref='docs/spec.md', spec_revision='accepted-spec',
                    cwd=self.temp.name, task='Inspect the specification without changes.', **changes)

    def claim(self):
        self.store.add_work(self.assignment())
        return self.store.claim_next()

    def test_idempotent_input_and_conflicting_identity(self):
        a = self.assignment()
        self.store.add_work(a)
        self.store.add_work(a)
        self.assertEqual(len(self.store.list_work()), 1)
        for key, value in [('repository_id', 2), ('goal_revision', 'other'), ('task', 'changed')]:
            with self.assertRaises(StateError):
                self.store.add_work({**a, key: value})

    def test_rejected_state_file_preserves_unrelated_permissions(self):
        path = Path(self.temp.name) / 'unrelated.txt'
        content = b'Not a database; preserve this file.'
        path.write_bytes(content)
        path.chmod(0o644)
        with self.assertRaises(StateError):
            StateStore(path)
        self.assertEqual(path.stat().st_mode & 0o777, 0o644)
        self.assertEqual(path.read_bytes(), content)

    def test_new_state_is_created_private_even_with_permissive_umask(self):
        previous = os.umask(0)
        try:
            state = StateStore(Path(self.temp.name) / 'private.sqlite3')
        finally:
            os.umask(previous)
        try:
            self.assertEqual(state.path.stat().st_mode & 0o777, 0o600)
        finally:
            state.db.close()

    def test_invalid_types_and_dependencies(self):
        for field, value in [('repository_id', True), ('priority', True), ('dependencies', 'a'),
                             ('dependencies', ['a']), ('dependencies', ['missing']), ('cwd', 'relative'),
                             ('role', 'approve'), ('task', ''), ('metadata', {'not-json'}), ('repository_id', 2**100)]:
            with self.subTest(field=field, value=value), self.assertRaises(StateError):
                self.store.add_work({**self.assignment(), field: value})

    def test_exact_duplicate_survives_unavailable_workspace(self):
        cwd = Path(self.temp.name) / 'workspace'
        cwd.mkdir()
        assignment = {**self.assignment(), 'cwd': str(cwd)}
        original = self.store.add_work(assignment)
        cwd.rmdir()
        self.assertEqual(self.store.add_work(assignment), original)
        with self.assertRaisesRegex(StateError, 'different immutable input'):
            self.store.add_work({**assignment, 'task': 'Changed scope'})
        with self.assertRaisesRegex(StateError, 'existing absolute directory'):
            self.store.add_work({**assignment, 'work_id': 'new'})
        self.assertEqual(len(self.store.list_work()), 1)
        self.assertEqual(self.store.list_runs(), [])

    def test_racing_claims_one_run(self):
        self.store.add_work(self.assignment())

        def attempt(_):
            state = StateStore(self.path)
            try:
                return state.claim_next()
            finally:
                state.db.close()

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
            results = list(pool.map(attempt, range(4)))
        self.assertEqual(sum(r is not None for r in results), 1)
        self.assertEqual(len(self.store.list_runs()), 1)

    def test_reservations_include_waits_and_unknown(self):
        for name, repo in [('a', 1), ('same-repo', 1), ('b', 2), ('c', 3)]:
            self.store.add_work(self.assignment(name, repo))
        a = self.store.claim_next()
        self.store.finish_run(a['id'], a['generation'], 'transport_unknown', {})
        b = self.store.claim_next()
        self.assertEqual(b['work_id'], 'b')
        self.store.finish_run(b['id'], b['generation'], 'completed', {'claimed_goal_achieved': True})
        self.assertIsNone(self.store.claim_next())
        self.assertEqual(self.store.get_work('b')['wait_reason'], 'verification')

    def test_reopen_does_not_expire_ownership(self):
        run = self.claim()
        self.store.set_identity(run['id'], 1, thread_id='t', turn_id='turn')
        reopened = StateStore(self.path)
        self.addCleanup(reopened.db.close)
        self.assertIsNone(reopened.claim_next())
        self.assertEqual(reopened.list_runs()[0]['thread_id'], 't')

    def test_cancel_unknown_recovery_preserves_cancel(self):
        run = self.claim()
        self.store.request_cancel('a')
        self.store.finish_run(run['id'], 1, 'transport_unknown', {})
        with self.assertRaises(StateError):
            self.store.resume('a')
        for confirmation in (False, 1, 'true', None):
            with self.assertRaises(StateError):
                self.store.recover_run(run['id'], confirmation, 'observation')
        self.store.recover_run(run['id'], True, 'Owned process termination observed in fixture')
        self.assertEqual(self.store.get_work('a')['status'], 'cancelled')
        with self.assertRaises(StateError):
            self.store.resume('a')

    def test_cancel_late_completion_never_admits_result(self):
        run = self.claim()
        self.store.request_cancel('a')
        event = self.store.record_event(run['id'], 1, 'late', {'candidate_ready': True})
        self.assertTrue(event['stale'])
        self.store.finish_run(run['id'], 1, 'completed', {'outcome': 'achieved'})
        self.assertEqual(self.store.get_work('a')['status'], 'cancelled')

    def test_generation_resume_and_identity_fencing(self):
        run = self.claim()
        self.store.set_identity(run['id'], 1, thread_id='saved')
        with self.assertRaises(StateError):
            self.store.set_identity(run['id'], 1, thread_id='other')
        self.store.pause('a')
        with self.assertRaises(StateError):
            self.store.resume('a')
        self.store.finish_run(run['id'], 1, 'interrupted', {})
        self.store.resume('a')
        new = self.store.claim_next()
        self.assertEqual(new['generation'], 2)
        self.assertEqual(new['resume_thread_id'], 'saved')
        with self.assertRaises(StateError):
            self.store.finish_run(run['id'], 1, 'completed', {})

    def test_duplicate_event_conflict_and_wrong_generation(self):
        run = self.claim()
        self.store.record_event(run['id'], 1, 'e', {'value': 1})
        self.store.record_event(run['id'], 1, 'e', {'value': 1})
        self.assertEqual(len(self.store.events(run['id'])), 1)
        with self.assertRaises(StateError):
            self.store.record_event(run['id'], 1, 'e', {'value': 2})
        with self.assertRaises(StateError):
            self.store.record_event(run['id'], 2, 'f', {})

    def test_decision_wait_and_unmet_dependency_do_not_dispatch(self):
        run = self.claim()
        self.store.add_work(self.assignment('dependent', 2, dependencies=['a']))
        self.store.finish_run(run['id'], 1, 'completed', {'detail': {'result': {'outcome': 'needs_decision'}}})
        self.assertEqual(self.store.get_work('a')['wait_reason'], 'decision')
        self.assertIsNone(self.store.claim_next())

    def test_local_stop_before_run(self):
        self.store.add_work(self.assignment())
        self.store.pause('a')
        self.assertIsNone(self.store.claim_next())
        self.store.resume('a')
        self.store.request_cancel('a')
        self.assertIsNone(self.store.claim_next())

    def test_unknown_database_version_not_reinitialized(self):
        self.store.db.execute('PRAGMA user_version=99')
        with self.assertRaises(StateError):
            StateStore(self.path)
        self.assertEqual(self.store.db.execute('PRAGMA user_version').fetchone()[0], 99)

    def test_malformed_result_preserves_provider_terminal_not_completion(self):
        run = self.claim()
        self.store.finish_run(run['id'], 1, 'completed', {'detail': None})
        self.assertEqual(self.store.list_runs()[0]['status'], 'completed')
        self.assertEqual(self.store.get_work('a')['status'], 'waiting')

    def test_incomplete_versioned_database_rejected(self):
        bad = Path(self.temp.name) / 'bad.sqlite3'
        connection = sqlite3.connect(bad)
        connection.execute('PRAGMA user_version=1')
        connection.close()
        with self.assertRaises(StateError):
            StateStore(bad)

    def test_busy_transaction_is_explicit_state_error(self):
        connection = sqlite3.connect(self.path)
        self.addCleanup(connection.close)
        connection.execute('BEGIN IMMEDIATE')
        self.store.db.execute('PRAGMA busy_timeout=1')
        with self.assertRaises(StateError):
            self.store.add_work(self.assignment())


if __name__ == '__main__':
    unittest.main()
