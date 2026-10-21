"""Default Issue planning from exact source bytes, without execution authority.

The caller owns protected source selection and the accepted digest's provenance.
Complete observations and ordering keys do not establish adoption, eligibility,
delegation or permission to dispatch. No source body or planning state is stored.
"""
import copy
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import re
import tomllib

from .github import GitHubError, _repo
from .project import _planning
from .work_records import (WorkRecordError, _canonical, _hex, _integer,
                           _issue_ref, _text, source_digest)


MAX_BODY_BYTES = 262_144
MAX_SOURCE_BYTES = 8_000_000
_CREATED = re.compile(r'([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})'
                      r'(?:\.([0-9]{1,9}))?(?:Z|\+00:00)\Z')


@dataclass(frozen=True)
class IssuePlanningRead:
    document: str

    @property
    def value(self):
        return json.loads(self.document)


class _InvalidPriority(Exception):
    pass


class _Changed(Exception):
    pass


def _require(value):
    if not value:
        raise GitHubError('Invalid Issue planning source')


def _created(value):
    _require(type(value) is str)
    match = _CREATED.fullmatch(value)
    _require(match is not None)
    try:
        datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        raise GitHubError('Invalid Issue creation time') from None
    # Validate the calendar without losing sub-microsecond ordering precision.
    return tuple(int(part) for part in match.groups()[:6]) + (int((match[7] or '').ljust(9, '0')),)


def priority_key(priority, created_at, source):
    """Order already qualified eligible candidates; unknown has no default key."""
    try:
        _issue_ref(source)
        _require(type(priority) is int and -1000 <= priority <= 1000)
        return -priority, _created(created_at), source['repository_id'], source['issue_number']
    except (WorkRecordError, GitHubError, TypeError, ValueError):
        raise GitHubError('Invalid native priority key') from None


def _priority(body):
    # CommonMark syntax only: never render HTML, fetch links or load extensions.
    from markdown_it import MarkdownIt
    tokens = MarkdownIt('commonmark').parse(body or '')
    blocks = [token for token in tokens if token.type == 'fence' and token.level == 0
              and token.info.split(maxsplit=1)[:1] == ['hydra']]
    if not blocks:
        return 0
    if len(blocks) != 1:
        raise _InvalidPriority()
    block = blocks[0]
    lines = (body or '').splitlines()
    if block.info.strip() != 'hydra' or not block.map or not block.markup:
        raise _InvalidPriority()
    closing = block.map[1] - 1
    pattern = r' {0,3}' + re.escape(block.markup[0]) + '{' + str(len(block.markup)) + r',}[ \t]*'
    if closing <= block.map[0] or closing >= len(lines) or re.fullmatch(pattern, lines[closing]) is None:
        raise _InvalidPriority()
    try:
        value = tomllib.loads(block.content)
    except (ValueError, RecursionError):
        raise _InvalidPriority() from None
    if set(value) - {'spec', 'spec_revision', 'dependencies', 'priority'}:
        raise _InvalidPriority()
    result = value.get('priority', 0)
    if type(result) is not int or not -1000 <= result <= 1000:
        raise _InvalidPriority()
    return result


def _repository(value, repository, source):
    _require(type(value) is dict and _integer(value.get('id'))
             and value['id'] == source['repository_id']
             and type(value.get('full_name')) is str
             and value['full_name'].casefold() == repository.casefold()
             and type(value.get('private')) is bool and _text(value.get('default_branch'), 200))
    _repo(value['full_name'])
    return value['id'], value['full_name'].casefold(), value['private'], value['default_branch']


def _snapshot(value, repository, source):
    _require(type(value) is dict and len(_canonical(value).encode('utf-8')) <= MAX_SOURCE_BYTES
             and 'pull_request' not in value and _integer(value.get('id'))
             and type(value.get('number')) is int and value['number'] == source['issue_number']
             and _text(value.get('node_id'), 256)
             and value.get('url') == f"https://api.github.com/repos/{repository}/issues/{source['issue_number']}"
             and value.get('state') in {'open', 'closed'})
    _require('title' in value and type(value['title']) is str
             and len(value['title'].encode('utf-8')) <= 4096 and 'body' in value
             and (value['body'] is None or type(value['body']) is str))
    for flag in ('truncated', 'body_truncated'):
        _require(flag not in value or value[flag] is False)
    _require(value['body'] is None or len(value['body'].encode('utf-8')) <= MAX_BODY_BYTES)
    created = _created(value.get('created_at'))
    return source_digest(value), (value['id'], value['node_id'], created)


def read_issue_priority(client, repository, source, planning, expected_source_digest):
    """Read selected Issue priority at one exact pin without adopting its meaning.

    A Project source never falls back here. Both complete source reads must match
    the supplied pin and stable numeric/node/creation identity. Reobserve for each
    use; preserve active work and reconcile source drift outside this data reader.
    """
    try:
        _repo(repository)
        _issue_ref(source)
        _require(_hex(expected_source_digest, 64))
    except (GitHubError, WorkRecordError, TypeError, ValueError):
        raise GitHubError('Invalid Issue planning request') from None
    policy = _planning({'version': 2, 'work_source': 'github_native', 'planning': copy.deepcopy(planning)})
    source = dict(source)

    def result(coverage='unavailable', priority=None, created_at=None, digest=None, reason='planning_unavailable'):
        return IssuePlanningRead(_canonical({'source': source, 'source_digest': digest,
            'coverage': coverage, 'priority': priority, 'created_at': created_at, 'reason': reason,
            'observed_at': datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')}))

    if policy['source'] != 'issue':
        return result(reason='planning_not_selected')
    observed = False
    try:
        with client.read_budget(seconds=15, requests=8):
            identity = client._identity()
            _require(_integer(identity.get('id')) and identity.get('login') == client.user)
            credential = client._authenticated_fingerprint
            _require(type(credential) is bytes and bool(credential))

            def read(callback, *args):
                value = callback(*args)
                client._request_timeout(15)
                if client._authenticated_fingerprint != credential:
                    raise _Changed()
                return value

            repo = read(client.repository, repository)
            context = _repository(repo, repository, source)
            repository = repo['full_name']
            first = read(client.issue, repository, source['issue_number'])
            digest, snapshot = _snapshot(first, repository, source)
            observed = True
            if digest != expected_source_digest:
                return result('partial', reason='source_changed')
            priority = _priority(first['body'])
            client._request_timeout(15)
            second = read(client.issue, repository, source['issue_number'])
            next_digest, next_snapshot = _snapshot(second, repository, source)
            if next_digest != expected_source_digest:
                return result('partial', reason='source_changed')
            _require(next_snapshot == snapshot)
            after = read(client.repository, repository)
            _require(_repository(after, repository, source) == context)
            client._request_timeout(15)
            complete = result('complete', priority, first['created_at'], digest, None)
            client._request_timeout(15)
            return complete
    except _InvalidPriority:
        return result('partial' if observed else 'unavailable', reason='invalid_priority')
    except _Changed:
        return result('partial' if observed else 'unavailable', reason='planning_context_changed')
    except (GitHubError, WorkRecordError, OSError, ValueError, TypeError, KeyError, AttributeError, RecursionError):
        return result('partial' if observed else 'unavailable')
