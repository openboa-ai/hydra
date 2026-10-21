"""Credential context is read policy, never control authority."""
from pathlib import Path
import copy
import json
import subprocess
import unittest
from unittest.mock import patch

from hydra_sdlc import projection as p
from hydra_sdlc.projection_read import ProjectionClient
from test_projection_read import ReadFixture

ROOT = Path(__file__).resolve().parents[1]
OWNERS = json.loads((ROOT / 'tests/fixtures/control-v3/source-owners.json').read_text())


class ProjectionContextTests(unittest.TestCase):
    def test_cleanup_wire_requires_the_exact_receipt_resource(self):
        inputs = json.loads((ROOT / 'tests/fixtures/control-v3/inputs.json').read_text())
        cases = {case['name']: case for case in inputs['cases']}
        for name in ('cleanup-exact-resource', 'cleanup-foreign-resource'):
            frame = copy.deepcopy(inputs['frame'])
            frame['request'] = cases[name]['changes'][0]['value']
            if cases[name]['accepted']:
                p.validate_frame(frame)
            else:
                with self.assertRaises(p.ProjectionError, msg='Foreign cleanup resource became verified proof'):
                    p.validate_frame(frame)

    def test_every_observation_kind_keeps_its_source_even_when_unavailable(self):
        self.assertEqual(set(OWNERS), set(p.SOURCE_FIELDS))
        template = ReadFixture().read(refresh=False)['observations'][0]
        for kind, owner in OWNERS.items():
            for source in ('github', 'codex', 'resource_provider', 'hydra'):
                with self.subTest(kind=kind, source=source):
                    value = copy.deepcopy(template)
                    value.update(revision=None, value=None, observed_at=None, availability='unavailable', reason='fixture_unavailable')
                    value['coverage'].update(state='unavailable', returned_count=0, total_count=None,
                                             next_cursor=None, reason='fixture_unavailable')
                    value['resource'] = {'source': source, 'kind': kind, 'id': 'fixture'}
                    if source == owner:
                        p.observation(value)
                    else:
                        with self.assertRaises(p.ProjectionError, msg='A foreign source impersonated the kind owner'):
                            p.observation(value)

    def test_actual_selected_credentials_produce_distinct_binding_local_wait_scopes(self):
        def read(token):
            fixture = ReadFixture()
            fixture.client = ProjectionClient()
            calls = []
            def process(argv, **kwargs):
                calls.append(argv[:])
                if argv[1:3] == ['auth', 'token']:
                    return subprocess.CompletedProcess(argv, 0, token + '\n', '')
                if argv[-1] == 'user':
                    return subprocess.CompletedProcess(argv, 0, json.dumps({'login': 'openboa'}), '')
                return subprocess.CompletedProcess(argv, 1,
                    'HTTP/2.0 429 Too Many Requests\r\nRetry-After: 3600\r\n\r\n{}', 'HTTP 429')
            with patch('hydra_sdlc.github.subprocess.run', side_effect=process):
                frame = fixture.read()
            self.assertTrue(calls)
            self.assertTrue(frame['retry_hints'])
            self.assertTrue(all(h['basis'] == 'provider' and h['after_seconds'] >= 3590 for h in frame['retry_hints']))
            self.assertNotIn(token, json.dumps(frame))
            return frame['retry_hints'][0]['scope']
        first = read('synthetic-credential-alpha')
        second = read('synthetic-credential-beta')
        self.assertNotEqual(first, second, 'A rotated credential inherited the previous credential wait scope')
        self.assertEqual(first, read('synthetic-credential-alpha'), 'Returning to a credential lost its policy scope')

    def test_context_probe_uses_only_local_credential_selection_and_scopes_by_binding(self):
        from hydra_sdlc.cli import read_connection_context
        from test_control_projection import EPOCH
        calls = []
        def process(argv, **kwargs):
            calls.append(argv)
            self.assertEqual(argv[1:3], ['auth', 'token'], 'A local context probe made HTTP')
            self.assertLessEqual(kwargs['timeout'], 2)
            return subprocess.CompletedProcess(argv, 0, 'synthetic-private-credential\n', '')
        with patch('hydra_sdlc.github.subprocess.run', side_effect=process):
            first = read_connection_context(EPOCH)
            again = read_connection_context(EPOCH)
            other = read_connection_context('00000000-0000-4000-8000-000000000099')
        self.assertEqual(first, again)
        self.assertNotEqual(first, other)
        self.assertEqual(len(calls), 3)
        self.assertNotIn('synthetic-private-credential', json.dumps([first, again, other]))
        with patch('hydra_sdlc.github.subprocess.run', side_effect=OSError('synthetic-private-error')):
            self.assertEqual(read_connection_context(EPOCH), {'scope': None})

    def test_changed_credential_is_rejected_before_any_http_and_local_admission_survives(self):
        from test_control_projection import EPOCH
        from hydra_sdlc.github import GitHubError, read_credential_scope
        import hashlib
        expected = read_credential_scope(EPOCH, hashlib.sha256(b'synthetic-old-credential').digest())
        fixture = ReadFixture()
        fixture.client = ProjectionClient()
        calls = []
        def process(argv, **kwargs):
            calls.append(argv)
            self.assertEqual(argv[1:3], ['auth', 'token'], 'A changed credential reached HTTP')
            return subprocess.CompletedProcess(argv, 0, 'synthetic-new-credential\n', '')
        with patch('hydra_sdlc.github.subprocess.run', side_effect=process):
            with self.assertRaises(GitHubError):
                fixture.read(credential_scope=expected)
        self.assertEqual(len(calls), 1)
        with patch('hydra_sdlc.github.subprocess.run', side_effect=AssertionError('Local read touched credentials')):
            frame = ReadFixture().read(refresh=False)
        self.assertEqual(frame['projects'][0]['admission']['value'], 'paused')
        self.assertIsNone(frame['projects'][0]['execution']['value'])

    def test_mid_read_rotation_does_not_mix_credentials_or_make_the_next_http_request(self):
        from hydra_sdlc.github import GitHubError
        fixture = ReadFixture()
        fixture.client = ProjectionClient()
        tokens = iter(('synthetic-first-credential', 'synthetic-second-credential'))
        http = []
        def process(argv, **kwargs):
            if argv[1:3] == ['auth', 'token']:
                return subprocess.CompletedProcess(argv, 0, next(tokens) + '\n', '')
            http.append(argv)
            if argv[-1] == 'user':
                return subprocess.CompletedProcess(argv, 0, json.dumps({'login': 'openboa'}), '')
            return subprocess.CompletedProcess(argv, 0, 'HTTP/2.0 200 OK\r\n\r\n' +
                json.dumps({'id': 101, 'full_name': 'example/alpha', 'default_branch': 'main'}), '')
        with patch('hydra_sdlc.github.subprocess.run', side_effect=process):
            with self.assertRaises(GitHubError):
                fixture.read()
        self.assertEqual(len(http), 2, 'A rotated credential reached the next HTTP request')
        self.assertTrue(fixture.client.context_changed)

    def test_reused_reader_does_not_carry_previous_response_hints_into_another_observation(self):
        from hydra_sdlc.github import GitHubError
        fixture = ReadFixture(fail=lambda _: GitHubError('limited', status=429))
        first = fixture.read()
        self.assertTrue(first['retry_hints'])
        fixture.fail = None
        second = fixture.read()
        self.assertEqual(second['retry_hints'], [], 'A reused reader reattached a prior rate-limit hint')
        self.assertTrue(all(row['coverage']['state'] == 'complete' for row in second['projects']))
