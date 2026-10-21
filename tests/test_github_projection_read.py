"""Owned GitHub GET metadata and preserved ordinary transport behavior."""
from datetime import datetime, timezone
import json
import subprocess
import unittest
from unittest.mock import patch

from hydra_sdlc.github import GitHub, GitHubError
from hydra_sdlc.github_read import parse_response


DATE = 'Tue, 20 Oct 2026 00:00:00 GMT'
CANARY = 'SYNTHETIC_RAW_ERROR_CANARY'


def http(status=200, headers=(), value=None):
    return ('HTTP/2.0 ' + str(status) + ' Result\r\n' +
            '\r\n'.join(k + ': ' + v for k, v in headers) + '\r\n\r\n' +
            (json.dumps(value) if value is not None else ''))


class GitHubProjectionReadTests(unittest.TestCase):
    def test_raw_projection_input_obeys_the_one_mib_utf8_boundary_before_decoding(self):
        limit = 1_048_576
        prefix, suffix = 'HTTP/2.0 200 Result\r\n\r\n{"body":"', '"}'
        for unit in ('x', '🚀'):
            with self.subTest(unit=unit):
                budget = limit - len((prefix + suffix).encode('utf-8'))
                count, remainder = divmod(budget, len(unit.encode('utf-8')))
                raw = prefix + unit * count + 'x' * remainder + suffix
                self.assertEqual(len(raw.encode('utf-8')), limit)
                self.assertIsInstance(parse_response(raw).value, dict)
                oversized = raw[:-len(suffix)] + 'x' + suffix
                with patch('hydra_sdlc.github_read.json.loads', wraps=json.loads) as decode:
                    with self.assertRaises(ValueError):
                        parse_response(oversized)
                    decode.assert_not_called()

    def test_registered_double_dot_names_are_not_confused_with_path_traversal(self):
        calls = []
        client = GitHub(transport=lambda method, path, payload: calls.append((method,path,payload)) or {'id':101})
        self.assertEqual(client.read_response('/repos/example/a..b').value, {'id':101})
        self.assertEqual(calls, [('GET','/repos/example/a..b',None)])
        for path in ('/repos/example/../private','/repos/example/%2e%2e/private',
                     '/repos/example/%2f..%2fprivate','/repos/example/./private',
                     '/repos/example/a\\..\\private','/repos/example/a\x00b'):
            with self.subTest(path=path), self.assertRaises(GitHubError):
                client.read_response(path)
        self.assertEqual(len(calls), 1)

    def test_success_status_does_not_erase_an_actual_provider_wait(self):
        response = parse_response(http(200, [('Retry-After', '37')], {'id': 101}), now=100)
        self.assertTrue(response.limited, 'A successful payload erased an actual provider wait')
        self.assertEqual(response.remaining_wait(105.2), 32)

    def test_malformed_wait_on_success_is_unknown_and_never_immediate_permission(self):
        response = parse_response(http(200, [('Retry-After', 'invalid')], {'id': 101}), now=100)
        self.assertTrue(response.limited)
        self.assertIsNone(response.retry_after)

    def test_explicit_provider_zero_is_not_missing_metadata(self):
        zero = parse_response(http(429, [('Retry-After', '0')], {'message': 'limited'}), now=100)
        self.assertTrue(zero.limited)
        self.assertEqual(zero.retry_after, 0)
        self.assertEqual(zero.remaining_wait(100), 0)
        missing = parse_response(http(429, [], {'message': 'limited'}), now=100)
        self.assertTrue(missing.limited)
        self.assertIsNone(missing.remaining_wait(100))
        normal = parse_response(http(200, [], {'id': 101}), now=100)
        self.assertFalse(normal.limited)
        self.assertIsNone(normal.retry_after)

    def test_longest_actual_provider_delay_survives_elapsed_time_and_backward_clock(self):
        reset = int(datetime(2026, 10, 20, tzinfo=timezone.utc).timestamp()) + 1200
        response = parse_response(http(200, [('Date', DATE), ('Retry-After', '300'),
            ('Retry-After', '60'), ('X-RateLimit-Remaining', '0'),
            ('X-RateLimit-Reset', str(reset))], {'id': 101}), now=100)
        self.assertTrue(response.limited)
        self.assertEqual(response.retry_after, 1200)
        self.assertEqual(response.remaining_wait(105.6), 1195)
        self.assertEqual(response.remaining_wait(50), 1200)

    def test_absolute_retry_uses_server_date_instead_of_local_wall_clock(self):
        response = parse_response(http(403, [('Date', DATE),
            ('Retry-After', 'Tue, 20 Oct 2026 00:10:00 GMT')], {'message': 'limited'}), now=100)
        self.assertEqual(response.retry_after, 600)
        unqualified = parse_response(http(403, [
            ('Retry-After', 'Tue, 20 Oct 2026 00:10:00 GMT')], {'message': 'limited'}), now=100)
        self.assertIsNone(unqualified.retry_after)

    def test_secondary_limit_and_access_denial_are_distinct(self):
        denied = parse_response(http(403, [], {'message': CANARY}), now=100)
        self.assertFalse(denied.limited)
        limited = parse_response(http(403, [], {'message': 'You have exceeded a secondary rate limit.'}), now=100)
        self.assertTrue(limited.limited)
        self.assertIsNone(limited.retry_after)

    def test_not_modified_has_no_invented_source_value(self):
        response = parse_response(http(304, [('Date', DATE)]), now=100)
        self.assertEqual(response.status, 304)
        self.assertIsNone(response.value)
        self.assertIsNone(response.retry_after)

    def test_metadata_is_bounded_and_malformed_headers_are_not_provider_zero(self):
        for raw in ('HTTP/2.0 200 Result\nmalformed\n\n{}',
                    'HTTP/2.0 200 Result\nX-Test: ' + 'x' * 16384 + '\n\n{}'):
            with self.subTest(size=len(raw)), self.assertRaises(ValueError):
                parse_response(raw)
        response = parse_response(http(429, [('Retry-After', '-1'),
            ('Retry-After', 'NaN'), ('X-RateLimit-Reset', 'invalid')], {'message': 'limited'}), now=100)
        self.assertTrue(response.limited)
        self.assertIsNone(response.retry_after)

    def client(self, raw, returncode=0):
        calls = []
        def run(argv, **kwargs):
            calls.append((argv, kwargs))
            if argv[:3] == ['gh', 'auth', 'token']:
                return subprocess.CompletedProcess(argv, 0, 'synthetic-fixture-credential\n', '')
            if argv[-1] == 'user':
                return subprocess.CompletedProcess(argv, 0, '{"login":"openboa"}', '')
            return subprocess.CompletedProcess(argv, returncode, raw, 'HTTP 403' if returncode else '')
        return calls, run

    def test_builtin_get_reads_actual_headers_and_existing_api_stays_json_only(self):
        client = GitHub()
        calls, run = self.client(http(200, [('Retry-After', '0')], {'id': 101}))
        with patch('hydra_sdlc.github.subprocess.run', side_effect=run):
            response = client.read_response('/repos/example/alpha')
        self.assertEqual(response.value, {'id': 101})
        self.assertEqual(response.retry_after, 0)
        self.assertIn('--include', calls[-1][0])
        self.assertIn('GET', calls[-1][0])
        calls, run = self.client('{"id":101}')
        with patch('hydra_sdlc.github.subprocess.run', side_effect=run):
            self.assertEqual(client.api('GET', '/repos/example/alpha'), {'id': 101})
        self.assertNotIn('--include', calls[-1][0])
        self.assertEqual(calls[-1][1]['env']['GH_TOKEN'], 'synthetic-fixture-credential')

    def test_failed_get_retains_sanitized_wait_without_error_body_or_headers(self):
        client = GitHub()
        calls, run = self.client(http(403, [('Retry-After', '37')], {'message': CANARY}), 1)
        with patch('hydra_sdlc.github.subprocess.run', side_effect=run), self.assertRaises(GitHubError) as raised:
            client.read_response('/repos/example/alpha')
        failure = raised.exception
        self.assertFalse(failure.uncertain)
        self.assertEqual(failure.status, 403)
        self.assertTrue(failure.read_response.limited)
        self.assertEqual(failure.read_response.retry_after, 37)
        self.assertIsNone(failure.read_response.value)
        self.assertNotIn(CANARY, str(failure))
        self.assertEqual(len([c for c in calls if '--include' in c[0]]), 1)

    def test_injected_json_reader_retains_unknown_headers_and_no_automatic_retry(self):
        calls = []
        def transport(method, path, payload):
            calls.append((method, path, payload))
            return {'id': 101}
        response = GitHub(transport=transport).read_response('/repos/example/alpha')
        self.assertEqual(response.value, {'id': 101})
        self.assertIsNone(response.retry_after)
        self.assertEqual(calls, [('GET', '/repos/example/alpha', None)])
