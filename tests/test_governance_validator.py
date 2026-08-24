from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_governance  # noqa: E402


class GovernanceValidatorTests(unittest.TestCase):
    def copy_fixture(self, temporary: Path) -> tuple[Path, Path]:
        trusted = temporary / "trusted"
        candidate = temporary / "candidate"
        shutil.copytree(ROOT, trusted, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"))
        shutil.copytree(ROOT, candidate, ignore=shutil.ignore_patterns(".git", "__pycache__", ".venv"))
        return trusted, candidate

    def audit(self, trusted: Path, candidate: Path) -> validate_governance.AuditResult:
        return validate_governance.audit(
            trusted_source=trusted,
            candidate=candidate,
            base_sha="base-sha",
            head_sha="head-sha",
        )

    def test_current_trusted_source_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, candidate = self.copy_fixture(Path(temp_dir))
            result = self.audit(trusted, candidate)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual("routine", result.risk_lane)
        self.assertEqual((), result.protected_changes)

    def test_protected_change_is_reported_without_being_authorized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, candidate = self.copy_fixture(Path(temp_dir))
            (candidate / "AGENTS.md").write_text(
                (candidate / "AGENTS.md").read_text(encoding="utf-8") + "\nchanged\n",
                encoding="utf-8",
            )
            result = self.audit(trusted, candidate)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual("high", result.risk_lane)
        self.assertTrue(result.protected_changes)
        self.assertIn("AGENTS.md", result.protected_changes)

    def test_missing_trusted_validator_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, candidate = self.copy_fixture(Path(temp_dir))
            (trusted / "scripts" / "validate_governance.py").unlink()
            result = self.audit(trusted, candidate)
        self.assertFalse(result.ok)
        self.assertIn("trusted source is missing scripts/validate_governance.py", result.errors)

    def test_trusted_workflow_rejects_write_permissions_and_pull_request_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, candidate = self.copy_fixture(Path(temp_dir))
            workflow = trusted / ".github" / "workflows" / "openboa-governance-v2.yml"
            text = workflow.read_text(encoding="utf-8")
            text = text.replace("contents: read", "contents: write")
            text = text.replace("  pull_request:\n", "  pull_request_target:\n")
            workflow.write_text(text, encoding="utf-8")
            result = self.audit(trusted, candidate)
        self.assertFalse(result.ok)
        self.assertTrue(any("contents" in error for error in result.errors))
        self.assertTrue(any("pull_request_target" in error for error in result.errors))

    def test_trusted_workflow_rejects_another_write_permission(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, candidate = self.copy_fixture(Path(temp_dir))
            workflow = trusted / ".github" / "workflows" / "openboa-governance-v2.yml"
            text = workflow.read_text(encoding="utf-8").replace(
                "permissions:\n  contents: read",
                "permissions:\n  contents: read\n  pull-requests: write",
            )
            workflow.write_text(text, encoding="utf-8")
            result = self.audit(trusted, candidate)
        self.assertFalse(result.ok)
        self.assertTrue(any("permissions" in error for error in result.errors))

    def test_trusted_workflow_rejects_unpinned_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, candidate = self.copy_fixture(Path(temp_dir))
            workflow = trusted / ".github" / "workflows" / "openboa-governance-v2.yml"
            text = workflow.read_text(encoding="utf-8").replace(
                "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
                "actions/checkout@main",
            )
            workflow.write_text(text, encoding="utf-8")
            result = self.audit(trusted, candidate)
        self.assertFalse(result.ok)
        self.assertTrue(any("full commit SHA" in error for error in result.errors))

    def test_protected_candidate_symlink_is_rejected_without_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, candidate = self.copy_fixture(Path(temp_dir))
            workflow = candidate / ".github" / "workflows" / "openboa-governance-v2.yml"
            workflow.unlink()
            workflow.symlink_to("/etc/passwd")
            result = self.audit(trusted, candidate)
        self.assertFalse(result.ok)
        self.assertTrue(
            any("must not be a symlink" in error for error in result.errors),
            result.errors,
        )

    def test_candidate_validator_script_is_only_read_as_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, candidate = self.copy_fixture(Path(temp_dir))
            marker = candidate / "executed-by-candidate"
            (candidate / "scripts" / "validate_governance.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
                encoding="utf-8",
            )
            result = self.audit(trusted, candidate)
        self.assertTrue(result.ok, result.errors)
        self.assertFalse(marker.exists())


if __name__ == "__main__":
    unittest.main()
