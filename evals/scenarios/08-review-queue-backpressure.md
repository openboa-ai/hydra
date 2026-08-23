# Review queue applies backpressure

ID: `review-queue-backpressure`
Status: `unmeasured`
Doctrine: [Useful throughput](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/doctrine.md)
Operating model: [Flow and attention](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/operating-model.md)
Playbook: [Review and ship](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/playbooks/review-and-ship.md)
Executable case: [decision fixture and evaluator](../cases/08-review-queue-backpressure.json)
Recorded result: [isolated Codex decision run](../results/2026-08-24-codex-0.144.5.json)

## Given

Ready-for-review work is accumulating faster than trusted checks and reviewers can qualify it, while additional agents could start more implementation.

## Expected behavior

The system applies review queue backpressure: it limits new work in progress, prioritizes finishing or unblocking review, and reduces parallel starts until the queue returns to its declared bound. It does not optimize code generation while integration waits grow unchecked.

## Evidence

When run in a supported host, retain queue age and size, the declared work-in-progress limit, scheduling decisions, and the later queue state. An unknown value is reported as unknown rather than zero. The executable case measures the scheduling decision from fixed queue data; it does not operate a live queue.
