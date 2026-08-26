from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN = ROOT / "plugins" / "openboa-ai-native-sdlc"


class MigrationContractTests(unittest.TestCase):
    def test_readme_documents_atomic_installation_sequence(self) -> None:
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        migration = text[text.index("## Migrate from OpenBoa Operations") :]
        steps = (
            "codex plugin marketplace upgrade openboa-hydra",
            "codex plugin add openboa-ai-native-sdlc@openboa-hydra",
            "Start a new task",
            "scripts/sync_agents.py",
            "codex plugin remove openboa-operations@openboa-hydra",
        )
        offsets = [migration.index(step) for step in steps]
        self.assertEqual(offsets, sorted(offsets))
        self.assertIn("temporary Codex home", text)
        self.assertIn("Do not delete Codex cache directories manually", text)
        self.assertNotIn('cp -p "$AGENTS_BACKUP" "$AGENTS_TARGET"', text)
        self.assertIn("Restore only the managed block", text)
        self.assertIn("Keep the current repository-local section byte for byte", text)

        playbook = (
            PLUGIN
            / "skills"
            / "openboa-ai-native-sdlc"
            / "references"
            / "playbooks"
            / "adopt-and-route.md"
        ).read_text(encoding="utf-8")
        self.assertIn(".AGENTS.md.sync-*", playbook)
        self.assertIn("managed-block-only edit", playbook)
        self.assertIn("preserve the target's current repository-local section", playbook)

    def test_current_managed_contract_is_packaged(self) -> None:
        marker = "<!-- openboa-ai-native-sdlc:managed:start contract=0.2.0 -->"
        for path in (
            ROOT / "AGENTS.md",
            PLUGIN / "skills" / "openboa-ai-native-sdlc" / "assets" / "managed-AGENTS.md",
        ):
            with self.subTest(path=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertEqual(1, text.count(marker))
                self.assertIn("## Repository-local instructions", text)

    def test_migration_tool_is_packaged_with_core_skill(self) -> None:
        tool = PLUGIN / "skills" / "openboa-ai-native-sdlc" / "scripts" / "sync_agents.py"
        self.assertTrue(tool.is_file())
        self.assertFalse((ROOT / "scripts" / "sync_agents.py").exists())


if __name__ == "__main__":
    unittest.main()
