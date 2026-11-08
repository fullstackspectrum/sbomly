[![Sbomly: what changed between two SBOMs, and what to check.](docs/brand/readme-banner.png)](https://github.com/fullstackspectrum/sbomly)

[![CI](https://img.shields.io/github/actions/workflow/status/fullstackspectrum/sbomly/build.yml?branch=main&style=for-the-badge&logo=githubactions&logoColor=white&label=CI&color=4f8cff&labelColor=10151d)](https://github.com/fullstackspectrum/sbomly/actions/workflows/build.yml)
[![Python](https://img.shields.io/badge/python-3.10%2B-f5c84c?style=for-the-badge&logo=python&logoColor=white&labelColor=10151d)](pyproject.toml)
[![License](https://img.shields.io/badge/license-Apache--2.0-646f7f?style=for-the-badge&labelColor=10151d)](LICENSE)

# Sbomly

**See what changed between two SBOMs, and what deserves a closer look.**

Sbomly compares two SBOMs, CycloneDX or SPDX JSON, and tells you which components were added, removed, upgraded or downgraded. It also flags the changes a reviewer should actually stop for:

- **Integrity:** same version, different digest. The artifact was rebuilt or replaced.
- **Copyleft:** a new dependency, or a new licence, that brings in GPL, LGPL, AGPL and similar.
- **Licence:** a licence changed, or stopped being declared.
- **Supplier:** a package's supplier changed. In a language ecosystem that's the account-takeover pattern.

Output goes wherever you need it: a terminal summary, a Markdown summary sized for a PR comment, JSON for other tools, and a self-contained HTML report that works offline. `--fail-on` turns any category into a CI gate.

Sbomly has no runtime dependencies and needs Python 3.10 or later.

> Sbomly is a sibling of [Vulnly](https://github.com/fullstackspectrum/Vulnly) and part of [Full-Stack-Spectrum](https://fullstackspectrum.com/): small open-source tools that turn noisy supply chain data into decisions.

## Install

```bash
pipx install sbomly     # or: pip install sbomly
```

## Usage

```bash
sbomly diff old.cdx.json new.cdx.json
```

```text
sbomly: payments-api 2.3.0  →  payments-api 2.4.0
9 → 10 components, 4 unchanged

2 added, 1 removed, 3 upgraded, 1 downgraded, 5 findings to review.

Findings
  integrity axios 1.6.0  Same version, different SHA256 digest: the artifact was rebuilt or replaced
  copyleft  readline-sync 1.4.10  New dependency under strong copyleft licence (GPL-3.0-only)
  copyleft  sharp 0.33.0  Now weak copyleft (Apache-2.0 AND LGPL-3.0-or-later)
  licence   sharp 0.33.0  Licence changed from Apache-2.0 to Apache-2.0 AND LGPL-3.0-or-later
  supplier  @acme/logger 1.2.0  Supplier changed from Acme Inc to Acme Holdings Ltd

Added (2)
  + chalk 5.3.0
  + readline-sync 1.4.10
...
```

Write reports alongside the terminal summary:

```bash
sbomly diff old.json new.json --html report.html --markdown pr.md --json diff.json
```

Read one SBOM from stdin, for example straight from a generator:

```bash
syft my-image:latest -o cyclonedx-json | sbomly diff baseline.cdx.json -
```

### Options

| Option | |
|---|---|
| `-f, --format text\|markdown\|json` | What to print to stdout (default `text`) |
| `--html FILE` | Write the offline HTML report |
| `--markdown FILE` | Write the Markdown summary |
| `--json FILE` | Write the full diff as JSON |
| `--fail-on LIST` | Exit 1 if any of these categories occur (see below) |
| `--title TEXT` | Title for the HTML and Markdown reports |
| `--theme dark\|light` | HTML report theme (default `dark`) |
| `--limit N` | Rows per section in text and Markdown (default 100) |
| `--no-color` | Plain terminal output. `NO_COLOR` and `FORCE_COLOR` are respected |
| `-q, --quiet` | Print nothing to stdout |

### Gating CI with `--fail-on`

| Category | Fails when |
|---|---|
| `added` / `removed` | A component appears or disappears |
| `upgraded` / `downgraded` | A component moves to a newer or older version |
| `changed` | A version changes but can't be ordered (commit SHAs, digests) |
| `hash` | Same version, different digest |
| `copyleft` | A new dependency is copyleft, or a licence becomes more restrictive |
| `license` | A licence changes, or is no longer declared |
| `supplier` | A component's supplier changes |
| `any` | Any of the above |

```bash
sbomly diff main.cdx.json pr.cdx.json --fail-on hash,copyleft,downgraded
```

Exit codes: `0` passed, `1` a `--fail-on` category was hit, `2` bad usage or an unreadable SBOM.

Some findings are informational. They're shown, but they never fail a build:

- A licence that was unknown and is now declared.
- A same-version digest change where the purl's `distro` qualifier also changed. Distros rebuild unchanged packages for each release.
- A supplier change for an OS package (apk, deb, rpm). There, the supplier is the distro maintainer, and maintainers rotate.

## GitHub Actions

Sbomly ships as a composite action. It writes the Markdown summary to the job page, and exposes the report paths for a PR comment or artifact upload.

```yaml
- uses: fullstackspectrum/sbomly@v0.1.0
  with:
    old: sbom-main.cdx.json
    new: sbom-pr.cdx.json
    fail-on: hash,copyleft
```

Or call the CLI yourself on any CI system:

```bash
pipx run sbomly diff baseline.json current.json --markdown sbomly.md --fail-on hash
```

## How components are matched

Components are paired across the two SBOMs by package URL, ignoring the version. Qualifiers that only describe the build environment, like `distro` and `repository_url`, are also ignored, so moving to a new base image doesn't report every OS package as removed and re-added. `arch`, `classifier` and `type` are kept, because they identify a different artifact. PyPI names are normalised as PEP 503 describes. Components without a purl fall back to their group and name.

When a package has several versions in both SBOMs, which npm often does, the leftover versions are paired in version order.

## Supported formats

| Format | Versions |
|---|---|
| CycloneDX JSON | 1.4 to 1.6 tested, older versions usually work |
| SPDX JSON | 2.2, 2.3 |

CycloneDX XML, SPDX tag-value and SPDX 3.0 aren't supported yet. Sbomly tells you so rather than guessing.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
```

## Licence

Apache-2.0. The bundled Space Grotesk and JetBrains Mono fonts are under the SIL Open Font License 1.1. See `sbomly/assets/`.

Copyleft classification is a triage signal, not legal advice.
