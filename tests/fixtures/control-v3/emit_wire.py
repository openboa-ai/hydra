"""Emit actual producer bytes and deliberate bad-wire inputs for real consumers.

One versioned input/oracle set is shared across Python, Rust and TypeScript.
No provider calls, saved native conversation or independent output goldens.
"""
from pathlib import Path
import copy
import json
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from hydra_sdlc import projection as p


def locate(value, path):
    for key in path:
        value = value[key]
    return value


def standard(frame):
    from hydra_sdlc.control_commands import _observation, _reply
    command = {'request_id': frame['request_id'], 'action': 'admission_set',
               'target': {'kind': 'repository', 'repository_id': 101}}
    observation = _observation(command, frame['runtime'],
        {'revision': 7, 'global_mode': 'paused', 'projects': {'example/alpha': 'running'}},
        'example/alpha', 'readback', frame['assembled_at'])
    return _reply(command, frame['runtime'], frame['binding_epoch'], 'applied', None,
                  observation=observation)


def vectors():
    fixture = json.loads(Path(__file__).with_name('inputs.json').read_text())
    assert fixture['fixture_version'] == 1 and 0 < len(fixture['cases']) <= 32
    result = []
    for case in fixture['cases']:
        value = (reader(fixture['frame'], fixture['reader']) if case.get('producer') == 'reader' else
                 copy.deepcopy(fixture['frame']) if case['profile'] == 'projection' else
                 legacy(fixture['frame']) if case['profile'] == 'legacy' else standard(fixture['frame']))
        for change in case['changes']:
            path = change['path']
            locate(value, path[:-1])[path[-1]] = change['value']
        for path in case['delete']:
            del locate(value, path[:-1])[path[-1]]
        wire = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        if case['duplicate'] is not None:
            duplicate = case['duplicate']
            wire = '{' + json.dumps(duplicate['key']) + ':' + json.dumps(duplicate['value']) + ',' + wire[1:]
        rejected = False
        try:
            parsed = p.read_json(wire.encode('utf-8'))
            if case['profile'] == 'projection':
                wire = p.encode(parsed).decode('utf-8')
            elif case['profile'] == 'standard':
                p.standard_reply(parsed)
        except p.ProjectionError:
            rejected = True
        assert rejected != case['accepted'], case['name']
        if case['accepted']:
            for expected in case['expected']:
                assert locate(value, expected['path']) == expected['value'], case['name']
        result.append({'name': case['name'], 'profile': case['profile'], 'accepted': case['accepted'],
                       'producer_rejected': rejected, 'wire': wire, 'expected': case['expected']})
    return result



def reader(frame, inputs):
    from contextlib import ExitStack
    from types import SimpleNamespace
    from urllib.parse import urlsplit, parse_qs
    from unittest.mock import patch
    from hydra_sdlc.cli import parser, operate_control
    from hydra_sdlc.projection_read import ProjectionClient, read_projection as read_source
    calls = []
    def transport(method, path, payload):
        assert method == 'GET' and payload is None
        calls.append(path)
        if path == '/user': return {'id': 42, 'login': 'openboa'}
        parsed = urlsplit(path)
        parts = parsed.path.strip('/').split('/')
        repository = '/'.join(parts[1:3])
        assert repository in inputs['repos']
        if len(parts) == 3:
            return {'id': 101 if repository == 'example/alpha' else 102,
                    'full_name': repository, 'default_branch': 'main'}
        query = parse_qs(parsed.query)
        if query.get('state') == ['open'] and 'labels' not in query and repository == 'example/alpha':
            return copy.deepcopy(inputs['issues'])
        return []
    cfg = {'repos': inputs['repos'], 'host_alias': 'fixture', 'lock_path': 'unused-fixture-lock'}
    control = SimpleNamespace(snapshot=lambda: {'revision': 7, 'global_mode': 'paused', 'projects': {}})
    client = ProjectionClient(transport=transport)
    with ExitStack() as context:
        context.enter_context(patch('hydra_sdlc.control.load_host_config', return_value=cfg))
        context.enter_context(patch('hydra_sdlc.projection_read.control_from_config', return_value=control))
        context.enter_context(patch('hydra_sdlc.projection_read.observe_coordinator', return_value={'state':'free'}))
        context.enter_context(patch('hydra_sdlc.projection_read.capture_runtime_identity', return_value=frame['runtime']))
        context.enter_context(patch('hydra_sdlc.projection_read.read_projection', side_effect=
            lambda *args, **kwargs: read_source(*args, **kwargs, github=client)))
        context.enter_context(patch('hydra_sdlc.projection_read._now', return_value=frame['assembled_at']))
        value = operate_control(parser().parse_args(['control','status','--config','/example/host.toml',
            '--projection-schema','3','--binding-epoch',frame['binding_epoch'],'--request-id',frame['request_id'],'--refresh']))
    assert calls and len(calls) <= 20
    assert 'SYNTHETIC_UNTRUSTED_EXTRA_CANARY' not in json.dumps(value)
    return value


def legacy(frame):
    from contextlib import ExitStack
    from types import SimpleNamespace
    from unittest.mock import patch
    from hydra_sdlc.control import control_result
    with ExitStack() as context:
        control = SimpleNamespace(snapshot=lambda: {'revision': 7, 'global_mode': 'paused',
                                  'projects': {'example/alpha': 'running'}})
        context.enter_context(patch('hydra_sdlc.control.control_from_config', return_value=control))
        context.enter_context(patch('hydra_sdlc.control.residual_workers', return_value=[]))
        context.enter_context(patch('hydra_sdlc.control.observe_coordinator', return_value={'state': 'free'}))
        context.enter_context(patch('hydra_sdlc.control.capture_runtime_identity', return_value=frame['runtime']))
        return control_result({'repos': ['example/alpha'], 'host_alias': 'fixture',
                               'lock_path': 'unused-fixture-lock'})


if __name__ == '__main__':
    print(json.dumps(vectors(), ensure_ascii=False, separators=(',', ':')))
