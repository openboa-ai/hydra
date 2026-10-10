"""Service scope follows the genuine objects sent by Git pack transfer."""

import copy
import os
import subprocess
import unittest
from unittest.mock import patch

from hydra_sdlc import workspace as workspace_module
from hydra_sdlc.runner import Runner, intake_digest
from hydra_sdlc.workspace import _environment
from test_runner import GitHub
import test_service_git as service_git_fixtures
from test_workspace import git


def fixture_for(test, layout):
    owner = service_git_fixtures.ServiceGitIsolationTests()
    owner.setUp()
    test.addCleanup(owner.doCleanups)
    return owner.checkout(layout)


def replacement_trap(fixture, *, packed):
    # The forged base already contains the excluded file, so an ordinary diff
    # against that replacement incorrectly reports only the allowed file.
    for path in (fixture.path, fixture.seed):
        (path / 'outside.txt').write_text('Synthetic excluded content\n')
    (fixture.path / 'candidate.txt').write_text('Allowed candidate content\n')
    git(fixture.path, 'add', '.')
    git(fixture.path, 'commit', '-m', 'Actual candidate with excluded path')
    head = git(fixture.path, '--no-replace-objects', 'rev-parse', 'HEAD')
    git(fixture.seed, 'add', 'outside.txt')
    git(fixture.seed, 'commit', '-m', 'Replacement baseline')
    replacement = git(fixture.seed, 'rev-parse', 'HEAD')
    git(fixture.path, 'fetch', str(fixture.seed), replacement)
    git(fixture.path, 'replace', fixture.base, replacement)
    if packed:
        git(fixture.path, 'pack-refs', '--all', '--prune')
    return head


class ReplacementScopeTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_replacement_refs_cannot_hide_paths_before_runner_publication(self):
        for layout in ('standalone', 'linked'):
            for packed in (False, True):
                with self.subTest(layout=layout, packed=packed):
                    fixture = fixture_for(self, layout)
                    head = replacement_trap(fixture, packed=packed)
                    reference = (fixture.common / 'packed-refs' if packed else
                                 fixture.common / 'refs/replace' / fixture.base)
                    before = reference.read_bytes()
                    # Demonstrate that this is a real Git replacement trap,
                    # independently of the service's command/environment policy.
                    env = _environment()
                    env.pop('GIT_NO_REPLACE_OBJECTS', None)
                    forged = subprocess.check_output(
                        ['git', 'diff', '--name-only', fixture.base, '--'],
                        cwd=fixture.path, env=env).decode().splitlines()
                    self.assertEqual(forged, ['candidate.txt'])
                    self.assertEqual(fixture.workspace.changed_paths(fixture.path, fixture.base),
                                     ['candidate.txt', 'outside.txt'])
                    self.assertEqual(fixture.workspace.inspect(fixture.path)['head'], head)
                    self.assertTrue(fixture.workspace.contains_base(fixture.path, fixture.base))

                    github = GitHub()
                    github.cfg.update(repository='example/project', revision=fixture.base,
                                      allowed_paths=['candidate.txt', 'docs/'])
                    github.work['number'] = 1
                    github.note = dict(attempt_id='00000000-0000-4000-8000-000000000001',
                                       host_alias='test-host', contract_revision=fixture.base,
                                       branch='hydra/issue-1', head=head, expected_head=None,
                                       expected_base=fixture.base, pending_action='publish',
                                       phase='uncertain', intake_digest=intake_digest(github.work))
                    async def forbidden(*args, **kwargs):
                        self.fail('Scope recovery must not dispatch a model or capability probe')
                    runner = Runner(github, fixture.workspace, host_alias='test-host',
                                    execute=forbidden, capabilities=forbidden)
                    with patch('hydra_sdlc.runner.load_project',
                               side_effect=lambda *args, **kwargs: copy.deepcopy(github.cfg)), \
                            patch.object(fixture.workspace, 'publish', wraps=fixture.workspace.publish) as publish:
                        result = await runner.step('example/project', 1)
                    self.assertEqual((result['action'], result['reason']), ('waiting', 'scope_changed'))
                    publish.assert_not_called()
                    self.assertEqual(github.note['pending_action'], 'publish')
                    self.assertEqual(github.note['head'], head)
                    self.assertFalse(any(write[0] != 'record' for write in github.writes))
                    self.assertIsNone(fixture.workspace._remote_sha(fixture.path, 'hydra/issue-1'))
                    self.assertEqual(reference.read_bytes(), before)


class ServiceGitInvocationTests(unittest.TestCase):
    def test_every_service_git_invocation_ignores_inherited_replacement_settings(self):
        original, commands = workspace_module._run, []
        def invoke(argv, cwd, timeout, env=None, **kwargs):
            self.assertEqual(argv[:2], ['git', '--no-replace-objects'])
            self.assertEqual(env.get('GIT_NO_REPLACE_OBJECTS'), '1')
            self.assertNotIn('GIT_REPLACE_REF_BASE', env)
            commands.append(list(argv))
            return original(argv, cwd, timeout, env, **kwargs)
        with patch.dict(os.environ, {'GIT_NO_REPLACE_OBJECTS': '0',
                                     'GIT_REPLACE_REF_BASE': 'refs/untrusted-replacements'}), \
                patch('hydra_sdlc.workspace._run', side_effect=invoke):
            fixture = fixture_for(self, 'standalone')
            (fixture.path / 'candidate.txt').write_text('Ordinary allowed content\n')
            self.assertEqual(fixture.workspace.changed_paths(fixture.path, fixture.base), ['candidate.txt'])
            head = fixture.workspace.checkpoint(fixture.path, 'Ordinary candidate')
            self.assertEqual(fixture.workspace.publish(fixture.path, 'hydra/issue-1', None), head)
            self.assertEqual(fixture.workspace.inspect(fixture.path)['remote_sha'], head)
        # Include early metadata reads/writes and preflight, not only dispatch.
        self.assertTrue(any('config' in argv and '--list' in argv for argv in commands))
        self.assertTrue(any('config' in argv and '--replace-all' in argv for argv in commands))
        self.assertTrue(any('ls-files' in argv and '--stage' in argv for argv in commands))
        for command in ('clone', 'diff', 'commit', 'push', 'ls-remote', 'rev-parse'):
            self.assertTrue(any(command in argv for argv in commands), command)


if __name__ == '__main__':
    unittest.main()
