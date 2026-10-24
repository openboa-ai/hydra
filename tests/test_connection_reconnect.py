"""P17 explicit reconnection preserves stopped admission and prior responsibility."""
import unittest
from hydra_sdlc.control import load_host_config
import test_connection_writer as fixtures


class ReconnectionTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.ConnectionWriterTests();self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)

    def test_pending_disconnect_can_reconnect_only_after_current_scoped_closure(self):
        f=self.fx
        f.write_config(pending=True);f.write_state(projects={fixtures.ALPHA:'stopped',fixtures.BETA:'running'})
        request=f.request('connect',fixtures.ALPHA)
        result=f.call(request)
        self.assertEqual(result['outcome'],'waiting')
        self.assertEqual(load_host_config(f.path)['project_connections'][fixtures.ALPHA]['desired'],'disconnect_requested')
        result=f.call(request,quiescence=f.closure)
        self.assertEqual(result['outcome'],'applied',result)
        self.assertEqual(load_host_config(f.path)['project_connections'][fixtures.ALPHA]['desired'],'connected')
        self.assertEqual(f.state()['projects'][fixtures.ALPHA],'stopped')
        self.assertEqual(f.state()['projects'][fixtures.BETA],'running')

    def test_removed_scope_with_retained_override_requires_closure_before_reuse(self):
        f=self.fx
        f.write_state(projects={fixtures.ALPHA:'running',fixtures.BETA:'running',fixtures.NEW:'stopped'})
        request=f.request()
        result=f.call(request)
        self.assertEqual(result['outcome'],'waiting')
        self.assertNotIn(fixtures.NEW,load_host_config(f.path)['repos'])
        result=f.call(request,quiescence=f.closure)
        self.assertEqual(result['outcome'],'applied',result)
        self.assertIn(fixtures.NEW,load_host_config(f.path)['repos'])
        self.assertEqual(f.state()['projects'][fixtures.NEW],'stopped')

    def test_duplicate_connected_scope_does_not_stop_or_rewrite_a_running_project(self):
        f=self.fx
        before=f.path.read_bytes(),f.state()
        result=f.call(f.request('connect',fixtures.ALPHA),quiescence=f.closure)
        self.assertEqual(result['outcome'],'rejected')
        self.assertEqual((f.path.read_bytes(),f.state()),before)
