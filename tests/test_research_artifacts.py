from __future__ import annotations

import csv
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESEARCH_VALIDATOR = ROOT / "scripts" / "validate_research.py"
PACKAGE = ROOT / "research" / "openboa-ai-native-sdlc-v0.1"
REQUIRED_GUIDES = ("lessons.md", "workflow.md", "github.md", "evals.md", "open-questions.md")


class ResearchArtifactTests(unittest.TestCase):
    def run_validator(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(RESEARCH_VALIDATOR), str(root)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_research_package_is_valid(self) -> None:
        result = self.run_validator(ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("40 source records", result.stdout)

    def test_ledger_has_required_source_cohorts(self) -> None:
        with (PACKAGE / "sources.csv").open(newline="", encoding="utf-8") as handle:
            rows = list(csv.DictReader(handle))

        organizations = {row["organization"] for row in rows}
        self.assertEqual(len(rows), 40)
        self.assertTrue({"OpenAI", "Anthropic", "NVIDIA"} <= organizations)
        self.assertTrue({"Cursor", "Factory", "Replit", "Vercel"} <= organizations)

    def test_obsolete_model_artifacts_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "hydra"
            shutil.copytree(ROOT, fixture, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            package = fixture / "research" / "openboa-ai-native-sdlc-v0.1"
            for name in ("lessons.md", "workflow.md", "github.md", "evals.md"):
                (package / name).write_text(f"# {name}\n", encoding="utf-8")
            obsolete = package / "draft-model.md"
            obsolete.write_text("# Obsolete model\n", encoding="utf-8")

            result = self.run_validator(fixture)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("obsolete artifact(s) remain", result.stdout + result.stderr)

    def test_required_guides_cannot_be_blank(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            for name in REQUIRED_GUIDES:
                with self.subTest(name=name):
                    fixture = Path(temp_dir) / name.removesuffix(".md")
                    shutil.copytree(ROOT, fixture, ignore=shutil.ignore_patterns(".git", "__pycache__"))
                    guide = fixture / "research" / "openboa-ai-native-sdlc-v0.1" / name
                    guide.write_text(" \n\t", encoding="utf-8")

                    result = self.run_validator(fixture)

                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(f"required guide is blank: {name}", result.stdout + result.stderr)

    def test_custom_lifecycle_protocol_artifacts_are_rejected(self) -> None:
        custom_artifacts = (
            "delivery-protocol.md",
            "lifecycle-schema.json",
            "research-model.yaml",
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            for name in custom_artifacts:
                with self.subTest(name=name):
                    fixture = Path(temp_dir) / name.replace(".", "-")
                    shutil.copytree(ROOT, fixture, ignore=shutil.ignore_patterns(".git", "__pycache__"))
                    artifact = fixture / "research" / "openboa-ai-native-sdlc-v0.1" / name
                    artifact.write_text("{}\n", encoding="utf-8")

                    result = self.run_validator(fixture)

                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("custom lifecycle protocol/schema artifact(s)", result.stdout + result.stderr)
                    self.assertIn(name, result.stdout + result.stderr)

    def test_normal_supplemental_document_is_allowed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "hydra"
            shutil.copytree(ROOT, fixture, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            notes = fixture / "research" / "openboa-ai-native-sdlc-v0.1" / "notes.md"
            notes.write_text("# Review notes\n", encoding="utf-8")

            result = self.run_validator(fixture)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
