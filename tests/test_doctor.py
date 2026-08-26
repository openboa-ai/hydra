from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
DOCTOR = ROOT / "plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/scripts/doctor.py"


class DoctorTests(unittest.TestCase):
    def test_json_is_read_only_and_reports_unknown_external_capabilities(self) -> None:
        before = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True, check=True).stdout
        result = subprocess.run([sys.executable, str(DOCTOR), str(ROOT), "--json"], text=True, capture_output=True, check=True)
        payload = json.loads(result.stdout)
        after = subprocess.run(["git", "status", "--porcelain"], cwd=ROOT, text=True, capture_output=True, check=True).stdout
        self.assertEqual(before, after)
        self.assertEqual("0.2.0", payload["contract"])
        self.assertEqual("unknown", payload["github_connector"])
        self.assertEqual("unknown", payload["scheduled_tasks"])

    def test_session_start_returns_bounded_context(self) -> None:
        event = {"hook_event_name": "SessionStart", "cwd": str(ROOT), "source": "startup"}
        result = subprocess.run([sys.executable, str(DOCTOR), "--hook"], input=json.dumps(event), text=True, capture_output=True, check=True)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["continue"])
        self.assertEqual("SessionStart", payload["hookSpecificOutput"]["hookEventName"])
        self.assertLess(len(payload["hookSpecificOutput"]["additionalContext"]), 2000)

    def test_post_compact_is_quiet_for_current_contract(self) -> None:
        event = {"hook_event_name": "PostCompact", "cwd": str(ROOT), "trigger": "auto"}
        result = subprocess.run([sys.executable, str(DOCTOR), "--hook"], input=json.dumps(event), text=True, capture_output=True, check=True)
        self.assertEqual("", result.stdout)

    def test_missing_path_reports_unavailable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            missing = Path(directory) / "missing"
            result = subprocess.run([sys.executable, str(DOCTOR), str(missing), "--json"], text=True, capture_output=True, check=True)
        self.assertEqual("unavailable", json.loads(result.stdout)["path_status"])


if __name__ == "__main__":
    unittest.main()
