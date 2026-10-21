"""Bounded native relation observations through the existing GitHub client.

Fixed read queries do not qualify a deployment or authorize an effect. The caller
owns source selection, registration and actual visibility qualification. No raw
page, relation state or credential is persisted.
"""
from datetime import datetime, timezone
import json
import re

from .github import GitHubError, _repo
from .work_records import _issue_ref
from .work_relations import MAX_RELATION_ITEMS, relation_read

MAX_PAGE_BYTES = 131_072
MAX_PAGES = 3
MAX_INTEGER = 9_007_199_254_740_991
_PERMISSIONS = {'READ', 'TRIAGE', 'WRITE', 'MAINTAIN', 'ADMIN'}
_NODE = 'id number repository{databaseId nameWithOwner isPrivate viewerPermission}'
_FIELDS = {
    'parent': 'parent{' + _NODE + '}',
    'children': ('subIssuesSummary{total} subIssues(first:$first,after:$after)'
                 '{totalCount nodes{' + _NODE + '} pageInfo{hasNextPage endCursor}}'),
    'blocked_by': ('issueDependenciesSummary{totalBlockedBy} blockedBy(first:$first,after:$after)'
                   '{totalCount nodes{' + _NODE + '} pageInfo{hasNextPage endCursor}}'),
}
_QUERIES = {kind: (
    'query HydraNativeRelations($owner:String!,$name:String!,$number:Int!'
    + ('' if kind == 'parent' else ',$first:Int!,$after:String') + '){'
    'repository(owner:$owner,name:$name){databaseId nameWithOwner isPrivate viewerPermission '
    'issue(number:$number){id number ' + fields + '}}}') for kind, fields in _FIELDS.items()}


class _Unavailable(Exception):
    pass


def _require(value):
    if not value:
        raise GitHubError('Invalid native relation source')


def _integer(value, *, positive=False):
    _require(type(value) is int and (1 if positive else 0) <= value <= MAX_INTEGER)
    return value


def _text(value, limit):
    _require(type(value) is str and 0 < len(value) <= limit
             and not any(ord(c) < 32 or ord(c) == 127 or 0xD800 <= ord(c) <= 0xDFFF for c in value))
    return value


def _repository(value):
    _require(type(value) is dict)
    identifier = _integer(value.get('databaseId'), positive=True)
    name = _text(value.get('nameWithOwner'), 200)
    _require(re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', name) is not None)
    _require(type(value.get('isPrivate')) is bool and 'viewerPermission' in value)
    permission = value['viewerPermission']
    if permission is None:
        raise _Unavailable()
    _require(type(permission) is str and permission in _PERMISSIONS)
    return identifier, name.casefold(), value['isPrivate'], permission


def _node(value):
    if value is None:
        raise _Unavailable()
    _require(type(value) is dict)
    repository = _repository(value.get('repository'))
    number = _integer(value.get('number'), positive=True)
    identifier = _text(value.get('id'), 256)
    return {'repository_id': repository[0], 'issue_number': number}, identifier, repository


def _source(value, repository, source):
    _require(type(value) is dict)
    try:
        size = len(json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(',', ':')).encode('utf-8'))
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise GitHubError('Invalid native relation source') from None
    _require(size <= MAX_PAGE_BYTES)
    if 'errors' in value:
        _require(type(value['errors']) is list)
        if value['errors']:
            raise _Unavailable()
    _require('data' in value)
    if value['data'] is None:
        raise _Unavailable()
    data = value['data']
    _require(type(data) is dict and 'repository' in data)
    if data['repository'] is None:
        raise _Unavailable()
    root = data['repository']
    identity = _repository(root)
    _require(identity[0] == source['repository_id'] and identity[1] == repository.casefold())
    _require('issue' in root)
    issue = root['issue']
    if issue is None:
        raise _Unavailable()
    _require(type(issue) is dict)
    _require(_integer(issue.get('number'), positive=True) == source['issue_number'])
    node_id = _text(issue.get('id'), 256)
    return issue, (identity, node_id)


def _page(issue, relation, limit, after, cursors):
    field, summary, total_field = ('blockedBy', 'issueDependenciesSummary', 'totalBlockedBy') if relation == 'blocked_by' else (
        'subIssues', 'subIssuesSummary', 'total')
    value, counts = issue.get(field), issue.get(summary)
    _require(type(value) is dict and type(counts) is dict)
    total, summary_count = _integer(value.get('totalCount')), _integer(counts.get(total_field))
    nodes, info = value.get('nodes'), value.get('pageInfo')
    _require(type(nodes) is list and len(nodes) <= limit and type(info) is dict)
    _require(type(info.get('hasNextPage')) is bool and 'endCursor' in info)
    more, cursor = info['hasNextPage'], info['endCursor']
    if cursor is not None:
        _text(cursor, 2048)
    if more:
        _require(nodes and cursor is not None and cursor != after and cursor not in cursors)
    return nodes, total, summary_count, more, cursor


def read_relation(client, repository, source, relation):
    """Observe one relation; matching reads are not a provider snapshot or CAS."""
    try:
        _repo(repository)
        _issue_ref(source)
        if type(relation) is not str or relation not in _FIELDS:
            raise ValueError()
    except (ValueError, GitHubError):
        raise GitHubError('Invalid native relation request') from None
    source = dict(source)
    owner, name = repository.split('/')
    items, seen, node_ids, repositories, names, cursors = [], set(), {}, {}, {}, set()
    after, expected_total, identity, credential = None, None, None, None

    def result(coverage):
        value = relation_read(source, relation, coverage, items,
                              datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
        if coverage == 'complete':
            try:
                client._request_timeout(15)
            except GitHubError:
                return relation_read(source, relation, 'partial' if items else 'unavailable', items,
                                     datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z'))
        return value

    def incomplete():
        return result('partial' if items else 'unavailable')

    with client.read_budget(seconds=15, requests=4):
        for _ in range(MAX_PAGES):
            limit = min(100, MAX_RELATION_ITEMS - len(items))
            variables = {'owner': owner, 'name': name, 'number': source['issue_number']}
            if relation != 'parent':
                variables.update(first=limit, after=after)
            try:
                raw = client.api('POST', '/graphql', {'query': _QUERIES[relation], 'variables': variables})
            except (GitHubError, OSError):
                return incomplete()
            current_credential = client._authenticated_fingerprint
            if identity is not None and current_credential != credential:
                return incomplete()
            try:
                issue, current_identity = _source(raw, repository, source)
                if identity is not None and current_identity != identity:
                    return incomplete()
                if identity is None:
                    identity, credential = current_identity, current_credential
                    node_ids[identity[1]] = (source['repository_id'], source['issue_number'])
                    repositories[identity[0][0]] = identity[0]
                    names[identity[0][1]] = identity[0][0]
                if relation == 'parent':
                    _require('parent' in issue)
                    nodes = [] if issue['parent'] is None else [issue['parent']]
                    total = summary = len(nodes)
                    more, cursor = False, None
                else:
                    nodes, total, summary, more, cursor = _page(issue, relation, limit, after, cursors)
                if expected_total is not None and expected_total != (total, summary):
                    return incomplete()
                expected_total = total, summary
                page_items = []
                for raw_node in nodes:
                    item, node_id, repo_identity = _node(raw_node)
                    key = item['repository_id'], item['issue_number']
                    _require(key not in seen and (node_id not in node_ids or node_ids[node_id] == key))
                    _require(repo_identity[0] not in repositories or repositories[repo_identity[0]] == repo_identity)
                    _require(repo_identity[1] not in names or names[repo_identity[1]] == repo_identity[0])
                    seen.add(key)
                    node_ids[node_id] = key
                    repositories[repo_identity[0]] = repo_identity
                    names[repo_identity[1]] = repo_identity[0]
                    page_items.append(item)
            except _Unavailable:
                return incomplete()
            try:
                client._request_timeout(15)
            except GitHubError:
                return incomplete()
            items.extend(page_items)
            if total != summary or len(items) > total:
                return result('partial')
            if not more:
                return result('complete' if len(items) == total else 'partial')
            if len(items) == MAX_RELATION_ITEMS:
                return result('partial')
            cursors.add(cursor)
            after = cursor
    return result('partial')
