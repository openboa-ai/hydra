# Design acceptance

The user approved the native Codex implementation plan. Independent review accepted
the scoped specification at SHA256
`918afc1dc9582d8aa6af5b0d7fd670caf1366dded370977ebca066398d2afad5`
against merged base `bdd54f58801b4ce27c9f53d7d676a9afe3e3a7fd`.
The review correction bound same-host admission across repositories and paused/closed
Issues through the existing bounded ownership ticket. This records design acceptance;
source, installed plugin, actual task/questions and delivery remain separate evidence.

Independent follow-up accepted the R5 clarification at SHA256
`f6a42a874724945e72583d222cab68d5ea1e2073f4fa383924f7264f7edbb66d`.
The scoped ownership digest and confirmed committed origin checkpoint address
missing-intent and callback-failure recovery. Implementation review also identified
repository-case normalization and accepted-spec retry accounting; both received
regression tests. Final-head code/security review remains a delivery requirement.

The final independent source review found no remaining actionable defect in the
reviewed native continuation boundary. Reviewed `native.py` SHA256:
`20cbaacd36f23518a5b87a8a992c0f880aba9bae54b6441d69741c163ea41927`.
The changed-intake stop regression also passed independently. This is source
review, not desktop installation, product planning or two-project operation.

## PR review corrections

Code review of commit `47a18eb93e77963531d3b59d67d4093cbefe3d73`
identified four continuation defects: uncertain ticket persistence lost its recovery
identity; uncertain retirement lost discovery; accepted change review could refer to
a different verification run; and completed write summaries remained in memory.

The correction batch returns the scoped recovery identity on uncertain registration,
retains the existing active discovery label until cleanup is confirmed, pairs native
review with the exact process-local verification receipts, and stores summaries only
for review phases. After a service restart, fresh verification requires fresh review.
No delivery gate or approval boundary was relaxed.

Independent source review found no additional actionable defect in this batch.
Reviewed SHA256 values:

- `native.py`: `749bad33b15ba4822eefc5d2c3349b0446e58d6b181c3e404986a9ac1b7a7e00`
- `coordinator.py`: `f7a6620fa21b76dbe2f752100230ae770e61c92da6bb94b7ea3959bc92a03cb2`
- `runner.py`: `f2c38c8d9c6bf788b2c309596e272fb62b4c0c8c67e8c46d637e7cb4f00ed5e2`
- `github.py`: `4a4e2836e490b1678a4f586e38e7ab14fbd367113d36daee2d43d5420e60a92c`

Current-head remote CI, coupled code/security review and required native approval
remain separate delivery conditions.
