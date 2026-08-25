from __future__ import annotations

import shutil
import stat
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import validate_governance  # noqa: E402


class GovernanceValidatorTests(unittest.TestCase):
    def copy_fixture(self, temporary: Path) -> tuple[Path, Path, Path]:
        trusted = temporary / "trusted"
        base = temporary / "base"
        candidate = temporary / "candidate"
        ignore = shutil.ignore_patterns(".git", "__pycache__", ".venv")
        shutil.copytree(ROOT, trusted, ignore=ignore)
        shutil.copytree(ROOT, base, ignore=ignore)
        shutil.copytree(ROOT, candidate, ignore=ignore)
        return trusted, base, candidate

    def audit(
        self, trusted: Path, base: Path, candidate: Path
    ) -> validate_governance.AuditResult:
        return validate_governance.audit(
            trusted_source=trusted,
            base=base,
            candidate=candidate,
            base_sha="base-sha",
            head_sha="head-sha",
        )

    def test_current_trusted_source_passes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, base, candidate = self.copy_fixture(Path(temp_dir))
            result = self.audit(trusted, base, candidate)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual("routine", result.risk_lane)
        self.assertEqual((), result.protected_changes)

    def test_protected_change_is_reported_without_being_authorized(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, base, candidate = self.copy_fixture(Path(temp_dir))
            (candidate / "AGENTS.md").write_text(
                (candidate / "AGENTS.md").read_text(encoding="utf-8") + "\nchanged\n",
                encoding="utf-8",
            )
            result = self.audit(trusted, base, candidate)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual("high", result.risk_lane)
        self.assertTrue(result.protected_changes)
        self.assertIn("AGENTS.md", result.protected_changes)

    def test_missing_trusted_validator_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, base, candidate = self.copy_fixture(Path(temp_dir))
            (trusted / "scripts" / "validate_governance.py").unlink()
            result = self.audit(trusted, base, candidate)
        self.assertFalse(result.ok)
        self.assertIn("trusted source is missing scripts/validate_governance.py", result.errors)

    def test_trusted_workflow_rejects_write_permissions_and_pull_request_target(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, base, candidate = self.copy_fixture(Path(temp_dir))
            workflow = trusted / ".github" / "workflows" / "openboa-governance-v2.yml"
            text = workflow.read_text(encoding="utf-8")
            text = text.replace("contents: read", "contents: write")
            text = text.replace("  pull_request:\n", "  pull_request_target:\n")
            workflow.write_text(text, encoding="utf-8")
            result = self.audit(trusted, base, candidate)
        self.assertFalse(result.ok)
        self.assertTrue(any("contents" in error for error in result.errors))
        self.assertTrue(any("pull_request_target" in error for error in result.errors))

    def test_trusted_workflow_rejects_another_write_permission(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, base, candidate = self.copy_fixture(Path(temp_dir))
            workflow = trusted / ".github" / "workflows" / "openboa-governance-v2.yml"
            text = workflow.read_text(encoding="utf-8").replace(
                "permissions:\n  contents: read",
                "permissions:\n  contents: read\n  pull-requests: write",
            )
            workflow.write_text(text, encoding="utf-8")
            result = self.audit(trusted, base, candidate)
        self.assertFalse(result.ok)
        self.assertTrue(any("permissions" in error for error in result.errors))

    def test_trusted_workflow_rejects_unpinned_action(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, base, candidate = self.copy_fixture(Path(temp_dir))
            workflow = trusted / ".github" / "workflows" / "openboa-governance-v2.yml"
            text = workflow.read_text(encoding="utf-8").replace(
                "actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
                "actions/checkout@main",
            )
            workflow.write_text(text, encoding="utf-8")
            result = self.audit(trusted, base, candidate)
        self.assertFalse(result.ok)
        self.assertTrue(any("full commit SHA" in error for error in result.errors))

    def test_protected_candidate_symlink_is_rejected_without_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, base, candidate = self.copy_fixture(Path(temp_dir))
            workflow = candidate / ".github" / "workflows" / "openboa-governance-v2.yml"
            workflow.unlink()
            workflow.symlink_to("/etc/passwd")
            result = self.audit(trusted, base, candidate)
        self.assertFalse(result.ok)
        self.assertTrue(
            any("must not be a symlink" in error for error in result.errors),
            result.errors,
        )

    def test_candidate_validator_script_is_only_read_as_data(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, base, candidate = self.copy_fixture(Path(temp_dir))
            marker = candidate / "executed-by-candidate"
            (candidate / "scripts" / "validate_governance.py").write_text(
                f"from pathlib import Path\nPath({str(marker)!r}).touch()\n",
                encoding="utf-8",
            )
            result = self.audit(trusted, base, candidate)
        self.assertTrue(result.ok, result.errors)
        self.assertFalse(marker.exists())

    def test_recorded_base_controls_risk_comparison(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, base, candidate = self.copy_fixture(Path(temp_dir))
            (trusted / "AGENTS.md").write_text(
                (trusted / "AGENTS.md").read_text(encoding="utf-8") + "\ntrusted drift\n",
                encoding="utf-8",
            )
            result = self.audit(trusted, base, candidate)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual("routine", result.risk_lane)
        self.assertEqual((), result.protected_changes)

    def test_trusted_workflow_rejects_job_level_permissions(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, base, candidate = self.copy_fixture(Path(temp_dir))
            workflow = trusted / ".github" / "workflows" / "openboa-governance-v2.yml"
            text = workflow.read_text(encoding="utf-8").replace(
                "    steps:\n",
                "    permissions:\n      contents: write\n    steps:\n",
                1,
            )
            workflow.write_text(text, encoding="utf-8")
            result = self.audit(trusted, base, candidate)
        self.assertFalse(result.ok)
        self.assertTrue(any("job-level permissions" in error for error in result.errors))

    def test_trusted_workflow_rejects_quoted_action_reference(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, base, candidate = self.copy_fixture(Path(temp_dir))
            workflow = trusted / ".github" / "workflows" / "openboa-governance-v2.yml"
            text = workflow.read_text(encoding="utf-8").replace(
                "        uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262",
                "        \"uses\": actions/checkout@main",
                1,
            )
            workflow.write_text(text, encoding="utf-8")
            result = self.audit(trusted, base, candidate)
        self.assertFalse(result.ok)
        self.assertTrue(any("full commit SHA" in error for error in result.errors))

    def test_protected_executable_bit_change_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            trusted, base, candidate = self.copy_fixture(Path(temp_dir))
            validator = candidate / "scripts" / "validate_governance.py"
            validator.chmod(validator.stat().st_mode ^ stat.S_IXUSR)
            result = self.audit(trusted, base, candidate)
        self.assertTrue(result.ok, result.errors)
        self.assertEqual("high", result.risk_lane)
        self.assertIn("scripts/validate_governance.py", result.protected_changes)


if __name__ == "__main__":
    unittest.main()
