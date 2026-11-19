#!/usr/bin/env bash
# Builds the Excalidraw editor to host yourself. Needs bun and network access once.
#
#   ./build.sh [output folder]      # default: ./dist
#
# Serve the folder with `Access-Control-Allow-Origin: *` and set EXCALIDRAW_ASSETS_URL
# in the Open-WebUI container. See ../README.md.
set -euo pipefail
cd "$(dirname "$0")"
out="${1:-dist}"

bun install --frozen-lockfile
rm -rf "$out"
# Code-split: rarely used parts load on demand from the same folder.
bun build editor.js --outdir "$out" --splitting --minify --target browser --format esm \
  --define 'process.env.NODE_ENV="production"'
dist_prod=node_modules/@excalidraw/excalidraw/dist/prod
cp "$dist_prod/index.css" "$out/index.css"
cp -r "$dist_prod/fonts" "$out/fonts" # Excalidraw loads these relative to EXCALIDRAW_ASSET_PATH

echo "built $out: $(du -sh "$out" | cut -f1), $(find "$out" -type f | wc -l) files"
