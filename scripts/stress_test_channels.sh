#!/usr/bin/env bash
# Stress test: open multiple channel streams simultaneously and monitor throughput.
# Usage: ./scripts/stress_test_channels.sh [N_CHANNELS] [DURATION_SECONDS]
#
# Each channel is consumed by a curl process writing to /dev/null.
# The script monitors CPU usage and checks Core logs for BACKPRESSURE warnings.

set -euo pipefail

HOST="${RETROVUE_HOST:-localhost:8000}"
N="${1:-4}"
DURATION="${2:-60}"
PIDS=()

# Get available channels
CHANNELS=$(curl -sf "http://${HOST}/channels" | python3 -c "
import sys, json
data = json.load(sys.stdin)
for ch in data['channels']:
    print(ch['id'])
")

CHANNEL_LIST=($CHANNELS)
TOTAL=${#CHANNEL_LIST[@]}

if [ "$N" -gt "$TOTAL" ]; then
    echo "Requested $N channels but only $TOTAL available. Using $TOTAL."
    N=$TOTAL
fi

echo "=== RetroVue Stress Test ==="
echo "Channels: $N / $TOTAL available"
echo "Duration: ${DURATION}s"
echo "Host:     $HOST"
echo ""

cleanup() {
    echo ""
    echo "=== Stopping consumers ==="
    for pid in "${PIDS[@]}"; do
        kill "$pid" 2>/dev/null || true
    done
    wait 2>/dev/null
    echo "All consumers stopped."
}
trap cleanup EXIT

# Start consumers
for i in $(seq 0 $((N - 1))); do
    CH="${CHANNEL_LIST[$i]}"
    echo "Starting consumer: $CH"
    curl -sf "http://${HOST}/channel/${CH}.ts" > /dev/null &
    PIDS+=($!)
    # Stagger starts to avoid thundering herd on AIR spawns
    sleep 2
done

echo ""
echo "All $N consumers running. Monitoring for ${DURATION}s..."
echo ""

# Monitor loop
START=$(date +%s)
INTERVAL=10
while true; do
    NOW=$(date +%s)
    ELAPSED=$((NOW - START))
    REMAINING=$((DURATION - ELAPSED))
    if [ "$REMAINING" -le 0 ]; then
        break
    fi

    # Check consumer health
    ALIVE=0
    for pid in "${PIDS[@]}"; do
        if kill -0 "$pid" 2>/dev/null; then
            ALIVE=$((ALIVE + 1))
        fi
    done

    # CPU snapshot
    CPU=$(top -bn1 | head -3 | tail -1 | awk '{print $2 + $4}')

    # Count backpressure warnings in last interval (from running Core process stdout)
    # We just check the AIR logs for recent backpressure
    BP_COUNT=0
    for i in $(seq 0 $((N - 1))); do
        CH="${CHANNEL_LIST[$i]}"
        LOG="/opt/retrovue/pkg/air/logs/${CH}-air.log"
        if [ -f "$LOG" ]; then
            # Count lines with BACKPRESSURE in last modified log
            C=$(grep -c "BACKPRESSURE" "$LOG" 2>/dev/null || true)
            BP_COUNT=$((BP_COUNT + C))
        fi
    done

    printf "[%3ds/%ds] consumers=%d/%d  cpu=%.0f%%  backpressure_events=%d\n" \
        "$ELAPSED" "$DURATION" "$ALIVE" "$N" "$CPU" "$BP_COUNT"

    # If all consumers died, abort
    if [ "$ALIVE" -eq 0 ]; then
        echo "ERROR: All consumers died!"
        break
    fi

    SLEEP=$INTERVAL
    if [ "$REMAINING" -lt "$INTERVAL" ]; then
        SLEEP=$REMAINING
    fi
    sleep "$SLEEP"
done

echo ""
echo "=== Final Report ==="
echo "Duration: ${DURATION}s"
echo "Channels tested: $N"

# Final backpressure tally per channel
for i in $(seq 0 $((N - 1))); do
    CH="${CHANNEL_LIST[$i]}"
    LOG="/opt/retrovue/pkg/air/logs/${CH}-air.log"
    if [ -f "$LOG" ]; then
        C=$(grep -c "BACKPRESSURE" "$LOG" 2>/dev/null || true)
        printf "  %-25s backpressure_drops=%d\n" "$CH" "$C"
    else
        printf "  %-25s (no log)\n" "$CH"
    fi
done
