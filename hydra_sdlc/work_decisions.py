"""Internal work selection boundary. Constructing facts does not qualify a source."""
from dataclasses import dataclass
from contextlib import contextmanager
import copy
from time import monotonic

from .decision_coordinator import DecisionCoordinator, DecisionSnapshot
from .decision_protocol import validate_selection
from .operations import OperationDenied
from .public_decisions import context_basis, parse_context, parse_receipt


@dataclass(frozen=True, repr=False)
class WorkDecisionObservation:
    """A qualified adapter's explicit result; unavailable never means absence."""
    status: str
    snapshot: DecisionSnapshot | None = None
    complete: bool = False


class WorkDecisionGuard:
    """One operation's pinned original selection, never a persisted journal.

    The installed adapter alone maps original work/question/answer/adoption facts
    and physical call coverage. No default source, provider fields or grants are
    supplied here. Legacy callers cannot consume a native public claim.
    """
    def __init__(self, runner, repository, number):
        self.runner, self.repository, self.number = runner, repository, number
        self.provider = getattr(runner, 'decision_source', None)
        self.coordinator, self.mode, self.consumed = None, None, False

    def _current(self, *, timeout=15):
        reader = self.runner.github.read_client()
        with reader.read_budget(seconds=timeout, requests=64):
            return reader.progress(self.repository, self.number)

    def _native_claim(self, record, *, timeout=15):
        reader = self.runner.github.read_client()
        identity = getattr(reader, '_identity', None)
        # Legacy adapters without native authentication cannot supply native
        # evidence. Their existing explicit human-resolution path is separate.
        if not callable(identity):
            return False
        with reader.read_budget(seconds=timeout, requests=64):
            actor = identity()
            if (type(actor) is not dict or type(actor.get('id')) is not int or actor['id'] < 1
                    or type(actor.get('login')) is not str or not actor['login']):
                raise OperationDenied('decision_source_unavailable')
            repository = reader.repository(self.repository)
            if (type(repository) is not dict or type(repository.get('id')) is not int
                    or repository['id'] < 1 or type(repository.get('full_name')) is not str
                    or repository['full_name'].casefold() != self.repository.casefold()):
                raise OperationDenied('decision_source_unavailable')
            linked = (reader.decision_context_attempt(self.repository, self.number, record.get('attempt_id'))
                      if record else None)
            attempts = {value for value in (linked, record.get('attempt_id') if record else None) if value}
            found = False
            for row in reader.comments(self.repository, self.number):
                if type(row) is not dict:
                    raise OperationDenied('decision_source_unavailable')
                author, body = row.get('user') or {}, row.get('body')
                if type(author) is not dict or type(body) is not str:
                    raise OperationDenied('decision_source_unavailable')
                if '<!-- hydra-decision-' not in body:
                    continue
                if type(author.get('id')) is not int or type(author.get('login')) is not str:
                    raise OperationDenied('decision_source_unavailable')
                if author['id'] != actor['id'] or author['login'] != actor['login']:
                    continue
                try:
                    context = parse_context(body)
                    basis = context_basis(context)
                except ValueError:
                    try:
                        key, _ = parse_receipt(body)
                    except ValueError:
                        if any(body.startswith('hydra: decision ' + attempt + ' ') for attempt in attempts):
                            found = True
                    else:
                        if (key[0] == repository['id'] and key[1] == self.number
                                and (record is None or key[2] in attempts)):
                            found = True
                    continue
                if (context.key[0] == repository['id'] and context.key[1] == self.number and (record is None
                        or context.key[0] == record.get('repository_id') and
                        (context.key[2] in attempts or basis['resume_attempt'] in attempts))):
                    found = True
            fresh = identity()
            if (type(fresh) is not dict or type(fresh.get('id')) is not int
                    or (fresh.get('id'), fresh.get('login')) != (actor['id'], actor['login'])):
                raise OperationDenied('decision_source_unavailable')
            return found

    def _work(self, *, timeout=15):
        deadline = monotonic() + timeout
        def remaining():
            value = deadline - monotonic()
            if value <= 0:
                raise OperationDenied('decision_source_unavailable')
            return value
        if getattr(self.runner, 'decision_source', None) is not self.provider:
            raise OperationDenied('decision_source_changed')
        record = self._current(timeout=remaining())
        if self.provider is None:
            if self._native_claim(record, timeout=remaining()):
                raise OperationDenied('decision_source_unsupported')
            remaining()
            return WorkDecisionObservation('none', complete=True), record
        read = getattr(self.provider, 'read_work', None)
        if not callable(read):
            raise OperationDenied('decision_source_unsupported')
        try:
            observed = read(self.repository, self.number, copy.deepcopy(record), timeout=remaining())
        except Exception:
            raise OperationDenied('decision_source_unavailable') from None
        remaining()
        if getattr(self.runner, 'decision_source', None) is not self.provider:
            raise OperationDenied('decision_source_changed')
        if (type(observed) is not WorkDecisionObservation or type(observed.complete) is not bool
                or type(observed.status) is not str):
            raise OperationDenied('decision_source_unavailable')
        if observed.status == 'unsupported':
            raise OperationDenied('decision_source_unsupported')
        if observed.status not in {'selected', 'none'} or not observed.complete:
            raise OperationDenied('decision_source_unavailable')
        if observed.status == 'none':
            if observed.snapshot is not None or self._native_claim(record, timeout=remaining()):
                raise OperationDenied('decision_source_changed')
        else:
            if type(observed.snapshot) is not DecisionSnapshot:
                raise OperationDenied('decision_source_unavailable')
            validate_selection(observed.snapshot.selection)
            if (not record or record.get('host_alias') != self.runner.host
                    or record.get('execution_mode') != 'native'
                    or record.get('branch') != 'hydra/issue-' + str(self.number)):
                raise OperationDenied('decision_binding_mismatch')
        remaining()
        return observed, record

    def _selection(self, *, timeout):
        observed, _ = self._work(timeout=timeout)
        if observed.status != 'selected':
            raise OperationDenied('decision_source_changed')
        return observed.snapshot

    def _prepare_resume(self, kind):
        if kind != 'resume':
            raise OperationDenied('effect_not_allowed')
        bound = self.runner._policy_scope.get()
        if bound is None or bound[0] != self.repository.casefold():
            raise OperationDenied('project_policy_unbound')
        record = self._current()
        if record is None:
            raise OperationDenied('decision_checkpoint_missing')
        config = {**bound[1], 'intake_digest': record.get('intake_digest')}
        reader = self.runner.github.read_client()
        with reader.read_budget(seconds=15, requests=64):
            reason = self.runner._latest(self.repository, self.number, config, github=reader)
        if reason:
            raise OperationDenied(reason)

    @contextmanager
    def _resume_guard(self, kind):
        if kind != 'resume' or getattr(self.runner, 'decision_source', None) is not self.provider:
            raise OperationDenied('decision_source_changed')
        # This is the one initial resume write. It precedes the ordinary native
        # consumed-decision guard; recursively requiring consumption here would
        # prevent every valid decision from ever progressing.
        from .runner import Runner
        continuation = self.runner._continuation_scope.get()
        guard = (continuation.guard(self.repository) if continuation is not None
                 else Runner._guard(self.runner, self.repository))
        with guard:
            yield

    def reconcile(self, *, allow_resume=False, record=None):
        try:
            observed, current = self._work()
            mode = observed.status
            if self.mode is not None and mode != self.mode:
                raise OperationDenied('decision_source_changed')
            self.mode = mode
            if mode == 'none':
                return current if current is not None else record
            if self.coordinator is None:
                selection = observed.snapshot.selection
                self.coordinator = DecisionCoordinator(self.runner.github, self.repository, self.number,
                    read_source=self._selection, effect_guard=self._resume_guard,
                    prepare_effect=self._prepare_resume, expected_key=selection.context.key,
                    expected_proposal=selection.proposal.source_check())
            result = self.coordinator.resume() if allow_resume else self.coordinator.inspect_resume()
            if result.outcome != 'applied':
                raise OperationDenied(result.reason)
            continuation = self.runner._continuation_scope.get()
            if continuation is not None and allow_resume:
                continuation.recorded(result.progress_source['record'])
            self.consumed = True
            return result.progress_source['record']
        except OperationDenied:
            raise
        except (OSError, RuntimeError, ValueError, TypeError, KeyError):
            raise OperationDenied('decision_source_unavailable') from None

    def check(self):
        return self.reconcile()

    def public_context(self):
        if not self.consumed or self.coordinator is None:
            return None
        return self.coordinator.selection.context.body.decode('utf-8')
