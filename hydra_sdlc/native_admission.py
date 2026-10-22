"""Explicit shared-installation authority for STDIO project admission only."""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from .operations import MAX_PROJECTS, MAX_REVISION

_FIELDS = {'schema_version', 'enabled', 'repository_ids', 'expires_at'}
_REQUIRED = {'schema_version', 'enabled', 'repository_ids'}
_EXPIRY = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z')


def _expiry(value):
    if type(value) is not str or not _EXPIRY.fullmatch(value):
        raise ValueError('Invalid installed admission profile')
    return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)


def parse_admission_profile(value):
    """Validate a closed settings table and normalize only repository order."""
    if (type(value) is not dict or not _REQUIRED <= set(value) <= _FIELDS
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or type(value['enabled']) is not bool):
        raise ValueError('Invalid installed admission profile')
    identifiers = value['repository_ids']
    if (type(identifiers) is not list or len(identifiers) > MAX_PROJECTS
            or any(type(identifier) is not int or not 1 <= identifier <= MAX_REVISION
                   for identifier in identifiers)
            or len(set(identifiers)) != len(identifiers)):
        raise ValueError('Invalid installed admission profile')
    result = {'schema_version': 1, 'enabled': value['enabled'], 'repository_ids': sorted(identifiers)}
    if 'expires_at' in value:
        _expiry(value['expires_at'])
        result['expires_at'] = value['expires_at']
    return result


def _now():
    return datetime.now(timezone.utc)


class InstallationAdmissionProvider:
    """Re-read one protected config; Context checks routing, not human identity."""

    def __init__(self, config_path):
        self._config_path = Path(config_path).expanduser().absolute()

    def __call__(self, context):
        if context is None:
            return None
        try:
            from mcp.server.mcpserver import Context
        except ImportError:
            return None
        if not isinstance(context, Context):
            return None
        from .control import load_host_config
        from .control_commands import AdmissionCallContext
        from .runtime_identity import capture_runtime_identity
        try:
            config = load_host_config(self._config_path)
            profile = config.get('native_admission_control')
            if not profile or not profile['enabled']:
                return None
            if 'expires_at' in profile and _now() >= _expiry(profile['expires_at']):
                return None
            digest = capture_runtime_identity(config)['config_digest']
            if digest is None:
                return None
            return AdmissionCallContext('native', None, frozenset(profile['repository_ids']),
                                        frozenset({'admission_set'}), config_digest=digest)
        except Exception:
            # Unavailable settings never supply a grant or disclose raw diagnostics.
            return None


def installation_admission_provider(config_path):
    return InstallationAdmissionProvider(config_path)
