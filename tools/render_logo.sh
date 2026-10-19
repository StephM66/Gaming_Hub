#!/bin/sh
# Renders docs/logo.svg to the brand images Home Assistant 2026.3+ reads from the integration
# (custom_components/gaming_hub/brand/). Needs Chromium (headless) and ImageMagick.
# Usage: tools/render_logo.sh [path to chromium]
set -eu
cd "$(dirname "$0")/.."
chromium="${1:-chromium}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
cp docs/logo.svg "$work/logo.svg"
printf '%s' '<html><body style="margin:0"><img src="logo.svg" width="1024" height="1024" style="display:block"></body></html>' > "$work/page.html"
"$chromium" --headless --no-sandbox --disable-gpu --hide-scrollbars --disable-background-networking \
  --default-background-color=00000000 --window-size=1024,1024 \
  --screenshot="$work/full.png" "file://$work/page.html" 2>/dev/null
# Trimmed, centred on a transparent square, as the brands specification asks.
convert "$work/full.png" -trim +repage "$work/trimmed.png"
side="$(identify -format '%[fx:max(w,h)]' "$work/trimmed.png")"
convert "$work/trimmed.png" -background none -gravity center -extent "${side}x${side}" "$work/square.png"
for size in 256 512; do
  name=icon.png
  [ "$size" = 512 ] && name=icon@2x.png
  convert "$work/square.png" -filter Lanczos -resize "${size}x${size}" -strip -interlace PNG \
    "custom_components/gaming_hub/brand/$name"
done
