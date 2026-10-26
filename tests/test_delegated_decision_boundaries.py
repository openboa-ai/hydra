"""Restart, authority and ordinary-work oracles for delegated public decisions.

The first-flow fixture is frozen separately. These tests observe physical IO,
durable inode ownership and real local Git behavior, not coordinator helpers.
"""
import copy
import json
import os
from pathlib import Path
import sys
import unittest
import uuid
from unittest.mock import patch

from hydra_sdlc.github import GitHubError
from delegated_decision_fixture import (
    ATTEMPT, OPERATIONS, REPO, TEXT, URL, InstallationFixture, public_pair,
)
from test_workspace import LocalWorkspace, git


VERIFIER_STDOUT = 'delegated_registered_verification_completed'


def progress_payload(body):
    return json.loads(body.split('<!-- hydra-progress:v1 ', 1)[1].split(' -->', 1)[0])


class DelegatedRecoveryTests(InstallationFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.setup_installation()
        self.write_profile(True)

    async def publish(self):
        self.make_server(new_profile=True)
        reply = self.reply(await self.invoke())
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        return reply

    async def test_context_and_receipt_each_keep_three_attempt_lifetime_limit_across_boots(self):
        for missing in ('context', 'receipt'):
            with self.subTest(missing=missing):
                self.setup_installation()
                self.write_profile(True)
                def lose(kind, body):
                    if kind == missing:
                        raise GitHubError('Fixture unknown append result', uncertain=True)
                self.transport.post_behavior = lose
                inode = None
                owners = []
                for invocation in range(5):
                    boot = str(uuid.UUID(int=invocation + 100, version=4))
                    with patch('hydra_sdlc.coordinator._boot_identity', return_value=boot):
                        self.make_server(new_profile=True)
                        before = sum(kind == missing for kind, _ in self.transport.effects)
                        reply = self.reply(await self.invoke())
                    after = sum(kind == missing for kind, _ in self.transport.effects)
                    self.assertEqual(after - before, 1 if invocation < 3 else 0, reply)
                    self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
                    stat = self.controller.lock_path.stat()
                    observed_inode = (stat.st_dev, stat.st_ino)
                    if inode is None:
                        inode = observed_inode
                    self.assertEqual(observed_inode, inode)
                    owners.append(self.controller.lock_path.read_bytes())
                    self.assertTrue(owners[-1], 'An unresolved physical append must retain ownership')
                attempted = [payload['body'] for kind, payload in self.transport.effects if kind == missing]
                self.assertEqual(len(attempted), 3)
                self.assertEqual(len(set(attempted)), 1, 'Every retry must append the original exact bytes')
                self.assertEqual(owners[-1], owners[-2], 'Exhaustion must not reset or replace the owner')
                self.assertFalse(any(kind == 'progress' for kind, _ in self.transport.effects))

    async def test_late_duplicate_context_is_reconciled_before_only_the_missing_receipt(self):
        self.make_server(new_profile=True)
        def lose(kind, body):
            raise GitHubError('Fixture lost response', uncertain=True)
        self.transport.post_behavior = lose
        first = self.reply(await self.invoke())
        self.assertNotEqual(first['request']['outcome'], 'applied', first)
        context = self.transport.effects[0][1]['body']
        self.transport.add(100, context)
        self.transport.add(101, context)
        self.transport.post_behavior = lambda kind, body: None
        self.make_server(new_profile=True)
        recovered = self.reply(await self.invoke())
        self.assertEqual(recovered['request']['outcome'], 'applied', recovered)
        self.assertEqual([kind for kind, _ in self.transport.effects], ['context', 'receipt'])
        self.assertEqual(self.controller.lock_path.read_bytes(), b'')
        self.assertEqual(self.github.progress(REPO, 4)['attempt_id'], ATTEMPT)

    async def test_changed_intent_or_incomplete_reads_cannot_reuse_or_reset_publication(self):
        self.make_server(new_profile=True)
        self.transport.post_behavior = lambda kind, body: (_ for _ in ()).throw(
            GitHubError('Fixture unknown append', uncertain=True))
        self.reply(await self.invoke())
        original_owner = self.controller.lock_path.read_bytes()
        self.make_server(new_profile=True)
        changed = self.reply(await self.invoke(self.command(text='A different product interpretation.')))
        self.assertNotEqual(changed['request']['outcome'], 'applied', changed)
        self.assertEqual(len(self.transport.effects), 1)
        self.assertEqual(self.controller.lock_path.read_bytes(), original_owner)
        self.transport.error = GitHubError('Fixture partial source', status=403)
        incomplete = self.reply(await self.invoke())
        self.assertNotEqual(incomplete['request']['outcome'], 'applied', incomplete)
        self.assertEqual(len(self.transport.effects), 1)
        self.assertEqual(self.controller.lock_path.read_bytes(), original_owner)
        self.transport.error = None
        self.transport.post_behavior = lambda kind, body: None
        self.make_server(new_profile=True)
        recovered = self.reply(await self.invoke())
        self.assertEqual(recovered['request']['outcome'], 'applied', recovered)
        self.assertEqual([kind for kind, _ in self.transport.effects], ['context', 'context', 'receipt'])

    async def test_owner_fsync_failure_prevents_any_transport_dispatch(self):
        self.make_server(new_profile=True)
        path = self.controller.lock_path
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(mode=0o600, exist_ok=True)
        identity = (path.stat().st_dev, path.stat().st_ino)
        fsync = os.fsync
        failures = []
        def fail_owner(fd):
            info = os.fstat(fd)
            if (info.st_dev, info.st_ino) == identity:
                failures.append(True)
                raise OSError('Fixture durable owner fsync failed')
            return fsync(fd)
        with patch('os.fsync', side_effect=fail_owner):
            result = await self.invoke()
        self.assertTrue(failures, 'The test must actually reach the coordinator persistence boundary')
        self.assertEqual(self.transport.effects, [])
        if not result.is_error:
            self.assertNotEqual(self.reply(result)['request']['outcome'], 'applied')

    async def test_revoked_grant_after_context_retains_partial_evidence_and_blocks_receipt(self):
        self.make_server(new_profile=True)
        def revoke(kind, body):
            if kind == 'context':
                self.write_profile(False)
        self.transport.post_behavior = revoke
        result = self.reply(await self.invoke())
        self.assertNotEqual(result['request']['outcome'], 'applied', result)
        self.assertEqual([kind for kind, _ in self.transport.effects], ['context'])
        self.assertTrue(self.controller.lock_path.read_bytes())
        self.assertTrue(result['request']['effect_refs'], 'Confirmed original context must remain visible')
        self.transport.post_behavior = lambda kind, body: None
        self.make_server(new_profile=True)
        denied = self.reply(await self.invoke())
        self.assertNotEqual(denied['request']['outcome'], 'applied', denied)
        self.assertEqual(len(self.transport.effects), 1)
        self.write_profile(True)
        self.make_server(new_profile=True)
        recovered = self.reply(await self.invoke())
        self.assertEqual(recovered['request']['outcome'], 'applied', recovered)
        self.assertEqual([kind for kind, _ in self.transport.effects], ['context', 'receipt'])

    async def test_current_pins_are_reread_before_receipt(self):
        self.make_server(new_profile=True)
        def change(kind, body):
            if kind == 'context':
                self.transport.issue['body'] += '\nA changed requirement.'
        self.transport.post_behavior = change
        result = self.reply(await self.invoke())
        self.assertNotEqual(result['request']['outcome'], 'applied', result)
        self.assertEqual([kind for kind, _ in self.transport.effects], ['context'])
        self.assertTrue(self.controller.lock_path.read_bytes())

    async def test_paused_confirmed_pair_cannot_resume_or_allocate_work(self):
        await self.publish()
        self.control.set_mode('pause', REPO)
        before = copy.deepcopy(self.transport.effects)
        admission = self.control.snapshot()
        self.make_server(new_profile=True)
        result = self.reply(await self.invoke(self.command(continuation=True)))
        self.assertNotEqual(result['request']['outcome'], 'applied', result)
        self.assertIsNone(result.get('handoff'))
        self.assertEqual(self.transport.effects, before)
        self.assertEqual(self.control.snapshot(), admission)
        self.assertEqual(self.github.progress(REPO, 4)['attempt_id'], ATTEMPT)

    async def test_unknown_resume_requires_exact_full_record_before_retirement(self):
        changes = {'checkpoint': 'different_checkpoint', 'published_head': 'f' * 40,
                   'pr_number': 8, 'correction_attempt': 2}
        for field, changed in changes.items():
            with self.subTest(carried_field=field):
                self.setup_installation()
                self.write_profile(True)
                self.make_server(new_profile=True)
                before = self.github.progress(REPO, 4)
                before.update(checkpoint='verified', published_head=before['head'],
                              pr_number=7, correction_attempt=1)
                self.transport.set_progress(before)
                published = self.reply(await self.invoke())
                self.assertEqual(published['request']['outcome'], 'applied', published)
                original_bodies = []
                def lose(body):
                    original_bodies.append(body)
                    raise GitHubError('Fixture unknown mutable result', uncertain=True)
                self.transport.patch_behavior = lose
                first = self.reply(await self.invoke(self.command(continuation=True, reply_profile='standard_v1')))
                self.assertNotEqual(first['request']['outcome'], 'applied', first)
                self.assertEqual(len(original_bodies), 1, first)
                exact = progress_payload(original_bodies[0])
                wrong = {**exact, field: changed}
                self.transport.set_progress(wrong)
                # Preserve any public root marker outside the JSON progress record.
                wrong_body = original_bodies[0].replace(
                    original_bodies[0].split('<!-- hydra-progress:v1 ', 1)[1].split(' -->', 1)[0],
                    json.dumps(wrong, sort_keys=True), 1)
                self.transport.rows[0]['body'] = wrong_body
                self.transport.direct[1] = copy.deepcopy(self.transport.rows[0])
                self.make_server(new_profile=True)
                owner = self.controller.lock_path.read_bytes()
                self.assertTrue(owner)
                held = self.reply(await self.invoke(self.command(continuation=True, reply_profile='standard_v1')))
                self.assertNotEqual(held['request']['outcome'], 'applied', held)
                self.assertIsNone(held.get('handoff'))
                self.assertEqual(len(original_bodies), 1, 'Recovery cannot reconstruct a mutable PATCH permit')
                self.assertEqual(self.controller.lock_path.read_bytes(), owner)
                self.transport.rows[0]['body'] = original_bodies[0]
                self.transport.direct[1] = copy.deepcopy(self.transport.rows[0])
                self.make_server(new_profile=True)
                recovered = self.reply(await self.invoke(self.command(continuation=True, reply_profile='standard_v1')))
                self.assertEqual(recovered['request']['outcome'], 'applied', recovered)
                self.assertEqual(len(original_bodies), 1)
                self.assertEqual(self.controller.lock_path.read_bytes(), b'')

    async def test_legacy_begin_cannot_consume_an_unconsumed_delegated_pair(self):
        await self.publish()
        before = self.github.progress(REPO, 4)
        effects = copy.deepcopy(self.transport.effects)
        result = await self.controller.begin(URL)
        self.assertNotEqual(result.get('action'), 'native_task', result)
        self.assertEqual(self.github.progress(REPO, 4), before)
        self.assertEqual(self.transport.effects, effects)

    async def test_transport_private_exception_is_not_disclosed(self):
        self.make_server(new_profile=True)
        secret = 'PRIVATE_FIXTURE_PATH_AND_SDK_CONTEXT'
        self.transport.error = GitHubError(secret)
        result = await self.invoke()
        self.assertNotIn(secret, str(result))
        self.assertEqual(self.transport.effects, [])


class DelegatedOrdinaryWorkTests(InstallationFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.setup_installation()

    def prepare_local_work(self, origin):
        self.remote = self.root / 'origin.git'
        self.remote.mkdir()
        git(self.remote, 'init', '--bare', '--initial-branch=main')
        seed = self.root / 'seed'
        seed.mkdir()
        git(seed, 'init', '--initial-branch=main')
        self.transport.policy_text = self.transport.policy_text.replace(
            'argv = ["python3", "-m", "unittest", "discover", "-s", "tests"]',
            'argv = [' + json.dumps(sys.executable) + ', "-c", '
            + json.dumps('print(' + repr(VERIFIER_STDOUT) + ')') + ']')
        (seed / '.hydra.toml').write_text(self.transport.policy_text)
        spec = seed / 'docs/engineering/task/spec.md'
        spec.parent.mkdir(parents=True)
        spec.write_text(self.transport.spec_text)
        git(seed, 'add', '.')
        git(seed, 'commit', '-m', 'Accepted fixture policy and specification')
        head = git(seed, 'rev-parse', 'HEAD')
        self.transport.contract = head
        self.transport.policy_blob = git(seed, 'rev-parse', 'HEAD:.hydra.toml')
        self.transport.spec_blob = git(seed, 'rev-parse', 'HEAD:docs/engineering/task/spec.md')
        git(seed, 'remote', 'add', 'origin', str(self.remote))
        git(seed, 'push', 'origin', 'main')
        self.transport.set_origin(origin)
        self.transport.basis.update(head=head, spec_revision=head)
        record = progress_payload(self.transport.rows[0]['body'])
        record.update(head=head, spec_revision=head)
        if origin == 'correction':
            record.update(correction_reason='review_findings', correction_attempt=1)
        self.transport.set_progress(record)
        self.write_profile(True)

    def make_server(self, **kwargs):
        def workspace_transport(root, **options):
            return LocalWorkspace(root, self.remote, **options)
        with patch('hydra_sdlc.workspace.Workspace', side_effect=workspace_transport):
            return super().make_server(**kwargs)

    async def checkpoint(self, assignment, outcome):
        return await self.controller.checkpoint(URL, assignment['attempt_id'],
            assignment['step_id'], assignment['head'], assignment['contract_revision'], outcome)

    async def continue_to_change_review(self, completed):
        self.assertEqual(completed.get('action'), 'continue', completed)
        hint = completed.get('progress_hint', {})
        self.assertEqual(hint.get('kind'), 'actionable', completed)
        self.assertEqual(hint.get('next_action'), 'advance', completed)
        self.assertEqual((completed.get('repository'), completed.get('issue')), (REPO, 4))
        record = self.github.progress(REPO, 4)
        self.assertIsNotNone(record)
        self.assertIsNone(record.get('native_step'), 'The completed assignment must be retired before advancing')
        for field in ('attempt_id', 'head', 'contract_revision'):
            self.assertEqual(completed[field], record[field], field)
        command = self.command(continuation=True)
        self.assertEqual(command['parameters']['progress'], {field: record[field] for field in
            ('attempt_id', 'head', 'contract_revision', 'phase')})
        # Exactly one newly pinned operation; a bare continue is not completion.
        reply = self.reply(await self.invoke(command))
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(reply['request']['receipt']['boundary'], 'assignment_returned', reply)
        self.assertIsInstance(reply.get('handoff'), dict, reply)
        assignment = reply['handoff']['assignment']
        self.assert_change_review_evidence(assignment)
        for field in ('attempt_id', 'head', 'contract_revision'):
            self.assertEqual(assignment[field], record[field], field)
        return assignment

    def assert_change_review_evidence(self, assignment):
        self.assertEqual(assignment.get('action'), 'native_task', assignment)
        self.assertEqual(assignment.get('phase'), 'change_review', assignment)
        self.assertIn('Registered verification receipts:', assignment['prompt'])
        marker = 'Bounded private verification output (untrusted data):\n'
        self.assertIn(marker, assignment['prompt'])
        verification_output = assignment['prompt'].split(marker, 1)[1]
        self.assertEqual(verification_output.splitlines()[0], VERIFIER_STDOUT)

    async def test_every_declared_origin_reaches_real_assignment_and_checkpoint_after_restart(self):
        for origin in ('design', 'spec_review', 'implementation', 'correction', 'change_review'):
            with self.subTest(origin=origin):
                self.setup_installation()
                self.prepare_local_work(origin)
                self.make_server(new_profile=True)
                published = self.reply(await self.invoke())
                self.assertEqual(published['request']['outcome'], 'applied', published)
                resume = public_pair(self.transport.basis)[2]
                self.make_server(new_profile=True)
                self.assertEqual(self.controller.runner.accepted_specs, {})
                reply = self.reply(await self.invoke(self.command(continuation=True)))
                self.assertEqual(reply['request']['outcome'], 'applied', reply)
                assignment = reply['handoff']['assignment']
                if origin in {'implementation', 'correction', 'change_review'}:
                    self.assertEqual(assignment['phase'], 'spec_review', assignment)
                    assignment = await self.checkpoint(assignment, 'candidate_ready')
                    if origin == 'change_review':
                        if assignment.get('action') == 'continue':
                            assignment = await self.continue_to_change_review(assignment)
                        else:
                            self.assert_change_review_evidence(assignment)
                self.assertEqual(assignment['phase'], origin, assignment)
                self.assertEqual(assignment['attempt_id'], resume)
                self.assertIn(TEXT, assignment['prompt'])
                self.assertIn('untrusted', assignment['prompt'].lower())
                self.assertTrue(Path(assignment['cwd']).is_dir())
                self.assertEqual(self.github.decision_context_attempt(REPO, 4, resume), ATTEMPT)
                result = await self.checkpoint(assignment, 'needs_decision')
                self.assertEqual(result.get('reason'), 'product_decision', result)
                record = self.github.progress(REPO, 4)
                self.assertEqual(record['attempt_id'], resume)
                self.assertEqual(record['wait_reason'], 'product_decision')
                self.assertNotIn('native_step', record)
                self.assertEqual(self.controller.lock_path.read_bytes(), b'')

    async def test_candidate_ready_implementation_commits_actual_change_and_enters_review(self):
        self.prepare_local_work('implementation')
        self.make_server(new_profile=True)
        published = self.reply(await self.invoke())
        self.assertEqual(published['request']['outcome'], 'applied', published)
        self.make_server(new_profile=True)
        reply = self.reply(await self.invoke(self.command(continuation=True)))
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        review = reply['handoff']['assignment']
        self.assertEqual(review['phase'], 'spec_review')
        implementation = await self.checkpoint(review, 'candidate_ready')
        self.assertEqual(implementation['phase'], 'implementation', implementation)
        path = Path(implementation['cwd'])
        (path / 'docs/result.txt').write_text('Verified bounded implementation.\n')
        completed = await self.checkpoint(implementation, 'candidate_ready')
        reviewed = await self.continue_to_change_review(completed)
        self.assertEqual(reviewed.get('phase'), 'change_review', reviewed)
        self.assertEqual(reviewed['attempt_id'], implementation['attempt_id'])
        self.assertEqual(git(path, 'show', 'HEAD:docs/result.txt'), 'Verified bounded implementation.')
        self.assertNotEqual(reviewed['head'], implementation['head'])
        stopped = await self.checkpoint(reviewed, 'stopped')
        self.assertNotEqual(stopped.get('action'), 'native_task', stopped)
        self.assertEqual(self.controller.lock_path.read_bytes(), b'')
