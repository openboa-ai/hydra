"""Final observation and restart must retain current controls and effect intent."""

import copy
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc.runner import Runner
from test_project import BASE, MERGE
from test_runner import GitHub, Workspace, complete_capabilities


REPO, NUMBER = 'example/product', 4
SPEC = 'docs/engineering/task/spec.md'


class FinalControlsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.reset()
        policy = patch('hydra_sdlc.runner.load_project',
                       side_effect=lambda gh, repo, revision=None: copy.deepcopy(gh.cfg))
        policy.start()
        self.addCleanup(policy.stop)

    def reset(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.github = GitHub()
        self.workspace = Workspace(directory.name, self.github)
        self.calls = []
        self.stopped = False
        self.dependency_open = False

    async def execute(self, assignment, **kwargs):
        self.calls.append(self.github.note['pending_action'])
        if assignment['mode'] == 'workspace_write':
            self.workspace.dirty = True
        return {'status': 'completed', 'detail': {'result': {'outcome': 'candidate_ready'}}}

    async def capabilities(self, cwd):
        return complete_capabilities()

    def runner(self, execute=None):
        return Runner(self.github, self.workspace, host_alias='host-a',
                      execute=execute or self.execute, capabilities=self.capabilities,
                      stop_requested=lambda: self.stopped)

    def effects(self, start=0):
        return [write for write in self.github.writes[start:] if write[0] != 'record']

    def bind_dependency(self):
        self.github.work['body'] = self.github.work['body'].replace(
            f'spec = "{SPEC}"', f'spec = "{SPEC}"\ndependencies = ["https://github.com/example/dependency/issues/9"]')
        original = self.github.issue
        def issue(repo, number):
            if repo == 'example/dependency' and number == 9:
                return {'number': number, 'state': 'open' if self.dependency_open else 'closed'}
            return original(repo, number)
        self.github.issue = issue

    async def external_merge(self):
        self.github.remote_pending = True
        self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'continue')
        self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'remote_delivery_gates')
        self.github.remote_pending = False
        self.github.pr.update(merged=True, state='closed', merge_commit_sha=MERGE,
                              mergeable=None, mergeable_state='unknown')

    async def test_final_candidate_read_cannot_bypass_changed_issue_controls(self):
        for recovery in (False, True):
            for control in ('dependency', 'paused', 'stop', 'intake'):
                with self.subTest(recovery=recovery, control=control):
                    self.reset()
                    self.bind_dependency()
                    await self.external_merge()
                    if recovery:
                        self.github.note.update(pending_action='close_issue', phase='closing')
                        self.github.work['state'] = 'closed'
                    observed = 0
                    changed = False
                    original = self.github.observe
                    def observe(*args):
                        nonlocal observed, changed
                        value = original(*args)
                        observed += 1
                        if self.github.note.get('pending_action') == 'close_issue' and (not recovery or observed == 2):
                            changed = True
                            if control == 'dependency':
                                self.dependency_open = True
                            elif control == 'paused':
                                self.github.work['labels'].append({'name': self.github.cfg['labels']['paused']})
                            elif control == 'stop':
                                self.stopped = True
                            else:
                                self.github.work['body'] += '\nChanged delegated acceptance.\n'
                        return value
                    self.github.observe = observe
                    calls, writes = len(self.calls), len(self.github.writes)
                    result = await self.runner().step(REPO, NUMBER)
                    self.assertTrue(changed, 'The control must change during the final candidate read')
                    self.assertEqual(result['action'], 'waiting')
                    self.assertEqual(self.effects(writes), [])
                    self.assertEqual(len(self.calls), calls)
                    self.assertEqual(self.github.note['pending_action'], 'close_issue')
                    self.assertNotEqual(self.github.note['phase'], 'completed')
                    self.assertEqual(self.github.work['state'], 'closed' if recovery else 'open')

    async def test_status_reports_malformed_intake_without_hiding_the_next_issue(self):
        malformed = copy.deepcopy(self.github.work)
        malformed['body'] = 'Missing the required intake sections and block.'
        valid = {**copy.deepcopy(self.github.work), 'number': NUMBER + 1}
        issues = {NUMBER: malformed, NUMBER + 1: valid}
        self.github.issues = lambda repo: copy.deepcopy(list(issues.values()))
        self.github.issue = lambda repo, number: copy.deepcopy(issues[number])
        result = self.runner().status([REPO])
        self.assertEqual([item['issue'] for item in result], [NUMBER, NUMBER + 1])
        self.assertEqual(result[0]['wait_reason'], 'intake_unavailable')
        self.assertIsNone(result[1]['wait_reason'])
        self.assertEqual(self.github.writes, [])
        self.assertEqual(self.calls, [])

    async def pending_design(self):
        spec = self.workspace.path / SPEC
        spec.unlink()
        self.workspace.changed_paths = lambda *args: [SPEC]
        self.workspace.publish_failures = 1
        async def interrupted(assignment, **kwargs):
            self.assertEqual(self.github.note['pending_action'], 'design')
            spec.write_text('Scoped specification')
            self.workspace.dirty = True
            return {'status': 'interrupted', 'detail': {'cleanup': 'confirmed'}}
        self.assertEqual((await self.runner(interrupted).step(REPO, NUMBER))['action'], 'waiting')
        self.assertEqual(self.github.note['pending_action'], 'publish')
        self.assertEqual(self.github.note['resume_phase'], 'design')
        self.assertEqual(self.github.note['expected_base'], BASE)
        self.assertIsNone(self.github.branch)

    async def test_pending_design_publication_uses_its_original_base_after_main_advances(self):
        await self.pending_design()
        head = self.github.note['head']
        self.github.cfg['revision'] = 'e' * 40
        bases = []
        def changed_paths(path, base):
            bases.append(base)
            return [SPEC] if base == BASE else [SPEC, 'docs/new-on-main.md']
        self.workspace.changed_paths = changed_paths
        self.workspace.contains_base = lambda *args: False
        calls, writes = len(self.calls), len(self.github.writes)
        self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'continue')
        self.assertTrue(bases)
        self.assertEqual(set(bases), {BASE})
        self.assertEqual(self.effects(writes), [('push', head)])
        self.assertEqual(len(self.calls), calls)
        self.assertEqual(self.github.branch, head)
        self.assertIsNone(self.github.note['pending_action'])
        self.assertEqual(self.github.note['expected_base'], BASE)
        self.assertEqual(self.github.note['resume_phase'], 'design')

    async def test_invalid_recovered_design_publication_preserves_the_pending_effect(self):
        for invalid in ('extra_path', 'empty_spec'):
            with self.subTest(invalid=invalid):
                self.reset()
                await self.pending_design()
                # An older execution may already have recorded this publication
                # intent. Current validation must hold, never replace that intent.
                if invalid == 'extra_path':
                    self.workspace.changed_paths = lambda *args: [SPEC, 'src/unaccepted.py']
                else:
                    (self.workspace.path / SPEC).write_text('')
                pinned = {key: self.github.note.get(key) for key in
                          ('pending_action', 'head', 'expected_head', 'expected_base',
                           'delivery_action', 'delivery_attempt', 'delivery_head')}
                calls, writes = len(self.calls), len(self.github.writes)
                for _ in range(2):
                    result = await self.runner().step(REPO, NUMBER)
                    self.assertEqual(result['action'], 'waiting')
                    self.assertEqual(self.github.note['phase'], 'uncertain')
                    self.assertEqual({key: self.github.note.get(key) for key in pinned}, pinned)
                self.assertEqual(self.effects(writes), [])
                self.assertEqual(len(self.calls), calls)


if __name__ == '__main__':
    unittest.main()
