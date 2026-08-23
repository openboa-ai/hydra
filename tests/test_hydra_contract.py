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
PLUGIN_ROOT = ROOT / "plugins" / PLUGIN_NAME
EXPECTED_SKILLS = {
    "openboa-delegate-work",
    "openboa-lead-work",
    "openboa-review-work",
    "openboa-deliver-work",
    "openboa-improve-system",
    "openboa-adopt-sdlc",
}


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

    def test_marketplace_has_only_the_ai_native_sdlc_plugin(self) -> None:
        marketplace = json.loads(
            (ROOT / ".agents" / "plugins" / "marketplace.json").read_text(encoding="utf-8")
        )
        self.assertEqual(marketplace["name"], "openboa-hydra")
        self.assertEqual(marketplace["interface"]["displayName"], "OpenBoa Hydra")
        self.assertEqual([entry["name"] for entry in marketplace["plugins"]], [PLUGIN_NAME])
        self.assertEqual(
            marketplace["plugins"][0]["source"]["path"],
            f"./plugins/{PLUGIN_NAME}",
        )

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

    def test_plugin_exposes_the_six_focused_skills(self) -> None:
        skills_root = PLUGIN_ROOT / "skills"
        actual = {path.name for path in skills_root.iterdir() if path.is_dir()}
        self.assertEqual(actual, EXPECTED_SKILLS)
        for name in EXPECTED_SKILLS:
            self.assertTrue((skills_root / name / "SKILL.md").is_file())
            self.assertTrue((skills_root / name / "agents" / "openai.yaml").is_file())

    def test_doctrine_separates_stable_purpose_from_replaceable_methods(self) -> None:
        doctrine = (PLUGIN_ROOT / "references" / "doctrine.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("organization member", doctrine)
        self.assertIn("OpenBoa's accountable human is `SonSangjoon`", doctrine)
        self.assertIn("Methods are replaceable", doctrine)
        self.assertNotIn("**Contract:**", doctrine)

    def test_assignments_inherit_accountability_and_record_changing_facts(self) -> None:
        for name in ("goal-issue.md", "task-issue.md", "pull-request.md", "handoff.md"):
            with self.subTest(name=name):
                text = (PLUGIN_ROOT / "assets" / name).read_text(encoding="utf-8")
                self.assertIn("Work lead", text)
                self.assertIn("inherited", text)
                self.assertNotIn("Accountable owner (human)", text)

        goal = (PLUGIN_ROOT / "assets" / "goal-issue.md").read_text(encoding="utf-8")
        for heading in ("Decision rights", "Resources", "Boundaries", "Acceptance evidence"):
            self.assertIn(heading, goal)

    def test_managed_guidance_enables_agent_leadership_without_micromanagement(self) -> None:
        template = (PLUGIN_ROOT / "assets" / "repository-AGENTS.md").read_text(
            encoding="utf-8"
        )

        self.assertIn("agents as team members", template)
        self.assertIn("may challenge an incomplete assignment", template)
        self.assertIn("Do not require step-by-step human approval", template)
        self.assertIn("accountability is inherited", template)

    def test_custom_governance_schema_is_absent(self) -> None:
        self.assertFalse(list(PLUGIN_ROOT.rglob("openboa-governance.yml")))
        github_reference = (PLUGIN_ROOT / "references" / "github.md").read_text(encoding="utf-8")
        self.assertIn("ruleset", github_reference.lower())
        self.assertIn("environment", github_reference.lower())
        self.assertIn("CODEOWNERS", github_reference)

    def test_duplicate_managed_markers_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "hydra"
            shutil.copytree(ROOT, fixture, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            template = fixture / "plugins" / PLUGIN_NAME / "assets" / "repository-AGENTS.md"
            template.write_text(
                template.read_text(encoding="utf-8")
                + "\n<!-- openboa-ai-native-sdlc:managed:start version=0.1.0 -->\n",
                encoding="utf-8",
            )

            result = self.run_validator(fixture)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("managed marker", result.stdout)

    def test_root_managed_text_must_match_repository_template(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "hydra"
            shutil.copytree(ROOT, fixture, ignore=shutil.ignore_patterns(".git", "__pycache__"))
            agents = fixture / "AGENTS.md"
            agents.write_text(
                agents.read_text(encoding="utf-8").replace(
                    "Preserve unrelated dirty work",
                    "Discard unrelated dirty work",
                    1,
                ),
                encoding="utf-8",
            )

            result = self.run_validator(fixture)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("must match repository-AGENTS.md", result.stdout)

    def test_github_control_plane_uses_plain_authority_language(self) -> None:
        github_reference = (PLUGIN_ROOT / "references" / "github.md").read_text(encoding="utf-8")

        self.assertIn("Codex GitHub connector", github_reference)
        self.assertIn("Authentication is not authority", github_reference)
        self.assertIn("`gh`", github_reference)
        self.assertNotIn("authority tuple", github_reference)
        self.assertIn("Require review from Code Owners", github_reference)
        self.assertIn("Own `/.github/CODEOWNERS` itself", github_reference)
        self.assertIn("label routes attention", github_reference)
        self.assertIn("does not grant authority", github_reference)

    def test_ci_publishes_the_new_check_and_keeps_a_safe_compatibility_check(self) -> None:
        workflow = (ROOT / ".github" / "workflows" / "validate.yml").read_text(
            encoding="utf-8"
        )

        self.assertIn("name: openboa-ai-native-sdlc", workflow)
        self.assertIn("name: openboa-governance", workflow)
        self.assertIn("needs: ai_native_sdlc", workflow)
        self.assertIn("if: ${{ always() }}", workflow)
        self.assertIn('test "$VALIDATION_RESULT" = "success"', workflow)

    def test_readme_migrates_installed_plugins_in_safe_order(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        migration = readme.split("## Migrate from OpenBoa Operations", 1)[1]
        commands = (
            "codex plugin remove openboa-operations@openboa-hydra",
            "codex plugin marketplace upgrade openboa-hydra",
            "codex plugin add openboa-ai-native-sdlc@openboa-hydra",
            "codex plugin list --marketplace openboa-hydra",
        )

        positions = [migration.index(command) for command in commands]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("Start a new Codex task", migration)
        self.assertNotIn("/Users/", readme)


if __name__ == "__main__":
    unittest.main()
