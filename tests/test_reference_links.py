from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.parse import unquote, urlsplit


ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_hydra.py"
PLUGIN_ROOT = ROOT / "plugins" / "openboa-ai-native-sdlc"
MARKDOWN_LINK = re.compile(r"!?(?:\[[^]]*\])\(([^)]+)\)")


class ReferenceLinkTests(unittest.TestCase):
    def test_broken_relative_link_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            fixture = Path(temp_dir) / "hydra"
            shutil.copytree(
                ROOT,
                fixture,
                ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"),
            )
            with (fixture / "DOCTRINE.md").open("a", encoding="utf-8") as handle:
                handle.write("\n[broken](missing-reference.md)\n")
            result = subprocess.run(
                [sys.executable, str(VALIDATOR), str(fixture)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
        self.assertNotEqual(0, result.returncode)
        self.assertIn("broken link", result.stdout)

    def test_root_documents_are_thin_routes(self) -> None:
        for name in ("DOCTRINE.md", "OPERATING-MODEL.md", "AI-NATIVE-SDLC.md", "GOVERNANCE.md"):
            path = ROOT / name
            with self.subTest(path=name):
                text = path.read_text(encoding="utf-8")
                self.assertLessEqual(len(text.splitlines()), 40)
                self.assertIn("plugins/openboa-ai-native-sdlc", text)

    def test_installed_plugin_links_stay_inside_the_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            installed = Path(temp_dir) / "cache" / "openboa-ai-native-sdlc" / "0.1.0"
            shutil.copytree(PLUGIN_ROOT, installed)

            for markdown in installed.rglob("*.md"):
                for match in MARKDOWN_LINK.finditer(markdown.read_text(encoding="utf-8")):
                    raw_target = match.group(1).strip()
                    if raw_target.startswith("<") and raw_target.endswith(">"):
                        raw_target = raw_target[1:-1]
                    parsed = urlsplit(raw_target)
                    if parsed.scheme or parsed.netloc or not parsed.path:
                        continue

                    resolved = (markdown.parent / unquote(parsed.path)).resolve()
                    with self.subTest(markdown=markdown.relative_to(installed), target=raw_target):
                        try:
                            resolved.relative_to(installed.resolve())
                        except ValueError:
                            self.fail(f"relative link escapes installed plugin: {raw_target}")
                        self.assertTrue(resolved.exists(), f"missing installed-plugin target: {raw_target}")

    def test_root_research_routes_to_the_packaged_canonical_copy(self) -> None:
        root_research = ROOT / "research" / "openboa-ai-native-sdlc-v0.1"
        packaged_research = (
            PLUGIN_ROOT
            / "skills"
            / "openboa-ai-native-sdlc"
            / "references"
            / "research"
        )

        readme = (root_research / "README.md").read_text(encoding="utf-8")
        trace = (root_research / "evidence-to-design.md").read_text(encoding="utf-8")
        for text in (readme, trace):
            self.assertIn("plugins/openboa-ai-native-sdlc", text)
        self.assertLessEqual(len(readme.splitlines()), 20)
        self.assertLessEqual(len(trace.splitlines()), 12)
        self.assertEqual(
            (root_research / "source-register.csv").read_bytes(),
            (packaged_research / "source-register.csv").read_bytes(),
        )


if __name__ == "__main__":
    unittest.main()
