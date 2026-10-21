"""Qualified view claims and independent membership-preserving bounds."""
from pathlib import Path
import copy,importlib.util,json,unittest
from hydra_sdlc import projection as p
from hydra_sdlc.projection_read import _bounded,_prune
from test_projection_read import ReadFixture,issue
FOLDER=Path(__file__).resolve().parent/'fixtures/control-v3'
spec=importlib.util.spec_from_file_location('qualified_vectors',FOLDER/'emit_qualified.py')
vectors=importlib.util.module_from_spec(spec);spec.loader.exec_module(vectors)
def membership_frames():
    rows={('example/alpha','open',False):[issue(7)],('example/beta','open',False):[issue(4)]}
    remote=ReadFixture(rows).read()
    local=ReadFixture(rows).read(refresh=False,admission_snapshot={'revision':8,'global_mode':'running',
                                  'projects':{'example/alpha':'paused','example/beta':'stopped'}})
    detail=ReadFixture(rows).read(repository='example/alpha')
    return remote,local,detail
def oversized_queries(*,relation_only=False):
    frame=copy.deepcopy(json.loads((FOLDER/'inputs.json').read_text())['frame'])
    frame['page']={'state':'complete','scope':'registered-projects;overview','returned_count':2,'total_count':2,'next_cursor':None,'reason':None}
    for project in frame['projects']:
        count=len(project['work_refs']);project['coverage']={'state':'complete','scope':project['coverage']['scope'],
            'returned_count':count,'total_count':count,'next_cursor':None,'reason':None}
    if relation_only:
        observed=next(o for o in frame['observations'] if o['resource']['kind']=='issue')
        frame['relations']=[{'from':copy.deepcopy(observed['resource']),'to':{'source':'github','kind':'issue','id':'101:1'},
                            'kind':'parent','evidence':[p.evidence_of(observed)]}]
        frame['work']=[]
        for project in frame['projects']:project['work_refs']=[];project['coverage'].update(returned_count=0,total_count=0)
    seed=next(o for o in frame['observations'] if o['resource']['kind']=='repository')
    for n in range(400):
        observed=copy.deepcopy(seed);observed['key']='github:query:fixture:'+str(n)
        observed['value']['contract_ref']={'path':'p'*512,'revision':None}
        observed['value']['url']='https://github.com/example/alpha?'+('q'*2000)
        frame['observations'].append(observed)
    return frame
class QualifiedFactTests(unittest.TestCase):
    def test_shared_claim_context_and_receipt_oracles(self):
        rows=list(vectors.cases());self.assertEqual(len(rows),431)
        for row in rows:
            for profile,key in [('projection','frame'),('standard','reply')]:
                with self.subTest(case=row['name'],profile=profile):
                    call=p.encode if profile=='projection' else p.standard_reply
                    if row['accepted_'+profile]:call(row[key])
                    else:
                        with self.assertRaises(p.ProjectionError):call(row[key])
    def test_optional_query_pruning_preserves_complete_membership(self):
        frame=oversized_queries();p.validate_frame(frame)
        self.assertGreater(len(p.canonical(frame).encode()),p.MAX_BYTES)
        value=_bounded(frame)
        self.assertEqual(value['projects'],frame['projects']);self.assertEqual(value['work'],frame['work'])
        self.assertEqual(value['page'],frame['page'],'Optional query eviction changed membership coverage')
        self.assertFalse(any(o['key'].startswith('github:query:') for o in value['observations']))
        p.encode(value)
    def test_relation_source_survives_optional_provenance_pruning(self):
        frame=oversized_queries(relation_only=True);p.validate_frame(frame)
        value=_bounded(frame)
        expected={e['observation_key'] for edge in frame['relations'] for e in edge['evidence']}
        self.assertTrue(expected<={o['key'] for o in value['observations']},'Pruning erased the retained relation source')
        self.assertEqual(value['relations'],frame['relations']);p.encode(value)
    def test_actual_membership_omission_remains_partial(self):
        frame=oversized_queries();value=_prune(frame,0,len(frame['projects']),query_count=0)
        self.assertEqual(value['work'],[]);self.assertEqual(value['page']['state'],'partial')
        self.assertEqual(value['page']['reason'],'response_limit')
    def test_optional_pruning_preserves_membership_refs_without_expanded_work(self):
        frame=oversized_queries();frame['work']=[];p.validate_frame(frame)
        value=_bounded(frame)
        self.assertEqual(value['projects'],frame['projects'],'Query eviction discarded known membership refs')
        self.assertEqual(value['page'],frame['page'])
        self.assertTrue(any(o['resource']['kind']=='issue' and o['resource']['id']=='101:7' for o in value['observations']))
        p.encode(value)
    def test_actual_reader_distinguishes_overview_and_repository_scope(self):
        remote,local,detail=membership_frames()
        self.assertEqual(remote['page']['state'],'complete');self.assertEqual(local['page']['state'],'partial')
        self.assertEqual(detail['page']['state'],'complete')
        self.assertNotEqual(remote['page']['scope'],detail['page']['scope'])
        self.assertFalse(any(o['resource']['source']=='github' and o['availability']=='current' for o in local['observations']))
if __name__=='__main__':unittest.main()
