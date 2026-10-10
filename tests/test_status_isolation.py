"""Status preserves healthy observations when a repository or progress read fails."""

import copy
import json
import unittest
from unittest.mock import Mock, patch

from hydra_sdlc.github import GitHubError
from hydra_sdlc.runner import Runner, intake_digest
from test_runner import GitHub


PRIVATE_ERROR = 'private-status-observation-detail'
FIRST, BROKEN, LAST = 'example/first', 'example/broken', 'example/last'


class StatusGitHub(GitHub):
    def __init__(self):
        super().__init__()
        self.rows, self.records = {}, {}
        for repo, numbers in ((FIRST, [1]), (BROKEN, [2, 3]), (LAST, [4])):
            self.rows[repo] = []
            for number in numbers:
                issue = {**copy.deepcopy(self.work), 'number': number}
                self.rows[repo].append(issue)
                self.records[repo, number] = dict(phase='review_wait', pending_action=None,
                                                 wait_reason='remote_delivery_gates',
                                                 intake_digest=intake_digest(issue))
        self.discovery_error = self.progress_error = None
        self.discovery_calls, self.progress_calls = [], []

    def issues(self, repo):
        self.discovery_calls.append(repo)
        if repo.casefold() == BROKEN and self.discovery_error:
            raise self.discovery_error
        return copy.deepcopy(self.rows[repo.casefold()])

    def progress(self, repo, number):
        self.progress_calls.append((repo, number))
        if repo.casefold() == BROKEN and number == 2 and self.progress_error:
            raise self.progress_error
        return copy.deepcopy(self.records[repo.casefold(), number])

    def issue(self, repo, number):
        return copy.deepcopy(next(row for row in self.rows[repo.casefold()] if row['number'] == number))


class StatusIsolationTests(unittest.TestCase):
    def setUp(self):
        self.github = StatusGitHub()
        self.workspace = Mock()
        self.runner = Runner(self.github, self.workspace, host_alias='status',
                             execute=self.forbidden_dispatch, capabilities=self.forbidden_dispatch)
        self.config_calls = []
        def load(github, repo, **kwargs):
            self.config_calls.append(repo)
            return {**copy.deepcopy(github.cfg), 'repository': repo.casefold()}
        load_patch = patch('hydra_sdlc.runner.load_project', side_effect=load)
        load_patch.start()
        self.addCleanup(load_patch.stop)
        self.before = copy.deepcopy((self.github.rows, self.github.records))

    def forbidden_dispatch(self, *args, **kwargs):
        self.fail('Read-only status must not dispatch capability or model work')

    def assert_read_only(self, result):
        self.assertEqual((self.github.rows, self.github.records), self.before)
        self.assertEqual(self.github.writes, [])
        self.assertEqual(self.workspace.mock_calls, [])
        self.assertNotIn(PRIVATE_ERROR, json.dumps(result))

    def test_repository_discovery_failure_preserves_healthy_results_and_alias_deduplication(self):
        for error in (ValueError, GitHubError, OSError):
            with self.subTest(error=error):
                self.github.discovery_error = error(PRIVATE_ERROR)
                self.github.discovery_calls.clear()
                self.github.progress_calls.clear()
                self.config_calls.clear()
                result = self.runner.status([FIRST, BROKEN, 'EXAMPLE/BROKEN', LAST])
                self.assertEqual([row['repository'] for row in result], [FIRST, BROKEN, LAST])
                self.assertEqual(result[1], {'repository': BROKEN, 'wait_reason': 'project_contract_unavailable'})
                self.assertEqual([result[index]['issue'] for index in (0, 2)], [1, 4])
                self.assertTrue(all(result[index]['wait_reason'] == 'remote_delivery_gates' for index in (0, 2)))
                self.assertEqual(self.github.discovery_calls, [FIRST, BROKEN, LAST])
                self.assertFalse(any(repo == BROKEN for repo, _ in self.github.progress_calls))
                self.assertNotIn(BROKEN, self.config_calls)
                self.assert_read_only(result)

    def test_progress_failure_preserves_next_issue_and_other_repository_without_false_unowned_state(self):
        for error in (ValueError, GitHubError, OSError):
            with self.subTest(error=error):
                self.github.progress_error = error(PRIVATE_ERROR)
                result = self.runner.status([FIRST, BROKEN, LAST])
                self.assertEqual([row['issue'] for row in result], [1, 2, 3, 4])
                self.assertEqual(result[1], {'repository': BROKEN, 'issue': 2, 'state': 'open',
                                             'progress': None, 'wait_reason': 'intake_unavailable'})
                for index in (0, 2, 3):
                    self.assertEqual(result[index]['wait_reason'], 'remote_delivery_gates')
                    self.assertIsNotNone(result[index]['progress'])
                self.assert_read_only(result)

    def test_base_exceptions_propagate_from_both_discovery_boundaries(self):
        for boundary in ('discovery_error', 'progress_error'):
            for error in (KeyboardInterrupt, SystemExit):
                with self.subTest(boundary=boundary, error=error):
                    self.github.discovery_error = self.github.progress_error = None
                    setattr(self.github, boundary, error(PRIVATE_ERROR))
                    with self.assertRaises(error):
                        self.runner.status([BROKEN, LAST])
                    self.assert_read_only([])


if __name__ == '__main__':
    unittest.main()
