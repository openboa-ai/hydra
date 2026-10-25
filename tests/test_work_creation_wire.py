"""Receipt grammar is distinct from source qualification and execution authority."""
import copy
import importlib.util
import json
import unittest

import test_work_creation as fixture
from hydra_sdlc import projection as p


class CreationWireTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.WorkCreationTests.asyncSetUp
    command = fixture.WorkCreationTests.command
    create = fixture.WorkCreationTests.create

    def structural(self, reply):
        try:
            p.command_result(reply['request'], p.observations_index(reply['observations']))
        except p.ProjectionError:
            return False
        return True

    @unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional pinned MCP SDK not installed')
    async def test_actual_mcp_registration_and_replay_have_closed_structural_receipts(self):
        from mcp import Client
        from hydra_sdlc.mcp import create_server
        server = create_server(self.controller, command_config_path=self.config_path,
            command_context_provider=lambda ctx: self.context)
        async with Client(server) as client:
            results = [await client.call_tool('hydra_command_v1', {'command': self.command()})
                       for _ in range(2)]
        for result in results:
            self.assertFalse(result.is_error)
            reply = result.structured_content or json.loads(result.content[0].text)
            self.assertEqual(reply['request']['outcome'], 'applied')
            self.assertTrue(self.structural(reply), 'Actual registered receipt must match CP data grammar')
        self.assertEqual([kind for kind, _ in self.wire.writes], ['fence', 'issue', 'binding'])

    async def test_applied_creation_requires_its_receipt_and_both_observed_effect_refs(self):
        reply = await self.create()
        for name in ('receipt', 'issue_ref', 'binding_ref', 'outcome'):
            with self.subTest(missing=name):
                altered = copy.deepcopy(reply)
                if name == 'receipt':
                    altered['request']['receipt'] = None
                elif name == 'outcome':
                    altered['request']['outcome'] = 'unknown'
                else:
                    ref = altered['request']['receipt'][name]
                    altered['request']['effect_refs'] = [v for v in altered['request']['effect_refs'] if v != ref]
                self.assertFalse(self.structural(altered))

    async def test_creation_receipt_cannot_be_assigned_to_another_action_or_repository(self):
        reply = await self.create()
        for name in ('action', 'target', 'issue_ref'):
            with self.subTest(mismatch=name):
                altered = copy.deepcopy(reply)
                if name == 'action':
                    altered['request']['action'] = 'workflow_step'
                    altered['request']['target']['issue_number'] = 11
                elif name == 'target':
                    altered['request']['target']['repository_id'] = 999
                else:
                    altered['request']['receipt']['issue_ref']['id'] = '123:12'
                self.assertFalse(self.structural(altered))

    async def test_closed_receipt_fields_and_registered_stage_reject_malformed_values(self):
        reply = await self.create()
        mutations = {'stage': 'prepared', 'repository_id': True, 'issue_number': 0,
            'create_key': '33333333-3333-5333-8333-333333333333', 'draft_digest': 'x' * 64,
            'proposal_digest': None, 'binding_digest': 'a' * 63,
            'issue_ref': {'source': 'hydra', 'kind': 'issue', 'id': '123:11'},
            'binding_ref': {'source': 'github', 'kind': 'issue_comment', 'id': 'invalid-locator'},
            'unexpected': fixture.CANARY}
        for key, value in mutations.items():
            with self.subTest(field=key):
                altered = copy.deepcopy(reply)
                altered['request']['receipt'][key] = value
                self.assertFalse(self.structural(altered))

    async def test_unknown_creation_without_receipt_remains_structurally_readable(self):
        self.controller.creation_source = None
        reply = await self.create()
        self.assertEqual(reply['request']['outcome'], 'unknown')
        self.assertIsNone(reply['request']['receipt'])
        self.assertTrue(self.structural(reply))

    async def test_structural_receipt_never_qualifies_bound_standard_or_projection_source(self):
        reply = await self.create()
        frame = json.loads((fixture.Path(__file__).parent / 'fixtures/control-v3/inputs.json').read_text())['frame']
        frame.update(runtime=copy.deepcopy(reply['runtime']), request=copy.deepcopy(reply['request']),
            observations=copy.deepcopy(reply['observations']), projects=[], work=[], relations=[], retry_hints=[])
        frame['page'] = {'state': 'complete', 'scope': 'fixture:creation-receipt',
            'returned_count': 0, 'total_count': 0, 'next_cursor': None, 'reason': None}
        for name, value, read in [('standard', reply, p.standard_reply), ('projection', frame, p.validate_frame)]:
            with self.subTest(profile=name):
                try:
                    read(value)
                except p.ProjectionError as exc:
                    reason = exc.reason
                else:
                    reason = None
                self.assertIn(reason, {'unsupported_command_source', 'unsupported_receipt_source'})
