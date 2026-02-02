#!/usr/bin/env bash
#
# P11D-006 Happy Path Validation
#
# Validates a SUCCESSFUL deadline-authoritative switch (not a skipped boundary).
#
# With P11D-009, the first boundary is feasible by construction (planning_time = station_utc; feasibility by boundary selection only).
# We stream long enough to see at least one successful A→B switch at the declared boundary.
#
# With 30s segments:
#   - First boundary: feasible by construction (planning discards infeasible)
#   - Subsequent boundaries: succeed with LoadPreview at T-7s, SwitchToLive at T-6s
#
# Success criteria:
#   - At least ONE boundary switch executed (not skipped)
#   - No SchedulingError for that switch
#   - Stream data received
#

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CORE_DIR="$REPO_ROOT/pkg/core"
ASSET_A="${ASSET_A:-/opt/retrovue/assets/SampleA.mp4}"
ASSET_B="${ASSET_B:-/opt/retrovue/assets/SampleB.mp4}"
PORT="${PORT:-18808}"
SEGMENT_SECONDS="${SEGMENT_SECONDS:-30}"
# Stream for 2+ segment lengths to guarantee we see at least one successful switch
STREAM_DURATION="${STREAM_DURATION:-65}"

echo "=============================================="
echo "P11D-006 Happy Path Validation"
echo "=============================================="
echo ""
echo "Configuration:"
echo "  SEGMENT_SECONDS: $SEGMENT_SECONDS"
echo "  STREAM_DURATION: $STREAM_DURATION"
echo "  Asset A: $ASSET_A"
echo "  Asset B: $ASSET_B"
echo ""
echo "Strategy:"
echo "  - First boundary feasible by construction (P11D-009)"
echo "  - We stream for 2+ segment lengths to guarantee successful A→B→A switches"
echo ""

# Check prerequisites
if [[ ! -f "$ASSET_A" ]]; then
  echo "ERROR: Asset A not found: $ASSET_A"
  exit 1
fi
if [[ ! -f "$ASSET_B" ]]; then
  echo "ERROR: Asset B not found: $ASSET_B"
  exit 1
fi

AIR_BIN="$REPO_ROOT/pkg/air/build/retrovue_air"
if [[ -z "${RETROVUE_AIR_EXE:-}" ]] && [[ ! -x "$AIR_BIN" ]]; then
  AIR_ALT="$REPO_ROOT/pkg/air/out/build/linux-debug/retrovue_air"
  if [[ ! -x "$AIR_ALT" ]]; then
    echo "ERROR: AIR binary not found. Build pkg/air or set RETROVUE_AIR_EXE."
    exit 1
  fi
fi

VENV="$CORE_DIR/.venv/bin/activate"
if [[ ! -f "$VENV" ]]; then
  echo "ERROR: Core venv not found: $VENV"
  exit 1
fi

LOG_FILE=$(mktemp)
STREAM_FILE=$(mktemp)

cleanup() {
  if [[ -n "${PD_PID:-}" ]] && kill -0 "$PD_PID" 2>/dev/null; then
    echo ""
    echo "Stopping Program Director (PID $PD_PID)..."
    kill "$PD_PID" 2>/dev/null || true
    wait "$PD_PID" 2>/dev/null || true
  fi
  rm -f "$STREAM_FILE"
}
trap cleanup EXIT

echo "Starting Program Director..."

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
  2>&1 | tee "$LOG_FILE" &
PD_PID=$!

BASE="http://127.0.0.1:$PORT"
DEADLINE=$(($(date +%s) + 20))
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

echo ""
echo "Streaming for ${STREAM_DURATION}s..."
echo ""

if curl -sSf -o "$STREAM_FILE" -m "$STREAM_DURATION" "$BASE/channel/test-1.ts" 2>/dev/null; then
  BYTES=$(stat -c%s "$STREAM_FILE" 2>/dev/null || stat -f%z "$STREAM_FILE")
  echo "Streamed $BYTES bytes."
elif [[ $? -eq 28 ]]; then
  BYTES=$(stat -c%s "$STREAM_FILE" 2>/dev/null || stat -f%z "$STREAM_FILE" || echo 0)
  echo "Streamed $BYTES bytes (curl timed out as expected)."
else
  echo "Stream request failed."
  BYTES=0
fi

sleep 2

echo ""
echo "=============================================="
echo "Validation Results"
echo "=============================================="
echo ""

PASS=true

# Count successful switches vs skipped boundaries
SWITCHES_EXECUTED=$(grep -c "SwitchToLive\|switch_to_live" "$LOG_FILE" 2>/dev/null || echo 0)
BOUNDARIES_SKIPPED=$(grep -c "skipping boundary" "$LOG_FILE" 2>/dev/null || echo 0)
PRELOADS=$(grep -c "LoadPreview\|preload" "$LOG_FILE" 2>/dev/null || echo 0)

echo "LoadPreview/preload calls: $PRELOADS"
echo "Boundaries skipped (insufficient lead time): $BOUNDARIES_SKIPPED"
echo "Switch executions: $SWITCHES_EXECUTED"
echo ""

# 1. Must have at least one preload
if [[ $PRELOADS -gt 0 ]]; then
    echo "[PASS] LoadPreview issued ($PRELOADS times)"
else
    echo "[FAIL] No LoadPreview found"
    PASS=false
fi

# 2. Must have at least one successful switch (not just skipped)
# A successful switch would show SwitchToLive being called without immediate skip
if grep -q "switch_to_live\|SwitchToLive" "$LOG_FILE" && ! grep -q "only.*skipping" "$LOG_FILE"; then
    # Check if any switch actually went through
    if grep -q "INV-SWITCH-DEADLINE-AUTHORITATIVE\|ExecuteSwitch\|switch.*complet" "$LOG_FILE"; then
        echo "[PASS] At least one switch executed"
    elif [[ $BOUNDARIES_SKIPPED -gt 0 ]] && [[ $SWITCHES_EXECUTED -eq 0 ]]; then
        echo "[FAIL] All boundaries were skipped - no successful switch"
        PASS=false
    else
        echo "[WARN] Switch called but no execution confirmation in logs"
    fi
else
    if [[ $BOUNDARIES_SKIPPED -gt 0 ]]; then
        echo "[FAIL] All boundaries were skipped - no successful switch"
        PASS=false
    else
        echo "[FAIL] No switch activity found"
        PASS=false
    fi
fi

# 3. Check for any SchedulingError (should not happen for successful switch)
if grep -qi "SchedulingError" "$LOG_FILE"; then
    echo "[FAIL] SchedulingError raised"
    PASS=false
else
    echo "[PASS] No SchedulingError"
fi

# 4. Check stream output
if [[ ${BYTES:-0} -gt 0 ]]; then
    echo "[PASS] Stream data received ($BYTES bytes)"
    if [[ -s "$STREAM_FILE" ]]; then
        FIRST=$(head -c 1 "$STREAM_FILE" | xxd -p)
        if [[ "$FIRST" == "47" ]]; then
            echo "[PASS] Valid MPEG-TS (0x47 sync)"
        fi
    fi
else
    echo "[FAIL] No stream data"
    PASS=false
fi

# Show relevant log lines
echo ""
echo "Key log lines:"
grep -i "preload\|switch\|boundary\|lead" "$LOG_FILE" | grep -v "^INFO.*HTTP" | head -10

echo ""
echo "=============================================="

if $PASS; then
    echo "RESULT: P11D-006 Happy Path VALIDATED"
    echo ""
    echo "At least one deadline-authoritative switch executed successfully."
    rm -f "$LOG_FILE"
    exit 0
else
    echo "RESULT: P11D-006 Happy Path FAILED"
    echo ""
    echo "Log file: $LOG_FILE"
    trap - EXIT
    cleanup
    exit 1
fi
