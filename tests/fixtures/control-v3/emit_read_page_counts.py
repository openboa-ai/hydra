"""One actual read producer and independent membership-count oracles."""
from pathlib import Path
import copy,json,sys
ROOT=Path(__file__).resolve().parents[3]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
from hydra_sdlc import projection as p
from test_projection_read import ReadFixture,issue

def vectors():
    frame=ReadFixture({('example/alpha','open',True):[issue(7)]}).read()
    assert len(frame['projects'])==2
    result=[]
    for case in json.loads(Path(__file__).with_name('read-page-counts.json').read_text())['cases']:
        value=copy.deepcopy(frame)
        target=value['page']
        if case.get('target')=='work_membership':
            mode=case['mode']
            if mode in {'complete_empty','partial_empty','empty_both'}:
                project=value['projects'][0];project['work_refs']=[]
                partial=mode=='partial_empty'
                project['coverage'].update(state='partial' if partial else 'complete',returned_count=0,
                    total_count=None if partial else 0,next_cursor=None,reason='source_coverage_incomplete' if partial else None)
            if mode=='no_projects':value['projects']=[]
            if mode=='wrong_project':value['projects']=value['projects'][1:]
            if mode in {'unexpanded','empty_both'}:value['work']=[]
        if case.get('target')=='project':
            project=value['projects'][0]
            assert len(project['work_refs'])==1
            project['work_refs']=project['work_refs'][:case['refs']]
            target=project['coverage']
        target.update(state=case['state'],returned_count=case['count'],total_count=case['total'],
            next_cursor=None,reason=None if case['state']=='complete' else 'source_coverage_incomplete')
        # Invalid wire is serialized directly so the consumer under test decides.
        wire=json.dumps(value,separators=(',',':'))
        result.append({'name':case['name'],'accepted':case['accepted'],'wire':wire})
    return result
if __name__=='__main__':print(json.dumps(vectors()))
