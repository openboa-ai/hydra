"""P13 actual subprocess, Git, export and public non-disclosure oracles."""

import copy
import hashlib
import json
import os
from pathlib import Path
import re
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
        self.json(self.case["fixture"], {"case_id": self.case["case_id"], "preconditions": ["synthetic"],
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
        result = subprocess.run([*command, "--manifest", MANIFEST,
            "--validate-report" if validate else "--output", "artifacts/mvp-verification/" + output,
            "--checked-sha", self.head, *args], cwd=self.root, env=self.env, capture_output=True, timeout=timeout)
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

    def test_export_failure_preserves_prior_bytes_and_single_effect(self):
        fixture = self.fixture(body="with Path('effect').open('a') as stream: stream.write('once')")
        fixture.write("artifacts/mvp-verification/report.json", "prior evidence")
        result = fixture.run()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(json.loads(result.stdout)["reason"], "export_failed")
        self.assertEqual((fixture.root / "artifacts/mvp-verification/report.json").read_text(), "prior evidence")
        self.assertEqual((fixture.root / "effect").read_text(), "once")

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
    required = ["permissions:\n  contents: read\n", "timeout-minutes: 10", "PYTHONDONTWRITEBYTECODE: '1'", "python: ['3.11', '3.14.2']",
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
    fixture = VerificationCollectorTests.fixture

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
        for cases in (32, 64):
            with self.subTest(cases=cases):
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
                result = fixture.run(timeout=120)
                self.assertEqual(len((fixture.root / 'effect').read_text().splitlines()), cases * 32)
                self.assertEqual(result.returncode, 0, result.stdout)
                report = fixture.report()
                self.assertEqual(len(report['results']), cases)
                self.assertEqual(sum(len(row['observed']) for row in report['results']), cases * 32)
                self.assertTrue(all(row['status'] == 'PASS' for row in report['results']))
                self.assertGreater((fixture.root / 'artifacts/mvp-verification/report.json').stat().st_size, 262_144)
                self.assertEqual(fixture.run(validate=True, timeout=120).returncode, 0)
                self.assertEqual(len((fixture.root / 'effect').read_text().splitlines()), cases * 32)

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
