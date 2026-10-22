"""Every declared CP fixture reference follows the actual maintained contract."""
from pathlib import Path
import hashlib
import json
import re
import unittest


class ProjectionFixtureReferenceTests(unittest.TestCase):
    def test_all_declared_contract_references_match_the_current_document(self):
        root = Path(__file__).resolve().parents[1]
        name = 'docs/engineering/mvp/contracts/control-plane.md'
        source = (root / name).read_bytes()
        revision = int(re.search(rb'Design contract, revision ([0-9]+),', source)[1])
        digest = hashlib.sha256(source).hexdigest()
        found = set()
        for path in sorted((root / 'tests/fixtures/control-v3').glob('*.json')):
            data = json.loads(path.read_text())
            ref = data.get('contract')
            if not isinstance(ref, dict) or ref.get('path') != name:
                continue
            found.add(path.name)
            if 'revision' in ref:
                with self.subTest(fixture=path.name, field='revision'):
                    self.assertEqual(ref['revision'], revision)
            with self.subTest(fixture=path.name, field='sha256'):
                self.assertEqual(ref.get('sha256'), digest)
        self.assertTrue({'qualified-command-sources.json', 'workflow-source-receipts.json',
            'qualified-facts.json', 'inputs.json', 'receipt-states.json',
            'cleanup-receipts.json'}.issubset(found))
