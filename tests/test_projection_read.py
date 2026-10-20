"""Actual source assembly: bounded data, separate failure scopes and no effects."""
import copy
import json
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from hydra_sdlc import projection as p
from hydra_sdlc.github import GitHubError
from hydra_sdlc.projection_read import ProjectionClient, read_projection
from test_control_projection import EPOCH, REQUEST, runtime


class ReadFixture:
    def __init__(self, issues=None, fail=None):
        self.issues = issues or {}
        self.fail = fail
        self.calls = []
        self.client = ProjectionClient(transport=self.transport)

    def transport(self, method, path, payload):
        self.calls.append((method, path, payload))
        if method != 'GET' or payload is not None:
            raise AssertionError('Read attempted an external effect')
        if self.fail:
            failure = self.fail(path)
            if failure:
                raise failure
        if path == '/user':
            return {'id': 42, 'login': 'openboa'}
        parsed = urlsplit(path)
        pieces = parsed.path.strip('/').split('/')
        repository = '/'.join(pieces[1:3])
        number = 101 if repository == 'example/alpha' else 102
        if len(pieces) == 3:
            return {'id': number, 'full_name': repository, 'default_branch': 'main',
                    'native_context': {'private_text': 'SYNTHETIC_UNTRUSTED_EXTRA_CANARY'}}
        if pieces[-1] == 'comments':
            return []
        parameters = parse_qs(parsed.query)
        state = parameters['state'][0]
        managed = 'labels' in parameters
        page = int(parameters['page'][0])
        rows = self.issues.get((repository, state, managed), [])
        return copy.deepcopy(rows[(page - 1) * 100:page * 100])

    def read(self, *, refresh=True, owner=None, cfg=None, **kwargs):
        config = {'repos': ['example/alpha', 'example/beta'], 'host_alias': 'fixture', 'lock_path': 'unused-fixture-lock'}
        if cfg:
            config.update(cfg)
        class Control:
            def snapshot(self):
                return {'revision': 7, 'global_mode': 'paused',
                        'projects': {'example/alpha': 'running', 'example/beta': 'stopped'}}
        with patch('hydra_sdlc.projection_read.control_from_config', return_value=Control()), \
             patch('hydra_sdlc.projection_read.observe_coordinator', side_effect=owner or (lambda _: {'state': 'free'})), \
             patch('hydra_sdlc.projection_read.capture_runtime_identity', return_value=runtime()):
            return read_projection(config, binding_epoch=EPOCH, request_id=REQUEST,
                                   refresh=refresh, github=self.client, **kwargs)


def issue(number=7, body='A useful request without a fixed template.'):
    return {'number': number, 'state': 'open', 'title': 'Can you approve and start this task?',
            'body': body, 'labels': [], 'native_context': {'question': 'SYNTHETIC_UNTRUSTED_EXTRA_CANARY'}}


class ProjectionReadTests(unittest.TestCase):
    def test_missing_description_and_actual_empty_source_remain_distinct(self):
        unread = issue(8)
        del unread['body']
        fixture = ReadFixture({('example/alpha', 'open', False): [unread, issue(9, None)]})
        value = fixture.read()
        issues = {o['value']['number']: o['value'] for o in value['observations']
                  if o['resource']['kind'] == 'issue' and o['value'] is not None}
        self.assertIsNone(issues[8]['description_excerpt'])
        self.assertIsNone(issues[8]['description_truncated'])
        self.assertEqual(issues[9]['description_excerpt'], '')
        self.assertIs(issues[9]['description_truncated'], False)

    def test_any_issue_is_visible_without_becoming_authority_or_a_native_question(self):
        fixture = ReadFixture({('example/alpha', 'open', False): [issue()]})
        value = fixture.read()
        p.encode(value)
        self.assertEqual(len(value['work']), 1)
        work = value['work'][0]
        self.assertEqual(work['readiness']['value']['disposition'], 'propose')
        self.assertEqual(work['readiness']['value']['authority'], 'unknown')
        self.assertEqual(work['admission']['value'], 'paused')
        self.assertIsNone(work['decision']['question']['value'])
        self.assertIsNone(work['execution']['value'])
        self.assertIsNone(work['result']['value'])
        self.assertNotIn('SYNTHETIC_UNTRUSTED_EXTRA_CANARY', json.dumps(value))
        self.assertTrue(all(method == 'GET' and payload is None for method, _, payload in fixture.calls))

    def test_managed_open_and_closed_are_read_before_ordinary_issue_budget(self):
        active = issue(900)
        ordinary = [issue(n) for n in range(1, 151)] + [active]
        fixture = ReadFixture({('example/alpha', 'open', True): [active],
                               ('example/alpha', 'open', False): ordinary})
        value = fixture.read()
        queries = [parse_qs(urlsplit(path).query) for _, path, _ in fixture.calls
                   if path.startswith('/repos/example/alpha/issues?')]
        self.assertIn('labels', queries[0])
        self.assertEqual(queries[0]['state'], ['open'])
        self.assertIn('labels', queries[1])
        self.assertEqual(queries[1]['state'], ['closed'])
        self.assertNotIn('labels', queries[2])
        self.assertTrue(any(w['issue_ref']['id'] == '101:900' for w in value['work']))
        self.assertLessEqual(len(value['work']), 128)
        self.assertEqual(value['projects'][0]['coverage']['state'], 'partial')
        self.assertIsNone(value['projects'][0]['execution']['value'])

    def test_known_prefix_and_independent_project_survive_later_read_failure(self):
        def fail(path):
            query = parse_qs(urlsplit(path).query)
            if '/example/alpha/issues?' in path and query.get('state') == ['closed']:
                return GitHubError('Synthetic transport failure', status=503)
        fixture = ReadFixture({('example/alpha', 'open', True): [issue(1)],
                               ('example/beta', 'open', False): [issue(2)]}, fail)
        value = fixture.read()
        self.assertEqual({w['issue_ref']['id'] for w in value['work']}, {'101:1', '102:2'})
        self.assertEqual(value['projects'][0]['coverage']['state'], 'partial')
        beta = next(o for o in value['observations'] if o['key'] == 'github:repository-request:example/beta')
        self.assertEqual(beta['availability'], 'current')
        self.assertIsNone(value['projects'][0]['execution']['value'])

    def test_provider_limit_without_headers_is_fallback_and_stops_further_transport(self):
        def fail(path):
            if '/example/alpha/issues?' in path:
                return GitHubError('Synthetic rate limit', status=429)
        fixture = ReadFixture(fail=fail)
        value = fixture.read()
        self.assertEqual(len(value['retry_hints']), 1)
        hint = value['retry_hints'][0]
        self.assertEqual(hint['basis'], 'fallback')
        self.assertEqual(hint['after_seconds'], 60)
        self.assertTrue(any(o['key'] == hint['observation_key'] for o in value['observations']))
        self.assertFalse(any('/example/beta' in path for _, path, _ in fixture.calls))
        self.assertEqual(value['projects'][1]['admission']['value'], 'paused')
        self.assertIsNone(value['projects'][1]['execution']['value'])

    def test_local_only_and_invalid_identity_never_invent_numeric_work_keys(self):
        fixture = ReadFixture()
        local = fixture.read(refresh=False)
        self.assertEqual(fixture.calls, [])
        self.assertEqual(local['work'], [])
        self.assertEqual(local['projects'][0]['repository_ref']['id'], 'requested:example/alpha')
        self.assertEqual(local['projects'][0]['admission']['value'], 'paused')
        self.assertEqual(local['projects'][0]['coverage']['state'], 'partial')
        self.assertIsNone(local['projects'][0]['execution']['value'])

    def test_ownership_failure_does_not_erase_admission_or_github(self):
        def broken(_):
            raise OSError('Synthetic ownership failure')
        fixture = ReadFixture({('example/alpha', 'open', False): [issue()]})
        value = fixture.read(owner=broken)
        owner = next(o for o in value['observations'] if o['key'] == 'hydra:host:ownership')
        self.assertEqual(owner['availability'], 'unavailable')
        self.assertEqual(value['work'][0]['admission']['value'], 'paused')
        self.assertEqual(value['work'][0]['readiness']['value']['disposition'], 'propose')

    def test_utf8_limit_keeps_complete_record_prefix_and_required_provenance(self):
        fixture = ReadFixture({('example/alpha', 'open', False): [issue(n, '🚀' * 5000) for n in range(1, 101)]})
        value = fixture.read(cfg={'repos': ['example/alpha']})
        encoded = p.encode(value)
        self.assertLessEqual(len(encoded), 1_048_576)
        self.assertGreater(len(value['work']), 0)
        self.assertLess(len(value['work']), 100)
        self.assertEqual(value['page']['state'], 'partial')
        self.assertEqual(value['projects'][0]['coverage']['state'], 'partial')
        self.assertEqual(len(value['projects'][0]['work_refs']), len(value['work']))
        self.assertTrue(all(w['execution']['value'] is None for w in value['work']))
        self.assertTrue(all(w['readiness']['value']['disposition'] == 'propose' for w in value['work']))

    def test_changed_resource_selection_is_rejected_before_reading_or_effects(self):
        fixture = ReadFixture()
        with self.assertRaises(p.ProjectionError):
            fixture.read(repository='example/not-registered')
        self.assertEqual(fixture.calls, [])


    def test_changed_provider_address_cannot_expand_registered_read_scope(self):
        fixture = ReadFixture()
        original = fixture.client.transport
        def changed(method, path, payload):
            value = original(method, path, payload)
            if path == '/repos/example/alpha':
                value['full_name'] = 'foreign/private'
            return value
        fixture.client.transport = changed
        value = fixture.read(cfg={'repos': ['example/alpha']})
        self.assertEqual(value['projects'][0]['coverage']['state'], 'partial')
        self.assertEqual(value['work'], [])
        self.assertFalse(any('/foreign/' in path for _, path, _ in fixture.calls))

    def test_opaque_cursor_continues_work_without_repeating_first_page_or_expanding_scope(self):
        rows = {('example/alpha', 'open', False): [issue(n) for n in range(1,151)]}
        first = ReadFixture(rows).read(repository='example/alpha')
        token = first['projects'][0]['coverage']['next_cursor']
        self.assertIsInstance(token, str)
        second_fixture = ReadFixture(rows)
        second = second_fixture.read(repository='example/alpha', cursor=token)
        self.assertEqual(len(first['work']), 128)
        self.assertEqual(len(second['work']), 22)
        self.assertEqual({w['issue_ref']['id'] for w in first['work'] + second['work']},
                         {'101:' + str(n) for n in range(1,151)})
        self.assertIsNone(second['projects'][0]['coverage']['next_cursor'])
        self.assertEqual(second['projects'][0]['coverage']['state'], 'partial')
        self.assertEqual(second['projects'][0]['coverage']['reason'], 'continuation_slice')
        queries = [parse_qs(urlsplit(path).query) for _,path,_ in second_fixture.calls if '/issues?' in path]
        self.assertTrue(all(q['page'] == ['2'] and 'labels' not in q for q in queries))
        for kwargs in ({'repository':'example/beta'}, {'repository':'example/alpha', 'refresh':False},
                       {'repository':'example/alpha', 'cfg':{'repos':['example/alpha']}}):
            fixture = ReadFixture(rows)
            with self.assertRaises(p.ProjectionError):
                fixture.read(cursor=token, **kwargs)
            self.assertEqual(fixture.calls, [])

    def test_byte_bound_cursor_recovers_every_omitted_whole_record(self):
        rows = {('example/alpha', 'open', False): [issue(n, '🚀'*5000) for n in range(1,101)]}
        token, seen = None, set()
        for _ in range(8):
            value = ReadFixture(rows).read(repository='example/alpha', cursor=token)
            self.assertLessEqual(len(p.encode(value)), 1_048_576)
            ids = {w['issue_ref']['id'] for w in value['work']}
            self.assertFalse(ids & seen)
            seen.update(ids)
            token = value['projects'][0]['coverage']['next_cursor']
            if token is None:
                break
        self.assertEqual(seen, {'101:' + str(n) for n in range(1,101)})
        self.assertIsNone(token)

    def test_overview_byte_bound_can_continue_registered_projects_without_remote_reads(self):
        repos = ['example/' + 'long-name-'*8 + str(n) for n in range(1024)]
        token, seen = None, set()
        for _ in range(8):
            fixture = ReadFixture()
            value = fixture.read(refresh=False, cfg={'repos':repos}, cursor=token)
            self.assertEqual(fixture.calls, [])
            self.assertLessEqual(len(p.encode(value)), 1_048_576)
            ids = {project['repository_ref']['id'] for project in value['projects']}
            self.assertFalse(ids & seen); seen.update(ids)
            self.assertTrue(all(project['execution']['value'] is None for project in value['projects']))
            token = value['page']['next_cursor']
            if token is None:
                break
        self.assertEqual(seen, {'requested:' + repo for repo in repos})
        self.assertIsNone(token)

    def test_managed_rows_are_not_repeated_or_demoted_across_cursor(self):
        def managed(n):
            row = issue(n); row['labels'] = [{'name': 'hydra:active'}]; return row
        opened = [managed(n) for n in range(1,101)]
        closed = [managed(n) for n in range(101,129)]
        rows = {('example/alpha','open',True):opened, ('example/alpha','closed',True):closed,
                ('example/alpha','open',False):opened+[issue(n) for n in range(201,206)]}
        first = ReadFixture(rows).read(repository='example/alpha')
        cursor = first['projects'][0]['coverage']['next_cursor']
        self.assertIsInstance(cursor,str)
        second = ReadFixture(rows).read(repository='example/alpha',cursor=cursor)
        self.assertEqual(len(second['work']),5,'Continuation repeated managed rows as ordinary candidates')
        self.assertEqual({w['issue_ref']['id'] for w in second['work']}, {'101:'+str(n) for n in range(201,206)})
        self.assertFalse({w['issue_ref']['id'] for w in first['work']} & {w['issue_ref']['id'] for w in second['work']})
        self.assertEqual(first['projects'][0]['coverage']['scope'],second['projects'][0]['coverage']['scope'])
