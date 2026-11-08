"""Format-neutral SBOM model shared by the parsers, the diff engine and the renderers."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import unquote

# Qualifiers that identify a different artifact rather than a different build
# of the same one. Everything else (distro, repository_url, ...) is dropped
# from the match key, otherwise a base-image bump that changes `distro=` would
# report every OS package as removed and re-added.
_IDENTITY_QUALIFIERS = ("arch", "classifier", "type")


@dataclass(frozen=True)
class Purl:
    type: str
    namespace: str
    name: str
    version: str
    qualifiers: dict[str, str]


def parse_purl(value: str) -> Purl | None:
    """Parse a package URL. Returns None for anything that isn't a pkg: URL."""
    if not value or not value.startswith("pkg:"):
        return None
    rest = value[4:].lstrip("/")
    rest, _, _subpath = rest.partition("#")
    rest, _, query = rest.partition("?")
    qualifiers: dict[str, str] = {}
    for pair in query.split("&") if query else ():
        key, _, val = pair.partition("=")
        if key:
            qualifiers[key.lower()] = unquote(val)
    version = ""
    # The version separator is the last '@' after the final '/', so scoped
    # npm names (pkg:npm/%40scope/name or the unencoded @scope) survive.
    head, slash, tail = rest.rpartition("/")
    if "@" in tail:
        tail, _, version = tail.rpartition("@")
        version = unquote(version)
    rest = f"{head}{slash}{tail}"
    ptype, _, path = rest.partition("/")
    if not ptype or not path:
        return None
    namespace, _, name = path.rpartition("/")
    return Purl(
        type=ptype.lower(),
        namespace=unquote(namespace),
        name=unquote(name),
        version=version,
        qualifiers=qualifiers,
    )


def _normalise_name(ptype: str, name: str) -> str:
    name = name.lower()
    if ptype == "pypi":
        # PEP 503: runs of -, _ and . are equivalent.
        name = re.sub(r"[-_.]+", "-", name)
    return name


@dataclass
class Component:
    name: str
    version: str = ""
    group: str = ""
    purl: str = ""
    ecosystem: str = ""
    license: str = ""
    hashes: dict[str, str] = field(default_factory=dict)
    supplier: str = ""
    ref: str = ""

    @property
    def key(self) -> str:
        """Identity used to pair a component across two SBOMs, ignoring version."""
        parsed = parse_purl(self.purl)
        if parsed:
            parts = [parsed.type]
            if parsed.namespace:
                parts.append(parsed.namespace.lower())
            parts.append(_normalise_name(parsed.type, parsed.name))
            key = "pkg:" + "/".join(parts)
            kept = sorted(
                (k, v) for k, v in parsed.qualifiers.items() if k in _IDENTITY_QUALIFIERS
            )
            if kept:
                key += "?" + "&".join(f"{k}={v}" for k, v in kept)
            return key
        parts = [p for p in (self.ecosystem, self.group) if p]
        parts.append(_normalise_name(self.ecosystem, self.name))
        return "name:" + "/".join(p.lower() for p in parts)

    @property
    def distro(self) -> str:
        """The purl's distro qualifier, e.g. 'debian-12.5' or '3.20.10'."""
        parsed = parse_purl(self.purl)
        return parsed.qualifiers.get("distro", "") if parsed else ""

    @property
    def display_name(self) -> str:
        if self.group:
            sep = ":" if self.ecosystem == "maven" else "/"
            return f"{self.group}{sep}{self.name}"
        return self.name


@dataclass
class Sbom:
    format: str  # "CycloneDX" or "SPDX"
    spec_version: str = ""
    subject: str = ""
    subject_version: str = ""
    created: str = ""
    tools: list[str] = field(default_factory=list)
    source: str = ""  # the path it was loaded from
    components: list[Component] = field(default_factory=list)
