# P11 input-evidence comparison

## Purpose and boundary

This increment implements the direct-output comparison in P11 revision 2,
P11-R03/R04 and P11-D09/D10. It reuses fixed input conditions, two-observation
producer membership and the existing producer-delivery result.

The internal comparator requires the same producer, exact delivery pin,
requirement/revision references and required observation stage. It distinguishes
unmet conditions, unavailable evidence and changed observations. An Issue close
is not an input. Stable empty conditions need no invented delivery record.

`RequirementEvidenceRead` is normalized internal data from a separately qualified
reader. Its constructor, its contents and a `matched` comparison authenticate
nothing. Source provenance, actual acceptance, freshness, binding acceptance,
delegation and the common dispatch guard remain separate responsibilities.
There is no default acceptance reader, public command, grant, cache or write.

## Deterministic evidence

- Twenty-three initial methods produce 36 purpose assertion failures before
  implementation, with zero collection/runtime errors or skips.
- The unchanged 23 methods pass after implementation.
- Four additional controls cover reference conditions, every delivery-pin
  field, multiple producers, independent consumers and malformed observations.
- A valid three-clause, 120-reference input reproduces one assertion failure
  when an aggregate evidence set incorrectly inherits one clause's count limit.
  The same regression passes after reusing the single-reference validator for
  aggregate evidence. Per-clause limits and the evidence byte limit are unchanged.
- Four further controls cover larger accepted/observed sets, missing observations
  and invalid references. The 60-reference control already passed before this
  correction and is not reported as a reproduced defect.
- All 139 related methods, including 31 feature methods, pass with zero failures, errors or skips under
  Python 3.14.2. Existing binding, input, relation and producer-reader tests
  remain unchanged.

The tests cover wrong requirements/revisions, missing observation evidence,
partial coverage, changed delivery/acceptance, wrong producer identity, malformed
or model-shaped objects and immutable inputs. No model, native task, network
effect, Issue close or dispatch is involved.

## Remaining qualification

Fresh final-head CI and independent code/security reviews remain required before
delivery, followed by the actual merge revision's checks. Qualified acceptance
and observation sources, consumer wiring, repaired-output evidence, goal
aggregation and the applicable L/O acceptance remain open. This comparison does
not enable native dispatch or establish full P11 or Hydra v1 completion.

## Revision 3 graph-source verification

The graph-source increment targets P11-R02/R04 and P11-D01/D04/D05. Thirty
feature methods pass under Python 3.14.2 with no failures, errors or skips. The
original always-unavailable fault control produced 20 assertion failures across
18 methods, with no errors or skips. One pagination fixture was corrected before
the first implementation check: 101 registered nodes exceeded the aggregate
request budget, so it now uses a coherent self-cycle and unregistered leaves to
isolate four root-page reads. Its expected cursor sequence and cycle result were
preserved; the complete transport-call assertion was strengthened.

Oracles cover two independent chains/empty graphs, changed membership, incomplete
pages, unregistered targets, cycles, exact depth/edge boundaries, aggregate request
exhaustion and deadline expiry after comparison. Built-in transport tests replace
only subprocess responses to exercise actual credential selection, account
validation, query execution and authentication reservation accounting. They are
deterministic transport fixtures, not live provider observations.

Cross-node and second-pass repository/Issue identity drift, failed credential
selection, reverse node-ID collisions, missing authentication and hook restoration
are checked without writes or dispatch. Final-head CI, independent code/security
review, protected merge and actual-main checks remain delivery gates. This does
not complete P11, native execution or Hydra v1 acceptance.

The full selected regression set comprises 244 methods: 238 source/graph/GitHub/
planning/delivery checks plus six existing relation identity/deadline checks.
All pass with zero failures, errors or skips. A scoped actual read of the existing
public Hydra work Issue returned two complete, matching empty dependency graphs
through the built-in authenticated GitHub transport. This establishes that narrow
read path only; live nonempty, multi-page, denied and concurrent graph scenarios
remain unqualified. No relationship or project execution state changed.
