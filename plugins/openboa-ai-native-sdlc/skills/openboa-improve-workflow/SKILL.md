---
name: openboa-improve-workflow
description: Use when repeated failure, review rework, incidents, or weak eval results show that the development workflow itself needs improvement.
---

# Improve the Workflow

Turn repeated failure into a smaller, durable improvement instead of a longer prompt.

1. Reproduce the failure and separate product defects from missing context, tools, tests, evals, graders, permissions, environment setup, or review.
2. Identify the smallest responsible layer. Improve `AGENTS.md` for stable repository facts, a skill for repeatable judgment, a script or test for deterministic behavior, and an eval for variable outcomes.
3. Add a regression case that fails for the observed problem before changing the workflow.
4. Make the smallest change, re-run the original case, and run nearby regressions.
5. Record what improved, what remains uncertain, and whether the change belongs to Hydra or only to the product repository.

Do not turn one unusual incident into a universal rule. Repeated patterns with evidence justify shared guidance; repository-specific facts stay local.

Read [evals and observation](../../references/evals.md), [doctrine](../../references/doctrine.md), and [operating model](../../references/operating-model.md).

Return the failure class, evidence, chosen layer, regression, improvement, validation result, owner, and follow-up signal.
