import copy
import unittest
from urllib.parse import parse_qs, urlsplit

from hydra_sdlc.github import GitHub, GitHubError
from test_github import BASE, HEAD, REPO, REPOSITORY, owned_pr


PROVIDER = {'login': 'chatgpt-codex-connector[bot]', 'user_id': 199175422, 'app_id': 1144995}


def connection(nodes, cursor=None):
    return {'nodes': nodes, 'pageInfo': {'hasNextPage': cursor is not None, 'endCursor': cursor}}


def comment(number, login=PROVIDER['login']):
    return {'databaseId': number, 'author': {'login': login} if login else None}


def thread(nodes, cursor=None, *, identity='PRRT_large', resolved=False):
    return {'id': identity, 'isResolved': resolved, 'isOutdated': True,
            'comments': connection(nodes, cursor)}


def outer(nodes, cursor=None, *, pr='PR_known'):
    return {'data': {'repository': {'pullRequest': {
        'id': pr, 'reviewDecision': None, 'reviewThreads': connection(nodes, cursor)}}}}


def nested(nodes, cursor=None, *, pr='PR_known', identity='PRRT_large'):
    return {'data': {'node': {'id': identity, 'pullRequest': {'id': pr},
                             'comments': connection(nodes, cursor)}}}


class ReviewTransport:
    def __init__(self, *, resolved=False, human_reply=False):
        self.resolved = resolved
        self.human_reply = human_reply
        self.queries = []
        self.mutations = 0

    def __call__(self, method, path, payload):
        if path == '/graphql':
            if payload['query'].startswith('mutation'):
                self.mutations += 1
                self.resolved = True
                return {'data': {'resolveReviewThread': {'thread': {
                    'id': 'PRRT_large', 'isResolved': True}}}}
            self.queries.append(copy.deepcopy(payload))
            variables = payload['variables']
            if 'thread' in variables:
                return nested([comment(101, 'human' if self.human_reply else PROVIDER['login'])])
            if variables['cursor'] is None:
                return outer([thread([comment(i) for i in range(1, 101)], 'comments-2',
                                     resolved=self.resolved)], 'threads-2')
            return outer([thread([comment(102, None)], identity='PRRT_small', resolved=True)])
        if path == f'/repos/{REPO}':
            return copy.deepcopy(REPOSITORY)
        if path == f'/repos/{REPO}/pulls/7':
            return {**owned_pr(), 'changed_files': 0, 'commits': 1}
        if path == f'/repos/{REPO}/git/ref/heads/main':
            return {'object': {'sha': BASE}}
        if path.startswith(f'/repos/{REPO}/pulls/7/comments?'):
            comments = [{'id': i, 'user': {'id': PROVIDER['user_id'], 'login': PROVIDER['login']},
                         'performed_via_github_app': {'id': PROVIDER['app_id']}} for i in range(1, 102)]
            if self.human_reply:
                comments[-1]['user'] = {'id': 8, 'login': 'human'}
            page = int(parse_qs(urlsplit(path).query)['page'][0])
            return comments[(page - 1) * 100:page * 100]
        if '/check-runs?' in path:
            return {'check_runs': []}
        if '/actions/runs?' in path:
            return {'workflow_runs': []}
        if '/commits?' in path:
            return [{'sha': HEAD}]
        if '/rules/branches/' in path:
            return []
        if method == 'GET' and '?' in path:
            return []
        raise AssertionError((method, path, payload))


class ReviewThreadPaginationTests(unittest.TestCase):
    def test_observe_collects_all_comments_for_resolved_and_unresolved_threads(self):
        for resolved in (False, True):
            with self.subTest(resolved=resolved):
                transport = ReviewTransport(resolved=resolved)
                observed = GitHub(transport=transport).observe(REPO, 7)
                threads = observed['threads']
                self.assertEqual([t['id'] for t in threads], ['PRRT_large', 'PRRT_small'])
                self.assertEqual(threads[0]['isResolved'], resolved)
                self.assertEqual([c['databaseId'] for c in threads[0]['comments']['nodes']], list(range(1, 102)))
                self.assertEqual(threads[0]['comments']['nodes'][-1]['author']['login'], PROVIDER['login'])
                self.assertIsNone(threads[1]['comments']['nodes'][0]['author'])
                self.assertFalse(threads[0]['comments']['pageInfo']['hasNextPage'])
                self.assertEqual(len(transport.queries), 3)
                self.assertEqual(transport.mutations, 0)

    def test_resolution_authenticates_late_comments_and_preserves_human_reply(self):
        for human_reply in (False, True):
            with self.subTest(human_reply=human_reply):
                transport = ReviewTransport(human_reply=human_reply)
                github = GitHub(transport=transport)
                if human_reply:
                    with self.assertRaises(GitHubError):
                        github.resolve_thread(REPO, 7, 'PRRT_large', HEAD, PROVIDER)
                    self.assertEqual(transport.mutations, 0)
                else:
                    resolved = github.resolve_thread(REPO, 7, 'PRRT_large', HEAD, PROVIDER)
                    self.assertTrue(resolved['isResolved'])
                    self.assertEqual(len(resolved['comments']['nodes']), 101)
                    self.assertEqual(transport.mutations, 1)

    def test_nested_identity_duplicate_or_malformed_comments_never_return_partial_evidence(self):
        for later in (nested([comment(101)], pr='PR_foreign'),
                      nested([comment(101)], identity='PRRT_foreign'),
                      nested([comment(100)]),
                      nested([{'databaseId': None, 'author': None}]),
                      {'data': {'node': None}},
                      nested(None)):
            with self.subTest(later=later):
                def transport(method, path, payload):
                    if 'thread' in payload['variables']:
                        return copy.deepcopy(later)
                    return outer([thread([comment(i) for i in range(1, 101)], 'comments-2')])
                with self.assertRaises(GitHubError):
                    GitHub(transport=transport)._threads(REPO, 7)

    def test_outer_pr_identity_and_duplicate_thread_are_rejected(self):
        for later in (outer([], pr='PR_foreign'), outer([thread([comment(2)])])):
            with self.subTest(later=later):
                def transport(method, path, payload):
                    return copy.deepcopy(later) if payload['variables']['cursor'] else outer([thread([comment(1)])], 'next')
                with self.assertRaises(GitHubError):
                    GitHub(transport=transport)._threads(REPO, 7)

    def test_cursor_cycles_in_either_collection_are_bounded(self):
        for inner in (False, True):
            with self.subTest(inner=inner):
                calls = []
                def transport(method, path, payload):
                    calls.append(copy.deepcopy(payload))
                    variables = payload['variables']
                    cursor = variables['cursor']
                    next_cursor = 'one' if cursor in (None, 'two') else 'two'
                    if inner:
                        if 'thread' not in variables:
                            return outer([thread([comment(1)], 'one')])
                        return nested([comment(len(calls))], next_cursor)
                    return outer([], next_cursor)
                with self.assertRaises(GitHubError):
                    GitHub(transport=transport)._threads(REPO, 7)
                self.assertEqual(len(calls), 3)

    def test_outer_and_nested_queries_share_one_hundred_request_bound(self):
        calls = []
        def transport(method, path, payload):
            calls.append(copy.deepcopy(payload))
            if 'thread' not in payload['variables']:
                return outer([thread([comment(1)], 'comments-1')], 'outer-next')
            return nested([comment(len(calls))], 'comments-' + str(len(calls)))
        with self.assertRaises(GitHubError):
            GitHub(transport=transport)._threads(REPO, 7)
        self.assertEqual(len(calls), 100)


if __name__ == '__main__':
    unittest.main()
