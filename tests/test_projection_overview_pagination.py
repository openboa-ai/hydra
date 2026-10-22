"""The accepted HTTP cap bounds each slice without dropping registered projects."""
import unittest
from unittest.mock import patch
from hydra_sdlc import projection as p
from hydra_sdlc.projection_read import ProjectionClient,_bounded
from test_projection_context_budgets import NativeHTTP
from test_projection_read import ReadFixture

class OverviewPaginationTests(unittest.TestCase):
    def test_all_supported_repositories_are_reachable_through_actual_bounded_cursors(self):
        repos=['example/p'+str(n) for n in range(1024)]
        expected={str(10000+n) for n in range(1024)};seen=set();cursors=set();cursor=None;pages=0
        for _ in range(16):
            fixture=ReadFixture();fixture.client=ProjectionClient();transport=NativeHTTP();collected=[]
            def capture(frame):
                collected.append([(row['repository_ref']['id'],row['coverage']['state']) for row in frame['projects']])
                return _bounded(frame)
            with patch('hydra_sdlc.github.subprocess.run',side_effect=transport.run), \
                 patch('hydra_sdlc.github.time.monotonic',return_value=100), \
                 patch('hydra_sdlc.projection_read._bounded',side_effect=capture):
                frame=fixture.read(cfg={'repos':repos},cursor=cursor)
            pages+=1
            self.assertLessEqual(len(transport.calls),4096,'One cold page exceeded the accepted request cap')
            self.assertEqual(sum(path=='/user' for _,_,path in transport.calls),1)
            self.assertEqual(len(transport.calls),1+4*len(collected[0]))
            self.assertEqual({state for _,state in collected[0]},{'complete'},'A repository share omitted a required query')
            self.assertLessEqual(len(p.encode(frame)),p.MAX_BYTES)
            returned={row['repository_ref']['id'] for row in frame['projects']}
            self.assertTrue(returned);self.assertFalse(seen & returned,'An overview cursor repeated an already returned project')
            self.assertEqual({row['coverage']['state'] for row in frame['projects']},{'complete'})
            seen.update(returned);cursor=frame['page']['next_cursor']
            if cursor is None:
                self.assertEqual(frame['page']['state'],'complete');break
            self.assertEqual(frame['page']['state'],'partial');self.assertNotIn(cursor,cursors);cursors.add(cursor)
        else:self.fail('Bounded overview pagination did not terminate')
        self.assertGreater(pages,1);self.assertEqual(seen,expected,'Pagination reduced the supported repository set')
if __name__=='__main__':unittest.main()
