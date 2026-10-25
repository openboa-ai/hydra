"""One fenced Issue/binding sequence. No assignment, cache or retry journal."""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import os
import re
import threading
import uuid

from . import projection as p
from .creation_sources import (bounded, credential_guard, digest, outcome_key,
    outside_draft, owned_comment, read_source, require)
from .coordinator import coordinator_lock
from .creation_history import HistoryGuard
from .work_drafts import parse_draft_ref
from .work_records import (Binding, _canonical, _decode_marker, _hex, _integer,
    _input_contract, _object, _uuid, parse_binding, source_digest, validate_binding)


FENCE_KEYS = {'create_key', 'target_repository_id', 'draft_ref', 'draft_digest',
              'proposal_digest', 'outcome_key', 'operation_nonce'}


def comment_ref(repository, identifier):
    return {'source': 'github', 'kind': 'issue_comment',
            'id': repository + '/comments/' + str(identifier)}


def issue_ref(repository_id, number):
    return {'source': 'github', 'kind': 'issue', 'id': str(repository_id) + ':' + str(number)}


def _fence(body):
    value = _decode_marker(body, 'hydra-create-dispatch', 'v1', 8192)
    _object(value, FENCE_KEYS)
    require(_uuid(value['create_key'], version=4) and _uuid(value['operation_nonce'], version=4)
            and _integer(value['target_repository_id'])
            and all(_hex(value[k], 64) for k in ('draft_digest', 'proposal_digest', 'outcome_key')))
    require(parse_draft_ref(value['draft_ref']).value['kind'] == 'github_comment')
    return value


def _issue(value, repository):
    root = 'https://api.github.com/repos/' + repository
    require(type(value) is dict and _integer(value.get('id')) and _integer(value.get('number'))
            and value.get('repository_url') == root
            and value.get('url') == root + '/issues/' + str(value['number'])
            and 'pull_request' not in value and value.get('state') in {'open', 'closed'}
            and type(value.get('title')) is str and (value.get('body') is None or type(value.get('body')) is str))
    return value


def _is_owned(row, actor):
    user = row.get('user') or {}
    return (type(user.get('id')) is int and user['id'] == actor['id']
            and user.get('login') == actor['login'])


def expected_binding(source, issue):
    draft = source.draft.value
    value = {**source.proposal, 'repository_id': draft['target_repository_id'],
        'issue_number': issue['number'], 'source_digest': source_digest(issue),
        'create_key': draft['create_key'], 'delegated_goal': draft['goal']}
    binding = validate_binding(Binding(_canonical(value)), spec_directory=source.policy['spec_directory'])
    if source.conditions is not None:
        # Both representations use the same normalized clauses and the same
        # validator as work_inputs, now with the real provider-assigned Issue.
        _input_contract({'kind': 'adopted', **source.conditions.value},
                        {k: value[k] for k in ('repository_id', 'issue_number')})
    return binding


@dataclass(repr=False)
class Discovery:
    fences: list = field(default_factory=list, repr=False)
    issue: dict | None = field(default=None, repr=False)
    binding: dict | None = field(default=None, repr=False)


def discover(client, source):
    """Complete original collections, never search or open-only absence proof."""
    draft, repository = source.draft.value, source.repository
    result = Discovery()
    with client.read_budget(seconds=45, requests=128), credential_guard(client, source.credential):
        actor = client._identity()
        require((actor.get('id'), actor.get('login')) == (source.actor['id'], source.actor['login']))
        issues = bounded(client._pages('/repos/' + repository + '/issues?state=all&sort=created&direction=asc'))
        rows = [(row, repository) for row in bounded(client._pages(
            '/repos/' + repository + '/issues/comments?sort=created&direction=asc'))]
        container = source.repositories[source.reference['repository_id']]
        if container != repository:
            rows += [(row, container) for row in bounded(client._pages('/repos/' + container + '/issues/' +
                str(source.reference['issue_number']) + '/comments'))]
        seen, by_number = set(), {}
        for row in issues:
            require(type(row) is dict and _integer(row.get('id')) and row['id'] not in seen)
            seen.add(row['id'])
            if 'pull_request' in row:
                continue
            _issue(row, repository)
            require(row['number'] not in by_number)
            by_number[row['number']] = row
            if not _is_owned(row, source.actor) or '<!-- hydra-create:' not in (row['body'] or ''):
                continue
            creation = _decode_marker(row['body'], 'hydra-create', 'v1', 32768)
            _object(creation, {'create_key'})
            require(_uuid(creation['create_key'], version=4))
            if creation['create_key'] != draft['create_key']:
                continue
            require(row['title'] == draft['title'] and row['body'] == draft['body'],
                    'creation_payload_conflict')
            require(result.issue is None, 'creation_result_conflict')
            result.issue = row
        seen_comments, bindings = set(), []
        for row, row_repository in rows:
            require(type(row) is dict and _integer(row.get('id')))
            marker_key = row.get('url')
            require(type(marker_key) is str and marker_key not in seen_comments)
            seen_comments.add(marker_key)
            if not _is_owned(row, source.actor):
                continue
            body = outside_draft(row.get('body'))
            if '<!-- hydra-create-dispatch:' in body:
                location = re.fullmatch(re.escape('https://api.github.com/repos/' + row_repository)
                                        + r'/issues/([1-9][0-9]*)', row.get('issue_url') or '')
                require(location is not None)
                owned_comment(row, source.actor, row_repository, int(location[1]))
                fence = _fence(body)
                require(source.repositories.get(fence['draft_ref']['repository_id']) == row_repository
                        and fence['draft_ref']['issue_number'] == int(location[1]))
                if fence['create_key'] == draft['create_key']:
                    require(fence['target_repository_id'] == draft['target_repository_id']
                            and fence['draft_ref'] == source.reference and fence['draft_digest'] == source.draft.digest
                            and fence['proposal_digest'] == digest(source.proposal)
                            and fence['outcome_key'] == draft['outcome_key'], 'creation_payload_conflict')
                    result.fences.append(row)
                elif fence['outcome_key'] == draft['outcome_key']:
                    require(False, 'creation_outcome_exists')
            if row_repository != repository or '<!-- hydra-work:' not in body:
                continue
            binding = parse_binding(body, spec_directory=source.policy['spec_directory'])
            value = binding.value
            if value['repository_id'] != draft['target_repository_id']:
                continue
            owned_comment(row, source.actor, repository, value['issue_number'])
            if result.issue is not None and value['issue_number'] == result.issue['number']:
                require(binding.document == expected_binding(source, result.issue).document,
                        'creation_payload_conflict')
                bindings.append(row)
                continue
            origin = {'kind': 'github_issue', 'repository_id': value['repository_id'],
                'issue_number': value['issue_number'], 'source_digest': value['source_digest']}
            if value['delegated_goal'] is not None or value['create_key'] is None:
                existing = outcome_key(value['repository_id'], value, value['delegated_goal'], origin)
                require(existing != draft['outcome_key'], 'creation_outcome_exists')
            elif (value['outcome'] == source.proposal['outcome']
                    and sorted(value['requirements'], key=_canonical) == sorted(source.proposal['requirements'], key=_canonical)):
                require(False, 'creation_duplicate_scope_unknown')
        require(len(result.fences) <= 1 and len(bindings) <= 1, 'creation_result_conflict')
        result.binding = bindings[0] if bindings else None
        client._request_timeout(45)
        require(client._authenticated_fingerprint == source.credential, 'creation_credential_changed')
        return result


class _Permit:
    """Unexported live-owner evidence; recovery never constructs this object."""
    def __init__(self, source, fence):
        self.owner = os.getpid(), threading.get_ident()
        self.signature, self.credential = source.signature, source.credential
        self.fence, self.unused = fence, {'issue', 'binding'}

    def consume(self, stage, source):
        require(self.owner == (os.getpid(), threading.get_ident())
                and self.signature == source.signature and self.credential == source.credential
                and stage in self.unused, 'creation_permit_unavailable')
        if stage == 'binding':
            require('issue' not in self.unused, 'creation_permit_unavailable')
        self.unused.remove(stage)


class Registration:
    def __init__(self, github, names, command, lock_path, *, validate_current, effect_guard, controller):
        self.github, self.names, self.command, self.lock_path = github, names, command, lock_path
        self.validate_current, self.effect_guard = validate_current, effect_guard
        self.source, self.issue, self.binding = None, None, None
        self.effects = []
        self.controller, self.history = controller, None

    def fresh(self):
        self.validate_current()
        value = read_source(self.github.read_client(), self.names, self.command)
        self.validate_current()
        if self.source is not None:
            require(value.signature == self.source.signature and value.credential == self.source.credential,
                    'creation_source_changed')
        self.source = value
        return value

    def observe(self):
        result = discover(self.github.read_client(), self.source)
        if result.issue is not None:
            self.confirm_issue(result.issue)
        return result

    def confirm_issue(self, row):
        client = self.github.read_client()
        with client.read_budget(seconds=45, requests=32), credential_guard(client, self.source.credential):
            actual = bounded(client.issue(self.source.repository, row['number']))
            _issue(actual, self.source.repository)
            require(_is_owned(actual, self.source.actor) and actual['id'] == row['id']
                    and actual['title'] == self.source.draft.value['title']
                    and actual['body'] == self.source.draft.value['body'], 'creation_payload_conflict')
            client._request_timeout(45)
            self.issue = actual
        ref = issue_ref(self.command['target']['repository_id'], actual['number'])
        if ref not in self.effects:
            self.effects.append(ref)

    def confirm_comment(self, row, repository, number):
        require(type(row) is dict and _integer(row.get('id')))
        client = self.github.read_client()
        with client.read_budget(seconds=45, requests=32), credential_guard(client, self.source.credential):
            actual = bounded(client.api('GET', '/repos/' + repository + '/issues/comments/' + str(row['id'])))
            owned_comment(actual, self.source.actor, repository, number)
            require(actual['id'] == row['id'])
            client._request_timeout(45)
        ref = comment_ref(repository, actual['id'])
        if ref not in self.effects:
            self.effects.append(ref)
        return actual

    def registered(self, row):
        self.confirm_issue(self.issue)
        self.binding = self.confirm_comment(row, self.source.repository, self.issue['number'])
        actual = parse_binding(self.binding['body'], spec_directory=self.source.policy['spec_directory'])
        require(actual.document == expected_binding(self.source, self.issue).document,
                'creation_payload_conflict')
        return {'kind': 'work_create', 'stage': 'registered',
            'repository_id': self.command['target']['repository_id'], 'issue_number': self.issue['number'],
            'create_key': actual.value['create_key'], 'draft_digest': self.source.draft.digest,
            'proposal_digest': digest(self.source.proposal),
            'issue_ref': issue_ref(self.command['target']['repository_id'], self.issue['number']),
            'binding_ref': comment_ref(self.source.repository, self.binding['id']),
            'binding_digest': actual.digest}

    def run(self):
        with coordinator_lock(self.lock_path):
            self.fresh()
            current = self.observe()
            if current.binding is not None:
                return self.registered(current.binding)
            require(not current.fences and current.issue is None, 'creation_effect_unconfirmed')
            self.fresh()
            current = self.observe()
            if current.binding is not None:
                return self.registered(current.binding)
            require(not current.fences and current.issue is None, 'creation_effect_unconfirmed')
            self.fresh()
            source = self.source
            draft = source.draft.value
            self.history = HistoryGuard(self.controller, source, self.command)
            self.history.preflight()
            fence = {'create_key': draft['create_key'], 'target_repository_id': draft['target_repository_id'],
                'draft_ref': source.reference, 'draft_digest': source.draft.digest,
                'proposal_digest': digest(source.proposal), 'outcome_key': draft['outcome_key'],
                'operation_nonce': str(uuid.uuid4())}
            container = source.repositories[source.reference['repository_id']]
            with self.effect_guard(), credential_guard(self.github, source.credential):
                self.history.consume('fence')
                row = self.github.api('POST', '/repos/' + container + '/issues/' +
                    str(source.reference['issue_number']) + '/comments',
                    {'body': '<!-- hydra-create-dispatch:v1 ' + _canonical(fence) + ' -->'})
            actual = self.confirm_comment(row, container, source.reference['issue_number'])
            require(_fence(actual['body']) == fence, 'creation_result_conflict')
            permit = _Permit(source, fence)
            self.fresh()
            current = self.observe()
            require(len(current.fences) == 1 and current.fences[0]['id'] == actual['id'], 'creation_effect_unconfirmed')
            if current.issue is not None:
                return self.registered(current.binding) if current.binding else None
            self.fresh()
            self.history.preflight()
            with self.effect_guard(), credential_guard(self.github, source.credential):
                permit.consume('issue', self.source)
                self.history.consume('issue')
                row = self.github.api('POST', '/repos/' + source.repository + '/issues',
                    {'title': draft['title'], 'body': draft['body']})
            _issue(row, source.repository)
            self.confirm_issue(row)
            self.fresh()
            current = self.observe()
            require(current.issue is not None and len(current.fences) == 1
                    and current.fences[0]['id'] == actual['id'], 'creation_effect_unconfirmed')
            if current.binding is not None:
                return self.registered(current.binding)
            self.fresh()
            binding = expected_binding(self.source, self.issue)
            self.history.preflight()
            with self.effect_guard(), credential_guard(self.github, source.credential):
                permit.consume('binding', self.source)
                self.history.consume('binding')
                row = self.github.api('POST', '/repos/' + source.repository + '/issues/' +
                    str(self.issue['number']) + '/comments',
                    {'body': '<!-- hydra-work:v2 ' + binding.document + ' -->'})
            receipt = self.registered(row)
            self.history.completed()
            return receipt

    def observation(self):
        if self.issue is None:
            return None
        now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
        key = 'command:' + self.command['request_id'] + ':created-issue'
        value = {'number': self.issue['number'], 'title': self.issue['title'], 'state': self.issue['state'],
            'url': 'https://github.com/' + self.source.repository + '/issues/' + str(self.issue['number']),
            'work_kind': None, 'parent_refs': None, 'requirement_refs': None,
            'description_excerpt': None, 'description_truncated': None}
        result = {'key': key, 'resource': issue_ref(self.command['target']['repository_id'], self.issue['number']),
            'revision': None, 'observed_at': now, 'last_attempt_at': now, 'availability': 'current',
            'coverage': {'state': 'complete', 'scope': key, 'returned_count': 1,
                         'total_count': 1, 'next_cursor': None, 'reason': None},
            'reason': None, 'value': value}
        p.observation(result)
        return result
