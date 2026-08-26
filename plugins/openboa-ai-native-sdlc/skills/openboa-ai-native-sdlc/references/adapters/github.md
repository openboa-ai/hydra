# GitHub adapter

GitHub is the durable control plane for work state, integration, repository policy, and delivery evidence.

## Default surfaces

- Issue: durable outcome, boundaries, decisions, dependencies, acceptance, and post-delivery observation.
- Pull request: coherent integration candidate, current diff, review discussion, and check evidence.
- Actions: deterministic checks and bounded automation from reviewed workflow code.
- Rulesets: stable merge and branch constraints.
- Releases and deployments: delivery records, not proof of product success by themselves.
- Audit log: attribution for consequential setting changes when available.

Use the Codex GitHub connector by default. Use local `git` for the data plane. A fallback client is a time-bounded exception only when the connector lacks the required operation.

## Review readiness

A ready claim is tied to the exact pull-request head. It requires the declared checks to succeed, a qualifying independent review on that head, no unresolved blocking conversation, and no policy mismatch. `skipped`, `neutral`, missing, stale, or unknown is not success.

A shadow readiness workflow reports the state but is not automatically a merge gate. Making it required, binding its expected source, or granting it write permissions is a separate repository-policy decision.

## Safe Actions design

- prefer base-controlled workflow and policy code;
- treat candidate files and metadata as data;
- use read-only permissions unless one reviewed job needs a narrower write;
- never execute candidate code with secrets, OIDC, or write credentials;
- pin third-party actions to immutable commit SHAs; and
- make retries idempotent and read back external effects.
