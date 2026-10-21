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
