"""Compare two SBOMs: what moved, and what about it deserves a reviewer's attention."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from . import licenses
from .model import Component, Sbom

CHANGE_KINDS = ("added", "removed", "upgraded", "downgraded", "changed")
# Most alarming first: a replaced artifact outranks a licence edit.
FINDING_KINDS = ("hash", "copyleft", "license", "supplier")
FAIL_ON_CHOICES = CHANGE_KINDS + FINDING_KINDS + ("any",)


@dataclass
class Change:
    kind: str
    name: str
    ecosystem: str
    key: str
    old_version: str = ""
    new_version: str = ""
    license: str = ""


@dataclass
class Finding:
    kind: str
    name: str
    ecosystem: str
    version: str
    message: str
    old: str = ""
    new: str = ""
    # Informational findings (a licence that was unknown and is now declared)
    # are reported but never fail a build.
    gating: bool = True


@dataclass
class Diff:
    old: Sbom
    new: Sbom
    changes: list[Change] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)
    unchanged: int = 0

    def count(self, kind: str) -> int:
        if kind in CHANGE_KINDS:
            return sum(1 for c in self.changes if c.kind == kind)
        return sum(1 for f in self.findings if f.kind == kind)

    @property
    def has_changes(self) -> bool:
        return bool(self.changes or self.findings)

    def triggered(self, fail_on: set[str]) -> dict[str, int]:
        """Categories in fail_on that this diff hits, with their counts."""
        kinds = set(CHANGE_KINDS + FINDING_KINDS) if "any" in fail_on else fail_on
        hits: dict[str, int] = {}
        for kind in CHANGE_KINDS + FINDING_KINDS:
            if kind not in kinds:
                continue
            if kind in CHANGE_KINDS:
                n = self.count(kind)
            else:
                n = sum(1 for f in self.findings if f.kind == kind and f.gating)
            if n:
                hits[kind] = n
        return hits


# ── Versions ──────────────────────────────────────────────────────────

_TOKEN = re.compile(r"\d+|[a-zA-Z]+")
_OPAQUE = re.compile(r"^[0-9a-f]{7,64}$", re.I)


def _tokens(version: str) -> tuple[int, list[int | str]]:
    version = version.strip().removeprefix("v").removeprefix("V")
    epoch = 0
    # Debian and RPM epochs: 1:2.3 sorts after 9.9.
    match = re.match(r"^(\d+):(.+)$", version)
    if match:
        epoch, version = int(match.group(1)), match.group(2)
    return epoch, [int(t) if t.isdigit() else t.lower() for t in _TOKEN.findall(version)]


def compare_versions(a: str, b: str) -> int | None:
    """-1, 0 or 1 like cmp(); None when the versions can't be ordered (digests, commit SHAs)."""
    if a == b:
        return 0
    if not a or not b or _OPAQUE.match(a) or _OPAQUE.match(b):
        return None
    epoch_a, ta = _tokens(a)
    epoch_b, tb = _tokens(b)
    if epoch_a != epoch_b:
        return -1 if epoch_a < epoch_b else 1
    if not ta or not tb:
        return None
    for x, y in zip(ta, tb):
        if x == y:
            continue
        if isinstance(x, int) and isinstance(y, int):
            return -1 if x < y else 1
        if isinstance(x, str) and isinstance(y, str):
            return -1 if x < y else 1
        # A number beats a word in the same slot: 1.0.1 > 1.0.beta.
        return 1 if isinstance(x, int) else -1
    if len(ta) == len(tb):
        return 0
    # One is a prefix of the other. A trailing word marks a pre-release
    # (1.0.0rc1 < 1.0.0); a trailing number is a later release (1.0 < 1.0.1).
    longer, sign = (ta, 1) if len(ta) > len(tb) else (tb, -1)
    nxt = longer[min(len(ta), len(tb))]
    return -sign if isinstance(nxt, str) else sign


# ── Diff ──────────────────────────────────────────────────────────────


def _index(sbom: Sbom) -> dict[str, dict[str, Component]]:
    index: dict[str, dict[str, Component]] = {}
    for comp in sbom.components:
        index.setdefault(comp.key, {})[comp.version] = comp
    return index


# For distro packages the "supplier" is the package maintainer, which
# rotates routinely. For language ecosystems a new supplier is exactly the
# account-takeover signal worth stopping for.
_OS_ECOSYSTEMS = {"apk", "deb", "rpm", "alpm", "ebuild", "opkg"}


def _norm(value: str) -> str:
    return " ".join(value.split()).casefold()


def _version_label(old: Component, new: Component) -> str:
    return new.version if old.version == new.version else f"{old.version} → {new.version}"


def _compare(old: Component, new: Component, findings: list[Finding]) -> None:
    """Record licence, copyleft, integrity and supplier findings for one pair."""
    name, eco, version = new.display_name, new.ecosystem, _version_label(old, new)

    if licenses.normalise(old.license) != licenses.normalise(new.license):
        if old.license and new.license:
            findings.append(Finding("license", name, eco, version,
                                    f"Licence changed from {old.license} to {new.license}",
                                    old.license, new.license))
        elif old.license:
            findings.append(Finding("license", name, eco, version,
                                    f"Licence no longer declared (was {old.license})",
                                    old.license, ""))
        else:
            findings.append(Finding("license", name, eco, version,
                                    f"Licence now declared as {new.license}",
                                    "", new.license, gating=False))
        before, after = licenses.copyleft_level(old.license), licenses.copyleft_level(new.license)
        if after > before:
            findings.append(Finding("copyleft", name, eco, version,
                                    f"Now {licenses.LABELS[after]} ({new.license})",
                                    old.license, new.license))

    if old.version == new.version:
        for alg in sorted(old.hashes.keys() & new.hashes.keys()):
            if old.hashes[alg] != new.hashes[alg]:
                if old.distro and new.distro and old.distro != new.distro:
                    # Distros rebuild unchanged versions for each release.
                    findings.append(Finding("hash", name, eco, version,
                                            f"Same version, different {alg} digest: rebuilt for "
                                            f"distro {new.distro} (was {old.distro})",
                                            old.hashes[alg], new.hashes[alg], gating=False))
                else:
                    findings.append(Finding("hash", name, eco, version,
                                            f"Same version, different {alg} digest: "
                                            "the artifact was rebuilt or replaced",
                                            old.hashes[alg], new.hashes[alg]))
                break

    if old.supplier and new.supplier and _norm(old.supplier) != _norm(new.supplier):
        findings.append(Finding("supplier", name, eco, version,
                                f"Supplier changed from {old.supplier} to {new.supplier}",
                                old.supplier, new.supplier,
                                gating=eco not in _OS_ECOSYSTEMS))


def _version_sort(versions: set[str]) -> list[str]:
    def key(v: str) -> tuple:
        epoch, tokens = _tokens(v)
        # Mixed int/str tokens don't compare in Python; tag each token so
        # sorting is total. Only used to pair versions up, not for display.
        return (epoch, [(0, t, "") if isinstance(t, int) else (1, 0, t) for t in tokens], v)
    return sorted(versions, key=key)


def diff(old: Sbom, new: Sbom) -> Diff:
    result = Diff(old=old, new=new)
    old_index, new_index = _index(old), _index(new)

    for key in old_index.keys() | new_index.keys():
        before, after = old_index.get(key, {}), new_index.get(key, {})
        common = before.keys() & after.keys()
        result.unchanged += len(common)
        for version in common:
            _compare(before[version], after[version], result.findings)

        # Several versions of one package can coexist (npm does this a lot).
        # Pair the leftovers in version order: 1.0 → 1.1 and 2.0 → 2.1, not
        # 1.0 → 2.1. Anything unpaired was genuinely added or removed.
        gone = _version_sort(set(before) - common)
        arrived = _version_sort(set(after) - common)
        for old_v, new_v in zip(gone, arrived):
            o, n = before[old_v], after[new_v]
            order = compare_versions(old_v, new_v)
            kind = {-1: "upgraded", 1: "downgraded"}.get(order, "changed")
            result.changes.append(Change(kind, n.display_name, n.ecosystem, key,
                                         old_v, new_v, n.license))
            _compare(o, n, result.findings)
        for old_v in gone[len(arrived):]:
            o = before[old_v]
            result.changes.append(Change("removed", o.display_name, o.ecosystem, key,
                                         old_version=old_v, license=o.license))
        for new_v in arrived[len(gone):]:
            n = after[new_v]
            result.changes.append(Change("added", n.display_name, n.ecosystem, key,
                                         new_version=new_v, license=n.license))
            level = licenses.copyleft_level(n.license)
            if level >= licenses.WEAK:
                result.findings.append(Finding("copyleft", n.display_name, n.ecosystem, new_v,
                                               f"New dependency under {licenses.LABELS[level]} "
                                               f"licence ({n.license})",
                                               "", n.license))

    result.changes.sort(key=lambda c: (CHANGE_KINDS.index(c.kind), c.name.lower(), c.new_version or c.old_version))
    result.findings.sort(key=lambda f: (FINDING_KINDS.index(f.kind), not f.gating, f.name.lower(), f.version))
    return result
