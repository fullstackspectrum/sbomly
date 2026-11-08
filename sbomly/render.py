"""Text, JSON and Markdown renderings of a Diff."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict

from . import __version__, udiff
from .diff import CHANGE_KINDS, FINDING_KINDS, Diff
from .model import Sbom

CHANGE_TITLES = {
    "added": "Added",
    "removed": "Removed",
    "upgraded": "Upgraded",
    "downgraded": "Downgraded",
    "changed": "Changed version",
}

FINDING_TITLES = {
    "hash": "Integrity",
    "copyleft": "Copyleft",
    "license": "Licence",
    "supplier": "Supplier",
}


def sbom_label(sbom: Sbom) -> str:
    """'payments-api 2.4.0', falling back to the file name."""
    label = " ".join(p for p in (sbom.subject, sbom.subject_version) if p)
    return label or sbom.source or "SBOM"


def headline(d: Diff) -> str:
    if not d.has_changes:
        return "No dependency changes."
    parts = [f"{d.count(k)} {k}" for k in CHANGE_KINDS if d.count(k)]
    flagged = sum(1 for f in d.findings if f.gating)
    if flagged:
        parts.append(f"{flagged} finding{'s' if flagged != 1 else ''} to review")
    return ", ".join(parts) + "."


# ── JSON ──────────────────────────────────────────────────────────────


def _sbom_meta(sbom: Sbom) -> dict:
    return {
        "source": sbom.source,
        "format": sbom.format,
        "specVersion": sbom.spec_version,
        "subject": sbom.subject,
        "subjectVersion": sbom.subject_version,
        "created": sbom.created,
        "tools": sbom.tools,
        "components": len(sbom.components),
    }


def to_json(d: Diff, fail_on: set[str] | None = None) -> str:
    doc = {
        "tool": {"name": "sbomly", "version": __version__},
        "old": _sbom_meta(d.old),
        "new": _sbom_meta(d.new),
        "summary": {
            **{k: d.count(k) for k in CHANGE_KINDS + FINDING_KINDS},
            "unchanged": d.unchanged,
        },
        "changes": [asdict(c) for c in d.changes],
        "findings": [asdict(f) for f in d.findings],
    }
    if fail_on is not None:
        doc["failOn"] = {"categories": sorted(fail_on), "triggered": d.triggered(fail_on)}
    return json.dumps(doc, indent=2, ensure_ascii=False) + "\n"


# ── Terminal ──────────────────────────────────────────────────────────

# Closest terminal colours to the Full-Stack-Spectrum palette: blue for new,
# bright blue (blue-soft) for upgrades, 256-colour 209 for orange, red only
# for the integrity finding.
_COLOURS = {
    "added": "34", "removed": "2", "upgraded": "94", "downgraded": "38;5;209", "changed": "33",
    "hash": "31;1", "copyleft": "38;5;209", "license": "33", "supplier": "33",
    "dim": "2", "bold": "1",
}

# The diff view keeps the convention everyone reads at a glance: removals in
# red. Additions take the brand blue rather than green.
_DIFF_COLOURS = {
    "bold": "1", "dim": "2", "hunk": "94", "del": "31", "add": "34",
    # Changed words: white on a dark red or dark blue (256-colour 88 and 25).
    "del-mark": "1;97;48;5;88", "add-mark": "1;97;48;5;25",
}


def use_colour(stream=None) -> bool:
    stream = stream or sys.stdout
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return hasattr(stream, "isatty") and stream.isatty()


def to_text(d: Diff, colour: bool = False, limit: int = 25) -> str:
    def c(style: str, text: str) -> str:
        return f"\033[{_COLOURS[style]}m{text}\033[0m" if colour else text

    lines = [
        c("bold", f"sbomly: {sbom_label(d.old)}  →  {sbom_label(d.new)}"),
        c("dim", f"{len(d.old.components)} → {len(d.new.components)} components, "
                 f"{d.unchanged} unchanged"),
        "",
        headline(d),
    ]

    if d.findings:
        lines += ["", c("bold", "Findings")]
        for f in d.findings[:limit]:
            tag = c(f.kind, f"{FINDING_TITLES[f.kind].lower():<9}")
            note = "" if f.gating else c("dim", "  (info)")
            lines.append(f"  {tag} {f.name} {c('dim', f.version)}  {f.message}{note}")
        if len(d.findings) > limit:
            lines.append(c("dim", f"  … and {len(d.findings) - limit} more"))

    for kind in CHANGE_KINDS:
        rows = [ch for ch in d.changes if ch.kind == kind]
        if not rows:
            continue
        lines += ["", c("bold", f"{CHANGE_TITLES[kind]} ({len(rows)})")]
        sign = {"added": "+", "removed": "-"}.get(kind, "~")
        for ch in rows[:limit]:
            if kind == "added":
                version = ch.new_version
            elif kind == "removed":
                version = ch.old_version
            else:
                version = f"{ch.old_version} → {ch.new_version}"
            lines.append(f"  {c(kind, sign)} {ch.name} {c('dim', version)}")
        if len(rows) > limit:
            lines.append(c("dim", f"  … and {len(rows) - limit} more"))

    return "\n".join(lines) + "\n"


def to_unified_text(d: Diff, context: int = 3, colour: bool = False) -> str:
    """The component diff for a terminal.

    Without colour it's a plain unified diff that patch(1) accepts. With
    colour it reads like the HTML report's diff view: an old/new line-number
    gutter, and the changed words highlighted within each -/+ pair.
    """
    lines = udiff.unified(d, context)
    if not lines:
        return "No dependency changes.\n"
    signs = {"file": "", "hunk": "", "del": "-", "add": "+", "ctx": " "}
    if not colour:
        return "\n".join(signs[ln.kind] + ln.text for ln in lines) + "\n"

    def c(style: str, text: str) -> str:
        return f"\033[{_DIFF_COLOURS[style]}m{text}\033[0m" if text else ""

    marks: dict[int, list[tuple[str, bool]]] = {}
    for i, j in udiff.pairs(lines).items():
        marks[i], marks[j] = udiff.word_marks(lines[i].text, lines[j].text)
    width = len(str(max(max(ln.old_no or 0, ln.new_no or 0) for ln in lines)))

    out = []
    for i, ln in enumerate(lines):
        if ln.kind == "file":
            out.append(c("bold", ln.text))
            continue
        if ln.kind == "hunk":
            out.append(c("hunk", ln.text))
            continue
        gutter = c("dim", f"{ln.old_no or '':>{width}} {ln.new_no or '':>{width}} │")
        if ln.kind == "ctx":
            out.append(f"{gutter}   {c('dim', ln.text)}")
            continue
        base = ln.kind
        if i in marks:
            body = "".join(c(f"{base}-mark" if changed else base, t) for t, changed in marks[i])
        else:
            body = c(base, ln.text)
        out.append(f"{gutter} {c(base, signs[ln.kind])} {body}")
    return "\n".join(out) + "\n"


# ── Markdown ──────────────────────────────────────────────────────────

# GitHub rejects comments over 65,536 characters. Stop adding rows well
# before that so the summary always makes it.
MARKDOWN_BUDGET = 60_000


def _md(text: str) -> str:
    """Escape the characters that would break a table cell or inject markup."""
    for ch in ("\\", "|", "`", "*", "_", "[", "]", "<", ">"):
        text = text.replace(ch, "\\" + ch)
    return text.replace("\n", " ")


def _code(text: str) -> str:
    # GitHub splits table cells on '|' even inside a code span, so it still
    # needs escaping there; a backtick would end the span early.
    if not text:
        return "—"
    text = " ".join(text.split()).replace("`", "").replace("|", "\\|")
    return f"`{text}`"


def to_markdown(d: Diff, limit: int = 100, title: str = "", context: int | None = None) -> str:
    """context: include a unified diff with this many context lines; None leaves it out."""
    out: list[str] = []
    out.append(f"### {_md(title) if title else 'SBOM diff'}")
    out.append("")
    out.append(f"**{_md(sbom_label(d.old))}** → **{_md(sbom_label(d.new))}** · "
               f"{len(d.old.components)} → {len(d.new.components)} components · "
               f"{d.unchanged} unchanged")
    out.append("")
    out.append(_md(headline(d)))
    out.append("")

    if d.has_changes:
        out.append("| " + " | ".join(CHANGE_TITLES[k] for k in CHANGE_KINDS) + " | Findings |")
        out.append("|" + "---:|" * (len(CHANGE_KINDS) + 1))
        flagged = sum(1 for f in d.findings if f.gating)
        out.append("| " + " | ".join(str(d.count(k)) for k in CHANGE_KINDS) + f" | {flagged} |")
        out.append("")

    size = sum(len(line) + 1 for line in out)
    truncated = False

    def section(heading: str, header: str, rows: list[str], open_: bool) -> None:
        nonlocal size, truncated
        if not rows:
            return
        block = [f"<details{' open' if open_ else ''}>",
                 f"<summary><strong>{heading}</strong> ({len(rows)})</summary>", "",
                 header, "|" + "---|" * header.count("|", 1)]
        shown = 0
        for row in rows[:limit]:
            if size + sum(len(b) + 1 for b in block) + len(row) > MARKDOWN_BUDGET:
                truncated = True
                break
            block.append(row)
            shown += 1
        if shown < len(rows):
            block.append("")
            block.append(f"_… {len(rows) - shown} more not shown. See the HTML or JSON report._")
        block += ["", "</details>", ""]
        out.extend(block)
        size += sum(len(b) + 1 for b in block)

    finding_rows = [
        f"| {FINDING_TITLES[f.kind]}{'' if f.gating else ' (info)'} | {_md(f.name)} | "
        f"{_code(f.version)} | {_md(f.message)} |"
        for f in d.findings
    ]
    section("Findings to review", "| Type | Package | Version | Detail |", finding_rows, True)

    if context is not None and d.has_changes:
        # GitHub colours a ```diff block red and green. Backticks are
        # swapped out so a component name can't close the fence early.
        diff_lines = [
            {"file": "", "hunk": "", "del": "-", "add": "+", "ctx": " "}[ln.kind] + ln.text.replace("`", "'")
            for ln in udiff.unified(d, context)
        ]
        block = ["<details open>", "<summary><strong>Diff</strong></summary>", "", "```diff"]
        budget = MARKDOWN_BUDGET - size - 2_000  # leave room for the change tables
        used = 0
        for line in diff_lines:
            if used + len(line) + 1 > budget:
                block.append("… diff truncated to fit GitHub's size limit")
                truncated = True
                break
            block.append(line)
            used += len(line) + 1
        block += ["```", "", "</details>", ""]
        out.extend(block)
        size += sum(len(b) + 1 for b in block)

    for kind in CHANGE_KINDS:
        rows = []
        for ch in (c for c in d.changes if c.kind == kind):
            if kind == "added":
                rows.append(f"| {_md(ch.name)} | {_code(ch.new_version)} | {_md(ch.license) or '—'} |")
            elif kind == "removed":
                rows.append(f"| {_md(ch.name)} | {_code(ch.old_version)} | {_md(ch.license) or '—'} |")
            else:
                rows.append(f"| {_md(ch.name)} | {_code(ch.old_version)} | {_code(ch.new_version)} |")
        header = ("| Package | Version | Licence |" if kind in ("added", "removed")
                  else "| Package | From | To |")
        section(CHANGE_TITLES[kind], header, rows, open_=False)

    if truncated:
        out.append("_This comment was shortened to fit GitHub's size limit._")
        out.append("")
    out.append(f"<sub>Generated by [sbomly](https://github.com/fullstackspectrum/sbomly) {__version__}</sub>")
    return "\n".join(out) + "\n"
