# Evaluator v1 immutable case baseline

The files in `cases/` preserve the exact bytes evaluated by [`2026-08-24-codex-0.144.5.json`](../../results/2026-08-24-codex-0.144.5.json). Their relative scenario links describe the original location and are archival; do not execute these files as current cases.

Every baseline file must retain the `case_sha256` recorded for the same case in the v1 ledger. Changes require a new baseline version and a new run, never an edit to this directory or the v1 result.

Evaluator v2 is checked against this baseline semantically. Across all 12 cases, `playbook` and `decision` move from core `required_fields` to telemetry-only `method_fields`. Only three non-executable requirements may be removed:

- case 03: `durable-work-item`
- case 05: `report-conflict`
- case 07: `rerun-trusted-checks`

Every other required field, required action, required observation, required unknown, and forbidden action must remain identical.
