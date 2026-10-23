# P11 optional Project priority reader

Contract: [P11 revision 2](spec.md), R05 and the [WR planning contract](../../contracts/work-records.md).
This stage supplies an internal read observation. It does not enable native work
selection, expose a new command, alter delegation or complete P11/v1 acceptance.

## Behavior

`GitHub.native_planning_read(repository, source, planning)` validates the existing
protected planning-policy shape and returns an immutable `PlanningRead`. Its value
contains the Issue identity, Project/field IDs, coverage, nullable integer priority,
safe reason and observation time. The caller owns registration, accepted policy
provenance, current authority and effect-time revalidation. A value or role is not
an execution grant.

Fixed GraphQL queries use variables for all caller values. The reader collects the
Issue's complete `projectItems`, including archived items, to find exactly one item
in the configured Project. It validates numeric repository/Issue and node identity,
Project ID, single-select field ID/type, field-to-Project identity and current option
IDs. Display names never choose the field or its priority mapping. Full field-value
pagination precedes a known result. Only confirmed null or a completely observed
unset field yields policy default zero. Missing/duplicate/redacted items, partial
coverage, field/type drift, unmapped options and access failures remain unavailable;
the reader does not fall back to Issue priority.

Every configured option ID must still exist in the observed field, even when this
Issue does not currently use it. A deleted or replaced unused option invalidates
the protected mapping for selected, explicit-null and unset values alike.

One read is bounded by 15 seconds and eight HTTP reservations including transport
authentication, three pages and 255 entries per collection, and 128 KiB of canonical
JSON per decoded response. Nested caller bounds remain effective. Source/field/
option/credential changes between pages cannot produce a known priority. Every
invocation rereads sources; no Project, field, option, item or priority is persisted
or edited. Raw source text, extra fields and provider error messages are not exported.

## Evidence and remaining work

The explicit always-unavailable new-feature control produced 16 assertion failures
across 25 methods, with zero errors/skips. This is a fault control, not a defect
claim about a published parent. The same test bytes pass after implementation.
The original preparation passed 328 selected Python 3.14.2 methods. Integration
onto main `7a9db88` preserves all original assertions and passes 355 impact methods
with zero failures, errors or skips, including the current default Issue-planning
reader and its deadline regressions.

Integration review found two boundary defects in the prepared reader. A malformed
provider type could raise an uncaught exception, and successful result construction
could outlive the read deadline. Three new methods retain a valid positive control
and reproduce three assertion failures across those negative cases, without errors
or skips. The same methods pass after validating the type before set membership
and checking the remaining deadline after constructing the complete result.

Independent review of `ceb0be2` found that stable observations of a field could
still omit an unused configured option. Three additional regression methods
reproduced that stale-mapping acceptance for selected, explicit-null and unset
values. They pass after checking all configured option IDs on every source read.
All 358 selected impact methods pass with zero failures, errors or skips. Original
test assertions are preserved. Earlier reviews and CI do not qualify the correction;
the final head requires fresh remote evidence.

Cases cover ID mapping and display-name changes, negative/null/unset priorities,
missing/duplicate/redacted/foreign items, field/type/option drift, pagination and
capacity, provider/permission failures, credential changes, caller budgets and
forbidden-effect call traces. The reader does not change existing relation,
binding, legacy execution or source-selection behavior.

Provider schema reads during preparation confirmed the fields, unions and argument
forms used to construct the profiles. A bounded query attempt under an existing credential
returned `INSUFFICIENT_SCOPES` requiring `read:project`. No credential or permission
was changed. That denial does not qualify actual Project visibility, priority data
or complete live query-profile behavior. GitHub documents this read-only scope in
its [OAuth scope reference](https://docs.github.com/en/apps/oauth-apps/building-oauth-apps/scopes-for-oauth-apps).

Fresh PR CI and independent code/security reviews, protected delivery and actual-main
checks remain required. Actual selected-Project qualification,
native candidate ordering, public projection consumers and full P11 acceptance remain
separate responsibilities. Issue-based planning retains its normal existing path.
