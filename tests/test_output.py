import json
import re
from pathlib import Path

import pytest

from sbomly.cli import main
from sbomly.diff import diff
from sbomly.html import to_html
from sbomly.model import Component, Sbom
from sbomly.parse import load
from sbomly.render import MARKDOWN_BUDGET, to_json, to_markdown, to_text

FIXTURES = Path(__file__).parent / "fixtures"
OLD, NEW = str(FIXTURES / "cdx-old.json"), str(FIXTURES / "cdx-new.json")

HOSTILE = '<script>alert(1)</script>{{BADGE_TEXT}}|`*[x](javascript:y)'


@pytest.fixture(scope="module")
def cdx():
    return diff(load(OLD), load(NEW))


def hostile_diff():
    old = Sbom(format="CycloneDX", subject=HOSTILE, components=[
        Component(HOSTILE, "1", license=HOSTILE, supplier="a"),
    ])
    new = Sbom(format="CycloneDX", subject=HOSTILE, components=[
        Component(HOSTILE, "1", license="GPL-3.0-only", supplier=HOSTILE),
        Component("x" + HOSTILE, HOSTILE, license=HOSTILE),
    ])
    return diff(old, new)


# ── JSON ──────────────────────────────────────────────────────────────


def test_json_round_trips(cdx):
    doc = json.loads(to_json(cdx, {"hash"}))
    assert doc["summary"]["added"] == 2
    assert doc["summary"]["hash"] == 1
    assert doc["failOn"]["triggered"] == {"hash": 1}
    assert doc["old"]["subjectVersion"] == "2.3.0"


# ── Text ──────────────────────────────────────────────────────────────


def test_text_has_no_ansi_without_colour(cdx):
    out = to_text(cdx, colour=False)
    assert "\033[" not in out
    assert "org.apache.commons:commons-text 1.10.0 → 1.9" in out


def test_text_limit(cdx):
    assert "… and 1 more" in to_text(cdx, limit=1)


# ── Markdown ──────────────────────────────────────────────────────────


def test_markdown_tables_and_sections(cdx):
    md = to_markdown(cdx, title="Release 2.4.0")
    assert md.startswith("### Release 2.4.0")
    assert "<details open>" in md  # findings expanded
    assert "| Integrity | axios | `1.6.0` |" in md


def test_markdown_escapes_injection():
    md = to_markdown(hostile_diff())
    # Code spans render their contents literally, so only check outside them.
    prose = re.sub(r"`[^`]*`", "", md)
    assert "<script>" not in prose
    assert not re.search(r"(?<!\\)\]\(javascript:", prose)
    # Every table row keeps its cell count: the pipes were escaped,
    # including the one inside the version's code span.
    for line in md.splitlines():
        if line.startswith("| Licence |") or line.startswith("| Supplier |"):
            assert len(re.findall(r"(?<!\\)\|", line)) == 5
        if line.startswith("| x"):
            assert len(re.findall(r"(?<!\\)\|", line)) == 4


def test_markdown_stays_under_github_limit():
    old = Sbom(format="CycloneDX", components=[])
    new = Sbom(format="CycloneDX", components=[
        Component(f"package-with-a-long-name-{i:05d}", "1.0.0", license="MIT") for i in range(5000)
    ])
    md = to_markdown(diff(old, new), limit=10_000)
    assert len(md) < MARKDOWN_BUDGET + 2_000
    assert "more not shown" in md
    assert "shortened to fit" in md


# ── HTML ──────────────────────────────────────────────────────────────


def test_html_is_self_contained(cdx):
    page = to_html(cdx)
    assert "{{" not in page
    assert not re.search(r'(src|href)="https?://', page.replace(
        'href="https://github.com/fullstackspectrum/sbomly"', "").replace(
        'href="https://fullstackspectrum.com/"', ""))
    assert "font/woff2;base64," in page
    assert "payments-api 2.3.0" in page


def test_html_light_theme(cdx):
    assert '<html lang="en" data-theme="light">' in to_html(cdx, theme="light")


def test_html_escapes_hostile_values():
    page = to_html(hostile_diff())
    assert "<script>alert(1)</script>" not in page
    assert "&lt;script&gt;" in page
    # A placeholder-shaped value is not expanded.
    assert "{{BADGE_TEXT}}" in page


# ── CLI ───────────────────────────────────────────────────────────────


def run(argv, capsys):
    with pytest.raises(SystemExit) as exc:
        main(argv)
    out = capsys.readouterr()
    return exc.value.code, out.out, out.err


def test_cli_ok(capsys):
    code, out, err = run(["diff", OLD, NEW, "--no-color"], capsys)
    assert code == 0
    assert "5 findings to review" in out
    assert err == ""


def test_cli_fail_on(capsys):
    code, _, err = run(["diff", OLD, NEW, "-q", "--fail-on", "hash,copyleft"], capsys)
    assert code == 1
    assert "1 hash, 2 copyleft" in err


def test_cli_fail_on_not_hit(capsys):
    code, _, _ = run(["diff", OLD, NEW, "-q", "--fail-on", "changed"], capsys)
    assert code == 0


def test_cli_bad_fail_on(capsys):
    code, _, err = run(["diff", OLD, NEW, "--fail-on", "nope"], capsys)
    assert code == 2
    assert "unknown category nope" in err


def test_cli_bad_input(capsys, tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("{}")
    code, _, err = run(["diff", str(bad), NEW], capsys)
    assert code == 2
    assert "not a CycloneDX or SPDX" in err


def test_cli_writes_files(capsys, tmp_path):
    code, out, _ = run(["diff", OLD, NEW, "-q",
                        "--html", str(tmp_path / "r" / "report.html"),
                        "--markdown", str(tmp_path / "pr.md"),
                        "--json", str(tmp_path / "diff.json")], capsys)
    assert code == 0
    assert out == ""
    assert (tmp_path / "r" / "report.html").read_text().startswith("<!DOCTYPE html>")
    assert (tmp_path / "pr.md").read_text().startswith("### SBOM diff")
    assert json.loads((tmp_path / "diff.json").read_text())["summary"]["removed"] == 1


def test_cli_json_stdout(capsys):
    code, out, _ = run(["diff", OLD, NEW, "-f", "json"], capsys)
    assert code == 0
    assert json.loads(out)["summary"]["upgraded"] == 3


def test_cli_no_command(capsys):
    code, out, _ = run([], capsys)
    assert code == 2
    assert "diff" in out


# ── Help ──────────────────────────────────────────────────────────────


def test_diff_help_is_grouped(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "100")
    code, out, _ = run(["diff", "--help"], capsys)
    assert code == 0
    for heading in ("arguments:", "output:", "diff view:", "ci gating:", "display:",
                    "fail-on categories:", "exit codes:", "examples:"):
        assert f"\n{heading}\n" in out
    # Each flag once, metavar at the end.
    assert "  -U, --context N " in out
    assert "\033[" not in out  # not a terminal, so no colour


def test_help_columns_line_up(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "100")
    _, out, _ = run(["diff", "--help"], capsys)
    columns = {line.index(desc) for line in out.splitlines()
               for desc in ("write the full diff as JSON", "a component's supplier changed",
                            "a --fail-on category occurred")
               if desc in line}
    assert len(columns) == 1


def test_root_help_lists_commands_without_placeholder(capsys):
    code, out, _ = run(["--help"], capsys)
    assert code == 0
    assert "  diff " in out and "\n  COMMAND\n" not in out


def test_help_colour_on_a_terminal(capsys, monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    _, out, _ = run(["diff", "--help"], capsys)
    assert "\033[94m--fail-on\033[0m" in out
    assert "\033[33mN\033[0m" in out


def test_version(capsys):
    code, out, _ = run(["--version"], capsys)
    assert code == 0 and out.startswith("sbomly ")
