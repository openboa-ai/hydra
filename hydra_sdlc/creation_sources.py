"""Fresh GitHub creation inputs. Source data never supplies caller authority."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import hashlib
import json
import re

from .github import GitHubError
from .github_work_drafts import read_work_draft
from .operations import OperationDenied
from .project import load_project
from .work_drafts import _draft_from_comment, parse_draft_ref
from .work_records import (WorkRecordError, _canonical, _decode_marker, _hex,
    _input_contract, _integer, _issue_ref, _object, _path, _requirements,
    _unchanged, source_digest)


PROPOSAL_KEYS = {'kind', 'outcome', 'requirements', 'spec', 'input_contract', 'delegation_ref'}
MAX_SOURCE_BYTES = 8_000_000


def require(value, reason='creation_source_unavailable'):
    if not value:
        raise OperationDenied(reason)


def digest(value):
    return hashlib.sha256(_canonical(value).encode('utf-8')).hexdigest()


def bounded(value):
    require(len(_canonical(value).encode('utf-8')) <= MAX_SOURCE_BYTES)
    return value


@contextmanager
def credential_guard(client, expected=None):
    previous = client._credential_selected
    local = client.__dict__.get('_credential_selected')
    had_local = '_credential_selected' in client.__dict__
    selected = expected

    def chosen(fingerprint):
        nonlocal selected
        previous(fingerprint)
        require(type(fingerprint) is bytes and bool(fingerprint))
        if selected is None:
            selected = fingerprint
        require(selected == fingerprint, 'creation_credential_changed')

    client._credential_selected = chosen
    try:
        yield
    finally:
        if had_local:
            client._credential_selected = local
        else:
            del client._credential_selected


def outside_draft(body):
    """Exclude the complete JSON-framed payload, including quoted markers."""
    require(type(body) is str and len(body.encode('utf-8')) <= MAX_SOURCE_BYTES)
    prefix = '<!-- hydra-create-draft:v1 '
    start = body.find(prefix)
    if start < 0:
        return body
    tail = body[start + len(prefix):]
    offset = len(tail) - len(tail.lstrip())
    _, end = json.JSONDecoder().raw_decode(tail, offset)
    remainder = tail[end:]
    whitespace = len(remainder) - len(remainder.lstrip())
    require(remainder[whitespace:].startswith('-->'))
    return body[:start] + remainder[whitespace + 3:]


def proposal_from_comment(body, spec_directory):
    value = _decode_marker(outside_draft(body), 'hydra-work-proposal', 'v1', 32768)
    _object(value, PROPOSAL_KEYS)
    require(type(value['kind']) is str and value['kind'] in {'goal', 'work'})
    require(type(value['outcome']) is str and re.fullmatch('[a-z0-9][a-z0-9-]{0,63}', value['outcome']))
    _requirements(value['requirements'])
    # The created Issue is not known yet. Its self-producer check runs again
    # against the actual Issue when constructing the final binding.
    _input_contract(value['input_contract'], None)
    spec = value['spec']
    if spec is not None:
        _object(spec, {'path', 'revision'})
        require(_path(spec['path']) and (spec['revision'] is None or _hex(spec['revision'], 40)))
        if value['kind'] == 'work':
            require(spec['path'].startswith(spec_directory + '/') and spec['path'].endswith('/spec.md'))
    require(value['delegation_ref'] is None or type(value['delegation_ref']) is str)
    return value


def outcome_key(repository_id, proposal, goal, source):
    return digest({'repository_id': repository_id, 'delegated_goal': goal,
        'source': None if goal is not None else source,
        'requirements': sorted(proposal['requirements'], key=_canonical),
        'outcome': proposal['outcome']})


def policy_semantics(policy):
    return {key: value for key, value in policy.items() if key != 'revision'}


def _actor(value):
    require(type(value) is dict and _integer(value.get('id')) and value.get('login') == 'openboa')
    return {'id': value['id'], 'login': value['login']}


def owned_comment(value, actor, repository, number):
    require(type(value) is dict and _integer(value.get('id')))
    user = value.get('user')
    require(type(user) is dict and type(user.get('id')) is int
            and user['id'] == actor['id'] and user.get('login') == actor['login'])
    root = 'https://api.github.com/repos/' + repository
    require(value.get('issue_url') == root + '/issues/' + str(number)
            and value.get('url') == root + '/issues/comments/' + str(value['id']))
    _unchanged(value)
    return value


@dataclass(frozen=True, repr=False)
class CreationSource:
    draft: object = field(repr=False)
    reference: dict = field(repr=False)
    proposal: dict = field(repr=False)
    repository: str
    repositories: dict = field(repr=False)
    actor: dict = field(repr=False)
    policy: dict = field(repr=False)
    conditions: object = field(repr=False)
    credential: bytes = field(repr=False)
    signature: str


def read_source(client, names, command):
    """Reobserve the exact public source; no cache, effects or default grant."""
    reference = parse_draft_ref(command['parameters']['draft_ref']).value
    require(reference['kind'] == 'github_comment', 'unsupported_operation')
    with client.read_budget(seconds=45, requests=128), credential_guard(client):
        actor = _actor(bounded(client._identity()))
        credential = client._authenticated_fingerprint
        require(type(credential) is bytes and bool(credential))
        repos = {}

        def repository(identifier):
            if identifier in repos:
                return repos[identifier]
            for name in names:
                if any(row['full_name'].casefold() == name.casefold() for row in repos.values()):
                    continue
                try:
                    row = bounded(client.repository(name))
                except GitHubError:
                    continue
                require(type(row.get('id')) is int and row['id'] > 0
                        and row.get('full_name', '').casefold() == name.casefold()
                        and type(row.get('private')) is bool)
                repos[row['id']] = row
                if row['id'] == identifier:
                    return row
            raise OperationDenied('creation_repository_unavailable')

        target = repository(command['target']['repository_id'])
        container = repository(reference['repository_id'])
        root = 'https://api.github.com/repos/' + container['full_name']
        raw = bounded(client.api('GET', '/repos/' + container['full_name'] +
                                 '/issues/comments/' + str(reference['comment_id'])))
        draft = _draft_from_comment(raw, reference, actor, root)
        value = draft.value
        require(value['create_key'] == command['effect_key'], 'creation_payload_conflict')
        require(draft.digest == command['parameters']['draft_digest'], 'creation_payload_conflict')
        check = command['expected']['source_checks'][0]
        require(check['resource'] == {'source': 'github', 'kind': 'issue_comment',
                    'id': container['full_name'] + '/comments/' + str(reference['comment_id'])}
                and check['actionable_digest'] == reference['revision'], 'creation_source_changed')
        policy = load_project(client, target['full_name'])
        proposal = proposal_from_comment(raw['body'], policy['spec_directory'])
        origin = value['source_ref']
        require(origin['kind'] == 'github_issue', 'unsupported_operation')
        needed = {value['target_repository_id'], reference['repository_id'], origin['repository_id']}
        if value['goal'] is not None:
            needed.add(value['goal']['repository_id'])
        needed.update(row['repository_id'] for row in proposal['requirements'])
        references = list(proposal['requirements'])
        contract = proposal['input_contract']
        if contract is not None and contract['kind'] == 'reference':
            needed.add(contract['ref']['repository_id'])
            references.append(contract['ref'])
        for identifier in sorted(needed):
            repository(identifier)
        result = read_work_draft(client, {k: repos[k]['full_name'] for k in needed},
            reference, author=actor, target_repository_id=target['id'], draft_digest=draft.digest)
        require(result.status == 'available' and result.source.draft.document == draft.document,
                'creation_source_changed' if result.status == 'changed' else 'creation_source_unavailable')
        goal = value['goal'] or origin
        owner = repository(goal['repository_id'])
        ref = proposal['delegation_ref']
        match = re.fullmatch(r'https://github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)#issuecomment-([1-9][0-9]*)', ref or '')
        require(match is not None and match[1].casefold() == owner['full_name'].casefold()
                and int(match[2]) == goal['issue_number'], 'creation_authority_unknown')
        declaration = bounded(client.api('GET', '/repos/' + owner['full_name'] + '/issues/comments/' + match[3]))
        require(type(declaration) is dict and declaration.get('id') == int(match[3])
                and declaration.get('issue_url') == 'https://api.github.com/repos/' + owner['full_name'] + '/issues/' + str(goal['issue_number'])
                and declaration.get('url') == 'https://api.github.com/repos/' + owner['full_name'] + '/issues/comments/' + match[3],
                'creation_authority_unknown')
        _unchanged(declaration)
        author = declaration.get('user') or {}
        require(_integer(author.get('id')) and author['id'] != actor['id']
                and author.get('type') == 'User' and not declaration.get('performed_via_github_app'),
                'creation_authority_unknown')
        current = policy if owner['full_name'] == target['full_name'] else load_project(client, owner['full_name'])
        require(author.get('login') in current['authorized_actors']
                and author.get('login') in policy['authorized_actors'], 'creation_authority_unknown')
        payload = _decode_marker(declaration.get('body'), 'hydra-delegation', 'v1', 32768)
        _object(payload, {'goal', 'goal_digest', 'contract_revision', 'actions'})
        _issue_ref(payload['goal'])
        actions = payload['actions']
        require(type(actions) is list and bool(actions)
                and all(type(a) is str and a in {'prepare', 'create_work', 'execute_work'} for a in actions)
                and len(set(actions)) == len(actions) and 'create_work' in actions
                and payload['goal'] == {k: goal[k] for k in ('repository_id', 'issue_number')}
                and _hex(payload['contract_revision'], 40), 'creation_authority_unknown')
        goal_issue = bounded(client.issue(owner['full_name'], goal['issue_number']))
        require(type(goal_issue) is dict and goal_issue.get('number') == goal['issue_number']
                and goal_issue.get('url') == 'https://api.github.com/repos/' + owner['full_name'] + '/issues/' + str(goal['issue_number'])
                and goal_issue.get('repository_url') == 'https://api.github.com/repos/' + owner['full_name']
                and 'pull_request' not in goal_issue and payload['goal_digest'] == source_digest(goal_issue)
                and payload['goal_digest'] == (value['goal']['source_digest'] if value['goal'] else value['source_digest']),
                'creation_source_changed')
        require(bool(re.sub(r'<!-- hydra-delegation:v1 .*? -->', '', declaration['body'], flags=re.S).strip()),
                'creation_authority_unknown')
        accepted = (current if payload['contract_revision'] == current['revision'] else
                    load_project(client, owner['full_name'], revision=payload['contract_revision']))
        require(policy_semantics(current) == policy_semantics(accepted), 'creation_policy_changed')
        require(len(needed) == 1 or all(not repos[k]['private'] and repos[k].get('visibility') == 'public'
                                     for k in needed), 'disclosure_policy_unavailable')
        files = {}
        def read_file(reference_source):
            key = tuple(reference_source[k] for k in ('repository_id', 'revision', 'path'))
            if key not in files:
                try:
                    row = client.immutable_file_source(repository(key[0])['full_name'], key[2], key[1],
                                                       repository_id=key[0])
                except (GitHubError, WorkRecordError):
                    raise OperationDenied('creation_reference_unavailable') from None
                files[key] = row
                require(sum(len(item['content'].encode('utf-8')) for item in files.values()) <= MAX_SOURCE_BYTES)
            return files[key]
        conditions = None
        if contract is not None:
            from .work_inputs import InputConditions, _reference_payload
            payload = ({'clauses': contract['clauses']} if contract['kind'] == 'adopted' else
                _reference_payload(read_file(contract['ref'])['content'], contract['ref']['selector']))
            _object(payload, {'clauses'})
            _input_contract({'kind': 'adopted', **payload}, None)
            conditions = InputConditions(_canonical(payload))
            for clause in conditions.value['clauses']:
                needed.update([clause['producer']['repository_id'], clause['basis']['repository_id']])
                needed.update(row['repository_id'] for row in clause['requirements'])
                references.extend([clause['basis'], *clause['requirements']])
        for identifier in sorted(needed):
            repository(identifier)
        require(len(needed) == 1 or all(not repos[k]['private'] and repos[k].get('visibility') == 'public'
                                     for k in needed), 'disclosure_policy_unavailable')
        spec = proposal['spec']
        if spec is not None and spec['revision'] is not None:
            references.append({'repository_id': target['id'], **spec})
        for reference_source in references:
            read_file(reference_source)
        source = {**origin, 'source_digest': value['source_digest']}
        require(value['outcome_key'] == outcome_key(target['id'], proposal, value['goal'], source),
                'creation_payload_conflict')
        client._request_timeout(45)
        require(client._authenticated_fingerprint == credential, 'creation_credential_changed')
        signature = digest({'draft': value, 'reference': reference, 'proposal': proposal,
            'policy': policy_semantics(policy), 'delegation_policy': policy_semantics(current),
            'declaration_id': declaration['id'], 'declaration_digest': hashlib.sha256(declaration['body'].encode()).hexdigest(),
            'declaration_actor': {'id': author['id'], 'login': author['login']},
            'reference_sources': [{k: row[k] for k in ('repository_id', 'path', 'revision', 'sha')}
                                  for _, row in sorted(files.items())],
            'reference_input_digest': conditions.digest if conditions is not None else None,
            'repositories': [{k: repos[rid][k] for k in ('id', 'full_name', 'private')} for rid in sorted(needed)]})
        return CreationSource(draft, reference, proposal, target['full_name'],
            {k: repos[k]['full_name'] for k in needed}, actor, policy, conditions, credential, signature)
