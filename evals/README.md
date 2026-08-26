# Behavioral evaluations

This directory keeps human-readable behavior contracts separate from executable case definitions and observed results:

- [`scenarios/`](scenarios/) states the full behavior that OpenBoa ultimately needs.
- [`cases/`](cases/) supplies concrete input, an isolated fixture, and versioned evaluator criteria for the safely measurable decision-policy slice of each scenario. [`behavior-case.schema.json`](fixtures/behavior-case.schema.json) defines evaluator v2.
- [`fixtures/decision-output.schema.json`](fixtures/decision-output.schema.json) constrains the agent's decision record.
- [`baselines/evaluator-v1/`](baselines/evaluator-v1/) preserves the exact v1 case bytes referenced by the immutable v1 ledger.
- [`results/`](results/) stores immutable run evidence. A result never changes the source scenario.

The runner enforces the checked-in behavior-case schema before it loads any case. The current v2 harness has one case shape, so it uses a small exact validator rather than a second JSON Schema framework: object keys, constants, string values, arrays, and scenario paths must all match. Formatting-only schema edits are allowed; a semantic schema change fails closed until the validator and parity tests change in the same review.

These evaluations are an eval harness, not product runtime. The current cases measure explicit skill routing and decision selection in fresh, read-only Codex tasks. They do not perform or claim GitHub writes, deployment, release, human approval, or other external effects. The broader end-to-end scenarios therefore retain `Status: unmeasured` until their requested live evidence exists.

## Result meanings

- `passed`: the selected run produced attributable evidence and every evaluator criterion passed.
- `failed`: attributable output violated at least one evaluator criterion or performed a forbidden tool call.
- `unsupported`: a deterministic preflight showed that the requested Codex, authentication, marketplace, or plugin capability was unavailable.
- `unmeasured`: the case was not run or the run ended without enough attributable evidence for a verdict.

`unmeasured` and `unsupported` are distinct states. Neither is a pass, failure, or numeric zero. Unavailable queue, cost, or other operational values stay `unknown` rather than becoming zero.

Evaluator v2 separates core acceptance from method telemetry. Every case still requires a `playbook` and headline `decision`, but their exact match is reported as `method_match` and does not decide the core result. Core acceptance uses the same rule for all 21 cases: exact skill attribution, the declared human gate, required safe actions, absence of every forbidden action, fixture-grounded observations, required unknowns, and zero tool calls.

## Run the evaluations

Validate all definitions without invoking a model:

```bash
python3 scripts/run_behavior_evals.py \
  --root . \
  --output /tmp/openboa-behavior-static.json
```

Run all decision cases in isolated Codex tasks:

```bash
python3 scripts/run_behavior_evals.py \
  --root . \
  --codex \
  --candidate-revision HEAD \
  --require-complete \
  --output /tmp/openboa-behavior-run.json
```

To run one named case, add `--case <scenario-id>`. With `--require-complete`, only the selected cases must be measured and pass; intentionally unselected cases remain `unmeasured`. The paired discovery probe must still pass.

Live mode resolves `--candidate-revision` once, reads the marketplace blob and plugin tree directly from those immutable Git objects, and materializes only those tracked files in a private owner-only snapshot. The marketplace must contain exactly the expected plugin and local source path. Symlinks, submodules, special files, path escapes, and untracked or ignored bytes are not admitted. The candidate fingerprint covers every packaged path, byte, file type, and executable bit, and includes the marketplace manifest separately.

The runner copies existing Codex authentication into temporary candidate and no-plugin control homes and installs only from the private snapshot. It resolves the `installedPath` returned by Codex beneath the exact temporary cache path and fingerprints the actual installed files immediately after installation and after all tasks. Snapshot or installed-cache mismatch makes the selected evidence `unmeasured`; matching live-source start/end hashes alone is never sufficient. Explicit discovery passes only when the installed task returns a sentence available in the skill and the matched no-plugin task does not. Each task is ephemeral and read-only. The prompt forbids tools, the evaluator requires zero observed tool calls, remote app and browser surfaces are disabled, and no GitHub operation is made. The runner reads the decision-output schema once before execution and gives every case a read-only temporary snapshot of those exact bytes; it never asks a running case to reopen the live repository copy. The report observes removal of the temporary homes, candidate snapshot, and copied authentication, and records whether the active Codex config digest stayed unchanged; per-case workspace cleanup is enforced by its temporary-directory boundary.

This isolation closes normal live-source, marketplace-routing, and installer-copy races. It is not an operating-system security boundary against a malicious process already running as the same user and deliberately changing a private path during the instant a task reads it. Run release evidence on a controlled host with no untrusted same-user process.

Run the focused harness and contract checks with:

```bash
python3 -m unittest \
  tests.test_behavior_eval_runner \
  tests.test_behavior_scenarios
```

The latest checked-in ledger is the runner's direct JSON output. It records the candidate Git revision, plugin tree and marketplace blob identities, private snapshot and installed-cache fingerprints, runner, schema, exact case-set, and linked-scenario digests; host and Codex versions; paired discovery evidence; every raw core and method criterion; the decision record; usage; and tool-call count. Case and scenario hashes are taken from the bytes loaded before execution. The runner reads the current file sets again at the end; any add, remove, rename, or content change makes selected results `unmeasured` instead of attributing an old in-memory evaluation to new files. The ledger deliberately records implicit skill invocation as `unmeasured`; only explicit invocation is exercised here. See the immutable baseline and latest [recorded results](results/README.md). `--require-complete` is non-zero if a measured core case fails, a selected case is unsupported or unmeasured, discovery does not pass, or the candidate snapshot, installed cache, runner, schemas, case set, or linked scenarios lose attribution during the run.

Packaging and identity migration are exercised separately. See [plugin installation and migration rehearsal](install-rehearsal.md).
