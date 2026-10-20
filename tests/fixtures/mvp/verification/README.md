# Selected verification evidence

`cases.json` selects five existing main-published source tests in two bounded cases.
It refers to the original requirements by path, exact document SHA-256 and section.
The other JSON files describe independent positive and forbidden-effect oracles;
they do not repeat the requirement document or introduce executable commands.

The collector accepts only exact `test_module.TestCase.test_method` selectors from
repository `tests/`. Every selected method is required. Deleted selectors, zero
collection, class-fixture failures, skips, expected failures, unexpected successes,
failed subtests, interruption and export failures cannot satisfy the gate.

Run from the repository root, through the host's required storage runner:

```sh
python3 -I scripts/run_mvp_verification.py --manifest tests/fixtures/mvp/verification/cases.json --output artifacts/mvp-verification/run.json
python3 -I scripts/run_mvp_verification.py --validate-report artifacts/mvp-verification/run.json
```

Use a fresh output name for each run. The exporter never replaces an existing
artifact, including on failure. `--validate-report` only reads the artifact and
current source bindings; it does not execute tests or repeat their effects.
Both commands return zero only for complete selected PASS evidence. Optional
`--checked-sha`, `--base-sha` and `--source-head` pins must be identical on validation.
CI supplies its checked commit separately from the PR source head and base.
Isolated Python (`-I`) is required before any shadowable imports. The script
rejects unsupported ordinary invocation before loading its other modules.

Results require clean committed source and bind the actual Git HEAD plus a digest
of tracked source, the collector, selected modules, manifest and fixture files.
Untracked Python in execution directories and dirty tracked files fail before tests.
Actual file bytes and executable modes are compared to HEAD blobs independently
of Git index hints such as assume-unchanged or skip-worktree.
Use a clean isolated candidate for this evidence gate; ordinary development tests
remain available in a working checkout. A change invalidates
reuse; it does not automatically rerun tests. Null base means `not_supplied`, not a
zero SHA or a timestamp. The artifact is not a signed or authenticated CI result:
producer/workflow/event/ref/head must still be checked at the original provider.
A fresh public verification alias connects every row to one export. It rejects
accidental row mixing across runs with identical source pins, but is neither a
native identifier nor a signature that authenticates an artifact producer.

Only fixed outcomes, counts, validated public selectors/references and revisions
are exported. Raw imports, test output, skip reasons, subtest labels, exception
messages and tracebacks are discarded, including child output inherited on the
standard file descriptors, including shutdown handlers. This is an output boundary for reviewed repository
tests, not a sandbox for hostile Python code. Tests retain their ordinary execution
authority and must not receive production credentials.

`scope=selected_source_d` and the explicit excluded set are mandatory. PASS does
not mean all v1 requirements passed, a live L evaluation ran, native operation was
qualified, `verify_only` was enabled, or GitHub authenticated the result. The
collector's own contract tests are run by the unchanged full kernel suite.


Execution inputs are copied from the pinned Git objects into a read-only snapshot;
the registered working directory remains the effects workspace. This is not a
sandbox or a live-cleanliness attestation. Preflight rejects untracked source,
legacy bytecode and extension modules in the execution roots. Run prior local
checks with `python3 -B -m unittest discover -s tests -v` in a clean checkout.
The kernel CI job disables bytecode caches and has a bounded ten-minute budget;
other required checks, permissions and trusted scanning are unchanged.


Each selector executes in a pristine isolated process, preserving ordinary
unittest setup/teardown while excluding earlier selected methods' module patches.
The orchestrator never imports test modules. Versioned oracle definitions require
D kind, nonempty typed oracle/scope fields and unique S01--S30 scenario links;
unknown fields are rejected. The read-only artifact consumer accepts only bounded
regular UTF-8 files and rejects FIFOs, directories and final symlinks before reading.


The isolated orchestration worker imports no selected modules. On single-threaded
Linux/macOS, each selector forks that clean state, closes inherited channels and
returns through normal private interpreter shutdown. Other profiles use fresh exec.
Sync/async probes require the selected callable to run and finish exactly once;
swallowed assertions, unfinished daemon calls and lazy generator/coroutine returns
cannot pass. Result counters alone cannot certify execution. Private request framing has a
separate bound from accepted manifest bytes. The maximum 64x32 execution remains
required while the redundant smaller matrix is retained only as historical evidence.


Selected code never serializes its verdict with mutable process-global JSON tools.
A fixed, bounded primitive packet goes to the pristine orchestrator, which checks
the completion/reason counts and creates JSON. Snapshot boundaries compare actual
bytes and directory names using pinned per-file hashes; timestamps do not replace
content checks. Initial/final canonical source checks remain independently pinned.


The selected callable must return None. Other returns, including map/filter/custom
iterators, do not prove deferred assertions ran. Collection binds the pristine
unittest loader before selected import and requires the exact selected class.

For repeated modules, the clean orchestrator may compile at most 8 MB of pinned
source once without executing it. Fresh forks inherit immutable code objects;
every selector still executes its own module namespace and setup/teardown. No
selected heap or pyc file is shared, and every source-byte boundary check remains.
The optimization is optional; larger inputs retain ordinary compilation.

Selected programs retain their ordinary OS and assertion authority. Deliberately
forging descriptors, replacing assertions or manufacturing verdicts is outside this
reviewed-test boundary. Packet framing and a public alias do not authenticate
hostile programs. Trusted hosted producer/run evidence remains a separate check.
