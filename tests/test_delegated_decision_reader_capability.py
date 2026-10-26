"""Legacy authenticated facades must not silently consume delegated v2 claims.

Reuse the old service contract and real local Git publication flow. This fixture
does not gain credential-selection or deadline hooks to imitate v2 transport.
"""
import copy
import hashlib
import json
import unittest
import uuid

from hydra_sdlc.control_commands import AdmissionCallContext, execute_command_v1
import test_native_publication as publication_fixture
from test_public_decisions import comment
from test_workspace import git


def literal_pair(record):
    """Independent public v2 bytes bound to this actual candidate attempt."""
    key = {'repository_id': record['repository_id'], 'issue_number': 4,
           'source_attempt': record['attempt_id'], 'round': 1}
    basis = {name: record[name] for name in
             ('head', 'contract_revision', 'spec_revision', 'intake_digest')}
    basis['origin_phase'] = 'implementation'
    text = 'Keep the accepted implementation scope.'

    def canonical(value):
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          ensure_ascii=True, allow_nan=False)

    preimage = {'profile': 'codex_delegated_v1', 'key': key,
                'basis': basis, 'public_text': text}
    digest = hashlib.sha256(canonical(preimage).encode('utf-8')).hexdigest()
    resume = str(uuid.uuid5(uuid.NAMESPACE_URL, 'hydra:codex-delegated-v1:' + digest))
    metadata = {**basis, 'key': key, 'resume_attempt': resume,
                'supersedes': None, 'profile': 'codex_delegated_v1'}
    context = (f"hydra: decision {record['attempt_id']} context\n{text}\n"
               '<!-- hydra-decision-intent:v2 ' + canonical(metadata) + ' -->\n')
    receipt = (f"hydra: decision {record['attempt_id']} resolved\n"
               '<!-- hydra-decision-receipt:v2 ' + canonical({
                   'context_sha256': hashlib.sha256(context.encode('utf-8')).hexdigest(),
                   'key': key}) + ' -->\n')
    return context, receipt


class DelegatedReaderCapabilityTests(unittest.IsolatedAsyncioTestCase):
    # Reuse only fixture helpers; inheriting the TestCase would duplicate its suite.
    _flow = publication_fixture.NativePublicationTests
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

    def assert_original_facade(self):
        reader = self.gh.read_client()
        self.assertEqual(reader._identity(), {'id': 11, 'login': 'openboa'})
        self.assertEqual(reader.repository('example/product')['id'], self.gh.cfg['repository_id'])
        self.assertEqual(reader.decision_progress_source('example/product', 4)['record'], self.gh.note)
        self.assertFalse(callable(getattr(reader, '_credential_selected', None)))
        self.assertFalse(callable(getattr(reader, '_request_timeout', None)))

    def add_relevant_v2_pair(self):
        context, receipt = literal_pair(self.gh.note)
        self.gh.extra_comments.extend([comment(810, context), comment(811, receipt)])
        source = self.gh.read_client()
        self.assertEqual(source.comments('example/product', 4), self.gh.extra_comments)
        self.assertEqual(source.comments('example/product', 4)[0]['user'], source._identity())

    def assert_held(self, reply, candidate, writes):
        self.assertIn(reply['request']['outcome'], {'waiting', 'rejected', 'unknown'}, reply)
        self.assertIsNone(reply['request']['receipt'], reply)
        self.assertIsNone(reply.get('handoff'), reply)
        self.no_publication(writes)
        self.assertEqual(self.gh.note['attempt_id'], candidate['attempt_id'])
        self.assertNotIn('native_step', self.gh.note)
        self.assertIsNone(self.gh.pr)
        self.assertEqual(git(self.path, 'rev-parse', 'HEAD'), candidate['head'])
        self.assertEqual(git(self.path, 'ls-remote', 'origin', 'refs/heads/hydra/issue-4'), '')

    async def test_no_native_claim_preserves_actual_legacy_publication(self):
        candidate = await self.reviewed()
        self.assert_original_facade()
        self.assertEqual(self.gh.extra_comments, [])
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

    async def test_relevant_v2_claim_blocks_actual_publication_without_v2_transport(self):
        candidate = await self.reviewed()
        self.assert_original_facade()
        self.add_relevant_v2_pair()
        writes = len(self.gh.writes)
        reply = await self.publish(self.publication_command(candidate))
        self.assert_held(reply, candidate, writes)

    async def test_relevant_v2_claim_blocks_typed_continuation_without_v2_transport(self):
        candidate = await self.reviewed()
        self.assert_original_facade()
        self.add_relevant_v2_pair()
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
        original = copy.deepcopy(self.gh.note)
        reply = await execute_command_v1(self.settings, command,
            context_provider=lambda: grant, github=self.gh, controller=self.controller)
        self.assert_held(reply, candidate, writes)
        self.assertEqual(self.gh.note.get('published_head'), original.get('published_head'))
        self.assertEqual(self.gh.note.get('pr_number'), original.get('pr_number'))
