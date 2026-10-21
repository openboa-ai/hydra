"""Bounded read-only source assembly. External text never selects effects."""
from datetime import datetime, timezone
import copy
import base64
import binascii
import hashlib
import time
import uuid
from types import MethodType
from urllib.parse import urlencode

from . import projection as p
from .control import control_from_config, observe_coordinator, _repository
from .github import GitHub, GitHubError, ACTIVE_LABEL, read_credential_scope
from .github_read import ReadResponse
from .operations import OperationDenied
from .runtime_identity import capture_runtime_identity


class ReadHeld(GitHubError):
    pass


class ProjectionClient(GitHub):
    """One separately owned GET client. Notes contain sanitized metadata only."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.notes = []
        self.context = None
        self.held = None
        self.requests = 0
        self.read_scope = None
        self.binding_epoch = None
        self.context_changed = False
        self._injected_context = uuid.uuid4().bytes

    def bind_context(self, binding_epoch, expected=None):
        self.notes = []
        self.context = None
        self.held = None
        self.requests = 0
        self.binding_epoch = binding_epoch
        self.context_changed = False
        if expected is not None:
            p.text(expected, 256)
        own = (isinstance(self.transport, MethodType) and self.transport.__self__ is self
               and self.transport.__func__ is GitHub._gh)
        self.read_scope = expected if own else expected or read_credential_scope(binding_epoch, self._injected_context)

    def _credential_selected(self, fingerprint):
        if self.binding_epoch is None:
            raise GitHubError('Read scope unavailable')
        scope = read_credential_scope(self.binding_epoch, fingerprint)
        if self.read_scope is not None and self.read_scope != scope:
            self.context_changed = True
            raise GitHubError('Read credential context changed')
        self.read_scope = scope

    def api(self, method, path, payload=None):
        if self.context_changed:
            raise GitHubError('Read credential context changed')
        if method != 'GET' or payload is not None:
            raise GitHubError('Read-only client rejects effects')
        if self.held is not None and self.held.remaining_wait() != 0:
            raise ReadHeld('Provider wait', status=429, read_response=self.held)
        self.requests += 1
        try:
            response = self.read_response(path)
        except GitHubError as exc:
            response = getattr(exc, 'read_response', None)
            if response is None and exc.status == 429:
                response = ReadResponse(429, None, limited=True, received_at=time.monotonic())
            self.notes.append({'context': self.context, 'path': path, 'response': response,
                               'valid': False, 'reason': _failure(exc), 'count': 0})
            if response is not None and response.limited:
                self.held = response
            raise
        self.notes.append({'context': self.context, 'path': path, 'response': response.without_value(),
                           'valid': False, 'reason': 'invalid_source',
                           'count': len(response.value) if isinstance(response.value, list) else 1})
        if response.limited:
            self.held = response.without_value()
        if response.status != 200:
            raise GitHubError('Read cache context unavailable', status=response.status,
                              read_response=response.without_value())
        return response.value

    def accepted(self, start):
        for note in self.notes[start:]:
            note['valid'] = True
            note['reason'] = None


def _now():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%S.%fZ')


def _failure(error):
    response = getattr(error, 'read_response', None)
    if isinstance(error, ReadHeld):
        return 'provider_wait'
    if response is not None and response.limited or getattr(error, 'status', None) == 429:
        return 'rate_limited'
    if getattr(error, 'status', None) in {401, 403, 404}:
        return 'access_denied'
    if getattr(error, 'status', None) == 304:
        return 'cache_context_unavailable'
    return 'transport_failed'


def _ref(source, kind, identifier):
    return {'source': source, 'kind': kind, 'id': str(identifier)}


def _coverage(scope, count, complete=True, reason=None):
    return {'state': 'complete' if complete else 'partial', 'scope': scope,
            'returned_count': count, 'total_count': count if complete else None,
            'next_cursor': None, 'reason': None if complete else reason or 'not_requested'}


def _observation(key, resource, scope, value, at, *, reason=None, revision=None):
    known = value is not None
    return {'key': key, 'resource': resource, 'revision': revision,
            'observed_at': at if known else None, 'last_attempt_at': at,
            'availability': 'current' if known else 'unavailable', 'reason': reason, 'value': value,
            'coverage': _coverage(scope, 1) if known else {
                'state': 'unavailable', 'scope': scope, 'returned_count': 0,
                'total_count': None, 'next_cursor': None, 'reason': reason or 'not_requested'}}


def _effective(snapshot, repository):
    mode = snapshot['global_mode']
    if mode == 'running':
        mode = snapshot['projects'].get(repository, 'running')
    return {'running': 'allowed', 'paused': 'paused', 'stopped': 'stopped'}[mode]


def _issue(raw, repository):
    p.require(type(raw) is dict and 'pull_request' not in raw)
    p.integer(raw.get('number'), 1)
    p.require(raw.get('state') in {'open', 'closed'} and type(raw.get('title')) is str)
    present = 'body' in raw
    body = raw.get('body')
    p.require(body is None or type(body) is str)
    if present and body is None:
        body = ''
    value = {'number': raw['number'], 'title': raw['title'][:512], 'state': raw['state'],
             'url': 'https://github.com/' + repository + '/issues/' + str(raw['number']),
             'work_kind': None, 'parent_refs': None, 'requirement_refs': None,
             'description_excerpt': None if not present else body[:4096],
             'description_truncated': None if not present else len(body) > 4096}
    p.source_value('issue', value)
    return value


def _work(issue, admission):
    resource = issue['resource']
    readiness = {'disposition': 'propose', 'source_ref': resource, 'source_revision': issue['revision'],
        'interpretation_ref': None, 'binding_ref': None,
        'extracted': {'purpose_excerpt': None, 'requirement_refs': [], 'scope_excerpt': None},
        'missing': [{'code': 'interpretation_unavailable', 'detail': 'Original issue is visible; interpretation and authority remain unverified.',
                     'owner_ref': None}], 'authority': 'unknown', 'trust_reason': 'not_interpreted'}
    return {'issue_ref': resource, 'goal_refs': [], 'spec_refs': [], 'requirement_refs': [],
        'readiness': p.known(readiness, [issue]), 'stage': p.unknown('stage_mapping_unverified'),
        'admission': copy.deepcopy(admission), 'execution': p.unknown('native_execution_unverified'),
        'wait': p.unknown('wait_unverified'), 'decision': p.unknown_decision(),
        'delivery': p.unknown('delivery_unverified'), 'result': p.unknown('acceptance_unverified'),
        'cleanup': p.unknown('resource_scope_unverified'), 'next_action': p.unknown('not_interpreted'),
        'task_refs': [], 'resource_refs': [], 'evidence_refs': [p.evidence_of(issue)]}


def _progress(source, issue_ref, repository):
    record = source['record']
    value = {key: None for key in p.SOURCE_FIELDS['progress'].split()}
    value['issue_ref'] = issue_ref
    for key in ('attempt_id', 'phase', 'native_step', 'head', 'contract_revision', 'branch',
                'expected_head', 'expected_base', 'published_head', 'wait_reason',
                'next_action', 'pending_action'):
        value[key] = record.get(key)
    number = record.get('pr_number')
    if type(number) is int and 1 <= number <= p.MAX_INTEGER:
        value['pr_ref'] = _ref('github', 'pull_request', repository + ':' + str(number))
    # Missing cleanup/binding/completion facts remain null, not fabricated empty success.
    p.source_value('progress', value)
    resource = {**source['resource'], 'kind': 'progress'}
    return value, resource



def _cursor(cfg, epoch, repository, position):
    value = {'v': 1, 'epoch': epoch, 'repositories_digest': hashlib.sha256(p.canonical(cfg['repos']).encode()).hexdigest(),
             'repository': repository, 'position': position}
    return base64.urlsafe_b64encode(p.canonical(value).encode()).decode().rstrip('=')


def _position(cfg, epoch, repository, token):
    if token is None:
        return None
    p.text(token, 2048)
    try:
        data = base64.b64decode(token + '=' * (-len(token) % 4), altchars=b'-_', validate=True)
        p.require(base64.urlsafe_b64encode(data).decode().rstrip('=') == token)
        value = p.read_json(data)
    except (ValueError, binascii.Error):
        raise p.ProjectionError('invalid_cursor') from None
    p.obj(value, 'v epoch repositories_digest repository position')
    p.require(value['v'] == 1 and type(value['v']) is int and value['epoch'] == epoch and value['repository'] == repository)
    p.require(value['repositories_digest'] == hashlib.sha256(p.canonical(cfg['repos']).encode()).hexdigest())
    pos = value['position']
    if repository is None:
        p.obj(pos, 'project_index'); p.integer(pos['project_index'])
        p.require(pos['project_index'] < len(cfg['repos']))
    else:
        p.obj(pos, 'plan page offset')
        for key in ('plan', 'page', 'offset'):
            p.integer(pos[key])
        p.require(pos['plan'] <= 2 and pos['page'] >= 1 and pos['offset'] < 100)
    return pos


def _issue_rows(client, repository, limit, position):
    rows, locations = {}, {}
    complete, reason = position is None, None if position is None else 'continuation_slice'
    initial = position or {'plan': 0, 'page': 1, 'offset': 0}
    resume = dict(initial)
    try:
        for plan, (state, managed) in enumerate([('open', True), ('closed', True), ('open', False)]):
            if plan < initial['plan']:
                continue
            first_page = initial['page'] if plan == initial['plan'] else 1
            for page in range(first_page, first_page + 4):
                first_offset = initial['offset'] if plan == initial['plan'] and page == first_page else 0
                resume = {'plan': plan, 'page': page, 'offset': first_offset}
                if len(rows) >= limit:
                    return rows, locations, False, 'record_limit', resume
                parameters = {'state': state, 'sort': 'created', 'direction': 'asc', 'per_page': 100, 'page': page}
                if managed:
                    parameters['labels'] = ACTIVE_LABEL
                start = len(client.notes)
                values = client.api('GET', '/repos/' + repository + '/issues?' + urlencode(parameters))
                p.require(type(values) is list and len(values) <= 100)
                for offset, raw in enumerate(values):
                    if offset < first_offset:
                        continue
                    resume = {'plan': plan, 'page': page, 'offset': offset}
                    if type(raw) is not dict:
                        complete, reason = False, 'invalid_source'; continue
                    if 'pull_request' in raw:
                        continue
                    if plan == 2:
                        labels = raw.get('labels')
                        names = ([label.get('name') if type(label) is dict else label for label in labels]
                                 if type(labels) is list else None)
                        if names is None or any(not isinstance(name, str) or not name for name in names):
                            complete, reason = False, 'label_metadata_unavailable'
                            # Unknown classification cannot overwrite earlier
                            # managed progress as an ordinary candidate.
                            continue
                        if any(name.casefold() == ACTIVE_LABEL.casefold() for name in names):
                            # Managed plans already own these identities, even on
                            # an earlier continuation page. Do not demote them.
                            continue
                    if len(rows) >= limit:
                        if reason != 'invalid_source':
                            client.accepted(start)
                        return rows, locations, False, 'record_limit', resume
                    try:
                        value = _issue(raw, repository)
                    except (ValueError, TypeError):
                        complete, reason = False, 'invalid_source'; continue
                    previous = rows.get(value['number'])
                    rows[value['number']] = (value, managed or bool(previous and previous[1]))
                    locations.setdefault(value['number'], resume.copy())
                if reason != 'invalid_source':
                    client.accepted(start)
                if len(values) < 100:
                    break
                if page == first_page + 3:
                    return rows, locations, False, 'page_limit', {'plan': plan, 'page': page + 1, 'offset': 0}
    except (ValueError, RuntimeError, OSError, TypeError, KeyError) as error:
        return rows, locations, False, _failure(error) if isinstance(error, GitHubError) else 'invalid_source', resume
    return rows, locations, complete, reason, None


def _finish(frame, cfg, epoch, locations, project_locations, *, repository=None):
    original = frame
    for _ in range(8):
        frame = _bounded(frame)
        kept = {p.canonical(w['issue_ref']) for w in frame['work']}
        for project in frame['projects']:
            repo_id = project['repository_ref']['id']
            omitted = next((w for w in original['work'] if w['issue_ref']['id'].split(':', 1)[0] == repo_id
                            and p.canonical(w['issue_ref']) not in kept), None)
            if omitted is not None:
                address, position = locations[p.canonical(omitted['issue_ref'])]
                project['coverage']['next_cursor'] = _cursor(cfg, epoch, address, position)
        present = {p.canonical(project['repository_ref']) for project in frame['projects']}
        omitted = next((row for row in original['projects'] if p.canonical(row['repository_ref']) not in present), None)
        if omitted is not None:
            # Repository-scoped requests cannot consume an overview cursor.
            # Optional query provenance is pruned first; if mandatory metadata
            # still cannot fit, fail this source instead of inventing navigation.
            if repository is not None:
                raise p.ProjectionError('response_limit')
            index = project_locations[p.canonical(omitted['repository_ref'])]
            frame['page']['next_cursor'] = _cursor(cfg, epoch, None, {'project_index': index})
        if len(p.canonical(frame).encode()) <= p.MAX_BYTES:
            return frame
    raise p.ProjectionError('response_limit')


def _prune(frame, work_count, project_count, query_count=None):
    value = copy.deepcopy(frame)
    value['projects'] = value['projects'][:project_count]
    project_refs = {p.canonical(row['repository_ref']) for row in value['projects']}
    selected = []
    for row in value['work'][:work_count]:
        repository_id = row['issue_ref']['id'].split(':', 1)[0]
        if p.canonical(_ref('github', 'repository', repository_id)) in project_refs:
            selected.append(row)
    value['work'] = selected
    work_refs = {p.canonical(row['issue_ref']) for row in selected}
    omitted_work = {p.canonical(row['issue_ref']) for row in frame['work']} - work_refs
    for project in value['projects']:
        before = project['work_refs']
        project['work_refs'] = [ref for ref in before if p.canonical(ref) not in omitted_work]
        if len(before) != len(project['work_refs']):
            project['coverage'] = _coverage(project['coverage']['scope'], len(project['work_refs']), False, 'response_limit')
    evidence_keys = {hint['observation_key'] for hint in value['retry_hints']}
    def refs(item):
        if type(item) is dict:
            if set(item) == {'observation_key', 'revision'}:
                evidence_keys.add(item['observation_key'])
            for child in item.values():
                refs(child)
        elif type(item) is list:
            for child in item:
                refs(child)
    refs(value['projects']); refs(value['work']); refs(value['relations'])
    resources = {p.canonical(ref) for row in value['projects'] for ref in row['source_refs']}
    resources.update(p.canonical(ref) for row in value['projects'] for ref in row['work_refs'])
    observations, queries = [], []
    for item in value['observations']:
        if item['key'] in evidence_keys or item['resource']['source'] == 'hydra':
            observations.append(item)
        elif p.canonical(item['resource']) in resources:
            (queries if item['key'].startswith('github:query:') else observations).append(item)
    value['observations'] = observations + queries[:query_count]
    if len(value['work']) < len(frame['work']) or len(value['projects']) < len(frame['projects']):
        value['page'] = _coverage(frame['page']['scope'], len(value['projects']), False, 'response_limit')
    return value


def _bounded(frame):
    def size(value):
        return len(p.canonical(value).encode('utf-8'))
    def prefix(maximum, make):
        low, high, best = 0, maximum, None
        while low <= high:
            middle = (low + high) // 2
            value = make(middle)
            if size(value) <= p.MAX_BYTES:
                best, low = value, middle + 1
            else:
                high = middle - 1
        return best
    if size(frame) <= p.MAX_BYTES:
        return frame
    projects, work = len(frame['projects']), len(frame['work'])
    # Query notes without a Fact/hint dependency are optional provenance. Keep
    # whole work records and their exact repository before those redundant notes.
    frame = _prune(frame, work, projects, query_count=0)
    if size(frame) <= p.MAX_BYTES:
        return frame
    empty = _prune(frame, 0, projects)
    if size(empty) > p.MAX_BYTES:
        candidate = prefix(projects, lambda n: _prune(frame, 0, n))
        if candidate is None:
            raise p.ProjectionError('response_limit')
        projects = len(candidate['projects'])
    candidate = prefix(work, lambda n: _prune(frame, n, projects))
    if candidate is None:
        raise p.ProjectionError('response_limit')
    return candidate


def read_projection(cfg, *, binding_epoch, request_id, refresh=False, repository=None, github=None, cursor=None, credential_scope=None, repository_bindings=None):
    """Read a registered scope; no admission mutation, model call or native wake."""
    p.uid(binding_epoch); p.uid(request_id)
    p.require(type(refresh) is bool)
    if repository_bindings is None:
        repository_bindings = {}
    p.require(type(repository_bindings) is dict and len(repository_bindings) <= 1024)
    for address, identifier in repository_bindings.items():
        p.require(type(address) is str and p._repository_name(address) == address)
        p.integer(identifier, 1)
    repository_bindings = {address: identifier for address, identifier in repository_bindings.items()
                           if address in cfg['repos']}
    if repository is not None:
        repository = _repository(repository)
        p.require(repository in cfg['repos'])
    position = _position(cfg, binding_epoch, repository, cursor)
    p.require(cursor is None or repository is None or refresh)
    start_project = position['project_index'] if position is not None and repository is None else 0
    repos = [repository] if repository else cfg['repos'][start_project:]
    control = control_from_config(cfg)
    at = _now()
    # Remote collection does not hold a local admission snapshot fresh. These
    # placeholder facts are rebound to one final local read before encoding.
    snapshot = None
    runtime = capture_runtime_identity(cfg, control)
    admission_ref = _ref('hydra', 'admission', runtime['control_binding_digest'] or 'requested:host-admission')
    admission = _observation('hydra:host:admission', admission_ref,
        'resource:host:admission', None, at, reason='not_requested')
    observations = {}
    frame = {'schema_version': 3, 'runtime': runtime,
        'binding_epoch': binding_epoch, 'request_id': request_id, 'assembled_at': at,
        'observations': [], 'projects': [], 'work': [], 'relations': [],
        'page': _coverage('registered-projects;overview', 0, False, 'not_requested'),
        'capabilities': [{'source': source, 'operation': operation, 'state': 'unsupported',
            'actor': actor, 'qualification_ref': None, 'reason': reason} for source, operation, actor, reason in [
                ('codex', 'native_read', 'native_actor', 'native_source_unqualified'),
                ('resource_provider', 'resource_inventory', 'provider', 'resource_source_unqualified'),
                ('github', 'binding_projection', 'core', 'binding_projection_unqualified')]],
        'retry_hints': [], 'request': None}
    client = github or ProjectionClient()
    p.require(isinstance(client, ProjectionClient))
    client.bind_context(binding_epoch, credential_scope)
    contexts, projects, work, locations, project_locations = {}, {}, {}, {}, {}
    with client.read_budget(seconds=45, requests=4096) as total:
        for index, address in enumerate(repos):
            requested_ref = _ref('github', 'repository', 'requested:' + address)
            context = {'requested': address, 'resource': requested_ref, 'value': None, 'observed_at': at}
            contexts[address] = context; client.context = address
            repo_observation = _observation('github:repository-request:' + address, requested_ref,
                'repository-address:' + address, None, at, reason='not_requested')
            repo_ref = requested_ref
            gate = (p.known(_effective(snapshot, address), [admission]) if snapshot is not None else
                    p.unknown('admission_unavailable', [admission]))
            project = {'repository_ref': repo_ref, 'goal_refs': [], 'work_refs': [], 'admission': gate,
                'execution': p.unknown('native_execution_unverified'), 'attention_refs': [],
                'coverage': _coverage('repository-address:' + address + ';managed-work+open-candidates', 0, False, 'not_requested'),
                'source_refs': [requested_ref, admission['resource']]}
            complete, reason, rows, next_cursor = False, 'not_requested', {}, None
            if refresh:
                try:
                    with client.read_budget(seconds=total.remaining_seconds / (len(repos) - index),
                                            requests=total.remaining_requests // (len(repos) - index)):
                        start = len(client.notes)
                        raw = client.api('GET', '/repos/' + address)
                        p.require(type(raw) is dict)
                        repo_value = {'numeric_id': raw.get('id'), 'full_name': raw.get('full_name'),
                            'url': 'https://github.com/' + str(raw.get('full_name')), 'contract_ref': None}
                        p.source_value('repository', repo_value)
                        _repository(repo_value['full_name'])
                        expected = repository_bindings.get(address)
                        p.require(repo_value['numeric_id'] == expected if expected is not None
                                  else repo_value['full_name'].casefold() == address.casefold())
                        client.accepted(start)
                        canonical, identifier = repo_value['full_name'], str(repo_value['numeric_id'])
                        repo_ref = _ref('github', 'repository', identifier)
                        context.update(value=repo_value, resource=repo_ref, observed_at=_now())
                        repo_observation = _observation('github:repository-request:' + address, repo_ref,
                            'repository-address:' + address, repo_value, context['observed_at'])
                        project['repository_ref'] = repo_ref
                        project['source_refs'].insert(0, repo_ref)
                        if p.canonical(repo_ref) in projects:
                            existing = projects[p.canonical(repo_ref)]
                            if existing['admission']['value'] != gate['value']:
                                existing['admission'] = p.unknown('repository_binding_conflict', [admission])
                            observations[repo_observation['key']] = repo_observation
                            continue
                        complete, reason = True, None
                        rows, row_locations, complete, reason, next_position = _issue_rows(client, canonical,
                            min(128, 512-len(work)), position if repository is not None else None)
                        next_cursor = _cursor(cfg, binding_epoch, address, next_position) if next_position is not None else None
                        for number, (value, managed) in rows.items():
                            resource = _ref('github', 'issue', identifier + ':' + str(number))
                            observed = _observation('github:' + identifier + ':issue:' + str(number),
                                resource, 'resource:' + identifier + ':issue:' + str(number), value, _now())
                            observations[observed['key']] = observed
                            view = _work(observed, gate)
                            if managed:
                                progress_key = 'github:' + identifier + ':progress:' + str(number)
                                progress_scope = 'resource:' + identifier + ':progress:' + str(number)
                                progress_ref = _ref('github', 'progress', 'requested:' + identifier + ':' + str(number))
                                progress_observed = _observation(progress_key, progress_ref,
                                    progress_scope, None, _now(), reason='progress_not_observed')
                                try:
                                    start = len(client.notes)
                                    source = client.progress_source(canonical, number)
                                    client.accepted(start)
                                    if source is not None:
                                        progress_value, progress_ref = _progress(source, resource, identifier)
                                        progress_observed = _observation(progress_key, progress_ref,
                                            progress_scope, progress_value, _now())
                                except (ValueError, RuntimeError, OSError, TypeError, KeyError):
                                    progress_observed = _observation(progress_key, progress_ref,
                                        progress_scope, None, _now(), reason='progress_unavailable')
                                observations[progress_key] = progress_observed
                                view['evidence_refs'].append(p.evidence_of(progress_observed))
                                view['stage'] = p.unknown(progress_observed['reason'] or 'stage_mapping_unverified', [progress_observed])
                            locations[p.canonical(resource)] = (address, row_locations[number])
                            work[p.canonical(resource)] = view
                            project['work_refs'].append(resource)
                except (ValueError, RuntimeError, OSError, TypeError, KeyError) as error:
                    complete, reason = False, _failure(error) if isinstance(error, GitHubError) else 'invalid_source'
                    if context['value'] is None:
                        repo_observation = _observation(repo_observation['key'], requested_ref,
                            repo_observation['coverage']['scope'], None, _now(), reason=reason)
            project['coverage'] = _coverage(project['coverage']['scope'], len(project['work_refs']), complete, reason)
            project['coverage']['next_cursor'] = next_cursor
            project_locations[p.canonical(project['repository_ref'])] = start_project + index
            projects[p.canonical(project['repository_ref'])] = project
            observations[repo_observation['key']] = repo_observation
    if client.context_changed:
        raise GitHubError('Read credential context changed')
    at = _now()
    try:
        p.require(runtime['control_binding_digest'] is not None)
        snapshot = control.snapshot()
        admission_value = {'revision': snapshot['revision'], 'global_mode': snapshot['global_mode'],
            'project_overrides': snapshot['projects'],
            'gate_reason': None if snapshot['global_mode'] == 'running' else 'host_' + snapshot['global_mode']}
        p.source_value('admission', admission_value)
        admission = _observation('hydra:host:admission', admission_ref,
            'resource:host:admission', admission_value, at,
            revision={'kind': 'monotonic', 'value': str(snapshot['revision'])})
    except (OperationDenied, ValueError, KeyError, TypeError, OSError):
        snapshot = None
        admission = _observation('hydra:host:admission', admission_ref,
            'resource:host:admission', None, at,
            reason='admission_unavailable' if runtime['control_binding_digest'] else 'admission_binding_unavailable')
    ownership_reason = 'ownership_unavailable'
    try:
        owner = observe_coordinator(cfg['lock_path'])
        p.require(type(owner) is dict)
        if owner.get('reason') in {'ownership_file_unsafe', 'ownership_file_changed',
                                 'ownership_changed_during_observation', 'ownership_observation_unavailable'}:
            ownership_reason = owner['reason']
        p.require(owner.get('state') != 'unknown' and owner.get('reason') is None)
        owner_value = {key: None for key in p.SOURCE_FIELDS['ownership'].split()}
        owner_value['state'] = owner.get('state')
        for source, target, validator in [('scope_digest', 'scope_digest', p.digest),
                                           ('nonce', 'step_nonce', p.uid)]:
            try:
                p.nullable(owner.get(source), validator)
                owner_value[target] = owner.get(source)
            except (ValueError, TypeError):
                pass
        p.source_value('ownership', owner_value)
    except (ValueError, TypeError, RuntimeError, OSError):
        owner_value = None
    ownership = _observation('hydra:host:ownership', _ref('hydra', 'ownership', 'host'),
        'resource:host:ownership', owner_value, at, reason=None if owner_value else ownership_reason)
    observations.update({item['key']: item for item in (admission, ownership)})
    gates = {}
    if snapshot is not None:
        for address, context in contexts.items():
            gates.setdefault(p.canonical(context['resource']), set()).add(_effective(snapshot, address))
    for project in projects.values():
        values = gates.get(p.canonical(project['repository_ref']), set())
        if snapshot is None:
            gate = p.unknown('admission_unavailable', [admission])
        elif len(values) != 1:
            gate = p.unknown('repository_binding_conflict', [admission])
        else:
            gate = p.known(next(iter(values)), [admission])
        project['admission'] = gate
        for ref in project['work_refs']:
            work[p.canonical(ref)]['admission'] = gate
    scope = client.read_scope
    for note in client.notes:
        context = contexts[note['context']]
        key = 'github:query:' + hashlib.sha256(note['path'].encode('utf-8')).hexdigest()
        response = note['response']
        limited = response is not None and response.limited
        reason = 'rate_limited' if limited else note['reason']
        value = context['value'] if note['valid'] else None
        observed = _observation(key, context['resource'] if value is not None else _ref('github', 'repository', 'requested:' + context['requested']),
            'query:' + hashlib.sha256(note['path'].encode('utf-8')).hexdigest(),
            value, context['observed_at'], reason=reason)
        if value is not None:
            observed['coverage'] = _coverage(observed['coverage']['scope'], note['count'])
        observations[key] = observed
        # A later note is the current observation for this exact query key.
        # Its old hint cannot point at a newly recovered non-limited source.
        frame['retry_hints'] = [h for h in frame['retry_hints'] if h['observation_key'] != key]
        if limited and scope is not None:
            remaining = response.remaining_wait()
            hint = {'observation_key': key, 'scope': scope,
                    'after_seconds': 60 if remaining is None else remaining,
                    'basis': 'fallback' if remaining is None else 'provider'}
            frame['retry_hints'].append(hint)
    frame['projects'] = list(projects.values()); frame['work'] = list(work.values())
    frame['observations'] = list(observations.values())
    complete = all(row['coverage']['state'] == 'complete' for row in frame['projects'])
    page_scope = 'registered-projects;' + ('repository:' + repository if repository is not None else 'overview')
    frame['page'] = _coverage(page_scope + (':from:' + str(start_project) if start_project else ''), len(frame['projects']), complete,
                              None if complete else 'source_coverage_incomplete')
    frame['assembled_at'] = _now()
    frame = _finish(frame, cfg, binding_epoch, locations, project_locations, repository=repository)
    p.encode(frame)
    return frame
