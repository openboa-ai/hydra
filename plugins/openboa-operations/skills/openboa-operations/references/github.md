# OpenBoa GitHub Profile

**Profile:** `public-standard`
**Contract:** `0.1.0`
**Execution owner:** `openboa-ai/.github`

## Repository contract

Each adopted repository may include `.github/openboa-governance.yml`:

```yaml
schema: 1
contract: "0.1.0"
profile: public-standard
human_gate:
  paths:
    - .github/workflows/**
    - .github/CODEOWNERS
    - SECURITY.md
```

The local manifest may add sensitive paths but may not remove the central baseline. The caller of the trusted reusable workflow is pinned to an exact commit SHA. A contract or pin mismatch fails closed.

## Issue and PR surface

Use these labels consistently:

- `status:backlog`, `status:ready`, `status:in-progress`, `status:in-review`
- `blocked`
- `delegate:codex`
- `risk:routine`, `risk:human-gate`
- `governance:exception`

Issue templates capture outcome, human owner, acceptance evidence, dependencies, and risk. PR templates capture linked goal, fast-path justification when applicable, risk lane, changed surface, verification, delivery, observation, and handoff state.

## Branch and merge baseline

Public default branches require a pull request, current required checks, resolved conversations, and no force-push or branch deletion. Use squash-only merge, auto-merge after all gates, and delete merged head branches. Preserve stronger repository-specific checks. Routine PRs do not require a human approval; human-gate PRs use the `openboa-major-change` environment with `SonSangjoon` as required reviewer and self-review prevention disabled.

The required central check is `openboa-governance`. The existing coffee trusted gate remains required during migration until the new check has passed canary verification everywhere it is used.

## Trusted workflow rules

The central workflow runs from trusted base-branch code and treats pull-request content as data. Candidate code is not executed with organization secrets or write credentials. It validates the contract manifest, changed-path risk, declared risk label, required checks, and the human-gate environment. Local CI remains the product repository's responsibility.

## Adoption and audit

The `openboa-operations` skill audits public repositories with read-only `gh` calls before proposing changes. Synchronization creates focused PRs that update only the managed `AGENTS.md` block and compatible GitHub projection. The v1 skill is explicit and on-demand; it does not dispatch Issues or run a background daemon.
