"""Actual read producer, one independent admission-default oracle matrix."""
from pathlib import Path
import copy
import json
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from hydra_sdlc import projection as p
from test_projection_read import ReadFixture, issue


def vectors():
    cases = json.loads(Path(__file__).with_name('connection-defaults.json').read_text())['cases']
    result = []
    for case in cases:
        mode = case['mode']
        snapshot = {'version': 1 if mode == 'legacy' else 2, 'revision': 7,
            'global_mode': 'paused' if mode == 'paused' else 'running',
            'projects': {'example/alpha': 'running'}}
        if mode != 'legacy':
            snapshot['connection_config'] = {'profile': 1, 'path': '/synthetic/PRIVATE_BINDING_CANARY.toml'}
        if mode == 'explicit':
            snapshot['projects']['example/beta'] = 'running'
        fixture = ReadFixture({('example/alpha', 'open', False): [issue(7)],
                               ('example/beta', 'open', False): [issue(8)]})
        frame = fixture.read(admission_snapshot=snapshot)
        admission = next(row['value'] for row in frame['observations'] if row['resource']['kind'] == 'admission')
        assert 'PRIVATE_BINDING_CANARY' not in json.dumps(frame)
        if case['accepted']:
            assert [row['admission']['value'] for row in frame['projects']] == [case['alpha'], case['beta']]
            assert [row['admission']['value'] for row in frame['work']] == [case['alpha'], case['beta']]
            assert ('default_project_mode' in admission) == (mode != 'legacy')
            wire = p.encode(frame).decode('utf-8')
        else:
            if mode == 'wrong_fact':
                frame['projects'][1]['admission']['value'] = 'allowed'
            elif mode == 'boolean':
                admission['default_project_mode'] = True
            elif mode == 'bad_default':
                admission['default_project_mode'] = 'paused'
            elif mode == 'private_field':
                admission['connection_config'] = copy.deepcopy(snapshot['connection_config'])
            elif mode == 'missing_default':
                del admission['default_project_mode']
            wire = json.dumps(frame, separators=(',', ':'))
        result.append({'name': case['name'], 'accepted': case['accepted'], 'wire': wire})
    return result


if __name__ == '__main__':
    print(json.dumps(vectors(), separators=(',', ':')))
