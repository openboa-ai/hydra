"""Explicit per-command authority from protected installation workflow settings.

The shared installation is the principal. SDK routing is not evidence of a
particular human, task or answer, and command content cannot expand this grant.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import re

from .operations import MAX_PROJECTS, MAX_REVISION


_FIELDS = {'schema_version', 'enabled', 'repository_ids', 'operations', 'expires_at'}
_OPERATIONS = frozenset({'workflow_step.decision_submit', 'workflow_step.continue',
                         'command_reply.native_handoff_v1'})
_EXPIRY = re.compile(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z\Z')


def _expiry(value):
    if type(value) is not str or not _EXPIRY.fullmatch(value):
        raise ValueError('Invalid installed workflow profile')
    try:
        return datetime.strptime(value, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
    except ValueError:
        raise ValueError('Invalid installed workflow profile') from None


def parse_workflow_profile(value):
    """Validate all fields, including a disabled profile's required expiry."""
    if (type(value) is not dict or set(value) != _FIELDS
            or type(value['schema_version']) is not int or value['schema_version'] != 1
            or type(value['enabled']) is not bool):
        raise ValueError('Invalid installed workflow profile')
    identifiers, operations = value['repository_ids'], value['operations']
    if (type(identifiers) is not list or len(identifiers) > MAX_PROJECTS
            or any(type(identifier) is not int or not 1 <= identifier <= MAX_REVISION
                   for identifier in identifiers)
            or len(set(identifiers)) != len(identifiers)
            or type(operations) is not list or len(operations) > len(_OPERATIONS)
            or any(type(operation) is not str or operation not in _OPERATIONS
                   for operation in operations)
            or len(set(operations)) != len(operations)):
        raise ValueError('Invalid installed workflow profile')
    _expiry(value['expires_at'])
    return {'schema_version': 1, 'enabled': value['enabled'],
            'repository_ids': sorted(identifiers), 'operations': sorted(operations),
            'expires_at': value['expires_at']}


def _now():
    return datetime.now(timezone.utc)


class InstallationWorkflowProvider:
    """Re-read one selected profile for an actual SDK call and parsed command."""

    def __init__(self, config_path):
        self._config_path = Path(config_path).expanduser().absolute()

    def for_command(self, context, command):
        if context is None:
            return None
        try:
            from mcp.server.mcpserver import Context
        except ImportError:
            return None
        if not isinstance(context, Context):
            return None
        if type(command) is not dict or command.get('action') != 'workflow_step':
            return None
        target, parameters = command.get('target'), command.get('parameters')
        if (type(target) is not dict or type(parameters) is not dict
                or type(target.get('repository_id')) is not int
                or not 1 <= target['repository_id'] <= MAX_REVISION
                or type(parameters.get('operation')) is not str
                or parameters.get('operation') not in {'decision_submit', 'continue'}):
            return None
        operation = 'workflow_step.' + parameters['operation']
        from .control import load_host_config
        from .control_commands import AdmissionCallContext
        from .runtime_identity import capture_runtime_identity
        try:
            config = load_host_config(self._config_path)
            profile = config.get('native_workflow_control')
            if (not profile or not profile['enabled']
                    or target['repository_id'] not in profile['repository_ids']
                    or operation not in profile['operations']):
                return None
            digest = capture_runtime_identity(config)['config_digest']
            if digest is None or _now() >= _expiry(profile['expires_at']):
                return None
            operations = {operation}
            if (operation == 'workflow_step.continue'
                    and parameters.get('reply_profile') == 'native_handoff_v1'
                    and 'command_reply.native_handoff_v1' in profile['operations']):
                operations.add('command_reply.native_handoff_v1')
            return AdmissionCallContext('native', None, frozenset({target['repository_id']}),
                                        frozenset(operations), config_digest=digest)
        except Exception:
            # Unavailable settings never supply a grant or expose provider text.
            return None


def installation_workflow_provider(config_path):
    return InstallationWorkflowProvider(config_path)
