"""Shared public closing-intent guard for publication and protected delivery."""
import re


CLOSING_INTENT = re.compile(r'\b(?:close[sd]?|fix(?:e[sd])?|resolve[sd]?)(?:\s*:\s*|\s+)'
    r'(?:(?:[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)?#[1-9][0-9]*'
    r'|https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/issues/[1-9][0-9]*)', re.I)
