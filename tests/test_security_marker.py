"""Authenticated provider metadata remains unambiguous across review recovery."""

import copy
import json
import re
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc.project import _provider, gate_delivery
from hydra_sdlc.runner import Runner
from test_project import HEAD, config, observation, summary
from test_runner import GitHub, Workspace, complete_capabilities


PATTERN = r'<!-- codex-security-review:v1 (.*?) -->'


def native_marker():
    return json.loads(re.search(PATTERN, summary())[1])


def replace_marker(value, encoded):
    comment = value['provider_comments'][0]
    comment['body'] = re.sub(PATTERN, lambda _: '<!-- codex-security-review:v1 ' + encoded + ' -->', comment['body'])
    return value


def duplicate_marker(field, first, second):
    marker = native_marker()
    marker[field] = first
    return json.dumps(marker)[:-1] + ', ' + json.dumps(field) + ': ' + json.dumps(second) + '}'


class SecurityMarkerTests(unittest.TestCase):
    def test_duplicate_fields_are_rejected_in_both_orders_including_equal_and_escaped_keys(self):
        cases = []
        for field, stale, current in [('headSha', 'a' * 40, HEAD), ('status', 'running', 'completed')]:
            cases.extend((duplicate_marker(field, stale, current), duplicate_marker(field, current, stale)))
        cases.extend(duplicate_marker(field, value, value) for field, value in native_marker().items())
        cases.append(json.dumps(native_marker())[:-1] + ', "\\u0068eadSha": ' + json.dumps(HEAD) + '}')
        for encoded in cases:
            with self.subTest(encoded=encoded):
                value = replace_marker(observation(), encoded)
                self.assertEqual(_provider(config(), value, HEAD), ['provider_format_unknown'])
                self.assertIn('provider_format_unknown', gate_delivery(config(), value, HEAD, ['src/main.py']))

    def test_exact_six_fields_and_scalar_types_are_required(self):
        cases = [[], None, 'completed']
        for field in native_marker():
            marker = native_marker()
            del marker[field]
            cases.append(marker)
        cases.append({**native_marker(), 'approved': True})
        for field, invalid in [('blockingSeverityThreshold', 0), ('headSha', [HEAD]),
                               ('mergeGateEnabled', 0), ('mergeGateEnabled', 'false'),
                               ('pullRequestNumber', True), ('pullRequestNumber', 7.0),
                               ('repository', {}), ('status', None)]:
            cases.append({**native_marker(), field: invalid})
        for marker in cases:
            with self.subTest(marker=marker):
                self.assertEqual(_provider(config(), replace_marker(observation(), json.dumps(marker)), HEAD),
                                 ['provider_format_unknown'])

    def test_native_metadata_values_neither_grant_approval_nor_replace_other_evidence(self):
        for threshold, merge_gate in [('P0', False), ('P2', True)]:
            with self.subTest(threshold=threshold, merge_gate=merge_gate):
                marker = {**native_marker(), 'blockingSeverityThreshold': threshold, 'mergeGateEnabled': merge_gate}
                value = replace_marker(observation(), json.dumps(marker))
                self.assertEqual(_provider(config(), value, HEAD), [])
                self.assertEqual(gate_delivery(config(), value, HEAD, ['src/main.py']), [])
                value['threads'] = [{'id': 'current-finding', 'isResolved': False}]
                self.assertIn('review_threads_unresolved_or_unknown', gate_delivery(config(), value, HEAD, ['src/main.py']))
                value['provider_comments'][0]['performed_via_github_app']['id'] = 1
                self.assertEqual(_provider(config(), value, HEAD), ['provider_summary_missing_or_ambiguous'])

    def test_current_head_completion_and_table_binding_still_apply(self):
        for field, value in [('headSha', 'a' * 40), ('status', 'running'),
                             ('repository', 'example/another'), ('pullRequestNumber', 8)]:
            with self.subTest(field=field):
                observed = replace_marker(observation(), json.dumps({**native_marker(), field: value}))
                self.assertEqual(_provider(config(), observed, HEAD), ['provider_head_or_completion_missing'])
        observed = observation()
        observed['provider_comments'][0]['body'] = observed['provider_comments'][0]['body'].replace('✅ **Completed**', '🔄 **Running**')
        self.assertEqual(_provider(config(), observed, HEAD), ['provider_review_not_completed'])


class SecurityMarkerRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.github = GitHub()
        self.workspace = Workspace(self.directory.name, self.github)
        self.calls = []
        policy = patch('hydra_sdlc.runner.load_project', side_effect=lambda gh, repo, revision=None: copy.deepcopy(gh.cfg))
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

    async def test_malformed_completed_marker_diagnoses_on_restart_without_settling_uncertain_request(self):
        await self.opened_pr()
        original = copy.deepcopy(self.github.note)
        original_pr, original_issue = copy.deepcopy(self.github.pr), copy.deepcopy(self.github.work)
        missing = native_marker()
        del missing['mergeGateEnabled']
        cases = [duplicate_marker('status', 'running', 'completed'),
                 duplicate_marker('headSha', 'a' * 40, HEAD), json.dumps(missing),
                 json.dumps({**native_marker(), 'approved': True}),
                 json.dumps({**native_marker(), 'pullRequestNumber': 7.0})]
        for encoded in cases:
            for pending in (False, True):
                with self.subTest(encoded=encoded, pending=pending):
                    self.github.note = copy.deepcopy(original)
                    self.github.pr = copy.deepcopy(original_pr)
                    self.github.work = copy.deepcopy(original_issue)
                    if pending:
                        self.github.note.update(phase='uncertain', pending_action='request_review',
                            pending_review_kind='security', delivery_action='request_review',
                            delivery_attempt=3, action_attempt=3, delivery_head=HEAD,
                            expected_head=HEAD, review_requested_security_head=None)
                    keys = ('head', 'expected_head', 'pending_action', 'pending_review_kind',
                            'delivery_action', 'delivery_attempt', 'action_attempt', 'delivery_head',
                            'review_requested_security_head')
                    preserved = {key: self.github.note.get(key) for key in keys}
                    self.github.transform_observation = lambda value: replace_marker(value, encoded)
                    calls, writes = len(self.calls), len(self.github.writes)
                    for _ in range(2):
                        self.assertEqual((await self.step())['reason'], 'replan_required')
                        self.assertEqual(self.github.note['next_action'], 'diagnose_review')
                        if pending:
                            self.assertEqual(self.github.note['phase'], 'uncertain')
                            self.assertEqual({key: self.github.note.get(key) for key in keys}, preserved)
                    self.assertEqual(len(self.calls), calls)
                    self.assertFalse(any(write[0] != 'record' for write in self.github.writes[writes:]))
                    self.assertFalse(self.github.pr['merged'])

    async def test_actual_running_marker_and_security_row_keep_existing_wait(self):
        await self.opened_pr()
        def running(value):
            value = replace_marker(value, json.dumps({**native_marker(), 'status': 'running'}))
            comment = value['provider_comments'][0]
            comment['body'] = '\n'.join(line.replace('✅ **Completed**', '🔄 **Running**')
                if '**Security Review**' in line else line for line in comment['body'].splitlines())
            return value
        self.github.transform_observation = running
        calls, writes = len(self.calls), len(self.github.writes)
        for _ in range(2):
            self.assertEqual((await self.step())['reason'], 'remote_delivery_gates')
        self.assertEqual(len(self.calls), calls)
        self.assertFalse(any(write[0] != 'record' for write in self.github.writes[writes:]))
        self.assertFalse(self.github.pr['merged'])


if __name__ == '__main__':
    unittest.main()
