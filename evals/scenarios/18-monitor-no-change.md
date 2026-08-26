# A monitor stays quiet when evidence did not change

ID: `monitor-no-change`
Status: `unmeasured`
Doctrine: [Prefer outcomes](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/doctrine.md)
Operating model: [Automation monitor](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/operating-model.md)
Playbook: [Automate and monitor](../../plugins/openboa-ai-native-sdlc/skills/openboa-ai-native-sdlc/references/playbooks/automate-and-monitor.md)
Executable case: [decision fixture and evaluator](../cases/18-monitor-no-change.json)

## Given

A periodic monitor wakes and the relevant target and evidence are unchanged.

## Expected behavior

Do no external write, avoid an unnecessary notification, and retain the next bounded wakeup.

## Evidence

When run in a supported host, retain the no-op decision tied to unchanged evidence and the next bounded wakeup.
