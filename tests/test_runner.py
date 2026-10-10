"""Workflow failures across restarts, with service facts independent of model claims."""

import asyncio
import copy
import os
import signal
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from hydra_sdlc.runner import Runner, usage_allowed
from test_project import BASE, HEAD, MERGE, config, observation, summary


class GitHub:
    user = "openboa"

    def __init__(self):
        self.cfg = config()
        self.work = {'number': 4, 'state': 'open', 'title': 'Document the development workflow',
                     'user': {'login': 'openboa'}, 'labels': [{'name': 'hydra:ready'}],
                     'body': '## Goal\nDescribe the supported workflow.\n## Scope\nDocumentation.\n'
                             '## Acceptance\nActual CLI examples.\n```hydra\nspec = "docs/engineering/task/spec.md"\n```'}
        self.note = None
        self.branch = None
        self.pr = None
        self.extra_comments = []
        self.writes = []
        self.remote_pending = False
        self.lose_pr = self.lose_merge = self.lose_publish = False
        self.on_record = lambda record: None
        self.transform_observation = lambda value: value
        self.closed_response_lost = False

    def issue(self, repo, n):
        return copy.deepcopy(self.work)

    def issues(self, repo):
        return [self.issue(repo, 4)]

    def file(self, repo, path, revision):
        return {'sha': self.cfg['blob_sha'], 'content': ''}

    def progress(self, repo, n):
        return copy.deepcopy(self.note)

    def record(self, repo, n, record):
        self.note = copy.deepcopy(record)
        self.note.update(version=1, issue_number=n, repository_id=self.cfg['repository_id'])
        self.writes.append(('record', record.get('pending_action')))
        self.on_record(record)

    def comments(self, repo, n):
        return copy.deepcopy(self.extra_comments)

    def ref(self, repo, branch):
        return self.branch

    def pulls(self, repo, branch):
        return [copy.deepcopy(self.pr)] if self.pr else []

    def ensure_pr(self, repo, n, branch, head, title, body):
        self.assert_intent('upsert_pr')
        self.writes.append(('pr', head))
        self.pr = observation()['pr']
        self.pr['body'] = f'<!-- hydra-pr:v1 {{"repository_id":{self.cfg["repository_id"]},"issue_number":{n}}} -->\n' + body
        for side in ('head', 'base'):
            self.pr[side]['repo']['id'] = self.cfg['repository_id']
        self.pr['head']['sha'] = head
        if self.lose_pr:
            self.lose_pr = False
            raise RuntimeError('response lost')
        return copy.deepcopy(self.pr)

    def owns_pr(self, repo, number, pr):
        from hydra_sdlc.github import GitHub as Client
        identity = self.cfg['repository_id']
        class Transport:
            def __call__(self, method, path, payload):
                if path == '/user':
                    return {'id': 11, 'login': 'openboa'}
                return {'id': identity, 'default_branch': 'main', 'full_name': repo}
        pr = copy.deepcopy(pr)
        pr['user']['id'] = 11
        return Client(transport=Transport()).owns_pr(repo, number, pr)

    def observe(self, repo, pr):
        value = observation()
        value['pr'] = copy.deepcopy(self.pr)
        head = value['pr']['head']['sha']
        value['head_sha'] = head
        value['commits'] = [{'sha': head}]
        value['provider_comments'][0]['body'] = summary(head)
        value['repository']['id'] = self.cfg['repository_id']
        value['provider_comments'][0]['body'] = value['provider_comments'][0]['body'].replace('example/product', repo)
        for c in value['checks']:
            c['head_sha'] = head
        for r in value['runs']:
            r['repository']['id'] = self.cfg['repository_id']
            for side in ('head', 'base'):
                r['pull_requests'][0][side]['repo']['id'] = self.cfg['repository_id']
            r['head_sha'] = head
            r['pull_requests'][0]['head']['sha'] = head
            r['jobs'][0]['head_sha'] = head
            r['jobs'][0]['check_run_url'] = r['jobs'][0]['check_run_url'].replace('example/product', repo)
        if self.remote_pending:
            value['runs'][0]['status'] = 'in_progress'
        return self.transform_observation(value)

    def observe_commit(self, repo, sha):
        value = observation()
        value.pop('pr')
        value['head_sha'] = sha
        value['runs'][0].update(event='push', head_sha=sha, head_branch='main')
        value['runs'][0]['jobs'][0]['head_sha'] = sha
        value['checks'][0]['head_sha'] = sha
        value['repository']['id'] = self.cfg['repository_id']
        value['runs'][0]['repository']['id'] = self.cfg['repository_id']
        value['runs'][0]['jobs'][0]['check_run_url'] = value['runs'][0]['jobs'][0]['check_run_url'].replace('example/product', repo)
        return value

    def merge(self, repo, pr, head):
        self.assert_intent('merge')
        self.writes.append(('merge', head))
        self.pr.update(merged=True, state='closed', merge_commit_sha=MERGE)
        if self.lose_merge:
            self.lose_merge = False
            raise RuntimeError('response lost')

    def close_issue(self, repo, n):
        self.assert_intent('close_issue')
        self.writes.append(('close', n))
        self.work['state'] = 'closed'
        if self.closed_response_lost:
            raise RuntimeError('response lost')

    def request_review(self, *args, **kwargs):
        self.assert_intent('request_review')
        self.writes.append(('request_review', kwargs.get('kind', 'code'), kwargs['head']))

    def resolve_thread(self, repo, number, thread, head, provider):
        self.assert_intent('resolve_threads')
        self.writes.append(('resolve_thread', thread))

    def assert_intent(self, action):
        if self.note.get('pending_action') != action:
            raise AssertionError('External write happened without intention')


class Workspace:
    def __init__(self, directory, github):
        self.path = Path(directory)
        self.gh = github
        self.head = BASE
        self.dirty = False
        spec = self.path / 'docs/engineering/task/spec.md'
        spec.parent.mkdir(parents=True)
        spec.write_text('Requirement-linked specification')
        self.verification_calls = 0
        self.publish_failures = 0
        self.fetch_calls = 0

    def prepare(self, *args):
        return self.path

    def inspect(self, path):
        return {'head': self.head, 'dirty': self.dirty, 'branch': 'hydra/issue-4'}

    def changed_paths(self, path, base):
        return ['src/main.py']

    def checkpoint(self, path, message):
        if self.dirty:
            self.head = HEAD if self.head == BASE else 'f' * 40
            self.dirty = False
        return self.head

    def verify(self, path, commands):
        self.verification_calls += 1
        return [{'passed': True, 'exit_code': 0, 'argv': ['true'], 'cwd': '.', 'output_digest': 'e' * 64}]

    def verification_output(self, digest):
        return ''

    def publish(self, path, branch, expected):
        self.gh.assert_intent('publish')
        self.gh.writes.append(('push', self.head))
        if self.publish_failures:
            self.publish_failures -= 1
            raise RuntimeError('not submitted')
        self.gh.branch = self.head
        if self.gh.lose_publish:
            self.gh.lose_publish = False
            raise RuntimeError('response lost')
        return self.head

    def fetch_base(self, *args):
        self.fetch_calls += 1


class RunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.github = GitHub()
        self.workspace = Workspace(self.directory.name, self.github)
        self.calls = []
        self.stop = False
        self.patch = patch('hydra_sdlc.runner.load_project', side_effect=lambda gh, repo: copy.deepcopy(gh.cfg))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    async def execute(self, assignment, **kwargs):
        from hydra_sdlc.codex import _assignment_options
        _assignment_options(assignment)  # Real adapter scope validation must precede the fixture result.
        self.calls.append(assignment['mode'])
        if assignment['mode'] == 'workspace_write':
            self.workspace.dirty = True
        return {'status': 'completed', 'detail': {'result': {'outcome': 'candidate_ready', 'summary': '', 'evidence': [], 'next_action': ''}}}

    async def capabilities(self, cwd):
        return {'usage': {'status': 'known', 'data': {'rateLimits': {'primary': {'usedPercent': 10}}}}}

    def runner(self, host='host-a'):
        return Runner(self.github, self.workspace, host_alias=host, execute=self.execute,
                      capabilities=self.capabilities, stop_requested=lambda: self.stop)

    async def publish(self):
        runner = self.runner()
        self.assertEqual((await runner.step('example/product', 4))['action'], 'continue')
        return runner

    async def test_delivery_lost_responses_and_restart(self):
        self.github.lose_pr = self.github.lose_publish = self.github.lose_merge = True
        runner = await self.publish()
        self.assertEqual((await runner.step('example/product', 4))['action'], 'continue')
        # Fresh instance has no prior transcript, accepted-spec cache or verification memory.
        self.assertEqual((await self.runner().step('example/product', 4))['action'], 'completed')
        for effect in ['push', 'pr', 'merge', 'close']:
            self.assertEqual(len([x for x in self.github.writes if x[0] == effect]), 1)
        self.assertEqual(self.github.work['state'], 'closed')

    async def test_unchanged_remote_wait_restart_never_wakes_model(self):
        self.github.remote_pending = True
        runner = await self.publish()
        self.assertEqual((await runner.step('example/product', 4))['reason'], 'remote_delivery_gates')
        count = len(self.calls)
        writes = len(self.github.writes)
        for _ in range(3):
            self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'remote_delivery_gates')
        self.assertEqual(len(self.calls), count)
        self.assertEqual(len([x for x in self.github.writes[writes:] if x[0] in {'push', 'pr', 'merge'}]), 0)

    async def test_foreign_branch_is_never_adopted(self):
        self.github.branch = HEAD
        self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'foreign_branch')
        self.assertEqual(self.calls, [])

    async def test_late_worker_and_foreign_host_need_explicit_stopped_handover(self):
        await self.publish()
        self.github.note.update(phase='executing', pending_action='implementation')
        self.assertEqual((await self.runner('host-b').step('example/product', 4))['reason'], 'confirm_previous_stopped')
        self.assertEqual(len(self.calls), 2)

    async def test_stopped_handover_reuses_published_work(self):
        self.github.remote_pending = True
        runner = await self.publish()
        await runner.step('example/product', 4)
        self.github.extra_comments.append({'user': {'login': 'operator'},
            'body': f"hydra: handover {self.github.note['attempt_id']} stopped"})
        count = len(self.calls)
        self.assertEqual((await self.runner('host-b').step('example/product', 4))['reason'], 'remote_delivery_gates')
        self.assertEqual(len(self.calls), count)

    async def test_pause_or_stop_after_intent_prevents_delivery(self):
        runner = await self.publish()
        self.github.on_record = lambda record: setattr(self, 'stop', True) if record.get('pending_action') == 'upsert_pr' else None
        await runner.step('example/product', 4)
        self.assertFalse(any(x[0] == 'pr' for x in self.github.writes))

    async def test_decision_wait_does_not_dispatch_again(self):
        await self.publish()
        self.github.note.update(wait_reason='product_decision', phase='waiting')
        count = len(self.calls)
        self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'product_decision')
        self.assertEqual(len(self.calls), count)

    async def test_partial_review_requests_only_missing_security_once(self):
        self.github.remote_pending = True
        runner = await self.publish()
        await runner.step('example/product', 4)
        self.github.transform_observation = lambda v: {**v, 'provider_comments': [
            {**v['provider_comments'][0], 'body': '\n'.join(line for line in summary().splitlines()
             if '**Security Review**' not in line)}]}
        for _ in range(4):
            await self.runner().step('example/product', 4)
        self.assertEqual([x for x in self.github.writes if x[0] == 'request_review'],
                         [('request_review', 'security', HEAD)])

    async def test_publish_retry_budget_survives_new_review_and_restart(self):
        runner = await self.publish()
        self.workspace.publish_failures = 8
        for _ in range(4):
            result = await self.runner().step('example/product', 4)
        self.assertEqual(result['reason'], 'service_retry_or_stop_boundary')
        self.assertEqual(len([x for x in self.github.writes if x[0] == 'push']), 3)
        self.assertIsNone(self.github.pr)

    async def test_correction_publish_retry_reconciles_old_pr_head(self):
        self.github.remote_pending = True
        runner = await self.publish()
        await runner.step('example/product', 4)
        self.workspace.head = 'f' * 40
        self.github.note.update(head='f' * 40, expected_head=HEAD, phase='implementation_done')
        self.workspace.publish_failures = 1
        result = await self.runner().step('example/product', 4)
        self.assertEqual(result['reason'], 'publish_unknown')
        result = await self.runner().step('example/product', 4)
        self.assertNotEqual(result.get('reason'), 'remote_head_changed')
        self.assertEqual(self.github.branch, 'f' * 40)

    async def test_pending_publish_reconciles_before_low_usage_can_erase_intent(self):
        self.github.remote_pending = True
        runner = await self.publish()
        await runner.step('example/product', 4)
        self.workspace.head = 'f' * 40
        self.github.note.update(head='f' * 40, expected_head=HEAD, pending_action='publish',
                                phase='uncertain', delivery_action='publish', delivery_attempt=1,
                                delivery_head='f' * 40)
        self.workspace.publish_failures = 1
        async def low_usage(cwd):
            return {'usage': {'status': 'unknown'}}
        runner = self.runner()
        runner.capabilities = low_usage
        self.assertEqual((await runner.step('example/product', 4))['reason'], 'publish_unknown')
        self.assertEqual(self.github.note['pending_action'], 'publish')
        count = len(self.calls)
        self.assertEqual((await runner.step('example/product', 4))['action'], 'continue')
        self.assertEqual(len(self.calls), count)
        self.assertEqual(self.github.branch, 'f' * 40)

    async def test_stop_during_pending_publish_preserves_external_intent(self):
        runner = await self.publish()
        record = {**self.github.note, 'head': HEAD, 'pending_action': 'publish', 'expected_head': None}
        self.stop = True
        runner._publish('example/product', 4, self.github.cfg, record, self.workspace.path, HEAD)
        self.assertEqual(self.github.note['pending_action'], 'publish')
        self.assertEqual(self.github.note['expected_head'], None)
        self.assertFalse(any(x[0] == 'push' for x in self.github.writes))

    async def test_single_issue_command_keeps_waiting_for_ci_until_deadline(self):
        from hydra_sdlc.cli import operate, parser
        self.github.remote_pending = True
        runner = await self.publish()
        await runner.step('example/product', 4)
        args = parser().parse_args(['run', '--issue', 'https://github.com/example/product/issues/4',
                                  '--workspace-root', self.directory.name, '--host-alias', 'host-a',
                                  '--lock-path', str(Path(self.directory.name) / 'host.lock'), '--timeout', '0.03'])
        before = len(self.calls)
        with patch('hydra_sdlc.cli.residual_workers', return_value=[]):
            result = await operate(args, github=self.github, workspace=self.workspace,
                                   execute=self.execute, capabilities=self.capabilities, emit=lambda _: None)
        self.assertEqual(result['action'], 'stopped')
        self.assertEqual(len(self.calls), before)

    async def test_successful_code_retry_leaves_security_request_its_own_budget(self):
        self.github.remote_pending = True
        runner = await self.publish()
        await runner.step('example/product', 4)
        self.github.transform_observation = lambda v: {**v, 'provider_comments': []}
        self.github.note.update(checkpoint='await_auto_review', delivery_action='request_review',
                                delivery_attempt=2, delivery_head=HEAD)
        await self.runner().step('example/product', 4)
        self.assertEqual([x[1] for x in self.github.writes if x[0] == 'request_review'], ['code', 'security'])

    async def test_behind_pr_integrates_once_before_publishing(self):
        self.github.remote_pending = True
        runner = await self.publish()
        await runner.step('example/product', 4)
        def behind(value):
            value['pr']['mergeable_state'] = 'behind'
            return value
        self.github.transform_observation = behind
        self.assertEqual((await self.runner().step('example/product', 4))['action'], 'continue')
        self.assertEqual(self.workspace.fetch_calls, 1)
        await self.runner().step('example/product', 4)
        self.assertEqual(self.workspace.fetch_calls, 1)
        self.assertEqual(self.github.branch, 'f' * 40)

    async def test_failed_ci_dispatches_correction(self):
        self.github.remote_pending = True
        runner = await self.publish()
        await runner.step('example/product', 4)
        def failed(value):
            value['checks'][0]['conclusion'] = 'failure'
            return value
        self.github.transform_observation = failed
        before = len(self.calls)
        result = await self.runner().step('example/product', 4)
        self.assertEqual(result['action'], 'continue')
        self.assertEqual(self.calls[before:], ['read_only', 'read_only', 'workspace_write'])

    async def test_completed_thread_resolution_does_not_consume_next_threads_budget(self):
        self.github.remote_pending = True
        runner = await self.publish()
        self.github.transform_observation = lambda v: {**v, 'threads': [
            {'id': str(i), 'isOutdated': True, 'isResolved': False, 'comments': {'nodes': [
             {'author': {'login': self.github.cfg['review_provider']['login']}}]}} for i in range(4)]}
        await runner.step('example/product', 4)
        self.assertEqual(len([x for x in self.github.writes if x[0] == 'resolve_thread']), 4)

    async def test_known_closed_issue_is_not_closed_again_after_lost_response(self):
        runner = await self.publish()
        await runner.step('example/product', 4)
        self.github.note.update(pending_action='close_issue', phase='closing')
        self.github.work['state'] = 'closed'
        self.assertEqual((await self.runner().step('example/product', 4))['action'], 'completed')
        self.assertFalse(any(x[0] == 'close' for x in self.github.writes))

    async def test_replan_starts_new_attempt_and_resets_failure_budget(self):
        await self.publish()
        old = self.github.note['attempt_id']
        self.github.note.update(wait_reason='replan_required', checkpoint='correction_3_verification_failure',
                                delivery_action='publish', delivery_attempt=3, delivery_head=HEAD)
        self.github.extra_comments.append({'user': {'login': 'operator'},
                                          'body': f'hydra: replan {old} ready'})
        await self.runner().step('example/product', 4)
        self.assertNotEqual(self.github.note['attempt_id'], old)
        self.assertIsNone(self.github.note['checkpoint'])

    async def test_signal_received_during_blocking_intent_prevents_merge(self):
        from hydra_sdlc.cli import operate, parser
        runner = await self.publish()
        self.github.remote_pending = True
        await runner.step('example/product', 4)
        self.github.remote_pending = False
        self.github.on_record = lambda record: os.kill(os.getpid(), signal.SIGTERM) if record.get('pending_action') == 'merge' else None
        args = parser().parse_args(['run', '--issue', 'https://github.com/example/product/issues/4',
                                  '--workspace-root', self.directory.name, '--host-alias', 'host-a',
                                  '--lock-path', str(Path(self.directory.name) / 'host.lock')])
        with patch('hydra_sdlc.cli.residual_workers', return_value=[]):
            await operate(args, github=self.github, workspace=self.workspace,
                          execute=self.execute, capabilities=self.capabilities, emit=lambda _: None)
        self.assertFalse(any(x[0] == 'merge' for x in self.github.writes))

    async def test_different_registered_projects_share_loop_and_decision_wait_releases_capacity(self):
        first, second = self.github, GitHub()
        second.cfg.update(repository='example/another', repository_id=456)
        class Router:
            def __getattr__(self, name):
                return lambda repo, *args, **kwargs: getattr(first if repo == 'example/product' else second, name)(repo, *args, **kwargs)
        router = Router()
        path = Path(self.directory.name) / 'second'
        path.mkdir()
        workspace2 = Workspace(path, second)
        class Workspaces:
            def prepare(self, repo, *args):
                return (self_outer.workspace if repo == 'example/product' else workspace2).prepare(repo, *args)
            def __getattr__(self, name):
                return lambda path, *args: getattr(self_outer.workspace if Path(path) == self_outer.workspace.path else workspace2, name)(path, *args)
        self_outer = self
        async def execute(assignment, **kwargs):
            if assignment['mode'] == 'workspace_write':
                (self.workspace if Path(assignment['cwd']) == self.workspace.path else workspace2).dirty = True
            return {'status': 'completed', 'detail': {'result': {'outcome': 'candidate_ready'}}}
        with patch('hydra_sdlc.runner.load_project', side_effect=lambda gh, repo: copy.deepcopy(first.cfg if repo == 'example/product' else second.cfg)):
            runner = Runner(router, Workspaces(), host_alias='host-a', execute=execute, capabilities=self.capabilities)
            first.extra_comments = []
            await runner.step('example/product', 4)
            first.note.update(wait_reason='product_decision', phase='waiting')
            result = await runner.cycle(['example/product', 'example/another'])
            self.assertEqual(result[0]['reason'], 'product_decision')
            self.assertEqual(result[1]['action'], 'continue')
            self.assertEqual(second.note['phase'], 'implementation_done')
            first.extra_comments.append({'user': {'login': 'operator'}, 'body': f"hydra: decision {first.note['attempt_id']} resolved"})
            # Different repository values are passed through the same Runner, not project-specific execution branches.
            for _ in range(3):
                await runner.cycle(['example/product', 'example/another'])
            self.assertEqual(first.work['state'], 'closed')
            self.assertEqual(second.work['state'], 'closed')

    def test_usage_threshold_and_unknown_windows(self):
        self.assertFalse(usage_allowed({'usage': {'status': 'unknown'}}))
        self.assertTrue(usage_allowed({'usage': {'status': 'known', 'data': {'rateLimits': {'primary': {'usedPercent': 80}}}}}))
        self.assertFalse(usage_allowed({'usage': {'status': 'known', 'data': {'rateLimits': {'primary': {'usedPercent': 81}}}}}))


if __name__ == '__main__':
    unittest.main()
