"""Nonunique required jobs diagnose a completed producer, never select a winner."""

import copy
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc.project import gate_checks, terminal_required_checks
from hydra_sdlc.runner import Runner
from test_project import BASE, BLOB, HEAD, config, observation
from test_runner import GitHub, Workspace, complete_capabilities


def duplicate_required_job(value, outcomes=('success', 'success')):
    run = value['runs'][0]
    duplicate = copy.deepcopy(run['jobs'][0])
    duplicate.update(id=91, check_run_url='https://api.github.com/repos/example/product/check-runs/91')
    run['jobs'].append(duplicate)
    check = copy.deepcopy(value['checks'][0])
    check['id'] = 91
    value['checks'].append(check)
    for job, check, outcome in zip(run['jobs'], value['checks'], outcomes):
        job['conclusion'] = check['conclusion'] = outcome
    return value


class RequiredJobAmbiguityTests(unittest.TestCase):
    def test_completed_duplicate_success_or_mixed_results_require_diagnosis(self):
        for outcomes in [('success', 'success'), ('success', 'failure'), ('failure', 'success')]:
            with self.subTest(outcomes=outcomes):
                cfg, obs = config(), duplicate_required_job(observation(), outcomes)
                self.assertEqual(terminal_required_checks(cfg, obs, HEAD),
                                 [{'job': 'Unit tests', 'conclusion': 'ambiguous_required_job'}])
                self.assertIn('check_job_not_successful:Unit tests', gate_checks(cfg, obs, HEAD))

    def test_active_duplicates_and_newer_active_rerun_wait(self):
        for status in ['queued', 'in_progress']:
            for newer in [False, True]:
                with self.subTest(status=status, newer=newer):
                    cfg, obs = config(), duplicate_required_job(observation())
                    if newer:
                        retry = copy.deepcopy(observation()['runs'][0])
                        retry.update(id=51, run_attempt=2, status=status, conclusion=None)
                        obs['runs'].append(retry)
                    else:
                        obs['runs'][0].update(status=status, conclusion=None)
                    self.assertEqual(terminal_required_checks(cfg, obs, HEAD), [])
                    self.assertTrue(gate_checks(cfg, obs, HEAD))

    def test_foreign_run_or_unbound_reusable_pin_cannot_trigger_diagnosis(self):
        cases = [(['workflow_id'], 999), (['path'], '.github/workflows/other.yml'),
                 (['repository', 'id'], 999), (['event'], 'workflow_dispatch'),
                 (['head_sha'], BASE), (['head_branch'], 'other-branch'),
                 (['pull_requests', 0, 'number'], 8),
                 (['pull_requests', 0, 'base', 'sha'], HEAD)]
        for path, replacement in cases:
            with self.subTest(path=path):
                cfg, obs = config(), duplicate_required_job(observation())
                target = obs['runs'][0]
                for component in path[:-1]:
                    target = target[component]
                target[path[-1]] = replacement
                self.assertEqual(terminal_required_checks(cfg, obs, HEAD), [])
                self.assertTrue(gate_checks(cfg, obs, HEAD))
        cfg, obs = config(), duplicate_required_job(observation())
        cfg['required_checks'][0].update(reusable_workflow='example/controls/.github/workflows/check.yml',
                                         reusable_sha=BLOB)
        self.assertEqual(terminal_required_checks(cfg, obs, HEAD), [])
        self.assertTrue(gate_checks(cfg, obs, HEAD))

    def test_optional_job_name_and_unique_failure_in_active_run_keep_their_meaning(self):
        cfg, obs = config(), duplicate_required_job(observation(), ('success', 'failure'))
        obs['runs'][0]['jobs'][1]['name'] = obs['checks'][1]['name'] = 'Optional report'
        self.assertEqual(terminal_required_checks(cfg, obs, HEAD), [])
        self.assertEqual(gate_checks(cfg, obs, HEAD), [])
        obs['runs'][0]['status'] = 'in_progress'
        obs['runs'][0]['jobs'][1].update(status='in_progress', conclusion=None)
        obs['checks'][1].update(status='in_progress', conclusion=None)
        obs['runs'][0]['jobs'][0]['conclusion'] = obs['checks'][0]['conclusion'] = 'failure'
        self.assertEqual(terminal_required_checks(cfg, obs, HEAD),
                         [{'job': 'Unit tests', 'conclusion': 'failure'}])
        self.assertTrue(gate_checks(cfg, obs, HEAD))


class RequiredJobDiagnosisRestartTests(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_required_jobs_hold_durable_diagnosis_without_restarting_work(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        github = GitHub()
        workspace = Workspace(directory.name, github)
        calls = []

        async def execute(assignment, **kwargs):
            calls.append(github.note['pending_action'])
            if assignment['mode'] == 'workspace_write':
                workspace.dirty = True
            return {'status': 'completed', 'detail': {'result': {'outcome': 'candidate_ready'}}}

        async def capabilities(cwd):
            return complete_capabilities()

        async def step():
            return await Runner(github, workspace, host_alias='host-a', execute=execute,
                                capabilities=capabilities).step('example/product', 4)

        with patch('hydra_sdlc.runner.load_project',
                   side_effect=lambda gh, repo, revision=None: copy.deepcopy(gh.cfg)):
            github.remote_pending = True
            self.assertEqual((await step())['action'], 'continue')
            self.assertEqual((await step())['reason'], 'remote_delivery_gates')
            github.remote_pending = False
            github.transform_observation = duplicate_required_job
            count, writes, head = len(calls), len(github.writes), github.note['head']
            for _ in range(2):
                self.assertEqual((await step())['reason'], 'replan_required')
                self.assertEqual(github.note['next_action'], 'diagnose_ci')
                self.assertEqual(github.note['head'], head)
            self.assertEqual(len(calls), count)
            self.assertFalse(any(write[0] != 'record' for write in github.writes[writes:]))
            self.assertFalse(github.pr['merged'])
            self.assertEqual(github.work['state'], 'open')
