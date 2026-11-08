"""Self-contained, offline HTML report for a Diff."""

from __future__ import annotations

import base64
import datetime
import re
from html import escape
from importlib import resources

from . import __version__
from .diff import CHANGE_KINDS, Diff
from .render import CHANGE_TITLES, FINDING_TITLES, headline, sbom_label

_FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32">'
    '<rect width="32" height="32" rx="6" fill="#0a0d12"/>'
    '<rect x="4" y="15" width="3.5" height="8" rx="1" fill="#4f8cff"/>'
    '<rect x="9.5" y="11" width="3.5" height="12" rx="1" fill="#8fb4ff"/>'
    '<rect x="15" y="7" width="3.5" height="16" rx="1" fill="#f5c84c"/>'
    '<rect x="20.5" y="11" width="3.5" height="12" rx="1" fill="#ff8a3d"/>'
    '<rect x="26" y="15" width="3.5" height="8" rx="1" fill="#ff4d5e"/>'
    '</svg>'
)

_STAT_SUBS = {
    "added": "New in this SBOM",
    "removed": "No longer present",
    "upgraded": "Moved to a newer version",
    "downgraded": "Moved to an older version",
    "changed": "Version can't be ordered",
}


def _asset(name: str) -> bytes:
    return resources.files("sbomly").joinpath("assets", name).read_bytes()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _fill(template: str, values: dict[str, str]) -> str:
    # One pass, so a placeholder-shaped string inside an SBOM value can never
    # be expanded by a later replacement.
    return re.sub(r"\{\{([A-Z0-9_]+)\}\}", lambda m: values.get(m.group(1), m.group(0)), template)


def _sbom_card(label: str, sbom) -> str:
    rows = [
        ("subject", sbom_label(sbom)),
        ("format", f"{sbom.format} {sbom.spec_version}".strip()),
        ("components", str(len(sbom.components))),
        ("created", sbom.created or "—"),
        ("tool", ", ".join(sbom.tools) or "—"),
        ("file", sbom.source or "—"),
    ]
    items = "".join(f"<dt>{escape(k)}</dt><dd>{escape(v)}</dd>" for k, v in rows)
    return f'<div class="sbom-card"><h2>{escape(label)}</h2><dl>{items}</dl></div>'


def _stat(kind: str, label: str, number: int, sub: str) -> str:
    zero = " zero" if number == 0 else ""
    return (f'<div class="stat-card k-{kind}{zero}"><div class="stat-label">{escape(label)}</div>'
            f'<div class="stat-number">{number}</div><div class="stat-sub">{escape(sub)}</div></div>')


def _findings(d: Diff) -> str:
    if not d.findings:
        return '<div class="empty">Nothing to review: no licence, integrity or supplier changes.</div>'
    cards = []
    for f in d.findings:
        kind = f.kind if f.gating else "info"
        label = FINDING_TITLES[f.kind] + ("" if f.gating else " · info")
        cards.append(
            f'<div class="finding k-{kind}"><span class="badge">{escape(label)}</span>'
            f'<div class="finding-title">{escape(f.name)}<code>{escape(f.version)}</code></div>'
            f'<div class="finding-msg">{escape(f.message)}</div></div>'
        )
    return f'<div class="findings">{"".join(cards)}</div>'


def _version_cell(kind: str, old: str, new: str) -> str:
    if kind == "added":
        return escape(new)
    if kind == "removed":
        return f'<span class="old">{escape(old)}</span>'
    return f'<span class="old">{escape(old)}</span><span class="sep">→</span>{escape(new)}'


def _changes(d: Diff) -> str:
    if not d.changes:
        return '<div class="empty">No components were added, removed or changed version.</div>'
    buttons = ['<button class="filter-btn" type="button" data-kind-filter="" aria-pressed="true">All</button>']
    for kind in CHANGE_KINDS:
        n = d.count(kind)
        if n:
            buttons.append(f'<button class="filter-btn k-{kind}" type="button" data-kind-filter="{kind}" '
                           f'aria-pressed="false">{escape(CHANGE_TITLES[kind])} {n}</button>')
    rows = []
    for c in d.changes:
        search = " ".join((c.name, c.ecosystem, c.old_version, c.new_version, c.license)).lower()
        rows.append(
            f'<tr data-kind="{c.kind}" data-search="{escape(search)}">'
            f'<td><span class="badge k-{c.kind}">{escape(c.kind)}</span></td>'
            f'<td class="pkg">{escape(c.name)}<small>{escape(c.ecosystem or "—")}</small></td>'
            f'<td class="ver">{_version_cell(c.kind, c.old_version, c.new_version)}</td>'
            f'<td class="lic">{escape(c.license or "—")}</td></tr>'
        )
    return (
        '<div class="controls">'
        '<input class="search-input" id="changeSearch" type="search" '
        'placeholder="search package, version or licence…" aria-label="Search changes" />'
        f'{"".join(buttons)}<span class="result-count" id="resultCount"></span></div>'
        '<div class="table-wrap"><table id="changesTable"><thead><tr>'
        '<th>Change</th><th>Package</th><th>Version</th><th>Licence</th>'
        f'</tr></thead><tbody>{"".join(rows)}</tbody></table></div>'
    )


def to_html(d: Diff, theme: str = "dark", title: str = "") -> str:
    template = _asset("report.html").decode("utf-8")
    flagged = sum(1 for f in d.findings if f.gating)

    if flagged:
        badge_class, badge_text = "k-findings", f"{flagged} to review"
    elif d.changes:
        badge_class, badge_text = "k-upgraded", f"{len(d.changes)} changes"
    else:
        badge_class, badge_text = "k-added", "no changes"

    old_label, new_label = sbom_label(d.old), sbom_label(d.new)
    if title:
        hero = escape(title)
    elif d.old.subject and d.old.subject == d.new.subject and d.old.subject_version != d.new.subject_version:
        # Same product, two releases: name it once.
        hero = (f'{escape(d.new.subject)} {escape(d.old.subject_version or "?")}'
                f'<span class="arrow">→</span>{escape(d.new.subject_version or "?")}')
    else:
        hero = f'{escape(old_label)}<span class="arrow">→</span>{escape(new_label)}'

    stats = [_stat(k, CHANGE_TITLES[k], d.count(k), _STAT_SUBS[k]) for k in CHANGE_KINDS]
    stats.append(_stat("findings", "Findings", flagged, "Licence, integrity, supplier"))

    return _fill(template, {
        "THEME_ATTR": ' data-theme="light"' if theme == "light" else "",
        "FAVICON_B64": _b64(_FAVICON_SVG.encode()),
        "FONT_DISPLAY_B64": _b64(_asset("space-grotesk-var.woff2")),
        "FONT_MONO_B64": _b64(_asset("jetbrains-mono-var.woff2")),
        "TITLE": escape(title or f"{old_label} → {new_label}"),
        "BADGE_CLASS": badge_class,
        "BADGE_TEXT": escape(badge_text),
        "HERO_TITLE": hero,
        "HEADLINE": escape(f"{headline(d)} {d.unchanged} components unchanged."),
        "OLD_CARD": _sbom_card("Before", d.old),
        "NEW_CARD": _sbom_card("After", d.new),
        "STAT_CARDS": "".join(stats),
        "FINDINGS": _findings(d),
        "CHANGES": _changes(d),
        "VERSION": escape(__version__),
        "REPORT_DATE": datetime.date.today().strftime("%d %b %Y"),
    })
