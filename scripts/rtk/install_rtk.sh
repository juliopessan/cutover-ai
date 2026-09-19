#!/usr/bin/env bash
# Install RTK CLI into the repository local tools folder (Linux/macOS)
set -euo pipefail

OUT_DIR=".tools/rtk"
mkdir -p "$OUT_DIR"

RELEASE_API="https://api.github.com/repos/rtk-ai/rtk/releases/latest"
echo "Fetching RTK latest release metadata..."
asset_url=$(curl -s $RELEASE_API | jq -r '.assets[] | select(.name | test("(unknown-linux|linux|darwin|x86_64|aarch64).*tar.gz|rtk-x86_64-apple-darwin.tar.gz|rtk-aarch64-apple-darwin.tar.gz")) | .browser_download_url' | head -n1)
if [ -z "$asset_url" ] || [ "$asset_url" = "null" ]; then
  echo "Could not find prebuilt asset automatically. Please download a release from https://github.com/rtk-ai/rtk/releases"
  exit 1
fi

echo "Downloading $asset_url"
tmpfile=$(mktemp)
curl -sL "$asset_url" -o "$tmpfile"
echo "Extracting to $OUT_DIR"
tar -xzf "$tmpfile" -C "$OUT_DIR" --strip-components=1
rm "$tmpfile"
chmod +x "$OUT_DIR/rtk" || true

echo "RTK installed to $OUT_DIR/rtk"
echo "Add $(pwd)/$OUT_DIR to your PATH or use it via ./scripts/rtk/install_rtk.sh && ./$OUT_DIR/rtk"
