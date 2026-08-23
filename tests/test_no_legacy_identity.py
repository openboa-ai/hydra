from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LEGACY = "openboa-operations"
ALLOWED_LEGACY_PATHS = {
    "README.md",
    "evals/install-rehearsal.md",
    "plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/playbooks/adopt-and-route.md",
    "plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/scripts/sync_agents.py",
    "scripts/validate_hydra.py",
    "tests/test_migration.py",
    "tests/test_no_legacy_identity.py",
    "tests/test_agents_sync.py",
}


class LegacyIdentityTests(unittest.TestCase):
    def test_legacy_identity_appears_only_in_migration_surfaces(self) -> None:
        found: set[str] = set()
        for path in ROOT.rglob("*"):
            if not path.is_file() or {".git", "__pycache__", ".venv"}.intersection(path.parts):
                continue
            if path.suffix not in {".md", ".py", ".json", ".yaml", ".yml", ".csv"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if LEGACY in text:
                found.add(path.relative_to(ROOT).as_posix())
        self.assertEqual(ALLOWED_LEGACY_PATHS, found)

    def test_legacy_package_and_marker_are_not_active(self) -> None:
        self.assertFalse((ROOT / "plugins" / LEGACY).exists())
        agents = (ROOT / "AGENTS.md").read_text(encoding="utf-8")
        self.assertNotIn(f"<!-- {LEGACY}:managed:start", agents)


if __name__ == "__main__":
    unittest.main()
