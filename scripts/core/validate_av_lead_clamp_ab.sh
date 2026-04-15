#!/usr/bin/env bash
# Validation-only: two AIR log captures (same workload) for AV lead clamp A/B.
#   Phase 1: RETROVUE_DISABLE_AV_LEAD_CLAMP=1 — clamp suppression off (ramp without clamp)
#   Phase 2: clamp on + RETROVUE_AV_LEAD_CLAMP_LOG_ALL=1 — every clamp logged
#
# Requires: server/.venv, runtime/build/retrovue_air, assets SampleA/B.
# Uses --mock-schedule-ab (channel test-1 in-process); no channel YAML needed.
#
# Usage:
#   ./scripts/core/validate_av_lead_clamp_ab.sh
# Output:
#   /tmp/retrovue_av_clamp_validation_before.log
#   /tmp/retrovue_av_clamp_validation_after.log

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
CORE_DIR="$REPO_ROOT/server"
AIR_LOG="$REPO_ROOT/runtime/logs/test-1-air.log"
PORT="${PORT:-18821}"
STREAM_SECONDS="${STREAM_SECONDS:-55}"
ASSET_A="${ASSET_A:-$REPO_ROOT/assets/SampleA.mp4}"
ASSET_B="${ASSET_B:-$REPO_ROOT/assets/SampleB.mp4}"

if [[ ! -f "$ASSET_A" || ! -f "$ASSET_B" ]]; then
  echo "Missing SampleA/SampleB under assets/ (set ASSET_A ASSET_B)."
  exit 1
fi
if [[ ! -x "$REPO_ROOT/runtime/build/retrovue_air" ]]; then
  echo "Build AIR first: cmake --build $REPO_ROOT/runtime/build --target retrovue_air"
  exit 1
fi

VENV="$CORE_DIR/.venv/bin/activate"
# shellcheck source=/dev/null
source "$VENV"
export PYTHONPATH="$CORE_DIR/src"

wait_http_200() {
  local deadline=$(( $(date +%s) + 120 ))
  while true; do
    local code
    code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:$PORT/channels" || echo 000)
    if [[ "$code" == "200" ]]; then
      return 0
    fi
    if [[ $(date +%s) -ge $deadline ]]; then
      echo "Timeout waiting for /channels HTTP 200 (last=$code)"
      return 1
    fi
    sleep 1
  done
}

run_phase() {
  local label="$1"
  echo "=== Phase: $label ==="
  # Avoid stale AIR / evidence listeners from a prior phase.
  pkill -f "program-director start --port $PORT" 2>/dev/null || true
  sleep 2
  rm -f "$AIR_LOG"
  cd "$CORE_DIR"
  python -m retrovue.cli.main program-director start \
    --port "$PORT" \
    --mock-schedule-ab \
    --asset-a "$ASSET_A" \
    --asset-b "$ASSET_B" \
    --segment-seconds 30 \
    > "/tmp/pd_${label}.log" 2>&1 &
  local pd_pid=$!
  if ! wait_http_200; then
    kill "$pd_pid" 2>/dev/null || true
    exit 1
  fi
  local out
  out=$(mktemp)
  set +e
  curl -sS -o "$out" -m "$STREAM_SECONDS" "http://127.0.0.1:$PORT/channel/test-1.ts"
  set -e
  kill "$pd_pid" 2>/dev/null || true
  wait "$pd_pid" 2>/dev/null || true
  sleep 3
  if [[ -f "$AIR_LOG" ]]; then
    cp "$AIR_LOG" "$2"
    echo "Wrote $2 ($(wc -c < "$2") bytes)"
  else
    echo "ERROR: AIR log not found at $AIR_LOG"
    tail -80 "/tmp/pd_${label}.log" || true
    exit 1
  fi
  rm -f "$out"
}

# --- Before: validation disable clamp (same binary; env-only) ---
export RETROVUE_DISABLE_AV_LEAD_CLAMP=1
export RETROVUE_AV_LEAD_CLAMP_LOG_ALL=1
run_phase "before_clamp_disabled" "/tmp/retrovue_av_clamp_validation_before.log"

# --- After: clamp enabled, log every event ---
unset RETROVUE_DISABLE_AV_LEAD_CLAMP
export RETROVUE_AV_LEAD_CLAMP_LOG_ALL=1
run_phase "after_clamp_enabled" "/tmp/retrovue_av_clamp_validation_after.log"

echo "Done. Compare:"
echo "  /tmp/retrovue_av_clamp_validation_before.log"
echo "  /tmp/retrovue_av_clamp_validation_after.log"
