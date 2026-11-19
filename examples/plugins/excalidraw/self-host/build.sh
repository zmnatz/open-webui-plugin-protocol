#!/usr/bin/env bash
# Builds a copy of the Excalidraw editor to host yourself, so the plugin's page loads nothing from
# the internet. Needs bun (https://bun.sh) and network access once, to fetch the pinned packages.
#
#   ./build.sh [output folder]      # default: ./dist
#
# Put the folder on any static web server, send `Access-Control-Allow-Origin: *` with it (the
# editor runs in Open-WebUI's sandboxed iframe, whose origin is opaque), and give the Open-WebUI
# container EXCALIDRAW_ASSETS_URL=<where it is served>. See ../README.md.
set -euo pipefail
cd "$(dirname "$0")"
out="${1:-dist}"

bun install --frozen-lockfile
rm -rf "$out"
# Code-split: the editor loads the first chunks at once and the rest (languages, diagram
# conversion) only when used, from the same folder.
bun build editor.js --outdir "$out" --splitting --minify --target browser --format esm \
  --define 'process.env.NODE_ENV="production"'
dist_prod=node_modules/@excalidraw/excalidraw/dist/prod
cp "$dist_prod/index.css" "$out/index.css"
cp -r "$dist_prod/fonts" "$out/fonts" # Excalidraw loads these relative to EXCALIDRAW_ASSET_PATH

echo "built $out: $(du -sh "$out" | cut -f1), $(find "$out" -type f | wc -l) files"
