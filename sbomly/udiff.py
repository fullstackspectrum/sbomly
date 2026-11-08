"""Unified-diff view of two SBOMs: one line per component, sorted like a lockfile.

Lines are built from the semantic diff rather than the raw documents, so
anything Sbomly treats as the same (licence term order, a distro qualifier)
renders identically on both sides and drops out as context. Hashes and
suppliers only appear on a line when they changed, which turns a
same-version finding into a visible -/+ pair.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from . import licenses
from .diff import Diff, _index, _norm, _tokens
from .model import Component

NAME_WIDTH, VERSION_WIDTH = 40, 24


@dataclass
class Line:
    kind: str  # "file", "hunk", "add", "del", "ctx"
    text: str
    old_no: int | None = None
    new_no: int | None = None
    key: str = ""  # the component this line belongs to, for pairing -/+ lines


def _sort_key(comp: Component) -> tuple:
    epoch, tokens = _tokens(comp.version)
    # Tag tokens so ints and strings never compare against each other.
    version = [(0, t, "") if isinstance(t, int) else (1, 0, t) for t in tokens]
    return (comp.ecosystem, comp.display_name.lower(), epoch, version, comp.version)


def _changed_hash(a: Component, b: Component) -> str | None:
    for alg in sorted(a.hashes.keys() & b.hashes.keys()):
        if a.hashes[alg] != b.hashes[alg]:
            return alg
    return None


def _render(comp: Component, license: str, extras: list[str], eco: bool,
            nw: int, vw: int) -> str:
    parts = [f"{comp.ecosystem:<8}"] if eco else []
    parts += [f"{comp.display_name:<{nw}}", f"{comp.version or '-':<{vw}}", license or "-"]
    return "  ".join(parts + extras).rstrip()


def _entries(d: Diff) -> list[tuple[str, str, str]]:
    """Every component as ("ctx" | "del" | "add", text, key), in lockfile order.

    Each component's removed line sits directly above its added one, so a
    version bump reads as a -/+ pair rather than two distant blocks.
    """
    old_index, new_index = _index(d.old), _index(d.new)
    every = d.old.components + d.new.components
    show_eco = len({c.ecosystem for c in every}) > 1
    nw = min(max((len(c.display_name) for c in every), default=0), NAME_WIDTH)
    vw = min(max((len(c.version) for c in every), default=0), VERSION_WIDTH)

    groups = []
    for key in old_index.keys() | new_index.keys():
        before, after = old_index.get(key, {}), new_index.get(key, {})
        supplier_changed = any(
            o.supplier and n.supplier and _norm(o.supplier) != _norm(n.supplier)
            for o in before.values() for n in after.values()
        )
        ctx, dels, adds = [], [], []
        for version in before.keys() | after.keys():
            o, n = before.get(version), after.get(version)
            o_extra: list[str] = []
            n_extra: list[str] = []
            o_lic = o.license if o else ""
            n_lic = n.license if n else ""
            if o and n:
                # Equivalent licences render the same, so they don't show as a change.
                if licenses.normalise(o_lic) == licenses.normalise(n_lic):
                    o_lic = n_lic
                alg = _changed_hash(o, n)
                if alg:
                    o_extra.append(f"{alg.lower()}:{o.hashes[alg][:12]}")
                    n_extra.append(f"{alg.lower()}:{n.hashes[alg][:12]}")
            if supplier_changed:
                if o:
                    o_extra.insert(0, f"by {o.supplier or '-'}")
                if n:
                    n_extra.insert(0, f"by {n.supplier or '-'}")
            o_text = _render(o, o_lic, o_extra, show_eco, nw, vw) if o else None
            n_text = _render(n, n_lic, n_extra, show_eco, nw, vw) if n else None
            if o_text is not None and o_text == n_text:
                ctx.append((_sort_key(n), n_text))
                continue
            if o_text is not None:
                dels.append((_sort_key(o), o_text))
            if n_text is not None:
                adds.append((_sort_key(n), n_text))
        rows = ([(k, "ctx", t) for k, t in ctx] + [(k, "del", t) for k, t in dels]
                + [(k, "add", t) for k, t in adds])
        first = min(k for k, _, _ in rows)
        # Unchanged versions first, then the removals above their replacements.
        order = {"ctx": 0, "del": 1, "add": 2}
        rows.sort(key=lambda r: (order[r[1]], r[0]))
        groups.append((first, [(kind, text, key) for _, kind, text in rows]))
    groups.sort(key=lambda g: g[0])
    return [entry for _, rows in groups for entry in rows]


def unified(d: Diff, context: int = 3) -> list[Line]:
    """Hunks with `context` unchanged lines around each change, as `diff -u` prints them."""
    entries = _entries(d)
    numbered: list[Line] = []
    old_no = new_no = 1
    for kind, text, key in entries:
        numbered.append(Line(kind, text,
                             old_no if kind != "add" else None,
                             new_no if kind != "del" else None, key))
        old_no += kind != "add"
        new_no += kind != "del"

    changed = [i for i, ln in enumerate(numbered) if ln.kind != "ctx"]
    if not changed:
        return []
    spans: list[list[int]] = []
    for i in changed:
        lo, hi = max(0, i - context), min(len(numbered) - 1, i + context)
        if spans and lo <= spans[-1][1] + 1:
            spans[-1][1] = max(spans[-1][1], hi)
        else:
            spans.append([lo, hi])

    out = [Line("file", f"--- {d.old.source or 'old'}"), Line("file", f"+++ {d.new.source or 'new'}")]
    for lo, hi in spans:
        hunk = numbered[lo:hi + 1]
        old_count = sum(1 for ln in hunk if ln.kind != "add")
        new_count = sum(1 for ln in hunk if ln.kind != "del")
        # Where the hunk starts on each side; a side with no lines points at
        # the line before, as diff -u does.
        old_start = next((ln.old_no for ln in hunk if ln.old_no), None)
        new_start = next((ln.new_no for ln in hunk if ln.new_no), None)
        if old_start is None:
            old_start = sum(1 for ln in numbered[:lo] if ln.kind != "add")
        if new_start is None:
            new_start = sum(1 for ln in numbered[:lo] if ln.kind != "del")
        out.append(Line("hunk", f"@@ -{old_start},{old_count} +{new_start},{new_count} @@"))
        out.extend(hunk)
    return out


def word_marks(old: str, new: str) -> tuple[list[tuple[str, bool]], list[tuple[str, bool]]]:
    """Split a -/+ pair into (text, changed) runs for intra-line highlighting."""
    a, b = re.split(r"(\s+)", old), re.split(r"(\s+)", new)
    left: list[tuple[str, bool]] = []
    right: list[tuple[str, bool]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
        same = op == "equal"
        left += [(t, not same and not t.isspace()) for t in a[i1:i2]]
        right += [(t, not same and not t.isspace()) for t in b[j1:j2]]
    return left, right


def pairs(lines: list[Line]) -> dict[int, int]:
    """Index pairs of del/add lines for the same component, for word highlighting.

    A component removed outright, or added outright, has no partner and so
    gets no word marks: the whole line is the change.
    """
    paired: dict[int, int] = {}
    waiting: dict[str, list[int]] = {}
    for i, line in enumerate(lines):
        if line.kind == "del":
            waiting.setdefault(line.key, []).append(i)
        elif line.kind == "add" and waiting.get(line.key):
            paired[waiting[line.key].pop(0)] = i
        elif line.kind in ("hunk", "ctx"):
            waiting.clear()
    return paired
