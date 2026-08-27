# Hydra evaluation boundary

Hydra does not evaluate itself. Independent evaluation design, task definitions, runs, and reviewed evidence belong in [hydra-eval](https://github.com/openboa-ai/hydra-eval).

The first evaluation target is Codex because it is the available execution client. Claude Code, Cursor, OpenCode, Hermes, and other compatible clients remain open targets and are reported as `not tested` until a real run exists. Client support is a property of a tested client and version, not of a GitHub account.

For the foundation, there is no score to copy here and no claim that Hydra improves an agent. A future release must point to an immutable Hydra revision and a reviewed Hydra Eval result. The result must keep success/quality, time, tokens, cost, and safety visible as separate dimensions.
