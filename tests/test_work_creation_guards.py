"""Original-outcome uncertainty and real-source obligations for P10."""
import copy
import hashlib
import importlib.util
import json
import unittest
from urllib.parse import urlsplit

import test_work_creation as fixture


class CreationGuardTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.WorkCreationTests.asyncSetUp
    command = fixture.WorkCreationTests.command
    create = fixture.WorkCreationTests.create

    def counts(self):
        return {kind: sum(k == kind for k, _ in self.wire.writes)
                for kind in ('fence', 'issue', 'binding')}

    async def test_omitted_acknowledged_fence_and_uncertain_issue_never_authorize_another_issue(self):
        self.wire.fail_after.add('issue')
        def hide(kind, row):
            if kind == 'issue':
                self.wire.hidden_issues.add(row['number'])
                self.wire.hidden_comments.update(value['id'] for name, value in self.wire.writes
                                                if name == 'fence')
        self.wire.after_effect = hide
        first = await self.create()
        self.assertEqual(first['request']['outcome'], 'unknown', first)
        self.assertEqual(self.counts()['issue'], 1)
        second = await self.create()
        self.assertNotEqual(second['request']['outcome'], 'applied', second)
        self.assertEqual(self.counts()['issue'], 1, 'Zero discovery must not reset original dispatch history')

    async def test_same_pending_outcome_in_another_valid_container_cannot_create_again(self):
        wire = self.wire
        wire.fail_after.add('issue')
        wire.after_effect = lambda kind, row: wire.hidden_issues.add(row['number']) if kind == 'issue' else None
        first = await self.create()
        self.assertEqual(first['request']['outcome'], 'unknown', first)
        original = copy.deepcopy(wire.comments[77])
        outcome = wire.draft['outcome_key']
        wire.issues[5] = wire.issue(5, 'Another parser observation',
            'The same accepted goal needs this parser result.', fixture.HUMAN)
        wire.draft['create_key'] = '55555555-5555-4555-8555-555555555555'
        wire.draft['source_ref'] = {'kind': 'github_issue', 'repository_id': 123, 'issue_number': 5}
        wire.draft['source_digest'] = fixture.source_digest(wire.issues[5])
        wire.draft['body'] = 'Implement the accepted parser behavior.\n\n' + fixture.marker(
            'hydra-create', {'create_key': wire.draft['create_key']})
        wire.refresh_source()
        body = wire.comments[77]['body']
        wire.comments[77] = original
        wire.comments[79] = wire.comment(79, 5, body)
        wire.reference = {'kind': 'github_comment', 'repository_id': 123, 'issue_number': 5,
            'comment_id': 79, 'revision': hashlib.sha256(body.encode()).hexdigest()}
        self.assertEqual(wire.draft['outcome_key'], outcome)
        request = wire.request
        def another_container(method, path, payload):
            if method == 'POST' and urlsplit(path).path == '/repos/' + fixture.REPO + '/issues/5/comments':
                self.assertEqual(set(payload), {'body'})
                self.assertTrue(payload['body'].startswith('<!-- hydra-create-dispatch:v1 '))
                row = wire.comment(wire.next_comment, 5, payload['body'])
                wire.next_comment += 1
                wire.comments[row['id']] = row
                wire.writes.append(('fence', copy.deepcopy(row)))
                return copy.deepcopy(row)
            return request(method, path, payload)
        wire.request = another_container
        command = self.command()
        command['expected']['source_checks'][0]['resource']['id'] = fixture.REPO + '/comments/79'
        second = await self.create(command)
        self.assertEqual(wire.comments[77], original)
        self.assertNotEqual(second['request']['outcome'], 'applied', second)
        self.assertEqual(self.counts()['issue'], 1, 'Draft location cannot reset the same outcome')

    async def test_delegation_removed_during_discovery_prevents_new_issue_dispatch(self):
        removed = False
        def remove(method, path, payload):
            nonlocal removed
            if (method == 'GET' and urlsplit(path).path == '/repos/' + fixture.REPO + '/issues/comments'
                    and self.counts() == {'fence': 1, 'issue': 0, 'binding': 0}):
                self.wire.comments.pop(78, None)
                removed = True
        self.wire.before_request = remove
        reply = await self.create()
        self.assertTrue(removed)
        self.assertEqual(self.counts()['issue'], 0)
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)

    async def test_valid_registration_reads_the_actual_immutable_specification(self):
        reply = await self.create()
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        paths = [urlsplit(path).path for method, path, _ in self.wire.calls if method == 'GET']
        self.assertIn('/repos/' + fixture.REPO + '/git/commits/' + fixture.BASE, paths)
        self.assertIn('/repos/' + fixture.REPO + '/git/blobs/' + self.wire.spec_sha, paths)

    async def test_missing_immutable_revision_or_path_cannot_register_as_accepted(self):
        self.wire.proposal['spec'] = {'path': 'docs/engineering/absent/spec.md', 'revision': 'f' * 40}
        self.wire.proposal['requirements'] = [{'repository_id': 123,
            'path': 'docs/engineering/absent/spec.md', 'revision': 'f' * 40, 'selector': 'R-ABSENT'}]
        self.wire.refresh_source()
        reply = await self.create()
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.wire.writes, [])

    async def test_unrelated_issue_with_null_body_does_not_block_registration(self):
        self.wire.issues[8] = self.wire.issue(8, 'Ordinary unbound request', None, fixture.HUMAN)
        reply = await self.create()
        self.assertEqual(reply['request']['outcome'], 'applied', reply)

    @unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional pinned MCP SDK not installed')
    async def test_malformed_known_creation_is_rejected_before_authority_or_io(self):
        from mcp import Client
        from hydra_sdlc.mcp import create_server
        contexts = []
        def grant(ctx):
            contexts.append(ctx)
            return self.context
        command = self.command()
        command['parameters']['body'] = fixture.CANARY
        server = create_server(self.controller, command_config_path=self.config_path,
            command_context_provider=grant)
        async with Client(server) as client:
            result = await client.call_tool('hydra_command_v1', {'command': command})
        self.assertTrue(result.is_error)
        self.assertNotIn(fixture.CANARY, json.dumps(result.model_dump()))
        self.assertEqual(contexts, [])
        self.assertEqual(self.wire.calls, [])
