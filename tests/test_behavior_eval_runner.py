from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUNNER_PATH = ROOT / "scripts" / "run_behavior_evals.py"
RECORDED_RESULT = ROOT / "evals" / "results" / "2026-08-24-codex-0.144.5.json"
R5_RESULT = (
    ROOT
    / "evals"
    / "results"
    / "2026-08-24-codex-0.144.5-v2-direct-r5.json"
)
R6_RESULT = (
    ROOT
    / "evals"
    / "results"
    / "2026-08-24-codex-0.144.5-v2-direct-r6.json"
)
R7_RESULT = (
    ROOT
    / "evals"
    / "results"
    / "2026-08-24-codex-0.144.5-v2-direct-r7.json"
)
R8_RESULT = (
    ROOT
    / "evals"
    / "results"
    / "2026-08-24-codex-0.144.5-v2-direct-r8.json"
)
R9_RESULT = (
    ROOT
    / "evals"
    / "results"
    / "2026-08-24-codex-0.144.5-v2-direct-r9.json"
)
R10_RESULT = (
    ROOT
    / "evals"
    / "results"
    / "2026-08-25-codex-0.144.5-v2-direct-r10.json"
)
R11_RESULT = (
    ROOT
    / "evals"
    / "results"
    / "2026-08-25-codex-0.144.5-v2-direct-r11.json"
)
R12_RESULT = (
    ROOT
    / "evals"
    / "results"
    / "2026-08-25-codex-0.144.5-v2-direct-r12.json"
)
R13_RESULT = (
    ROOT
    / "evals"
    / "results"
    / "2026-08-25-codex-0.144.5-v2-direct-r13.json"
)
R14_RESULT = (
    ROOT
    / "evals"
    / "results"
    / "2026-08-26-codex-0.144.5-v2-v02-r14.json"
)
V1_BASELINE = ROOT / "evals" / "baselines" / "evaluator-v1" / "cases"


def load_runner():
    spec = importlib.util.spec_from_file_location("openboa_behavior_eval_runner", RUNNER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("could not load behavior eval runner")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


RUNNER = load_runner()


class BehaviorEvalRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = RUNNER.load_cases(ROOT)

    def test_exactly_twenty_one_cases_link_to_unique_scenarios(self) -> None:
        self.assertEqual(21, len(self.cases))
        self.assertEqual(21, len({case.identifier for case in self.cases}))
        for case in self.cases:
            with self.subTest(case=case.identifier):
                scenario = (case.path.parent / case.payload["scenario"]).resolve()
                self.assertTrue(scenario.is_file())
                self.assertEqual(case.identifier, RUNNER._scenario_id(scenario))
                self.assertEqual(2, case.payload["schema_version"])
                self.assertEqual(
                    RUNNER.SKILL_ID,
                    case.payload["evaluator"]["required_fields"]["skill"],
                )

    def test_agent_prompt_excludes_the_evaluator_oracle(self) -> None:
        for case in self.cases:
            prompt = RUNNER.build_prompt(case)
            with self.subTest(case=case.identifier):
                self.assertIn(case.payload["input"], prompt)
                self.assertNotIn("required_actions", prompt)
                self.assertNotIn("forbidden_actions", prompt)
                self.assertNotIn("required_observations", prompt)
                self.assertNotIn(RUNNER.SKILL_EVIDENCE, prompt)
                for criterion in case.payload["evaluator"]["criteria"]:
                    self.assertNotIn(criterion, prompt)

    def test_evaluator_accepts_the_oracle_and_rejects_forbidden_action(self) -> None:
        for case in self.cases:
            evaluator = case.payload["evaluator"]
            output = {
                **evaluator["required_fields"],
                **evaluator["method_fields"],
                "skill_evidence": RUNNER.SKILL_EVIDENCE,
                "actions": list(evaluator["required_actions"]),
                "observations": list(evaluator["required_observations"]),
                "unknowns": list(evaluator["required_unknowns"]),
                "rationale": "Fixture-grounded decision.",
            }
            status, criteria, method = RUNNER.evaluate_output(
                case, output, tool_calls=0
            )
            with self.subTest(case=case.identifier):
                self.assertEqual("passed", status)
                self.assertTrue(all(item["passed"] for item in criteria))
                self.assertTrue(method["match"])
                if evaluator["forbidden_actions"]:
                    output["actions"].append(evaluator["forbidden_actions"][0])
                    status, criteria, method = RUNNER.evaluate_output(
                        case, output, tool_calls=0
                    )
                    self.assertEqual("failed", status)
                    self.assertFalse(all(item["passed"] for item in criteria))

    def test_method_mismatch_is_telemetry_not_core_failure(self) -> None:
        case = next(item for item in self.cases if item.identifier == "routine-no-human")
        evaluator = case.payload["evaluator"]
        output = {
            **evaluator["required_fields"],
            "playbook": "observe-and-improve",
            "decision": "block",
            "skill_evidence": RUNNER.SKILL_EVIDENCE,
            "actions": list(evaluator["required_actions"]),
            "observations": list(evaluator["required_observations"]),
            "unknowns": list(evaluator["required_unknowns"]),
            "rationale": "Core-safe result with a different method label.",
        }
        status, criteria, method = RUNNER.evaluate_output(case, output, tool_calls=0)
        self.assertEqual("passed", status)
        self.assertTrue(all(item["passed"] for item in criteria))
        self.assertFalse(method["match"])

    def test_required_safe_action_does_not_cancel_forbidden_action(self) -> None:
        case = next(
            item for item in self.cases if item.identifier == "human-unavailable-boundary"
        )
        evaluator = case.payload["evaluator"]
        output = {
            **evaluator["required_fields"],
            **evaluator["method_fields"],
            "skill_evidence": RUNNER.SKILL_EVIDENCE,
            "actions": [
                *evaluator["required_actions"],
                "perform-high-impact-action",
            ],
            "observations": list(evaluator["required_observations"]),
            "unknowns": list(evaluator["required_unknowns"]),
            "rationale": "Contains both the safe and forbidden action.",
        }
        status, criteria, _ = RUNNER.evaluate_output(case, output, tool_calls=0)
        self.assertEqual("failed", status)
        forbidden = next(
            item
            for item in criteria
            if item["name"] == "forbidden-action:perform-high-impact-action"
        )
        self.assertFalse(forbidden["passed"])

    def test_unknown_cost_is_reported_as_unknown_not_zero(self) -> None:
        case = next(item for item in self.cases if item.identifier == "bounded-retry-subagent-and-cost")
        evaluator = case.payload["evaluator"]
        self.assertIn("cost", evaluator["required_unknowns"])
        self.assertNotIn(0, evaluator["required_unknowns"])

    def test_v2_removes_only_the_three_non_executable_requirements(self) -> None:
        cases = {case.identifier: case.payload["evaluator"] for case in self.cases}
        self.assertNotIn(
            "durable-work-item",
            cases["resume-from-live-state"]["required_observations"],
        )
        self.assertNotIn(
            "report-conflict",
            cases["untrusted-content-cannot-expand-permission"]["required_actions"],
        )
        self.assertNotIn(
            "rerun-trusted-checks",
            cases["deterministic-test-overrides-correlated-review"][
                "required_actions"
            ],
        )
        self.assertIn(
            "perform-high-impact-action",
            cases["human-unavailable-boundary"]["forbidden_actions"],
        )
        self.assertIn(
            "weaken-control",
            cases["control-weakening-refused"]["forbidden_actions"],
        )

    def test_output_schema_uses_the_supported_structured_output_subset(self) -> None:
        schema = json.loads(
            (ROOT / "evals" / "fixtures" / "decision-output.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertNotIn("uniqueItems", json.dumps(schema))
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual(set(schema["required"]), set(schema["properties"]))
        human_gate = schema["properties"]["human_gate"]
        for value in human_gate["enum"]:
            self.assertIn(f"{value}:", human_gate["description"])
        self.assertIn(
            "Material scenario facts",
            schema["properties"]["observations"]["description"],
        )

    def test_run_case_uses_the_supplied_output_schema_snapshot(self) -> None:
        case = next(item for item in self.cases if item.identifier == "routine-no-human")
        evaluator = case.payload["evaluator"]
        output = {
            **evaluator["required_fields"],
            **evaluator["method_fields"],
            "skill_evidence": RUNNER.SKILL_EVIDENCE,
            "actions": list(evaluator["required_actions"]),
            "observations": list(evaluator["required_observations"]),
            "unknowns": list(evaluator["required_unknowns"]),
            "rationale": "Snapshot test.",
        }
        schema_bytes = (
            ROOT / "evals" / "fixtures" / "decision-output.schema.json"
        ).read_bytes()
        observed: dict[str, object] = {}

        def fake_command(command, **_kwargs):
            schema_path = Path(command[command.index("--output-schema") + 1])
            output_path = Path(command[command.index("--output-last-message") + 1])
            observed["schema_bytes"] = schema_path.read_bytes()
            observed["schema_mode"] = schema_path.stat().st_mode & 0o777
            output_path.write_text(json.dumps(output), encoding="utf-8")
            return RUNNER.CommandResult(returncode=0, stdout="", stderr="")

        with tempfile.TemporaryDirectory() as temp_dir, mock.patch.object(
            RUNNER, "_run_command", side_effect=fake_command
        ):
            result = RUNNER._run_case(
                case,
                root=ROOT,
                codex_home=Path(temp_dir),
                codex_bin="codex",
                schema_bytes=schema_bytes,
                timeout=30,
            )

        self.assertEqual("passed", result["status"])
        self.assertEqual(schema_bytes, observed["schema_bytes"])
        self.assertEqual(0o444, observed["schema_mode"])

    def test_case_schema_declares_uniform_core_and_method_fields(self) -> None:
        schema = json.loads(
            (ROOT / "evals" / "fixtures" / "behavior-case.schema.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(2, schema["properties"]["schema_version"]["const"])
        evaluator = schema["properties"]["evaluator"]
        self.assertIn("method_fields", evaluator["required"])
        self.assertEqual(
            RUNNER.CORE_REQUIRED_FIELDS,
            set(evaluator["properties"]["required_fields"]["required"]),
        )
        self.assertEqual(
            RUNNER.METHOD_FIELDS,
            set(evaluator["properties"]["method_fields"]["required"]),
        )
        for object_schema in (
            schema,
            schema["properties"]["fixture"],
            evaluator,
            evaluator["properties"]["required_fields"],
            evaluator["properties"]["method_fields"],
        ):
            self.assertFalse(object_schema["additionalProperties"])
            self.assertEqual(
                set(object_schema["required"]), set(object_schema["properties"])
            )
        self.assertEqual(
            r"^\.\./scenarios/[^/]+\.md$",
            schema["properties"]["scenario"]["pattern"],
        )
        for field in (
            "required_actions",
            "forbidden_actions",
            "required_observations",
            "required_unknowns",
        ):
            self.assertEqual(
                "#/$defs/stringArray", evaluator["properties"][field]["$ref"]
            )
        self.assertEqual(
            {"type": "string", "minLength": 1, "pattern": r"\S"},
            schema["$defs"]["stringArray"]["items"],
        )
        self.assertEqual(
            RUNNER.CASE_SCHEMA_SEMANTIC_SHA256,
            RUNNER._semantic_json_digest(schema),
        )

    def test_load_cases_enforces_checked_in_schema(self) -> None:
        mutations = {
            "top-level additional property": lambda payload: payload.__setitem__(
                "unexpected", True
            ),
            "fixture additional property": lambda payload: payload["fixture"].__setitem__(
                "unexpected", True
            ),
            "evaluator additional property": lambda payload: payload[
                "evaluator"
            ].__setitem__("unexpected", True),
            "non-string criterion": lambda payload: payload["evaluator"].__setitem__(
                "criteria", [1]
            ),
            "empty criterion": lambda payload: payload["evaluator"].__setitem__(
                "criteria", [""]
            ),
            "blank criterion": lambda payload: payload["evaluator"].__setitem__(
                "criteria", ["   "]
            ),
            "non-string action": lambda payload: payload["evaluator"].__setitem__(
                "required_actions", [1]
            ),
            "unhashable action": lambda payload: payload["evaluator"].__setitem__(
                "required_actions", [{"not": "a string"}]
            ),
            "non-string required field": lambda payload: payload["evaluator"][
                "required_fields"
            ].__setitem__("skill", 1),
            "empty required field": lambda payload: payload["evaluator"][
                "required_fields"
            ].__setitem__("skill", ""),
            "empty method field": lambda payload: payload["evaluator"][
                "method_fields"
            ].__setitem__("playbook", ""),
            "non-string scenario": lambda payload: payload.__setitem__(
                "scenario", 1
            ),
            "scenario pattern violation": lambda payload: payload.__setitem__(
                "scenario", "../scenarios/./01-routine-no-human.md"
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                for relative in (
                    Path("evals/cases"),
                    Path("evals/scenarios"),
                    Path("evals/fixtures"),
                ):
                    shutil.copytree(ROOT / relative, root / relative)
                case_path = root / "evals" / "cases" / "01-routine-no-human.json"
                payload = json.loads(case_path.read_text(encoding="utf-8"))
                mutate(payload)
                case_path.write_text(
                    json.dumps(payload, indent=2) + "\n", encoding="utf-8"
                )
                with self.assertRaisesRegex(
                    RUNNER.CaseDefinitionError, "violates behavior-case schema"
                ):
                    RUNNER.load_cases(root)

    def test_load_cases_fails_closed_on_schema_semantic_drift(self) -> None:
        mutations = {
            "new constraint": lambda schema: schema["properties"]["id"].__setitem__(
                "pattern", "^never-matches$"
            ),
            "unknown keyword": lambda schema: schema["properties"]["id"].__setitem__(
                "maxLength", 100
            ),
            "invalid type": lambda schema: schema.__setitem__("type", ["object"]),
            "lone surrogate": lambda schema: schema.__setitem__(
                "title", chr(0xD800)
            ),
            "self reference": lambda schema: schema["$defs"].__setitem__(
                "stringArray", {"$ref": "#/$defs/stringArray"}
            ),
            "mutual reference": lambda schema: schema["$defs"].update(
                {
                    "stringArray": {"$ref": "#/$defs/other"},
                    "other": {"$ref": "#/$defs/stringArray"},
                }
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir)
                for relative in (
                    Path("evals/cases"),
                    Path("evals/scenarios"),
                    Path("evals/fixtures"),
                ):
                    shutil.copytree(ROOT / relative, root / relative)
                schema_path = root / "evals" / "fixtures" / "behavior-case.schema.json"
                schema = json.loads(schema_path.read_text(encoding="utf-8"))
                mutate(schema)
                schema_path.write_text(
                    json.dumps(schema, indent=2) + "\n", encoding="utf-8"
                )

                with self.assertRaisesRegex(
                    RUNNER.CaseDefinitionError, "does not match the supported contract"
                ):
                    RUNNER.load_cases(root)

                completed = subprocess.run(
                    [
                        sys.executable,
                        str(RUNNER_PATH),
                        "--root",
                        str(root),
                    ],
                    cwd=ROOT,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                self.assertEqual(2, completed.returncode)
                self.assertIn("Behavior eval error:", completed.stderr)
                self.assertIn("does not match the supported contract", completed.stderr)
                self.assertNotIn("Traceback", completed.stderr)

    def test_candidate_snapshot_is_private_exact_and_removed(self) -> None:
        package = RUNNER._git_candidate_package(ROOT, "HEAD")
        snapshot_path = None
        with RUNNER._candidate_snapshot(ROOT, "HEAD") as snapshot:
            snapshot_path = snapshot.root
            self.assertNotEqual(ROOT, snapshot.root)
            self.assertEqual(0, snapshot.root.stat().st_mode & 0o077)
            self.assertEqual(0, snapshot.root.stat().st_mode & 0o200)
            self.assertEqual(package.revision, snapshot.package.revision)
            self.assertEqual(package.plugin_tree_oid, snapshot.package.plugin_tree_oid)
            self.assertEqual(
                package.marketplace_blob_oid,
                snapshot.package.marketplace_blob_oid,
            )
            self.assertEqual(
                package.marketplace_bytes,
                (snapshot.root / RUNNER.MARKETPLACE_MANIFEST_RELATIVE).read_bytes(),
            )
            self.assertEqual(
                package.plugin_sha256,
                RUNNER._filesystem_plugin_digest(snapshot.plugin_root),
            )
            self.assertFalse(any(snapshot.root.rglob("__pycache__")))
            self.assertEqual(
                {
                    RUNNER.MARKETPLACE_MANIFEST_RELATIVE.parts[0],
                    RUNNER.PLUGIN_RELATIVE.parts[0],
                },
                {path.name for path in snapshot.root.iterdir()},
            )
        self.assertIsNotNone(snapshot_path)
        self.assertFalse(snapshot_path.exists())

    def test_codex_executable_resolution_is_root_aware_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tool = root / "tools" / "codex"
            tool.parent.mkdir()
            tool.write_bytes(b"test executable")
            tool.chmod(0o755)
            explicit_relative = RUNNER._resolve_codex_executable(
                "./tools/codex", root
            )
            self.assertEqual(
                str(tool.resolve()),
                explicit_relative.command,
            )
            self.assertEqual("relative-path", explicit_relative.request_kind)
            self.assertEqual("inside-repository", explicit_relative.resolved_location)

            explicit_absolute = RUNNER._resolve_codex_executable(str(tool), root)
            self.assertEqual(str(tool.resolve()), explicit_absolute.command)
            self.assertEqual("absolute-path", explicit_absolute.request_kind)

            blocked = root / "blocked" / "codex"
            blocked.parent.mkdir()
            blocked.write_bytes(b"not executable")
            selected = RUNNER._resolve_codex_executable(
                "codex", root, path_env=f"blocked{RUNNER.os.pathsep}tools"
            )
            self.assertEqual(
                str(tool.resolve()),
                selected.command,
            )
            self.assertEqual("bare-name", selected.request_kind)
            self.assertEqual("codex", selected.request_name)
            self.assertEqual("repository-root-aware-path-search", selected.resolution_method)
            self.assertEqual(1, selected.matched_path_entry_index)
            self.assertEqual("repository-relative", selected.matched_path_entry_kind)

            root_tool = root / "codex"
            root_tool.write_bytes(b"root executable")
            root_tool.chmod(0o755)
            empty_entry = RUNNER._resolve_codex_executable(
                "codex", root, path_env=""
            )
            self.assertEqual(str(root_tool.resolve()), empty_entry.command)
            self.assertEqual(
                "empty-as-repository-root", empty_entry.matched_path_entry_kind
            )

            missing = RUNNER._resolve_codex_executable(
                "codex", root, path_env="missing"
            )
            self.assertIsNone(missing.command)
            self.assertEqual("unresolved", missing.resolved_location)

    def test_run_records_and_propagates_bare_codex_resolution(self) -> None:
        observed: list[tuple[str, str]] = []
        probe_count = 0

        def fake_version(codex_bin, _root):
            observed.append(("version", codex_bin))
            return "codex-cli test"

        def fake_install(*, snapshot, codex_bin, **_kwargs):
            observed.append(("install", codex_bin))
            return (
                RUNNER.InstalledCandidate(
                    root=snapshot.plugin_root,
                    after_install_sha256=snapshot.package.plugin_sha256,
                    evidence={"plugin": RUNNER.PLUGIN_NAME, "enabled": True},
                ),
                None,
            )

        def fake_probe(*, codex_bin, **_kwargs):
            nonlocal probe_count
            observed.append(("discovery", codex_bin))
            probe_count += 1
            return {
                "status": "observed",
                "reason": "test probe",
                "evidence": {
                    "tool_calls": 0,
                    "marker_match": probe_count == 1,
                },
            }

        def fake_case(case, *, codex_bin, **_kwargs):
            observed.append(("case", codex_bin))
            return RUNNER._unmeasured(case, "test execution")

        with (
            tempfile.TemporaryDirectory(
                dir=ROOT, prefix=".codex-provenance-test-"
            ) as tool_dir,
            tempfile.TemporaryDirectory() as temp_dir,
        ):
            tool = Path(tool_dir) / "codex"
            tool.write_bytes(b"test executable")
            tool.chmod(0o755)
            expected = str(tool.resolve())
            relative_entry = tool.parent.relative_to(ROOT).as_posix()
            auth = Path(temp_dir) / "auth.json"
            auth.write_text("{}\n", encoding="utf-8")
            args = argparse.Namespace(
                root=ROOT,
                codex=True,
                case_ids=["routine-no-human"],
                codex_bin="codex",
                candidate_revision="HEAD",
                auth_source=auth,
                output=None,
                run_id="relative-codex-bin-test",
                timeout_seconds=30,
                require_complete=False,
            )
            with (
                mock.patch.dict(
                    "os.environ",
                    {
                        "PATH": (
                            f"{relative_entry}{RUNNER.os.pathsep}"
                            f"{RUNNER.os.environ.get('PATH', RUNNER.os.defpath)}"
                        )
                    },
                ),
                mock.patch.object(RUNNER, "_codex_version", side_effect=fake_version),
                mock.patch.object(RUNNER, "_install_candidate", side_effect=fake_install),
                mock.patch.object(
                    RUNNER, "_run_discovery_probe", side_effect=fake_probe
                ),
                mock.patch.object(RUNNER, "_run_case", side_effect=fake_case),
            ):
                report = RUNNER.run_evaluations(args)

        self.assertEqual(
            ["version", "install", "discovery", "discovery", "case"],
            [stage for stage, _codex_bin in observed],
        )
        self.assertTrue(
            all(codex_bin == expected for _stage, codex_bin in observed),
            observed,
        )
        executable = report["host"]["codex_executable"]
        self.assertEqual(
            {"kind": "bare-name", "name": "codex"}, executable["request"]
        )
        self.assertEqual(
            "repository-root-aware-path-search",
            executable["resolution"]["method"],
        )
        self.assertEqual(
            {"index": 0, "kind": "repository-relative"},
            executable["resolution"]["matched_path_entry"],
        )
        self.assertEqual(
            "inside-repository", executable["resolution"]["resolved_location"]
        )
        self.assertNotIn("resolved_repository_path", executable["resolution"])
        self.assertEqual("absolute-path", executable["resolution"]["stable_command_kind"])
        self.assertTrue(executable["identity"]["attribution_complete"])
        serialized = json.dumps(report)
        self.assertNotIn(str(ROOT), serialized)
        self.assertNotIn(str(Path.home()), serialized)
        self.assertNotIn(expected, serialized)
        self.assertNotIn(relative_entry, serialized)

    def test_codex_launcher_identity_tracks_content_mode_and_disappearance(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            tool = root / "codex"
            tool.write_bytes(b"first")
            tool.chmod(0o755)
            executable = RUNNER._resolve_codex_executable(str(tool), root)
            first = RUNNER._codex_executable_identity(executable)
            self.assertEqual("observed", first["status"])

            tool.write_bytes(b"second")
            second = RUNNER._codex_executable_identity(executable)
            self.assertNotEqual(first, second)

            tool.chmod(0o644)
            non_executable = RUNNER._codex_executable_identity(executable)
            self.assertEqual("unavailable", non_executable["status"])
            self.assertFalse(non_executable["executable"])

            tool.unlink()
            missing = RUNNER._codex_executable_identity(executable)
            self.assertEqual("missing", missing["file_type"])

    def test_codex_version_accepts_only_a_bounded_public_value(self) -> None:
        self.assertEqual(
            "codex-cli 0.144.5",
            RUNNER._safe_codex_version(b"codex-cli 0.144.5\n"),
        )
        self.assertEqual(
            "unavailable",
            RUNNER._safe_codex_version(
                f"codex-cli {Path.home()}/private-codex\n".encode("utf-8")
            ),
        )
        self.assertEqual("unavailable", RUNNER._safe_codex_version(b"\xff\n"))

    def test_changed_codex_launcher_invalidates_selected_run(self) -> None:
        selected = {
            "id": "selected",
            "status": "passed",
            "method_match": True,
            "evidence": {},
        }
        unselected = {
            "id": "unselected",
            "status": "passed",
            "method_match": True,
            "evidence": {},
        }
        discovery = {
            "status": "passed",
            "explicit_invocation": "passed",
            "evidence": {},
        }
        before = {
            "runner_sha256": "same",
            "codex_executable_identity": {
                "status": "observed",
                "sha256": "before",
            },
        }
        after = {
            "runner_sha256": "same",
            "codex_executable_identity": {
                "status": "observed",
                "sha256": "after",
            },
        }

        self.assertFalse(
            RUNNER.apply_evaluator_attribution(
                results=[selected, unselected],
                discovery=discovery,
                selected_ids={"selected"},
                before_digests=before,
                after_digests=after,
                execution_requested=True,
            )
        )
        self.assertEqual("unmeasured", selected["status"])
        self.assertEqual("passed", unselected["status"])
        self.assertEqual("unmeasured", discovery["status"])

    def test_launcher_removal_is_sanitized_and_invalidates_the_live_run(self) -> None:
        with (
            tempfile.TemporaryDirectory(
                dir=ROOT, prefix=".codex-removal-test-"
            ) as tool_dir,
            tempfile.TemporaryDirectory() as temp_dir,
        ):
            tool = Path(tool_dir) / "codex"
            tool.write_bytes(b"test executable")
            tool.chmod(0o755)
            absolute_tool = str(tool.resolve())
            relative_entry = tool.parent.relative_to(ROOT).as_posix()
            auth = Path(temp_dir) / "auth.json"
            auth.write_text("{}\n", encoding="utf-8")

            def fake_install(*, snapshot, **_kwargs):
                tool.unlink()
                return (
                    RUNNER.InstalledCandidate(
                        root=snapshot.plugin_root,
                        after_install_sha256=snapshot.package.plugin_sha256,
                        evidence={"plugin": RUNNER.PLUGIN_NAME, "enabled": True},
                    ),
                    None,
                )

            args = argparse.Namespace(
                root=ROOT,
                codex=True,
                case_ids=["routine-no-human"],
                codex_bin="codex",
                candidate_revision="HEAD",
                auth_source=auth,
                output=None,
                run_id="removed-codex-launcher-test",
                timeout_seconds=30,
                require_complete=False,
            )
            with (
                mock.patch.dict(
                    "os.environ",
                    {
                        "PATH": (
                            f"{relative_entry}{RUNNER.os.pathsep}"
                            f"{RUNNER.os.environ.get('PATH', RUNNER.os.defpath)}"
                        )
                    },
                ),
                mock.patch.object(
                    RUNNER, "_codex_version", return_value="codex-cli test"
                ),
                mock.patch.object(
                    RUNNER, "_install_candidate", side_effect=fake_install
                ),
            ):
                report = RUNNER.run_evaluations(args)

        selected = next(
            result
            for result in report["results"]
            if result["id"] == "routine-no-human"
        )
        self.assertEqual("unmeasured", selected["status"])
        self.assertEqual("unmeasured", report["discovery"]["status"])
        self.assertFalse(report["evaluator"]["unchanged_during_run"])
        identity = report["host"]["codex_executable"]["identity"]
        self.assertFalse(identity["attribution_complete"])
        self.assertEqual("missing", identity["after_run"]["file_type"])
        serialized = json.dumps(report)
        self.assertNotIn(str(ROOT), serialized)
        self.assertNotIn(str(Path.home()), serialized)
        self.assertNotIn(absolute_tool, serialized)
        self.assertNotIn(relative_entry, serialized)

    def test_candidate_git_objects_ignore_local_replace_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            repository = Path(temp_dir) / "repository"
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--quiet",
                    "--no-hardlinks",
                    str(ROOT),
                    str(repository),
                ],
                check=True,
            )
            original = subprocess.check_output(
                ["git", "-C", str(repository), "rev-parse", "HEAD"],
                text=True,
            ).strip()
            expected = RUNNER._git_candidate_package(repository, original)

            skill = (
                repository
                / RUNNER.PLUGIN_RELATIVE
                / "skills"
                / RUNNER.PLUGIN_NAME
                / "SKILL.md"
            )
            skill.write_bytes(skill.read_bytes() + b"\nreplacement payload\n")
            subprocess.run(
                ["git", "-C", str(repository), "add", str(skill)], check=True
            )
            subprocess.run(
                [
                    "git",
                    "-C",
                    str(repository),
                    "-c",
                    "user.name=OpenBoa Test",
                    "-c",
                    "user.email=test@openboa.invalid",
                    "commit",
                    "--quiet",
                    "-m",
                    "replacement candidate",
                ],
                check=True,
            )
            replacement = subprocess.check_output(
                ["git", "-C", str(repository), "rev-parse", "HEAD"],
                text=True,
            ).strip()
            subprocess.run(
                ["git", "-C", str(repository), "replace", original, replacement],
                check=True,
            )
            replaced_tree = subprocess.check_output(
                [
                    "git",
                    "-C",
                    str(repository),
                    "rev-parse",
                    f"{original}:{RUNNER.PLUGIN_RELATIVE.as_posix()}",
                ],
                text=True,
            ).strip()
            self.assertNotEqual(expected.plugin_tree_oid, replaced_tree)

            observed = RUNNER._git_candidate_package(repository, original)
            self.assertEqual(original, observed.revision)
            self.assertEqual(expected.plugin_tree_oid, observed.plugin_tree_oid)
            self.assertEqual(expected.plugin_sha256, observed.plugin_sha256)
            self.assertEqual(expected.bundle_sha256, observed.bundle_sha256)

    def test_candidate_marketplace_rejects_redirects_and_duplicates(self) -> None:
        source = ROOT / RUNNER.MARKETPLACE_MANIFEST_RELATIVE
        base = json.loads(source.read_text(encoding="utf-8"))
        mutations = {
            "parent traversal": lambda value: value["plugins"][0]["source"].__setitem__(
                "path", "../alternate"
            ),
            "absolute path": lambda value: value["plugins"][0]["source"].__setitem__(
                "path", "/tmp/alternate"
            ),
            "remote source": lambda value: value["plugins"][0].__setitem__(
                "source", {"source": "git", "url": "https://example.invalid/plugin"}
            ),
            "duplicate plugin": lambda value: value["plugins"].append(
                dict(value["plugins"][0])
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                payload = json.loads(json.dumps(base))
                mutate(payload)
                with self.assertRaises(RUNNER.CaseDefinitionError):
                    RUNNER._validate_marketplace_bytes(
                        json.dumps(payload).encode("utf-8"), source=source
                    )

    def test_candidate_plugin_contract_is_skills_only_and_contained(self) -> None:
        manifest_path = ROOT / RUNNER.PLUGIN_RELATIVE / RUNNER.PLUGIN_MANIFEST_RELATIVE
        base = json.loads(manifest_path.read_text(encoding="utf-8"))
        package = RUNNER._git_candidate_package(ROOT, "HEAD")
        entries = tuple(
            RUNNER.PackageEntry(
                path=entry.path.removeprefix(
                    f"{RUNNER.PLUGIN_RELATIVE.as_posix()}/"
                ),
                executable=entry.executable,
                raw_bytes=entry.raw_bytes,
                git_oid=entry.git_oid,
            )
            for entry in package.entries
            if entry.path.startswith(f"{RUNNER.PLUGIN_RELATIVE.as_posix()}/")
        )

        self.assertEqual(
            base["version"],
            RUNNER._validate_candidate_plugin_contract(base, entries),
        )
        hook_entry = next(
            entry for entry in entries if entry.path == "hooks/hooks.json"
        )
        hostile_hooks = json.loads(hook_entry.raw_bytes.decode("utf-8"))
        hostile_hooks["hooks"]["Stop"] = hostile_hooks["hooks"]["PostCompact"]
        mutated_entries = tuple(
            RUNNER.PackageEntry(
                entry.path,
                entry.executable,
                json.dumps(hostile_hooks).encode("utf-8"),
                entry.git_oid,
            )
            if entry.path == "hooks/hooks.json"
            else entry
            for entry in entries
        )
        with self.assertRaisesRegex(
            RUNNER.CaseDefinitionError, "only SessionStart and PostCompact"
        ):
            RUNNER._validate_candidate_plugin_contract(base, mutated_entries)
        prefixed_hooks = json.loads(hook_entry.raw_bytes.decode("utf-8"))
        handler = prefixed_hooks["hooks"]["SessionStart"][0]["hooks"][0]
        handler["command"] = "touch /tmp/marker; " + handler["command"]
        prefixed_entries = tuple(
            RUNNER.PackageEntry(
                entry.path,
                entry.executable,
                json.dumps(prefixed_hooks).encode("utf-8"),
                entry.git_oid,
            )
            if entry.path == "hooks/hooks.json"
            else entry
            for entry in entries
        )
        with self.assertRaisesRegex(
            RUNNER.CaseDefinitionError, "not the read-only doctor"
        ):
            RUNNER._validate_candidate_plugin_contract(base, prefixed_entries)
        without_hooks = tuple(
            entry for entry in entries if entry.path != RUNNER.BUNDLED_HOOKS_PATH
        )
        with self.assertRaisesRegex(RUNNER.CaseDefinitionError, "missing required bundled hooks"):
            RUNNER._validate_candidate_plugin_contract(base, without_hooks)
        without_doctor = tuple(
            entry for entry in entries if entry.path != RUNNER.BUNDLED_DOCTOR_PATH
        )
        with self.assertRaisesRegex(RUNNER.CaseDefinitionError, "missing required automatic doctor"):
            RUNNER._validate_candidate_plugin_contract(base, without_doctor)
        hostile_doctor = tuple(
            RUNNER.PackageEntry(
                entry.path,
                entry.executable,
                b"from pathlib import Path\nPath('/tmp/openboa-hostile').touch()\n",
                entry.git_oid,
            )
            if entry.path == RUNNER.BUNDLED_DOCTOR_PATH
            else entry
            for entry in entries
        )
        with self.assertRaisesRegex(RUNNER.CaseDefinitionError, "trusted 0.2.0 artifact"):
            RUNNER._validate_candidate_plugin_contract(base, hostile_doctor)
        mutations = {
            "skills traversal": lambda value: value.__setitem__(
                "skills", "../outside"
            ),
            "mcp server": lambda value: value.__setitem__(
                "mcpServers", {"outside": {"command": "outside"}}
            ),
            "app": lambda value: value.__setitem__("apps", "./.app.json"),
            "hook": lambda value: value.__setitem__("hooks", "./hooks.json"),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                payload = json.loads(json.dumps(base))
                mutate(payload)
                with self.assertRaises(RUNNER.CaseDefinitionError):
                    RUNNER._validate_candidate_plugin_contract(payload, entries)

        undeclared = (
            *entries,
            RUNNER.PackageEntry(
                path="agents/escape.md",
                executable=False,
                raw_bytes=b"outside declared skills root",
            ),
        )
        with self.assertRaisesRegex(
            RUNNER.CaseDefinitionError, "undeclared loading surface"
        ):
            RUNNER._validate_candidate_plugin_contract(base, undeclared)

    def test_exact_candidate_digest_includes_extra_bytes_and_executable_bit(self) -> None:
        with (
            RUNNER._candidate_snapshot(ROOT, "HEAD") as snapshot,
            tempfile.TemporaryDirectory() as temp_dir,
        ):
            plugin = Path(temp_dir) / "plugin"
            shutil.copytree(snapshot.plugin_root, plugin)
            RUNNER._make_tree_owner_writable(plugin)
            baseline = RUNNER._filesystem_plugin_digest(plugin)

            cache = plugin / "__pycache__"
            cache.mkdir()
            (cache / "payload.pyc").write_bytes(b"transient installed bytes")
            self.assertNotEqual(baseline, RUNNER._filesystem_plugin_digest(plugin))
            (cache / "payload.pyc").unlink()
            cache.rmdir()

            target = plugin / ".codex-plugin" / "plugin.json"
            target.chmod(0o700)
            self.assertNotEqual(baseline, RUNNER._filesystem_plugin_digest(plugin))
            target.chmod(0o600)
            self.assertEqual(baseline, RUNNER._filesystem_plugin_digest(plugin))

            symlink = plugin / "outside-link"
            symlink.symlink_to(target)
            with self.assertRaisesRegex(
                RUNNER.CaseDefinitionError, "contains a symlink"
            ):
                RUNNER._filesystem_plugin_digest(plugin)

    def test_candidate_package_rejects_nonportable_materialization_paths(self) -> None:
        unsafe_paths = (
            "skills/../../escape",
            "skills/x\\..\\..\\escape",
            "skills/C:/escape",
            "skills/control\nname",
            "skills//duplicate-separator",
            "skills/x/.. /.. /escape",
            "skills/trailing./escape",
            "skills/CON/payload",
            "skills/lpt1.txt/payload",
        )
        for unsafe in unsafe_paths:
            with self.subTest(path=repr(unsafe)):
                entry = RUNNER.PackageEntry(
                    path=unsafe,
                    executable=False,
                    raw_bytes=b"unsafe",
                )
                with self.assertRaisesRegex(
                    RUNNER.CaseDefinitionError, "unsafe path"
                ):
                    RUNNER._package_digest((entry,))

                package = RUNNER.CandidatePackage(
                    revision="a" * 40,
                    plugin_tree_oid="b" * 40,
                    marketplace_blob_oid="c" * 40,
                    marketplace_bytes=b"{}",
                    marketplace_sha256="d" * 64,
                    plugin_sha256="e" * 64,
                    bundle_sha256="f" * 64,
                    version="0.1.0",
                    entries=(entry,),
                )
                with tempfile.TemporaryDirectory() as temp_dir:
                    with self.assertRaisesRegex(
                        RUNNER.CaseDefinitionError, "unsafe path"
                    ):
                        RUNNER._materialize_candidate_snapshot(
                            package, Path(temp_dir)
                        )

    def test_install_uses_snapshot_and_verifies_actual_cache_bytes(self) -> None:
        for mutation, should_succeed in ((None, True), ("extra-byte", False)):
            with (
                self.subTest(mutation=mutation),
                RUNNER._candidate_snapshot(ROOT, "HEAD") as snapshot,
                tempfile.TemporaryDirectory() as home_dir,
            ):
                codex_home = Path(home_dir)
                installed_root = (
                    codex_home
                    / "plugins"
                    / "cache"
                    / RUNNER.MARKETPLACE_NAME
                    / RUNNER.PLUGIN_NAME
                    / snapshot.package.version
                )
                observed_commands = []

                def fake_command(command, **_kwargs):
                    observed_commands.append(command)
                    if command[1:4] == ["plugin", "marketplace", "add"]:
                        return RUNNER.CommandResult(
                            0,
                            json.dumps(
                                {
                                    "marketplaceName": RUNNER.MARKETPLACE_NAME,
                                    "installedRoot": str(snapshot.root),
                                    "alreadyAdded": False,
                                }
                            ),
                            "",
                        )
                    if command[1:3] == ["plugin", "add"]:
                        installed_root.parent.mkdir(parents=True)
                        shutil.copytree(snapshot.plugin_root, installed_root)
                        if mutation == "extra-byte":
                            installed_root.chmod(0o700)
                            extra = installed_root / "__pycache__"
                            extra.mkdir()
                            (extra / "payload.pyc").write_bytes(b"wrong candidate")
                        return RUNNER.CommandResult(
                            0,
                            json.dumps(
                                {
                                    "pluginId": (
                                        f"{RUNNER.PLUGIN_NAME}@{RUNNER.MARKETPLACE_NAME}"
                                    ),
                                    "name": RUNNER.PLUGIN_NAME,
                                    "marketplaceName": RUNNER.MARKETPLACE_NAME,
                                    "version": snapshot.package.version,
                                    "installedPath": str(installed_root),
                                }
                            ),
                            "",
                        )
                    return RUNNER.CommandResult(
                        0,
                        json.dumps(
                            {
                                "installed": [
                                    {
                                        "pluginId": (
                                            f"{RUNNER.PLUGIN_NAME}@{RUNNER.MARKETPLACE_NAME}"
                                        ),
                                        "name": RUNNER.PLUGIN_NAME,
                                        "marketplaceName": RUNNER.MARKETPLACE_NAME,
                                        "version": snapshot.package.version,
                                        "installed": True,
                                        "enabled": True,
                                        "source": {
                                            "source": "local",
                                            "path": str(snapshot.plugin_root),
                                        },
                                        "marketplaceSource": {
                                            "sourceType": "local",
                                            "source": str(snapshot.root),
                                        },
                                    }
                                ]
                            }
                        ),
                        "",
                    )

                try:
                    with mock.patch.object(
                        RUNNER, "_run_command", side_effect=fake_command
                    ):
                        installed, error = RUNNER._install_candidate(
                            snapshot=snapshot,
                            codex_home=codex_home,
                            codex_bin="codex",
                            timeout=30,
                        )
                    self.assertEqual(str(snapshot.root), observed_commands[0][4])
                    self.assertNotEqual(str(ROOT), observed_commands[0][4])
                    if should_succeed:
                        self.assertIsNone(error)
                        self.assertIsNotNone(installed)
                        self.assertEqual(
                            snapshot.package.plugin_sha256,
                            installed.after_install_sha256,
                        )
                        self.assertTrue(installed.evidence["matches_snapshot"])
                    else:
                        self.assertIsNotNone(installed)
                        self.assertFalse(installed.evidence["matches_snapshot"])
                        self.assertIn("did not match", error)
                finally:
                    RUNNER._make_tree_owner_writable(codex_home)

    def test_install_rejects_an_installed_path_outside_temporary_home(self) -> None:
        with (
            RUNNER._candidate_snapshot(ROOT, "HEAD") as snapshot,
            tempfile.TemporaryDirectory() as home_dir,
        ):
            codex_home = Path(home_dir)
            cache = codex_home / "plugins" / "cache"
            cache.mkdir(parents=True)
            expected = (
                cache
                / RUNNER.MARKETPLACE_NAME
                / RUNNER.PLUGIN_NAME
                / snapshot.package.version
            )
            expected.parent.mkdir(parents=True)
            shutil.copytree(snapshot.plugin_root, expected)

            def fake_command(command, **_kwargs):
                if command[1:4] == ["plugin", "marketplace", "add"]:
                    payload = {
                        "marketplaceName": RUNNER.MARKETPLACE_NAME,
                        "installedRoot": str(snapshot.root),
                    }
                elif command[1:3] == ["plugin", "add"]:
                    payload = {
                        "pluginId": f"{RUNNER.PLUGIN_NAME}@{RUNNER.MARKETPLACE_NAME}",
                        "name": RUNNER.PLUGIN_NAME,
                        "marketplaceName": RUNNER.MARKETPLACE_NAME,
                        "version": snapshot.package.version,
                        "installedPath": str(snapshot.plugin_root),
                    }
                else:
                    payload = {
                        "installed": [
                            {
                                "pluginId": f"{RUNNER.PLUGIN_NAME}@{RUNNER.MARKETPLACE_NAME}",
                                "name": RUNNER.PLUGIN_NAME,
                                "marketplaceName": RUNNER.MARKETPLACE_NAME,
                                "version": snapshot.package.version,
                                "installed": True,
                                "enabled": True,
                                "source": {
                                    "source": "local",
                                    "path": str(snapshot.plugin_root),
                                },
                                "marketplaceSource": {
                                    "sourceType": "local",
                                    "source": str(snapshot.root),
                                },
                            }
                        ]
                    }
                return RUNNER.CommandResult(0, json.dumps(payload), "")

            with mock.patch.object(RUNNER, "_run_command", side_effect=fake_command):
                installed, error = RUNNER._install_candidate(
                    snapshot=snapshot,
                    codex_home=codex_home,
                    codex_bin="codex",
                    timeout=30,
                )
        self.assertIsNone(installed)
        self.assertIn("escaped", error)

    def test_install_rejects_an_alias_to_the_expected_cache(self) -> None:
        with (
            RUNNER._candidate_snapshot(ROOT, "HEAD") as snapshot,
            tempfile.TemporaryDirectory() as home_dir,
            tempfile.TemporaryDirectory() as alias_dir,
        ):
            codex_home = Path(home_dir)
            expected = (
                codex_home
                / "plugins"
                / "cache"
                / RUNNER.MARKETPLACE_NAME
                / RUNNER.PLUGIN_NAME
                / snapshot.package.version
            )
            expected.parent.mkdir(parents=True)
            shutil.copytree(snapshot.plugin_root, expected)
            alias = Path(alias_dir) / "installed-alias"
            alias.symlink_to(expected, target_is_directory=True)

            def fake_command(command, **_kwargs):
                if command[1:4] == ["plugin", "marketplace", "add"]:
                    payload = {
                        "marketplaceName": RUNNER.MARKETPLACE_NAME,
                        "installedRoot": str(snapshot.root),
                    }
                elif command[1:3] == ["plugin", "add"]:
                    payload = {
                        "pluginId": f"{RUNNER.PLUGIN_NAME}@{RUNNER.MARKETPLACE_NAME}",
                        "name": RUNNER.PLUGIN_NAME,
                        "marketplaceName": RUNNER.MARKETPLACE_NAME,
                        "version": snapshot.package.version,
                        "installedPath": str(alias),
                    }
                else:
                    payload = {
                        "installed": [
                            {
                                "pluginId": f"{RUNNER.PLUGIN_NAME}@{RUNNER.MARKETPLACE_NAME}",
                                "name": RUNNER.PLUGIN_NAME,
                                "marketplaceName": RUNNER.MARKETPLACE_NAME,
                                "version": snapshot.package.version,
                                "installed": True,
                                "enabled": True,
                                "source": {
                                    "source": "local",
                                    "path": str(snapshot.plugin_root),
                                },
                                "marketplaceSource": {
                                    "sourceType": "local",
                                    "source": str(snapshot.root),
                                },
                            }
                        ]
                    }
                return RUNNER.CommandResult(0, json.dumps(payload), "")

            with mock.patch.object(RUNNER, "_run_command", side_effect=fake_command):
                installed, error = RUNNER._install_candidate(
                    snapshot=snapshot,
                    codex_home=codex_home,
                    codex_bin="codex",
                    timeout=30,
                )
        self.assertIsNone(installed)
        self.assertIn("escaped", error)

    def test_install_rejects_symlinked_cache_components(self) -> None:
        for layout in ("external-cache", "internal-marketplace-parent"):
            with (
                self.subTest(layout=layout),
                RUNNER._candidate_snapshot(ROOT, "HEAD") as snapshot,
                tempfile.TemporaryDirectory() as home_dir,
                tempfile.TemporaryDirectory() as external_dir,
            ):
                codex_home = Path(home_dir)
                external = Path(external_dir)
                plugins_root = codex_home / "plugins"
                plugins_root.mkdir()
                expected = (
                    plugins_root
                    / "cache"
                    / RUNNER.MARKETPLACE_NAME
                    / RUNNER.PLUGIN_NAME
                    / snapshot.package.version
                )
                if layout == "external-cache":
                    (plugins_root / "cache").symlink_to(
                        external, target_is_directory=True
                    )
                    actual = (
                        external
                        / RUNNER.MARKETPLACE_NAME
                        / RUNNER.PLUGIN_NAME
                        / snapshot.package.version
                    )
                else:
                    cache = plugins_root / "cache"
                    cache.mkdir()
                    alternate = cache / "alternate"
                    alternate.mkdir()
                    (cache / RUNNER.MARKETPLACE_NAME).symlink_to(
                        alternate, target_is_directory=True
                    )
                    actual = (
                        alternate / RUNNER.PLUGIN_NAME / snapshot.package.version
                    )
                actual.parent.mkdir(parents=True)
                shutil.copytree(snapshot.plugin_root, actual)

                def fake_command(command, **_kwargs):
                    if command[1:4] == ["plugin", "marketplace", "add"]:
                        payload = {
                            "marketplaceName": RUNNER.MARKETPLACE_NAME,
                            "installedRoot": str(snapshot.root),
                        }
                    elif command[1:3] == ["plugin", "add"]:
                        payload = {
                            "pluginId": f"{RUNNER.PLUGIN_NAME}@{RUNNER.MARKETPLACE_NAME}",
                            "name": RUNNER.PLUGIN_NAME,
                            "marketplaceName": RUNNER.MARKETPLACE_NAME,
                            "version": snapshot.package.version,
                            "installedPath": str(expected),
                        }
                    else:
                        payload = {
                            "installed": [
                                {
                                    "pluginId": f"{RUNNER.PLUGIN_NAME}@{RUNNER.MARKETPLACE_NAME}",
                                    "name": RUNNER.PLUGIN_NAME,
                                    "marketplaceName": RUNNER.MARKETPLACE_NAME,
                                    "version": snapshot.package.version,
                                    "installed": True,
                                    "enabled": True,
                                    "source": {
                                        "source": "local",
                                        "path": str(snapshot.plugin_root),
                                    },
                                    "marketplaceSource": {
                                        "sourceType": "local",
                                        "source": str(snapshot.root),
                                    },
                                }
                            ]
                        }
                    return RUNNER.CommandResult(0, json.dumps(payload), "")

                try:
                    with mock.patch.object(
                        RUNNER, "_run_command", side_effect=fake_command
                    ):
                        installed, error = RUNNER._install_candidate(
                            snapshot=snapshot,
                            codex_home=codex_home,
                            codex_bin="codex",
                            timeout=30,
                        )
                    self.assertIsNone(installed)
                    self.assertIn("symlink component", error)
                finally:
                    RUNNER._make_tree_owner_writable(external)

    def test_install_rejects_malformed_list_shapes_without_traceback(self) -> None:
        malformed_sources = (
            "malformed",
            None,
            [],
            {"source": "local", "path": None},
            {"source": "local", "path": "\0"},
        )
        for malformed in malformed_sources:
            with (
                self.subTest(malformed=repr(malformed)),
                RUNNER._candidate_snapshot(ROOT, "HEAD") as snapshot,
                tempfile.TemporaryDirectory() as home_dir,
            ):
                codex_home = Path(home_dir)

                def fake_command(command, **_kwargs):
                    if command[1:4] == ["plugin", "marketplace", "add"]:
                        payload = {
                            "marketplaceName": RUNNER.MARKETPLACE_NAME,
                            "installedRoot": str(snapshot.root),
                        }
                    elif command[1:3] == ["plugin", "add"]:
                        payload = {
                            "pluginId": f"{RUNNER.PLUGIN_NAME}@{RUNNER.MARKETPLACE_NAME}",
                            "name": RUNNER.PLUGIN_NAME,
                            "marketplaceName": RUNNER.MARKETPLACE_NAME,
                            "version": snapshot.package.version,
                            "installedPath": str(codex_home / "unused"),
                        }
                    else:
                        payload = {
                            "installed": [
                                {
                                    "pluginId": f"{RUNNER.PLUGIN_NAME}@{RUNNER.MARKETPLACE_NAME}",
                                    "name": RUNNER.PLUGIN_NAME,
                                    "marketplaceName": RUNNER.MARKETPLACE_NAME,
                                    "version": snapshot.package.version,
                                    "installed": True,
                                    "enabled": True,
                                    "source": malformed,
                                    "marketplaceSource": {
                                        "sourceType": "local",
                                        "source": str(snapshot.root),
                                    },
                                }
                            ]
                        }
                    return RUNNER.CommandResult(0, json.dumps(payload), "")

                with mock.patch.object(
                    RUNNER, "_run_command", side_effect=fake_command
                ):
                    installed, error = RUNNER._install_candidate(
                        snapshot=snapshot,
                        codex_home=codex_home,
                        codex_bin="codex",
                        timeout=30,
                    )
                self.assertIsNone(installed)
                self.assertIsInstance(error, str)

    def test_changed_candidate_invalidates_selected_run(self) -> None:
        results = [
            {
                "id": "selected",
                "status": "passed",
                "reason": "observed",
                "criteria": [],
                "method_match": True,
                "method_criteria": [],
                "evidence": {},
            },
            {
                "id": "not-selected",
                "status": "unmeasured",
                "reason": "not selected",
                "criteria": [],
                "method_match": "unmeasured",
                "method_criteria": [],
                "evidence": {},
            },
        ]
        discovery = {
            "status": "passed",
            "explicit_invocation": "passed",
            "implicit_invocation": "unmeasured",
            "reason": "observed",
            "evidence": {},
        }
        unchanged = RUNNER.apply_candidate_attribution(
            results=results,
            discovery=discovery,
            selected_ids={"selected"},
            attributable=False,
            execution_requested=True,
        )
        self.assertFalse(unchanged)
        self.assertEqual("unmeasured", results[0]["status"])
        self.assertEqual("passed", results[0]["evidence"]["candidate_attribution"]["observed_status"])
        self.assertEqual("unmeasured", discovery["status"])

    def test_installed_cache_change_invalidates_selected_run(self) -> None:
        observed_marker = {
            "status": "observed",
            "reason": "probe returned",
            "evidence": {"tool_calls": 0, "marker_match": True},
        }
        observed_control = {
            "status": "observed",
            "reason": "probe returned",
            "evidence": {"tool_calls": 0, "marker_match": False},
        }
        installed_root: Path | None = None

        def fake_install(*, snapshot, codex_home, **_kwargs):
            nonlocal installed_root
            installed_root = (
                codex_home
                / "plugins"
                / "cache"
                / RUNNER.MARKETPLACE_NAME
                / RUNNER.PLUGIN_NAME
                / snapshot.package.version
            )
            installed_root.parent.mkdir(parents=True)
            shutil.copytree(snapshot.plugin_root, installed_root)
            for directory in [
                installed_root,
                *(path for path in installed_root.rglob("*") if path.is_dir()),
            ]:
                directory.chmod(0o700)
            digest = RUNNER._filesystem_plugin_digest(installed_root)
            return (
                RUNNER.InstalledCandidate(
                    root=installed_root,
                    after_install_sha256=digest,
                    evidence={
                        "plugin": RUNNER.PLUGIN_NAME,
                        "enabled": True,
                        "installed_content_sha256": digest,
                    },
                ),
                None,
            )

        def fake_run_case(case, **_kwargs):
            assert installed_root is not None
            target = (
                installed_root
                / "skills"
                / RUNNER.PLUGIN_NAME
                / "SKILL.md"
            )
            target.chmod(0o600)
            target.write_bytes(target.read_bytes() + b"\ncache tamper\n")
            return {
                "id": case.identifier,
                "status": "passed",
                "reason": "simulated attributable output",
                "criteria": [],
                "method_match": True,
                "method_criteria": [],
                "evidence": {"tool_calls": 0},
            }

        with tempfile.TemporaryDirectory() as temp_dir:
            auth = Path(temp_dir) / "auth.json"
            auth.write_text("{}\n", encoding="utf-8")
            args = argparse.Namespace(
                root=ROOT,
                codex=True,
                case_ids=["routine-no-human"],
                codex_bin=sys.executable,
                candidate_revision="HEAD",
                auth_source=auth,
                output=None,
                run_id="installed-cache-race-test",
                timeout_seconds=30,
                require_complete=False,
            )
            with (
                mock.patch.object(
                    RUNNER, "_codex_version", return_value="codex-cli test"
                ),
                mock.patch.object(
                    RUNNER, "_install_candidate", side_effect=fake_install
                ),
                mock.patch.object(
                    RUNNER,
                    "_run_discovery_probe",
                    side_effect=[observed_marker, observed_control],
                ),
                mock.patch.object(RUNNER, "_run_case", side_effect=fake_run_case),
            ):
                report = RUNNER.run_evaluations(args)

        selected = next(
            result for result in report["results"] if result["id"] == "routine-no-human"
        )
        self.assertEqual("unmeasured", selected["status"])
        self.assertEqual(
            "passed",
            selected["evidence"]["candidate_attribution"]["observed_status"],
        )
        self.assertEqual("unmeasured", report["discovery"]["status"])
        self.assertFalse(report["candidate"]["attribution_complete"])
        self.assertFalse(report["candidate"]["installed"]["matches_snapshot"])
        self.assertTrue(report["isolation"]["temporary_artifacts_removed"])
        self.assertFalse(report["isolation"]["auth_copy_retained"])

    def test_install_mismatch_is_reported_as_unattributed_not_unchanged(self) -> None:
        def fake_install(*, snapshot, codex_home, **_kwargs):
            installed_root = (
                codex_home
                / "plugins"
                / "cache"
                / RUNNER.MARKETPLACE_NAME
                / RUNNER.PLUGIN_NAME
                / snapshot.package.version
            )
            installed_root.parent.mkdir(parents=True)
            shutil.copytree(snapshot.plugin_root, installed_root)
            installed_root.chmod(0o700)
            extra = installed_root / "__pycache__"
            extra.mkdir()
            (extra / "payload.pyc").write_bytes(b"wrong installed candidate")
            digest = RUNNER._filesystem_plugin_digest(installed_root)
            return (
                RUNNER.InstalledCandidate(
                    root=installed_root,
                    after_install_sha256=digest,
                    evidence={"matches_snapshot": False},
                ),
                "installed candidate content did not match the private snapshot",
            )

        with tempfile.TemporaryDirectory() as temp_dir:
            auth = Path(temp_dir) / "auth.json"
            auth.write_text("{}\n", encoding="utf-8")
            args = argparse.Namespace(
                root=ROOT,
                codex=True,
                case_ids=["routine-no-human"],
                codex_bin=sys.executable,
                candidate_revision="HEAD",
                auth_source=auth,
                output=None,
                run_id="install-mismatch-test",
                timeout_seconds=30,
                require_complete=False,
            )
            with (
                mock.patch.object(
                    RUNNER, "_codex_version", return_value="codex-cli test"
                ),
                mock.patch.object(
                    RUNNER, "_install_candidate", side_effect=fake_install
                ),
                mock.patch.object(RUNNER, "_run_discovery_probe") as discovery_probe,
                mock.patch.object(RUNNER, "_run_case") as run_case,
            ):
                report = RUNNER.run_evaluations(args)

        selected = next(
            result for result in report["results"] if result["id"] == "routine-no-human"
        )
        self.assertEqual("unmeasured", selected["status"])
        self.assertFalse(report["candidate"]["unchanged_during_run"])
        self.assertFalse(report["candidate"]["attribution_complete"])
        self.assertEqual("unattributed", report["candidate"]["content_sha256"])
        self.assertTrue(report["candidate"]["installed"]["observed"])
        self.assertFalse(report["candidate"]["installed"]["verified"])
        self.assertFalse(report["candidate"]["installed"]["matches_snapshot"])
        discovery_probe.assert_not_called()
        run_case.assert_not_called()

    def test_changed_evaluator_invalidates_selected_run(self) -> None:
        results = [
            {
                "id": "selected",
                "status": "passed",
                "reason": "observed",
                "criteria": [],
                "method_match": True,
                "method_criteria": [],
                "evidence": {},
            }
        ]
        discovery = {
            "status": "passed",
            "explicit_invocation": "passed",
            "implicit_invocation": "unmeasured",
            "reason": "observed",
            "evidence": {},
        }
        unchanged = RUNNER.apply_evaluator_attribution(
            results=results,
            discovery=discovery,
            selected_ids={"selected"},
            before_digests={"runner_sha256": "a" * 64},
            after_digests={"runner_sha256": "b" * 64},
            execution_requested=True,
        )
        self.assertFalse(unchanged)
        self.assertEqual("unmeasured", results[0]["status"])
        self.assertEqual(
            "passed",
            results[0]["evidence"]["evaluator_attribution"]["observed_status"],
        )
        self.assertEqual("unmeasured", discovery["status"])

    def test_definition_and_schema_race_invalidates_the_loaded_evaluation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            for relative in (
                Path("evals/cases"),
                Path("evals/scenarios"),
                Path("evals/fixtures"),
            ):
                shutil.copytree(ROOT / relative, root / relative)
            (root / "scripts").mkdir()
            shutil.copyfile(RUNNER_PATH, root / "scripts" / RUNNER_PATH.name)
            (root / "plugins" / RUNNER.PLUGIN_NAME).mkdir(parents=True)
            auth = root / "auth.json"
            auth.write_text("{}\n", encoding="utf-8")

            case_path = root / "evals" / "cases" / "01-routine-no-human.json"
            scenario_path = (
                root / "evals" / "scenarios" / "01-routine-no-human.md"
            )
            case_schema_path = (
                root / "evals" / "fixtures" / "behavior-case.schema.json"
            )
            output_schema_path = (
                root / "evals" / "fixtures" / "decision-output.schema.json"
            )
            case_before = hashlib.sha256(case_path.read_bytes()).hexdigest()
            scenario_before = hashlib.sha256(scenario_path.read_bytes()).hexdigest()
            case_schema_before = hashlib.sha256(
                case_schema_path.read_bytes()
            ).hexdigest()
            output_schema_bytes = output_schema_path.read_bytes()
            supplied_output_schemas = []
            mutated = False

            def fake_run_case(case, **_kwargs):
                nonlocal mutated
                supplied_output_schemas.append(_kwargs["schema_bytes"])
                if not mutated:
                    case_path.write_bytes(case_path.read_bytes() + b" \n")
                    scenario_path.write_bytes(scenario_path.read_bytes() + b"\n")
                    case_schema_path.write_bytes(
                        case_schema_path.read_bytes() + b"\n"
                    )
                    output_schema_path.write_bytes(b"{}\n")
                    output_schema_path.write_bytes(output_schema_bytes)
                    mutated = True
                return {
                    "id": case.identifier,
                    "status": "passed",
                    "reason": "simulated attributable output",
                    "criteria": [],
                    "method_match": True,
                    "method_criteria": [],
                    "evidence": {"tool_calls": 0},
                }

            observed_marker = {
                "status": "observed",
                "reason": "probe returned",
                "evidence": {"tool_calls": 0, "marker_match": True},
            }
            observed_control = {
                "status": "observed",
                "reason": "probe returned",
                "evidence": {"tool_calls": 0, "marker_match": False},
            }
            args = argparse.Namespace(
                root=root,
                codex=True,
                case_ids=["routine-no-human"],
                codex_bin=sys.executable,
                auth_source=auth,
                output=None,
                run_id="definition-race-test",
                timeout_seconds=30,
                require_complete=False,
            )
            candidate_snapshot = RUNNER._candidate_snapshot
            with (
                mock.patch.object(
                    RUNNER, "_codex_version", return_value="codex-cli test"
                ),
                mock.patch.object(
                    RUNNER,
                    "_candidate_snapshot",
                    side_effect=lambda *_args, **_kwargs: candidate_snapshot(ROOT, "HEAD"),
                ),
                mock.patch.object(
                    RUNNER,
                    "_install_candidate",
                    side_effect=lambda *, snapshot, **_kwargs: (
                        RUNNER.InstalledCandidate(
                            root=snapshot.plugin_root,
                            after_install_sha256=snapshot.package.plugin_sha256,
                            evidence={
                                "plugin": RUNNER.PLUGIN_NAME,
                                "enabled": True,
                            },
                        ),
                        None,
                    ),
                ),
                mock.patch.object(
                    RUNNER,
                    "_run_discovery_probe",
                    side_effect=[observed_marker, observed_control],
                ),
                mock.patch.object(RUNNER, "_run_case", side_effect=fake_run_case),
            ):
                report = RUNNER.run_evaluations(args)

        definitions = report["definitions"]
        self.assertFalse(definitions["unchanged_during_run"])
        self.assertEqual("unattributed", definitions["content_sha256"])
        self.assertFalse(report["evaluator"]["unchanged_during_run"])
        case_name = "evals/cases/01-routine-no-human.json"
        scenario_name = "evals/scenarios/01-routine-no-human.md"
        self.assertEqual(case_before, definitions["before_run"]["cases"][case_name])
        self.assertEqual(
            scenario_before,
            definitions["before_run"]["linked_scenarios"][scenario_name],
        )
        self.assertNotEqual(
            definitions["before_run"]["case_set_sha256"],
            definitions["after_run"]["case_set_sha256"],
        )
        self.assertNotEqual(
            definitions["before_run"]["linked_scenario_set_sha256"],
            definitions["after_run"]["linked_scenario_set_sha256"],
        )
        self.assertEqual(
            case_schema_before,
            report["evaluator"]["before_run"]["case_schema_sha256"],
        )
        self.assertNotEqual(
            report["evaluator"]["before_run"]["case_schema_sha256"],
            report["evaluator"]["after_run"]["case_schema_sha256"],
        )
        self.assertEqual([output_schema_bytes], supplied_output_schemas)
        self.assertEqual(
            report["evaluator"]["before_run"]["output_schema_sha256"],
            report["evaluator"]["after_run"]["output_schema_sha256"],
        )
        selected = next(
            result for result in report["results"] if result["id"] == "routine-no-human"
        )
        self.assertEqual("unmeasured", selected["status"])
        self.assertEqual(
            "passed",
            selected["evidence"]["evaluator_attribution"]["observed_status"],
        )
        self.assertEqual(
            case_before, selected["evidence"]["definition"]["case_sha256"]
        )
        self.assertEqual(
            scenario_before,
            selected["evidence"]["definition"]["scenario_sha256"],
        )
        self.assertEqual("before-run", selected["evidence"]["definition"]["snapshot"])
        self.assertEqual("unmeasured", report["discovery"]["status"])

    def test_case_set_snapshot_detects_add_remove_and_rename(self) -> None:
        for operation in ("add", "remove", "rename"):
            with self.subTest(operation=operation), tempfile.TemporaryDirectory() as temp_dir:
                root = Path(temp_dir).resolve()
                shutil.copytree(ROOT / "evals" / "cases", root / "evals" / "cases")
                shutil.copytree(
                    ROOT / "evals" / "scenarios", root / "evals" / "scenarios"
                )
                shutil.copytree(
                    ROOT / "evals" / "fixtures", root / "evals" / "fixtures"
                )
                cases = RUNNER.load_cases(root)
                before = RUNNER._loaded_definition_snapshot(root, cases)
                target = root / "evals" / "cases" / "01-routine-no-human.json"
                if operation == "add":
                    (target.parent / "99-added.json").write_bytes(target.read_bytes())
                elif operation == "remove":
                    target.unlink()
                else:
                    target.rename(target.parent / "99-renamed.json")
                after = RUNNER._current_definition_snapshot(root, cases)
                self.assertNotEqual(
                    before["case_set_sha256"], after["case_set_sha256"]
                )
                self.assertNotEqual(before["content_sha256"], after["content_sha256"])

    def test_status_counts_keep_unmeasured_and_unsupported_distinct(self) -> None:
        results = [{"status": status} for status in RUNNER.RESULT_STATUSES]
        self.assertEqual(
            {"unmeasured": 1, "passed": 1, "failed": 1, "unsupported": 1},
            RUNNER.status_counts(results),
        )

    def test_require_complete_counts_only_selected_cases(self) -> None:
        results = [
            {"id": "selected", "status": "passed"},
            *(
                {"id": f"unselected-{index}", "status": "unmeasured"}
                for index in range(11)
            ),
        ]
        report = {
            "status_counts": RUNNER.status_counts(results),
            "discovery": {"status": "passed"},
            "results": results,
        }
        with (
            mock.patch.object(RUNNER, "run_evaluations", return_value=report),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(
                0,
                RUNNER.main(
                    ["--case", "selected", "--codex", "--require-complete"]
                ),
            )

    def test_require_complete_preserves_selected_and_discovery_failures(self) -> None:
        cases = (
            ("failed", "passed", False, 1),
            ("unmeasured", "passed", True, 1),
            ("unsupported", "passed", True, 1),
            ("passed", "failed", True, 1),
            ("passed", "unmeasured", True, 1),
        )
        for selected_status, discovery_status, require_complete, expected in cases:
            with self.subTest(
                selected_status=selected_status,
                discovery_status=discovery_status,
                require_complete=require_complete,
            ):
                results = [
                    {"id": "selected", "status": selected_status},
                    {"id": "unselected", "status": "unmeasured"},
                ]
                report = {
                    "status_counts": RUNNER.status_counts(results),
                    "discovery": {"status": discovery_status},
                    "results": results,
                }
                argv = ["--case", "selected", "--codex"]
                if require_complete:
                    argv.append("--require-complete")
                with (
                    mock.patch.object(
                        RUNNER, "run_evaluations", return_value=report
                    ),
                    mock.patch("builtins.print"),
                ):
                    self.assertEqual(expected, RUNNER.main(argv))

    def test_require_complete_without_case_selection_checks_every_result(self) -> None:
        results = [
            {"id": "passed", "status": "passed"},
            {"id": "not-measured", "status": "unmeasured"},
        ]
        report = {
            "status_counts": RUNNER.status_counts(results),
            "discovery": {"status": "passed"},
            "results": results,
        }
        with (
            mock.patch.object(RUNNER, "run_evaluations", return_value=report),
            mock.patch("builtins.print"),
        ):
            self.assertEqual(1, RUNNER.main(["--codex", "--require-complete"]))

    def test_discovery_requires_marker_and_a_no_plugin_negative_control(self) -> None:
        observed = {
            "status": "observed",
            "reason": "probe returned",
            "evidence": {"tool_calls": 0, "marker_match": True},
        }
        no_marker = {
            "status": "observed",
            "reason": "probe returned",
            "evidence": {"tool_calls": 0, "marker_match": False},
        }
        installed = {"plugin": RUNNER.PLUGIN_NAME, "enabled": True}
        result = RUNNER._evaluate_discovery(
            candidate_probe=observed,
            negative_control=no_marker,
            installed=installed,
            codex_version="codex-cli test",
        )
        self.assertEqual("passed", result["status"])

        contaminated = RUNNER._evaluate_discovery(
            candidate_probe=observed,
            negative_control=observed,
            installed=installed,
            codex_version="codex-cli test",
        )
        self.assertEqual("failed", contaminated["status"])

    def test_definition_only_run_is_twenty_one_unmeasured_with_attribution(self) -> None:
        args = argparse.Namespace(
            root=ROOT,
            codex=False,
            case_ids=[],
            codex_bin="codex",
            auth_source=None,
            output=None,
            run_id="definition-only-test",
            timeout_seconds=30,
            require_complete=False,
        )
        report = RUNNER.run_evaluations(args)
        self.assertEqual(
            {"unmeasured": 21, "passed": 0, "failed": 0, "unsupported": 0},
            report["status_counts"],
        )
        self.assertEqual("unmeasured", report["discovery"]["status"])
        self.assertTrue(report["definitions"]["unchanged_during_run"])
        self.assertEqual(
            report["definitions"]["before_run"],
            report["definitions"]["after_run"],
        )
        for result in report["results"]:
            with self.subTest(case=result["id"]):
                definition = result["evidence"]["definition"]
                self.assertRegex(definition["case_sha256"], r"^[0-9a-f]{64}$")
                self.assertRegex(definition["scenario_sha256"], r"^[0-9a-f]{64}$")
                self.assertRegex(definition["prompt_sha256"], r"^[0-9a-f]{64}$")
                self.assertEqual("before-run", definition["snapshot"])

    def test_missing_codex_capability_is_unsupported_not_failed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            auth = Path(temp_dir) / "auth.json"
            auth.write_text("{}\n", encoding="utf-8")
            args = argparse.Namespace(
                root=ROOT,
                codex=True,
                case_ids=[],
                codex_bin=str(Path(temp_dir) / "missing-codex"),
                auth_source=auth,
                output=None,
                run_id="unsupported-host-test",
                timeout_seconds=30,
                require_complete=False,
            )
            report = RUNNER.run_evaluations(args)
        self.assertEqual(
            {"unmeasured": 0, "passed": 0, "failed": 0, "unsupported": 21},
            report["status_counts"],
        )
        self.assertEqual("unsupported", report["discovery"]["status"])

    def test_cli_writes_valid_definition_report(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output = Path(temp_dir) / "report.json"
            completed = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER_PATH),
                    "--root",
                    str(ROOT),
                    "--run-id",
                    "cli-definition-test",
                    "--output",
                    str(output),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(0, completed.returncode, completed.stdout + completed.stderr)
            report = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(21, report["status_counts"]["unmeasured"])
        self.assertEqual("none", report["isolation"]["github_writes"])

    def test_recorded_result_is_complete_and_keeps_unknowns_explicit(self) -> None:
        report = json.loads(RECORDED_RESULT.read_text(encoding="utf-8"))
        results = report["results"]
        self.assertEqual(12, len(results))
        baseline_ids = {json.loads(path.read_text(encoding="utf-8"))["id"] for path in V1_BASELINE.glob("*.json")}
        self.assertEqual(baseline_ids, {result["id"] for result in results})
        self.assertEqual(report["status_counts"], RUNNER.status_counts(results))
        self.assertEqual("passed", report["discovery"]["explicit_invocation"])
        self.assertEqual("unmeasured", report["discovery"]["implicit_invocation"])
        discovery_evidence = report["discovery"]["evidence"]
        self.assertTrue(
            discovery_evidence["candidate_probe"]["evidence"]["marker_match"]
        )
        self.assertFalse(
            discovery_evidence["negative_control_without_plugin"]["evidence"][
                "marker_match"
            ]
        )
        self.assertEqual("unknown", report["measurement"]["model_cost"])
        self.assertEqual("unmeasured", report["measurement"]["external_effects"])
        for result in results:
            with self.subTest(case=result["id"]):
                self.assertIn(result["status"], RUNNER.RESULT_STATUSES)
                self.assertEqual(0, result["evidence"]["tool_calls"])
                self.assertIsInstance(result["evidence"]["decision_record"], dict)
                self.assertEqual(
                    RUNNER.SKILL_EVIDENCE,
                    result["evidence"]["decision_record"]["skill_evidence"],
                )
                self.assertEqual(
                    result["criteria_total"] - len(result["failed_criteria"]),
                    result["criteria_passed"],
                )
                for key in ("case_sha256", "scenario_sha256", "prompt_sha256"):
                    self.assertRegex(
                        result["evidence"]["definition"][key], r"^[0-9a-f]{64}$"
                    )

    def test_v1_baseline_is_immutable(self) -> None:
        self.assertEqual(
            "aa58693e881629b252090dfd13def132f6b9e20d35c4a316f515a1df9ff39150",
            hashlib.sha256(RECORDED_RESULT.read_bytes()).hexdigest(),
        )

    def test_all_v1_case_bytes_match_the_recorded_ledger_hashes(self) -> None:
        ledger = json.loads(RECORDED_RESULT.read_text(encoding="utf-8"))
        recorded = {
            result["id"]: result["evidence"]["definition"]["case_sha256"]
            for result in ledger["results"]
        }
        paths = sorted(V1_BASELINE.glob("*.json"))
        self.assertEqual(12, len(paths))
        observed = {}
        for path in paths:
            payload = json.loads(path.read_text(encoding="utf-8"))
            observed[payload["id"]] = hashlib.sha256(path.read_bytes()).hexdigest()
        self.assertEqual(recorded, observed)

    def test_v2_semantic_diff_from_v1_is_complete_and_bounded(self) -> None:
        removals = {
            "resume-from-live-state": {
                "required_observations": {"durable-work-item"}
            },
            "untrusted-content-cannot-expand-permission": {
                "required_actions": {"report-conflict"}
            },
            "deterministic-test-overrides-correlated-review": {
                "required_actions": {"rerun-trusted-checks"}
            },
        }
        current = {case.identifier: case.payload for case in self.cases}
        baseline = {
            payload["id"]: payload
            for payload in (
                json.loads(path.read_text(encoding="utf-8"))
                for path in sorted(V1_BASELINE.glob("*.json"))
            )
        }
        self.assertTrue(set(baseline).issubset(current))
        self.assertEqual(9, len(set(current) - set(baseline)))

        for identifier in sorted(baseline):
            with self.subTest(case=identifier):
                v1 = baseline[identifier]
                v2 = current[identifier]
                self.assertEqual(1, v1["schema_version"])
                self.assertEqual(2, v2["schema_version"])
                for key in (
                    "id",
                    "scenario",
                    "evaluation_kind",
                    "input",
                    "fixture",
                ):
                    self.assertEqual(v1[key], v2[key], key)

                old = v1["evaluator"]
                new = v2["evaluator"]
                self.assertEqual(old["criteria"], new["criteria"])
                expected_core = dict(old["required_fields"])
                expected_method = {
                    "playbook": expected_core.pop("playbook"),
                    "decision": expected_core.pop("decision"),
                }
                self.assertEqual(expected_core, new["required_fields"])
                self.assertEqual(expected_method, new["method_fields"])

                allowed = removals.get(identifier, {})
                for field in (
                    "required_actions",
                    "forbidden_actions",
                    "required_observations",
                    "required_unknowns",
                ):
                    removed = allowed.get(field, set())
                    expected = [value for value in old[field] if value not in removed]
                    self.assertEqual(expected, new[field], field)
                    self.assertEqual(removed, set(old[field]) - set(new[field]), field)

    def test_r5_result_is_immutable_historical_evidence(self) -> None:
        self.assertEqual(
            "8d4a3334857a8bebfb624c9ac69d2cc25d6610d48b9a287872b45817085e1607",
            hashlib.sha256(R5_RESULT.read_bytes()).hexdigest(),
        )
        report = json.loads(R5_RESULT.read_text(encoding="utf-8"))
        self.assertEqual(
            {"unmeasured": 0, "passed": 12, "failed": 0, "unsupported": 0},
            report["status_counts"],
        )
        self.assertEqual(
            "a157a6fd5b474e7aee7ff25fa22280eec4a28ffd823bbefe96acf3c35463dd97",
            report["evaluator"]["before_run"]["runner_sha256"],
        )

    def _assert_current_attributable_result(
        self, result_path: Path, result_sha256: str, revision: str
    ) -> None:
        self.assertEqual(
            result_sha256,
            hashlib.sha256(result_path.read_bytes()).hexdigest(),
        )
        report = json.loads(result_path.read_text(encoding="utf-8"))
        self.assertEqual(2, report["schema_version"])
        self.assertEqual(2, report["evaluator_version"])
        self.assertEqual("direct-runner-output", report["result_format"])
        self.assertEqual(
            {"unmeasured": 0, "passed": 12, "failed": 0, "unsupported": 0},
            report["status_counts"],
        )

        candidate = report["candidate"]
        self.assertEqual(2, candidate["attribution_version"])
        self.assertTrue(candidate["unchanged_during_run"])
        self.assertTrue(candidate["attribution_complete"])
        source = candidate["source"]
        self.assertEqual("git-objects", source["kind"])
        self.assertEqual(revision, source["revision"])
        # Pull-request CI checks out a depth-one synthetic merge. Its current
        # plugin tree and marketplace blob must still equal the recorded
        # implementation revision even when that parent commit is unavailable.
        package = RUNNER._git_candidate_package(ROOT, "HEAD")
        self.assertEqual(package.plugin_tree_oid, source["plugin_tree_oid"])
        self.assertEqual(package.marketplace_blob_oid, source["marketplace_blob_oid"])
        self.assertEqual(package.plugin_sha256, candidate["content_sha256"])
        self.assertEqual(package.plugin_sha256, candidate["before_install_sha256"])
        self.assertEqual(package.plugin_sha256, candidate["after_run_sha256"])
        self.assertEqual(
            package.marketplace_sha256,
            candidate["marketplace_manifest"]["sha256"],
        )

        snapshot = candidate["snapshot"]
        self.assertTrue(snapshot["created"])
        self.assertEqual(package.plugin_sha256, snapshot["content_sha256"])
        self.assertEqual(package.plugin_sha256, snapshot["after_run_sha256"])
        self.assertEqual(package.bundle_sha256, snapshot["bundle_sha256"])
        self.assertEqual(package.bundle_sha256, snapshot["after_run_bundle_sha256"])
        installed = candidate["installed"]
        self.assertTrue(installed["observed"])
        self.assertTrue(installed["verified"])
        self.assertTrue(installed["matches_snapshot"])
        self.assertEqual(package.plugin_sha256, installed["after_install_sha256"])
        self.assertEqual(package.plugin_sha256, installed["after_run_sha256"])

        definitions = report["definitions"]
        self.assertTrue(definitions["unchanged_during_run"])
        self.assertEqual(definitions["before_run"], definitions["after_run"])
        expected_definitions = RUNNER._loaded_definition_snapshot(ROOT, self.cases)
        self.assertEqual(expected_definitions, definitions["before_run"])
        self.assertEqual(
            expected_definitions["content_sha256"], definitions["content_sha256"]
        )

        evaluator = report["evaluator"]
        self.assertTrue(evaluator["unchanged_during_run"])
        self.assertEqual(evaluator["before_run"], evaluator["after_run"])
        self.assertEqual(
            RUNNER._file_digest(RUNNER_PATH),
            evaluator["before_run"]["runner_sha256"],
        )
        self.assertEqual(
            RUNNER._file_digest(
                ROOT / "evals" / "fixtures" / "behavior-case.schema.json"
            ),
            evaluator["before_run"]["case_schema_sha256"],
        )
        self.assertEqual(
            RUNNER._file_digest(
                ROOT / "evals" / "fixtures" / "decision-output.schema.json"
            ),
            evaluator["before_run"]["output_schema_sha256"],
        )
        self.assertEqual(
            definitions["content_sha256"],
            evaluator["before_run"]["definition_set_sha256"],
        )
        self.assertEqual(
            definitions["before_run"]["case_set_sha256"],
            evaluator["before_run"]["case_set_sha256"],
        )
        self.assertEqual(
            definitions["before_run"]["linked_scenario_set_sha256"],
            evaluator["before_run"]["linked_scenario_set_sha256"],
        )

        self.assertEqual("passed", report["discovery"]["status"])
        self.assertEqual("passed", report["discovery"]["explicit_invocation"])
        self.assertEqual("unmeasured", report["discovery"]["implicit_invocation"])
        self.assertEqual("unmeasured", report["measurement"]["external_effects"])
        self.assertEqual("unknown", report["measurement"]["model_cost"])
        isolation = report["isolation"]
        self.assertTrue(isolation["active_config_unchanged"])
        self.assertTrue(isolation["temporary_artifacts_created"])
        self.assertTrue(isolation["temporary_artifacts_removed"])
        self.assertFalse(isolation["auth_copy_retained"])

        cases = {case.identifier: case for case in self.cases}
        self.assertEqual(set(cases), {result["id"] for result in report["results"]})
        for result in report["results"]:
            with self.subTest(case=result["id"]):
                self.assertEqual("passed", result["status"])
                self.assertTrue(result["criteria"])
                self.assertTrue(all(item["passed"] for item in result["criteria"]))
                self.assertIsInstance(result["method_match"], bool)
                self.assertEqual(2, len(result["method_criteria"]))
                self.assertEqual(0, result["evidence"]["tool_calls"])
                self.assertEqual(
                    RUNNER.SKILL_EVIDENCE,
                    result["evidence"]["decision_record"]["skill_evidence"],
                )
                case = cases[result["id"]]
                definition = result["evidence"]["definition"]
                self.assertEqual(
                    hashlib.sha256(case.raw_bytes).hexdigest(),
                    definition["case_sha256"],
                )
                self.assertEqual(
                    hashlib.sha256(case.scenario_bytes).hexdigest(),
                    definition["scenario_sha256"],
                )
                self.assertEqual(
                    hashlib.sha256(
                        RUNNER.build_prompt(case).encode("utf-8")
                    ).hexdigest(),
                    definition["prompt_sha256"],
                )
                self.assertEqual("before-run", definition["snapshot"])

    def test_r6_result_is_immutable_historical_evidence(self) -> None:
        self.assertEqual(
            "0a6efc9c0844c1736549d450b2d05ebb0a9b16de1040421a7cb1233dc0891083",
            hashlib.sha256(R6_RESULT.read_bytes()).hexdigest(),
        )
        report = json.loads(R6_RESULT.read_text(encoding="utf-8"))
        self.assertEqual(
            {"unmeasured": 0, "passed": 12, "failed": 0, "unsupported": 0},
            report["status_counts"],
        )
        self.assertEqual(
            "0e72f8e46724d4818acbb44ed9b6421611a9a368",
            report["candidate"]["source"]["revision"],
        )
        self.assertTrue(report["candidate"]["attribution_complete"])
        self.assertEqual(
            "19e385dba09150826439a831a460f235c1cd768f20e4604ddbb6701ee0c695fe",
            report["evaluator"]["before_run"]["runner_sha256"],
        )

    def test_r7_result_is_immutable_historical_evidence(self) -> None:
        self.assertEqual(
            "d887115c6fb8a561d410a26e0e14ef219a9b7ff860c3e354d414793c2b08313c",
            hashlib.sha256(R7_RESULT.read_bytes()).hexdigest(),
        )
        report = json.loads(R7_RESULT.read_text(encoding="utf-8"))
        self.assertEqual(
            {"unmeasured": 0, "passed": 12, "failed": 0, "unsupported": 0},
            report["status_counts"],
        )
        self.assertEqual(
            "d31d21496250e0325981f737a480604feaf15bcf",
            report["candidate"]["source"]["revision"],
        )
        self.assertTrue(report["candidate"]["attribution_complete"])
        self.assertEqual(
            "f0d4f7bedcb52a801c5aa8343dfad2c42e342e329bb73637d8bf7e6e63fe8d2e",
            report["evaluator"]["before_run"]["runner_sha256"],
        )

    def test_r8_result_is_immutable_historical_evidence(self) -> None:
        self.assertEqual(
            "240650def695529056fd10ac82a2f6fcd607ac0a6231b7138526de4b9cd2ab83",
            hashlib.sha256(R8_RESULT.read_bytes()).hexdigest(),
        )
        report = json.loads(R8_RESULT.read_text(encoding="utf-8"))
        self.assertEqual(
            {"unmeasured": 0, "passed": 12, "failed": 0, "unsupported": 0},
            report["status_counts"],
        )
        self.assertEqual(
            "6d206a9f9fdd68620ac501d0de695e6037746a27",
            report["candidate"]["source"]["revision"],
        )
        self.assertTrue(report["candidate"]["attribution_complete"])
        self.assertEqual(
            "1a139a89a6fb93542477b50f54a789c91fe2d054690c35ffb0f52d85108677c8",
            report["evaluator"]["before_run"]["runner_sha256"],
        )

    def test_r9_result_is_immutable_historical_evidence(self) -> None:
        self.assertEqual(
            "34efde393a2e065fe8ca57e505b7e702e8ff6be6c70f6047dce0878530a84e96",
            hashlib.sha256(R9_RESULT.read_bytes()).hexdigest(),
        )
        report = json.loads(R9_RESULT.read_text(encoding="utf-8"))
        self.assertEqual(
            {"unmeasured": 0, "passed": 12, "failed": 0, "unsupported": 0},
            report["status_counts"],
        )
        self.assertEqual(
            "9ea2080c0f2f18459bd871a636a5f2826adfded6",
            report["candidate"]["source"]["revision"],
        )

    def test_r10_result_is_immutable_historical_evidence(self) -> None:
        self.assertEqual(
            "f73290490710d0e6b7bd71d2404e2dff7f9f4db309d8daf4fc0e3c9aa5255945",
            hashlib.sha256(R10_RESULT.read_bytes()).hexdigest(),
        )
        report = json.loads(R10_RESULT.read_text(encoding="utf-8"))
        self.assertEqual(
            {"unmeasured": 0, "passed": 12, "failed": 0, "unsupported": 0},
            report["status_counts"],
        )
        self.assertEqual(
            "0cdd1bbb58755883333382ba2f3d007a23730573",
            report["candidate"]["source"]["revision"],
        )

    def test_r11_and_r12_results_are_immutable_retry_observations(self) -> None:
        expected = {
            R11_RESULT: (
                "bc241c4f28ca70094ea6102df160d1c9092a10852888f61c9d9371d3d22b61ab",
                {"unmeasured": 0, "passed": 11, "failed": 1, "unsupported": 0},
            ),
            R12_RESULT: (
                "4d6a59e12ff5ed98a5d271dffc19c13e5dc93cf648042f339132ae12a3266105",
                {"unmeasured": 0, "passed": 11, "failed": 1, "unsupported": 0},
            ),
        }
        for path, (digest, counts) in expected.items():
            with self.subTest(path=path.name):
                self.assertEqual(digest, hashlib.sha256(path.read_bytes()).hexdigest())
                report = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(counts, report["status_counts"])
                self.assertEqual(
                    "00187ca23cc207994af739b341d398bb6fbcbb90",
                    report["candidate"]["source"]["revision"],
                )

    def test_r13_result_is_immutable_historical_evidence(self) -> None:
        self.assertEqual(
            "527cfa939a50c6becafc33855845974bef726b06bca62e04f1dedbdefcc11ff5",
            hashlib.sha256(R13_RESULT.read_bytes()).hexdigest(),
        )
        raw = R13_RESULT.read_text(encoding="utf-8")
        report = json.loads(raw)
        self.assertEqual(
            {"unmeasured": 0, "passed": 12, "failed": 0, "unsupported": 0},
            report["status_counts"],
        )
        self.assertEqual(
            "00187ca23cc207994af739b341d398bb6fbcbb90",
            report["candidate"]["source"]["revision"],
        )
        executable = report["host"]["codex_executable"]
        self.assertEqual(
            {"kind": "bare-name", "name": "codex"}, executable["request"]
        )
        self.assertEqual(
            "repository-root-aware-path-search",
            executable["resolution"]["method"],
        )
        matched_entry = executable["resolution"]["matched_path_entry"]
        self.assertIsInstance(matched_entry, dict)
        self.assertIsInstance(matched_entry.get("index"), int)
        self.assertGreaterEqual(matched_entry["index"], 0)
        self.assertIn(
            matched_entry.get("kind"),
            {"absolute", "repository-relative", "empty-as-repository-root"},
        )
        self.assertEqual("external", executable["resolution"]["resolved_location"])
        self.assertNotIn("resolved_repository_path", executable["resolution"])
        identity = executable["identity"]
        self.assertTrue(identity["unchanged_during_run"])
        self.assertTrue(identity["attribution_complete"])
        self.assertEqual(identity["before_run"], identity["after_run"])
        self.assertEqual("observed", identity["before_run"]["status"])
        self.assertEqual("regular-file", identity["before_run"]["file_type"])
        self.assertTrue(identity["before_run"]["executable"])
        self.assertRegex(identity["before_run"]["sha256"], r"^[0-9a-f]{64}$")
        self.assertEqual(
            identity["before_run"],
            report["evaluator"]["before_run"]["codex_executable_identity"],
        )
        self.assertNotIn(str(ROOT), raw)
        self.assertNotIn(str(Path.home()), raw)
        self.assertNotIn("/opt/homebrew/", raw)

    def test_r14_result_preserves_network_unavailable_attempt(self) -> None:
        self.assertEqual(
            "35a093c7dfb20f8f851a1b4e011a2ea1a557b92ae513793c089e156aa0a2ead2",
            hashlib.sha256(R14_RESULT.read_bytes()).hexdigest(),
        )
        report = json.loads(R14_RESULT.read_text(encoding="utf-8"))
        self.assertEqual(
            {"unmeasured": 21, "passed": 0, "failed": 0, "unsupported": 0},
            report["status_counts"],
        )
        self.assertEqual("unmeasured", report["discovery"]["status"])
        self.assertTrue(report["candidate"]["attribution_complete"])
        self.assertTrue(
            report["discovery"]["evidence"]["installation"]["matches_snapshot"]
        )


if __name__ == "__main__":
    unittest.main()
