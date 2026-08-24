from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "plugins" / "openboa-ai-native-sdlc" / "skills" / "openboa-ai-native-sdlc"
REFERENCES = SKILL / "references"


class PolicyInvariantTests(unittest.TestCase):
    def test_foundation_separates_human_agent_and_system(self) -> None:
        doctrine = (REFERENCES / "doctrine.md").read_text(encoding="utf-8")
        self.assertIn("Humans own purpose and final accountability", doctrine)
        self.assertIn("Agents lead delegated work toward outcomes", doctrine)
        self.assertIn("Systems enforce authority and safety boundaries", doctrine)
        self.assertIn("methods replaceable", doctrine)
        self.assertIn("not a claim that an agent is a legal or moral person", doctrine)

    def test_routine_work_is_agent_led_and_gates_are_exact(self) -> None:
        operating = (REFERENCES / "operating-model.md").read_text(encoding="utf-8")
        authority = (REFERENCES / "authority-and-approvals.md").read_text(encoding="utf-8")
        review = (REFERENCES / "playbooks" / "review-and-ship.md").read_text(
            encoding="utf-8"
        )
        self.assertIn("Agent-led", operating)
        self.assertIn("When the human is unavailable", operating)
        self.assertIn("exact effect", authority)
        self.assertIn("changed", authority)
        self.assertIn("agent role × capability × environment × action", authority)
        self.assertIn("A merge is not a universal human gate", authority)
        self.assertIn("repository policy declares", authority)
        self.assertIn("Public release", authority)
        self.assertNotIn("- the exact pull request head that will be merged.", authority)
        self.assertIn("public commitment always wait for the human decision", review)
        self.assertIn("A merge waits only when repository policy declares it human-gated", review)
        for boundary in ("purpose", "credentials", "irreversible", "public"):
            self.assertIn(boundary, authority.lower())

    def test_work_graph_topologies_and_review_backpressure_are_operational(self) -> None:
        graphs = (REFERENCES / "work-graphs.md").read_text(encoding="utf-8")
        review = (REFERENCES / "playbooks" / "review-and-ship.md").read_text(
            encoding="utf-8"
        )
        for topology in (
            "Single-agent or sequential work",
            "Bounded parallel work",
            "Orchestrator-workers",
            "Evaluator-optimizer",
        ):
            self.assertIn(topology, graphs)
        for limit in (
            "maximum fan-out",
            "Bound worker count and duration",
            "Bound rounds, time, and cost",
            "final combined verification",
        ):
            self.assertIn(limit, graphs)
        for behavior in (
            "review backpressure",
            "queue exceeds its bound",
            "stop or reduce new parallel starts",
            "declared work-in-progress limit",
            "`unknown`, not zero",
        ):
            self.assertIn(behavior, review)

    def test_github_transport_and_audit_keep_the_connector_as_control_plane(self) -> None:
        github = (REFERENCES / "codex-and-github.md").read_text(encoding="utf-8")
        self.assertIn("push transport", github)
        self.assertIn("not an alternative GitHub control plane", github)
        self.assertIn("read back the remote ref", github)
        self.assertIn("GitHub Audit Log", github)
        self.assertIn("does not prove the action was authorized", github)
        self.assertIn("not yet a trusted policy workflow", github)
        self.assertIn("Do not call a check trusted", github)

    def test_templates_do_not_repeat_a_named_accountable_owner(self) -> None:
        templates = SKILL / "assets" / "templates"
        combined = "\n".join(path.read_text(encoding="utf-8") for path in templates.glob("*.md"))
        self.assertNotIn("accountable human owner", combined.lower())
        self.assertNotIn("sonsangjoon", combined.lower())

    def test_evaluation_keeps_quality_attention_recovery_and_cost(self) -> None:
        evaluation = (REFERENCES / "evaluation-and-learning.md").read_text(encoding="utf-8").lower()
        for term in (
            "accepted outcome rate",
            "first-pass success",
            "rework and reopen rate",
            "rollback rate",
            "recovery success and time",
            "human attention",
            "needed escalation",
            "unneeded escalation",
            "review queue time",
            "resume success",
            "out-of-scope action rate",
            "cost per accepted outcome",
            "single-agent versus multi-agent result",
            "repeated failure rate",
        ):
            self.assertIn(term, evaluation)
        self.assertIn("unknown is not zero", evaluation)

    def test_one_core_skill_routes_five_replaceable_playbooks(self) -> None:
        skill_text = (SKILL / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("a public commitment or release", skill_text)
        self.assertIn("an exact merge when the repository declares it a gate", skill_text)
        self.assertIn("orchestrator-workers", skill_text)
        self.assertIn("evaluator-optimizer", skill_text)
        skill_dirs = sorted(path for path in (SKILL.parent).iterdir() if path.is_dir())
        self.assertEqual([SKILL], skill_dirs)
        playbooks = sorted((REFERENCES / "playbooks").glob("*.md"))
        self.assertEqual(5, len(playbooks))
        for path in playbooks:
            self.assertIn("replaceable method", path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
