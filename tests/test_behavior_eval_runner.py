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
LATEST_RESULT = (
    ROOT
    / "evals"
    / "results"
    / "2026-08-24-codex-0.144.5-v2-direct-r2.json"
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

    def test_exactly_twelve_cases_link_to_unique_scenarios(self) -> None:
        self.assertEqual(12, len(self.cases))
        self.assertEqual(12, len({case.identifier for case in self.cases}))
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
            before_digest="a" * 64,
            after_digest="b" * 64,
            execution_requested=True,
        )
        self.assertFalse(unchanged)
        self.assertEqual("unmeasured", results[0]["status"])
        self.assertEqual("passed", results[0]["evidence"]["candidate_attribution"]["observed_status"])
        self.assertEqual("unmeasured", discovery["status"])

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

    def test_case_and_scenario_race_invalidates_the_loaded_evaluation(self) -> None:
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
            case_before = hashlib.sha256(case_path.read_bytes()).hexdigest()
            scenario_before = hashlib.sha256(scenario_path.read_bytes()).hexdigest()
            mutated = False

            def fake_run_case(case, **_kwargs):
                nonlocal mutated
                if not mutated:
                    case_path.write_bytes(case_path.read_bytes() + b" \n")
                    scenario_path.write_bytes(scenario_path.read_bytes() + b"\n")
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
                codex_bin="codex",
                auth_source=auth,
                output=None,
                run_id="definition-race-test",
                timeout_seconds=30,
                require_complete=False,
            )
            with (
                mock.patch.object(
                    RUNNER, "_codex_version", return_value="codex-cli test"
                ),
                mock.patch.object(
                    RUNNER,
                    "_install_candidate",
                    return_value=(
                        {"plugin": RUNNER.PLUGIN_NAME, "enabled": True},
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

    def test_definition_only_run_is_twelve_unmeasured_with_attribution(self) -> None:
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
            {"unmeasured": 12, "passed": 0, "failed": 0, "unsupported": 0},
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
            {"unmeasured": 0, "passed": 0, "failed": 0, "unsupported": 12},
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
        self.assertEqual(12, report["status_counts"]["unmeasured"])
        self.assertEqual("none", report["isolation"]["github_writes"])

    def test_recorded_result_is_complete_and_keeps_unknowns_explicit(self) -> None:
        report = json.loads(RECORDED_RESULT.read_text(encoding="utf-8"))
        results = report["results"]
        self.assertEqual(12, len(results))
        self.assertEqual(
            {case.identifier for case in self.cases},
            {result["id"] for result in results},
        )
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
        self.assertEqual(set(baseline), set(current))

        for identifier in sorted(current):
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

    def test_v2_result_is_attributable_and_core_complete(self) -> None:
        self.assertEqual(
            "b9acc9a528b2f402dc728d9e6d4c59d8515e1e04fb2536fc1c7f865f46737f38",
            hashlib.sha256(LATEST_RESULT.read_bytes()).hexdigest(),
        )
        report = json.loads(LATEST_RESULT.read_text(encoding="utf-8"))
        self.assertEqual(2, report["schema_version"])
        self.assertEqual(2, report["evaluator_version"])
        self.assertEqual("direct-runner-output", report["result_format"])
        self.assertEqual(
            {"unmeasured": 0, "passed": 12, "failed": 0, "unsupported": 0},
            report["status_counts"],
        )
        candidate = report["candidate"]
        self.assertTrue(candidate["unchanged_during_run"])
        self.assertEqual(
            candidate["before_install_sha256"], candidate["after_run_sha256"]
        )
        self.assertEqual(
            candidate["content_sha256"],
            RUNNER._tree_digest(ROOT / "plugins" / RUNNER.PLUGIN_NAME),
        )
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
        self.assertEqual("passed", report["discovery"]["explicit_invocation"])
        self.assertEqual("unmeasured", report["discovery"]["implicit_invocation"])
        self.assertEqual("unmeasured", report["measurement"]["external_effects"])
        self.assertEqual("unknown", report["measurement"]["model_cost"])

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
                    hashlib.sha256(RUNNER.build_prompt(case).encode("utf-8")).hexdigest(),
                    definition["prompt_sha256"],
                )
                self.assertEqual("before-run", definition["snapshot"])


if __name__ == "__main__":
    unittest.main()
