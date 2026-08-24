from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL_ROOT = (
    ROOT
    / "plugins"
    / "openboa-ai-native-sdlc"
    / "skills"
    / "openboa-ai-native-sdlc"
)
DOCTRINE = SKILL_ROOT / "references" / "doctrine.md"

# Intentionally vendored from the canonical brand-system snapshot rather than
# read from a sibling checkout at runtime. This keeps the plugin self-contained.
CANONICAL_BRAND_SOURCE = (
    "openboa-brand-system@e76ac5031fe8:"
    "00-overview/OPENBOA-BRAND-FOUNDATION.md"
)
CANONICAL_HIERARCHY = (
    "Humanity is defined not only by what it can understand, but by what it can imagine and realize.",
    "OpenBoa exists to expand the horizon of human possibility.",
    "Poiesis is the enduring human capacity through which possibility becomes part of the world.",
    "Agents mark a new dimension of creation.",
    "OpenBoa explores this horizon through the Business of Agents.",
    "We develop products and businesses that expand what human imagination can realize.",
)
CANONICAL_VOCABULARY = (
    "Creation describes the new dimension opened by agents.",
    "Realization describes possibility becoming consequential in products and businesses.",
    "The Business of Agents is OpenBoa's present field of exploration, not its timeless purpose.",
)
RETIRED_LANGUAGE = (
    "Quiet Infrastructure",
    "Calm, operational and inspectable",
    "Boa Skin, Open System",
    "give form",
    "bring into being",
    "not-yet",
)
PUBLIC_ROOT_FILES = (
    ROOT / "README.md",
    ROOT / "AGENTS.md",
    ROOT / "DOCTRINE.md",
    ROOT / "OPERATING-MODEL.md",
    ROOT / "AI-NATIVE-SDLC.md",
    ROOT / "GOVERNANCE.md",
)


class BrandContractTest(unittest.TestCase):
    def test_doctrine_preserves_canonical_hierarchy(self) -> None:
        doctrine = DOCTRINE.read_text(encoding="utf-8")
        cursor = -1

        for phrase in CANONICAL_HIERARCHY:
            position = doctrine.find(phrase)
            self.assertGreater(
                position,
                cursor,
                f"missing or out-of-order canonical phrase from {CANONICAL_BRAND_SOURCE}: {phrase}",
            )
            cursor = position

    def test_doctrine_preserves_canonical_vocabulary(self) -> None:
        doctrine = DOCTRINE.read_text(encoding="utf-8")

        for phrase in CANONICAL_VOCABULARY:
            self.assertIn(phrase, doctrine)

        self.assertEqual(1, doctrine.count("Poiesis"))
        self.assertNotIn("through creation", doctrine)

    def test_continuity_is_a_reconstructable_current_hypothesis(self) -> None:
        doctrine = DOCTRINE.read_text(encoding="utf-8")

        self.assertIn("capable operational collaborator", doctrine)
        self.assertIn("designs the role to be reconstructable", doctrine)
        self.assertIn("is a current hypothesis to be tested", doctrine)
        self.assertNotIn("is a persistent operational role", doctrine)

    def test_retired_language_is_absent_from_public_contract(self) -> None:
        public_files = tuple(path for path in PUBLIC_ROOT_FILES if path.exists()) + tuple(
            sorted(SKILL_ROOT.rglob("*.md"))
        )

        for path in public_files:
            text = path.read_text(encoding="utf-8").casefold()
            for phrase in RETIRED_LANGUAGE:
                self.assertNotIn(
                    phrase.casefold(),
                    text,
                    f"retired brand language found in {path.relative_to(ROOT)}: {phrase}",
                )


if __name__ == "__main__":
    unittest.main()
