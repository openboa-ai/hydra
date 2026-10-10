"""Known undispatched work resumes; uncertain execution and reviews remain owned."""

import copy
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc.runner import Runner
from test_project import BASE, HEAD
from test_runner import GitHub, Workspace, complete_capabilities


REPO, NUMBER = 'example/product', 4


class DispatchReconciliationTests(unittest.IsolatedAsyncioTestCase):
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
        return Runner(self.github, self.workspace, host_alias='host-a', execute=execute or self.execute,
                      capabilities=self.capabilities, stop_requested=lambda: self.stopped)

    def effects(self, start=0):
        return [write for write in self.github.writes[start:] if write[0] != 'record']

    def bind_dependency(self):
        self.github.work['body'] = self.github.work['body'].replace(
            'spec = ', 'dependencies = ["https://github.com/example/dependency/issues/9"]\nspec = ')
        original = self.github.issue
        def issue(repo, number):
            if repo == 'example/dependency':
                return {'number': number, 'state': 'open' if self.dependency_open else 'closed'}
            return original(repo, number)
        self.github.issue = issue

    def block(self, control):
        if control == 'stop':
            self.stopped = True
        elif control == 'paused':
            self.github.work['labels'].append({'name': self.github.cfg['labels']['paused']})
        else:
            self.dependency_open = True

    def clear_controls(self):
        self.stopped = self.dependency_open = False
        self.github.work['labels'] = [{'name': self.github.cfg['labels']['ready']}]
        self.github.on_record = lambda record: None

    async def test_undispatched_implementation_and_verification_resume_after_final_guard_clears(self):
        for action in ('implementation', 'verification'):
            for control in ('stop', 'paused', 'dependency'):
                with self.subTest(action=action, control=control):
                    self.reset()
                    self.bind_dependency()
                    runner = self.runner()
                    if action == 'verification':
                        self.assertEqual((await runner.step(REPO, NUMBER))['action'], 'continue')
                    self.calls.clear()
                    def changed(record):
                        if record.get('phase') == 'executing' and record.get('pending_action') == action:
                            self.block(control)
                    self.github.on_record = changed
                    writes, checks = len(self.github.writes), self.workspace.verification_calls
                    self.assertEqual((await runner.step(REPO, NUMBER))['action'], 'waiting')
                    self.assertNotIn(action, self.calls)
                    self.assertEqual(self.workspace.verification_calls, checks)
                    self.assertNotEqual(self.github.note['phase'], 'executing')
                    self.assertNotEqual(self.github.note.get('pending_action'), action)
                    self.assertEqual(self.effects(writes), [])
                    self.clear_controls()
                    self.github.remote_pending = True
                    result = await self.runner().step(REPO, NUMBER)
                    self.assertNotEqual(result.get('reason'), 'confirm_previous_stopped')
                    if action == 'implementation':
                        self.assertEqual(result['action'], 'continue')
                        self.assertEqual(self.calls.count('implementation'), 1)
                    else:
                        self.assertEqual(self.workspace.verification_calls, checks + 1)
                        self.assertIn('change_review', self.calls)

    async def test_model_phase_guard_restores_the_whole_prior_continuation(self):
        for phase in ('design', 'spec_review', 'correction', 'change_review'):
            with self.subTest(phase=phase):
                self.reset()
                self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'continue')
                previous = copy.deepcopy(self.github.note)
                previous.update(phase='implementation_done', resume_phase=phase, pending_action=None,
                                checkpoint='verification_mutation_pending', correction_reason='verification_mutation',
                                correction_attempt=1, next_action=phase, wait_reason=None)
                self.github.record(REPO, NUMBER, previous)
                self.calls.clear()
                def stop(record):
                    if record.get('phase') == 'executing' and record.get('pending_action') == phase:
                        self.stopped = True
                self.github.on_record = stop
                config = {**self.github.cfg, 'intake_digest': previous['intake_digest']}
                correction = ('verification_mutation', 2) if phase == 'correction' else None
                result, wait = await self.runner()._model(REPO, NUMBER, config, previous,
                    self.workspace.path, phase, 'Continue the accepted bounded phase.', correction=correction)
                self.assertIsNone(result)
                self.assertEqual(wait['action'], 'waiting')
                self.assertEqual(self.github.note, {**previous, 'wait_reason': 'stop_requested'})
                self.assertEqual(self.calls, [])
                self.clear_controls()
                result, wait = await self.runner()._model(REPO, NUMBER, config, self.github.progress(REPO, NUMBER),
                    self.workspace.path, phase, 'Continue the accepted bounded phase.', correction=correction)
                self.assertIsNone(wait)
                self.assertEqual(result['outcome'], 'candidate_ready')
                self.assertEqual(self.calls, [phase])
                if phase == 'correction':
                    self.assertEqual(self.github.note['correction_attempt'], 2)
                    self.assertIsNone(self.github.note['checkpoint'])

    async def test_failed_compensation_retains_the_durable_execution_intent(self):
        original_record = self.github.record
        def record(repo, number, value):
            if (self.github.note and self.github.note.get('pending_action') == 'implementation'
                    and value.get('phase') != 'executing'):
                raise RuntimeError('Compensating progress write unavailable')
            return original_record(repo, number, value)
        self.github.record = record
        self.github.on_record = lambda value: self.block('stop') if value.get('pending_action') == 'implementation' else None
        with self.assertRaises(RuntimeError):
            await self.runner().step(REPO, NUMBER)
        self.assertNotIn('implementation', self.calls)
        self.assertEqual(self.github.note['phase'], 'executing')
        self.assertEqual(self.github.note['pending_action'], 'implementation')
        self.github.record = original_record
        self.clear_controls()
        self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'confirm_previous_stopped')

    async def test_dispatched_unknown_model_still_requires_stopped_handover(self):
        async def execute(assignment, **kwargs):
            if self.github.note['pending_action'] != 'implementation':
                return await self.execute(assignment, **kwargs)
            self.calls.append('implementation')
            self.stopped = True
            return {'status': 'transport_unknown', 'detail': {'cleanup': 'unknown'}}
        self.assertEqual((await self.runner(execute).step(REPO, NUMBER))['action'], 'waiting')
        self.assertEqual(self.calls.count('implementation'), 1)
        self.assertEqual(self.github.note['pending_action'], 'implementation')
        pinned = copy.deepcopy(self.github.note)
        self.clear_controls()
        self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'confirm_previous_stopped')
        self.assertEqual(self.github.note, pinned)
        self.assertEqual(self.calls.count('implementation'), 1)

    async def test_confirmed_stop_checkpoint_can_publish_but_pause_still_blocks_it(self):
        for paused in (False, True):
            with self.subTest(paused=paused):
                self.reset()
                async def interrupted(assignment, **kwargs):
                    if self.github.note['pending_action'] != 'implementation':
                        return await self.execute(assignment, **kwargs)
                    self.calls.append('implementation')
                    self.workspace.dirty = True
                    self.stopped = True
                    if paused:
                        self.block('paused')
                    return {'status': 'interrupted', 'detail': {'cleanup': 'confirmed'}}
                self.assertEqual((await self.runner(interrupted).step(REPO, NUMBER))['action'], 'waiting')
                self.assertEqual(self.github.note['head'], HEAD)
                self.assertEqual(self.github.note['checkpoint'], 'interrupted_committed')
                self.assertEqual(self.effects(), [] if paused else [('push', HEAD)])
                self.assertEqual(self.calls.count('implementation'), 1)
                self.assertIsNone(self.github.pr)

    async def test_external_effect_intents_are_not_restored_as_undispatched_workers(self):
        for action in ('publish', 'merge', 'request_review'):
            with self.subTest(action=action):
                self.reset()
                self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'continue')
                previous = copy.deepcopy(self.github.note)
                previous.update(phase='uncertain', pending_action=action, delivery_action=action,
                                delivery_attempt=2, delivery_head=HEAD, expected_head=HEAD,
                                expected_base=BASE, pending_review_kind='security')
                self.github.record(REPO, NUMBER, previous)
                self.github.on_record = lambda record: self.block('stop') if record.get('pending_action') == action else None
                config = {**self.github.cfg, 'intake_digest': previous['intake_digest']}
                writes = len(self.github.writes)
                result = self.runner()._intent(REPO, NUMBER, config, previous, action,
                    phase='publishing', pending_review_kind='security')
                self.assertIsNone(result)
                self.assertEqual(self.github.note['pending_action'], action)
                self.assertEqual(self.github.note['delivery_attempt'], 3)
                self.assertEqual(self.github.note['head'], HEAD)
                self.assertEqual(self.github.note['expected_base'], BASE)
                self.assertEqual(self.github.note['pending_review_kind'], 'security')
                self.assertEqual(self.effects(writes), [])

    async def opened_pr(self):
        self.github.remote_pending = True
        self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'continue')
        self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'remote_delivery_gates')
        self.github.remote_pending = False

    async def test_duplicate_authenticated_evidence_diagnoses_and_replan_only_reconciles(self):
        for duplicate in ('summary', 'Code Review', 'Security Review'):
            for pending in (False, True):
                with self.subTest(duplicate=duplicate, pending=pending):
                    self.reset()
                    await self.opened_pr()
                    if pending:
                        def code_running(value):
                            body = value['provider_comments'][0]['body']
                            body = '\n'.join(line for line in body.splitlines() if '**Security Review**' not in line)
                            value['provider_comments'][0]['body'] = body.replace('✅ **Completed**', '🔄 **Running**')
                            return value
                        self.github.transform_observation = code_running
                        self.github.note['checkpoint'] = 'await_auto_review'
                        def lost(*args, **kwargs):
                            self.assertEqual(kwargs['kind'], 'security')
                            raise RuntimeError('Review request outcome unknown')
                        self.github.request_review = lost
                        self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'review_request_unknown')
                        self.assertEqual(self.github.note.get('pending_review_kind'), 'security')
                    pinned = {key: self.github.note.get(key) for key in
                              ('head', 'pending_action', 'pending_review_kind', 'delivery_action', 'delivery_attempt', 'delivery_head')}
                    def ambiguous(value):
                        if duplicate == 'summary':
                            extra = copy.deepcopy(value['provider_comments'][0])
                            extra['id'] += 1
                            value['provider_comments'].append(extra)
                        else:
                            body = value['provider_comments'][0]['body']
                            row = next(line for line in body.splitlines() if f'**{duplicate}**' in line)
                            value['provider_comments'][0]['body'] = body + '\n' + row
                        return value
                    self.github.transform_observation = ambiguous
                    calls, writes = len(self.calls), len(self.github.writes)
                    for _ in range(2):
                        self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'replan_required')
                        self.assertEqual(self.github.note['next_action'], 'diagnose_review')
                        self.assertEqual({key: self.github.note.get(key) for key in pinned}, pinned)
                    self.assertEqual(len(self.calls), calls)
                    self.assertEqual(self.effects(writes), [])
                    if pending:
                        for _ in range(2):
                            self.github.extra_comments.append({'user': {'login': 'operator'},
                                'body': f"hydra: replan {self.github.note['attempt_id']} ready"})
                            self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'replan_required')
                            self.assertEqual(self.github.note['pending_action'], 'request_review')
                            self.assertEqual(self.github.note['pending_review_kind'], 'security')
                            self.assertEqual(self.github.note['head'], HEAD)
                        self.assertEqual(len(self.calls), calls)
                        self.assertEqual(self.effects(writes), [])
                    self.github.extra_comments.append({'user': {'login': 'operator'},
                        'body': f"hydra: replan {self.github.note['attempt_id']} ready"})
                    self.github.transform_observation = lambda value: value
                    self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'continue')
                    self.assertTrue(self.github.pr['merged'])
                    self.assertEqual(len(self.calls), calls)
                    self.assertEqual(self.effects(writes), [('merge', HEAD)])

    async def test_unauthenticated_extra_summary_does_not_create_provider_ambiguity(self):
        await self.opened_pr()
        def untrusted(value):
            extra = copy.deepcopy(value['provider_comments'][0])
            extra['id'] += 1
            extra['user']['id'] = 999
            value['provider_comments'].append(extra)
            return value
        self.github.transform_observation = untrusted
        calls = len(self.calls)
        self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'continue')
        self.assertTrue(self.github.pr['merged'])
        self.assertEqual(len(self.calls), calls)


if __name__ == '__main__':
    unittest.main()
