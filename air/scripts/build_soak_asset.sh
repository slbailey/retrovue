#!/usr/bin/env bash
# AIR vNext — build a long test asset for soak testing.
#
# Produces /opt/retrovue/assets/sample_30min.mp4 by concatenating SampleA
# enough times to exceed 30 minutes. Runs once; skips if output exists.
#
# For overnight soak (>= 8h), pass a larger LOOPS value:
#   LOOPS=1000 ./scripts/build_soak_asset.sh
#
# Usage:
#   cd /opt/retrovue/air && ./scripts/build_soak_asset.sh

set -euo pipefail

SRC="${AIR_SOAK_SRC:-/opt/retrovue/assets/SampleA.mp4}"
DST="${AIR_SOAK_DST:-/opt/retrovue/assets/sample_30min.mp4}"
LOOPS="${LOOPS:-60}"  # SampleA is ~30s; 60 loops ≈ 30 minutes

if [[ ! -f "$SRC" ]]; then
  echo "ERROR: source not found at $SRC" >&2
  exit 1
fi

if [[ -f "$DST" ]]; then
  echo "Already exists: $DST (delete to rebuild)"
  exit 0
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "ERROR: ffmpeg not found on PATH" >&2
  exit 1
fi

echo "Building $DST from $SRC (LOOPS=$LOOPS)..."
ffmpeg -nostdin -y -stream_loop "$LOOPS" -i "$SRC" -c copy "$DST" 2>&1 | tail -5
echo "Done. Duration:"
ffprobe -v error -show_entries format=duration -of default=noprint_wrappers=1 "$DST"
