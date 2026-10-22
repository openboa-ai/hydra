"""A successful identity response can consume the final provider allowance."""
import subprocess,unittest
from unittest.mock import patch
from hydra_sdlc.projection_read import ProjectionClient
from test_projection_read import ReadFixture
from test_github_projection_read import http

class ExhaustedIdentitySuccessTests(unittest.TestCase):
    def test_successful_identity_with_zero_remaining_holds_repository_gets(self):
        calls=[]
        def run(argv,**kwargs):
            if argv[1:3]==['auth','token']:return subprocess.CompletedProcess(argv,0,'synthetic-credential\n','')
            calls.append(list(argv))
            self.assertEqual(argv[-1],'user','The final identity allowance was followed by another API request')
            return subprocess.CompletedProcess(argv,0,http(200,[('Date','Wed, 21 Oct 2026 00:00:00 GMT'),
                ('X-RateLimit-Remaining','0'),('X-RateLimit-Reset','1792540920')],{'login':'openboa','id':42}),'')
        f=ReadFixture();f.client=ProjectionClient()
        with patch('hydra_sdlc.github.subprocess.run',side_effect=run), \
             patch('hydra_sdlc.github.time.monotonic',return_value=100):
            value=f.read()
        self.assertIsNotNone(f.client._authenticated_fingerprint,'A valid expected identity was discarded')
        self.assertEqual(len(calls),1)
        self.assertEqual({(h['basis'],h['after_seconds']) for h in value['retry_hints']},{('provider',120)})
        self.assertEqual([p['coverage']['reason'] for p in value['projects']],['rate_limited','provider_wait'])
