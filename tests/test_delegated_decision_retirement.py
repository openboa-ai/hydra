"""The final recovery read must retain the original mutable-result identity."""
import copy
from contextlib import contextmanager
import unittest
from unittest.mock import patch

from hydra_sdlc.continuation_commands import ContinuationScope
from hydra_sdlc.github import GitHubError
from delegated_decision_fixture import REPO, InstallationFixture


class DelegatedRetirementTests(InstallationFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.setup_installation()
        self.write_profile(True)
        self.make_server(new_profile=True)
        published = self.reply(await self.invoke())
        self.assertEqual(published['request']['outcome'], 'applied', published)
        intended = []
        def lose(body):
            intended.append(body)
            raise GitHubError('Fixture lost original resume response', uncertain=True)
        self.transport.patch_behavior = lose
        first = self.reply(await self.invoke(self.command(
            continuation=True, reply_profile='standard_v1')))
        self.assertNotEqual(first['request']['outcome'], 'applied', first)
        self.assertEqual(len(intended), 1)
        self.owner = self.controller.lock_path.read_bytes()
        self.assertTrue(self.owner)
        self.transport.rows[0]['body'] = intended[0]
        self.transport.direct[1] = copy.deepcopy(self.transport.rows[0])
        self.original = copy.deepcopy(self.transport.rows[0])
        self.effects = copy.deepcopy(self.transport.effects)
        self.make_server(new_profile=True)

    async def recover_with_final_read(self, *, replace_original):
        inside_guard, witnessed = [False], []
        actual_guard = ContinuationScope.guard
        @contextmanager
        def guarded(scope, *args, **kwargs):
            previous = inside_guard[0]
            inside_guard[0] = True
            try:
                # Run the actual source/grant/admission guard. Only external
                # comment visibility changes while its final source read runs.
                with actual_guard(scope, *args, **kwargs):
                    yield
            finally:
                inside_guard[0] = previous
        def on_read(path):
            if (inside_guard[0] and not witnessed
                    and path.startswith(f'/repos/{REPO}/issues/4/comments?')):
                witnessed.append(copy.deepcopy(self.transport.direct[1]))
                if replace_original:
                    replacement = {**copy.deepcopy(self.original), 'id': 77}
                    self.transport.rows = [replacement if row['id'] == 1 else row
                                           for row in self.transport.rows]
                    self.transport.direct[77] = copy.deepcopy(replacement)
                    self.transport.direct[1] = GitHubError('Fixture original disappeared', status=404)
        self.transport.before_read = on_read
        try:
            command = self.command(continuation=True, reply_profile='standard_v1')
            with patch.object(ContinuationScope, 'guard', new=guarded):
                result = self.reply(await self.invoke(command))
        finally:
            self.transport.before_read = lambda path: None
        self.assertEqual(len(witnessed), 1,
            'The source change must occur in the final guard, after earlier exact recovery observations')
        self.assertEqual(witnessed[0], self.original)
        return result

    async def test_same_bytes_replacement_at_final_guard_cannot_retire_original_owner(self):
        result = await self.recover_with_final_read(replace_original=True)
        self.assertNotEqual(result['request']['outcome'], 'applied', result)
        self.assertIsNone(result.get('handoff'))
        self.assertEqual(self.controller.lock_path.read_bytes(), self.owner,
            'A byte-identical replacement comment is not the original PATCH result')
        self.assertEqual(self.transport.effects, self.effects,
            'The uncertain mutable write cannot be retried or followed by assignment')
        self.assertEqual(self.transport.direct[77]['body'], self.original['body'])

    async def test_exact_original_at_final_guard_retires_without_another_write(self):
        result = await self.recover_with_final_read(replace_original=False)
        self.assertEqual(result['request']['outcome'], 'applied', result)
        self.assertEqual(result['request']['receipt']['boundary'], 'existing_result_reconciled')
        self.assertEqual(result['request']['receipt']['progress_ref'],
            {'source': 'github', 'kind': 'issue_comment', 'id': REPO + '/comments/1'})
        self.assertIsNone(result.get('handoff'))
        self.assertEqual(self.transport.effects, self.effects)
        self.assertEqual(self.controller.lock_path.read_bytes(), b'')
