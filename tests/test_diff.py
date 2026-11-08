from pathlib import Path

import pytest

from sbomly import licenses
from sbomly.diff import compare_versions, diff
from sbomly.model import Component, Sbom
from sbomly.parse import load

FIXTURES = Path(__file__).parent / "fixtures"


def sbom(*components):
    return Sbom(format="CycloneDX", components=list(components))


def npm(name, version, **kw):
    return Component(name, version, purl=f"pkg:npm/{name}@{version}", ecosystem="npm", **kw)


@pytest.fixture(scope="module")
def cdx():
    return diff(load(str(FIXTURES / "cdx-old.json")), load(str(FIXTURES / "cdx-new.json")))


def test_fixture_counts(cdx):
    assert {k: cdx.count(k) for k in ("added", "removed", "upgraded", "downgraded", "changed")} == {
        "added": 2, "removed": 1, "upgraded": 3, "downgraded": 1, "changed": 0,
    }
    assert cdx.unchanged == 4


def test_fixture_findings(cdx):
    found = {(f.kind, f.name) for f in cdx.findings}
    assert found == {
        ("hash", "axios"),
        ("copyleft", "readline-sync"),
        ("copyleft", "sharp"),
        ("license", "sharp"),
        ("supplier", "@acme/logger"),
    }
    # Most alarming first.
    assert cdx.findings[0].kind == "hash"


def test_multiple_versions_pair_in_order(cdx):
    debug = [c for c in cdx.changes if c.name == "debug"]
    assert [(c.kind, c.old_version, c.new_version) for c in debug] == [("upgraded", "4.3.4", "4.3.5")]


def test_spdx_distro_change_does_not_churn():
    d = diff(load(str(FIXTURES / "spdx-old.json")), load(str(FIXTURES / "spdx-new.json")))
    assert d.count("removed") == 0
    assert [c.name for c in d.changes if c.kind == "added"] == ["tzdata"]
    assert d.count("upgraded") == 2


def test_identical_sboms_have_no_changes():
    s = load(str(FIXTURES / "cdx-new.json"))
    d = diff(s, s)
    assert not d.has_changes
    assert d.unchanged == len(s.components)


def test_unknown_to_known_licence_is_info_only():
    d = diff(sbom(npm("a", "1")), sbom(npm("a", "1", license="MIT")))
    assert [(f.kind, f.gating) for f in d.findings] == [("license", False)]
    assert d.triggered({"license"}) == {}


def test_known_to_unknown_licence_gates():
    d = diff(sbom(npm("a", "1", license="MIT")), sbom(npm("a", "1")))
    assert d.triggered({"license"}) == {"license": 1}


def test_licence_case_and_spacing_are_not_a_change():
    d = diff(sbom(npm("a", "1", license="Apache-2.0")), sbom(npm("a", "1", license=" apache-2.0 ")))
    assert d.findings == []


def test_hash_change_only_counts_for_same_version():
    d = diff(sbom(npm("a", "1", hashes={"SHA256": "aa"})), sbom(npm("a", "2", hashes={"SHA256": "bb"})))
    assert d.count("hash") == 0


def test_hash_compares_only_shared_algorithms():
    d = diff(sbom(npm("a", "1", hashes={"SHA1": "aa"})), sbom(npm("a", "1", hashes={"SHA256": "bb"})))
    assert d.count("hash") == 0


def test_unorderable_versions_are_changed():
    d = diff(sbom(npm("a", "3f2a9c1")), sbom(npm("a", "9b8e7d6")))
    assert d.changes[0].kind == "changed"


def test_triggered_any_and_specific(cdx):
    assert cdx.triggered(set()) == {}
    assert cdx.triggered({"hash"}) == {"hash": 1}
    assert set(cdx.triggered({"any"})) == {"added", "removed", "upgraded", "downgraded",
                                           "hash", "copyleft", "license", "supplier"}


@pytest.mark.parametrize("a, b, expected", [
    ("1.0.0", "1.0.1", -1),
    ("1.10.0", "1.9", 1),
    ("v2.0.0", "2.0.0", 0),
    ("1.0.0rc1", "1.0.0", -1),
    ("1.0.0-beta.2", "1.0.0-beta.10", -1),
    ("1.0", "1.0.1", -1),
    ("1:1.0", "2.0", 1),
    ("7.88.1-10+deb12u4", "7.88.1-10+deb12u5", -1),
    ("3.0.11-1~deb12u1", "3.0.11-1~deb12u2", -1),
    ("abcdef1", "1234567", None),
    ("", "1.0", None),
])
def test_compare_versions(a, b, expected):
    assert compare_versions(a, b) == expected


@pytest.mark.parametrize("expression, level", [
    ("MIT", licenses.NONE),
    ("", licenses.NONE),
    ("GPL-3.0-only", licenses.STRONG),
    ("LGPL-2.1-or-later", licenses.WEAK),
    ("AGPL-3.0-or-later", licenses.NETWORK),
    ("MIT OR GPL-3.0-only", licenses.NONE),
    ("MIT AND GPL-3.0-only", licenses.STRONG),
    ("(MIT OR Apache-2.0) AND MPL-2.0", licenses.WEAK),
    ("MIT OR (GPL-3.0-only AND Apache-2.0)", licenses.NONE),
    ("(MIT AND GPL-3.0-only) OR LGPL-2.1-only", licenses.WEAK),
    ("MIT AND", licenses.NONE),
    ("GPL-2.0-only WITH Classpath-exception-2.0", licenses.WEAK),
    ("GNU General Public License v3", licenses.STRONG),
    ("GNU Lesser General Public License", licenses.WEAK),
])
def test_copyleft_level(expression, level):
    assert licenses.copyleft_level(expression) == level


def test_licence_term_order_is_not_a_change():
    d = diff(sbom(npm("a", "1", license="MPL-2.0 AND MIT")), sbom(npm("a", "1", license="MIT AND MPL-2.0")))
    assert d.findings == []


def apk(name, version, distro, **kw):
    return Component(name, version, ecosystem="apk",
                     purl=f"pkg:apk/alpine/{name}@{version}?arch=x86_64&distro={distro}", **kw)


def test_distro_rebuild_hash_change_is_info():
    d = diff(sbom(apk("scanelf", "1.3.7-r2", "3.19.9", hashes={"SHA1": "aa"})),
             sbom(apk("scanelf", "1.3.7-r2", "3.20.10", hashes={"SHA1": "bb"})))
    assert [(f.kind, f.gating) for f in d.findings] == [("hash", False)]
    assert "rebuilt for distro 3.20.10" in d.findings[0].message


def test_same_distro_hash_change_still_gates():
    d = diff(sbom(apk("scanelf", "1.3.7-r2", "3.20.10", hashes={"SHA1": "aa"})),
             sbom(apk("scanelf", "1.3.7-r2", "3.20.10", hashes={"SHA1": "bb"})))
    assert d.triggered({"hash"}) == {"hash": 1}


def test_os_package_maintainer_change_is_info_but_npm_gates():
    os_diff = diff(sbom(apk("musl", "1.2.4", "3.19", supplier="Timo")),
                   sbom(apk("musl", "1.2.5", "3.20", supplier="Natanael")))
    assert os_diff.triggered({"supplier"}) == {}
    npm_diff = diff(sbom(npm("a", "1", supplier="Alice")), sbom(npm("a", "2", supplier="Mallory")))
    assert npm_diff.triggered({"supplier"}) == {"supplier": 1}
