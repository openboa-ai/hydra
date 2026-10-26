"""External IO fixtures for the actual delegated-decision production entry.

No decision source, authority grant, accepted-policy loader, or successful
workflow result is substituted. All identities and public data are examples.
"""
from __future__ import annotations

import base64
import copy
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid
from unittest.mock import patch

from hydra_sdlc.control import control_from_config, load_host_config
from hydra_sdlc.control_commands import _runtime_key
from hydra_sdlc.github import GitHub, GitHubError
from hydra_sdlc.runtime_identity import capture_runtime_identity
import test_project as policy
import test_public_decisions as wire


REPO = 'example/product'
URL = 'https://github.com/example/product/issues/4'
ATTEMPT = wire.ATTEMPT
TEXT = 'Use the existing contract.'
OPERATIONS = ('workflow_step.decision_submit', 'workflow_step.continue',
              'command_reply.native_handoff_v1')
KEY = {'repository_id': 123, 'issue_number': 4,
       'source_attempt': ATTEMPT, 'round': 1}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False)


def public_pair(basis, text=TEXT):
    """Independent wire contract oracle, never a production serializer."""
    text = text.replace('\r\n', '\n').replace('\r', '\n').rstrip('\n')
    preimage = {'profile': 'codex_delegated_v1', 'key': KEY,
                'basis': basis, 'public_text': text}
    digest = hashlib.sha256(canonical(preimage).encode()).hexdigest()
    resume = str(uuid.uuid5(uuid.NAMESPACE_URL, 'hydra:codex-delegated-v1:' + digest))
    metadata = {**basis, 'key': KEY, 'resume_attempt': resume,
                'supersedes': None, 'profile': 'codex_delegated_v1'}
    context = (f'hydra: decision {ATTEMPT} context\n{text}\n'
               '<!-- hydra-decision-intent:v2 ' + canonical(metadata) + ' -->\n')
    receipt = (f'hydra: decision {ATTEMPT} resolved\n'
               '<!-- hydra-decision-receipt:v2 ' + canonical({
                   'context_sha256': hashlib.sha256(context.encode()).hexdigest(),
                   'key': KEY}) + ' -->\n')
    return context, receipt, resume


class DelegatedTransport(wire.ReadOnlyTransport):
    """GitHub transport with literal policy and independent physical write log."""
    def __init__(self):
        super().__init__([])
        self.issue = {'number': 4, 'state': 'open',
            'title': 'Document the development workflow',
            'user': {'login': 'openboa'},
            'labels': [{'name': 'hydra:ready'}, {'name': 'hydra:active'}],
            'body': '## Goal\nDescribe the supported workflow.\n## Scope\nDocumentation.\n'
                    '## Acceptance\nActual CLI examples.\n```hydra\n'
                    'spec = "docs/engineering/task/spec.md"\n```'}
        self.policy_text = policy.TOML
        self.contract = 'b' * 40
        self.policy_blob = 'd' * 40
        self.spec_text = '# Example specification\n\nAn accepted documentation task.\n'
        self.spec_blob = 'e' * 40
        self.effects = []
        self.post_behavior = lambda kind, body: None
        self.patch_behavior = lambda body: None
        self.before_read = lambda path: None
        self.route_errors = []
        self.set_origin('implementation')

    def set_origin(self, phase):
        issue_bytes = json.dumps({'title': self.issue['title'], 'body': self.issue['body']},
            sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
        self.basis = {'origin_phase': phase, 'head': 'a' * 40,
            'contract_revision': self.contract, 'spec_revision': None,
            'intake_digest': hashlib.sha256(issue_bytes).hexdigest()}
        self.set_progress({'version': 1, 'repository_id': 123, 'issue_number': 4,
            'attempt_id': ATTEMPT, 'host_alias': 'fixture', 'branch': 'hydra/issue-4',
            'execution_mode': 'native', 'head': self.basis['head'],
            'contract_revision': self.contract, 'spec_revision': None,
            'intake_digest': self.basis['intake_digest'], 'phase': 'checkpoint',
            'pending_action': None, 'wait_reason': 'product_decision',
            'next_action': 'operator_decision', 'resume_phase': phase})

    def set_progress(self, record):
        body = '<!-- hydra-progress:v1 ' + json.dumps(record, sort_keys=True) + ' -->'
        row = wire.comment(1, body)
        self.rows = [row, *[item for item in self.rows if item['id'] != 1]]
        self.direct[1] = copy.deepcopy(row)

    def add(self, identifier, body):
        row = wire.comment(identifier, body)
        self.rows.append(row)
        self.direct[identifier] = copy.deepcopy(row)
        return copy.deepcopy(row)

    def __call__(self, method, path, payload):
        if method == 'GET':
            self.before_read(path)
            if path.startswith(f'/repos/{REPO}/git/ref/heads/'):
                self.calls.append(path)
                if path.endswith('/main'):
                    return {'object': {'sha': self.contract}}
                raise GitHubError('Fixture unpublished branch', status=404)
            if path.startswith(f'/repos/{REPO}/contents/'):
                self.calls.append(path)
                name = path.split('/contents/', 1)[1].split('?', 1)[0]
                if name == '.hydra.toml':
                    text, blob = self.policy_text, self.policy_blob
                elif name == 'docs/engineering/task/spec.md':
                    text, blob = self.spec_text, self.spec_blob
                else:
                    raise AssertionError('Unregistered fixture file: ' + name)
                return {'type': 'file', 'encoding': 'base64', 'sha': blob,
                        'content': base64.b64encode(text.encode()).decode()}
            if '/collaborators/' in path and path.endswith('/permission'):
                self.calls.append(path)
                login = path.split('/')[-2]
                if login not in {'openboa', 'operator'}:
                    raise AssertionError('Unregistered policy actor')
                return {'user': {'login': login}, 'permission': 'write'}
            if path.startswith(f'/repos/{REPO}/issues?'):
                self.calls.append(path)
                return [] if 'state=closed' in path else [copy.deepcopy(self.issue)]
            if path.startswith(f'/repos/{REPO}/pulls?'):
                self.calls.append(path)
                return []
        if method == 'POST' and path == f'/repos/{REPO}/issues/4/comments':
            body = payload['body']
            kind = ('context' if body.startswith(f'hydra: decision {ATTEMPT} context\n')
                    else 'receipt' if body.startswith(f'hydra: decision {ATTEMPT} resolved\n')
                    else 'progress')
            self.effects.append((kind, copy.deepcopy(payload)))
            self.post_behavior(kind, body)
            return self.add(max([99, *self.direct]) + 1, body)
        if method == 'PATCH' and path.startswith(f'/repos/{REPO}/issues/comments/'):
            identifier = int(path.rsplit('/', 1)[1])
            if '<!-- hydra-progress:v1 ' not in self.direct[identifier]['body']:
                raise AssertionError('Only progress may be patched')
            self.effects.append(('progress', copy.deepcopy(payload)))
            self.patch_behavior(payload['body'])
            row = {**self.direct[identifier], 'body': payload['body']}
            self.rows = [copy.deepcopy(row) if item['id'] == identifier else item for item in self.rows]
            self.direct[identifier] = copy.deepcopy(row)
            return copy.deepcopy(row)
        try:
            return super().__call__(method, path, payload)
        except AssertionError:
            self.route_errors.append((method, path))
            raise


class InstallationFixture:
    """Actual main/factories, replacing only GitHub IO and SDK stdio runner."""
    def setup_installation(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.settings = self.root / 'host.toml'
        self.base_settings = ('repos=["example/product"]\nhost_alias="fixture"\n'
                              'workspace_root="work"\nlock_path="locks/host.lock"\n')
        self.write_profile(None)
        self.control = control_from_config(load_host_config(self.settings))
        self.control.set_mode('start')
        self.transport = DelegatedTransport()
        self.request_number = 0

    def write_profile(self, enabled=True, *, operations=OPERATIONS, repositories=(123,),
                      expires='2099-01-01T00:00:00Z', admission=None):
        text = self.base_settings
        if enabled is not None:
            text += ('\n[native_workflow_control]\nschema_version=1\n'
                     f'enabled={str(enabled).lower()}\nrepository_ids={json.dumps(list(repositories))}\n'
                     f'operations={json.dumps(list(operations))}\nexpires_at="{expires}"\n')
        if admission is not None:
            text += ('\n[native_admission_control]\nschema_version=1\nenabled=true\n'
                     f'repository_ids={json.dumps(list(admission))}\n'
                     'expires_at="2099-01-01T00:00:00Z"\n')
        self.settings.write_text(text)
        self.settings.chmod(0o600)

    def make_server(self, *, new_profile=False):
        from hydra_sdlc import mcp as entry
        old_init, create = GitHub.__init__, entry.create_server
        captured = {}
        def inject_transport(instance, *args, **kwargs):
            return old_init(instance, *args, **{**kwargs, 'transport': self.transport})
        def observe_factory(controller, **kwargs):
            captured['controller'] = controller
            captured['server'] = create(controller, **kwargs)
            return captured['server']
        old_mask = os.umask(0o077)
        try:
            with patch.object(GitHub, '__init__', new=inject_transport), \
                    patch.object(entry, 'create_server', side_effect=observe_factory), \
                    patch('hydra_sdlc.mcp_stdio.run_stdio'), \
                    patch.object(sys, 'argv', ['hydra-mcp', '--config', str(self.settings)]):
                try:
                    entry.main()
                except ValueError as exc:
                    if new_profile and str(exc) == 'Invalid installed host settings':
                        self.fail('The accepted native_workflow_control profile must load through the production factory')
                    raise
        finally:
            os.umask(old_mask)
        self.controller = captured['controller']
        self.server = captured['server']
        self.github = self.controller.runner.github
        self.assertIsNone(getattr(self.controller, 'decision_source', None))
        return self.server

    def command(self, *, text=TEXT, continuation=False, reply_profile='native_handoff_v1'):
        self.request_number += 1
        expected = {'runtime_key': _runtime_key(capture_runtime_identity(
            load_host_config(self.settings), self.control)),
            'admission_revision': self.control.snapshot()['revision'],
            'source_checks': [], 'assignment': None}
        parameters = {'operation': 'decision_submit', 'source_attempt': ATTEMPT,
            'round': 1, 'basis': copy.deepcopy(self.transport.basis), 'public_text': text}
        if continuation:
            record = self.github.progress(REPO, 4)
            parameters = {'operation': 'continue', 'reply_profile': reply_profile,
                'progress': {key: record[key] for key in
                    ('attempt_id', 'head', 'contract_revision', 'phase')}}
        return {'command_schema': 1, 'request_id': str(uuid.UUID(int=self.request_number, version=4)),
            'binding_epoch': None, 'action': 'workflow_step',
            'target': {'repository_id': 123, 'issue_number': 4}, 'expected': expected,
            'effect_key': None if continuation else f'decision:{ATTEMPT}:1',
            'parameters': parameters}

    async def invoke(self, command=None, *, meta=None):
        from mcp import Client
        async with Client(self.server) as client:
            kwargs = {} if meta is None else {'meta': meta}
            result = await client.call_tool('hydra_command_v1',
                {'command': self.command() if command is None else command}, **kwargs)
        self.assertEqual(self.transport.route_errors, [], 'Unexpected fixture route is not behavior RED')
        return result

    def reply(self, result):
        self.assertFalse(result.is_error, 'The accepted command must return a typed reply: ' + str(result.content))
        return result.structured_content or json.loads(result.content[0].text)
