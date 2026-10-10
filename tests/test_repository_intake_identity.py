"""Canonical repository evidence and recoverable pinned-spec encoding failures."""

import copy
import tempfile
import unittest

from hydra_sdlc.project import ProjectError, _provider, gate_checks, load_project
from hydra_sdlc.runner import Runner, intake_digest
from test_project import BASE, BLOB, HEAD, TOML, ConfigGitHub, observation
from test_runner import GitHub, Workspace, complete_capabilities


REPO = 'example/product'
SPEC = 'docs/engineering/task/spec.md'
ACCEPTED = 'Requirement-linked specification'


class ObservedProject(ConfigGitHub):
    def __init__(self, canonical=REPO, identity=123):
        super().__init__()
        self.canonical, self.identity = canonical, identity

    def repository(self, repo):
        return {'id': self.identity, 'full_name': self.canonical, 'default_branch': 'main'}


class RepositoryPolicyTests(unittest.TestCase):
    def test_canonical_full_name_binds_actual_ci_and_provider_evidence(self):
        for canonical, alias in ((REPO, 'Example/Product'), ('Example/Product', REPO)):
            with self.subTest(canonical=canonical):
                config = load_project(ObservedProject(canonical), alias)
                self.assertEqual(config['repository'], canonical)
                value = observation()
                value['runs'][0]['jobs'][0]['check_run_url'] = value['runs'][0]['jobs'][0]['check_run_url'].replace(REPO, canonical)
                value['provider_comments'][0]['body'] = value['provider_comments'][0]['body'].replace(REPO, canonical)
                self.assertEqual(gate_checks(config, value, HEAD), [])
                self.assertEqual(_provider(config, value, HEAD), [])

    def test_foreign_or_malformed_canonical_identity_never_rebinds_policy(self):
        for canonical, identity in (('other/product', 123), (None, 123), ('example/product/extra', 123),
                                    ('example/ product', 123), (REPO, 999)):
            with self.subTest(canonical=canonical, identity=identity), self.assertRaises(ProjectError):
                load_project(ObservedProject(canonical, identity), 'Example/Product')


class IntakeIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.github = GitHub()
        self.workspace = Workspace(directory.name, self.github)
        self.calls, self.prepared, self.recorded = [], [], []
        self.github.repository = ObservedProject().repository
        self.github.api = ObservedProject().api
        original_ref = self.github.ref
        self.github.ref = lambda repo, branch: BASE if branch == 'main' else original_ref(repo, branch)
        self.github.file = lambda repo, path, revision: {
            'content': TOML if path == '.hydra.toml' else ACCEPTED,
            'sha': BLOB if path == '.hydra.toml' else HEAD}
        self.github.cfg = load_project(self.github, REPO)
        original_prepare = self.workspace.prepare
        def prepare(repo, *args, **kwargs):
            self.prepared.append(repo)
            return original_prepare(repo, *args, **kwargs)
        self.workspace.prepare = prepare
        original_record = self.github.record
        def record(repo, *args):
            self.recorded.append(repo)
            return original_record(repo, *args)
        self.github.record = record

    async def execute(self, assignment, **kwargs):
        self.calls.append(self.github.note['pending_action'])
        if assignment['mode'] == 'workspace_write':
            self.workspace.dirty = True
        return {'status': 'completed', 'detail': {'result': {'outcome': 'candidate_ready'}}}

    async def capabilities(self, cwd):
        return complete_capabilities()

    def runner(self):
        return Runner(self.github, self.workspace, host_alias='host-a', execute=self.execute,
                      capabilities=self.capabilities)

    def pinned_spec(self, content):
        self.github.work['body'] = self.github.work['body'].replace('spec = ', f'spec_revision = "{BASE}"\nspec = ')
        (self.workspace.path / SPEC).write_bytes(content)

    async def test_alias_step_uses_one_canonical_workspace_review_and_effect_identity(self):
        runner = self.runner()
        self.assertEqual((await runner.step('Example/Product', 4))['action'], 'continue')
        self.github.remote_pending = True
        self.assertEqual((await runner.step('EXAMPLE/PRODUCT', 4))['reason'], 'remote_delivery_gates')
        self.assertEqual(self.calls.count('spec_review'), 1)
        self.assertEqual(set(self.prepared), {REPO})
        self.assertEqual(set(self.recorded), {REPO})
        self.assertTrue(runner.accepted_specs)
        self.assertTrue(runner.verified_heads)
        self.assertTrue(all(key[0] == REPO for key in runner.accepted_specs))
        self.assertTrue(all(key[0] == REPO for key in runner.verified_heads))

    async def test_cycle_and_read_only_status_deduplicate_alias_intake(self):
        original = self.github.issues
        acquired = []
        def issues(repo):
            acquired.append(repo)
            return original(repo)
        self.github.issues = issues
        runner = self.runner()
        aliases = ['Example/Product', REPO, 'EXAMPLE/PRODUCT']
        status = runner.status(aliases)
        self.assertEqual(len(status), 1)
        self.assertEqual(status[0]['repository'], REPO)
        self.assertEqual(len(acquired), 1)
        self.assertEqual(self.github.writes, [])
        acquired.clear()
        result = await runner.cycle(aliases)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['repository'], REPO)
        self.assertEqual(self.calls.count('implementation'), 1)
        self.assertEqual(len(acquired), 1)
        self.assertEqual(set(self.prepared), {REPO})

    async def test_invalid_pinned_utf8_diagnoses_across_restart_without_replacing_artifact(self):
        content = b'\xff\xfepinned artifact'
        self.pinned_spec(content)
        delegated = copy.deepcopy(self.github.work)
        result = await self.runner().step('Example/Product', 4)
        self.assertEqual(result['reason'], 'replan_required')
        self.assertEqual(self.github.note['next_action'], 'diagnose_spec_artifact')
        self.assertEqual(self.github.note['intake_digest'], intake_digest(delegated))
        for _ in range(2):
            result = (await self.runner().cycle([REPO]))[0]
            self.assertEqual(result['reason'], 'replan_required')
            self.assertEqual(self.github.note['next_action'], 'diagnose_spec_artifact')
        self.assertEqual((self.workspace.path / SPEC).read_bytes(), content)
        self.assertEqual(self.github.work, delegated)
        self.assertEqual(self.calls, [])
        self.assertTrue(all(write[0] == 'record' for write in self.github.writes))

    async def test_restored_accepted_bytes_still_require_authorized_replan_and_independent_review(self):
        self.pinned_spec(b'\xffinvalid')
        self.assertEqual((await self.runner().step(REPO, 4))['reason'], 'replan_required')
        attempt = self.github.note['attempt_id']
        (self.workspace.path / SPEC).write_bytes(ACCEPTED.encode('utf-8'))
        self.assertEqual((await self.runner().step(REPO, 4))['reason'], 'replan_required')
        self.assertEqual(self.calls, [])
        self.github.extra_comments.append({'user': {'login': 'operator'},
            'body': f'hydra: replan {attempt} ready'})
        self.assertEqual((await self.runner().step(REPO, 4))['action'], 'continue')
        self.assertEqual(self.calls, ['spec_review', 'implementation'])
        self.assertEqual((self.workspace.path / SPEC).read_text(), ACCEPTED)

    async def test_valid_utf8_mismatch_keeps_existing_accepted_content_hold(self):
        self.pinned_spec('Different valid text'.encode('utf-8'))
        self.assertEqual((await self.runner().step(REPO, 4))['reason'], 'accepted_spec_content_changed')
        self.assertEqual(self.calls, [])
        self.assertTrue(all(write[0] == 'record' for write in self.github.writes))
        self.assertEqual((self.workspace.path / SPEC).read_text(), 'Different valid text')
