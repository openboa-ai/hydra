"""Actual synthetic Registration replies shared by all three data readers.

No native source, network, runtime installation or execution authority is involved.
"""
import asyncio
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'tests'))
import test_work_creation as fixture


async def originals():
    result = {}
    async def run(kind):
        test = fixture.WorkCreationTests()
        await test.asyncSetUp()
        try:
            if kind == 'registered':
                result[kind] = await test.create()
                before = copy.deepcopy(test.wire.writes)
                result['registered_replay'] = await test.create()
                assert result[kind]['request']['receipt'] == result['registered_replay']['request']['receipt']
                assert test.wire.writes == before
                assert [name for name, _ in before] == ['fence', 'issue', 'binding']
            elif kind == 'history_unavailable':
                test.controller.creation_source = None
                result[kind] = await test.create()
                assert not test.wire.writes
            else:
                test.wire.fail_after.add('binding')
                test.wire.after_effect = lambda name, value: (
                    test.wire.hidden_comments.add(value['id']) if name == 'binding' else None)
                result[kind] = await test.create()
                assert [name for name, _ in test.wire.writes] == ['fence', 'issue', 'binding']
                assert result[kind]['request']['receipt'] is None
                assert any(ref['kind'] == 'issue' for ref in result[kind]['request']['effect_refs'])
        finally:
            test.doCleanups()
    for kind in ('registered', 'history_unavailable', 'partial_issue'):
        await run(kind)
    for name, reply in result.items():
        expected = 'applied' if name.startswith('registered') else 'unknown'
        assert reply['request']['outcome'] == expected, name
        assert fixture.CANARY not in json.dumps(reply)
    return result


def locate(value, path):
    for key in path:
        value = value[key]
    return value


def vectors():
    matrix = json.loads(Path(__file__).with_name('creation-receipts.json').read_text())
    assert matrix['fixture_version'] == 1 and 0 < len(matrix['cases']) <= 256
    bases = asyncio.run(originals())
    rows = []
    for case in matrix['cases']:
        value = copy.deepcopy(bases[case['base']])
        for change in case['changes']:
            locate(value, change['path'][:-1])[change['path'][-1]] = change['value']
        for path in case['delete']:
            del locate(value, path[:-1])[path[-1]]
        if case['omit_effect'] is not None:
            ref = value['request']['receipt'][case['omit_effect']]
            value['request']['effect_refs'] = [item for item in value['request']['effect_refs'] if item != ref]
        wire = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
        assert fixture.CANARY not in wire
        rows.append({'name': case['name'], 'wire': wire, 'schema_accepted': case['schema_accepted'],
                     'standard_reason': case['standard_reason']})
    return rows


if __name__ == '__main__':
    print(json.dumps(vectors(), ensure_ascii=False, separators=(',', ':')))
