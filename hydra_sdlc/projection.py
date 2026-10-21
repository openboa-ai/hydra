"""Closed, bounded control-plane values. Reading a value never grants authority.

The core emits allowlisted source fields; the bridge and renderer independently
validate this wire. No source text, PID, title or cache entry becomes an owner,
decision, execution proof or command permission.
"""
from datetime import datetime, timezone
import copy
import json
import re
import uuid


MAX_BYTES = 1_048_576
MAX_INTEGER = 9_007_199_254_740_991
SOURCES = {'github', 'codex', 'resource_provider', 'hydra'}
SOURCE_OWNERS = {**dict.fromkeys(('repository', 'issue', 'progress', 'pull_request', 'check', 'review'), 'github'),
                 **dict.fromkeys(('native_task_metadata', 'native_history_page', 'native_task', 'native_schedule'), 'codex'),
                 'resource': 'resource_provider', 'admission': 'hydra', 'ownership': 'hydra'}
MODES = {'running', 'paused', 'stopped'}
SOURCE_FIELDS = {
    'repository': 'numeric_id full_name url contract_ref',
    'issue': 'number title state url work_kind parent_refs requirement_refs description_excerpt description_truncated',
    'progress': ('issue_ref attempt_id phase native_step head contract_revision branch expected_head expected_base '
                 'published_head wait_reason next_action pending_action pr_ref completion_refs cleanup_state'),
    'pull_request': 'number url state head base merge_commit required_check_refs review_refs',
    'check': 'producer name head status conclusion url',
    'review': 'producer head state unresolved_count url',
    'native_task_metadata': 'task_ref reported_status',
    'native_history_page': 'task_ref turns page',
    'native_task': 'task_ref assignment_ref execution question_ref schedule_refs open_ref',
    'native_schedule': 'schedule_ref task_ref status next_wake_at open_ref',
    'resource': 'resource_ref owner_ref activity preservation retirement open_ref',
    'admission': 'revision global_mode project_overrides gate_reason',
    'ownership': 'state scope_digest step_nonce',
}


class ProjectionError(ValueError):
    def __init__(self, reason='invalid_response'):
        self.reason = reason
        super().__init__(reason)


def require(value):
    if not value:
        raise ProjectionError()


def obj(value, keys):
    require(type(value) is dict and set(value) == set(keys.split() if isinstance(keys, str) else keys))


def text(value, limit=256, *, empty=False, controls=False):
    require(type(value) is str and (empty or bool(value)) and len(value) <= limit)
    require(not any(0xD800 <= ord(c) <= 0xDFFF for c in value))
    if not controls:
        require(not any(ord(c) < 32 or ord(c) == 127 for c in value))


def integer(value, minimum=0):
    require(type(value) is int and minimum <= value <= MAX_INTEGER)


def code(value):
    require(type(value) is str and re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,119}', value))


def one(value, choices):
    require(type(value) is str and value in choices)


def nullable(value, validator):
    if value is not None:
        validator(value)


def uid(value):
    text(value, 36)
    try:
        require(str(uuid.UUID(value)) == value)
    except ValueError as exc:
        raise ProjectionError() from exc


def sha(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{40}', value))


def digest(value):
    require(type(value) is str and re.fullmatch('[0-9a-f]{64}', value))


def timestamp(value):
    require(type(value) is str and len(value) <= 64 and re.fullmatch(
        r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?(?:Z|\+00:00)', value))
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
        require(parsed.utcoffset().total_seconds() == 0)
    except (ValueError, OverflowError) as exc:
        raise ProjectionError() from exc


def array(value, validator, limit=4096):
    require(type(value) is list and len(value) <= limit)
    for item in value:
        validator(item)


def ref(value):
    obj(value, 'source kind id')
    one(value['source'], SOURCES)
    require(type(value['kind']) is str and re.fullmatch('[a-z][a-z0-9_]{0,63}', value['kind']))
    text(value['id'])


def kind_ref(value, kind):
    ref(value)
    require(value['kind'] == kind)
    if kind.startswith('native_'):
        require(value['source'] == 'codex')


def revision(value):
    obj(value, 'kind value')
    one(value['kind'], {'opaque', 'monotonic'})
    text(value['value'])
    if value['kind'] == 'monotonic':
        require(re.fullmatch(r'0|[1-9][0-9]*', value['value']))


def coverage(value):
    obj(value, 'state scope returned_count total_count next_cursor reason')
    one(value['state'], {'complete', 'partial', 'unavailable'})
    text(value['scope'], 512)
    integer(value['returned_count'])
    nullable(value['total_count'], integer)
    nullable(value['next_cursor'], lambda v: text(v, 2048))
    nullable(value['reason'], code)
    require(value['total_count'] is None or value['total_count'] >= value['returned_count'])
    if value['state'] == 'complete':
        require(value['next_cursor'] is None)
        require(value['total_count'] is None or value['total_count'] == value['returned_count'])
    elif value['state'] == 'unavailable':
        require(value['returned_count'] == 0 and value['total_count'] is None and value['next_cursor'] is None)
    if value['state'] != 'complete':
        require(value['reason'] is not None)


def issue_ref(value):
    obj(value, 'repository_id issue_number')
    integer(value['repository_id'], 1)
    integer(value['issue_number'], 1)


def goal_ref(value):
    obj(value, 'repository_id issue_number source_digest')
    integer(value['repository_id'], 1)
    integer(value['issue_number'], 1)
    digest(value['source_digest'])


def parent_ref(value):
    require(type(value) is dict)
    goal_ref(value) if 'source_digest' in value else issue_ref(value)


def requirement_ref(value):
    obj(value, 'repository_id path revision selector')
    integer(value['repository_id'], 1)
    text(value['path'], 512)
    require(not value['path'].startswith(('/', '~')) and '\\' not in value['path'])
    require(all(p not in {'', '.', '..', '.git'} for p in value['path'].split('/')))
    sha(value['revision'])
    text(value['selector'], 160)


def branch(value):
    require(type(value) is str and re.fullmatch(r'hydra/issue-[1-9][0-9]*', value))


def runtime(value):
    obj(value, 'identity_schema package version code_digest code_digest_scope config_digest control_binding_digest identity_reason')
    require(type(value['identity_schema']) is int and value['identity_schema'] == 1)
    require(value['package'] == 'openboa-hydra-sdlc' and value['code_digest_scope'] == 'package_sources_at_startup')
    nullable(value['version'], lambda v: (text(v, 128), require(v.isascii())))
    for key in ('code_digest', 'config_digest', 'control_binding_digest'):
        nullable(value[key], digest)
    nullable(value['identity_reason'], code)


def execution(value):
    obj(value, 'state active_count')
    one(value['state'], {'unobserved', 'running', 'ended'})
    nullable(value['active_count'], integer)


def reported_status(value):
    require(type(value) is str and re.fullmatch('[A-Za-z][A-Za-z0-9_-]{0,119}', value))


def source_value(kind, value):
    require(kind in SOURCE_FIELDS)
    obj(value, SOURCE_FIELDS[kind])
    nref = lambda v: nullable(v, ref)
    refs = lambda v: array(v, ref)
    nrefs = lambda v: nullable(v, refs)
    url = lambda v: text(v, 2048)
    if kind == 'repository':
        integer(value['numeric_id'], 1)
        require(type(value['full_name']) is str and re.fullmatch(
            r'[A-Za-z0-9][A-Za-z0-9-]{0,38}/[A-Za-z0-9_.-]{1,100}', value['full_name']))
        url(value['url'])
        if value['contract_ref'] is not None:
            obj(value['contract_ref'], 'path revision')
            text(value['contract_ref']['path'], 512)
            nullable(value['contract_ref']['revision'], sha)
    elif kind == 'issue':
        integer(value['number'], 1)
        text(value['title'], 512, empty=True, controls=True)
        one(value['state'], {'open', 'closed'})
        url(value['url'])
        nullable(value['work_kind'], lambda v: one(v, {'goal', 'work'}))
        nullable(value['parent_refs'], lambda v: array(v, parent_ref, 100))
        nullable(value['requirement_refs'], lambda v: array(v, requirement_ref, 100))
        nullable(value['description_excerpt'], lambda v: text(v, 4096, empty=True, controls=True))
        nullable(value['description_truncated'], lambda v: require(type(v) is bool))
        require((value['description_excerpt'] is None) == (value['description_truncated'] is None))
    elif kind == 'progress':
        kind_ref(value['issue_ref'], 'issue')
        for key in ('attempt_id', 'native_step'):
            nullable(value[key], uid)
        for key in ('head', 'contract_revision', 'expected_head', 'expected_base', 'published_head'):
            nullable(value[key], sha)
        nullable(value['branch'], branch)
        for key in ('phase', 'wait_reason', 'next_action', 'pending_action', 'cleanup_state'):
            nullable(value[key], code)
        nref(value['pr_ref'])
        nrefs(value['completion_refs'])
    elif kind == 'pull_request':
        integer(value['number'], 1)
        url(value['url'])
        one(value['state'], {'open', 'closed'})
        for key in ('head', 'base', 'merge_commit'):
            nullable(value[key], sha)
        nrefs(value['required_check_refs'])
        nrefs(value['review_refs'])
    elif kind in {'check', 'review'}:
        nref(value['producer'])
        nullable(value['head'], sha)
        nullable(value['url'], url)
        if kind == 'check':
            text(value['name'], 512)
            code(value['status'])
            nullable(value['conclusion'], code)
        else:
            code(value['state'])
            nullable(value['unresolved_count'], integer)
    elif kind in {'native_task_metadata', 'native_history_page'}:
        kind_ref(value['task_ref'], 'native_task')
        require(value['task_ref']['source'] == 'codex')
        if kind == 'native_task_metadata':
            reported_status(value['reported_status'])
        else:
            obj(value['page'], 'order limit has_more')
            require(value['page']['order'] == 'newest_first' and type(value['page']['has_more']) is bool)
            integer(value['page']['limit'], 1)
            turns, messages = set(), set()
            def turn(t):
                obj(t, 'turn_ref reported_status started_at completed_at messages')
                kind_ref(t['turn_ref'], 'native_turn')
                marker = canonical(t['turn_ref'])
                require(marker not in turns)
                turns.add(marker)
                reported_status(t['reported_status'])
                nullable(t['started_at'], timestamp)
                nullable(t['completed_at'], timestamp)
                def message(m):
                    obj(m, 'message_ref message_type')
                    kind_ref(m['message_ref'], 'native_message')
                    one(m['message_type'], {'userMessage', 'agentMessage'})
                    marker = canonical(m['message_ref'])
                    require(marker not in messages)
                    messages.add(marker)
                array(t['messages'], message)
            array(value['turns'], turn)
            require(len(value['turns']) <= value['page']['limit'])
    elif kind == 'native_task':
        kind_ref(value['task_ref'], 'native_task')
        nref(value['assignment_ref'])
        nullable(value['execution'], execution)
        nref(value['question_ref'])
        nrefs(value['schedule_refs'])
        nullable(value['open_ref'], url)
    elif kind == 'native_schedule':
        kind_ref(value['schedule_ref'], 'native_schedule')
        nref(value['task_ref'])
        code(value['status'])
        nullable(value['next_wake_at'], timestamp)
        nullable(value['open_ref'], url)
    elif kind == 'resource':
        ref(value['resource_ref'])
        nref(value['owner_ref'])
        for key in ('activity', 'preservation', 'retirement'):
            nullable(value[key], code)
        nullable(value['open_ref'], url)
    elif kind == 'admission':
        integer(value['revision'])
        one(value['global_mode'], MODES)
        require(type(value['project_overrides']) is dict and len(value['project_overrides']) <= 1024)
        for repository, mode in value['project_overrides'].items():
            require(type(repository) is str and re.fullmatch(r'[a-z0-9][a-z0-9-]{0,38}/[a-z0-9_.-]{1,100}', repository))
            one(mode, MODES)
        nullable(value['gate_reason'], code)
    elif kind == 'ownership':
        one(value['state'], {'free', 'absent', 'owned', 'busy', 'native', 'unknown'})
        nullable(value['scope_digest'], digest)
        nullable(value['step_nonce'], uid)


def progress_source_value(record, issue_ref, repository):
    value = {key: None for key in SOURCE_FIELDS['progress'].split()}
    value['issue_ref'] = issue_ref
    for key in ('attempt_id', 'phase', 'native_step', 'head', 'contract_revision', 'branch',
                'expected_head', 'expected_base', 'published_head', 'wait_reason',
                'next_action', 'pending_action'):
        value[key] = record.get(key)
    number = record.get('pr_number')
    if type(number) is int and 1 <= number <= MAX_INTEGER:
        value['pr_ref'] = {'source': 'github', 'kind': 'pull_request', 'id': repository + ':' + str(number)}
    source_value('progress', value)
    return value


def observation(value):
    obj(value, 'key resource revision observed_at last_attempt_at availability coverage reason value')
    text(value['key'], 512)
    ref(value['resource'])
    require(value['resource']['kind'] in SOURCE_FIELDS)
    require(value['resource']['source'] == SOURCE_OWNERS[value['resource']['kind']])
    nullable(value['revision'], revision)
    nullable(value['observed_at'], timestamp)
    timestamp(value['last_attempt_at'])
    one(value['availability'], {'current', 'stale', 'unavailable', 'unsupported'})
    coverage(value['coverage'])
    nullable(value['reason'], code)
    if value['availability'] == 'current':
        require(value['coverage']['state'] != 'unavailable')
    if value['availability'] in {'current', 'stale'}:
        require(value['observed_at'] is not None and value['value'] is not None)
        source_value(value['resource']['kind'], value['value'])
        if value['resource']['kind'] == 'admission':
            require(value['revision'] == {'kind': 'monotonic', 'value': str(value['value']['revision'])})
        elif value['resource']['kind'] == 'repository':
            require(value['resource']['id'] == str(value['value']['numeric_id']))
        elif value['resource']['kind'] == 'issue':
            locator = re.fullmatch(r'([1-9][0-9]*):([1-9][0-9]*)', value['resource']['id'])
            require(locator is not None)
            integer(int(locator[1]), 1)
            integer(int(locator[2]), 1)
            require(int(locator[2]) == value['value']['number'])
    else:
        require(value['value'] is None and value['observed_at'] is None and value['reason'] is not None)
        require(value['coverage']['state'] == 'unavailable')
    if value['resource']['kind'] in {'native_task_metadata', 'native_history_page'}:
        require(value['revision'] is None)
        if value['value'] is not None:
            c = value['coverage']
            if value['resource']['kind'] == 'native_task_metadata':
                require(c['state'] == 'complete' and c['returned_count'] == c['total_count'] == 1)
            else:
                page = value['value']['page']
                require(c['state'] == 'partial' and c['total_count'] is None
                        and c['returned_count'] == len(value['value']['turns']))
                require(c['reason'] == ('more_pages' if page['has_more'] else 'history_scope_unverified'))
                require((c['next_cursor'] is not None) == page['has_more'])


def evidence(value):
    obj(value, 'observation_key revision')
    text(value['observation_key'], 512)
    nullable(value['revision'], revision)


def fact(value, validator, observations):
    obj(value, 'value evidence reason')
    array(value['evidence'], evidence)
    nullable(value['reason'], code)
    seen = set()
    for item in value['evidence']:
        key = item['observation_key']
        require(key not in seen and key in observations and observations[key]['revision'] == item['revision'])
        seen.add(key)
        if value['value'] is not None:
            require(observations[key]['availability'] == 'current'
                    and observations[key]['coverage']['state'] == 'complete')
    if value['value'] is not None:
        require(bool(seen) and value['reason'] is None)
        validator(value['value'])
    else:
        require(value['reason'] is not None)


def _repository_name(value):
    if type(value) is not str or not value.isascii():
        return None
    name = value.lower()
    return name if re.fullmatch(r'[a-z0-9][a-z0-9-]{0,38}/[a-z0-9_.-]{1,100}', name) else None


def repository_names(repository, observations):
    """Resolve display context only; retained identity never grants an effect."""
    kind_ref(repository, 'repository')
    require(repository['source'] == 'github')
    identifier = repository['id']
    if identifier.startswith('requested:'):
        name = _repository_name(identifier[10:])
        require(name is not None)
        return {name}
    require(re.fullmatch(r'[1-9][0-9]*', identifier) is not None)
    integer(int(identifier), 1)
    names, fallback = set(), set()
    for observed in observations.values():
        if observed['resource'] != repository:
            continue
        requested = []
        for field, prefix in ((observed['key'], 'github:repository-request:'),
                              (observed['coverage']['scope'], 'repository-address:')):
            if field.startswith(prefix):
                name = _repository_name(field[len(prefix):])
                if name is None:
                    return set()
                requested.append(name)
        if len(set(requested)) > 1:
            return set()
        if requested:
            names.update(requested)
        elif observed['value'] is not None:
            name = _repository_name(observed['value']['full_name'])
            if name is not None:
                fallback.add(name)
    return names or fallback


def issue_repository(issue):
    kind_ref(issue, 'issue')
    require(issue['source'] == 'github')
    locator = re.fullmatch(r'([1-9][0-9]*):([1-9][0-9]*)', issue['id'])
    require(locator is not None)
    integer(int(locator[1]), 1)
    integer(int(locator[2]), 1)
    return {'source': 'github', 'kind': 'repository', 'id': locator[1]}


def admission_fact(value, observations, names, binding):
    fact(value, lambda w: one(w, {'allowed', 'paused', 'stopped'}), observations)
    if value['value'] is not None:
        sources = [observations[e['observation_key']] for e in value['evidence']
                   if observations[e['observation_key']]['resource']['source'] == 'hydra'
                   and observations[e['observation_key']]['resource']['kind'] == 'admission']
        require(bool(sources) and binding is not None)
        for observed in sources:
            require(observed['resource']['id'] == binding)
            snapshot = observed['value']
            mode = snapshot['global_mode']
            if mode == 'running':
                require(bool(names))
                modes = {snapshot['project_overrides'].get(name, 'running') for name in names}
                require(len(modes) == 1)
                mode = next(iter(modes))
            require(value['value'] == {'running': 'allowed', 'paused': 'paused', 'stopped': 'stopped'}[mode])


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False)


def read_json(data):
    if isinstance(data, str):
        data = data.encode('utf-8')
    require(type(data) is bytes and len(data) <= MAX_BYTES)
    def pairs(entries):
        value = {}
        for key, item in entries:
            require(key not in value)
            value[key] = item
        return value
    def invalid(_):
        raise ProjectionError()
    try:
        return json.loads(data.decode('utf-8'), object_pairs_hook=pairs, parse_constant=invalid)
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise ProjectionError() from exc


def evidence_of(observed):
    return {'observation_key': observed['key'], 'revision': copy.deepcopy(observed['revision'])}


def unknown(reason, observed=()):
    code(reason)
    return {'value': None, 'evidence': [evidence_of(o) for o in observed], 'reason': reason}


def known(value, observed):
    require(observed and all(o['availability'] == 'current' and o['coverage']['state'] == 'complete'
                             for o in observed))
    return {'value': copy.deepcopy(value), 'evidence': [evidence_of(o) for o in observed], 'reason': None}


def unknown_decision():
    return {name: unknown('decision_provenance_unverified')
            for name in ('question', 'answer', 'acceptance', 'application')}


def readiness(value):
    obj(value, 'disposition source_ref source_revision interpretation_ref binding_ref extracted missing authority trust_reason')
    one(value['disposition'], {'actionable', 'needs_info', 'propose', 'quarantined'})
    ref(value['source_ref'])
    nullable(value['source_revision'], revision)
    nullable(value['interpretation_ref'], ref)
    nullable(value['binding_ref'], ref)
    obj(value['extracted'], 'purpose_excerpt requirement_refs scope_excerpt')
    for key in ('purpose_excerpt', 'scope_excerpt'):
        nullable(value['extracted'][key], lambda v: text(v, 1024, empty=True, controls=True))
    array(value['extracted']['requirement_refs'], requirement_ref, 100)
    def missing(item):
        obj(item, 'code detail owner_ref')
        code(item['code'])
        text(item['detail'], 1024, empty=True, controls=True)
        nullable(item['owner_ref'], ref)
    array(value['missing'], missing, 100)
    one(value['authority'], {'confirmed', 'missing', 'unknown'})
    nullable(value['trust_reason'], code)


def unmapped_fact(value, validator, observations):
    fact(value, validator, observations)
    require(value['value'] is None)


def readiness_fact(value, observations, issue):
    fact(value, readiness, observations)
    if value['value'] is None:
        return
    v = value['value']
    # The implemented mapping exposes a visible, uninterpreted Issue proposal.
    # Accepted authority and extracted requirements need their own source mapping.
    require(v['source_ref'] == issue and v['disposition'] == 'propose'
            and v['authority'] == 'unknown' and v['interpretation_ref'] is None
            and v['binding_ref'] is None)
    require(v['extracted'] == {'purpose_excerpt': None, 'requirement_refs': [], 'scope_excerpt': None})
    require(any(observations[e['observation_key']]['resource'] == issue
                and issue['source'] == 'github' and issue['kind'] == 'issue'
                and observations[e['observation_key']]['revision'] == v['source_revision']
                for e in value['evidence']))


def project_work_refs(values, repository):
    array(values, lambda item: require(issue_repository(item) == repository), 128)
    require(len({canonical(item) for item in values}) == len(values))


def parent_relation(value, observations):
    obj(value, 'from to kind evidence')
    issue_repository(value['from']); issue_repository(value['to'])
    require(value['kind'] == 'parent')
    fact({'value': 'relation', 'evidence': value['evidence'], 'reason': None}, lambda _: None, observations)
    require(any(o['resource'] == value['from'] and o['resource']['kind'] == 'issue'
                and any(value['to'] == {'source': 'github', 'kind': 'issue',
                        'id': str(parent['repository_id']) + ':' + str(parent['issue_number'])}
                        for parent in (o['value']['parent_refs'] or []))
                for e in value['evidence'] for o in [observations[e['observation_key']]]))


def decision(value, observations):
    obj(value, 'question answer acceptance application')
    # No implemented SourceValue mapping qualifies a decision axis. A typed
    # value or capability claim cannot substitute for that missing mapping.
    for key in ('question', 'answer', 'acceptance', 'application'):
        fact(value[key], lambda _: require(False), observations)


def wait(value):
    if value == 'none':
        return
    obj(value, 'kind owner_ref wake_ref reason')
    one(value['kind'], {'human', 'external', 'resource'})
    nullable(value['owner_ref'], ref)
    nullable(value['wake_ref'], ref)
    code(value['reason'])


def next_action(value, observations):
    obj(value, 'code target_ref rationale_excerpt evidence')
    code(value['code'])
    nullable(value['target_ref'], ref)
    text(value['rationale_excerpt'], 1024, empty=True, controls=True)
    # Nested guidance references have the same frame boundary as its Fact.
    fact({'value': 'candidate', 'evidence': value['evidence'], 'reason': None},
         lambda v: None, observations)


def assignment(value):
    obj(value, 'attempt_id step_id head contract_revision spec_revision')
    uid(value['attempt_id'])
    uid(value['step_id'])
    sha(value['head'])
    sha(value['contract_revision'])
    nullable(value['spec_revision'], sha)


def candidate(value):
    obj(value, 'attempt_id head contract_revision')
    uid(value['attempt_id'])
    sha(value['head'])
    sha(value['contract_revision'])


def target(value, action):
    if action == 'admission_set':
        require(type(value) is dict)
        if value.get('kind') == 'host':
            obj(value, 'kind')
        else:
            obj(value, 'kind repository_id')
            require(value['kind'] == 'repository')
            integer(value['repository_id'], 1)
    elif action in {'workflow_step', 'work_create'}:
        obj(value, 'repository_id issue_number' if action == 'workflow_step' else 'repository_id')
        for item in value.values():
            integer(item, 1)
    elif action == 'cleanup':
        obj(value, 'kind repository_id issue_number source_attempt resource')
        require(value['kind'] == 'owned_resource')
        integer(value['repository_id'], 1)
        integer(value['issue_number'], 1)
        uid(value['source_attempt'])
        ref(value['resource'])
    else:
        ref(value)


def command_result(value, observations):
    obj(value, 'request_id action target outcome reason effect_refs observed_refs receipt required_next')
    uid(value['request_id'])
    one(value['action'], {'admission_set', 'work_create', 'workflow_step', 'native_control', 'cleanup', 'open_record'})
    target(value['target'], value['action'])
    one(value['outcome'], {'applied', 'waiting', 'rejected', 'unknown'})
    nullable(value['reason'], code)
    array(value['effect_refs'], ref)
    array(value['observed_refs'], evidence)
    for e in value['observed_refs']:
        require(e['observation_key'] in observations and observations[e['observation_key']]['revision'] == e['revision'])
    one(value['required_next'], {'none', 'refresh', 'reconcile', 'open_source'})
    if value['receipt'] is not None:
        receipt(value['receipt'], observations)
    if value['outcome'] == 'applied' and value['action'] in {'workflow_step', 'cleanup'}:
        require(value['receipt'] is not None)
    if value['outcome'] == 'applied' and value['receipt'] is not None:
        if value['receipt']['kind'] == 'publication':
            require(value['receipt']['stage'] == 'publication_ready')
        if value['receipt']['kind'] == 'delivery':
            require(value['receipt']['post_merge'] == 'success' and value['receipt']['issue_closed'] is True)
    if value['action'] == 'admission_set' or (
            value['receipt'] is not None and value['receipt']['kind'] in {'checkpoint', 'decision'}):
        require((value['receipt'] is not None) == (value['outcome'] == 'applied'))
    if value['receipt'] is not None:
        kind = value['receipt']['kind']
        if value['action'] == 'cleanup':
            require(value['receipt']['resource'] == value['target']['resource'])
        require((value['action'] == 'admission_set' and kind == 'admission') or
                (value['action'] == 'workflow_step' and kind in {'checkpoint', 'decision', 'continuation',
                 'verification', 'verification_review', 'publication', 'delivery'}) or
                (value['action'] == 'cleanup' and kind == 'cleanup'))

    if value['action'] == 'workflow_step' and value['receipt'] is not None and 'progress_ref' in value['receipt']:
        progress = value['receipt']['progress_ref']
        expected = str(value['target']['repository_id']) + ':' + str(value['target']['issue_number'])
        require(progress['source'] == 'github')
        if progress['kind'] == 'progress':
            require(progress['id'] == expected)
        else:
            require(progress['kind'] == 'issue_comment')
            proofs = [observations[e['observation_key']] for e in value['observed_refs']
                if observations[e['observation_key']]['resource'] ==
                   {'source': 'github', 'kind': 'progress', 'id': progress['id']}]
            require(len(proofs) == 1)
            proof = proofs[0]
            require(proof['availability'] == 'current' and proof['coverage']['state'] == 'complete'
                    and proof['value'] is not None and proof['value']['issue_ref'] ==
                    {'source': 'github', 'kind': 'issue', 'id': expected})


def receipt(value, observations):
    require(type(value) is dict)
    kind = value.get('kind')
    fields = {
        'admission': 'kind readback',
        'checkpoint': 'kind assignment outcome checkpoint_head progress_ref step_retired ticket_released',
        'decision': 'kind source_attempt round intent_ref context_ref resolved_ref resume_attempt',
        'continuation': 'kind progress_ref attempt_id head contract_revision boundary',
        'verification': 'kind candidate verdict review progress_ref evidence_refs',
        'verification_review': 'kind candidate assignment review progress_ref evidence_refs step_retired ticket_released',
        'publication': 'kind candidate branch observed_remote_head pr_ref review_request_refs progress_ref stage',
        'delivery': 'kind candidate pr_ref integration_base merge_commit post_merge issue_closed progress_ref',
        'cleanup': 'kind resource operation result evidence_refs',
    }
    require(kind in fields)
    obj(value, fields[kind])
    if kind == 'admission':
        e = value['readback']
        evidence(e)
        require(e['observation_key'] in observations)
        observed = observations[e['observation_key']]
        require(observed['revision'] == e['revision'] and observed['availability'] == 'current'
                and observed['coverage']['state'] == 'complete' and observed['resource']['kind'] == 'admission')
    if kind == 'checkpoint':
        assignment(value['assignment'])
        one(value['outcome'], {'stopped', 'candidate_ready', 'failed', 'needs_decision'})
        sha(value['checkpoint_head'])
    if kind in {'checkpoint', 'verification_review'}:
        require(value['step_retired'] is True and value['ticket_released'] is True)
    if kind == 'decision':
        uid(value['source_attempt'])
        integer(value['round'], 1)
        uid(value['resume_attempt'])
        for key in ('intent_ref', 'context_ref', 'resolved_ref'):
            ref(value[key])
    if kind == 'continuation':
        uid(value['attempt_id'])
        sha(value['head'])
        sha(value['contract_revision'])
        one(value['boundary'], {'progress_recorded', 'assignment_returned', 'existing_result_reconciled'})
    if kind in {'verification', 'verification_review', 'publication', 'delivery'}:
        candidate(value['candidate'])
    if kind == 'verification':
        one(value['verdict'], {'passed', 'failed'})
        nullable(value['review'], lambda v: one(v, {'pending', 'accepted', 'failed', 'not_required'}))
    if kind == 'verification_review':
        assignment(value['assignment'])
        require(all(value['assignment'][k] == value['candidate'][k] for k in ('attempt_id', 'head', 'contract_revision')))
        one(value['review'], {'accepted', 'failed', 'pending'})
    if kind == 'publication':
        branch(value['branch'])
        sha(value['observed_remote_head'])
        require(value['observed_remote_head'] == value['candidate']['head'])
        nullable(value['pr_ref'], ref)
        array(value['review_request_refs'], ref)
        one(value['stage'], {'branch_published', 'pr_ready', 'publication_ready'})
        require(value['stage'] == 'branch_published' or value['pr_ref'] is not None)
    if kind == 'delivery':
        ref(value['pr_ref'])
        sha(value['integration_base'])
        sha(value['merge_commit'])
        one(value['post_merge'], {'pending', 'success', 'failed', 'unknown'})
        nullable(value['issue_closed'], lambda v: require(type(v) is bool))
    if kind == 'cleanup':
        ref(value['resource'])
        one(value['operation'], {'preserve', 'archive', 'retire', 'remove_schedule'})
        require(value['result'] == {'preserve': 'preserved', 'archive': 'archived',
                'retire': 'retired', 'remove_schedule': 'schedule_removed'}[value['operation']])
        require(bool(value['evidence_refs']))
    if 'evidence_refs' in value:
        array(value['evidence_refs'], ref)
    if 'progress_ref' in value:
        ref(value['progress_ref'])


def observations_index(values):
    array(values, observation)
    indexed = {v['key']: v for v in values}
    require(len(indexed) == len(values))
    return indexed


def bound_command_result(value, observations, binding):
    command_result(value, observations)
    receipt = value['receipt']
    if receipt is not None and receipt['kind'] == 'admission':
        source = observations[receipt['readback']['observation_key']]
        require(binding is not None and source['resource'] ==
                {'source': 'hydra', 'kind': 'admission', 'id': binding})


def standard_reply(value):
    # A native handoff is never traversed, cached, echoed or downgraded here.
    require(type(value) is dict)
    if 'reply_profile' in value or 'handoff' in value:
        raise ProjectionError('unsupported_reply_profile')
    obj(value, 'command_schema runtime binding_epoch request observations')
    require(type(value['command_schema']) is int and value['command_schema'] == 1)
    runtime(value['runtime'])
    nullable(value['binding_epoch'], uid)
    bound_command_result(value['request'], observations_index(value['observations']),
                         value['runtime']['control_binding_digest'])
    return value


def validate_frame(value):
    obj(value, 'schema_version runtime binding_epoch request_id assembled_at observations projects work relations page capabilities retry_hints request')
    require(type(value['schema_version']) is int and value['schema_version'] == 3)
    runtime(value['runtime'])
    uid(value['binding_epoch'])
    uid(value['request_id'])
    timestamp(value['assembled_at'])
    observations = observations_index(value['observations'])
    seen_hints = set()
    def retry_hint(v):
        obj(v, 'observation_key scope after_seconds basis')
        text(v['observation_key'], 512)
        text(v['scope'])
        integer(v['after_seconds'])
        one(v['basis'], {'provider', 'fallback'})
        marker = (v['observation_key'], v['scope'])
        require(marker not in seen_hints and v['observation_key'] in observations)
        seen_hints.add(marker)
        source = observations[v['observation_key']]
        require(source['availability'] != 'unsupported')
        require(source['availability'] in {'unavailable', 'stale'}
                or source['coverage']['state'] != 'complete'
                or source['reason'] in {'rate_limited', 'provider_wait'})
    array(value['retry_hints'], retry_hint)
    def project(v):
        obj(v, 'repository_ref goal_refs work_refs admission execution attention_refs coverage source_refs')
        kind_ref(v['repository_ref'], 'repository')
        array(v['goal_refs'], goal_ref, 100)
        project_work_refs(v['work_refs'], v['repository_ref'])
        admission_fact(v['admission'], observations, repository_names(v['repository_ref'], observations),
                       value['runtime']['control_binding_digest'])
        unmapped_fact(v['execution'], execution, observations)
        array(v['attention_refs'], ref)
        coverage(v['coverage'])
        array(v['source_refs'], ref)
    array(value['projects'], project, 1024)
    require(len({canonical(v['repository_ref']) for v in value['projects']}) == len(value['projects']))
    def work(v):
        obj(v, 'issue_ref goal_refs spec_refs requirement_refs readiness stage admission execution wait decision delivery result cleanup next_action task_refs resource_refs evidence_refs')
        kind_ref(v['issue_ref'], 'issue')
        array(v['goal_refs'], goal_ref, 100)
        array(v['spec_refs'], requirement_ref, 100)
        array(v['requirement_refs'], requirement_ref, 100)
        facts = {
            'readiness': readiness,
            'stage': lambda w: one(w, {'prepare', 'design', 'implement', 'verify', 'deliver', 'observe', 'complete'}),
            'execution': execution, 'wait': wait,
            'delivery': lambda w: one(w, {'candidate', 'published', 'merged', 'post_merge_verified', 'deployment_observed'}),
            'result': lambda w: one(w, {'incomplete', 'complete', 'cancelled'}),
            'cleanup': lambda w: one(w, {'not_required', 'pending', 'complete'}),
            'next_action': lambda w: next_action(w, observations),
        }
        for key, validator in facts.items():
            if key == 'readiness':
                readiness_fact(v[key], observations, v['issue_ref'])
            else:
                unmapped_fact(v[key], validator, observations)
        admission_fact(v['admission'], observations, repository_names(issue_repository(v['issue_ref']), observations),
                       value['runtime']['control_binding_digest'])
        decision(v['decision'], observations)
        array(v['task_refs'], ref)
        array(v['resource_refs'], ref)
        array(v['evidence_refs'], evidence)
        for e in v['evidence_refs']:
            require(e['observation_key'] in observations and observations[e['observation_key']]['revision'] == e['revision'])
    array(value['work'], work, 512)
    require(len({canonical(v['issue_ref']) for v in value['work']}) == len(value['work']))
    array(value['relations'], lambda v: parent_relation(v, observations))
    coverage(value['page'])
    def capability(v):
        obj(v, 'source operation state actor qualification_ref reason')
        one(v['source'], SOURCES)
        text(v['operation'])
        one(v['state'], {'available', 'unsupported', 'unavailable'})
        one(v['actor'], {'core', 'native_actor', 'provider'})
        nullable(v['qualification_ref'], lambda w: text(w, 2048))
        nullable(v['reason'], code)
        if v['state'] == 'available':
            require(v['qualification_ref'] is not None and v['reason'] is None)
        else:
            require(v['reason'] is not None)
    array(value['capabilities'], capability)
    if value['request'] is not None:
        bound_command_result(value['request'], observations, value['runtime']['control_binding_digest'])
    return value


def encode(value):
    try:
        validate_frame(value)
        data = canonical(value).encode('utf-8')
        if len(data) > MAX_BYTES:
            raise ProjectionError('response_limit')
        return data
    except (TypeError, UnicodeError, RecursionError) as exc:
        raise ProjectionError() from exc
