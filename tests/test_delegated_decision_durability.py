"""External POSTs require durable namespace and owner reservation publication."""
import copy
import os
import stat
import unittest
import uuid
from unittest.mock import patch

from hydra_sdlc.github import GitHubError
from delegated_decision_fixture import InstallationFixture


def same_inode(descriptor, path):
    try:
        opened, named = os.fstat(descriptor), path.stat()
    except FileNotFoundError:
        return False
    return (opened.st_dev, opened.st_ino) == (named.st_dev, named.st_ino)


class DelegatedDurabilityTests(InstallationFixture, unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.fresh_installation()

    def fresh_installation(self):
        self.setup_installation()
        self.write_profile(True)
        self.make_server(new_profile=True)
        self.lock = self.controller.lock_path
        self.assertTrue(self.lock.parent.is_dir())
        self.assertFalse(self.lock.exists(), 'This fixture must exercise the first coordinator pathname')
        # The operating-control fixture already prepared its parent. Explicitly
        # establish that directory before fault injection; only host.lock is new.
        descriptor = os.open(self.lock.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    async def test_new_coordinator_name_is_durable_before_first_external_post(self):
        events = []
        fsync = os.fsync
        def observe_sync(descriptor):
            result = fsync(descriptor)
            if stat.S_ISDIR(os.fstat(descriptor).st_mode) and same_inode(descriptor, self.lock.parent):
                events.append(('directory_fsynced', self.lock.exists()))
            return result
        self.transport.post_behavior = lambda kind, body: events.append(('post', kind))
        with patch('os.fsync', side_effect=observe_sync):
            result = self.reply(await self.invoke())
        self.assertEqual(result['request']['outcome'], 'applied', result)
        self.assertEqual([kind for kind, _ in self.transport.effects], ['context', 'receipt'])
        first_post = next(index for index, event in enumerate(events) if event[0] == 'post')
        self.assertIn(('directory_fsynced', True), events[:first_post],
            'File fsync alone does not durably publish the new host.lock directory entry before POST')
        self.assertEqual(self.lock.read_bytes(), b'')

    async def test_new_coordinator_directory_fsync_failure_prevents_post(self):
        fsync, failed = os.fsync, []
        def fail_directory(descriptor):
            if stat.S_ISDIR(os.fstat(descriptor).st_mode) and same_inode(descriptor, self.lock.parent):
                failed.append(True)
                raise OSError('Fixture coordinator namespace persistence failed')
            return fsync(descriptor)
        with patch('os.fsync', side_effect=fail_directory):
            for invocation in range(2):
                self.make_server(new_profile=True)
                result = await self.invoke()
                self.assertGreaterEqual(len(failed), invocation + 1,
                    'An existing name after failed directory fsync is not evidence of durable creation')
                self.assertEqual(self.transport.effects, [])
                if not result.is_error:
                    self.assertNotEqual(self.reply(result)['request']['outcome'], 'applied')

    async def assert_bounded_recovery(self, kind, maximum):
        """Fresh boots do not recover a spent budget or create a new intent."""
        before = sum(name == kind for name, _ in self.transport.effects)
        def lose(name, body):
            if name == kind:
                raise GitHubError('Fixture unknown append result', uncertain=True)
        self.transport.post_behavior = lose
        for number in range(5):
            with patch('hydra_sdlc.coordinator._boot_identity',
                       return_value=str(uuid.UUID(int=number + 500, version=4))):
                self.make_server(new_profile=True)
                self.reply(await self.invoke())
            self.assertLessEqual(sum(name == kind for name, _ in self.transport.effects) - before, maximum)
            self.assertTrue(self.lock.read_bytes())
        attempted = [payload['body'] for name, payload in self.transport.effects if name == kind]
        self.assertLessEqual(len(set(attempted)), 1)
        self.assertFalse(any(name == 'progress' for name, _ in self.transport.effects))

    async def test_each_counter_reservation_fsync_failure_has_no_corresponding_post(self):
        for kind in ('context', 'receipt'):
            with self.subTest(reservation=kind):
                self.fresh_installation()
                fsync, last_durable, failed = os.fsync, [None], []
                def fail_reservation(descriptor):
                    if same_inode(descriptor, self.lock):
                        raw = os.pread(descriptor, 4096, 0)
                        prior = last_durable[0]
                        ready = not self.transport.effects if kind == 'context' else (
                            [name for name, _ in self.transport.effects] == ['context'])
                        if raw and prior is not None and raw != prior and ready and not failed:
                            failed.append(copy.deepcopy(raw))
                            raise OSError('Fixture reservation fsync failed')
                        result = fsync(descriptor)
                        if raw:
                            last_durable[0] = raw
                        return result
                    return fsync(descriptor)
                with patch('os.fsync', side_effect=fail_reservation):
                    result = await self.invoke()
                self.assertEqual(len(failed), 1, 'The failure must follow an already durable initial owner')
                self.assertEqual(sum(name == kind for name, _ in self.transport.effects), 0)
                self.assertTrue(self.lock.read_bytes(), 'Unconfirmed persistence must keep conservative ownership')
                if not result.is_error:
                    self.assertNotEqual(self.reply(result)['request']['outcome'], 'applied')
                # The reserved increment remains visible to fresh controllers.
                # Its failed fsync is not permission to reset it to zero.
                await self.assert_bounded_recovery(kind, 2)

    async def test_partial_reservation_write_then_failure_never_dispatches_that_post(self):
        for kind in ('context', 'receipt'):
            with self.subTest(reservation=kind):
                self.fresh_installation()
                fsync, pwrite = os.fsync, os.pwrite
                last_durable, partial, failed = [None], [], []
                def observe_sync(descriptor):
                    result = fsync(descriptor)
                    if same_inode(descriptor, self.lock):
                        raw = os.pread(descriptor, 4096, 0)
                        if raw:
                            last_durable[0] = raw
                    return result
                def interrupt_reservation(descriptor, data, offset):
                    if same_inode(descriptor, self.lock):
                        if partial and not failed:
                            failed.append(True)
                            raise OSError('Fixture continuation of partial write failed')
                        ready = not self.transport.effects if kind == 'context' else (
                            [name for name, _ in self.transport.effects] == ['context'])
                        if (not partial and ready and offset == 0 and last_durable[0] is not None
                                and data != last_durable[0] and len(data) > 1):
                            size = len(data) - 1
                            written = pwrite(descriptor, data[:size], offset)
                            partial.append(written)
                            return written
                    return pwrite(descriptor, data, offset)
                with patch('os.fsync', side_effect=observe_sync), \
                        patch('os.pwrite', side_effect=interrupt_reservation):
                    result = await self.invoke()
                self.assertEqual(len(partial), 1)
                self.assertGreater(partial[0], 0, 'A positive partial physical write must actually occur')
                self.assertEqual(len(failed), 1)
                self.assertEqual(sum(name == kind for name, _ in self.transport.effects), 0)
                self.assertTrue(self.lock.read_bytes())
                if not result.is_error:
                    self.assertNotEqual(self.reply(result)['request']['outcome'], 'applied')
                # A torn owner may remain held forever; if its exact complete
                # bytes are recoverable, lifetime retries must still be bounded.
                await self.assert_bounded_recovery(kind, 3)

    async def test_short_positive_writes_complete_and_fsync_before_normal_publication(self):
        pwrite, fsync = os.pwrite, os.fsync
        writes, durable, at_post = [], [None], []
        def short_write(descriptor, data, offset):
            if same_inode(descriptor, self.lock) and len(data) > 7:
                written = pwrite(descriptor, data[:7], offset)
                writes.append((offset, written))
                return written
            return pwrite(descriptor, data, offset)
        def observe_sync(descriptor):
            result = fsync(descriptor)
            if same_inode(descriptor, self.lock):
                durable[0] = os.pread(descriptor, 4096, 0)
            return result
        self.transport.post_behavior = lambda kind, body: at_post.append(
            (kind, self.lock.read_bytes(), durable[0]))
        with patch('os.pwrite', side_effect=short_write), patch('os.fsync', side_effect=observe_sync):
            result = self.reply(await self.invoke())
        self.assertEqual(result['request']['outcome'], 'applied', result)
        self.assertGreater(len(writes), 3)
        self.assertEqual([kind for kind, _, _ in at_post], ['context', 'receipt'])
        for kind, visible, synced in at_post:
            self.assertTrue(visible, kind)
            self.assertEqual(visible, synced, 'The full current reservation must be fsynced before ' + kind)
        self.assertEqual(self.lock.read_bytes(), b'')
