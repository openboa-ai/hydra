# Releasing Hydra

There is no release for `0.0.0`. This file records the future order so a package revision, an evaluation result, and a catalog entry cannot drift apart.

1. Freeze an exact candidate commit and package version.
2. Run Hydra's package checks and the candidate in Hydra Eval with a temporary catalog source.
3. Review the task result, verifier output, trajectory/artifacts, time, token use, cost, and safety evidence.
4. Decide whether the candidate is a release. A human owns the purpose and public release decision.
5. Create an immutable release only after the exact reviewed commit is known.
6. Update the separate OpenBoa Plugins marketplace to that exact source revision and verify a fresh install.
7. Observe the installed result. If it is unsafe or incorrect, disable the catalog entry, record invalidation and rollback guidance, and publish a higher patch version; do not move or rewrite the old revision.

The marketplace is not a second version source. Hydra owns package versions; Hydra Eval owns evaluation evidence; the marketplace owns the source revision and install availability it advertises.
