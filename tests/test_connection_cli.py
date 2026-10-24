"""The actual foreground CLI preserves bounded, private connection replies."""
import json
from pathlib import Path
import subprocess
import sys
import unittest
import test_connection_writer as fixtures


class ConnectionCliTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.ConnectionWriterTests();self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)

    def invoke(self, action, body=b''):
        root=Path(__file__).resolve().parents[1]
        code='import sys;sys.path.insert(0,'+repr(str(root))+');from hydra_sdlc.cli import main;raise SystemExit(main())'
        result=subprocess.run([sys.executable,'-I','-B','-c',code,'connection',action,
            '--config',str(self.fx.path)],input=body,capture_output=True,timeout=15)
        self.assertEqual(result.returncode,0,result.stderr[:300])
        self.assertEqual(result.stderr,b'')
        value=json.loads(result.stdout)
        self.assertNotIn(str(self.fx.path),result.stdout.decode())
        return value

    def test_real_cli_status_reports_current_config_without_touching_stores(self):
        before=self.fx.path.read_bytes(),self.fx.state()
        value=self.invoke('status')
        self.assertIsNone(value['request_id'])
        self.assertEqual(value['configured'][0]['repository'],fixtures.ALPHA)
        self.assertEqual((self.fx.path.read_bytes(),self.fx.state()),before)

    def test_real_cli_invalid_utf8_returns_a_typed_rejection_without_diagnostics(self):
        before=self.fx.path.read_bytes(),self.fx.state()
        value=self.invoke('apply',b'\xff')
        self.assertEqual(value['outcome'],'rejected')
        self.assertEqual((self.fx.path.read_bytes(),self.fx.state()),before)

    def test_real_cli_oversized_stdin_is_rejected_without_an_effect(self):
        before=self.fx.path.read_bytes(),self.fx.state()
        value=self.invoke('preview',b' ' * 65537)
        self.assertEqual(value['outcome'],'rejected')
        self.assertEqual((self.fx.path.read_bytes(),self.fx.state()),before)
