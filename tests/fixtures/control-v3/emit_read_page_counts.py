"""One actual read producer and independent membership-count oracles."""
from pathlib import Path
import copy,json,sys
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from hydra_sdlc import projection as p
from test_projection_read import ReadFixture

def vectors():
    frame=ReadFixture().read()
    assert len(frame['projects'])==2
    result=[]
    for case in json.loads(Path(__file__).with_name('read-page-counts.json').read_text())['cases']:
        value=copy.deepcopy(frame)
        value['page'].update(state=case['state'],returned_count=case['count'],total_count=case['total'],
            next_cursor=None,reason=None if case['state']=='complete' else 'source_coverage_incomplete')
        # Invalid wire is serialized directly so the consumer under test decides.
        wire=json.dumps(value,separators=(',',':'))
        result.append({'name':case['name'],'accepted':case['accepted'],'wire':wire})
    return result
if __name__=='__main__':print(json.dumps(vectors()))
