# Authenticated producer delivery observations

Implementation scope: P11 revision 2 R03 and WR section 9. This internal read-only
step supplies delivery facts. Requirement acceptance, operational observation,
native candidate dispatch and full P11 acceptance remain separate responsibilities.

## Purpose and source boundary

An open producer can have delivered the required output. A closed producer can
have no usable output. Read the authenticated existing progress comment, actual
owned PR and immutable squash result, independent candidate reviews and current
required CI for the exact merge commit. Issue state and success prose supply none
of those facts. The existing GitHub client and project parser own authentication,
source collection, protected configuration and provider identity validation.

`hydra_sdlc.github_producer_delivery.read_delivery(client, repository, source)`
accepts one already allowed repository and its numeric IssueRef. The caller owns
the synchronous client scope and source selection. The reader does not discover
or register repositories. It uses the existing version-1 progress profile for
both legacy and native execution records, without invoking legacy execution.
Unsupported progress formats remain unknown.

## Behavior and recovery

1. Validate numeric repository/Issue identity, actual Issue and authenticated
   service-comment ownership and exact locator. A complete missing record is
   `not_delivered`; transport, partial collection and malformed source are unknown.
2. Require a final `completed` progress record with no pending action and exact
   attempt, contract/spec revision, source digest, candidate, PR and squash receipt.
   A marker is a locator and authenticated statement, never independent merge proof.
3. Load existing protected project configuration at the recorded contract
   revision and current default branch. Compare the same blob and validated
   semantics, including current actor permissions. Advancing main with the same
   policy is supported. Changed policy holds this observation for reconciliation.
4. Reuse `owns_pr`, `gate_completed_delivery` and `post_merge_check_state` against
   actual external observations. Validate numeric identities without coercion.
   Require exact PR/head, immutable tree/parent, matching receipt and candidate
   review/CI evidence. Required merge CI uses its actual workflow, event, SHA,
   run attempt, check suite, job and Actions identity.
5. Re-read exact progress, current policy and exact-merge CI before returning.
   A new pending or failed required rerun supersedes an earlier green. Changed
   receipt, comment identity or credentials holds the result. Every credential
   selection is checked, including a change followed by restoration; existing
   client hooks are chained and restored.

The memory-only result contains numeric source identity, status, reason, observed
time and an optional allowlisted delivery locator. `verified` with `delivery_only`
means those delivery facts were observed. It contains no RequirementRef acceptance,
operational PASS, delegation or dispatch permission. A constructed result object
does not authenticate its origin. The qualified consumer must obtain fresh reads
and independently verify the exact accepted requirements and required stage.

`not_delivered`, `pending`, `failed`, `unknown` and `changed` remain distinct. No
failure starts work, changes an Issue, repairs a relationship, closes a producer,
retries an effect or releases ownership. Reobservation uses the existing source;
there is no persisted delivery cache, tracker or evidence database. Normal external
changes can occur after a read; this is not an atomic provider snapshot.

The read shares inherited limits and adds 45 seconds and 128 API reservations,
including authentication, for the whole observation. The existing collections
retain their bounded pagination. Each decoded canonical UTF-8 observation has an
8,000,000-byte ceiling. Final-response deadline exhaustion stays unknown. Raw
comments, policies, provider errors and credentials are neither exported nor stored.
This step adds no CLI/MCP command, public projection variant or runtime activation.

## Deterministic verification and remaining evidence

The new 21-method source suite first produced 27 assertion failures against an
explicit always-unknown new-feature control, with no import errors or skips. The
same tests pass against the implemented reader. Six additional independent guard
methods exposed three numeric-identity coercions in the unpublished implementation;
the corrected implementation passes the unchanged guard tests. An earlier byte
oracle counted JSON-escaped Unicode instead of canonical UTF-8; that oracle was
corrected before the final guard RED and GREEN. All intermediate results are retained.

Integration onto checked main `1aedced` supplies the existing credential-selection
hook required by the reader. The two additional frozen deadline methods then expose
actual assertion failures at final result normalization, with no errors or skips.
The reader now checks the effective deadline again after constructing a verified
result. Both its own 45-second limit and a shorter inherited limit must reject a
late result as unknown while restoring the previous credential hook.

All 29 feature methods pass, and the final selected Python 3.14.2 impact run passes
369 methods with no failures, errors or skips. It includes all three feature suites,
existing candidate and post-merge gates, required-job ambiguity, GitHub resource
budgets, work inputs, runner behavior, status isolation, relation readers and default
Issue planning. These checks are deterministic fixture evidence.

A fresh bounded GET-only read with the final Python 3.14.2 source of this repository's existing goal observed
`not_delivered/delivery_record_missing`, without mutation or retained raw pages.
That observation qualifies the selected source's absence handling only.

Final publication still requires integration onto the verified main revision,
exact-head CI, independent code/security reviews and normal protected delivery.
A real selected producer's authenticated final receipt, actual merged PR and
required CI have not been positively qualified by this implementation step.
Actual absence is not positive delivery qualification. Requirement-specific
acceptance, stage `observed`, dependency effect guards and v1 remote acceptance
remain open; the existing source-only P13 report cannot fill those gaps.

Final integration reuses those exact production and test bytes on PR30's actual
merge `22ed6f2`. All 369 selected methods pass on that base, without failures,
errors or skips. The earlier RED/GREEN and bounded absence observations remain
revision-bound evidence; a new main base does not turn absence into positive
producer delivery or RequirementRef acceptance. Required final-head CI, independent
reviews, protected merge and exact actual-main checks remain publication gates.
