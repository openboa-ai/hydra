"""P10/WR6: original effects and state are the registration oracles.

The transport and authority are isolated test dependencies, not native grants.
Normal and fault paths use the existing common command dispatcher.
"""
import asyncio
import base64
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from urllib.parse import parse_qs, urlsplit

from hydra_sdlc.control import control_from_config, load_host_config
from hydra_sdlc.control_commands import AdmissionCallContext, execute_command_v1
from hydra_sdlc.github import GitHub, GitHubError
from hydra_sdlc.native import NativeController
from hydra_sdlc.runtime_identity import capture_runtime_identity
from hydra_sdlc.work_records import parse_binding
from test_project import BASE, BLOB, TOML
from creation_history_fixture import CreationHistoryFixture


REPO = 'example/product'
ROOT = 'https://api.github.com/repos/' + REPO
KEY = '33333333-3333-4333-8333-333333333333'
REQUEST = '22222222-2222-4222-8222-222222222222'
STAMP = '2026-10-25T00:00:00Z'
SERVICE = {'id': 101, 'login': 'openboa', 'type': 'User'}
HUMAN = {'id': 42, 'login': 'operator', 'type': 'User'}
CANARY = 'PRIVATE_CREATION_PROVIDER_CANARY'


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def source_digest(value):
    return digest({key: value.get(key) for key in ('title', 'body')})


def marker(kind, value):
    return '<!-- ' + kind + ':v1 ' + canonical(value) + ' -->'


class WireClient(GitHub):
    def __init__(self, wire):
        self.wire = wire
        super().__init__(transport=self.dispatch)

    def dispatch(self, method, path, payload):
        self._credential_selected(self.wire.credential)
        self._authenticated_fingerprint = self.wire.credential
        return self.wire.request(method, path, payload)

    def read_client(self):
        return WireClient(self.wire)


class Wire:
    def __init__(self):
        self.credential = b'isolated-creation-credential'
        self.repo = {'id': 123, 'full_name': REPO, 'default_branch': 'main',
                     'private': False, 'visibility': 'public'}
        self.policy = TOML
        self.spec_content = '# Parser specification\n\n## R-EMPTY-1\nReturn the accepted empty value.\n'
        data = self.spec_content.encode()
        self.spec_sha = hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data,
                                    usedforsecurity=False).hexdigest()
        self.issues = {4: self.issue(4, 'Accepted parser goal',
            'Implement the accepted empty-input result and its regression tests.', HUMAN)}
        self.comments = {}
        self.calls = []
        self.writes = []
        self.fail_after = set()
        self.hidden_issues = set()
        self.hidden_comments = set()
        self.before_request = lambda method, path, payload: None
        self.after_effect = lambda kind, value: None
        self.next_comment = 200
        self.proposal = {'kind': 'work', 'outcome': 'empty-result',
            'requirements': [{'repository_id': 123,
                'path': 'docs/engineering/parser/spec.md', 'revision': BASE,
                'selector': 'R-EMPTY-1'}],
            'spec': {'path': 'docs/engineering/parser/spec.md', 'revision': BASE},
            'input_contract': {'kind': 'adopted', 'clauses': []},
            'delegation_ref': 'https://github.com/' + REPO + '/issues/4#issuecomment-78'}
        self.draft = {'create_key': KEY, 'target_repository_id': 123,
            'outcome_key': '', 'goal': {'repository_id': 123, 'issue_number': 4,
                'source_digest': source_digest(self.issues[4])},
            'source_ref': {'kind': 'github_issue', 'repository_id': 123, 'issue_number': 4},
            'source_digest': source_digest(self.issues[4]),
            'title': 'Return the accepted empty-input result',
            'body': 'Implement the accepted parser behavior.\n\n' + marker('hydra-create', {'create_key': KEY})}
        self.refresh_source()
        delegation = {'goal': {'repository_id': 123, 'issue_number': 4},
            'goal_digest': source_digest(self.issues[4]), 'contract_revision': BASE,
            'actions': ['prepare', 'create_work']}
        self.comments[78] = self.comment(78, 4,
            'Create the scoped parser result under this accepted goal.\n' +
            marker('hydra-delegation', delegation), HUMAN)

    @staticmethod
    def issue(number, title, body, author=SERVICE):
        return {'id': 10000 + number, 'number': number, 'title': title, 'body': body,
            'state': 'open', 'user': copy.deepcopy(author), 'repository_url': ROOT,
            'url': ROOT + '/issues/' + str(number),
            'html_url': 'https://github.com/' + REPO + '/issues/' + str(number)}

    @staticmethod
    def comment(identifier, number, body, author=SERVICE):
        return {'id': identifier, 'body': body, 'user': copy.deepcopy(author),
            'url': ROOT + '/issues/comments/' + str(identifier),
            'issue_url': ROOT + '/issues/' + str(number),
            'html_url': 'https://github.com/' + REPO + '/issues/' + str(number) + '#issuecomment-' + str(identifier),
            'created_at': STAMP, 'updated_at': STAMP}

    def refresh_source(self, *, proposal=True):
        # Independent WR outcome formula; never call the implementation helper.
        self.draft['outcome_key'] = digest({'repository_id': 123,
            'delegated_goal': self.draft['goal'], 'source': None,
            'requirements': sorted(self.proposal['requirements'], key=canonical),
            'outcome': self.proposal['outcome']})
        body = 'Prepared fixed payload.\n' + marker('hydra-create-draft', self.draft)
        if proposal:
            body += '\n' + marker('hydra-work-proposal', self.proposal)
        self.comments[77] = self.comment(77, 4, body)
        self.reference = {'kind': 'github_comment', 'repository_id': 123,
            'issue_number': 4, 'comment_id': 77,
            'revision': hashlib.sha256(body.encode()).hexdigest()}

    def request(self, method, path, payload):
        self.calls.append((method, path, copy.deepcopy(payload)))
        self.before_request(method, path, payload)
        url = urlsplit(path)
        route, query = url.path, parse_qs(url.query)
        prefix = '/repos/' + REPO
        if method == 'GET':
            if route == '/user':
                return copy.deepcopy(SERVICE)
            if route == prefix:
                return copy.deepcopy(self.repo)
            if route == prefix + '/git/ref/heads/main':
                return {'object': {'sha': BASE}}
            if route == prefix + '/contents/.hydra.toml':
                return {'type': 'file', 'encoding': 'base64', 'sha': BLOB,
                        'content': base64.b64encode(self.policy.encode()).decode()}
            if route == prefix + '/git/commits/' + BASE:
                return {'sha': BASE, 'tree': {'sha': 'e' * 40}}
            if route == prefix + '/git/trees/' + 'e' * 40:
                paths = ['docs', 'docs/engineering', 'docs/engineering/parser']
                return {'sha': 'e' * 40, 'truncated': False, 'tree': [
                    {'path': path, 'mode': '040000', 'type': 'tree', 'sha': 'e' * 40}
                    for path in paths] + [{'path': 'docs/engineering/parser/spec.md',
                        'mode': '100644', 'type': 'blob', 'sha': self.spec_sha,
                        'size': len(self.spec_content.encode())}]}
            if route == prefix + '/git/blobs/' + self.spec_sha:
                return {'sha': self.spec_sha, 'size': len(self.spec_content.encode()),
                    'encoding': 'base64', 'content': base64.b64encode(self.spec_content.encode()).decode()}
            if route.startswith(prefix + '/git/'):
                raise GitHubError(CANARY)
            if '/collaborators/' in route and route.endswith('/permission'):
                return {'user': {'login': route.split('/')[-2]}, 'permission': 'write'}
            if route.startswith(prefix + '/issues/comments/'):
                identifier = int(route.rsplit('/', 1)[1])
                if identifier in self.comments and identifier not in self.hidden_comments:
                    return copy.deepcopy(self.comments[identifier])
                raise GitHubError(CANARY)
            if route == prefix + '/issues/comments' or route.endswith('/comments'):
                values = [v for k, v in sorted(self.comments.items()) if k not in self.hidden_comments]
                if route != prefix + '/issues/comments':
                    issue_number = int(route.split('/')[-2])
                    values = [v for v in values if v['issue_url'] == ROOT + '/issues/' + str(issue_number)]
                page, count = int(query.get('page', ['1'])[0]), int(query.get('per_page', ['100'])[0])
                return copy.deepcopy(values[(page - 1) * count:page * count])
            if route == prefix + '/issues':
                values = [v for k, v in sorted(self.issues.items()) if k not in self.hidden_issues]
                if query.get('state') in (['open'], ['closed']):
                    values = [v for v in values if v['state'] == query['state'][0]]
                page, count = int(query.get('page', ['1'])[0]), int(query.get('per_page', ['100'])[0])
                return copy.deepcopy(values[(page - 1) * count:page * count])
            if route.startswith(prefix + '/issues/'):
                number = int(route.rsplit('/', 1)[1])
                if number in self.issues and number not in self.hidden_issues:
                    return copy.deepcopy(self.issues[number])
                raise GitHubError(CANARY)
            raise AssertionError('Unexpected GET: ' + route)
        if method != 'POST':
            raise AssertionError('Forbidden mutative method: ' + method)
        if route == prefix + '/issues':
            if set(payload) != {'title', 'body'}:
                raise AssertionError('Issue creation may not set labels or relationships')
            value = self.issue(11, payload['title'], payload['body'])
            self.issues[11] = value
            kind = 'issue'
        elif route in {prefix + '/issues/4/comments', prefix + '/issues/11/comments'}:
            if set(payload) != {'body'}:
                raise AssertionError('Only exact comment body is supported')
            kind = 'fence' if 'hydra-create-dispatch:v1 ' in payload['body'] else 'binding'
            if (kind == 'fence' and not route.endswith('/4/comments') or
                    kind == 'binding' and (not route.endswith('/11/comments') or
                    not payload['body'].startswith('<!-- hydra-work:v2 '))):
                raise AssertionError('Forbidden comment effect')
            value = self.comment(self.next_comment, int(route.split('/')[-2]), payload['body'])
            self.next_comment += 1
            self.comments[value['id']] = value
        else:
            raise AssertionError('Forbidden POST: ' + route)
        self.writes.append((kind, copy.deepcopy(value)))
        self.after_effect(kind, value)
        if kind in self.fail_after:
            self.fail_after.remove(kind)
            raise GitHubError(CANARY)
        return copy.deepcopy(value)


class WorkCreationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.config_path = self.root / 'host.toml'
        self.config_path.write_text('repos=["' + REPO + '"]\nhost_alias="fixture"\n'
            'workspace_root="work"\nlock_path="locks/host.lock"\n')
        self.config_path.chmod(0o600)
        self.cfg = load_host_config(self.config_path)
        self.control = control_from_config(self.cfg)
        self.control.set_mode('start')
        self.runtime = capture_runtime_identity(self.cfg, self.control)
        self.wire = Wire()
        self.client = WireClient(self.wire)
        self.controller = NativeController(self.client, SimpleNamespace(root=Path(self.cfg['workspace_root'])),
            repos=self.cfg['repos'], host_alias=self.cfg['host_alias'],
            lock_path=self.cfg['lock_path'], operations=self.control)
        self.context = AdmissionCallContext('native', None, frozenset({123}), frozenset({'work_create'}))
        self.history = CreationHistoryFixture(self.wire)
        self.controller.creation_source = self.history
        request = self.wire.request
        def observed_request(method, path, payload):
            if method == 'POST':
                self.history.dispatch()
            return request(method, path, payload)
        self.wire.request = observed_request

    def command(self):
        return {'command_schema': 1, 'request_id': REQUEST, 'binding_epoch': None,
            'action': 'work_create', 'target': {'repository_id': 123},
            'expected': {'runtime_key': json.dumps([self.runtime[k] for k in
                ('version', 'code_digest', 'config_digest', 'control_binding_digest')], separators=(',', ':')),
                'admission_revision': self.control.snapshot()['revision'], 'assignment': None,
                'source_checks': [{'resource': {'source': 'github', 'kind': 'issue_comment',
                    'id': REPO + '/comments/77'}, 'revision': None,
                    'actionable_digest': self.wire.reference['revision']}]},
            'effect_key': self.wire.draft['create_key'], 'parameters': {
                'draft_ref': copy.deepcopy(self.wire.reference), 'draft_digest': digest(self.wire.draft)}}

    async def create(self, command=None):
        self.history.begin()
        return await execute_command_v1(self.config_path, command or self.command(),
            context_provider=lambda: self.context, github=self.client, controller=self.controller)

    def binding(self):
        rows = [v for _, v in self.wire.writes if v['body'].startswith('<!-- hydra-work:v2 ')]
        self.assertEqual(len(rows), 1)
        return parse_binding(rows[0]['body'], spec_directory='docs/engineering').value

    async def test_valid_registration_has_actual_receipt_and_only_three_effects(self):
        reply = await self.create()
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual([kind for kind, _ in self.wire.writes], ['fence', 'issue', 'binding'])
        receipt = reply['request']['receipt']
        self.assertEqual((receipt['kind'], receipt['stage']), ('work_create', 'registered'))
        self.assertEqual((receipt['repository_id'], receipt['issue_number']), (123, 11))
        self.assertEqual(receipt['create_key'], KEY)
        self.assertEqual(receipt['draft_digest'], digest(self.wire.draft))
        self.assertEqual(receipt['proposal_digest'], digest(self.wire.proposal))
        self.assertEqual(receipt['issue_ref'], {'source': 'github', 'kind': 'issue', 'id': '123:11'})
        self.assertEqual(self.wire.issues[11]['body'], self.wire.draft['body'])
        self.assertEqual(self.wire.issues[11]['title'], self.wire.draft['title'])
        binding = self.binding()
        self.assertEqual(binding['source_digest'], source_digest(self.wire.issues[11]))
        self.assertEqual(binding['delegated_goal'], self.wire.draft['goal'])
        self.assertEqual(binding['requirements'], self.wire.proposal['requirements'])
        self.assertEqual(binding['create_key'], KEY)
        self.assertEqual(receipt['binding_digest'], digest(binding))
        self.assertFalse(Path(self.cfg['workspace_root']).exists())
        self.assertEqual(Path(self.cfg['lock_path']).read_bytes(), b'')

    async def test_confirmed_registration_replays_same_refs_without_more_posts(self):
        first = await self.create()
        self.assertEqual(first['request']['outcome'], 'applied', first)
        effects = copy.deepcopy(self.wire.writes)
        second = await self.create()
        self.assertEqual(second['request']['receipt'], first['request']['receipt'])
        self.assertEqual(self.wire.writes, effects)

    async def test_read_only_grant_cannot_create_despite_real_public_delegation(self):
        self.context = AdmissionCallContext('native', None, frozenset({123}), frozenset())
        reply = await self.create()
        self.assertEqual(reply['request']['reason'], 'authority_denied', reply)
        self.assertEqual(self.wire.writes, [])

    async def test_missing_current_caller_authority_cannot_be_replaced_by_marker(self):
        self.context = None
        reply = await self.create()
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.wire.writes, [])

    async def test_service_self_delegation_does_not_create_work(self):
        self.wire.comments[78]['user'] = copy.deepcopy(SERVICE)
        reply = await self.create()
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.wire.writes, [])

    async def test_missing_proposal_never_defaults_to_new_model_interpretation(self):
        self.wire.refresh_source(proposal=False)
        reply = await self.create()
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.wire.writes, [])

    async def test_nested_proposal_text_is_payload_and_real_proposal_still_registers(self):
        nested = marker('hydra-work-proposal', {**self.wire.proposal, 'outcome': 'nested-data'})
        self.wire.draft['body'] = nested + '\n' + marker('hydra-create', {'create_key': KEY})
        self.wire.refresh_source()
        reply = await self.create()
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.binding()['outcome'], 'empty-result')
        self.assertEqual(self.wire.issues[11]['body'], self.wire.draft['body'])

    async def test_quoted_proposal_cannot_replace_absent_metadata(self):
        self.wire.draft['body'] = marker('hydra-work-proposal', self.wire.proposal) + '\n' + marker('hydra-create', {'create_key': KEY})
        self.wire.refresh_source(proposal=False)
        reply = await self.create()
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.wire.writes, [])

    async def test_duplicate_real_proposals_do_not_select_a_latest_one(self):
        self.wire.comments[77]['body'] += '\n' + marker('hydra-work-proposal', self.wire.proposal)
        self.wire.reference['revision'] = hashlib.sha256(self.wire.comments[77]['body'].encode()).hexdigest()
        reply = await self.create()
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.wire.writes, [])

    async def test_outcome_hash_is_recomputed_instead_of_trusting_the_supplied_hash(self):
        self.wire.draft['outcome_key'] = '0' * 64
        body = marker('hydra-create-draft', self.wire.draft) + '\n' + marker('hydra-work-proposal', self.wire.proposal)
        self.wire.comments[77]['body'] = body
        self.wire.reference['revision'] = hashlib.sha256(body.encode()).hexdigest()
        reply = await self.create()
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.wire.writes, [])

    async def test_same_key_changed_payload_after_registration_cannot_create_again(self):
        first = await self.create()
        self.assertEqual(first['request']['outcome'], 'applied', first)
        self.wire.draft['title'] += ' changed'
        self.wire.refresh_source()
        before = copy.deepcopy(self.wire.writes)
        reply = await self.create()
        self.assertEqual(reply['request']['reason'], 'creation_payload_conflict', reply)
        self.assertEqual(self.wire.writes, before)

    async def test_binding_response_loss_recovers_late_exact_result_without_another_post(self):
        self.wire.fail_after.add('binding')
        self.wire.after_effect = lambda kind, value: self.wire.hidden_comments.add(value['id']) if kind == 'binding' else None
        first = await self.create()
        self.assertEqual([kind for kind, _ in self.wire.writes], ['fence', 'issue', 'binding'])
        self.assertEqual(first['request']['outcome'], 'unknown', first)
        self.assertIsNone(first['request']['receipt'])
        second = await self.create()
        self.assertEqual(second['request']['outcome'], 'unknown', second)
        self.assertEqual(len(self.wire.writes), 3)
        self.wire.hidden_comments.clear()
        third = await self.create()
        self.assertEqual(third['request']['outcome'], 'applied', third)
        self.assertEqual(len(self.wire.writes), 3)

    async def test_issue_response_loss_with_zero_then_one_never_reposts_or_invents_binding(self):
        self.wire.fail_after.add('issue')
        self.wire.after_effect = lambda kind, value: self.wire.hidden_issues.add(11) if kind == 'issue' else None
        first = await self.create()
        self.assertEqual([kind for kind, _ in self.wire.writes], ['fence', 'issue'])
        self.assertEqual(first['request']['outcome'], 'unknown', first)
        await self.create()
        self.wire.hidden_issues.clear()
        third = await self.create()
        self.assertEqual(third['request']['outcome'], 'unknown', third)
        self.assertIsNone(third['request']['receipt'])
        self.assertEqual([kind for kind, _ in self.wire.writes], ['fence', 'issue'])
        self.assertTrue(any(x['resource']['id'] == '123:11' for x in third['observations']))
        self.assertTrue(all(x['revision'] is None for x in third['observations']))

    async def test_uncertain_fence_with_zero_issues_never_mints_a_create_permit(self):
        self.wire.fail_after.add('fence')
        first = await self.create()
        self.assertEqual([kind for kind, _ in self.wire.writes], ['fence'])
        self.assertEqual(first['request']['outcome'], 'unknown', first)
        second = await self.create()
        self.assertEqual(second['request']['outcome'], 'unknown', second)
        self.assertEqual([kind for kind, _ in self.wire.writes], ['fence'])

    async def test_pause_after_issue_dispatch_retains_issue_and_prevents_binding(self):
        self.wire.after_effect = lambda kind, value: self.control.set_mode('pause', REPO) if kind == 'issue' else None
        reply = await self.create()
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual([kind for kind, _ in self.wire.writes], ['fence', 'issue'])
        self.assertIn(11, self.wire.issues)
        again = await self.create()
        self.assertNotEqual(again['request']['outcome'], 'applied', again)
        self.assertEqual([kind for kind, _ in self.wire.writes], ['fence', 'issue'])

    async def test_original_closed_goal_does_not_erase_delegated_repair_responsibility(self):
        self.wire.issues[4]['state'] = 'closed'
        self.wire.proposal['outcome'] = 'repair-' + 'd' * 40
        self.wire.refresh_source()
        reply = await self.create()
        self.assertEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.binding()['outcome'], 'repair-' + 'd' * 40)
        self.assertEqual(self.binding()['input_contract'], {'kind': 'adopted', 'clauses': []})
        self.assertEqual(self.wire.issues[4]['state'], 'closed')

    async def test_provider_errors_never_echo_source_or_diagnostic_payload(self):
        def fail(method, path, payload):
            raise GitHubError(CANARY)
        self.wire.before_request = fail
        reply = await self.create()
        self.assertNotIn(CANARY, json.dumps(reply))
        self.assertNotEqual(reply['request']['outcome'], 'applied', reply)
        self.assertEqual(self.wire.writes, [])

    @unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional pinned MCP SDK not installed')
    async def test_actual_mcp_core_round_trip_registers_and_replays_the_same_work(self):
        from mcp import Client
        from hydra_sdlc.mcp import create_server
        server = create_server(self.controller, command_config_path=self.config_path,
            command_context_provider=lambda ctx: self.context)
        async with Client(server) as client:
            results = [await client.call_tool('hydra_command_v1', {'command': self.command()})
                       for _ in range(2)]
        # Keep assertions outside the SDK task group so a purpose failure is
        # reported as an assertion, rather than an ExceptionGroup runtime error.
        for result in results:
            self.assertFalse(result.is_error, result.content)
        first, second = [r.structured_content or json.loads(r.content[0].text) for r in results]
        self.assertEqual(first['request']['outcome'], 'applied', first)
        self.assertEqual(second['request']['receipt'], first['request']['receipt'])
        self.assertEqual([kind for kind, _ in self.wire.writes], ['fence', 'issue', 'binding'])
