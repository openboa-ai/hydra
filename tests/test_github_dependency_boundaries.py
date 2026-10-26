"""Transport wiring and exact resource-boundary oracles for P11."""
import json
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hydra_sdlc.github import GitHub, GitHubError
from hydra_sdlc.work_relations import dependency_topology
from test_github_dependencies import ROOT, REGISTRY, Wire


def empty_page():
    return {'data': {'repository': {'databaseId': 101, 'nameWithOwner': 'example/product',
        'isPrivate': False, 'viewerPermission': 'READ', 'issue': {'id': 'I_101_1',
        'number': 1, 'issueDependenciesSummary': {'totalBlockedBy': 0},
        'blockedBy': {'totalCount': 0, 'nodes': [],
                      'pageInfo': {'hasNextPage': False, 'endCursor': None}}}}}}


class NativeDependencyBoundaryTests(unittest.TestCase):
    def test_builtin_transport_selects_credentials_and_authenticates_once(self):
        calls = []
        def process(argv, **kwargs):
            calls.append(argv)
            if argv[1:3] == ['auth', 'token']:
                self.assertEqual(argv[-2:], ['--user', 'openboa'])
                text = 'synthetic-test-credential'
            elif argv[-1] == 'user':
                text = 'HTTP/2 200\r\n\r\n' + json.dumps({'login': 'openboa', 'id': 123})
            else:
                self.assertIn('graphql', argv)
                self.assertTrue(json.loads(kwargs['input'])['query'].startswith('query '))
                text = json.dumps(empty_page())
            return SimpleNamespace(returncode=0, stdout=text, stderr='')
        client = GitHub()
        with patch('hydra_sdlc.github.subprocess.run', process):
            result = client.native_dependency_read({'repository_id': 101, 'issue_number': 1},
                                                   repositories=REGISTRY)
        self.assertEqual(result.status, 'matched')
        self.assertEqual(sum(a[1:3] == ['auth', 'token'] for a in calls), 2)
        self.assertEqual(sum(a[-1] == 'user' for a in calls), 1)
        self.assertEqual(sum('graphql' in a for a in calls), 2)
        self.assertNotIn('_credential_selected', client.__dict__)

    def test_builtin_authentication_consumes_outer_http_reservation(self):
        calls = []
        def process(argv, **kwargs):
            calls.append(argv)
            text = ('synthetic-test-credential' if argv[1:3] == ['auth', 'token'] else
                    'HTTP/2 200\r\n\r\n{"login":"openboa","id":123}' if argv[-1] == 'user'
                    else json.dumps(empty_page()))
            return SimpleNamespace(returncode=0, stdout=text, stderr='')
        client = GitHub()
        with patch('hydra_sdlc.github.subprocess.run', process):
            with client.read_budget(seconds=45, requests=2):
                result = client.native_dependency_read({'repository_id': 101, 'issue_number': 1},
                                                       repositories=REGISTRY)
        self.assertEqual(result.status, 'unknown')
        self.assertEqual(sum('graphql' in a for a in calls), 1)
        self.assertEqual(sum(a[-1] == 'user' for a in calls), 1)
        self.assertEqual(client._read_budgets, [])

    def test_builtin_changed_credential_cannot_authenticate_a_second_graph(self):
        selections, api_calls = [], []
        def process(argv, **kwargs):
            if argv[1:3] == ['auth', 'token']:
                selections.append(len(selections))
                text = 'synthetic-A' if len(selections) == 1 else 'synthetic-B'
            else:
                api_calls.append(argv)
                text = ('HTTP/2 200\r\n\r\n{"login":"openboa","id":123}'
                        if argv[-1] == 'user' else json.dumps(empty_page()))
            return SimpleNamespace(returncode=0, stdout=text, stderr='')
        client = GitHub()
        with patch('hydra_sdlc.github.subprocess.run', process):
            result = client.native_dependency_read({'repository_id': 101, 'issue_number': 1},
                                                   repositories=REGISTRY)
        self.assertEqual(result.status, 'unknown')
        self.assertEqual(result.first.edges, ())
        self.assertEqual(result.first.coverage, 'unavailable')
        self.assertEqual(len(selections), 2)
        self.assertEqual(sum('graphql' in a for a in api_calls), 1)

    def test_deadline_after_successful_comparison_invalidates_the_result(self):
        for expire in (False, True):
            with self.subTest(expire=expire):
                clock = [10.0]
                def compare(*args, **kwargs):
                    result = dependency_topology(*args, **kwargs)
                    if expire:
                        clock[0] = 100.0
                    return result
                with patch('hydra_sdlc.github.time.monotonic', lambda: clock[0]), \
                     patch('hydra_sdlc.github_dependencies.dependency_topology', compare):
                    result = Wire({}).read()
                self.assertEqual(result.status, 'unknown' if expire else 'matched')

    def test_exact_depth_32_succeeds_and_depth_33_does_not_query_beyond_limit(self):
        for depth in (32, 33):
            with self.subTest(depth=depth):
                wire = Wire({(101, n): [(101, n + 1)] for n in range(1, depth + 1)})
                result = wire.read()
                self.assertEqual(result.status, 'matched' if depth == 32 else 'unknown')
                if depth == 33:
                    self.assertEqual(result.reason, 'graph_depth_limit')
                    self.assertFalse(any(key == (101, 34) for _, key, _ in wire.calls))

    def test_exact_edge_1024_succeeds_and_edge_1025_is_incomplete(self):
        mids = [(101, n) for n in range(2, 33)]
        leaves = [(101, n) for n in range(33, 64)]
        for overflow in (False, True):
            with self.subTest(overflow=overflow):
                graph = {ROOT: mids + leaves, **{mid: list(leaves) for mid in mids}}
                graph[mids[0]].append(mids[1])
                if overflow:
                    graph[mids[0]].append(mids[2])
                self.assertEqual(sum(map(len, graph.values())), 1025 if overflow else 1024)
                wire = Wire(graph)
                result = wire.read()
                self.assertEqual(result.status, 'unknown' if overflow else 'matched')
                if overflow:
                    self.assertEqual(result.reason, 'graph_edge_limit')
                else:
                    self.assertEqual(len(result.second.edges), 1024)
                    self.assertEqual(len(wire.calls), 126)

    def test_256_node_prefix_hits_request_cap_without_inventing_node_overflow(self):
        wire = Wire({ROOT: [(101, n) for n in range(2, 257)]})
        result = wire.read()
        self.assertEqual(result.status, 'unknown')
        self.assertEqual(len(wire.calls), 128)
        self.assertEqual(len(result.first.nodes), 256)
        self.assertNotEqual(result.first.reason, 'graph_node_limit')
        self.assertNotEqual(result.second.reason, 'graph_node_limit')

    def test_second_pass_only_source_identity_drift_invalidates_both_graphs(self):
        for field, value in (('nameWithOwner', 'example/changed'), ('isPrivate', True),
                             ('viewerPermission', 'WRITE'), ('id', 'I_DIFFERENT')):
            with self.subTest(field=field):
                def change(wire, key, after, result):
                    if wire.pass_index == 1:
                        repo = result['data']['repository']
                        (repo['issue'] if field == 'id' else repo)[field] = value
                result = Wire({}, callback=change).read()
                self.assertEqual(result.status, 'unknown')
                self.assertEqual((result.first.coverage, result.second.coverage),
                                 ('unavailable', 'unavailable'))
                self.assertEqual((result.first.nodes, result.second.nodes), ((), ()))

    def test_reverse_node_id_collision_across_sources_invalidates(self):
        def collide(wire, key, after, result):
            if key == (101, 3):
                result['data']['repository']['issue']['id'] = 'I_101_2'
        result = Wire({ROOT: [(101, 2), (101, 3)]}, callback=collide).read()
        self.assertEqual(result.status, 'unknown')
        self.assertEqual(result.first.nodes, ())

    def test_hook_cleanup_on_provider_error_and_credential_change(self):
        for local_hook in (False, True):
            for credential_change in (False, True):
                with self.subTest(local_hook=local_hook, change=credential_change):
                    def fail(wire, key, after, result):
                        if credential_change:
                            wire.client._credential_selected(b'b' * 32)
                        raise GitHubError('PRIVATE_DEPENDENCY_CANARY')
                    wire = Wire({}, callback=fail)
                    hook = lambda _: None
                    if local_hook:
                        wire.client._credential_selected = hook
                    self.assertEqual(wire.read().status, 'unknown')
                    self.assertEqual(wire.client._read_budgets, [])
                    if local_hook:
                        self.assertIs(wire.client._credential_selected, hook)
                    else:
                        self.assertNotIn('_credential_selected', wire.client.__dict__)

    def test_valid_looking_page_without_authenticated_fingerprint_is_unknown(self):
        def unqualified(wire, key, after, result):
            wire.client._authenticated_fingerprint = None
        result = Wire({}, callback=unqualified).read()
        self.assertEqual(result.status, 'unknown')
        self.assertEqual(result.first.coverage, 'unavailable')

    def test_unbounded_registration_is_rejected_without_network(self):
        wire = Wire({})
        with self.assertRaises(GitHubError):
            wire.read({n: f'example/r{n}' for n in range(1, 258)})
        self.assertEqual(wire.calls, [])
