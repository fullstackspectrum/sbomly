"""Command-line interface."""

from __future__ import annotations

import argparse
import inspect
import re
import shutil
import sys
from pathlib import Path

from . import __version__
from .diff import FAIL_ON_CHOICES, diff
from .parse import SbomError, load
from .render import to_json, to_markdown, to_text, to_unified_text, use_colour

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


# ── Help ──────────────────────────────────────────────────────────────

REPO = "https://github.com/fullstackspectrum/sbomly"

# Reference sections printed after the options. Kept as plain two-column
# text so they line up with argparse's own sections and colour the same way.
DIFF_EPILOG = """\
fail-on categories:
  added, removed        a component appears or disappears
  upgraded, downgraded  a component moves to a newer or older version
  changed               a version change that can't be ordered (commit SHAs, digests)
  hash                  same version, different digest: rebuilt or replaced
  copyleft              a new dependency or licence brings in copyleft terms
  license               a licence changed, or is no longer declared
  supplier              a component's supplier changed
  any                   all of the above

exit codes:
  0                     passed, or nothing in --fail-on occurred
  1                     a --fail-on category occurred
  2                     bad usage, or an SBOM that can't be read

examples:
  $ sbomly diff old.cdx.json new.cdx.json
  $ sbomly diff old.json new.json -u                    # line-by-line diff
  $ sbomly diff old.json new.json --html report.html    # offline HTML report
  $ sbomly diff main.json pr.json --fail-on hash,copyleft
  $ syft my-image -o cyclonedx-json | sbomly diff baseline.json -
"""

ROOT_EPILOG = f"""\
examples:
  $ sbomly diff old.cdx.json new.cdx.json
  $ sbomly diff --help                                  # every option for diff

docs:
  {REPO}
"""

# Brand colours as terminal codes: flags take blue-soft (keys in code),
# placeholders yellow (strings), headings the // eyebrow.
_HELP_STYLES = {"flag": "94", "meta": "33", "dim": "2", "bold": "1", "red": "31"}


def _style(code: str, text: str) -> str:
    return f"\033[{_HELP_STYLES[code]}m{text}\033[0m"


def _colourise_help(text: str) -> str:
    out = []
    section = ""
    for line in text.splitlines():
        heading = re.fullmatch(r"([a-z][a-z -]*):", line)
        if heading:
            section = heading.group(1)
            out.append(f"{_style('dim', '//')} {_style('bold', section)}")
            continue
        if line.startswith("usage:"):
            out.append(f"{_style('dim', '//')} {_style('bold', 'usage')}")
            out.append("  " + re.sub(r"\b(sbomly(?: diff)?)\b", lambda m: _style("red", m.group(1)), line[7:], count=1))
            continue
        if section == "examples" and line.lstrip().startswith("$"):
            cmd, _, comment = line.partition("#")
            cmd = cmd.replace("$", _style("dim", "$"), 1)
            out.append(cmd + (_style("dim", "#" + comment) if comment else ""))
            continue
        if section == "docs":
            out.append(_style("flag", line))
            continue
        m = re.match(r"^(  )(\S.*?)(\s{2,}\S.*)?$", line)
        if m and section not in ("", "usage"):
            term = re.sub(r"(?<![\w-])(--?[\w-]+)", lambda x: _style("flag", x.group(1)), m.group(2))
            term = re.sub(r"(?<![\w-])([A-Z]+)\b", lambda x: _style("meta", x.group(1)), term)
            if section in ("fail-on categories", "commands", "exit codes"):
                term = _style("flag", m.group(2))
            out.append(m.group(1) + term + (m.group(3) or ""))
            continue
        out.append(line)
    return "\n".join(out) + "\n"


class _HelpFormatter(argparse.RawDescriptionHelpFormatter):
    def __init__(self, prog: str) -> None:
        width = min(shutil.get_terminal_size((100, 24)).columns, 100)
        super().__init__(prog, max_help_position=24, width=width)
        # Pin the help column at 24 in every section, so options and the
        # hand-written reference sections in the epilog line up.
        self._action_max_length = 22

    def _format_action(self, action: argparse.Action) -> str:
        # List subcommands directly under "commands:", without argparse's
        # extra "COMMAND" line above them.
        if isinstance(action, argparse._SubParsersAction):
            return "".join(self._format_action(a) for a in action._get_subactions())
        return super()._format_action(action)

    def _format_action_invocation(self, action: argparse.Action) -> str:
        # "-U, --context N" rather than argparse's "-U N, --context N".
        if not action.option_strings or action.nargs == 0:
            return super()._format_action_invocation(action)
        metavar = self._format_args(action, self._get_default_metavar_for_optional(action))
        return f"{', '.join(action.option_strings)} {metavar}"


class _Parser(argparse.ArgumentParser):
    """ArgumentParser whose help is grouped, wrapped to the terminal and, on a
    colour terminal, styled in the Full-Stack-Spectrum palette."""

    def __init__(self, *args, **kwargs) -> None:
        kwargs.setdefault("formatter_class", _HelpFormatter)
        kwargs.setdefault("add_help", False)
        # Python 3.14 colours help itself; this parser does its own.
        if "color" in inspect.signature(argparse.ArgumentParser.__init__).parameters:
            kwargs.setdefault("color", False)
        super().__init__(*args, **kwargs)

    def format_help(self) -> str:
        text = super().format_help()
        return _colourise_help(text) if use_colour() else text


def _help_flag(group) -> None:
    group.add_argument("-h", "--help", action="help", help="show this help and exit")


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="sbomly",
        usage="sbomly COMMAND [options]",
        description=f"sbomly {__version__}: see what changed between two SBOMs, "
                    "and what deserves a closer look.",
        epilog=ROOT_EPILOG,
    )
    sub = parser.add_subparsers(dest="command", title="commands", metavar="COMMAND",
                                parser_class=_Parser)
    general = parser.add_argument_group("options")
    _help_flag(general)
    general.add_argument("--version", action="version", version=f"sbomly {__version__}",
                         help="print the version and exit")

    d = sub.add_parser(
        "diff",
        help="compare two CycloneDX or SPDX JSON SBOMs",
        usage="sbomly diff OLD NEW [options]",
        description=(
            "Compare two SBOMs: what was added, removed, upgraded or downgraded, and which\n"
            "integrity, copyleft, licence and supplier changes deserve a closer look.\n"
            "Reads CycloneDX (1.4 to 1.6) or SPDX (2.2, 2.3) JSON, in any combination."
        ),
        epilog=DIFF_EPILOG,
    )

    inputs = d.add_argument_group("arguments")
    inputs.add_argument("old", metavar="OLD", help="the baseline SBOM (before)")
    inputs.add_argument("new", metavar="NEW", help="the SBOM to compare against it (after); "
                                                   "either can be - for stdin")

    output = d.add_argument_group("output")
    output.add_argument("-f", "--format", choices=("text", "markdown", "json"), default="text",
                        metavar="FORMAT", help="what to print: text (default), markdown or json")
    output.add_argument("--html", metavar="FILE", type=Path,
                        help="write a self-contained HTML report that works offline")
    output.add_argument("--markdown", metavar="FILE", type=Path,
                        help="write a Markdown summary sized for a PR comment")
    output.add_argument("--json", metavar="FILE", type=Path, help="write the full diff as JSON")
    output.add_argument("-q", "--quiet", action="store_true", help="print nothing to stdout")

    view = d.add_argument_group("diff view")
    view.add_argument("-u", "--unified", action="store_true",
                      help="print a line-by-line diff of the component lists, like diff -u")
    view.add_argument("-U", "--context", type=int, default=3, metavar="N",
                      help="unchanged components shown around each change (default: 3)")

    gate = d.add_argument_group("ci gating")
    gate.add_argument("--fail-on", metavar="LIST", type=_fail_on, default=set(),
                      help="exit 1 if any of these comma-separated categories occur (see below)")

    display = d.add_argument_group("display")
    display.add_argument("--title", default="", metavar="TEXT",
                         help="title for the HTML and Markdown reports")
    display.add_argument("--theme", choices=("dark", "light"), default="dark", metavar="THEME",
                         help="HTML report theme: dark (default) or light")
    display.add_argument("--limit", type=int, default=100, metavar="N",
                         help="rows per section in text and Markdown output (default: 100)")
    display.add_argument("--no-color", action="store_true",
                         help="plain terminal output; NO_COLOR and FORCE_COLOR are respected too")
    _help_flag(display)
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
    if args.context < 0:
        raise SbomError("--context can't be negative")
    result = diff(load(args.old), load(args.new))
    md_context = args.context if args.unified else None
    colour = use_colour() and not args.no_color

    if args.html:
        from .html import to_html  # Only pay for loading the fonts when asked.

        _write(args.html, to_html(result, theme=args.theme, title=args.title, context=args.context))
    if args.markdown:
        _write(args.markdown, to_markdown(result, limit=args.limit, title=args.title, context=md_context))
    if args.json:
        _write(args.json, to_json(result, args.fail_on))

    if not args.quiet:
        if args.format == "json":
            sys.stdout.write(to_json(result, args.fail_on))
        elif args.format == "markdown":
            sys.stdout.write(to_markdown(result, limit=args.limit, title=args.title, context=md_context))
        elif args.unified:
            sys.stdout.write(to_unified_text(result, context=args.context, colour=colour))
        else:
            sys.stdout.write(to_text(result, colour=colour, limit=args.limit))

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
