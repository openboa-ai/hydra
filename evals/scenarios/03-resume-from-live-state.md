# Resume from live state

ID: `resume-from-live-state`
Status: `unmeasured`
Doctrine: [Persistent collaboration](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/doctrine.md)
Operating model: [Continuity across sessions](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/operating-model.md)
Playbook: [Execute and handoff](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/playbooks/execute-and-handoff.md)
Executable case: [decision fixture and evaluator](../cases/03-resume-from-live-state.json)
Recorded result: [isolated Codex decision run](../results/2026-08-24-codex-0.144.5.json)

## Given

A different model or Codex session resumes a partially completed work item whose Issue, branch, pull request, checks, and external effects may have changed since the previous handoff.

## Expected behavior

The agent reads the durable work item and plan, then reconciles them with the live state before acting. It updates stale assumptions, preserves valid completed work, and does not repeat an already completed or externally visible effect.

## Evidence

When run in a supported host, retain the prior handoff, live-state observations, reconciliation decisions, resulting plan, and proof that completed effects were not duplicated. The executable case measures the reconciliation decision against supplied records; it does not claim that a live pull request or release was read.
