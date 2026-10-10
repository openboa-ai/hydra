"""Lost service responses and mutating verification remain recoverable."""

import copy
import tempfile
import unittest
from unittest.mock import patch

from hydra_sdlc.runner import Runner
from hydra_sdlc.workspace import WorkspaceWait
from test_project import BASE, HEAD, MERGE, summary
from test_runner import GitHub, Workspace, complete_capabilities


REPO, NUMBER = 'example/product', 4


class DeliveryReconciliationTests(unittest.IsolatedAsyncioTestCase):
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

    async def execute(self, assignment, **kwargs):
        phase = self.github.note['pending_action']
        self.calls.append(phase)
        if phase == 'correction':
            self.assertFalse(self.workspace.dirty)
            self.assertEqual(self.github.note['head'], self.workspace.head)
        if assignment['mode'] == 'workspace_write':
            self.workspace.dirty = True
        return {'status': 'completed', 'detail': {'result': {'outcome': 'candidate_ready'}}}

    async def capabilities(self, cwd):
        return complete_capabilities()

    def runner(self):
        return Runner(self.github, self.workspace, host_alias='host-a', execute=self.execute,
                      capabilities=self.capabilities, stop_requested=lambda: self.stopped)

    def effects(self, start=0):
        return [write for write in self.github.writes[start:] if write[0] != 'record']

    async def opened_pr(self):
        self.github.remote_pending = True
        self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'continue')
        self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'remote_delivery_gates')
        self.github.remote_pending = False

    @staticmethod
    def code_running(value):
        body = summary(value['head_sha'])
        body = '\n'.join(line for line in body.splitlines() if '**Security Review**' not in line)
        value['provider_comments'][0]['body'] = body.replace('✅ **Completed**', '🔄 **Running**')
        return value

    async def test_observed_third_code_request_reconciles_without_resetting_unknown_security(self):
        await self.opened_pr()
        running = False
        def observation(value):
            if running:
                return self.code_running(value)
            value['provider_comments'] = []
            return value
        self.github.transform_observation = observation
        self.github.note['checkpoint'] = 'await_auto_review'
        requests = []
        def lost(repo, pr, kind='code', head=None, *, issue_number):
            nonlocal running
            self.assertEqual(issue_number, NUMBER)
            self.assertEqual(self.github.note.get('pending_review_kind'), kind)
            self.assertEqual(head, HEAD)
            requests.append(kind)
            if requests.count('code') == 3:
                running = True
            raise RuntimeError('request submitted; response and read-back unavailable')
        self.github.request_review = lost
        for attempt in range(1, 4):
            self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'review_request_unknown')
            self.assertEqual(self.github.note['delivery_attempt'], attempt)
            self.assertEqual(self.github.note['pending_review_kind'], 'code')
        calls = len(self.calls)
        for attempt in range(1, 4):
            self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'review_request_unknown')
            self.assertEqual(self.github.note['review_requested_head'], HEAD)
            self.assertEqual(self.github.note['pending_review_kind'], 'security')
            self.assertEqual(self.github.note['delivery_attempt'], attempt)
        for _ in range(2):
            self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'replan_required')
        self.assertEqual(requests, ['code'] * 3 + ['security'] * 3)
        self.assertEqual(len(self.calls), calls)
        self.assertFalse(self.github.pr['merged'])

    async def test_ambiguous_legacy_request_cannot_infer_its_kind_from_code_running(self):
        await self.opened_pr()
        self.github.transform_observation = lambda value: {**value, 'provider_comments': []}
        self.github.note['checkpoint'] = 'await_auto_review'
        def lost(*args, **kwargs):
            raise RuntimeError('outcome unknown')
        self.github.request_review = lost
        for _ in range(3):
            self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'review_request_unknown')
        self.github.note.pop('pending_review_kind', None)
        self.github.transform_observation = self.code_running
        self.github.request_review = lambda *args, **kwargs: self.fail('Ambiguous legacy intent was transferred')
        self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'replan_required')
        self.assertEqual(self.github.note['pending_action'], 'request_review')
        self.assertEqual(self.github.note['delivery_attempt'], 3)

    async def test_close_rechecks_exact_merge_ci_after_intent_and_preserves_recovery(self):
        for recovery in (False, True):
            for outcome in ('queued', 'failure', 'new_failed_rerun'):
                with self.subTest(recovery=recovery, outcome=outcome):
                    self.reset()
                    await self.opened_pr()
                    self.github.pr.update(merged=True, state='closed', merge_commit_sha=MERGE)
                    self.github.note.update(checkpoint='squash_' + MERGE, expected_head=HEAD, expected_base=BASE)
                    if recovery:
                        self.github.note.update(pending_action='close_issue', phase='closing')
                        self.github.work['state'] = 'closed'
                    changed = False
                    if recovery:
                        original_observe = self.github.observe
                        reads = 0
                        def observe(*args):
                            nonlocal changed, reads
                            value = original_observe(*args)
                            reads += 1
                            if reads == 2:
                                changed = True
                            return value
                        self.github.observe = observe
                    else:
                        def on_record(record):
                            nonlocal changed
                            if record.get('pending_action') == 'close_issue':
                                changed = True
                        self.github.on_record = on_record
                    commits = []
                    original_post = self.github.observe_commit
                    def post(repo, sha):
                        commits.append(sha)
                        value = original_post(repo, sha)
                        if changed:
                            run = value['runs'][0]
                            if outcome == 'new_failed_rerun':
                                run = copy.deepcopy(run)
                                run.update(id=run['id'] + 1, run_attempt=run['run_attempt'] + 1)
                                value['runs'].append(run)
                            state, conclusion = ('queued', None) if outcome == 'queued' else ('completed', 'failure')
                            run.update(status=state, conclusion=conclusion)
                            run['jobs'][0].update(status=state, conclusion=conclusion)
                            value['checks'][0].update(status=state, conclusion=conclusion)
                        return value
                    self.github.observe_commit = post
                    calls, writes = len(self.calls), len(self.github.writes)
                    result = await self.runner().step(REPO, NUMBER)
                    self.assertTrue(changed)
                    self.assertGreaterEqual(len(commits), 2)
                    self.assertEqual(set(commits), {MERGE})
                    self.assertEqual(result['action'], 'waiting')
                    self.assertEqual(self.github.note['pending_action'], 'close_issue')
                    self.assertEqual(self.effects(writes), [])
                    self.assertEqual(len(self.calls), calls)
                    self.assertEqual(self.github.work['state'], 'closed' if recovery else 'open')
                    self.github.observe_commit = original_post
                    self.github.on_record = lambda record: None
                    self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'completed')
                    self.assertEqual(self.effects(writes), [] if recovery else [('close', NUMBER)])

    async def test_final_push_check_observation_reapplies_current_controls(self):
        for recovery in (False, True):
            for control in ('dependency', 'paused', 'stop', 'intake'):
                with self.subTest(recovery=recovery, control=control):
                    self.reset()
                    dependency_open = False
                    self.github.work['body'] = self.github.work['body'].replace(
                        'spec = ', 'dependencies = ["https://github.com/example/dependency/issues/9"]\nspec = ')
                    original_issue = self.github.issue
                    def issue(repo, number):
                        if repo == 'example/dependency':
                            return {'number': number, 'state': 'open' if dependency_open else 'closed'}
                        return original_issue(repo, number)
                    self.github.issue = issue
                    await self.opened_pr()
                    self.github.pr.update(merged=True, state='closed', merge_commit_sha=MERGE)
                    self.github.note.update(checkpoint='squash_' + MERGE, expected_head=HEAD, expected_base=BASE)
                    if recovery:
                        self.github.note.update(pending_action='close_issue', phase='closing')
                        self.github.work['state'] = 'closed'
                    reads = 0
                    original_post = self.github.observe_commit
                    def post(*args):
                        nonlocal reads, dependency_open
                        value = original_post(*args)
                        reads += 1
                        if reads == 2:
                            if control == 'dependency':
                                dependency_open = True
                            elif control == 'paused':
                                self.github.work['labels'].append({'name': self.github.cfg['labels']['paused']})
                            elif control == 'stop':
                                self.stopped = True
                            else:
                                self.github.work['body'] += '\nDifferent acceptance.\n'
                        return value
                    self.github.observe_commit = post
                    calls, writes = len(self.calls), len(self.github.writes)
                    self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'waiting')
                    self.assertEqual(reads, 2)
                    self.assertEqual(self.github.note['pending_action'], 'close_issue')
                    self.assertNotEqual(self.github.note['phase'], 'completed')
                    self.assertEqual(self.effects(writes), [])
                    self.assertEqual(len(self.calls), calls)

    async def prepare_verification(self):
        runner = self.runner()
        self.assertEqual((await runner.step(REPO, NUMBER))['action'], 'continue')
        self.assertEqual(self.workspace.head, HEAD)
        self.calls.clear()
        return runner

    def mutate(self, kind):
        artifact = self.workspace.path / 'src/generated.py'
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text('Generated during verification\n')
        self.workspace.dirty = True
        if kind == 'commit':
            self.workspace.checkpoint(self.workspace.path, 'Verifier created a commit')

    async def test_verification_mutations_are_corrected_before_review_and_reverified(self):
        for kind in ('dirty', 'commit'):
            for passed in (True, False):
                with self.subTest(kind=kind, passed=passed):
                    self.reset()
                    runner = await self.prepare_verification()
                    original = self.workspace.verify
                    def verify(*args, **kwargs):
                        self.assertEqual(self.github.note['phase'], 'executing')
                        self.assertEqual(self.github.note['pending_action'], 'verification')
                        result = original(*args, **kwargs)
                        self.mutate(kind)
                        result[0].update(passed=passed, exit_code=0 if passed else 1)
                        return result
                    self.workspace.verify = verify
                    writes = len(self.github.writes)
                    self.assertEqual((await runner.step(REPO, NUMBER))['action'], 'continue')
                    self.assertEqual(self.calls, ['correction'])
                    self.assertEqual(self.github.note['correction_reason'], 'verification_mutation')
                    self.assertEqual(self.github.note['head'], self.workspace.head)
                    self.assertFalse(self.workspace.dirty)
                    self.assertEqual(self.effects(writes), [])
                    self.assertEqual(runner.verified_heads, set())
                    self.workspace.verify = original
                    self.github.remote_pending = True
                    self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'remote_delivery_gates')
                    self.assertEqual(self.workspace.verification_calls, 2)
                    self.assertEqual(self.calls.count('change_review'), 1)
                    self.assertLess(self.calls.index('correction'), self.calls.index('change_review'))
                    self.assertEqual([w for w in self.effects(writes) if w[0] == 'push'], [('push', self.workspace.head)])

    async def test_stopped_verification_preserves_mutation_for_correction_on_resume(self):
        for kind in ('dirty', 'commit'):
            for raises in (False, True):
                with self.subTest(kind=kind, raises=raises):
                    self.reset()
                    runner = await self.prepare_verification()
                    original = self.workspace.verify
                    def verify(*args, **kwargs):
                        result = original(*args, **kwargs)
                        self.mutate(kind)
                        self.stopped = True
                        if raises:
                            raise WorkspaceWait('verification_stopped')
                        return result
                    self.workspace.verify = verify
                    writes = len(self.github.writes)
                    self.assertEqual((await runner.step(REPO, NUMBER))['reason'], 'stop_requested')
                    self.assertEqual(self.calls, [])
                    self.assertFalse(self.workspace.dirty)
                    self.assertEqual(self.github.note['head'], self.workspace.head)
                    self.assertEqual(self.github.note['resume_phase'], 'correction')
                    self.assertEqual(self.github.note['correction_reason'], 'verification_mutation')
                    self.assertIsNone(self.github.note['pending_action'])
                    self.assertEqual(self.effects(writes), [])
                    self.stopped = False
                    self.workspace.verify = original
                    self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'continue')
                    self.assertIn('correction', self.calls)
                    self.assertNotIn('change_review', self.calls)
                    self.assertEqual(self.effects(writes), [])

    async def test_unconfirmed_verification_blocks_host_until_explicit_stopped_recovery(self):
        runner = await self.prepare_verification()
        original = self.workspace.verify
        def unknown(*args, **kwargs):
            self.mutate('dirty')
            raise WorkspaceWait('verification_cleanup_unknown', uncertain=True)
        self.workspace.verify = unknown
        writes = len(self.github.writes)
        self.assertEqual((await runner.step(REPO, NUMBER))['action'], 'waiting')
        self.assertTrue(runner.host_hold_reason)
        self.assertEqual(self.github.note['phase'], 'executing')
        self.assertEqual(self.github.note['pending_action'], 'verification')
        self.assertTrue(self.workspace.dirty)
        self.assertEqual((await runner.step('example/another', 8))['reason'], runner.host_hold_reason)
        self.assertEqual(self.calls, [])
        self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'confirm_previous_stopped')
        self.github.extra_comments.append({'user': {'login': 'operator'},
            'body': f"hydra: handover {self.github.note['attempt_id']} stopped"})
        self.workspace.verify = original
        self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'continue')
        self.assertIn('correction', self.calls)
        self.assertNotIn('change_review', self.calls)
        self.assertEqual(self.github.note['correction_reason'], 'verification_mutation')
        self.assertEqual(self.effects(writes), [])

    async def test_repeated_mutating_verification_reaches_durable_bounded_diagnosis(self):
        runner = await self.prepare_verification()
        original = self.workspace.verify
        def always_mutates(*args, **kwargs):
            result = original(*args, **kwargs)
            self.mutate('dirty')
            return result
        self.workspace.verify = always_mutates
        writes = len(self.github.writes)
        for _ in range(2):
            self.assertEqual((await runner.step(REPO, NUMBER))['action'], 'continue')
            runner = self.runner()
        self.assertEqual((await runner.step(REPO, NUMBER))['reason'], 'replan_required')
        self.assertEqual(self.calls.count('correction'), 2)
        self.assertNotIn('change_review', self.calls)
        self.assertFalse(self.workspace.dirty)
        self.assertEqual(self.github.note['head'], self.workspace.head)
        count = len(self.calls)
        self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'replan_required')
        self.assertEqual(len(self.calls), count)
        self.assertEqual(self.effects(writes), [])

    async def test_checkpoint_or_progress_failure_preserves_verification_recovery(self):
        for failure in ('checkpoint', 'progress'):
            with self.subTest(failure=failure):
                self.reset()
                runner = await self.prepare_verification()
                original_verify = self.workspace.verify
                original_checkpoint = self.workspace.checkpoint
                original_record = self.github.record
                def verify(*args, **kwargs):
                    value = original_verify(*args, **kwargs)
                    self.mutate('dirty')
                    return value
                self.workspace.verify = verify
                if failure == 'checkpoint':
                    def checkpoint(*args):
                        raise RuntimeError('checkpoint unavailable')
                    self.workspace.checkpoint = checkpoint
                else:
                    def record(repo, number, value):
                        if value.get('phase') == 'implementation_done' and value.get('head') != HEAD:
                            raise RuntimeError('progress write did not persist')
                        return original_record(repo, number, value)
                    self.github.record = record
                writes = len(self.github.writes)
                with self.assertRaises(RuntimeError):
                    await runner.step(REPO, NUMBER)
                self.assertEqual(self.github.note['phase'], 'executing')
                self.assertEqual(self.github.note['pending_action'], 'verification')
                self.assertEqual(self.calls, [])
                self.assertTrue((self.workspace.path / 'src/generated.py').is_file())
                self.assertEqual(self.effects(writes), [])
                self.workspace.verify = original_verify
                self.workspace.checkpoint = original_checkpoint
                self.github.record = original_record
                self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'confirm_previous_stopped')
                self.github.extra_comments.append({'user': {'login': 'operator'},
                    'body': f"hydra: handover {self.github.note['attempt_id']} stopped"})
                self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'continue')
                self.assertEqual(self.github.note['correction_reason'], 'verification_mutation')
                self.assertEqual(self.github.note['head'], self.workspace.head)
                self.assertIn('correction', self.calls)
                self.assertNotIn('change_review', self.calls)
                self.assertEqual(self.effects(writes), [])

    async def test_stopped_verification_is_checkpointed_before_ci_or_merge_shortcuts(self):
        for remote_state in ('cancelled_ci', 'external_merge'):
            with self.subTest(remote_state=remote_state):
                self.reset()
                await self.opened_pr()
                self.github.note['phase'] = 'implementation_done'
                def unknown(*args, **kwargs):
                    self.mutate('dirty')
                    raise WorkspaceWait('verification_cleanup_unknown', uncertain=True)
                self.workspace.verify = unknown
                self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'waiting')
                self.assertEqual(self.github.note['pending_action'], 'verification')
                self.assertTrue(self.workspace.dirty)
                self.github.extra_comments.append({'user': {'login': 'operator'},
                    'body': f"hydra: handover {self.github.note['attempt_id']} stopped"})
                if remote_state == 'cancelled_ci':
                    def cancelled(value):
                        value['runs'][0].update(status='completed', conclusion='cancelled')
                        value['runs'][0]['jobs'][0].update(status='completed', conclusion='cancelled')
                        value['checks'][0].update(status='completed', conclusion='cancelled')
                        return value
                    self.github.transform_observation = cancelled
                else:
                    self.github.pr.update(merged=True, state='closed', merge_commit_sha=MERGE)
                calls, writes = len(self.calls), len(self.github.writes)
                result = await self.runner().step(REPO, NUMBER)
                self.assertEqual(result['action'], 'waiting')
                self.assertFalse(self.workspace.dirty)
                self.assertNotEqual(self.workspace.head, HEAD)
                self.assertEqual(self.github.note['head'], self.workspace.head)
                self.assertEqual(self.github.note['resume_phase'], 'correction')
                self.assertEqual(self.github.note['correction_reason'], 'verification_mutation')
                self.assertEqual(self.github.note['checkpoint'], 'verification_mutation_pending')
                self.assertNotEqual(self.github.note['phase'], 'completed')
                self.assertEqual(self.github.work['state'], 'open')
                self.assertEqual(len(self.calls), calls)
                self.assertEqual(self.effects(writes), [])
                self.assertTrue((self.workspace.path / 'src/generated.py').is_file())

    async def test_authorized_replan_retains_unknown_security_before_new_code_request(self):
        await self.opened_pr()
        self.github.transform_observation = self.code_running
        self.github.note['checkpoint'] = 'await_auto_review'
        requests = []
        def lost(repo, pr, kind='code', head=None, *, issue_number):
            self.assertEqual(issue_number, NUMBER)
            requests.append(kind)
            raise RuntimeError('request response unavailable')
        self.github.request_review = lost
        for _ in range(3):
            self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'review_request_unknown')
        self.assertEqual(requests, ['security'] * 3)
        self.assertIsNone(self.github.note.get('review_requested_head'))
        self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'replan_required')
        self.github.extra_comments.append({'user': {'login': 'operator'},
            'body': f"hydra: replan {self.github.note['attempt_id']} ready"})
        self.github.transform_observation = lambda value: {**value, 'provider_comments': []}
        calls = len(self.calls)
        for _ in range(2):
            result = await self.runner().step(REPO, NUMBER)
            if len(requests) > 3:
                break
        self.assertEqual(requests, ['security'] * 4)
        self.assertEqual(result['reason'], 'review_request_unknown')
        self.assertEqual(self.github.note['pending_review_kind'], 'security')
        self.assertEqual(self.github.note['delivery_attempt'], 1)
        self.assertEqual(len(self.calls), calls)

    async def test_repeated_mutation_stops_consume_new_correction_attempts_on_resume(self):
        runner = await self.prepare_verification()
        original = self.workspace.verify
        def mutates_and_stops(*args, **kwargs):
            result = original(*args, **kwargs)
            self.mutate('dirty')
            self.stopped = True
            return result
        self.workspace.verify = mutates_and_stops
        writes = len(self.github.writes)
        for attempt in (1, 2, 3):
            self.assertEqual((await runner.step(REPO, NUMBER))['reason'], 'stop_requested')
            self.assertEqual(self.github.note['checkpoint'], 'verification_mutation_pending')
            self.assertEqual(self.github.note['resume_phase'], 'correction')
            self.stopped = False
            if attempt < 3:
                async def low_usage(cwd):
                    return complete_capabilities(used=95, allowed=False)
                runner.capabilities = low_usage
                self.assertEqual((await runner.step(REPO, NUMBER))['reason'], 'usage_unavailable_or_low')
                self.assertEqual(self.github.note['checkpoint'], 'verification_mutation_pending')
                runner = self.runner()
                self.assertEqual((await runner.step(REPO, NUMBER))['action'], 'continue')
                self.assertEqual(self.github.note['correction_attempt'], attempt)
                self.assertNotEqual(self.github.note['checkpoint'], 'verification_mutation_pending')
                runner = self.runner()
            else:
                self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'replan_required')
        self.assertEqual(self.calls.count('correction'), 2)
        self.assertNotIn('change_review', self.calls)
        self.assertEqual(self.effects(writes), [])
        self.assertFalse(self.workspace.dirty)
        self.assertEqual(self.github.note['head'], self.workspace.head)

    async def test_stopped_verification_cannot_adopt_an_advanced_or_deleted_remote(self):
        for remote in ('e' * 40, None):
            with self.subTest(remote=remote):
                self.reset()
                await self.opened_pr()
                self.github.note['phase'] = 'implementation_done'
                def unknown(*args, **kwargs):
                    self.mutate('dirty')
                    raise WorkspaceWait('verification_cleanup_unknown', uncertain=True)
                self.workspace.verify = unknown
                self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'waiting')
                self.assertEqual(self.github.note['expected_head'], HEAD)
                pinned = copy.deepcopy(self.github.note)
                self.github.extra_comments.append({'user': {'login': 'operator'},
                    'body': f"hydra: handover {self.github.note['attempt_id']} stopped"})
                self.github.branch = remote
                if remote:
                    self.github.pr['head']['sha'] = remote
                calls, writes, prepared = len(self.calls), len(self.github.writes), len(self.workspace.prepared_recovery)
                for _ in range(2):
                    self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'remote_head_changed')
                    self.assertEqual(self.github.note, pinned)
                self.assertTrue(self.workspace.dirty)
                self.assertEqual(self.workspace.head, HEAD)
                self.assertEqual(len(self.workspace.prepared_recovery), prepared)
                self.assertEqual(len(self.calls), calls)
                self.assertEqual(self.effects(writes), [])

    async def test_policy_change_preserves_verification_origin_until_original_policy_returns(self):
        await self.opened_pr()
        original_config = copy.deepcopy(self.github.cfg)
        self.github.note['phase'] = 'implementation_done'
        original_verify = self.workspace.verify
        def unknown(*args, **kwargs):
            self.mutate('dirty')
            raise WorkspaceWait('verification_cleanup_unknown', uncertain=True)
        self.workspace.verify = unknown
        self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'waiting')
        pinned = copy.deepcopy(self.github.note)
        self.github.extra_comments.append({'user': {'login': 'operator'},
            'body': f"hydra: handover {self.github.note['attempt_id']} stopped"})
        self.github.file = lambda repo, path, revision: {'sha': original_config['blob_sha'], 'content': ''}
        self.github.cfg.update(revision='e' * 40, blob_sha='f' * 40)
        calls, writes, prepared = len(self.calls), len(self.github.writes), len(self.workspace.prepared_recovery)
        for _ in range(2):
            self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'policy_changed')
            self.assertEqual(self.github.note, pinned)
        self.assertTrue(self.workspace.dirty)
        self.assertEqual(len(self.workspace.prepared_recovery), prepared)
        self.assertEqual(len(self.calls), calls)
        self.assertEqual(self.effects(writes), [])
        self.github.cfg = original_config
        self.workspace.verify = original_verify
        self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'continue')
        self.assertFalse(self.workspace.dirty)
        self.assertEqual(self.github.note['head'], self.workspace.head)
        self.assertEqual(self.github.note['correction_reason'], 'verification_mutation')
        self.assertIn('correction', self.calls[calls:])
        self.assertNotIn('change_review', self.calls[calls:])
        self.assertEqual(self.effects(writes), [])

    async def test_pending_verifier_correction_finishes_before_integration_without_losing_its_reason(self):
        runner = await self.prepare_verification()
        original_verify = self.workspace.verify
        def mutating_stop(*args, **kwargs):
            result = original_verify(*args, **kwargs)
            self.mutate('dirty')
            self.stopped = True
            return result
        self.workspace.verify = mutating_stop
        self.assertEqual((await runner.step(REPO, NUMBER))['reason'], 'stop_requested')
        self.stopped = False
        self.workspace.verify = original_verify
        self.github.cfg['revision'] = 'e' * 40
        integrated = False
        self.workspace.contains_base = lambda *args: integrated
        reasons = []
        original_execute = self.execute
        async def execute(assignment, **kwargs):
            nonlocal integrated
            if self.github.note['pending_action'] == 'correction':
                reason = self.github.note['correction_reason']
                reasons.append(reason)
                if reason == 'integration_changed':
                    integrated = True
            return await original_execute(assignment, **kwargs)
        self.execute = execute
        self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'continue')
        self.assertEqual(reasons, ['verification_mutation'])
        self.assertEqual(self.github.note['correction_attempt'], 1)
        self.assertIsNone(self.github.note.get('resume_phase'))
        self.assertEqual((await self.runner().step(REPO, NUMBER))['action'], 'continue')
        self.assertEqual(reasons, ['verification_mutation', 'integration_changed'])
        self.assertTrue(integrated)
        self.github.remote_pending = True
        self.assertEqual((await self.runner().step(REPO, NUMBER))['reason'], 'remote_delivery_gates')
        self.assertEqual(reasons, ['verification_mutation', 'integration_changed'])
        self.assertEqual(self.calls.count('change_review'), 1)


if __name__ == '__main__':
    unittest.main()
