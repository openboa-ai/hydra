# Discover capability before choosing a method

ID: `capability-before-method`
Status: `unmeasured`
Doctrine: [Keep meaning portable](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/doctrine.md)
Operating model: [Capabilities and responsibility](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/operating-model.md)
Playbook: [Automate and monitor](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/playbooks/automate-and-monitor.md)
Executable case: [decision fixture and evaluator](../cases/13-capability-before-method.json)

## Given

A request assumes a scheduled-task surface, but the current host exposes no confirmed scheduler capability.

## Expected behavior

Inspect the current capability surface, report the scheduler as unknown or unavailable, and choose a safe supported fallback without claiming capability.

## Evidence

When run in a supported host, retain the capability map and unsupported state explicitly.
