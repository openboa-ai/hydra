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
- All 135 related methods pass with zero failures, errors or skips under
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
