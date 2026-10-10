"""A pre-dispatch wait never establishes ownership of a remote issue branch."""

import copy
import tempfile
import unittest
from unittest.mock import Mock, patch

from hydra_sdlc.runner import Runner
from test_project import BASE, HEAD, observation
from test_runner import GitHub, Workspace, complete_capabilities


REPO = 'example/product'
NUMBER = 4
DEPENDENCY = 9
EFFECTS = {'push', 'pr', 'merge', 'close', 'resolve_thread', 'request_review'}


class BranchRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.github = GitHub()
        self.workspace = Workspace(self.directory.name, self.github)
        self.workspace_calls = {}
        for name in ('prepare', 'fetch_base', 'inspect', 'checkpoint', 'changed_paths',
                     'verify', 'publish', 'contains_base', 'valid_spec', 'read_spec'):
            method = Mock(wraps=getattr(self.workspace, name))
            self.workspace_calls[name] = method
            setattr(self.workspace, name, method)
        self.model_calls = []
        self.capability_calls = []
        self.used_percent = 10
        self.dependency_state = 'open'
        original_issue = self.github.issue

        def issue(repo, number):
            if repo == REPO and number == DEPENDENCY:
                return {'number': number, 'state': self.dependency_state}
            return original_issue(repo, number)

        self.github.issue = issue
        policy = patch('hydra_sdlc.runner.load_project',
                       side_effect=lambda gh, repo, revision=None: copy.deepcopy(gh.cfg))
        policy.start()
        self.addCleanup(policy.stop)

    async def execute(self, assignment, **kwargs):
        self.model_calls.append(copy.deepcopy(assignment))
        return {'status': 'completed', 'detail': {'result': {
            'outcome': 'candidate_ready', 'summary': '', 'evidence': [], 'next_action': '',
        }}}

    async def capabilities(self, cwd):
        self.capability_calls.append(cwd)
        return complete_capabilities(self.used_percent)

    def runner(self):
        return Runner(self.github, self.workspace, host_alias='host-a',
                      execute=self.execute, capabilities=self.capabilities)

    def add_dependency(self):
        self.github.work['body'] = self.github.work['body'].replace(
            '\n```hydra\n',
            f'\n```hydra\ndependencies = ["https://github.com/{REPO}/issues/{DEPENDENCY}"]\n')

    def call_counts(self):
        return {name: method.call_count for name, method in self.workspace_calls.items()}

    async def assert_foreign_untouched(self):
        remote = self.github.branch
        pr = copy.deepcopy(self.github.pr)
        head = self.workspace.head
        files = {str(path.relative_to(self.workspace.path)): path.read_bytes()
                 for path in self.workspace.path.rglob('*') if path.is_file()}
        calls = self.call_counts()
        capabilities = len(self.capability_calls)
        models = len(self.model_calls)
        for _ in range(2):
            result = await self.runner().step(REPO, NUMBER)
            self.assertEqual(result['action'], 'waiting')
            self.assertEqual(self.call_counts(), calls,
                             'A progress-only wait must not authorize workspace preparation or inspection')
            self.assertEqual(len(self.capability_calls), capabilities)
            self.assertEqual(len(self.model_calls), models)
            self.assertEqual(self.github.branch, remote)
            self.assertEqual(self.github.pr, pr)
            self.assertEqual(self.workspace.head, head)
            self.assertEqual({str(path.relative_to(self.workspace.path)): path.read_bytes()
                              for path in self.workspace.path.rglob('*') if path.is_file()}, files)
            self.assertFalse(any(item[0] in EFFECTS for item in self.github.writes))
            if self.github.note is not None:
                self.assertIsNone(self.github.note.get('head'))

    async def test_existing_foreign_branch_stays_foreign_after_dependency_closes(self):
        self.add_dependency()
        self.github.branch = HEAD
        result = await self.runner().step(REPO, NUMBER)
        self.assertEqual(result['action'], 'waiting')
        self.assertIn(result['reason'], {'foreign_branch', 'dependency_open'})
        self.assertTrue(all(count == 0 for count in self.call_counts().values()))
        self.assertEqual(self.capability_calls, [])
        self.assertEqual(self.model_calls, [])
        self.dependency_state = 'closed'
        await self.assert_foreign_untouched()

    async def test_branch_appearing_during_dependency_wait_is_not_adopted(self):
        self.add_dependency()
        result = await self.runner().step(REPO, NUMBER)
        self.assertEqual(result['reason'], 'dependency_open')
        self.assertIsNone(self.github.note['head'])
        self.assertTrue(all(count == 0 for count in self.call_counts().values()))
        self.github.branch = HEAD
        self.dependency_state = 'closed'
        await self.assert_foreign_untouched()

    async def test_branch_appearing_during_usage_wait_is_not_prepared(self):
        self.used_percent = 81
        result = await self.runner().step(REPO, NUMBER)
        self.assertEqual(result['reason'], 'usage_unavailable_or_low')
        self.assertIsNone(self.github.note['head'])
        self.assertEqual(self.workspace_calls['prepare'].call_count, 1)
        self.assertEqual(self.model_calls, [])
        self.assertEqual(self.workspace.head, BASE)
        self.github.branch = HEAD
        self.used_percent = 10
        await self.assert_foreign_untouched()

    async def test_foreign_pr_appearing_during_dependency_wait_is_preserved(self):
        self.add_dependency()
        self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'dependency_open')
        self.github.branch = HEAD
        self.github.pr = observation()['pr']
        self.github.pr.update(user={'login': 'another-actor'}, body='Unrelated work')
        self.dependency_state = 'closed'
        await self.assert_foreign_untouched()

    async def test_unpublished_local_head_does_not_own_foreign_branch_at_same_base(self):
        result = await self.runner().step(REPO, NUMBER)
        self.assertEqual(result['action'], 'continue')
        self.assertEqual(self.github.note['head'], BASE)
        self.assertIsNone(self.github.branch)
        self.assertIsNone(self.github.pr)
        self.assertFalse(any(item[0] in EFFECTS for item in self.github.writes))
        self.github.branch = BASE
        calls = self.call_counts()
        models = len(self.model_calls)
        for _ in range(2):
            result = await self.runner().step(REPO, NUMBER)
            self.assertEqual(result['action'], 'waiting')
            self.assertEqual(self.call_counts(), calls)
            self.assertEqual(len(self.model_calls), models)
            self.assertEqual(self.github.note['head'], BASE)
            self.assertEqual(self.github.branch, BASE)
            self.assertIsNone(self.github.pr)
            self.assertFalse(any(item[0] in EFFECTS for item in self.github.writes))

    async def test_branch_appearing_after_initial_read_is_rechecked_before_prepare(self):
        reads = []

        def ref(repo, branch):
            reads.append(branch)
            if len(reads) > 1:
                self.github.branch = HEAD
            return self.github.branch

        self.github.ref = ref
        result = await self.runner().step(REPO, NUMBER)
        self.assertEqual(result['action'], 'waiting')
        self.assertGreaterEqual(len(reads), 2)
        self.assertTrue(all(count == 0 for count in self.call_counts().values()))
        self.assertEqual(self.capability_calls, [])
        self.assertEqual(self.model_calls, [])
        self.assertEqual(self.github.branch, HEAD)
        self.assertIsNone(self.github.pr)
        self.assertFalse(any(item[0] in EFFECTS for item in self.github.writes))

    async def late_owned_ref_change(self, *, recovery, advanced):
        self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'continue')
        self.github.remote_pending = True
        self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'remote_delivery_gates')
        self.assertTrue(self.github.owns_pr(REPO, NUMBER, self.github.pr))
        previous = self.github.branch
        self.github.note.update(phase='executing' if recovery else 'implementation_done',
                                pending_action='implementation' if recovery else None,
                                expected_head=previous)
        if recovery:
            self.workspace.dirty = True
            pending = self.workspace.path / 'src/main.py'
            pending.parent.mkdir(parents=True, exist_ok=True)
            pending.write_bytes(b'preserve stopped implementation\n')
            self.github.extra_comments.append({'user': {'login': 'operator'},
                'body': f"hydra: handover {self.github.note['attempt_id']} stopped"})
        files = {str(path.relative_to(self.workspace.path)): path.read_bytes()
                 for path in self.workspace.path.rglob('*') if path.is_file()}
        reads = []

        def ref(repo, branch):
            reads.append(branch)
            # The initial acquisition and existing-head checks both see the
            # recorded ref. Only the final pre-prepare observation changes.
            if len(reads) == 3:
                self.github.branch = advanced
                if advanced is not None:
                    self.github.pr['head']['sha'] = advanced
            return self.github.branch

        self.github.ref = ref
        calls, models, capabilities = self.call_counts(), len(self.model_calls), len(self.capability_calls)
        writes = len(self.github.writes)
        result = await self.runner().step(REPO, NUMBER)
        self.assertEqual(result['reason'], 'remote_head_changed')
        self.assertEqual(len(reads), 3)
        self.assertEqual(self.call_counts(), calls)
        self.assertEqual(len(self.model_calls), models)
        self.assertEqual(len(self.capability_calls), capabilities)
        self.assertEqual(self.github.note['head'], previous)
        self.assertEqual(self.github.note['expected_head'], previous)
        self.assertEqual(self.workspace.head, previous)
        self.assertEqual(self.workspace.dirty, recovery)
        self.assertEqual(self.github.branch, advanced)
        self.assertEqual({str(path.relative_to(self.workspace.path)): path.read_bytes()
                          for path in self.workspace.path.rglob('*') if path.is_file()}, files)
        self.assertFalse(any(item[0] in EFFECTS for item in self.github.writes[writes:]))

    async def test_owned_pr_late_ref_advance_is_rejected_before_prepare(self):
        await self.late_owned_ref_change(recovery=False, advanced=HEAD)

    async def test_stopped_recovery_late_ref_advance_is_not_prepared_or_stamped(self):
        await self.late_owned_ref_change(recovery=True, advanced=HEAD)

    async def test_stopped_recovery_late_ref_disappearance_is_not_prepared_or_stamped(self):
        await self.late_owned_ref_change(recovery=True, advanced=None)


if __name__ == '__main__':
    unittest.main()
