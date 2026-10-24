"""Internal P06 decision inputs and pure reconciliation.

These are normalized facts for an independently qualified source adapter, not
provider fields or a caller JSON schema. No default adapter, qualification,
authority grant, persistence or effect dispatcher is supplied by this module.
The owning controller must re-read source facts and enforce current policy,
ownership and admission before acting on a plan.
"""
from dataclasses import dataclass, field
import re

from .github import GitHub, GitHubError
from .native_question_source import SourceScope
from . import projection as p
from .public_decisions import (DecisionObservation, InvalidPublicDecision,
                               PublicContext, context_basis, parse_context)


_ROLES = frozenset({'work', 'question', 'answer', 'adoption', 'authority', 'proposal'})


@dataclass(frozen=True, repr=False)
class DecisionEvidence:
    """One original private source ref and its qualified change detection."""
    role: str
    resource: tuple[str, str, str]
    revision: tuple[str, str] | None
    actionable_digest: str | None = None

    def reference(self):
        return dict(zip(('source', 'kind', 'id'), self.resource))

    def source_check(self):
        return {'resource': self.reference(),
                'revision': None if self.revision is None else dict(zip(('kind', 'value'), self.revision)),
                'actionable_digest': self.actionable_digest}


@dataclass(frozen=True, repr=False)
class DecisionSelection:
    """A qualified adapter's explicit selection, never decoded from a command.

    The adapter owns actual question/answer/adoption/authority/work mapping and
    complete scope coverage. Constructing this type is not that qualification.
    The exact public proposal already exists in its original private source.
    """
    scope: SourceScope
    context: PublicContext
    evidence: tuple[DecisionEvidence, ...]
    predecessor: PublicContext | None = None
    replacement: DecisionEvidence | None = None
    replan: DecisionEvidence | None = None

    @property
    def proposal(self):
        return next(item for item in self.evidence if item.role == 'proposal')


@dataclass(frozen=True, repr=False)
class DecisionCallCoverage:
    """Original physical-call evidence; absence or unknown count is not zero.

    A real adapter must qualify how it obtains these facts. No native provider
    is assumed to expose fields bearing these names. Applied progress is
    separately reconciled from the authenticated original progress source.
    """
    complete: bool
    context_posts: int | None
    receipt_posts: int | None
    resume_writes: int | None
    resume_state: str


@dataclass(frozen=True, repr=False)
class DecisionPlan:
    action: str
    reason: str
    resume_record: dict | None = field(default=None, repr=False)


class InvalidDecisionFacts(ValueError):
    def __init__(self):
        super().__init__('invalid_decision_facts')


def _require(value):
    if not value:
        raise InvalidDecisionFacts()


def _evidence(value, role):
    _require(type(value) is DecisionEvidence and value.role == role
             and type(value.resource) is tuple and len(value.resource) == 3
             and all(type(item) is str for item in value.resource))
    p.ref(value.reference())
    _require(value.resource[0] == 'codex')
    if value.revision is not None:
        _require(type(value.revision) is tuple and len(value.revision) == 2
                 and all(type(item) is str for item in value.revision))
        p.revision(dict(zip(('kind', 'value'), value.revision)))
    if value.actionable_digest is not None:
        _require(type(value.actionable_digest) is str
                 and re.fullmatch('[0-9a-f]{64}', value.actionable_digest) is not None)
    _require(value.revision is not None or value.actionable_digest is not None)


def validate_selection(value):
    """Validate normalized data shape; the adapter still owns its provenance."""
    try:
        _require(type(value) is DecisionSelection and type(value.scope) is SourceScope
                 and all(type(item) is str and 0 < len(item) <= 256
                         and all(ord(char) >= 32 and not 127 <= ord(char) <= 159 for char in item)
                         for item in (value.scope.source_id, value.scope.connection_id, value.scope.task_id))
                 and type(value.context) is PublicContext and type(value.evidence) is tuple
                 and len(value.evidence) == len(_ROLES))
        _require(all(type(item) is DecisionEvidence for item in value.evidence))
        _require({item.role for item in value.evidence} == _ROLES)
        for item in value.evidence:
            _evidence(item, item.role)
        context = parse_context(value.context.body)
        basis = context_basis(context)
        if context.key[3] == 1:
            _require(value.predecessor is None and value.replacement is None and value.replan is None)
        else:
            _require(type(value.predecessor) is PublicContext)
            previous = parse_context(value.predecessor.body)
            _require(previous.key[:3] == context.key[:3] and previous.key[3] == context.key[3] - 1
                     and basis['supersedes']['context_sha256'] == previous.sha256)
            _evidence(value.replacement, 'replacement')
            if value.replan is not None:
                _evidence(value.replan, 'replan')
        return context, basis
    except (ValueError, TypeError, AttributeError, KeyError, StopIteration):
        raise InvalidDecisionFacts() from None


def _calls(value):
    _require(type(value) is DecisionCallCoverage and type(value.complete) is bool)
    for count in (value.context_posts, value.receipt_posts, value.resume_writes):
        _require(count is None or type(count) is int and 0 <= count <= 3)
    _require(type(value.resume_state) is str and value.resume_state in
             {'not_dispatched', 'not_applied', 'unconfirmed', 'applied'})
    if value.resume_state == 'not_dispatched':
        _require(value.resume_writes == 0)
    elif value.resume_state in {'not_applied', 'applied'}:
        _require(type(value.resume_writes) is int and value.resume_writes > 0)
    else:
        _require(value.resume_writes is None or value.resume_writes > 0)


def _public(value):
    _require(type(value) is DecisionObservation and type(value.status) is str
             and value.status in {'unknown', 'conflict', 'pair', 'context',
                                  'not_observed', 'receipt_without_context'})
    for identifier in (value.context_id, value.receipt_id):
        _require(identifier is None or type(identifier) is int and 0 < identifier <= 9_007_199_254_740_991)
    if value.status == 'pair':
        _require(value.context_id is not None and value.receipt_id is not None
                 and value.context_id != value.receipt_id)
    elif value.status == 'context':
        _require(value.context_id is not None and value.receipt_id is None)
    elif value.status == 'not_observed':
        _require(value.context_id is None and value.receipt_id is None)


def decision_root(context):
    basis = context_basis(context)
    return {'decision': {'key': basis['key'], 'context_sha256': context.sha256},
            'resume_attempt': basis['resume_attempt']}


def consumed_decision(record, context, linked_source_attempt, root):
    basis = context_basis(context)
    return (linked_source_attempt == context.key[2] and
            (root == decision_root(context) or root is None and record.get('attempt_id') == basis['resume_attempt']))


def decision_plan(selection, calls, record, public, *, resume=False, linked_source_attempt=None, native_root=None,
                  predecessor_public=None, predecessor_calls=None):
    """Choose one bounded next operation; never perform it or confer authority."""
    hold = lambda reason: DecisionPlan('hold', reason)
    try:
        context, basis = validate_selection(selection)
        _calls(calls)
        _public(public)
        _require(type(resume) is bool and type(record) is dict)
        GitHub._validate_record(record, metadata=True)
        _require(record.get('repository_id') == context.key[0]
                 and record.get('issue_number') == context.key[1])
    except (InvalidDecisionFacts, GitHubError, InvalidPublicDecision, ValueError, TypeError):
        return hold('decision_facts_unavailable')
    if public.status in {'unknown', 'conflict', 'receipt_without_context'}:
        return hold('decision_evidence_conflict' if public.status == 'conflict' else 'decision_evidence_unknown')
    # An exact authenticated resumed record is stronger than an uncertain PATCH
    # response. Current policy/head/spec/ownership guards still belong to Runner.
    if (consumed_decision(record, context, linked_source_attempt, native_root)
            and record.get('contract_revision') == basis['contract_revision']
            and record.get('intake_digest') == basis['intake_digest']):
        return (DecisionPlan('reuse_resume' if resume else 'publish_complete', 'decision_reconciled')
                if public.status == 'pair' else hold('decision_pair_missing'))
    if record.get('native_step') or record.get('pending_action') is not None:
        return hold('decision_checkpoint_missing')
    source_attempt = context.key[2]
    if context.key[3] > 1:
        try:
            _public(predecessor_public)
            _calls(predecessor_calls)
            previous_basis = context_basis(selection.predecessor)
        except (InvalidDecisionFacts, InvalidPublicDecision, ValueError, TypeError):
            return hold('decision_predecessor_unknown')
        if (not predecessor_calls.complete or any(count is None for count in (
                predecessor_calls.context_posts, predecessor_calls.receipt_posts,
                predecessor_calls.resume_writes))
                or predecessor_public.status not in {'context', 'pair'}):
            return hold('decision_predecessor_unknown')
        consumed = consumed_decision(record, selection.predecessor, linked_source_attempt, native_root)
        if predecessor_calls.resume_writes and not consumed and predecessor_calls.resume_state != 'not_applied':
            return hold('decision_resume_unknown')
        if (predecessor_public.status == 'pair' or consumed) and selection.replan is None:
            return hold('decision_amendment_required')
        if consumed:
            source_attempt = record['attempt_id']
    if (record.get('attempt_id') != source_attempt or record.get('wait_reason') != 'product_decision'
            or record.get('next_action') != 'operator_decision'
            or record.get('phase') in {'executing', 'completed', 'merging'}
            or record.get('branch') != 'hydra/issue-' + str(context.key[1])
            or record.get('resume_phase') != basis['origin_phase']
            or any(record.get(name) != basis[name] for name in
                   ('head', 'contract_revision', 'spec_revision', 'intake_digest'))):
        return hold('decision_source_changed')
    if resume:
        if public.status != 'pair':
            return hold('decision_pair_missing')
        if not calls.complete or calls.resume_writes is None:
            return hold('decision_call_coverage_unknown')
        if calls.resume_state not in {'not_dispatched', 'not_applied'}:
            return hold('decision_resume_unknown')
        if calls.resume_writes >= 3:
            return hold('decision_retry_exhausted')
        values = {name: value for name, value in record.items()
                  if name not in {'repository_id', 'issue_number', 'version'}}
        values.update(attempt_id=basis['resume_attempt'],
            phase='implementation_done' if basis['origin_phase'] in {'correction', 'change_review'} else 'ready',
            wait_reason=None, pending_action=None, resume_phase=basis['origin_phase'],
            next_action='decision_context_' + context.key[2])
        return DecisionPlan('record_resume', 'decision_ready', values)
    if public.status == 'pair':
        return DecisionPlan('publish_complete', 'decision_confirmed')
    if not calls.complete:
        return hold('decision_call_coverage_unknown')
    count = calls.context_posts if public.status == 'not_observed' else calls.receipt_posts
    if count is None:
        return hold('decision_call_coverage_unknown')
    if count >= 3:
        return hold('decision_retry_exhausted')
    return DecisionPlan('post_context' if public.status == 'not_observed' else 'post_receipt', 'decision_ready')
