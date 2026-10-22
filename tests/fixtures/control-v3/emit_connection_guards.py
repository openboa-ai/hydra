"""The real settings/config/read producer supplies unchanged strict consumers."""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.dont_write_bytecode = True
sys.path[:0] = [str(ROOT), str(ROOT / 'tests')]
from hydra_sdlc import projection as p
import test_connection_review as fixture


def vectors():
    cases = json.loads(Path(__file__).with_name('connection-guards.json').read_text())['cases']
    rows = []
    for case in cases:
        probe = fixture.ConnectionReviewTests('test_connected_current_work_and_legacy_controls_keep_normal_paths')
        probe.setUp()
        try:
            mode = case['mode']
            cfg = probe.connected(desired='disconnect_requested' if mode in
                {'disconnect', 'forged_disconnect', 'paused'} else 'connected')
            if mode in {'unprepared', 'forged_unprepared'}:
                cfg = probe.load(probe.text().replace(
                    f'[project_connections."{fixture.ALPHA}"]\ndesired="connected"\n', '')
                    + f'[project_connections."{fixture.BETA}"]\ndesired="connected"\n')
            control = probe.state(cfg, projects={fixture.ALPHA: 'running', fixture.BETA: 'running'})
            if mode == 'paused':
                snapshot = control.snapshot()
                snapshot['global_mode'] = 'paused'
                control.settings_path.write_text(json.dumps(snapshot) + '\n')
            frame = probe.frame(cfg)
            stored = next(row['value'] for row in frame['observations']
                if row['resource']['kind'] == 'admission' and row['value'] is not None)
            assert stored['project_overrides'][fixture.ALPHA] == 'running'
            if case['accepted']:
                expected = {'101': case['alpha'], '102': case['beta']}
                assert {row['repository_ref']['id']: row['admission']['value'] for row in frame['projects']} == expected
                assert all(row['admission']['value'] == expected[row['issue_ref']['id'].split(':')[0]] for row in frame['work'])
                wire = p.encode(frame).decode('utf-8')
            else:
                alpha = next(row for row in frame['projects'] if row['repository_ref']['id'] == '101')
                assert alpha['admission']['value'] is None
                alpha['admission'].update(value='allowed', reason=None)
                wire = json.dumps(frame, separators=(',', ':'))
            assert str(probe.path) not in wire
            rows.append({'name': case['name'], 'accepted': case['accepted'], 'wire': wire})
        finally:
            probe.doCleanups()
    return rows


if __name__ == '__main__':
    print(json.dumps(vectors(), separators=(',', ':')))
