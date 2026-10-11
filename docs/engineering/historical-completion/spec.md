# Historical candidate CI reconciliation

Work record: https://github.com/openboa-ai/hydra/issues/3
Base: `679c3d0cd7d71beaa9cbfe33b35e8818e1d14c4e`

## Intent and observed failure

Finish a delivered Issue after a fresh controller reconstructs GitHub evidence.
The successful candidate `pull_request` workflow for Ouroboros PR #6 currently
returns `pull_requests: []` after merge. The exact run/head/branch/workflow and
job/check identities remain available. The existing historical gate rejects this
response and leaves a correctly delivered Issue waiting.

## Authority and boundaries

This is a correction within the accepted GitHub workflow's delivery/recovery
boundary. No new delegation, credentials, policy file, protected check or state
store. Preserve all live merge conditions. Do not edit an installed runtime in
place, forge a receipt, close the Issue manually or add a completion override.
Public artifacts contain only public source and delivery evidence.

## Requirements

- R1: During historical completion only, accept an explicitly empty PR association
  array on a `pull_request` run when the observed PR is exactly `merged=true`,
  `state=closed`, with a valid merge SHA. Retain exact repository, workflow ID/path,
  configured event, candidate SHA and branch binding and job/check identity.
- R2: Missing, null, malformed or incorrect nonempty associations remain rejected.
  Do not change live `gate_checks` or `gate_delivery` eligibility. The existing
  `pull_request_target` exception still requires its pinned reusable producer.
- R3: Completion still requires the exact-head expected-base same-tree squash
  result and method receipt, current candidate code/security review evidence,
  resolved threads and all required successful candidate checks. A newer failed
  bound rerun prevents completion.
- R4: The existing runner still observes required push checks on the actual merge
  commit before exactly one Issue closure. Restart must neither start a model turn
  nor issue another merge for this completed PR. Pending/failed main checks wait.
- R5: Deliver through normal independent review and GitHub CI/review gates. Install
  only the verified merge into a separate fixed-revision runtime and preserve the
  previous runtime for rollback. Then recheck the actual waiting Issue with a fresh
  controller and record observed completion/normal lifecycle cleanup.

## Lifecycle failures and compatibility

Unavailable or ambiguous GitHub facts remain waits. A closed unmerged PR, missing
squash receipt, wrong parent/tree or head, malformed association, source mismatch,
failed rerun or missing review cannot be turned into completion by this exception.
This changes no CLI/MCP input or project TOML format. No additional dependencies.
No host reboot or lost unpublished work recovery is claimed by the controller test.

## Requirement-linked acceptance

- R1/R2: Historical fixture reproduces an empty array after actual merge; it passes
  completion while identical live merge checks reject it, even for a merged PR.
  Missing/null/malformed/wrong nonempty associations fail.
- R1/R3: Wrong workflow/repository/event/head/branch/job/check, newer failed rerun,
  absent review/receipt and wrong squash topology still fail.
- R4: Fresh runner reconstructs an already merged task with empty candidate
  association and successful main checks, performs no model or merge action and
  closes once. Pending/failed main checks keep it open; repeat reconciling cannot
  create a duplicate external effect.
- R5: Current PR CI plus coupled code/security reviews, actual merge and fresh
  installed-controller continuation are reported separately. Native heartbeat
  stays disabled until real completion and restart qualification pass.
