"""Command-line interface."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .diff import FAIL_ON_CHOICES, diff
from .parse import SbomError, load
from .render import to_json, to_markdown, to_text, use_colour

# Exit codes: 0 clean (or nothing gated), 1 a --fail-on category was hit,
# 2 bad usage or unreadable input. argparse already uses 2 for usage errors.
EXIT_OK, EXIT_GATED, EXIT_ERROR = 0, 1, 2


def _fail_on(value: str) -> set[str]:
    kinds = {v.strip().lower() for v in value.split(",") if v.strip()}
    unknown = kinds - set(FAIL_ON_CHOICES)
    if unknown:
        raise argparse.ArgumentTypeError(
            f"unknown category {', '.join(sorted(unknown))} (choose from {', '.join(FAIL_ON_CHOICES)})"
        )
    return kinds


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="sbomly",
        description="See what changed between two SBOMs, and what deserves a closer look.",
    )
    parser.add_argument("--version", action="version", version=f"sbomly {__version__}")
    sub = parser.add_subparsers(dest="command", metavar="COMMAND")

    d = sub.add_parser(
        "diff",
        help="compare two CycloneDX or SPDX JSON SBOMs",
        description="Compare two CycloneDX or SPDX JSON SBOMs. Use - to read one from stdin.",
        epilog=(
            "fail-on categories: added, removed, upgraded, downgraded, changed "
            "(a version change that can't be ordered), hash (same version, different digest), "
            "copyleft (new or newly copyleft licence), license, supplier, any. "
            "Example: --fail-on hash,copyleft"
        ),
    )
    d.add_argument("old", help="the baseline SBOM (before)")
    d.add_argument("new", help="the SBOM to compare against it (after)")
    d.add_argument("-f", "--format", choices=("text", "markdown", "json"), default="text",
                   help="what to print to stdout (default: text)")
    d.add_argument("--html", metavar="FILE", type=Path, help="write a self-contained HTML report")
    d.add_argument("--markdown", metavar="FILE", type=Path, help="write a Markdown summary, e.g. for a PR comment")
    d.add_argument("--json", metavar="FILE", type=Path, help="write the full diff as JSON")
    d.add_argument("--fail-on", metavar="LIST", type=_fail_on, default=set(),
                   help="exit 1 if any of these comma-separated categories occur")
    d.add_argument("--title", default="", help="title for the HTML and Markdown reports")
    d.add_argument("--theme", choices=("dark", "light"), default="dark", help="HTML report theme (default: dark)")
    d.add_argument("--limit", type=int, default=100, metavar="N",
                   help="rows per section in text and Markdown output (default: 100)")
    d.add_argument("--no-color", action="store_true", help="disable coloured terminal output")
    d.add_argument("-q", "--quiet", action="store_true", help="print nothing to stdout")
    return parser


def _write(path: Path, content: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise SbomError(f"{path}: can't write ({exc.strerror})") from None


def run_diff(args: argparse.Namespace) -> int:
    if args.old == "-" and args.new == "-":
        raise SbomError("only one SBOM can come from stdin")
    result = diff(load(args.old), load(args.new))

    if args.html:
        from .html import to_html  # Only pay for loading the fonts when asked.

        _write(args.html, to_html(result, theme=args.theme, title=args.title))
    if args.markdown:
        _write(args.markdown, to_markdown(result, limit=args.limit, title=args.title))
    if args.json:
        _write(args.json, to_json(result, args.fail_on))

    if not args.quiet:
        if args.format == "json":
            sys.stdout.write(to_json(result, args.fail_on))
        elif args.format == "markdown":
            sys.stdout.write(to_markdown(result, limit=args.limit, title=args.title))
        else:
            sys.stdout.write(to_text(result, colour=use_colour() and not args.no_color, limit=args.limit))

    hits = result.triggered(args.fail_on)
    if hits:
        summary = ", ".join(f"{n} {kind}" for kind, n in hits.items())
        # Keep the report above the verdict when both go to a terminal.
        sys.stdout.flush()
        print(f"sbomly: failing because of {summary}", file=sys.stderr)
        return EXIT_GATED
    return EXIT_OK


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command != "diff":
        parser.print_help()
        sys.exit(EXIT_ERROR)
    try:
        sys.exit(run_diff(args))
    except SbomError as exc:
        print(f"sbomly: {exc}", file=sys.stderr)
        sys.exit(EXIT_ERROR)
