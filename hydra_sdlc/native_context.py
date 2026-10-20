"""Bounded MCP transport diagnostics, never task identity or human authority.

Optional SDK imports occur only when an MCP server selects its startup profile.
No context, metadata, request identifier or response is retained by this reader.
"""
from dataclasses import dataclass
from importlib.metadata import version


PROTOCOLS = frozenset(('2024-11-05', '2025-03-26', '2025-06-18',
                       '2025-11-25', '2026-07-28'))
FORM_PROTOCOLS = frozenset(('2025-06-18', '2025-11-25', '2026-07-28'))
FIELD_ERRORS = (AttributeError, TypeError, ValueError, RuntimeError)


@dataclass(frozen=True)
class SDKProfile:
    context_type: type | None = None
    capabilities_type: type | None = None
    elicitation_type: type | None = None
    form_type: type | None = None
    url_type: type | None = None

    @property
    def supported(self):
        return all(isinstance(t, type) for t in (
            self.context_type, self.capabilities_type, self.elicitation_type,
            self.form_type, self.url_type))


def load_sdk_profile():
    """Inspect only the pinned SDK's public types once, at server startup."""
    try:
        if version('mcp') != '2.3.0' or version('mcp-types') != '2.3.0':
            return SDKProfile()
        from mcp.server.mcpserver import Context
        from mcp_types import (ClientCapabilities, ElicitationCapability,
                               FormElicitationCapability, UrlElicitationCapability,
                               InputRequiredResult)
        if not all(isinstance(getattr(Context, name, None), property) for name in
                   ('protocol_version', 'session', 'client_capabilities')):
            return SDKProfile()
        for cls, fields in ((ClientCapabilities, ('elicitation',)),
                            (ElicitationCapability, ('form', 'url')),
                            (InputRequiredResult, ('input_requests', 'request_state'))):
            if not isinstance(cls, type) or not all(
                    field in getattr(cls, 'model_fields', {}) for field in fields):
                return SDKProfile()
        return SDKProfile(Context, ClientCapabilities, ElicitationCapability,
                          FormElicitationCapability, UrlElicitationCapability)
    except Exception:
        # Diagnostics must not disclose dependency/import exception text.
        return SDKProfile()


def project_probe(*, sdk_present=False, protocol=None, channel=None, form='unknown'):
    """Project only bounded scalar observations; no raw SDK value is serialized."""
    known = sdk_present is True and type(protocol) is str and protocol in PROTOCOLS
    return {
        'schema_version': 1,
        'protocol_version': protocol if known else None,
        'request_channel': ('available' if channel else 'unavailable')
            if known and type(channel) is bool and not (
                protocol == '2026-07-28' and channel is True) else 'unknown',
        'form_elicitation': form if known and protocol in FORM_PROTOCOLS
            and type(form) is str and form in ('declared', 'not_declared') else 'unknown',
        'input_required_sdk': 'present' if sdk_present is True else 'unknown',
        'input_required_client': 'unverified',
        'caller_task_binding': 'unverified',
    }


def _form_declaration(context, profile, protocol):
    if protocol not in FORM_PROTOCOLS:
        return 'unknown'
    capabilities = context.client_capabilities
    if not isinstance(capabilities, profile.capabilities_type):
        return 'unknown'
    elicitation = capabilities.elicitation
    if elicitation is None:
        return 'not_declared'
    if not isinstance(elicitation, profile.elicitation_type):
        return 'unknown'
    form = elicitation.form
    if isinstance(form, profile.form_type):
        return 'declared'
    if form is not None:
        return 'unknown'
    url = elicitation.url
    if protocol in ('2025-11-25', '2026-07-28') and isinstance(url, profile.url_type):
        return 'not_declared'
    return 'unknown'


def probe_context(context, profile):
    """Read only typed protocol/channel/form fields, at most once per request."""
    fallback = project_probe(sdk_present=profile.supported)
    if not profile.supported or not isinstance(context, profile.context_type):
        return fallback
    try:
        try:
            protocol = context.protocol_version
        except FIELD_ERRORS:
            return fallback
        if type(protocol) is not str or protocol not in PROTOCOLS:
            return fallback
        try:
            channel = context.session.can_send_request
        except FIELD_ERRORS:
            channel = None
        try:
            form = _form_declaration(context, profile, protocol)
        except FIELD_ERRORS:
            form = 'unknown'
        return project_probe(sdk_present=True, protocol=protocol, channel=channel, form=form)
    except Exception:
        # Only extraction is isolated. Controller errors and cancellation propagate.
        return fallback


def read_probe(status):
    """Strict diagnostic consumer. Missing/invalid probe does not invalidate status."""
    probe = status.get('native_context') if isinstance(status, dict) else None
    if not isinstance(probe, dict) or set(probe) != set(project_probe()):
        return None
    if type(probe['schema_version']) is not int or probe['schema_version'] != 1:
        return None
    protocol = probe['protocol_version']
    if protocol is not None and (type(protocol) is not str or protocol not in PROTOCOLS):
        return None
    enums = {
        'request_channel': ('available', 'unavailable', 'unknown'),
        'form_elicitation': ('declared', 'not_declared', 'unknown'),
        'input_required_sdk': ('present', 'absent', 'unknown'),
        'input_required_client': ('unverified',), 'caller_task_binding': ('unverified',),
    }
    if any(type(probe[key]) is not str or probe[key] not in values
           for key, values in enums.items()):
        return None
    return dict(probe)
