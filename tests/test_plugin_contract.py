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
PLUGIN_NAME = "openboa-ai-native-sdlc"


class PluginContractTests(unittest.TestCase):
    def run_validator(self, root: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(root)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def copy_fixture(self, parent: Path) -> Path:
        fixture = parent / "hydra"
        shutil.copytree(
            ROOT,
            fixture,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"),
        )
        return fixture

    def test_repository_contract_is_valid(self) -> None:
        result = self.run_validator(ROOT)
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_marketplace_and_manifest_share_one_identity(self) -> None:
        marketplace = json.loads(
            (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
        )
        manifest = json.loads(
            (ROOT / "plugins" / PLUGIN_NAME / ".codex-plugin" / "plugin.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual("openboa-hydra", marketplace["name"])
        self.assertEqual([PLUGIN_NAME], [item["name"] for item in marketplace["plugins"]])
        self.assertEqual(PLUGIN_NAME, manifest["name"])
        self.assertEqual("./skills/", manifest["skills"])
        for forbidden in ("hooks", "mcpServers", "apps"):
            self.assertNotIn(forbidden, manifest)

    def test_installed_skill_contains_canonical_research(self) -> None:
        research = (
            ROOT
            / "plugins"
            / PLUGIN_NAME
            / "skills"
            / PLUGIN_NAME
            / "references"
            / "research"
        )
        for name in ("README.md", "source-register.csv", "evidence-to-design.md"):
            with self.subTest(name=name):
                self.assertTrue((research / name).is_file())

    def test_wrong_marketplace_name_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.copy_fixture(Path(temp_dir))
            path = fixture / ".agents" / "plugins" / "marketplace.json"
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["name"] = "personal"
            path.write_text(json.dumps(payload), encoding="utf-8")
            result = self.run_validator(fixture)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("openboa-hydra", result.stdout)

    def test_missing_canonical_reference_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.copy_fixture(Path(temp_dir))
            target = (
                fixture
                / "plugins"
                / PLUGIN_NAME
                / "skills"
                / PLUGIN_NAME
                / "references"
                / "doctrine.md"
            )
            target.unlink()
            result = self.run_validator(fixture)
        self.assertNotEqual(0, result.returncode)
        self.assertIn("doctrine.md", result.stdout)

    def test_required_check_name_remains_compatible(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(encoding="utf-8")
        self.assertIn("name: openboa-governance", workflow)
        self.assertIn("permissions:\n  contents: read", workflow)
        self.assertNotIn("pull_request_target", workflow)

    def test_shadow_readiness_is_read_only_and_not_a_gate(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "openboa-ready-shadow.yml").read_text(encoding="utf-8")
        self.assertIn("contents: read", workflow)
        self.assertIn("pull-requests: read", workflow)
        self.assertIn("checks: read", workflow)
        self.assertIn("ref: main", workflow)
        self.assertNotIn("pull_request_target", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertNotIn("pull-requests: write", workflow)
        self.assertNotIn("gh pr merge", workflow)

    def test_manifest_declares_v02_automation_without_runtime_fields(self) -> None:
        manifest = json.loads((ROOT / "plugins" / PLUGIN_NAME / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
        self.assertEqual("0.2.0", manifest["version"])
        self.assertIn("Automation", manifest["interface"]["capabilities"])
        self.assertTrue((ROOT / "plugins" / PLUGIN_NAME / "hooks" / "hooks.json").is_file())
        for forbidden in ("hooks", "mcpServers", "apps"):
            self.assertNotIn(forbidden, manifest)

    def test_v02_rollback_restores_same_plugin_identity(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        rollback = readme.split("### Roll back a 0.2.0 public cutover", 1)[1].split("## Package map", 1)[0]
        self.assertIn("codex plugin add openboa-ai-native-sdlc@openboa-hydra", rollback)
        legacy_add = "codex plugin add " + "openboa-" + "operations@openboa-hydra"
        self.assertNotIn(legacy_add, rollback)
        self.assertIn("version greater than 0.2.0", rollback)

    def test_v02_does_not_package_uncontained_local_execution(self) -> None:
        skill = ROOT / "plugins" / PLUGIN_NAME / "skills" / PLUGIN_NAME
        self.assertFalse((skill / "scripts" / "run_headless.py").exists())
        self.assertFalse((skill / "assets" / "launchd").exists())
        self.assertFalse((skill / "assets" / "cron").exists())
        adapter = (skill / "references" / "adapters" / "headless-and-ci.md").read_text(encoding="utf-8")
        self.assertIn("generic local headless execution as unavailable in v0.2", adapter)
        self.assertIn("detached descendants", adapter)

    def test_v02_scheduled_templates_are_read_only_handoffs(self) -> None:
        skill = ROOT / "plugins" / PLUGIN_NAME / "skills" / PLUGIN_NAME
        automation = skill / "assets" / "automations"
        combined = "\n".join(
            path.read_text(encoding="utf-8") for path in sorted(automation.glob("*.md"))
        )
        self.assertIn("read-only monitor prompts", combined)
        self.assertIn("must not edit a checkout or write to GitHub", combined)
        self.assertIn("interactive Codex task", combined)
        for forbidden in (
            "fix routine findings inside the approved branch",
            "open or update one durable private or public work item",
            "prepare a coherent documentation update and run",
        ):
            self.assertNotIn(forbidden, combined)


if __name__ == "__main__":
    unittest.main()
