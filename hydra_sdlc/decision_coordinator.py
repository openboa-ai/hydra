"""P06 original-source coordination; no installed source or grant is supplied."""
import copy
from dataclasses import dataclass, field, replace
import time

from .decision_protocol import (DecisionCallCoverage, DecisionSelection,
    InvalidDecisionFacts, _calls, decision_plan, validate_selection)
from .github import GitHubError, _number, _repo
from .operations import OperationDenied
from . import projection as p
from .public_decisions import (InvalidPublicDecision, context_basis, parse_context,
    read_public_decision, receipt_body)


@dataclass(frozen=True, repr=False)
class DecisionSnapshot:
    """Qualified internal source facts, not provider fields or caller JSON."""
    selection: DecisionSelection
    calls: DecisionCallCoverage
    known_context_id: int | None = None
    known_receipt_id: int | None = None
    predecessor_calls: DecisionCallCoverage | None = None
    predecessor_context_id: int | None = None
    predecessor_receipt_id: int | None = None


@dataclass(frozen=True, repr=False)
class DecisionEffectResult:
    outcome: str
    reason: str
    receipt: dict | None = field(default=None, repr=False)
    progress_source: dict | None = field(default=None, repr=False)
    effect_refs: tuple[dict, ...] = field(default=(), repr=False)


class DecisionCoordinator:
    """One server-bound decision. Source qualification remains an external gate.

    read_source(timeout=...) must be a bounded qualified original-source read.
    effect_guard(kind) is the owning controller's current policy/authority and
    shared admission lease. Neither callback comes from the command payload.
    """
    def __init__(self, github, repository, issue_number, *, read_source, effect_guard,
                 expected_key, expected_proposal, cancel=None, prepare_effect=None):
        self.github, self.repository, self.issue_number = github, repository, issue_number
        self.read_source, self.effect_guard = read_source, effect_guard
        self.expected_key, self.expected_proposal, self.cancel = expected_key, copy.deepcopy(expected_proposal), cancel
        self.prepare_effect = prepare_effect
        self.selection, self.initial_counts = None, None
        self.local = dict.fromkeys(('context_posts', 'receipt_posts', 'resume_writes'), 0)
        self.known_context_id = self.known_receipt_id = None
        self.confirmed_refs = {}

    def _remaining(self):
        if self.cancel is not None and self.cancel.is_set():
            raise OperationDenied('decision_cancelled')
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise OperationDenied('decision_deadline_exhausted')
        return remaining

    def _snapshot(self):
        timeout = min(15, self._remaining())
        try:
            value = self.read_source(timeout=timeout)
        except Exception:
            raise OperationDenied('decision_source_unavailable') from None
        self._remaining()
        if type(value) is not DecisionSnapshot:
            raise OperationDenied('decision_source_unavailable')
        context, _ = validate_selection(value.selection)
        _calls(value.calls)
        selected = replace(value.selection, context=context,
            evidence=tuple(sorted(value.selection.evidence, key=lambda item: item.role)),
            predecessor=None if value.selection.predecessor is None else parse_context(value.selection.predecessor.body))
        if context.key != self.expected_key or selected.proposal.source_check() != self.expected_proposal:
            raise OperationDenied('stale_decision')
        if self.selection is None:
            self.selection, self.initial_counts = selected, value.calls
        elif selected != self.selection:
            raise OperationDenied('decision_source_changed')
        counts = {}
        for name in self.local:
            initial, current = getattr(self.initial_counts, name), getattr(value.calls, name)
            if initial is not None and current is not None and current < initial:
                raise OperationDenied('decision_call_coverage_unknown')
            counts[name] = (None if current is None else
                max(current, (initial or 0) + self.local[name]))
        calls = replace(value.calls, **counts)
        _calls(calls)
        return replace(value, selection=selected, calls=calls)

    def _public(self, snapshot):
        known_context = self.known_context_id or snapshot.known_context_id
        known_receipt = self.known_receipt_id or snapshot.known_receipt_id
        public = read_public_decision(self.client, self.repository, self.issue_number,
            snapshot.selection.context, known_context_id=known_context, known_receipt_id=known_receipt)
        # A later source result may contain another previously observed physical
        # duplicate. Check that original ref too; it is not replaced by a new ID.
        if ((snapshot.known_context_id is not None and snapshot.known_context_id != known_context)
                or (snapshot.known_receipt_id is not None and snapshot.known_receipt_id != known_receipt)):
            extra = read_public_decision(self.client, self.repository, self.issue_number,
                snapshot.selection.context, known_context_id=snapshot.known_context_id,
                known_receipt_id=snapshot.known_receipt_id)
            if extra.status in {'unknown', 'conflict'}:
                public = extra
        if self.known_context_id is None:
            self.known_context_id = public.context_id
        if self.known_receipt_id is None:
            self.known_receipt_id = public.receipt_id
        if public.status in {'context', 'pair'}:
            for role, identifier in (('context', public.context_id), ('receipt', public.receipt_id)):
                if identifier is not None:
                    self.confirmed_refs[role] = {'source': 'github', 'kind': 'issue_comment',
                        'id': self.repository + '/comments/' + str(identifier)}
        return public

    def _observe(self, *, resume=False):
        snapshot = self._snapshot()
        source = self.client.progress_source(self.repository, self.issue_number)
        if source is None:
            raise OperationDenied('decision_checkpoint_missing')
        public = self._public(snapshot)
        predecessor = None
        if snapshot.selection.predecessor is not None:
            predecessor = read_public_decision(self.client, self.repository, self.issue_number,
                snapshot.selection.predecessor, known_context_id=snapshot.predecessor_context_id,
                known_receipt_id=snapshot.predecessor_receipt_id)
        linked = self.client.decision_context_attempt(self.repository, self.issue_number,
            source['record'].get('attempt_id'))
        plan = decision_plan(snapshot.selection, snapshot.calls, source['record'], public,
            resume=resume, linked_source_attempt=linked, predecessor_public=predecessor,
            predecessor_calls=snapshot.predecessor_calls)
        self._remaining()
        return snapshot, source, public, plan

    def _decision_receipt(self, context, public):
        def ref(identifier):
            return {'source': 'github', 'kind': 'issue_comment',
                    'id': self.repository + '/comments/' + str(identifier)}
        basis = context_basis(context)
        return {'kind': 'decision', 'source_attempt': context.key[2], 'round': context.key[3],
            'intent_ref': ref(public.context_id), 'context_ref': ref(public.context_id),
            'resolved_ref': ref(public.receipt_id), 'resume_attempt': basis['resume_attempt']}

    @staticmethod
    def _resume_receipt(source, *, reused=False):
        record = source['record']
        return {'kind': 'continuation', 'progress_ref': copy.deepcopy(source['resource']),
            'attempt_id': record['attempt_id'], 'head': record['head'],
            'contract_revision': record['contract_revision'],
            'boundary': 'existing_result_reconciled' if reused else 'progress_recorded'}

    def _apply(self):
        attempted = set()
        for _ in range(3):
            snapshot, source, public, plan = self._observe()
            if plan.action == 'hold':
                return DecisionEffectResult('waiting', plan.reason, progress_source=source)
            if plan.action == 'publish_complete':
                return DecisionEffectResult('applied', plan.reason,
                    self._decision_receipt(snapshot.selection.context, public), source)
            if plan.action not in {'post_context', 'post_receipt'}:
                return DecisionEffectResult('unknown', 'decision_post_unknown', progress_source=source)
            # Reconcile all inputs at the write boundary. These reads stay
            # outside the shared admission lease and do not create remote CAS.
            if self.prepare_effect is not None:
                self.prepare_effect('context' if plan.action == 'post_context' else 'receipt')
                self._remaining()
            snapshot, source, public, plan = self._observe()
            if plan.action == 'hold':
                return DecisionEffectResult('waiting', plan.reason, progress_source=source)
            if plan.action == 'publish_complete':
                return DecisionEffectResult('applied', plan.reason,
                    self._decision_receipt(snapshot.selection.context, public), source)
            kind = 'context' if plan.action == 'post_context' else 'receipt'
            if plan.action not in {'post_context', 'post_receipt'} or kind in attempted:
                return DecisionEffectResult('unknown', 'decision_post_unknown', progress_source=source)
            body = snapshot.selection.context.body if kind == 'context' else receipt_body(snapshot.selection.context)
            with self.effect_guard(kind):
                self._remaining()
                attempted.add(kind)
                self.local['context_posts' if kind == 'context' else 'receipt_posts'] += 1
                try:
                    self.client.api('POST', f'/repos/{self.repository}/issues/{self.issue_number}/comments',
                                    {'body': body.decode('utf-8')})
                except GitHubError:
                    pass  # Reconcile the original effect; never resend in this call.
            # Always reconcile the original bytes before reading a potentially
            # changed selection. Pause/cancellation still permits read-back.
            confirmed = self._public(snapshot)
            if (kind == 'context' and confirmed.status not in {'context', 'pair'}
                    or kind == 'receipt' and confirmed.status != 'pair'):
                return DecisionEffectResult('unknown', 'decision_post_unknown', progress_source=source)
        return DecisionEffectResult('unknown', 'decision_post_unknown')

    def _resume(self):
        snapshot, source, public, plan = self._observe(resume=True)
        if plan.action == 'reuse_resume':
            return DecisionEffectResult('applied', plan.reason, self._resume_receipt(source, reused=True), source)
        if plan.action != 'record_resume':
            return DecisionEffectResult('waiting', plan.reason, progress_source=source)
        if self.prepare_effect is not None:
            self.prepare_effect('resume')
            self._remaining()
        snapshot, source, public, plan = self._observe(resume=True)
        if plan.action == 'reuse_resume':
            return DecisionEffectResult('applied', plan.reason, self._resume_receipt(source, reused=True), source)
        if plan.action != 'record_resume':
            return DecisionEffectResult('waiting', plan.reason, progress_source=source)
        with self.effect_guard('resume'):
            self._remaining()
            self.local['resume_writes'] += 1
            try:
                self.client.record_checkpoint(self.repository, self.issue_number, plan.resume_record)
            except GitHubError:
                pass
        # A mutable PATCH is attempted once. An old or partial read-back cannot
        # authorize another PATCH, a new UUID, or an assignment.
        observed = self.client.progress_source(self.repository, self.issue_number)
        if observed is not None:
            values = {name: value for name, value in observed['record'].items()
                      if name not in {'repository_id', 'issue_number', 'version'}}
            linked = self.client.decision_context_attempt(self.repository, self.issue_number,
                                                        observed['record'].get('attempt_id'))
            if values == plan.resume_record and linked == snapshot.selection.context.key[2]:
                return DecisionEffectResult('applied', 'decision_reconciled',
                    self._resume_receipt(observed), observed)
        return DecisionEffectResult('unknown', 'decision_resume_unknown', progress_source=observed)

    def _run(self, callback):
        self.confirmed_refs = {}
        try:
            _repo(self.repository)
            _number(self.issue_number)
            if (type(self.expected_key) is not tuple or len(self.expected_key) != 4
                    or not callable(self.read_source) or not callable(self.effect_guard)):
                raise OperationDenied('decision_source_unavailable')
            self.deadline = time.monotonic() + 90
            self.client = self.github.read_client()
            with self.client.read_budget(seconds=90, requests=128):
                result = callback()
        except OperationDenied as exc:
            try:
                p.code(exc.reason)
                reason = exc.reason
            except ValueError:
                reason = 'decision_unconfirmed'
            result = DecisionEffectResult('waiting', reason)
        except (GitHubError, InvalidDecisionFacts, InvalidPublicDecision, ValueError, TypeError, OSError):
            result = DecisionEffectResult('unknown', 'decision_unconfirmed')
        return replace(result, effect_refs=tuple(copy.deepcopy(value) for value in self.confirmed_refs.values()))

    def apply(self):
        return self._run(self._apply)

    def resume(self):
        return self._run(self._resume)

    def inspect_resume(self):
        """Revalidate an already consumed pair without dispatching any effect."""
        def inspect():
            snapshot, source, public, plan = self._observe(resume=True)
            if plan.action == 'reuse_resume':
                return DecisionEffectResult('applied', plan.reason,
                    self._resume_receipt(source, reused=True), source)
            return DecisionEffectResult('waiting', 'decision_not_consumed'
                if plan.action == 'record_resume' else plan.reason, progress_source=source)
        return self._run(inspect)
