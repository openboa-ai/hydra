"""Inactive internal reader for one already mapped native question.

No default transport, task discovery, persistence or lifecycle effects. A server
must supply a scoped source whose transport enforces bounded reads and cleanup.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass, field
import hashlib
import json
import re
import time
from typing import Protocol


@dataclass(frozen=True, repr=False)
class SourceScope:
    source_id: str
    connection_id: str
    task_id: str


@dataclass(frozen=True, repr=False)
class QuestionLocator:
    scope: SourceScope
    turn_id: str
    item_id: str


@dataclass(frozen=True, repr=False)
class PageRequest:
    task_id: str
    turn_id: str
    anchor: str
    direction: str
    limit: int = 20
    method: str = 'thread/items/list'

    def params(self):
        return {'threadId': self.task_id, 'turnId': self.turn_id,
                'sortDirection': self.direction, 'limit': self.limit,
                'cursor': {'type': 'item', 'itemId': self.anchor}}


class PageSource(Protocol):
    def binding(self) -> SourceScope | None: ...

    def open_page(self, request: PageRequest, *, max_bytes: int,
                  timeout: float) -> AbstractAsyncContextManager[AsyncIterator[bytes]]: ...


@dataclass(frozen=True, repr=False)
class Question:
    title: str
    options: tuple[str, ...] | None
    options_present: bool


@dataclass(frozen=True, repr=False)
class QuestionObservation:
    locator: QuestionLocator
    questions: tuple[Question, ...]
    content_digest: str
    repeated: bool
    source_revision: None = None


@dataclass(frozen=True)
class QuestionRead:
    status: str
    reason: str
    pages_read: int = 0
    observation: QuestionObservation | None = field(default=None, repr=False)


class SourceFailure(Exception):
    """Adapter-classified failures; provider exception text is never returned."""

    def __init__(self, kind):
        super().__init__()
        self.kind = kind if kind in {'unsupported', 'not_found', 'access_denied'} else 'unavailable'


class _ReadFailure(Exception):
    def __init__(self, reason, status='unavailable'):
        super().__init__()
        self.reason, self.status = reason, status


def _require(condition, reason='invalid_response'):
    if not condition:
        raise _ReadFailure(reason)


def _identifier(value):
    return (isinstance(value, str) and 0 < len(value) <= 256
            and all(ord(char) >= 32 and not 127 <= ord(char) <= 159 for char in value))


def _valid_scope(scope):
    return (isinstance(scope, SourceScope)
            and all(_identifier(value) for value in (scope.source_id, scope.connection_id, scope.task_id)))


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result)
        result[key] = value
    return result


def _reject_constant(value):
    raise _ReadFailure('invalid_response')


def _page(raw, locator, anchor):
    response = json.loads(raw.decode('utf-8'), object_pairs_hook=_unique_object,
                          parse_constant=_reject_constant)
    _require(type(response) is dict)
    if 'error' in response:
        error = response['error']
        if type(error) is dict and error.get('code') == -32601:
            raise _ReadFailure('source_failure', 'unsupported')
        raise _ReadFailure('rpc_error')
    result = response.get('result')
    _require(type(result) is dict and type(result.get('data')) is list)
    entries = result['data']
    _require(len(entries) <= 20, 'item_limit')
    seen = set()
    for entry in entries:
        _require(type(entry) is dict and entry.get('turnId') == locator.turn_id)
        item = entry.get('item')
        _require(type(item) is dict and _identifier(item.get('id'))
                 and _identifier(item.get('type')))
        item_id = item['id']
        _require(item_id != anchor and item_id not in seen, 'invalid_anchor_page')
        seen.add(item_id)
    return entries


def _question(entries, locator):
    for entry in entries:
        item = entry['item']
        if item['id'] != locator.item_id:
            continue
        if item['type'] != 'agentMessage':
            raise _ReadFailure('question_type_changed', 'conflict')
        _require(item.get('delivery') == 'async', 'invalid_question')
        questions = item.get('questions')
        _require(type(questions) is list and bool(questions), 'invalid_question')
        normalized, canonical = [], []
        for value in questions:
            _require(type(value) is dict and isinstance(value.get('title'), str)
                     and bool(value['title']), 'invalid_question')
            title = value['title']
            options = value.get('options')
            _require(options is None or (type(options) is list
                     and all(isinstance(option, str) for option in options)), 'invalid_question')
            present = 'options' in value
            normalized.append(Question(title, None if options is None else tuple(options), present))
            selected = {'title': title}
            if present:
                selected['options'] = options
            canonical.append(selected)
        data = json.dumps(canonical, sort_keys=True, ensure_ascii=False,
                          separators=(',', ':')).encode('utf-8')
        return tuple(normalized), hashlib.sha256(data).hexdigest()
    raise _ReadFailure('target_not_observed', 'inconclusive')


async def read_question(source: PageSource, scope: SourceScope,
                        locator: QuestionLocator | None, *, previous_digest=None,
                        repeat=False, clock: Callable[[], float] | None = None) -> QuestionRead:
    """Read at most DESC(Q), ASC(B), and one optional exact ASC(B) repeat.

    The injected adapter owns transport-level byte/time limits and cancellation
    cleanup. These checks also bound assembly and processing here. Cancellation
    propagates after the owned request context exits; it never schedules a retry.
    """
    if locator is None:
        return QuestionRead('mapping_unavailable', 'locator_missing')
    pages, total = 0, 0
    clock = clock or time.monotonic
    deadline = clock() + 50

    def remaining():
        left = deadline - clock()
        if left <= 0:
            raise _ReadFailure('deadline_exhausted')
        return left

    def bound():
        _require(source.binding() == scope, 'scope_changed')

    async def read(direction, anchor):
        nonlocal pages, total
        bound()
        timeout = min(30, remaining())
        _require(pages < 3, 'page_limit')
        pages += 1
        raw = bytearray()
        request = PageRequest(scope.task_id, locator.turn_id, anchor, direction)
        async with asyncio.timeout(timeout):
            async with source.open_page(request, max_bytes=1_048_576, timeout=timeout) as chunks:
                async for chunk in chunks:
                    remaining()
                    _require(type(chunk) is bytes, 'invalid_response')
                    _require(len(raw) + len(chunk) <= 1_048_576
                             and total + len(chunk) <= 3_145_728, 'input_limit')
                    raw.extend(chunk)
                    total += len(chunk)
        remaining()
        bound()
        entries = _page(raw, locator, anchor)
        remaining()
        return entries

    try:
        _require(_valid_scope(scope) and isinstance(locator, QuestionLocator)
                 and _valid_scope(locator.scope) and locator.scope == scope
                 and _identifier(locator.turn_id) and _identifier(locator.item_id), 'scope_mismatch')
        _require(type(repeat) is bool and (previous_digest is None or
                 (isinstance(previous_digest, str) and re.fullmatch('[0-9a-f]{64}', previous_digest))),
                 'invalid_request')
        before = await read('desc', locator.item_id)
        if not before:
            return QuestionRead('inconclusive', 'predecessor_not_observed', pages)
        predecessor = before[0]['item']['id']
        questions, digest = _question(await read('asc', predecessor), locator)
        remaining()
        if previous_digest is not None and previous_digest != digest:
            return QuestionRead('conflict', 'question_changed', pages)
        if repeat:
            _, repeated_digest = _question(await read('asc', predecessor), locator)
            remaining()
            if repeated_digest != digest:
                return QuestionRead('conflict', 'question_changed', pages)
        remaining()
        bound()
        return QuestionRead('observed', 'question_read', pages,
                            QuestionObservation(locator, questions, digest, repeat))
    except _ReadFailure as failure:
        return QuestionRead(failure.status, failure.reason, pages)
    except SourceFailure as failure:
        return QuestionRead(failure.kind, 'source_failure', pages)
    except TimeoutError:
        return QuestionRead('unavailable', 'deadline_exhausted', pages)
    except Exception:
        # Do not persist/return raw pages, locators, source errors or transcripts.
        return QuestionRead('unavailable', 'invalid_response', pages)
