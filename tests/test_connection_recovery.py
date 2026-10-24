"""P17 recovery checks use physical file effects, not request echoes."""
import errno
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from hydra_sdlc import connections
from hydra_sdlc.connections import NativeProjectBinding
import test_connection_writer as fixtures


class ConnectionRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fx=fixtures.ConnectionWriterTests()
        self.fx.setUp();self.addCleanup(self.fx.doCleanups)

    def test_preview_of_an_already_stopped_target_does_not_claim_stop_application(self):
        f=self.fx
        f.write_state(projects={fixtures.ALPHA:'stopped',fixtures.BETA:'running'})
        result=f.call(f.request('update',fixtures.ALPHA),action='preview')
        self.assertEqual(result['outcome'],'preview')
        self.assertFalse(result['stopped_applied'],'Preview must report no applied effects')
        self.assertFalse(result['config_applied'])

    def test_physical_parent_replacement_after_config_write_is_not_an_applied_receipt(self):
        f=self.fx
        folder=f.root/'configuration';folder.mkdir(mode=0o700)
        old=f.path;f.path=folder/old.name;old.rename(f.path);f.write_state()
        request=f.request();real_replace=os.replace;changed=[False]
        def replace(source,destination,**kwargs):
            result=real_replace(source,destination,**kwargs)
            if destination==f.path.name and not changed[0]:
                changed[0]=True
                saved=f.root/'retained-original-parent';folder.rename(saved)
                folder.mkdir(mode=0o700)
                f.path.write_bytes((saved/f.path.name).read_bytes());f.path.chmod(0o600)
            return result
        with patch.object(connections.os,'replace',side_effect=replace):
            result=f.call(request)
        self.assertTrue(changed[0])
        self.assertEqual(result['outcome'],'unknown',result)
        self.assertIsNone(result['finalized'])

    def test_oversized_proposal_is_rejected_before_any_store_effect(self):
        f=self.fx;retained=None
        for count in range(1,120):
            repos=['example/r'+str(n).zfill(3) for n in range(count)]
            raw=(f'repos={json.dumps(repos)}\nhost_alias="fixture"\n'
                f'workspace_root={json.dumps(str(f.root/"work"))}\nlock_path={json.dumps(str(f.lock))}\n'
                'connection_schema=1\n')
            for name in repos:
                raw+=f'[project_connections.{json.dumps(name)}]\ndesired="connected"\nnative_project_id="'+('☕'*256)+'"\n'
            if len(raw.encode())>65536:
                break
            retained=(raw,repos)
        self.assertIsNotNone(retained)
        raw,repos=retained;f.path.write_text(raw)
        f.write_state()
        for index,name in enumerate(repos):
            f.source.ids[name]=1000+index
        request=f.request(native_project_id='😀'*256)
        before=f.path.read_bytes(),f.state()
        provider=lambda *args:NativeProjectBinding(125,'fixture','😀'*256)
        for action in ['preview','apply']:
            with self.subTest(action=action):
                result=f.call(request,action=action,native_project=provider)
                self.assertEqual(result['outcome'],'rejected',result)
                self.assertEqual((f.path.read_bytes(),f.state()),before)

    def test_parent_fsync_failure_after_replace_retains_observed_state_without_retry(self):
        f=self.fx;real_fsync=os.fsync;real_replace=os.replace;failed=[False];config_writes=[]
        def fsync(fd):
            info=os.fstat(fd)
            if (not failed[0] and info.st_ino==f.root.stat().st_ino
                    and fixtures.NEW in f.path.read_text()):
                failed[0]=True
                raise OSError(errno.EIO,'PRIVATE_DISK_DIAGNOSTIC')
            return real_fsync(fd)
        def replace(source,destination,**kwargs):
            if destination==f.path.name:
                config_writes.append(destination)
            return real_replace(source,destination,**kwargs)
        with patch.object(connections.os,'fsync',side_effect=fsync),patch.object(connections.os,'replace',side_effect=replace):
            result=f.call(f.request())
        self.assertTrue(failed[0])
        self.assertEqual(result['outcome'],'unknown',result)
        self.assertTrue(result['config_applied'])
        self.assertTrue(result['stopped_applied'])
        self.assertEqual(len(config_writes),1)
        self.assertNotIn('PRIVATE_DISK_DIAGNOSTIC',json.dumps(result))
