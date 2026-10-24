"""Deliver one published candidate through the existing guarded effect engine."""
import asyncio
import copy
from contextlib import contextmanager
from threading import Event

from .coordinator import coordinator_lock, operation_scope
from .github import GitHub
from .public_payload import CLOSING_INTENT as _CLOSING
from .native_verification import _candidate, _source
from .operations import OperationDenied
from .project import gate_completed_delivery, gate_delivery


_PENDING = frozenset({None, 'merge', 'close_issue'})


class Delivery:
    def __init__(self, controller, repo, number, params, repository_id, revision,
                 before_effect, observer, finalize_reply, cancel):
        self.controller, self.runner = controller, controller.runner
        self.repo, self.number, self.params = repo, number, params
        self.pin, self.repository_id, self.revision = params['candidate'], repository_id, revision
        self.before_effect, self.observer, self.finalize_reply, self.cancel = before_effect, observer, finalize_reply, cancel
        self.expected, self.config, self.path, self.receipt = None, None, None, None
        self.reader, self.attempted = None, set()
        self.state = {'profile': 'deliver', 'before_progress': self.before_progress,
            'after_progress': self.after_progress, 'before_delivery': self.before_delivery,
            'before_callback': self.before_callback}
        if not hasattr(self.runner, '_delivery_undispatched'):
            self.runner._delivery_undispatched = {}
        self.cache = self.runner._delivery_undispatched
        self.key = (repo, number, params['pr_number'], params['integration_base'],
                    *(self.pin[name] for name in ('attempt_id', 'head', 'contract_revision')))

    def guard(self):
        if self.cancel.is_set():
            raise OperationDenied('delivery_cancelled')
        self.before_effect()

    def source(self, expected):
        if self.reader is not None:
            return _source(self.runner, self.repo, self.number, expected, self.observer, github=self.reader)
        with self.read_scope() as reader:
            return _source(self.runner, self.repo, self.number, expected, self.observer, github=reader)

    def bind(self):
        if self.runner.host_hold_reason:
            raise OperationDenied(self.runner.host_hold_reason)
        try:
            record, config = self.controller._bound(self.repo, self.number,
                self.pin['attempt_id'], self.pin['head'], self.pin['contract_revision'])
        except ValueError:
            raise OperationDenied('stale_candidate') from None
        if (record.get('repository_id') != self.repository_id
                or config.get('repository_id') != self.repository_id or record.get('native_step')
                or record.get('pending_action') not in _PENDING
                or record.get('pr_number') != self.params['pr_number']
                or record.get('branch') != f'hydra/issue-{self.number}'
                or record.get('published_head') != self.pin['head']):
            raise OperationDenied('stale_delivery')
        if record.get('wait_reason') == 'product_decision' or record.get('next_action') == 'operator_decision':
            raise OperationDenied('product_decision')
        self.config = {**config, 'intake_digest': record['intake_digest']}
        return record

    @contextmanager
    def read_scope(self):
        github = self.runner.github
        if not isinstance(github, GitHub):
            yield github
            return
        reader, previous = github.read_client(), self.reader
        self.reader = reader
        try:
            with reader.read_budget(seconds=15, requests=32):
                yield reader
        finally:
            self.reader = previous

    def read_pr(self):
        with self.read_scope() as reader:
            value = reader.observe(self.repo, self.params['pr_number'])
            pr = value.get('pr')
            if (type(pr) is not dict or pr.get('number') != self.params['pr_number']
                    or not reader.owns_pr(self.repo, self.number, pr)
                    or value.get('head_sha') != self.pin['head']
                    or pr.get('head', {}).get('sha') != self.pin['head']):
                raise OperationDenied('stale_delivery')
            if not pr.get('merged') and (type(pr.get('title')) is not str or type(pr.get('body')) is not str
                    or _CLOSING.search(pr['title']) or _CLOSING.search(pr['body'])):
                raise OperationDenied('premature_issue_closure')
            return value

    def completed_gate(self, value):
        return gate_completed_delivery(self.config, value, self.pin['head'], self.runner._paths(value),
            expected_base=self.expected.get('expected_base'), checkpoint=self.expected.get('checkpoint'))

    def before_progress(self):
        self.source(self.expected)
        self.bind()
        reason = self.runner._latest(self.repo, self.number, self.config)
        if reason and not (reason == 'issue_closed' and not self.completed_gate(self.read_pr())):
            raise OperationDenied(reason)
        self.guard()

    def action_key(self, record):
        return tuple(record.get(name) for name in
                     ('pending_action', 'head', 'expected_base', 'delivery_attempt'))

    def after_progress(self):
        previous = self.expected
        self.expected = copy.deepcopy(self.source(self.state['record'])['record'])
        if (previous.get('pending_action') is None
                and self.expected.get('pending_action') in _PENDING - {None}
                and self.action_key(self.expected) not in self.attempted):
            if len(self.cache) >= 128 and self.key not in self.cache:
                self.cache.pop(next(iter(self.cache)))
            self.cache[self.key] = self.runner._record_values(self.expected)
        elif self.expected.get('pending_action') is None:
            self.cache.pop(self.key, None)
        elif self.cache.get(self.key) != self.runner._record_values(self.expected):
            self.cache.pop(self.key, None)

    def before_callback(self, effect):
        if effect != 'progress':
            self.attempted.add(self.action_key(self.expected))
            self.cache.pop(self.key, None)

    def check_new_merge(self, value):
        if (self.config.get('_completion_only')
                or value.get('base_sha') != self.params['integration_base']
                or value['pr'].get('base', {}).get('sha') != self.params['integration_base']
                or self.config['revision'] != self.params['integration_base']):
            raise OperationDenied('stale_delivery')
        rules = value.get('rules')
        if type(rules) is not list or any(type(rule) is not dict for rule in rules):
            raise OperationDenied('delivery_protection_unknown')
        if any(rule.get('type') == 'merge_queue' for rule in rules):
            raise OperationDenied('merge_queue_unsupported')
        if gate_delivery(self.config, value, self.pin['head'], self.runner._paths(value)):
            raise OperationDenied('delivery_facts_changed')

    def before_delivery(self, effect, args, kwargs):
        self.source(self.expected)
        self.bind()
        value = self.read_pr()
        if effect == 'merge':
            self.check_new_merge(value)
            record, config, path, _ = _candidate(self.controller, self.repo, self.number,
                self.pin, self.repository_id, pending_actions=_PENDING,
                workspace_change_reason='candidate_changed')
            messages = self.runner.workspace.commit_messages(path, config['revision'])
            if type(messages) is not list or any(type(message) is not str for message in messages):
                raise RuntimeError('Candidate messages unavailable')
            if any(_CLOSING.search(message) for message in messages):
                raise OperationDenied('premature_issue_closure')
        elif effect == 'close':
            if self.completed_gate(value):
                raise OperationDenied('completion_evidence_missing')
            status = self.runner._observe_post_merge(self.repo, self.config, value['pr']['merge_commit_sha'])
            if status != 'success':
                raise OperationDenied('post_merge_evidence_changed')
        else:
            raise OperationDenied('effect_not_allowed')
        reason = self.runner._latest(self.repo, self.number, self.config)
        if reason:
            raise OperationDenied(reason)
        self.source(self.expected)
        self.guard()

    def remember_receipt(self, value):
        if (self.expected.get('expected_base') != self.params['integration_base']
                or self.completed_gate(value)):
            return
        with self.read_scope() as reader:
            issue = reader.issue(self.repo, self.number)
            closed = True if issue.get('state') == 'closed' else False if issue.get('state') == 'open' else None
            resource = self.source(self.expected)['resource']
        self.receipt = {'kind': 'delivery', 'candidate': dict(self.pin),
            'pr_ref': {'source': 'github', 'kind': 'pull_request',
                       'id': f'{self.repository_id}:{self.params["pr_number"]}'},
            'integration_base': self.params['integration_base'],
            'merge_commit': value['pr']['merge_commit_sha'],
            'post_merge': self.state.get('post_merge') or 'unknown',
            'issue_closed': closed, 'progress_ref': resource}

    def reuse_intent(self):
        if self.cache.get(self.key) != self.runner._record_values(self.expected):
            raise OperationDenied('delivery_unconfirmed')
        self.state['reuse_intent'] = self.runner._record_values(self.expected)

    def advance(self):
        self.guard()
        self.expected = self.bind()
        self.source(self.expected)
        value = self.read_pr()
        pending = self.expected.get('pending_action')
        if value['pr'].get('merged'):
            if self.expected.get('expected_base') != self.params['integration_base']:
                raise OperationDenied('stale_delivery')
            known_unsent = self.cache.get(self.key) == self.runner._record_values(self.expected)
            if pending == 'close_issue' and known_unsent:
                self.reuse_intent()
            result = self.runner._complete_delivery(self.repo, self.number, self.config,
                self.expected, value, closing_recovery=pending == 'close_issue' and not known_unsent,
                retire=False)
            self.remember_receipt(value)
            if result.get('action') == 'completed' and self.receipt and self.receipt['issue_closed']:
                return self.finalize_reply('applied', None, receipt=self.receipt)
            return self.finalize_reply('waiting', result.get('reason') or 'delivery_unconfirmed', receipt=self.receipt)
        if pending == 'merge':
            self.reuse_intent()
        elif pending is not None or self.expected.get('phase') not in {'published', 'review_wait'}:
            raise OperationDenied('stale_delivery')
        self.check_new_merge(value)
        self.source(self.expected)
        result = self.runner._merge(self.repo, self.number, self.config, self.expected,
            self.params['pr_number'], self.pin['head'], self.runner._paths(value))
        if result.get('action') != 'continue':
            return self.finalize_reply('waiting', result.get('reason') or 'delivery_unconfirmed')
        # One merge and one bounded completion pass; no broad runner continuation.
        value = self.read_pr()
        result = self.runner._complete_delivery(self.repo, self.number, self.config,
            self.expected, value, retire=False)
        self.remember_receipt(value)
        if result.get('action') == 'completed' and self.receipt and self.receipt['issue_closed']:
            return self.finalize_reply('applied', None, receipt=self.receipt)
        return self.finalize_reply('waiting', result.get('reason') or 'delivery_unconfirmed', receipt=self.receipt)

    def run(self):
        policy = self.runner._policy_scope.set(None)
        ceiling = self.runner._checkpoint_ceiling.set((self.repo, self.revision, self.guard, self.state))
        try:
            with operation_scope(self.runner.operations, self.repo, expected_revision=self.revision), \
                 coordinator_lock(self.controller.lock_path):
                try:
                    return self.advance()
                except OperationDenied as exc:
                    if self.expected is not None:
                        try:
                            self.remember_receipt(self.read_pr())
                        except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError):
                            pass
                    outcome = ('rejected' if exc.reason in {'stale_candidate', 'stale_delivery'} else
                               'unknown' if exc.reason == 'delivery_unconfirmed' else 'waiting')
                    return self.finalize_reply(outcome, exc.reason, receipt=self.receipt)
                except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError):
                    planned = self.state.get('record')
                    if planned is not None:
                        try:
                            # This owner has not entered the next provider
                            # writer. Only an exact confirmed new intent can
                            # retain that process-local undispatched witness.
                            self.after_progress()
                        except (OSError, RuntimeError, ValueError):
                            pass
                    return self.finalize_reply('unknown', 'delivery_unconfirmed', receipt=self.receipt)
        finally:
            self.runner._checkpoint_ceiling.reset(ceiling)
            self.runner._policy_scope.reset(policy)


async def execute(controller, repo, number, params, *, repository_id, admission_revision,
                  before_effect, source_observer, finalize_reply):
    cancel = Event()
    command = Delivery(controller, repo, number, params, repository_id, admission_revision,
        before_effect, source_observer, finalize_reply, cancel)
    worker = asyncio.create_task(asyncio.to_thread(command.run))
    try:
        return await asyncio.shield(worker)
    except asyncio.CancelledError:
        cancel.set()
        while not worker.done():
            try:
                await asyncio.shield(worker)
            except asyncio.CancelledError:
                continue
        worker.result()
        raise
