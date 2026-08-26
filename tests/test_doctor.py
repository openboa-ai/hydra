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

    def test_repository_fsmonitor_command_is_not_executed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            repository = base / "repo"
            repository.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=repository, check=True)
            marker = base / "fsmonitor-ran"
            monitor = base / "fsmonitor"
            monitor.write_text(
                "#!/usr/bin/env python3\n"
                "from pathlib import Path\n"
                f"Path({str(marker)!r}).write_text('unsafe', encoding='utf-8')\n",
                encoding="utf-8",
            )
            monitor.chmod(0o700)
            subprocess.run(
                ["git", "config", "core.fsmonitor", str(monitor)], cwd=repository, check=True
            )

            result = subprocess.run(
                [sys.executable, str(DOCTOR), str(repository), "--json"],
                text=True, capture_output=True, check=True,
            )

            payload = json.loads(result.stdout)
            self.assertEqual("available", payload["git"])
            self.assertFalse(marker.exists())

    def test_oversized_agents_file_is_not_read(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = Path(directory) / "repo"
            repository.mkdir()
            agents = repository / "AGENTS.md"
            agents.write_bytes(b"x" * 131073)

            result = subprocess.run(
                [sys.executable, str(DOCTOR), str(repository), "--json"],
                text=True, capture_output=True, check=True,
            )

        payload = json.loads(result.stdout)
        self.assertEqual("available", payload["agents"])
        self.assertEqual("unreadable", payload["managed_contract"])


if __name__ == "__main__":
    unittest.main()
