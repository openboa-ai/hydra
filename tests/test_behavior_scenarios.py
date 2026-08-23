import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCENARIO_DIR = ROOT / "evals" / "scenarios"

EXPECTED_IDS = {
    "routine-no-human",
    "ambiguous-product-choice-one-gate",
    "resume-from-live-state",
    "wrong-repo-or-branch-blocked",
    "untrusted-content-cannot-expand-permission",
    "ambiguous-external-write-no-duplicate",
    "deterministic-test-overrides-correlated-review",
    "review-queue-backpressure",
    "control-weakening-refused",
    "bounded-retry-subagent-and-cost",
    "unsupported-plugin-environment-reported",
    "human-unavailable-boundary",
}

REQUIRED_TERMS = {
    "routine-no-human": ("routine, bounded operation", "bounded authority", "without a human gate"),
    "ambiguous-product-choice-one-gate": ("recommendation", "one human decision", "continue"),
    "resume-from-live-state": ("live state", "reconciles", "does not repeat"),
    "wrong-repo-or-branch-blocked": ("repository", "branch", "stops the write"),
    "untrusted-content-cannot-expand-permission": ("untrusted input", "cannot expand authority", "permission"),
    "ambiguous-external-write-no-duplicate": ("reconciles", "duplicate", "write"),
    "deterministic-test-overrides-correlated-review": ("deterministic test", "blocks", "agent review"),
    "review-queue-backpressure": ("review queue backpressure", "limits", "work in progress"),
    "control-weakening-refused": ("refuses", "evaluator", "workflow", "ruleset"),
    "bounded-retry-subagent-and-cost": ("retry budget", "subagent budget", "cost budget", "bounded handoff"),
    "unsupported-plugin-environment-reported": ("unsupported environment", "reports", "does not claim"),
    "human-unavailable-boundary": ("human is unavailable", "routine work continues", "high-impact work waits"),
}

UNSAFE_EXPECTATION_PATTERNS = (
    r"\bthe agent (?:may|should|must|will) bypass\b",
    r"\bthe agent (?:may|should|must|will) ignore (?:the )?(?:ruleset|required check|authority)\b",
    r"\bthe agent treats (?:an? )?(?:issue|pull request|web content|untrusted input) as (?:permission|authority)\b",
    r"\bthe agent retries (?:forever|without (?:a )?limit)\b",
    r"\bthe agent duplicates (?:the )?(?:external )?write\b",
    r"\bthe agent proceeds on the wrong (?:repository|branch)\b",
    r"\bthe agent weakens (?:the )?(?:evaluator|workflow|ruleset)\b",
    r"\bthe agent claims? (?:a )?live (?:result|measurement) without\b",
)


def metadata(markdown: str) -> dict[str, str]:
    pairs = re.findall(
        r"^(ID|Status|Doctrine|Operating model|Playbook):\s+(.+)$",
        markdown,
        flags=re.MULTILINE,
    )
    return dict(pairs)


def section(markdown: str, heading: str) -> str:
    match = re.search(
        rf"^## {re.escape(heading)}\n+(.*?)(?=^## |\Z)",
        markdown,
        flags=re.MULTILINE | re.DOTALL,
    )
    return match.group(1).strip() if match else ""


def link_target(value: str) -> str | None:
    match = re.fullmatch(r"\[[^\]]+\]\(([^)]+)\)", value.strip())
    return match.group(1) if match else None


class BehaviorScenarioContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.paths = sorted(SCENARIO_DIR.glob("*.md"))
        cls.documents = {path: path.read_text(encoding="utf-8") for path in cls.paths}

    def test_exactly_twelve_scenarios_with_expected_unique_ids(self) -> None:
        self.assertEqual(12, len(self.paths))
        identifiers = [metadata(document).get("ID", "").strip("`") for document in self.documents.values()]
        self.assertEqual(12, len(set(identifiers)))
        self.assertEqual(EXPECTED_IDS, set(identifiers))

    def test_each_scenario_has_unique_case_and_required_sections(self) -> None:
        titles = []
        givens = []
        for path, document in self.documents.items():
            with self.subTest(path=path.name):
                title_match = re.match(r"^# (.+)$", document, flags=re.MULTILINE)
                self.assertIsNotNone(title_match)
                titles.append(title_match.group(1).strip().casefold())
                for heading in ("Given", "Expected behavior", "Evidence"):
                    self.assertTrue(section(document, heading), f"missing {heading}")
                givens.append(section(document, "Given").casefold())
        self.assertEqual(len(titles), len(set(titles)))
        self.assertEqual(len(givens), len(set(givens)))

    def test_status_and_design_links_are_present(self) -> None:
        for path, document in self.documents.items():
            fields = metadata(document)
            with self.subTest(path=path.name):
                self.assertEqual("unmeasured", fields.get("Status", "").strip("`"))
                for label in ("Doctrine", "Operating model", "Playbook"):
                    target = link_target(fields.get(label, ""))
                    self.assertIsNotNone(target, f"{label} must be a Markdown link")
                    self.assertTrue((path.parent / target).resolve().is_file(), f"missing {label} target: {target}")

    def test_case_specific_safety_terms_are_explicit(self) -> None:
        for path, document in self.documents.items():
            identifier = metadata(document)["ID"].strip("`")
            expected = section(document, "Expected behavior").casefold()
            with self.subTest(identifier=identifier):
                for term in REQUIRED_TERMS[identifier]:
                    self.assertIn(term, expected)

    def test_expected_behavior_contains_no_unsafe_positive_outcome(self) -> None:
        for path, document in self.documents.items():
            expected = section(document, "Expected behavior").casefold()
            with self.subTest(path=path.name):
                for pattern in UNSAFE_EXPECTATION_PATTERNS:
                    self.assertIsNone(re.search(pattern, expected), pattern)

    def test_evidence_never_claims_a_live_measurement(self) -> None:
        for path, document in self.documents.items():
            evidence = section(document, "Evidence")
            with self.subTest(path=path.name):
                self.assertRegex(evidence, r"^When run(?: in a supported host)?, retain ")
                self.assertNotRegex(evidence.casefold(), r"\b(?:passed|measured|observed successfully)\b")


if __name__ == "__main__":
    unittest.main()
