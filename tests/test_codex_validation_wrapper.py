from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WRAPPER = ROOT / "scripts" / "validate_codex.py"
SKILL_NAMES = (
    "openboa-adopt-sdlc",
    "openboa-delegate-work",
    "openboa-deliver-work",
    "openboa-improve-system",
    "openboa-lead-work",
    "openboa-review-work",
)
FAKE_VALIDATOR = """\
from pathlib import Path
import sys

target = Path(sys.argv[1])
if not target.exists():
    raise SystemExit(2)
print(f"validated {target.name}")
"""


class CodexValidationWrapperTests(unittest.TestCase):
    def test_wrapper_discovers_codex_home_and_validates_every_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            codex_home = temp / "portable-codex-home"
            plugin_validator = (
                codex_home
                / "skills"
                / ".system"
                / "plugin-creator"
                / "scripts"
                / "validate_plugin.py"
            )
            skill_validator = (
                codex_home
                / "skills"
                / ".system"
                / "skill-creator"
                / "scripts"
                / "quick_validate.py"
            )
            plugin_validator.parent.mkdir(parents=True)
            skill_validator.parent.mkdir(parents=True)
            plugin_validator.write_text(FAKE_VALIDATOR, encoding="utf-8")
            skill_validator.write_text(FAKE_VALIDATOR, encoding="utf-8")

            fixture = temp / "hydra"
            skills = fixture / "plugins" / "openboa-ai-native-sdlc" / "skills"
            for name in SKILL_NAMES:
                (skills / name).mkdir(parents=True)

            # Let the wrapper use the current interpreter without requiring uv in this test.
            (temp / "yaml.py").write_text("", encoding="utf-8")
            environment = os.environ.copy()
            environment["CODEX_HOME"] = str(codex_home)
            environment["PYTHONPATH"] = str(temp)

            result = subprocess.run(
                [sys.executable, str(WRAPPER), str(fixture)],
                cwd=ROOT,
                env=environment,
                capture_output=True,
                text=True,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(result.stdout.count("validated "), 7)
            self.assertIn("1 plugin, 6 skills", result.stdout)


if __name__ == "__main__":
    unittest.main()
