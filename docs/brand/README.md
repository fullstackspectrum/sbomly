# Sbomly brand assets

Sbomly follows the [Full-Stack-Spectrum](https://fullstackspectrum.com) design system.

- `sbomly-icon.svg`: the mark on a 64×64 `#0a0d12` tile (radius 14), for avatars and app icons. The HTML report inlines it as its tab icon (`_FAVICON_SVG` in `sbomly/html.py`) and draws the tile-less mark in its header (`sbomly/assets/report.html`); keep all three in sync.
- `sbomly-mark.svg`: the mark alone, for dark grounds only (its layers are filled `#0a0d12`).
- `readme-banner.png`: 2560×640, shown at 1280×320 at the top of the README.
- `github-social-preview.png`: 1280×640, uploaded under the repository's Settings → Social preview.
- `src/brand.html` and `src/render.sh`: the source for both PNGs. Edit the HTML, then run `./docs/brand/src/render.sh` (needs Google Chrome).

The mark is Layered Core with the red core replaced by a ± sign, the diff glyph: blue and yellow layers behind a `#eef1f6` outline, cool at the back, hot at the front. The glyph is a 3-unit `#ff4d5e` stroke with round caps, matching GitPulse's pulse line.

The wordmark is written Sbomly in prose and headings, and `sbomly` in mono contexts (the command, eyebrows).
