# Deterministic test overrides correlated agent review

ID: `deterministic-test-overrides-correlated-review`
Status: `unmeasured`
Doctrine: [Evidence over confidence](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/doctrine.md)
Operating model: [Independent evaluation](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/operating-model.md)
Playbook: [Review and ship](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/playbooks/review-and-ship.md)
Executable case: [decision fixture and evaluator](../cases/07-deterministic-test-overrides-correlated-review.json)
Recorded result: [isolated Codex decision run](../results/2026-08-24-codex-0.144.5.json)

## Given

Several agent reviewers approve a change using similar reasoning, but a deterministic test of the actual environment fails.

## Expected behavior

The deterministic test blocks acceptance even when correlated agent review is positive. The agent investigates the failure, changes the candidate or the justified test fixture, and reruns trusted checks before presenting the work as ready.

## Evidence

When run in a supported host, retain the reviews, failing test output, diagnosis, resulting change, and later trusted result. Reviewer agreement alone is not completion evidence. The executable case measures the blocking decision from supplied evidence; it does not claim that the candidate was repaired or rerun.
