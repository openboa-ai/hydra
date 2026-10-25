"""Original history, physical ownership and positive progress are the oracles."""
import copy
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import unittest

import test_work_creation as fixture
from creation_history_fixture import changed
from hydra_sdlc.native import NativeController


class CreationHistoryTests(unittest.IsolatedAsyncioTestCase):
    asyncSetUp = fixture.WorkCreationTests.asyncSetUp
    command = fixture.WorkCreationTests.command
    create = fixture.WorkCreationTests.create

    def hide_uncertain_issue(self):
        self.wire.fail_after.add('issue')
        def hide(kind, row):
            if kind == 'issue':
                self.wire.hidden_issues.add(row['number'])
                self.wire.hidden_comments.update(r['id'] for k, r in self.wire.writes if k == 'fence')
        self.wire.after_effect = hide

    def issue_posts(self):
        return sum(kind == 'issue' for kind, _ in self.wire.writes)

    async def test_missing_history_cannot_use_a_new_fence_as_first_use(self):
        self.controller.creation_source = None
        result = await self.create()
        self.assertNotEqual(result['request']['outcome'], 'applied', result)
        self.assertEqual(result['request']['reason'], 'creation_history_unsupported')
        self.assertEqual(self.wire.writes, [])

    async def test_incomplete_wrong_scope_or_nonoriginal_current_execution_never_dispatches(self):
        for alteration in [lambda h: changed(h, complete=False),
                lambda h: changed(h, scope=(999, self.wire.draft['outcome_key'])),
                lambda h: changed(h, current_first_execution=False)]:
            with self.subTest(alteration=alteration.__code__.co_firstlineno):
                self.history.transform = alteration
                result = await self.create()
                self.assertNotEqual(result['request']['outcome'], 'applied', result)
                self.assertEqual(self.wire.writes, [])

    async def test_source_failure_is_private_and_never_defaults_to_first_use(self):
        def fail(*args, **kwargs):
            raise RuntimeError(fixture.CANARY)
        self.history.read_work_creation_history = fail
        result = await self.create()
        self.assertNotEqual(result['request']['outcome'], 'applied', result)
        self.assertNotIn(fixture.CANARY, json.dumps(result))
        self.assertEqual(self.wire.writes, [])

    async def test_restart_with_hidden_results_keeps_original_uncertain_outcome(self):
        self.hide_uncertain_issue()
        first = await self.create()
        self.assertEqual(first['request']['outcome'], 'unknown', first)
        self.assertEqual(self.issue_posts(), 1)
        self.controller = NativeController(self.client,
            SimpleNamespace(root=Path(self.cfg['workspace_root'])), repos=self.cfg['repos'],
            host_alias=self.cfg['host_alias'], lock_path=self.cfg['lock_path'], operations=self.control)
        self.controller.creation_source = self.history
        second = await self.create()
        self.assertNotEqual(second['request']['outcome'], 'applied', second)
        self.assertEqual(self.issue_posts(), 1)

    async def test_same_physical_execution_cannot_be_replayed_as_a_fresh_claim(self):
        self.hide_uncertain_issue()
        await self.create()
        self.history.replay_next = True
        second = await self.create()
        self.assertNotEqual(second['request']['outcome'], 'applied', second)
        self.assertEqual(self.issue_posts(), 1)

    async def test_rewound_prior_dispatch_count_cannot_erase_live_observation_floor(self):
        self.hide_uncertain_issue()
        await self.create()
        def rewind(h):
            return changed(h, prior_calls=tuple(changed(r, writes=0, state='not_dispatched')
                                               for r in h.prior_calls))
        self.history.transform = rewind
        second = await self.create()
        self.assertNotEqual(second['request']['outcome'], 'applied', second)
        self.assertEqual(self.issue_posts(), 1)

    async def test_omitted_known_call_does_not_become_complete_empty_history(self):
        self.hide_uncertain_issue()
        await self.create()
        self.history.transform = lambda h: changed(h, prior_calls=())
        second = await self.create()
        self.assertNotEqual(second['request']['outcome'], 'applied', second)
        self.assertEqual(self.issue_posts(), 1)

    async def test_partial_history_retains_later_pending_identity_before_holding(self):
        def partial(h):
            # These are synthetic source records, not inferred from GitHub absence.
            from hydra_sdlc.creation_history import CreationPriorCall
            return changed(h, complete=False, prior_calls=(
                CreationPriorCall('old-a', 'execution-a', None, 0, 'not_dispatched'),
                CreationPriorCall('old-b', 'execution-b', 'b' * 64, 2, 'unconfirmed')))
        self.history.transform = partial
        first = await self.create()
        self.assertNotEqual(first['request']['outcome'], 'applied', first)
        self.assertEqual(self.wire.writes, [])
        def omit_later(h):
            from hydra_sdlc.creation_history import CreationPriorCall
            return changed(h, prior_calls=(CreationPriorCall(
                'old-a', 'execution-a', None, 0, 'not_dispatched'),))
        self.history.transform = omit_later
        second = await self.create()
        self.assertNotEqual(second['request']['outcome'], 'applied', second)
        self.assertEqual(self.wire.writes, [])

    async def test_unknown_prior_cannot_be_reclassified_as_a_fresh_zero_dispatch(self):
        from hydra_sdlc.creation_history import CreationPriorCall
        self.history.transform = lambda h: changed(h, complete=False, prior_calls=(
            CreationPriorCall('original-call', 'original-execution', None, None, 'unconfirmed'),))
        first = await self.create()
        self.assertNotEqual(first['request']['outcome'], 'applied', first)
        self.assertEqual(self.wire.writes, [])
        self.history.transform = lambda h: changed(h, prior_calls=(
            CreationPriorCall('original-call', 'original-execution', None, 0, 'not_dispatched'),))
        second = await self.create()
        self.assertNotEqual(second['request']['outcome'], 'applied', second)
        self.assertEqual(self.wire.writes, [])

    async def test_earlier_physical_delivery_contradicts_first_execution_of_same_invocation(self):
        from hydra_sdlc.creation_history import CreationPriorCall
        self.history.transform = lambda h: changed(h, prior_calls=(CreationPriorCall(
            h.owner.invocation_id, 'earlier-physical-execution', h.intent_digest, 0, 'not_dispatched'),))
        result = await self.create()
        self.assertNotEqual(result['request']['outcome'], 'applied', result)
        self.assertEqual(self.wire.writes, [])

    async def test_provider_revoked_inside_owner_validation_cannot_send_issue(self):
        def revoke():
            if self.history.current['writes'] == 1:
                self.controller.creation_source = None
        self.history.before_owner = revoke
        result = await self.create()
        self.assertNotEqual(result['request']['outcome'], 'applied', result)
        self.assertEqual([kind for kind, _ in self.wire.writes], ['fence'])

    async def test_actual_call_owner_change_before_issue_dispatch_preserves_fence_only(self):
        def replace_caller():
            if self.history.current['writes'] == 1:
                self.history.caller_binding = 'different-synthetic-caller'
        self.history.before_owner = replace_caller
        result = await self.create()
        self.assertNotEqual(result['request']['outcome'], 'applied', result)
        self.assertEqual([kind for kind, _ in self.wire.writes], ['fence'])

    async def test_history_provider_replaced_during_discovery_cannot_dispatch_issue(self):
        def replace(method, path, payload):
            if (method == 'GET' and path.startswith('/repos/' + fixture.REPO + '/issues/comments')
                    and len(self.wire.writes) == 1):
                self.controller.creation_source = None
        self.wire.before_request = replace
        result = await self.create()
        self.assertNotEqual(result['request']['outcome'], 'applied', result)
        self.assertEqual([kind for kind, _ in self.wire.writes], ['fence'])

    async def test_positively_undispatched_prior_call_does_not_block_normal_registration(self):
        self.history.begin()
        # The fixture observes this actual synthetic call had no physical effect.
        result = await self.create()
        self.assertEqual(result['request']['outcome'], 'applied', result)
        self.assertEqual([kind for kind, _ in self.wire.writes], ['fence', 'issue', 'binding'])

    async def test_confirmed_registration_readback_needs_no_new_history_claim(self):
        first = await self.create()
        self.assertEqual(first['request']['outcome'], 'applied', first)
        writes = copy.deepcopy(self.wire.writes)
        self.controller.creation_source = None
        second = await self.create()
        self.assertEqual(second['request']['receipt'], first['request']['receipt'])
        self.assertEqual(self.wire.writes, writes)

    @unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional pinned MCP SDK not installed')
    async def test_actual_mcp_no_history_has_no_fallback_or_private_source_echo(self):
        from mcp import Client
        from hydra_sdlc.mcp import create_server
        self.controller.creation_source = None
        server = create_server(self.controller, command_config_path=self.config_path,
            command_context_provider=lambda ctx: self.context)
        async with Client(server) as client:
            result = await client.call_tool('hydra_command_v1', {'command': self.command()})
        self.assertFalse(result.is_error)
        value = result.structured_content or json.loads(result.content[0].text)
        self.assertEqual(value['request']['reason'], 'creation_history_unsupported', value)
        self.assertNotIn(fixture.CANARY, json.dumps(value))
        self.assertEqual(self.wire.writes, [])
