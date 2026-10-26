"""Two bounded, authenticated dependency collections without stored graph state.

Registration is supplied by the caller, never inferred from provider data. The
caller exclusively owns the synchronous GitHub client, including its budgets and
credential hook. These source observations do not authorize an effect or satisfy
a required output. No relation rows are reused between the two collections.
"""
from dataclasses import replace

from .github import GitHubError, _repo
from .github_relations import MAX_INTEGER, read_relation
from .work_records import _issue_ref
from .work_relations import DependencyGraph, DependencyTopology, dependency_topology

MAX_REGISTERED_REPOSITORIES = 256
MAX_PROVENANCE_IDENTITIES = 1024
MAX_NODES = 256
MAX_EDGES = 1024
MAX_DEPTH = 32


class _Changed(Exception):
    pass


class _Unavailable(Exception):
    pass


def _request(root, repositories):
    try:
        _issue_ref(root)
        if any(type(value) is not int or not 1 <= value <= MAX_INTEGER
               for value in root.values()):
            raise ValueError()
        if type(repositories) is not dict or len(repositories) > MAX_REGISTERED_REPOSITORIES:
            raise ValueError()
        result, names = {}, set()
        for identifier, name in repositories.items():
            if type(identifier) is not int or not 1 <= identifier <= MAX_INTEGER:
                raise ValueError()
            if type(name) is not str or len(name) > 200:
                raise ValueError()
            _repo(name)
            if any(part in {'.', '..'} for part in name.split('/')):
                raise ValueError()
            if name.casefold() in names:
                raise ValueError()
            result[identifier] = name
            names.add(name.casefold())
        return dict(root), result
    except (GitHubError, ValueError, TypeError):
        raise GitHubError('Invalid native dependency request') from None


class _Provenance:
    """Transient identity consistency; no raw page or credential is returned."""

    def __init__(self, registered):
        self.registered = {identifier: name.casefold() for identifier, name in registered.items()}
        self.names = {name: identifier for identifier, name in self.registered.items()}
        self.repositories = {}
        self.issues = {}
        self.node_ids = {}
        self.fingerprint = None

    def credential(self, fingerprint):
        if type(fingerprint) is not bytes or not fingerprint:
            raise _Unavailable()
        if self.fingerprint is None:
            self.fingerprint = fingerprint
        elif self.fingerprint != fingerprint:
            raise _Changed()

    def observe(self, issue, node_id, repository, fingerprint):
        self.credential(fingerprint)
        identifier, name, _, _ = repository
        key = issue['repository_id'], issue['issue_number']
        if (identifier in self.registered and self.registered[identifier] != name
                or identifier in self.repositories and self.repositories[identifier] != repository
                or name in self.names and self.names[name] != identifier
                or key in self.issues and self.issues[key] != node_id
                or node_id in self.node_ids and self.node_ids[node_id] != key):
            raise _Changed()
        if (identifier not in self.repositories and len(self.repositories) >= MAX_PROVENANCE_IDENTITIES
                or key not in self.issues and len(self.issues) >= MAX_PROVENANCE_IDENTITIES):
            raise _Unavailable()
        self.repositories[identifier] = repository
        self.names[name] = identifier
        self.issues[key] = node_id
        self.node_ids[node_id] = key


def _unknown(reason):
    # Explicitly override the comparator's cycle precedence for mixed sources.
    empty = DependencyGraph('unavailable', reason, (), (), False)
    return DependencyTopology('unknown', reason, empty, empty)


def _collect(client, root, repositories, scope):
    start = root['repository_id'], root['issue_number']
    reads, queue, nodes, edges = {}, [start], {start}, set()
    depths, position = {start: 0}, 0
    while position < len(queue):
        source = queue[position]
        position += 1
        if source[0] not in repositories:
            continue
        try:
            client._request_timeout(45)
        except GitHubError:
            return reads, True
        if any(budget.remaining_requests <= 0 for budget in client._read_budgets):
            return reads, True
        issue = {'repository_id': source[0], 'issue_number': source[1]}
        observed = read_relation(client, repositories[source[0]], issue, 'blocked_by',
                                 _observer=scope)
        reads[source] = observed
        for item in observed.value['items']:
            target = item['repository_id'], item['issue_number']
            # Retain the row that establishes the limit. The comparator bounds
            # its normalized prefix and supplies the specific limit reason.
            if len(edges) >= MAX_EDGES:
                return reads, False
            if target not in nodes:
                if len(nodes) >= MAX_NODES or depths[source] + 1 > MAX_DEPTH:
                    return reads, False
                nodes.add(target)
                depths[target] = depths[source] + 1
                queue.append(target)
            edges.add((source, target))
    return reads, False


def read_dependencies(client, root, *, repositories):
    """Collect current reachable topology twice, never readiness or authority.

    The aggregate budget includes authentication and nested relation requests.
    Each pass has independent traversal state. Only transient provenance is
    shared. Callers must not use this client's mutable read state concurrently.
    """
    root, repositories = _request(root, repositories)
    registered = frozenset(repositories)
    if root['repository_id'] not in repositories:
        return dependency_topology(root, {}, {}, registered_repositories=registered)
    scope = _Provenance(repositories)
    original_hook = client._credential_selected
    had_local_hook = '_credential_selected' in client.__dict__
    original_local_hook = client.__dict__.get('_credential_selected')

    def selected(fingerprint):
        # Observe a selection even when an earlier observer rejects it. A failed
        # request followed by a restored credential must not erase the change.
        try:
            original_hook(fingerprint)
        finally:
            scope.credential(fingerprint)

    client._credential_selected = selected
    try:
        with client.read_budget(seconds=45, requests=128):
            first, first_limited = _collect(client, root, repositories, scope)
            second, second_limited = _collect(client, root, repositories, scope)
            result = dependency_topology(root, first, second, registered_repositories=registered)
            try:
                client._request_timeout(45)
            except GitHubError:
                second_limited = True
            if first_limited or second_limited:
                after = replace(result.second,
                    coverage='partial' if result.second.edges else 'unavailable',
                    reason='dependency_read_budget')
                return DependencyTopology('unknown', 'dependency_read_budget', result.first, after)
            return result
    except _Changed:
        return _unknown('dependency_source_changed')
    except (_Unavailable, GitHubError, OSError, ValueError, TypeError):
        return _unknown('dependency_source_unavailable')
    finally:
        if had_local_hook:
            client._credential_selected = original_local_hook
        else:
            del client._credential_selected
