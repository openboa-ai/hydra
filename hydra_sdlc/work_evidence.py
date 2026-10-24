"""Internal input-evidence comparison; never an acceptance or execution grant.

Qualified readers own provenance, actual acceptance and source freshness. These
immutable values carry normalized observations, not a new provider protocol.
There is no public command, default reader, persistence or effect here.
"""
from dataclasses import dataclass
import json

from .github_producer_delivery import ProducerDeliveryRead
from .work_records import (_hex, _integer, _issue_ref, _json_object, _object,
                           _require, _requirements, _uuid, validate_binding)
from .work_relations import _time, compare_bound_producers


MAX_EVIDENCE_BYTES = 65_536
_DELIVERY_KEYS = {'attempt_id', 'contract_revision', 'spec_revision', 'source_digest',
                  'head', 'merge_sha', 'pr_number', 'progress_comment_id'}
_DELIVERY_STATES = {'verified', 'not_delivered', 'pending', 'failed', 'unknown', 'changed'}


@dataclass(frozen=True)
class RequirementEvidenceRead:
    """Normalized reader data, not proof of its origin or independent acceptance.

    `accepted` and `observed` contain exact RequirementRefs for one direct
    producer and delivery pin. Only a separately qualified source can establish
    those facts. Constructing this internal value never grants that capability.
    """
    document: str

    @property
    def value(self):
        return json.loads(self.document)


@dataclass(frozen=True)
class InputEvidenceComparison:
    status: str
    reason: str
    producer_count: int = 0
    clause_count: int = 0
    unmet_clauses: int = 0


def compare_input_evidence(binding, first_relation, second_relation, first, second,
                           *, spec_directory, conditions=None):
    """Compare fixed conditions with two supplied, already-qualified snapshots.

    Each snapshot maps (repository_id, issue_number) to a tuple of the existing
    ProducerDeliveryRead and an optional RequirementEvidenceRead. A match is a
    data consistency result, not permission to dispatch or a completed goal.
    It cannot certify freshness, provenance or atomicity of the caller's reads.
    Repaired outputs and goal aggregation retain their separate qualifications.
    """
    membership = compare_bound_producers(binding, first_relation, second_relation,
        spec_directory=spec_directory, conditions=conditions)

    def result(status, reason, unmet=0):
        return InputEvidenceComparison(status, reason, membership.producer_count,
                                       membership.clause_count, unmet)

    if membership.status != 'matched':
        return result(membership.status, membership.reason)
    value = validate_binding(binding, spec_directory=spec_directory).value
    contract = value['input_contract']
    clauses = contract['clauses'] if contract['kind'] == 'adopted' else conditions.value['clauses']
    if not clauses:
        return result('matched', 'no_required_inputs')
    expected = {_identity(clause['producer']) for clause in clauses}
    for snapshot in (first, second):
        if snapshot is None:
            return result('unknown', 'evidence_scope_unavailable')
        _require(type(snapshot) is dict, 'invalid_evidence')
        for key in snapshot:
            _require(type(key) is tuple and len(key) == 2, 'invalid_evidence')
            _issue_ref({'repository_id': key[0], 'issue_number': key[1]})
        if set(snapshot) != expected:
            return result('unknown', 'evidence_scope_unavailable')
    current = {}
    for key in sorted(expected):
        before, after = (_producer(snapshot[key], key) for snapshot in (first, second))
        if before[0] != after[0]:
            return result('changed', 'producer_delivery_changed')
        if before[1] != after[1]:
            return result('changed', 'requirement_evidence_changed')
        current[key] = after
    for delivered, accepted in current.values():
        status, pin = delivered
        if status != 'verified':
            outcome, reason = {
                'not_delivered': ('unmet', 'required_output_missing'),
                'pending': ('unknown', 'producer_delivery_pending'),
                'failed': ('unmet', 'producer_delivery_failed'),
                'unknown': ('unknown', 'producer_delivery_unavailable'),
                'changed': ('changed', 'producer_delivery_changed'),
            }[status]
            return result(outcome, reason)
        if accepted is None:
            return result('unknown', 'acceptance_unavailable')
        accepted_pin, coverage, _, _ = accepted
        if coverage != 'complete':
            return result('unknown', 'acceptance_incomplete')
        if accepted_pin != pin:
            return result('changed', 'acceptance_delivery_changed')
    missing_acceptance = missing_observation = 0
    for clause in clauses:
        _, accepted = current[_identity(clause['producer'])]
        _, _, accepted_refs, observed_refs = accepted
        required = {_reference(ref) for ref in clause['requirements']}
        if not required <= accepted_refs:
            missing_acceptance += 1
        elif clause['required_stage'] == 'observed' and not required <= observed_refs:
            missing_observation += 1
    if missing_acceptance:
        return result('unmet', 'required_requirement_missing', missing_acceptance + missing_observation)
    if missing_observation:
        return result('unmet', 'required_observation_missing', missing_observation)
    return result('matched', 'input_evidence_only')


def _identity(value):
    _issue_ref(value)
    return value['repository_id'], value['issue_number']


def _reference(value):
    return tuple(value[key] for key in ('repository_id', 'path', 'revision', 'selector'))


def _document(value, expected_type):
    _require(type(value) is expected_type and type(value.document) is str, 'invalid_evidence')
    try:
        size = len(value.document.encode('utf-8'))
    except UnicodeError:
        _require(False, 'invalid_evidence')
    _require(size <= MAX_EVIDENCE_BYTES, 'evidence_limit')
    return _json_object(value.document)


def _pin(value):
    _object(value, _DELIVERY_KEYS)
    _require(_uuid(value['attempt_id']) and _hex(value['source_digest'], 64), 'invalid_evidence')
    _require(all(_hex(value[key], 40) for key in
                 ('contract_revision', 'spec_revision', 'head', 'merge_sha')), 'invalid_evidence')
    _require(all(_integer(value[key]) for key in ('pr_number', 'progress_comment_id')), 'invalid_evidence')
    return tuple(value[key] for key in sorted(_DELIVERY_KEYS))


def _producer(row, key):
    _require(type(row) is tuple and len(row) == 2, 'invalid_evidence')
    delivery = _document(row[0], ProducerDeliveryRead)
    _object(delivery, {'source', 'status', 'reason', 'delivery', 'observed_at'})
    _require(_identity(delivery['source']) == key, 'identity_mismatch')
    _require(type(delivery['status']) is str and delivery['status'] in _DELIVERY_STATES,
             'invalid_evidence')
    _require(type(delivery['reason']) is str and 1 <= len(delivery['reason']) <= 128,
             'invalid_evidence')
    _time(delivery['observed_at'])
    if delivery['status'] == 'verified':
        _require(delivery['reason'] == 'delivery_only', 'invalid_evidence')
        pin = _pin(delivery['delivery'])
    else:
        _require(delivery['delivery'] is None, 'invalid_evidence')
        pin = None
    delivered = delivery['status'], pin
    if row[1] is None:
        return delivered, None
    accepted = _document(row[1], RequirementEvidenceRead)
    _object(accepted, {'source', 'delivery', 'coverage', 'accepted', 'observed'})
    _require(_identity(accepted['source']) == key, 'identity_mismatch')
    accepted_pin = _pin(accepted['delivery'])
    _require(type(accepted['coverage']) is str
             and accepted['coverage'] in {'complete', 'partial', 'unavailable'}, 'invalid_evidence')
    _requirements(accepted['accepted'])
    _requirements(accepted['observed'])
    accepted_refs = frozenset(_reference(ref) for ref in accepted['accepted'])
    observed_refs = frozenset(_reference(ref) for ref in accepted['observed'])
    _require(observed_refs <= accepted_refs, 'invalid_evidence')
    return delivered, (accepted_pin, accepted['coverage'], accepted_refs, observed_refs)
