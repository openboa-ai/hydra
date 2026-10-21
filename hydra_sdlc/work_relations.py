"""Stateless relation membership checks for fixed v2 input conditions.

These values do not authenticate a source, accept a binding, satisfy an output
requirement, or authorize dispatch. The qualified reader and common effect guard
own those boundaries. No transport, relation edit, persistence, or fallback is
provided here.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
import hashlib
import re

from .work_inputs import InputConditions, input_conditions
from .work_records import (_canonical, _hex, _input_contract, _issue_ref,
                           _json_object, _object, _require, validate_binding)


MAX_RELATION_ITEMS = 255  # One source plus these targets fits the 256-node budget.
MAX_RELATION_BYTES = 65_536
_FIELDS = {'source', 'relation', 'coverage', 'items', 'observed_at', 'digest'}


def _time(value):
    _require(type(value) is str and re.fullmatch(
        r'\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?(?:Z|\+00:00)', value) is not None,
        'invalid_relation')
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        _require(False, 'invalid_relation')
    _require(parsed.utcoffset() == timedelta(0), 'invalid_relation')


def _identity(value):
    _issue_ref(value)
    return value['repository_id'], value['issue_number']


def _membership(value):
    return {'source': value['source'], 'relation': value['relation'], 'items': value['items']}


def _digest(value):
    return hashlib.sha256(_canonical(_membership(value)).encode('utf-8')).hexdigest()


@dataclass(frozen=True, repr=False)
class RelationRead:
    document: str

    @property
    def value(self):
        return _json_object(self.document)


def relation_read(source, relation, coverage, items, observed_at):
    """Snapshot the exact WR fields; a bounded prefix is explicitly partial.

    The source reader must establish endpoint coverage and identity before asking
    for a complete observation. This constructor cannot establish those facts.
    Limits here cover one source collection, not a complete transitive graph.
    """
    _issue_ref(source)
    _require(type(relation) is str and relation in {'parent', 'children', 'blocked_by'},
             'invalid_relation')
    _require(type(coverage) is str and coverage in {'complete', 'partial', 'unavailable'},
             'invalid_relation')
    _require(type(items) is list, 'invalid_relation')
    _time(observed_at)
    _require(coverage != 'unavailable' or not items, 'invalid_relation')
    _require(relation != 'parent' or coverage != 'complete' or len(items) <= 1,
             'invalid_relation')
    if len(items) > MAX_RELATION_ITEMS:
        items, coverage = items[:MAX_RELATION_ITEMS], 'partial'
    identities = [_identity(item) for item in items]
    _require(len(identities) == len(set(identities)), 'duplicate_relation')
    value = {'source': source, 'relation': relation, 'coverage': coverage,
             'items': sorted(items, key=_identity), 'observed_at': observed_at, 'digest': None}
    if coverage == 'complete':
        value['digest'] = _digest(value)
    return RelationRead(_canonical(value))


def validate_relation(read):
    """Revalidate values supplied to a consumer, including manually built DTOs."""
    _require(type(read) is RelationRead and type(read.document) is str, 'invalid_relation')
    try:
        size = len(read.document.encode('utf-8'))
    except UnicodeError:
        _require(False, 'invalid_relation')
    _require(size <= MAX_RELATION_BYTES, 'relation_limit')
    value = _json_object(read.document)
    _object(value, _FIELDS)
    _require(type(value['items']) is list and len(value['items']) <= MAX_RELATION_ITEMS,
             'relation_limit')
    normalized = relation_read(value['source'], value['relation'], value['coverage'],
                               value['items'], value['observed_at'])
    expected = normalized.value
    _require(value['digest'] == expected['digest'], 'invalid_relation_digest')
    return normalized


@dataclass(frozen=True)
class ProducerMembership:
    status: str
    reason: str
    producer_count: int = 0
    clause_count: int = 0


def compare_bound_producers(binding, first, second, *, spec_directory, conditions=None):
    """Compare current blocked-by membership with a fixed binding's conditions.

    Reference conditions must come from the existing qualified P09 reader for
    that exact binding/reference. Neither an InputConditions value nor this result
    attests its provenance or independent acceptance. This helper is not exposed
    as a command, and matching membership is never a readiness/authority result.
    """
    value = validate_binding(binding, spec_directory=spec_directory).value
    target = {key: value[key] for key in ('repository_id', 'issue_number')}
    if first is None or second is None:
        return ProducerMembership('unknown', 'relations_unavailable')
    observations = [validate_relation(read).value for read in (first, second)]
    for observed in observations:
        _require(observed['source'] == target, 'identity_mismatch')
        _require(observed['relation'] == 'blocked_by', 'relation_mismatch')
    if any(observed['coverage'] != 'complete' for observed in observations):
        return ProducerMembership('unknown', 'relations_incomplete')
    if observations[0]['digest'] != observations[1]['digest']:
        return ProducerMembership('changed', 'relations_unstable')
    current = {_identity(item) for item in observations[1]['items']}
    if _identity(target) in current:
        return ProducerMembership('unknown', 'self_dependency')
    contract = value['input_contract']
    if contract is None:
        return ProducerMembership('unknown', 'dependency_unknown', len(current))
    if contract['kind'] == 'adopted':
        resolved = input_conditions(binding, spec_directory=spec_directory)
        if conditions is not None:
            _require(type(conditions) is InputConditions
                     and conditions.document == resolved.document, 'input_conditions_mismatch')
    else:
        if conditions is None:
            return ProducerMembership('unknown', 'accepted_meaning_unavailable', len(current))
        _require(type(conditions) is InputConditions and type(conditions.document) is str,
                 'invalid_input_conditions')
        try:
            size = len(conditions.document.encode('utf-8'))
        except UnicodeError:
            _require(False, 'invalid_input_conditions')
        _require(size <= MAX_RELATION_BYTES, 'input_conditions_limit')
        resolved = conditions
    payload = resolved.value
    _object(payload, {'clauses'})
    _input_contract({'kind': 'adopted', 'clauses': payload['clauses']}, target)
    expected = {_identity(clause['producer']) for clause in payload['clauses']}
    if current != expected:
        return ProducerMembership('changed', 'relationship_changed', len(current), len(payload['clauses']))
    return ProducerMembership('matched', 'producer_membership_only', len(current), len(payload['clauses']))


@dataclass(frozen=True)
class DependencyGraph:
    coverage: str
    reason: str
    nodes: tuple
    edges: tuple
    cyclic: bool


@dataclass(frozen=True)
class DependencyTopology:
    status: str
    reason: str
    first: DependencyGraph
    second: DependencyGraph


def _dependency_graph(root, reads, registered):
    """Analyze reachable supplied observations without fetching missing rows.

    A false cyclic flag on a partial observation does not prove acyclicity.
    """
    nodes, edges, queue, depths = {root}, set(), [root], {root: 0}
    coverage, reason, position, stopped = 'complete', 'graph_observed', 0, False

    def hold(code, *, unavailable=False):
        nonlocal coverage, reason
        if coverage == 'complete':
            coverage = 'unavailable' if unavailable else 'partial'
            reason = code

    while position < len(queue) and not stopped:
        source = queue[position]
        position += 1
        if source[0] not in registered:
            hold('unregistered_producer', unavailable=source == root)
            continue
        observed = None if reads is None else reads.get(source)
        if observed is None:
            hold('relations_unavailable', unavailable=source == root)
            continue
        value = validate_relation(observed).value
        _require(_identity(value['source']) == source, 'identity_mismatch')
        _require(value['relation'] == 'blocked_by', 'relation_mismatch')
        if value['coverage'] != 'complete':
            hold('relations_unavailable' if value['coverage'] == 'unavailable'
                 else 'relations_incomplete', unavailable=source == root
                 and value['coverage'] == 'unavailable')
        for item in value['items']:
            target = _identity(item)
            if len(edges) >= 1024:
                coverage, reason, stopped = 'partial', 'graph_edge_limit', True
                break
            if target not in nodes:
                if len(nodes) >= 256:
                    coverage, reason, stopped = 'partial', 'graph_node_limit', True
                    break
                if depths[source] + 1 > 32:
                    coverage, reason, stopped = 'partial', 'graph_depth_limit', True
                    break
                nodes.add(target)
                depths[target] = depths[source] + 1
                queue.append(target)
            edges.add((source, target))

    # Kahn's algorithm detects cycles without recursion and computes the longest
    # acyclic root path. Discovery depth alone would let shortcut edges hide it.
    outgoing = {node: [] for node in nodes}
    incoming = dict.fromkeys(nodes, 0)
    longest = dict.fromkeys(nodes, 0)
    for source, target in edges:
        outgoing[source].append(target)
        incoming[target] += 1
    ready = [node for node in sorted(nodes) if incoming[node] == 0]
    position = 0
    while position < len(ready):
        source = ready[position]
        position += 1
        for target in outgoing[source]:
            longest[target] = max(longest[target], longest[source] + 1)
            incoming[target] -= 1
            if incoming[target] == 0:
                ready.append(target)
    cyclic = len(ready) != len(nodes)
    if not cyclic and max(longest.values()) > 32:
        coverage, reason = 'partial', 'graph_depth_limit'
    return DependencyGraph(coverage, reason, tuple(sorted(nodes)),
                           tuple(sorted(edges)), cyclic)


def dependency_topology(root, first, second, *, registered_repositories):
    """Compare two bounded blocked-by graphs, never readiness or authority.

    Read pools are plain dictionaries keyed by numeric (repository_id,
    issue_number); None denotes an unavailable pass/row. Only reachable rows are
    inspected. Qualified source adapters own visibility, complete pagination,
    request budgets and current registration. This function performs no I/O and
    cannot authenticate the supplied observations or repository scope.
    Supplying the same pool twice does not prove two actual provider reads.

    Each immutable pass retains its own coverage and bounded observed prefix.
    Matching topology does not satisfy a binding's inputs, deliverables or stage,
    validate its parent, or grant any effect. Callers must re-read before effects.
    """
    source = _identity(root)
    _require(first is None or type(first) is dict, 'invalid_graph_reads')
    _require(second is None or type(second) is dict, 'invalid_graph_reads')
    _require(type(registered_repositories) in {set, frozenset}, 'invalid_graph_context')
    registered = frozenset(registered_repositories)
    for identifier in registered:
        _identity({'repository_id': identifier, 'issue_number': 1})
    before = _dependency_graph(source, first, registered)
    after = _dependency_graph(source, second, registered)
    if after.cyclic:
        return DependencyTopology('cycle', 'dependency_cycle', before, after)
    for observed in (after, before):
        if observed.coverage != 'complete':
            return DependencyTopology('unknown', observed.reason, before, after)
    if before.nodes != after.nodes or before.edges != after.edges:
        return DependencyTopology('changed', 'relations_unstable', before, after)
    return DependencyTopology('matched', 'topology_only', before, after)
