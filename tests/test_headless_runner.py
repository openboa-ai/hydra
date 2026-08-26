from __future__ import annotations

import json
import fcntl
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/scripts/run_headless.py"


class HeadlessRunnerTests(unittest.TestCase):
    def test_relative_paths_are_refused(self) -> None:
        result = subprocess.run([sys.executable, str(RUNNER), "--project", ".", "--prompt", "prompt.md", "--state-dir", "/tmp/state", "--job", "test"], text=True, capture_output=True)
        self.assertEqual(2, result.returncode)

    def test_prompt_symlink_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = base / "repo"
            project.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            real = base / "real.md"
            real.write_text("prompt\n", encoding="utf-8")
            prompt = base / "prompt.md"
            prompt.symlink_to(real)
            result = subprocess.run([sys.executable, str(RUNNER), "--project", str(project), "--prompt", str(prompt), "--state-dir", str(base / "state"), "--job", "symlink"], text=True, capture_output=True)
        self.assertEqual(2, result.returncode)

    def test_active_job_lock_refuses_overlap(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = base / "repo"
            project.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            prompt = base / "prompt.md"
            prompt.write_text("prompt\n", encoding="utf-8")
            state = base / "state"
            state.mkdir(mode=0o700)
            lock_path = state / "locked.lock"
            with lock_path.open("a+", encoding="utf-8") as lock:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                result = subprocess.run([sys.executable, str(RUNNER), "--project", str(project), "--prompt", str(prompt), "--state-dir", str(state), "--job", "locked"], text=True, capture_output=True)
        self.assertEqual(3, result.returncode)
        self.assertIn("already running", result.stderr)

    def test_dirty_primary_checkout_is_refused_for_workspace_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = base / "repo"
            project.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=project, check=True)
            subprocess.run(["git", "config", "user.name", "Test"], cwd=project, check=True)
            (project / "tracked").write_text("one\n", encoding="utf-8")
            subprocess.run(["git", "add", "tracked"], cwd=project, check=True)
            subprocess.run(["git", "commit", "-qm", "initial"], cwd=project, check=True)
            (project / "tracked").write_text("dirty\n", encoding="utf-8")
            prompt = base / "prompt.md"
            prompt.write_text("Do bounded work.\n", encoding="utf-8")
            state = base / "state"
            result = subprocess.run([sys.executable, str(RUNNER), "--project", str(project), "--prompt", str(prompt), "--state-dir", str(state), "--job", "dirty", "--sandbox", "workspace-write"], text=True, capture_output=True)
        self.assertEqual(2, result.returncode)
        self.assertIn("clean", result.stderr)

    def test_read_only_run_records_jsonl_without_prompt_content(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = base / "repo"
            project.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            prompt = base / "prompt.md"
            prompt.write_text("PRIVATE-PROMPT-CONTENT\n", encoding="utf-8")
            state = base / "state"
            fake = base / "fake-codex"
            fake.write_text("#!/usr/bin/env python3\nimport pathlib,sys\nargs=sys.argv\nout=pathlib.Path(args[args.index('--output-last-message')+1])\nsys.stdin.read()\nout.write_text('done\\n', encoding='utf-8')\nprint('{\"type\":\"turn.completed\"}')\n", encoding="utf-8")
            fake.chmod(0o700)
            result = subprocess.run([sys.executable, str(RUNNER), "--project", str(project), "--prompt", str(prompt), "--state-dir", str(state), "--job", "readonly", "--codex-bin", str(fake)], text=True, capture_output=True, check=True)
            record = json.loads(result.stdout)
            events = Path(record["events"]).read_text(encoding="utf-8")
            final = Path(record["final"]).read_text(encoding="utf-8")
        self.assertNotIn("PRIVATE-PROMPT-CONTENT", events)
        self.assertEqual("done\n", final)
        self.assertIn('"openboa_event": "run.completed"', events)

    def test_timeout_is_attributable_and_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            project = base / "repo"
            project.mkdir()
            subprocess.run(["git", "init", "-q"], cwd=project, check=True)
            prompt = base / "prompt.md"
            prompt.write_text("prompt\n", encoding="utf-8")
            fake = base / "slow-codex"
            fake.write_text("#!/usr/bin/env python3\nimport time\ntime.sleep(10)\n", encoding="utf-8")
            fake.chmod(0o700)
            result = subprocess.run([sys.executable, str(RUNNER), "--project", str(project), "--prompt", str(prompt), "--state-dir", str(base / "state"), "--job", "timeout", "--timeout", "1", "--codex-bin", str(fake)], text=True, capture_output=True)
            record = json.loads(result.stdout)
            events = Path(record["events"]).read_text(encoding="utf-8")
        self.assertEqual(124, result.returncode)
        self.assertIn('"returncode": 124', events)


if __name__ == "__main__":
    unittest.main()
