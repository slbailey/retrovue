#!/usr/bin/env bash
# Run P11D-006 (Core LoadPreview sufficient lead time) with real assets at least once.
#
# Starts Program Director with mock A/B schedule using SampleA.mp4 and SampleB.mp4,
# connects a viewer to channel test-1 for long enough to cross one segment boundary,
# so LoadPreview (T-7s) and SwitchToLive (T-5s) run with real AIR and real assets.
#
# Prerequisites:
#   - pkg/core/.venv
#   - pkg/air/build/retrovue_air (or RETROVUE_AIR_EXE)
#   - /opt/retrovue/assets/SampleA.mp4 and SampleB.mp4 (or ASSET_A, ASSET_B)
#
# Usage:
#   ./scripts/core/run_p11d006_real_assets.sh
#   ASSET_A=/path/to/A.mp4 ASSET_B=/path/to/B.mp4 ./scripts/core/run_p11d006_real_assets.sh

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CORE_DIR="$REPO_ROOT/pkg/core"
ASSET_A="${ASSET_A:-/opt/retrovue/assets/SampleA.mp4}"
ASSET_B="${ASSET_B:-/opt/retrovue/assets/SampleB.mp4}"
PORT="${PORT:-18806}"
# Run past one full segment so we see at least one A→B switch
STREAM_DURATION="${STREAM_DURATION:-35}"
# 30s segments so after ~6s launch the next boundary is ~24s away (≥5s lead for SwitchToLive)
SEGMENT_SECONDS="${SEGMENT_SECONDS:-30}"

if [[ ! -f "$ASSET_A" ]]; then
  echo "Asset A not found: $ASSET_A"
  exit 1
fi
if [[ ! -f "$ASSET_B" ]]; then
  echo "Asset B not found: $ASSET_B"
  exit 1
fi

AIR_BIN="$REPO_ROOT/pkg/air/build/retrovue_air"
if [[ -z "${RETROVUE_AIR_EXE:-}" ]] && [[ ! -x "$AIR_BIN" ]]; then
  AIR_ALT="$REPO_ROOT/pkg/air/out/build/linux-debug/retrovue_air"
  if [[ ! -x "$AIR_ALT" ]]; then
    echo "AIR binary not found. Build pkg/air or set RETROVUE_AIR_EXE."
    exit 1
  fi
fi

VENV="$CORE_DIR/.venv/bin/activate"
if [[ ! -f "$VENV" ]]; then
  echo "Core venv not found: $VENV"
  exit 1
fi

# Start Program Director with mock A/B and real assets (background)
echo "Starting Program Director (port=$PORT, A=$ASSET_A, B=$ASSET_B, segment=${SEGMENT_SECONDS}s)..."
cd "$CORE_DIR"
# shellcheck source=/dev/null
source .venv/bin/activate
export PYTHONPATH="$CORE_DIR/src"
python -m retrovue.cli.main program-director start \
  --port "$PORT" \
  --mock-schedule-ab \
  --asset-a "$ASSET_A" \
  --asset-b "$ASSET_B" \
  --segment-seconds "$SEGMENT_SECONDS" \
  &
PD_PID=$!

cleanup() {
  if [[ -n "${PD_PID:-}" ]] && kill -0 "$PD_PID" 2>/dev/null; then
    echo "Stopping Program Director (PID $PD_PID)..."
    kill "$PD_PID" 2>/dev/null || true
    wait "$PD_PID" 2>/dev/null || true
  fi
}
trap cleanup EXIT

# Wait for server to be up
BASE="http://127.0.0.1:$PORT"
DEADLINE=$(($(date +%s) + 15))
while true; do
  if curl -sSf -o /dev/null "$BASE/channels" 2>/dev/null; then
    echo "Program Director is up."
    break
  fi
  if [[ $(date +%s) -ge $DEADLINE ]]; then
    echo "Timeout waiting for Program Director."
    exit 1
  fi
  sleep 0.5
done

# Connect a viewer long enough to cross at least one segment boundary (P11D-006: preload T-7, switch T-5)
# STREAM_DURATION > SEGMENT_SECONDS so we see at least one A→B switch
echo "Requesting stream for ${STREAM_DURATION}s (channel test-1, segment=${SEGMENT_SECONDS}s) to exercise P11D-006 with real assets..."
OUT=$(mktemp)
if curl -sSf -o "$OUT" -m "$STREAM_DURATION" "$BASE/channel/test-1.ts" 2>/dev/null; then
  BYTES=$(stat -c%s "$OUT" 2>/dev/null || stat -f%z "$OUT" 2>/dev/null || echo 0)
  echo "Streamed $BYTES bytes."
  if [[ ${BYTES:-0} -eq 0 ]]; then
    echo "Error: received 0 bytes (stream did not deliver TS)."
    rm -f "$OUT"
    exit 1
  fi
else
  # curl -m can exit 28 (timeout) after successfully receiving for STREAM_DURATION; that's success
  EXIT=$?
  BYTES=$(stat -c%s "$OUT" 2>/dev/null || stat -f%z "$OUT" 2>/dev/null || echo 0)
  if [[ $EXIT -eq 28 ]] && [[ ${BYTES:-0} -gt 0 ]]; then
    echo "Streamed $BYTES bytes (curl timed out as expected)."
  else
    echo "Stream request failed (exit=$EXIT, bytes=${BYTES:-0})."
    rm -f "$OUT"
    exit 1
  fi
fi
# First bytes should be TS sync 0x47
if [[ -s "$OUT" ]]; then
  FIRST=$(head -c 1 "$OUT" | xxd -p)
  [[ "$FIRST" == "47" ]] && echo "TS sync 0x47 present." || echo "Warning: first byte not 0x47 (got $FIRST)."
fi
rm -f "$OUT"

echo "P11D-006 run with real assets completed successfully."
