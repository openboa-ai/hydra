"""A merged policy change can finish only its already-owned delivery."""

import copy
import json
import unittest

from hydra_sdlc.github import GitHub as Client, GitHubError
from hydra_sdlc.project import ProjectError, load_project
from hydra_sdlc.runner import Runner, intake_digest
from test_project import BASE, BLOB, HEAD, MERGE, TOML, observation
from test_runner import GitHub


REPO = 'example/product'
CURRENT = 'e' * 40


class PolicyGitHub(GitHub):
    def __init__(self, current='changed'):
        super().__init__()
        self.current = current
        self.reads = []
        self.record_author = {'login': 'openboa', 'id': 11}
        self.pr = observation()['pr']
        self.pr.update(state='closed', merged=True, merge_commit_sha=MERGE,
                       body='<!-- hydra-pr:v1 {"repository_id":123,"issue_number":4} -->')
        self.branch = HEAD
        self.note = dict(version=1, repository_id=123, issue_number=4,
                         attempt_id='12345678-1234-1234-1234-123456789abc', host_alias='host-a',
                         contract_revision=BASE, spec_revision=HEAD, head=HEAD,
                         branch='hydra/issue-4', pr_number=7, phase='observing',
                         pending_action=None, expected_head=HEAD, expected_base=BASE,
                         checkpoint='squash_' + MERGE, intake_digest=intake_digest(self.work))

    def api(self, method, path):
        return {'user': {'login': path.split('/')[-2]}, 'permission': 'write'}

    def repository(self, repo):
        return {'id': 123, 'default_branch': 'main', 'full_name': repo}

    def ref(self, repo, branch):
        return CURRENT if branch == 'main' else self.branch

    def file(self, repo, path, revision):
        self.reads.append((path, revision))
        if revision == BASE:
            return {'content': TOML, 'sha': BLOB}
        if self.current == 'missing':
            raise GitHubError('Missing project file', status=404)
        if self.current == 'renamed_controls':
            return {'content': TOML.replace('hydra:ready', 'work:ready').replace(
                'hydra:paused', 'work:paused').replace('hydra:decision', 'work:decision'), 'sha': 'f' * 40}
        return {'content': 'invalid = [' if self.current == 'invalid' else
                TOML.replace('job = "Unit tests"', 'job = "New policy check"'), 'sha': 'f' * 40}

    def progress(self, repo, number):
        # Exercise actual author/marker validation rather than granting ownership
        # from the fixture's presence alone.
        def transport(method, path, payload):
            if path == '/user':
                return {'id': 11, 'login': 'openboa'}
            if '/comments?' in path:
                return [] if self.note is None else [{'id': 77, 'user': self.record_author,
                    'body': '<!-- hydra-progress:v1 ' + json.dumps(self.note) + ' -->'}]
            return self.repository(repo)
        return Client(transport=transport).progress(repo, number)


async def forbidden_model(*args, **kwargs):
    raise AssertionError('Completion must not start any SDK operation')


class PolicyCompletionTests(unittest.IsolatedAsyncioTestCase):
    def runner(self, github, *, stop=False):
        return Runner(github, None, host_alias='host-a', execute=forbidden_model,
                      capabilities=forbidden_model, stop_requested=lambda: stop)

    async def test_step_finishes_with_original_checks_after_changed_invalid_or_deleted_policy(self):
        for current in ['changed', 'invalid', 'missing']:
            with self.subTest(current=current):
                github = PolicyGitHub(current)
                result = await self.runner(github).step(REPO, 4)
                self.assertEqual(result['action'], 'completed')
                self.assertEqual(github.work['state'], 'closed')
                self.assertEqual(github.note['contract_revision'], BASE)
                self.assertIn(('.hydra.toml', BASE), github.reads)
                self.assertEqual([x for x in github.writes if x[0] != 'record'], [('close', 4)])

    async def test_serve_and_status_find_pending_completion_without_current_policy(self):
        for current in ['changed', 'invalid', 'missing']:
            for closed in [False, True]:
                with self.subTest(current=current, closed=closed):
                    github = PolicyGitHub(current)
                    if closed:
                        github.work['state'] = 'closed'
                        github.note.update(pending_action='close_issue', phase='closing')
                    runner = self.runner(github)
                    self.assertEqual(runner.status([REPO])[0]['wait_reason'], 'completion_reconciliation')
                    self.assertEqual(github.writes, [])
                    self.assertEqual((await runner.cycle([REPO]))[0]['action'], 'completed')
                    effects = [x for x in github.writes if x[0] != 'record']
                    self.assertEqual(effects, [] if closed else [('close', 4)])

    async def test_old_policy_cannot_authorize_unmerged_foreign_or_wrong_head_work(self):
        for current in ['changed', 'invalid', 'missing']:
            for mutation in ['unmerged', 'foreign', 'stale_head', 'foreign_progress', 'multiple']:
                with self.subTest(current=current, mutation=mutation):
                    github = PolicyGitHub(current)
                    if mutation == 'unmerged':
                        github.pr.update(merged=False, state='open')
                    elif mutation == 'foreign':
                        github.pr['user']['login'] = 'another-writer'
                    elif mutation == 'stale_head':
                        github.note['head'] = '1' * 40
                    elif mutation == 'foreign_progress':
                        github.record_author = {'login': 'openboa', 'id': 999}
                    else:
                        github.pulls = lambda *args: [copy.deepcopy(github.pr), copy.deepcopy(github.pr)]
                    runner = self.runner(github)
                    try:
                        result = await runner.step(REPO, 4)
                        self.assertEqual(result['action'], 'waiting')
                    except (ProjectError, GitHubError):
                        self.assertIn(current, {'invalid', 'missing'})
                    self.assertFalse(any(x[0] in {'push', 'pr', 'merge', 'close'} for x in github.writes))
                    self.assertEqual(github.work['state'], 'open')

    async def test_current_issue_boundaries_hold_open_and_closed_completion(self):
        for closed in [False, True]:
            for boundary, expected in [('pause', 'paused'), ('decision', 'human_decision'),
                                       ('intake', 'intake_changed'), ('stop', 'stop_requested')]:
                with self.subTest(closed=closed, boundary=boundary):
                    github = PolicyGitHub('missing')
                    if closed:
                        github.work['state'] = 'closed'
                        github.note.update(pending_action='close_issue', phase='closing')
                    if boundary in {'pause', 'decision'}:
                        label = 'hydra:paused' if boundary == 'pause' else 'hydra:decision'
                        github.work['labels'].append({'name': label})
                    elif boundary == 'intake':
                        github.work['body'] += '\nChanged goal'
                    original = copy.deepcopy(github.note)
                    runner = self.runner(github, stop=boundary == 'stop')
                    self.assertEqual((await runner.step(REPO, 4))['reason'], expected)
                    self.assertEqual(runner.status([REPO])[0]['wait_reason'], expected)
                    self.assertEqual(await runner.cycle([REPO]), [])
                    self.assertEqual(github.note, original)
                    self.assertEqual(github.writes, [])

    async def test_pause_arriving_during_post_merge_check_preserves_pending_close(self):
        github = PolicyGitHub('invalid')
        github.work['state'] = 'closed'
        github.note.update(pending_action='close_issue', phase='closing')
        observe = github.observe_commit
        def pause(repo, sha):
            result = observe(repo, sha)
            github.work['labels'].append({'name': 'hydra:paused'})
            return result
        github.observe_commit = pause
        self.assertEqual((await self.runner(github).step(REPO, 4))['reason'], 'delivery_boundary_changed')
        self.assertEqual(github.note['pending_action'], 'close_issue')
        self.assertNotEqual(github.note['phase'], 'completed')
        self.assertFalse(any(x[0] == 'close' for x in github.writes))

    async def test_valid_new_control_names_can_stop_but_never_delegate_old_work(self):
        for labels, reason in [(['hydra:ready', 'work:paused'], 'paused'),
                               (['hydra:ready', 'work:decision'], 'human_decision'),
                               (['hydra:ready', 'hydra:paused'], 'paused'),
                               (['hydra:ready', 'hydra:decision'], 'human_decision'),
                               (['work:ready'], 'not_delegated')]:
            with self.subTest(labels=labels):
                github = PolicyGitHub('renamed_controls')
                github.work['labels'] = [{'name': name} for name in labels]
                runner = self.runner(github)
                self.assertEqual((await runner.step(REPO, 4))['reason'], reason)
                self.assertEqual(runner.status([REPO])[0]['wait_reason'], reason)
                self.assertEqual(await runner.cycle([REPO]), [])
                self.assertEqual(github.writes, [])

    async def test_post_merge_failure_still_waits_on_original_required_check(self):
        github = PolicyGitHub('missing')
        observe = github.observe_commit
        def failed(repo, sha):
            result = observe(repo, sha)
            result['checks'][0]['conclusion'] = 'failure'
            return result
        github.observe_commit = failed
        self.assertEqual((await self.runner(github).step(REPO, 4))['reason'], 'post_merge_checks')
        self.assertFalse(any(x[0] == 'close' for x in github.writes))
        github.observe_commit = observe
        self.assertEqual((await self.runner(github).step(REPO, 4))['action'], 'completed')

    def test_pinned_loader_reads_only_explicit_exact_revision(self):
        github = PolicyGitHub('invalid')
        self.assertEqual(load_project(github, REPO, revision=BASE)['revision'], BASE)
        self.assertEqual(github.reads, [('.hydra.toml', BASE)])
        with self.assertRaises(ProjectError):
            load_project(github, REPO, revision='main')
        self.assertEqual(github.reads, [('.hydra.toml', BASE)])


if __name__ == '__main__':
    unittest.main()
