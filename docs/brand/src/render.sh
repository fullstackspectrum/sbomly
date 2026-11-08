#!/usr/bin/env bash
# Re-render the README banner and social preview from brand.html with
# headless Chrome. Run from anywhere: ./docs/brand/src/render.sh
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
chrome="${CHROME:-/Applications/Google Chrome.app/Contents/MacOS/Google Chrome}"
shot() { # layout width height scale out
  "$chrome" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor="$4" \
    --window-size="$2,$3" --virtual-time-budget=2000 --screenshot="$5" \
    "file://$here/brand.html?layout=$1" 2>/dev/null
}
shot banner 1280 320 2 "$here/../readme-banner.png"
shot social 1280 640 1 "$here/../github-social-preview.png"
