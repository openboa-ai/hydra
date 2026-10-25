"""Ephemeral, authenticated CI investigation context for existing status rows.

This read-only handoff is neither delivery acceptance nor repair authority.
The caller's GitHub client, admission state and durable progress stay untouched.
"""
from datetime import datetime, timezone
import json
import re
import uuid
from urllib.parse import urlencode

from .github import GitHubError, _repo, _sha
from .github_producer_delivery import _bounded, _comment, _policy
from .project import (_bound_runs, _post_merge_binding_state, _run_order,
                      gate_squash_result, load_project, post_merge_check_state,
                      squash_recovery_checkpoint)
from .work_records import _canonical, _integer


MAX_CONTEXTS = 4
MAX_REFS = 32
MAX_CONTEXT_BYTES = 32768
# Leave bounded framing room for the two axes' coverage, times and through-scopes.
_FRAMING_RESERVE = 2048
MAX_HISTORY_RUNS = 8
MAX_HISTORY_ATTEMPTS = 8
_STATES = {'failed', 'pending', 'success', 'unknown'}
_SOURCE_ERRORS = (RuntimeError, OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError)


class _LocalChanged(Exception):
    pass


class _SharedChanged(Exception):
    pass


def _require(value):
    if not value:
        raise GitHubError('Post-merge source unavailable')


def _now():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def _size(value):
    # Bound normalized UTF-8 and a conservative JSON wire representation.
    return max(len(_canonical(value).encode()), len(json.dumps(value).encode()))


def _coverage(scope, state='unavailable', count=0, total=None, reason=None):
    return {'state': state, 'scope': scope, 'returned_count': count,
            'total_count': total, 'next_cursor': None, 'reason': reason}


def _empty(*, changed=False, reason=None):
    code = 'post_merge_source_changed' if changed else 'post_merge_source_unavailable'
    return {'schema_version': 1, 'state': 'changed' if changed else 'unknown',
        'reason': code, 'source': None,
        'current': {'state': 'unknown', 'checks': [],
            'coverage': _coverage('required_check_bindings', reason=reason or code), 'observed_at': None},
        'history': {'failed_checks': [], 'through': [],
            'coverage': _coverage('historical_failed_checks', reason=reason or code), 'observed_at': None},
        'observed_at': _now()}


class _Binding:
    """One owned client's sticky credential/account/disclosure observation guard."""
    def __init__(self, client):
        self.client = client
        self.fingerprint = None
        self.identity = None
        self.repositories = {}
        self.changed = False
        self.original_api = client.api
        self.original_hook = client._credential_selected
        self.original_pages = client._pages

    def invalidate(self):
        self.changed = True
        raise _SharedChanged()

    def credential(self, fingerprint):
        if self.changed:
            self.invalidate()
        self.original_hook(fingerprint)
        _require(type(fingerprint) is bytes and bool(fingerprint))
        if self.fingerprint is None:
            self.fingerprint = fingerprint
        elif self.fingerprint != fingerprint:
            self.invalidate()

    def repository(self, value, key, *, partial=False):
        _require(type(value) is dict)
        old = self.repositories.get(key)
        if partial and (old is None or not _integer(value.get('id')) or value['id'] != old.get('id')):
            # Foreign run metadata is not a disclosure observation of this
            # selected repository. Its run/check predicates still reject it.
            return
        if not partial:
            _require(_integer(value.get('id')))
        fields = ('id', 'full_name', 'private', 'visibility', 'permissions', 'archived', 'disabled')
        basis = {name: value[name] for name in fields if name in value} if partial else {
            name: value.get(name) for name in fields}
        if isinstance(basis.get('full_name'), str):
            basis['full_name'] = basis['full_name'].casefold()
        if old is not None:
            for name, item in basis.items():
                previous = old.get(name)
                if partial and name == 'permissions' and type(item) is dict and type(previous) is dict:
                    if any(k in previous and _canonical(previous[k]) != _canonical(v) for k, v in item.items()):
                        self.invalidate()
                    basis[name] = {**previous, **item}
                elif name in old and _canonical(previous) != _canonical(item):
                    self.invalidate()
        self.repositories[key] = {**(old or {}), **basis}

    def pages(self, path, key=None):
        if key not in {'workflow_runs', 'check_runs', 'jobs'}:
            return self.original_pages(path, key)
        rows, identifiers, declared = [], set(), None
        for page in range(1, 101):
            value = self.client.api('GET', path + ('&' if '?' in path else '?') +
                                    urlencode({'per_page': 100, 'page': page}))
            _require(type(value) is dict and type(value.get(key)) is list)
            total = value.get('total_count')
            _require(type(total) is int and 0 <= total <= 2**53 - 1)
            _require(declared is None or declared == total)
            declared = total
            chunk = value[key]
            _require(len(chunk) <= 100 and all(type(row) is dict and _integer(row.get('id')) for row in chunk))
            for row in chunk:
                _require(row['id'] not in identifiers)
                identifiers.add(row['id'])
            rows.extend(chunk)
            _bounded(rows)
            _require(len(rows) <= declared)
            if len(chunk) < 100 or len(rows) == declared:
                _require(len(rows) == declared)
                return rows
        raise GitHubError('Post-merge collection incomplete')

    def api(self, method, path, payload=None):
        if self.changed:
            self.invalidate()
        _require(method == 'GET' and payload is None)
        repository_path = bool(re.fullmatch(r'/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', path))
        try:
            value = _bounded(self.original_api(method, path, payload))
        except GitHubError as error:
            if repository_path and path.casefold() in self.repositories and error.status in {401, 403, 404}:
                self.invalidate()
            raise
        self.credential(self.client._authenticated_fingerprint)
        if path == '/user':
            identity = (value.get('id'), value.get('login')) if type(value) is dict else None
            if self.identity is not None and identity != self.identity:
                self.invalidate()
            _require(identity is not None and _integer(identity[0]) and identity[1] == self.client.user)
            self.identity = identity
        elif repository_path:
            # Compare a repository with its own prior disclosure basis, never
            # with the different visibility of another configured repository.
            self.repository(value, path.casefold())
        else:
            # Actions responses also carry authenticated repository metadata.
            # Missing nested fields are not observations of changed access.
            match = re.match(r'(/repos/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/actions/runs(?:/|\?)', path)
            if match and type(value) is dict:
                nested = value.get('workflow_runs', [value])
                if type(nested) is list:
                    for run in nested:
                        if type(run) is dict and type(run.get('repository')) is dict:
                            self.repository(run['repository'], match[1].casefold(), partial=True)
        return value

    def __enter__(self):
        self.client.api = self.api
        self.client._credential_selected = self.credential
        self.client._pages = self.pages
        return self

    def __exit__(self, *_):
        del self.client.api
        del self.client._credential_selected
        del self.client._pages


def _eligible(row):
    record = row.get('progress')
    return (type(record) is dict and
            (record.get('phase') in {'observing', 'closing', 'completed'}
             or record.get('pending_action') == 'merge'))


def _record(value, source):
    record = value['record']
    required = {'attempt_id', 'contract_revision', 'spec_revision', 'head', 'published_head',
                'expected_head', 'expected_base', 'checkpoint', 'intake_digest', 'pr_number', 'branch'}
    _require(required <= record.keys() and _eligible({'progress': record}))
    _require(record['branch'] == f"hydra/issue-{source['issue_number']}"
             and _integer(record['pr_number'])
             and record['head'] == record['published_head'] == record['expected_head'])
    _require(type(record['attempt_id']) is str and str(uuid.UUID(record['attempt_id'])) == record['attempt_id'])
    for field in ('contract_revision', 'head', 'expected_base'):
        _sha(record[field])
    if record['spec_revision'] is not None:
        _sha(record['spec_revision'])
    _require(type(record['intake_digest']) is str and re.fullmatch('[0-9a-f]{64}', record['intake_digest']))
    return record


def _run_repository_id(run):
    repository = run.get('repository')
    if type(repository) is dict:
        return repository.get('id', run.get('repository_id'))
    return run.get('repository_id') if 'repository' not in run else None


def _selection(config, observation, sha):
    selected = []
    for binding in config['required_checks']:
        try:
            candidates = _bound_runs(config, observation, sha, binding, post_merge=True)
            if not candidates or any(not _integer(run.get(field)) for run in candidates
                                     for field in ('id', 'run_number', 'run_attempt')) or any(
                    not _integer(_run_repository_id(run)) or _run_repository_id(run) != config['repository_id']
                    for run in candidates):
                selected.append(None)
                continue
            run = max(candidates, key=_run_order)
            if sum(_run_order(row) == _run_order(run) for row in candidates) != 1:
                selected.append(None)
            else:
                selected.append((binding['workflow_id'], binding['job'], run['id'],
                                 run['run_number'], run['run_attempt']))
        except _SOURCE_ERRORS:
            selected.append(None)
    return selected


def _refs(config, observed, sha):
    refs = []
    for binding, selected in zip(config['required_checks'], _selection(config, observed, sha)):
        if selected is None:
            continue
        try:
            state = _post_merge_binding_state(config, observed, sha, binding)
        except _SOURCE_ERRORS:
            continue
        if state == 'unknown':
            continue
        run = next(run for run in observed['runs'] if run['id'] == selected[2]
                   and run['run_attempt'] == selected[4])
        jobs = [job for job in run['jobs'] if job.get('name') == binding['job']]
        if len(jobs) != 1:
            continue
        job = jobs[0]
        _require(all(_integer(n) for n in (run['id'], run['run_attempt'], run['workflow_id'], job['id'])))
        repo, rid, jid = config['repository'], run['id'], job['id']
        refs.append({'workflow_id': run['workflow_id'], 'run_id': rid,
            'run_attempt': run['run_attempt'], 'job_id': jid, 'check_run_id': jid,
            'job_name': binding['job'], 'state': state,
            'run_url': f'https://github.com/{repo}/actions/runs/{rid}',
            'attempt_url': f'https://api.github.com/repos/{repo}/actions/runs/{rid}/attempts/{run["run_attempt"]}',
            'job_url': f'https://api.github.com/repos/{repo}/actions/jobs/{jid}',
            'check_url': f'https://api.github.com/repos/{repo}/check-runs/{jid}'})
    return refs


def _current(client, binding, row):
    repo, number = _repo(row['repository']), row['issue']
    _require(_integer(number) and _integer(row['progress'].get('repository_id')))
    source = {'repository_id': row['progress']['repository_id'], 'issue_number': number}
    identity = client._identity()
    metadata = client.repository(repo)
    _require(metadata['id'] == source['repository_id'])
    repo = metadata['full_name']
    issue = client.issue(repo, number)
    _require(type(issue) is dict and _integer(issue.get('id')) and 'pull_request' not in issue
             and type(issue.get('number')) is int and issue['number'] == number
             and issue.get('url') == f'https://api.github.com/repos/{repo}/issues/{number}'
             and issue.get('state') in {'open', 'closed'})
    original = _comment(client, repo, source, identity)
    _require(original is not None)
    if original['record'] != row['progress']:
        raise _LocalChanged()
    record = _record(original, source)
    config = load_project(client, repo, revision=record['contract_revision'])
    policy = load_project(client, repo)
    if _policy(config) != _policy(policy):
        raise _LocalChanged()
    pr = client.api('GET', f'/repos/{repo}/pulls/{record["pr_number"]}')
    _require(type(pr) is dict and type(pr.get('number')) is int and pr['number'] == record['pr_number']
             and pr.get('url') == f'https://api.github.com/repos/{repo}/pulls/{record["pr_number"]}'
             and type(pr.get('user')) is dict and _integer(pr['user'].get('id'))
             and all(type(pr.get(side)) is dict and type(pr[side].get('repo')) is dict
                     and _integer(pr[side]['repo'].get('id')) for side in ('head', 'base'))
             and client.owns_pr(repo, number, pr))
    observed = {'pr': pr, 'head_sha': record['head'],
                'head_commit': client.commit(repo, record['head']),
                'merge_commit': client.commit(repo, _sha(pr.get('merge_commit_sha')))}
    _require(not gate_squash_result(observed, record['head'], record['expected_base']))
    checkpoint = 'squash_' + pr['merge_commit_sha']
    _require(squash_recovery_checkpoint(config, number, record, observed) == checkpoint
             if record.get('pending_action') == 'merge' else record['checkpoint'] == checkpoint)
    merge = pr['merge_commit_sha']
    first = _bounded(client.observe_commit(repo, merge))
    first_selection = _selection(config, first, merge)
    final = _comment(client, repo, source, identity)
    if final != original or _policy(load_project(client, repo)) != _policy(config):
        raise _LocalChanged()
    current = _bounded(client.observe_commit(repo, merge))
    if _selection(config, current, merge) != first_selection:
        raise _LocalChanged()
    client._identity()
    client._request_timeout(45)
    state = post_merge_check_state(config, current, merge)
    refs = _refs(config, current, merge)
    source.update(progress_comment_id=original['id'], attempt_id=record['attempt_id'],
        contract_revision=record['contract_revision'], spec_revision=record['spec_revision'],
        source_digest=record['intake_digest'], head=record['head'], pr_number=record['pr_number'], merge_sha=merge)
    value = {'schema_version': 1, 'state': state,
        'reason': {'failed': 'post_merge_failed', 'pending': 'post_merge_checks',
                   'success': None, 'unknown': 'post_merge_evidence_unknown'}[state], 'source': source,
        'current': {'state': state, 'checks': [],
            'coverage': _coverage('required_check_bindings', 'complete', 0, len(config['required_checks'])),
            'observed_at': _now()},
        'history': {'failed_checks': [], 'through': [],
            'coverage': _coverage('historical_failed_checks'), 'observed_at': None}, 'observed_at': _now()}
    # Preserve confirmed failure targets first when a bounded result cannot fit
    # every configured slot. Ordering conveys no additional execution authority.
    for ref in sorted(refs, key=lambda ref: ref['state'] != 'failed'):
        _append(value, 'current', ref)
    axis = value['current']
    count, total = len(axis['checks']), len(config['required_checks'])
    if count != total:
        axis['coverage'] = _coverage('required_check_bindings', 'partial', count, total,
            'reference_limit' if len(refs) > MAX_REFS else
            'byte_limit' if len(refs) > count else 'post_merge_evidence_unknown')
    else:
        axis['coverage']['returned_count'] = count
    _require(_size(value) <= MAX_CONTEXT_BYTES)
    return value, config, current


def _append(context, axis_name, ref):
    axis = context[axis_name]
    key = 'checks' if axis_name == 'current' else 'failed_checks'
    if len(context['current']['checks']) + len(context['history']['failed_checks']) >= MAX_REFS:
        return False
    axis[key].append(ref)
    if _size(context) > MAX_CONTEXT_BYTES - _FRAMING_RESERVE:
        axis[key].pop()
        return False
    return True


def _history_plan(config, observed, sha):
    selected = {part[2] for part in _selection(config, observed, sha) if part is not None}
    runs = {}
    for requirement in config['required_checks']:
        for run in _bound_runs(config, observed, sha, requirement, post_merge=True):
            _require(all(_integer(run.get(field)) for field in ('id', 'workflow_id', 'run_number', 'run_attempt')))
            _require(_integer(_run_repository_id(run)) and _run_repository_id(run) == config['repository_id'])
            through = run['run_attempt'] - (run['id'] in selected)
            if through:
                runs[run['id']] = (run, through)
    ordered = sorted(runs.values(), key=lambda part: (part[0]['run_number'], part[0]['id']))
    return ordered[:MAX_HISTORY_RUNS], len(ordered) > MAX_HISTORY_RUNS


def _attempt(client, repo, captured, attempt, config, sha):
    rid = captured['id']
    run = client.api('GET', f'/repos/{repo}/actions/runs/{rid}/attempts/{attempt}')
    _require(type(run) is dict and all(type(run.get(key)) is int for key in
             ('id', 'run_number', 'run_attempt', 'workflow_id'))
             and run['id'] == rid and run['run_attempt'] == attempt
             and run['run_number'] == captured['run_number'] and run['workflow_id'] == captured['workflow_id'])
    jobs = client._pages(f'/repos/{repo}/actions/runs/{rid}/attempts/{attempt}/jobs', 'jobs')
    _require(all(type(job) is dict for job in jobs))
    required = {item['job'] for item in config['required_checks'] if item['workflow_id'] == run['workflow_id']}
    checks = []
    for job in jobs:
        if job.get('name') in required and _integer(job.get('id')):
            checks.append(client.api('GET', f'/repos/{repo}/check-runs/{job["id"]}'))
    value = {'repository': {'id': config['repository_id']}, 'head_sha': sha,
             'runs': [{**run, 'jobs': jobs}], 'checks': checks}
    subset = {**config, 'required_checks': [item for item in config['required_checks']
                                          if item['workflow_id'] == run['workflow_id']]}
    _require(bool(subset['required_checks']))
    refs = _refs(subset, value, sha)
    complete = (run.get('status') == 'completed' and len(refs) == len(subset['required_checks'])
                and all(ref['state'] in {'success', 'failed'} for ref in refs))
    return [ref for ref in refs if ref['state'] == 'failed'], complete


def _history(client, context, config, observed, budget):
    axis, sha = context['history'], context['source']['merge_sha']
    plan, truncated = _history_plan(config, observed, sha)
    through = [{'workflow_id': run['workflow_id'], 'run_id': run['id'], 'through_attempt': limit}
               for run, limit in plan]
    axis['through'] = through
    if _size(context) > MAX_CONTEXT_BYTES:
        axis['through'] = []
        axis['coverage'] = _coverage('historical_failed_checks', reason='byte_limit')
        return
    complete, observed_any, reason = not truncated, not plan, 'history_limit' if truncated else None
    for run, limit in plan:
        if limit > MAX_HISTORY_ATTEMPTS:
            complete, reason = False, 'history_limit'
        for attempt in range(1, min(limit, MAX_HISTORY_ATTEMPTS) + 1):
            if budget.remaining_requests <= 2:
                complete, reason = False, 'source_budget'
                break
            try:
                refs, terminal = _attempt(client, config['repository'], run, attempt, config, sha)
                observed_any = True
                if not terminal:
                    complete, reason = False, reason or 'post_merge_evidence_unknown'
                for ref in refs:
                    if not _append(context, 'history', ref):
                        complete, reason = False, 'reference_limit' if len(context['current']['checks']) + len(axis['failed_checks']) >= MAX_REFS else 'byte_limit'
            except _SOURCE_ERRORS:
                complete, reason = False, 'history_source_unavailable'
                break
    count = len(axis['failed_checks'])
    axis['coverage'] = _coverage('historical_failed_checks',
        'complete' if complete else 'partial' if observed_any else 'unavailable',
        count, count if complete else None, reason)
    axis['observed_at'] = _now()


def enrich_status(github, rows):
    """Enrich existing rows in two bounded phases, with no durable side effects."""
    eligible = [index for index, row in enumerate(rows) if _eligible(row)]
    if not eligible:
        return rows
    result = [dict(row) for row in rows]
    for index in eligible:
        result[index]['post_merge_context'] = _empty(reason='context_limit' if index not in eligible[:MAX_CONTEXTS] else None)
    binding = None
    snapshots = []
    try:
        client = github.read_client()
        _require(client is not github)
        with client.read_budget(seconds=45, requests=128) as budget, _Binding(client) as binding:
            # All selected current snapshots settle before the first optional
            # historical GET. Incomplete source/budget never blocks other rows.
            for index in eligible[:MAX_CONTEXTS]:
                try:
                    value, config, observed = _current(client, binding, result[index])
                    result[index]['post_merge_context'] = value
                    snapshots.append((index, config, observed))
                except _LocalChanged:
                    result[index]['post_merge_context'] = _empty(changed=True)
                except _SOURCE_ERRORS:
                    pass
            for index, config, observed in snapshots:
                try:
                    _history(client, result[index]['post_merge_context'], config, observed, budget)
                except _SOURCE_ERRORS:
                    # History is optional. It cannot erase a current failure.
                    result[index]['post_merge_context']['history']['coverage'] = _coverage(
                        'historical_failed_checks', reason='history_source_unavailable')
            # Reobserve the shared account if optional reads left time/budget.
            # A source change actually observed anywhere is always sticky.
            if budget.remaining_requests:
                try:
                    client._identity()
                except _SOURCE_ERRORS:
                    pass
    except _SharedChanged:
        pass
    except _SOURCE_ERRORS:
        pass
    if binding is not None and binding.changed:
        for index in eligible:
            result[index]['post_merge_context'] = _empty(changed=True)
    for index in eligible:
        context = result[index]['post_merge_context']
        context['observed_at'] = _now()
        if _size(context) > MAX_CONTEXT_BYTES:
            result[index]['post_merge_context'] = _empty(reason='byte_limit')
    return result
