#!/usr/bin/env python3
"""Render the Homebrew formula for an sbomly release.

Fills in the sdist url and sha256 from PyPI. Sbomly has no runtime dependencies, so
the formula needs no resource blocks; this refuses to render if that ever changes,
rather than shipping a formula that's missing them.

    render_formula.py 0.1.0 > Formula/sbomly.rb
    render_formula.py 0.1.0 --sdist dist/sbomly-0.1.0.tar.gz  # local testing
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

PACKAGE = "sbomly"
TEMPLATE = Path(__file__).with_name("sbomly.rb")


def pypi_release(version: str) -> tuple[str, str]:
    """Return the sdist url and sha256 for VERSION, checking it has no runtime deps."""
    with urllib.request.urlopen(f"https://pypi.org/pypi/{PACKAGE}/{version}/json", timeout=30) as resp:
        data = json.load(resp)
    # Extras (e.g. `dev`) are fine; anything unconditional would need a resource block.
    runtime = [req for req in data["info"].get("requires_dist") or [] if "extra ==" not in req]
    if runtime:
        raise SystemExit(f"{PACKAGE} {version} has runtime dependencies {runtime}; add resource blocks")
    for item in data["urls"]:
        if item["packagetype"] == "sdist":
            return item["url"], item["digests"]["sha256"]
    raise SystemExit(f"{PACKAGE} {version} has no sdist on PyPI; Homebrew builds from source")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("version")
    parser.add_argument("--sdist", help="Use a local sdist instead of the PyPI release.")
    args = parser.parse_args()

    if args.sdist:
        sdist = Path(args.sdist).resolve()
        url, sha256 = sdist.as_uri(), hashlib.sha256(sdist.read_bytes()).hexdigest()
    else:
        url, sha256 = pypi_release(args.version)

    sys.stdout.write(TEMPLATE.read_text().replace("@URL@", url).replace("@SHA256@", sha256))


if __name__ == "__main__":
    main()
