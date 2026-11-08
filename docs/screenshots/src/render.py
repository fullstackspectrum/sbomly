"""Re-render the README screenshots from the test fixtures.

    python docs/screenshots/src/render.py

Needs Google Chrome (set CHROME to override the path). Writes terminal.png
and report.png next to this folder.
"""

from __future__ import annotations

import html
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from sbomly.diff import diff  # noqa: E402
from sbomly.html import to_html  # noqa: E402
from sbomly.parse import load  # noqa: E402
from sbomly.render import to_text, to_unified_text  # noqa: E402

OUT = Path(__file__).resolve().parents[1]
CHROME = os.environ.get("CHROME", "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")
FONTS = ROOT / "sbomly" / "assets"

# ANSI SGR codes the CLI emits, mapped to brand tokens.
ANSI = {
    "1": "font-weight:700;color:#eef1f6",
    "2": "color:#646f7f",
    "33": "color:#f5c84c",
    "34": "color:#4f8cff",
    "94": "color:#8fb4ff",
    "38;5;209": "color:#ff8a3d",
    "31;1": "color:#ff4d5e;font-weight:700",
    "31": "color:#ff4d5e",
    "1;97;48;5;88": "color:#ffffff;font-weight:700;background:#8a1f2b",
    "1;97;48;5;25": "color:#ffffff;font-weight:700;background:#1f4f9a",
}

LINE_HEIGHT = 22
PAD = 32


def ansi_to_html(text: str) -> str:
    def span(match: re.Match) -> str:
        return f'<span style="{ANSI[match.group(1)]}">{match.group(2)}</span>'
    escaped = html.escape(text, quote=False)
    return re.sub(r"\x1b\[([\d;]+)m(.*?)\x1b\[0m", span, escaped)


def chrome(url: str, out: Path, width: int, height: int, scale: float) -> None:
    subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", "--hide-scrollbars",
         f"--force-device-scale-factor={scale}", f"--window-size={width},{height}",
         "--virtual-time-budget=2000", f"--screenshot={out}", url],
        check=True, capture_output=True,
    )


def page_height(path: Path, width: int, fragment: str = "") -> int:
    """Full scroll height of a page, so the screenshot shows all of it."""
    probe = path.with_name("probe.html")
    probe.write_text(path.read_text(encoding="utf-8").replace(
        "</body>", "<script>document.title=document.documentElement.scrollHeight</script></body>"),
        encoding="utf-8")
    dom = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", f"--window-size={width},900",
         "--virtual-time-budget=2000", "--dump-dom", probe.as_uri() + fragment],
        check=True, capture_output=True, text=True,
    ).stdout
    return int(re.search(r"<title>(\d+)</title>", dom).group(1))


def terminal(tmp: Path, output: str, command: str, out: Path) -> None:
    """Capture CLI output as a terminal window in the brand's colours."""
    body = ansi_to_html(output).rstrip("\n")
    prompt = f'<span style="color:#646f7f">$</span> {html.escape(command)}'
    lines = 2 + body.count("\n") + 1
    page = tmp / f"{out.stem}.html"
    page.write_text(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
@font-face {{ font-family: 'JetBrains Mono'; font-weight: 100 800; src: url({(FONTS / 'jetbrains-mono-var.woff2').as_uri()}); }}
html, body {{ margin: 0; background: #10151d; }}
pre {{ margin: 0; padding: {PAD}px; font: 14px/{LINE_HEIGHT}px 'JetBrains Mono', monospace; color: #c9d0db; white-space: pre; }}
</style></head><body><pre>{prompt}

{body}</pre></body></html>""", encoding="utf-8")
    chrome(page.as_uri(), out, 980, lines * LINE_HEIGHT + PAD * 2, 2)


def main() -> None:
    fixtures = ROOT / "tests" / "fixtures"
    old, new = load(str(fixtures / "cdx-old.json")), load(str(fixtures / "cdx-new.json"))
    # Shorter paths read better in a screenshot.
    old.source, new.source = "payments-api-2.3.0.cdx.json", "payments-api-2.4.0.cdx.json"
    result = diff(old, new)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        terminal(tmp_path, to_text(result, colour=True), f"sbomly diff {old.source} {new.source}",
                 OUT / "terminal.png")
        terminal(tmp_path, to_unified_text(result, context=1, colour=True),
                 f"sbomly diff {old.source} {new.source} -u -U 1", OUT / "terminal-diff.png")

        report = tmp_path / "report.html"
        report.write_text(to_html(result), encoding="utf-8")
        chrome(report.as_uri(), OUT / "report.png", 1200, page_height(report, 1200) + 84, 1.5)

        # The diff view on its own: the same report opened at #diff with
        # everything above the changes section hidden.
        only_changes = (".hero, .stats-row, main > section:first-of-type, footer { display: none; }"
                        "main { padding-top: 2rem; }")
        diff_page = tmp_path / "diff.html"
        diff_page.write_text(to_html(result).replace("</style>", only_changes + "</style>", 1),
                             encoding="utf-8")
        height = page_height(diff_page, 1200, "#diff") + 24
        chrome(diff_page.as_uri() + "#diff", OUT / "diff.png", 1200, height, 1.5)

    print(f"wrote terminal.png, terminal-diff.png, report.png and diff.png to {OUT}")


if __name__ == "__main__":
    main()
