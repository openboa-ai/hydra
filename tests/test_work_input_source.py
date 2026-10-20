import base64
import copy
import hashlib
import unittest

from hydra_sdlc.github import GitHub, GitHubError
from hydra_sdlc.work_records import WorkRecordError
from test_work_inputs import PAYLOAD, PAYLOAD_DIGEST, document, parsed, reference


REPO = 'example/alpha'
ROOT = '/repos/' + REPO
REVISION = '1' * 40
TREES = ['2' * 40, '3' * 40, '4' * 40]


class WorkInputSourceTests(unittest.TestCase):
    def client(self, content=None):
        data = (document() if content is None else content).encode()
        blob = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()
        values = {ROOT: {'id': 101, 'full_name': REPO, 'default_branch': 'main'},
                  ROOT + '/git/commits/' + REVISION: {'sha': REVISION, 'tree': {'sha': TREES[0]}},
                  ROOT + '/git/blobs/' + blob: {'sha': blob, 'size': len(data), 'encoding': 'base64',
                                              'content': base64.b64encode(data).decode()}}
        for tree, path, sha, mode, kind in [(TREES[0], 'docs', TREES[1], '040000', 'tree'),
                                           (TREES[1], 'design', TREES[2], '040000', 'tree'),
                                           (TREES[2], 'spec.md', blob, '100644', 'blob')]:
            values[ROOT + '/git/trees/' + tree] = {'sha': tree, 'truncated': False,
                'tree': [{'path': path, 'sha': sha, 'mode': mode, 'type': kind}]}
        values[ROOT + '/git/trees/' + TREES[2]]['tree'][0]['size'] = len(data)
        calls = []
        def transport(method, path, payload):
            calls.append((method, path, payload))
            self.assertEqual(method, 'GET', 'Input reference resolution must never mutate provider state')
            self.assertIsNone(payload)
            value = values[path]
            if isinstance(value, Exception):
                raise value
            return copy.deepcopy(value)
        return GitHub(transport=transport), calls, values, blob

    def read(self, client, selected=None, repo=REPO):
        self.assertTrue(callable(getattr(client, 'work_input_source', None)),
                        'P09 exact Git reference read adapter is not implemented')
        return client.work_input_source(repo, reference() if selected is None else selected)

    def reason(self, reason, client, **kwargs):
        with self.assertRaises(WorkRecordError) as caught:
            self.read(client, **kwargs)
        self.assertEqual(caught.exception.reason, reason)
        self.assertEqual(str(caught.exception), reason)

    def test_exact_commit_tree_and_blob_read_returns_only_canonical_conditions(self):
        client, calls, _, blob = self.client()
        result = self.read(client)
        self.assertEqual(result.value, PAYLOAD)
        self.assertEqual(result.digest, PAYLOAD_DIGEST)
        self.assertEqual(len(calls), 6)
        self.assertEqual(calls[-1][1], ROOT + '/git/blobs/' + blob)
        self.assertTrue(any('/git/commits/' + REVISION in path for _, path, _ in calls))
        self.assertFalse(any('/contents/' in path for _, path, _ in calls))

    def test_adopted_contract_requires_no_external_source_read(self):
        client, calls, _, _ = self.client()
        self.assertEqual(self.read(client, parsed({'kind': 'adopted', **PAYLOAD})).digest, PAYLOAD_DIGEST)
        self.assertEqual(calls, [])

    def test_fresh_client_reconstructs_same_conditions_and_does_not_reuse_cache(self):
        one, calls, _, _ = self.client()
        first = self.read(one)
        second = self.read(one)
        self.assertEqual(len(calls), 12)
        two, other_calls, _, _ = self.client()
        self.assertEqual(first.digest, self.read(two).digest)
        self.assertEqual(first.document, second.document)
        self.assertEqual(len(other_calls), 6)

    def test_repository_display_case_uses_canonical_name_and_numeric_identity(self):
        client, calls, values, _ = self.client()
        values['/repos/' + REPO.upper()] = values[ROOT]
        self.assertEqual(self.read(client, repo=REPO.upper()).digest, PAYLOAD_DIGEST)
        self.assertEqual(calls[0][1], '/repos/' + REPO.upper())
        self.assertTrue(all(path.startswith(ROOT) for _, path, _ in calls[1:]))
        client, calls, values, _ = self.client()
        values[ROOT]['id'] = 102
        self.reason('identity_mismatch', client)
        self.assertEqual(len(calls), 1)

    def test_wrong_or_missing_commit_tree_identity_never_becomes_latest_ref(self):
        for value in [{'sha': '9' * 40, 'tree': {'sha': TREES[0]}},
                      {'sha': REVISION}, {'sha': REVISION, 'tree': {'sha': 'main'}}]:
            client, calls, values, _ = self.client()
            values[ROOT + '/git/commits/' + REVISION] = value
            with self.subTest(value=value):
                self.reason('unknown', client)
            self.assertEqual(len(calls), 2)

    def test_symlink_submodule_directory_and_unrecognized_modes_are_never_followed(self):
        for index, mode, kind in [(0, '120000', 'blob'), (1, '160000', 'commit'),
                                  (2, '120000', 'blob'), (2, '160000', 'commit'),
                                  (2, '040000', 'tree'), (2, '000000', 'blob')]:
            client, calls, values, _ = self.client()
            values[ROOT + '/git/trees/' + TREES[index]]['tree'][0].update(mode=mode, type=kind)
            with self.subTest(index=index, mode=mode):
                self.reason('invalid_reference_path', client)
            self.assertFalse(any('/git/blobs/' in path for _, path, _ in calls))

    def test_executable_regular_file_is_a_valid_non_executing_source(self):
        client, _, values, _ = self.client()
        values[ROOT + '/git/trees/' + TREES[2]]['tree'][0]['mode'] = '100755'
        self.assertEqual(self.read(client).digest, PAYLOAD_DIGEST)

    def test_non_string_file_mode_is_a_structured_invalid_source(self):
        client, _, values, _ = self.client()
        values[ROOT + '/git/trees/' + TREES[2]]['tree'][0]['mode'] = []
        try:
            self.read(client)
        except WorkRecordError as exc:
            self.assertEqual(exc.reason, 'invalid_reference_path')
        except Exception as exc:
            self.fail('Malformed file mode escaped the source error boundary: ' + type(exc).__name__)
        else:
            self.fail('Malformed file mode was accepted')

    def test_partial_duplicate_missing_or_wrong_tree_is_not_a_complete_path_proof(self):
        for kind in ['truncated', 'missing_coverage', 'duplicate', 'missing', 'wrong_sha']:
            client, _, values, _ = self.client()
            tree = values[ROOT + '/git/trees/' + TREES[0]]
            expected = 'unknown'
            if kind == 'truncated': tree['truncated'] = True
            if kind == 'missing_coverage': del tree['truncated']
            if kind == 'duplicate':
                tree['tree'].append(copy.deepcopy(tree['tree'][0]))
                expected = 'conflict'
            if kind == 'missing':
                tree['tree'] = []
                expected = 'accepted_meaning_unavailable'
            if kind == 'wrong_sha': tree['sha'] = '9' * 40
            with self.subTest(kind=kind):
                self.reason(expected, client)

    def test_blob_size_sha_base64_utf8_and_content_identity_are_checked(self):
        for changes in [{'sha': '9' * 40}, {'size': True}, {'size': 1}, {'encoding': 'utf-8'},
                        {'content': 'not-base64'}, {'content': base64.b64encode(b'\xff').decode(), 'size': 1},
                        {'content': base64.b64encode(b'changed').decode(), 'size': 7}]:
            client, _, values, blob = self.client()
            values[ROOT + '/git/blobs/' + blob].update(changes)
            with self.subTest(changes=changes):
                self.reason('invalid_reference', client)

    def test_declared_large_blob_stops_before_read_and_budget_stops_before_traversal(self):
        client, calls, values, _ = self.client()
        values[ROOT + '/git/trees/' + TREES[2]]['tree'][0]['size'] = 1_048_577
        self.reason('reference_limit', client)
        self.assertFalse(any('/git/blobs/' in path for _, path, _ in calls))
        client, calls, _, _ = self.client()
        with client.read_budget(seconds=30, requests=2):
            self.reason('unknown', client)
        self.assertEqual(len(calls), 2)

    def test_transport_failure_has_no_raw_source_in_public_error(self):
        client, _, values, _ = self.client()
        values[ROOT] = GitHubError('private-source-canary')
        self.reason('unknown', client)

    def test_public_fixture_contains_one_structured_source_section(self):
        from pathlib import Path
        client, _, values, blob = self.client()
        content = (Path(__file__).parent / 'fixtures/work-inputs.md').read_bytes()
        new_blob = hashlib.sha1(b'blob ' + str(len(content)).encode() + b'\0' + content).hexdigest()
        values[ROOT + '/git/trees/' + TREES[2]]['tree'][0].update(sha=new_blob, size=len(content))
        values[ROOT + '/git/blobs/' + new_blob] = {'sha': new_blob, 'size': len(content), 'encoding': 'base64',
                                                'content': base64.b64encode(content).decode()}
        self.assertEqual(self.read(client).value, {'clauses': []})


if __name__ == '__main__':
    unittest.main()
