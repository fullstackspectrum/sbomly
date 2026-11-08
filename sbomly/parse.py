"""Load CycloneDX and SPDX JSON documents into the shared model."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from .model import Component, Sbom, parse_purl


class SbomError(Exception):
    """An input that can't be read as a supported SBOM. The message is shown to the user."""


# Package types whose purl namespace is part of the name people know the
# package by. For OS packages (deb, rpm, apk) the namespace is the distro,
# which would only add noise to the display name.
_NAMESPACED_TYPES = {"maven", "npm", "golang", "composer", "github", "swift"}

_SPDX_EMPTY = {"", "NOASSERTION", "NONE"}


def load(source: str) -> Sbom:
    """Read an SBOM from a path, or from stdin when source is '-'."""
    if source == "-":
        text = sys.stdin.read()
    else:
        path = Path(source)
        if not path.is_file():
            raise SbomError(f"{source}: file not found")
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            raise SbomError(f"{source}: not a text file") from None
    sbom = loads(text, source)
    sbom.source = "stdin" if source == "-" else source
    return sbom


def loads(text: str, source: str = "input") -> Sbom:
    stripped = text.lstrip()
    if stripped.startswith("<"):
        raise SbomError(f"{source}: XML SBOMs aren't supported yet; export CycloneDX as JSON")
    if stripped.startswith("SPDXVersion:"):
        raise SbomError(f"{source}: SPDX tag-value isn't supported yet; export SPDX as JSON")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise SbomError(f"{source}: not valid JSON ({exc.msg}, line {exc.lineno})") from None
    if not isinstance(data, dict):
        raise SbomError(f"{source}: expected a JSON object at the top level")
    if data.get("bomFormat") == "CycloneDX":
        return parse_cyclonedx(data)
    if str(data.get("spdxVersion", "")).startswith("SPDX-"):
        return parse_spdx(data)
    if "@context" in data and "spdx" in json.dumps(data.get("@context")).lower():
        raise SbomError(f"{source}: SPDX 3.0 isn't supported yet; export SPDX 2.3 JSON")
    raise SbomError(f"{source}: not a CycloneDX or SPDX JSON document")


# ── Shared helpers ────────────────────────────────────────────────────


def _str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _list(value: Any) -> list:
    return value if isinstance(value, list) else []


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def normalise_alg(alg: str) -> str:
    """'SHA-256', 'sha256' and 'SHA_256' all name the same algorithm."""
    return re.sub(r"[-_\s]", "", alg).upper()


def _clean_party(value: str) -> str:
    """Strip SPDX's 'Organization: ' prefix and any trailing '(email)'."""
    value = re.sub(r"^(Organization|Person|Tool):\s*", "", value.strip())
    value = re.sub(r"\s*\([^)]*\)\s*$", "", value)
    return "" if value.upper() in _SPDX_EMPTY else value


def _apply_purl(component: Component) -> None:
    parsed = parse_purl(component.purl)
    if not parsed:
        return
    component.ecosystem = component.ecosystem or parsed.type
    if not component.group and parsed.type in _NAMESPACED_TYPES:
        component.group = parsed.namespace
    if not component.version:
        component.version = parsed.version


def _dedupe(components: list[Component]) -> list[Component]:
    """Merge components that share a key and version.

    Scanners often list one library several times, once per path it was found
    at. For the diff those are the same thing.
    """
    seen: dict[tuple[str, str], Component] = {}
    for comp in components:
        ident = (comp.key, comp.version)
        kept = seen.get(ident)
        if kept is None:
            seen[ident] = comp
            continue
        kept.license = kept.license or comp.license
        kept.supplier = kept.supplier or comp.supplier
        for alg, digest in comp.hashes.items():
            kept.hashes.setdefault(alg, digest)
    return list(seen.values())


# ── CycloneDX ─────────────────────────────────────────────────────────


def _cdx_license(entries: list) -> str:
    parts = []
    for entry in entries:
        entry = _dict(entry)
        if _str(entry.get("expression")):
            parts.append(_str(entry["expression"]))
            continue
        lic = _dict(entry.get("license"))
        value = _str(lic.get("id")) or _str(lic.get("name"))
        if value:
            parts.append(value)
    # A list of licences has no operator; keep a stable order so the same
    # set compares equal across two documents.
    return " AND ".join(sorted(set(parts)))


def _cdx_supplier(raw: dict) -> str:
    for key in ("supplier", "manufacturer"):
        name = _str(_dict(raw.get(key)).get("name"))
        if name:
            return name
    if _str(raw.get("publisher")):
        return _str(raw["publisher"])
    for author in _list(raw.get("authors")):
        name = _str(_dict(author).get("name"))
        if name:
            return name
    return _str(raw.get("author"))


def _cdx_component(raw: dict) -> Component | None:
    name = _str(raw.get("name"))
    if not name:
        return None
    comp = Component(
        name=name,
        version=_str(raw.get("version")),
        group=_str(raw.get("group")),
        purl=_str(raw.get("purl")),
        license=_cdx_license(_list(raw.get("licenses"))),
        supplier=_cdx_supplier(raw),
        ref=_str(raw.get("bom-ref")),
    )
    for h in _list(raw.get("hashes")):
        h = _dict(h)
        alg, content = _str(h.get("alg")), _str(h.get("content"))
        if alg and content:
            comp.hashes[normalise_alg(alg)] = content.lower()
    _apply_purl(comp)
    return comp


def _cdx_walk(items: list, out: list[Component]) -> None:
    for raw in items:
        raw = _dict(raw)
        comp = _cdx_component(raw)
        if comp:
            out.append(comp)
        _cdx_walk(_list(raw.get("components")), out)


def _cdx_tools(metadata: dict) -> list[str]:
    tools = metadata.get("tools")
    # 1.4 and earlier: a list of tools. 1.5+: {components: [...], services: [...]}.
    entries = _list(tools) or _list(_dict(tools).get("components")) + _list(_dict(tools).get("services"))
    names = []
    for tool in entries:
        tool = _dict(tool)
        label = " ".join(p for p in (_str(tool.get("name")), _str(tool.get("version"))) if p)
        if label:
            names.append(label)
    return names


def parse_cyclonedx(data: dict) -> Sbom:
    metadata = _dict(data.get("metadata"))
    subject = _dict(metadata.get("component"))
    components: list[Component] = []
    _cdx_walk(_list(data.get("components")), components)
    return Sbom(
        format="CycloneDX",
        spec_version=_str(data.get("specVersion")),
        subject=_str(subject.get("name")),
        subject_version=_str(subject.get("version")),
        created=_str(metadata.get("timestamp")),
        tools=_cdx_tools(metadata),
        components=_dedupe(components),
    )


# ── SPDX 2.x ──────────────────────────────────────────────────────────


def _spdx_license(raw: dict) -> str:
    for key in ("licenseConcluded", "licenseDeclared"):
        value = _str(raw.get(key))
        if value.upper() not in _SPDX_EMPTY:
            return value
    return ""


def _spdx_package(raw: dict) -> Component | None:
    name = _str(raw.get("name"))
    if not name:
        return None
    purl = ""
    for ref in _list(raw.get("externalRefs")):
        ref = _dict(ref)
        if _str(ref.get("referenceType")).lower() == "purl":
            purl = _str(ref.get("referenceLocator"))
            break
    comp = Component(
        name=name,
        version=_str(raw.get("versionInfo")),
        purl=purl,
        license=_spdx_license(raw),
        supplier=_clean_party(_str(raw.get("supplier"))) or _clean_party(_str(raw.get("originator"))),
        ref=_str(raw.get("SPDXID")),
    )
    for c in _list(raw.get("checksums")):
        c = _dict(c)
        alg, value = _str(c.get("algorithm")), _str(c.get("checksumValue"))
        if alg and value:
            comp.hashes[normalise_alg(alg)] = value.lower()
    _apply_purl(comp)
    return comp


def _spdx_roots(data: dict) -> set[str]:
    """IDs of the packages the document describes: the subject, not a dependency."""
    doc_id = _str(data.get("SPDXID")) or "SPDXRef-DOCUMENT"
    roots = {r for r in _list(data.get("documentDescribes")) if isinstance(r, str)}
    for rel in _list(data.get("relationships")):
        rel = _dict(rel)
        kind = _str(rel.get("relationshipType"))
        if kind == "DESCRIBES" and _str(rel.get("spdxElementId")) == doc_id:
            roots.add(_str(rel.get("relatedSpdxElement")))
        elif kind == "DESCRIBED_BY" and _str(rel.get("relatedSpdxElement")) == doc_id:
            roots.add(_str(rel.get("spdxElementId")))
    return roots


def parse_spdx(data: dict) -> Sbom:
    creation = _dict(data.get("creationInfo"))
    roots = _spdx_roots(data)
    subject, subject_version = "", ""
    components: list[Component] = []
    for raw in _list(data.get("packages")):
        raw = _dict(raw)
        if _str(raw.get("SPDXID")) in roots:
            if not subject:
                subject = _str(raw.get("name"))
                subject_version = _str(raw.get("versionInfo"))
            continue
        comp = _spdx_package(raw)
        if comp:
            components.append(comp)
    tools = [
        _str(c)[len("Tool:"):].strip()
        for c in _list(creation.get("creators"))
        if _str(c).startswith("Tool:")
    ]
    return Sbom(
        format="SPDX",
        spec_version=_str(data.get("spdxVersion")).removeprefix("SPDX-"),
        subject=subject or _str(data.get("name")),
        subject_version=subject_version,
        created=_str(creation.get("created")),
        tools=tools,
        components=_dedupe(components),
    )
