# Scheduled work reconciles before acting

ID: `scheduled-read-only-reconcile`
Status: `unmeasured`
Doctrine: [Recover before repeating](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/doctrine.md)
Operating model: [Automation monitor](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/operating-model.md)
Playbook: [Automate and monitor](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/playbooks/automate-and-monitor.md)
Executable case: [decision fixture and evaluator](../cases/14-scheduled-read-only-reconcile.json)

## Given

A scheduled follow-up wakes after an uncertain prior GitHub comment attempt.

## Expected behavior

Read current state first, preserve the read-only default, bind the next wakeup and expiry, and avoid a duplicate effect.

## Evidence

When run in a supported host, retain the target, wakeup, expiry, and live external state before any retry.
