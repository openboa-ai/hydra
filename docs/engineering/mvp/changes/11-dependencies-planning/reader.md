# P11 native relation reader

Contract: [P11 revision 2](spec.md), WR relation observations and the GitHub
integration contract. This is one implementation stage. Source tests and scoped
live reads do not complete P11, authorize dispatch or activate a deployment.

## Behavior and boundaries

`GitHub.native_relation_read(repository, source, relation)` returns the existing
immutable `RelationRead` for one parent, children or blocked-by collection. It
reuses the selected client's authentication and nested read budgets. Fixed
GraphQL query profiles request only the selected relation and its identity/count
metadata; all caller values and cursors are variables. `POST /graphql` carries a
query, never a mutation. There is no REST writer, legacy fallback, record store,
model call, scheduler or command route.

The adapter validates the requested numeric repository/Issue identity, current
repository name, source node, returned node identities, visibility metadata,
counts and terminal `pageInfo`. Repository names and IDs must map consistently
throughout one observation. A known role is observation metadata; it does not
qualify a deployment or grant execution authority. Null repository/Issue or
unknown visibility remains unavailable. Explicit null parent is distinct from a
failed lookup. GraphQL field errors do not become empty successful relations.

Collections use the provider's explicit termination and advertised totals. The
blocked-by summary uses `totalBlockedBy`, which includes open and closed Issues;
an open-only count cannot erase accepted producer inputs. GitHub documents these
fields in its [Issue schema](https://docs.github.com/en/graphql/reference/issues).
Digest equality compares membership, not provider revisions or an atomic snapshot.
Two required effect-time observations must be two actual source collections.

One observation is bounded by 15 seconds, four HTTP reservations including
credential identity, at most three query pages, 100 rows per page, 255 retained
targets and 128 KiB of canonical JSON per decoded page. Existing outer budgets remain effective. A
later HTTP failure or exhausted budget retains an observed partial prefix.
Incomplete totals, source changes or credential rotation cannot produce complete
membership. Repeated/overlapping pages and malformed identity are rejected with
fixed diagnostics. Raw extra fields, private text and provider error strings are
not copied into the normalized value.

## Deterministic verification

The new-feature always-unavailable control caused 38 assertion failures across
the first 20 methods, with no errors/skips. This is a deliberate fault control,
not a published-parent defect claim. A separate unpublished-reader regression
reproduced two assertion failures for one repository name carrying different IDs.
The final implementation rejects those aliases while keeping normal cases.

The 26 reader methods cover null/present parent, valid empty relations, two-page
completion, failed second pages, GraphQL errors, source/target identity, opaque
cursor injection, count and permission failures, exact/overflowing capacity and
decoded-page limits, credential changes, independent rereads and post-response deadlines. Literal membership
bytes, expected identity sets, coverage states and transport call records are
independent oracles. The original 20-method test bytes are unchanged.
Three additional clock-fault tests reproduced five assertion failures in the
unpublished reader when source/target validation or normalization completed after
the deadline. The corrected reader does not accept late pages or emit complete
values after normalization exhausts the budget. Existing prefixes remain partial.

All 291 selected Python 3.14.2 methods pass on verified main `9b3e904` with
zero failures/errors/skips. The
selection includes these reader tests and the existing P09/P11, GitHub transport,
runner, status-isolation and public-decision suites. This stage changes no Rust,
TypeScript, installed configuration or existing source-selection behavior.
The implementation adds only the relation reader entry point to the baseline
GitHub client; it does not import the separate projection implementation.

## Scoped actual observation and remaining work

The final adapter made six actual read queries against an existing public Issue:
two each for parent, children and blocked-by. Each selected scope returned an
explicit complete empty result with matching membership digests. No mutations,
new credentials, source activation or raw-page retention occurred.

The final deadline-corrected reader also made two bounded collections from an
[existing public VS Code Issue](https://github.com/microsoft/vscode/issues/342050),
returning 13 children both times with complete coverage and equal membership
digests. These were actual single-page read queries without mutation, credential
changes or source activation. Live multi-page, denied or hidden relationships,
cross-repository visibility and concurrent changes remain unqualified. Source activation, current registration, effect-time graph collection,
required-output evidence, planning and goal aggregation remain separate P11 work.
No Issue close, topology match or observed role becomes an output/authority proof.

Fresh PR CI and independent code/security review, protected delivery and actual-
main checks remain required. Earlier projection CI does not qualify this reader.
