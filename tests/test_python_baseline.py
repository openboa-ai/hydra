"""The package, source entry points and CI share one Python compatibility floor."""

import ast
from pathlib import Path
import re
import subprocess
import sys
import tomllib
import unittest


ROOT = Path(__file__).resolve().parents[1]
FLOOR = (3, 14)


class PythonBaselineTests(unittest.TestCase):
    def test_package_metadata_and_ci_use_the_supported_floor(self):
        metadata = tomllib.loads((ROOT / 'pyproject.toml').read_text())
        self.assertEqual(metadata['project']['requires-python'], '>=3.14')
        workflow = (ROOT / '.github/workflows/ci.yml').read_text()
        matrix = re.findall(r'^        python: (.+)$', workflow, re.MULTILINE)
        self.assertEqual(len(matrix), 1)
        versions = ast.literal_eval(matrix[0])
        self.assertTrue(versions)
        observed = [tuple(map(int, value.split('.'))) for value in versions]
        self.assertTrue(all(version >= FLOOR for version in observed))
        self.assertTrue(any(version[:2] == FLOOR for version in observed))
        self.assertIn('assert sys.version_info >= (3, 14)', workflow)

    def test_old_versions_fail_before_cli_or_mcp_runtime_imports(self):
        for version in [(3, 11, 17), (3, 12, 7), (3, 13, 9)]:
            for module in ['hydra_sdlc.cli', 'hydra_sdlc.mcp']:
                with self.subTest(version=version, module=module):
                    program = f'''
import importlib, sys
sys.path.insert(0, {str(ROOT)!r})
sys.version_info = {version!r}
try:
    importlib.import_module({module!r})
except ImportError as error:
    assert 'Hydra requires Python 3.14 or newer.' in str(error), str(error)
    assert not any(key.startswith('hydra_sdlc.') for key in sys.modules)
    print('rejected-before-runtime')
else:
    raise AssertionError('unsupported interpreter accepted')
'''
                    result = subprocess.run([sys.executable, '-I', '-c', program],
                        cwd='/', capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout.strip(), 'rejected-before-runtime')

    def test_floor_and_future_versions_can_import_the_package(self):
        for version in [(3, 14, 0), (3, 14, 2), (3, 15, 0)]:
            with self.subTest(version=version):
                program = f'''
import sys
sys.path.insert(0, {str(ROOT)!r})
sys.version_info = {version!r}
import hydra_sdlc
print(hydra_sdlc.__version__)
'''
                result = subprocess.run([sys.executable, '-I', '-c', program],
                    cwd='/', capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertRegex(result.stdout.strip(), r'^\d+\.\d+\.\d+$')
