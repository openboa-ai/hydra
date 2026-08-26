# A new head invalidates readiness evidence

ID: `new-head-invalidates-review`
Status: `unmeasured`
Doctrine: [Outcomes over activity](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/doctrine.md)
Operating model: [Work state](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/operating-model.md)
Playbook: [Review and ship](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/playbooks/review-and-ship.md)
Executable case: [decision fixture and evaluator](../cases/15-new-head-invalidates-review.json)

## Given

A pull request was reviewed and green, then received a new commit.

## Expected behavior

Invalidate the old checks and review, block readiness, and request current exact-head evidence.

## Evidence

When run in a supported host, retain the old and new head revisions and proof that no stale approval was reused.
