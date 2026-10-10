"""Strict squash receipts survive response loss without accepting external merges."""

import copy
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc.github import GitHub, GitHubError
from hydra_sdlc.project import (ProjectError, gate_completed_delivery, gate_squash_result,
                                squash_message, squash_message_matches)
from hydra_sdlc.runner import Runner
from test_github import REPO, owned_pr
from test_project import BASE, HEAD, MERGE, config, observation
from test_runner import GitHub as RunnerGitHub, Workspace, complete_capabilities


TREE, LATER = 'e' * 40, 'f' * 40
INTAKE = '1' * 64


def merged_observation():
    value = observation()
    value['pr'].update(merged=True, state='closed', merge_commit_sha=MERGE)
    value['head_commit'] = {'sha': HEAD, 'tree': {'sha': TREE}}
    value['merge_commit'] = {'sha': MERGE, 'tree': {'sha': TREE},
                             'parents': [{'sha': BASE}], 'message': 'Squash title\n\n'
                             + squash_message(123, 4, 7, HEAD, BASE, INTAKE) + '\n'}
    return value


class SquashEvidenceTests(unittest.TestCase):
    def test_historical_result_and_receipt_remain_bound_after_main_advances(self):
        cfg, value = config(), merged_observation()
        cfg['revision'] = value['base_sha'] = LATER
        self.assertEqual(gate_completed_delivery(cfg, value, HEAD, ['src/main.py'],
                                                expected_base=BASE, checkpoint='squash_' + MERGE), [])
        for base, checkpoint in [(None, 'squash_' + MERGE), (LATER, 'squash_' + MERGE),
                                 (BASE, None), (BASE, 'squash_' + LATER)]:
            with self.subTest(base=base, checkpoint=checkpoint):
                self.assertTrue(gate_completed_delivery(cfg, value, HEAD, ['src/main.py'],
                                                       expected_base=base, checkpoint=checkpoint))
        value['provider_comments'] = []
        self.assertTrue(gate_completed_delivery(cfg, value, HEAD, ['src/main.py'],
                                               expected_base=BASE, checkpoint='squash_' + MERGE))

    def test_malformed_commit_identity_tree_and_parent_never_pass(self):
        changes = [
            ('head_commit', None), ('head_commit', {}), ('merge_commit', None),
            ('merge_commit', {'sha': MERGE, 'tree': {'sha': TREE}, 'parents': None}),
            ('merge_commit', {'sha': MERGE, 'tree': {'sha': TREE}, 'parents': [None]}),
            ('merge_commit', {'sha': MERGE, 'tree': {'sha': TREE}, 'parents': [{'sha': 'bad'}]}),
        ]
        for key, field, replacement in [
            ('head_commit', 'sha', LATER), ('head_commit', 'tree', {}),
            ('merge_commit', 'sha', HEAD), ('merge_commit', 'tree', None),
            ('merge_commit', 'tree', {'sha': 'bad'}), ('merge_commit', 'tree', {'sha': LATER}),
            ('merge_commit', 'parents', []), ('merge_commit', 'parents', [{'sha': LATER}]),
            ('merge_commit', 'parents', [{'sha': BASE}, {'sha': HEAD}]),
        ]:
            commit = merged_observation()[key]
            commit[field] = replacement
            changes.append((key, commit))
        for key, replacement in changes:
            with self.subTest(key=key, replacement=replacement):
                value = merged_observation()
                value[key] = replacement
                self.assertTrue(gate_squash_result(value, HEAD, BASE))

    def test_marker_binds_logical_effect_and_requires_one_exact_line(self):
        fields = [123, 4, 7, HEAD, BASE, INTAKE]
        marker = squash_message(*fields)
        self.assertTrue(squash_message_matches('Title (#7)\n\n' + marker + '\n', marker))
        self.assertEqual(squash_message(*fields), marker)
        for index, replacement in enumerate([124, 5, 8, LATER, LATER, '2' * 64]):
            changed = fields.copy()
            changed[index] = replacement
            self.assertFalse(squash_message_matches(squash_message(*changed), marker))
        for text in [None, '', 'prefix ' + marker, marker + ' suffix', marker + '\n' + marker,
                     marker + '\nHydra-Squash-v1: ' + '2' * 64]:
            with self.subTest(text=text):
                self.assertFalse(squash_message_matches(text, marker))
        for index, replacement in [(0, True), (1, 0), (3, None), (4, 'main'), (5, 'bad')]:
            changed = fields.copy()
            changed[index] = replacement
            with self.assertRaises(ProjectError):
                squash_message(*changed)

    def test_single_parent_same_tree_never_substitutes_for_method_receipt(self):
        value = merged_observation()
        value['merge_commit']['message'] = 'One commit rebased on main'
        self.assertEqual(gate_squash_result(value, HEAD, BASE), [])
        self.assertIn('squash_method_unknown', gate_completed_delivery(
            config(), value, HEAD, ['src/main.py'], expected_base=BASE))


class SquashGitHubTests(unittest.TestCase):
    def test_merged_observation_reads_exact_immutable_commits_not_current_main(self):
        value, calls = merged_observation(), []
        def transport(method, path, payload):
            calls.append((method, path))
            if path.endswith('/pulls/7'):
                return value['pr']
            if path.endswith('/rules/branches/main'):
                return []
            return copy.deepcopy({f'/repos/{REPO}/git/commits/{HEAD}': value['head_commit'],
                                  f'/repos/{REPO}/git/commits/{MERGE}': value['merge_commit']}[path])
        gh = GitHub(transport=transport)
        gh.repository = lambda repo: {'id': 123, 'default_branch': 'main'}
        gh.ref = lambda repo, branch: LATER
        gh._pages = lambda path, key=None: [{'filename': 'src/main.py'}] if '/files' in path else []
        gh._threads = lambda repo, pr: ([], None)
        gh.comments = lambda repo, pr: []
        actual = gh.observe(REPO, 7)
        self.assertEqual(gate_squash_result(actual, HEAD, BASE), [])
        self.assertEqual(actual['base_sha'], LATER)
        self.assertEqual([path for _, path in calls if '/git/commits/' in path],
                         [f'/repos/{REPO}/git/commits/{HEAD}', f'/repos/{REPO}/git/commits/{MERGE}'])
        self.assertTrue(all(method == 'GET' for method, _ in calls))

    def test_invalid_put_responses_and_readbacks_cannot_create_receipt(self):
        marker = squash_message(123, 4, 7, HEAD, BASE, INTAKE)
        good = {'merged': True, 'sha': MERGE}
        raw = {**owned_pr(), 'merged': True, 'state': 'closed', 'merge_commit_sha': MERGE}
        cases = [(response, raw) for response in [None, {}, {'merged': 1, 'sha': MERGE},
                 {'merged': False, 'sha': MERGE}, {'merged': True}, {'merged': True, 'sha': 'bad'}]]
        cases += [(good, readback) for readback in [None, {**raw, 'merge_commit_sha': LATER},
                   {**raw, 'head': {'sha': LATER}}, {**raw, 'state': 'open'},
                   GitHubError('read unavailable')]]
        for response, readback in cases:
            with self.subTest(response=response, readback=readback):
                writes = []
                def transport(method, path, payload):
                    if method == 'PUT':
                        writes.append(payload)
                        return response
                    if not writes:
                        return owned_pr()
                    if isinstance(readback, Exception):
                        raise readback
                    return readback
                with self.assertRaises(GitHubError) as caught:
                    GitHub(transport=transport).merge(REPO, 7, HEAD, commit_message=marker)
                self.assertTrue(caught.exception.uncertain)
                self.assertEqual(writes, [{'sha': HEAD, 'merge_method': 'squash', 'commit_message': marker}])


class SquashRunnerTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.github = RunnerGitHub()
        self.workspace = Workspace(directory.name, self.github)
        self.calls = []
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
        return await Runner(self.github, self.workspace, host_alias='host-a', execute=self.execute,
                            capabilities=self.capabilities).step(REPO, 4)

    async def opened_pr(self):
        self.github.remote_pending = True
        self.assertEqual((await self.step())['action'], 'continue')
        self.assertEqual((await self.step())['reason'], 'remote_delivery_gates')
        self.github.remote_pending = False

    async def test_lost_squash_response_and_readback_recover_after_restart_without_remerge(self):
        await self.opened_pr()
        calls = len(self.calls)
        self.github.lose_merge = True
        original = self.github.observe
        def unavailable(repo, pr):
            if self.github.pr.get('merged'):
                raise RuntimeError('read-back unavailable until restart')
            return original(repo, pr)
        self.github.observe = unavailable
        with self.assertRaisesRegex(RuntimeError, 'read-back unavailable'):
            await self.step()
        self.assertEqual(self.github.note['pending_action'], 'merge')
        self.assertNotEqual(self.github.note.get('checkpoint'), 'squash_' + MERGE)
        self.github.observe = original
        self.assertEqual((await self.step())['action'], 'completed')
        self.assertEqual(self.github.note['checkpoint'], 'squash_' + MERGE)
        self.assertEqual(len(self.calls), calls)
        self.assertEqual([x[0] for x in self.github.writes if x[0] in {'merge', 'close'}], ['merge', 'close'])

    async def test_external_rebase_or_merge_commit_holds_without_effects(self):
        await self.opened_pr()
        calls, writes = len(self.calls), len(self.github.writes)
        self.github.pr.update(merged=True, state='closed', merge_commit_sha=MERGE)
        for parents in [[{'sha': BASE}], [{'sha': BASE}, {'sha': HEAD}], [{'sha': LATER}]]:
            with self.subTest(parents=parents):
                def external(value):
                    value['merge_commit']['parents'] = parents
                    return value
                self.github.transform_observation = external
                self.assertEqual((await self.step())['action'], 'waiting')
                self.assertEqual(self.github.work['state'], 'open')
        self.assertEqual(len(self.calls), calls)
        self.assertFalse(any(x[0] != 'record' for x in self.github.writes[writes:]))

    async def test_pending_merge_intent_cannot_recover_missing_wrong_or_duplicate_marker(self):
        directory = self.workspace.path
        for mutation in [lambda marker: None, lambda marker: 'Ordinary commit message',
                         lambda marker: 'Hydra-Squash-v1: ' + '9' * 64,
                         lambda marker: marker + '\n' + marker]:
            with self.subTest(mutation=mutation):
                self.github = RunnerGitHub()
                self.workspace = Workspace(directory, self.github)
                self.calls = []
                await self.opened_pr()
                calls = len(self.calls)
                merge = self.github.merge
                def lost_response(repo, pr, head, *, commit_message):
                    merge(repo, pr, head, commit_message=commit_message)
                    self.github.merge_message = mutation(commit_message)
                    raise RuntimeError('response lost')
                self.github.merge = lost_response
                self.assertEqual((await self.step())['reason'], 'merge_unknown')
                writes = len(self.github.writes)
                self.assertEqual((await self.step())['reason'], 'squash_method_unknown')
                self.assertEqual(self.github.note['pending_action'], 'merge')
                self.assertNotEqual(self.github.note.get('checkpoint'), 'squash_' + MERGE)
                self.assertEqual(self.github.work['state'], 'open')
                self.assertEqual(len(self.calls), calls)
                self.assertEqual(len([x for x in self.github.writes if x[0] == 'merge']), 1)
                self.assertFalse(any(x[0] != 'record' for x in self.github.writes[writes:]))

    async def test_close_intent_rechecks_commit_facts_and_closed_recovery_preserves_receipt(self):
        await self.opened_pr()
        self.assertEqual((await self.step())['action'], 'continue')
        self.assertEqual(self.github.note['checkpoint'], 'squash_' + MERGE)
        def change_after_close_intent(record):
            if record.get('pending_action') == 'close_issue':
                def wrong_tree(value):
                    value['merge_commit']['tree'] = {'sha': LATER}
                    return value
                self.github.transform_observation = wrong_tree
        self.github.on_record = change_after_close_intent
        self.assertEqual((await self.step())['reason'], 'completion_evidence_missing')
        self.assertFalse(any(x[0] == 'close' for x in self.github.writes))
        self.github.on_record = lambda record: None
        self.github.transform_observation = lambda value: value
        self.github.closed_response_lost = True
        issue = self.github.issue
        def closed_readback_unavailable(repo, number):
            if self.github.work['state'] == 'closed':
                raise RuntimeError('close read-back unavailable until restart')
            return issue(repo, number)
        self.github.issue = closed_readback_unavailable
        with self.assertRaisesRegex(RuntimeError, 'close read-back unavailable'):
            await self.step()
        self.assertEqual(self.github.work['state'], 'closed')
        self.assertEqual(self.github.note['pending_action'], 'close_issue')
        self.github.issue = issue
        self.assertEqual((await self.step())['action'], 'completed')
        self.assertEqual(self.github.note['checkpoint'], 'squash_' + MERGE)
        self.assertEqual(len([x for x in self.github.writes if x[0] == 'close']), 1)


if __name__ == '__main__':
    unittest.main()
