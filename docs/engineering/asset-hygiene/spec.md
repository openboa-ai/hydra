# Verified binary asset classification for repository hygiene

Revision: 2

## Problem and scope

The repository hygiene workflow forces every candidate file to text for whitespace
checking. This prevents candidate attributes from disabling the check, but also
interprets the bundled TTF/WOFF2 fonts and PNG icon as text. Their original bytes
produce meaningless whitespace failures, stopping later workflow and secret checks.
The two OFL notices additionally contain one trailing space each. Two continuity
test files contain an extra blank line at EOF.

This change corrects classification for three exact original assets and removes only
those text whitespace errors. It does not change asset bytes, application behavior, scanner
policy, protected review, or installation authority.

## Contract

1. Keep the global forced-text whitespace rule in `.git/info/attributes` for all
   other paths. Candidate `.gitattributes` and asset manifests cannot define or
   broaden the exception.
2. Pin the following paths and SHA-256 values directly in the protected workflow:

   | Path | SHA-256 |
   | --- | --- |
   | `apps/mac/public/fonts/MartianGrotesk-wdth-wght.ttf` | `f81807163c34ff754e6d915b0b59f76cca88332b67c45cfc7453ace5751ae912` |
   | `apps/mac/public/fonts/PretendardVariable.woff2` | `9599f12fd42fc0bce1cd50b47a0c022e108d7aa64dd0d1bb0ed44f3282d900b4` |
   | `apps/mac/src-tauri/icons/icon.png` | `005be38b40da8a96037bc632b6f2c3ff48028d007b9e959dc9ed2a6543c3580c` |

3. Inspect both comparison endpoints using Git objects. Each present exact-path
   entry must be a single regular, non-executable `100644 blob` whose bytes match
   the pinned SHA-256. Reject changed bytes, symlinks, executable modes, trees,
   gitlinks, malformed entries, and failed Git queries. Genuine absence is allowed
   at either endpoint, including an empty initial base and deletion of an asset.
4. Append an exact-path `-diff` entry only after every present object for that path
   passes validation. An asset absent at both endpoints needs no override.
5. Keep the checked-HEAD assertion and whitespace settings. Disable rename
   detection for the whitespace diff so a verified asset cannot transfer its
   classification to another destination. Keep external diffs and textconv disabled.
6. Preserve all OFL notice text; remove only the two existing trailing spaces.
   Remove only the final extra newline in `tests/test_post_merge_continuity.py`
   and `tests/test_progress_hints.py`, preserving their code and assertions.
7. Leave actionlint, immutable shared tooling, history/source secret scanning,
   permissions, ignore-file rejection, CODEOWNERS, and protected checks unchanged.
   Existing scanner exclusions remain unchanged. Exact asset hashes prove byte
   integrity, not absence of embedded secrets or a secret scan of binary payloads.

## Verification and delivery

Exercise the actual workflow whitespace script against isolated Git repositories.
Verify valid asset additions, unchanged assets, deletions, and an empty initial base.
Reject ordinary source and license whitespace even with candidate attributes;
reject changed asset bytes, text substituted at an asset path, invalid object modes,
invalid base objects, and an invalid base asset even when the head is valid. Check
that a renamed/mutated asset destination cannot inherit the exception. Run the actual
whitespace check on the complete publishable candidate against its PR base, as well
as the isolated regression fixtures; fixture success is not full-candidate evidence.

Independently review this revision before implementation and review the final
workflow delta before publication. Re-run current-head CI and distinguish its
whitespace, workflow-lint, kernel, and trusted secret-scan results. Local checks do
not establish remote success. Because `.github/` changes, merge still requires the
configured human code-owner approval; agent review or green candidate CI cannot
substitute for it. Keep the existing PR a draft until its other acceptance and
delivery gates are satisfied.
