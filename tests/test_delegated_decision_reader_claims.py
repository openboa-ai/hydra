"""Malformed relevant v2 claims cannot become legacy-reader absence.

Only source data changes here. The legacy facade retains its original service
actor and has no credential-selection or deadline capabilities added to it.
"""
import unittest

from hydra_sdlc.control_commands import AdmissionCallContext, execute_command_v1
import test_delegated_decision_reader_capability as capability_fixture
from test_public_decisions import comment
from test_workspace import git


class DelegatedReaderMalformedClaimTests(unittest.IsolatedAsyncioTestCase):
    # Explicit fixture aliases avoid inheriting and rerunning another TestCase.
    _flow = capability_fixture.DelegatedReaderCapabilityTests
    asyncSetUp = _flow.asyncSetUp
    new_controller = _flow.new_controller
    result = _flow.result
    command = _flow.command
    checkpoint = _flow.checkpoint
    real_git_assignment = _flow.real_git_assignment
    candidate = _flow.candidate
    verification_command = _flow.verification_command
    verification_grant = _flow.verification_grant
    call = _flow.call
    finish_command = _flow.finish_command
    reviewed = _flow.reviewed
    publication_command = _flow.publication_command
    publication_grant = _flow.publication_grant
    publish = _flow.publish
    no_publication = _flow.no_publication
    assert_original_facade = _flow.assert_original_facade
    assert_held = _flow.assert_held

    def add_prefixed_claims(self, *, receipt_present, outsider=False):
        context, receipt = capability_fixture.literal_pair(self.gh.note)
        prefix = 'Quoted source content follows.\n'
        rows = [comment(820, prefix + context)]
        if receipt_present:
            # A normal receipt heading would independently trigger the old
            # fallback, concealing a failure to recognize malformed contexts.
            rows.append(comment(821, prefix + receipt))
        if outsider:
            for row in rows:
                row['user'] = {'id': 99, 'login': 'unrelated-contributor'}
        self.gh.extra_comments.extend(rows)
        source = self.gh.read_client()
        self.assertEqual(source.comments('example/product', 4), rows)
        self.assertEqual(source._identity(), {'id': 11, 'login': 'openboa'})
        for row in rows:
            self.assertIn(f'"source_attempt":"{self.gh.note["attempt_id"]}"', row['body'])
            self.assertIn('<!-- hydra-decision-', row['body'])
            self.assertEqual(row['user'], {'id': 99, 'login': 'unrelated-contributor'}
                             if outsider else source._identity())

    async def test_prefixed_service_context_without_receipt_blocks_publication(self):
        candidate = await self.reviewed()
        self.assert_original_facade()
        self.add_prefixed_claims(receipt_present=False)
        writes = len(self.gh.writes)
        reply = await self.publish(self.publication_command(candidate))
        self.assert_held(reply, candidate, writes)

    async def test_prefixed_service_context_and_receipt_block_publication(self):
        candidate = await self.reviewed()
        self.assert_original_facade()
        self.add_prefixed_claims(receipt_present=True)
        writes = len(self.gh.writes)
        reply = await self.publish(self.publication_command(candidate))
        self.assert_held(reply, candidate, writes)

    async def test_prefixed_service_context_and_receipt_block_typed_continuation(self):
        candidate = await self.reviewed()
        self.assert_original_facade()
        self.add_prefixed_claims(receipt_present=True)
        command = self.verification_command(candidate)
        command['parameters'] = {
            'operation': 'continue', 'reply_profile': 'native_handoff_v1',
            'progress': {name: self.gh.note[name] for name in
                         ('attempt_id', 'head', 'contract_revision', 'phase')},
        }
        grant = AdmissionCallContext('native', None,
            frozenset({self.gh.cfg['repository_id']}),
            frozenset({'workflow_step.continue', 'command_reply.native_handoff_v1'}))
        writes = len(self.gh.writes)
        reply = await execute_command_v1(self.settings, command,
            context_provider=lambda: grant, github=self.gh, controller=self.controller)
        self.assert_held(reply, candidate, writes)

    async def test_outsider_authored_prefixed_bytes_do_not_block_legacy_publication(self):
        candidate = await self.reviewed()
        self.assert_original_facade()
        self.add_prefixed_claims(receipt_present=True, outsider=True)
        writes = len(self.gh.writes)
        reply = await self.publish(self.publication_command(candidate))
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(reply['request']['receipt']['kind'], 'publication')
        self.assertEqual(reply['request']['receipt']['candidate'], candidate)
        self.assertEqual(self.pushes, [('hydra/issue-4', None)])
        self.assertEqual([row[0] for row in self.gh.writes[writes:] if row[0] != 'record'], ['pr'])
        self.assertEqual(git(self.path, 'ls-remote', 'origin', 'refs/heads/hydra/issue-4').split()[0],
                         candidate['head'])
        self.assertEqual(self.counter.read_text(), '1')
        self.assertEqual(self.lock.read_bytes(), b'')
