"""Plain authorized decisions coexist with strict versioned-source boundaries.

The production factory, policy loader, GitHub adapter, and ordinary native
controller are real. Only external GitHub IO and local repository transport use
fixtures. Legacy positives keep the delegated workflow grant disabled; the MCP
negative has its own explicit bounded grant and a same-grant positive control.
"""
import copy
import hashlib
from pathlib import Path
import unittest
from unittest.mock import patch

from hydra_sdlc.control import load_host_config
from hydra_sdlc.project import load_project
from hydra_sdlc.public_delegated_decisions import (
    find_delegated_public_decision, parse_delegated_context,
    read_delegated_public_decision,
)
from delegated_decision_fixture import (
    ATTEMPT, KEY, REPO, URL, InstallationFixture, canonical, public_pair,
)
import test_delegated_decision_boundaries as work_fixture
from test_delegated_decision_boundaries import progress_payload
from test_delegated_decision_reader_capability import literal_pair
from test_workspace import LocalWorkspace


LEGACY_TEXT = 'Retain the accepted implementation scope and existing public interfaces.'


class PlainServiceDecisionTests(InstallationFixture, unittest.IsolatedAsyncioTestCase):
    prepare_local_work = work_fixture.DelegatedOrdinaryWorkTests.prepare_local_work
    checkpoint = work_fixture.DelegatedOrdinaryWorkTests.checkpoint

    async def asyncSetUp(self):
        self.setup_installation()
        self.url = URL

    def prepare(self, *, service_authorized=True):
        # Keep intake eligible when only the resolution author's permission is
        # removed. Commit those policy/intake facts before deriving their pins.
        self.transport.issue['user']['login'] = 'operator'
        if not service_authorized:
            self.transport.policy_text = self.transport.policy_text.replace(
                'authorized_actors = ["openboa", "operator"]',
                'authorized_actors = ["operator"]')
        self.prepare_local_work('implementation')
        # prepare_local_work enables its own profile; this oracle explicitly
        # disables it afterward and before production factory construction.
        self.write_profile(False)
        self.make_server(new_profile=True)
        self.addAsyncCleanup(self.close_pending)
        self.assertFalse(load_host_config(self.settings)['native_workflow_control']['enabled'])
        self.assertIsNone(self.controller.decision_source)
        policy = load_project(self.github, REPO)
        self.assertEqual('openboa' in policy['authorized_actors'], service_authorized)
        self.assertIn('operator', policy['authorized_actors'])
        self.assertEqual(self.github._identity(), {'id': 11, 'login': 'openboa'})
        self.assertTrue(callable(self.github._credential_selected))
        self.assertTrue(callable(self.github._request_timeout))
        self.transport.add(100, f'hydra: decision {ATTEMPT} context\n{LEGACY_TEXT}')
        self.transport.add(101, f'hydra: decision {ATTEMPT} resolved')
        for identifier in (100, 101):
            self.assertEqual(self.transport.direct[identifier]['user'], {'id': 11, 'login': 'openboa'})
            self.assertNotIn('<!-- hydra-decision-', self.transport.direct[identifier]['body'])
        self.assertEqual(self.transport.effects, [])

    def make_server(self, **kwargs):
        def local_workspace(root, **options):
            return LocalWorkspace(root, self.remote, **options)
        with patch('hydra_sdlc.workspace.Workspace', side_effect=local_workspace):
            return super().make_server(**kwargs)

    async def close_pending(self):
        record = self.github.progress(REPO, 4)
        if record and record.get('native_step'):
            await self.controller.checkpoint(URL, record['attempt_id'], record['native_step'],
                record['native_head'], record['contract_revision'], 'stopped')

    async def assert_implementation_assignment(self, result):
        self.assertEqual(result.get('action'), 'native_task', result)
        self.assertIn(LEGACY_TEXT, result['prompt'])
        self.assertIn('untrusted', result['prompt'].lower())
        if result['phase'] == 'spec_review':
            result = await self.checkpoint(result, 'candidate_ready')
        self.assertEqual(result.get('action'), 'native_task', result)
        self.assertEqual(result['phase'], 'implementation', result)
        self.assertEqual((result['repository'], result['issue']), (REPO, 4))
        self.assertNotEqual(result['attempt_id'], ATTEMPT)
        self.assertTrue(Path(result['cwd']).is_dir())
        self.assertIn(LEGACY_TEXT, result['prompt'])
        current = self.github.decision_progress_source(REPO, 4)
        self.assertEqual(current['record']['attempt_id'], result['attempt_id'])
        self.assertEqual(current['record']['native_step'], result['step_id'])
        self.assertEqual(current['decision_context'],
                         {'source_attempt': ATTEMPT, 'resume_attempt': result['attempt_id']})
        self.assertIsNone(current['native_root'], 'A plain legacy decision must not manufacture a v2 root')
        self.assertFalse(load_host_config(self.settings)['native_workflow_control']['enabled'])
        self.assertTrue(self.transport.effects, 'The real controller must record its resumed work and assignment')
        self.assertTrue(all(kind == 'progress' for kind, _ in self.transport.effects))

    async def assert_begin_holds(self):
        progress = self.github.progress(REPO, 4)
        controls = self.control.snapshot()
        result = await self.controller.begin(URL)
        self.assertEqual(result.get('action'), 'waiting', result)
        self.assertNotIn('step_id', result)
        self.assertEqual(self.transport.effects, [])
        self.assertEqual(self.github.progress(REPO, 4), progress)
        self.assertEqual(self.control.snapshot(), controls)
        if self.controller.lock_path.exists():
            self.assertEqual(self.controller.lock_path.read_bytes(), b'')

    async def test_authorized_plain_service_pair_begins_with_delegated_profile_disabled(self):
        self.prepare()
        await self.assert_implementation_assignment(await self.controller.begin(URL))

    async def test_authorized_plain_service_pair_advances_with_delegated_profile_disabled(self):
        self.prepare()
        record = self.github.progress(REPO, 4)
        result = await self.controller.advance(URL, record['attempt_id'],
            record['head'], record['contract_revision'])
        await self.assert_implementation_assignment(result)

    async def test_service_identity_without_legacy_actor_authority_does_not_resolve(self):
        self.prepare(service_authorized=False)
        await self.assert_begin_holds()

    async def test_granted_mcp_continue_holds_unreadable_claim_then_accepts_plain_pair(self):
        self.prepare()
        # This command has a distinct actual protected grant. Its negative must
        # reach source validation, not pass because a disabled grant rejects it.
        self.write_profile(True, operations=(
            'workflow_step.continue', 'command_reply.native_handoff_v1'))
        self.make_server(new_profile=True)
        before = self.github.progress(REPO, 4)
        controls = self.control.snapshot()
        plain_rows, plain_direct = copy.deepcopy(self.transport.rows), copy.deepcopy(self.transport.direct)
        self.transport.add(110, malformed_claims(self.transport.basis)['nonnumeric version'])
        held = self.reply(await self.invoke(self.command(continuation=True)))
        self.assertIn(held['request']['outcome'], {'waiting', 'rejected', 'unknown'}, held)
        self.assertNotIn(held['request']['reason'], {
            'authority_denied', 'unsupported_reply_profile', 'unsupported_operation', 'stale_runtime'}, held)
        self.assertIsNone(held['request']['receipt'])
        self.assertIsNone(held.get('handoff'))
        self.assertEqual(self.transport.effects, [])
        self.assertEqual(self.github.progress(REPO, 4), before)
        self.assertEqual(self.control.snapshot(), controls)
        # The same protected config/SDK path must actually progress once only
        # the malformed external source row is removed.
        self.transport.rows, self.transport.direct = plain_rows, plain_direct
        accepted = self.reply(await self.invoke(self.command(continuation=True)))
        self.assertEqual(accepted['request']['outcome'], 'applied', accepted)
        self.assertEqual(accepted['request']['receipt']['boundary'], 'assignment_returned')
        assignment = accepted['handoff']['assignment']
        self.assertEqual(assignment.get('action'), 'native_task', assignment)
        self.assertIn(LEGACY_TEXT, assignment['prompt'])
        self.assertNotEqual(assignment['attempt_id'], ATTEMPT)
        self.assertEqual(self.github.progress(REPO, 4)['native_step'], assignment['step_id'])


def malformed_claims(basis):
    context, _, _ = public_pair(basis, LEGACY_TEXT)
    key = canonical(KEY)
    prefix = f'Quoted external content.\nhydra: decision {ATTEMPT} context\n'
    return {
        'prefixed canonical v2': 'Quoted external content.\n' + context,
        'nonnumeric version': prefix + '<!-- hydra-decision-intent:future {unreadable-key -->\n',
        'unsupported kind': prefix + '<!-- hydra-decision-future:v2 {"key":' + key + '} -->\n',
        'truncated namespace': prefix + '<!-- hydra-decision-intent',
        'malformed separator': prefix + '<!-- hydra-decision-intent v2 {"key":' + key + '} -->\n',
        'missing key': prefix + '<!-- hydra-decision-intent:v2 {} -->\n',
    }


class PlainVersionedClaimReaderTests(InstallationFixture, unittest.TestCase):
    """Cheap real-adapter classification checks; no workspace or Git execution."""
    def setUp(self):
        self.setup_installation()
        self.write_profile(False)
        self.make_server(new_profile=True)
        self.transport.add(100, f'hydra: decision {ATTEMPT} context\n{LEGACY_TEXT}')
        self.transport.add(101, f'hydra: decision {ATTEMPT} resolved')
        self.plain_rows = copy.deepcopy(self.transport.rows)
        self.plain_direct = copy.deepcopy(self.transport.direct)

    def reset_plain(self):
        self.transport.rows = copy.deepcopy(self.plain_rows)
        self.transport.direct = copy.deepcopy(self.plain_direct)

    def find(self, *, expected_root=None):
        result = find_delegated_public_decision(self.github, REPO, 4, ATTEMPT,
                                                expected_root=expected_root)
        self.assertEqual(self.transport.route_errors, [])
        self.assertEqual(self.transport.effects, [])
        return result

    def assert_absent(self):
        context, observed = self.find()
        self.assertIsNone(context)
        self.assertEqual(observed.status, 'not_observed')

    def assert_unknown(self, *, expected_root=None):
        context, observed = self.find(expected_root=expected_root)
        self.assertIsNone(context)
        self.assertIn(observed.status, {'unknown', 'conflict'})

    def foreign_pair(self):
        record = progress_payload(self.transport.rows[0]['body'])
        return literal_pair({**record, 'repository_id': 124})

    def test_marker_free_authorized_service_pair_is_not_a_versioned_claim(self):
        self.assert_absent()

    def test_all_unreadable_service_namespaces_hold_before_legacy_fallback(self):
        for name, body in malformed_claims(self.transport.basis).items():
            with self.subTest(claim=name):
                self.reset_plain()
                self.transport.add(110, body)
                self.assert_unknown()

    def test_unreadable_namespace_and_valid_foreign_key_hold_in_both_orders(self):
        foreign_context, _ = self.foreign_pair()
        unreadable = malformed_claims(self.transport.basis)['nonnumeric version']
        for ordering, body in (
            ('unreadable first', unreadable + '\n' + foreign_context),
            ('foreign first', foreign_context + '\n' + unreadable),
        ):
            with self.subTest(ordering=ordering):
                self.reset_plain()
                self.transport.add(110, body)
                self.assert_unknown()

    def test_outsider_authored_unreadable_namespaces_do_not_claim_service_work(self):
        for name, body in malformed_claims(self.transport.basis).items():
            with self.subTest(claim=name):
                self.reset_plain()
                self.transport.add(110, body)
                row = self.transport.direct[110]
                row['user'] = {'id': 99, 'login': 'unrelated-contributor'}
                self.transport.rows = [copy.deepcopy(row) if item['id'] == 110 else item
                                       for item in self.transport.rows]
                self.assert_absent()

    def test_valid_foreign_full_key_alone_is_not_a_claim_on_this_work(self):
        context, receipt = self.foreign_pair()
        self.transport.add(110, context)
        self.transport.add(111, receipt)
        self.assert_absent()

    def test_expected_root_keeps_marker_stripped_public_sources_unknown(self):
        context, receipt, resume = public_pair(self.transport.basis, LEGACY_TEXT)
        root = {'decision': {'key': copy.deepcopy(KEY),
                            'context_sha256': hashlib.sha256(context.encode('utf-8')).hexdigest()},
                'resume_attempt': resume}
        # Both public records have lost their version markers, but the caller's
        # independently pinned root still requires that original exact pair.
        self.assert_unknown(expected_root=root)
        # A still-present exact receipt also cannot explain a stripped context.
        self.transport.add(111, receipt)
        self.assert_unknown(expected_root=root)

    def test_known_context_id_cannot_accept_its_marker_stripped_body(self):
        context, receipt, _ = public_pair(self.transport.basis, LEGACY_TEXT)
        expected = parse_delegated_context(context)
        row = self.transport.direct[101]
        row['body'] = receipt
        self.transport.rows = [copy.deepcopy(row) if item['id'] == 101 else item
                               for item in self.transport.rows]
        observed = read_delegated_public_decision(self.github, REPO, 4, expected,
            known_context_id=100, known_receipt_id=101)
        self.assertIn(observed.status, {'unknown', 'conflict'})
        self.assertEqual(self.transport.effects, [])
        self.assertEqual(self.transport.route_errors, [])
