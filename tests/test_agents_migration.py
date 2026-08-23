from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MIGRATOR = ROOT / "plugins" / "openboa-ai-native-sdlc" / "scripts" / "sync_agents.py"
TEMPLATE = ROOT / "plugins" / "openboa-ai-native-sdlc" / "assets" / "repository-AGENTS.md"
LEGACY_START = "<!-- openboa-operations:managed:start contract=0.1.0 -->"
LEGACY_END = "<!-- openboa-operations:managed:end -->"
NEW_START = "<!-- openboa-ai-native-sdlc:managed:start version=0.1.0 -->"
NEW_END = "<!-- openboa-ai-native-sdlc:managed:end -->"
LOCAL = "## Repository-local instructions\n\n- Keep this exact local rule.\n"


class AgentsMigrationTests(unittest.TestCase):
    def run_sync(
        self, target: Path, template: Path = TEMPLATE
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(MIGRATOR), str(target), str(template)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_legacy_block_is_replaced_and_local_text_is_preserved(self) -> None:
        legacy = (
            "# Product\n\n"
            f"{LEGACY_START}\nold managed text\n{LEGACY_END}\n\n"
            f"{LOCAL}"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "AGENTS.md"
            target.write_text(legacy, encoding="utf-8")

            result = self.run_sync(target)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            migrated = target.read_text(encoding="utf-8")
            self.assertIn(NEW_START, migrated)
            self.assertIn(NEW_END, migrated)
            self.assertNotIn(LEGACY_START, migrated)
            self.assertTrue(migrated.endswith(LOCAL))

            second_result = self.run_sync(target)
            self.assertEqual(
                second_result.returncode,
                0,
                second_result.stdout + second_result.stderr,
            )
            self.assertIn("already current", second_result.stdout)
            self.assertEqual(target.read_text(encoding="utf-8"), migrated)

    def test_missing_block_is_installed_before_local_text(self) -> None:
        source = "# Product\n\nKeep this introduction.\n\n" + LOCAL
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "AGENTS.md"
            target.write_text(source, encoding="utf-8")

            result = self.run_sync(target)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            installed = target.read_text(encoding="utf-8")
            self.assertTrue(installed.startswith("# Product\n\nKeep this introduction."))
            self.assertIn(NEW_START, installed)
            self.assertLess(installed.index(NEW_END), installed.index(LOCAL))
            self.assertTrue(installed.endswith(LOCAL))

    def test_crlf_local_section_is_preserved_byte_for_byte(self) -> None:
        prefix = b"# Product\r\n\r\n"
        local = (
            b"## Repository-local instructions\r\n\r\n"
            b"- Keep this exact local rule.\r\n"
        )
        source = (
            prefix
            + LEGACY_START.encode()
            + b"\r\nold managed text\r\n"
            + LEGACY_END.encode()
            + b"\r\n\r\n"
            + local
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "AGENTS.md"
            target.write_bytes(source)

            result = self.run_sync(target)

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            migrated = target.read_bytes()
            self.assertTrue(migrated.startswith(prefix))
            self.assertTrue(migrated.endswith(local))
            self.assertIn(NEW_START.encode(), migrated)
            self.assertNotIn(LEGACY_START.encode(), migrated)

    def test_duplicate_legacy_markers_fail_without_writing(self) -> None:
        source = (
            f"{LEGACY_START}\none\n{LEGACY_END}\n"
            f"{LEGACY_START}\ntwo\n{LEGACY_END}\n{LOCAL}"
        )
        self.assert_refused_without_writing(source, "marker")

    def test_malformed_marker_fails_without_writing(self) -> None:
        source = f"{LEGACY_START}\nmissing end\n{LOCAL}"
        self.assert_refused_without_writing(source, "marker")

    def test_unknown_version_fails_without_writing(self) -> None:
        source = (
            "<!-- openboa-ai-native-sdlc:managed:start version=2.0.0 -->\n"
            "future text\n"
            f"{NEW_END}\n{LOCAL}"
        )
        self.assert_refused_without_writing(source, "version")

    def test_reversed_markers_fail_without_writing(self) -> None:
        source = f"{NEW_END}\nmanaged text\n{NEW_START}\n{LOCAL}"
        self.assert_refused_without_writing(source, "order")

    def test_reversed_template_markers_fail_without_writing(self) -> None:
        source = "# Product\n\n" + LOCAL
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            target = temp / "AGENTS.md"
            template = temp / "template.md"
            target.write_text(source, encoding="utf-8")
            template.write_text(
                f"# Template\n\n{NEW_END}\nmanaged text\n{NEW_START}\n\n{LOCAL}",
                encoding="utf-8",
            )

            result = self.run_sync(target, template)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("order", result.stdout.lower() + result.stderr.lower())
            self.assertEqual(target.read_text(encoding="utf-8"), source)

    def test_template_block_after_local_heading_fails_without_writing(self) -> None:
        source = "# Product\n\n" + LOCAL
        with tempfile.TemporaryDirectory() as temp_dir:
            temp = Path(temp_dir)
            target = temp / "AGENTS.md"
            template = temp / "template.md"
            target.write_text(source, encoding="utf-8")
            template.write_text(
                f"# Template\n\n{LOCAL}\n{NEW_START}\nmanaged\n{NEW_END}\n",
                encoding="utf-8",
            )

            result = self.run_sync(target, template)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("overlap", result.stdout.lower() + result.stderr.lower())
            self.assertEqual(target.read_text(encoding="utf-8"), source)

    def test_managed_block_after_local_heading_fails_without_writing(self) -> None:
        source = f"# Product\n\n{LOCAL}\n{LEGACY_START}\nmanaged\n{LEGACY_END}\n"
        self.assert_refused_without_writing(source, "overlap")

    def test_managed_block_spanning_local_heading_fails_without_writing(self) -> None:
        source = f"# Product\n\n{LEGACY_START}\nmanaged\n{LOCAL}{LEGACY_END}\n"
        self.assert_refused_without_writing(source, "overlap")

    def test_managed_block_without_local_heading_fails_without_writing(self) -> None:
        source = f"# Product\n\n{LEGACY_START}\nmanaged\n{LEGACY_END}\n"
        self.assert_refused_without_writing(source, "local")

    def assert_refused_without_writing(self, source: str, message: str) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "AGENTS.md"
            target.write_text(source, encoding="utf-8")

            result = self.run_sync(target)

            self.assertNotEqual(result.returncode, 0)
            self.assertIn(message, result.stdout.lower() + result.stderr.lower())
            self.assertEqual(target.read_text(encoding="utf-8"), source)


if __name__ == "__main__":
    unittest.main()
