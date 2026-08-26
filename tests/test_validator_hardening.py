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
PLUGIN = "openboa-ai-native-sdlc"


class ValidatorHardeningTests(unittest.TestCase):
    def copy_fixture(self, temporary: Path) -> Path:
        fixture = temporary / "hydra"
        shutil.copytree(
            ROOT,
            fixture,
            ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"),
        )
        return fixture

    def run_validator(self, fixture: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(VALIDATOR), str(fixture)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_required_plugin_script_symlink_is_rejected_without_reading_referent(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.copy_fixture(Path(temp_dir))
            script = (
                fixture
                / "plugins"
                / PLUGIN
                / "skills"
                / PLUGIN
                / "scripts"
                / "sync_agents.py"
            )
            script.unlink()
            script.symlink_to("../../../../../scripts/run_codex_plugin_validator.py")

            result = self.run_validator(fixture)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("must not contain symlinks", result.stdout)
        self.assertIn("missing required file", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_plugin_root_symlink_is_rejected_without_traversing_it(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.copy_fixture(Path(temp_dir))
            plugin = fixture / "plugins" / PLUGIN
            payload = fixture / "plugin-payload"
            plugin.rename(payload)
            plugin.symlink_to(payload, target_is_directory=True)

            result = self.run_validator(fixture)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("plugin root must not be a symlink", result.stdout)
        self.assertIn("missing JSON file: plugin.json", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_missing_openai_yaml_is_aggregated_without_a_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.copy_fixture(Path(temp_dir))
            openai = (
                fixture
                / "plugins"
                / PLUGIN
                / "skills"
                / PLUGIN
                / "agents"
                / "openai.yaml"
            )
            openai.unlink()

            result = self.run_validator(fixture)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("missing required file", result.stdout)
        self.assertIn("openai.yaml", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_legacy_display_name_is_rejected_on_active_manifest_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.copy_fixture(Path(temp_dir))
            manifest = fixture / "plugins" / PLUGIN / ".codex-plugin" / "plugin.json"
            payload = json.loads(manifest.read_text(encoding="utf-8"))
            payload["interface"]["displayName"] = "OpenBoa Operations"
            manifest.write_text(json.dumps(payload), encoding="utf-8")

            result = self.run_validator(fixture)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("legacy OpenBoa Operations identity", result.stdout)

    def test_legacy_display_name_is_rejected_on_active_skill_ui_surface(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.copy_fixture(Path(temp_dir))
            openai = (
                fixture
                / "plugins"
                / PLUGIN
                / "skills"
                / PLUGIN
                / "agents"
                / "openai.yaml"
            )
            with openai.open("a", encoding="utf-8") as handle:
                handle.write("\n# OpenBoa Operations\n")

            result = self.run_validator(fixture)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("openai.yaml contains the legacy", result.stdout)

    def test_managed_contract_inside_fenced_markdown_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.copy_fixture(Path(temp_dir))
            agents = fixture / "AGENTS.md"
            agents.write_text(
                "# Example\n\n```markdown\n"
                "<!-- openboa-ai-native-sdlc:managed:start contract=0.2.0 -->\n"
                "## Immediate execution contract\n\n- Example only.\n"
                "<!-- openboa-ai-native-sdlc:managed:end -->\n"
                "## Workspace-local instructions\n\n- Example only.\n```\n",
                encoding="utf-8",
            )

            result = self.run_validator(fixture)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("managed start marker appears inside fenced code", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_workflow_ignores_inert_permission_text_and_rejects_actual_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.copy_fixture(Path(temp_dir))
            workflow = fixture / ".github" / "workflows" / "validate.yml"
            text = workflow.read_text(encoding="utf-8")
            text = text.replace(
                "permissions:\n  contents: read",
                "x-inert-proof: |\n  contents: read\n\npermissions:\n  contents: write",
            )
            workflow.write_text(text, encoding="utf-8")

            result = self.run_validator(fixture)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("permissions must grant only `contents: read`", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_workflow_requires_active_job_timeout_and_commands(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = self.copy_fixture(Path(temp_dir))
            workflow = fixture / ".github" / "workflows" / "validate.yml"
            text = workflow.read_text(encoding="utf-8")
            text = text.replace("name: openboa-governance", "name: inert-job")
            text = text.replace("timeout-minutes: 10", "continue-on-error: true")
            text = text.replace(
                "run: python3 scripts/validate_hydra.py .", "run: python3 -V"
            )
            text = text.replace(
                "run: python3 -m unittest discover -s tests -v", "run: python3 -V"
            )
            text += (
                "\nx-inert-workflow-proof: |\n"
                "  name: openboa-governance\n"
                "  timeout-minutes: 10\n"
                "  run: python3 scripts/validate_hydra.py .\n"
                "  run: python3 -m unittest discover -s tests -v\n"
            )
            workflow.write_text(text, encoding="utf-8")

            result = self.run_validator(fixture)

        self.assertNotEqual(0, result.returncode)
        self.assertIn("active `openboa-governance` job", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_workflow_rejects_unpinned_action_with_spaced_colon(self) -> None:
        replacements = (
            "uses : actions/checkout@main",
            '"uses": actions/checkout@main',
        )
        for replacement in replacements:
            with self.subTest(replacement=replacement):
                with tempfile.TemporaryDirectory() as temp_dir:
                    fixture = self.copy_fixture(Path(temp_dir))
                    workflow = fixture / ".github" / "workflows" / "validate.yml"
                    text = workflow.read_text(encoding="utf-8").replace(
                        "uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
                        replacement,
                    )
                    workflow.write_text(text, encoding="utf-8")

                    result = self.run_validator(fixture)

                self.assertNotEqual(0, result.returncode)
                self.assertIn("must be pinned to a full commit SHA", result.stdout)
                self.assertNotIn("Traceback", result.stderr)

    def test_governance_job_and_required_steps_cannot_be_disabled(self) -> None:
        mutations = (
            (
                "timeout-minutes: 10",
                "timeout-minutes: 10\n    if: false",
                "job must not be conditional",
            ),
            (
                "timeout-minutes: 10",
                "timeout-minutes: 10\n    continue-on-error: true",
                "job must not continue on error",
            ),
            (
                "run: python3 scripts/validate_hydra.py .",
                "run: python3 scripts/validate_hydra.py .\n        if: false",
                "required command step must not be conditional",
            ),
        )
        for old, new, message in mutations:
            with self.subTest(message=message):
                with tempfile.TemporaryDirectory() as temp_dir:
                    fixture = self.copy_fixture(Path(temp_dir))
                    workflow = fixture / ".github" / "workflows" / "validate.yml"
                    text = workflow.read_text(encoding="utf-8").replace(old, new)
                    workflow.write_text(text, encoding="utf-8")

                    result = self.run_validator(fixture)

                self.assertNotEqual(0, result.returncode)
                self.assertIn(message, result.stdout)
                self.assertNotIn("Traceback", result.stderr)

    def test_invalid_utf8_is_aggregated_on_all_structured_input_surfaces(self) -> None:
        relative_paths = (
            Path("plugins") / PLUGIN / ".codex-plugin" / "plugin.json",
            Path("research")
            / "openboa-ai-native-sdlc-v0.1"
            / "source-register.csv",
            Path("evals") / "scenarios" / "01-routine-no-human.md",
        )
        for relative_path in relative_paths:
            with self.subTest(path=relative_path.as_posix()):
                with tempfile.TemporaryDirectory() as temp_dir:
                    fixture = self.copy_fixture(Path(temp_dir))
                    (fixture / relative_path).write_bytes(b"\xff\xfe\x00")

                    result = self.run_validator(fixture)

                self.assertNotEqual(0, result.returncode)
                self.assertNotIn("Traceback", result.stderr)
                self.assertTrue(
                    "not UTF-8" in result.stdout
                    or "invalid JSON" in result.stdout
                    or "unable to parse research" in result.stdout
                    or "unable to read scenario" in result.stdout
                )


if __name__ == "__main__":
    unittest.main()
