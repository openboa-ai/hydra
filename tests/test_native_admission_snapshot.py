"""P02: a new config grant cannot operate the superseded configuration."""
import importlib.util
import unittest

from test_native_admission_profile import ProfileFixture


@unittest.skipUnless(importlib.util.find_spec('mcp'), 'optional pinned MCP SDK not installed')
class ProfileSnapshotTests(ProfileFixture, unittest.IsolatedAsyncioTestCase):
    async def test_final_grant_from_replaced_semantics_cannot_mutate_old_admission(self):
        from mcp import Client
        replacements = [
            ('host_alias="fixture"', 'host_alias="changed"'),
            ('lock_path="locks/host.lock"', 'lock_path="locks/replaced.lock"'),
            ('repos=["example/alpha","example/beta"]', 'repos=["example/alpha"]'),
            ('repository_ids=[101]', 'repository_ids=[101,202]'),
        ]
        for old, new in replacements:
            with self.subTest(field=old):
                self.install()
                self.control.set_mode('resume', 'example/alpha')
                before = self.payload()
                initial = self.config_path.read_text()
                provider = self.provider()
                calls = []
                def replaced(ctx):
                    calls.append(True)
                    if len(calls) == 2:
                        self.config_path.write_text(initial.replace(old, new))
                    return provider(ctx)
                async with Client(self.server(replaced)) as client:
                    result = await self.call(client, self.request())
                self.assertEqual(len(calls), 2)
                self.assertEqual((result['request']['outcome'], result['request']['reason']),
                                 ('rejected', 'stale_runtime'), result)
                self.assertIsNone(result['request']['receipt'])
                self.assertEqual(self.payload(), before)

    async def test_equivalent_profile_reordering_during_final_read_still_progresses(self):
        from mcp import Client
        self.install('schema_version=1\nenabled=true\nrepository_ids=[101,202]')
        initial = self.config_path.read_text()
        provider = self.provider()
        calls = []
        def reordered(ctx):
            calls.append(True)
            if len(calls) == 2:
                self.config_path.write_text(initial.replace('repository_ids=[101,202]',
                    'repository_ids = [202, 101] # equivalent settings'))
            return provider(ctx)
        async with Client(self.server(reordered)) as client:
            result = await self.call(client, self.request())
        self.assertEqual(len(calls), 2)
        self.assertEqual(result['request']['outcome'], 'applied', result)
        self.assertEqual(self.control.snapshot()['projects']['example/alpha'], 'paused')
