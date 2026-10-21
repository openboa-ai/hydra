"""Inactive, explicitly injected CLI transport for the bounded question reader.

The server must qualify the selected executable, account/home, scope and locator.
These parameters are not authority. Nothing installs or chooses a default source;
this helper neither discovers tasks nor handles approval/input server requests.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import uuid

from .native_question_source import PageRequest, QuestionRead, SourceFailure, read_question


_PAGE_BYTES = 1_048_576
_AUX_BYTES = 65_536
_STARTUP_SECONDS = 15


def _object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise SourceFailure('unavailable')
        value[key] = item
    return value


def _constant(value):
    raise SourceFailure('unavailable')


class _StdioSource:
    def __init__(self, executable, binding, scope):
        self.executable, self._binding, self.scope = executable, binding, scope
        self.process = None
        self.buffer = bytearray()
        self.stdout_bytes = self.stderr_bytes = self.aux_bytes = self.notifications = self.pages = 0
        self.stderr_open = True
        self.initialized = False

    def binding(self):
        return self._binding()

    def _current(self):
        if self.binding() != self.scope:
            raise SourceFailure('unavailable')

    async def _ready(self, descriptors, *, writing=False):
        """Wait only on this invocation's nonblocking pipe descriptors."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        add = loop.add_writer if writing else loop.add_reader
        remove = loop.remove_writer if writing else loop.remove_reader
        registered = []
        def ready():
            if not future.done():
                future.set_result(None)
        try:
            for descriptor in descriptors:
                add(descriptor, ready)
                registered.append(descriptor)
            await future
        finally:
            for descriptor in registered:
                remove(descriptor)

    async def _send(self, method, params, *, identifier=None):
        self._current()
        if method not in {'initialize', 'initialized', 'thread/items/list'}:
            raise SourceFailure('unavailable')
        value = {'method': method, 'params': params}
        if identifier is not None:
            value['id'] = identifier
        raw = json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode() + b'\n'
        if len(raw) > 16_384:
            raise SourceFailure('unavailable')
        descriptor = self.process.stdin.fileno()
        while raw:
            self._current()
            try:
                written = os.write(descriptor, raw)
            except BlockingIOError:
                await self._ready([descriptor], writing=True)
                continue
            if written <= 0:
                raise SourceFailure('unavailable')
            raw = raw[written:]

    async def _read(self):
        output = self.process.stdout.fileno()
        error = self.process.stderr.fileno()
        while True:
            self._current()
            descriptors = [output] + ([error] if self.stderr_open else [])
            # Bound diagnostics before accepting a simultaneously available result.
            if self.stderr_open:
                try:
                    chunk = os.read(error, 8192)
                except BlockingIOError:
                    pass
                else:
                    self.stderr_bytes += len(chunk)
                    if self.stderr_bytes > _AUX_BYTES:
                        raise SourceFailure('unavailable')
                    self.stderr_open = bool(chunk)
            try:
                chunk = os.read(output, 8192)
            except BlockingIOError:
                descriptors = [output] + ([error] if self.stderr_open else [])
                await self._ready(descriptors)
                continue
            if not chunk:
                raise SourceFailure('unavailable')
            self.stdout_bytes += len(chunk)
            if self.stdout_bytes > 3 * _PAGE_BYTES + _AUX_BYTES:
                raise SourceFailure('unavailable')
            return chunk

    async def _receive(self, identifier, limit, *, startup=False):
        while True:
            boundary = self.buffer.find(b'\n')
            if boundary < 0:
                if len(self.buffer) >= limit:
                    raise SourceFailure('unavailable')
                self.buffer.extend(await self._read())
                continue
            if boundary + 1 > limit:
                raise SourceFailure('unavailable')
            raw = bytes(self.buffer[:boundary + 1])
            del self.buffer[:boundary + 1]
            try:
                value = json.loads(raw.decode('utf-8'), object_pairs_hook=_object,
                                   parse_constant=_constant)
            except (ValueError, UnicodeError, RecursionError):
                raise SourceFailure('unavailable') from None
            if type(value) is not dict:
                raise SourceFailure('unavailable')
            if 'method' in value:
                if 'id' in value or not isinstance(value['method'], str):
                    # A read must not answer approvals, elicitation or tool calls.
                    raise SourceFailure('unavailable')
                self.notifications += 1
                self.aux_bytes += len(raw)
                if self.notifications > 32 or self.aux_bytes > _AUX_BYTES:
                    raise SourceFailure('unavailable')
                continue
            if value.get('id') != identifier or ('result' in value) == ('error' in value):
                raise SourceFailure('unavailable')
            self._current()
            if startup:
                self.aux_bytes += len(raw)
                if self.aux_bytes > _AUX_BYTES:
                    raise SourceFailure('unavailable')
            return raw, value

    async def _start(self):
        if self.initialized:
            return
        self._current()
        executable = Path(self.executable)
        if os.name != 'posix' or not executable.is_absolute():
            raise SourceFailure('unsupported' if os.name != 'posix' else 'unavailable')
        # Keep the already selected account/home. No alternate configuration,
        # model invocation, listener or shell command is selected on failure.
        try:
            self.process = subprocess.Popen([str(executable), 'app-server', '--listen', 'stdio://'],
                cwd='/', stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                bufsize=0, start_new_session=True)
        except OSError:
            raise SourceFailure('unavailable') from None
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            os.set_blocking(stream.fileno(), False)
        identifier = uuid.uuid4().hex
        async with asyncio.timeout(_STARTUP_SECONDS):
            await self._send('initialize', {'clientInfo': {
                'name': 'hydra_readonly_question_source', 'version': '1'}}, identifier=identifier)
            _, value = await self._receive(identifier, _AUX_BYTES, startup=True)
            if 'error' in value:
                error = value['error']
                raise SourceFailure('unsupported' if type(error) is dict
                                    and error.get('code') == -32601 else 'unavailable')
            if type(value['result']) is not dict:
                raise SourceFailure('unavailable')
            await self._send('initialized', {})
        self.initialized = True

    @asynccontextmanager
    async def open_page(self, request, *, max_bytes, timeout):
        self._current()
        if (type(request) is not PageRequest or request.method != 'thread/items/list'
                or request.task_id != self.scope.task_id or request.limit != 20
                or request.direction not in {'asc', 'desc'} or max_bytes != _PAGE_BYTES
                or not 0 < timeout <= 30 or self.pages >= 3):
            raise SourceFailure('unavailable')
        async with asyncio.timeout(timeout):
            await self._start()
            self.pages += 1
            identifier = uuid.uuid4().hex
            await self._send('thread/items/list', request.params(), identifier=identifier)
            raw, _ = await self._receive(identifier, max_bytes)
            async def chunks():
                yield raw
            yield chunks()

    async def close(self):
        """Release owned pipes and bound EOF/terminate/kill of the owned child.

        This is trusted CLI request cleanup, not containment of a hostile program
        or an assertion that unrelated/native application processes terminated.
        """
        process = self.process
        self.buffer.clear()
        if process is None:
            return True
        for stream in (process.stdin, process.stdout, process.stderr):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        for action, seconds in ((None, .25), (signal.SIGTERM, .5), (signal.SIGKILL, 1)):
            if process.poll() is not None:
                return True
            if action is not None:
                try:
                    os.killpg(process.pid, action)
                except ProcessLookupError:
                    pass
            deadline = time.monotonic() + seconds
            while process.poll() is None and time.monotonic() < deadline:
                await asyncio.sleep(.01)
        return process.poll() is not None


async def _closed(source):
    task = asyncio.create_task(source.close())
    interrupted = False
    while True:
        try:
            result = await asyncio.shield(task)
            break
        except asyncio.CancelledError:
            interrupted = True
        except Exception:
            result = False
            break
    if interrupted:
        raise asyncio.CancelledError
    return result


async def read_question_stdio(executable, binding, scope, locator, *,
                              previous_digest=None, repeat=False, clock=None):
    """Read through one explicitly selected owned stdio invocation, then close it.

    Missing/invalid locators and initial binding mismatches start no process. The
    existing reader owns the 50-second/three-page budget, including initialization.
    Bounded owned-child cleanup follows success, failure and cancellation. No
    persistence, caller/work authentication, default profile or live grant exists.
    """
    source = _StdioSource(executable, binding, scope)
    try:
        result = await read_question(source, scope, locator, previous_digest=previous_digest,
                                     repeat=repeat, clock=clock)
    finally:
        ended = await _closed(source)
    if not ended:
        return QuestionRead('unavailable', 'source_failure', result.pages_read)
    return result
