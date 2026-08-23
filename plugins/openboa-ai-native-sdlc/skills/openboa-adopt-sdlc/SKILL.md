---
name: openboa-adopt-sdlc
description: Use when auditing, installing, or updating the OpenBoa human-agent operating model in a workspace or repository.
---

# Adopt OpenBoa AI-Native SDLC

Adopt the shared doctrine and current working method without erasing local repository knowledge.

1. Audit the workspace and every named repository before editing. Identify current human and agent roles, delegation practices, GitHub controls, Codex surfaces, and local instructions. Use the Codex GitHub connector for supported repository, Issue, pull request, review, and Actions reads.
2. Read each `AGENTS.md` and classify its managed block as absent, current, legacy, duplicate, malformed, or unknown version.
3. Use [sync_agents.py](../../scripts/sync_agents.py) with the appropriate [workspace or repository asset](../../assets/) to install, migrate, or update exactly one valid managed block. Preserve the local section byte-for-byte.
4. Stop on duplicate, malformed, overlapping, or unknown-version markers. Report the file and decision needed; do not guess or overwrite the file.
5. Propose templates that inherit OpenBoa's accountable human and record the facts that change: purpose, work lead, authority, resources, boundaries, and evidence. Record another human only for specifically delegated decisions. Propose required Actions, ruleset, `CODEOWNERS`, and environment settings. Repository administrators apply security and approval settings.
6. Group adoption into meaningful repository changes. Keep one pull request per repository when repositories have independent rules and owners; do not split a repository migration into tiny pull requests.

Read [doctrine](../../references/doctrine.md), [Codex](../../references/codex.md), [GitHub](../../references/github.md), [workflow](../../references/workflow.md), and [governance](../../references/governance.md). Use the workspace or repository `AGENTS.md` asset and the Goal, Task, pull request, and handoff templates in [assets](../../assets/).

Return the role and authority audit, drift, proposed changes, validation, blockers, and a Git plan. Do not push, merge, or change repository administrator settings without the authority required by the assignment.
