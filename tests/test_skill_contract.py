from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "plugins" / "openboa-ai-native-sdlc" / "skills"
EXPECTED = {
    "openboa-plan-work": {
        "Codex Goal",
        "explicitly asks",
        "parent Issue",
        "sub-issues",
        "issue dependencies",
    },
    "openboa-build-change": {"worktree", "dirty", "handoff", "untrusted"},
    "openboa-review-change": {"outcome", "tests", "evals", "/review"},
    "openboa-ship-change": {"required checks", "auto-merge", "human approval", "rollback"},
    "openboa-improve-workflow": {"repeated failure", "test", "eval", "AGENTS.md"},
    "openboa-adopt-sdlc": {"managed block", "local", "Codex GitHub connector", "malformed"},
}


class SkillContractTests(unittest.TestCase):
    def test_skills_use_focused_trigger_descriptions_and_expected_decisions(self) -> None:
        for name, terms in EXPECTED.items():
            with self.subTest(name=name):
                text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
                description = re.search(r"^description:\s*(.+)$", text, re.MULTILINE)
                self.assertIsNotNone(description)
                self.assertTrue(description.group(1).startswith("Use when"))
                for term in terms:
                    self.assertIn(term, text)

    def test_skills_route_to_shared_references_instead_of_copying_policy(self) -> None:
        for name in EXPECTED:
            with self.subTest(name=name):
                text = (SKILLS / name / "SKILL.md").read_text(encoding="utf-8")
                self.assertIn("../../references/", text)
                self.assertLess(len(text.split()), 500)

    def test_skills_do_not_require_a_custom_runtime(self) -> None:
        for path in SKILLS.glob("*/SKILL.md"):
            text = path.read_text(encoding="utf-8").lower()
            for forbidden in ("goalspec", "graphspec", "admissiondecision", "daemon", "mcp server"):
                self.assertNotIn(forbidden, text, f"{path.name} contains {forbidden}")

    def test_skill_links_resolve_inside_the_plugin(self) -> None:
        link_pattern = re.compile(r"\[[^\]]+\]\(([^)]+)\)")
        for path in SKILLS.glob("*/SKILL.md"):
            with self.subTest(skill=path.parent.name):
                links = link_pattern.findall(path.read_text(encoding="utf-8"))
                self.assertTrue(links)
                for link in links:
                    target = (path.parent / link).resolve()
                    self.assertTrue(target.exists(), f"broken link in {path}: {link}")

    def test_default_prompts_explicitly_invoke_their_skill(self) -> None:
        for skill_root in SKILLS.iterdir():
            if not skill_root.is_dir():
                continue
            with self.subTest(skill=skill_root.name):
                metadata = (skill_root / "agents" / "openai.yaml").read_text(
                    encoding="utf-8"
                )
                self.assertIn(f"${skill_root.name}", metadata)


if __name__ == "__main__":
    unittest.main()
