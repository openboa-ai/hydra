"""Real transport clocks and authentication metadata determine usable read facts."""
import json,subprocess,unittest
from unittest.mock import patch
from hydra_sdlc import projection as wire
from hydra_sdlc.projection_read import ProjectionClient
from test_projection_read import ReadFixture
from test_projection_context_budgets import NativeHTTP
from test_github_projection_read import http

class TimedHTTP(NativeHTTP):
    def __init__(self,clock,slow_first=False):
        super().__init__();self.clock=clock;self.slow_first=slow_first
    def run(self,argv,**kwargs):
        duration=0.05 if argv[1:3]==['auth','token'] else 0.2
        if self.slow_first and '--method' in argv and '-H' in argv and argv[argv.index('-H')+2]=='repos/example/p0':duration=60
        limit=kwargs['timeout']
        if duration>limit:
            self.clock[0]+=limit
            raise subprocess.TimeoutExpired(argv,limit)
        self.clock[0]+=duration
        return super().run(argv,**kwargs)

class SourceBudgetAndIdentityTests(unittest.TestCase):
    def page(self,repos,*,cursor=None,slow_first=False):
        now=[100.0];transport=TimedHTTP(now,slow_first);f=ReadFixture();f.client=ProjectionClient()
        with patch('hydra_sdlc.github.subprocess.run',side_effect=transport.run), \
             patch('hydra_sdlc.github.time.monotonic',side_effect=lambda:now[0]):
            value=f.read(cfg={'repos':repos},cursor=cursor)
        self.assertLessEqual(now[0]-100,45.000001)
        self.assertLessEqual(len(transport.calls),4096)
        self.assertLessEqual(len(wire.encode(value)),wire.MAX_BYTES)
        return value,transport

    def test_supported_overview_with_realistic_call_latency_produces_current_sources(self):
        repos=['example/p'+str(n) for n in range(1024)]
        first,_=self.page(repos)
        self.assertTrue(any(row['coverage']['state']=='complete' for row in first['projects']),
            'A healthy network produced no usable repository facts')
        self.assertEqual(first['projects'][0]['repository_ref']['id'],'10000')
        self.assertIsNotNone(first['page']['next_cursor'])
        second,_=self.page(repos,cursor=first['page']['next_cursor'])
        self.assertEqual(second['projects'][0]['repository_ref']['id'],str(10000+len(first['projects'])),
            'The deadline cursor skipped the unattempted repository prefix')
        first_ids={p['repository_ref']['id'] for p in first['projects']}
        self.assertFalse(first_ids & {p['repository_ref']['id'] for p in second['projects']})

    def test_one_slow_source_preserves_a_cursor_to_the_first_unattempted_repository(self):
        repos=['example/p'+str(n) for n in range(1024)]
        first,_=self.page(repos,slow_first=True)
        self.assertEqual(len(first['projects']),1,'A deadline manufactured attempts for untouched repositories')
        self.assertNotEqual(first['projects'][0]['coverage']['state'],'complete')
        self.assertIsNotNone(first['page']['next_cursor'])
        second,_=self.page(repos,cursor=first['page']['next_cursor'])
        self.assertEqual(second['projects'][0]['repository_ref']['id'],'10001')
        self.assertEqual(second['projects'][0]['coverage']['state'],'complete')

    def test_identity_probe_preserves_primary_secondary_zero_and_access_denial(self):
        cases=[('primary',403,[('Date','Wed, 21 Oct 2026 00:00:00 GMT'),('X-RateLimit-Remaining','0'),('X-RateLimit-Reset','1792540920')],120),
            ('secondary',403,[('Retry-After','120')],120),('zero',429,[('Retry-After','0')],0),('denied',403,[],None)]
        for name,status,headers,wait in cases:
            with self.subTest(case=name):
                calls=[]
                message=('Resource not accessible' if name=='denied' else 'secondary rate limit' if name=='secondary' else 'API rate limit exceeded')+' SYNTHETIC_PRIVATE_IDENTITY_CANARY'
                def run(argv,**kwargs):
                    if argv[1:3]==['auth','token']:return subprocess.CompletedProcess(argv,0,'synthetic-credential\n','')
                    calls.append(list(argv));self.assertEqual(argv[-1],'user','A denied identity reached a repository request')
                    body=http(status,headers,{'message':message})
                    if kwargs.get('check'):raise subprocess.CalledProcessError(1,argv,output=body,stderr=f'gh: unavailable (HTTP {status})')
                    return subprocess.CompletedProcess(argv,1,body,f'gh: unavailable (HTTP {status})')
                fixture=ReadFixture();fixture.client=ProjectionClient()
                with patch('hydra_sdlc.github.subprocess.run',side_effect=run), \
                     patch('hydra_sdlc.github.time.monotonic',return_value=100):
                    frame=fixture.read()
                self.assertIsNone(fixture.client._authenticated_fingerprint)
                self.assertNotIn('SYNTHETIC_PRIVATE_IDENTITY_CANARY',wire.encode(frame).decode())
                if wait is None:
                    self.assertEqual(frame['retry_hints'],[])
                    self.assertEqual({p['coverage']['reason'] for p in frame['projects']},{'access_denied'})
                else:
                    self.assertTrue(frame['retry_hints'],'The identity quota did not reach the read policy')
                    self.assertEqual({(h['basis'],h['after_seconds']) for h in frame['retry_hints']},{('provider',wait)})
                    if wait>0:self.assertEqual(len(calls),1,'A held identity was retried during provider wait')
                self.assertTrue(all('--include' in args for args in calls),'Identity metadata was discarded before parsing')
