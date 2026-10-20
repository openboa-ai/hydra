"""NC-D03/04/06/09/10: positive observations and noninterference, no live client."""
import asyncio
import contextlib
import importlib.util
import io
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hydra_sdlc.native_context import (
    SDKProfile, load_sdk_profile, probe_context, project_probe, read_probe,
)


class Form:
    def __bool__(self):
        raise AssertionError('empty typed declaration must not be coerced')


class Url:
    pass


class Elicitation:
    def __init__(self, form=None, url=None):
        self.form, self.url = form, url


class Capabilities:
    def __init__(self, elicitation=None):
        self.elicitation = elicitation


class ContextFixture:
    def __init__(self, protocol='2025-11-25', channel=True, capabilities=None, error=None):
        self.values = dict(protocol_version=protocol, session=SimpleNamespace(can_send_request=channel),
                           client_capabilities=capabilities)
        self.reads = []
        self.error = error or {}

    def __getattr__(self, key):
        if key not in self.values:
            raise AssertionError('unrelated context property accessed')
        self.reads.append(key)
        if key in self.error:
            raise self.error[key]
        return self.values[key]


PROFILE = SDKProfile(ContextFixture, Capabilities, Elicitation, Form, Url)
UNKNOWN = {
    'schema_version': 1, 'protocol_version': None,
    'request_channel': 'unknown', 'form_elicitation': 'unknown',
    'input_required_sdk': 'present', 'input_required_client': 'unverified',
    'caller_task_binding': 'unverified',
}


class NativeContextTests(unittest.TestCase):
    def fixture(self, **kwargs):
        kwargs.setdefault('capabilities', Capabilities(Elicitation(form=Form())))
        return ContextFixture(**kwargs)

    def test_independent_positive_and_negative_json_vectors(self):
        directory = Path(__file__).parent / 'fixtures/mvp/native-context-v1'
        vectors = list(directory.glob('*.json'))
        self.assertGreaterEqual(len(vectors), 5)
        for path in vectors:
            with self.subTest(case=path.stem):
                case = json.loads(path.read_text())
                source = case['input']
                if source is None:
                    context = None
                else:
                    capabilities = {
                        'form': Capabilities(Elicitation(form=Form())),
                        'url': Capabilities(Elicitation(url=Url())),
                        'empty': Capabilities(),
                        'ambiguous': Capabilities(Elicitation()),
                        'missing': None,
                    }[source['capabilities']]
                    context = ContextFixture(source['protocol'], source['channel'], capabilities)
                self.assertEqual(probe_context(context, PROFILE), case['expected'])

    def test_channel_and_form_fail_independently_and_read_once(self):
        for field, expected in (
                ('session', {'request_channel': 'unknown', 'form_elicitation': 'declared'}),
                ('client_capabilities', {'request_channel': 'available', 'form_elicitation': 'unknown'})):
            for error in (AttributeError(), TypeError(), ValueError(), RuntimeError()):
                with self.subTest(field=field, error=type(error).__name__):
                    context = self.fixture(error={field: error})
                    actual = probe_context(context, PROFILE)
                    self.assertEqual(actual, {**UNKNOWN, 'protocol_version': '2025-11-25', **expected})
                    self.assertEqual(context.reads, ['protocol_version', 'session', 'client_capabilities'])

    def test_bad_scalars_and_future_protocol_do_not_echo(self):
        for protocol in ('2099-12-31', 'X' * 65, '\nSYNTHETIC_PRIVATE_CANARY', [], 1, None):
            context = self.fixture(protocol=protocol)
            self.assertEqual(probe_context(context, PROFILE), UNKNOWN)
            self.assertEqual(context.reads, ['protocol_version'])
        for channel in (0, 1, 'true', [], None):
            self.assertEqual(probe_context(self.fixture(channel=channel), PROFILE)['request_channel'], 'unknown')
        actual = probe_context(self.fixture(protocol='2026-07-28', channel=True), PROFILE)
        self.assertEqual(actual['request_channel'], 'unknown')
        self.assertEqual(actual['form_elicitation'], 'declared')

    def test_malformed_and_old_declarations_are_unknown(self):
        for capabilities in ({'elicitation': {'form': {}}},
                             Capabilities({}), Capabilities(Elicitation(form={})), None):
            actual = probe_context(self.fixture(capabilities=capabilities), PROFILE)
            self.assertEqual(actual['form_elicitation'], 'unknown')
        for protocol in ('2024-11-05', '2025-03-26'):
            context = self.fixture(protocol=protocol)
            self.assertEqual(probe_context(context, PROFILE)['form_elicitation'], 'unknown')
            self.assertNotIn('client_capabilities', context.reads)

    def test_unexpected_diagnostic_errors_never_leak_and_cancellation_propagates(self):
        for field in ('protocol_version', 'session', 'client_capabilities'):
            context = self.fixture(error={field: OSError('SYNTHETIC_PRIVATE_CANARY')})
            with contextlib.redirect_stdout(io.StringIO()) as out, contextlib.redirect_stderr(io.StringIO()) as err:
                self.assertEqual(probe_context(context, PROFILE), UNKNOWN)
            self.assertEqual(out.getvalue() + err.getvalue(), '')
            for error in (asyncio.CancelledError(), KeyboardInterrupt(), SystemExit()):
                with self.assertRaises(type(error)):
                    probe_context(self.fixture(error={field: error}), PROFILE)

    def test_unrelated_metadata_is_never_read_or_hashed(self):
        original = probe_context(self.fixture(), PROFILE)
        context = self.fixture()
        context.values.update(_meta={'task_id': 'forged', 'human_approved': True,
                                    'secret': 'SYNTHETIC_PRIVATE_CANARY', 'blob': ['x' * 1000] * 1000},
                              headers={'authorization': 'SYNTHETIC_PRIVATE_CANARY'})
        # Make even a read (not merely serialization) of unrelated fields fail.
        context.error.update({key: AssertionError('private field accessed') for key in ('_meta', 'headers')})
        self.assertEqual(json.dumps(probe_context(context, PROFILE)), json.dumps(original))
        self.assertEqual(context.reads, ['protocol_version', 'session', 'client_capabilities'])

    def test_requests_do_not_reuse_previous_context_or_infer_identity(self):
        a = self.fixture()
        b = self.fixture(protocol='2026-07-28', channel=False, capabilities=Capabilities())
        second = probe_context(b, PROFILE)
        first = probe_context(a, PROFILE)
        self.assertEqual(first['form_elicitation'], 'declared')
        self.assertEqual(second['form_elicitation'], 'not_declared')
        self.assertEqual(first['caller_task_binding'], 'unverified')
        first['caller_task_binding'] = 'changed'
        self.assertEqual(probe_context(a, PROFILE)['caller_task_binding'], 'unverified')
        self.assertEqual(probe_context({'task_id': 'fake'}, PROFILE), UNKNOWN)
        self.assertEqual(probe_context(a, SDKProfile()), {**UNKNOWN, 'input_required_sdk': 'unknown'})

    def test_consumer_rejects_only_invalid_probe_not_legacy_status(self):
        valid = {**UNKNOWN, 'protocol_version': '2025-11-25', 'request_channel': 'available',
                 'form_elicitation': 'declared'}
        status = {'projects': ['unchanged'], 'native_context': valid}
        self.assertEqual(read_probe(status), valid)
        for change in ({'schema_version': 2}, {'schema_version': True}, {'extra': 'x'},
                       {'caller_task_binding': 'verified'}, {'request_channel': 1},
                       {'form_elicitation': []}, {'protocol_version': 'future'}):
            self.assertIsNone(read_probe({**status, 'native_context': {**valid, **change}}))
            self.assertEqual(status['projects'], ['unchanged'])
        self.assertIsNone(read_probe({'projects': ['unchanged']}))
        self.assertIsNone(read_probe({'native_context': {}}))

    def test_projection_cannot_promote_unknown_profile(self):
        self.assertEqual(project_probe(sdk_present=False, protocol='2025-11-25', channel=True,
                                      form='declared'), {**UNKNOWN, 'input_required_sdk': 'unknown'})


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional pinned MCP SDK not installed')
class RealSDKProfileTests(unittest.TestCase):
    def test_real_typed_context_and_missing_api_or_metadata(self):
        from mcp.server.mcpserver import Context
        from mcp_types import ClientCapabilities
        profile = load_sdk_profile()
        self.assertTrue(profile.supported)
        context = Context(request_context=SimpleNamespace(protocol_version='2025-11-25',
            session=SimpleNamespace(can_send_request=True,
                                    client_capabilities=ClientCapabilities(elicitation={'form': {}}))))
        self.assertEqual(probe_context(context, profile), {
            **UNKNOWN, 'protocol_version': '2025-11-25', 'request_channel': 'available',
            'form_elicitation': 'declared'})
        self.assertEqual(probe_context(Context(), profile), UNKNOWN)
        for metadata in ('2.2.0', RuntimeError('SYNTHETIC_PRIVATE_CANARY')):
            with patch('hydra_sdlc.native_context.version', **(
                    {'side_effect': metadata} if isinstance(metadata, Exception) else {'return_value': metadata})):
                self.assertFalse(load_sdk_profile().supported)
        with patch('mcp_types.InputRequiredResult', object()):
            self.assertFalse(load_sdk_profile().supported)


if __name__ == '__main__':
    unittest.main()
