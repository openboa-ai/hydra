"""P13 actual subprocess, Git, export and public non-disclosure oracles."""

import copy
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import shutil
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = "scripts/run_mvp_verification.py"
MANIFEST = "tests/fixtures/mvp/verification/cases.json"
CANARY = "PRIVATE_CANARY_DO_NOT_EXPORT"
EXCLUSIONS = sorted(["unselected_v1_requirements", "live_model_evaluation", "native_operation",
                     "verify_only_command", "trusted_ci_attestation"])


def digest(data):
    return "sha256:" + hashlib.sha256(data).hexdigest()


class Fixture:
    def __init__(self, root, body="pass", decorator="", extra=""):
        self.root = Path(root)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(("GIT_", "PYTHON"))}
        self.env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull,
                        GIT_AUTHOR_NAME="Evidence fixture", GIT_COMMITTER_NAME="Evidence fixture",
                        GIT_AUTHOR_EMAIL="fixture@example.invalid", GIT_COMMITTER_EMAIL="fixture@example.invalid",
                        PYTHONDONTWRITEBYTECODE="1")
        self.write(SCRIPT, (ROOT / SCRIPT).read_text())
        self.write("docs/contract.md", "# Acceptance\n\nPublic fixture contract.\n")
        self.write(".github/workflows/ci.yml", "name: Synthetic policy\n")
        self.write("tests/test_probe.py", "import unittest, os, subprocess, sys\nfrom pathlib import Path\n"
                   + extra + "\nclass Probe(unittest.TestCase):\n"
                   + (" " + decorator + "\n" if decorator else "")
                   + " def test_required(self):\n" + "\n".join("  " + line for line in body.splitlines()) + "\n")
        self.case = {"case_id": "VF-D01-FIXTURE", "requirements": [{"path": "docs/contract.md",
            "revision": digest((self.root / "docs/contract.md").read_bytes()), "section": "acceptance"}],
            "selectors": ["test_probe.Probe.test_required"],
            "fixture": "tests/fixtures/mvp/verification/probe.json"}
        self.manifest = {"schema_version": 1, "scope": "selected_source_d", "excluded": EXCLUSIONS,
                         "cases": [self.case]}
        self.json(self.case["fixture"], {"case_id": self.case["case_id"], "kind": "D", "scenarios": ["S01"],
             "scope": "Synthetic selected source evidence contract.", "preconditions": ["synthetic"],
             "events": ["execute"], "expected": ["actual required evidence"],
             "forbidden_effects": ["incomplete evidence accepted"], "oracle": "independent subprocess exit"})
        self.save()
        self.git("init", "--quiet", "--object-format=sha1")
        self.git("config", "commit.gpgsign", "false")
        self.git("add", ".")
        self.git("commit", "--quiet", "-m", "Synthetic evidence source")
        self.head = self.git("rev-parse", "HEAD")

    def write(self, name, value):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(value)

    def json(self, name, value):
        self.write(name, json.dumps(value, indent=2) + "\n")

    def save(self):
        self.json(MANIFEST, self.manifest)

    def git(self, *args):
        result = subprocess.run(["git", *args], cwd=self.root, env=self.env, capture_output=True, timeout=15)
        if result.returncode:
            raise AssertionError("Synthetic git setup failed")
        return result.stdout.decode().strip()

    def freeze(self):
        paths = [name for name in ("scripts", "tests", "docs", ".github", "hydra_sdlc")
                 if (self.root / name).exists()]
        self.git("add", "--", *paths)
        self.git("commit", "--quiet", "--allow-empty", "-m", "Freeze synthetic candidate")
        self.head = self.git("rev-parse", "HEAD")

    def run(self, *, output="report.json", validate=False, args=(), freeze=True, driver=None, timeout=20):
        if freeze and not validate:
            self.freeze()
        command = [sys.executable, "-I", "-c", driver, SCRIPT] if driver else [sys.executable, "-I", SCRIPT]
        argv = [*command, "--manifest", MANIFEST,
            "--validate-report" if validate else "--output", "artifacts/mvp-verification/" + output,
            "--checked-sha", self.head, *args]
        process = subprocess.Popen(argv, cwd=self.root, env=self.env, stdout=subprocess.PIPE,
                                   stderr=subprocess.PIPE)
        try:
            stdout, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            # Let the collector's existing supervisor reap its separate group
            # before the test fixture removes files. Retain the timeout failure.
            process.send_signal(signal.SIGTERM)
            try:
                process.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.communicate(timeout=5)
            raise
        result = subprocess.CompletedProcess(argv, process.returncode, stdout, stderr)
        assert CANARY.encode() not in result.stdout + result.stderr
        assert b"Traceback" not in result.stdout + result.stderr
        assert str(self.root).encode() not in result.stdout + result.stderr
        return result

    def report(self, name="report.json"):
        return json.loads((self.root / "artifacts/mvp-verification" / name).read_text())

    def add_missing_case(self):
        second = copy.deepcopy(self.case)
        second.update(case_id="VF-D01-MISSING", selectors=["test_probe.Probe.test_missing"],
                      fixture="tests/fixtures/mvp/verification/missing.json")
        value = json.loads((self.root / self.case["fixture"]).read_text())
        value["case_id"] = second["case_id"]
        self.json(second["fixture"], value)
        self.manifest["cases"].append(second)
        self.save()


class VerificationCollectorTests(unittest.TestCase):
    def fixture(self, **kwargs):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        return Fixture(directory.name, **kwargs)

    def test_normal_required_collection_export_and_same_revision_consumer_pass(self):
        fixture = self.fixture(body="Path('effect').write_text('once')\nself.assertEqual(2 + 2, 4)")
        args = ("--base-sha", "a" * 40, "--source-head", "b" * 40)
        self.assertEqual(fixture.run(args=args).returncode, 0)
        report = fixture.report()
        self.assertEqual(report["binding"]["candidate_head"], fixture.head)
        self.assertEqual(report["binding"]["source_head"], "b" * 40)
        self.assertEqual(report["binding"]["base_sha"], "a" * 40)
        row = report["results"][0]
        self.assertEqual((row["status"], row["observed"][0]["executed"], row["observed"][0]["completed"]), ("PASS", 1, 1))
        self.assertEqual(report["excluded"], EXCLUSIONS)
        self.assertEqual(fixture.run(validate=True, args=args).returncode, 0)

    def test_report_python_floor_preserves_supported_versions_without_rerun(self):
        fixture = self.fixture(body="with Path('effect').open('a') as stream: stream.write('once')")
        self.assertEqual(fixture.run().returncode, 0)
        original = fixture.report()
        versions = (("3.13.9", 2), ("3.14.0", 0), ("3.9.99", 2),
                    ("3.14.2", 0), ("2.99.99", 2), ("3.15.0", 0),
                    ("4.0.0", 0), ("3.14", 2), ("3.14.0rc1", 2))
        target = fixture.root / "artifacts/mvp-verification/report.json"
        for version, expected in versions:
            with self.subTest(python=version):
                report = copy.deepcopy(original)
                report["results"][0]["environment"]["python"] = version
                fixture.json("artifacts/mvp-verification/report.json", report)
                saved = target.read_bytes()
                result = fixture.run(validate=True)
                self.assertEqual(result.returncode, expected)
                self.assertEqual(json.loads(result.stdout),
                    {"status": "PASS", "reason": "passed"} if expected == 0 else
                    {"status": "FAIL", "reason": "invalid_input"})
                self.assertEqual(target.read_bytes(), saved)
                self.assertEqual((fixture.root / "effect").read_text(), "once")
        fixture.json("artifacts/mvp-verification/report.json", original)
        self.assertEqual(fixture.run(validate=True).returncode, 0)
        self.assertEqual((fixture.root / "effect").read_text(), "once")


    def test_versioned_manifest_executes_five_actual_source_methods(self):
        fixture = self.fixture()
        shutil.copytree(ROOT / "hydra_sdlc", fixture.root / "hydra_sdlc",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        for name in ("test_project.py", "test_repository_intake_identity.py", "test_runner.py"):
            fixture.write("tests/" + name, (ROOT / "tests" / name).read_text())
        manifest = json.loads((ROOT / MANIFEST).read_text())
        fixture.json(MANIFEST, manifest)
        for case in manifest["cases"]:
            fixture.write(case["fixture"], (ROOT / case["fixture"]).read_text())
            for reference in case["requirements"]:
                fixture.write(reference["path"], (ROOT / reference["path"]).read_text())
        result = fixture.run()
        self.assertEqual(result.returncode, 0, result.stdout)
        rows = fixture.report()["results"]
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(len(row["observed"]) for row in rows), 5)
        self.assertTrue(all(row["status"] == "PASS" for row in rows))

    def test_required_skip_expected_failure_unexpected_success_error_and_subtest_fail_are_not_green(self):
        cases = [dict(decorator="@unittest.skip('" + CANARY + "')"),
                 dict(decorator="@unittest.expectedFailure", body="self.fail('" + CANARY + "')"),
                 dict(decorator="@unittest.expectedFailure"),
                 dict(body="raise RuntimeError('" + CANARY + "')"),
                 dict(body="with self.subTest(secret='" + CANARY + "'):\n self.assertEqual(1, 2)"),
                 dict(body="self.fail('" + CANARY + "')")]
        for kwargs in cases:
            with self.subTest(kind=sorted(kwargs)):
                fixture = self.fixture(**kwargs)
                self.assertNotEqual(fixture.run().returncode, 0)
                self.assertNotEqual(fixture.report()["results"][0]["status"], "PASS")
                self.assertNotIn(CANARY, json.dumps(fixture.report()))

    def test_class_setup_skip_and_error_are_not_executed(self):
        for exception in ("unittest.SkipTest", "RuntimeError"):
            fixture = self.fixture()
            path = fixture.root / "tests/test_probe.py"
            path.write_text(path.read_text() + " @classmethod\n def setUpClass(cls):\n  raise " + exception + "('" + CANARY + "')\n")
            self.assertNotEqual(fixture.run().returncode, 0)
            self.assertEqual(fixture.report()["results"][0]["observed"][0]["executed"], 0)

    def test_missing_zero_duplicate_callable_and_import_failure_never_satisfy_collection(self):
        for mode in ("missing", "zero", "duplicate", "callable", "import", "load_zero"):
            with self.subTest(mode=mode):
                fixture = self.fixture()
                if mode == "missing":
                    fixture.case["selectors"] = ["test_probe.Probe.test_missing"]
                elif mode == "zero":
                    fixture.manifest["cases"] = []
                elif mode == "duplicate":
                    fixture.case["selectors"] *= 2
                elif mode == "callable":
                    fixture.write("tests/test_probe.py", "def Probe():\n raise RuntimeError('" + CANARY + "')\n")
                elif mode == "import":
                    fixture.write("tests/test_probe.py", "raise RuntimeError('" + CANARY + "')\n")
                else:
                    path = fixture.root / "tests/test_probe.py"
                    path.write_text(path.read_text() + "\nProbe.test_required = None\n")
                fixture.save()
                self.assertNotEqual(fixture.run().returncode, 0)

    def test_missing_requirement_evidence_fails_only_that_case_not_complete_control(self):
        fixture = self.fixture()
        fixture.add_missing_case()
        self.assertNotEqual(fixture.run().returncode, 0)
        self.assertEqual([row["status"] for row in fixture.report()["results"]], ["PASS", "NOT RUN"])

    def test_output_from_import_python_fd_child_and_exception_is_never_public(self):
        payload = "print('" + CANARY + "' * 10000)\nos.write(2, b'" + CANARY + "')\n"
        fixture = self.fixture(extra=payload, body=payload +
            "subprocess.run([sys.executable, '-c', \"print('" + CANARY + "')\"])\nself.fail('" + CANARY + "')")
        self.assertNotEqual(fixture.run().returncode, 0)
        self.assertNotIn(CANARY, json.dumps(fixture.report()))

    def test_output_from_test_shutdown_handlers_is_never_public(self):
        fixture = self.fixture(extra="import atexit\n"
            "atexit.register(lambda: os.write(2, b'" + CANARY + "'))\n"
            "atexit.register(lambda: print('" + CANARY + "'))")
        self.assertEqual(fixture.run().returncode, 0)

    def test_interruption_preserves_effect_without_retry_and_marks_remaining_case(self):
        fixture = self.fixture(body="Path('effect').write_text('once')\nraise KeyboardInterrupt('" + CANARY + "')")
        fixture.add_missing_case()
        self.assertNotEqual(fixture.run().returncode, 0)
        self.assertEqual((fixture.root / "effect").read_text(), "once")
        self.assertEqual(fixture.report()["results"][1]["status"], "NOT RUN")

    def test_occupied_output_prevents_execution_and_preserves_prior_evidence(self):
        for kind in ('file', 'directory', 'fifo'):
            with self.subTest(kind=kind):
                fixture = self.fixture(body="with Path('effect').open('a') as stream: stream.write('once')")
                target = fixture.root / 'artifacts/mvp-verification/report.json'
                target.parent.mkdir(parents=True)
                if kind == 'file':
                    target.write_text('prior evidence')
                elif kind == 'directory':
                    target.mkdir()
                else:
                    os.mkfifo(target)
                result = fixture.run()
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse((fixture.root / 'effect').exists(), 'Occupied output still executed a selector')
                self.assertEqual(json.loads(result.stdout)['reason'], 'invalid_input')
                if kind == 'file':
                    self.assertEqual(target.read_text(), 'prior evidence')
                elif kind == 'directory':
                    self.assertTrue(target.is_dir())
                else:
                    import stat
                    self.assertTrue(stat.S_ISFIFO(target.stat().st_mode))
        control = self.fixture(body="with Path('effect').open('a') as stream: stream.write('once')")
        self.assertEqual(control.run().returncode, 0)
        saved = (control.root / 'artifacts/mvp-verification/report.json').read_bytes()
        self.assertEqual((control.root / 'effect').read_text(), 'once')
        self.assertNotEqual(control.run().returncode, 0)
        self.assertEqual((control.root / 'effect').read_text(), 'once', 'Same-name retry repeated an existing effect')
        self.assertEqual((control.root / 'artifacts/mvp-verification/report.json').read_bytes(), saved)

    def test_revision_and_corrupt_artifact_cannot_be_reused_or_rerun_effects(self):
        for mode in ("head", "source", "base", "spec", "policy", "fixture", "extra", "status", "count"):
            with self.subTest(mode=mode):
                fixture = self.fixture(body="with Path('effect').open('a') as stream: stream.write('once')")
                self.assertEqual(fixture.run().returncode, 0)
                report = fixture.report()
                if mode in {"head", "source", "base"}:
                    report["binding"][{"head": "candidate_head", "source": "source_head", "base": "base_sha"}[mode]] = "c" * 40
                elif mode == "spec":
                    fixture.write("docs/contract.md", "Changed requirement\n")
                elif mode == "policy":
                    fixture.write(".github/workflows/ci.yml", "Changed policy\n")
                elif mode == "fixture":
                    fixture.write(fixture.case["fixture"], "{}")
                elif mode == "extra":
                    report["results"][0]["raw"] = CANARY
                elif mode == "status":
                    report["results"][0]["status"] = "NOT RUN"
                else:
                    report["results"][0]["observed"][0]["executed"] = 0
                fixture.json("artifacts/mvp-verification/report.json", report)
                self.assertNotEqual(fixture.run(validate=True).returncode, 0)
                self.assertEqual((fixture.root / "effect").read_text(), "once")

    def test_source_change_during_execution_invalidates_export(self):
        fixture = self.fixture(body="Path('docs/contract.md').write_text('changed')")
        self.assertNotEqual(fixture.run().returncode, 0)
        self.assertFalse((fixture.root / "artifacts/mvp-verification/report.json").exists())

    def test_checked_revision_mismatch_before_any_effect(self):
        fixture = self.fixture(body="Path('effect').write_text('forbidden')")
        self.assertNotEqual(fixture.run(args=("--checked-sha", "d" * 40)).returncode, 0)
        self.assertFalse((fixture.root / "effect").exists())

    def test_dirty_source_at_start_cannot_claim_committed_candidate(self):
        fixture = self.fixture()
        path = fixture.root / "tests/test_probe.py"
        path.write_text(path.read_text().replace("  pass", "  Path('effect').write_text('forbidden')"))
        self.assertNotEqual(fixture.run(freeze=False).returncode, 0)
        self.assertFalse((fixture.root / "effect").exists())

    def test_untracked_python_shadow_cannot_claim_committed_candidate(self):
        fixture = self.fixture(body="Path('effect').write_text('forbidden')")
        fixture.write("tests/shadow.py", "# Uncommitted source\n")
        self.assertNotEqual(fixture.run(freeze=False).returncode, 0)
        self.assertFalse((fixture.root / "effect").exists())

    def test_startup_module_shadow_cannot_execute_before_rejection(self):
        fixture = self.fixture()
        fixture.write("scripts/argparse.py", "from pathlib import Path\n"
                      "Path('effect').write_text('forbidden')\nprint('" + CANARY + "')\n")
        self.assertNotEqual(fixture.run(freeze=False).returncode, 0)
        self.assertFalse((fixture.root / "effect").exists())
        result = subprocess.run([sys.executable, SCRIPT, "--output", "artifacts/mvp-verification/report.json"],
            cwd=fixture.root, env=fixture.env, capture_output=True, timeout=20)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(CANARY.encode(), result.stdout + result.stderr)
        self.assertEqual(json.loads(result.stdout)["reason"], "isolated_python_required")
        self.assertFalse((fixture.root / "effect").exists())

    def test_index_hints_cannot_hide_dirty_bytes_from_candidate_binding(self):
        for flag in ("--assume-unchanged", "--skip-worktree"):
            with self.subTest(flag=flag):
                fixture = self.fixture()
                fixture.git("update-index", flag, "tests/test_probe.py")
                path = fixture.root / "tests/test_probe.py"
                path.write_text(path.read_text().replace("  pass", "  Path('effect').write_text('forbidden')"))
                self.assertNotEqual(fixture.run(freeze=False).returncode, 0)
                self.assertFalse((fixture.root / "effect").exists())

    def test_passing_rows_from_two_failed_same_revision_runs_cannot_be_combined(self):
        fixture = self.fixture(body="self.assertNotEqual(os.environ.get('FAILING_CASE'), 'first')")
        path = fixture.root / "tests/test_probe.py"
        path.write_text(path.read_text() + " def test_second(self):\n"
                        "  self.assertNotEqual(os.environ.get('FAILING_CASE'), 'second')\n")
        fixture.add_missing_case()
        fixture.manifest["cases"][1]["selectors"] = ["test_probe.Probe.test_second"]
        fixture.save()
        fixture.freeze()
        fixture.env["FAILING_CASE"] = "first"
        self.assertNotEqual(fixture.run(output="first.json", freeze=False).returncode, 0)
        first = fixture.report("first.json")
        fixture.env["FAILING_CASE"] = "second"
        self.assertNotEqual(fixture.run(output="second.json", freeze=False).returncode, 0)
        second = fixture.report("second.json")
        self.assertEqual(first["binding"], second["binding"])
        mixed = copy.deepcopy(first)
        mixed["results"][0] = second["results"][0]
        self.assertTrue(all(row["status"] == "PASS" for row in mixed["results"]))
        fixture.json("artifacts/mvp-verification/mixed.json", mixed)
        self.assertNotEqual(fixture.run(validate=True, output="mixed.json").returncode, 0)
        del fixture.env["FAILING_CASE"]
        self.assertEqual(fixture.run(output="complete.json", freeze=False).returncode, 0)
        self.assertEqual(fixture.run(validate=True, output="complete.json").returncode, 0)

    def test_symlink_output_parent_and_target_preserve_foreign_files(self):
        for target in (False, True):
            fixture = self.fixture(body="Path('effect').write_text('forbidden')")
            directory = tempfile.TemporaryDirectory()
            self.addCleanup(directory.cleanup)
            outside = Path(directory.name)
            (outside / "report.json").write_text("owned elsewhere")
            if target:
                (fixture.root / "artifacts/mvp-verification").mkdir(parents=True)
                (fixture.root / "artifacts/mvp-verification/report.json").symlink_to(outside / "report.json")
            else:
                (fixture.root / "artifacts").symlink_to(outside, target_is_directory=True)
            self.assertNotEqual(fixture.run().returncode, 0)
            self.assertFalse((fixture.root / "effect").exists())
            self.assertEqual((outside / "report.json").read_text(), "owned elsewhere")

    def test_manifest_shell_or_unknown_fields_are_not_authority(self):
        fixture = self.fixture(body="Path('effect').write_text('forbidden')")
        fixture.case["command"] = "touch forbidden"
        fixture.save()
        self.assertNotEqual(fixture.run().returncode, 0)
        self.assertFalse((fixture.root / "effect").exists())

    def test_actual_gate_oracles_detect_isolated_defects_and_always_deny(self):
        body = ("from hydra_sdlc.project import load_project, ProjectError, gate_checks\n"
                "from test_project import ConfigGitHub, TOML, config, observation, HEAD, BASE\n"
                "self.assertEqual(load_project(ConfigGitHub(), 'example/product')['repository_id'], 123)\n"
                "with self.assertRaises(ProjectError):\n"
                " load_project(ConfigGitHub(TOML.replace('repository_id = 123', 'repository_id = 999')), 'example/product')\n"
                "self.assertEqual(gate_checks(config(), observation(), HEAD), [])\n"
                "unknown = observation(); unknown['checks'][0]['app']['id'] = 999\n"
                "self.assertTrue(gate_checks(config(), unknown, HEAD))\n"
                "stale = observation(); stale['runs'][0]['head_sha'] = BASE\n"
                "self.assertTrue(gate_checks(config(), stale, HEAD))")
        defects = {"control": "", "identity": (
            "\n_real_require = _require\ndef _require(condition, message):\n"
            " return _real_require(True if message == 'Repository identity mismatch' else condition, message)\n"),
            "unknown": ("\n_real_gate = gate_checks\ndef gate_checks(cfg, obs, sha, **kw):\n"
                         " return [] if obs['checks'][0]['app']['id'] == 999 else _real_gate(cfg, obs, sha, **kw)\n"),
            "stale": ("\n_real_gate = gate_checks\ndef gate_checks(cfg, obs, sha, **kw):\n"
                       " return [] if obs['runs'][0]['head_sha'] != sha else _real_gate(cfg, obs, sha, **kw)\n"),
            "always_deny": "\ndef gate_checks(*args, **kwargs): return ['denied']\n"}
        for name, change in defects.items():
            with self.subTest(defect=name):
                fixture = self.fixture(body=body)
                fixture.write("hydra_sdlc/__init__.py", "")
                fixture.write("hydra_sdlc/project.py", (ROOT / "hydra_sdlc/project.py").read_text() + change)
                fixture.write("tests/test_project.py", (ROOT / "tests/test_project.py").read_text())
                result = fixture.run()
                self.assertEqual(result.returncode == 0, name == "control")
                if name != "control":
                    self.assertEqual(fixture.report()["results"][0]["observed"][0]["reasons"], ["test_failure"])


def ci_script(text):
    marker = "      - name: Collect selected source verification evidence\n"
    if text.count(marker) != 1:
        raise AssertionError("Missing unique collection step")
    step = text.split(marker)[1].split("      - name:", 1)[0]
    run = step.split("        run: |\n", 1)[1]
    return "\n".join(line[10:] for line in run.splitlines()) + "\n"


def assert_ci_contract(text):
    """Bounded regression tripwire, backed by actionlint and independent CI review."""
    required = ["permissions:\n  contents: read\n", "timeout-minutes: 10", "PYTHONDONTWRITEBYTECODE: '1'", "python: ['3.14.2']",
        "python3 -m pip install '.[mcp]'", "python3 -m unittest discover -s tests -v",
        "uses: actions/upload-artifact@cf430e030ddbb5b0abf93d22962f4752f3646cd9",
        "path: artifacts/mvp-verification/result.json", "if-no-files-found: error",
        "include-hidden-files: false", "overwrite: false", "--checked-sha \"$CHECKED_SHA\"",
        "python3 -I scripts/run_mvp_verification.py",
        "SOURCE_HEAD: ${{ github.event.pull_request.head.sha || github.sha }}",
        "CHECKED_SHA: ${{ github.sha }}"]
    if not all(item in text for item in required):
        raise AssertionError("Required CI contract removed")
    for forbidden in ("continue-on-error", "contents: write", "secrets.", "pull_request_target", "|| true"):
        if forbidden in text:
            raise AssertionError("CI authority or gate changed")
    if text.count("  mac-app:\n") != 1:
        raise AssertionError("Mac job removed")
    suffix = "  mac-app:\n" + text.split("  mac-app:\n", 1)[1]
    if hashlib.sha256(suffix.encode()).hexdigest() != "91b45a94c8cdbea92ce97b6e6e61d6e80722e09fa5342bc50196a65e7920c79e":
        raise AssertionError("Existing Mac or trusted hygiene policy changed")


class VerificationProcessBoundaryTests(unittest.TestCase):
    def test_early_worker_setup_os_failures_keep_environment_control(self):
        for fresh in (False, True):
            control = self.fixture(body="Path('effect').write_text('once')")
            if fresh:
                control.write(SCRIPT, (control.root / SCRIPT).read_text() + '\ndef _fork_available(): return False\n')
            self.assertEqual(control.run().returncode, 0)
            self.assertEqual((control.root / 'effect').read_text(), 'once')
            for stage in ('quiet', 'install_termination_handler'):
                with self.subTest(fresh=fresh, stage=stage):
                    fixture = self.fixture(body="Path('effect').write_text('forbidden')")
                    source = (fixture.root / SCRIPT).read_text()
                    if fresh:
                        source += '\ndef _fork_available(): return False\n'
                    source += ("\n_original_setup=" + stage + "\n"
                        "def " + stage + "(*args,**kwargs):\n"
                        " marker=Path.cwd()/'worker_setup_seen'\n"
                        " if marker.exists(): raise OSError('synthetic bootstrap failure')\n"
                        " marker.write_text('setup')\n"
                        " return _original_setup(*args,**kwargs)\n")
                    fixture.write(SCRIPT, source)
                    result = fixture.run()
                    self.assertEqual(json.loads(result.stdout), {'status':'BLOCKED','reason':'environment_unavailable'},
                        'Early infrastructure failure became a selected test failure')
                    self.assertNotEqual(result.returncode, 0)
                    self.assertFalse((fixture.root / 'effect').exists())
                    self.assertFalse((fixture.root / 'artifacts/mvp-verification/report.json').exists())

    fixture = VerificationCollectorTests.fixture

    def test_late_binary_resolution_cannot_replace_pinned_source(self):
        import importlib.machinery
        import math
        suffix = next(s for s in importlib.machinery.EXTENSION_SUFFIXES if math.__file__.endswith(s))
        for fresh_exec in (False, True):
            for binary in ('bytecode', 'extension'):
                with self.subTest(fresh_exec=fresh_exec, binary=binary):
                    name = 'helper' if binary == 'bytecode' else 'math'
                    check = 'helper.VALUE' if binary == 'bytecode' else "hasattr(math, 'pi')"
                    fixture = self.fixture(body="sys.modules.pop(" + repr(name) + ", None)\nimport " + name +
                                           "\nself.assertTrue(" + check + ")\nPath('binary_import_effect').touch()")
                    fixture.write('tests/' + name + '.py', 'VALUE = False\n')
                    self.assertEqual(fixture.run(output='normal.json').returncode, 1)
                    hook = '''
original_emit=_emit_selector
def late_binary(root,selector,descriptor):
    import py_compile,shutil
    directory=root/'tests'
    mode=directory.stat().st_mode & 0o777
    original=directory/(NAME+'.py')
    target=directory/(NAME+SUFFIX)
    with tempfile.TemporaryDirectory(prefix='binary-source-fixture-') as temporary:
        temporary=Path(temporary)
        os.chmod(directory,mode|0o200)
        if BINARY=='bytecode':
            fake=temporary/'helper.py';fake.write_text('VALUE = True\\n')
            compiled=temporary/'helper.pyc'
            py_compile.compile(str(fake),cfile=str(compiled),doraise=True)
            original.rename(temporary/'original.py')
            shutil.copyfile(compiled,target)
        else:
            shutil.copyfile(EXTENSION,target)
        os.chmod(directory,mode)
        try: return original_emit(root,selector,descriptor)
        finally:
            os.chmod(directory,mode|0o200)
            target.unlink(missing_ok=True)
            if BINARY=='bytecode': (temporary/'original.py').rename(original)
            os.chmod(directory,mode)
_emit_selector=late_binary
'''
                    values = {'NAME': name, 'SUFFIX': '.pyc' if binary == 'bytecode' else suffix,
                              'BINARY': binary, 'EXTENSION': math.__file__}
                    prefix = '\n' + '\n'.join(key + '=' + repr(value) for key, value in values.items()) + '\n'
                    if fresh_exec:
                        prefix += '\ndef _fork_available(): return False\n'
                    fixture.write(SCRIPT, (fixture.root / SCRIPT).read_text() + prefix + hook)
                    result = fixture.run(output='fault.json')
                    self.assertNotEqual(result.returncode, 0, 'A late binary loader substituted unpinned source')
                    self.assertFalse((fixture.root / 'binary_import_effect').exists())

    def test_read_only_validation_consumes_pinned_fixture_revision(self):
        fixture = self.fixture()
        self.assertEqual(fixture.run().returncode, 0)
        self.assertEqual(fixture.run(validate=True).returncode, 0)
        raw = (fixture.root / fixture.case['fixture']).read_bytes()
        changed = raw.replace(b'Synthetic', b'SynthetiX')
        self.assertNotEqual(raw, changed)
        self.assertEqual(len(raw), len(changed))
        report = fixture.report()
        report['results'][0]['fixture_revision'] = digest(changed)
        fixture.json('artifacts/mvp-verification/report.json', report)
        saved = (fixture.root / 'artifacts/mvp-verification/report.json').read_bytes()
        driver = '''import os,runpy,sys
from pathlib import Path
script=sys.argv.pop(1)
scope=runpy.run_path(script)
scope=scope['main'].__globals__
original=scope['validate']
def transient(report,root,manifest,pins,*args,**kwargs):
    target=root/manifest['cases'][0]['fixture']
    raw=target.read_bytes();changed=raw.replace(b'Synthetic',b'SynthetiX')
    mode=target.stat().st_mode & 0o777
    os.chmod(target,mode|0o200);target.write_bytes(changed);os.chmod(target,mode)
    try: return original(report,root,manifest,pins,*args,**kwargs)
    finally:
        os.chmod(target,mode|0o200);target.write_bytes(raw);os.chmod(target,mode)
scope['validate']=transient
raise SystemExit(scope['main']())
'''
        result = fixture.run(validate=True, driver=driver)
        self.assertNotEqual(result.returncode, 0, 'Transient fixture bytes validated a counterfeit revision')
        self.assertEqual((fixture.root / fixture.case['fixture']).read_bytes(), raw)
        self.assertEqual((fixture.root / 'artifacts/mvp-verification/report.json').read_bytes(), saved)

    def test_transient_worker_script_substitution_cannot_manufacture_pass(self):
        fixture = self.fixture(body="self.fail('committed failure')")
        driver = '''import os,runpy,subprocess,sys
from pathlib import Path
original_popen=subprocess.Popen
def changed_popen(argv,*args,**kwargs):
    if (isinstance(argv,list) and len(argv)>4 and argv[0]==sys.executable
            and argv[1:3]==['-I','-c'] and argv[-1].endswith('scripts/run_mvp_verification.py')):
        target=Path(argv[-1]);data=target.read_bytes();mode=target.stat().st_mode & 0o777
        extra="\\n_source=Path(__file__)\\nos.chmod(_source,"+repr(mode|0o200)+")\\n_source.write_bytes("+repr(data)+")\\nos.chmod(_source,"+repr(mode)+")\\n"
        extra+="_original_execute=execute\\ndef execute(root,manifest,pins):\\n report=_original_execute(root,manifest,pins)\\n for row in report['results']:\\n  row['status']='PASS';row['remaining_owner']=None\\n  for item in row['observed']:\\n   item.update(collected=1,executed=1,completed=1,reasons=['passed'])\\n Path('bootstrap_effect').touch()\\n return report\\n"
        os.chmod(target,mode|0o200);target.write_bytes(data+extra.encode());os.chmod(target,mode)
        process=original_popen(argv,*args,**kwargs)
        original_wait=process.wait
        def wait(*args,**kwargs):
            try: return original_wait(*args,**kwargs)
            finally:
                os.chmod(target,mode|0o200);target.write_bytes(data);os.chmod(target,mode)
        process.wait=wait
        return process
    return original_popen(argv,*args,**kwargs)
subprocess.Popen=changed_popen
script=sys.argv.pop(1)
runpy.run_path(script,run_name='__main__')
'''
        result = fixture.run(driver=driver)
        self.assertNotEqual(result.returncode, 0, 'Substituted collector manufactured committed PASS')
        self.assertFalse((fixture.root / 'bootstrap_effect').exists())

    def test_selected_source_profile_rejects_tracked_binary_importables(self):
        import importlib.machinery
        import py_compile
        for extension in ('.pyc', importlib.machinery.EXTENSION_SUFFIXES[0]):
            with self.subTest(extension=extension):
                fixture = self.fixture(body="Path('binary_effect').touch()")
                if extension == '.pyc':
                    fixture.write('tests/helper.py', 'VALUE = True\n')
                    py_compile.compile(str(fixture.root / 'tests/helper.py'),
                                       cfile=str(fixture.root / 'tests/helper.pyc'), doraise=True)
                    (fixture.root / 'tests/helper.py').unlink()
                else:
                    fixture.write('tests/helper' + extension, 'not a qualified source import')
                result = fixture.run()
                self.assertNotEqual(result.returncode, 0, 'A binary repository importable entered the source-only profile')
                self.assertFalse((fixture.root / 'binary_effect').exists())

    def test_fresh_worker_metadata_does_not_shrink_the_accepted_manifest(self):
        fixture = self.fixture()
        method = 'test_' + 'x' * 230000
        probe = fixture.root / 'tests/test_probe.py'
        probe.write_text(probe.read_text().replace('test_required', method))
        fixture.case['selectors'] = ['test_probe.Probe.' + method]
        fixture.save()
        self.assertLess((fixture.root / MANIFEST).stat().st_size, 262144)
        for number in range(1000):
            fixture.write('tests/support/' + str(number).zfill(4) + '_' + 's' * 210 + '.py', '')
        fixture.write(SCRIPT, (fixture.root / SCRIPT).read_text() + '\ndef _fork_available(): return False\n')
        result = fixture.run(timeout=120)
        self.assertEqual(result.returncode, 0, 'Source metadata consumed the accepted selector request budget')
        self.assertEqual(fixture.report()['results'][0]['observed'][0]['reasons'], ['passed'])
        self.assertEqual(fixture.run(validate=True, timeout=120).returncode, 0)

    def test_late_final_signal_keeps_a_structured_frozen_status(self):
        for signum in (signal.SIGTERM, signal.SIGINT):
            with self.subTest(signum=signum):
                fixture = self.fixture()
                driver = '''import os,runpy,signal,sys
original_write=os.write
fired=[False]
def write(fd,data):
    if not fired[0] and b'"reason"' in data and b'"status"' in data:
        fired[0]=True
        os.kill(os.getpid(),SIGNUM)
    return original_write(fd,data)
os.write=write
script=sys.argv.pop(1)
runpy.run_path(script,run_name='__main__')
'''.replace('SIGNUM', str(int(signum)))
                result = fixture.run(driver=driver, args=('--checked-sha', '0' * 40))
                self.assertTrue(result.stdout.strip().startswith(b'{'), 'Late interruption lost the terminal JSON')
                self.assertEqual(json.loads(result.stdout), {'status': 'FAIL', 'reason': 'invalid_input'})
                self.assertEqual(result.returncode, 2)

    def test_numeric_selected_exit_codes_are_failures_and_do_not_suppress_later_work(self):
        for fresh_exec in (False, True):
            for at_shutdown in (False, True):
                for code in (75, 130, 143):
                    with self.subTest(fresh_exec=fresh_exec, at_shutdown=at_shutdown, code=code):
                        body = ("import atexit\natexit.register(lambda: os._exit(" + str(code) + "))"
                                if at_shutdown else 'os._exit(' + str(code) + ')')
                        fixture = self.fixture(body=body)
                        probe = fixture.root / 'tests/test_probe.py'
                        probe.write_text(probe.read_text() + " def test_later(self):\n  Path('later_effect').touch()\n")
                        fixture.case['selectors'].append('test_probe.Probe.test_later')
                        fixture.save()
                        if fresh_exec:
                            fixture.write(SCRIPT, (fixture.root / SCRIPT).read_text() + '\ndef _fork_available(): return False\n')
                        result = fixture.run()
                        self.assertEqual(result.returncode, 1, 'A selected numeric exit was mistaken for supervisor control')
                        observed = fixture.report()['results'][0]['observed']
                        self.assertEqual(observed[0]['reasons'], ['test_error'])
                        self.assertEqual(observed[1]['reasons'], ['passed'])
                        self.assertTrue((fixture.root / 'later_effect').exists())

    def test_single_use_and_helper_imports_read_pinned_bytes(self):
        for fresh_exec in (False, True):
            for helper in (False, True):
                with self.subTest(fresh_exec=fresh_exec, helper=helper):
                    body = ("import helper\nself.assertTrue(helper.VALUE)" if helper
                            else "self.fail('committed')")
                    fixture = self.fixture(body=body + "\nPath('import_effect').touch()")
                    if helper:
                        fixture.write('tests/helper.py', 'VALUE = False\n')
                    hook = '''
original_emit=_emit_selector
def swapped_emit(root,selector,descriptor):
    target=root/TARGET
    original=target.read_bytes()
    changed=original.replace(BEFORE,AFTER)
    assert changed!=original and len(changed)==len(original)
    mode=target.stat().st_mode & 0o777
    original_get_data=importlib.machinery.SourceFileLoader.get_data
    def get_data(loader,path):
        if Path(path)!=target: return original_get_data(loader,path)
        os.chmod(target,mode|0o200)
        target.write_bytes(changed)
        os.chmod(target,mode)
        try: return original_get_data(loader,path)
        finally:
            os.chmod(target,mode|0o200)
            target.write_bytes(original)
            os.chmod(target,mode)
    importlib.machinery.SourceFileLoader.get_data=get_data
    return original_emit(root,selector,descriptor)
_emit_selector=swapped_emit
'''
                    before = b'VALUE = False' if helper else b"self.fail('committed')"
                    after = b'VALUE = True ' if helper else b'pass' + b' ' * (len(before) - 4)
                    hook = ("\nTARGET=" + repr('tests/helper.py' if helper else 'tests/test_probe.py') +
                            "\nBEFORE=" + repr(before) + "\nAFTER=" + repr(after) + "\n" + hook)
                    if fresh_exec:
                        hook += '\ndef _fork_available(): return False\n'
                    fixture.write(SCRIPT, (fixture.root / SCRIPT).read_text() + hook)
                    result = fixture.run()
                    self.assertNotEqual(result.returncode, 0, 'Transient import bytes became committed PASS')
                    self.assertFalse((fixture.root / 'import_effect').exists(), 'Substituted import executed')

    def test_pinned_imports_preserve_normal_helpers_and_internal_symlinks(self):
        for fresh_exec in (False, True):
            for layout in ('regular', 'directory_link'):
                with self.subTest(fresh_exec=fresh_exec, layout=layout):
                    fixture = self.fixture(body="from helper import VALUE\nself.assertTrue(VALUE)\nPath('import_effect').touch()")
                    if layout == 'directory_link':
                        fixture.write('tests/pkg/__init__.py', '')
                        fixture.write('tests/pkg/value.py', 'VALUE = True\n')
                        (fixture.root / 'tests/linked').symlink_to('pkg', target_is_directory=True)
                        fixture.write('tests/helper.py', 'from linked.value import VALUE\n')
                    else:
                        fixture.write('tests/helper.py', 'VALUE = True\n')
                    if fresh_exec:
                        fixture.write(SCRIPT, (fixture.root / SCRIPT).read_text() + '\ndef _fork_available(): return False\n')
                    self.assertEqual(fixture.run().returncode, 0)
                    self.assertTrue((fixture.root / 'import_effect').exists())
                    self.assertEqual(fixture.run(validate=True).returncode, 0)

    def test_compiled_selector_bytes_cannot_be_substituted_between_snapshot_checks(self):
        def repeated(body):
            fixture = self.fixture(body=body)
            fixture.write('tests/test_probe.py', (fixture.root / 'tests/test_probe.py').read_text() +
                " def test_later(self):\n  with Path('effect').open('a') as f: f.write('once\\n')\n")
            fixture.case['selectors'].append('test_probe.Probe.test_later')
            fixture.save()
            return fixture
        normal = repeated('self.assertEqual(2 + 2, 4)')
        self.assertEqual(normal.run().returncode, 0)
        self.assertEqual(normal.run(validate=True).returncode, 0)
        self.assertEqual((normal.root / 'effect').read_text().splitlines(), ['once'])
        fixture = repeated("self.fail('committed')")
        hook = '''
phase=[False]
target=[None]
original_read=Path.read_bytes
original_fdopen=os.fdopen
original_compile=_compile_selected
saved=[None,None,None]
def replace_source(data):
    os.chmod(target[0],saved[2]|0o200)
    target[0].write_bytes(data)
    os.chmod(target[0],saved[2])
def swapped_read(read):
    replace_source(saved[1])
    try: return read()
    finally: replace_source(saved[0])
def changed_read(path):
    if phase[0] and path==target[0]:
        return swapped_read(lambda: original_read(path))
    return original_read(path)
class ChangedStream:
    def __init__(self,stream): self.stream=stream
    def __enter__(self): return self
    def __exit__(self,*args): return self.stream.__exit__(*args)
    def __getattr__(self,name): return getattr(self.stream,name)
    def read(self,*args): return swapped_read(lambda: self.stream.read(*args))
def changed_fdopen(fd,*args,**kwargs):
    stream=original_fdopen(fd,*args,**kwargs)
    if phase[0] and target[0] is not None:
        left,right=os.fstat(fd),target[0].stat()
        if (left.st_dev,left.st_ino)==(right.st_dev,right.st_ino):
            return ChangedStream(stream)
    return stream
def changed_compile(root,manifest,*args,**kwargs):
    target[0]=root/'tests/test_probe.py'
    saved[0]=original_read(target[0])
    expression=b"self.fail('committed')"
    saved[1]=saved[0].replace(expression,b'pass'+b' '*(len(expression)-4))
    assert saved[0]!=saved[1] and len(saved[0])==len(saved[1])
    saved[2]=target[0].stat().st_mode & 0o777
    phase[0]=True
    try: return original_compile(root,manifest,*args,**kwargs)
    finally: phase[0]=False
Path.read_bytes=changed_read
os.fdopen=changed_fdopen
_compile_selected=changed_compile
'''
        fixture.write(SCRIPT, (fixture.root / SCRIPT).read_text() + hook)
        result = fixture.run()
        self.assertNotEqual(result.returncode, 0, 'Substituted compiled code certified the committed failing selector')
        self.assertFalse((fixture.root / 'effect').exists())
        self.assertFalse((fixture.root / 'artifacts/mvp-verification/report.json').exists())

    def test_packetless_zero_exit_records_failed_evidence_and_runs_later_selector(self):
        for fresh_exec in (False, True):
            with self.subTest(fresh_exec=fresh_exec):
                fixture = self.fixture(body='os._exit(0)')
                fixture.write('tests/test_probe.py', (fixture.root / 'tests/test_probe.py').read_text() +
                    " def test_later(self):\n  with Path('effect').open('a') as f: f.write('once\\n')\n")
                fixture.case['selectors'].append('test_probe.Probe.test_later')
                fixture.save()
                if fresh_exec:
                    fixture.write(SCRIPT, (fixture.root / SCRIPT).read_text() + '\ndef _fork_available(): return False\n')
                result = fixture.run()
                self.assertEqual(json.loads(result.stdout), {'status': 'FAIL', 'reason': 'required_evidence_incomplete'})
                self.assertEqual(result.returncode, 1)
                crashed, later = fixture.report()['results'][0]['observed']
                self.assertEqual(crashed['reasons'], ['test_error'])
                self.assertEqual(tuple(crashed[k] for k in ('collected', 'executed', 'completed')), (0, 0, 0))
                self.assertEqual(later['reasons'], ['passed'])
                self.assertEqual((fixture.root / 'effect').read_text().splitlines(), ['once'])

    def test_missing_report_is_invalid_evidence_with_or_without_parent(self):
        for parent in (False, True):
            with self.subTest(parent=parent):
                fixture = self.fixture(body="Path('effect').write_text('forbidden')")
                if parent:
                    (fixture.root / 'artifacts/mvp-verification').mkdir(parents=True)
                result = fixture.run(validate=True)
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stdout), {'status': 'FAIL', 'reason': 'invalid_input'})
                self.assertFalse((fixture.root / 'effect').exists())

    def test_crashed_selector_has_failed_evidence_and_does_not_hide_later_execution(self):
        for fresh_exec in (False, True):
            for shutdown in (False, True):
                for crash in ('os.kill(os.getpid(), signal.SIGKILL)', 'os._exit(7)'):
                    with self.subTest(fresh_exec=fresh_exec, shutdown=shutdown, crash=crash):
                        body = ('atexit.register(lambda: ' + crash + ')' if shutdown else crash)
                        fixture = self.fixture(extra='import signal, atexit', body=body)
                        fixture.write('tests/test_probe.py', (fixture.root / 'tests/test_probe.py').read_text() +
                            " def test_later(self):\n  with Path('effect').open('a') as f: f.write('once\\n')\n")
                        fixture.case['selectors'].append('test_probe.Probe.test_later')
                        fixture.save()
                        if fresh_exec:
                            fixture.write(SCRIPT, (fixture.root / SCRIPT).read_text() + '\ndef _fork_available(): return False\n')
                        result = fixture.run()
                        self.assertEqual(json.loads(result.stdout), {'status': 'FAIL', 'reason': 'required_evidence_incomplete'})
                        self.assertEqual(result.returncode, 1)
                        row = fixture.report()['results'][0]
                        self.assertEqual(row['status'], 'FAIL')
                        crashed, later = row['observed']
                        self.assertEqual(crashed['reasons'], ['test_error'])
                        expected = (1, 1, 1) if shutdown else (0, 0, 0)
                        self.assertEqual(tuple(crashed[k] for k in ('collected', 'executed', 'completed')), expected)
                        self.assertEqual(later['reasons'], ['passed'])
                        self.assertEqual((fixture.root / 'effect').read_text().splitlines(), ['once'])
                        self.assertEqual(fixture.run(validate=True).returncode, 1)
                        self.assertEqual((fixture.root / 'effect').read_text().splitlines(), ['once'])

    def test_report_rejects_impossible_utc_dates_and_preserves_valid_leap_days(self):
        fixture = self.fixture(body="with Path('effect').open('a') as f: f.write('once\\n')")
        self.assertEqual(fixture.run().returncode, 0)
        report = fixture.report()
        invalid = ['0000-01-01T00:00:00+00:00', '2026-02-30T00:00:00+00:00',
                   '2025-02-29T00:00:00+00:00', '2026-13-01T00:00:00+00:00',
                   '2026-01-01T25:00:00+00:00', '2026-01-01T00:60:00+00:00',
                   '2026-01-01T00:00:60+00:00']
        for stamp in invalid:
            with self.subTest(timestamp=stamp):
                changed = copy.deepcopy(report)
                changed['results'][0].update(started_at=stamp, finished_at=stamp)
                fixture.json('artifacts/mvp-verification/report.json', changed)
                self.assertEqual(fixture.run(validate=True).returncode, 2)
        for start, end, valid in [('2000-02-29T00:00:00+00:00', '2000-02-29T00:00:01+00:00', True),
                                  ('2026-01-01T00:00:01+00:00', '2026-01-01T00:00:00+00:00', False)]:
            changed = copy.deepcopy(report)
            changed['results'][0].update(started_at=start, finished_at=end)
            fixture.json('artifacts/mvp-verification/report.json', changed)
            self.assertEqual(fixture.run(validate=True).returncode, 0 if valid else 2)
        self.assertEqual((fixture.root / 'effect').read_text().splitlines(), ['once'])

    def test_artifact_parent_replacement_cannot_substitute_an_external_pass(self):
        for stage in ('after_path_check', 'before_report_open'):
            with self.subTest(stage=stage):
                fixture = self.fixture(body="with Path('effect').open('a') as f: f.write('once\\n')")
                self.assertEqual(fixture.run().returncode, 0)
                report = fixture.report()
                fixture.json('outside-report/report.json', report)
                report['run_alias'] = 'invalid-original-report'
                fixture.json('artifacts/mvp-verification/report.json', report)
                hook = ("scope=namespace['main'].__globals__\nPath=scope['Path']\nos=scope['os']\nswapped=[False]\n"
                    "def swap():\n"
                    " if swapped[0]: return\n swapped[0]=True\n"
                    " parent=Path.cwd()/'artifacts/mvp-verification'\n"
                    " parent.rename(parent.with_name('retained-parent'))\n"
                    " parent.symlink_to(Path.cwd()/'outside-report',target_is_directory=True)\n")
                if stage == 'after_path_check':
                    hook += ("original=scope['artifact_path']\n"
                        "def changed(*args,**kwargs):\n"
                        " target=original(*args,**kwargs)\n swap()\n return target\n"
                        "scope['artifact_path']=changed\n")
                else:
                    hook += ("original=os.open\n"
                        "def changed(path,*args,**kwargs):\n"
                        " if str(path).endswith('/report.json') or str(path)=='report.json': swap()\n"
                        " return original(path,*args,**kwargs)\n"
                        "os.open=changed\n")
                result = fixture.run(validate=True, driver=self.driver(hook))
                self.assertNotEqual(result.returncode, 0, 'An intermediate symlink substituted an outside PASS')
                self.assertEqual((fixture.root / 'effect').read_text().splitlines(), ['once'])

    def test_environment_preflight_snapshot_and_launch_are_blocked_without_public_details(self):
        for stage in ('git_timeout', 'snapshot_io', 'worker_launch'):
            with self.subTest(stage=stage):
                fixture = self.fixture(body="Path('effect').write_text('forbidden')")
                hook = "import subprocess\nscope=namespace['main'].__globals__\n"
                if stage == 'git_timeout':
                    hook += ("def unavailable(*args,**kwargs): raise subprocess.TimeoutExpired('" + CANARY + "',15)\n"
                             "scope['git']=unavailable\n")
                elif stage == 'snapshot_io':
                    hook += ("def unavailable(*args,**kwargs): raise OSError('" + CANARY + "')\n"
                             "scope['source_snapshot']=unavailable\n")
                else:
                    hook += ("original=scope['isolated_worker']\n"
                        "def failed_launch(*args,**kwargs): raise OSError('" + CANARY + "')\n"
                        "def unavailable(*args,**kwargs):\n"
                        " old=subprocess.Popen\n subprocess.Popen=failed_launch\n"
                        " try: return original(*args,**kwargs)\n"
                        " finally: subprocess.Popen=old\n"
                        "scope['isolated_worker']=unavailable\n")
                result = fixture.run(driver=self.driver(hook))
                self.assertEqual(result.returncode, 2)
                self.assertEqual(json.loads(result.stdout), {'status': 'BLOCKED', 'reason': 'environment_unavailable'})
                self.assertFalse((fixture.root / 'effect').exists())
                self.assertFalse((fixture.root / 'artifacts/mvp-verification/report.json').exists())
        normal = self.fixture(body="with Path('effect').open('a') as f: f.write('once\\n')")
        self.assertEqual(normal.run().returncode, 0)
        self.assertEqual(normal.run(validate=True).returncode, 0)
        self.assertEqual((normal.root / 'effect').read_text().splitlines(), ['once'])

    def test_private_worker_infrastructure_failure_keeps_its_environment_classification(self):
        profiles = (False, True) if sys.platform in {'darwin', 'linux'} and hasattr(os, 'fork') else (True,)
        for fresh_exec in profiles:
            for stage in ('launch', 'selector_setup'):
                for failure in ('os_error', 'timeout'):
                    with self.subTest(fresh_exec=fresh_exec, stage=stage, failure=failure):
                        fixture = self.fixture(body="Path('effect').write_text('forbidden')")
                        extra = '\ndef _fork_available(): return ' + str(not fresh_exec) + '\n'
                        extra += "def _unavailable(*args,**kwargs):\n raise " + (
                            "OSError('" + CANARY + "')" if failure == 'os_error' else
                            "subprocess.TimeoutExpired('" + CANARY + "',15)") + '\n'
                        extra += ("_emit_selector=_unavailable\n" if stage == 'selector_setup' else
                                  "subprocess.Popen=_unavailable\n" if fresh_exec else "os.fork=_unavailable\n")
                        fixture.write(SCRIPT, (fixture.root / SCRIPT).read_text() + extra)
                        result = fixture.run()
                        self.assertEqual(result.returncode, 2)
                        self.assertEqual(json.loads(result.stdout), {'status': 'BLOCKED', 'reason': 'environment_unavailable'})
                        self.assertFalse((fixture.root / 'effect').exists())
                        self.assertFalse((fixture.root / 'artifacts/mvp-verification/report.json').exists())

    def test_signal_at_selector_return_keeps_interruption_classification(self):
        for fresh_exec in (False, True):
            for signum in ('SIGTERM', 'SIGINT'):
                with self.subTest(fresh_exec=fresh_exec, signal=signum):
                    fixture = self.fixture(extra='import signal', body=
                        "with Path('effect').open('a') as f: f.write('once')\n"
                        "def cancel_return(frame,event,value):\n"
                        " if event == 'return' and frame.f_code.co_name == 'execute_selector':\n"
                        "  sys.setprofile(None)\n"
                        "  os.kill(os.getpid(),signal." + signum + ")\n"
                        "sys.setprofile(cancel_return)")
                    if fresh_exec:
                        fixture.write(SCRIPT, (fixture.root / SCRIPT).read_text() +
                                      '\ndef _fork_available(): return False\n')
                    self.add_control(fixture)
                    result = fixture.run()
                    self.assertEqual((fixture.root / 'effect').read_text(), 'once')
                    self.assertEqual(result.returncode, 2)
                    self.assertEqual(json.loads(result.stdout), {'status': 'FAIL', 'reason': 'interrupted'})
                    self.assertFalse((fixture.root / 'control_effect').exists())
                    self.assertFalse((fixture.root / 'artifacts/mvp-verification/report.json').exists())

    @unittest.skipUnless(sys.platform in {'darwin', 'linux'} and hasattr(os, 'register_at_fork'),
                         'Requires the supported selector fork profile')
    def test_signal_during_fork_bootstrap_cannot_be_cleared(self):
        for signum in ('SIGTERM', 'SIGINT'):
            with self.subTest(signal=signum):
                fixture = self.fixture(body="Path('effect').write_text('forbidden')")
                fixture.write(SCRIPT, (fixture.root / SCRIPT).read_text() +
                    '\nos.register_at_fork(after_in_child=lambda:os.kill(os.getpid(),signal.' + signum + '))\n')
                self.add_control(fixture)
                result = fixture.run()
                self.assertEqual(result.returncode, 2, 'An inherited termination was cleared during child setup')
                self.assertEqual(json.loads(result.stdout), {'status': 'FAIL', 'reason': 'interrupted'})
                self.assertFalse((fixture.root / 'effect').exists())
                self.assertFalse((fixture.root / 'control_effect').exists())
                self.assertFalse((fixture.root / 'artifacts/mvp-verification/report.json').exists())

    def test_normal_shutdown_uses_remaining_worker_deadline(self):
        for fresh_exec in (False, True):
            with self.subTest(fresh_exec=fresh_exec):
                fixture = self.fixture(extra='import atexit, time', body=
                    "with Path('effect').open('a') as f: f.write('once')\n"
                    "atexit.register(lambda: (time.sleep(3), Path('shutdown_effect').write_text('once')))")
                if fresh_exec:
                    fixture.write(SCRIPT, (fixture.root / SCRIPT).read_text() +
                                  '\ndef _fork_available(): return False\n')
                self.add_control(fixture)
                result = fixture.run()
                self.assertEqual(result.returncode, 0, 'Normal shutdown was killed by an unrelated two-second wait')
                self.assertEqual((fixture.root / 'effect').read_text(), 'once')
                self.assertEqual((fixture.root / 'shutdown_effect').read_text(), 'once')
                self.assertEqual((fixture.root / 'control_effect').read_text(), 'once')
                self.assertEqual([row['status'] for row in fixture.report()['results']], ['PASS', 'PASS'])
                self.assertEqual(fixture.run(validate=True).returncode, 0)

    def test_shutdown_signal_cannot_certify_an_already_written_pass_packet(self):
        for fresh_exec in (False, True):
            for signum in ('SIGTERM', 'SIGINT'):
                with self.subTest(fresh_exec=fresh_exec, signal=signum):
                    fixture = self.fixture(extra='import atexit, signal', body=
                        "with Path('effect').open('a') as f: f.write('once')\n"
                        "atexit.register(lambda: os.kill(os.getpid(), signal." + signum + "))")
                    if fresh_exec:
                        fixture.write(SCRIPT, (fixture.root / SCRIPT).read_text() +
                                      '\ndef _fork_available(): return False\n')
                    self.add_control(fixture)
                    result = fixture.run()
                    self.assertNotEqual(result.returncode, 0, 'Interrupted selector shutdown exported PASS')
                    self.assertEqual(json.loads(result.stdout), {'status': 'FAIL', 'reason': 'interrupted'})
                    self.assertEqual((fixture.root / 'effect').read_text(), 'once')
                    self.assertFalse((fixture.root / 'control_effect').exists())
                    self.assertFalse((fixture.root / 'artifacts/mvp-verification/report.json').exists())

    def test_selected_json_patch_cannot_serialize_failure_as_pass(self):
        for target in ('dumps', 'encoder'):
            with self.subTest(target=target):
                fixture = self.fixture(extra='import json', body=
                    "Path('effect').write_text('once')\nself.fail('required failure')")
                if target == 'dumps':
                    tail = (" def tearDown(self):\n  original=json.dumps\n"
                        "  def forged(value,*args,**kwargs):\n"
                        "   if isinstance(value,dict) and 'outcome' in value: value['outcome']['reasons']=['passed']\n"
                        "   return original(value,*args,**kwargs)\n  json.dumps=forged\n")
                else:
                    tail = (" def tearDown(self):\n  original=json.JSONEncoder.encode\n"
                        "  def forged(encoder,value,*args,**kwargs):\n"
                        "   if isinstance(value,dict) and 'outcome' in value: value['outcome']['reasons']=['passed']\n"
                        "   return original(encoder,value,*args,**kwargs)\n  json.JSONEncoder.encode=forged\n")
                path = fixture.root / 'tests/test_probe.py'
                path.write_text(path.read_text() + tail)
                result = fixture.run()
                self.assertNotEqual(result.returncode, 0, 'Patched selected heap serialized actual failure as PASS')
                self.assertEqual(fixture.report()['results'][0]['observed'][0]['reasons'], ['test_failure'])
                self.assertEqual((fixture.root / 'effect').read_text(), 'once')
                self.assertNotEqual(fixture.run(validate=True).returncode, 0)

    def test_unfinished_daemon_call_cannot_be_completed_by_result_counters(self):
        fixture = self.fixture(extra='import threading\nstarted=threading.Event()\nblocked=threading.Event()',
            body="Path('started').write_text('once')\nstarted.set()\nblocked.wait(60)\nPath('effect').write_text('late')")
        path = fixture.root / 'tests/test_probe.py'
        path.write_text(path.read_text() + " def run(self,result):\n  result.startTest(self)\n"
            "  threading.Thread(target=self.test_required,daemon=True).start()\n"
            "  started.wait(5)\n  result.stopTest(self)\n")
        result = fixture.run()
        self.assertNotEqual(result.returncode, 0, 'A still-blocked selected body was reported complete')
        self.assertEqual((fixture.root / 'started').read_text(), 'once')
        self.assertFalse((fixture.root / 'effect').exists())
        self.assertNotEqual(fixture.report()['results'][0]['status'], 'PASS')

    def test_swallowed_selected_assertion_is_not_a_successful_method(self):
        fixture = self.fixture(body="Path('effect').write_text('once')\nself.fail('must be reported')")
        path = fixture.root / 'tests/test_probe.py'
        path.write_text(path.read_text() + " def run(self,result):\n  result.startTest(self)\n"
            "  try: self.test_required()\n  except AssertionError: pass\n  result.stopTest(self)\n")
        result = fixture.run()
        self.assertNotEqual(result.returncode, 0, 'Lifecycle suppressed an actual selected assertion')
        self.assertEqual(fixture.report()['results'][0]['observed'][0]['reasons'], ['test_failure'])
        self.assertEqual((fixture.root / 'effect').read_text(), 'once')

    def test_lazy_selected_returns_do_not_certify_unexecuted_bodies(self):
        for mode in ('generator', 'async_generator', 'wrapped_generator'):
            with self.subTest(mode=mode):
                fixture = self.fixture(body="Path('effect').write_text('must not be certified')\nyield None")
                path = fixture.root / 'tests/test_probe.py'
                if mode == 'async_generator':
                    path.write_text(path.read_text().replace(' def test_required(self):',
                                                             ' async def test_required(self):'))
                elif mode == 'wrapped_generator':
                    fixture.write('tests/test_probe.py', 'import unittest\nfrom pathlib import Path\n'
                        'def lazy():\n Path("effect").write_text("must not be certified")\n yield None\n'
                        'class Probe(unittest.TestCase):\n def test_required(self): return lazy()\n')
                result = fixture.run()
                self.assertNotEqual(result.returncode, 0, 'Unittest did not consume this lazy body')
                self.assertFalse((fixture.root / 'effect').exists())
                self.assertNotEqual(fixture.report()['results'][0]['status'], 'PASS')

    def test_snapshot_drift_with_restored_size_mode_and_mtime_holds_before_next_method(self):
        fixture = self.fixture(body="target=Path(__file__).parent/'test_control.py'\n"
            "info=target.stat()\nraw=target.read_bytes()\ntarget.chmod(0o644)\n"
            "target.write_bytes(raw.replace(b'False',b'True '))\ntarget.chmod(info.st_mode & 0o777)\n"
            "os.utime(target,ns=(info.st_atime_ns,info.st_mtime_ns))\nPath('effect').write_text('once')")
        self.add_control(fixture)
        path = fixture.root / 'tests/test_control.py'
        path.write_text(path.read_text() + '  self.assertTrue(False)\n')
        original = path.read_bytes()
        result = fixture.run()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((fixture.root / 'effect').read_text(), 'once')
        self.assertFalse((fixture.root / 'control_effect').exists())
        self.assertFalse((fixture.root / 'artifacts/mvp-verification/report.json').exists())
        self.assertEqual(path.read_bytes(), original)

    def test_coarse_metadata_never_replaces_actual_snapshot_byte_checks(self):
        fixture = self.fixture(body="target=Path(__file__).parent/'test_control.py'\n"
            "info=target.stat()\nraw=target.read_bytes()\ntarget.chmod(0o644)\n"
            "target.write_bytes(raw.replace(b'False',b'True '))\ntarget.chmod(info.st_mode & 0o777)\n"
            "os.utime(target,ns=(info.st_atime_ns,info.st_mtime_ns))\nPath('effect').write_text('once')")
        self.add_control(fixture)
        path = fixture.root / 'tests/test_control.py'
        path.write_text(path.read_text() + '  self.assertTrue(False)\n')
        # Simulate a filesystem metadata cache/timestamp tick while bytes change.
        # The actual later effect is the oracle, not a checker call count.
        fixture.write(SCRIPT, (fixture.root / SCRIPT).read_text() +
            '\n_original_fingerprint=_snapshot_fingerprint\n'
            'def _snapshot_fingerprint(info):\n'
            ' return _original_fingerprint(info)[:-2]+(1700000000123000000,1700000000123000000)\n')
        result = fixture.run()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((fixture.root / 'effect').read_text(), 'once')
        self.assertFalse((fixture.root / 'control_effect').exists(), 'Metadata equality let substituted code execute')
        self.assertFalse((fixture.root / 'artifacts/mvp-verification/report.json').exists())

    def test_compact_maximum_manifest_reserves_private_worker_envelope(self):
        fixture = self.fixture(body="with Path('effect').open('a') as f: f.write('once\\n')")
        # Cover the fresh-exec path on every host, including hosts that can fork.
        fixture.write(SCRIPT, (fixture.root / SCRIPT).read_text() +
                      '\ndef _fork_available(): return False\n')
        fixture.case['selectors'] = ['test_probe.C.test_required']
        compact = lambda: json.dumps(fixture.manifest, separators=(',', ':'))
        name = 'C' + 'A' * (262_144 - len(compact().encode()))
        fixture.case['selectors'] = ['test_probe.' + name + '.test_required']
        fixture.write(MANIFEST, compact())
        self.assertEqual((fixture.root / MANIFEST).stat().st_size, 262_144)
        fixture.write('tests/test_probe.py', 'import unittest\nfrom pathlib import Path\nclass ' + name
            + '(unittest.TestCase):\n def test_required(self):\n'
              "  with Path('effect').open('a') as f: f.write('once\\n')\n")
        result = fixture.run()
        self.assertEqual(result.returncode, 0, 'Accepted selector was rejected by private request framing')
        self.assertEqual((fixture.root / 'effect').read_text().splitlines(), ['once'])
        self.assertEqual(fixture.run(validate=True).returncode, 0)
        self.assertEqual((fixture.root / 'effect').read_text().splitlines(), ['once'])

    def test_result_counters_cannot_replace_actual_method_invocation(self):
        for mode in ('class_override', 'import_assignment', 'double_call'):
            with self.subTest(mode=mode):
                fixture = self.fixture(body="with Path('effect').open('a') as f: f.write('once\\n')")
                path = fixture.root / 'tests/test_probe.py'
                lines = ("result.startTest(self)\n" +
                    ("self.test_required()\nself.test_required()\n" if mode == 'double_call' else '') +
                    "result.stopTest(self)\n")
                if mode == 'class_override':
                    source = '\n def run(self,result):\n' + ''.join('  ' + line + '\n' for line in lines.splitlines())
                else:
                    source = '\ndef counted_only(self,result):\n' + ''.join(' ' + line + '\n' for line in lines.splitlines())
                    source += 'Probe.run=counted_only\n'
                path.write_text(path.read_text() + source)
                result = fixture.run()
                self.assertNotEqual(result.returncode, 0, 'Counters certified an omitted or repeated method')
                self.assertNotEqual(fixture.report()['results'][0]['status'], 'PASS')
                effect = fixture.root / 'effect'
                self.assertEqual(effect.read_text().splitlines() if effect.exists() else [],
                                 ['once', 'once'] if mode == 'double_call' else [])
                self.assertNotEqual(fixture.run(validate=True).returncode, 0)

        # The invocation probe must preserve real async unittest execution.
        fixture = self.fixture(extra='import asyncio', body="await asyncio.sleep(0)\nPath('effect').write_text('once')")
        path = fixture.root / 'tests/test_probe.py'
        path.write_text(path.read_text().replace('class Probe(unittest.TestCase):',
            'class Probe(unittest.IsolatedAsyncioTestCase):').replace(' def test_required(self):',
            ' async def test_required(self):'))
        self.assertEqual(fixture.run().returncode, 0)
        self.assertEqual((fixture.root / 'effect').read_text(), 'once')

    def test_selector_shutdown_effect_runs_once_and_output_stays_private(self):
        fixture = self.fixture(extra='import atexit', body="Path('effect').write_text('once')\n"
            "atexit.register(lambda:Path('shutdown_effect').write_text('once'))\n"
            "atexit.register(lambda:os.write(1," + repr(CANARY.encode()) + "))")
        self.assertEqual(fixture.run().returncode, 0)
        self.assertEqual((fixture.root / 'effect').read_text(), 'once')
        self.assertEqual((fixture.root / 'shutdown_effect').read_text(), 'once')
        self.assertEqual(fixture.run(validate=True).returncode, 0)
        self.assertEqual((fixture.root / 'shutdown_effect').read_text(), 'once')

    def test_each_selector_uses_committed_code_after_prior_memory_patches(self):
        for target in ("same_module", "imported_dependency"):
            with self.subTest(target=target):
                fixture = self.fixture(body=(
                    "Probe.test_later = lambda self: None" if target == "same_module" else
                    "import test_dependency\ntest_dependency.required = lambda: True") +
                    "\nwith Path('first_effect').open('a') as stream: stream.write('once\\n')")
                path = fixture.root / 'tests/test_probe.py'
                path.write_text(path.read_text() +
                    " def test_later(self):\n"
                    "  with Path('later_effect').open('a') as stream: stream.write('original\\n')\n" +
                    ("  self.fail('committed required failure')\n" if target == 'same_module' else
                     "  import test_dependency\n  self.assertTrue(test_dependency.required())\n"))
                fixture.write('tests/test_dependency.py', 'def required(): return False\n')
                fixture.case['selectors'].append('test_probe.Probe.test_later')
                fixture.save()
                result = fixture.run()
                self.assertNotEqual(result.returncode, 0, 'A prior heap patch concealed required failure')
                outcomes = fixture.report()['results'][0]['observed']
                self.assertEqual(outcomes[0]['reasons'], ['passed'])
                self.assertEqual(outcomes[1]['reasons'], ['test_failure'])
                self.assertEqual((fixture.root / 'first_effect').read_text().splitlines(), ['once'])
                self.assertEqual((fixture.root / 'later_effect').read_text().splitlines(), ['original'])

    def test_oracle_fixture_is_typed_nonempty_d_and_linked_before_execution(self):
        valid = self.fixture(body="Path('effect').write_text('once')")
        self.assertEqual(valid.run().returncode, 0)
        self.assertEqual(valid.run(validate=True).returncode, 0)
        changes = [
            {'kind': 'O'}, {'kind': None}, {'scenarios': []}, {'scenarios': ['S99']},
            {'scenarios': ['S01', 'S01']}, {'scenarios': [True]},
            {'preconditions': []}, {'events': [' ']}, {'expected': []},
            {'expected': [True]}, {'forbidden_effects': []}, {'oracle': ''},
            {'oracle': []}, {'scope': ' '}, {'command': 'must not be interpreted'},
            {'kind': 'O', 'scenarios': [], 'expected': [], 'forbidden_effects': [], 'oracle': ''},
        ]
        for changed in changes:
            with self.subTest(changed=changed):
                fixture = self.fixture(body="Path('forbidden_effect').write_text('executed')")
                path = fixture.root / fixture.case['fixture']
                fixture.json(fixture.case['fixture'], {**json.loads(path.read_text()), **changed})
                result = fixture.run()
                self.assertNotEqual(result.returncode, 0, 'Incomplete oracle supplied D PASS')
                self.assertFalse((fixture.root / 'forbidden_effect').exists())
                self.assertFalse((fixture.root / 'artifacts/mvp-verification/report.json').exists())

    def test_report_validation_rejects_non_regular_inputs_without_waiting(self):
        fixture = self.fixture(body="with Path('effect').open('a') as stream: stream.write('once\\n')")
        self.assertEqual(fixture.run(output='valid.json').returncode, 0)
        self.assertEqual(fixture.run(validate=True, output='valid.json').returncode, 0)
        artifacts = fixture.root / 'artifacts/mvp-verification'
        for kind in ('fifo', 'directory', 'utf-16', 'utf-32'):
            with self.subTest(kind=kind):
                path = artifacts / (kind + '.json')
                if kind == 'fifo':
                    os.mkfifo(path)
                elif kind == 'directory':
                    path.mkdir()
                else:
                    path.write_bytes((artifacts / 'valid.json').read_text().encode(kind))
                try:
                    result = fixture.run(validate=True, output=path.name, timeout=3)
                except subprocess.TimeoutExpired:
                    self.fail('Read-only report validation waited for a non-regular input')
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout), {'status': 'FAIL', 'reason': 'invalid_input'})
                self.assertEqual((fixture.root / 'effect').read_text().splitlines(), ['once'])
        self.assertEqual(fixture.run(validate=True, output='valid.json').returncode, 0)

    @staticmethod
    def driver(hook):
        return ("import runpy,sys,json,os\nfrom pathlib import Path\n"
                "script=sys.argv.pop(1)\nnamespace=runpy.run_path(script)\n" + hook
                + "\nraise SystemExit(namespace['main']())\n")

    @staticmethod
    def add_control(fixture):
        second = copy.deepcopy(fixture.case)
        second.update(case_id="VF-D01-CONTROL", selectors=["test_control.Control.test_required"],
                      fixture="tests/fixtures/mvp/verification/control.json")
        value = json.loads((fixture.root / fixture.case["fixture"]).read_text())
        value["case_id"] = second["case_id"]
        fixture.json(second["fixture"], value)
        fixture.write("tests/test_control.py", "import unittest\nfrom pathlib import Path\n"
                      "class Control(unittest.TestCase):\n def test_required(self):\n"
                      "  Path('control_effect').write_text('once')\n")
        fixture.manifest["cases"].append(second)
        fixture.save()

    def test_selected_test_cannot_rewrite_a_later_snapshot_module(self):
        replacement = ("import unittest\nfrom pathlib import Path\nclass Control(unittest.TestCase):\n"
                       " def test_required(self):\n  Path('control_effect').write_text('substituted')\n")
        fixture = self.fixture(body="target = Path(__file__).parent / 'test_control.py'\n"
            "target.chmod(0o644)\ntarget.write_text(" + repr(replacement) + ")\n"
            "with Path('effect').open('a') as stream: stream.write('once\\n')")
        self.add_control(fixture)
        path = fixture.root / 'tests/test_control.py'
        path.write_text(path.read_text() + "  self.fail('original required failure')\n")
        original = path.read_bytes()
        result = fixture.run()
        self.assertEqual((fixture.root / 'effect').read_text().splitlines(), ['once'])
        self.assertEqual(path.read_bytes(), original)
        if result.returncode == 0:
            self.assertEqual(fixture.run(validate=True).returncode, 0,
                             'The reproduced snapshot substitution no longer validates')
        self.assertNotEqual(result.returncode, 0, 'A substituted later test was exported as committed PASS')
        self.assertFalse((fixture.root / 'control_effect').exists(), 'Later substituted code executed')
        self.assertFalse((fixture.root / 'artifacts/mvp-verification/report.json').exists())

    def test_snapshot_mutation_after_worker_is_rejected_before_publication(self):
        fixture = self.fixture(body="with Path('effect').open('a') as stream: stream.write('once\\n')")
        hook = ("scope=namespace['main'].__globals__\noriginal=scope['isolated_execute']\n"
                "def changed(snapshot,*args,**kwargs):\n"
                " report=original(snapshot,*args,**kwargs)\n"
                " target=snapshot/'tests/test_probe.py'\n target.chmod(0o644)\n"
                " target.write_bytes(target.read_bytes()+b'\\n# changed after execution\\n')\n"
                " return report\nscope['isolated_execute']=changed\n")
        original = (fixture.root / 'tests/test_probe.py').read_bytes()
        result = fixture.run(driver=self.driver(hook))
        self.assertEqual((fixture.root / 'effect').read_text().splitlines(), ['once'])
        self.assertEqual((fixture.root / 'tests/test_probe.py').read_bytes(), original)
        if result.returncode == 0:
            self.assertEqual(fixture.run(validate=True).returncode, 0)
        self.assertNotEqual(result.returncode, 0, 'Changed snapshot bytes remained reusable as PASS')
        self.assertFalse((fixture.root / 'artifacts/mvp-verification/report.json').exists())

    def test_accepted_case_selector_matrix_exports_and_validates_without_rerun(self):
        # Keep the complete accepted maximum; the smaller matrix adds no new oracle.
        cases = 64
        fixture = self.fixture()
        contract = '\n\n'.join('# Acceptance-' + str(n) for n in range(8)) + '\n'
        fixture.write('docs/contract.md', contract)
        refs = [{'path': 'docs/contract.md', 'revision': digest(contract.encode()),
                 'section': 'acceptance-' + str(n)} for n in range(8)]
        source = 'import unittest\nfrom pathlib import Path\nclass Probe(unittest.TestCase):\n'
        fixture.manifest['cases'] = []
        for n in range(cases):
            case = copy.deepcopy(fixture.case)
            case.update(case_id='VF-D-MATRIX-' + str(n), requirements=copy.deepcopy(refs),
                selectors=['test_probe.Probe.test_case_' + str(n) + '_method_' + str(m) for m in range(32)],
                fixture='tests/fixtures/mvp/verification/matrix_' + str(n) + '.json')
            payload = json.loads((fixture.root / fixture.case['fixture']).read_text())
            payload['case_id'] = case['case_id']
            fixture.json(case['fixture'], payload)
            fixture.manifest['cases'].append(case)
            for m in range(32):
                source += (' def test_case_' + str(n) + '_method_' + str(m) + '(self):\n'
                           "  with Path('effect').open('a') as stream: stream.write('once\\n')\n"
                           '  self.assertEqual(2 + 2, 4)\n')
        fixture.write('tests/test_probe.py', source)
        fixture.save()
        self.assertLessEqual((fixture.root / MANIFEST).stat().st_size, 262_144)
        result = fixture.run(timeout=240)
        self.assertEqual(len((fixture.root / 'effect').read_text().splitlines()), cases * 32)
        self.assertEqual(result.returncode, 0, result.stdout)
        report = fixture.report()
        self.assertEqual(len(report['results']), cases)
        self.assertEqual(sum(len(row['observed']) for row in report['results']), cases * 32)
        self.assertTrue(all(row['status'] == 'PASS' for row in report['results']))
        self.assertGreater((fixture.root / 'artifacts/mvp-verification/report.json').stat().st_size, 262_144)
        self.assertEqual(fixture.run(validate=True, timeout=120).returncode, 0)
        self.assertEqual(len((fixture.root / 'effect').read_text().splitlines()), cases * 32)

    def test_deferred_and_other_non_none_returns_never_certify_unexecuted_work(self):
        for returned in ('map', 'filter', 'custom_iterator'):
            with self.subTest(returned=returned):
                fixture = self.fixture()
                definitions = ("import unittest\nfrom pathlib import Path\n"
                    "class Probe(unittest.TestCase):\n def test_required(self):\n"
                    "  def fail_later(_):\n   Path('deferred_effect').write_text('forbidden')\n"
                    "   self.fail('deferred assertion')\n")
                if returned == 'custom_iterator':
                    definitions += ("  class Deferred:\n   def __iter__(self): return self\n"
                                    "   def __next__(self): return fail_later(None)\n  return Deferred()\n")
                else:
                    definitions += '  return ' + returned + '(fail_later,[1])\n'
                fixture.write('tests/test_probe.py', definitions)
                result = fixture.run()
                self.assertNotEqual(result.returncode, 0, 'A deferred return was certified without evaluating its assertions')
                self.assertFalse((fixture.root / 'deferred_effect').exists())
                self.assertEqual(fixture.report()['results'][0]['status'], 'FAIL')

    def test_import_patched_loader_cannot_replace_the_exact_selected_class(self):
        for changed in ('class', 'method'):
            with self.subTest(changed=changed):
                fixture = self.fixture(body="Path('selected_effect').write_text('once')\nself.fail('actual selected failure')")
                path = fixture.root / 'tests/test_probe.py'
                extra = ("\nclass Substitute(unittest.TestCase):\n"
                         " def id(self): return 'test_probe.Probe.test_required'\n"
                         " def test_required(self): Path('substitute_effect').write_text('forbidden')\n"
                         "class ReplacementLoader(unittest.TestLoader):\n"
                         " def loadTestsFromName(self,*args,**kwargs):\n"
                         "  return unittest.TestSuite([Substitute('test_required')])\n")
                extra += ("unittest.TestLoader=ReplacementLoader\n" if changed == 'class' else
                          "unittest.TestLoader.loadTestsFromName=ReplacementLoader.loadTestsFromName\n")
                path.write_text(path.read_text() + extra)
                result = fixture.run()
                self.assertNotEqual(result.returncode, 0, 'A different class forged the selected string id')
                self.assertFalse((fixture.root / 'substitute_effect').exists())
                self.assertEqual((fixture.root / 'selected_effect').read_text(), 'once')

    def test_compile_only_reuse_never_executes_selected_modules_in_the_orchestrator(self):
        fixture = self.fixture(body="Path('effect').write_text('once')")
        path = fixture.root / 'tests/test_probe.py'
        path.write_text(path.read_text() + "\n def test_second(self):\n  Path('second_effect').write_text('once')\n"
                        "\nwith Path('imports').open('a') as log: log.write('once\\n')\n")
        fixture.case['selectors'].append('test_probe.Probe.test_second')
        fixture.save()
        self.assertEqual(fixture.run().returncode, 0)
        self.assertEqual((fixture.root / 'imports').read_text().splitlines(), ['once', 'once'])
        self.assertEqual((fixture.root / 'effect').read_text(), 'once')
        self.assertEqual((fixture.root / 'second_effect').read_text(), 'once')

    def test_valid_long_selector_fits_report_transport_export_and_consumer(self):
        fixture = self.fixture()
        name = 'C' + 'A' * 180_000
        fixture.write('tests/test_probe.py', 'import unittest\nfrom pathlib import Path\nclass ' + name
            + '(unittest.TestCase):\n def test_required(self):\n'
              "  with Path('effect').open('a') as stream: stream.write('once\\n')\n")
        selector = 'test_probe.' + name + '.test_required'
        fixture.case['selectors'] = [selector]
        fixture.save()
        self.assertLessEqual((fixture.root / MANIFEST).stat().st_size, 262_144)
        result = fixture.run(timeout=120)
        self.assertEqual((fixture.root / 'effect').read_text().splitlines(), ['once'])
        self.assertEqual(result.returncode, 0, result.stdout)
        report = fixture.report()
        self.assertEqual(report['results'][0]['observed'][0]['selector'], selector)
        self.assertGreater((fixture.root / 'artifacts/mvp-verification/report.json').stat().st_size, 262_144)
        self.assertEqual(fixture.run(validate=True, timeout=120).returncode, 0)
        self.assertEqual((fixture.root / 'effect').read_text().splitlines(), ['once'])

    def test_manifest_initial_swap_cannot_replace_committed_selector(self):
        fixture = self.fixture(body="Path('declared_effect').write_text('once')")
        probe = fixture.root / "tests/test_probe.py"
        probe.write_text(probe.read_text() + " def test_substituted(self):\n"
                         "  Path('substituted_effect').write_text('forbidden')\n")
        hook = ("original_read = Path.read_text\n"
            "def swapping_read(path, *args, **kwargs):\n"
            " if path == Path.cwd() / '" + MANIFEST + "':\n"
            "  original = original_read(path, *args, **kwargs)\n"
            "  changed = json.loads(original)\n"
            "  changed['cases'][0]['selectors'] = ['test_probe.Probe.test_substituted']\n"
            "  path.write_text(json.dumps(changed))\n"
            "  try: return original_read(path, *args, **kwargs)\n"
            "  finally: path.write_text(original)\n"
            " return original_read(path, *args, **kwargs)\n"
            "Path.read_text = swapping_read\n")
        result = fixture.run(driver=self.driver(hook))
        self.assertEqual(result.returncode, 0)
        self.assertFalse((fixture.root / "substituted_effect").exists(),
                         "A transient live manifest changed the executed method")
        self.assertEqual((fixture.root / "declared_effect").read_text(), "once")
        self.assertEqual(fixture.report()["results"][0]["observed"][0]["selector"],
                         "test_probe.Probe.test_required")

    def test_selected_descriptors_cannot_write_to_public_result_channel(self):
        control = self.fixture(body="print('private output')\nos.write(2,b'private output')")
        self.assertEqual(control.run().returncode, 0)
        for payload in (CANARY, CANARY * 20000):
            with self.subTest(size=len(payload)):
                fixture = self.fixture(body="Path('effect').write_text('once')\n"
                    "for descriptor in range(3,32):\n"
                    " try: os.write(descriptor, " + repr(payload.encode()) + ")\n"
                    " except OSError: pass")
                result = fixture.run()
                self.assertEqual(result.stderr, b'')
                self.assertEqual(len(result.stdout.splitlines()), 1)
                self.assertIn(json.loads(result.stdout)["status"], {"PASS", "FAIL"})
                self.assertEqual((fixture.root / "effect").read_text(), "once")

    def test_import_system_exit_is_collection_error_without_cancelling_control(self):
        fixture = self.fixture(extra="raise SystemExit(0)")
        self.add_control(fixture)
        self.assertNotEqual(fixture.run().returncode, 0)
        rows = fixture.report()["results"]
        self.assertEqual(rows[0]["observed"][0]["reasons"], ["collection_invalid"])
        self.assertEqual(rows[1]["status"], "PASS")
        self.assertEqual((fixture.root / "control_effect").read_text(), "once")

    def test_worker_cannot_change_reported_interpreter_context(self):
        fixture = self.fixture(body="Path('effect').write_text('once')\nsys.version_info=(9,9,9)")
        self.assertNotEqual(fixture.run().returncode, 0)
        self.assertFalse((fixture.root / 'artifacts/mvp-verification/report.json').exists())
        self.assertEqual((fixture.root / 'effect').read_text(), 'once')

    def test_caught_sigterm_stays_interrupted_and_cannot_export_pass(self):
        fixture = self.fixture(body="import signal\nPath('effect').write_text('once')\n"
            "try: os.kill(os.getpid(),signal.SIGTERM)\nexcept KeyboardInterrupt: pass")
        self.add_control(fixture)
        self.assertNotEqual(fixture.run().returncode, 0)
        rows = fixture.report()["results"]
        self.assertEqual(rows[0]["observed"][0]["reasons"], ["interrupted"])
        self.assertEqual(rows[1]["status"], "NOT RUN")
        self.assertFalse((fixture.root / "control_effect").exists())
        self.assertEqual((fixture.root / "effect").read_text(), "once")

    def test_export_finalization_failure_does_not_leave_reusable_pass(self):
        for replace in (False, True):
            with self.subTest(replace=replace):
                fixture = self.fixture(body="with Path('effect').open('a') as f: f.write('once')")
                hook = ("import stat\noriginal_sync = os.fsync\n"
                    "def failed_directory_sync(fd):\n"
                    " if stat.S_ISDIR(os.fstat(fd).st_mode):\n"
                    + ("  target=Path.cwd()/'artifacts/mvp-verification/report.json'\n"
                       "  target.unlink()\n  target.write_text('foreign evidence')\n" if replace else "")
                    + "  raise OSError('" + CANARY + "')\n"
                    " return original_sync(fd)\n"
                    "os.fsync = failed_directory_sync\n")
                result = fixture.run(driver=self.driver(hook))
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(json.loads(result.stdout)["reason"], "export_failed")
                self.assertNotEqual(fixture.run(validate=True, freeze=False).returncode, 0,
                                    "Failed export remained reusable as PASS")
                target = fixture.root / "artifacts/mvp-verification/report.json"
                if replace:
                    self.assertEqual(target.read_text(), "foreign evidence")
                else:
                    self.assertFalse(target.exists())
                self.assertEqual((fixture.root / "effect").read_text(), "once")

    def test_publication_commit_point_keeps_late_cancellation_consistent(self):
        early_hook = ("import signal,stat\noriginal_sync=os.fsync\n"
            "def cancel_before_commit(fd):\n"
            " if stat.S_ISDIR(os.fstat(fd).st_mode): os.kill(os.getpid(),signal.SIGTERM)\n"
            " return original_sync(fd)\nos.fsync=cancel_before_commit\n")
        early = self.fixture(body="Path('effect').write_text('once')")
        result = early.run(driver=self.driver(early_hook))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout)['reason'], 'interrupted')
        self.assertFalse((early.root / 'artifacts/mvp-verification/report.json').exists())
        self.assertEqual((early.root / 'effect').read_text(), 'once')
        for after_commit in ("os.kill(os.getpid(),signal.SIGTERM)",
                             "raise KeyboardInterrupt()", "raise OSError('cleanup failed')"):
            with self.subTest(after_commit=after_commit):
                fixture = self.fixture(body="with Path('effect').open('a') as f: f.write('once')")
                hook = ("import signal\nfrom contextlib import contextmanager\n"
                    "scope=namespace['main'].__globals__\noriginal_snapshot=scope['source_snapshot']\n"
                    "@contextmanager\ndef cancelled_teardown(root,head):\n"
                    " with original_snapshot(root,head) as snapshot:\n"
                    "  yield snapshot\n  " + after_commit + "\n"
                    "scope['source_snapshot']=cancelled_teardown\n")
                result = fixture.run(driver=self.driver(hook))
                self.assertEqual(result.returncode, 0,
                                 'A completed publication was relabeled after its commit point')
                self.assertEqual(json.loads(result.stdout), {'status':'PASS','reason':'passed'})
                self.assertEqual(fixture.run(validate=True, freeze=False).returncode, 0)
                self.assertEqual((fixture.root / 'effect').read_text(), 'once')


class VerificationCIContractTests(unittest.TestCase):
    fixture = VerificationCollectorTests.fixture
    def test_ci_shell_consumes_actual_collector_exit_and_separate_checked_revision(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text()
        assert_ci_contract(text)
        for skipped in (False, True):
            fixture = self.fixture(decorator="@unittest.skip('unavailable')" if skipped else "")
            environment = {**fixture.env, "CHECKED_SHA": fixture.head, "SOURCE_HEAD": "b" * 40,
                           "BASE_SHA": "a" * 40}
            result = subprocess.run(["bash", "-euo", "pipefail", "-c", ci_script(text)],
                cwd=fixture.root, env=environment, capture_output=True, timeout=20)
            self.assertEqual(result.returncode == 0, not skipped)
            self.assertEqual(fixture.report("result.json")["binding"]["candidate_head"], fixture.head)
            self.assertEqual(fixture.report("result.json")["binding"]["source_head"], "b" * 40)

    def test_ci_contract_rejects_required_deletion_untrusted_scan_and_permissions(self):
        text = (ROOT / ".github/workflows/ci.yml").read_text()
        assert_ci_contract(text)
        mutations = [text.replace("python3 -m unittest discover -s tests -v", "true"),
                     text.replace("contents: read", "contents: write"),
                     text.replace('--config "$GITLEAKS_TRUSTED_CONFIG"', '--config candidate/.gitleaks.toml'),
                     text.replace("if-no-files-found: error", "if-no-files-found: ignore"),
                     text.replace("python3 -I scripts/run_mvp_verification.py", "true #"),
                     text.replace("PYTHONDONTWRITEBYTECODE: '1'", "PYTHONDONTWRITEBYTECODE: '0'")]
        for changed in mutations:
            with self.subTest(changed=changed != text):
                self.assertTrue(changed != text, "Defect injection must alter the workflow")
                with self.assertRaises(AssertionError):
                    assert_ci_contract(changed)


class VerificationEvidenceReferenceTests(unittest.TestCase):
    fixture = VerificationCollectorTests.fixture

    def test_inline_html_and_autolinks_do_not_hide_real_requirement_headings(self):
        cases = [('<https://example.com>\n## Acceptance\n', True),
                 ('<span>inline</span>\n## Acceptance\n', True),
                 ('<a href="/path">link</a>\n## Acceptance\n', True),
                 ('paragraph\n<custom>\n## Acceptance\n', True),
                 ('<div>\n## Acceptance\n</div>\n', False),
                 ('<custom>\n## Acceptance\n', False),
                 ('<style>\n\n## Acceptance\n</style>\n', False),
                 ('<custom>\n\n## Acceptance\n', True)]
        for document, valid in cases:
            with self.subTest(document=document):
                fixture = self.fixture(body="Path('effect').write_text('once')")
                fixture.write('docs/contract.md', document)
                fixture.case['requirements'][0]['revision'] = digest(document.encode())
                fixture.save()
                result = fixture.run()
                self.assertEqual(result.returncode == 0, valid, result.stdout)
                self.assertEqual((fixture.root / 'effect').exists(), valid)

    def test_missing_registered_markdown_dependency_is_a_safe_environment_wait(self):
        fixture = self.fixture(body="Path('effect').write_text('forbidden')")
        hook = ("import builtins\noriginal=builtins.__import__\n"
                "def unavailable(name,*args,**kwargs):\n"
                " if name=='markdown_it': raise ImportError('" + CANARY + "')\n"
                " return original(name,*args,**kwargs)\n"
                "builtins.__import__=unavailable\n")
        result = fixture.run(driver=VerificationProcessBoundaryTests.driver(hook))
        self.assertEqual(result.returncode, 2)
        self.assertEqual(json.loads(result.stdout), {'status': 'BLOCKED', 'reason': 'environment_unavailable'})
        self.assertFalse((fixture.root / 'effect').exists())
        self.assertFalse((fixture.root / 'artifacts/mvp-verification/report.json').exists())

    def test_requirement_section_resolves_before_selected_test_effect(self):
        cases = [
            ("## Acceptance\n", "acceptance", True),
            ("## Renamed\n", "acceptance", False),
            ("## Acceptance\n", "acceptance-typo", False),
            ("```markdown\n## Acceptance\n```\n", "acceptance", False),
            ("~~~markdown\n## Acceptance\n~~~\n", "acceptance", False),
            ("    ## Acceptance\n", "acceptance", False),
            ("<div>\nblock\n## Acceptance\n</div>\n", "acceptance", False),
            ("<pre>\n\n## Acceptance\n</pre>\n", "acceptance", False),
            ("## Other\nAcceptance is only prose.\n", "acceptance", False),
            ("## Acceptance\n## Acceptance\n", "acceptance-1", True),
            ("Acceptance\n==========\n", "acceptance", True),
            ("## **Acceptance**\n", "acceptance", True),
            ("## foo_bar_baz\n", "foobarbaz", False),
            ("## _ Acceptance _\n", "acceptance", False),
            ("## _Acceptance_\n", "acceptance", True),
            ("## `Acceptance` ###\n", "acceptance", True),
        ]
        for document, section, valid in cases:
            with self.subTest(document=document, section=section):
                fixture = self.fixture(body="Path('effect').write_text('once')")
                fixture.write("docs/contract.md", document)
                reference = fixture.case["requirements"][0]
                reference.update(revision=digest(document.encode()), section=section)
                fixture.save()
                result = fixture.run()
                self.assertEqual(result.returncode == 0, valid, result.stdout)
                self.assertEqual((fixture.root / "effect").exists(), valid)
                if valid:
                    self.assertEqual(fixture.report()["results"][0]["status"], "PASS")
                else:
                    self.assertFalse((fixture.root / "artifacts/mvp-verification/report.json").exists())

    def test_subtest_exception_and_assertion_have_distinct_safe_reasons(self):
        for body, reason in [("raise RuntimeError('" + CANARY + "')", "test_error"),
                             ("self.fail('" + CANARY + "')", "test_failure")]:
            with self.subTest(reason=reason):
                fixture = self.fixture(body="with self.subTest(secret='" + CANARY + "'):\n " + body)
                self.assertNotEqual(fixture.run().returncode, 0)
                row = fixture.report()["results"][0]
                self.assertEqual(row["status"], "FAIL")
                outcome = row["observed"][0]
                self.assertEqual(outcome["reasons"], [reason])
                self.assertEqual((outcome["collected"], outcome["executed"], outcome["completed"]), (1, 1, 1))
                self.assertEqual(outcome["subtests"], 1)
                self.assertNotIn(CANARY, json.dumps(fixture.report()))

    def test_versioned_identity_fixture_matches_canonical_scenario_mapping(self):
        matrix = (ROOT / "docs/engineering/mvp/verification.md").read_text()
        expected = [scenario for scenario, row in re.findall(r"^\| (S\d{2}) \| (.+)$", matrix, re.MULTILINE)
                    if re.search(r"\bVF-D23\b", row)]
        self.assertEqual(expected, ["S25"])
        fixture = json.loads((ROOT / "tests/fixtures/mvp/verification/repository_identity.json").read_text())
        self.assertEqual(fixture["scenarios"], expected)


class VerificationRuntimeBoundaryTests(unittest.TestCase):
    fixture = VerificationCollectorTests.fixture

    def test_selected_source_is_read_only_while_effect_workspace_stays_writable(self):
        for reported_root in (False, True):
            with self.subTest(reported_root=reported_root):
                prefix = ("os.geteuid = lambda: 0\n"
                    "def forbidden_write(*args): raise AssertionError('privileged write oracle is not portable')\n"
                    "Path.write_bytes = forbidden_write\n") if reported_root else ""
                fixture = self.fixture(body=prefix + "source = Path(__file__)\n"
                    "original = source.read_bytes()\n"
                    "self.assertNotEqual(source.resolve(), Path.cwd() / 'tests/test_probe.py')\n"
                    "self.assertEqual(source.stat().st_mode & 0o222, 0)\n"
                    "if not hasattr(os, 'geteuid') or os.geteuid() != 0:\n"
                    " with self.assertRaises(PermissionError): source.write_bytes(original)\n"
                    "Path('effect').write_text('snapshot-used')")
                original = (fixture.root / "tests/test_probe.py").read_bytes()
                fixture.freeze()
                # Packaging output is not part of the frozen import root.
                fixture.write('build/lib/unrelated.py', "raise RuntimeError('untracked build output must not run')\n")
                self.assertEqual(fixture.run(freeze=False).returncode, 0)
                self.assertEqual((fixture.root / "effect").read_text(), "snapshot-used")
                self.assertEqual((fixture.root / "tests/test_probe.py").read_bytes(), original)

    def test_late_background_source_write_cannot_export_pass(self):
        import time
        hook = ("import time\noriginal_read = Path.read_bytes\n"
            "def observed_read(path):\n"
            " data = original_read(path)\n"
            " if path == Path.cwd() / 'zz_binding_tail.txt' and Path('execution_finished').exists():\n"
            "  Path('race_go').write_text('go')\n"
            "  deadline = time.monotonic() + 6\n"
            "  while not Path('race_done').exists():\n"
            "   if time.monotonic() >= deadline: raise RuntimeError('writer timeout')\n"
            "   time.sleep(.01)\n"
            " return data\nPath.read_bytes = observed_read")
        writer_code = ("from pathlib import Path\nimport sys,time\n"
            "root=Path(sys.argv[1]); deadline=time.monotonic()+10\n"
            "while not (root/'race_go').exists():\n"
            " if time.monotonic()>=deadline: raise SystemExit(2)\n"
            " time.sleep(.01)\n"
            "if sys.argv[2]=='mutate': (root/'docs/contract.md').write_text('# Rewritten\\n')\n"
            "(root/'race_done').write_text('done')\n")
        for mutate in (False, True):
            with self.subTest(mutate=mutate):
                fixture = self.fixture(body="Path('execution_finished').write_text('done')")
                fixture.write("zz_binding_tail.txt", "late tracked input\n")
                fixture.git("add", "zz_binding_tail.txt")
                fixture.freeze()
                child = subprocess.Popen([sys.executable, '-I', '-c', writer_code,
                    str(fixture.root), 'mutate' if mutate else 'observe'],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                try:
                    # The injector is external to selected tests: isolating their
                    # interpreter must not remove this actual source-write oracle.
                    result = fixture.run(freeze=False, driver=VerificationProcessBoundaryTests.driver(hook))
                    self.assertEqual(child.wait(timeout=12), 0)
                finally:
                    if child.poll() is None:
                        child.kill()
                        child.wait(timeout=3)
                self.assertEqual(result.returncode == 0, not mutate)
                self.assertEqual((fixture.root / 'race_done').read_text(), 'done')
                if mutate:
                    self.assertFalse((fixture.root / 'artifacts/mvp-verification/report.json').exists())

    def test_sigterm_during_preflight_and_read_only_validation_is_structured(self):
        import signal
        import time
        for validate in (False, True):
            with self.subTest(validate=validate):
                fixture = self.fixture()
                if validate:
                    self.assertEqual(fixture.run().returncode, 0)
                with tempfile.TemporaryDirectory() as temp:
                    tools = Path(temp)
                    ready = tools / 'ready'
                    helper = tools / 'git'
                    helper.write_text('#!' + sys.executable + '\nimport pathlib,time\n'
                        + 'pathlib.Path(' + repr(str(ready)) + ').write_text("ready")\n'
                        + 'time.sleep(30)\n')
                    helper.chmod(0o700)
                    environment = {**fixture.env, 'PATH': str(tools) + os.pathsep + fixture.env['PATH']}
                    child = subprocess.Popen([sys.executable, '-I', SCRIPT,
                        '--validate-report' if validate else '--output',
                        'artifacts/mvp-verification/report.json', '--checked-sha', fixture.head],
                        cwd=fixture.root, env=environment, stdout=subprocess.PIPE,
                        stderr=subprocess.PIPE, start_new_session=True)
                    try:
                        deadline = time.monotonic() + 8
                        while not ready.exists() and child.poll() is None and time.monotonic() < deadline:
                            time.sleep(.01)
                        self.assertTrue(ready.exists(), 'collector never entered preflight')
                        child.send_signal(signal.SIGTERM)
                        output, errors = child.communicate(timeout=5)
                        self.assertEqual(child.returncode, 2)
                        self.assertEqual(json.loads(output), {'status': 'FAIL', 'reason': 'interrupted'})
                        self.assertEqual(errors, b'')
                    finally:
                        try:
                            os.killpg(child.pid, signal.SIGKILL)
                        except ProcessLookupError:
                            pass
                        child.wait(timeout=3)

    def test_untracked_bytecode_and_extension_shadow_rejected_before_effects(self):
        import importlib.machinery
        import py_compile
        for kind in ('bytecode', 'extension'):
            with self.subTest(kind=kind):
                body = ('from hydra_sdlc import rogue\nself.assertTrue(rogue.loaded)' if kind == 'bytecode'
                    else "import importlib.util, importlib.machinery\n"
                    "self.assertIsInstance(importlib.util.find_spec('hydra_sdlc.project').loader, "
                    "importlib.machinery.ExtensionFileLoader)\nPath('effect').write_text('forbidden')")
                fixture = self.fixture(body=body)
                fixture.write('hydra_sdlc/__init__.py', '')
                fixture.write('hydra_sdlc/project.py', 'verified_source = True\n')
                fixture.freeze()
                if kind == 'bytecode':
                    with tempfile.TemporaryDirectory() as temp:
                        module = Path(temp) / 'source.py'
                        module.write_text("from pathlib import Path\nPath('effect').write_text('forbidden')\nloaded=True\n")
                        py_compile.compile(str(module), cfile=str(fixture.root / 'hydra_sdlc/rogue.pyc'), doraise=True)
                else:
                    suffix = importlib.machinery.EXTENSION_SUFFIXES[0]
                    (fixture.root / ('hydra_sdlc/project' + suffix)).write_bytes(b'synthetic extension placeholder')
                self.assertNotEqual(fixture.run(freeze=False).returncode, 0)
                self.assertFalse((fixture.root / 'effect').exists())


    def test_existing_hash_bytecode_cache_is_not_an_execution_input(self):
        import importlib.util
        import py_compile
        fixture = self.fixture(body="from hydra_sdlc import source_input\n"
            "self.assertEqual(source_input.value, 'verified')\n"
            "Path('effect').write_text(source_input.value)")
        fixture.write('hydra_sdlc/__init__.py', '')
        fixture.write('hydra_sdlc/source_input.py', "value = 'verified'\n")
        fixture.freeze()
        cache = Path(importlib.util.cache_from_source(str(fixture.root / 'hydra_sdlc/source_input.py')))
        cache.parent.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / 'untracked.py'
            source.write_text("from pathlib import Path\nPath('poisoned').write_text('forbidden')\nvalue='poisoned'\n")
            py_compile.compile(str(source), cfile=str(cache), doraise=True,
                invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH)
        self.assertEqual(fixture.run(freeze=False).returncode, 0)
        self.assertEqual((fixture.root / 'effect').read_text(), 'verified')
        self.assertFalse((fixture.root / 'poisoned').exists())
        self.assertTrue(cache.is_file(), 'unrelated existing cache must be preserved')

    def test_kernel_budget_covers_documented_suite_plus_evidence_overhead(self):
        workflow = (ROOT / '.github/workflows/ci.yml').read_text()
        kernel = workflow.split('  kernel:\n', 1)[1].split('  mac-app:\n', 1)[0]
        minutes = int(re.search(r'^    timeout-minutes: (\d+)$', kernel, re.MULTILINE)[1])
        self.assertGreater(minutes * 60, 284.417 + 60)
        self.assertLessEqual(minutes, 10)


if __name__ == "__main__":
    unittest.main()
