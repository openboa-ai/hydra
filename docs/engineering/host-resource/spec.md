# Host resource completion

Status: proposed continuation specification; not implementation or activation evidence.

This change extends `docs/engineering/github-workflow/spec.md` from merged revision
`bdd54f58801b4ce27c9f53d7d676a9afe3e3a7fd`. Preparation, registered verification,
process ownership, delivery gates and product policy remain unchanged.

## Purpose and scope

Release completed workspaces through an installed lifecycle provider, including
after a restart between product completion and resource retirement. Product Issues,
PRs and CI remain workflow truth. The existing host resource registry supplies only
ownership, cleanup eligibility and discovery identities; it is not a workflow
journal. Add no database, scheduler, credentials or replacement lifecycle system.

## Optional provider extension

Add two small optional operations to the existing trusted lifecycle provider:

- `issue_numbers(repo)` returns the positive Issue numbers of this provider's
  currently registered resources belonging to its configured host owner.
- `completed(repo, number, branch, head, pr_number, merge_sha, path)` reconciles
  release and retirement of that exact resource using the existing lifecycle.

Repository and Issue identity determine the same canonical path and branch as
preparation. The runtime validates and deduplicates discovery IDs, limits lookup
to requested repositories, and derives the path itself. Candidate files and Issue
text cannot select a provider, owner, path or cleanup command. Providers without
these optional operations retain existing behavior; resource recycling is not
claimed for them. The existing storage command wrapper is unchanged.

## Completion boundary

Invoke resource completion only after the existing completion path has verified
the owned PR's exact recorded head and actual merge, candidate delivery evidence,
the exact merge commit's required main-push checks, current controls, closed Issue
and authenticated durable completed progress. A successful close request alone
does not establish this boundary. Reuse existing completion verification, including
its policy-change recovery; do not introduce weaker cleanup-specific merge gates.

The provider independently rechecks registered ownership, exact PR head and merge
facts, main ancestry, cleanliness and absence of active resource users. It uses
normal owner release and retirement. Unknown, foreign, dirty, busy or changed
resources remain intact. A path's absence is not proof of retirement; successful
read-back or an existing matching retirement receipt makes retries idempotent.
Never allocate, prepare, reset, overwrite or adopt a checkout merely to clean it up.

Cleanup failure or an uncertain response preserves the delivered GitHub facts and
completed progress. Report the resource wait separately. On retry, reconcile
existing lifecycle state before acting; do not repeat model work, create another
PR, merge again or issue another close. Stopping prevents a new cleanup action.

## Restart discovery and observability

For each requested repository, combine ordinary GitHub discovery with the current
host owner's known resource Issue IDs. Fetch current GitHub Issues and authenticated
progress for those additional IDs, including closed Issues whose active label was
already removed. IDs are discovery hints, never acceptance or takeover authority.
Deduplicate normal and resource discovery so a task is reconciled once per cycle.

Only existing authenticated completion or close-recovery work enters the completion
path. Discovery cannot reopen closed work, restore delegation, bypass pause or
intake controls, or start development from a resource record. A malformed discovery
result or unavailable registry reports a resource wait without inventing completion
or adopting another owner's resource. Read-only status may report retained resources
but never release them. Keep host paths, registry contents and private diagnostics
out of public progress; report public identities and bounded reason codes.

## Acceptance evidence

- Normal exact delivery records durable completion before invoking the hook;
  failed candidate evidence, merge identity or main checks never invoke it.
- Restart after Issue closure or completed-record/active-label cleanup discovers
  the still-owned resource and reuses current GitHub completion verification.
- Discovery deduplication invokes cleanup once; foreign ownership, arbitrary paths
  and missing authenticated completion evidence cannot authorize it.
- Dirty, busy, unknown or changed resources survive unchanged. Failed release or
  lost retirement response preserves completed progress and reconciles on retry
  without a model, new PR, merge or close.
- Already retired resources do not get recreated; stop and read-only status cause
  no lifecycle mutation. Providers without the extension retain current behavior.

Local contract tests, actual host-provider qualification, resource recycling and
autonomous product delivery remain separate evidence. This specification alone
does not establish host installation or background operation.
