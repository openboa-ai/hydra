import copy
import json
import unittest

from hydra_sdlc.project import ProjectError, gate_checks, gate_delivery, gate_post_merge, load_project, parse_intake, terminal_required_checks, _provider


BASE, HEAD, BLOB, MERGE = 'a' * 40, 'b' * 40, 'c' * 40, 'd' * 40
TOML = '''version = 1
repository_id = 123
authorized_actors = ["openboa", "operator"]
human_reviewers = ["operator"]
spec_directory = "docs/engineering"
allowed_paths = ["src/", "tests/", "docs/", ".hydra.toml", ".github/"]
protected_paths = ["tests/holdout/"]
[labels]
ready = "hydra:ready"
paused = "hydra:paused"
decision = "hydra:decision"
[[verification]]
argv = ["python3", "-m", "unittest", "discover", "-s", "tests"]
cwd = "."
timeout = 120
[[required_checks]]
workflow_id = 40
workflow_path = ".github/workflows/ci.yml"
job = "Unit tests"
events = ["pull_request", "push"]
app_id = 15368
[review_provider]
login = "chatgpt-codex-connector[bot]"
user_id = 199175422
app_id = 1144995
format = "codex_summary_v1"
[delivery]
automatic_merge = true
production_effect = false
'''


class ConfigGitHub:
    def __init__(self, content=TOML, repo_id=123, repo='example/product', base=BASE):
        self.content, self.repo_id, self.repo, self.base = content, repo_id, repo, base
        self.file_calls = []

    def api(self, method, path):
        return {"user": {"login": path.split("/")[-2]}, "permission": "write"}

    def repository(self, repo):
        return {'id': self.repo_id, 'default_branch': 'main', 'full_name': repo}

    def ref(self, repo, branch):
        return self.base

    def file(self, repo, path, ref):
        self.file_calls.append((repo, path, ref))
        return {'content': self.content, 'sha': BLOB}


def config():
    return load_project(ConfigGitHub(), 'example/product')


def summary(head=HEAD):
    marker = {'blockingSeverityThreshold': 'P0', 'headSha': head, 'mergeGateEnabled': False,
              'pullRequestNumber': 7, 'repository': 'example/product', 'status': 'completed'}
    return '<!-- codex-pull-request-review-summary -->\n<!-- codex-security-review:v1 ' + json.dumps(marker) + ' -->\n' + '\n'.join(
        f'| {icon} **{name}** | ✅ **Completed** <relative-time datetime="2026-10-10T00:00:00Z">2026-10-10T00:00:00Z</relative-time> | `{head[:7]}` | PR opened |'
        for icon, name in [('📝', 'Code Review'), ('🔒', 'Security Review')])


def observation():
    association = {'number': 7, 'head': {'sha': HEAD, 'repo': {'id': 123}}, 'base': {'sha': BASE, 'repo': {'id': 123}}}
    return {'repository': {'id': 123}, 'head_sha': HEAD, 'base_sha': BASE,
            'pr': {**association, 'head': {**association['head'], 'ref': 'hydra/issue-4'},
                   'base': {**association['base'], 'ref': 'main'}, 'state': 'open', 'draft': False,
                   'user': {'login': 'openboa'}, 'mergeable': True, 'mergeable_state': 'clean',
                   'changed_files': 1, 'commits': 1, 'merged': False},
            'checks': [{'id': 90, 'check_suite': {'id': 80}, 'app': {'id': 15368}, 'head_sha': HEAD,
                        'name': 'Unit tests', 'status': 'completed', 'conclusion': 'success'}],
            'runs': [{'id': 50, 'workflow_id': 40, 'path': '.github/workflows/ci.yml',
                      'repository': {'id': 123}, 'event': 'pull_request', 'head_sha': HEAD,
                      'head_branch': 'hydra/issue-4', 'status': 'completed', 'conclusion': 'success',
                      'run_number': 1, 'run_attempt': 1, 'check_suite_id': 80,
                      'pull_requests': [association], 'jobs': [{'id': 90, 'name': 'Unit tests',
                      'head_sha': HEAD, 'status': 'completed', 'conclusion': 'success',
                      'check_run_url': 'https://api.github.com/repos/example/product/check-runs/90'}]}],
            'native_reviews': [], 'threads': [], 'inline_comments': [], 'review_decision': None,
            'provider_comments': [{'id': 60, 'user': {'id': 199175422, 'login': 'chatgpt-codex-connector[bot]'},
                                   'performed_via_github_app': {'id': 1144995}, 'body': summary()}],
            'commits': [{'sha': HEAD}], 'changed_files': [{'filename': 'src/main.py'}],
            'rules': [{'type': 'non_fast_forward'}, {'type': 'required_status_checks', 'parameters': {
                'strict_required_status_checks_policy': True,
                'required_status_checks': [{'context': 'Unit tests', 'integration_id': 15368}]}},
                {'type': 'pull_request', 'parameters': {'dismiss_stale_reviews_on_push': True,
                 'require_code_owner_review': True, 'required_review_thread_resolution': True,
                 'required_approving_review_count': 0}}],
            'rule_sources': [{'enforcement': 'active', 'bypass_actors': []}]}


class ProjectTests(unittest.TestCase):
    def test_two_repositories_read_only_protected_revision(self):
        for repo, rid, spec_dir in [('example/product', 123, 'docs/engineering'), ('other/worker', 999, 'design')]:
            with self.subTest(repo=repo):
                gh = ConfigGitHub(TOML.replace('repository_id = 123', f'repository_id = {rid}').replace('docs/engineering', spec_dir), rid)
                cfg = load_project(gh, repo)
                self.assertEqual((cfg['revision'], cfg['blob_sha'], cfg['repository']), (BASE, BLOB, repo))
                self.assertEqual(gh.file_calls, [(repo, '.hydra.toml', BASE)])

    def test_unknown_identity_policy_or_commands_fail(self):
        bad = [TOML.replace('version = 1', 'version = 2'), TOML.replace('repository_id = 123', 'repository_id = 999'),
               TOML.replace('timeout = 120', 'timeout = 0'), TOML.replace('cwd = "."', 'cwd = "../private"'),
               TOML.replace('argv = ["python3", "-m", "unittest", "discover", "-s", "tests"]', 'argv = "sh test.sh"'),
               TOML.replace('format = "codex_summary_v1"', 'format = "free_text"'),
               TOML.replace('human_reviewers = ["operator"]', 'human_reviewers = ["openboa"]'),
               TOML.replace('app_id = 15368', 'app_id = 7'), TOML.replace('events = ["pull_request", "push"]', 'events = ["push"]'),
               'unknown = true\n' + TOML]
        for content in bad:
            with self.subTest(content=content):
                with self.assertRaises(ProjectError):
                    load_project(ConfigGitHub(content), 'example/product')

    def test_intake_actor_requires_actual_repository_write_permission(self):
        gh = ConfigGitHub()
        gh.api = lambda method, path: {'user': {'login': path.split('/')[-2]}, 'permission': 'read'}
        with self.assertRaisesRegex(ProjectError, 'repository writer'):
            load_project(gh, 'example/product')

    def test_ui_paths_come_only_from_pinned_contract(self):
        self.assertEqual(config()['ui_paths'], [])
        content = 'ui_paths = ["apps/web/", "src/**/*.tsx"]\n' + TOML
        self.assertEqual(load_project(ConfigGitHub(content), 'example/product')['ui_paths'], ['apps/web/', 'src/**/*.tsx'])
        for invalid in ['"apps/web"', '["/private/screen"]', '["../outside"]', '[false]']:
            with self.subTest(invalid=invalid), self.assertRaises(ProjectError):
                load_project(ConfigGitHub('ui_paths = ' + invalid + '\n' + TOML), 'example/product')

    def test_delivery_defaults_to_off_with_unknown_effect(self):
        cfg = load_project(ConfigGitHub(TOML.split('[delivery]')[0]), 'example/product')
        self.assertEqual(cfg['delivery'], {'automatic_merge': False, 'production_effect': True})
        blockers = gate_delivery(cfg, observation(), HEAD, ['src/main.py'])
        self.assertIn('automatic_merge_disabled', blockers)
        self.assertIn('production_effect_requires_decision', blockers)

    def test_intake_is_non_executable_and_does_not_attest_acceptance(self):
        issue = {'number': 4, 'state': 'open', 'title': 'Handle missing input', 'user': {'login': 'operator'},
                 'labels': [{'name': 'hydra:ready'}], 'body': '## Goal\nHandle empty input.\n## Scope\nParser only.\n## Acceptance\nRegression test passes.\n```hydra\nspec = "docs/engineering/parser/spec.md"\nspec_revision = "' + HEAD + '"\ndependencies = ["https://github.com/example/other/issues/3"]\npriority = 4\n```'}
        got = parse_intake(issue, config())
        self.assertEqual(got, {'issue_number': 4, 'spec': 'docs/engineering/parser/spec.md', 'spec_revision': HEAD,
                               'dependencies': ['https://github.com/example/other/issues/3'], 'priority': 4})
        for mutation in [dict(state='closed'), dict(user={'login': 'stranger'}), dict(labels=[{'name': 'hydra:ready'}, {'name': 'hydra:decision'}]),
                         dict(body=issue['body'].replace('## Acceptance', '## Notes')),
                         dict(body=issue['body'].replace('priority = 4', 'argv = ["sh", "bad.sh"]')),
                         dict(body=issue['body'].replace('priority = 4', 'ui = false')),
                         dict(body=issue['body'].replace('docs/engineering/parser/spec.md', '../private/spec.md')),
                         dict(body=issue['body'] + '\n```hydra\nspec="x"\n```')]:
            with self.subTest(mutation=mutation), self.assertRaises(ProjectError):
                parse_intake({**issue, **mutation}, config())

    def test_exact_head_genuine_checks_and_completed_provider_pass(self):
        self.assertEqual(gate_delivery(config(), observation(), HEAD, ['src/main.py']), [])

    def test_intake_spec_requires_its_concrete_path_in_candidate_allowlist(self):
        issue = {'number': 4, 'state': 'open', 'title': 'Scoped change', 'user': {'login': 'operator'},
                 'labels': [{'name': 'hydra:ready'}],
                 'body': '## Goal\nFix parsing.\n## Scope\nParser.\n## Acceptance\nTests pass.\n'
                         '```hydra\nspec = "docs/engineering/parser/spec.md"\nspec_revision = "' + HEAD + '"\n```'}
        cfg = config()
        for paths in [['src/'], ['docs/engineering/other/'], ['docs/engineering/parser/spec.md.bak']]:
            with self.subTest(paths=paths):
                cfg['allowed_paths'] = paths
                with self.assertRaisesRegex(ProjectError, 'candidate allowlist'):
                    parse_intake(issue, cfg)
        for paths in [['docs/'], ['docs/engineering/*/spec.md'], ['docs/engineering/parser/spec.md']]:
            with self.subTest(paths=paths):
                cfg['allowed_paths'] = paths
                self.assertEqual(parse_intake(issue, cfg)['spec'], 'docs/engineering/parser/spec.md')

    def test_spoofed_or_stale_checks_and_native_evidence_block(self):
        cases = [(['runs', 0, 'workflow_id'], 9), (['runs', 0, 'path'], '.github/workflows/fake.yml'),
                 (['runs', 0, 'event'], 'workflow_dispatch'), (['runs', 0, 'head_sha'], BASE),
                 (['runs', 0, 'jobs', 0, 'id'], 999), (['runs', 0, 'jobs', 0, 'conclusion'], 'skipped'),
                 (['checks', 0, 'app', 'id'], 7), (['checks', 0, 'check_suite', 'id'], 7),
                 (['runs', 0, 'pull_requests', 0, 'head', 'sha'], BASE),
                 (['runs', 0, 'pull_requests', 0, 'base', 'sha'], HEAD),
                 (['base_sha'], HEAD), (['pr', 'draft'], True), (['pr', 'mergeable_state'], 'blocked'),
                 (['rules', 1, 'parameters', 'strict_required_status_checks_policy'], False),
                 (['rule_sources', 0, 'bypass_actors'], [{'actor_id': 1}]),
                 (['review_decision'], 'REVIEW_REQUIRED')]
        for path, value in cases:
            with self.subTest(path=path):
                obs = observation(); target = obs
                for key in path[:-1]: target = target[key]
                target[path[-1]] = value
                self.assertTrue(gate_delivery(config(), obs, HEAD, ['src/main.py']))

    def test_newer_failed_rerun_does_not_reuse_old_success(self):
        obs = observation()
        failed = copy.deepcopy(obs['runs'][0])
        failed.update(id=51, run_attempt=2, conclusion='failure')
        failed['jobs'][0].update(id=91, conclusion='failure',
                                check_run_url='https://api.github.com/repos/example/product/check-runs/91')
        check = copy.deepcopy(obs['checks'][0]); check.update(id=91, conclusion='failure')
        obs['runs'].append(failed); obs['checks'].append(check)
        self.assertIn('check_job_not_successful:Unit tests', gate_delivery(config(), obs, HEAD, ['src/main.py']))
        self.assertEqual(terminal_required_checks(config(), obs, HEAD), [{'job': 'Unit tests', 'conclusion': 'failure'}])

    def test_optional_job_failure_does_not_block_successful_required_job(self):
        cfg, obs = config(), observation()
        run = obs['runs'][0]
        run['conclusion'] = 'failure'
        optional = copy.deepcopy(run['jobs'][0])
        optional.update(id=91, name='Optional report', conclusion='failure',
                        check_run_url='https://api.github.com/repos/example/product/check-runs/91')
        run['jobs'].append(optional)
        check = copy.deepcopy(obs['checks'][0]); check.update(id=91, name='Optional report', conclusion='failure')
        obs['checks'].append(check)
        self.assertEqual(gate_delivery(cfg, obs, HEAD, ['src/main.py']), [])
        self.assertEqual(terminal_required_checks(cfg, obs, HEAD), [])
        run.update(event='push', head_sha=MERGE, head_branch='main')
        for item in run['jobs'] + obs['checks']:
            item['head_sha'] = MERGE
        self.assertEqual(gate_checks(cfg, obs, MERGE, events=['push']), [])

    def test_required_job_and_check_failures_remain_actionable(self):
        for outcome in ['failure', 'timed_out', 'cancelled', 'startup_failure', 'skipped', 'unknown_result']:
            for source in ['job', 'check', 'both']:
                with self.subTest(outcome=outcome, source=source):
                    cfg, obs = config(), observation()
                    if source in {'job', 'both'}:
                        obs['runs'][0]['jobs'][0]['conclusion'] = outcome
                    if source in {'check', 'both'}:
                        obs['checks'][0]['conclusion'] = outcome
                    self.assertTrue(gate_checks(cfg, obs, HEAD))
                    self.assertEqual(terminal_required_checks(cfg, obs, HEAD),
                                     [{'job': 'Unit tests', 'conclusion': outcome}])

    def test_missing_required_job_in_completed_bound_run_requires_diagnosis(self):
        for conclusion in ['success', 'failure', 'cancelled', 'startup_failure']:
            with self.subTest(conclusion=conclusion):
                cfg, obs = config(), observation()
                obs['runs'][0].update(conclusion=conclusion, jobs=[])
                self.assertTrue(gate_checks(cfg, obs, HEAD))
                self.assertEqual(terminal_required_checks(cfg, obs, HEAD),
                                 [{'job': 'Unit tests', 'conclusion': 'missing_required_job'}])
        obs['runs'][0]['status'] = 'in_progress'
        self.assertTrue(gate_checks(cfg, obs, HEAD))
        self.assertEqual(terminal_required_checks(cfg, obs, HEAD), [])

    def test_completed_required_failure_is_actionable_while_optional_work_remains_active(self):
        for source in ['job', 'check', 'both']:
            with self.subTest(source=source):
                cfg, obs = config(), observation()
                obs['runs'][0].update(status='in_progress', conclusion=None)
                if source in {'job', 'both'}:
                    obs['runs'][0]['jobs'][0]['conclusion'] = 'failure'
                if source in {'check', 'both'}:
                    obs['checks'][0]['conclusion'] = 'failure'
                self.assertTrue(gate_checks(cfg, obs, HEAD))
                self.assertEqual(terminal_required_checks(cfg, obs, HEAD),
                                 [{'job': 'Unit tests', 'conclusion': 'failure'}])

    def test_unknown_or_active_required_evidence_does_not_pass_or_trigger_correction(self):
        cases = [(['runs', 0, 'workflow_id'], 999),
                 (['runs', 0, 'jobs', 0, 'head_sha'], BASE),
                 (['runs', 0, 'jobs', 0, 'check_run_url'], 'https://api.github.com/repos/other/repo/check-runs/90'),
                 (['checks', 0, 'app', 'id'], 999),
                 (['runs', 0, 'jobs', 0, 'status'], 'in_progress'),
                 (['checks', 0, 'status'], 'queued')]
        for path, value in cases:
            with self.subTest(path=path):
                cfg, obs = config(), observation()
                obs['runs'][0]['conclusion'] = 'failure'
                obs['runs'][0]['jobs'][0]['conclusion'] = 'failure'
                obs['checks'][0]['conclusion'] = 'failure'
                target = obs
                for key in path[:-1]:
                    target = target[key]
                target[path[-1]] = value
                self.assertTrue(gate_checks(cfg, obs, HEAD))
                self.assertEqual(terminal_required_checks(cfg, obs, HEAD), [])
        cfg, obs = config(), observation()
        cfg['required_checks'][0].update(reusable_workflow='example/controls/.github/workflows/check.yml', reusable_sha=BLOB)
        obs['runs'][0].update(conclusion='startup_failure', jobs=[])
        self.assertTrue(gate_checks(cfg, obs, HEAD))
        self.assertEqual(terminal_required_checks(cfg, obs, HEAD), [])

    def test_target_event_requires_current_base_head_association(self):
        cfg, obs = config(), observation(); cfg['required_checks'][0]['events'] = ['pull_request_target', 'push']
        obs['runs'][0].update(event='pull_request_target')
        self.assertEqual(gate_delivery(cfg, obs, HEAD, ['src/main.py']), [])
        obs['runs'][0]['pull_requests'][0]['head']['sha'] = BASE
        self.assertTrue(gate_delivery(cfg, obs, HEAD, ['src/main.py']))

    def test_observed_target_producer_and_codex_summary_contract(self):
        # Public API fields from ouroboros PR 2 / run 37883341081. This is a
        # historical producer-format fixture, not permission to merge a PR.
        head = '04de73009dd65f0bd0c0643db15dcfdc78f757b4'
        base = '313e4a6ee63de24abb3d37ae23aed4dec4838e53'
        pin = '83967987ca23cc8b8eda60975eda320e434fb7bd'
        repo = 'openboa-ai/ouroboros'
        cfg = config(); cfg.update(repository=repo, repository_id=1411114385, revision=base)
        cfg['required_checks'] = [{'workflow_id': 379254350,
            'workflow_path': '.github/workflows/trusted-baseline.yml',
            'job': 'trusted-baseline / Trusted repository baseline', 'events': ['pull_request_target', 'push'],
            'app_id': 15368, 'reusable_workflow': 'openboa-ai/.github/.github/workflows/repository-baseline.yml', 'reusable_sha': pin}]
        obs = {'head_sha': head, 'base_sha': base,
            'pr': {'number': 2, 'state': 'closed', 'merged': True, 'commits': 1,
                   'head': {'sha': head, 'ref': 'codex/development-readiness', 'repo': {'id': 1411114385}},
                   'base': {'sha': base, 'ref': 'main', 'repo': {'id': 1411114385}}},
            'runs': [{'id': 37883341081, 'workflow_id': 379254350,
                'path': '.github/workflows/trusted-baseline.yml', 'repository': {'id': 1411114385},
                'event': 'pull_request_target', 'head_sha': head, 'head_branch': 'codex/development-readiness',
                'pull_requests': [], 'referenced_workflows': [{'path': cfg['required_checks'][0]['reusable_workflow'] + '@' + pin, 'sha': pin}],
                'check_suite_id': 102640931543, 'run_number': 2, 'run_attempt': 1, 'status': 'completed', 'conclusion': 'success',
                'jobs': [{'id': 113667757620, 'name': 'trusted-baseline / Trusted repository baseline',
                         'head_sha': head, 'status': 'completed', 'conclusion': 'success',
                         'check_run_url': 'https://api.github.com/repos/openboa-ai/ouroboros/check-runs/113667757620'}]}],
            'checks': [{'id': 113667757620, 'name': 'trusted-baseline / Trusted repository baseline',
                        'head_sha': head, 'status': 'completed', 'conclusion': 'success',
                        'check_suite': {'id': 102640931543}, 'app': {'id': 15368}}],
            'commits': [{'sha': head}], 'threads': [], 'inline_comments': [],
            'provider_comments': [{'id': 6074182170, 'user': {'id': 199175422, 'login': 'chatgpt-codex-connector[bot]'},
                'performed_via_github_app': {'id': 1144995},
                'body': summary(head).replace('example/product', repo).replace('"pullRequestNumber": 7', '"pullRequestNumber": 2')}]}
        self.assertEqual(gate_checks(cfg, obs, head), [])
        self.assertEqual(_provider(cfg, obs, head), [])
        for path, value in [(['runs', 0, 'head_sha'], base), (['runs', 0, 'head_branch'], 'other'),
                            (['runs', 0, 'pull_requests'], None), (['runs', 0, 'event'], 'pull_request'),
                            (['runs', 0, 'referenced_workflows'], []),
                            (['runs', 0, 'referenced_workflows', 0, 'sha'], BASE),
                            (['runs', 0, 'jobs', 0, 'check_run_url'], 'https://api.github.com/repos/other/repo/check-runs/113667757620'),
                            (['pr', 'head', 'repo', 'id'], 999), (['checks', 0, 'app', 'id'], 999)]:
            with self.subTest(path=path):
                broken = copy.deepcopy(obs); target = broken
                for key in path[:-1]: target = target[key]
                target[path[-1]] = value
                self.assertTrue(gate_checks(cfg, broken, head))
        del cfg['required_checks'][0]['reusable_sha']
        self.assertTrue(gate_checks(cfg, obs, head))

    def test_reusable_revision_is_bound(self):
        cfg, obs = config(), observation(); b = cfg['required_checks'][0]
        b.update(reusable_workflow='example/controls/.github/workflows/check.yml', reusable_sha=BLOB)
        self.assertIn('check_reusable_identity_missing:Unit tests', gate_delivery(cfg, obs, HEAD, ['src/main.py']))
        obs['runs'][0]['referenced_workflows'] = [{'path': b['reusable_workflow'] + '@' + BLOB, 'sha': BLOB}]
        self.assertEqual(gate_delivery(cfg, obs, HEAD, ['src/main.py']), [])

    def test_provider_spoof_unknown_stale_prefix_or_missing_security_wait(self):
        cases = [(['provider_comments', 0, 'user', 'id'], 77),
                 (['provider_comments', 0, 'performed_via_github_app', 'id'], 77),
                 (['provider_comments', 0, 'body'], summary(BASE)),
                 (['provider_comments', 0, 'body'], summary().replace('✅ **Completed**', '⏳ **Running**', 1)),
                 (['provider_comments', 0, 'body'], summary().replace('**Security Review**', '**Other Review**')),
                 (['pr', 'commits'], 2)]
        for path, value in cases:
            with self.subTest(path=path):
                obs = observation(); target = obs
                for key in path[:-1]: target = target[key]
                target[path[-1]] = value
                self.assertTrue(gate_delivery(config(), obs, HEAD, ['src/main.py']))
        obs = observation(); obs['pr']['commits'] = 2; obs['commits'].append({'sha': 'b' * 7 + 'c' * 33})
        self.assertIn('provider_revision_ambiguous_or_stale', gate_delivery(config(), obs, HEAD, ['src/main.py']))

    def test_security_threshold_is_not_no_findings(self):
        obs = observation(); comment = copy.deepcopy(obs['provider_comments'][0]); comment.update(id=61, body='Finding: fix this issue.'); obs['provider_comments'].append(comment)
        self.assertIn('provider_additional_comments_require_resolution', gate_delivery(config(), obs, HEAD, ['src/main.py']))
        obs = observation(); obs['inline_comments'] = [{'id': 71}]
        self.assertIn('review_comment_resolution_unobserved', gate_delivery(config(), obs, HEAD, ['src/main.py']))
        obs['threads'] = [{'isResolved': True, 'comments': {'nodes': [{'databaseId': 71}]}}]
        self.assertEqual(gate_delivery(config(), obs, HEAD, ['src/main.py']), [])
        obs['threads'][0]['isResolved'] = False
        self.assertIn('review_threads_unresolved_or_unknown', gate_delivery(config(), obs, HEAD, ['src/main.py']))

    def test_protected_path_current_human_approval_and_renames(self):
        obs = observation(); obs['changed_files'] = [{'filename': 'src/new.py', 'previous_filename': '.hydra.toml'}]
        paths = ['src/new.py', '.hydra.toml']
        self.assertIn('protected_change_needs_current_human_review', gate_delivery(config(), obs, HEAD, paths))
        self.assertIn('changed_paths_mismatch', gate_delivery(config(), obs, HEAD, ['src/new.py']))
        obs['native_reviews'] = [{'id': 1, 'user': {'login': 'operator', 'type': 'User'}, 'state': 'APPROVED', 'commit_id': HEAD}]
        obs['review_decision'] = 'APPROVED'
        self.assertEqual(gate_delivery(config(), obs, HEAD, paths), [])
        obs['native_reviews'][0]['commit_id'] = BASE
        self.assertIn('protected_change_needs_current_human_review', gate_delivery(config(), obs, HEAD, paths))

    def test_nullable_review_authors_and_app_identity_never_authorize_delivery(self):
        obs = observation()
        obs['provider_comments'].insert(0, {'user': None, 'performed_via_github_app': None})
        self.assertEqual(gate_delivery(config(), obs, HEAD, ['src/main.py']), [])
        obs['provider_comments'][-1]['performed_via_github_app'] = None
        self.assertTrue(gate_delivery(config(), obs, HEAD, ['src/main.py']))
        obs = observation()
        obs['native_reviews'] = [{'id': 1, 'user': None, 'state': 'APPROVED', 'commit_id': HEAD}]
        self.assertIn('native_review_author_unknown', gate_delivery(config(), obs, HEAD, ['src/main.py']))

    def test_actual_merge_push_checks_required_before_completion(self):
        cfg, obs = config(), observation()
        self.assertTrue(gate_post_merge(cfg, obs, MERGE))
        obs['pr'].update(merged=True, merge_commit_sha=MERGE)
        obs['runs'][0].update(event='push', head_sha=MERGE, head_branch='main')
        obs['runs'][0]['jobs'][0]['head_sha'] = MERGE; obs['checks'][0]['head_sha'] = MERGE
        self.assertEqual(gate_post_merge(cfg, obs, MERGE), [])
        obs['runs'][0]['head_branch'] = 'other'
        self.assertTrue(gate_post_merge(cfg, obs, MERGE))
        self.assertEqual(gate_checks(cfg, obs, MERGE, events=['unknown']), ['check_target_unknown'])


if __name__ == '__main__':
    unittest.main()
