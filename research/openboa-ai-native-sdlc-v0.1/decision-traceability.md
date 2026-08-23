# Decision Traceability

This table makes the proposed OpenBoa rules falsifiable. A rule is not accepted because a source mentions it; it is accepted only when the evidence, local application, and validation method agree.

| Decision ID | Evidence pattern | Source IDs | Candidate OpenBoa rule | Local validation method | Confidence |
| --- | --- | --- | --- | --- | --- |
| D-01 | Durable goal is more stable than session or PR | OA-02, AN-02, GH-01, LI-01 | Every long-running or delegated task has one human-owned goal record | Inspect Hydra Issue #3 and require owner, outcome, criteria, dependencies, and risk | High |
| D-02 | Repository context and invariants affect agent performance | OA-01, AN-07, GO-03, GH-04, SG-01 | Repository instructions and acceptance commands are versioned, discoverable, and small | Run validator and inspect nearest AGENTS.md plus reference routing | High |
| D-03 | Long runs lose context without structured state | OA-07, AN-02, AN-05, VE-05 | Every run leaves progress, decisions, evidence, blockers, and next action | Use the handoff template at a context boundary and verify restart from clean state | High |
| D-04 | Agent evaluation must include path and outcome | OA-06, AN-04, NV-02, RE-01 | Verification records include tests, tool or trajectory evidence, and outcome evidence | Run a bounded task with a captured command/evidence ledger and independent review | High |
| D-05 | Agent authority is not account identity | NV-01, NV-05, GH-02, LI-01 | Bind connector operations to workspace, repository, goal, risk, and allowed operation | Attempt an out-of-scope operation and confirm it is rejected or handed off | High |
| D-06 | Safety is layered across runtime and workflow | OA-03, AN-06, NV-04, NV-06, GH-03, VE-03 | Combine sandbox, least privilege, safe outputs, approvals, and observation | Audit the governance reference and inspect connector exception path | High |
| D-07 | Multi-agent execution depends on task topology | AN-03, GO-04, CU-01 | Require a topology reason before parallel delegation | Compare a sequential research task with a parallelizable corpus task | Medium-high |
| D-08 | Review and runtime evidence become bottlenecks | OA-02, FA-01, VE-01, CU-01 | Optimize for bounded, reviewable artifacts and observable delivery, not raw output count | Measure artifact completeness and review rework on the research task | Medium-high |
| D-09 | Portable semantics outlast provider implementations | OA-05, AN-05, GO-01, VE-02, VE-03 | Keep goal, state, evidence, and gate semantics provider-neutral | Validate that the research package can be read without a vendor runtime | High |
| D-10 | Reversibility enables safe autonomy | RE-02, VE-04, OA-03 | Use isolated worktrees, disposable environments, and rollback evidence before sensitive delivery | Confirm no main-branch mutation and capture worktree/branch evidence | High |

## Validation status

- D-01: applied to Hydra Issue #3.
- D-02: baseline repository validator and tests pass before research edits.
- D-03 through D-10: draft; require an application exercise and human review before contract migration.
