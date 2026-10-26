"""Missing installation-authority boundaries through the actual SDK producer."""
from datetime import datetime, timezone
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hydra_sdlc.control import load_host_config
from hydra_sdlc.native_admission import installation_admission_provider
from hydra_sdlc.runtime_identity import capture_runtime_identity
from delegated_decision_fixture import InstallationFixture


EXPIRY = '2099-01-01T00:00:00Z'
BEFORE_EXPIRY = datetime(2098, 12, 31, 23, 59, 59, tzinfo=timezone.utc)
AT_EXPIRY = datetime(2099, 1, 1, tzinfo=timezone.utc)


class DelegatedDecisionAuthorityTests(InstallationFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.setup_installation()

    def assert_rejected_without_effects(self, reply, reason):
        self.assertEqual(reply['request']['outcome'], 'rejected', reply)
        self.assertEqual(reply['request']['reason'], reason, reply)
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual(reply['request']['effect_refs'], [])
        self.assertEqual(self.transport.effects, [])

    def admission_command(self):
        command = self.command()
        command.update(action='admission_set', target={'kind': 'repository', 'repository_id': 123},
                       effect_key=None, parameters={'mode': 'paused'})
        return command

    def test_workflow_expiry_is_required_canonical_utc_even_when_disabled(self):
        invalid = (None, '"2099-01-01T00:00:00+00:00"', '"2099-01-01T00:00:00.1Z"',
                   '"2099-01-01T00:00:00z"', '"2099-02-30T00:00:00Z"',
                   '"2099-01-01T00:00:60Z"', '2099-01-01T00:00:00Z')
        for enabled in (True, False):
            self.write_profile(enabled, operations=('workflow_step.decision_submit',))
            self.assertEqual(load_host_config(self.settings)['native_workflow_control'], {
                'schema_version': 1, 'enabled': enabled, 'repository_ids': [123],
                'operations': ['workflow_step.decision_submit'], 'expires_at': EXPIRY})
            for expiry in invalid:
                with self.subTest(enabled=enabled, expiry=expiry):
                    self.write_profile(enabled)
                    replacement = '' if expiry is None else 'expires_at=' + expiry
                    self.settings.write_text(self.settings.read_text().replace(
                        'expires_at="2099-01-01T00:00:00Z"', replacement))
                    with self.assertRaises(ValueError) as raised:
                        load_host_config(self.settings)
                    self.assertEqual(str(raised.exception), 'Invalid installed host settings')

    def test_workflow_provider_refuses_non_sdk_context_before_reading_settings(self):
        self.write_profile(True)
        provider, command = installation_admission_provider(self.settings), self.command()
        contexts = (None, {}, {'authorized': True, 'surface': 'native'},
                    SimpleNamespace(request_context=SimpleNamespace(method='tools/call'),
                                    surface='native', authorized=True))
        with patch('hydra_sdlc.control.load_host_config',
                   side_effect=AssertionError('Non-SDK data must not reach authority settings')) as load_settings:
            for context in contexts:
                with self.subTest(context_type=type(context).__name__):
                    self.assertIsNone(provider.for_command(context, command))
            load_settings.assert_not_called()

    async def test_workflow_expires_at_exact_utc_cutoff_despite_valid_admission_grant(self):
        self.write_profile(True, admission=(123,))
        self.make_server(new_profile=True)
        before = self.control.snapshot()
        with patch('hydra_sdlc.native_workflow._now', return_value=AT_EXPIRY), \
                patch('hydra_sdlc.native_admission._now', return_value=BEFORE_EXPIRY):
            reply = self.reply(await self.invoke())
        self.assert_rejected_without_effects(reply, 'authority_unavailable')
        self.assertEqual(self.control.snapshot(), before)

    async def test_clock_expiry_after_context_blocks_receipt_without_changing_config(self):
        self.write_profile(True)
        self.make_server(new_profile=True)
        settings, before = self.settings.read_bytes(), self.control.snapshot()
        moment = [BEFORE_EXPIRY]

        def expire(kind, body):
            if kind == 'context':
                moment[0] = AT_EXPIRY

        self.transport.post_behavior = expire
        with patch('hydra_sdlc.native_workflow._now', side_effect=lambda: moment[0]):
            reply = self.reply(await self.invoke())
        self.assertEqual(reply['request']['outcome'], 'waiting', reply)
        self.assertEqual(reply['request']['reason'], 'authority_unavailable', reply)
        self.assertIsNone(reply['request']['receipt'])
        self.assertEqual([kind for kind, _ in self.transport.effects], ['context'])
        self.assertEqual(reply['request']['effect_refs'], [
            {'source': 'github', 'kind': 'issue_comment', 'id': 'example/product/comments/100'}])
        self.assertTrue(self.controller.lock_path.read_bytes(), 'Unfinished publication retains ownership')
        self.assertEqual(self.settings.read_bytes(), settings)
        self.assertEqual(self.control.snapshot(), before)

    async def test_continue_or_handoff_grant_does_not_imply_decision_publication(self):
        for operations in (('workflow_step.continue',), ('command_reply.native_handoff_v1',)):
            with self.subTest(operations=operations):
                self.write_profile(True, operations=operations, admission=(123,))
                self.make_server(new_profile=True)
                before = self.control.snapshot()
                reply = self.reply(await self.invoke())
                self.assert_rejected_without_effects(reply, 'authority_unavailable')
                self.assertEqual(self.control.snapshot(), before)

    async def test_workflow_scope_and_expiry_cannot_supply_admission_authority(self):
        cases = (((999,), EXPIRY, 'authority_denied'),
                 ((123,), '2000-01-01T00:00:00Z', 'authority_unavailable'))
        for repositories, expiry, reason in cases:
            with self.subTest(admission_repositories=repositories, admission_expiry=expiry):
                self.write_profile(True, admission=repositories)
                # Change only the separately scoped admission profile's last expiry.
                prefix, _, suffix = self.settings.read_text().rpartition('expires_at="' + EXPIRY + '"')
                self.settings.write_text(prefix + 'expires_at="' + expiry + '"' + suffix)
                self.make_server(new_profile=True)
                before = self.control.snapshot()
                with patch('hydra_sdlc.native_admission._now', return_value=BEFORE_EXPIRY), \
                        patch('hydra_sdlc.native_workflow._now', return_value=BEFORE_EXPIRY):
                    reply = self.reply(await self.invoke(self.admission_command()))
                self.assert_rejected_without_effects(reply, reason)
                self.assertEqual(self.control.snapshot(), before)

    async def test_each_workflow_authority_field_invalidates_the_old_command_runtime_pin(self):
        changes = (
            ('enabled', {'enabled': False}, 'authority_unavailable'),
            ('repository_ids', {'repositories': (123, 999)}, 'stale_runtime'),
            ('operations', {'operations': ('workflow_step.decision_submit',)}, 'stale_runtime'),
            ('expires_at', {'expires': '2099-01-02T00:00:00Z'}, 'stale_runtime'),
        )
        for field, replacement, reason in changes:
            with self.subTest(field=field):
                self.write_profile(True)
                self.make_server(new_profile=True)
                command = self.command()
                original = capture_runtime_identity(load_host_config(self.settings), self.control)
                self.write_profile(**{'enabled': True, **replacement})
                changed = capture_runtime_identity(load_host_config(self.settings), self.control)
                self.assertNotEqual(changed['config_digest'], original['config_digest'])
                self.make_server(new_profile=True)
                reply = self.reply(await self.invoke(command))
                self.assert_rejected_without_effects(reply, reason)
