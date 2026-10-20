"""Sanitized GitHub GET metadata for read-only projection, never credentials."""
from dataclasses import dataclass, replace
from datetime import timezone
from email.utils import parsedate_to_datetime
import json
import math
import re
import time

MAX_INTEGER = 9_007_199_254_740_991


@dataclass(frozen=True)
class ReadResponse:
    status: int
    value: object
    limited: bool = False
    retry_after: int | None = None
    received_at: float = 0.0

    def remaining_wait(self, now=None):
        if self.retry_after is None:
            return None
        elapsed = max(0.0, (time.monotonic() if now is None else now) - self.received_at)
        return max(0, self.retry_after - math.floor(elapsed))

    def without_value(self):
        return replace(self, value=None)


def _uint(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,16}', value.strip()):
        return None
    value = int(value)
    return value if value <= MAX_INTEGER else None


def _date(value):
    try:
        date = parsedate_to_datetime(value)
        if date.tzinfo is not None and date.utcoffset().total_seconds() == 0:
            return date.astimezone(timezone.utc)
    except (ValueError, TypeError, OverflowError, AttributeError):
        pass
    return None


def parse_response(raw, *, status_hint=None, now=None):
    """Consume bounded gh --include output; retain no raw headers/error body.

    Server Date anchors absolute retry/reset values. Without that anchor an
    absolute timestamp is unqualified, never a manufactured provider zero.
    """
    if type(raw) is not str or len(raw.encode('utf-8')) > 8_000_000:
        raise ValueError('Invalid GitHub read response')
    received = time.monotonic() if now is None else now
    raw = raw.replace('\r\n', '\n')
    headers, status = {}, status_hint
    for _ in range(5):
        if not raw.startswith('HTTP/'):
            break
        block, separator, body = raw.partition('\n\n')
        if not separator or len(block.encode('utf-8')) > 16384:
            raise ValueError('Invalid GitHub read response')
        lines = block.splitlines()
        match = re.fullmatch(r'HTTP/\d+(?:\.\d+)?\s+([1-5][0-9]{2})(?:\s+.*)?', lines[0])
        if match is None:
            raise ValueError('Invalid GitHub read response')
        status, headers = int(match[1]), {}
        for line in lines[1:]:
            key, separator, value = line.partition(':')
            if not separator or not re.fullmatch('[A-Za-z0-9-]+', key):
                raise ValueError('Invalid GitHub read response')
            key = key.lower()
            if key in {'date', 'retry-after', 'x-ratelimit-reset', 'x-ratelimit-remaining'}:
                headers.setdefault(key, []).append(value.strip())
        raw = body
    if raw.startswith('HTTP/') or type(status) is not int or not 100 <= status <= 599:
        raise ValueError('Invalid GitHub read response')
    value = json.loads(raw) if raw.strip() else None
    anchors = [date for item in headers.get('date', []) if (date := _date(item)) is not None]
    delays = []
    for item in headers.get('retry-after', []):
        seconds = _uint(item)
        if seconds is not None:
            delays.append(seconds)
        elif anchors and (date := _date(item)) is not None:
            delays.extend(max(0, math.ceil((date - anchor).total_seconds())) for anchor in anchors)
    remaining = [_uint(item) for item in headers.get('x-ratelimit-remaining', [])]
    if 0 in remaining and anchors:
        for item in headers.get('x-ratelimit-reset', []):
            reset = _uint(item)
            if reset is not None:
                delays.extend(max(0, math.ceil(reset - anchor.timestamp())) for anchor in anchors)
    delay = max(delays) if delays else None
    if delay is not None and delay > MAX_INTEGER:
        raise ValueError('Invalid GitHub read response')
    message = value.get('message', '') if isinstance(value, dict) else ''
    message = message.lower() if isinstance(message, str) else ''
    limited = (status == 429 or 0 in remaining or 'retry-after' in headers or status == 403 and (
        'retry-after' in headers or 'secondary rate limit' in message or 'rate limit exceeded' in message))
    return ReadResponse(status, value, limited, delay, received)
