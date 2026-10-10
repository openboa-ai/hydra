"""Native label discovery and interrupted completion cleanup, without a local DB."""

import copy
import json
import unittest

from hydra_sdlc.github import GitHub, GitHubError
from test_github import BASE, HEAD, IDENTITY, REPO, REPOSITORY
import test_runner


class NativeIssueTransport:
    def __init__(self):
        self.issue = {'number': 4, 'state': 'open', 'comments': 0,
                      'labels': [{'name': 'unrelated'}]}
        self.comment = None
        self.label_exists = True
        self.calls = []
        self.fail = None

    def __call__(self, method, path, payload):
        self.calls.append((method, path, copy.deepcopy(payload)))
        prefix = f'/repos/{REPO}'
        if method == 'GET':
            if path == '/user':
                return copy.deepcopy(IDENTITY)
            if path == prefix:
                return copy.deepcopy(REPOSITORY)
            if path == prefix + '/issues/4':
                return copy.deepcopy(self.issue)
            if path == prefix + '/labels/hydra%3Aactive':
                if not self.label_exists:
                    raise GitHubError('missing', status=404)
                return {'name': 'hydra:active'}
            if path == prefix + '/issues/4/comments?per_page=100&page=1':
                return [copy.deepcopy(self.comment)] if self.comment else []
            if path == prefix + '/issues?state=open&sort=created&direction=asc&per_page=100&page=1':
                return [copy.deepcopy(self.issue)] if self.issue['state'] == 'open' else []
            if path == prefix + '/issues?state=closed&labels=hydra%3Aactive&sort=created&direction=asc&per_page=100&page=1':
                active = {'name': 'hydra:active'} in self.issue['labels']
                return [copy.deepcopy(self.issue)] if self.issue['state'] == 'closed' and active else []
        elif method == 'POST' and path == prefix + '/labels':
            self.label_exists = True
            return {'name': payload['name']}
        elif method == 'POST' and path == prefix + '/issues/4/labels':
            if self.fail == 'label_add':
                raise GitHubError('label unavailable', status=403)
            self.issue['labels'].append({'name': 'hydra:active'})
            return copy.deepcopy(self.issue['labels'])
        elif (method, path) in [('POST', prefix + '/issues/4/comments'),
                               ('PATCH', prefix + '/issues/comments/77')]:
            if self.fail == 'comment_before':
                raise GitHubError('progress unavailable', uncertain=True)
            self.comment = {'id': 77, 'user': copy.deepcopy(IDENTITY), 'body': payload['body']}
            self.issue['comments'] = 1
            if self.fail == 'comment_after':
                raise GitHubError('response lost', uncertain=True)
            return copy.deepcopy(self.comment)
        elif method == 'DELETE' and path == prefix + '/issues/4/labels/hydra%3Aactive':
            if self.fail == 'label_remove_before':
                raise GitHubError('cleanup unavailable', uncertain=True)
            self.issue['labels'] = [x for x in self.issue['labels'] if x['name'] != 'hydra:active']
            if self.fail == 'label_remove_after':
                raise GitHubError('cleanup response lost', uncertain=True)
            return copy.deepcopy(self.issue['labels'])
        raise AssertionError(f'Unexpected transport action: {method} {path}')


class ActiveLabelTests(unittest.TestCase):
    def setUp(self):
        self.transport = NativeIssueTransport()
        self.github = GitHub(transport=self.transport)
        self.record = {'phase': 'ready', 'branch': 'hydra/issue-4', 'head': HEAD,
                       'contract_revision': BASE, 'pending_action': None}

    def test_active_precedes_authorizing_progress_and_preserves_other_labels(self):
        self.transport.label_exists = False
        self.github.record(REPO, 4, self.record)
        writes = [(m, p) for m, p, _ in self.transport.calls if m != 'GET']
        self.assertEqual(writes, [('POST', f'/repos/{REPO}/labels'),
                                  ('POST', f'/repos/{REPO}/issues/4/labels'),
                                  ('POST', f'/repos/{REPO}/issues/4/comments')])
        self.assertIn({'name': 'unrelated'}, self.transport.issue['labels'])
        self.assertEqual(self.github.progress(REPO, 4)['phase'], 'ready')

    def test_label_failure_blocks_progress_and_progress_failure_is_not_a_receipt(self):
        for failure in ('label_add', 'comment_before'):
            with self.subTest(failure=failure):
                self.setUp()
                self.transport.fail = failure
                with self.assertRaises(GitHubError):
                    self.github.record(REPO, 4, self.record)
                self.assertIsNone(self.github.progress(REPO, 4))
                if failure == 'label_add':
                    self.assertFalse(any(p.endswith('/comments') and m == 'POST'
                                         for m, p, _ in self.transport.calls))

    def test_completion_is_durable_before_label_cleanup_and_equal_record_retries(self):
        self.github.record(REPO, 4, self.record)
        self.transport.issue['state'] = 'closed'
        completed = {**self.record, 'phase': 'completed'}
        self.transport.fail = 'label_remove_before'
        with self.assertRaises(GitHubError):
            self.github.record(REPO, 4, completed)
        self.assertEqual(self.github.progress(REPO, 4)['phase'], 'completed')
        self.assertEqual(self.github.issues(REPO), [self.transport.issue])
        self.transport.fail = None
        before = len(self.transport.calls)
        self.github.record(REPO, 4, completed)
        writes = [(m, p) for m, p, _ in self.transport.calls[before:] if m != 'GET']
        self.assertEqual(writes, [('DELETE', f'/repos/{REPO}/issues/4/labels/hydra%3Aactive')])
        self.assertEqual(self.github.issues(REPO), [])
        self.assertEqual(self.transport.issue['labels'], [{'name': 'unrelated'}])

    def test_lost_completion_response_keeps_authenticated_recovery_discoverable(self):
        self.github.record(REPO, 4, self.record)
        self.transport.issue['state'] = 'closed'
        completed = {**self.record, 'phase': 'completed'}
        self.transport.fail = 'comment_after'
        with self.assertRaises(GitHubError):
            self.github.record(REPO, 4, completed)
        self.assertEqual(self.github.issues(REPO), [self.transport.issue])
        self.transport.fail = None
        self.github.record(REPO, 4, completed)
        self.assertEqual(self.github.issues(REPO), [])

    def test_lost_label_cleanup_response_does_not_repeat_comment_or_delete(self):
        self.github.record(REPO, 4, self.record)
        self.transport.issue['state'] = 'closed'
        completed = {**self.record, 'phase': 'completed'}
        self.transport.fail = 'label_remove_after'
        with self.assertRaises(GitHubError):
            self.github.record(REPO, 4, completed)
        self.transport.fail = None
        before = len(self.transport.calls)
        self.github.record(REPO, 4, completed)
        self.assertTrue(all(m == 'GET' for m, _, _ in self.transport.calls[before:]))

    def test_closed_history_and_label_without_authenticated_progress_are_not_acquired(self):
        self.transport.issue['state'] = 'closed'
        self.assertEqual(self.github.issues(REPO), [])
        self.transport.issue['labels'].append({'name': 'hydra:active'})
        self.transport.issue['comments'] = 100
        foreign = {'version': 1, 'repository_id': 123, 'issue_number': 4,
                   'pending_action': 'close_issue'}
        self.transport.comment = {'id': 77, 'user': {'login': 'foreign', 'id': 999},
                                  'body': '<!-- hydra-progress:v1 ' + json.dumps(foreign) + ' -->'}
        self.assertEqual(self.github.issues(REPO), [])
        self.assertTrue(all(m == 'GET' for m, _, _ in self.transport.calls))
        self.assertFalse(any('state=all' in p for _, p, _ in self.transport.calls))


class CompletionCleanupTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = test_runner.RunnerTests.asyncSetUp
    execute = test_runner.RunnerTests.execute
    capabilities = test_runner.RunnerTests.capabilities
    runner = test_runner.RunnerTests.runner
    publish = test_runner.RunnerTests.publish

    async def test_changed_pr_owner_retains_active_completion_reconciliation(self):
        runner = await self.publish()
        await runner.step(REPO, 4)
        self.github.note.update(pending_action=None, phase='completed')
        self.github.work['state'] = 'closed'
        transport = NativeIssueTransport()
        transport.issue = {**self.github.work, 'comments': 1,
                           'labels': self.github.work['labels'] + [{'name': 'hydra:active'}]}
        transport.comment = {'id': 77, 'user': IDENTITY,
                             'body': '<!-- hydra-progress:v1 ' + json.dumps(self.github.note) + ' -->'}
        client = GitHub(transport=transport)
        self.github.record = client.record
        self.github.progress = client.progress

        def foreign(value):
            value['pr']['body'] = 'Changed ownership marker'
            return value

        self.github.transform_observation = foreign
        before = len(self.calls)
        self.assertEqual((await self.runner().step(REPO, 4))['reason'], 'foreign_pr')
        self.assertEqual(len(self.calls), before)
        progress = client.progress(REPO, 4)
        self.assertEqual(progress['phase'], 'closing')
        self.assertEqual(progress['pending_action'], 'close_issue')
        self.assertEqual(client.issues(REPO), [transport.issue])
        self.assertFalse(any(m == 'DELETE' for m, _, _ in transport.calls))

    async def test_completed_active_recovery_rechecks_delivery_without_model_or_close(self):
        runner = await self.publish()
        await runner.step('example/product', 4)
        self.github.note.update(pending_action=None, phase='completed')
        self.github.work['state'] = 'closed'
        before = len(self.calls), len(self.github.writes)
        self.assertEqual(self.runner().status(['example/product'])[0]['wait_reason'], 'completion_reconciliation')
        self.assertEqual((len(self.calls), len(self.github.writes)), before)
        actual = self.github.observe_commit

        def pending(repo, sha):
            value = actual(repo, sha)
            value['runs'][0]['status'] = 'in_progress'
            return value

        self.github.observe_commit = pending
        self.assertEqual((await self.runner().cycle(['example/product']))[0]['reason'], 'post_merge_checks')
        self.assertEqual(self.github.note['pending_action'], 'close_issue')
        self.github.observe_commit = actual
        self.assertEqual((await self.runner().cycle(['example/product']))[0]['action'], 'completed')
        self.assertEqual(len(self.calls), before[0])
        self.assertFalse(any(x[0] == 'close' for x in self.github.writes))
