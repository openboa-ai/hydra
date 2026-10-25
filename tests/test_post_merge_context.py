"""Requirement-derived source oracles through real GitHub reads and status."""
import base64
import copy
from contextlib import contextmanager
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from hydra_sdlc.github import GitHub
from hydra_sdlc.native import NativeController
from hydra_sdlc.project import squash_message
from hydra_sdlc.runner import Runner, intake_digest
from test_github_producer_delivery import ATTEMPT, final_record
from test_post_merge_checks import pending, push_observation
from test_project import BASE, BLOB, HEAD, MERGE, TOML


CANARY = 'PRIVATE_POST_MERGE_SOURCE_CANARY'
REPO = 'example/product'
CONTEXT_KEYS = {'schema_version', 'state', 'reason', 'source', 'current', 'history', 'observed_at'}
REF_KEYS = {'workflow_id', 'run_id', 'run_attempt', 'job_id', 'check_run_id', 'job_name',
            'state', 'run_url', 'attempt_url', 'job_url', 'check_url'}


class Workspace:
    def __init__(self):
        self.retained = []

    def issue_numbers(self, repo):
        return list(self.retained)

    def __getattr__(self, name):
        raise AssertionError('Status attempted a workspace effect: ' + name)


class Wire:
    """Only the provider/credential boundary is synthetic, never the context."""
    def __init__(self, count=1):
        self.rows = {}
        self.calls = []
        self.before = lambda repo, path: None
        self.token = 'synthetic-read-credential'
        self.credential_next = None
        self.account = {'id': 101, 'login': 'openboa'}
        self.enriching = False
        self.readers = []
        self.workspace = Workspace()
        for index in range(count):
            repo = REPO if index == 0 else f'example/project{index}'
            rid = 123 + index
            issue = {'id': 44, 'number': 4, 'state': 'open', 'title': 'Bounded source work',
                'user': {'login': 'operator'}, 'labels': ['hydra:ready'], 'comments': 1,
                'body': '## Goal\nRead failure.\n## Scope\nStatus.\n## Acceptance\nExact source.\n'
                        '```hydra\nspec="docs/engineering/work/spec.md"\n```\n' + CANARY,
                'url': f'https://api.github.com/repos/{repo}/issues/4'}
            record = final_record()
            record.update(repository_id=rid, phase='observing', spec_revision=None,
                          intake_digest=intake_digest(issue), host_alias='other-host')
            pr = {'number': 7, 'url': f'https://api.github.com/repos/{repo}/pulls/7',
                'merged': True, 'state': 'closed', 'merge_commit_sha': MERGE,
                'head': {'sha': HEAD, 'ref': 'hydra/issue-4', 'repo': {'id': rid}},
                'base': {'sha': BASE, 'ref': 'main', 'repo': {'id': rid}},
                'user': {'id': 101, 'login': 'openboa'},
                'body': '<!-- hydra-pr:v1 ' + json.dumps({'repository_id': rid, 'issue_number': 4}) + ' -->\n' + CANARY}
            observed = push_observation()
            observed['repository'] = {'id': rid}
            for run in observed['runs']:
                run['repository']['id'] = run['head_repository']['id'] = rid
                for job in run['jobs']:
                    job.update(run_id=run['id'], run_attempt=run['run_attempt'],
                               check_run_url=f'https://api.github.com/repos/{repo}/check-runs/{job["id"]}')
            observed['runs'][0]['jobs'][0]['conclusion'] = observed['checks'][0]['conclusion'] = 'failure'
            self.rows[repo] = {'repo': {'id': rid, 'full_name': repo, 'default_branch': 'main',
                'private': False, 'visibility': 'public', 'permissions': {'pull': True}},
                'issue': issue, 'record': record, 'pr': pr, 'current': observed,
                'policy': TOML.replace('repository_id = 123', f'repository_id = {rid}'),
                'history': {}, 'comment_id': 600, 'comment_user': {'id': 101, 'login': 'openboa'},
                'head_commit': {'sha': HEAD, 'tree': {'sha': BLOB}},
                'merge_commit': {'sha': MERGE, 'tree': {'sha': BLOB}, 'parents': [{'sha': BASE}],
                    'message': squash_message(rid, 4, 7, HEAD, BASE, record['intake_digest'])}}

    def rerun(self, repo=REPO, state='success'):
        row = self.rows[repo]
        old = copy.deepcopy(row['current'])
        row['history'][(50, 1)] = old
        now = row['current']
        now['runs'][0].update(run_attempt=2)
        now['runs'][0]['jobs'][0].update(id=91, run_attempt=2,
            check_run_url=f'https://api.github.com/repos/{repo}/check-runs/91')
        now['checks'][0]['id'] = 91
        now['runs'][0]['jobs'][0]['conclusion'] = now['checks'][0]['conclusion'] = state
        if state == 'pending':
            pending(now)

    def credential(self, _client):
        if self.credential_next:
            selected, self.credential_next = self.credential_next, None
            return selected
        return self.token

    def cli(self, argv, **kwargs):
        if argv[:2] != ['gh', 'api']:
            raise AssertionError('Unexpected subprocess during a read')
        method = argv[argv.index('--method') + 1]
        if method != 'GET' or kwargs.get('input') is not None:
            raise AssertionError('Source read attempted a remote effect')
        raw = next(arg for arg in argv if arg == 'user' or arg.startswith('repos/'))
        path, query = urlsplit('/' + raw).path, parse_qs(urlsplit('/' + raw).query)
        repo = '/'.join(path.split('/')[2:4]) if path.startswith('/repos/') else None
        self.calls.append((self.enriching, method, repo, raw))
        self.before(repo, raw)
        if path == '/user':
            value = self.account
        else:
            row = self.rows[repo]
            suffix = path[len('/repos/' + repo):]
            if suffix == '':
                value = row['repo']
            elif suffix == '/issues':
                value = [row['issue']] if query.get('state') == [row['issue']['state']] and (
                    row['issue']['state'] == 'open' or 'hydra:active' in row['issue']['labels']) else []
            elif suffix == '/issues/4':
                value = row['issue']
            elif suffix == '/issues/4/comments':
                value = [] if row['record'] is None else [{'id': row['comment_id'],
                    'url': f'https://api.github.com/repos/{repo}/issues/comments/{row["comment_id"]}',
                    'issue_url': row['issue']['url'], 'user': row['comment_user'],
                    'body': '<!-- hydra-progress:v1 ' + json.dumps(row['record']) + ' -->'}]
            elif suffix.startswith('/git/ref/heads/'):
                value = {'object': {'sha': BASE}}
            elif suffix == '/contents/.hydra.toml':
                value = {'type': 'file', 'encoding': 'base64', 'sha': BLOB,
                         'content': base64.b64encode(row['policy'].encode()).decode()}
            elif suffix.startswith('/collaborators/') and suffix.endswith('/permission'):
                value = {'user': {'login': suffix.split('/')[2]}, 'permission': 'write'}
            elif suffix == '/pulls/7':
                value = row['pr']
            elif suffix == '/git/commits/' + HEAD:
                value = row['head_commit']
            elif suffix == '/git/commits/' + MERGE:
                value = row['merge_commit']
            elif suffix == '/commits/' + MERGE + '/check-runs':
                value = {'check_runs': row['current']['checks']}
            elif suffix == '/actions/runs':
                start = (int(query.get('page', ['1'])[0]) - 1) * 100
                value = {'workflow_runs': row['current']['runs'][start:start + 100]}
            elif suffix.startswith('/check-runs/'):
                number = int(suffix.split('/')[-1])
                checks = row['current']['checks'] + [check for old in row['history'].values() for check in old['checks']]
                value = next(check for check in checks if check['id'] == number)
            elif suffix.startswith('/actions/runs/'):
                parts = suffix.split('/')
                rid = int(parts[3])
                if len(parts) >= 6 and parts[4] == 'attempts':
                    observation = row['history'][(rid, int(parts[5]))]
                else:
                    observation = row['current']
                run = next(run for run in observation['runs'] if run['id'] == rid)
                value = {'jobs': run['jobs']} if parts[-1] == 'jobs' else run
            else:
                raise AssertionError('Unexpected provider route: ' + suffix)
        value = copy.deepcopy(value)
        if type(value) is dict and set(value) in ({'workflow_runs'}, {'check_runs'}, {'jobs'}):
            key = next(iter(value))
            value['total_count'] = len(row['current']['runs']) if key == 'workflow_runs' else len(value[key])
        stdout = json.dumps(value)
        if '--include' in argv:
            stdout = 'HTTP/2 200 OK\r\ncontent-type: application/json\r\n\r\n' + stdout
        return subprocess.CompletedProcess(argv, 0, stdout, '')

    @contextmanager
    def installed_boundary(self):
        original = GitHub.read_client
        wire = self
        def reader(client):
            value = original(client)
            assert value is not client and value._read_budgets == []
            wire.readers.append(value)
            wire.enriching = True
            return value
        with patch.object(GitHub, '_credential', lambda client: self.credential(client)), \
                patch('hydra_sdlc.github.subprocess.run', side_effect=self.cli), \
                patch.object(GitHub, 'read_client', reader):
            yield GitHub()


def forbidden(*args, **kwargs):
    raise AssertionError('Status attempted execution')


class SourceContextTests(unittest.TestCase):
    def read(self, wire):
        with wire.installed_boundary() as github:
            runner = Runner(github, wire.workspace, host_alias='local-host', execute=forbidden, capabilities=forbidden)
            return runner.status(wire.rows)

    def context(self, rows, index=0):
        self.assertIn('post_merge_context', rows[index], 'Eligible real source must reach status')
        result = rows[index]['post_merge_context']
        self.assertEqual(set(result), CONTEXT_KEYS)
        self.assertEqual(result['schema_version'], 1)
        for ref in result['current']['checks'] + result['history']['failed_checks']:
            self.assertEqual(set(ref), REF_KEYS)
        self.assertLessEqual(len(json.dumps(result).encode()), 32768)
        return result

    def test_actual_failed_job_reaches_status_without_prose_or_effects(self):
        wire = Wire()
        original = copy.deepcopy(wire.rows)
        value = self.context(self.read(wire))
        self.assertEqual((value['state'], value['reason']), ('failed', 'post_merge_failed'))
        self.assertEqual(value['source'], {'repository_id': 123, 'issue_number': 4,
            'progress_comment_id': 600, 'attempt_id': ATTEMPT, 'contract_revision': BASE,
            'spec_revision': None, 'source_digest': original[REPO]['record']['intake_digest'],
            'head': HEAD, 'pr_number': 7, 'merge_sha': MERGE})
        self.assertEqual(value['current']['checks'], [{'workflow_id': 40, 'run_id': 50,
            'run_attempt': 1, 'job_id': 90, 'check_run_id': 90, 'job_name': 'Unit tests',
            'state': 'failed', 'run_url': 'https://github.com/example/product/actions/runs/50',
            'attempt_url': 'https://api.github.com/repos/example/product/actions/runs/50/attempts/1',
            'job_url': 'https://api.github.com/repos/example/product/actions/jobs/90',
            'check_url': 'https://api.github.com/repos/example/product/check-runs/90'}])
        self.assertEqual(value['current']['coverage']['total_count'], 1)
        self.assertEqual(value['history']['coverage']['state'], 'complete')
        self.assertEqual(value['history']['coverage']['total_count'], 0)
        self.assertEqual(wire.rows, original)
        self.assertEqual(len(wire.readers), 1)
        self.assertNotIn(CANARY, json.dumps(value))
        self.assertLessEqual(sum(c[0] for c in wire.calls), 128)

    def test_all_eligible_phases_and_pending_merge_preserve_original_intents(self):
        for phase, action in [('observing', None), ('closing', 'close_issue'),
                              ('completed', None), ('published', 'merge')]:
            with self.subTest(phase=phase, action=action):
                wire = Wire()
                wire.rows[REPO]['record'].update(phase=phase, pending_action=action)
                value = self.context(self.read(wire))
                self.assertEqual(value['state'], 'failed')
                self.assertEqual(wire.rows[REPO]['record']['pending_action'], action)

    def test_success_pending_and_missing_required_job_remain_distinct(self):
        for state in ('success', 'pending', 'unknown'):
            with self.subTest(state=state):
                wire = Wire()
                current = wire.rows[REPO]['current']
                if state == 'pending':
                    pending(current)
                elif state == 'unknown':
                    current['runs'][0]['jobs'] = []
                else:
                    current['runs'][0]['jobs'][0]['conclusion'] = current['checks'][0]['conclusion'] = 'success'
                value = self.context(self.read(wire))
                self.assertEqual(value['state'], state)
                self.assertEqual(value['current']['state'], state)
                if state == 'unknown':
                    self.assertEqual(value['current']['checks'], [])

    def test_history_uses_original_failed_attempt_and_current_latest_attempt(self):
        for state in ('pending', 'success'):
            with self.subTest(state=state):
                wire = Wire()
                wire.rerun(state=state)
                value = self.context(self.read(wire))
                self.assertEqual(value['state'], state)
                self.assertEqual(value['current']['checks'][0]['run_attempt'], 2)
                self.assertEqual(value['history']['through'], [{'workflow_id': 40, 'run_id': 50, 'through_attempt': 1}])
                old = value['history']['failed_checks']
                self.assertEqual([(r['run_id'], r['run_attempt'], r['job_id'], r['state']) for r in old], [(50, 1, 90, 'failed')])
                paths = [c[3] for c in wire.calls if c[0]]
                self.assertTrue(any('/attempts/1/jobs' in p for p in paths))
                self.assertTrue(any('/check-runs/90' in p for p in paths))
                self.assertEqual(value['history']['coverage']['total_count'], 1)

    def test_wait_prose_without_a_historical_attempt_proves_no_failure(self):
        wire = Wire()
        wire.rows[REPO]['record']['wait_reason'] = 'post_merge_failed'
        current = wire.rows[REPO]['current']
        current['runs'][0]['jobs'][0]['conclusion'] = current['checks'][0]['conclusion'] = 'success'
        value = self.context(self.read(wire))
        self.assertEqual(value['state'], 'success')
        self.assertEqual(value['history']['failed_checks'], [])
        self.assertEqual(value['history']['coverage']['state'], 'complete')

    def test_optional_history_denial_preserves_qualified_current_failure(self):
        wire = Wire()
        wire.rerun(state='failure')
        def deny(repo, path):
            if wire.enriching and '/attempts/' in path:
                raise OSError(CANARY)
        wire.before = deny
        value = self.context(self.read(wire))
        self.assertEqual(value['state'], 'failed')
        self.assertEqual(value['current']['checks'][0]['run_attempt'], 2)
        self.assertNotEqual(value['history']['coverage']['state'], 'complete')
        self.assertIsNone(value['history']['coverage']['total_count'])
        self.assertNotIn(CANARY, json.dumps(value))

    def test_sibling_currents_finish_before_any_history(self):
        wire = Wire(2)
        for repo in wire.rows:
            wire.rerun(repo)
        self.read(wire)
        enriched = [c for c in wire.calls if c[0]]
        history_indices = [i for i, c in enumerate(enriched) if '/attempts/' in c[3]]
        self.assertTrue(history_indices, 'An actual historical source read is required')
        first_history = history_indices[0]
        earlier = enriched[:first_history]
        for repo in wire.rows:
            self.assertGreaterEqual(sum(c[2] == repo and '/commits/' + MERGE + '/check-runs' in c[3] for c in earlier), 2)

    def test_foreign_or_ambiguous_current_evidence_cannot_become_a_failure_target(self):
        for mutate in (
            lambda x: x['runs'][0].update(workflow_id=999),
            lambda x: x['runs'][0].update(event='pull_request'),
            lambda x: x['runs'][0].update(head_sha=HEAD),
            lambda x: x['checks'][0]['app'].update(id=999),
            lambda x: x['runs'][0]['jobs'].append(copy.deepcopy(x['runs'][0]['jobs'][0])),
            lambda x: x['checks'].append(copy.deepcopy(x['checks'][0])),
        ):
            with self.subTest(mutate=mutate):
                wire = Wire()
                mutate(wire.rows[REPO]['current'])
                value = self.context(self.read(wire))
                self.assertEqual(value['state'], 'unknown')
                self.assertEqual(value['current']['checks'], [])

    def test_unrelated_foreign_noise_does_not_erase_valid_current_failure(self):
        wire = Wire()
        current = wire.rows[REPO]['current']
        other = copy.deepcopy(current['runs'][0])
        other.update(id=51, workflow_id=999, run_number=999)
        current['runs'].append(other)
        value = self.context(self.read(wire))
        self.assertEqual(value['state'], 'failed')
        self.assertEqual(value['current']['checks'][0]['run_id'], 50)

    def test_unknown_or_forged_squash_never_discloses_origin_or_job_refs(self):
        for key, new in [('checkpoint', 'squash_' + 'e' * 40), ('expected_base', 'e' * 40)]:
            with self.subTest(key=key):
                wire = Wire()
                wire.rows[REPO]['record'][key] = new
                value = self.context(self.read(wire))
                self.assertEqual(value['state'], 'unknown')
                self.assertIsNone(value['source'])
                self.assertEqual(value['current']['checks'], [])
        wire = Wire()
        wire.rows[REPO]['record'].update(phase='published', pending_action='merge')
        wire.rows[REPO]['merge_commit']['message'] = 'No correlation'
        self.assertIsNone(self.context(self.read(wire))['source'])

    def test_progress_changes_in_final_current_read_invalidate_only_that_row(self):
        wire = Wire(2)
        counts = {}
        def change(repo, path):
            if wire.enriching and '/issues/4/comments' in path:
                counts[repo] = counts.get(repo, 0) + 1
                if repo == REPO and counts[repo] == 2:
                    wire.rows[repo]['record']['intake_digest'] = '8' * 64
        wire.before = change
        rows = self.read(wire)
        first, sibling = self.context(rows), self.context(rows, 1)
        self.assertEqual(first['state'], 'changed')
        self.assertIsNone(first['source'])
        self.assertEqual(sibling['state'], 'failed')

    def test_observed_credential_rotation_then_restoration_invalidates_all_siblings(self):
        wire = Wire(2)
        for repo in wire.rows:
            wire.rerun(repo)
        def rotate(repo, path):
            if wire.enriching and repo == 'example/project1' and '/attempts/1' in path:
                wire.credential_next = 'different-observed-credential'
        wire.before = rotate
        rows = self.read(wire)
        self.assertEqual(wire.token, 'synthetic-read-credential')
        for index in range(2):
            value = self.context(rows, index)
            self.assertEqual((value['state'], value['reason']), ('changed', 'post_merge_source_changed'))
            self.assertIsNone(value['source'])
            self.assertEqual(value['current']['checks'], [])
            self.assertEqual(value['history']['failed_checks'], [])
            self.assertIsNone(value['current']['observed_at'])

    def test_shared_account_or_disclosure_change_is_sticky_across_siblings(self):
        for kind in ('account', 'disclosure'):
            with self.subTest(kind=kind):
                wire = Wire(2)
                seen = {'count': 0}
                def change(repo, path):
                    if wire.enriching and repo == 'example/project1' and '/issues/4/comments' in path:
                        seen['count'] += 1
                        if seen['count'] == 2:
                            if kind == 'account':
                                wire.account['id'] = 999
                            else:
                                wire.rows[repo]['repo'].update(private=True, visibility='private')
                wire.before = change
                rows = self.read(wire)
                for index in range(2):
                    self.assertEqual(self.context(rows, index)['state'], 'changed')

    def test_unrelated_phases_and_unregistered_work_do_not_start_enrichment(self):
        for phase in ('ready', 'executing', 'published'):
            with self.subTest(phase=phase):
                wire = Wire()
                wire.rows[REPO]['record']['phase'] = phase
                rows = self.read(wire)
                self.assertNotIn('post_merge_context', rows[0])
                self.assertEqual(wire.readers, [])
        wire = Wire()
        wire.rows[REPO]['record'] = None
        self.assertNotIn('post_merge_context', self.read(wire)[0])
        self.assertEqual(wire.readers, [])

    def test_context_cap_is_explicit_and_never_starts_a_fifth_enrichment(self):
        wire = Wire(5)
        rows = self.read(wire)
        value = self.context(rows, 4)
        self.assertEqual(value['state'], 'unknown')
        self.assertEqual(value['current']['coverage']['reason'], 'context_limit')
        self.assertIsNone(value['source'])
        self.assertFalse(any(c[0] and c[2] == 'example/project4' for c in wire.calls))
        self.assertLessEqual(sum(c[0] for c in wire.calls), 128)

    def test_closed_retained_work_and_restart_reobserve_the_same_external_identity(self):
        wire = Wire()
        wire.rows[REPO]['record']['phase'] = 'completed'
        wire.rows[REPO]['issue']['state'] = 'closed'
        wire.workspace.retained = [4]
        wire.rows[REPO]['record']['host_alias'] = 'local-host'
        first = self.context(self.read(wire))
        wire.enriching = False
        second = self.context(self.read(wire))
        self.assertEqual(first['source'], second['source'])
        self.assertEqual(first['current']['checks'], second['current']['checks'])
        self.assertEqual(len(wire.readers), 2)

    def test_current_policy_change_is_local_and_newer_attempt_is_not_silently_adopted(self):
        for kind in ('policy', 'attempt'):
            with self.subTest(kind=kind):
                wire = Wire(2)
                count = {'value': 0}
                def change(repo, path):
                    marker = '/contents/.hydra.toml' if kind == 'policy' else '/commits/' + MERGE + '/check-runs'
                    if wire.enriching and repo == REPO and marker in path:
                        count['value'] += 1
                        if count['value'] == (3 if kind == 'policy' else 2):
                            if kind == 'policy':
                                wire.rows[repo]['policy'] = wire.rows[repo]['policy'].replace('timeout = 120', 'timeout = 121')
                            else:
                                wire.rerun(state='pending')
                wire.before = change
                rows = self.read(wire)
                value = self.context(rows)
                self.assertIn(value['state'], {'changed', 'unknown'})
                self.assertEqual(value['current']['checks'], [])
                self.assertEqual(self.context(rows, 1)['state'], 'failed')

    def test_old_run_failure_is_preserved_beside_a_newer_current_run(self):
        wire = Wire()
        row = wire.rows[REPO]
        old = copy.deepcopy(row['current'])
        run = old['runs'][0]
        run.update(id=49, check_suite_id=79)
        run['jobs'][0].update(id=89, run_id=49,
            check_run_url='https://api.github.com/repos/example/product/check-runs/89')
        old['checks'][0].update(id=89, check_suite={'id': 79})
        row['history'][(49, 1)] = old
        row['current']['runs'][0]['run_number'] = 2
        row['current']['runs'].append(copy.deepcopy(run))
        row['current']['checks'].append(copy.deepcopy(old['checks'][0]))
        value = self.context(self.read(wire))
        self.assertEqual(value['current']['checks'][0]['run_id'], 50)
        self.assertEqual([(r['run_id'], r['job_id']) for r in value['history']['failed_checks']], [(49, 89)])
        self.assertEqual(value['history']['through'], [{'workflow_id': 40, 'run_id': 49, 'through_attempt': 1}])

    def test_historical_attempt_cap_does_not_limit_current_selection_or_invent_a_total(self):
        wire = Wire()
        row = wire.rows[REPO]
        for attempt in range(1, 11):
            old = copy.deepcopy(row['current'])
            old['runs'][0]['run_attempt'] = attempt
            old['runs'][0]['jobs'][0].update(id=100 + attempt, run_attempt=attempt,
                check_run_url=f'https://api.github.com/repos/example/product/check-runs/{100 + attempt}')
            old['checks'][0]['id'] = 100 + attempt
            row['history'][(50, attempt)] = old
        row['current']['runs'][0]['run_attempt'] = 11
        row['current']['runs'][0]['jobs'][0]['run_attempt'] = 11
        value = self.context(self.read(wire))
        self.assertEqual(value['current']['checks'][0]['run_attempt'], 11)
        self.assertEqual(value['history']['through'], [{'workflow_id': 40, 'run_id': 50, 'through_attempt': 10}])
        self.assertEqual(value['history']['coverage']['state'], 'partial')
        self.assertIsNone(value['history']['coverage']['total_count'])
        self.assertEqual(len(value['history']['failed_checks']), 8)
        self.assertFalse(any('/attempts/9' in c[3] or '/attempts/10' in c[3] for c in wire.calls))

    def test_partial_current_collection_is_unknown_and_never_falls_back_to_old_success(self):
        wire = Wire()
        row = wire.rows[REPO]
        run = row['current']['runs'][0]
        row['current']['runs'] = [copy.deepcopy(run) for _ in range(100)]
        def truncate(repo, path):
            if wire.enriching and '/actions/runs?' in path and 'page=2' in path:
                raise OSError(CANARY)
        wire.before = truncate
        value = self.context(self.read(wire))
        self.assertEqual(value['state'], 'unknown')
        self.assertEqual(value['current']['checks'], [])
        self.assertNotIn(CANARY, json.dumps(value))

    def test_history_deadline_does_not_destroy_the_current_snapshot(self):
        wire = Wire()
        wire.rerun(state='failure')
        now = [100.0]
        def delay(repo, path):
            if wire.enriching and '/attempts/' in path:
                now[0] += 46
        wire.before = delay
        with patch('hydra_sdlc.github.time.monotonic', side_effect=lambda: now[0]):
            value = self.context(self.read(wire))
        self.assertEqual(value['state'], 'failed')
        self.assertNotEqual(value['history']['coverage']['state'], 'complete')
        self.assertEqual(value['current']['checks'][0]['run_attempt'], 2)

    def test_raw_provider_limit_and_fixed_errors_disclose_no_private_fields(self):
        wire = Wire()
        wire.rows[REPO]['current']['checks'][0]['output'] = {'text': CANARY * 300000}
        value = self.context(self.read(wire))
        self.assertEqual(value['state'], 'unknown')
        self.assertIsNone(value['source'])
        self.assertNotIn(CANARY, json.dumps(value))

    def test_reference_and_normalized_byte_caps_keep_coverage_truthful(self):
        for count, name_length in ((34, 8), (9, 4000)):
            with self.subTest(count=count, name_length=name_length):
                wire = Wire()
                row = wire.rows[REPO]
                for index in range(1, count):
                    name = 'Required' + str(index) + 'x' * name_length
                    row['policy'] += '\n[[required_checks]]\nworkflow_id=40\nworkflow_path=".github/workflows/ci.yml"\n' + \
                        'job=' + json.dumps(name) + '\nevents=["pull_request","push"]\napp_id=15368\n'
                    job = copy.deepcopy(row['current']['runs'][0]['jobs'][0])
                    job.update(id=100 + index, name=name,
                        check_run_url=f'https://api.github.com/repos/example/product/check-runs/{100 + index}')
                    check = copy.deepcopy(row['current']['checks'][0])
                    check.update(id=100 + index, name=name)
                    row['current']['runs'][0]['jobs'].append(job)
                    row['current']['checks'].append(check)
                value = self.context(self.read(wire))
                self.assertEqual(value['state'], 'failed')
                self.assertLessEqual(len(value['current']['checks']) + len(value['history']['failed_checks']), 32)
                coverage = value['current']['coverage']
                self.assertEqual(coverage['state'], 'partial')
                self.assertEqual(coverage['total_count'], count)
                self.assertEqual(coverage['returned_count'], len(value['current']['checks']))


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional pinned MCP SDK not installed')
class SourceContextProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_real_native_status_and_mcp_reply_show_failed_source_while_paused(self):
        from mcp import Client
        from hydra_sdlc.mcp import create_server
        from hydra_sdlc.operations import OperatingControl
        wire = Wire()
        with tempfile.TemporaryDirectory() as directory, wire.installed_boundary() as github:
            lock = Path(directory) / 'host.lock'
            controls = OperatingControl(lock, list(wire.rows))
            controls.set_mode('pause')
            controller = NativeController(github, wire.workspace, repos=wire.rows,
                host_alias='local-host', lock_path=lock, operations=controls)
            with patch('hydra_sdlc.codex.execute', side_effect=forbidden), \
                    patch('hydra_sdlc.codex.capabilities', side_effect=forbidden):
                async with Client(create_server(controller)) as client:
                    result = await client.call_tool('hydra_status', {})
            self.assertFalse(result.is_error, result.content)
            value = result.structured_content or json.loads(result.content[0].text)
            self.assertIn('post_merge_context', value['projects'][0])
            context = value['projects'][0]['post_merge_context']
            self.assertEqual(context['state'], 'failed')
            self.assertEqual(context['source']['merge_sha'], MERGE)
            self.assertEqual(context['current']['checks'][0]['job_id'], 90)
            self.assertNotIn(CANARY, json.dumps(value))
            self.assertEqual(controls.snapshot()['global_mode'], 'paused')
