import re
import shutil
import subprocess
from pathlib import Path

import pytest

from sbomly import udiff
from sbomly.cli import main
from sbomly.diff import diff
from sbomly.html import to_html
from sbomly.model import Component, Sbom
from sbomly.parse import load
from sbomly.render import to_markdown, to_unified_text

FIXTURES = Path(__file__).parent / "fixtures"
OLD, NEW = str(FIXTURES / "cdx-old.json"), str(FIXTURES / "cdx-new.json")


@pytest.fixture(scope="module")
def cdx():
    return diff(load(OLD), load(NEW))


def sides(d):
    """The full old and new listings, as the diff sees them."""
    entries = udiff._entries(d)
    old = [t for k, t, _ in entries if k != "add"]
    new = [t for k, t, _ in entries if k != "del"]
    return old, new


def apply(old, lines):
    """Apply unified-diff hunks to the old listing, as patch would."""
    result, pos = [], 0
    for line in lines:
        if line.kind == "hunk":
            start = int(re.match(r"@@ -(\d+)", line.text).group(1))
            # A hunk with no old lines names the line before it.
            count = int(re.match(r"@@ -\d+,(\d+)", line.text).group(1))
            start = start if count else start + 1
            result += old[pos:start - 1]
            pos = start - 1
        elif line.kind == "ctx":
            assert old[pos] == line.text
            result.append(line.text)
            pos += 1
        elif line.kind == "del":
            assert old[pos] == line.text
            pos += 1
        elif line.kind == "add":
            result.append(line.text)
    return result + old[pos:]


@pytest.mark.parametrize("context", [0, 1, 3, 50])
def test_hunks_reconstruct_the_new_listing(cdx, context):
    old, new = sides(cdx)
    assert apply(old, udiff.unified(cdx, context)) == new


@pytest.mark.parametrize("context", [0, 2])
def test_spdx_hunks_reconstruct(context):
    d = diff(load(str(FIXTURES / "spdx-old.json")), load(str(FIXTURES / "spdx-new.json")))
    old, new = sides(d)
    assert apply(old, udiff.unified(d, context)) == new


@pytest.mark.skipif(not shutil.which("patch"), reason="needs patch(1)")
def test_gnu_patch_accepts_the_diff(cdx, tmp_path):
    old, new = sides(cdx)
    (tmp_path / "list").write_text("\n".join(old) + "\n")
    text = to_unified_text(cdx, context=2)
    subprocess.run(["patch", "-s", str(tmp_path / "list")], input=text, text=True, check=True)
    assert (tmp_path / "list").read_text() == "\n".join(new) + "\n"


def test_removal_sits_above_its_replacement(cdx):
    texts = [(ln.kind, ln.text.split()[1]) for ln in udiff.unified(cdx, 0) if ln.kind in ("add", "del")]
    i = texts.index(("del", "express"))
    assert texts[i + 1] == ("add", "express")


def test_hash_and_supplier_only_shown_when_changed(cdx):
    text = "\n".join(ln.text for ln in udiff.unified(cdx, 50))
    assert "sha256:aaaaaaaaaaaa" in text and "sha256:bbbbbbbbbbbb" in text
    assert "by Acme Inc" in text
    # express has no hash or supplier change, so no extras.
    express = [ln.text for ln in udiff.unified(cdx, 50) if " express " in ln.text]
    assert all("sha256" not in t and " by " not in t for t in express)


def test_equivalent_licences_are_context_not_change():
    a = Sbom("CycloneDX", source="a", components=[Component("x", "1", license="MPL-2.0 AND MIT", purl="pkg:npm/x@1")])
    b = Sbom("CycloneDX", source="b", components=[Component("x", "1", license="MIT AND MPL-2.0", purl="pkg:npm/x@1")])
    assert udiff.unified(diff(a, b)) == []


def test_pairs_only_match_the_same_component(cdx):
    lines = udiff.unified(cdx, 1)
    for i, j in udiff.pairs(lines).items():
        assert lines[i].key == lines[j].key
    unpaired = {lines[i].text.split()[1] for i, ln in enumerate(lines)
                if ln.kind in ("add", "del") and i not in udiff.pairs(lines)
                and i not in udiff.pairs(lines).values()}
    assert unpaired == {"chalk", "left-pad", "readline-sync"}


def test_word_marks_flag_only_the_changed_tokens():
    left, right = udiff.word_marks("debug  4.3.4  MIT", "debug  4.3.5  MIT")
    assert [t for t, changed in left if changed] == ["4.3.4"]
    assert [t for t, changed in right if changed] == ["4.3.5"]


def test_no_changes_prints_message():
    s = load(NEW)
    assert to_unified_text(diff(s, s)) == "No dependency changes.\n"


def test_terminal_colours(cdx):
    out = to_unified_text(cdx, colour=True)
    assert "\033[31m-" in out and "\033[34m+" in out


def test_markdown_diff_block(cdx):
    md = to_markdown(cdx, context=1)
    assert "```diff" in md
    assert "\n-npm       express" in md
    assert "```diff" not in to_markdown(cdx)


def test_markdown_diff_fence_cannot_be_broken():
    a = Sbom("CycloneDX", components=[])
    b = Sbom("CycloneDX", components=[Component("evil```\n# hi", "1")])
    md = to_markdown(diff(a, b), context=0)
    block = md.split("```diff", 1)[1]
    assert block.count("```") == 1  # only the closing fence


def test_html_has_both_views_and_escapes(cdx):
    page = to_html(cdx, context=1)
    assert 'id="viewTable"' in page and 'id="viewDiff" hidden' in page
    assert "<mark>4.3.5</mark>" in page
    hostile = Sbom("CycloneDX", components=[Component("<img src=x onerror=alert(1)>", "1")])
    page = to_html(diff(Sbom("CycloneDX"), hostile))
    assert "<img src=x" not in page


def run(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    out = capsys.readouterr()
    return exc.value.code, out.out, out.err


def test_cli_unified(capsys):
    code, out, _ = run(["diff", OLD, NEW, "-u", "-U", "0", "--no-color"], capsys)
    assert code == 0
    assert out.startswith(f"--- {OLD}\n+++ {NEW}\n@@ ")
    assert "\n npm" not in out  # no context lines at -U 0


def test_cli_negative_context(capsys):
    code, _, err = run(["diff", OLD, NEW, "-u", "-U", "-1"], capsys)
    assert code == 2
    assert "negative" in err


def test_colour_terminal_diff_has_gutter_and_word_marks(cdx):
    out = to_unified_text(cdx, context=1, colour=True)
    plain = re.sub(r"\x1b\[[\d;]*m", "", out)
    assert "6 │ + npm       debug" in plain
    # The changed version is highlighted; the unchanged name isn't.
    assert "\033[1;97;48;5;25m4.3.5\033[0m" in out
    assert "\033[1;97;48;5;25mdebug" not in out


def test_plain_terminal_diff_is_a_patch(cdx):
    out = to_unified_text(cdx, context=1)
    assert "│" not in out and "\033[" not in out
