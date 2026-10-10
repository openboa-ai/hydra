"""Native Git filenames stay local when remote path validation rejects them."""

import copy
import hashlib
import unittest
from unittest.mock import patch

from hydra_sdlc.project import _path, matches
from hydra_sdlc.runner import Runner, intake_digest
from test_runner import GitHub, complete_capabilities
import test_service_git as service_git_fixtures
from test_workspace import git


class ControlCharacterPathTests(unittest.IsolatedAsyncioTestCase):
    def fixture(self):
        owner = service_git_fixtures.ServiceGitIsolationTests()
        owner.setUp()
        self.addCleanup(owner.doCleanups)
        return owner.checkout('standalone')

    def test_local_control_character_rule_matches_remote_validation(self):
        for codepoint in range(32):
            name = f'src/before{chr(codepoint)}after.py'
            with self.subTest(codepoint=codepoint):
                self.assertFalse(_path(name))
                self.assertFalse(matches(name, ['src/**']))
        for name in ('src/ordinary.py', 'src/space name.py', 'src/café.py', 'src/del\x7f.py'):
            with self.subTest(name=name):
                self.assertTrue(_path(name))
                self.assertTrue(matches(name, ['src/**']))

    def test_actual_git_control_paths_preserve_untracked_staged_and_rename_bytes(self):
        fixture = self.fixture()
        root, workspace = fixture.path, fixture.workspace
        (root / 'src').mkdir()
        old, renamed = 'src/before\tname.py', 'src/after\nname.py'
        (root / old).write_bytes(b'Exact rename bytes\n')
        base = workspace.checkpoint(root, 'Track native control-character filename')
        git(root, 'mv', '--', old, renamed)
        untracked = 'src/untracked\tname.py'
        (root / untracked).write_bytes(b'Exact untracked bytes\n')
        index = (root / '.git/index').read_bytes()
        paths = workspace.changed_paths(root, base)
        self.assertEqual(set(paths), {old, renamed, untracked})
        self.assertTrue(all(not matches(path, ['src/**']) for path in paths))
        self.assertEqual((root / '.git/index').read_bytes(), index)
        self.assertEqual(workspace.inspect(root)['head'], base)
        self.assertEqual((root / renamed).read_bytes(), b'Exact rename bytes\n')
        self.assertEqual((root / untracked).read_bytes(), b'Exact untracked bytes\n')
        self.assertIsNone(workspace._remote_sha(root, 'hydra/issue-1'))

    async def test_actual_runner_corrects_checkpointed_control_paths_before_publish(self):
        fixture = self.fixture()
        root, workspace = fixture.path, fixture.workspace
        spec = 'docs/engineering/task/spec.md'
        (root / spec).parent.mkdir(parents=True)
        content = b'Requirement-linked accepted specification\n'
        (root / spec).write_bytes(content)
        head = workspace.checkpoint(root, 'Prepare owned specification')
        github = GitHub()
        github.cfg.update(repository='example/project', revision=fixture.base,
                          allowed_paths=['src/**', 'docs/'])
        github.work['number'] = 1
        github.note = dict(attempt_id='00000000-0000-4000-8000-000000000001',
                           host_alias='test-host', contract_revision=fixture.base,
                           branch='hydra/issue-1', head=head, expected_head=None,
                           phase='ready', pending_action=None,
                           intake_digest=intake_digest(github.work))
        names = ('src/line\nbreak.py', 'src/tab\tname.py')
        original = {name: ('Preserve ' + name).encode('utf-8') for name in names}
        phases, prompts = [], []

        async def capabilities(cwd):
            return complete_capabilities()

        async def execute(assignment, **kwargs):
            phase = github.note['pending_action']
            phases.append(phase)
            prompts.append(assignment['prompt'])
            if phase == 'implementation':
                (root / 'src').mkdir()
                for name, data in original.items():
                    (root / name).write_bytes(data)
                self.assertTrue(set(names).issubset(workspace.changed_paths(root, fixture.base)))
                outcome = 'candidate_ready'
            else:
                self.assertEqual(phase, 'correction')
                outcome = 'needs_decision'
            return {'status': 'completed', 'detail': {'result': {'outcome': outcome}}}

        runner = Runner(github, workspace, host_alias='test-host', execute=execute,
                        capabilities=capabilities)
        runner.accepted_specs[('example/project', 1, hashlib.sha256(content).hexdigest())] = True
        with patch('hydra_sdlc.runner.load_project', side_effect=lambda *args, **kwargs: copy.deepcopy(github.cfg)), \
                patch.object(workspace, 'publish', wraps=workspace.publish) as publish, \
                patch.object(workspace, 'verify', wraps=workspace.verify) as verify:
            self.assertEqual((await runner.step('example/project', 1))['action'], 'continue')
            self.assertEqual(github.note['phase'], 'implementation_done')
            result = await runner.step('example/project', 1)
            self.assertEqual(result['reason'], 'product_decision')
            publish.assert_not_called()
            verify.assert_not_called()
        self.assertEqual(phases, ['implementation', 'correction'])
        self.assertTrue(prompts[-1].startswith('Resolve scope_changed'))
        self.assertIn('src/line\\nbreak.py', prompts[-1])
        self.assertIn('src/tab\\tname.py', prompts[-1])
        self.assertEqual(github.note['correction_reason'], 'scope_changed')
        self.assertEqual(github.note['resume_phase'], 'correction')
        self.assertTrue(all(write[0] == 'record' for write in github.writes))
        self.assertFalse(workspace.inspect(root)['dirty'])
        self.assertIsNone(workspace._remote_sha(root, 'hydra/issue-1'))
        for name, data in original.items():
            self.assertEqual((root / name).read_bytes(), data)


if __name__ == '__main__':
    unittest.main()
