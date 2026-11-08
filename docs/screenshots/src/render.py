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
from sbomly.render import to_text  # noqa: E402

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


def page_height(path: Path, width: int) -> int:
    """Full scroll height of a page, so the screenshot shows all of it."""
    probe = path.with_name("probe.html")
    probe.write_text(path.read_text(encoding="utf-8").replace(
        "</body>", "<script>document.title=document.documentElement.scrollHeight</script></body>"),
        encoding="utf-8")
    dom = subprocess.run(
        [CHROME, "--headless=new", "--disable-gpu", f"--window-size={width},900",
         "--virtual-time-budget=2000", "--dump-dom", probe.as_uri()],
        check=True, capture_output=True, text=True,
    ).stdout
    return int(re.search(r"<title>(\d+)</title>", dom).group(1))


def main() -> None:
    fixtures = ROOT / "tests" / "fixtures"
    old, new = load(str(fixtures / "cdx-old.json")), load(str(fixtures / "cdx-new.json"))
    # Shorter paths read better in a screenshot.
    old.source, new.source = "payments-api-2.3.0.cdx.json", "payments-api-2.4.0.cdx.json"
    result = diff(old, new)

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        body = ansi_to_html(to_text(result, colour=True)).rstrip("\n")
        prompt = ('<span style="color:#646f7f">$</span> sbomly diff '
                  f"{old.source} {new.source}")
        lines = 2 + body.count("\n") + 1
        width, height = 980, lines * LINE_HEIGHT + PAD * 2
        (tmp_path / "terminal.html").write_text(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
@font-face {{ font-family: 'JetBrains Mono'; font-weight: 100 800; src: url({(FONTS / 'jetbrains-mono-var.woff2').as_uri()}); }}
html, body {{ margin: 0; background: #10151d; }}
pre {{ margin: 0; padding: {PAD}px; font: 14px/{LINE_HEIGHT}px 'JetBrains Mono', monospace; color: #c9d0db; white-space: pre; }}
</style></head><body><pre>{prompt}

{body}</pre></body></html>""", encoding="utf-8")
        chrome((tmp_path / "terminal.html").as_uri(), OUT / "terminal.png", width, height, 2)

        report = tmp_path / "report.html"
        report.write_text(to_html(result), encoding="utf-8")
        chrome(report.as_uri(), OUT / "report.png", 1200, page_height(report, 1200) + 84, 1.5)

    print(f"wrote {OUT / 'terminal.png'} and {OUT / 'report.png'}")


if __name__ == "__main__":
    main()
