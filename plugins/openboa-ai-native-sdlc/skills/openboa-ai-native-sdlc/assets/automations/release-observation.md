# Release observation

- Target: exact release or deployment artifact and environment.
- Start only after the public-release or production gate is recorded.
- Capture: baseline, artifact revision, delivery readback, observation window, user-visible behavior, errors, rollback signal, and metric definition.
- Notify immediately: installability, authority, security, data-integrity, or core-behavior stop condition.
- Stop: qualified window completes, a new artifact invalidates the observation, or recovery takes control.
- Never publish, promote, or roll back solely because a timer fired.
