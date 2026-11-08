import json
from pathlib import Path

import pytest

from sbomly.model import Component, parse_purl
from sbomly.parse import SbomError, load, loads

FIXTURES = Path(__file__).parent / "fixtures"


def test_cyclonedx_metadata_and_components():
    sbom = load(str(FIXTURES / "cdx-old.json"))
    assert sbom.format == "CycloneDX"
    assert sbom.spec_version == "1.6"
    assert (sbom.subject, sbom.subject_version) == ("payments-api", "2.3.0")
    assert sbom.tools == ["cdxgen 11.1.0"]
    names = sorted(c.display_name for c in sbom.components)
    assert "@acme/logger" in names
    assert "org.apache.commons:commons-text" in names
    # Two versions of debug are kept, not merged.
    assert sum(1 for c in sbom.components if c.name == "debug") == 2


def test_spdx_skips_the_described_root_package():
    sbom = load(str(FIXTURES / "spdx-old.json"))
    assert sbom.format == "SPDX"
    assert sbom.spec_version == "2.3"
    assert sbom.subject == "registry.example.com/payments-api"
    assert sbom.tools == ["syft-1.18.0"]
    assert sorted(c.name for c in sbom.components) == ["curl", "libc6", "openssl", "zlib1g"]


def test_spdx_supplier_prefix_and_email_are_stripped():
    sbom = load(str(FIXTURES / "spdx-old.json"))
    assert {c.supplier for c in sbom.components} == {"Debian Maintainers"}


def test_spdx_noassertion_licence_is_empty():
    sbom = load(str(FIXTURES / "spdx-new.json"))
    tzdata = next(c for c in sbom.components if c.name == "tzdata")
    assert tzdata.license == ""


def test_cyclonedx_14_tool_list_and_nested_components():
    doc = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.4",
        "metadata": {"tools": [{"vendor": "x", "name": "syft", "version": "0.90"}]},
        "components": [
            {"name": "outer", "version": "1", "components": [{"name": "inner", "version": "2"}]}
        ],
    }
    sbom = loads(json.dumps(doc))
    assert sbom.tools == ["syft 0.90"]
    assert sorted(c.name for c in sbom.components) == ["inner", "outer"]


def test_duplicate_components_are_merged():
    doc = {
        "bomFormat": "CycloneDX",
        "components": [
            {"name": "a", "version": "1", "purl": "pkg:npm/a@1"},
            {"name": "a", "version": "1", "purl": "pkg:npm/a@1",
             "licenses": [{"license": {"id": "MIT"}}]},
        ],
    }
    sbom = loads(json.dumps(doc))
    assert len(sbom.components) == 1
    assert sbom.components[0].license == "MIT"


def test_licence_lists_compare_regardless_of_order():
    def lic(*ids):
        doc = {"bomFormat": "CycloneDX", "components": [
            {"name": "a", "licenses": [{"license": {"id": i}} for i in ids]}]}
        return loads(json.dumps(doc)).components[0].license
    assert lic("MIT", "ISC") == lic("ISC", "MIT")


@pytest.mark.parametrize("text, message", [
    ("<bom/>", "XML"),
    ("SPDXVersion: SPDX-2.3\n", "tag-value"),
    ("{not json", "not valid JSON"),
    ("[]", "JSON object"),
    ('{"hello": 1}', "not a CycloneDX or SPDX"),
    ('{"@context": "https://spdx.org/rdf/3.0.0/spdx-context.jsonld"}', "SPDX 3.0"),
])
def test_unsupported_inputs_explain_themselves(text, message):
    with pytest.raises(SbomError, match=message):
        loads(text)


def test_missing_file():
    with pytest.raises(SbomError, match="file not found"):
        load("does/not/exist.json")


def test_parse_purl_scoped_npm_and_qualifiers():
    p = parse_purl("pkg:npm/%40acme/logger@1.2.0?foo=bar#sub")
    assert (p.type, p.namespace, p.name, p.version) == ("npm", "@acme", "logger", "1.2.0")
    assert p.qualifiers == {"foo": "bar"}
    assert parse_purl("not-a-purl") is None


def test_key_ignores_version_and_distro_but_keeps_arch():
    a = Component("openssl", purl="pkg:deb/debian/openssl@3.0.1?arch=amd64&distro=debian-12.1")
    b = Component("openssl", purl="pkg:deb/debian/openssl@3.0.2?distro=debian-12.5&arch=amd64")
    c = Component("openssl", purl="pkg:deb/debian/openssl@3.0.2?arch=arm64")
    assert a.key == b.key
    assert a.key != c.key


def test_pypi_names_normalise():
    a = Component("Foo_Bar", purl="pkg:pypi/Foo_Bar@1.0")
    b = Component("foo-bar", purl="pkg:pypi/foo.bar@1.1")
    assert a.key == b.key
