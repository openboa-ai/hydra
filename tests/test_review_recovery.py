"""Uncertain merges and terminal provider reviews retain actionable service state."""

import copy
import json
import re
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc.runner import Runner
from test_project import HEAD, MERGE, summary
from test_runner import GitHub, Workspace, complete_capabilities


class ReviewRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.github = GitHub()
        self.workspace = Workspace(self.directory.name, self.github)
        self.calls = []
        self.merge_requests = []
        policy = patch('hydra_sdlc.runner.load_project',
                       side_effect=lambda gh, repo, revision=None: copy.deepcopy(gh.cfg))
        policy.start()
        self.addCleanup(policy.stop)

    async def execute(self, assignment, **kwargs):
        self.calls.append(self.github.note['pending_action'])
        if assignment['mode'] == 'workspace_write':
            self.workspace.dirty = True
        return {'status': 'completed', 'detail': {'result': {'outcome': 'candidate_ready'}}}

    async def capabilities(self, cwd):
        return complete_capabilities()

    async def step(self):
        runner = Runner(self.github, self.workspace, host_alias='host-a',
                        execute=self.execute, capabilities=self.capabilities)
        return await runner.step('example/product', 4)

    async def opened_pr(self):
        self.github.remote_pending = True
        self.assertEqual((await self.step())['action'], 'continue')
        self.assertEqual((await self.step())['reason'], 'remote_delivery_gates')
        self.github.remote_pending = False

    async def unknown_merge(self):
        await self.opened_pr()
        def fail_merge(repo, number, head, *, commit_message, issue_number):
            self.assertEqual(issue_number, 4)
            self.github.assert_intent('merge')
            self.github.merge_message = commit_message
            self.merge_requests.append(head)
            raise RuntimeError('merge response unavailable')
        self.github.merge = fail_merge
        self.assertEqual((await self.step())['reason'], 'merge_unknown')
        self.assertEqual(self.github.note['pending_action'], 'merge')
        self.assertEqual(len(self.merge_requests), 1)

    async def held_merge(self, change):
        await self.unknown_merge()
        pinned = {key: self.github.note.get(key) for key in ('head', 'expected_head', 'expected_base')}
        calls, writes = len(self.calls), len(self.github.writes)
        self.github.transform_observation = change
        for _ in range(2):
            self.assertEqual((await self.step())['action'], 'waiting')
            self.assertEqual(self.github.note['phase'], 'uncertain')
            self.assertEqual(self.github.note['pending_action'], 'merge')
            self.assertEqual({key: self.github.note.get(key) for key in pinned}, pinned)
        self.assertEqual(len(self.calls), calls)
        self.assertEqual(len(self.merge_requests), 1)
        self.assertFalse(any(write[0] != 'record' for write in self.github.writes[writes:]))

    async def test_pending_merge_with_new_behind_state_never_integrates_or_retargets(self):
        def behind(value):
            value['pr']['mergeable_state'] = 'behind'
            value['pr']['base']['sha'] = 'e' * 40
            value['base_sha'] = 'e' * 40
            return value
        await self.held_merge(behind)

    async def test_pending_merge_with_new_finding_never_dispatches_correction(self):
        def finding(value):
            value['threads'] = [{'id': 'current-finding', 'isOutdated': False, 'isResolved': False,
                                 'comments': {'nodes': [{'databaseId': 901, 'author': {
                                     'login': self.github.cfg['review_provider']['login']}}]}}]
            value['inline_comments'] = [{'id': 901, 'body': 'Current-head finding', 'path': 'src/main.py', 'line': 1}]
            return value
        await self.held_merge(finding)

    async def test_matching_merge_readback_requires_post_checks_then_closes_without_repeat_merge(self):
        await self.unknown_merge()
        calls = len(self.calls)
        self.github.pr.update(merged=True, state='closed', merge_commit_sha=MERGE)
        original = self.github.observe_commit
        passing = False
        observed = []
        def observe_commit(repo, sha):
            observed.append(sha)
            value = original(repo, sha)
            if not passing:
                value['checks'][0]['conclusion'] = 'failure'
                value['runs'][0]['conclusion'] = 'failure'
            return value
        self.github.observe_commit = observe_commit
        self.assertEqual((await self.step())['reason'], 'post_merge_checks')
        self.assertEqual(self.github.work['state'], 'open')
        passing = True
        self.assertEqual((await self.step())['action'], 'completed')
        self.assertEqual(observed, [MERGE, MERGE, MERGE])
        self.assertEqual(self.github.work['state'], 'closed')
        self.assertEqual(self.github.note['phase'], 'completed')
        self.assertEqual(len(self.calls), calls)
        self.assertEqual(len(self.merge_requests), 1)
        self.assertEqual(len([write for write in self.github.writes if write[0] == 'close']), 1)

    @staticmethod
    def review_status(value, name, status):
        comment = value['provider_comments'][0]
        lines = comment['body'].splitlines()
        for index, line in enumerate(lines):
            if line.startswith('|') and f'**{name}**' in line:
                cells = line.split('|')
                icon = '🔄' if status == 'Running' else '⏳' if status in {'Queued', 'Pending'} else '❌'
                cells[2] = f' {icon} **{status}** '
                lines[index] = '|'.join(cells)
        comment['body'] = '\n'.join(lines)
        return value

    async def terminal_reviews(self, status):
        await self.opened_pr()
        original = copy.deepcopy(self.github.note)
        for name in ('Code Review', 'Security Review'):
            with self.subTest(review=name, status=status):
                self.github.note = copy.deepcopy(original)
                self.github.transform_observation = lambda value: self.review_status(value, name, status)
                calls, writes = len(self.calls), len(self.github.writes)
                for _ in range(2):
                    self.assertEqual((await self.step())['reason'], 'replan_required')
                    self.assertEqual(self.github.note['wait_reason'], 'replan_required')
                    self.assertEqual(self.github.note['next_action'], 'diagnose_review')
                self.assertEqual(self.github.work['state'], 'open')
                self.assertFalse(self.github.pr['merged'])
                self.assertEqual(len(self.calls), calls)
                self.assertFalse(any(write[0] != 'record' for write in self.github.writes[writes:]))

    async def test_failed_review_enters_durable_diagnosis(self):
        await self.terminal_reviews('Failed')

    async def test_cancelled_review_enters_durable_diagnosis(self):
        await self.terminal_reviews('Cancelled')

    async def test_error_review_enters_durable_diagnosis(self):
        await self.terminal_reviews('Error')

    async def test_unknown_current_review_status_enters_diagnosis(self):
        await self.terminal_reviews('New terminal state')

    async def test_recognized_active_review_states_wait_without_diagnosis_or_requests(self):
        await self.opened_pr()
        original = copy.deepcopy(self.github.note)
        for status in ('Queued', 'Pending', 'Running'):
            with self.subTest(status=status):
                self.github.note = copy.deepcopy(original)
                self.github.transform_observation = lambda value: self.review_status(value, 'Code Review', status)
                calls, writes = len(self.calls), len(self.github.writes)
                for _ in range(2):
                    self.assertEqual((await self.step())['reason'], 'remote_delivery_gates')
                self.assertEqual(len(self.calls), calls)
                self.assertFalse(self.github.pr['merged'])
                self.assertFalse(any(write[0] != 'record' for write in self.github.writes[writes:]))

    @staticmethod
    def malformed_completion(value, case):
        body = value['provider_comments'][0]['body']
        pattern = r'<!-- codex-security-review:v1 (.*?) -->'
        if case == 'missing':
            body = re.sub(pattern, '', body)
        elif case == 'malformed':
            body = re.sub(pattern, '<!-- codex-security-review:v1 {invalid -->', body)
        elif case in {'repository', 'pullRequestNumber', 'headSha', 'status'}:
            marker = json.loads(re.search(pattern, body)[1])
            marker[case] = {'repository': 'example/another', 'pullRequestNumber': 8,
                            'headSha': 'e' * 40, 'status': 'failed'}[case]
            body = re.sub(pattern, '<!-- codex-security-review:v1 ' + json.dumps(marker) + ' -->', body)
        else:
            lines = body.splitlines()
            for index, line in enumerate(lines):
                if line.startswith('|') and '**Security Review**' in line:
                    if case == 'extra_cell':
                        lines[index] = line + ' unexpected |'
                    elif case == 'revision_text':
                        lines[index] = line.replace(f'`{HEAD[:7]}`', f'`{HEAD[:7]}` unknown')
                    elif case in {'truncated_row', 'missing_revision_column'}:
                        cells = line.split('|')
                        if case == 'truncated_row':
                            lines[index] = '|'.join(cells[:3])
                        else:
                            cells.pop(3)
                            lines[index] = '|'.join(cells)
                    elif case in {'missing_backticks', 'empty_revision', 'unresolvable_revision', 'ambiguous_revision'}:
                        revision = {'missing_backticks': HEAD[:7], 'empty_revision': '',
                                    'unresolvable_revision': '`0000000`',
                                    'ambiguous_revision': f'`{HEAD[:7]}`'}[case]
                        lines[index] = line.replace(f'`{HEAD[:7]}`', revision)
                        if case == 'ambiguous_revision':
                            value['commits'].append({'sha': HEAD[:7] + 'e' * 33})
                            value['pr']['commits'] += 1
                    else:
                        lines[index] = line.replace('✅ **Completed**', '✅ **Completed** unknown')
            body = '\n'.join(lines)
        value['provider_comments'][0]['body'] = body
        return value

    async def test_terminal_envelope_and_row_errors_diagnose_across_restart_preserving_uncertain_request(self):
        await self.opened_pr()
        original = copy.deepcopy(self.github.note)
        for case in ('missing', 'malformed', 'repository', 'pullRequestNumber', 'headSha',
                     'status', 'extra_cell', 'revision_text', 'status_text'):
            for pending in (False, True):
                with self.subTest(case=case, pending=pending):
                    self.github.note = copy.deepcopy(original)
                    if pending:
                        self.github.note.update(phase='uncertain', pending_action='request_review',
                            pending_review_kind='security', delivery_action='request_review',
                            delivery_attempt=3, action_attempt=3, delivery_head=HEAD,
                            expected_head=HEAD, review_requested_security_head=None)
                    keys = ('head', 'expected_head', 'pending_action', 'pending_review_kind',
                            'delivery_action', 'delivery_attempt', 'action_attempt', 'delivery_head',
                            'review_requested_security_head')
                    pinned = {key: self.github.note.get(key) for key in keys}
                    self.github.transform_observation = lambda value: self.malformed_completion(value, case)
                    calls, writes = len(self.calls), len(self.github.writes)
                    for _ in range(2):
                        self.assertEqual((await self.step())['reason'], 'replan_required')
                        self.assertEqual(self.github.note['next_action'], 'diagnose_review')
                        self.assertEqual(self.github.note['wait_reason'], 'replan_required')
                        if pending:
                            self.assertEqual(self.github.note['phase'], 'uncertain')
                            self.assertEqual({key: self.github.note.get(key) for key in keys}, pinned)
                    self.assertEqual(len(self.calls), calls)
                    self.assertFalse(any(write[0] != 'record' for write in self.github.writes[writes:]))
                    self.assertFalse(self.github.pr['merged'])

    async def test_unbound_terminal_revision_diagnoses_even_after_requests_were_recorded(self):
        await self.opened_pr()
        original = copy.deepcopy(self.github.note)
        for case in ('missing_backticks', 'empty_revision', 'unresolvable_revision', 'ambiguous_revision',
                     'truncated_row', 'missing_revision_column'):
            for pending in (False, True):
                with self.subTest(case=case, pending=pending):
                    self.github.note = copy.deepcopy(original)
                    self.github.note.update(review_requested_head=HEAD, review_requested_security_head=HEAD)
                    if pending:
                        self.github.note.update(phase='uncertain', pending_action='request_review',
                            pending_review_kind='security', delivery_action='request_review',
                            delivery_attempt=3, action_attempt=3, delivery_head=HEAD, expected_head=HEAD)
                    keys = ('head', 'expected_head', 'pending_action', 'pending_review_kind',
                            'delivery_action', 'delivery_attempt', 'action_attempt', 'delivery_head',
                            'review_requested_head', 'review_requested_security_head')
                    pinned = {key: self.github.note.get(key) for key in keys}
                    self.github.transform_observation = lambda value: self.malformed_completion(value, case)
                    calls, writes = len(self.calls), len(self.github.writes)
                    for _ in range(2):
                        self.assertEqual((await self.step())['reason'], 'replan_required')
                        self.assertEqual(self.github.note['next_action'], 'diagnose_review')
                        self.assertEqual({key: self.github.note.get(key) for key in keys}, pinned)
                        if pending:
                            self.assertEqual(self.github.note['phase'], 'uncertain')
                    self.assertEqual(len(self.calls), calls)
                    self.assertFalse(any(write[0] != 'record' for write in self.github.writes[writes:]))
                    self.assertFalse(self.github.pr['merged'])

    async def test_active_review_without_terminal_envelope_still_waits_normally(self):
        await self.opened_pr()
        original = copy.deepcopy(self.github.note)
        for name in ('Code Review', 'Security Review'):
            for status in ('Queued', 'Pending', 'Running'):
                with self.subTest(name=name, status=status):
                    self.github.note = copy.deepcopy(original)
                    def active(value):
                        return self.review_status(self.malformed_completion(value, 'missing'), name, status)
                    self.github.transform_observation = active
                    calls, writes = len(self.calls), len(self.github.writes)
                    for _ in range(2):
                        self.assertEqual((await self.step())['reason'], 'remote_delivery_gates')
                        self.assertNotEqual(self.github.note.get('next_action'), 'diagnose_review')
                    self.assertEqual(len(self.calls), calls)
                    self.assertFalse(any(write[0] != 'record' for write in self.github.writes[writes:]))
                    self.assertFalse(self.github.pr['merged'])

    async def test_prior_head_completed_reviews_request_reviews_for_the_new_head(self):
        await self.opened_pr()
        previous_head = 'e' * 40
        def previous(value):
            value['provider_comments'][0]['body'] = summary(previous_head)
            value['commits'] = [{'sha': previous_head}, {'sha': HEAD}]
            value['pr']['commits'] = 2
            return value
        self.github.transform_observation = previous
        calls, writes = len(self.calls), len(self.github.writes)
        for _ in range(2):
            self.assertEqual((await self.step())['reason'], 'remote_delivery_gates')
            self.assertNotEqual(self.github.note.get('next_action'), 'diagnose_review')
        self.assertEqual(len(self.calls), calls)
        self.assertEqual([write for write in self.github.writes[writes:] if write[0] != 'record'],
                         [('request_review', 'code', HEAD), ('request_review', 'security', HEAD)])
        self.assertFalse(self.github.pr['merged'])

    async def test_mixed_old_and_current_completed_rows_request_only_the_missing_kind(self):
        await self.opened_pr()
        original = copy.deepcopy(self.github.note)
        old = 'e' * 40
        for kind, name in (('code', 'Code Review'), ('security', 'Security Review')):
            with self.subTest(kind=kind):
                self.github.note = copy.deepcopy(original)
                def mixed(value):
                    body = value['provider_comments'][0]['body']
                    value['provider_comments'][0]['body'] = '\n'.join(
                        line.replace(f'`{HEAD[:7]}`', f'`{old[:7]}`')
                        if line.startswith('|') and f'**{name}**' in line else line
                        for line in body.splitlines())
                    value['commits'] = [{'sha': old}, {'sha': HEAD}]
                    value['pr']['commits'] = 2
                    return value
                self.github.transform_observation = mixed
                calls, writes = len(self.calls), len(self.github.writes)
                for _ in range(2):
                    self.assertEqual((await self.step())['reason'], 'remote_delivery_gates')
                    self.assertNotEqual(self.github.note.get('next_action'), 'diagnose_review')
                self.assertEqual(len(self.calls), calls)
                self.assertEqual([w for w in self.github.writes[writes:] if w[0] != 'record'],
                                 [('request_review', kind, HEAD)])
                self.assertFalse(self.github.pr['merged'])

    async def test_valid_terminal_envelope_keeps_current_findings_on_correction_path(self):
        await self.opened_pr()
        def finding(value):
            value['threads'] = [{'id': 'finding', 'isResolved': False, 'isOutdated': False,
                'comments': {'nodes': [{'databaseId': 901,
                    'author': {'login': self.github.cfg['review_provider']['login']}}]}}]
            value['inline_comments'] = [{'id': 901, 'body': 'Fix the current behavior.',
                                        'path': 'src/main.py', 'line': 1}]
            return value
        self.github.transform_observation = finding
        calls, writes = len(self.calls), len(self.github.writes)
        self.assertEqual((await self.step())['action'], 'continue')
        self.assertIn('correction', self.calls[calls:])
        self.assertEqual(self.github.note['correction_reason'], 'remote_review_findings')
        self.assertNotEqual(self.github.note.get('next_action'), 'diagnose_review')
        self.assertFalse(any(write[0] != 'record' for write in self.github.writes[writes:]))
        self.assertFalse(self.github.pr['merged'])

    async def test_valid_terminal_envelope_with_additional_provider_comment_enters_diagnosis(self):
        await self.opened_pr()
        def comment(value):
            value['provider_comments'].append({**value['provider_comments'][0], 'id': 61,
                                              'body': 'A finding requires resolution.'})
            return value
        self.github.transform_observation = comment
        calls, writes = len(self.calls), len(self.github.writes)
        for _ in range(2):
            self.assertEqual((await self.step())['reason'], 'replan_required')
            self.assertEqual(self.github.note.get('next_action'), 'diagnose_review')
        self.assertEqual(len(self.calls), calls)
        self.assertFalse(any(write[0] != 'record' for write in self.github.writes[writes:]))
        self.assertFalse(self.github.pr['merged'])


if __name__ == '__main__':
    unittest.main()
