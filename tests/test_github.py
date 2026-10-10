import base64
import copy
import json
import os
import subprocess
import unittest
from unittest.mock import patch

from hydra_sdlc.github import GitHub, GitHubError


HEAD, BASE, MERGE = 'b' * 40, 'a' * 40, 'd' * 40
REPO = 'example/product'
IDENTITY = {'login': 'openboa', 'id': 11}
REPOSITORY = {'id': 123, 'full_name': REPO, 'default_branch': 'main'}


def owned_pr():
    return {'number': 7, 'state': 'open', 'user': IDENTITY,
            'body': '<!-- hydra-pr:v1 {"repository_id":123,"issue_number":4} -->',
            'head': {'sha': HEAD, 'ref': 'hydra/issue-4', 'repo': {'id': 123}},
            'base': {'sha': BASE, 'ref': 'main', 'repo': {'id': 123}},
            'draft': False, 'mergeable': True, 'mergeable_state': 'clean'}


class Fake:
    def __init__(self, replies=None):
        self.replies = replies or {}
        self.calls = []

    def __call__(self, method, path, payload):
        self.calls.append((method, path, payload))
        value = self.replies[(method, path)]
        if isinstance(value, Exception):
            raise value
        return copy.deepcopy(value)


class GitHubTests(unittest.TestCase):
    def test_reads_all_pages_without_treating_pull_requests_as_intake(self):
        first = [{'number': n} for n in range(100)]
        fake = Fake({('GET', f'/repos/{REPO}/issues?state=open&sort=created&direction=asc&per_page=100&page=1'): first,
                     ('GET', f'/repos/{REPO}/issues?state=open&sort=created&direction=asc&per_page=100&page=2'): [{'number': 101}, {'number': 102, 'pull_request': {}}]})
        self.assertEqual(len(GitHub(transport=fake).issues(REPO)), 101)
        self.assertEqual(len(fake.calls), 2)

    def test_authentication_failure_is_not_absent_branch(self):
        path = f'/repos/{REPO}/git/ref/heads/hydra%2Fissue-4'
        for status in [401, 403, 500, None]:
            with self.subTest(status=status), self.assertRaises(GitHubError):
                GitHub(transport=Fake({('GET', path): GitHubError('failure', status=status)})).ref(REPO, 'hydra/issue-4')
        self.assertIsNone(GitHub(transport=Fake({('GET', path): GitHubError('missing', status=404)})).ref(REPO, 'hydra/issue-4'))

    def test_file_only_exact_revision_regular_utf8(self):
        path = f'/repos/{REPO}/contents/.hydra.toml?ref={BASE}'
        value = {'type': 'file', 'encoding': 'base64', 'content': base64.b64encode(b'version=1').decode(), 'sha': HEAD}
        gh = GitHub(transport=Fake({('GET', path): value}))
        self.assertEqual(gh.file(REPO, '.hydra.toml', BASE), {'content': 'version=1', 'sha': HEAD})
        for revision in ['main', '', '../x']:
            with self.assertRaises(GitHubError): gh.file(REPO, '.hydra.toml', revision)
        for kind in ['symlink', 'dir', 'submodule']:
            with self.assertRaises(GitHubError): GitHub(transport=Fake({('GET', path): {**value, 'type': kind}})).file(REPO, '.hydra.toml', BASE)

    def progress_fake(self, comments):
        return Fake({('GET', '/user'): IDENTITY, ('GET', f'/repos/{REPO}'): REPOSITORY,
                     ('GET', f'/repos/{REPO}/issues/4/comments?per_page=100&page=1'): comments,
                     ('POST', f'/repos/{REPO}/issues/4/comments'): {'id': 77},
                     ('PATCH', f'/repos/{REPO}/issues/comments/77'): {'id': 77}})

    def test_foreign_progress_ignored_and_own_duplicate_is_conflict(self):
        body = '<!-- hydra-progress:v1 {"version":1,"repository_id":123,"issue_number":4,"phase":"waiting"} -->'
        foreign = {'id': 1, 'user': {'login': 'openboa', 'id': 999}, 'body': body}
        own = {'id': 77, 'user': IDENTITY, 'body': body}
        self.assertIsNone(GitHub(transport=self.progress_fake([foreign])).progress(REPO, 4))
        self.assertEqual(GitHub(transport=self.progress_fake([foreign, own])).progress(REPO, 4)['phase'], 'waiting')
        with self.assertRaises(GitHubError): GitHub(transport=self.progress_fake([own, own])).progress(REPO, 4)

    def test_progress_no_change_no_write_and_strict_public_fields(self):
        record = {'phase': 'waiting', 'branch': 'hydra/issue-4', 'head': HEAD,
                  'attempt_id': '12345678-1234-1234-1234-123456789abc', 'wait_reason': 'ci_pending'}
        metadata = {**record, 'version': 1, 'repository_id': 123, 'issue_number': 4}
        own = {'id': 77, 'user': IDENTITY, 'body': '<!-- hydra-progress:v1 ' + json.dumps(metadata) + ' -->'}
        fake = self.progress_fake([own]); gh = GitHub(transport=fake)
        gh.record(REPO, 4, record)
        self.assertFalse(any(m != 'GET' for m, _, _ in fake.calls))
        gh.record(REPO, 4, {**record, 'phase': 'review'})
        body = fake.calls[-1][2]['body']
        self.assertIn('## Hydra progress', body)
        self.assertIn('<!-- hydra-progress:v1 ', body)
        for bad in [{'raw_model_output': 'done'}, {'checkpoint': '/private/report.txt'}, {'phase': 'Here is my report'}, {'branch': 'hydra/issue-5'}, {'attempt_id': 'not-a-uuid'}]:
            with self.subTest(bad=bad), self.assertRaises(GitHubError): gh.record(REPO, 4, bad)

    def test_record_never_overwrites_malformed_or_mismatched_existing_record(self):
        for body in ['<!-- hydra-progress:v1 broken -->', '<!-- hydra-progress:v1 {"version":1,"repository_id":999,"repository_id":123,"issue_number":4} -->', '<!-- hydra-progress:v1 {"version":1,"repository_id":999,"issue_number":4} -->']:
            fake = self.progress_fake([{'id': 77, 'user': IDENTITY, 'body': body}])
            with self.assertRaises(GitHubError): GitHub(transport=fake).record(REPO, 4, {'phase': 'waiting'})
            self.assertFalse(any(m != 'GET' for m, _, _ in fake.calls))

    def pr_fake(self, pulls):
        return Fake({('GET', f'/repos/{REPO}'): REPOSITORY, ('GET', '/user'): IDENTITY,
                     ('GET', f'/repos/{REPO}/pulls?state=all&head=example%3Ahydra%2Fissue-4&per_page=100&page=1'): pulls,
                     ('GET', f'/repos/{REPO}/git/ref/heads/hydra%2Fissue-4'): {'object': {'sha': HEAD}},
                     ('POST', f'/repos/{REPO}/pulls'): owned_pr()})

    def test_pr_ownership_matches_published_json_and_actual_author(self):
        gh = GitHub(transport=self.pr_fake([]))
        self.assertTrue(gh.owns_pr(REPO, 4, owned_pr()))
        for mutation in [
            {'body': '<!-- hydra:pr:v1 repository=example/product issue=4 -->'},
            {'body': '<!-- hydra-pr:v1 {"repository_id":999,"issue_number":4} -->'},
            {'body': '<!-- hydra-pr:v1 {"repository_id":123,"issue_number":5} -->'},
            {'body': '<!-- hydra-pr:v1 {"repository_id":999,"repository_id":123,"issue_number":4} -->'},
            {'body': '<!-- hydra-pr:v1 malformed -->'},
            {'body': owned_pr()['body'] + owned_pr()['body']},
            {'user': {'id': 999, 'login': 'openboa'}}, {'user': {'id': 11, 'login': 'foreign'}},
            {'head': {'sha': HEAD, 'ref': 'hydra/issue-4', 'repo': {'id': 999}}},
            {'head': {'sha': HEAD, 'ref': 'foreign-branch', 'repo': {'id': 123}}},
            {'head': {'sha': HEAD, 'ref': 'hydra/issue-4', 'repo': None}}, {'user': None},
        ]:
            with self.subTest(mutation=mutation):
                self.assertFalse(gh.owns_pr(REPO, 4, {**owned_pr(), **mutation}))
        marker = gh.ensure_pr(REPO, 4, 'hydra/issue-4', HEAD, 'Fix', 'Scope and tests')
        self.assertTrue(gh.owns_pr(REPO, 4, marker))

    def test_existing_owned_pr_recovers_lost_creation_response_without_duplicate(self):
        fake = self.pr_fake([owned_pr()]); gh = GitHub(transport=fake)
        self.assertEqual(gh.ensure_pr(REPO, 4, 'hydra/issue-4', HEAD, 'Fix parser', 'Scope and validation'), owned_pr())
        self.assertFalse(any(m != 'GET' for m, _, _ in fake.calls))
        fake = self.pr_fake([]); gh = GitHub(transport=fake)
        gh.ensure_pr(REPO, 4, 'hydra/issue-4', HEAD, 'Fix parser', 'Scope and validation')
        payload = fake.calls[-1][2]
        self.assertEqual(payload['base'], 'main'); self.assertIn('Related issue: #4', payload['body']); self.assertNotIn('Closes', payload['body'])

    def test_foreign_stale_closed_duplicate_prs_and_auto_close_rejected(self):
        wrong = [dict(user={'id': 999}), dict(body='fake marker'), dict(state='closed'), dict(head={'sha': BASE}), dict(base={'ref': 'other'})]
        for mutation in wrong:
            with self.subTest(mutation=mutation), self.assertRaises(GitHubError):
                GitHub(transport=self.pr_fake([{**owned_pr(), **mutation}])).ensure_pr(REPO, 4, 'hydra/issue-4', HEAD, 'Fix', 'Tests')
        with self.assertRaises(GitHubError): GitHub(transport=self.pr_fake([owned_pr(), owned_pr()])).ensure_pr(REPO, 4, 'hydra/issue-4', HEAD, 'Fix', 'Tests')
        with self.assertRaises(GitHubError): GitHub(transport=self.pr_fake([])).ensure_pr(REPO, 4, 'hydra/issue-4', HEAD, 'Fix', 'Closes #4')

    def test_exact_head_merge_readback_and_unknown_result_not_success(self):
        calls, merged = [], False
        def transport(method, path, payload):
            nonlocal merged
            calls.append((method, path, payload))
            if method == 'PUT':
                self.assertEqual(payload, {'sha': HEAD, 'merge_method': 'squash'}); merged = True
                return {'merged': True, 'sha': MERGE}
            return {**owned_pr(), 'merged': merged, 'merge_commit_sha': MERGE if merged else None}
        gh = GitHub(transport=transport)
        self.assertEqual(gh.merge(REPO, 7, HEAD)['merge_commit_sha'], MERGE)
        self.assertEqual(len(calls), 3)
        gh.merge(REPO, 7, HEAD)
        self.assertEqual(len([c for c in calls if c[0] == 'PUT']), 1)
        with self.assertRaises(GitHubError): gh.merge(REPO, 7, BASE)
        fake = Fake({('GET', f'/repos/{REPO}/pulls/7'): owned_pr(), ('PUT', f'/repos/{REPO}/pulls/7/merge'): {'merged': True}})
        with self.assertRaises(GitHubError) as caught: GitHub(transport=fake).merge(REPO, 7, HEAD)
        self.assertTrue(caught.exception.uncertain)

    def test_gh_auth_is_per_process_bounded_and_never_added_to_parent_environment(self):
        calls = []
        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            if argv[1:3] == ['auth', 'token']:
                return subprocess.CompletedProcess(argv, 0, 'runtime-test-token\n', '')
            if argv[-1] == 'user':
                return subprocess.CompletedProcess(argv, 0, json.dumps(IDENTITY), '')
            return subprocess.CompletedProcess(argv, 0, json.dumps(REPOSITORY), '')
        before = dict(os.environ)
        with patch('hydra_sdlc.github.subprocess.run', side_effect=run):
            gh = GitHub(); gh.repository(REPO); gh.repository(REPO)
        self.assertEqual(os.environ, before)
        self.assertEqual(sum(argv[1:3] == ['auth', 'token'] for argv, _ in calls), 2)
        self.assertEqual(sum(argv[-1] == 'user' for argv, _ in calls), 1)
        for argv, options in calls:
            self.assertIn('timeout', options)
            self.assertNotIn('runtime-test-token', argv)
            if argv[1] == 'api': self.assertEqual(options['env']['GH_TOKEN'], 'runtime-test-token')
        with self.assertRaises(GitHubError): GitHub(user='operator')

    def test_changed_credential_is_reauthenticated_before_polling_or_writing(self):
        token = 'first'
        calls = []
        def run(argv, **kwargs):
            calls.append(argv)
            if argv[1] == 'auth':
                return subprocess.CompletedProcess(argv, 0, token, '')
            if argv[-1] == 'user':
                identity = IDENTITY if token == 'first' else {'login': 'operator'}
                return subprocess.CompletedProcess(argv, 0, json.dumps(identity), '')
            return subprocess.CompletedProcess(argv, 0, json.dumps(REPOSITORY), '')
        with patch('hydra_sdlc.github.subprocess.run', side_effect=run):
            gh = GitHub()
            gh.repository(REPO)
            before = len(calls)
            token = 'changed'
            with self.assertRaises(GitHubError):
                gh.api('PATCH', '/repos/' + REPO, {'description': 'never sent'})
        self.assertEqual(len(calls) - before, 2)
        self.assertFalse(any('PATCH' in argv for argv in calls))

    def test_transport_failure_does_not_expose_token_or_diagnostic(self):
        def run(argv, **kwargs):
            if argv[1] == 'auth': return subprocess.CompletedProcess(argv, 0, 'sensitive-token', '')
            if argv[-1] == 'user': return subprocess.CompletedProcess(argv, 0, json.dumps(IDENTITY), '')
            return subprocess.CompletedProcess(argv, 1, '', 'sensitive-token HTTP 403')
        with patch('hydra_sdlc.github.subprocess.run', side_effect=run):
            with self.assertRaises(GitHubError) as caught: GitHub().close_issue(REPO, 4)
        self.assertEqual(str(caught.exception), 'GitHub request failed')
        self.assertEqual(caught.exception.status, 403)
        self.assertTrue(caught.exception.uncertain)

    def test_review_request_lost_response_recovers_and_never_reposts(self):
        posted = []
        calls = []
        def transport(method, path, payload):
            calls.append((method, path, payload))
            if path == '/user': return IDENTITY
            if path == f'/repos/{REPO}/pulls/7': return owned_pr()
            if method == 'GET': return posted
            posted.append({'id': 99, 'user': IDENTITY, 'body': payload['body']})
            raise GitHubError('response lost', uncertain=True)
        gh = GitHub(transport=transport)
        self.assertEqual(gh.request_review(REPO, 7, head=HEAD)['id'], 99)
        self.assertIn(f'head={HEAD} kind=code', posted[0]['body'])
        gh.request_review(REPO, 7, head=HEAD)
        self.assertEqual(sum(m == 'POST' for m, _, _ in calls), 1)
        with self.assertRaises(GitHubError): gh.request_review(REPO, 7, head=BASE)

    def test_progress_recovery_fields_are_typed_and_bounded(self):
        fake = self.progress_fake([])
        record = {'phase': 'publishing', 'expected_head': HEAD, 'expected_base': BASE,
                  'action_attempt': 3, 'review_requested_head': HEAD}
        GitHub(transport=fake).record(REPO, 4, record)
        for mutation in [{'action_attempt': 4}, {'action_attempt': True}, {'expected_base': 'main'}, {'review_requested_head': 'short'}]:
            with self.subTest(mutation=mutation), self.assertRaises(GitHubError):
                GitHub(transport=fake).record(REPO, 4, {**record, **mutation})

    def test_delivery_retry_record_round_trips_independently_of_model_action(self):
        fields = {'delivery_action': 'merge', 'delivery_attempt': 3, 'delivery_head': HEAD,
                  'review_requested_security_head': HEAD}
        record = {**fields, 'pending_action': 'review', 'action_attempt': 1}
        fake = self.progress_fake([])
        gh = GitHub(transport=fake)
        gh.record(REPO, 4, record)
        body = fake.calls[-1][2]['body']
        own = {'id': 77, 'user': IDENTITY, 'body': body}
        restored = GitHub(transport=self.progress_fake([own])).progress(REPO, 4)
        self.assertEqual({k: restored[k] for k in fields}, fields)
        self.assertEqual(restored['pending_action'], 'review')
        self.assertEqual(restored['action_attempt'], 1)
        gh.record(REPO, 4, {k: None for k in fields})
        for key, values in {'delivery_action': ['raw action text', '/private/path'],
                            'delivery_attempt': [0, 4, True, '3'], 'delivery_head': ['main'],
                            'review_requested_security_head': ['short']}.items():
            for value in values:
                with self.subTest(key=key, value=value), self.assertRaises(GitHubError):
                    gh.record(REPO, 4, {**record, key: value})

    def test_commit_observation_binds_jobs_to_returned_run(self):
        fake = Fake({('GET', f'/repos/{REPO}'): REPOSITORY,
                     ('GET', f'/repos/{REPO}/commits/{MERGE}/check-runs?filter=latest&per_page=100&page=1'): {'check_runs': [{'id': 91}]},
                     ('GET', f'/repos/{REPO}/actions/runs?head_sha={MERGE}&per_page=100&page=1'): {'workflow_runs': [{'id': 50}]},
                     ('GET', f'/repos/{REPO}/actions/runs/50'): {'id': 50, 'head_sha': MERGE},
                     ('GET', f'/repos/{REPO}/actions/runs/50/jobs?filter=latest&per_page=100&page=1'): {'jobs': [{'id': 91}]}})
        observed = GitHub(transport=fake).observe_commit(REPO, MERGE)
        self.assertEqual(observed['head_sha'], MERGE)
        self.assertEqual(observed['runs'][0]['jobs'], [{'id': 91}])

    def thread_transport(self, *, outdated=True, author=None, app=None, lose_response=False, change_head=False, extra_thread_comment=False, human_reply=False):
        provider = {'login': 'chatgpt-codex-connector[bot]', 'user_id': 199175422, 'app_id': 1144995}
        state = {'resolved': False, 'mutations': 0}
        def transport(method, path, payload):
            if path.endswith('/pulls/7'):
                return {**owned_pr(), 'head': {'sha': BASE if change_head and state['resolved'] else HEAD}}
            if '/pulls/7/comments?' in path:
                return [{'id': 81, 'user': author or {'id': provider['user_id'], 'login': provider['login']}, 'performed_via_github_app': app}] + ([{'id': 82, 'user': {'id': 8, 'login': 'human'}}] if human_reply else [])
            if payload['query'].startswith('mutation'):
                self.assertEqual(payload['variables'], {'thread': 'PRRT_known'})
                self.assertIn('resolveReviewThread', payload['query'])
                state.update(resolved=True, mutations=state['mutations'] + 1)
                if lose_response: raise GitHubError('response lost', uncertain=True)
                return {'data': {'resolveReviewThread': {'thread': {'id': 'PRRT_known', 'isResolved': True}}}}
            nodes = [{'databaseId': 81}]
            if human_reply or extra_thread_comment and state['resolved']: nodes.append({'databaseId': 82})
            thread = {'id': 'PRRT_known', 'isOutdated': outdated, 'isResolved': state['resolved'],
                      'comments': {'nodes': nodes, 'pageInfo': {'hasNextPage': False}}}
            return {'data': {'repository': {'pullRequest': {'reviewDecision': None,
                    'reviewThreads': {'nodes': [thread], 'pageInfo': {'hasNextPage': False, 'endCursor': None}}}}}}
        return GitHub(transport=transport), provider, state

    def test_resolve_only_owned_outdated_provider_thread_and_read_back(self):
        for lose_response in [False, True]:
            with self.subTest(lose_response=lose_response):
                gh, provider, state = self.thread_transport(lose_response=lose_response)
                result = gh.resolve_thread(REPO, 7, 'PRRT_known', HEAD, provider)
                self.assertTrue(result['isResolved']); self.assertEqual(state['mutations'], 1)
                gh.resolve_thread(REPO, 7, 'PRRT_known', HEAD, provider)
                self.assertEqual(state['mutations'], 1)

    def test_thread_resolution_preserves_current_human_foreign_unknown_threads(self):
        for kwargs in [{'outdated': False}, {'author': {'id': 8, 'login': 'human'}},
                       {'author': {'id': 8, 'login': 'chatgpt-codex-connector[bot]'}},
                       {'app': {'id': 999}}, {'human_reply': True}]:
            with self.subTest(kwargs=kwargs):
                gh, provider, state = self.thread_transport(**kwargs)
                with self.assertRaises(GitHubError): gh.resolve_thread(REPO, 7, 'PRRT_known', HEAD, provider)
                self.assertEqual(state['mutations'], 0)
        for tid, head in [('PRRT_foreign', HEAD), ('PRRT_known', BASE)]:
            gh, provider, state = self.thread_transport()
            with self.assertRaises(GitHubError): gh.resolve_thread(REPO, 7, tid, head, provider)
            self.assertEqual(state['mutations'], 0)

    def test_concurrent_head_or_comment_change_after_resolution_is_uncertain(self):
        for kwargs in [{'change_head': True}, {'extra_thread_comment': True}]:
            with self.subTest(kwargs=kwargs):
                gh, provider, state = self.thread_transport(**kwargs)
                with self.assertRaises(GitHubError) as caught: gh.resolve_thread(REPO, 7, 'PRRT_known', HEAD, provider)
                self.assertTrue(caught.exception.uncertain)
                self.assertEqual(state['mutations'], 1)

    def test_observe_collects_server_facts_and_thread_pagination(self):
        requests = []
        raw = {**owned_pr(), 'changed_files': 1, 'commits': 1}
        def transport(method, path, payload):
            requests.append((method, path, payload))
            if path == '/user': return IDENTITY
            if path == f'/repos/{REPO}': return REPOSITORY
            if path == f'/repos/{REPO}/pulls/7': return raw
            if '/git/ref/' in path: return {'object': {'sha': BASE}}
            if path == '/graphql':
                more = payload['variables']['cursor'] is None
                # Simulate GraphQL selection: omitted author fields must not be
                # supplied by a runner-shaped fixture and hide a query defect.
                comment = {'databaseId': 81}
                if 'nodes{databaseId author{login}}' in payload['query']:
                    comment['author'] = {'login': 'chatgpt-codex-connector[bot]'}
                thread = {'id': 'PRRT_provider', 'isResolved': False, 'isOutdated': True,
                          'comments': {'nodes': [comment], 'pageInfo': {'hasNextPage': False}}}
                return {'data': {'repository': {'pullRequest': {'reviewDecision': None, 'reviewThreads': {'nodes': [thread] if more else [], 'pageInfo': {'hasNextPage': more, 'endCursor': 'next' if more else None}}}}}}
            if '/check-runs?' in path: return {'check_runs': []}
            if '/actions/runs?' in path: return {'workflow_runs': []}
            if '/files?' in path: return [{'filename': 'src/main.py'}]
            if '/commits?' in path: return [{'sha': HEAD}]
            if '/rules/branches/' in path: return [{'type': 'non_fast_forward', 'ruleset_id': 8, 'ruleset_source': REPO, 'ruleset_source_type': 'Repository'}]
            if '/rulesets/' in path: return {'id': 8, 'enforcement': 'active', 'bypass_actors': []}
            return []
        got = GitHub(transport=transport).observe(REPO, 7)
        self.assertEqual(got['head_sha'], HEAD); self.assertEqual(got['base_sha'], BASE)
        self.assertEqual(got['changed_files'], [{'filename': 'src/main.py'}])
        self.assertEqual(got['commits'], [{'sha': HEAD}])
        self.assertEqual(got['threads'][0]['comments']['nodes'][0].get('author'),
                         {'login': 'chatgpt-codex-connector[bot]'})
        self.assertEqual(len([c for c in requests if c[1] == '/graphql']), 2)
        raw['changed_files'] = 2
        with self.assertRaises(GitHubError): GitHub(transport=transport).observe(REPO, 7)


if __name__ == '__main__':
    unittest.main()
