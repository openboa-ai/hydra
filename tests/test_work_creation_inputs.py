"""Adopted and exact-reference conditions share the same creation boundary."""
import hashlib
import unittest

import test_work_creation as fixture


class CreationInputTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.WorkCreationTests.asyncSetUp
    command = fixture.WorkCreationTests.command
    create = fixture.WorkCreationTests.create

    def configure(self, kind, clauses):
        self.wire = fixture.Wire()
        self.client = fixture.WireClient(self.wire)
        # Each representation is a new isolated provider world. Preserve the
        # same behavioral assertions without carrying another world's calls.
        self.controller = fixture.NativeController(self.client,
            fixture.SimpleNamespace(root=fixture.Path(self.cfg['workspace_root'])),
            repos=self.cfg['repos'], host_alias=self.cfg['host_alias'],
            lock_path=self.cfg['lock_path'], operations=self.control)
        self.history = fixture.CreationHistoryFixture(self.wire)
        self.controller.creation_source = self.history
        request = self.wire.request
        def observed_request(method, path, payload):
            if method == 'POST':
                self.history.dispatch()
            return request(method, path, payload)
        self.wire.request = observed_request
        self.wire.spec_content += '\n## INPUTS\n```json\n' + fixture.canonical({'clauses': clauses}) + '\n```\n'
        data = self.wire.spec_content.encode()
        self.wire.spec_sha = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data,
                                         usedforsecurity=False).hexdigest()
        self.wire.proposal['input_contract'] = ({'kind': 'adopted', 'clauses': clauses} if kind == 'adopted'
            else {'kind': 'reference', 'ref': {'repository_id': 123,
                'path': 'docs/engineering/parser/spec.md', 'revision': fixture.BASE, 'selector': 'INPUTS'}})
        self.wire.refresh_source()

    def clause(self, repository_id, issue_number):
        ref = {'repository_id': 123, 'path': 'docs/engineering/parser/spec.md',
               'revision': fixture.BASE, 'selector': 'R-EMPTY-1'}
        return {'producer': {'repository_id': repository_id, 'issue_number': issue_number},
            'requirements': [ref], 'required_stage': 'post_merge_verified', 'basis': ref}

    async def test_unregistered_nested_producer_is_held_for_both_representations(self):
        for kind in ('adopted', 'reference'):
            with self.subTest(kind=kind):
                self.configure(kind, [self.clause(999, 10)])
                reply = await self.create()
                self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
                self.assertEqual(self.wire.writes, [])

    async def test_actual_new_issue_cannot_be_its_own_producer_in_either_representation(self):
        for kind in ('adopted', 'reference'):
            with self.subTest(kind=kind):
                self.configure(kind, [self.clause(123, 11)])
                reply = await self.create()
                self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
                self.assertEqual([name for name, _ in self.wire.writes], ['fence', 'issue'])
                self.assertIsNone(reply['request']['receipt'])

    async def test_both_explicit_empty_condition_forms_still_make_real_registration_progress(self):
        for kind in ('adopted', 'reference'):
            with self.subTest(kind=kind):
                self.configure(kind, [])
                reply = await self.create()
                self.assertEqual(reply['request']['outcome'], 'applied', reply)
                self.assertEqual([name for name, _ in self.wire.writes], ['fence', 'issue', 'binding'])
                self.assertEqual(reply['request']['receipt']['stage'], 'registered')
