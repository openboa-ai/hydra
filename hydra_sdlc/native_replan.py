"""Guarded native technical successors; source qualification is not supplied here."""
import copy
from dataclasses import dataclass, replace
import hashlib
import json
import uuid
from time import monotonic

from .decision_protocol import decision_root
from .github import GitHubError, _native_decision_root
from .operations import OperationDenied
from . import projection as p


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True,
                      allow_nan=False).encode('ascii')


@dataclass(frozen=True, repr=False)
class TechnicalReplanIntent:
    effect: tuple[int, int, str]
    before: bytes
    after: bytes
    before_context: bytes
    before_root: bytes | None
    root: bytes
    authorization: bytes

    @property
    def digest(self):
        return hashlib.sha256(canonical({'effect': self.effect, **{
            name: None if getattr(self, name) is None else getattr(self, name).decode('ascii')
            for name in ('before', 'after', 'before_context', 'before_root', 'root', 'authorization')}})).hexdigest()


@dataclass(frozen=True, repr=False)
class TechnicalReplanCoverage:
    """Separately qualified original facts, never inferred from initial resume calls."""
    effect: tuple[int, int, str]
    intent_digest: str
    complete: bool
    writes: int | None
    state: str
    successor_fresh: bool


@dataclass(frozen=True, repr=False)
class TechnicalReplanEffect:
    """One original physical effect, including unknown coverage after restart."""
    effect: tuple[int, int, str]
    intent_digest: str | None
    root: bytes | None
    writes: int | None
    state: str
    complete: bool


@dataclass(frozen=True, repr=False)
class TechnicalReplanEffects:
    repository_id: int
    issue_number: int
    complete: bool
    effects: tuple[TechnicalReplanEffect, ...]


@dataclass(frozen=True, repr=False)
class TechnicalReplanObservation:
    """A bounded live fence; unknown counts retain identity and uncertainty."""
    intent_digest: str | None
    root: bytes | None
    minimum_writes: int
    unresolved: bool


def _retain_observation(runner, effect, digest, root, writes, *, unresolved):
    observations = runner.technical_replan_observations
    previous = observations.get(effect)
    attempted = runner.technical_replan_attempts.get(effect)
    minimum = max(previous.minimum_writes if previous else 0, attempted[1] if attempted else 0)
    if writes is not None and writes < minimum:
        raise OperationDenied('technical_replan_coverage_unknown')
    if attempted is not None:
        if digest is not None and digest != attempted[0]:
            raise OperationDenied('technical_replan_coverage_unknown')
        if root is not None and root != attempted[2].root:
            raise OperationDenied('technical_replan_source_changed')
        digest, root = digest or attempted[0], root or attempted[2].root
    if previous is not None:
        if (previous.intent_digest is not None and digest is not None and previous.intent_digest != digest
                and (previous.minimum_writes > 0 or previous.unresolved)):
            raise OperationDenied('technical_replan_coverage_unknown')
        if previous.root is not None and root is not None and previous.root != root:
            raise OperationDenied('technical_replan_source_changed')
        digest, root = digest or previous.intent_digest, root or previous.root
    if previous is None and len(observations) >= 1024:
        raise OperationDenied('technical_replan_capacity')
    value = TechnicalReplanObservation(digest, root, max(minimum, writes or 0),
        unresolved or (previous.unresolved if previous else False))
    observations[effect] = value
    return value


class TechnicalReplanPermit:
    """Server-owned, one-dispatch exact writer permit, not a command parameter."""
    def __init__(self, intent, attempted):
        self.intent, self.attempted, self.used = intent, attempted, False

    def authorize(self, repository_id, number, old, new, context, root):
        intent = self.intent
        if (self.used or (repository_id, number, old.get('attempt_id')) != intent.effect
                or canonical(old) != intent.before or canonical(new) != intent.after
                or canonical(context) != intent.before_context
                or (None if root is None else canonical(root)) != intent.before_root):
            raise GitHubError('Native successor binding changed')
        return json.loads(intent.root)

    def consume(self):
        if self.used:
            raise GitHubError('Native successor permit already consumed')
        self.used = True  # An exception cannot make this dispatch permit reusable.
        self.attempted()


def _ready(reader, repository, number, record, config):
    phrase = f"hydra: replan {record['attempt_id']} ready"
    rows = [row for row in reader.comments(repository, number)
            if type(row) is dict and type(row.get('body')) is str and row['body'].strip() == phrase
            and (row.get('user') or {}).get('login') in config['authorized_actors']]
    if not rows:
        raise OperationDenied('replan_authorization_changed')
    if any(type(row.get('id')) is not int or row['id'] < 1 for row in rows):
        raise OperationDenied('replan_authorization_unknown')
    row = min(rows, key=lambda item: item['id'])
    direct = reader.api('GET', f"/repos/{repository}/issues/comments/{row['id']}")
    fields = ('id', 'body', 'user', 'updated_at', 'issue_url')
    if (type(direct) is not dict or any(direct.get(key) != row.get(key) for key in fields)
            or direct.get('issue_url') != f'https://api.github.com/repos/{repository}/issues/{number}'
            or type((direct.get('user') or {}).get('id')) is not int
            or direct['user']['id'] < 1):
        raise OperationDenied('replan_authorization_unknown')
    p.timestamp(direct.get('updated_at'))
    return {'resource': {'source': 'github', 'kind': 'issue_comment',
            'id': f"{repository}/comments/{row['id']}"},
            'revision': {'kind': 'opaque', 'value': hashlib.sha256(canonical(
                {key: direct[key] for key in fields})).hexdigest()}}


def _coverage(frame, intent):
    read = getattr(frame.provider, 'read_technical_replan', None)
    if not callable(read):
        raise OperationDenied('technical_replan_source_unsupported')
    try:
        value = read(intent, timeout=15)
    except Exception:
        raise OperationDenied('technical_replan_source_unavailable') from None
    if (type(value) is not TechnicalReplanCoverage or type(value.effect) is not tuple
            or len(value.effect) != 3 or any(type(item) is not int for item in value.effect[:2])
            or type(value.effect[2]) is not str or value.effect != intent.effect
            or value.intent_digest != intent.digest or type(value.complete) is not bool
            or type(value.successor_fresh) is not bool
            or value.writes is not None and (type(value.writes) is not int or not 0 <= value.writes <= 3)
            or type(value.state) is not str or value.state not in
                {'not_dispatched', 'not_applied', 'unconfirmed', 'applied'}
            or value.state == 'not_dispatched' and value.writes != 0
            or value.state in {'not_applied', 'applied'} and (value.writes is None or value.writes == 0)
            or value.state == 'unconfirmed' and value.writes == 0):
        raise OperationDenied('technical_replan_coverage_unknown')
    observations = frame.runner.technical_replan_observations
    observed = _retain_observation(frame.runner, intent.effect, intent.digest, intent.root, value.writes,
        unresolved=not value.complete or value.writes is None or value.state == 'unconfirmed')
    if value.state == 'not_dispatched' and observed.unresolved:
        raise OperationDenied('technical_replan_unconfirmed')
    if not value.complete or not value.successor_fresh or value.writes is None:
        raise OperationDenied('technical_replan_coverage_unknown')
    if value.state not in {'not_dispatched', 'not_applied'}:
        raise OperationDenied('technical_replan_unconfirmed')
    if value.writes >= 3:
        raise OperationDenied('technical_replan_retry_exhausted')
    observations[intent.effect] = replace(observed, unresolved=False)
    return value


def reconcile_work_effects(runner, provider, repository, number, record, *, timeout):
    """Require original work coverage; an empty transient map proves nothing."""
    deadline = monotonic() + timeout
    def remaining():
        value = deadline - monotonic()
        if value <= 0:
            raise OperationDenied('technical_replan_effects_unavailable')
        return value
    read = getattr(provider, 'read_technical_replan_effects', None)
    if not callable(read):
        raise OperationDenied('technical_replan_effects_unsupported')
    reader = runner.github.read_client()
    with reader.read_budget(seconds=remaining(), requests=64):
        repository_id = (record['repository_id'] if record is not None
                         else reader.repository(repository)['id'])
    scope = (repository_id, number)
    attempts, observations = runner.technical_replan_attempts, runner.technical_replan_observations
    known = {key for key in attempts if key[:2] == scope}
    known |= {key for key, value in observations.items() if key[:2] == scope
              and (value.minimum_writes > 0 or value.unresolved)}
    try:
        value = read(repository_id, number, known_effects=tuple(sorted(known)), timeout=remaining())
    except Exception:
        raise OperationDenied('technical_replan_effects_unavailable') from None
    if (type(value) is not TechnicalReplanEffects
            or type(value.repository_id) is not int or type(value.issue_number) is not int
            or (value.repository_id, value.issue_number) != scope or type(value.complete) is not bool
            or type(value.effects) is not tuple or len(value.effects) > 1024):
        raise OperationDenied('technical_replan_effects_unknown')
    seen, retained = set(), []
    for fact in value.effects:
        if (type(fact) is not TechnicalReplanEffect or type(fact.effect) is not tuple or len(fact.effect) != 3
                or type(fact.effect[0]) is not int or type(fact.effect[1]) is not int
                or type(fact.effect[2]) is not str
                or fact.effect[:2] != scope or fact.effect in seen or type(fact.complete) is not bool
                or type(fact.state) is not str or fact.state not in
                    {'not_dispatched', 'not_applied', 'unconfirmed', 'applied'}
                or fact.writes is not None and (type(fact.writes) is not int or not 0 <= fact.writes <= 3)):
            raise OperationDenied('technical_replan_effects_unknown')
        p.uid(fact.effect[2])
        if fact.intent_digest is not None:
            p.digest(fact.intent_digest)
        root = None
        if fact.root is not None:
            if type(fact.root) is not bytes or len(fact.root) > 4096:
                raise OperationDenied('technical_replan_effects_unknown')
            root = _native_decision_root(json.loads(fact.root))
            if (root['decision']['key']['repository_id'], root['decision']['key']['issue_number']) != scope:
                raise OperationDenied('technical_replan_effects_unknown')
            if canonical(root) != fact.root:
                raise OperationDenied('technical_replan_effects_unknown')
        effect = fact.effect
        seen.add(effect)
        if fact.state == 'not_dispatched' and fact.writes != 0:
            raise OperationDenied('technical_replan_effects_unknown')
        if fact.state in {'not_applied', 'applied'} and (fact.writes is None or fact.writes == 0):
            raise OperationDenied('technical_replan_effects_unknown')
        if fact.state == 'unconfirmed' and fact.writes == 0:
            raise OperationDenied('technical_replan_effects_unknown')
        # Retain the identity/bindings and count floor before any uncertainty
        # hold. A later incomplete or lagging page cannot turn this into absence.
        observed = _retain_observation(runner, effect, fact.intent_digest,
            None if root is None else canonical(root), fact.writes,
            unresolved=not fact.complete or fact.writes is None or fact.state == 'unconfirmed')
        retained.append((fact, root, observed))
    # Validate and retain every returned identity before an uncertainty hold;
    # a partial page or an earlier unknown item must not hide later facts.
    # A progress/source race also rejects the operation without discarding
    # original history already observed during that read.
    if not value.complete or known - seen:
        raise OperationDenied('technical_replan_effects_unknown')
    remaining()
    if runner.decision_source is not provider:
        raise OperationDenied('technical_replan_effects_unknown')
    with reader.read_budget(seconds=remaining(), requests=64):
        original = reader.decision_progress_source(repository, number)
    if (original['record'] if original is not None else None) != record:
        raise OperationDenied('technical_replan_source_changed')
    for fact, root, observed in retained:
        effect = fact.effect
        if fact.state == 'not_dispatched' and observed.unresolved:
            raise OperationDenied('technical_replan_unconfirmed')
        successor = str(uuid.uuid5(uuid.NAMESPACE_URL, 'hydra:technical-replan:v1:' + ':'.join(map(str, effect))))
        if root is None and observed.root is not None:
            root = json.loads(observed.root)
        confirmed = (root is not None and original is not None
            and original['record'].get('attempt_id') == successor and original['native_root'] == root
            and original['decision_context'] == {'source_attempt': root['decision']['key']['source_attempt'],
                                                  'resume_attempt': successor})
        ended = fact.complete and fact.state in {'not_dispatched', 'not_applied', 'applied'}
        if not ended and not confirmed:
            raise OperationDenied('technical_replan_unconfirmed')
        if fact.state == 'applied' and record is not None and record.get('attempt_id') == effect[2]:
            raise OperationDenied('technical_replan_source_changed')
        if observed.intent_digest is not None and fact.intent_digest is None and not confirmed:
            raise OperationDenied('technical_replan_effects_unknown')
        attempts.pop(effect, None)
        if record is not None and record.get('attempt_id') == effect[2]:
            observations[effect] = replace(observed, unresolved=False)
        else:
            observations.pop(effect, None)
    remaining()


def technical_replan(frame, record, values):
    runner, repository, number = frame.runner, frame.repository, frame.number
    if (not frame.consumed or frame.coordinator is None or record.get('native_step')
            or record.get('pending_action') is not None or record.get('phase') == 'executing'
            or record.get('wait_reason') != 'replan_required' or record.get('host_alias') != runner.host):
        raise OperationDenied('technical_replan_original_effect_pending')
    bound = runner._policy_scope.get()
    config = {**bound[1], 'intake_digest': record.get('intake_digest')}
    reader = runner.github.read_client()
    with reader.read_budget(seconds=15, requests=64):
        source = reader.decision_progress_source(repository, number)
        authorization = _ready(reader, repository, number, record, config)
    root = decision_root(frame.coordinator.selection.context)
    context = {'source_attempt': root['decision']['key']['source_attempt'],
               'resume_attempt': record['attempt_id']}
    if (source is None or source['record'] != record or source['decision_context'] != context
            or source['native_root'] != root and not (source['native_root'] is None
                and record['attempt_id'] == root['resume_attempt'])):
        raise OperationDenied('technical_replan_source_changed')
    effect = (record['repository_id'], number, record['attempt_id'])
    successor = str(uuid.uuid5(uuid.NAMESPACE_URL, 'hydra:technical-replan:v1:' + ':'.join(map(str, effect))))
    if successor in {record['attempt_id'], root['resume_attempt'], context['source_attempt']}:
        raise OperationDenied('technical_replan_successor_not_fresh')
    after_values = runner._record_values(record, **values, attempt_id=successor)
    after = {**after_values, 'version': 1, 'repository_id': record['repository_id'], 'issue_number': number}
    intent = TechnicalReplanIntent(effect, canonical(record), canonical(after), canonical(context),
        None if source['native_root'] is None else canonical(source['native_root']), canonical(root),
        canonical(authorization))
    initial = _coverage(frame, intent)
    if effect not in runner.technical_replan_attempts and len(runner.technical_replan_attempts) >= 1024:
        raise OperationDenied('technical_replan_capacity')
    checked = [initial]

    def guard():
        if runner.decision_source is not frame.provider:
            raise OperationDenied('decision_source_changed')
        checked[0] = _coverage(frame, intent)
        current = runner.github.read_client()
        with current.read_budget(seconds=15, requests=64):
            reason = runner._latest(repository, number, config, github=current)
            if reason:
                raise OperationDenied(reason)
            ready = _ready(current, repository, number, record, config)
            observed = current.decision_progress_source(repository, number)
        if canonical(ready) != intent.authorization or observed != source:
            raise OperationDenied('technical_replan_source_changed')

    def attempted():
        known = runner.technical_replan_attempts.get(effect)
        observed = runner.technical_replan_observations.get(effect)
        count = max(checked[0].writes, known[1] if known else 0,
                    observed.minimum_writes if observed else 0) + 1
        _retain_observation(runner, effect, intent.digest, intent.root, count, unresolved=True)
        runner.technical_replan_attempts[effect] = (intent.digest, count, intent)

    permit = TechnicalReplanPermit(intent, attempted)
    previous_guard = frame.technical_guard
    if previous_guard is not None:
        raise OperationDenied('technical_replan_scope_conflict')
    frame.technical_guard = guard
    try:
        runner._effect(repository, runner.github.record_checkpoint, repository, number, after_values,
            preserve_decision_context=True, decision_successor=permit, _checkpoint_effect='progress')
    except GitHubError:
        pass  # Only exact original read-back can confirm this mutable write.
    finally:
        frame.technical_guard = previous_guard
    current = runner.github.read_client()
    with current.read_budget(seconds=15, requests=64):
        observed = current.decision_progress_source(repository, number)
    if (observed is None or canonical(observed['record']) != intent.after
            or observed['native_root'] != root or observed['decision_context'] !=
                {'source_attempt': context['source_attempt'], 'resume_attempt': successor}):
        raise OperationDenied('technical_replan_unconfirmed')
    runner.technical_replan_attempts.pop(effect, None)
    runner.technical_replan_observations.pop(effect, None)
    continuation = runner._continuation_scope.get()
    if continuation is not None:
        continuation.recorded(observed['record'])
    return copy.deepcopy(observed['record'])
