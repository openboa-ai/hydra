import base64
import copy
import hashlib
import json
import unittest

from hydra_sdlc.github import GitHub, GitHubError
from hydra_sdlc.work_records import Binding, WorkRecordError
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
        flattened = []
        prefix = []
        for tree, path, sha, mode, kind in [(TREES[0], 'docs', TREES[1], '040000', 'tree'),
                                           (TREES[1], 'design', TREES[2], '040000', 'tree'),
                                           (TREES[2], 'spec.md', blob, '100644', 'blob')]:
            values[ROOT + '/git/trees/' + tree] = {'sha': tree, 'truncated': False,
                'tree': [{'path': path, 'sha': sha, 'mode': mode, 'type': kind}]}
            prefix.append(path)
            flattened.append({'path': '/'.join(prefix), 'sha': sha, 'mode': mode, 'type': kind})
        values[ROOT + '/git/trees/' + TREES[2]]['tree'][0]['size'] = len(data)
        flattened[-1]['size'] = len(data)
        values[ROOT + '/git/trees/' + TREES[0] + '?recursive=1'] = {
            'sha': TREES[0], 'truncated': False, 'tree': flattened}
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
        return client.work_input_source(repo, reference() if selected is None else selected, spec_directory='docs')

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
        self.assertEqual(len(calls), 4)
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
        self.assertEqual(len(calls), 8)
        two, other_calls, _, _ = self.client()
        self.assertEqual(first.digest, self.read(two).digest)
        self.assertEqual(first.document, second.document)
        self.assertEqual(len(other_calls), 4)

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
            values[ROOT + '/git/trees/' + TREES[0] + '?recursive=1']['tree'][index].update(mode=mode, type=kind)
            with self.subTest(index=index, mode=mode):
                self.reason('invalid_reference_path', client)
            self.assertFalse(any('/git/blobs/' in path for _, path, _ in calls))

    def test_executable_regular_file_is_a_valid_non_executing_source(self):
        client, _, values, _ = self.client()
        values[ROOT + '/git/trees/' + TREES[0] + '?recursive=1']['tree'][2]['mode'] = '100755'
        self.assertEqual(self.read(client).digest, PAYLOAD_DIGEST)

    def test_non_string_file_mode_is_a_structured_invalid_source(self):
        client, _, values, _ = self.client()
        values[ROOT + '/git/trees/' + TREES[0] + '?recursive=1']['tree'][2]['mode'] = []
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
            tree = values[ROOT + '/git/trees/' + TREES[0] + '?recursive=1']
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
        values[ROOT + '/git/trees/' + TREES[0] + '?recursive=1']['tree'][2]['size'] = 65_537
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
        values[ROOT + '/git/trees/' + TREES[0] + '?recursive=1']['tree'][2].update(sha=new_blob, size=len(content))
        values[ROOT + '/git/blobs/' + new_blob] = {'sha': new_blob, 'size': len(content), 'encoding': 'base64',
                                                'content': base64.b64encode(content).decode()}
        self.assertEqual(self.read(client).value, {'clauses': []})

    def test_reader_rejects_an_oversized_valid_source_before_blob_fetch(self):
        content = document()
        content += ' ' * (65_537 - len(content.encode()))
        client, calls, _, _ = self.client(content)
        self.reason('reference_limit', client)
        self.assertFalse(any('/git/blobs/' in path for _, path, _ in calls))

    def test_a_schema_valid_deep_path_resolves_within_the_default_read_budget(self):
        client, calls, values, blob = self.client()
        parts = ['d' + str(n) for n in range(29)] + ['spec.md']
        trees = [TREES[0]] + [hashlib.sha1(('deep-tree-' + str(n)).encode()).hexdigest() for n in range(29)]
        flattened = []
        for index, part in enumerate(parts):
            leaf = index == len(parts) - 1
            entry = {'path': part, 'mode': '100644' if leaf else '040000',
                     'type': 'blob' if leaf else 'tree', 'sha': blob if leaf else trees[index + 1]}
            if leaf:
                entry['size'] = len(document().encode())
            values[ROOT + '/git/trees/' + trees[index]] = {
                'sha': trees[index], 'truncated': False, 'tree': [entry]}
            flattened.append({**entry, 'path': '/'.join(parts[:index + 1])})
        values[ROOT + '/git/trees/' + TREES[0] + '?recursive=1'] = {
            'sha': TREES[0], 'truncated': False, 'tree': flattened}
        contract = reference().value['input_contract']
        contract['ref']['path'] = '/'.join(parts)
        try:
            result = self.read(client, parsed(contract))
        except WorkRecordError as exc:
            self.fail('A valid complete deep-path source exhausted its own budget: ' + exc.reason)
        self.assertEqual(result.digest, PAYLOAD_DIGEST)
        self.assertEqual(len(calls), 4)

    def test_forged_binding_is_rejected_before_any_provider_read(self):
        client, calls, _, _ = self.client()
        value = reference().value
        value['source_digest'] = 'forged'
        self.reason('invalid_schema', client, selected=Binding(json.dumps(value)))
        self.assertEqual(calls, [])

    def test_malformed_repository_name_returns_a_static_unknown_error(self):
        for name in [None, 7, [], {}]:
            client, _, values, _ = self.client()
            values[ROOT]['full_name'] = name
            try:
                self.read(client)
            except WorkRecordError as exc:
                self.assertEqual(exc.reason, 'unknown')
                self.assertEqual(str(exc), 'unknown')
            except Exception as exc:
                self.fail('Repository metadata escaped the source boundary: ' + type(exc).__name__)
            else:
                self.fail('Malformed repository metadata was accepted')


if __name__ == '__main__':
    unittest.main()
