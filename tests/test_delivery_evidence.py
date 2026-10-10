"""Final effects and completion require current, bound delivery evidence."""

import copy
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc.runner import Runner
from test_project import BASE, HEAD, MERGE, summary
from test_runner import GitHub, Workspace, complete_capabilities


REPO, NUMBER = 'example/product', 4
SPEC = 'docs/engineering/task/spec.md'


class DeliveryEvidenceTests(unittest.IsolatedAsyncioTestCase):
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
                      execute=execute or self.execute, capabilities=self.capabilities)

    async def step(self, execute=None):
        return await self.runner(execute).step(REPO, NUMBER)

    async def opened_pr(self):
        self.github.remote_pending = True
        self.assertEqual((await self.step())['action'], 'continue')
        self.assertEqual((await self.step())['reason'], 'remote_delivery_gates')
        self.github.remote_pending = False

    def effects(self, start=0):
        return [write for write in self.github.writes[start:] if write[0] != 'record']

    async def test_interrupted_design_keeps_invalid_or_extra_path_checkpoints_local(self):
        for kind in ('extra_path', 'empty', 'symlink'):
            with self.subTest(kind=kind):
                self.reset()
                spec = self.workspace.path / SPEC
                spec.unlink()
                paths = [SPEC, 'src/unaccepted.py'] if kind == 'extra_path' else [SPEC]
                self.workspace.changed_paths = lambda *args: paths
                async def interrupted(assignment, **kwargs):
                    self.assertEqual(self.github.note['pending_action'], 'design')
                    if kind == 'symlink':
                        spec.symlink_to('absent-target')
                    else:
                        spec.write_text('Scoped specification' if kind == 'extra_path' else '')
                    if kind == 'extra_path':
                        extra = self.workspace.path / 'src/unaccepted.py'
                        extra.parent.mkdir(parents=True, exist_ok=True)
                        extra.write_text('Unaccepted implementation\n')
                    self.workspace.dirty = True
                    return {'status': 'interrupted', 'detail': {'cleanup': 'confirmed'}}
                result = await self.step(interrupted)
                self.assertEqual(result['action'], 'waiting')
                self.assertNotEqual(self.workspace.head, BASE)
                self.assertEqual(self.github.note['head'], self.workspace.head)
                self.assertEqual(self.github.note['resume_phase'], 'design')
                self.assertEqual(self.effects(), [])
                self.assertTrue(spec.exists() or spec.is_symlink())

    async def test_interrupted_exact_regular_spec_can_publish_its_checkpoint(self):
        spec = self.workspace.path / SPEC
        spec.unlink()
        self.workspace.changed_paths = lambda *args: [SPEC]
        async def interrupted(assignment, **kwargs):
            spec.write_text('Scoped specification')
            self.workspace.dirty = True
            return {'status': 'interrupted', 'detail': {'cleanup': 'confirmed'}}
        self.assertEqual((await self.step(interrupted))['reason'], 'stop_requested')
        self.assertEqual(self.effects(), [('push', self.workspace.head)])
        self.assertEqual(self.github.note['resume_phase'], 'design')

    @staticmethod
    def ci_outcome(value, conclusion, *, state='completed'):
        value['checks'][0].update(status=state, conclusion=conclusion)
        value['runs'][0].update(status=state, conclusion=conclusion)
        value['runs'][0]['jobs'][0].update(status=state, conclusion=conclusion)
        return value

    async def test_every_bound_terminal_ci_outcome_is_actionable_not_an_endless_gate_wait(self):
        for outcome in ('failure', 'timed_out', 'cancelled', 'startup_failure', 'action_required',
                        'stale', 'neutral', 'skipped', 'new_terminal_conclusion'):
            with self.subTest(outcome=outcome):
                self.reset()
                await self.opened_pr()
                self.github.transform_observation = lambda value: self.ci_outcome(value, outcome)
                result = await self.step()
                if result['action'] == 'continue':
                    self.assertEqual(self.github.note['correction_reason'], 'ci_failure')
                    self.assertEqual(self.github.note['correction_attempt'], 1)
                else:
                    self.assertEqual(result['reason'], 'replan_required')
                    self.assertTrue(self.github.note['next_action'].startswith('diagnose'))
                    count = len(self.calls)
                    self.assertEqual((await self.step())['reason'], 'replan_required')
                    self.assertEqual(len(self.calls), count)
                self.assertFalse(self.github.pr['merged'])
                self.assertEqual(self.github.work['state'], 'open')

    async def test_active_required_ci_and_unrelated_failed_check_do_not_trigger_correction(self):
        for state in ('queued', 'in_progress'):
            for extra in (False, True):
                with self.subTest(state=state, unrelated=extra):
                    self.reset()
                    await self.opened_pr()
                    def active(value):
                        self.ci_outcome(value, None, state=state)
                        if extra:
                            unrelated = copy.deepcopy(value['checks'][0])
                            unrelated.update(id=999, check_suite={'id': 998}, status='completed', conclusion='failure')
                            value['checks'].append(unrelated)
                        return value
                    self.github.transform_observation = active
                    calls, writes = len(self.calls), len(self.github.writes)
                    result = await self.step()
                    self.assertEqual(result['action'], 'waiting')
                    self.assertEqual(result['reason'], 'remote_delivery_gates')
                    self.assertEqual(len(self.calls), calls)
                    self.assertEqual(self.effects(writes), [])

    def bind_dependency(self):
        self.github.work['body'] = self.github.work['body'].replace(
            f'spec = "{SPEC}"', f'spec = "{SPEC}"\ndependencies = ["https://github.com/example/dependency/issues/9"]')
        original = self.github.issue
        def issue(repo, number):
            if repo == 'example/dependency' and number == 9:
                return {'number': number, 'state': 'open' if self.dependency_open else 'closed'}
            return original(repo, number)
        self.github.issue = issue

    async def test_reopened_dependency_stops_publish_merge_and_close_at_each_final_guard(self):
        for action in ('publish', 'merge', 'close_issue'):
            for boundary in ('before_intent', 'after_intent'):
                with self.subTest(action=action, boundary=boundary):
                    self.reset()
                    self.bind_dependency()
                    if action == 'publish':
                        self.assertEqual((await self.step())['action'], 'continue')
                    else:
                        await self.opened_pr()
                    if action == 'close_issue':
                        self.github.pr.update(merged=True, state='closed', merge_commit_sha=MERGE)
                    execute = None
                    if boundary == 'after_intent':
                        def reopen(record):
                            if record.get('pending_action') == action:
                                self.dependency_open = True
                        self.github.on_record = reopen
                    elif action == 'publish':
                        async def execute(assignment, **kwargs):
                            result = await self.execute(assignment, **kwargs)
                            if self.github.note['pending_action'] == 'change_review':
                                self.dependency_open = True
                            return result
                    else:
                        method = 'observe_commit' if action == 'close_issue' else 'observe'
                        original = getattr(self.github, method)
                        def observe(*args):
                            value = original(*args)
                            self.dependency_open = True
                            return value
                        setattr(self.github, method, observe)
                    writes = len(self.github.writes)
                    self.assertEqual((await self.step(execute))['action'], 'waiting')
                    self.assertTrue(self.dependency_open)
                    self.assertEqual(self.effects(writes), [])
                    self.assertEqual(self.github.work['state'], 'open')

    async def external_merge(self):
        await self.opened_pr()
        self.github.pr.update(merged=True, state='closed', merge_commit_sha=MERGE,
                              mergeable=None, mergeable_state='unknown')

    async def test_external_merge_cannot_complete_without_preserved_candidate_evidence(self):
        cases = ('code_missing', 'security_missing', 'provider_stale', 'ci_missing', 'ci_stale',
                 'ci_wrong_workflow', 'ci_invalid_historical_base', 'target_without_pin',
                 'unresolved_thread', 'protected_approval_missing', 'protected_approval_stale')
        for case in cases:
            with self.subTest(case=case):
                self.reset()
                if case == 'target_without_pin':
                    self.github.cfg['required_checks'][0]['events'] = ['pull_request_target', 'push']
                await self.external_merge()
                def missing(value):
                    if case in {'code_missing', 'security_missing'}:
                        name = 'Code Review' if case == 'code_missing' else 'Security Review'
                        value['provider_comments'][0]['body'] = '\n'.join(
                            line for line in value['provider_comments'][0]['body'].splitlines()
                            if f'**{name}**' not in line)
                    elif case == 'provider_stale':
                        value['provider_comments'][0]['body'] = summary('e' * 40)
                    elif case == 'ci_missing':
                        value.update(checks=[], runs=[])
                    elif case == 'ci_stale':
                        value['runs'][0]['head_sha'] = 'e' * 40
                        value['runs'][0]['jobs'][0]['head_sha'] = 'e' * 40
                        value['checks'][0]['head_sha'] = 'e' * 40
                    elif case == 'ci_wrong_workflow':
                        value['runs'][0]['workflow_id'] = 999
                    elif case == 'ci_invalid_historical_base':
                        value['runs'][0]['pull_requests'][0]['base']['sha'] = 'invalid'
                    elif case == 'target_without_pin':
                        value['runs'][0].update(event='pull_request_target', pull_requests=[])
                    elif case == 'unresolved_thread':
                        value['threads'] = [{'id': 'unresolved', 'isResolved': False, 'isOutdated': False,
                                             'comments': {'nodes': []}}]
                    else:
                        value['changed_files'] = [{'filename': '.hydra.toml'}]
                        if case == 'protected_approval_stale':
                            value['native_reviews'] = [{'id': 21, 'state': 'APPROVED', 'commit_id': 'e' * 40,
                                'submitted_at': '2026-10-10T00:00:00Z', 'user': {'login': 'operator', 'type': 'User'}}]
                            value['review_decision'] = 'APPROVED'
                    return value
                self.github.transform_observation = missing
                calls, writes = len(self.calls), len(self.github.writes)
                for _ in range(2):
                    self.assertEqual((await self.step())['action'], 'waiting')
                self.assertEqual(self.github.work['state'], 'open')
                self.assertEqual(len(self.calls), calls)
                self.assertEqual(self.effects(writes), [])

    async def test_external_merge_with_historical_base_and_disabled_auto_merge_can_complete(self):
        for protected in (False, True):
            with self.subTest(protected=protected):
                self.reset()
                self.github.cfg['delivery'].update(automatic_merge=False, production_effect=True)
                await self.external_merge()
                self.github.cfg['revision'] = 'e' * 40
                def historical(value):
                    value['base_sha'] = 'e' * 40  # Current main has advanced beyond the candidate's PR run.
                    if protected:
                        value['changed_files'] = [{'filename': '.hydra.toml'}]
                        value['native_reviews'] = [{'id': 21, 'state': 'APPROVED', 'commit_id': HEAD,
                            'submitted_at': '2026-10-10T00:00:00Z', 'user': {'login': 'operator', 'type': 'User'}}]
                        value['review_decision'] = 'APPROVED'
                    return value
                self.github.transform_observation = historical
                calls, writes = len(self.calls), len(self.github.writes)
                self.assertEqual((await self.step())['action'], 'completed')
                self.assertEqual(self.github.work['state'], 'closed')
                self.assertEqual(len(self.calls), calls)
                self.assertEqual(self.effects(writes), [('close', NUMBER)])


if __name__ == '__main__':
    unittest.main()
