"""Native identity spelling and external waits do not change work semantics."""

import asyncio
import copy
import json
import unittest
from contextlib import nullcontext
from types import SimpleNamespace
from unittest.mock import patch

from hydra_sdlc.cli import operate, parser
from hydra_sdlc.github import GitHub as Client
from hydra_sdlc.project import ProjectError, load_project, parse_intake
from hydra_sdlc.runner import Runner, intake_digest
from test_active_labels import NativeIssueTransport
from test_github import BASE, HEAD, IDENTITY, REPO
from test_project import ConfigGitHub, TOML
from test_runner import GitHub


class CasePreservingLabels(NativeIssueTransport):
    spelling = 'Hydra:Active'

    def __call__(self, method, path, payload):
        present = any(x['name'].casefold() == 'hydra:active' for x in self.issue['labels'])
        if method == 'POST' and path.endswith('/issues/4/labels'):
            self.calls.append((method, path, payload))
            if not present:
                self.issue['labels'].append({'name': self.spelling})
            return copy.deepcopy(self.issue['labels'])
        if method == 'DELETE' and path.endswith('/labels/hydra%3Aactive'):
            self.calls.append((method, path, payload))
            self.issue['labels'] = [x for x in self.issue['labels'] if x['name'].casefold() != 'hydra:active']
            return copy.deepcopy(self.issue['labels'])
        if method == 'GET' and '?state=closed&labels=hydra%3Aactive&' in path:
            self.calls.append((method, path, payload))
            return [copy.deepcopy(self.issue)] if self.issue['state'] == 'closed' and present else []
        return super().__call__(method, path, payload)


class LabelIdentityTests(unittest.TestCase):
    def test_case_preserved_add_readback_and_repeat_record_need_no_rename(self):
        for spelling in ('Hydra:Active', 'HYDRA:ACTIVE'):
            with self.subTest(spelling=spelling):
                transport = CasePreservingLabels()
                transport.spelling = spelling
                github = Client(transport=transport)
                record = {'phase': 'ready', 'branch': 'hydra/issue-4', 'head': HEAD}
                github.record(REPO, 4, record)
                self.assertEqual(github.progress(REPO, 4)['phase'], 'ready')
                self.assertEqual(transport.issue['labels'], [{'name': 'unrelated'}, {'name': spelling}])
                before = len(transport.calls)
                github.record(REPO, 4, record)
                self.assertTrue(all(m == 'GET' for m, _, _ in transport.calls[before:]))

    def test_case_preserved_closed_recovery_authenticates_and_cleans_only_active_label(self):
        for authenticated in (False, True):
            with self.subTest(authenticated=authenticated):
                transport = CasePreservingLabels()
                transport.issue.update(state='closed', comments=1,
                    labels=[{'name': 'unrelated'}, {'name': transport.spelling}])
                record = {'phase': 'completed', 'pending_action': None, 'wait_reason': None}
                transport.comment = {'id': 77, 'user': IDENTITY if authenticated else {'id': 999, 'login': 'foreign'},
                    'body': '<!-- hydra-progress:v1 ' + json.dumps({**record,
                        'version': 1, 'repository_id': 123, 'issue_number': 4}) + ' -->'}
                github = Client(transport=transport)
                self.assertEqual(github.issues(REPO), [transport.issue] if authenticated else [])
                self.assertTrue(all(m == 'GET' for m, _, _ in transport.calls))
                if authenticated:
                    github.record(REPO, 4, record)
                    self.assertEqual(transport.issue['labels'], [{'name': 'unrelated'}])
                    self.assertEqual([m for m, _, _ in transport.calls if m != 'GET'], ['DELETE'])
                    self.assertEqual(github.issues(REPO), [])


class ControlLabelIdentityTests(unittest.TestCase):
    def setUp(self):
        self.github = GitHub()
        self.runner = Runner(self.github, None, host_alias='host-a', execute=None, capabilities=None)

    def test_ready_and_uppercase_configured_roles_match_without_renaming(self):
        for configured_uppercase in (False, True):
            with self.subTest(configured_uppercase=configured_uppercase):
                content = TOML
                if configured_uppercase:
                    for role in ('ready', 'paused', 'decision'):
                        content = content.replace(f'"hydra:{role}"', f'"HYDRA:{role.upper()}"')
                config = load_project(ConfigGitHub(content), REPO)
                self.github.cfg = config
                self.github.work['labels'] = [{'name': 'Hydra:Ready'}]
                before = copy.deepcopy(self.github.work['labels'])
                self.assertEqual(parse_intake(self.github.work, config)['issue_number'], 4)
                with patch('hydra_sdlc.runner.load_project', return_value=copy.deepcopy(config)):
                    self.assertIsNone(self.runner._latest(REPO, 4, config))
                self.assertEqual(self.github.work['labels'], before)
                self.assertEqual(self.github.writes, [])

    def test_paused_and_decision_case_variants_block_intake_and_final_dispatch(self):
        for role, reason in (('paused', 'paused'), ('decision', 'human_decision')):
            for configured_uppercase in (False, True):
                with self.subTest(role=role, configured_uppercase=configured_uppercase):
                    self.setUp()
                    if configured_uppercase:
                        self.github.cfg['labels'] = {key: value.upper() for key, value in self.github.cfg['labels'].items()}
                    self.github.work['labels'] = [{'name': 'Hydra:Ready'}, {'name': f'HYDRA:{role.upper()}'}]
                    with self.assertRaises(ProjectError):
                        parse_intake(self.github.work, self.github.cfg)
                    self.github.work['labels'] = [{'name': 'Hydra:Ready'}]
                    previous = {'phase': 'ready', 'pending_action': None,
                                'intake_digest': intake_digest(self.github.work)}
                    self.github.on_record = lambda record: self.github.work['labels'].append({'name': f'HYDRA:{role.upper()}'})
                    config = {**self.github.cfg, 'intake_digest': previous['intake_digest']}
                    with patch('hydra_sdlc.runner.load_project', return_value=copy.deepcopy(self.github.cfg)):
                        result = self.runner._intent(REPO, 4, config, previous, 'implementation', phase='executing')
                    self.assertIsNone(result)
                    self.assertEqual(self.github.note['phase'], 'ready')
                    self.assertEqual(self.github.note['wait_reason'], reason)
                    self.assertIsNone(self.github.note['pending_action'])
                    self.assertTrue(all(write[0] == 'record' for write in self.github.writes))

    def test_current_completion_control_case_variants_still_block_final_dispatch(self):
        for role, reason in (('paused', 'paused'), ('decision', 'human_decision')):
            with self.subTest(role=role):
                self.setUp()
                previous = {'phase': 'observing', 'pending_action': None,
                            'intake_digest': intake_digest(self.github.work)}
                config = {**self.github.cfg, '_completion_only': True,
                          '_completion_controls': {'paused': 'Current:Paused', 'decision': 'Current:Decision'},
                          'intake_digest': previous['intake_digest']}
                self.github.on_record = lambda record: self.github.work['labels'].append({'name': f'CURRENT:{role.upper()}'})
                result = self.runner._intent(REPO, 4, config, previous, 'close_issue', phase='closing')
                self.assertIsNone(result)
                self.assertEqual(self.runner._latest(REPO, 4, config), reason)
                self.assertEqual(self.github.note['pending_action'], 'close_issue')
                self.assertTrue(all(write[0] == 'record' for write in self.github.writes))

    def test_case_aliases_cannot_assign_one_native_label_to_multiple_control_roles(self):
        for replaced, value in (('paused', 'READY'), ('paused', 'HYDRA:READY'), ('decision', 'Hydra:Paused')):
            with self.subTest(replaced=replaced):
                content = TOML.replace(f'{replaced} = "hydra:{replaced}"', f'{replaced} = "{value}"')
                if value == 'READY':
                    content = content.replace('ready = "hydra:ready"', 'ready = "ready"')
                with self.assertRaises(ProjectError):
                    load_project(ConfigGitHub(content), REPO)


class DependencyIdentityTests(unittest.IsolatedAsyncioTestCase):
    async def dispatch(self, *, repeated=False, recovery=False, registered=REPO):
        github = GitHub()
        def issue(number, priority, dependencies=()):
            value = copy.deepcopy(github.work)
            value.update(number=number, created_at=f'2026-10-10T00:00:0{number}Z')
            value['body'] = value['body'].replace('spec = ',
                f'priority = {priority}\ndependencies = {list(dependencies)!r}\nspec = ')
            return value
        dependencies = [f'https://github.com/Example/Product/issues/1']
        if repeated:
            dependencies += [f'https://github.com/EXAMPLE/PRODUCT/issues/1',
                             f'https://github.com/{REPO}/issues/1']
        items = {1: issue(1, 0), 2: issue(2, 10), 3: issue(3, 20, dependencies)}
        if repeated:
            items[4] = issue(4, 20, [f'https://github.com/{REPO}/issues/2'])
        github.issues = lambda repo: copy.deepcopy(list(items.values()))
        github.issue = lambda repo, number: copy.deepcopy(items[number])
        progress = {'phase': 'implementation_done', 'branch': 'hydra/issue-2',
                    'contract_revision': BASE, 'head': HEAD, 'intake_digest': intake_digest(items[2])}
        github.progress = lambda repo, number: copy.deepcopy(progress) if recovery and number == 2 else None
        runner = Runner(github, None, host_alias='host-a', execute=None, capabilities=None)
        order = []
        async def step(repo, number):
            order.append(number)
            return {'action': 'continue'}
        runner.step = step
        with patch('hydra_sdlc.runner.load_project', side_effect=lambda gh, repo, revision=None: copy.deepcopy(gh.cfg)):
            await runner.cycle([registered])
        self.assertEqual(github.writes, [])
        return order

    async def test_dependency_and_registered_repository_case_do_not_hide_unblocker(self):
        for registered in (REPO, 'EXAMPLE/Product'):
            with self.subTest(registered=registered):
                self.assertEqual(await self.dispatch(registered=registered), [1, 2])

    async def test_one_issue_case_aliases_count_once_and_recovery_stays_first(self):
        self.assertEqual(await self.dispatch(repeated=True), [2, 1])
        self.assertEqual(await self.dispatch(recovery=True), [2, 1])


class WaitCadenceTests(unittest.IsolatedAsyncioTestCase):
    async def observe(self, command, result, *, timeout=1000, signal_stop=False):
        clock, observed = [0.0], []
        class SecondObservation(Exception):
            pass
        class FakeRunner:
            def __init__(self, *args, stop_requested, **kwargs):
                self.stop_requested = stop_requested
            async def step(self, *args):
                observed.append(clock[0])
                if len(observed) > 1:
                    raise SecondObservation()
                return copy.deepcopy(result)
            async def cycle(self, *args):
                return [await self.step()]
        handlers = {}
        def handler(sig, callback):
            handlers[sig] = callback
        async def sleep(delay):
            clock[0] += delay
            if signal_stop:
                import signal
                handlers[signal.SIGTERM](signal.SIGTERM, None)
        target = ['--issue', f'https://github.com/{REPO}/issues/1'] if command == 'run' else ['--repos', REPO]
        args = parser().parse_args([command, *target, '--workspace-root', '/unused', '--host-alias', 'host-a',
                                    '--timeout', str(timeout)])
        with patch('hydra_sdlc.runner.Runner', FakeRunner), \
                patch('hydra_sdlc.cli.coordinator_lock', return_value=nullcontext()), \
                patch('hydra_sdlc.cli.residual_workers', return_value=[]), \
                patch('hydra_sdlc.cli.asyncio.get_running_loop', return_value=SimpleNamespace(time=lambda: clock[0])), \
                patch('hydra_sdlc.cli.asyncio.sleep', sleep), \
                patch('hydra_sdlc.cli.signal.signal', side_effect=handler):
            try:
                outcome = await operate(args, github=object(), workspace=object(), emit=lambda text: None)
            except SecondObservation:
                outcome = None
        return observed, clock[0], outcome

    async def test_run_and_serve_share_active_external_wait_cadence(self):
        for command in ('run', 'serve'):
            for reason in ('remote_delivery_gates', 'post_merge_checks', 'delivery_facts_changed'):
                with self.subTest(command=command, reason=reason):
                    observed, _, _ = await self.observe(command, {'action': 'waiting', 'reason': reason})
                    self.assertEqual(observed, [0.0, 60.0])

    async def test_passive_wait_continue_deadline_and_signal_keep_their_behavior(self):
        passive = {'action': 'waiting', 'reason': 'human_decision'}
        self.assertEqual((await self.observe('serve', passive))[0], [0.0, 300.0])
        self.assertEqual((await self.observe('run', passive))[2], passive)
        for command in ('run', 'serve'):
            with self.subTest(command=command):
                self.assertEqual((await self.observe(command, {'action': 'continue'}))[0], [0.0, 0.0])
                for options, elapsed in (({'timeout': 20}, 20), ({'signal_stop': True}, 1)):
                    observed, duration, outcome = await self.observe(command,
                        {'action': 'waiting', 'reason': 'delivery_facts_changed'}, **options)
                    self.assertEqual(observed, [0.0])
                    self.assertEqual(duration, elapsed)
                    self.assertEqual(outcome, {'action': 'stopped', 'reason': 'signal_or_deadline'})
