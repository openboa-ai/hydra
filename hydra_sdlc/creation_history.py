"""Original-outcome guards; no production history or caller source is supplied."""
from dataclasses import dataclass, replace
import os
import re
import threading

from .creation_sources import digest, require
from .operations import OperationDenied
from .work_records import _canonical, _hex


MAX_CALLS = 1024


@dataclass(frozen=True, repr=False)
class CreationIntent:
    scope: tuple[int, str]
    create_key: str
    draft_ref: str
    draft_digest: str
    proposal_digest: str
    actionable_digest: str
    source_signature: str
    runtime_key: str

    @property
    def digest(self):
        return digest(self.__dict__)


@dataclass(frozen=True, repr=False)
class CreationOwner:
    invocation_id: str
    execution_id: str
    caller_binding: str
    intent_digest: str


@dataclass(frozen=True, repr=False)
class CreationPriorCall:
    invocation_id: str
    execution_id: str
    intent_digest: str | None
    writes: int | None
    state: str


@dataclass(frozen=True, repr=False)
class CreationHistory:
    scope: tuple[int, str]
    intent_digest: str
    owner: CreationOwner
    current_first_execution: bool
    complete: bool
    prior_calls: tuple[CreationPriorCall, ...]


@dataclass(frozen=True, repr=False)
class _Observation:
    scope: tuple[int, str]
    intent_digest: str | None
    minimum_writes: int
    unresolved: bool
    claimed: bool = False


def _identifier(value):
    return type(value) is str and re.fullmatch(r'[!-~]{1,256}', value) is not None


def _identity(value):
    require(_identifier(value.invocation_id) and _identifier(value.execution_id),
            'creation_history_unknown')
    return value.invocation_id, value.execution_id


class HistoryGuard:
    def __init__(self, controller, source, command):
        self.controller = controller
        self.provider = controller.creation_source
        value = source.draft.value
        self.intent = CreationIntent((value['target_repository_id'], value['outcome_key']),
            value['create_key'], _canonical(source.reference), source.draft.digest,
            digest(source.proposal), command['expected']['source_checks'][0]['actionable_digest'],
            source.signature, command['expected']['runtime_key'])
        self.observations = controller.creation_observations
        self.owner = None
        self.claimed = False
        self.unused = {'fence', 'issue', 'binding'}
        self.local_owner = os.getpid(), threading.get_ident()

    def _provider_current(self):
        require(self.provider is not None, 'creation_history_unsupported')
        require(self.controller.creation_source is self.provider, 'creation_history_changed')

    def _remember(self, key, intent_digest, writes, unresolved, *, claimed=False):
        before = self.observations.get(key)
        if before is None:
            require(len(self.observations) < MAX_CALLS, 'creation_history_capacity')
        conflict = before is not None and (before.scope != self.intent.scope
            or writes is not None and writes < before.minimum_writes
            or before.intent_digest is not None and intent_digest is not None
               and before.intent_digest != intent_digest)
        if before is not None and before.scope != self.intent.scope:
            return False
        self.observations[key] = _Observation(self.intent.scope,
            before.intent_digest if before is not None and before.intent_digest is not None else intent_digest,
            max(before.minimum_writes if before else 0, writes or 0),
            unresolved or conflict or bool(before and before.unresolved),
            claimed or bool(before and before.claimed))
        return not conflict

    def preflight(self):
        """Read original facts outside admission; a partial page never proves absence."""
        self._provider_current()
        read = getattr(self.provider, 'read_work_creation_history', None)
        require(callable(read) and callable(getattr(self.provider, 'current_creation_owner', None)),
                'creation_history_unsupported')
        known = tuple(sorted(key for key, value in self.observations.items()
                             if value.scope == self.intent.scope))
        try:
            value = read(self.intent, known_calls=known, timeout=15)
        except Exception:
            raise OperationDenied('creation_history_unavailable') from None
        self._provider_current()
        require(type(value) is CreationHistory and type(value.scope) is tuple
            and len(value.scope) == 2 and type(value.scope[0]) is int and _hex(value.scope[1], 64)
            and value.scope == self.intent.scope and value.intent_digest == self.intent.digest
            and _hex(value.intent_digest, 64)
            and type(value.complete) is bool and type(value.current_first_execution) is bool
            and type(value.owner) is CreationOwner and value.owner.intent_digest == self.intent.digest
            and _hex(value.owner.intent_digest, 64)
            and _identifier(value.owner.caller_binding)
            and type(value.prior_calls) is tuple and len(value.prior_calls) <= MAX_CALLS,
            'creation_history_unknown')
        current = _identity(value.owner)
        if self.owner is not None:
            require(value.owner == self.owner, 'creation_history_changed')
        seen, conflict, pending, replayed = set(), False, False, False
        for record in value.prior_calls:
            require(type(record) is CreationPriorCall, 'creation_history_unknown')
            key = _identity(record)
            require(key not in seen and key != current
                and (record.intent_digest is None or _hex(record.intent_digest, 64))
                and (record.writes is None or type(record.writes) is int and 0 <= record.writes <= 3)
                and type(record.state) is str
                and record.state in {'not_dispatched', 'unconfirmed', 'not_applied', 'applied'}
                and (record.state != 'not_dispatched' or record.writes == 0)
                and (record.state not in {'not_applied', 'applied'}
                     or record.writes is not None and record.writes > 0)
                and (record.state != 'unconfirmed' or record.writes != 0),
                'creation_history_unknown')
            seen.add(key)
            replayed |= record.invocation_id == value.owner.invocation_id
            uncertain = record.writes is None or record.state == 'unconfirmed'
            if not self._remember(key, record.intent_digest, record.writes, uncertain):
                conflict = True
            observed = self.observations[key]
            pending |= bool(observed.minimum_writes or observed.unresolved or observed.claimed)
        # Retain all valid returned records before any completeness/pending hold.
        require(not conflict and set(known) - {current} <= seen, 'creation_history_unknown')
        require(value.complete, 'creation_history_unknown')
        require(not replayed, 'creation_execution_unavailable')
        require(not pending, 'creation_effect_unconfirmed')
        require(value.current_first_execution, 'creation_execution_unavailable')
        existing = self.observations.get(current)
        if not self.claimed:
            require(existing is None or (existing.scope == self.intent.scope
                and not existing.claimed and not existing.minimum_writes and not existing.unresolved
                and existing.intent_digest in {None, self.intent.digest}),
                'creation_execution_unavailable')
            require(self._remember(current, self.intent.digest, 0, False), 'creation_history_unknown')
        else:
            require(existing is not None and existing.claimed and existing.intent_digest == self.intent.digest,
                    'creation_execution_unavailable')
        self.owner = value.owner

    def consume(self, stage):
        """Only local trusted ownership validation occurs inside admission's lock."""
        self._provider_current()
        require(self.local_owner == (os.getpid(), threading.get_ident()) and self.owner is not None
                and stage in self.unused, 'creation_execution_unavailable')
        try:
            owner = self.provider.current_creation_owner(self.intent)
        except Exception:
            raise OperationDenied('creation_execution_unavailable') from None
        self._provider_current()
        require(type(owner) is CreationOwner and owner == self.owner, 'creation_execution_unavailable')
        require((stage == 'fence' and not self.claimed)
                or (stage == 'issue' and self.claimed and 'fence' not in self.unused)
                or (stage == 'binding' and self.claimed and 'issue' not in self.unused),
                'creation_execution_unavailable')
        key = _identity(owner)
        current = self.observations[key]
        require(current.minimum_writes < 3 and current.intent_digest == self.intent.digest,
                'creation_execution_unavailable')
        self.claimed = True
        self.unused.remove(stage)  # Exceptions can never restore a physical dispatch.
        self._remember(key, self.intent.digest, current.minimum_writes + 1, True, claimed=True)

    def completed(self):
        if self.claimed:
            key = _identity(self.owner)
            current = self.observations[key]
            # Only actual exact Issue/binding read-back resolves this live
            # sequence. A later zero-count history claim cannot clear it.
            self.observations[key] = replace(current, unresolved=False)
