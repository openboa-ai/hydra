from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_hydra.py"


class HydraContractTests(unittest.TestCase):
    def run_validator(self, path: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(path)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_repository_contract_is_valid(self) -> None:
        result = self.run_validator(ROOT)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_wrong_marketplace_name_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "hydra"
            shutil.copytree(ROOT, fixture, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            marketplace = fixture / ".agents" / "plugins" / "marketplace.json"
            payload = json.loads(marketplace.read_text(encoding="utf-8"))
            payload["name"] = "personal"
            marketplace.write_text(json.dumps(payload), encoding="utf-8")

            result = self.run_validator(fixture)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("openboa-hydra", result.stdout + result.stderr)

    def test_duplicate_managed_markers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "hydra"
            shutil.copytree(ROOT, fixture, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            template = fixture / "plugins" / "openboa-operations" / "skills" / "openboa-operations" / "assets" / "repository-AGENTS.md"
            self.assertTrue(template.exists(), "repository template is missing")
            template.write_text(
                template.read_text(encoding="utf-8")
                + "\n<!-- openboa-operations:managed:start contract=0.1.0 -->\n",
                encoding="utf-8",
            )

            result = self.run_validator(fixture)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("managed marker", result.stdout)

    def test_github_control_plane_is_connector_scoped(self) -> None:
        github_reference = (
            ROOT
            / "plugins"
            / "openboa-operations"
            / "skills"
            / "openboa-operations"
            / "references"
            / "github.md"
        )
        text = github_reference.read_text(encoding="utf-8")

        self.assertIn("Codex GitHub connector is the default control-plane", text)
        self.assertIn("account identity is not authority", text)
        self.assertIn("`gh` CLI", text)
        self.assertIn("governance exception", text)


if __name__ == "__main__":
    unittest.main()
