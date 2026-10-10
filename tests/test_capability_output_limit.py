"""Capability reports are bounded while reading, before EOF or JSON acceptance."""

import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from hydra_sdlc import codex, execution_boundary as boundary


WORKER = r'''
import os, pathlib, sys, time
root, mode, limit = pathlib.Path(sys.argv[1]), sys.argv[2], int(sys.argv[3])
(root / 'worker.pid').write_text(str(os.getpid()))
report = b'{"available":true,"private_fixture":"must not propagate"}\n'
if mode == 'partial':
    os.write(1, report[:5])
    while not (root / 'release').exists():
        time.sleep(.005)
    sys.stdout.buffer.write(report[5:])
else:
    size = limit + (1 if mode == 'overflow_closed' else 0)
    sys.stdout.buffer.write(report + b' ' * (size - len(report)))
sys.stdout.buffer.flush()
if mode == 'overflow_open':
    while True:
        os.write(1, b' ' * 65536)
if mode == 'no_eof':
    while True:
        time.sleep(.005)
'''


@unittest.skipUnless(os.name == 'posix', 'requires actual POSIX probe processes')
class CapabilityOutputLimitTests(unittest.IsolatedAsyncioTestCase):
    async def probe(self, mode, *, cleanup_unknown=False):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        evidence = {'reads': [], 'received': 0, 'eof': False, 'waited': False, 'cleanup': None}
        handles = []

        class ObservedProcess(boundary.OwnedProcess):
            async def start(self, deadline):
                handles.append(self)
                await super().start(deadline)

            @property
            def stdout(self):
                reader = super().stdout

                async def read(n=-1):
                    evidence['reads'].append((n, evidence['received']))
                    if n <= 0:
                        raise AssertionError('Capability collector requested unbounded output')
                    data = await reader.read(n)
                    evidence['received'] += len(data)
                    if data and mode == 'partial':
                        (root / 'release').touch()
                    if not data:
                        evidence['eof'] = True
                    return data

                return SimpleNamespace(read=read)

            async def wait(self):
                evidence['waited'] = True
                return await super().wait()

            async def cleanup(self):
                evidence['cleanup'] = await super().cleanup()
                return False if cleanup_unknown else evidence['cleanup']

        command = [sys.executable, '-I', '-c', WORKER, str(root), mode, str(boundary.MAX_FRAME_BYTES)]
        with patch.object(codex, '_capability_command', return_value=command), \
                patch.object(boundary, 'OwnedProcess', ObservedProcess), \
                patch.object(codex, 'CAPABILITIES_TIMEOUT_SECONDS', 2.0):
            result = await codex.capabilities(str(root))
        self.assertEqual(len(handles), 1)
        self.assertTrue(evidence['cleanup'])
        self.assertIsNotNone(handles[0].process.returncode)
        pid = int((root / 'worker.pid').read_text())
        with self.assertRaises(ProcessLookupError):
            os.kill(pid, 0)
        self.assertTrue(boundary._group_absent(pid))
        self.assertTrue(evidence['reads'])
        for requested, received in evidence['reads']:
            self.assertGreater(requested, 0)
            self.assertLessEqual(requested, min(64 * 1024, boundary.MAX_FRAME_BYTES + 1 - received))
        self.assertLessEqual(evidence['received'], boundary.MAX_FRAME_BYTES + 1)
        self.assertNotIn('must not propagate', str(result))
        return result, evidence

    async def test_partial_document_is_collected_until_actual_eof(self):
        result, evidence = await self.probe('partial')
        self.assertTrue(result['available'])
        self.assertTrue(evidence['eof'])
        self.assertTrue(evidence['waited'])
        self.assertGreaterEqual(len(evidence['reads']), 3)

    async def test_exact_limit_report_requires_one_byte_eof_confirmation(self):
        result, evidence = await self.probe('exact')
        self.assertTrue(result['available'])
        self.assertEqual(evidence['received'], boundary.MAX_FRAME_BYTES)
        self.assertEqual(evidence['reads'][-1], (1, boundary.MAX_FRAME_BYTES))
        self.assertTrue(evidence['eof'])
        self.assertTrue(evidence['waited'])

    async def test_overflow_is_rejected_with_or_without_producer_eof(self):
        for mode in ('overflow_closed', 'overflow_open'):
            with self.subTest(mode=mode):
                result, evidence = await self.probe(mode)
                self.assertFalse(result['available'])
                self.assertEqual(result['error_type'], 'ValueError')
                self.assertEqual(evidence['received'], boundary.MAX_FRAME_BYTES + 1)
                self.assertFalse(evidence['eof'])
                self.assertFalse(evidence['waited'])

    async def test_exact_limit_without_eof_remains_deadline_bounded(self):
        result, evidence = await self.probe('no_eof')
        self.assertFalse(result['available'])
        self.assertEqual(result['error_type'], 'TimeoutError')
        self.assertEqual(evidence['received'], boundary.MAX_FRAME_BYTES)
        self.assertEqual(evidence['reads'][-1], (1, boundary.MAX_FRAME_BYTES))
        self.assertFalse(evidence['eof'])
        self.assertFalse(evidence['waited'])

    async def test_overflow_does_not_hide_unknown_cleanup(self):
        result, evidence = await self.probe('overflow_open', cleanup_unknown=True)
        self.assertFalse(result['available'])
        self.assertEqual(result['error_type'], 'ValueError')
        self.assertEqual(result['cleanup'], 'unknown')
        self.assertEqual(evidence['received'], boundary.MAX_FRAME_BYTES + 1)
        self.assertFalse(evidence['waited'])
