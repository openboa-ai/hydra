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


def complete_capabilities(used=10, *, allowed=True):
    from hydra_sdlc.codex import SDK_VERSION
    return {'available': True, 'sdk_version': SDK_VERSION, 'runtime_version': SDK_VERSION,
            'account': {'status': 'known', 'type': 'chatgpt', 'authenticated': True},
            'models': {'status': 'known', 'ids': ['configured-default']},
            'usage': {'status': 'known', 'data': {'ordinaryUsageAllowed': allowed,
                      'rateLimits': {'primary': {'usedPercent': used}}}}}


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
        self.merge_message = "External merge without a service request"

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
        if value['pr'].get('merged'):
            tree = {'sha': 'd' * 40}
            value['head_commit'] = {'sha': head, 'tree': tree}
            value['merge_commit'] = {'sha': value['pr']['merge_commit_sha'], 'tree': tree,
                                     'parents': [{'sha': BASE}], 'message': self.merge_message}
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

    def merge(self, repo, pr, head, *, commit_message):
        self.assert_intent('merge')
        self.writes.append(('merge', head))
        self.merge_message = commit_message
        self.pr.update(merged=True, state='closed', merge_commit_sha=MERGE)
        if self.lose_merge:
            self.lose_merge = False
            raise RuntimeError('response lost')
        return copy.deepcopy(self.pr)

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
        spec.parent.mkdir(parents=True, exist_ok=True)
        spec.write_text('Requirement-linked specification')
        self.verification_calls = 0
        self.publish_failures = 0
        self.fetch_calls = 0
        self.prepared_recovery = []

    def prepare(self, *args, recover_dirty=False):
        self.prepared_recovery.append(recover_dirty)
        if self.dirty and not recover_dirty:
            raise RuntimeError('Owned workspace has unreviewed edits')
        return self.path

    def inspect(self, path):
        return {'head': self.head, 'dirty': self.dirty, 'branch': 'hydra/issue-4'}

    def changed_paths(self, path, base):
        return ['src/main.py']

    def checkpoint(self, path, message):
        if self.dirty:
            self.head = HEAD if self.head == BASE else ('e' if self.head == 'f' * 40 else 'f') * 40
            self.dirty = False
        return self.head

    def verify(self, path, commands, *, stop_requested=lambda: False):
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
        if self.gh.pr:
            self.gh.pr['head']['sha'] = self.head
        if self.gh.lose_publish:
            self.gh.lose_publish = False
            raise RuntimeError('response lost')
        return self.head

    def fetch_base(self, *args):
        self.fetch_calls += 1

    def contains_base(self, path, sha):
        return True

    def valid_spec(self, path, relative, *, require_tracked=True):
        candidate = Path(path) / relative
        return not candidate.is_symlink() and candidate.is_file() and candidate.stat().st_size > 0

    def read_spec(self, path, relative):
        return (Path(path) / relative).read_bytes()


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
        return complete_capabilities()

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

    async def test_changed_goal_holds_old_candidate_after_restart(self):
        self.github.remote_pending = True
        runner = await self.publish()
        await runner.step('example/product', 4)
        digest = self.github.note['intake_digest']
        self.github.work['body'] += '\nDifferent acceptance after delegation.'
        self.github.remote_pending = False
        before = len(self.calls)
        self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'intake_changed')
        self.assertEqual(self.github.note['intake_digest'], digest)
        self.assertEqual(len(self.calls), before)
        self.assertFalse(any(x[0] in {'merge', 'close'} for x in self.github.writes))

    async def test_intake_change_during_intent_blocks_external_write_and_preserves_intent(self):
        runner = await self.publish()
        self.github.on_record = lambda r: self.github.work.update(title='Changed delegated goal') if r.get('pending_action') == 'publish' else None
        await runner.step('example/product', 4)
        self.assertEqual(self.github.note['pending_action'], 'publish')
        self.assertFalse(any(x[0] == 'push' for x in self.github.writes))
        self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'intake_changed')
        self.assertEqual(self.github.note['pending_action'], 'publish')

    async def test_unbound_existing_attempt_is_observed_without_adoption(self):
        await self.publish()
        self.github.note.pop('intake_digest')
        count = len(self.calls)
        self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'intake_unbound')
        self.assertEqual(len(self.calls), count)

    async def test_restored_intake_preserves_existing_execution_and_decision_waits(self):
        await self.publish()
        original = self.github.work['body']
        for phase, reason, expected in [('implementation_done', 'product_decision', 'product_decision'),
                                         ('executing', None, 'confirm_previous_stopped'),
                                         ('waiting', 'replan_required', 'replan_required')]:
            with self.subTest(phase=phase, reason=reason):
                self.github.note.update(phase=phase, wait_reason=reason, pending_action='correction')
                record = copy.deepcopy(self.github.note)
                self.github.work['body'] = original + '\nChanged acceptance.'
                self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'intake_changed')
                self.assertEqual(self.github.note, record)
                self.github.work['body'] = original
                self.assertEqual((await self.runner().step('example/product', 4))['reason'], expected)

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
        self.assertEqual(result['reason'], 'replan_required')
        self.assertEqual(self.github.note['wait_reason'], 'replan_required')
        self.assertEqual(self.github.note['pending_action'], 'publish')
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
                                delivery_attempt=2, delivery_head=HEAD, pending_review_kind='code')
        attempts = []
        self.github.on_record = lambda record: attempts.append((record['pending_review_kind'], record['delivery_attempt'])) if record.get('pending_action') == 'request_review' else None
        await self.runner().step('example/product', 4)
        self.assertEqual([x[1] for x in self.github.writes if x[0] == 'request_review'], ['code', 'security'])
        self.assertEqual(attempts, [('code', 3), ('security', 1)])

    async def test_behind_pr_integrates_once_before_publishing(self):
        self.github.remote_pending = True
        runner = await self.publish()
        await runner.step('example/product', 4)
        def behind(value):
            value['pr']['mergeable_state'] = 'behind'
            return value
        self.github.transform_observation = behind
        self.assertEqual((await self.runner().step('example/product', 4))['action'], 'continue')
        count = self.workspace.fetch_calls
        await self.runner().step('example/product', 4)
        self.assertEqual(self.workspace.fetch_calls, count + 1)
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

    async def test_actual_inline_finding_body_reaches_private_correction_prompt(self):
        self.github.remote_pending = True
        runner = await self.publish()
        await runner.step('example/product', 4)
        def finding(value):
            value['threads'] = [{'id': 'thread-1', 'isResolved': False, 'isOutdated': False,
                                 'comments': {'nodes': [{'databaseId': 77,
                                     'author': {'login': 'chatgpt-codex-connector'}}]}}]
            value['inline_comments'] = [{'id': 77, 'body': 'Reconcile missing main object before diff',
                                         'path': 'src/main.py', 'line': 42, 'diff_hunk': '@@ example @@'}]
            return value
        self.github.transform_observation = finding
        prompts = []
        async def execute(assignment, **kwargs):
            prompts.append(assignment['prompt'])
            return await self.execute(assignment, **kwargs)
        runner = self.runner()
        runner.execute = execute
        self.assertEqual((await runner.step('example/product', 4))['action'], 'continue')
        self.assertIn('Reconcile missing main object before diff', prompts[-1])
        self.assertIn('src/main.py', prompts[-1])
        self.assertIn('42', prompts[-1])

    async def test_correction_budget_survives_publication_and_restart(self):
        self.github.remote_pending = True
        runner = await self.publish()
        await runner.step('example/product', 4)
        def failed(value):
            value['checks'][0]['conclusion'] = 'failure'
            return value
        self.github.transform_observation = failed
        for attempt in [1, 2]:
            self.assertEqual((await self.runner().step('example/product', 4))['action'], 'continue')
            self.assertEqual(self.github.note['correction_attempt'], attempt)
            self.github.note.update(checkpoint='await_auto_review')
        count = len(self.calls)
        self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'replan_required')
        self.assertEqual(len(self.calls), count + 2)  # Read-only recheck; no third correction.

    async def test_usage_wait_never_consumes_an_undispatched_correction(self):
        self.github.remote_pending = True
        runner = await self.publish()
        await runner.step('example/product', 4)
        def failed(value):
            value['checks'][0]['conclusion'] = 'failure'
            return value
        self.github.transform_observation = failed
        async def low_usage(cwd):
            return complete_capabilities(81, allowed=False)
        runner.capabilities = low_usage
        count = len(self.calls)
        for _ in range(4):
            self.assertEqual((await runner.step('example/product', 4))['reason'], 'usage_unavailable_or_low')
            self.assertIsNone(self.github.note.get('correction_attempt'))
        self.assertEqual(len(self.calls), count)
        runner.capabilities = self.capabilities
        self.assertEqual((await runner.step('example/product', 4))['action'], 'continue')
        self.assertEqual(self.github.note['correction_attempt'], 1)
        self.assertEqual(len(self.calls), count + 1)

    async def test_completed_thread_resolution_does_not_consume_next_threads_budget(self):
        self.github.remote_pending = True
        runner = await self.publish()
        self.github.transform_observation = lambda v: {**v, 'threads': [
            {'id': str(i), 'isOutdated': True, 'isResolved': False, 'comments': {'nodes': [
             {'author': {'login': self.github.cfg['review_provider']['login']}}]}} for i in range(4)]}
        await runner.step('example/product', 4)
        self.assertEqual(len([x for x in self.github.writes if x[0] == 'resolve_thread']), 4)

    async def test_unknown_thread_author_holds_resolution_without_crashing_loop(self):
        self.github.remote_pending = True
        runner = await self.publish()
        self.github.transform_observation = lambda v: {**v, 'threads': [
            {'id': 'unknown-author', 'isOutdated': True, 'isResolved': False,
             'comments': {'nodes': [{'databaseId': 77, 'author': None}]}}]}
        self.assertEqual((await runner.step('example/product', 4))['reason'], 'remote_delivery_gates')
        self.assertFalse(any(x[0] == 'resolve_thread' for x in self.github.writes))
        self.assertEqual((await self.runner().cycle(['example/product']))[0]['reason'], 'remote_delivery_gates')

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

    async def test_replan_of_unchanged_candidate_really_dispatches_implementation(self):
        runner = self.runner()
        config = {**self.github.cfg}
        record = dict(attempt_id='12345678-1234-1234-1234-123456789abc', host_alias='host-a',
                      contract_revision=BASE, spec_revision=None, head=BASE,
                      branch='hydra/issue-4', phase='waiting', pending_action=None,
                      wait_reason='replan_required')
        from hydra_sdlc.runner import intake_digest
        record['intake_digest'] = intake_digest(self.github.work)
        self.github.record('example/product', 4, record)
        self.github.extra_comments.append({'user': {'login': 'operator'},
            'body': f"hydra: replan {record['attempt_id']} ready"})
        self.assertEqual((await runner.step('example/product', 4))['action'], 'continue')
        self.assertEqual(self.calls, ['read_only', 'workspace_write'])
        self.assertEqual(self.workspace.head, HEAD)
        self.assertEqual(self.github.note['phase'], 'implementation_done')
        self.assertFalse(any(x[0] in {'push', 'pr', 'merge'} for x in self.github.writes))

    async def test_decision_resumes_owned_partial_implementation_and_correction(self):
        for phase in ['implementation', 'correction']:
            with self.subTest(phase=phase):
                self.github = GitHub()
                self.workspace = Workspace(self.directory.name, self.github)
                self.calls.clear()
                runner = await self.publish()
                config = {**self.github.cfg, 'intake_digest': self.github.note['intake_digest']}
                async def needs_decision(assignment, **kwargs):
                    self.workspace.dirty = True
                    (self.workspace.path / 'partial.txt').write_text('preserved partial work')
                    return {'status': 'completed', 'detail': {'result': {'outcome': 'needs_decision'}}}
                runner.execute = needs_decision
                record = {**self.github.note, 'correction_reason': 'review_findings', 'correction_attempt': 1}
                _, result = await runner._model('example/product', 4, config, record,
                                               self.workspace.path, phase, 'Apply accepted requirement')
                self.assertEqual(result['reason'], 'product_decision')
                self.assertFalse(self.workspace.dirty)
                partial_head = self.workspace.head
                self.assertEqual(self.github.note['head'], partial_head)
                self.assertEqual(self.github.note['resume_phase'], phase)
                attempt = self.github.note['attempt_id']
                self.github.extra_comments += [{'user': {'login': 'operator'}, 'body': 'Choose the existing safe behavior.'},
                    {'user': None, 'body': f'hydra: decision {attempt} resolved'},
                    {'user': {'login': 'operator'}, 'body': f'hydra: decision {attempt} resolved'}]
                prompts = []
                async def resume(assignment, **kwargs):
                    prompts.append(assignment)
                    return await self.execute(assignment, **kwargs)
                resumed = self.runner()
                resumed.execute = resume
                self.assertEqual((await resumed.step('example/product', 4))['action'], 'continue')
                self.assertEqual(prompts[-1]['mode'], 'workspace_write')
                self.assertIn('Choose the existing safe behavior.', prompts[-1]['prompt'])
                self.assertNotEqual(self.workspace.head, partial_head)
                self.assertNotEqual(self.github.note['attempt_id'], attempt)
                self.assertIsNone(self.github.note['resume_phase'])
                self.assertEqual((self.workspace.path / 'partial.txt').read_text(), 'preserved partial work')
                self.assertFalse(any(x[0] in {'push', 'pr', 'merge'} for x in self.github.writes))

    async def test_decision_marker_does_not_resolve_a_later_question(self):
        runner = await self.publish()
        self.github.note.update(phase='waiting', wait_reason='product_decision', resume_phase='implementation')
        attempt = self.github.note['attempt_id']
        self.github.extra_comments.append({'user': {'login': 'operator'}, 'body': f'hydra: decision {attempt} resolved'})
        async def needs_decision(assignment, **kwargs):
            return {'status': 'completed', 'detail': {'result': {'outcome': 'needs_decision' if assignment['mode'] == 'workspace_write' else 'candidate_ready'}}}
        runner.execute = needs_decision
        self.assertEqual((await runner.step('example/product', 4))['reason'], 'product_decision')
        current = self.github.note['attempt_id']
        self.assertNotEqual(current, attempt)
        self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'product_decision')

    async def test_read_only_decision_resumes_review_before_delivery(self):
        runner = await self.publish()
        config = {**self.github.cfg, 'intake_digest': self.github.note['intake_digest']}
        async def needs_decision(assignment, **kwargs):
            return {'status': 'completed', 'detail': {'result': {'outcome': 'needs_decision'}}}
        runner.execute = needs_decision
        await runner._model('example/product', 4, config, self.github.note,
                            self.workspace.path, 'change_review', 'Review actual candidate')
        self.github.extra_comments.append({'user': {'login': 'operator'},
            'body': f"hydra: decision {self.github.note['attempt_id']} resolved"})
        self.calls.clear()
        self.github.remote_pending = True
        self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'remote_delivery_gates')
        self.assertEqual(self.calls, ['read_only', 'read_only'])
        self.assertEqual(self.workspace.verification_calls, 1)
        self.assertFalse(any(x[0] == 'merge' for x in self.github.writes))
        count = len(self.calls)
        self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'remote_delivery_gates')
        self.assertEqual(len(self.calls), count)

    async def test_partial_design_resumes_design_before_spec_acceptance(self):
        runner = await self.publish()
        self.github.note['spec_revision'] = None  # This fixture resumes initial, unaccepted design.
        self.workspace.changed_paths = lambda *args: ['docs/engineering/task/spec.md']
        config = {**self.github.cfg, 'intake_digest': self.github.note['intake_digest']}
        async def needs_decision(assignment, **kwargs):
            self.workspace.dirty = True
            return {'status': 'completed', 'detail': {'result': {'outcome': 'needs_decision'}}}
        runner.execute = needs_decision
        await runner._model('example/product', 4, config, self.github.note,
                            self.workspace.path, 'design', 'Complete only the scoped spec')
        self.github.extra_comments.append({'user': {'login': 'operator'},
            'body': f"hydra: decision {self.github.note['attempt_id']} resolved"})
        self.calls.clear()
        self.assertEqual((await self.runner().step('example/product', 4))['action'], 'continue')
        self.assertEqual(self.calls, ['workspace_write'])
        self.assertEqual(self.github.note['phase'], 'design_done')
        self.assertFalse(any(x[0] in {'push', 'pr', 'merge'} for x in self.github.writes))

    async def test_spec_only_design_and_correction_reject_sibling_edits(self):
        for correction in [False, True]:
            with self.subTest(correction=correction):
                self.github = GitHub()
                self.workspace = Workspace(self.directory.name, self.github)
                spec = self.workspace.path / 'docs/engineering/task/spec.md'
                if not correction:
                    spec.unlink()
                self.workspace.changed_paths = lambda *args: ['docs/engineering/task/spec.md', 'docs/engineering/unrelated/spec.md']
                async def create_spec(assignment, **kwargs):
                    if assignment['mode'] == 'workspace_write':
                        spec.write_text('Scoped requirement')
                        self.workspace.dirty = True
                    return {'status': 'completed', 'detail': {'result': {'outcome': 'failed' if assignment['mode'] == 'read_only' else 'candidate_ready'}}}
                runner = self.runner()
                runner.execute = create_spec
                self.assertEqual((await runner.step('example/product', 4))['reason'], 'implementation_before_design_acceptance')
                self.assertEqual(self.workspace.head, BASE)
                self.assertTrue(self.workspace.dirty)
                self.assertFalse(any(x[0] in {'push', 'pr', 'merge'} for x in self.github.writes))

    async def test_missing_unpublished_checkpoint_is_not_replaced_by_older_checkout(self):
        runner = await self.publish()
        # The base branch was published by this service before the newer local checkpoint.
        self.github.note.update(head=HEAD, expected_head=BASE, published_head=BASE, phase='implementation_done')
        self.github.branch = BASE
        self.workspace.head = BASE
        self.github.extra_comments.append({'user': {'login': 'operator'},
            'body': f"hydra: handover {self.github.note['attempt_id']} stopped"})
        self.calls.clear()
        self.assertEqual((await self.runner('host-b').step('example/product', 4))['reason'], 'unpublished_checkpoint_missing')
        self.assertEqual(self.github.note['head'], HEAD)
        self.assertEqual(self.calls, [])
        self.assertEqual(self.workspace.verification_calls, 0)
        self.assertFalse(any(x[0] in {'push', 'pr', 'merge'} for x in self.github.writes))

    async def test_low_usage_wait_preserves_unpublished_correction_for_later_verification(self):
        self.github.remote_pending = True
        runner = await self.publish()
        await runner.step('example/product', 4)
        self.workspace.head = 'f' * 40
        self.github.note.update(head='f' * 40, expected_head=HEAD, phase='implementation_done')
        runner = self.runner()
        async def low_usage(cwd):
            return complete_capabilities(81, allowed=False)
        runner.capabilities = low_usage
        self.assertEqual((await runner.step('example/product', 4))['reason'], 'usage_unavailable_or_low')
        self.assertEqual(self.github.note['head'], 'f' * 40)
        self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'remote_delivery_gates')
        self.assertEqual(self.github.branch, 'f' * 40)

    async def test_failed_correction_checkpoint_remains_available_to_replan(self):
        runner = await self.publish()
        config = {**self.github.cfg, 'intake_digest': self.github.note['intake_digest']}
        async def failed(assignment, **kwargs):
            self.workspace.dirty = True
            return {'status': 'completed', 'detail': {'result': {'outcome': 'failed'}}}
        runner.execute = failed
        self.assertEqual((await runner._correct('example/product', 4, config, self.github.note,
                            self.workspace.path, 'implementation_failure'))['reason'], 'replan_required')
        self.assertEqual(self.github.note['head'], self.workspace.head)
        self.github.extra_comments.append({'user': {'login': 'operator'},
            'body': f"hydra: replan {self.github.note['attempt_id']} ready"})
        self.calls.clear()
        self.assertEqual((await self.runner().step('example/product', 4))['action'], 'continue')
        self.assertIn('workspace_write', self.calls)

    async def test_successful_verification_output_is_private_review_input(self):
        runner = await self.publish()
        private_output = 'SKIPPED behavior receipt; warning private-test-account'
        self.workspace.verification_output = lambda digest: private_output + 'x' * 30000
        prompts = []
        async def capture(assignment, **kwargs):
            prompts.append(assignment['prompt'])
            return await self.execute(assignment, **kwargs)
        runner.execute = capture
        self.github.remote_pending = True
        await runner.step('example/product', 4)
        self.assertIn(private_output, prompts[-1])
        self.assertLess(len(prompts[-1]), 27000)
        self.assertNotIn(private_output, str(self.github.note))
        self.assertNotIn(private_output, self.github.pr['body'])

    async def test_exhausted_review_request_retries_wait_for_explicit_replan(self):
        self.github.remote_pending = True
        runner = await self.publish()
        await runner.step('example/product', 4)
        self.github.transform_observation = lambda v: {**v, 'provider_comments': []}
        calls = []
        def lost(*args, **kwargs):
            calls.append(kwargs['head'])
            raise RuntimeError('review request outcome unknown')
        self.github.request_review = lost
        self.github.note['checkpoint'] = 'await_auto_review'
        for _ in range(3):
            self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'review_request_unknown')
            self.assertEqual(self.github.note['pending_action'], 'request_review')
        self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'replan_required')
        self.assertEqual(self.github.note['next_action'], 'diagnose')
        self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'replan_required')
        self.assertEqual(len(calls), 3)
        self.github.extra_comments.append({'user': {'login': 'operator'},
            'body': f"hydra: replan {self.github.note['attempt_id']} ready"})
        before = len(self.calls)
        self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'review_request_unknown')
        self.assertEqual(len(calls), 4)
        self.assertEqual(self.github.note['pending_review_kind'], 'code')
        self.assertEqual(self.github.note['delivery_attempt'], 1)
        self.assertEqual(len(self.calls), before)

    async def test_cycle_and_status_recover_closed_pending_completion_without_model_or_close(self):
        runner = await self.publish()
        await runner.step('example/product', 4)
        self.github.note.update(pending_action='close_issue', phase='closing')
        self.github.work['state'] = 'closed'
        before = len(self.calls)
        restarted = self.runner()
        self.assertEqual(restarted.status(['example/product'])[0]['wait_reason'], 'completion_reconciliation')
        self.assertEqual((await restarted.cycle(['example/product']))[0]['action'], 'completed')
        self.assertEqual(self.github.note['phase'], 'completed')
        self.assertEqual(len(self.calls), before)
        self.assertFalse(any(x[0] == 'close' for x in self.github.writes))

    async def test_closed_completion_intent_survives_post_merge_wait_and_restart(self):
        runner = await self.publish()
        await runner.step('example/product', 4)
        self.github.note.update(pending_action='close_issue', phase='closing')
        self.github.work['state'] = 'closed'
        self.github.issues = lambda repo: [self.github.issue(repo, 4)] if self.github.note.get('pending_action') == 'close_issue' else []
        actual = self.github.observe_commit
        def pending(repo, sha):
            value = actual(repo, sha)
            value['runs'][0]['status'] = 'in_progress'
            return value
        self.github.observe_commit = pending
        before = len(self.calls)
        self.assertEqual((await self.runner().cycle(['example/product']))[0]['reason'], 'post_merge_checks')
        self.assertEqual(self.github.note['pending_action'], 'close_issue')
        self.assertEqual(self.runner().status(['example/product'])[0]['wait_reason'], 'completion_reconciliation')
        self.github.observe_commit = actual
        self.assertEqual((await self.runner().cycle(['example/product']))[0]['action'], 'completed')
        self.assertEqual(len(self.calls), before)
        self.assertFalse(any(x[0] == 'close' for x in self.github.writes))

    async def test_closed_completion_never_falls_through_to_implementation(self):
        runner = await self.publish()
        await runner.step('example/product', 4)
        self.github.note.update(pending_action='close_issue', phase='closing')
        self.github.work['state'] = 'closed'
        pr = copy.deepcopy(self.github.pr)
        before = len(self.calls), len(self.github.writes)
        for value, expected in [(None, 'completion_pr_unavailable'),
                                ({**pr, 'merged': False, 'state': 'open'}, 'completion_merge_unconfirmed')]:
            with self.subTest(reason=expected):
                self.github.pr = value
                self.assertEqual((await self.runner().cycle(['example/product']))[0]['reason'], expected)
                self.assertEqual(self.github.note['pending_action'], 'close_issue')
        self.assertEqual(len(self.calls), before[0])
        self.assertFalse(any(x[0] in {'push', 'pr', 'merge', 'close'} for x in self.github.writes[before[1]:]))

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
            def prepare(self, repo, *args, **kwargs):
                return (self_outer.workspace if repo == 'example/product' else workspace2).prepare(repo, *args, **kwargs)
            def __getattr__(self, name):
                return lambda path, *args, **kwargs: getattr(self_outer.workspace if Path(path) == self_outer.workspace.path else workspace2, name)(path, *args, **kwargs)
        self_outer = self
        async def execute(assignment, **kwargs):
            if assignment['mode'] == 'workspace_write':
                (self.workspace if Path(assignment['cwd']) == self.workspace.path else workspace2).dirty = True
            return {'status': 'completed', 'detail': {'result': {'outcome': 'candidate_ready'}}}
        with patch('hydra_sdlc.runner.load_project', side_effect=lambda gh, repo: copy.deepcopy(first.cfg if repo == 'example/product' else second.cfg)):
            runner = Runner(router, Workspaces(), host_alias='host-a', execute=execute, capabilities=self.capabilities)
            first.extra_comments = []
            await runner.step('example/product', 4)
            first.note.update(wait_reason='product_decision', phase='waiting', resume_phase='implementation')
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
        for value in [0, 80, 93, 100]:
            with self.subTest(allowed_percent=value):
                self.assertTrue(usage_allowed(complete_capabilities(value)))
        for value in [-1, 101, None, True, '10', float('nan'), float('inf')]:
            with self.subTest(invalid_percent=value):
                self.assertFalse(usage_allowed(complete_capabilities(value)))
        for value in [None, False, 1, 'true']:
            with self.subTest(ordinary_usage_allowed=value):
                caps = complete_capabilities(93)
                caps['usage']['data']['ordinaryUsageAllowed'] = value
                self.assertFalse(usage_allowed(caps))
        for value, allowed in [(None, True), (False, True), (True, False), (0, False), (1, False), ('false', False)]:
            with self.subTest(spend_control_reached=value):
                caps = complete_capabilities(100)
                caps['usage']['data']['rateLimits']['spendControlReached'] = value
                self.assertEqual(usage_allowed(caps), allowed)

    async def test_incomplete_capabilities_never_dispatch_worker(self):
        for field, value in [('available', False), ('cleanup', 'unknown'), ('sdk_version', None),
                             ('account', {'status': 'unknown'}), ('models', {'status': 'unknown'}),
                             ('models', {'status': 'known', 'ids': []})]:
            with self.subTest(field=field, value=value):
                async def incomplete(cwd):
                    return {**complete_capabilities(), field: value}
                runner = self.runner()
                runner.capabilities = incomplete
                self.assertEqual((await runner.step('example/product', 4))['reason'],
                                 'host_cleanup_unconfirmed' if field == 'cleanup' else 'usage_unavailable_or_low')
        self.assertEqual(self.calls, [])
        for value in [None, False]:
            caps = complete_capabilities()
            caps['usage']['data']['ordinaryUsageAllowed'] = value
            self.assertFalse(usage_allowed(caps))

    async def test_advanced_base_is_fetched_before_unpublished_diff(self):
        self.github.cfg['revision'] = 'a' * 40
        fetched = set()
        def fetch(path, sha):
            fetched.add(sha)
        def diff(path, sha):
            if sha not in fetched:
                raise RuntimeError('new main object is absent from local clone')
            return ['src/main.py']
        self.workspace.fetch_base = fetch
        self.workspace.changed_paths = diff
        self.assertEqual((await self.runner().step('example/product', 4))['action'], 'continue')
        self.assertEqual(fetched, {'a' * 40})

    async def test_advanced_base_is_integrated_before_unpublished_scope_check(self):
        runner = await self.publish()
        self.github.cfg['revision'] = 'a' * 40
        integrated = False
        self.workspace.contains_base = lambda path, sha: integrated
        self.workspace.changed_paths = lambda path, sha: ['src/main.py'] if integrated else ['upstream-only.txt', 'src/main.py']
        async def integrate(assignment, **kwargs):
            nonlocal integrated
            self.assertIn('a' * 40, assignment['prompt'])
            integrated = True
            self.workspace.dirty = True
            self.calls.append(assignment['mode'])
            return {'status': 'completed', 'detail': {'result': {'outcome': 'candidate_ready'}}}
        runner.execute = integrate
        self.calls.clear()
        self.assertEqual((await runner.step('example/product', 4))['action'], 'continue')
        self.assertEqual(self.github.note['correction_reason'], 'integration_changed')
        self.assertEqual(self.calls, ['workspace_write'])
        self.assertFalse(any(x[0] == 'push' for x in self.github.writes))
        runner.execute = self.execute
        self.assertEqual((await runner.step('example/product', 4))['action'], 'continue')
        self.assertEqual(len([x for x in self.github.writes if x[0] == 'push']), 1)

    async def test_pending_publish_uses_original_base_before_advanced_base_integration(self):
        runner = await self.publish()
        self.github.note.update(pending_action='publish', expected_head=None)
        self.github.cfg['revision'] = 'a' * 40
        self.workspace.contains_base = lambda *args: False
        bases = []
        def diff(path, base):
            bases.append(base)
            return ['src/main.py'] if base == BASE else ['upstream-only.txt']
        self.workspace.changed_paths = diff
        self.calls.clear()
        self.assertEqual((await runner.step('example/product', 4))['action'], 'continue')
        self.assertEqual(bases, [BASE])
        self.assertEqual(self.calls, [])
        self.assertEqual(self.github.branch, HEAD)
        self.assertIsNone(self.github.note['pending_action'])
        self.assertEqual((await runner.step('example/product', 4))['action'], 'continue')
        self.assertEqual(self.github.note['correction_reason'], 'integration_changed')

    async def test_pending_publish_remembers_integrated_base_not_initial_contract(self):
        runner = await self.publish()
        self.github.cfg['revision'] = 'a' * 40
        self.workspace.publish_failures = 1
        self.workspace.changed_paths = lambda path, sha: ['src/main.py'] if sha == 'a' * 40 else ['upstream-only.txt']
        self.assertEqual((await runner.step('example/product', 4))['reason'], 'publish_unknown')
        self.assertEqual(self.github.note['contract_revision'], BASE)
        self.assertEqual(self.github.note['expected_base'], 'a' * 40)
        self.github.cfg['revision'] = 'b' * 40
        self.calls.clear()
        self.assertEqual((await self.runner().step('example/product', 4))['action'], 'continue')
        self.assertEqual(self.calls, [])
        self.assertEqual(self.github.branch, HEAD)
        self.assertEqual(self.github.note['expected_base'], 'a' * 40)

    async def test_cancelled_verification_does_not_review_or_correct(self):
        from hydra_sdlc.workspace import WorkspaceWait
        runner = await self.publish()
        self.calls.clear()
        def verify(path, commands, *, stop_requested):
            self.stop = True
            self.assertTrue(stop_requested())
            raise WorkspaceWait('verification_stopped')
        self.workspace.verify = verify
        self.assertEqual((await runner.step('example/product', 4))['reason'], 'stop_requested')
        self.assertEqual(self.calls, [])
        self.assertFalse(any(x[0] == 'push' for x in self.github.writes))

    async def test_verification_success_racing_stop_is_not_accepted(self):
        runner = await self.publish()
        self.calls.clear()
        original = self.workspace.verify
        def verify(*args, **kwargs):
            self.stop = True
            return original(*args, **kwargs)
        self.workspace.verify = verify
        self.assertEqual((await runner.step('example/product', 4))['reason'], 'stop_requested')
        self.assertEqual(self.calls, [])
        self.assertEqual(runner.verified_heads, set())

    async def test_design_without_actual_spec_enters_diagnosis_once(self):
        spec = self.workspace.path / 'docs/engineering/task/spec.md'
        spec.unlink()
        self.workspace.changed_paths = lambda *args: []
        runner = self.runner()
        self.assertEqual((await runner.step('example/product', 4))['reason'], 'replan_required')
        self.assertEqual(self.workspace.head, BASE)
        self.assertEqual(self.calls, ['workspace_write'])
        self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'replan_required')
        self.assertEqual(self.calls, ['workspace_write'])

    async def test_special_and_untracked_existing_specs_are_not_read_or_reviewed(self):
        for kind in ['fifo', 'symlink', 'empty', 'untracked']:
            with self.subTest(kind=kind):
                self.github = GitHub()
                self.workspace = Workspace(self.directory.name, self.github)
                self.calls.clear()
                spec = self.workspace.path / 'docs/engineering/task/spec.md'
                spec.unlink()
                if kind == 'fifo':
                    os.mkfifo(spec)
                elif kind == 'symlink':
                    spec.symlink_to('missing-spec')
                else:
                    spec.write_text('Untracked spec' if kind == 'untracked' else '')
                if kind == 'untracked':
                    self.workspace.valid_spec = lambda *args, require_tracked=True: not require_tracked
                self.workspace.read_spec = lambda *args: self.fail('Invalid spec was read')
                self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'replan_required')
                self.assertEqual(self.calls, [])
                spec.unlink()

    async def test_new_regular_design_is_checkpointed_before_tracked_readiness(self):
        spec = self.workspace.path / 'docs/engineering/task/spec.md'
        spec.unlink()
        self.workspace.changed_paths = lambda *args: ['docs/engineering/task/spec.md']
        checked = []
        def valid(path, relative, *, require_tracked=True):
            checked.append((require_tracked, self.workspace.head))
            return spec.is_file() and (not require_tracked or self.workspace.head == HEAD)
        self.workspace.valid_spec = valid
        async def design(assignment, **kwargs):
            spec.write_text('Requirement-linked design')
            self.workspace.dirty = True
            return {'status': 'completed', 'detail': {'result': {'outcome': 'candidate_ready'}}}
        runner = self.runner()
        runner.execute = design
        self.assertEqual((await runner.step('example/product', 4))['action'], 'continue')
        self.assertEqual(self.github.note['phase'], 'design_done')
        self.assertIn((False, BASE), checked)
        self.assertEqual(checked[-1], (True, HEAD))

    async def test_lost_pr_response_cannot_adopt_foreign_same_head_pr(self):
        runner = await self.publish()
        original = self.github.ensure_pr
        def foreign(*args):
            original(*args)
            self.github.pr['user']['login'] = 'another-writer'
            raise RuntimeError('creation response lost')
        self.github.ensure_pr = foreign
        self.assertEqual((await runner.step('example/product', 4))['reason'], 'foreign_pr')
        self.assertFalse(any(x[0] == 'merge' for x in self.github.writes))

    async def test_confirmed_stopped_handover_recovers_owned_dirty_edits(self):
        await self.publish()
        self.workspace.dirty = True
        self.github.note.update(phase='executing', pending_action='correction')
        runner = self.runner()
        self.assertEqual((await runner.step('example/product', 4))['reason'], 'confirm_previous_stopped')
        self.assertTrue(self.workspace.dirty)
        self.github.extra_comments.append({'user': {'login': 'operator'},
            'body': f"hydra: handover {self.github.note['attempt_id']} stopped"})
        self.assertEqual((await self.runner().step('example/product', 4))['action'], 'continue')
        self.assertTrue(self.workspace.prepared_recovery[-1])
        self.assertFalse(self.workspace.dirty)
        self.assertEqual(self.workspace.verification_calls, 1)

    async def test_interrupted_checkpoint_requires_local_verification_after_restart(self):
        for failed_push in [False, True]:
            with self.subTest(failed_push=failed_push):
                self.github = GitHub()
                self.workspace = Workspace(self.directory.name, self.github)
                self.stop = False
                self.github.remote_pending = True
                runner = await self.publish()
                await runner.step('example/product', 4)
                config = {**self.github.cfg, 'intake_digest': self.github.note['intake_digest']}
                async def interrupted(assignment, **kwargs):
                    self.workspace.dirty = True
                    self.stop = True
                    return {'status': 'interrupted', 'detail': {'cleanup': 'confirmed'}}
                runner.execute = interrupted
                self.workspace.publish_failures = int(failed_push)
                _, result = await runner._model('example/product', 4, config,
                    self.github.note, self.workspace.path, 'correction', 'Fix actual finding')
                self.assertEqual(result['reason'], 'stop_requested')
                self.assertEqual(self.github.note['checkpoint'], 'interrupted_committed')
                if failed_push:
                    self.assertEqual(self.github.note['pending_action'], 'publish')
                    self.assertEqual(self.github.note['delivery_attempt'], 1)
                self.stop = False
                self.github.remote_pending = False
                before = self.workspace.verification_calls
                self.calls.clear()
                restarted = self.runner()
                await restarted.step('example/product', 4)
                if failed_push:
                    self.assertEqual(self.github.note['checkpoint'], 'interrupted_committed')
                    self.assertEqual(self.workspace.verification_calls, before)
                    self.assertFalse(any(x[0] == 'merge' for x in self.github.writes))
                    await restarted.step('example/product', 4)
                self.assertEqual(self.workspace.verification_calls, before + 1)
                self.assertIn('read_only', self.calls)
                self.assertNotEqual(self.github.note['checkpoint'], 'interrupted_committed')

    async def test_paused_interruption_reuses_unpublished_checkpoint_after_resume(self):
        self.github.remote_pending = True
        runner = await self.publish()
        await runner.step('example/product', 4)
        config = {**self.github.cfg, 'intake_digest': self.github.note['intake_digest']}
        async def interrupted(assignment, **kwargs):
            self.workspace.dirty = True
            self.github.work['labels'].append({'name': self.github.cfg['labels']['paused']})
            return {'status': 'interrupted', 'detail': {'cleanup': 'confirmed'}}
        runner.execute = interrupted
        await runner._model('example/product', 4, config, self.github.note,
                            self.workspace.path, 'correction', 'Fix actual finding')
        self.assertEqual(self.github.branch, HEAD)
        self.assertEqual(self.github.note['expected_head'], HEAD)
        self.assertEqual(self.github.note['checkpoint'], 'interrupted_committed')
        self.github.work['labels'] = [{'name': 'hydra:ready'}]
        before = self.workspace.verification_calls
        self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'remote_delivery_gates')
        self.assertEqual(self.workspace.verification_calls, before + 1)
        self.assertEqual(self.github.branch, 'f' * 40)

    async def test_remote_head_changed_during_interruption_is_never_adopted(self):
        self.github.remote_pending = True
        runner = await self.publish()
        await runner.step('example/product', 4)
        config = {**self.github.cfg, 'intake_digest': self.github.note['intake_digest']}
        async def interrupted(assignment, **kwargs):
            self.workspace.dirty = True
            self.github.branch = 'd' * 40
            self.github.pr['head']['sha'] = 'd' * 40
            self.stop = True
            return {'status': 'interrupted', 'detail': {'cleanup': 'confirmed'}}
        runner.execute = interrupted
        await runner._model('example/product', 4, config, self.github.note,
                            self.workspace.path, 'correction', 'Fix actual finding')
        self.assertEqual(self.github.note['expected_head'], HEAD)
        self.assertFalse(any(x == ('push', 'f' * 40) for x in self.github.writes))
        self.stop = False
        self.calls.clear()
        before = self.workspace.verification_calls
        self.assertEqual((await self.runner().step('example/product', 4))['reason'], 'remote_head_changed')
        self.assertEqual(self.workspace.verification_calls, before)
        self.assertEqual(self.calls, [])
        self.assertFalse(any(x[0] == 'merge' for x in self.github.writes))

    async def test_unknown_host_cleanup_blocks_other_projects_until_restart(self):
        for unknown in ['capability', 'execution']:
            with self.subTest(unknown=unknown):
                first, second = GitHub(), GitHub()
                first.work['body'] = first.work['body'].replace('```hydra\n', '```hydra\npriority = 1\n')
                second.cfg.update(repository='example/another', repository_id=456)
                class Router:
                    def __getattr__(self, name):
                        return lambda repo, *args, **kwargs: getattr(first if repo == 'example/product' else second, name)(repo, *args, **kwargs)
                router = Router()
                path = Path(self.directory.name) / unknown
                path.mkdir()
                workspace = Workspace(path, first)
                probes, turns = [], []
                async def capabilities(cwd):
                    probes.append(cwd)
                    return {**complete_capabilities(), 'cleanup': 'unknown'} if unknown == 'capability' else complete_capabilities()
                async def execute(assignment, **kwargs):
                    turns.append(assignment)
                    return {'status': 'transport_unknown', 'detail': {'cleanup': 'unknown'}}
                with patch('hydra_sdlc.runner.load_project', side_effect=lambda gh, repo: copy.deepcopy(first.cfg if repo == 'example/product' else second.cfg)):
                    runner = Runner(router, workspace, host_alias='host-a', execute=execute, capabilities=capabilities)
                    result = await runner.cycle(['example/product', 'example/another'])
                    self.assertEqual(len(result), 1)
                    expected = 'host_cleanup_unconfirmed' if unknown == 'capability' else 'host_execution_unconfirmed'
                    self.assertEqual(runner.host_hold_reason, expected)
                    self.assertIsNone(second.note)
                    before = len(probes), len(turns)
                    self.assertEqual((await runner.cycle(['example/product', 'example/another']))[0]['reason'], expected)
                    self.assertEqual((await runner.step('example/another', 4))['reason'], expected)
                    self.assertEqual((len(probes), len(turns)), before)


if __name__ == '__main__':
    unittest.main()
