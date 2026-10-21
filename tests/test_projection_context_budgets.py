"""Independent read-context, authentication-budget and current-result regressions."""
import copy,json,subprocess,unittest
from collections import Counter
from unittest.mock import patch
from urllib.parse import urlsplit
from hydra_sdlc import projection as p
from hydra_sdlc.control_commands import _observation,_reply
from hydra_sdlc.projection_read import ProjectionClient,_bounded
from test_control_projection import EPOCH
from test_github_projection_read import http
from test_projection_read import ReadFixture

def uid(n):return '00000000-0000-4000-8000-'+format(n,'012x')

def request_frames():
    frames,replies=[],[]
    for index,(revision,mode,result) in enumerate(((7,'running',False),(8,'paused',True),(8,'paused',False),(9,'running',True))):
        snapshot={'revision':revision,'global_mode':'paused','projects':{'example/alpha':mode}}
        frame=ReadFixture().read(cfg={'repos':['example/alpha']},admission_snapshot=snapshot)
        frame['request_id']=uid(100+index)
        if result:
            command={'request_id':uid(1000+index),'action':'admission_set','target':{'kind':'repository','repository_id':101}}
            observed=_observation(command,frame['runtime'],snapshot,'example/alpha','readback',frame['assembled_at'])
            reply=p.standard_reply(_reply(command,frame['runtime'],EPOCH,'applied',None,observation=observed))
            frame['observations'].extend(copy.deepcopy(reply['observations']))
            frame['request']=copy.deepcopy(reply['request']);replies.append(reply)
        frames.append(json.loads(p.encode(frame)))
    return {'frames':frames,'replies':replies}

class NativeHTTP:
    def __init__(self):self.calls=[];self.token='synthetic-context-a';self.rename=False;self.denied=False;self.reused=False
    def run(self,argv,**kwargs):
        if argv[1:3]==['auth','token']:
            return subprocess.CompletedProcess(argv,0,self.token+'\n','')
        token=kwargs['env']['GH_TOKEN']
        if argv[-1]=='user':
            self.calls.append((token,'GET','/user'))
            return subprocess.CompletedProcess(argv,0,json.dumps({'login':'openboa','id':42}),'')
        assert argv[1:3]==['api','--hostname'] and '--include' in argv
        method=argv[argv.index('--method')+1];path='/'+argv[argv.index('-H')+2]
        assert method=='GET' and kwargs['input'] is None,'A projection issued an effect'
        self.calls.append((token,method,path));parts=urlsplit(path).path.strip('/').split('/')
        name='/'.join(parts[1:3]);status=403 if self.denied else 200
        if len(parts)==3:
            identifier={'example/alpha':101,'example/beta':102}.get(name)
            if identifier is None:identifier=10000+int(parts[-1][1:])
            value={'id':202 if self.reused else identifier,'full_name':'example/renamed' if self.rename else name}
        else:value=[]
        return subprocess.CompletedProcess(argv,0,http(status,[],value),'' if status==200 else 'gh: denied (HTTP 403)')

class ProjectionContextBudgetTests(unittest.TestCase):
    def test_maximum_allowlist_respects_the_accepted_cap_and_completes_first_membership(self):
        fixture=ReadFixture();fixture.client=ProjectionClient();transport=NativeHTTP();observed=[]
        def capture(frame):
            observed.append([(row['repository_ref']['id'],row['coverage']['state']) for row in frame['projects']])
            return _bounded(frame)
        with patch('hydra_sdlc.github.subprocess.run',side_effect=transport.run), \
             patch('hydra_sdlc.github.time.monotonic',return_value=100), \
             patch('hydra_sdlc.projection_read._bounded',side_effect=capture):
            frame=fixture.read(cfg={'repos':['example/p'+str(n) for n in range(1024)]})
        self.assertLessEqual(len(transport.calls),4096,'Authentication exceeded the accepted aggregate provider cap')
        self.assertEqual(sum(path=='/user' for _,_,path in transport.calls),1)
        self.assertEqual(observed[0][0],('10000','complete'),'The initial authentication starved the first repository')
        self.assertEqual({state for _,state in observed[0]},{'complete'})
        self.assertLessEqual(len(p.encode(frame)),p.MAX_BYTES)
        self.assertEqual(frame['page']['state'],'partial');self.assertIsNotNone(frame['page']['next_cursor'])

    def test_outer_caller_request_and_time_caps_still_bound_authenticated_reads(self):
        for cap,seconds in ((4,45),(8,45),(20,0)):
            with self.subTest(cap=cap,seconds=seconds):
                fixture=ReadFixture();fixture.client=ProjectionClient();transport=NativeHTTP()
                with patch('hydra_sdlc.github.subprocess.run',side_effect=transport.run), \
                     patch('hydra_sdlc.github.time.monotonic',return_value=100), \
                     fixture.client.read_budget(seconds=seconds,requests=cap):
                    frame=fixture.read()
                self.assertLessEqual(len(transport.calls),cap)
                self.assertEqual(sum(path=='/user' for _,_,path in transport.calls),int(seconds>0))
                self.assertEqual(frame['page']['state'],'partial')
                self.assertTrue(any(row['coverage']['state']!='complete' for row in frame['projects']))
                if seconds==0:self.assertEqual(transport.calls,[])
                p.encode(frame)

    def test_rotated_credential_freshly_proves_rename_and_denial_cannot_reuse_identity_as_access(self):
        fixture=ReadFixture();fixture.client=ProjectionClient();transport=NativeHTTP()
        with patch('hydra_sdlc.github.subprocess.run',side_effect=transport.run):
            first=fixture.read(cfg={'repos':['example/alpha']})
            self.assertEqual(first['projects'][0]['repository_ref']['id'],'101')
            transport.token='synthetic-context-b';transport.rename=True;transport.calls=[]
            renamed=fixture.read(cfg={'repos':['example/alpha']},repository_bindings={'example/alpha':101})
            self.assertEqual(renamed['projects'][0]['coverage']['state'],'complete')
            repository=next(o for o in renamed['observations'] if o['resource']['kind']=='repository' and o['value'])
            self.assertEqual(repository['value']['full_name'],'example/renamed')
            self.assertEqual(len(transport.calls),5)
            self.assertEqual(transport.calls[0],('synthetic-context-b','GET','/user'))
            self.assertTrue(all(token=='synthetic-context-b' for token,_,_ in transport.calls))
            self.assertEqual(transport.calls[1][2],'/repos/example/alpha')
            self.assertTrue(all(urlsplit(path).path=='/repos/example/renamed/issues' for _,_,path in transport.calls[2:]))
            for denied,reused in ((True,False),(False,True)):
                transport.token='synthetic-context-'+str(denied);transport.denied=denied;transport.reused=reused
                transport.rename=False;transport.calls=[]
                frame=fixture.read(cfg={'repos':['example/alpha']},repository_bindings={'example/alpha':101})
                self.assertEqual(frame['projects'][0]['coverage']['state'],'partial')
                self.assertEqual(len(transport.calls),2,'Denied or reused identity reached issue reads')
                self.assertFalse(any(o['resource']['kind']=='repository' and o['value'] for o in frame['observations']))
                self.assertEqual(frame['projects'][0]['admission']['value'],'paused')
                self.assertIsNone(frame['projects'][0]['execution']['value']);p.encode(frame)

    def test_result_sequence_uses_actual_reply_producer_and_encoder(self):
        value=request_frames();self.assertEqual([f['request'] is not None for f in value['frames']],[False,True,False,True])
        self.assertNotEqual(value['replies'][0]['request']['request_id'],value['replies'][1]['request']['request_id'])
        for frame in value['frames']:p.encode(frame)
        for reply in value['replies']:p.standard_reply(reply)

if __name__=='__main__':unittest.main()
