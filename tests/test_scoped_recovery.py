"""Preparatory integration and scoped correction retain the work they precede."""

import copy
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc.runner import Runner
from test_project import BASE
from test_runner import GitHub, Workspace, complete_capabilities


class ScopedRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.github = GitHub()
        self.workspace = Workspace(self.directory.name, self.github)
        self.prompts = []
        self.used = 10
        self.integrated = True
        self.paths = ['src/main.py']
        self.restore_scope = True
        self.workspace.contains_base = lambda path, sha: self.integrated
        self.workspace.changed_paths = lambda path, sha: self.paths[:]
        load = patch('hydra_sdlc.runner.load_project', side_effect=lambda gh, repo: copy.deepcopy(gh.cfg))
        load.start()
        self.addCleanup(load.stop)

    async def capabilities(self, cwd):
        return complete_capabilities(self.used)

    async def execute(self, assignment, **kwargs):
        prompt = assignment['prompt']
        self.prompts.append(prompt)
        if assignment['mode'] == 'workspace_write':
            self.workspace.dirty = True
            if prompt.startswith('Resolve integration_changed'):
                self.integrated = True
            if prompt.startswith('Resolve scope_changed') and self.restore_scope:
                self.paths = ['src/main.py']
        return {'status': 'completed', 'detail': {'result': {'outcome': 'candidate_ready'}}}

    def runner(self):
        return Runner(self.github, self.workspace, host_alias='host-a', execute=self.execute,
                      capabilities=self.capabilities)

    async def step(self):
        return await self.runner().step('example/product', 4)

    def effects(self):
        return [x for x in self.github.writes if x[0] in {'push', 'pr', 'merge', 'close'}]

    async def test_integration_before_first_implementation_preserves_original_phase(self):
        self.integrated = False
        self.assertEqual((await self.step())['action'], 'continue')
        self.assertEqual(self.github.note['phase'], 'ready')
        self.assertEqual(len(self.prompts), 1)
        self.assertTrue(self.prompts[0].startswith('Resolve integration_changed'))
        self.assertEqual(self.effects(), [])

        self.assertEqual((await self.step())['action'], 'continue')
        self.assertTrue(self.prompts[1].startswith('Independently review the ACTUAL specification'))
        self.assertTrue(self.prompts[2].startswith('Implement the accepted specification'))
        self.assertEqual(self.github.note['phase'], 'implementation_done')
        self.assertEqual(self.workspace.verification_calls, 0)
        self.assertEqual(self.effects(), [])

    async def test_low_usage_before_first_implementation_survives_later_integration(self):
        self.used = 90
        self.assertEqual((await self.step())['reason'], 'usage_unavailable_or_low')
        self.assertEqual(self.prompts, [])
        self.used = 10
        self.github.cfg['revision'] = 'e' * 40
        self.integrated = False
        self.assertEqual((await self.step())['action'], 'continue')
        self.assertEqual(self.github.note['resume_phase'], 'implementation')
        self.assertEqual((await self.step())['action'], 'continue')
        self.assertTrue(self.prompts[-2].startswith('Independently review the ACTUAL specification'))
        self.assertTrue(self.prompts[-1].startswith('Implement the accepted specification'))
        self.assertEqual(self.effects(), [])

    async def test_completed_implementation_is_not_repeated_after_integration(self):
        await self.step()
        self.integrated = False
        self.assertEqual((await self.step())['action'], 'continue')
        self.assertEqual(self.github.note['phase'], 'implementation_done')
        self.assertEqual((await self.step())['action'], 'continue')
        self.assertEqual(sum(p.startswith('Implement the accepted specification') for p in self.prompts), 1)
        self.assertEqual(self.workspace.verification_calls, 1)
        self.assertEqual([x[0] for x in self.effects()], ['push', 'pr', 'merge'])

    async def test_unpublished_scope_violation_is_corrected_before_verification_and_publication(self):
        await self.step()
        self.paths.append('unintended.txt')
        original_config = copy.deepcopy(self.github.cfg)
        self.assertEqual((await self.step())['action'], 'continue')
        prompt = self.prompts[-1]
        self.assertTrue(prompt.startswith('Resolve scope_changed'))
        self.assertIn('unintended.txt', prompt)
        self.assertIn(BASE, prompt)
        self.assertIn('do not broaden policy or delete unrelated work', prompt)
        self.assertEqual(self.paths, ['src/main.py'])
        self.assertEqual(self.github.cfg, original_config)
        self.assertEqual(self.workspace.verification_calls, 0)
        self.assertEqual(self.effects(), [])

        corrected_head = self.github.note['head']
        self.assertEqual((await self.step())['action'], 'continue')
        self.assertEqual(self.workspace.verification_calls, 1)
        self.assertIn(('push', corrected_head), self.effects())

    async def test_scope_correction_exhaustion_preserves_actionable_replan(self):
        await self.step()
        self.paths.append('unintended.txt')
        self.restore_scope = False
        for _ in range(2):
            self.assertEqual((await self.step())['action'], 'continue')
        self.assertEqual((await self.step())['reason'], 'replan_required')
        self.assertEqual(self.github.note['resume_phase'], 'correction')
        count = len(self.prompts)
        self.assertEqual((await self.step())['reason'], 'replan_required')
        self.assertEqual(len(self.prompts), count)
        self.assertEqual(self.effects(), [])

        self.github.extra_comments.append({'user': {'login': 'operator'},
            'body': f"hydra: replan {self.github.note['attempt_id']} ready"})
        self.restore_scope = True
        self.assertEqual((await self.step())['action'], 'continue')
        self.assertTrue(self.prompts[-1].startswith('Resolve scope_changed'))
        self.assertEqual(self.paths, ['src/main.py'])
        self.assertEqual(self.effects(), [])

    async def test_usage_wait_before_scope_correction_preserves_reason_without_consuming_retry(self):
        runner = self.runner()
        await runner.step('example/product', 4)
        self.paths.append('unintended.txt')
        self.used = 90
        for _ in range(3):
            self.assertEqual((await runner.step('example/product', 4))['reason'], 'usage_unavailable_or_low')
            self.assertEqual(self.github.note['correction_reason'], 'scope_changed')
            self.assertIsNone(self.github.note['correction_attempt'])
        self.used = 10
        self.assertEqual((await self.step())['action'], 'continue')
        self.assertTrue(self.prompts[-1].startswith('Resolve scope_changed'))
        self.assertIn('unintended.txt', self.prompts[-1])
        self.assertEqual(self.github.note['correction_attempt'], 1)
        self.assertEqual(self.paths, ['src/main.py'])
        self.assertEqual(self.effects(), [])

    async def test_uncertain_publication_scope_failure_never_dispatches_correction(self):
        await self.step()
        self.github.note.update(pending_action='publish', expected_head=None, expected_base=BASE)
        self.paths.append('unintended.txt')
        count = len(self.prompts)
        for _ in range(2):
            self.assertEqual((await self.step())['reason'], 'scope_changed')
            self.assertEqual(self.github.note['pending_action'], 'publish')
        self.assertEqual(len(self.prompts), count)
        self.assertEqual(self.effects(), [])


if __name__ == '__main__':
    unittest.main()
