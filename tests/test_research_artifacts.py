from __future__ import annotations

import csv
import subprocess
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_VALIDATOR = ROOT / "scripts" / "validate_research.py"
PACKAGE = ROOT / "research" / "openboa-ai-native-sdlc-v0.1"


class ResearchArtifactTests(unittest.TestCase):
    def test_research_package_is_valid(self) -> None:
        result = subprocess.run(
            [sys.executable, str(RESEARCH_VALIDATOR), str(ROOT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("40 source records", result.stdout)

    def test_ledger_has_required_source_cohorts(self) -> None:
        with (PACKAGE / "sources.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        organizations = {row["organization"] for row in rows}
        self.assertEqual(len(rows), 40)
        self.assertTrue({"OpenAI", "Anthropic", "NVIDIA"} <= organizations)
        self.assertTrue({"Cursor", "Factory", "Replit", "Vercel"} <= organizations)

    def test_public_rename_is_explicitly_deferred(self) -> None:
        draft = (PACKAGE / "draft-model.md").read_text(encoding="utf-8")
        application = (PACKAGE / "application-hydra.md").read_text(encoding="utf-8")
        self.assertIn("No migration is authorized by this draft.", draft)
        self.assertIn("human approval", application.lower())


if __name__ == "__main__":
    unittest.main()
