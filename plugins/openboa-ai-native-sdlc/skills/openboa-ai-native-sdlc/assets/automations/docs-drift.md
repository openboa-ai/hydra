# Documentation drift

- Target: declared source files and the routes, examples, schemas, or generated docs that depend on them.
- Wake: source change, release candidate, or low-frequency scheduled audit.
- Compare meaning and runnable examples, not timestamps alone.
- Safe action: report the coherent documentation change and validation commands needed, then hand it to an interactive Codex task; do not edit files from the scheduled run.
- Notify: doctrine conflict, product behavior ambiguity, private information risk, or a public-release boundary.
- Stop: all declared routes agree at the current revision or the source relationship is removed.
