import copy
import hashlib
import json
import unittest
from unittest.mock import patch

from hydra_sdlc.work_inputs import InputConditions, input_conditions
from hydra_sdlc.work_records import Binding, WorkRecordError, parse_binding
from hydra_sdlc.work_relations import (MAX_RELATION_ITEMS, RelationRead,
    compare_bound_producers, relation_read, validate_relation)


SOURCE = {'repository_id': 101, 'issue_number': 11}
PRODUCER = {'repository_id': 202, 'issue_number': 3}
OTHER = {'repository_id': 303, 'issue_number': 4}
AT = '2026-01-01T00:00:00Z'
LATER = '2026-01-01T00:00:01Z'
REQUIREMENT = {'repository_id': 101, 'path': 'docs/design/spec.md',
               'revision': '1' * 40, 'selector': 'R-CONSUME'}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def clause(producer=PRODUCER, selector='R-OUTPUT'):
    return {'producer': copy.deepcopy(producer), 'requirements': [
        {'repository_id': producer['repository_id'], 'path': 'docs/output/spec.md',
         'revision': '2' * 40, 'selector': selector}], 'required_stage': 'post_merge_verified',
        'basis': copy.deepcopy(REQUIREMENT)}


def binding(clauses=(), **changes):
    value = {**SOURCE, 'source_digest': 'a' * 64, 'kind': 'work', 'create_key': None,
        'delegated_goal': None, 'outcome': 'consume-output', 'requirements': [REQUIREMENT],
        'spec': {'path': 'docs/design/spec.md', 'revision': '1' * 40},
        'input_contract': {'kind': 'adopted', 'clauses': sorted(copy.deepcopy(list(clauses)), key=canonical)},
        'delegation_ref': None, **changes}
    return parse_binding('<!-- hydra-work:v2 ' + canonical(value) + ' -->', spec_directory='docs')


def read(items=(), *, source=SOURCE, relation='blocked_by', coverage='complete', at=AT):
    return relation_read(copy.deepcopy(source), relation, coverage, list(copy.deepcopy(items)), at)


def compare(fixed=None, first=None, second=None, **kwargs):
    return compare_bound_producers(binding() if fixed is None else fixed,
        read() if first is None else first, read(at=LATER) if second is None else second,
        spec_directory='docs', **kwargs)


class RelationReadTests(unittest.TestCase):
    def test_literal_empty_membership_digest_excludes_observation_time(self):
        expected = b'{"items":[],"relation":"blocked_by","source":{"issue_number":11,"repository_id":101}}'
        observed = read().value
        self.assertEqual(set(observed), {'source', 'relation', 'coverage', 'items', 'observed_at', 'digest'})
        self.assertEqual(observed['digest'], hashlib.sha256(expected).hexdigest())
        self.assertEqual(read(at=LATER).value['digest'], observed['digest'])
        self.assertEqual(validate_relation(read()).value, observed)

    def test_numeric_sort_and_immutable_snapshot(self):
        items = [{'repository_id': 20, 'issue_number': 1},
                 {'repository_id': 2, 'issue_number': 10}, {'repository_id': 2, 'issue_number': 2}]
        source = copy.deepcopy(SOURCE)
        observed = relation_read(source, 'blocked_by', 'complete', items, AT)
        source['repository_id'] = 999
        items[0]['issue_number'] = 999
        self.assertEqual(observed.value['source'], SOURCE)
        self.assertEqual(observed.value['items'], [
            {'repository_id': 2, 'issue_number': 2}, {'repository_id': 2, 'issue_number': 10},
            {'repository_id': 20, 'issue_number': 1}])
        changed = observed.value
        changed['items'].clear()
        self.assertEqual(len(observed.value['items']), 3)

    def test_partial_and_unavailable_cannot_have_complete_digests(self):
        for observation in (read([PRODUCER], coverage='partial'), read(coverage='unavailable')):
            self.assertIsNone(observation.value['digest'])
            self.assertEqual(validate_relation(observation).value, observation.value)
            forged = observation.value
            forged['digest'] = '0' * 64
            with self.assertRaises(WorkRecordError):
                validate_relation(RelationRead(canonical(forged)))
        with self.assertRaises(WorkRecordError):
            read([PRODUCER], coverage='unavailable')

    def test_parent_complete_cardinality_and_other_relation_names(self):
        self.assertEqual(read(relation='parent').value['items'], [])
        self.assertEqual(read([PRODUCER], relation='parent').value['items'], [PRODUCER])
        with self.assertRaises(WorkRecordError):
            read([PRODUCER, OTHER], relation='parent')
        for invalid in ('dependencies', 'legacy_issue', '', None):
            with self.subTest(relation=invalid), self.assertRaises(WorkRecordError):
                read(relation=invalid)

    def test_overflow_is_an_explicit_bounded_partial_observation(self):
        items = [{'repository_id': 202, 'issue_number': number} for number in range(1, 257)]
        observed = read(items).value
        self.assertEqual(MAX_RELATION_ITEMS, 255)
        self.assertEqual(observed['coverage'], 'partial')
        self.assertEqual(len(observed['items']), 255)
        self.assertIsNone(observed['digest'])
        self.assertEqual(observed['items'], items[:255])

    def test_duplicate_refs_are_errors_instead_of_silent_deduplication(self):
        with self.assertRaises(WorkRecordError) as caught:
            read([PRODUCER, PRODUCER])
        self.assertEqual(caught.exception.reason, 'duplicate_relation')

    def test_closed_identity_types_and_observation_time(self):
        for reference in ({'repository_id': True, 'issue_number': 1},
                          {'repository_id': 1, 'issue_number': 0},
                          {'repository_id': 1, 'issue_number': 1, 'state': 'closed'},
                          {'repository_id': 9_007_199_254_740_992, 'issue_number': 1}):
            with self.subTest(reference=reference), self.assertRaises(WorkRecordError):
                read([reference])
        for at in ('2026-01-01', '2026-01-01T00:00:00', '2026-01-01T09:00:00+09:00',
                   '2026-13-01T00:00:00Z', '2026-01-01T00:00:00-00:00', True):
            with self.subTest(at=at), self.assertRaises(WorkRecordError):
                read(at=at)
        self.assertEqual(read(at='2026-01-01T00:00:00.123456789+00:00').value['coverage'], 'complete')

    def test_forged_digest_unknown_fields_duplicate_json_and_oversized_dto_reject(self):
        values = []
        changed = read().value
        changed['digest'] = 'f' * 64
        values.append(canonical(changed))
        changed = read().value
        changed['authorized'] = True
        values.append(canonical(changed))
        values.append(read().document.replace('"coverage":"complete"', '"coverage":"complete","coverage":"complete"'))
        values.append(' ' * 65537)
        for raw in values:
            with self.subTest(size=len(raw)), self.assertRaises(WorkRecordError):
                validate_relation(RelationRead(raw))

    def test_digest_binds_source_and_relation_not_just_target_set(self):
        baseline = read([PRODUCER]).value['digest']
        self.assertNotEqual(read([PRODUCER], source=OTHER).value['digest'], baseline)
        self.assertNotEqual(read([PRODUCER], relation='children').value['digest'], baseline)


class BoundProducerMembershipTests(unittest.TestCase):
    def test_stable_empty_relations_and_explicit_empty_conditions_match(self):
        result = compare()
        self.assertEqual((result.status, result.reason, result.producer_count, result.clause_count),
                         ('matched', 'producer_membership_only', 0, 0))
        for name in ('ready', 'authorized', 'accepted', 'requirements_met', 'dispatch'):
            self.assertFalse(hasattr(result, name))

    def test_stable_normal_producer_and_multiple_clauses_match(self):
        fixed = binding([clause(selector='R-ONE'), clause(selector='R-TWO')])
        before = copy.deepcopy(fixed.value)
        result = compare(fixed, read([PRODUCER]), read([PRODUCER], at=LATER))
        self.assertEqual((result.status, result.producer_count, result.clause_count), ('matched', 1, 2))
        self.assertEqual(fixed.value, before)

    def test_membership_changes_between_collections_hold_even_if_second_matches(self):
        result = compare(binding([clause()]), read(), read([PRODUCER], at=LATER))
        self.assertEqual((result.status, result.reason), ('changed', 'relations_unstable'))

    def test_added_and_removed_edges_do_not_rewrite_fixed_conditions(self):
        fixed = binding([clause()])
        before = fixed.document
        for items in ([], [PRODUCER, OTHER]):
            with self.subTest(items=items):
                result = compare(fixed, read(items), read(items, at=LATER))
                self.assertEqual((result.status, result.reason), ('changed', 'relationship_changed'))
                self.assertEqual(fixed.document, before)

    def test_empty_conditions_do_not_absorb_new_edge(self):
        result = compare(binding(), read([PRODUCER]), read([PRODUCER], at=LATER))
        self.assertEqual(result.reason, 'relationship_changed')

    def test_same_issue_number_in_different_repository_is_a_different_producer(self):
        other = {'repository_id': 999, 'issue_number': 3}
        result = compare(binding([clause()]), read([other]), read([other], at=LATER))
        self.assertEqual(result.reason, 'relationship_changed')

    def test_partial_unavailable_and_missing_second_read_never_match(self):
        for coverage in ('partial', 'unavailable'):
            result = compare(binding(), read(coverage=coverage), read(at=LATER))
            self.assertEqual((result.status, result.reason), ('unknown', 'relations_incomplete'))
        for first, second in ((None, read()), (read(), None), (None, None)):
            result = compare_bound_producers(binding(), first, second, spec_directory='docs')
            self.assertEqual((result.status, result.reason), ('unknown', 'relations_unavailable'))

    def test_partial_children_do_not_replace_or_block_the_required_blocked_by_reads(self):
        unrelated = read([OTHER], relation='children', coverage='partial')
        self.assertEqual(unrelated.value['coverage'], 'partial')
        self.assertEqual(compare().status, 'matched')
        with self.assertRaises(WorkRecordError):
            compare(binding(), unrelated, read())

    def test_wrong_source_and_wrong_relation_are_never_adopted(self):
        for first in (read(source=OTHER), read(relation='parent'), read(relation='children')):
            with self.subTest(first=first.value), self.assertRaises(WorkRecordError):
                compare(binding(), first, read())

    def test_self_dependency_holds_without_using_issue_close_or_output_claims(self):
        result = compare(binding(), read([SOURCE]), read([SOURCE], at=LATER))
        self.assertEqual((result.status, result.reason), ('unknown', 'self_dependency'))

    def test_missing_input_contract_is_not_an_empty_contract(self):
        fixed = binding(input_contract=None)
        self.assertEqual(compare(fixed).reason, 'dependency_unknown')

    def test_reference_payload_uses_existing_p09_normalizer(self):
        fixed = binding(input_contract={'kind': 'reference', 'ref': {
            **REQUIREMENT, 'selector': 'Inputs'}})
        text = '# Inputs\n\n```json\n' + canonical({'clauses': [clause()]}) + '\n```\n'
        resolved = input_conditions(fixed, spec_directory='docs', content=text)
        result = compare(fixed, read([PRODUCER]), read([PRODUCER], at=LATER), conditions=resolved)
        self.assertEqual((result.status, result.clause_count), ('matched', 1))
        self.assertEqual(compare(fixed, read([PRODUCER]), read([PRODUCER], at=LATER)).reason,
                         'accepted_meaning_unavailable')

    def test_adopted_payload_cannot_be_replaced_with_another_conditions_value(self):
        other = input_conditions(binding([clause()]), spec_directory='docs')
        with self.assertRaises(WorkRecordError) as caught:
            compare(binding(), conditions=other)
        self.assertEqual(caught.exception.reason, 'input_conditions_mismatch')

    def test_invalid_reference_payload_and_forged_binding_are_revalidated(self):
        fixed = binding(input_contract={'kind': 'reference', 'ref': {
            **REQUIREMENT, 'selector': 'Inputs'}})
        for document in ('{"clauses":[],"authorized":true}', '{"clauses":true}',
                         '{"clauses":[],"clauses":[]}', ' ' * 65537):
            with self.subTest(document=document[:30]), self.assertRaises(WorkRecordError):
                compare(fixed, conditions=InputConditions(document))
        forged = binding().value
        forged['authorized'] = True
        with self.assertRaises(WorkRecordError):
            compare(Binding(canonical(forged)))

    def test_current_parent_is_separate_from_fixed_goal_and_input_conditions(self):
        goal = {**OTHER, 'source_digest': 'f' * 64}
        fixed = binding(delegated_goal=goal)
        original = fixed.document
        self.assertEqual(read([PRODUCER], relation='parent').value['items'], [PRODUCER])
        self.assertEqual(compare(fixed).status, 'matched')
        self.assertEqual(fixed.document, original)

    def test_fresh_controller_values_restore_same_membership_without_persistent_state(self):
        fixed = binding([clause()])
        first = compare(fixed, read([PRODUCER]), read([PRODUCER], at=LATER))
        restored = compare(Binding(fixed.document), RelationRead(read([PRODUCER]).document),
                           RelationRead(read([PRODUCER], at=LATER).document))
        self.assertEqual(first, restored)

    def test_matched_membership_has_no_transport_or_effect_calls(self):
        with patch('hydra_sdlc.github.GitHub.api', side_effect=AssertionError('Unexpected API call')):
            self.assertEqual(compare().status, 'matched')


class DependencyTopologyTests(unittest.TestCase):
    @staticmethod
    def ref(key):
        return {'repository_id': key[0], 'issue_number': key[1]}

    @classmethod
    def pool(cls, adjacency, at=AT):
        return {source: read([cls.ref(item) for item in items],
            source=cls.ref(source), at=at) for source, items in adjacency.items()}

    def topology(self, first, second=..., *, repositories=frozenset({1})):
        from hydra_sdlc.work_relations import dependency_topology
        if second is ...:
            second = copy.deepcopy(first)
        return dependency_topology(self.ref((1, 1)), first, second,
            registered_repositories=repositories)

    def test_complete_empty_graph_is_a_valid_topology_only_match(self):
        result = self.topology(self.pool({(1, 1): []}))
        self.assertEqual((result.status, result.reason), ('matched', 'topology_only'))
        self.assertEqual(result.second.coverage, 'complete')
        self.assertEqual(result.second.nodes, ((1, 1),))
        self.assertEqual(result.second.edges, ())

    def test_complete_chain_preserves_exact_numeric_edges(self):
        result = self.topology(self.pool({(1, 1): [(1, 2)], (1, 2): [(1, 3)], (1, 3): []}))
        self.assertEqual(result.status, 'matched')
        self.assertEqual(result.second.nodes, ((1, 1), (1, 2), (1, 3)))
        self.assertEqual(result.second.edges, (((1, 1), (1, 2)), ((1, 2), (1, 3))))
        self.assertFalse(result.second.cyclic)

    def test_transitive_drift_holds_with_identical_root_membership(self):
        first = self.pool({(1, 1): [(1, 2)], (1, 2): [(1, 3)], (1, 3): []})
        second = self.pool({(1, 1): [(1, 2)], (1, 2): []})
        saved = copy.deepcopy((first, second))
        result = self.topology(first, second)
        self.assertEqual((result.status, result.reason), ('changed', 'relations_unstable'))
        self.assertEqual(result.first.nodes, ((1, 1), (1, 2), (1, 3)))
        self.assertEqual(result.second.nodes, ((1, 1), (1, 2)))
        self.assertEqual((first, second), saved)

    def test_timestamp_and_input_order_do_not_change_topology(self):
        first = self.pool({(1, 1): [(1, 10), (1, 2)], (1, 2): [], (1, 10): []})
        second = dict(reversed(list(self.pool(
            {(1, 10): [], (1, 2): [], (1, 1): [(1, 2), (1, 10)]}, LATER).items())))
        result = self.topology(first, second)
        self.assertEqual(result.status, 'matched')
        self.assertEqual(result.second.nodes, ((1, 1), (1, 2), (1, 10)))

    def test_self_and_indirect_cycles_are_distinct_from_incomplete_reads(self):
        for adjacency in ({(1, 1): [(1, 1)]},
                {(1, 1): [(1, 2)], (1, 2): [(1, 3)], (1, 3): [(1, 2)]}):
            with self.subTest(adjacency=adjacency):
                result = self.topology(self.pool(adjacency))
                self.assertEqual((result.status, result.reason), ('cycle', 'dependency_cycle'))
                self.assertTrue(result.second.cyclic)
                self.assertEqual(result.second.coverage, 'complete')

    def test_an_observed_cycle_remains_a_cycle_with_an_unavailable_branch(self):
        pool = self.pool({(1, 1): [(1, 1), (1, 2)]})
        result = self.topology(pool)
        self.assertEqual(result.status, 'cycle')
        self.assertTrue(result.second.cyclic)
        self.assertEqual(result.second.coverage, 'partial')

    def test_missing_root_and_reachable_reads_never_become_empty_complete(self):
        for pool, coverage in ((None, 'unavailable'), ({}, 'unavailable'),
                (self.pool({(1, 1): [(1, 2)]}), 'partial')):
            with self.subTest(coverage=coverage):
                result = self.topology(pool)
                self.assertEqual((result.status, result.reason), ('unknown', 'relations_unavailable'))
                self.assertEqual(result.second.coverage, coverage)

    def test_each_pass_must_be_complete_and_keeps_its_own_facts(self):
        complete = self.pool({(1, 1): [(1, 2)], (1, 2): []})
        result = self.topology(complete, None)
        self.assertEqual(result.status, 'unknown')
        self.assertEqual(result.first.edges, (((1, 1), (1, 2)),))
        self.assertEqual(result.first.coverage, 'complete')
        self.assertEqual(result.second.coverage, 'unavailable')
        self.assertEqual(self.topology(None, complete).status, 'unknown')

    def test_partial_edges_are_retained_without_becoming_a_match(self):
        pool = self.pool({(1, 2): []})
        pool[(1, 1)] = read([self.ref((1, 2))], source=self.ref((1, 1)), coverage='partial')
        result = self.topology(pool)
        self.assertEqual((result.status, result.reason), ('unknown', 'relations_incomplete'))
        self.assertEqual(result.second.coverage, 'partial')
        self.assertEqual(result.second.edges, (((1, 1), (1, 2)),))

    def test_unavailable_dto_is_not_an_empty_complete_relation(self):
        pool = {(1, 1): read(source=self.ref((1, 1)), coverage='unavailable')}
        result = self.topology(pool)
        self.assertEqual((result.status, result.reason), ('unknown', 'relations_unavailable'))
        self.assertEqual(result.second.coverage, 'unavailable')

    def test_registered_cross_repository_graph_can_match(self):
        pool = self.pool({(1, 1): [(2, 3)], (2, 3): []})
        result = self.topology(pool, repositories=frozenset({1, 2}))
        self.assertEqual(result.status, 'matched')
        self.assertEqual(result.second.edges, (((1, 1), (2, 3)),))

    def test_unregistered_sources_are_held_without_reading_their_values(self):
        pool = self.pool({(1, 1): [(2, 3)]})
        pool[(2, 3)] = object()
        result = self.topology(pool)
        self.assertEqual((result.status, result.reason), ('unknown', 'unregistered_producer'))
        result = self.topology({(1, 1): object()}, repositories=frozenset())
        self.assertEqual((result.status, result.reason), ('unknown', 'unregistered_producer'))

    def test_unrelated_invalid_and_cyclic_components_do_not_block_this_root(self):
        pool = self.pool({(1, 1): [], (1, 20): [(1, 20)]})
        pool[(9, 9)] = object()
        result = self.topology(pool)
        self.assertEqual(result.status, 'matched')
        self.assertEqual(result.second.nodes, ((1, 1),))

    def test_selected_dtos_revalidate_identity_relation_and_digest(self):
        for mode in ('identity', 'relation', 'digest'):
            with self.subTest(mode=mode):
                row = read(source=self.ref((1, 2)) if mode == 'identity' else self.ref((1, 1)),
                    relation='parent' if mode == 'relation' else 'blocked_by')
                if mode == 'digest':
                    value = row.value
                    value['digest'] = 'a' * 64
                    row = RelationRead(canonical(value))
                with self.assertRaises(WorkRecordError):
                    self.topology({(1, 1): row})

    def test_snapshot_remains_immutable_after_inputs_change(self):
        pool = self.pool({(1, 1): [(1, 2)], (1, 2): []})
        result = self.topology(pool)
        pool.clear()
        self.assertEqual(result.second.nodes, ((1, 1), (1, 2)))
        self.assertEqual(result.second.edges, (((1, 1), (1, 2)),))
        with self.assertRaises(AttributeError):
            result.second.nodes += ((1, 3),)

    def test_node_budget_is_global_across_individually_valid_relations(self):
        adjacency = {(1, n): [] for n in range(1, 257)}
        adjacency[(1, 1)] = [(1, n) for n in range(2, 257)]
        exact = self.topology(self.pool(adjacency))
        self.assertEqual(exact.status, 'matched')
        self.assertEqual(len(exact.second.nodes), 256)
        adjacency[(1, 2)] = [(1, 257)]
        adjacency[(1, 257)] = []
        over = self.topology(self.pool(adjacency))
        self.assertEqual((over.status, over.reason), ('unknown', 'graph_node_limit'))
        self.assertEqual(over.second.coverage, 'partial')
        self.assertLessEqual(len(over.second.nodes), 256)

    def test_edge_budget_boundary_does_not_reject_the_normal_control(self):
        adjacency = {(1, n): [] for n in range(1, 257)}
        adjacency[(1, 1)] = [(1, n) for n in range(2, 257)]
        for n in range(2, 6):
            adjacency[(1, n)] = [(1, k) for k in range(6, 198)]
        adjacency[(1, 6)] = [(1, 255)]
        exact = self.topology(self.pool(adjacency))
        self.assertEqual(exact.status, 'matched')
        self.assertEqual(len(exact.second.edges), 1024)
        adjacency[(1, 6)] = [(1, 254), (1, 255)]
        over = self.topology(self.pool(adjacency))
        self.assertEqual((over.status, over.reason), ('unknown', 'graph_edge_limit'))
        self.assertEqual(over.second.coverage, 'partial')
        self.assertLessEqual(len(over.second.edges), 1024)

    def test_depth_32_matches_and_depth_33_is_partial(self):
        adjacency = {(1, n): [(1, n + 1)] for n in range(1, 33)}
        adjacency[(1, 33)] = []
        exact = self.topology(self.pool(adjacency))
        self.assertEqual(exact.status, 'matched')
        adjacency[(1, 33)] = [(1, 34)]
        adjacency[(1, 34)] = []
        over = self.topology(self.pool(adjacency))
        self.assertEqual((over.status, over.reason), ('unknown', 'graph_depth_limit'))
        self.assertEqual(over.second.coverage, 'partial')

    def test_shortcuts_cannot_hide_an_over_depth_acyclic_path(self):
        adjacency = {(1, n): [(1, n + 1)] for n in range(2, 34)}
        adjacency[(1, 34)] = []
        adjacency[(1, 1)] = [(1, n) for n in range(2, 35)]
        result = self.topology(self.pool(adjacency))
        self.assertEqual((result.status, result.reason), ('unknown', 'graph_depth_limit'))
        self.assertFalse(result.second.cyclic)

    def test_invalid_graph_context_is_rejected_instead_of_inferred(self):
        pool = self.pool({(1, 1): []})
        for invalid in (True, '1', {True}, {0}, {9007199254740992}):
            with self.subTest(context=repr(invalid)):
                with self.assertRaises(WorkRecordError):
                    self.topology(pool, repositories=invalid)
        with self.assertRaises(WorkRecordError):
            self.topology([])


if __name__ == '__main__':
    unittest.main()
