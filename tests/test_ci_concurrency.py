"""P14-T12: literal workflow contract and an explicit event-policy model.

The fixture selects between two known policies; it neither evaluates GitHub
expressions nor schedules Actions runs. Real consecutive-push evidence is O05.
"""

from dataclasses import dataclass, replace
from pathlib import Path
import re
import unittest


ROOT = Path(__file__).resolve().parents[1]
GROUP = (
    "${{ github.workflow }}-${{ github.event_name == 'pull_request' && "
    "format('pr-{0}', github.event.pull_request.number) || format('run-{0}', github.run_id) }}"
)
CANCEL = "${{ github.event_name == 'pull_request' }}"
LEGACY_GROUP = "repository-ci-${{ github.ref }}"


def concurrency(document):
    """Read the two literal scalars, rejecting duplicate or unexpected fields."""
    lines = document.splitlines()
    starts = [i for i, line in enumerate(lines) if line == "concurrency:"]
    if len(starts) != 1:
        raise AssertionError("Expected one top-level concurrency block")
    fields = {}
    for line in lines[starts[0] + 1:]:
        if not line.strip():
            continue
        if not line.startswith(" "):
            break
        match = re.fullmatch(r"  (group|cancel-in-progress): (.+)", line)
        if match is None or match[1] in fields:
            raise AssertionError("Unexpected concurrency field or representation")
        fields[match[1]] = match[2]
    if set(fields) != {"group", "cancel-in-progress"}:
        raise AssertionError("Both concurrency scalars are required")
    return fields


@dataclass(frozen=True)
class Event:
    workflow: str
    event_name: str
    ref: str
    run_id: int
    sha: str
    pr_number: int | None = None


def policy_fixture(fields, event):
    """Closed model of the candidate and original policies, not an interpreter."""
    if fields["group"] == GROUP:
        suffix = (f"pr-{event.pr_number}" if event.event_name == "pull_request"
                  else f"run-{event.run_id}")
        group = f"{event.workflow}-{suffix}"
    elif fields["group"] == LEGACY_GROUP:
        group = f"repository-ci-{event.ref}"
    else:
        raise AssertionError("The expression contract changed; review this fixture")
    if fields["cancel-in-progress"] == CANCEL:
        cancel = event.event_name == "pull_request"
    elif fields["cancel-in-progress"] == "true":
        cancel = True
    else:
        raise AssertionError("The cancellation contract changed; review this fixture")
    return group, cancel


class CIConcurrencyTests(unittest.TestCase):
    def setUp(self):
        self.fields = concurrency((ROOT / ".github/workflows/ci.yml").read_text())
        self.push = Event("Repository CI", "push", "refs/heads/main", 101, "a" * 40)
        self.pr = Event("Repository CI", "pull_request", "refs/pull/7/merge", 201,
                        "b" * 40, pr_number=7)

    def test_workflow_uses_the_reviewed_expression_contract(self):
        self.assertEqual(self.fields, {"group": GROUP, "cancel-in-progress": CANCEL})

    def test_three_main_merge_shas_have_three_independent_groups(self):
        events = [replace(self.push, run_id=101 + i, sha=char * 40)
                  for i, char in enumerate("abc")]
        observed = [policy_fixture(self.fields, event) for event in events]
        # This fails on the actual old workflow: all three map to refs/heads/main.
        self.assertEqual(len({group for group, _ in observed}), 3)
        self.assertEqual([cancel for _, cancel in observed], [False, False, False])
        self.assertEqual([group for group, _ in observed],
                         ["Repository CI-run-101", "Repository CI-run-102", "Repository CI-run-103"])

    def test_same_pr_candidates_share_group_and_allow_obsolete_run_cancellation(self):
        later = replace(self.pr, run_id=202, sha="c" * 40)
        self.assertEqual(policy_fixture(self.fields, self.pr), ("Repository CI-pr-7", True))
        self.assertEqual(policy_fixture(self.fields, later), policy_fixture(self.fields, self.pr))

    def test_different_prs_do_not_share_group(self):
        other = replace(self.pr, pr_number=8, ref="refs/pull/8/merge", run_id=202)
        self.assertEqual(policy_fixture(self.fields, other), ("Repository CI-pr-8", True))
        self.assertNotEqual(policy_fixture(self.fields, self.pr)[0], policy_fixture(self.fields, other)[0])

    def test_workflow_names_partition_both_event_kinds(self):
        for event in (self.push, self.pr):
            with self.subTest(event=event.event_name):
                other = replace(event, workflow="Other CI")
                self.assertNotEqual(policy_fixture(self.fields, event)[0], policy_fixture(self.fields, other)[0])

    def test_pr_number_and_push_run_id_cannot_collide(self):
        push = replace(self.push, run_id=7)
        self.assertEqual(policy_fixture(self.fields, push), ("Repository CI-run-7", False))
        self.assertNotEqual(policy_fixture(self.fields, push)[0], policy_fixture(self.fields, self.pr)[0])

    def test_push_partition_uses_run_id_even_for_the_same_sha(self):
        other = replace(self.push, run_id=102)
        self.assertNotEqual(policy_fixture(self.fields, self.push)[0], policy_fixture(self.fields, other)[0])
