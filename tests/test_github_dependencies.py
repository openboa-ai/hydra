"""Independent transport oracles for bounded dependency collections."""
import copy
import unittest
from unittest.mock import patch

from hydra_sdlc.github import GitHub, GitHubError

ROOT = (101, 1)
REGISTRY = {101: 'example/product', 102: 'example/other'}
CANARY = 'PRIVATE_DEPENDENCY_CANARY'


class Wire:
    def __init__(self, first, second=None, *, root=ROOT, callback=None):
        self.graphs = [first, first if second is None else second]
        self.root, self.callback = root, callback
        self.calls, self.pass_index = [], -1
        self.client = GitHub(transport=self.request)
        self.fingerprint = b'a' * 32

    def repository(self, identifier):
        return {'databaseId': identifier, 'nameWithOwner': REGISTRY.get(identifier, 'foreign/repo'),
                'isPrivate': False, 'viewerPermission': 'READ'}

    def node(self, key):
        return {'id': f'I_{key[0]}_{key[1]}', 'number': key[1],
                'repository': self.repository(key[0]), 'body': CANARY}

    def request(self, method, path, payload):
        assert (method, path) == ('POST', '/graphql'), 'Unexpected effect'
        assert payload['query'].startswith('query HydraNativeRelations(')
        assert 'blockedBy' in payload['query'] and 'mutation' not in payload['query']
        variables = payload['variables']
        name = variables['owner'] + '/' + variables['name']
        identifier = {v: k for k, v in REGISTRY.items()}[name]
        key = identifier, variables['number']
        after = variables['after']
        if key == self.root and after is None:
            self.pass_index += 1
        assert self.pass_index in (0, 1), 'Unexpected third collection'
        self.calls.append((self.pass_index, key, after))
        self.client._credential_selected(self.fingerprint)
        self.client._authenticated_fingerprint = self.fingerprint
        targets = self.graphs[self.pass_index].get(key, ())
        offset = 0 if after is None else int(after.removeprefix('offset:'))
        selected = targets[offset:offset + variables['first']]
        end = offset + len(selected)
        more = end < len(targets)
        issue = {'id': f'I_{key[0]}_{key[1]}', 'number': key[1],
                 'issueDependenciesSummary': {'totalBlockedBy': len(targets)},
                 'blockedBy': {'totalCount': len(targets), 'nodes': [self.node(k) for k in selected],
                               'pageInfo': {'hasNextPage': more,
                                            'endCursor': f'offset:{end}' if more else None}}}
        result = {'data': {'repository': {**self.repository(identifier), 'issue': issue}},
                  'ignored': CANARY}
        if self.callback:
            replacement = self.callback(self, key, after, result)
            if replacement is not None:
                result = replacement
        return result

    def read(self, registry=None):
        return self.client.native_dependency_read(
            {'repository_id': self.root[0], 'issue_number': self.root[1]},
            repositories=copy.deepcopy(REGISTRY) if registry is None else registry)


class NativeDependencyReadTests(unittest.TestCase):
    def test_chain_collects_every_reachable_source_twice(self):
        graph = {ROOT: [(101, 2)], (101, 2): [(102, 3)]}
        wire = Wire(graph)
        result = wire.read()
        self.assertEqual((result.status, result.reason), ('matched', 'topology_only'))
        expected = ((ROOT, (101, 2)), ((101, 2), (102, 3)))
        self.assertEqual(result.first.edges, expected)
        self.assertEqual(result.second.edges, expected)
        self.assertEqual(wire.calls, [(p, key, None) for p in (0, 1)
                                      for key in (ROOT, (101, 2), (102, 3))])
        self.assertNotIn(CANARY, repr(result))

    def test_empty_root_and_unreachable_failure_are_positive(self):
        def reject_unreachable(wire, key, after, result):
            self.assertEqual(key, ROOT)
        wire = Wire({(102, 999): [(999, 1)]}, callback=reject_unreachable)
        result = wire.read()
        self.assertEqual(result.status, 'matched')
        self.assertEqual(result.first.coverage, 'complete')
        self.assertEqual(result.first.edges, ())
        self.assertEqual(len(wire.calls), 2)

    def test_second_collection_follows_its_own_added_and_removed_edges(self):
        for before, after in (({}, {ROOT: [(101, 3)]}), ({ROOT: [(101, 2)]}, {})):
            with self.subTest(before=before):
                wire = Wire(before, after)
                result = wire.read()
                self.assertEqual(result.status, 'changed')
                self.assertNotEqual(result.first.edges, result.second.edges)
                self.assertEqual(result.second.edges, ((ROOT, (101, 3)),) if after else ())

    def test_cursor_pages_are_separately_collected_for_each_pass(self):
        # A coherent cycle avoids spending the remaining budget on 101 leaf reads.
        graph = {ROOT: [ROOT] + [(102, n) for n in range(1, 101)]}
        wire = Wire(graph)
        result = wire.read({101: 'example/product'})
        self.assertEqual(result.status, 'cycle')
        self.assertEqual(wire.calls,
                         [(0, ROOT, None), (0, ROOT, 'offset:100'),
                          (1, ROOT, None), (1, ROOT, 'offset:100')])

    def test_later_page_failure_preserves_prefix_without_empty_success(self):
        def fail(wire, key, after, result):
            if after is not None:
                raise GitHubError(CANARY, status=403)
        wire = Wire({ROOT: [(101, n) for n in range(2, 103)]}, callback=fail)
        result = wire.read()
        self.assertEqual(result.status, 'unknown')
        self.assertNotEqual(result.first.coverage, 'complete')
        self.assertTrue(result.first.edges)
        self.assertNotIn(CANARY, repr(result))
        self.assertLessEqual(len(wire.calls), 128)

    def test_hidden_root_never_means_no_dependencies(self):
        wire = Wire({}, callback=lambda *args: {'data': {'repository': None}})
        result = wire.read()
        self.assertEqual(result.status, 'unknown')
        self.assertEqual(result.first.coverage, 'unavailable')

    def test_unregistered_target_is_retained_but_never_queried(self):
        wire = Wire({ROOT: [(102, 2)]})
        result = wire.read({101: 'example/product'})
        self.assertEqual((result.status, result.reason), ('unknown', 'unregistered_producer'))
        self.assertEqual(result.first.edges, ((ROOT, (102, 2)),))
        self.assertEqual(wire.calls, [(0, ROOT, None), (1, ROOT, None)])

    def test_unregistered_root_and_invalid_mapping_make_no_requests(self):
        wire = Wire({})
        self.assertEqual(wire.read({}).status, 'unknown')
        for invalid in ({True: 'example/product'}, {101: '../product'},
                        {101: 'example/product', 102: 'EXAMPLE/PRODUCT'},
                        {101: 'x' * 201 + '/product'}, []):
            with self.subTest(invalid=invalid):
                with self.assertRaises((GitHubError, ValueError)):
                    wire.read(invalid)
        self.assertEqual(wire.calls, [])

    def test_registration_is_snapshotted_before_callbacks(self):
        registry = dict(REGISTRY)
        def mutate(wire, key, after, result):
            registry.clear()
        wire = Wire({ROOT: [(102, 2)]}, callback=mutate)
        self.assertEqual(wire.read(registry).status, 'matched')
        self.assertEqual(registry, {})

    def test_coherent_cycle_is_distinct_from_unknown(self):
        result = Wire({ROOT: [(101, 2)], (101, 2): [ROOT]}).read()
        self.assertEqual((result.status, result.reason), ('cycle', 'dependency_cycle'))

    def test_shortcut_does_not_hide_longest_path_over_depth_bound(self):
        graph = {(101, n): [(101, n + 1)] for n in range(1, 35)}
        graph[ROOT] = [(101, 2), (101, 34)]
        result = Wire(graph).read()
        self.assertEqual((result.status, result.reason), ('unknown', 'graph_depth_limit'))

    def test_node_and_edge_overflow_remain_bounded(self):
        cases = [('graph_node_limit', {ROOT: [(101, n) for n in range(2, 257)],
                                     (101, 2): [(102, 1)]}),
                 ('graph_edge_limit', {**{(101, n): [(101, k) for k in range(10, 220)]
                                         for n in range(2, 8)},
                                       ROOT: [(101, n) for n in range(2, 8)]})]
        for reason, graph in cases:
            with self.subTest(reason=reason):
                wire = Wire(graph)
                result = wire.read()
                self.assertEqual((result.status, result.reason), ('unknown', reason))
                for observed in (result.first, result.second):
                    self.assertLessEqual(len(observed.nodes), 256)
                    self.assertLessEqual(len(observed.edges), 1024)
                self.assertLessEqual(len(wire.calls), 128)

    def test_outer_request_budget_is_shared_across_both_passes(self):
        wire = Wire({ROOT: [(101, 2)]})
        with wire.client.read_budget(seconds=45, requests=3):
            result = wire.read()
        self.assertEqual(result.status, 'unknown')
        self.assertEqual(len(wire.calls), 3)
        self.assertEqual(wire.client._read_budgets, [])

    def test_late_response_and_final_comparison_cannot_be_matched(self):
        clock = [10.0]
        def late(wire, key, after, result):
            if wire.pass_index == 1:
                clock[0] = 100.0
        with patch('hydra_sdlc.github.time.monotonic', lambda: clock[0]):
            result = Wire({}, callback=late).read()
        self.assertEqual(result.status, 'unknown')

    def test_successful_credential_rotation_invalidates_even_a_cycle(self):
        def rotate(wire, key, after, result):
            if wire.pass_index == 0:
                wire.fingerprint = b'b' * 32
        wire = Wire({ROOT: [ROOT]}, callback=rotate)
        result = wire.read()
        self.assertEqual(result.status, 'unknown')
        self.assertEqual(result.first.edges, ())
        self.assertEqual(result.second.edges, ())

    def test_failed_credential_selection_stays_invalid_after_restore(self):
        def failed_selection(wire, key, after, result):
            if key == (101, 2):
                wire.client._credential_selected(b'b' * 32)
                wire.client._credential_selected(b'a' * 32)
                raise GitHubError(CANARY)
        wire = Wire({ROOT: [(101, 2)]}, callback=failed_selection)
        result = wire.read()
        self.assertEqual(result.status, 'unknown')
        self.assertEqual(result.first.edges, ())
        self.assertEqual(result.second.edges, ())

    def test_cross_node_and_cross_pass_provenance_changes_invalidate(self):
        for field in ('nameWithOwner', 'isPrivate', 'viewerPermission', 'node'):
            with self.subTest(field=field):
                def change(wire, key, after, result):
                    if key != (101, 2):
                        return
                    repo = result['data']['repository']
                    if field == 'node':
                        repo['issue']['id'] = 'I_CHANGED'
                    else:
                        repo[field] = {'nameWithOwner': 'example/renamed',
                                       'isPrivate': True, 'viewerPermission': 'WRITE'}[field]
                result = Wire({ROOT: [(101, 2)]}, callback=change).read()
                self.assertEqual(result.status, 'unknown')
                self.assertEqual(result.first.edges, ())
                self.assertEqual(result.second.edges, ())

    def test_previous_hook_is_composed_and_restored_on_success_and_failure(self):
        for graph in ({}, {ROOT: [ROOT]}):
            with self.subTest(graph=graph):
                wire = Wire(graph)
                calls = []
                hook = calls.append
                wire.client._credential_selected = hook
                result = wire.read()
                self.assertIn(result.status, {'matched', 'cycle'})
                self.assertIs(wire.client._credential_selected, hook)
                self.assertTrue(calls)
                self.assertEqual(wire.client._read_budgets, [])
