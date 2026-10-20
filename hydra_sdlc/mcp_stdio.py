"""Bounded input for the dedicated POSIX MCP entry; the SDK owns JSON-RPC."""
from contextlib import contextmanager
import json
import math
import os
import stat
import sys
import threading

from .control_commands import MAX_COMMAND_BYTES

# A command includes its params/metadata bound. Allow a separately bounded RPC
# envelope. Every UTF-8 byte needs at most six wire bytes under JSON escaping
# (ASCII \uXXXX is worst; an astral scalar needs 12 / 4). CRLF adds two.
MAX_RPC_OVERHEAD_BYTES = 16 * 1024
MAX_DECODED_BYTES = MAX_COMMAND_BYTES + MAX_RPC_OVERHEAD_BYTES
MAX_WIRE_BYTES = 6 * MAX_DECODED_BYTES + 2
MAX_JSON_DEPTH = 64
READ_BYTES = 8192
INVALID_FRAME = '{\n'
_owner = threading.Lock()


class StdioUnavailable(RuntimeError):
    def __init__(self):
        super().__init__('stdio_unavailable')


class InvalidFrame(ValueError):
    pass


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidFrame()
        result[key] = value
    return result


def _constant(value):
    raise InvalidFrame()


def _bounded_depth(text):
    depth, quoted, escaped = 0, False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '[{':
            depth += 1
            if depth > MAX_JSON_DEPTH:
                raise InvalidFrame()
        elif char in ']}':
            depth -= 1


def _bounded_value(value):
    pending, count, string_bytes = [value], 0, 0
    while pending:
        item = pending.pop()
        count += 1
        # Each node/key needs at least one byte in any legal compact JSON.
        if count > MAX_DECODED_BYTES:
            raise InvalidFrame()
        if type(item) is dict:
            pending.extend(item.keys())
            pending.extend(item.values())
        elif type(item) is list:
            pending.extend(item)
        elif type(item) is str:
            string_bytes += len(item.encode('utf-8', errors='strict'))
            if string_bytes > MAX_DECODED_BYTES:
                raise InvalidFrame()
        elif type(item) is float and not math.isfinite(item):
            raise InvalidFrame()
    if len(json.dumps(value, ensure_ascii=False, allow_nan=False,
                      separators=(',', ':')).encode('utf-8')) > MAX_DECODED_BYTES:
        raise InvalidFrame()


def _bounded_rpc(value):
    # The public SDK validates the envelope; these are only size measurements.
    bodies = ('params', 'result', 'error')
    compact = lambda item: len(json.dumps(item, ensure_ascii=False, allow_nan=False,
                                         separators=(',', ':')).encode('utf-8'))
    overhead = {key: None if key in bodies else item for key, item in value.items()}
    if compact(overhead) > MAX_RPC_OVERHEAD_BYTES:
        raise InvalidFrame()
    if sum(compact(value[key]) for key in bodies if key in value) > MAX_COMMAND_BYTES:
        raise InvalidFrame()


def validate_frame(raw):
    """Return unchanged valid text, or a constant for the SDK's error path.

    Never reconstruct a JSON-RPC envelope or infer an ambiguous request ID.
    Generic SDK validation happens here too, before its formatter sees input.
    """
    from mcp.types import jsonrpc_message_adapter
    try:
        if len(raw) > MAX_WIRE_BYTES:
            raise InvalidFrame()
        text = raw.decode('utf-8', errors='strict')
        _bounded_depth(text)
        value = json.loads(text, object_pairs_hook=_pairs, parse_constant=_constant)
        _bounded_value(value)
        jsonrpc_message_adapter.validate_python(value, by_name=False)
        _bounded_rpc(value)
        return text
    except (ValueError, TypeError, OverflowError, RecursionError):
        return INVALID_FRAME


class ValidatedLines:
    """A bounded line iterator; no worker can remain blocked on a recycled fd."""
    def __init__(self, fd):
        self.fd = fd
        self.buffered_peak = 0

    def __aiter__(self):
        return self._lines()

    async def _lines(self):
        import anyio
        buffer, oversized = bytearray(), False
        while True:
            try:
                await anyio.wait_readable(self.fd)
                chunk = os.read(self.fd, READ_BYTES)
            except BlockingIOError:
                continue
            except OSError:
                raise StdioUnavailable() from None
            if not chunk:
                if oversized:
                    yield INVALID_FRAME
                elif buffer:
                    yield validate_frame(bytes(buffer))
                return
            start = 0
            while start < len(chunk):
                end = chunk.find(b'\n', start)
                complete = end != -1
                end = end + 1 if complete else len(chunk)
                part = chunk[start:end]
                if not oversized:
                    if len(buffer) + len(part) > MAX_WIRE_BYTES:
                        buffer.clear()
                        oversized = True
                    else:
                        buffer.extend(part)
                        self.buffered_peak = max(self.buffered_peak, len(buffer))
                if complete:
                    yield INVALID_FRAME if oversized else validate_frame(bytes(buffer))
                    buffer.clear()
                    oversized = False
                start = end


def _identity(fd):
    value = os.fstat(fd)
    return value.st_dev, value.st_ino, value.st_mode


@contextmanager
def claimed_stdin():
    """Only the fresh, sole dedicated entry may own fd0; no unsafe fallback.

    Failed restoration is fatal. Retain the duplicate on failure rather than
    recycling a descriptor still needed to recover the original wire.
    """
    if os.name != 'posix' or threading.current_thread() is not threading.main_thread():
        raise StdioUnavailable()
    import fcntl
    if not _owner.acquire(blocking=False):
        raise StdioUnavailable()
    owned, flags, attempted, restored = None, None, False, False
    try:
        if sys.stdin.fileno() != 0 or not stat.S_ISFIFO(os.fstat(0).st_mode):
            raise StdioUnavailable()
        owned = fcntl.fcntl(0, fcntl.F_DUPFD_CLOEXEC, 3)
        flags = fcntl.fcntl(owned, fcntl.F_GETFL)
        null = os.open(os.devnull, os.O_RDONLY | os.O_CLOEXEC)
        try:
            attempted = True
            os.dup2(null, 0)
            if _identity(0) != _identity(null):
                raise StdioUnavailable()
        finally:
            os.close(null)
        fcntl.fcntl(owned, fcntl.F_SETFL, flags | os.O_NONBLOCK)
        yield ValidatedLines(owned)
    except (OSError, ValueError):
        raise StdioUnavailable() from None
    finally:
        try:
            if owned is not None:
                if flags is not None:
                    fcntl.fcntl(owned, fcntl.F_SETFL, flags)
                if attempted:
                    os.dup2(owned, 0)
                restored = True
        except OSError:
            raise StdioUnavailable() from None
        finally:
            if owned is None or restored:
                if owned is not None:
                    os.close(owned)
                _owner.release()


async def compose_server(high, subscriptions):
    """Adapt the current registry through public SDK handlers and actual Context."""
    import base64
    from mcp.server.lowlevel import Server
    from mcp.server.mcpserver import Context
    from mcp.server.mcpserver.exceptions import ResourceError, ResourceNotFoundError
    from mcp.server.subscriptions import ListenHandler
    from mcp.shared.exceptions import MCPError
    from mcp.types import (BlobResourceContents, CallToolResult,
        InputRequiredResult, ListPromptsResult, ListResourcesResult, ListResourceTemplatesResult,
        ListToolsResult, ReadResourceResult, TextContent, TextResourceContents, INVALID_PARAMS, INTERNAL_ERROR)

    def context(ctx, params):
        return Context(request_context=ctx, mcp_server=high, input_params=params, subscriptions=subscriptions)

    async def list_tools(ctx, params):
        return ListToolsResult(tools=await high.list_tools())

    async def call_tool(ctx, params):
        try:
            return await high.call_tool(params.name, params.arguments or {}, context(ctx, params))
        except MCPError:
            raise
        except Exception as exc:
            return CallToolResult(content=[TextContent(type='text', text=str(exc))], is_error=True)

    async def list_prompts(ctx, params):
        return ListPromptsResult(prompts=await high.list_prompts())

    async def get_prompt(ctx, params):
        return await high.get_prompt(params.name, params.arguments, context(ctx, params))

    async def list_resources(ctx, params):
        return ListResourcesResult(resources=await high.list_resources())

    async def list_templates(ctx, params):
        return ListResourceTemplatesResult(resource_templates=await high.list_resource_templates())

    async def read_resource(ctx, params):
        try:
            items = await high.read_resource(params.uri, context(ctx, params))
        except ResourceError as exc:
            code = INVALID_PARAMS if isinstance(exc, ResourceNotFoundError) else INTERNAL_ERROR
            raise MCPError(code=code, message=str(exc), data={'uri': str(params.uri)}) from None
        if isinstance(items, InputRequiredResult):
            return items
        contents = []
        for item in items:
            if isinstance(item.content, bytes):
                contents.append(BlobResourceContents(uri=params.uri, blob=base64.b64encode(item.content).decode(),
                    mime_type=item.mime_type or 'application/octet-stream', _meta=item.meta))
            else:
                contents.append(TextResourceContents(uri=params.uri, text=item.content,
                    mime_type=item.mime_type or 'text/plain', _meta=item.meta))
        return ReadResourceResult(contents=contents)

    schemas = {tool.name: tool.input_schema for tool in await high.list_tools()}
    low = Server(high.name, title=high.title, description=high.description, instructions=high.instructions,
        website_url=high.website_url, icons=high.icons, version=high.version,
        get_tool_input_schema=schemas.get, on_list_tools=list_tools, on_call_tool=call_tool,
        on_list_prompts=list_prompts, on_get_prompt=get_prompt, on_list_resources=list_resources,
        on_list_resource_templates=list_templates, on_read_resource=read_resource,
        on_subscriptions_listen=ListenHandler(subscriptions))
    low.middleware[:] = list(high.middleware)
    return low


async def serve_stdio(high, subscriptions):
    """Serve one dedicated process; only the official SDK writes protocol output."""
    from mcp.server.stdio import stdio_server
    original_stdout = _identity(1)
    if not stat.S_ISFIFO(original_stdout[2]) or original_stdout == _identity(2):
        raise StdioUnavailable()
    low = await compose_server(high, subscriptions)
    with claimed_stdin() as stdin:
        async with stdio_server(stdin=stdin) as (reader, writer):
            if _identity(1) != _identity(2):
                raise StdioUnavailable()
            await low.run(reader, writer, low.create_initialization_options())
    if _identity(1) != original_stdout:
        raise StdioUnavailable()


def run_stdio(high, subscriptions):
    import anyio
    try:
        anyio.run(serve_stdio, high, subscriptions)
    except StdioUnavailable:
        print('stdio_unavailable', file=sys.stderr)
        raise SystemExit(2) from None
