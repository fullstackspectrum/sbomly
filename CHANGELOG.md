# Changelog

## 1.0.0 (2026-11-17)

First stable release. From here, Sbomly follows semantic versioning: the CLI flags, the `--fail-on` categories, the exit codes, the JSON output and the GitHub Action inputs and outputs only change in a backwards-incompatible way in a new major version.

- No functional changes since 0.1.0.
- The GitHub Action can be pinned to `fullstackspectrum/sbomly@v1`, which follows the newest 1.x release.
- Docker images are also tagged with the major version, e.g. `fullstackspectrum/sbomly:1`.

## 0.1.0 (2026-11-09)

First release.

- `sbomly diff OLD NEW` compares two CycloneDX (1.4 to 1.6) or SPDX (2.2, 2.3) JSON SBOMs, in any combination.
- Reports added, removed, upgraded, downgraded and changed components, matched by package URL.
- Flags integrity (same version, new digest), copyleft, licence and supplier changes.
- Output: terminal summary, Markdown for PR comments (kept under GitHub's size limit), JSON, and a self-contained offline HTML report in light and dark themes.
- `--fail-on` turns any category into a CI gate, with exit code 1.
- `-u` / `-U N` prints a unified diff of the component lists that `patch` accepts. The HTML report has the same diff behind a table/diff toggle, with word-level highlighting, and Markdown output gets a `diff` block.
- Composite GitHub Action that writes the summary to the job page.
