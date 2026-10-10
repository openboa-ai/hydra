"""Delivery retries and stopped-write recovery retain their original authority."""

import copy
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc.codex import _assignment_options
from hydra_sdlc.runner import Runner, intake_digest
from test_project import BASE, HEAD
from test_runner import GitHub, Workspace, complete_capabilities


REPO = 'example/product'
NUMBER = 4
SPEC = 'docs/engineering/task/spec.md'
EFFECTS = {'push', 'pr', 'merge', 'close', 'resolve_thread'}


class DeliveryRecoveryTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.github = GitHub()
        self.workspace = Workspace(self.directory.name, self.github)
        self.calls = []
        self.records = []
        self.stop = False
        original = self.github.record

        def record(repo, number, value):
            original(repo, number, value)
            self.records.append(copy.deepcopy(value))

        self.github.record = record
        policy = patch('hydra_sdlc.runner.load_project',
                       side_effect=lambda gh, repo, revision=None: copy.deepcopy(gh.cfg))
        policy.start()
        self.addCleanup(policy.stop)

    async def execute(self, assignment, **kwargs):
        _assignment_options(assignment)
        self.calls.append(assignment['mode'])
        if assignment['mode'] == 'workspace_write':
            phase = self.github.note['pending_action']
            target = self.workspace.path / (SPEC if phase == 'design' else 'src/main.py')
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(('preserved ' + phase + '\n').encode())
            self.workspace.dirty = True
        return {'status': 'completed', 'detail': {'result': {
            'outcome': 'candidate_ready', 'summary': '', 'evidence': [], 'next_action': '',
        }}}

    async def capabilities(self, cwd):
        return complete_capabilities()

    def runner(self):
        return Runner(self.github, self.workspace, host_alias='host-a', execute=self.execute,
                      capabilities=self.capabilities, stop_requested=lambda: self.stop)

    def seed(self, **values):
        record = dict(attempt_id='12345678-1234-1234-1234-123456789abc', host_alias='host-a',
                      contract_revision=BASE, spec_revision=BASE, head=self.workspace.head,
                      branch='hydra/issue-4', pr_number=None, phase='implementation_done',
                      pending_action=None, checkpoint=None, wait_reason=None, next_action='verification',
                      intake_digest=intake_digest(self.github.work))
        record.update(values)
        self.github.record(REPO, NUMBER, record)
        return self.github.progress(REPO, NUMBER)

    async def implemented(self):
        result = await self.runner().step(REPO, NUMBER)
        self.assertEqual(result['action'], 'continue')
        self.assertEqual(self.workspace.head, HEAD)

    async def opened_pr(self):
        await self.implemented()
        self.github.remote_pending = True
        result = await self.runner().step(REPO, NUMBER)
        self.assertEqual(result['reason'], 'remote_delivery_gates')
        self.assertTrue(self.github.owns_pr(REPO, NUMBER, self.github.pr))

    async def exhausted_service(self, action):
        if action in {'publish', 'upsert_pr'}:
            await self.implemented()
            self.github.remote_pending = True
        else:
            await self.opened_pr()
        if action in {'merge', 'close_issue'}:
            self.github.remote_pending = False
        if action == 'close_issue':
            self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'continue')
            self.assertTrue(self.github.pr['merged'])
        if action == 'resolve_threads':
            thread = {'id': 'outdated-provider-thread', 'isOutdated': True, 'isResolved': False,
                      'comments': {'nodes': [{'author': {'login': self.github.cfg['review_provider']['login']}}]}}
            self.github.transform_observation = lambda value: {**value, 'threads': [copy.deepcopy(thread)]}
        owner, method = (self.workspace, 'publish') if action == 'publish' else (
            self.github, {'upsert_pr': 'ensure_pr', 'merge': 'merge',
                          'close_issue': 'close_issue', 'resolve_threads': 'resolve_thread'}[action])
        original = getattr(owner, method)
        requests = []
        failing = [True]

        def request(*args, **kwargs):
            self.github.assert_intent(action)
            requests.append(copy.deepcopy(self.github.note))
            if failing[0]:
                raise RuntimeError('service response unavailable')
            return original(*args, **kwargs)

        setattr(owner, method, request)
        reasons = {'publish': 'publish_unknown', 'upsert_pr': 'pr_unknown', 'merge': 'merge_unknown',
                   'close_issue': 'close_unknown', 'resolve_threads': 'review_resolution_boundary'}
        pinned = None
        for attempt in range(1, 4):
            result = await self.runner().step(REPO, NUMBER)
            self.assertEqual(result['reason'], reasons[action])
            self.assertEqual(len(requests), attempt)
            self.assertEqual(self.github.note['delivery_attempt'], attempt)
            self.assertEqual(self.github.note['pending_action'], action)
            current = {key: self.github.note.get(key) for key in ('head', 'expected_head', 'expected_base')}
            pinned = current if pinned is None else pinned
            self.assertEqual(current, pinned)
        result = await self.runner().step(REPO, NUMBER)
        self.assertEqual(result['reason'], 'replan_required')
        self.assertEqual(self.github.note['wait_reason'], 'replan_required')
        self.assertEqual(self.github.note['phase'], 'uncertain')
        self.assertEqual(self.github.note['next_action'], 'diagnose')
        self.assertEqual(self.github.note['pending_action'], action)
        self.assertEqual(self.github.note['delivery_attempt'], 3)
        self.assertEqual({key: self.github.note.get(key) for key in pinned}, pinned)
        self.assertEqual(len(requests), 3)
        self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'replan_required')
        self.assertEqual(len(requests), 3)
        return requests, failing, pinned

    async def service_replan(self, action):
        requests, failing, pinned = await self.exhausted_service(action)
        attempt = self.github.note['attempt_id']
        marker = f'hydra: replan {attempt} ready'
        self.github.extra_comments.append({'user': {'login': 'untrusted'}, 'body': marker})
        self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'replan_required')
        self.assertEqual(len(requests), 3)
        self.github.extra_comments.append({'user': {'login': 'operator'}, 'body': marker})
        before = len(self.records)
        writes = self.calls.count('workspace_write')
        failing[0] = False
        await self.runner().step(REPO, NUMBER)
        resumed = next(value for value in self.records[before:] if value['attempt_id'] != attempt)
        self.assertEqual(resumed['pending_action'], action)
        self.assertEqual(resumed['phase'], 'uncertain')
        self.assertIsNone(resumed.get('resume_phase'))
        self.assertEqual({key: resumed.get(key) for key in pinned}, pinned)
        self.assertEqual(len(requests), 4)
        self.assertEqual(requests[-1]['delivery_attempt'], 1)
        self.assertEqual({key: requests[-1].get(key) for key in pinned}, pinned)
        self.assertEqual(self.calls.count('workspace_write'), writes)

    async def test_publish_exhaustion_and_authorized_replan_resume_same_effect(self):
        await self.service_replan('publish')

    async def test_pr_exhaustion_and_authorized_replan_resume_same_effect(self):
        await self.service_replan('upsert_pr')

    async def test_merge_exhaustion_and_authorized_replan_resume_same_effect(self):
        await self.service_replan('merge')

    async def test_close_exhaustion_and_authorized_replan_resume_same_effect(self):
        await self.service_replan('close_issue')

    async def test_thread_exhaustion_and_authorized_replan_resume_same_effect(self):
        await self.service_replan('resolve_threads')

    async def test_resolved_thread_lost_response_does_not_consume_next_thread_budget(self):
        await self.opened_pr()
        threads = [{'id': name, 'isOutdated': True, 'isResolved': False,
                    'comments': {'nodes': [{'author': {'login': self.github.cfg['review_provider']['login']}}]}}
                   for name in ['thread-a', 'thread-b']]
        self.github.transform_observation = lambda value: {**value, 'threads': copy.deepcopy(threads)}
        requests = []
        writes = self.calls.count('workspace_write')

        def resolve(repo, number, thread, head, provider):
            self.github.assert_intent('resolve_threads')
            requests.append((thread, copy.deepcopy(self.github.note)))
            if thread == 'thread-a':
                if len(requests) == 3:
                    threads[0]['isResolved'] = True
                raise RuntimeError('thread resolution read-back unavailable')
            threads[1]['isResolved'] = True

        self.github.resolve_thread = resolve
        for attempt in range(1, 4):
            result = await self.runner().step(REPO, NUMBER)
            self.assertEqual(result['reason'], 'review_resolution_boundary')
            self.assertEqual(len(requests), attempt)
            self.assertEqual(requests[-1][0], 'thread-a')
            self.assertEqual(requests[-1][1]['delivery_attempt'], attempt)
        self.assertTrue(threads[0]['isResolved'])
        self.assertFalse(threads[1]['isResolved'])
        result = await self.runner().step(REPO, NUMBER)
        self.assertEqual([thread for thread, _ in requests], ['thread-a'] * 3 + ['thread-b'])
        self.assertEqual(requests[-1][1]['delivery_attempt'], 1)
        self.assertEqual(requests[-1][1]['pending_thread'], 'thread-b')
        self.assertEqual(result['action'], 'continue')
        self.assertIsNone(self.github.note.get('pending_action'))
        self.assertTrue(all(thread['isResolved'] for thread in threads))
        self.assertEqual(self.calls.count('workspace_write'), writes)

    async def test_historical_pr_delivery_does_not_skip_failed_correction_replan(self):
        await self.opened_pr()
        published = self.workspace.head
        self.assertEqual(self.github.note['delivery_action'], 'upsert_pr')
        self.assertEqual(self.github.note['delivery_head'], published)
        original_execute = self.execute

        async def failed_correction(assignment, **kwargs):
            result = await original_execute(assignment, **kwargs)
            if assignment['mode'] == 'workspace_write':
                self.assertEqual(self.github.note['pending_action'], 'correction')
                result['detail']['result']['outcome'] = 'failed'
            return result

        def failed_ci(value):
            value['checks'][0]['conclusion'] = 'failure'
            return value

        self.execute = failed_correction
        self.github.transform_observation = failed_ci
        result = await self.runner().step(REPO, NUMBER)
        self.assertEqual(result['reason'], 'replan_required')
        checkpointed = self.workspace.head
        self.assertNotEqual(checkpointed, published)
        self.assertEqual(self.github.note['head'], checkpointed)
        self.assertEqual(self.github.note['expected_head'], published)
        self.assertIsNone(self.github.note['pending_action'])
        self.assertFalse(self.workspace.dirty)
        self.assertEqual(self.github.note['delivery_action'], 'upsert_pr')
        self.assertEqual(self.github.note['delivery_head'], published)
        self.assertEqual(self.github.branch, published)
        self.github.extra_comments.append({'user': {'login': 'operator'},
            'body': f"hydra: replan {self.github.note['attempt_id']} ready"})
        async def replanned_implementation(assignment, **kwargs):
            if assignment['mode'] == 'workspace_write':
                self.assertEqual(self.github.note['pending_action'], 'implementation')
            return await original_execute(assignment, **kwargs)

        self.execute = replanned_implementation
        self.github.transform_observation = lambda value: value
        writes = self.calls.count('workspace_write')
        before = len(self.github.writes)
        result = await self.runner().step(REPO, NUMBER)
        self.assertEqual(self.calls.count('workspace_write'), writes + 1)
        self.assertEqual(result['action'], 'continue')
        self.assertNotEqual(self.workspace.head, checkpointed)
        self.assertEqual(self.github.note['phase'], 'implementation_done')
        self.assertFalse(any(item[0] in EFFECTS for item in self.github.writes[before:]))
        self.assertEqual(self.github.branch, published)
        self.assertEqual(self.github.pr['head']['sha'], published)

    async def test_replan_cannot_adopt_conflicting_remote_publication(self):
        requests, failing, pinned = await self.exhausted_service('publish')
        self.github.branch = 'e' * 40
        self.github.extra_comments.append({'user': {'login': 'operator'},
            'body': f"hydra: replan {self.github.note['attempt_id']} ready"})
        failing[0] = False
        writes = self.calls.count('workspace_write')
        result = await self.runner().step(REPO, NUMBER)
        self.assertEqual(result['action'], 'waiting')
        self.assertEqual(len(requests), 3)
        self.assertEqual(self.github.note['pending_action'], 'publish')
        self.assertEqual({key: self.github.note.get(key) for key in pinned}, pinned)
        self.assertEqual(self.calls.count('workspace_write'), writes)

    async def test_fresh_merge_observation_rechecks_pr_marker_before_intent(self):
        await self.opened_pr()
        self.github.remote_pending = False
        observations = []

        def changed(value):
            observations.append(copy.deepcopy(value['pr']))
            if len(observations) == 2:
                value['pr']['body'] = 'ownership marker removed after earlier observation'
            return value

        self.github.transform_observation = changed
        before = len(self.github.writes)
        calls = len(self.calls)
        result = await self.runner().step(REPO, NUMBER)
        self.assertEqual(result['action'], 'waiting')
        self.assertEqual(len(observations), 2)
        self.assertFalse(any(kind == 'merge' or (kind == 'record' and value == 'merge')
                             for kind, value in self.github.writes[before:]))
        self.assertEqual(len(self.calls), calls)

    async def checkpoint_failure(self, phase, fault):
        if phase == 'design':
            (self.workspace.path / SPEC).unlink()
            self.workspace.changed_paths = lambda *args: [SPEC]
        elif phase == 'correction':
            self.seed()
            self.workspace.verify = lambda *args, **kwargs: [
                {'passed': False, 'exit_code': 1, 'argv': ['true'], 'cwd': '.', 'output_digest': 'e' * 64}]
        original_checkpoint = self.workspace.checkpoint
        original_record = self.github.record
        checkpoint_entry = []
        original_head = self.workspace.head

        def checkpoint(path, message):
            checkpoint_entry.append(copy.deepcopy(self.github.note))
            self.assertEqual(self.github.note['phase'], 'executing')
            self.assertEqual(self.github.note['pending_action'], phase)
            if fault == 'checkpoint':
                raise RuntimeError('checkpoint unavailable')
            return original_checkpoint(path, message)

        def record(repo, number, value):
            if fault == 'record' and checkpoint_entry and value.get('head') != original_head:
                raise RuntimeError('checkpoint progress unavailable')
            return original_record(repo, number, value)

        self.workspace.checkpoint = checkpoint
        self.github.record = record
        with self.assertRaisesRegex(RuntimeError, 'checkpoint.*unavailable'):
            await self.runner().step(REPO, NUMBER)
        self.assertEqual(len(checkpoint_entry), 1)
        note = copy.deepcopy(self.github.note)
        self.assertEqual(note['phase'], 'executing')
        self.assertEqual(note['pending_action'], phase)
        target = self.workspace.path / (SPEC if phase == 'design' else 'src/main.py')
        content = target.read_bytes()
        self.assertEqual(content, ('preserved ' + phase + '\n').encode())
        self.assertEqual(self.workspace.dirty, fault == 'checkpoint')
        self.assertEqual(self.workspace.head == original_head, fault == 'checkpoint')
        self.assertEqual(note.get('head'), checkpoint_entry[0].get('head'))
        self.assertFalse(any(item[0] in EFFECTS for item in self.github.writes))
        before = (len(self.calls), len(self.workspace.prepared_recovery), self.workspace.verification_calls,
                  len(self.github.writes), self.workspace.head)
        result = await self.runner().step(REPO, NUMBER)
        self.assertEqual(result['reason'], 'confirm_previous_stopped')
        self.assertEqual(self.github.note, note)
        self.assertEqual((len(self.calls), len(self.workspace.prepared_recovery), self.workspace.verification_calls,
                          len(self.github.writes), self.workspace.head), before)
        self.assertEqual(target.read_bytes(), content)
        self.workspace.checkpoint = original_checkpoint
        self.github.record = original_record
        self.github.extra_comments.append({'user': {'login': 'operator'},
            'body': f"hydra: handover {note['attempt_id']} stopped"})
        checkpointed_head = self.workspace.head

        def stop_after_recovery(value):
            if value.get('attempt_id') != note['attempt_id'] and value.get('head') == self.workspace.head:
                self.stop = True

        self.github.on_record = stop_after_recovery
        result = await self.runner().step(REPO, NUMBER)
        self.assertEqual(result['reason'], 'stop_requested')
        self.assertTrue(self.workspace.prepared_recovery[-1])
        self.assertFalse(self.workspace.dirty)
        self.assertEqual(self.github.note['head'], self.workspace.head)
        self.assertEqual(target.read_bytes(), content)
        self.assertEqual(len(self.calls), before[0])
        if fault == 'record':
            self.assertEqual(self.workspace.head, checkpointed_head)

    async def test_design_checkpoint_failure_requires_stopped_handover(self):
        await self.checkpoint_failure('design', 'checkpoint')

    async def test_design_checkpoint_record_failure_requires_stopped_handover(self):
        await self.checkpoint_failure('design', 'record')

    async def test_implementation_checkpoint_failure_requires_stopped_handover(self):
        await self.checkpoint_failure('implementation', 'checkpoint')

    async def test_implementation_checkpoint_record_failure_requires_stopped_handover(self):
        await self.checkpoint_failure('implementation', 'record')

    async def test_correction_checkpoint_failure_requires_stopped_handover(self):
        await self.checkpoint_failure('correction', 'checkpoint')

    async def test_correction_checkpoint_record_failure_requires_stopped_handover(self):
        await self.checkpoint_failure('correction', 'record')


if __name__ == '__main__':
    unittest.main()
