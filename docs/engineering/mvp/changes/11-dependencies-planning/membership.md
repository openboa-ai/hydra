# P11 fixed producer membership and bounded topology

This source component implements the RelationRead normalization, bounded topology and two-read
producer-set comparison in [P11 revision 2](spec.md), step 3 and the membership
portion of step 4, using [WR §9](../../contracts/work-records.md#9-관계-원본입력조건계획을-따로-읽는다).
It is a prerequisite for the eventual effect guard, not full dependency readiness.

## Responsibility and input

`hydra_sdlc/work_relations.py` reuses the existing P09 Binding and InputConditions
validators. `relation_read` constructs the exact six-field WR value and snapshots
the source and IssueRef items into immutable canonical content. Complete values
have a numeric-sorted membership digest; partial/unavailable values have none.
Observation time is excluded from the membership digest and conveys no authority.

The source reader must establish endpoint identity, permission, visibility and
pagination coverage. Constructing a RelationRead cannot establish those facts.
Previously constructed DTOs are revalidated before comparison, including closed
keys, integer bounds, duplicate refs/JSON keys, source/relation, timestamps,
cardinality and digest. No provider or RPC request is performed by this module.

One source plus 255 target refs fits the existing 256-node resource budget. The
constructor bounds an overflowing collection to the observed prefix and marks it
partial with no digest. An oversized hand-built complete DTO is rejected. These
are single-collection limits. The topology consumer also enforces a global
budget across the reachable graph, as described below.

## Comparison and failure meaning

`compare_bound_producers` takes a fixed v2 binding and two blocked-by observations
for that same Issue. It does not derive conditions from the current edge set.

| Result | Meaning |
| --- | --- |
| `matched` / `producer_membership_only` | Two complete observations have the same membership, matching the fixed clause producer set. |
| `changed` / `relations_unstable` | The two complete collections disagree. |
| `changed` / `relationship_changed` | Stable current producers differ from the fixed conditions. |
| `unknown` | A necessary read/coverage/condition is missing or a self dependency is observed. |

Missing conditions do not become empty clauses. Explicit empty clauses and two
complete empty collections are a normal matching case. Multiple clauses for one
producer are preserved; their requirements and stages still need evaluation.
Adding/removing an edge never modifies a binding, goal or accepted condition.

Adopted conditions are derived from the fixed binding. Referenced conditions must
come from P09's qualified read of that exact binding/reference; this pure helper
does not attest a caller-supplied value's provenance or independent acceptance.
The helper has no command route or activation profile. Its result includes no
readiness, authority, requirement-satisfaction or dispatch decision.

## Bounded dependency topology

`dependency_topology` analyzes two supplied blocked-by read pools. Each pool is a
plain dictionary keyed by numeric `(repository_id, issue_number)`; a missing row
or unavailable pool remains unknown. Only rows reachable from the selected root
are inspected. The supplied registered-repository set restricts reads; it is not
authentication, a source grant or permission to execute. Every selected DTO is
revalidated for its exact source and relation before traversal. Unrelated denied,
malformed or cyclic components cannot block the selected candidate.

Each pass produces an immutable graph with its own coverage, reason, numeric
nodes and directed edges. Traversal is iterative and retains a bounded observed
prefix: at most 256 nodes, 1,024 edges and depth 32. Exceeding a budget means
partial coverage. The longest acyclic root path is checked as well as discovery
depth, so a shortcut edge cannot hide an overlong path. Missing, denied,
unregistered or partial reachable observations never become complete empty rows.

An observed cycle in the current pass returns `cycle` / `dependency_cycle`, even
when another branch is missing. A false cycle flag on a partial observation only
means no cycle was observed. Any incomplete pass otherwise returns `unknown`.
Two complete graphs with different reachable nodes or edges return `changed` /
`relations_unstable`; stable complete topology returns `matched` / `topology_only`.
Transitive drift is detected even when the root's direct producer set is stable.

The helper performs no I/O and cannot prove two actual provider reads from two
supplied pools. The qualified adapter owns actual collection, pagination,
visibility, identity, timing and current registration. A topology match establishes
neither a binding's requirement/stage satisfaction nor parent coverage, readiness
or effect authority. No relation copy, scheduler, command route, grant or legacy
fallback is introduced; a future effect guard must collect current facts again.

## Verification and remaining integration

`tests/test_work_dependencies.py` covers the membership portions of WR-D49/51/52/
61/62: literal digest input, stable positive/empty cases, changes between reads,
added/removed/cross-repository producers, partial/missing reads, self dependency,
adopted/reference forms, source/type tampering, resource limits and cache-free
reconstruction. Independent expected sets and literal bytes are the oracles.

```sh
python3 -m unittest discover -s tests -p 'test_work_dependencies.py' -v
python3 -m unittest discover -s tests -p 'test_work_records.py' -v
python3 -m unittest discover -s tests -p 'test_work_record_source.py' -v
python3 -m unittest discover -s tests -p 'test_work_input*.py' -v
```

The 20 topology methods also cover the graph portions of WR-D21/51/52/60 and
numeric registration boundaries in WR-D65/66. Literal graph outcomes cover valid
empty, chain and cross-repository cases; partial/unavailable observations; cycles;
transitive drift; selected DTO tampering; immutable snapshots; and exact positive
and overflowing node, edge and depth budgets. On Python 3.14.2 the complete five-
module P09/P11 impact selection passed 104 methods with no skips. Direct module
execution also collected and passed all 46 dependency methods.

With the exact same topology tests, an always-unknown scaffold caused 30 assertion
failures and removing only the transitive-drift guard caused one assertion failure;
both controls had zero errors or skips. These demonstrate behavioral sensitivity,
not a defect in the published parent or actual provider/native operation.

Deliberate always-unknown and ignored-condition membership fault controls must fail the same
tests. They are injected controls, not published-parent defect claims. Final-head
CI and independent code/security review are required for delivery.

Full P11 still requires the qualified HTTP relation reader and actual native
parent/graph coverage, requirement/revision/delivery/main-CI/observed-stage
evidence, optional planning, goal aggregation and common effect-guard integration.
Legacy behavior is unchanged. Native qualification and actual operating acceptance
remain separate from these deterministic source fixtures.

The next [native relation reader stage](reader.md) connects fixed provider queries
to these values and records its separate deterministic and scoped live evidence.
