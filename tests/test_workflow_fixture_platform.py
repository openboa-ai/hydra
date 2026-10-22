"""Mac-style temporary aliases must not become installed host-setting paths."""
from pathlib import Path
import json,os,subprocess,sys,tempfile,unittest

ROOT=Path(__file__).resolve().parents[1]


class WorkflowFixturePlatformTests(unittest.TestCase):
    def test_actual_checkpoint_wire_fixture_uses_a_canonical_temporary_root(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder).resolve(strict=True)
            physical=root/'physical'
            physical.mkdir()
            alias=root/'alias'
            alias.symlink_to(physical,target_is_directory=True)
            env={k:v for k,v in os.environ.items() if not k.startswith(('GH_','GITHUB_','GIT_','PYTHON'))}
            env.update(TMPDIR=str(alias),PYTHONDONTWRITEBYTECODE='1')
            result=subprocess.run([sys.executable,'-I',str(ROOT/'tests/fixtures/control-v3/emit_workflow_progress.py')],
                cwd=ROOT,env=env,capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stderr[-2000:])
            rows=json.loads(result.stdout)
            self.assertEqual(len(rows),134)
            actual=[row for row in rows if row['name']=='actual-checkpoint-producer']
            self.assertEqual(len(actual),2)
            for row in actual:
                value=json.loads(row['wire'])
                self.assertEqual(value['request']['outcome'],'applied')
                self.assertEqual(value['request']['receipt']['kind'],'checkpoint')
