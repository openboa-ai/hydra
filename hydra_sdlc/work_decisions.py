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
        self.technical_guard = None
        self.delegated_context = None

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
        from .delegated_decisions import _has_delegated_read_transport
        from .public_delegated_decisions import _progress_context_link
        unsupported_transport = not _has_delegated_read_transport(reader)
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
            original = reader.decision_progress_source(self.repository, self.number) if record else None
            if original is not None and original['record'] != record:
                raise OperationDenied('decision_source_changed')
            context = original['decision_context'] if original else None
            linked = (context['source_attempt'] if context is not None
                      and context['resume_attempt'] == record.get('attempt_id') else None)
            attempts = {value for value in (linked, record.get('attempt_id') if record else None) if value}
            found = original is not None and original['native_root'] is not None
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
                        only_progress_link = (unsupported_transport
                            and body.count('<!-- hydra-decision-') == 1
                            and _progress_context_link(body, body.find('<!-- hydra-decision-')))
                        if (unsupported_transport and not only_progress_link or any(
                                body.startswith('hydra: decision ' + attempt + ' ') for attempt in attempts)):
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
        from .delegated_decisions import observe_work
        delegated = observe_work(self.runner, self.repository, self.number, record, timeout=remaining())
        remaining()
        if delegated is not None:
            return delegated, record
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
            from .native_replan import reconcile_work_effects
            reconcile_work_effects(self.runner, self.provider, self.repository, self.number, record,
                timeout=remaining())
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
            if type(observed) is tuple:
                from .delegated_decisions import reconcile
                if self.mode not in {None, 'delegated'}:
                    raise OperationDenied('decision_source_changed')
                context = observed[0]
                if self.delegated_context is not None and context != self.delegated_context:
                    raise OperationDenied('decision_source_changed')
                self.mode, self.delegated_context = 'delegated', context
                source = reconcile(self, observed, allow_resume=allow_resume)
                self.consumed = True
                continuation = self.runner._continuation_scope.get()
                if continuation is not None:
                    # Retain the actual validated consumer for the final reply
                    # guard, including a continuation that needs no new write.
                    continuation.frame = self
                return source['record']
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
        record = self.reconcile()
        if self.technical_guard is not None:
            self.technical_guard()
        return record

    def check_readonly(self):
        """Validate a captured consumed decision in an isolated preflight read.

        This is not ownership evidence. The dispatching parent must retain its
        own coordinator and admission guards; the read thread cannot retire or
        recreate a permit from its deliberately empty Context.
        """
        if self.delegated_context is None:
            return self.check()
        from .delegated_decisions import _consumed
        observed, record = self._work()
        if (not self.consumed or self.mode != 'delegated' or type(observed) is not tuple
                or observed[0] != self.delegated_context or not _consumed(observed[1], observed[0])):
            raise OperationDenied('decision_source_changed')
        return record

    def replan(self, record, values):
        if self.delegated_context is not None:
            raise OperationDenied('delegated_replan_unsupported')
        from .native_replan import technical_replan
        return technical_replan(self, record, values)

    def public_context(self):
        if self.consumed and self.delegated_context is not None:
            return self.delegated_context.body.decode('utf-8')
        if not self.consumed or self.coordinator is None:
            return None
        return self.coordinator.selection.context.body.decode('utf-8')
