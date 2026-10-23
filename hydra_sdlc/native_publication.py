"""Publish an accepted candidate through the existing owned effect engine."""
import asyncio
import copy
from contextlib import contextmanager
import json
import re
from threading import Event

from .coordinator import coordinator_lock, operation_scope
from .github import GitHub
from .native_verification import _candidate, _source
from .operations import OperationDenied
from .project import _provider


_PENDING = frozenset({None, 'publish', 'upsert_pr', 'request_review'})
_CLOSING = re.compile(r'\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)(?:\s*:\s*|\s+)'
    r'(?:(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?#[1-9][0-9]*'
    r'|https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*)', re.I)


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate review state field')
        result[key] = value
    return result


def _review_requests(github, repo, config, observation, head):
    """Request observations are distinct from approval and delivery evidence."""
    comments, commits = observation.get('provider_comments'), observation.get('commits')
    pr = observation.get('pr', {})
    if (type(comments) is not list or type(commits) is not list or type(pr) is not dict
            or type(pr.get('commits')) is not int or pr['commits'] != len(commits) or not commits
            or any(type(row) is not dict or type(row.get('sha')) is not str
                   or re.fullmatch('[0-9a-f]{40}', row['sha']) is None for row in commits)):
        raise RuntimeError('Review observation incomplete')
    if len({row['sha'] for row in commits}) != len(commits):
        raise RuntimeError('Duplicate commit observation')
    provider = config['review_provider']
    markers = ('<!-- hydra-review-request:', '<!-- codex-pull-request-review-summary -->',
               '<!-- codex-review-state:', '<!-- codex-security-review:')
    comments = [row for row in comments if type(row) is dict and (
        type(row.get('user')) is dict and row['user'].get('id') == provider['user_id']
        and row['user'].get('login') == provider['login']
        or type(row.get('body')) is str and any(marker in row['body'] for marker in markers))]
    for row in comments:
        if (type(row) is not dict or type(row.get('body')) is not str
                or type(row.get('user')) is not dict
                or type(row['user'].get('id')) is not int or row['user']['id'] < 1
                or type(row['user'].get('login')) is not str or not row['user']['login']):
            raise RuntimeError('Comment author observation incomplete')
        app = row.get('performed_via_github_app')
        if app is not None and (type(app) is not dict or type(app.get('id')) is not int or app['id'] < 1):
            raise RuntimeError('Comment producer observation incomplete')
    identity = github._identity()
    if (type(identity) is not dict or type(identity.get('id')) is not int or identity['id'] < 1
            or type(identity.get('login')) is not str or not identity['login']):
        raise RuntimeError('Request author observation unavailable')
    observed, refs = set(), []
    for kind in ('code', 'security'):
        marker = f'<!-- hydra-review-request:v1 head={head} kind={kind} -->'
        rows = [row for row in comments if type(row) is dict
            and (row.get('user') or {}).get('id') == identity['id']
            and (row.get('user') or {}).get('login') == identity['login']
            and marker in (row.get('body') or '')]
        if len(rows) > 1:
            raise RuntimeError('Ambiguous owned review request')
        if rows:
            identifier = rows[0].get('id')
            if type(identifier) is not int or identifier < 1:
                raise RuntimeError('Review request identity unavailable')
            observed.add(kind)
            refs.append({'source': 'github', 'kind': 'issue_comment',
                         'id': f'{repo}/comments/{identifier}'})
    if not _provider(config, {**observation, 'provider_comments': comments}, head):
        return {'code', 'security'}, refs
    provider = config['review_provider']
    summaries = [row for row in comments if type(row) is dict
        and (row.get('user') or {}).get('id') == provider['user_id']
        and (row.get('user') or {}).get('login') == provider['login']
        and (row.get('performed_via_github_app') or {}).get('id') == provider['app_id']
        and '<!-- codex-pull-request-review-summary -->' in (row.get('body') or '')]
    if len(summaries) > 1:
        raise RuntimeError('Ambiguous review producer')
    if not summaries:
        return observed, refs
    body = summaries[0]['body']
    legacy = re.findall(r'<!-- codex-security-review:v1 (.*?) -->', body, re.S)
    if legacy:
        if len(legacy) != 1:
            raise RuntimeError('Ambiguous legacy producer binding')
        binding = json.loads(legacy[0], object_pairs_hook=_unique)
        fields = {'blockingSeverityThreshold': str, 'headSha': str, 'mergeGateEnabled': bool,
                  'pullRequestNumber': int, 'repository': str, 'status': str}
        if (type(binding) is not dict or set(binding) != set(fields)
                or any(type(binding[key]) is not kind for key, kind in fields.items())
                or binding['repository'] != config['repository']
                or binding['pullRequestNumber'] != pr.get('number')
                or re.fullmatch('[0-9a-f]{40}', binding['headSha']) is None):
            raise RuntimeError('Legacy producer binding unavailable')
        security = [line for line in body.splitlines() if line.startswith('|') and '**Security Review**' in line]
        cells = security[0].split('|') if len(security) == 1 else []
        marker = re.fullmatch(r'\s*`([0-9a-f]{7,40})`\s*', cells[3]) if len(cells) == 6 else None
        if marker is None or not binding['headSha'].startswith(marker[1]):
            raise RuntimeError('Conflicting legacy producer revision')
    markers = re.findall(r'<!-- codex-review-state:v1 (.*?) -->', body, re.S)
    if markers:
        if len(markers) != 1:
            raise RuntimeError('Ambiguous review state')
        state = json.loads(markers[0], object_pairs_hook=_unique)
        for kind in ('code', 'security'):
            row = state.get(kind + '_review') if type(state) is dict else None
            if (type(row) is not dict or type(row.get('commit_sha')) is not str
                    or re.fullmatch('[0-9a-f]{40}', row['commit_sha']) is None
                    or type(row.get('status')) is not str
                    or row['status'] not in {'queued', 'running', 'completed'}):
                raise RuntimeError('Review state observation unavailable')
            if legacy and kind == 'security' and row['commit_sha'] != binding['headSha']:
                raise RuntimeError('Conflicting producer revisions')
            if row['commit_sha'] == head:
                observed.add(kind)
        return observed, refs
    if not legacy:
        raise RuntimeError('Review source format unavailable')
    # Retain the configured legacy summary's exact-head request observation.
    for kind, name in (('code', 'Code Review'), ('security', 'Security Review')):
        rows = [line for line in body.splitlines() if line.startswith('|') and f'**{name}**' in line]
        if len(rows) > 1:
            raise RuntimeError('Ambiguous review row')
        if not rows:
            continue
        cells = rows[0].split('|')
        match = re.fullmatch(r'\s*`([0-9a-f]{7,40})`\s*', cells[3]) if len(cells) == 6 else None
        if (match and {row['sha'] for row in commits if row['sha'].startswith(match[1])} == {head}
                and re.fullmatch(r'(?:✅ \*\*Completed\*\*|(?:🔄|⏳) \*\*(?:Running|Queued|Pending)\*\*)(?: .*)?',
                                 cells[2].strip())):
            observed.add(kind)
    return observed, refs


class Publication:
    def __init__(self, controller, repo, number, params, repository_id, revision,
                 before_effect, observer, finalize_reply, cancel):
        self.controller, self.runner = controller, controller.runner
        self.repo, self.number, self.params = repo, number, params
        self.pin, self.repository_id, self.revision = params['candidate'], repository_id, revision
        self.before_effect, self.observer, self.finalize_reply, self.cancel = before_effect, observer, finalize_reply, cancel
        self.expected, self.config, self.path, self.receipt = None, None, None, None
        self.attempted = set()
        self.state = {'profile': 'publish_candidate', 'before_progress': self.before_progress,
            'after_progress': self.after_progress, 'before_publication': self.before_publication,
            'before_callback': self.before_callback}
        if not hasattr(self.runner, '_publication_undispatched'):
            self.runner._publication_undispatched = {}
        self.cache = self.runner._publication_undispatched
        self.key = (repo, number, *(self.pin[name] for name in ('attempt_id', 'head', 'contract_revision')))

    def source(self, expected):
        return _source(self.runner, self.repo, self.number, expected, self.observer,
            github=getattr(self, '_publication_reader', None))

    def guard(self):
        if self.cancel.is_set():
            raise OperationDenied('publication_cancelled')
        self.before_effect()

    def before_progress(self):
        self.source(self.expected)
        self.guard()

    def action_key(self, record):
        return tuple(record.get(name) for name in
            ('pending_action', 'head', 'delivery_attempt', 'pending_review_kind'))

    def after_progress(self):
        planned = self.state['record']
        self.expected = copy.deepcopy(self.source(planned)['record'])
        if (self.expected.get('pending_action') in _PENDING - {None}
                and self.action_key(self.expected) not in self.attempted):
            if len(self.cache) >= 128 and self.key not in self.cache:
                self.cache.pop(next(iter(self.cache)))
            self.cache[self.key] = self.runner._record_values(self.expected)
        elif self.expected.get('pending_action') is None:
            self.cache.pop(self.key, None)

    def before_callback(self, effect):
        if effect != 'progress':
            self.attempted.add(self.action_key(self.expected))
            self.cache.pop(self.key, None)

    def candidate(self):
        return _candidate(self.controller, self.repo, self.number, self.pin, self.repository_id,
            pending_actions=_PENDING, workspace_change_reason='candidate_changed')

    @contextmanager
    def _read_scope(self):
        source = self.runner.github
        if not isinstance(source, GitHub):
            # Trusted injected dependencies retain their own existing contract.
            yield source
            return
        reader = source.read_client()
        previous = getattr(self, '_publication_reader', None)
        self._publication_reader = reader
        try:
            with reader.read_budget(seconds=15, requests=32):
                yield reader
        finally:
            self._publication_reader = previous

    def public_payloads(self):
        messages = self.runner.workspace.commit_messages(self.path, self.config['revision'])
        if type(messages) is not list or any(type(message) is not str for message in messages):
            raise RuntimeError('Candidate messages unavailable')
        if any(_CLOSING.search(message) for message in messages):
            raise OperationDenied('premature_issue_closure')
        with self._read_scope() as reader:
            pulls = reader.pulls(self.repo, self.params['branch'])
            if len(pulls) > 1:
                raise OperationDenied('multiple_prs')
            for pr in pulls:
                if not reader.owns_pr(self.repo, self.number, pr):
                    raise OperationDenied('foreign_pr')
                if (type(pr.get('title')) is not str or type(pr.get('body')) is not str
                        or _CLOSING.search(pr['title']) or _CLOSING.search(pr['body'])):
                    raise OperationDenied('premature_issue_closure')

    def reviewed_phase(self, record):
        if (record.get('resume_phase') is not None or record.get('phase') not in
                {'change_review_done', 'published', 'review_wait', 'publishing', 'publishing_pr', 'uncertain'}):
            raise OperationDenied('candidate_review_required')
        if record.get('phase') == 'uncertain' and self.cache.get(self.key) != self.runner._record_values(record):
            raise OperationDenied('publication_unconfirmed')

    def before_publication(self, effect, args, kwargs):
        self.source(self.expected)
        record, _, _, _ = self.candidate()
        self.reviewed_phase(record)
        if (self.repo, self.number, self.pin['head'], self.config['blob_sha']) not in self.runner.verified_heads:
            raise OperationDenied('candidate_review_required')
        self.public_payloads()
        if effect == 'pr':
            if len(args) < 2 or any(type(value) is not str for value in args[-2:]):
                raise RuntimeError('Proposed public payload unavailable')
            if any(_CLOSING.search(value) for value in args[-2:]):
                raise OperationDenied('premature_issue_closure')
        self.source(self.expected)
        self.guard()

    def write(self, **values):
        self.runner._record(self.repo, self.number, self.expected, **values)
        return self.expected

    def check_pr(self, pr, *, github=None):
        reader = self.runner.github if github is None else github
        if (type(pr) is not dict or type(pr.get('number')) is not int or pr['number'] < 1
                or not reader.owns_pr(self.repo, self.number, pr)):
            raise OperationDenied('foreign_pr')
        if pr.get('head', {}).get('sha') != self.pin['head']:
            raise OperationDenied('stale_publication')
        if (type(pr.get('title')) is not str or type(pr.get('body')) is not str
                or _CLOSING.search(pr['title']) or _CLOSING.search(pr['body'])):
            raise OperationDenied('premature_issue_closure')
        if pr.get('state') != 'open' or pr.get('draft') is not False:
            raise OperationDenied('publication_pr_not_open')

    def remember_receipt(self, remote, pr=None, observed=frozenset(), refs=()):
        known = (self.expected.get('published_head') == self.pin['head']
            or self.expected.get('pending_action') == 'publish' and self.expected.get('head') == self.pin['head'])
        if remote == self.pin['head'] and known:
            self.receipt = {'kind': 'publication', 'candidate': dict(self.pin),
                'branch': self.params['branch'], 'observed_remote_head': remote,
                'pr_ref': {'source': 'github', 'kind': 'pull_request',
                           'id': f'{self.repository_id}:{pr["number"]}'} if pr else None,
                'review_request_refs': list(refs), 'progress_ref': self.source(self.expected)['resource'],
                'stage': ('publication_ready' if pr and observed == {'code', 'security'}
                          else 'pr_ready' if pr else 'branch_published')}

    def read_publication(self):
        with self._read_scope() as reader:
            remote = reader.ref(self.repo, self.params['branch'])
            pulls = reader.pulls(self.repo, self.params['branch'])
            if len(pulls) > 1:
                raise OperationDenied('multiple_prs')
            pr, observation, observed = None, None, set()
            refs = []
            if pulls:
                pr = pulls[0]
                self.check_pr(pr, github=reader)
                self.remember_receipt(remote, pr)
                if isinstance(reader, GitHub):
                    observation = reader._publication_observation(self.repo, pr['number'])
                else:
                    method = getattr(reader, 'observe_publication', None)
                    observation = (method if callable(method) else reader.observe)(self.repo, pr['number'])
                if (observation.get('head_sha') != self.pin['head']
                        or observation.get('pr', {}).get('number') != pr['number']
                        or not reader.owns_pr(self.repo, self.number, observation['pr'])):
                    raise RuntimeError('Publication source changed')
                self.check_pr(observation['pr'], github=reader)
                observed, refs = _review_requests(reader, self.repo, self.config, observation, self.pin['head'])
            self.remember_receipt(remote, pr, observed, refs)
            return remote, pr, observation, observed

    def reuse_intent(self):
        if self.cache.get(self.key) != self.runner._record_values(self.expected):
            raise OperationDenied('publication_unconfirmed')
        self.state['reuse_intent'] = self.runner._record_values(self.expected)

    def reconcile_known(self, remote, pr, observed):
        """Acknowledge source-confirmed effects without recreating private proof."""
        if remote != self.pin['head'] or self.receipt is None:
            return
        record, head = self.expected, self.pin['head']
        if (record.get('resume_phase') is not None or record.get('phase') not in
                {'change_review_done', 'published', 'review_wait', 'publishing', 'publishing_pr', 'uncertain'}):
            raise OperationDenied('candidate_review_required')
        pending = record.get('pending_action')
        values = {}
        if pending == 'publish':
            values.update(head=head, published_head=head, checkpoint='remote_committed',
                          phase='published', next_action='pr')
        elif pending == 'upsert_pr' and pr is None:
            return
        elif pending == 'request_review' and (pr is None
                or record.get('pending_review_kind') not in observed):
            # An unrelated observed kind cannot settle or resend this intent.
            return
        if pending is not None:
            values.update(pending_action=None, pending_review_kind=None, wait_reason=None,
                          delivery_action=None, delivery_attempt=None, delivery_head=None)
        if pr is not None:
            if record.get('pr_number') not in {None, pr['number']}:
                raise OperationDenied('stale_publication')
            values.update(pr_number=pr['number'], phase='review_wait', next_action='remote_review',
                          wait_reason=None)
            for kind, field in (('code', 'review_requested_head'),
                                ('security', 'review_requested_security_head')):
                if kind in observed:
                    values[field] = head
                elif record.get(field) == head:
                    # Missing read-back is not proof an earlier request was unsent.
                    raise OperationDenied('publication_unconfirmed')
        if any(record.get(key) != value for key, value in values.items()):
            self.write(**values)
            self.read_publication()

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
                            self.read_publication()
                        except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError):
                            pass
                    return self.finalize_reply('rejected' if exc.reason in
                        {'stale_candidate', 'stale_publication'} else 'unknown' if exc.reason ==
                        'publication_unconfirmed' else 'waiting', exc.reason, receipt=self.receipt)
                except (OSError, RuntimeError, ValueError, KeyError, TypeError, AttributeError):
                    # Reconcile only the exact attempted progress, without resending.
                    planned = self.state.get('record')
                    if planned is not None:
                        try:
                            self.expected = copy.deepcopy(self.source(planned)['record'])
                        except (OSError, RuntimeError, ValueError):
                            pass
                    return self.finalize_reply('unknown', 'publication_unconfirmed', receipt=self.receipt)
        finally:
            self.runner._checkpoint_ceiling.reset(ceiling)
            self.runner._policy_scope.reset(policy)

    def advance(self):
        self.guard()
        try:
            self.expected, self.config = self.controller._bound(self.repo, self.number,
                self.pin['attempt_id'], self.pin['head'], self.pin['contract_revision'])
        except ValueError:
            raise OperationDenied('stale_candidate') from None
        if (self.expected.get('repository_id') != self.repository_id
                or self.config.get('repository_id') != self.repository_id
                or self.config.get('_completion_only') or self.expected.get('native_step')
                or self.expected.get('pending_action') not in _PENDING):
            raise OperationDenied('stale_candidate')
        if self.expected.get('wait_reason') == 'product_decision' or self.expected.get('next_action') == 'operator_decision':
            raise OperationDenied('product_decision')
        self.source(self.expected)
        if self.params['branch'] != self.expected.get('branch'):
            raise OperationDenied('stale_publication')
        if self.params['expected_remote_head'] != self.expected.get('expected_head'):
            raise OperationDenied('stale_publication')
        self.config = {**self.config, 'intake_digest': self.expected['intake_digest']}
        remote, pr, observation, observed = self.read_publication()
        if remote != self.params['expected_remote_head'] and not (
                remote == self.pin['head'] and self.receipt is not None
                and self.params['expected_remote_head'] == self.expected.get('expected_head')):
            raise OperationDenied('stale_publication')
        self.reconcile_known(remote, pr, observed)
        if (self.receipt is not None and self.receipt['stage'] == 'publication_ready'
                and self.expected.get('pending_action') is None
                and self.expected.get('pr_number') == pr['number']):
            return self.finalize_reply('applied', None, receipt=self.receipt)
        record, self.config, self.path, _ = self.candidate()
        self.reviewed_phase(record)
        if (self.repo, self.number, self.pin['head'], self.config['blob_sha']) not in self.runner.verified_heads:
            raise OperationDenied('candidate_review_required')
        self.public_payloads()
        self.source(record)
        if remote != self.pin['head']:
            if record.get('pending_action') == 'publish':
                self.reuse_intent()
            elif record.get('pending_action') is not None:
                raise OperationDenied('publication_unconfirmed')
            wait = self.runner._publish(self.repo, self.number, self.config, self.expected, self.path, self.pin['head'])
            if wait:
                raise OperationDenied(wait['reason'])
            remote, pr, observation, observed = self.read_publication()
        self.reconcile_known(remote, pr, observed)
        if remote != self.pin['head']:
            raise OperationDenied('publication_unconfirmed')
        if pr is None:
            if self.expected.get('pending_action') == 'upsert_pr':
                self.reuse_intent()
            elif self.expected.get('pending_action') is not None:
                raise OperationDenied('publication_unconfirmed')
            _, _, wait = self.runner._upsert_pr(self.repo, self.number, self.config,
                self.expected, self.runner._scoped_spec(self.repo, self.number, self.config, self.expected))
            if wait:
                raise OperationDenied('publication_unconfirmed')
            remote, pr, observation, observed = self.read_publication()
        if pr is None:
            raise OperationDenied('publication_unconfirmed')
        self.reconcile_known(remote, pr, observed)
        if observed != {'code', 'security'}:
            if self.expected.get('pending_action') == 'request_review':
                self.reuse_intent()
            self.runner._request_missing_review(self.repo, self.number, self.config, self.expected, observation)
            remote, pr, observation, observed = self.read_publication()
        self.reconcile_known(remote, pr, observed)
        if observed == {'code', 'security'}:
            return self.finalize_reply('applied', None, receipt=self.receipt)
        return self.finalize_reply('waiting', 'remote_review_request_pending', receipt=self.receipt)


async def execute(controller, repo, number, params, *, repository_id, admission_revision,
                  before_effect, source_observer, finalize_reply):
    cancel = Event()
    command = Publication(controller, repo, number, params, repository_id, admission_revision,
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
        # A sent provider operation drains before ownership can be released.
        worker.result()
        raise
